"""Micrograph ingestion: decoding, browser-safe display copies, thumbnails and grey levels.

The original upload is stored byte-for-byte (its SHA-256 is the image identity). A
display copy is written only when the browser cannot show the original faithfully
(TIFF, 16-bit, float, palette, CMYK ...). Every conversion is described in
``conversion_note`` so provenance never depends on memory.
"""

from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image as PILImage
from PIL import ImageOps

ACCEPTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
BROWSER_NATIVE = {".png", ".jpg", ".jpeg"}
THUMB_SIZE = 320


class ImageIngestError(ValueError):
    """The upload cannot be used as a micrograph; the message is safe to show to users."""


@dataclass
class IngestedImage:
    sha256: str
    width: int
    height: int
    source_mode: str
    needs_display_copy: bool
    display_png: bytes | None
    conversion_note: str
    thumbnail_jpeg: bytes


def safe_stem(filename: str) -> str:
    """Filesystem- and pipeline-safe stem.

    HydrideSegmentation treats any file whose stem contains ``_mask`` as a mask, so
    that substring is rewritten in image stems.
    """
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "image"
    stem = re.sub(r"_mask", "-mask", stem, flags=re.IGNORECASE)
    return stem[:120]


def _to_display_array(img: PILImage.Image) -> tuple[np.ndarray, str]:
    """Return an 8-bit L or RGB array plus a note describing any value transformation."""
    mode = img.mode
    if mode in ("L", "RGB"):
        return np.asarray(img), ""
    if mode == "1":
        return np.asarray(img.convert("L")), "1-bit image expanded to 8-bit (0/255)."
    if mode in ("P", "PA"):
        return np.asarray(img.convert("RGB")), "Palette image expanded to RGB."
    if mode in ("RGBA", "LA"):
        return np.asarray(img.convert("RGB" if mode == "RGBA" else "L")), "Alpha channel discarded."
    if mode == "CMYK":
        return np.asarray(img.convert("RGB")), "CMYK converted to RGB."
    if mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        finite = arr[np.isfinite(arr)]
        lo, hi = (np.percentile(finite, [0.1, 99.9]) if finite.size else (0.0, 1.0))
        if hi <= lo:
            lo, hi = float(finite.min(initial=0.0)), float(finite.max(initial=1.0))
            hi = hi if hi > lo else lo + 1.0
        scaled = np.clip((arr - lo) / (hi - lo), 0.0, 1.0) * 255.0
        note = (f"{mode} data linearly scaled to 8-bit for display using the 0.1-99.9 percentile "
                f"window [{lo:.4g}, {hi:.4g}]. The original file is kept unchanged.")
        return np.nan_to_num(scaled).round().astype(np.uint8), note
    return np.asarray(img.convert("RGB")), f"{mode} converted to RGB."


def ingest(raw: bytes, filename: str, max_megapixels: float) -> IngestedImage:
    ext = Path(filename).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise ImageIngestError(
            f"{filename}: unsupported file type. Use PNG, JPEG, TIFF or BMP."
        )
    PILImage.MAX_IMAGE_PIXELS = int(max_megapixels * 1_000_000)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            img = PILImage.open(io.BytesIO(raw))
            img.load()
    except (PILImage.DecompressionBombError, PILImage.DecompressionBombWarning) as exc:
        raise ImageIngestError(f"{filename}: larger than the {max_megapixels:g} MP limit.") from exc
    except Exception as exc:  # noqa: BLE001 - any decoder failure is a user-facing rejection
        raise ImageIngestError(f"{filename}: not a readable image ({exc.__class__.__name__}).") from exc

    notes: list[str] = []
    if getattr(img, "n_frames", 1) > 1:
        notes.append(f"Multi-page file: only the first of {img.n_frames} pages is used.")
        img.seek(0)
    orientation = img.getexif().get(0x0112, 1) if hasattr(img, "getexif") else 1
    if orientation not in (1, None):
        notes.append("EXIF orientation ignored: pixels are annotated exactly as stored.")

    source_mode = img.mode
    arr, note = _to_display_array(img)
    if note:
        notes.append(note)
    height, width = arr.shape[:2]
    if width < 8 or height < 8:
        raise ImageIngestError(f"{filename}: image is too small ({width} x {height}).")

    # Browsers apply EXIF rotation when displaying, which would misalign the labels,
    # so a rotated original always gets an un-rotated display copy.
    needs_copy = (ext not in BROWSER_NATIVE or bool(note) or source_mode not in ("L", "RGB")
                  or orientation not in (1, None))
    display_png = None
    display_img = PILImage.fromarray(arr)
    if needs_copy:
        buf = io.BytesIO()
        display_img.save(buf, format="PNG")
        display_png = buf.getvalue()

    thumb = ImageOps.contain(display_img.convert("RGB"), (THUMB_SIZE, THUMB_SIZE))
    tbuf = io.BytesIO()
    thumb.save(tbuf, format="JPEG", quality=82)

    return IngestedImage(
        sha256=hashlib.sha256(raw).hexdigest(),
        width=width,
        height=height,
        source_mode=source_mode,
        needs_display_copy=needs_copy,
        display_png=display_png,
        conversion_note=" ".join(notes),
        thumbnail_jpeg=tbuf.getvalue(),
    )


def grey_levels(display_path: Path) -> np.ndarray:
    """8-bit luminance of the display image, used by the assisted-selection tools."""
    with PILImage.open(display_path) as img:
        return np.asarray(img.convert("L"), dtype=np.uint8)
