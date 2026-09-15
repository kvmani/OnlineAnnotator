"""Importing masks made by other tools: one path for the single-image and the bulk import.

The routers only translate HTTP. Here a file is analysed (``labels.analyze_mask_file``), the
rules are applied -- never import a file the analysis could not interpret, never import an
ambiguous file without the user's confirmation -- and the analysis is kept with the image as
provenance, so every later version and export says exactly how the file was read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
from sqlalchemy.orm import Session

from .._version import __version__
from ..config import Settings
from ..models import Image, Project, User, utcnow
from . import access, imaging, workflow
from . import labels as label_ops

# Mask names that pair with an image stem: HydrideSegmentation's label and preview downloads,
# and the classic "<stem>_mask.png" (longest suffix first).
MASK_SUFFIXES = ("_mask_labels", "_mask_preview", "_mask")


@dataclass
class ImportOptions:
    """How the user asked for a file to be read (see ``labels.IMPORT_MODES``)."""

    mode: str = "auto"
    target_class: int | None = None
    threshold: float | None = None
    invert: bool = False
    confirm: bool = False
    source_tool: str = ""
    remarks: str = ""


class ImportRefused(workflow.WorkflowError):
    """Nothing was imported. The message says why and what to do; ``analysis`` describes the file."""

    def __init__(self, message: str, analysis: label_ops.MaskAnalysis | None = None, status: int = 400) -> None:
        super().__init__(message, status)
        self.analysis = analysis


def file_name(raw: str | None) -> str:
    return PurePosixPath((raw or "mask").replace("\\", "/")).name or "mask"


def classes_of(project: Project) -> dict[int, label_ops.MaskClass]:
    return {c.index: label_ops.MaskClass(c.index, c.name, c.color)
            for c in sorted(project.classes, key=lambda c: c.index)}


def analyse(image: Image, data: bytes, filename: str,
            options: ImportOptions) -> tuple[label_ops.MaskAnalysis, np.ndarray | None]:
    """Describe how ``data`` would become this image's labels, without storing anything."""
    return label_ops.analyze_mask_file(
        data, width=image.width, height=image.height, classes=classes_of(image.project),
        mode=options.mode, target_class=options.target_class, threshold=options.threshold,
        invert=options.invert, filename=filename, image_sha256=image.sha256,
    )


def import_file(db: Session, settings: Settings, image: Image, user: User, data: bytes, filename: str,
                options: ImportOptions) -> label_ops.MaskAnalysis:
    """Analyse one file and, if it may be imported, make it the image's working copy (not committed)."""
    analysis, labels = analyse(image, data, filename, options)
    if not analysis.ok:
        raise ImportRefused(analysis.error, analysis)
    if analysis.requires_confirmation and not options.confirm:
        raise ImportRefused(f"{analysis.confirmation} Nothing was imported: check the preview, confirm, "
                            "then import again.", analysis, 409)
    entered = options.source_tool.strip()
    from_file = analysis.embedded_metadata.get("Software", "").strip()
    tool = entered or from_file
    record = analysis.provenance(
        source_tool=tool, remarks=options.remarks.strip(),
        confirmed=options.confirm and analysis.requires_confirmation,
        imported_by=user.email, imported_at=utcnow().isoformat(), tool_version=__version__,
    )
    record["source_tool_origin"] = "entered by the user" if entered else "file metadata" if from_file else ""
    workflow.import_working(db, settings, image, user, labels,
                            origin=f"imported from {filename} ({analysis.kind})", source_file=filename,
                            source_tool=tool, source_remarks=options.remarks, import_details=record)
    return analysis


def audit_summary(record: dict) -> dict:
    """The part of a provenance record worth repeating in a batch audit entry."""
    keys = ("file", "detected_encoding", "mapping", "normalization", "target_class", "threshold", "invert",
            "warnings", "confirmed", "class_pixels")
    return {k: record.get(k) for k in keys}


# ------------------------------------------------------------------------------ batches
def _index(project: Project) -> dict[str, Image]:
    by_stem: dict[str, Image] = {}
    for img in project.images:
        by_stem[img.stem.lower()] = img
        by_stem.setdefault(Path(img.original_filename).stem.lower(), img)
    return by_stem


def image_key(filename: str) -> str:
    """The image stem a mask file name refers to: ``x_mask.png``, ``x_mask_labels.png`` or ``x.png``."""
    stem = Path(filename).stem
    for suffix in MASK_SUFFIXES:
        if stem.lower().endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    return stem


def _match(index: dict[str, Image], filename: str) -> tuple[str, Image | None]:
    key = image_key(filename)
    return key, index.get(key.lower()) or index.get(imaging.safe_stem(key).lower())


def _entry(name: str, image: Image | None, status: str, message: str,
           analysis: label_ops.MaskAnalysis | None) -> dict:
    return {"file": name, "image_id": image.id if image else None, "image": image.stem if image else None,
            "status": status, "message": message, "analysis": analysis.to_dict() if analysis else None}


def _unmatched(name: str, key: str) -> dict:
    return _entry(name, None, "unmatched", f"no image called {key!r} in this project. Name each mask after its "
                                           f"image, for example {key}_mask.png for the image {key}.", None)


def analyse_batch(project: Project, uploads: list[tuple[str, bytes]], options: ImportOptions) -> list[dict]:
    """The preview of a bulk import: for every file, its image and how it would be read."""
    index, results = _index(project), []
    for name, data in uploads:
        key, image = _match(index, name)
        if image is None:
            results.append(_unmatched(name, key))
            continue
        analysis, _ = analyse(image, data, name, options)
        if not analysis.ok:
            results.append(_entry(name, image, "refused", analysis.error, analysis))
        elif analysis.requires_confirmation:
            results.append(_entry(name, image, "needs_confirmation", analysis.confirmation, analysis))
        else:
            results.append(_entry(name, image, "ready", f"{analysis.encoding_name} -> {image.stem}", analysis))
    return results


def import_batch(db: Session, settings: Settings, project: Project, user: User,
                 uploads: list[tuple[str, bytes]], options: ImportOptions) -> dict:
    """Import every file that may be imported; each file succeeds or fails on its own."""
    index = _index(project)
    imported: list[str] = []
    errors: list[str] = []
    results: list[dict] = []
    records: list[dict] = []
    for name, data in uploads:
        key, image = _match(index, name)
        if image is None:
            entry = _unmatched(name, key)
            results.append(entry)
            errors.append(f"{name}: {entry['message']}")
            continue
        try:
            analysis = import_file(db, settings, image, user, data, name, options)
            db.commit()
        except access.Refused as exc:
            db.rollback()
            analysis = getattr(exc, "analysis", None)
            waiting = analysis is not None and analysis.ok and analysis.requires_confirmation
            results.append(_entry(name, image, "needs_confirmation" if waiting else "refused", str(exc), analysis))
            errors.append(f"{name}: {exc}")
            continue
        imported.append(f"{name} -> {image.stem} ({analysis.kind} mask)")
        records.append(audit_summary(json.loads(image.mask_import_details)))
        results.append(_entry(name, image, "imported", f"{analysis.encoding_name} -> {image.stem}", analysis))
    return {"imported": imported, "errors": errors, "results": results, "records": records}
