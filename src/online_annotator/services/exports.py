"""ML dataset export.

A bundle is a ZIP containing images, masks, a README and ``manifest.json`` with full
provenance (who annotated, who approved, which version, SHA-256 of every file).

Layouts
-------
``hydride_pairs``
    One flat ``pairs/`` folder of ``<stem>.png`` + ``<stem>_mask.png``: exactly the
    input HydrideSegmentation's ``prepare_dataset`` expects (it performs its own
    seeded split). Splits are still recorded in the manifest.
``split_folders``
    ``train|val|test/images`` and ``.../masks``: the layout produced by
    HydrideSegmentation's dataset preparation and used by most training code.

Mask styles
-----------
``binary`` 0/255 for one target class; ``red`` target class as pure red RGB
(HydrideSegmentation ``rgb_mask_mode``); ``indexed`` pixel value = class index;
``colour`` RGB in the project class colours.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from .._version import TOOL_ID, __version__
from ..config import Settings
from ..models import Export, Image, Project, User, Version, as_utc, utcnow
from . import labels as label_ops
from . import workflow

LAYOUTS = ("hydride_pairs", "split_folders")
MASK_STYLES = ("binary", "red", "indexed", "colour")
INCLUDE = ("approved", "approved_and_submitted")
SPLIT_MODES = ("assigned", "auto")
MANIFEST_SCHEMA = "online-annotator.export/1"


class ExportError(ValueError):
    """Invalid export request; message is safe to show."""


@dataclass
class ExportOptions:
    layout: str = "hydride_pairs"
    mask_style: str = "binary"
    target_class: int | None = None
    include: str = "approved"
    split_mode: str = "assigned"
    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    seed: int = 42
    include_coco: bool = True
    include_yolo: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self, project: Project) -> None:
        if self.layout not in LAYOUTS:
            raise ExportError(f"Unknown layout {self.layout!r}.")
        if self.mask_style not in MASK_STYLES:
            raise ExportError(f"Unknown mask style {self.mask_style!r}.")
        if self.include not in INCLUDE:
            raise ExportError(f"Unknown selection {self.include!r}.")
        if self.split_mode not in SPLIT_MODES:
            raise ExportError(f"Unknown split mode {self.split_mode!r}.")
        indices = [c.index for c in project.classes]
        if not indices:
            raise ExportError("The project has no classes.")
        if self.mask_style in ("binary", "red"):
            if self.target_class is None:
                self.target_class = indices[0]
            if self.target_class not in indices:
                raise ExportError(f"Class {self.target_class} does not exist in this project.")
        if self.split_mode == "auto":
            ratios = [self.train, self.val, self.test]
            if any(r < 0 for r in ratios) or sum(ratios) <= 0:
                raise ExportError("Split fractions must be non-negative and not all zero.")
        if self.include_yolo and not yolo_available():
            raise ExportError("YOLO export needs OpenCV (pip install opencv-python-headless) on the server.")


def yolo_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class Selection:
    image: Image
    version: Version
    split: str


def select_images(project: Project, options: ExportOptions) -> tuple[list[Selection], dict[str, int]]:
    """Pick one version per image according to ``options.include``; report what was left out."""
    chosen: list[Selection] = []
    skipped = {"not_approved": 0, "no_annotation": 0}
    for image in sorted(project.images, key=lambda i: i.stem):
        version = workflow.latest(image, "approved")
        if version is None and options.include == "approved_and_submitted":
            version = workflow.latest(image, "submitted")
        if version is None:
            skipped["no_annotation" if image.status == "new" else "not_approved"] += 1
            continue
        chosen.append(Selection(image=image, version=version, split=image.split))
    if options.split_mode == "auto":
        _auto_split(chosen, options)
    return chosen, skipped


def _auto_split(chosen: list[Selection], options: ExportOptions) -> None:
    """Deterministic split: order by SHA-256(seed:image-hash), then cut by the ratios."""
    ordered = sorted(chosen, key=lambda s: hashlib.sha256(f"{options.seed}:{s.image.sha256}".encode()).hexdigest())
    total = options.train + options.val + options.test
    n = len(ordered)
    n_train = round(n * options.train / total)
    n_val = round(n * options.val / total)
    for i, sel in enumerate(ordered):
        sel.split = "train" if i < n_train else ("val" if i < n_train + n_val else "test")


def preview(project: Project, options: ExportOptions) -> dict[str, Any]:
    options.validate(project)
    chosen, skipped = select_images(project, options)
    splits: dict[str, int] = {}
    for sel in chosen:
        splits[sel.split] = splits.get(sel.split, 0) + 1
    warnings: list[str] = []
    if not chosen:
        warnings.append("No images match the selection yet: approve some annotations first.")
    if options.include == "approved_and_submitted" and any(s.version.status == "submitted" for s in chosen):
        warnings.append("Some masks are not yet reviewed. Use them for experiments, not as final ground truth.")
    if options.layout == "split_folders" and splits.get("unassigned"):
        warnings.append(f"{splits['unassigned']} image(s) have no split; they go to an 'unassigned' folder. "
                        "Assign splits on the project page or choose automatic splitting.")
    return {"image_count": len(chosen), "splits": splits, "skipped": skipped, "warnings": warnings}


def _mask_array(labels: np.ndarray, options: ExportOptions, palette: dict[int, str]) -> np.ndarray:
    if options.mask_style == "binary":
        return label_ops.binary(labels, options.target_class)
    if options.mask_style == "red":
        rgb = np.zeros((*labels.shape, 3), dtype=np.uint8)
        rgb[labels == options.target_class] = (255, 0, 0)
        return rgb
    if options.mask_style == "colour":
        return label_ops.colourize(labels, palette)
    return labels


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _rle(binary_mask: np.ndarray) -> dict[str, Any]:
    """Uncompressed COCO RLE (column-major, first run counts zeros)."""
    flat = np.asfortranarray(binary_mask).ravel(order="F").astype(np.uint8)
    change = np.flatnonzero(np.diff(flat)) + 1
    bounds = np.concatenate(([0], change, [flat.size]))
    counts = np.diff(bounds).tolist()
    if flat.size and flat[0] == 1:
        counts = [0] + counts
    return {"size": [int(binary_mask.shape[0]), int(binary_mask.shape[1])], "counts": counts}


def _yolo_lines(labels: np.ndarray, class_order: list[int]) -> list[str]:
    import cv2

    h, w = labels.shape
    lines: list[str] = []
    for yolo_id, index in enumerate(class_order):
        mask = (labels == index).astype(np.uint8)
        if not mask.any():
            continue
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if len(contour) < 3:
                continue
            pts = contour.reshape(-1, 2)
            coords = " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in pts)
            lines.append(f"{yolo_id} {coords}")
    return lines


def _iso(value) -> str | None:
    value = as_utc(value)
    return value.isoformat() if value else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "project"


README_TEMPLATE = """{project} - annotation export
{rule}

Created {created} by {user} with {tool} {version}.
Images: {count}   Layout: {layout}   Masks: {mask_desc}
Selection: {include}

FILES
{files}

manifest.json records, for every image: the original filename, the SHA-256 of the
image and of the exported mask, the annotation version, who annotated it, who
approved it and when, the split, and the pixel count of every class.

CLASSES (mask value -> class)
{classes}

USING WITH HydrideSegmentation
{hydride}
"""


def build_export(db: Session, settings: Settings, project: Project, user: User,
                 options: ExportOptions) -> Export:
    options.validate(project)
    chosen, skipped = select_images(project, options)
    if not chosen:
        raise ExportError("Nothing to export: no image has an annotation matching the selection.")

    palette = {c.index: c.color for c in project.classes}
    class_order = [c.index for c in project.classes]
    created = utcnow()
    base = f"{_slug(project.name)}_{created.strftime('%Y%m%d-%H%M%S')}_{secrets.token_hex(3)}"
    filename = f"{base}.zip"
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = settings.exports_dir / (filename + ".part")

    records: list[dict[str, Any]] = []
    coco = {
        "info": {"description": f"{project.name} (semantic segmentation, one RLE per class per image)",
                 "version": __version__, "date_created": created.isoformat()},
        "categories": [{"id": c.index, "name": c.name, "supercategory": "microstructure"}
                       for c in project.classes],
        "images": [], "annotations": [],
    }
    ann_id = 1
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sel in chosen:
            image, version = sel.image, sel.version
            labels = workflow.load_version(settings, image, version)
            mask = _mask_array(labels, options, palette)
            src = workflow.original_path(settings, image)
            ext = Path(image.stored_name).suffix.lower()
            if ext in (".png", ".jpg", ".jpeg") and image.display_name == image.stored_name:
                image_name, image_bytes = f"{image.stem}{'.jpg' if ext == '.jpeg' else ext}", src.read_bytes()
            else:
                image_name = f"{image.stem}.png"
                image_bytes = workflow.display_path(settings, image).read_bytes()
            mask_name = f"{image.stem}_mask.png"
            folder = "pairs" if options.layout == "hydride_pairs" else sel.split
            img_arc = f"{folder}/{image_name}" if options.layout == "hydride_pairs" else f"{folder}/images/{image_name}"
            mask_arc = f"{folder}/{mask_name}" if options.layout == "hydride_pairs" else f"{folder}/masks/{mask_name}"
            mask_bytes = _png(mask)
            zf.writestr(img_arc, image_bytes)
            zf.writestr(mask_arc, mask_bytes)

            pixels = version.pixels
            total = image.width * image.height
            records.append({
                "stem": image.stem,
                "original_filename": image.original_filename,
                "image_file": img_arc,
                "mask_file": mask_arc,
                "split": sel.split,
                "width": image.width,
                "height": image.height,
                "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "original_sha256": image.sha256,
                "mask_png_sha256": hashlib.sha256(mask_bytes).hexdigest(),
                "label_sha256": version.mask_sha256,
                "conversion_note": image.conversion_note,
                "version": version.number,
                "version_status": version.status,
                "version_kind": version.kind,
                # Provenance of the ground truth: "manual" = drawn in Online Annotator,
                # "imported" = an external mask was loaded and then corrected here.
                "mask_source": version.mask_source,
                "mask_source_tool": version.mask_source_tool,
                "mask_source_file": version.mask_source_file,
                "mask_source_remarks": version.mask_source_remarks,
                "annotated_by": version.created_by,
                "annotated_at": _iso(version.created_at),
                "contributors": sorted({v.created_by for v in image.versions if v.number <= version.number}),
                "approved_by": version.reviewed_by if version.status == "approved" else None,
                "approved_at": _iso(version.reviewed_at) if version.status == "approved" else None,
                "class_pixels": pixels,
                "class_fractions": {k: round(v / total, 6) for k, v in pixels.items()},
            })

            if options.include_coco:
                coco["images"].append({"id": image.id, "file_name": img_arc, "width": image.width,
                                       "height": image.height})
                for index in class_order:
                    binary = labels == index
                    area = int(binary.sum())
                    if not area:
                        continue
                    ys, xs = np.nonzero(binary)
                    x0, y0 = int(xs.min()), int(ys.min())
                    coco["annotations"].append({
                        "id": ann_id, "image_id": image.id, "category_id": index, "iscrowd": 0,
                        "area": area, "bbox": [x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1],
                        "segmentation": _rle(binary.astype(np.uint8)),
                    })
                    ann_id += 1
            if options.include_yolo:
                label_folder = "pairs_yolo" if options.layout == "hydride_pairs" else f"{sel.split}/labels"
                zf.writestr(f"{label_folder}/{image.stem}.txt", "\n".join(_yolo_lines(labels, class_order)) + "\n")

        if options.include_coco:
            zf.writestr("coco_annotations.json", json.dumps(coco))
        if options.include_yolo:
            names = "\n".join(f"  {i}: {c.name}" for i, c in enumerate(project.classes))
            zf.writestr("yolo_data.yaml", f"# YOLO class id = project class index - 1\nnames:\n{names}\n")

        classes = [{"index": c.index, "name": c.name, "color": c.color, "description": c.description}
                   for c in project.classes]
        target = next((c for c in project.classes if c.index == options.target_class), None)
        mask_desc = {
            "binary": f"binary PNG, 255 = {target.name if target else ''}, 0 = everything else",
            "red": f"RGB PNG, pure red (255,0,0) = {target.name if target else ''}, black = everything else",
            "indexed": "8-bit PNG, pixel value = class index, 0 = background",
            "colour": "RGB PNG in the project class colours, black = background",
        }[options.mask_style]
        splits: dict[str, int] = {}
        for r in records:
            splits[r["split"]] = splits.get(r["split"], 0) + 1
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "tool": {"id": TOOL_ID, "version": __version__},
            "project": {"id": project.id, "name": project.name, "description": project.description},
            "created_at": created.isoformat(),
            "created_by": user.email,
            "options": asdict(options),
            "mask_encoding": mask_desc,
            "classes": classes,
            "background_value": 0,
            "summary": {"images": len(records), "splits": splits, "skipped": skipped},
            "images": records,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        if options.layout == "hydride_pairs":
            files = ("pairs/<stem>.png         the micrograph\n"
                     "pairs/<stem>_mask.png    its mask")
            hydride = ("Unzip, then point prepare_dataset at the pairs/ folder, e.g.\n"
                       "  input_dir: <unzipped>/pairs\n"
                       f"  rgb_mask_mode: {'true' if options.mask_style == 'red' else 'false'}\n"
                       "HydrideSegmentation performs its own seeded train/val/test split.")
        else:
            files = ("<split>/images/<stem>.png       micrographs, split = train | val | test\n"
                     "<split>/masks/<stem>_mask.png   masks")
            hydride = "This layout matches the output of HydrideSegmentation's dataset preparation."
        if options.include_coco:
            files += "\ncoco_annotations.json    COCO JSON, one uncompressed-RLE annotation per class per image"
        if options.include_yolo:
            files += "\n*/labels or pairs_yolo/  YOLO-seg polygons (outer contours only; holes are not encoded)"
        files += "\nmanifest.json            provenance and statistics"
        zf.writestr("README.txt", README_TEMPLATE.format(
            project=project.name, rule="=" * (len(project.name) + 22), created=created.isoformat(),
            user=user.email, tool=TOOL_ID, version=__version__, count=len(records), layout=options.layout,
            mask_desc=mask_desc, include=options.include, files=files,
            classes="\n".join(f"  {c.index:>3} -> {c.name}" for c in project.classes) + "\n    0 -> background",
            hydride=hydride,
        ))

    final_path = settings.exports_dir / filename
    tmp_path.replace(final_path)
    digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
    export = Export(project_id=project.id, created_by=user.email, created_at=created, filename=filename,
                    size_bytes=final_path.stat().st_size, sha256=digest, image_count=len(records),
                    options=json.dumps(asdict(options), sort_keys=True),
                    summary=json.dumps(manifest["summary"], sort_keys=True))
    db.add(export)
    db.commit()
    return export
