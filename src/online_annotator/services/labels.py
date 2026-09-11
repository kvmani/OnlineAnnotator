"""Label-map primitives: validation, persistence, statistics and rendering.

A label map is a ``uint8`` array of shape ``(height, width)``. Value 0 is background;
values 1..255 are class indices defined by the project. These functions are the only
place label maps are encoded or decoded, so every path (browser save, import,
version snapshot, export) obeys one contract.
"""

from __future__ import annotations

import gzip
import hashlib
import io
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
from PIL import Image as PILImage


class LabelError(ValueError):
    """A label map violates the contract; the message is safe to show to users."""


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def decode_raw(payload: bytes, width: int, height: int, gzipped: bool = False) -> np.ndarray:
    """Decode the browser's raw label bytes (row-major, one byte per pixel)."""
    if gzipped:
        try:
            payload = gzip.decompress(payload)
        except (OSError, EOFError) as exc:
            raise LabelError("The label data could not be decompressed.") from exc
    if len(payload) != width * height:
        raise LabelError(
            f"Label data has {len(payload)} pixels but the image has {width} x {height} = {width * height}."
        )
    return np.frombuffer(payload, dtype=np.uint8).reshape(height, width).copy()


def validate(labels: np.ndarray, allowed: Iterable[int], width: int, height: int) -> None:
    if labels.dtype != np.uint8 or labels.shape != (height, width):
        raise LabelError(f"Label map must be {width} x {height} 8-bit; got {labels.shape[::-1]} {labels.dtype}.")
    allowed_set = set(int(a) for a in allowed) | {0}
    present = set(int(v) for v in np.unique(labels))
    unknown = sorted(present - allowed_set)
    if unknown:
        raise LabelError(f"Label map uses class values {unknown} that are not defined in this project.")


def class_pixels(labels: np.ndarray) -> dict[str, int]:
    counts = np.bincount(labels.ravel(), minlength=1)
    return {str(i): int(c) for i, c in enumerate(counts) if c and i > 0}


def to_png_bytes(labels: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    PILImage.fromarray(np.ascontiguousarray(labels, dtype=np.uint8)).save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def sha256_of(labels: np.ndarray) -> str:
    """Content hash of the label values themselves (independent of PNG encoder settings)."""
    digest = hashlib.sha256()
    digest.update(f"{labels.shape[1]}x{labels.shape[0]}:".encode())
    digest.update(np.ascontiguousarray(labels).tobytes())
    return digest.hexdigest()


def save(labels: np.ndarray, path: Path) -> str:
    """Write an 8-bit grey PNG atomically and return the label content hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(to_png_bytes(labels))
    tmp.replace(path)
    return sha256_of(labels)


def load(path: Path, width: int, height: int) -> np.ndarray:
    if not path.exists():
        return np.zeros((height, width), dtype=np.uint8)
    with PILImage.open(path) as img:
        arr = np.asarray(img)
    if arr.ndim != 2 or arr.dtype != np.uint8 or arr.shape != (height, width):
        raise LabelError(f"Stored label map {path.name} is corrupt (shape {arr.shape}, {arr.dtype}).")
    return arr


def to_raw_gzip(labels: np.ndarray) -> bytes:
    return gzip.compress(np.ascontiguousarray(labels).tobytes(), compresslevel=5)


def colourize(labels: np.ndarray, palette: Mapping[int, str]) -> np.ndarray:
    """RGB rendering using the project class colours (background black)."""
    lut = np.zeros((256, 3), dtype=np.uint8)
    for index, color in palette.items():
        lut[int(index)] = hex_to_rgb(color)
    return lut[labels]


def binary(labels: np.ndarray, class_index: int) -> np.ndarray:
    return np.where(labels == class_index, 255, 0).astype(np.uint8)


def interpret_mask_image(
    arr: np.ndarray, palette: Mapping[int, str], import_class: int
) -> tuple[np.ndarray, str]:
    """Convert an externally produced mask into a label map. Returns (labels, description).

    Accepted inputs, tried in order:

    * single-channel whose values are all project class indices -> used as-is ("indexed");
    * single-channel with only {0, 255} (or {0, 1}) -> foreground becomes ``import_class`` ("binary");
    * RGB whose colours are exactly project class colours -> mapped by colour ("colour");
    * RGB red-dominant (R >= 200, G <= 60, B <= 60, the HydrideSegmentation convention)
      -> ``import_class`` ("red-dominant").

    Anything else is rejected rather than guessed.
    """
    allowed = {0} | {int(i) for i in palette}
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if arr.ndim == 3 and arr.shape[2] == 3 and np.array_equal(arr[:, :, 0], arr[:, :, 1]) and np.array_equal(
        arr[:, :, 1], arr[:, :, 2]
    ):
        arr = arr[:, :, 0]
    if arr.ndim == 2:
        arr = arr.astype(np.int64)
        values = set(int(v) for v in np.unique(arr))
        if values <= allowed and not values <= {0, 255}:
            return arr.astype(np.uint8), "indexed"
        if values <= {0, 255} or values <= {0, 1}:
            out = np.where(arr > 0, import_class, 0).astype(np.uint8)
            return out, "binary"
        raise LabelError(
            f"Grey mask values {sorted(values)[:8]} are neither class indices {sorted(allowed)} nor binary 0/255."
        )
    if arr.ndim == 3 and arr.shape[2] == 3:
        rgb = arr.astype(np.uint8)
        out = np.zeros(rgb.shape[:2], dtype=np.uint8)
        matched = np.all(rgb == 0, axis=2)
        for index, color in palette.items():
            hit = np.all(rgb == np.array(hex_to_rgb(color), dtype=np.uint8), axis=2)
            out[hit] = int(index)
            matched |= hit
        if matched.all():
            return out, "colour"
        red = (rgb[:, :, 0] >= 200) & (rgb[:, :, 1] <= 60) & (rgb[:, :, 2] <= 60)
        return np.where(red, import_class, 0).astype(np.uint8), "red-dominant"
    raise LabelError(f"Unsupported mask layout {arr.shape}.")
