"""Label-map primitives: validation, persistence, statistics, rendering and mask import.

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
from dataclasses import asdict, dataclass, field
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


# ============================================================================= mask import
# Everything below turns a mask file made by another tool into a label map. Class numbers
# (what a pixel *means*) are kept apart from display values (how a viewer *shows* it): a
# black/white PNG stores 255 for "foreground" only so that people can see it, whereas a label
# map stores the class number. The analysis decides which of the two a file is before anything
# is stored, explains the decision, and asks instead of guessing when a file reads both ways.

IMPORT_MODES = ("auto", "indexed", "binary", "threshold", "colour")
PROVENANCE_SCHEMA = "online-annotator.mask-import/1"
# HydrideSegmentation's red-on-black convention (the same thresholds as its dataset preparation).
RED_MIN, GREEN_BLUE_MAX = 200, 60
# Pixels that are neither red nor near-black, as a fraction of the image: up to this much the
# red-on-black reading is offered for confirmation (soft edges); beyond it, it is not such a mask.
RED_STRAY_TOLERANCE = 0.01
PHOTO_COLOURS = 256  # more distinct colours than this and the file is a picture, not a mask
FEW_LEVELS = 16  # an unknown grey mask with at most this many levels reads as class numbers

BINARY_ENCODINGS = frozenset({"binary", "binary_0_1", "binary_0_255", "binary_like", "threshold", "red_on_black"})

# detected encoding -> (name shown to people, one-word "kind" kept for older API clients)
ENCODINGS: dict[str, tuple[str, str]] = {
    "indexed": ("Indexed class mask", "indexed"),
    "palette_indexed": ("Palette PNG whose indices are class numbers", "indexed"),
    "binary_0_1": ("Binary mask (0/1)", "binary"),
    "binary_0_255": ("Binary display mask (0/255)", "binary"),
    "binary_like": ("Two-value mask", "binary"),
    "binary": ("Binary mask", "binary"),
    "threshold": ("Greyscale mask cut at a threshold", "threshold"),
    "colour": ("Colour mask in the project's class colours", "colour"),
    "red_on_black": ("Red-on-black mask (HydrideSegmentation convention)", "red-dominant"),
    "grayscale_multilevel": ("Greyscale image with many levels", "grayscale"),
    "indexed_unknown": ("Class-number mask with values this project does not define", "indexed"),
    "colour_unknown": ("Colour image whose colours are not class colours", "colour"),
    "photo": ("Photograph or micrograph, not a mask", "photo"),
    "wrong_size": ("Mask of the wrong size", "invalid"),
    "unreadable": ("Unreadable file", "invalid"),
    "unsupported": ("Unsupported file", "invalid"),
}
MODE_NAMES = {"auto": "Auto detect", "indexed": "Indexed class mask", "binary": "Binary mask",
              "threshold": "Grayscale threshold", "colour": "Colour mask"}


@dataclass(frozen=True)
class MaskClass:
    """A project class as the mask analysis needs it."""

    index: int
    name: str
    color: str

    @property
    def label(self) -> str:
        return f"class {self.index} {self.name}"


@dataclass
class MaskAnalysis:
    """What an uploaded mask file is and exactly how it becomes labels.

    One object serves the preview shown before import, the import itself, the audit entry,
    the provenance stored with the image and every exported version, and the tests.
    ``ok`` means the file can be turned into labels with the chosen options;
    ``requires_confirmation`` means it must not be imported until the user confirms
    ``confirmation``. When ``ok`` is false, ``error`` says what was found and what to do.
    """

    filename: str = ""
    requested_mode: str = "auto"
    file_sha256: str = ""
    file_format: str = ""
    pil_mode: str = ""
    dtype: str = ""
    channels: int = 0
    width: int = 0
    height: int = 0
    expected_width: int = 0
    expected_height: int = 0
    detected: str = "unreadable"
    observed_values: list[float] = field(default_factory=list)
    value_count: int = 0
    value_range: list[float] | None = None
    observed_colours: list[dict] = field(default_factory=list)
    colour_count: int = 0
    palette: list[dict] = field(default_factory=list)
    mapping: list[dict] = field(default_factory=list)
    normalization: str = ""
    target_class: int | None = None
    target_class_name: str = ""
    threshold: float | None = None
    suggested_threshold: float | None = None
    invert: bool = False
    foreground_fraction: float | None = None
    class_pixels: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    confirmation: str = ""
    ok: bool = False
    error: str = ""
    suggested_mode: str | None = None
    embedded_metadata: dict[str, str] = field(default_factory=dict)
    resized: bool = False

    @property
    def encoding_name(self) -> str:
        return ENCODINGS.get(self.detected, (self.detected, self.detected))[0]

    @property
    def kind(self) -> str:
        return ENCODINGS.get(self.detected, (self.detected, self.detected))[1]

    def note(self, text: str) -> None:
        self.normalization = f"{self.normalization} {text}".strip()

    def fail(self, detected: str, error: str, suggested_mode: str | None = None) -> None:
        self.detected, self.error, self.ok = detected, error, False
        self.requires_confirmation, self.confirmation = False, ""
        self.suggested_mode = suggested_mode

    def confirm(self, question: str) -> None:
        self.requires_confirmation = True
        self.confirmation = f"{self.confirmation} {question}".strip()

    def summary(self) -> list[str]:
        """Plain-language lines describing the detection and what will be stored."""
        head = f"Detected: {self.encoding_name}"
        if self.value_count and self.value_count <= 12:
            head += f" (values {_values_text(self.observed_values)})"
        elif self.value_count:
            head += f" ({self.value_count} levels, {_fmt(self.value_range[0])} to {_fmt(self.value_range[1])})"
        elif self.colour_count:
            head += f" ({self.colour_count} colour{'s' if self.colour_count != 1 else ''})"
        lines = [head]
        if self.width:
            parts = [f"{self.file_format or 'image'} {self.pil_mode}".strip(), self.dtype,
                     f"{self.width} x {self.height} px"]
            lines.append("File: " + ", ".join(p for p in parts if p))
        for entry in self.mapping:
            lines.append(f"{entry['source']} -> {entry['target']} ({entry['pixels']:,} px)")
        if self.foreground_fraction is not None:
            lines.append(f"Foreground: {self.foreground_fraction * 100:.1f}% of the image")
        if self.ok:
            lines.append("Size matches the image; nothing is resized.")
        return lines

    def to_dict(self) -> dict:
        out = asdict(self)
        out.update({"kind": self.kind, "encoding_name": self.encoding_name, "summary": self.summary(),
                    "mode_name": MODE_NAMES.get(self.requested_mode, self.requested_mode)})
        return out

    def provenance(self, *, source_tool: str, remarks: str, confirmed: bool, imported_by: str,
                   imported_at: str, tool_version: str) -> dict:
        """The record kept with the image, frozen into versions and written to export manifests."""
        return {
            "schema": PROVENANCE_SCHEMA,
            "file": self.filename,
            "file_sha256": self.file_sha256,
            "source_tool": source_tool,
            "remarks": remarks,
            "requested_mode": self.requested_mode,
            "detected_encoding": self.detected,
            "encoding_name": self.encoding_name,
            "file_format": {"format": self.file_format, "mode": self.pil_mode, "dtype": self.dtype,
                            "channels": self.channels, "width": self.width, "height": self.height},
            "observed_values": self.observed_values,
            "value_count": self.value_count,
            "observed_colours": self.observed_colours,
            "palette": self.palette,
            "mapping": self.mapping,
            "normalization": self.normalization,
            "target_class": self.target_class,
            "target_class_name": self.target_class_name,
            "threshold": self.threshold if self.detected == "threshold" else None,
            "invert": self.invert,
            "warnings": self.warnings,
            "confirmation_required": self.requires_confirmation,
            "confirmation": self.confirmation,
            "confirmed": bool(confirmed),
            "resized": False,
            "class_pixels": self.class_pixels,
            "foreground_fraction": self.foreground_fraction,
            "embedded_metadata": self.embedded_metadata,
            "imported_by": imported_by,
            "imported_at": imported_at,
            "tool": {"id": "online-annotator", "version": tool_version},
        }


# ----------------------------------------------------------------------------- helpers
def _num(value) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else round(number, 6)


def _fmt(value) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _values_text(values, limit: int = 12) -> str:
    shown = ", ".join(_fmt(v) for v in list(values)[:limit])
    return shown + (", ..." if len(values) > limit else "")


def _hex(code: int) -> str:
    return f"#{int(code):06X}"


def _class_list(classes: Mapping[int, MaskClass], colours: bool = False) -> str:
    parts = [f"{c.index} {c.name}" + (f" {c.color.upper()}" if colours else "") for c in classes.values()]
    return ", ".join(parts)


def _otsu(arr: np.ndarray, integral: bool) -> float | int:
    """Threshold separating the two main populations; pixels at or above it are foreground."""
    data = arr.astype(np.float64).ravel()
    low, high = float(data.min()), float(data.max())
    if low == high:
        return _num(low)
    hist, edges = np.histogram(data, bins=256, range=(low, high))
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centres)
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.divide(m0, w0, out=np.zeros_like(m0), where=valid)
    mu1 = np.divide(m0[-1] - m0, w1, out=np.zeros_like(m0), where=valid)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1.0)
    cut = float(edges[int(np.argmax(between)) + 1])
    return int(np.ceil(cut)) if integral else round(cut, 6)


@dataclass
class _Decoded:
    grey: np.ndarray | None = None  # 2-D numeric
    rgb: np.ndarray | None = None  # H x W x 3 uint8
    indices: np.ndarray | None = None  # palette PNG indices
    palette: np.ndarray | None = None  # 256 x 3 uint8
    grey_from_rgb: bool = False


def _alpha_channel(colour: np.ndarray, alpha: np.ndarray, a: MaskAnalysis) -> np.ndarray | None:
    """Masks drawn as opacity over one flat colour: the mask is the alpha channel."""
    if int(alpha.min()) == 255:
        return None
    flat = colour.reshape(-1, colour.shape[-1]) if colour.ndim == 3 else colour.reshape(-1, 1)
    if np.all(flat == flat[0]) and np.unique(alpha).size > 1:
        a.note("The colour is the same everywhere, so the mask was read from the transparency (alpha) channel.")
        return alpha
    a.warnings.append("Transparency is ignored: pixels are read by their stored values, whatever their opacity.")
    return None


def _decode(data: bytes, a: MaskAnalysis) -> _Decoded:
    try:
        pil = PILImage.open(io.BytesIO(data))
        pil.load()
    except (OSError, SyntaxError, ValueError, PILImage.DecompressionBombError) as exc:
        a.detected = "unreadable"
        raise LabelError(f"not a readable image ({exc}). Choose a PNG, TIFF or BMP mask file.") from exc
    out = _Decoded()
    with pil:
        a.file_format, a.pil_mode = pil.format or "", pil.mode
        a.width, a.height = pil.size
        a.embedded_metadata = {str(k)[:60]: v[:300] for k, v in list(pil.info.items())[:12] if isinstance(v, str)}
        frames = getattr(pil, "n_frames", 1)
        if frames > 1:
            a.detected = "unsupported"
            raise LabelError(f"the file holds {frames} pages or frames, but a mask is one image. "
                             "Save the page that belongs to this image as its own file.")
        mode = pil.mode
        if mode == "1":
            out.grey = np.asarray(pil.convert("L"))
            a.note("1-bit black/white image: white is read as 255.")
        elif mode == "P":
            out.indices = np.asarray(pil).astype(np.uint8)
            entries = np.asarray((pil.getpalette() or [])[:768], dtype=np.uint8).reshape(-1, 3)
            out.palette = np.zeros((256, 3), dtype=np.uint8)
            out.palette[: len(entries)] = entries
        elif mode == "L":
            out.grey = np.asarray(pil)
        elif mode.startswith("I;16"):
            out.grey = np.asarray(pil).astype(np.uint16)
        elif mode == "I":
            out.grey = np.asarray(pil).astype(np.int32)
        elif mode == "F":
            out.grey = np.asarray(pil).astype(np.float32)
        elif mode == "LA":
            arr = np.asarray(pil)
            alpha = _alpha_channel(arr[:, :, 0], arr[:, :, 1], a)
            out.grey = arr[:, :, 0] if alpha is None else alpha
        else:
            if mode not in ("RGB", "RGBA"):
                a.note(f"{mode} image converted to RGBA before reading.")
                pil = pil.convert("RGBA")
            arr = np.asarray(pil)
            rgb = arr[:, :, :3]
            alpha = _alpha_channel(rgb, arr[:, :, 3], a) if arr.shape[2] == 4 else None
            if alpha is not None:
                out.grey = alpha
            elif np.array_equal(rgb[:, :, 0], rgb[:, :, 1]) and np.array_equal(rgb[:, :, 1], rgb[:, :, 2]):
                out.grey, out.grey_from_rgb = rgb[:, :, 0], True
                a.note("RGB image with identical channels, read as greyscale.")
            else:
                out.rgb = rgb
    a.channels = 3 if out.rgb is not None else 1
    return out


def _mapping(source: str, target: MaskClass | None, pixels: int) -> dict:
    return {"source": source, "class_index": target.index if target else 0,
            "target": target.label if target else "background", "pixels": int(pixels)}


# ---------------------------------------------------------------------------- analysers
def _analyse_grey(arr: np.ndarray, a: MaskAnalysis, classes: Mapping[int, MaskClass], mode: str,
                  target: MaskClass) -> np.ndarray | None:
    a.dtype = str(arr.dtype)
    if arr.dtype.kind == "f" and np.isnan(arr).any():
        a.fail("unsupported", "the mask contains undefined (NaN) values. Save it without empty pixels.")
        return None
    values, counts = np.unique(arr, return_counts=True)
    integral = arr.dtype.kind in "biu" or bool(np.all(np.mod(values, 1) == 0))
    a.value_count = int(values.size)
    a.observed_values = [_num(v) for v in values[:32]]
    a.value_range = [_num(values[0]), _num(values[-1])]
    small = integral and values.size <= 256
    vset = {int(v) for v in values} if small else set()
    count = {int(v): int(c) for v, c in zip(values, counts, strict=True)} if small else {}
    allowed = {0, *classes}
    display_max = 255 if arr.dtype == np.uint8 else 65535 if arr.dtype.kind in "iu" else None

    def indexed(detected: str = "indexed") -> np.ndarray:
        a.detected = detected
        a.mapping = [_mapping(str(v), classes.get(v), count[v]) for v in sorted(vset)]
        a.note("None: every value is already a class number of this project and is stored exactly as it is.")
        return arr.astype(np.uint8)

    def two_level(detected: str, foreground_value: int | None) -> np.ndarray:
        a.detected = detected
        fg = arr != 0
        fg_source, bg_source = (str(foreground_value) if foreground_value is not None else "non-zero"), "0"
        if a.invert:
            fg, fg_source, bg_source = ~fg, "0", fg_source
        a.mapping = [_mapping(fg_source, target, int(fg.sum())), _mapping(bg_source, None, int((~fg).sum()))]
        a.note(f"Binary normalization: {fg_source} marks the foreground and becomes {target.label}; "
               f"{bg_source} becomes background.")
        return np.where(fg, target.index, 0).astype(np.uint8)

    def unknown_values() -> None:
        if small and len(vset) <= FEW_LEVELS:
            unknown = sorted(vset - allowed)
            a.fail("indexed_unknown",
                   f"the mask holds the value{'s' if len(unknown) > 1 else ''} {_values_text(unknown)}, which "
                   f"{'are' if len(unknown) > 1 else 'is'} not a class number of this project (classes: "
                   f"{_class_list(classes)}). If they are classes, an administrator can add them under Classes "
                   "& guidelines. If this is a black/white mask, choose Binary mask; if it is a greyscale or "
                   "probability image, choose Grayscale threshold.", "threshold")
        else:
            a.suggested_threshold = _otsu(arr, integral)
            a.fail("grayscale_multilevel",
                   f"this is a greyscale image with {values.size} different levels ({_fmt(values[0])} to "
                   f"{_fmt(values[-1])}), not a binary or class-number mask. Nothing is guessed: choose Grayscale "
                   f"threshold, check the preview (suggested threshold {_fmt(a.suggested_threshold)}) and "
                   "confirm. If this is the micrograph rather than its mask, choose the mask file instead.",
                   "threshold")

    if mode == "colour":
        if arr.dtype != np.uint8:
            a.fail("unsupported", "this is a high bit-depth greyscale image, not a colour mask. "
                                  "Choose Auto detect, Binary mask or Grayscale threshold.")
            return None
        return _analyse_rgb(np.repeat(arr[:, :, None], 3, axis=2), a, classes, mode, target)

    if mode == "threshold":
        a.suggested_threshold = _otsu(arr, integral)
        if a.threshold is None:
            a.detected = "threshold"
            a.fail("threshold", f"enter a threshold: pixels at or above it become {target.label}. The suggested "
                                f"threshold for this image is {_fmt(a.suggested_threshold)}.", "threshold")
            return None
        a.detected = "threshold"
        t = a.threshold
        fg = arr >= t
        fg_source, bg_source = f"values >= {_fmt(t)}", f"values < {_fmt(t)}"
        if a.invert:
            fg, fg_source, bg_source = ~fg, bg_source, fg_source
        a.mapping = [_mapping(fg_source, target, int(fg.sum())), _mapping(bg_source, None, int((~fg).sum()))]
        a.note(f"Threshold {_fmt(t)} chosen by the user: {fg_source} become {target.label}, "
               f"{bg_source} become background.")
        if small and vset <= allowed and len(vset) > 2:
            a.warnings.append("These values are already class numbers of this project; a threshold merges them "
                              "into one class. Choose Indexed class mask to keep every class.")
        fraction = float(fg.mean())
        a.confirm(f"Confirm the threshold: {fg_source} become {target.label} ({fraction * 100:.1f}% of the "
                  "image); everything else becomes background.")
        return np.where(fg, target.index, 0).astype(np.uint8)

    if mode == "indexed":
        if small and vset <= allowed:
            return indexed()
        unknown_values()
        return None

    if mode == "binary":
        if not small:
            unknown_values()
            a.error = a.error.replace("not a binary or class-number mask", "not a binary mask")
            return None
        nonzero = sorted(vset - {0})
        if len(nonzero) > 1:
            a.fail("indexed_unknown" if len(vset) <= FEW_LEVELS else "grayscale_multilevel",
                   f"it holds {len(nonzero)} different non-zero values ({_values_text(nonzero)}), so it is not a "
                   "binary mask. Choose Indexed class mask if they are class numbers, or Grayscale threshold.",
                   "threshold")
            return None
        value = nonzero[0] if nonzero else None
        detected = "binary_0_1" if value == 1 else "binary_0_255" if value == 255 else "binary"
        return two_level(detected, value)

    # ---- auto: the documented order
    if small and vset <= allowed and a.pil_mode != "1":
        return indexed()
    if small and vset <= {0, 1}:
        return two_level("binary_0_1", 1)
    if small and display_max is not None and display_max in vset and vset <= {0, display_max}:
        return two_level("binary_0_255" if display_max == 255 else "binary", display_max)
    if small and len(vset) == 2 and 0 in vset:
        value = max(vset)
        labels = two_level("binary_like", value)
        a.confirm(f"The mask holds only 0 and {value}. Confirm that {value} marks the foreground "
                  f"({target.label}) and is not a class number from another project.")
        return labels
    unknown_values()
    return None


def _analyse_rgb(rgb: np.ndarray, a: MaskAnalysis, classes: Mapping[int, MaskClass], mode: str,
                 target: MaskClass) -> np.ndarray | None:
    a.dtype = str(rgb.dtype)
    a.channels = 3
    if mode in ("indexed", "binary", "threshold"):
        a.fail("colour_unknown", f"this is a colour image, which cannot be read as {MODE_NAMES[mode]}. "
                                 "Choose Auto detect or Colour mask.", "colour")
        return None
    r, g, b = (rgb[:, :, i].astype(np.int32) for i in range(3))
    codes = (r << 16) | (g << 8) | b
    uniq, counts = np.unique(codes, return_counts=True)
    order = np.argsort(-counts, kind="stable")
    a.colour_count = int(uniq.size)
    a.observed_colours = [{"rgb": _hex(uniq[i]), "pixels": int(counts[i])} for i in order[:16]]

    colour_class: dict[int, MaskClass] = {}
    shared = set()
    for cls in classes.values():
        code = int.from_bytes(bytes(hex_to_rgb(cls.color)), "big")
        if code in colour_class or code == 0:
            shared.add(code)
        colour_class[code] = cls
    for code in shared:
        colour_class.pop(code, None)
    if shared:
        a.warnings.append("Some classes share a colour (or use black), so those colours cannot identify a class.")

    present = {int(u) for u in uniq}
    if uniq.size <= PHOTO_COLOURS and present <= set(colour_class) | {0}:
        out = np.zeros(codes.shape, dtype=np.uint8)
        pixels = {int(u): int(c) for u, c in zip(uniq, counts, strict=True)}
        a.mapping = []
        for code in sorted(present):
            cls = colour_class.get(code)
            if cls is not None:
                out[codes == code] = cls.index
            a.mapping.append(_mapping(f"colour {_hex(code)}", cls, pixels[code]))
        a.detected = "colour"
        a.note("Each colour was matched exactly to a project class colour; black is background.")
        if a.invert:
            a.warnings.append("Foreground is black applies only to binary and threshold masks, so it was ignored.")
            a.invert = False
        return out

    red = (r >= RED_MIN) & (g <= GREEN_BLUE_MAX) & (b <= GREEN_BLUE_MAX)
    dark = ~red & (np.maximum(np.maximum(r, g), b) <= GREEN_BLUE_MAX)
    stray = ~(red | dark)
    n_stray, total = int(stray.sum()), int(codes.size)
    if red.any() and n_stray <= RED_STRAY_TOLERANCE * total:
        a.detected = "red_on_black"
        a.mapping = [_mapping(f"red (R >= {RED_MIN}, G and B <= {GREEN_BLUE_MAX})", target, int(red.sum())),
                     _mapping("black and near-black", None, int(dark.sum()))]
        a.note(f"Red-on-black normalization (HydrideSegmentation convention): red pixels become {target.label}; "
               f"black and near-black pixels (every channel <= {GREEN_BLUE_MAX}) become background.")
        if n_stray:
            a.mapping.append(_mapping("other colours", None, n_stray))
            a.warnings.append(f"{n_stray:,} pixels ({n_stray / total * 100:.2f}%) are neither red nor black, for "
                              "example soft or anti-aliased edges; they become background.")
            a.confirm("Confirm that the pixels that are neither red nor black are background.")
        if a.invert:
            a.warnings.append("Foreground is black applies only to binary and threshold masks, so it was ignored.")
            a.invert = False
        return np.where(red, target.index, 0).astype(np.uint8)

    if uniq.size > PHOTO_COLOURS or n_stray > 0.5 * total:
        a.fail("photo", f"it has {uniq.size:,} different colours, so it looks like a photograph, micrograph or "
                        "overlay rather than a mask. Choose the mask file. A colour mask may only use black and "
                        f"the project's class colours ({_class_list(classes, colours=True)}), or red on black.")
        return None
    unmatched = [f"{_hex(uniq[i])} ({int(counts[i]):,} px)" for i in order
                 if int(uniq[i]) not in colour_class and int(uniq[i]) != 0][:5]
    a.fail("colour_unknown",
           f"its colours {', '.join(unmatched)} are not class colours of this project "
           f"({_class_list(classes, colours=True)}), and it is not a red-on-black mask. Change the class colours "
           "to match, or save the mask as class numbers (0 = background, 1, 2, ... = classes).")
    return None


def _analyse_palette(dec: _Decoded, a: MaskAnalysis, classes: Mapping[int, MaskClass], mode: str,
                     target: MaskClass) -> np.ndarray | None:
    idx, pal = dec.indices, dec.palette
    used, counts = np.unique(idx, return_counts=True)
    used_set = {int(u) for u in used}
    pixels = {int(u): int(c) for u, c in zip(used, counts, strict=True)}
    shown = {int(u): _hex(int.from_bytes(bytes(pal[u]), "big")) for u in used}
    a.palette = [{"index": u, "rgb": shown[u], "pixels": pixels[u]} for u in sorted(used_set)[:32]]
    colours = pal[idx]
    allowed = {0, *classes}

    if mode == "colour":
        a.note("Palette PNG read by its display colours, as requested.")
        return _analyse_rgb(colours, a, classes, mode, target)

    if mode == "indexed" or (mode == "auto" and used_set <= allowed):
        a.dtype = "uint8"
        a.value_count = len(used_set)
        a.observed_values = sorted(used_set)[:32]
        a.value_range = [min(used_set), max(used_set)]
        if not used_set <= allowed:
            unknown = sorted(used_set - allowed)
            a.fail("indexed_unknown", f"its palette indices {_values_text(unknown)} are not class numbers of this "
                                      f"project (classes: {_class_list(classes)}). Choose Colour mask to read the "
                                      "file by its colours instead.", "colour")
            return None
        a.detected = "palette_indexed"
        a.mapping = [_mapping(f"index {u} (shown {shown[u]})", classes.get(u), pixels[u])
                     for u in sorted(used_set)]
        a.note("Palette indices are class numbers of this project and are stored exactly; the palette only "
               "decides how viewers colour them.")
        labels = idx.copy()
        if mode == "auto":
            alt = MaskAnalysis(width=a.width, height=a.height)
            decoded_grey = np.array_equal(colours[:, :, 0], colours[:, :, 1]) and np.array_equal(
                colours[:, :, 1], colours[:, :, 2])
            alt_labels = (_analyse_grey(colours[:, :, 0], alt, classes, "auto", target) if decoded_grey
                          else _analyse_rgb(colours, alt, classes, "auto", target))
            if alt_labels is not None and not np.array_equal(alt_labels, labels):
                a.warnings.append(f"Read by its display colours instead, this file would give different labels "
                                  f"({alt.encoding_name}). The stored class numbers are the palette indices.")
                a.confirm("Confirm that the palette indices are the class numbers. To read the file by its "
                          "colours instead, choose Colour mask.")
            else:
                differ = [f"{u} shown {shown[u]}" for u in sorted(used_set)
                          if u in classes and shown[u] != classes[u].color.upper()]
                if differ:
                    a.warnings.append(f"The palette shows class numbers in other colours than the project uses "
                                      f"({', '.join(differ)}). Only the numbers are stored, so the labels are "
                                      "unaffected.")
        return labels

    a.note(f"Palette indices {_values_text(sorted(used_set))} are not class numbers of this project, so the "
           "palette colours were read instead.")
    is_grey = bool(np.all(pal[used, 0] == pal[used, 1]) and np.all(pal[used, 1] == pal[used, 2]))
    if is_grey:
        return _analyse_grey(colours[:, :, 0], a, classes, mode, target)
    if mode in ("binary", "threshold"):
        a.note("The palette is not grey, so the indices were read as grey levels.")
        return _analyse_grey(idx, a, classes, mode, target)
    return _analyse_rgb(colours, a, classes, mode, target)


def analyze_mask_file(
    data: bytes,
    *,
    width: int,
    height: int,
    classes: Mapping[int, MaskClass],
    mode: str = "auto",
    target_class: int | None = None,
    threshold: float | None = None,
    invert: bool = False,
    filename: str = "",
    image_sha256: str | None = None,
) -> tuple[MaskAnalysis, np.ndarray | None]:
    """Work out what an uploaded mask file is and, when possible, the label map it stands for.

    The single place an externally produced mask becomes labels, shared by the preview and by
    the per-image and bulk imports. Auto detection, in order:

    1. every value is a class number of the project -> stored exactly ("indexed");
    2. values {0, 1} -> binary, 1 becomes the chosen class;
    3. values {0, 255} -> binary display mask, 255 becomes the chosen class;
    4. two values, one of them 0 ({0, 128}, {0, 7}) -> binary-like, only after confirmation;
    5. RGB in exactly black and the project class colours -> classes by colour;
    6. red on black (R >= 200, G <= 60, B <= 60) -> the chosen class (HydrideSegmentation);
    7. palette PNG -> indices first when they are class numbers, otherwise its colours;
    8. greyscale with many levels -> refused; import it with an explicit threshold instead.

    Nothing is ever resized: a mask of the wrong size is refused. Returns the analysis and the
    labels (``None`` whenever ``analysis.ok`` is false).
    """
    a = MaskAnalysis(filename=filename, requested_mode=mode, expected_width=width, expected_height=height,
                     invert=bool(invert), threshold=None if threshold is None else _num(threshold))
    a.file_sha256 = hashlib.sha256(data).hexdigest()
    if mode not in IMPORT_MODES:
        a.fail("unsupported", f"unknown interpretation {mode!r}; choose one of {', '.join(IMPORT_MODES)}.")
        return a, None
    if not classes:
        a.fail("unsupported", "this project has no classes yet, so a mask cannot be interpreted. An "
                              "administrator adds classes under Classes & guidelines.")
        return a, None
    if target_class in classes:
        target = classes[target_class]
    else:
        target = classes[min(classes)]
        if target_class is not None:
            a.warnings.append(f"Class {target_class} does not exist in this project, so {target.label} was used.")
    a.target_class, a.target_class_name = target.index, target.name
    if image_sha256 and a.file_sha256 == image_sha256:
        a.fail("unsupported", "this file is the image itself, not a mask. Choose the mask file that belongs to it.")
        return a, None

    try:
        dec = _decode(data, a)
    except LabelError as exc:
        a.fail(a.detected, str(exc))
        return a, None
    if (a.width, a.height) != (width, height):
        a.fail("wrong_size", f"its size {a.width} x {a.height} does not match the image ({width} x {height}). "
                             "Masks are never resized, because resizing would change the ground truth. Export "
                             "the mask at the image's full resolution, or check that it belongs to this image.")
        return a, None

    if dec.indices is not None:
        labels = _analyse_palette(dec, a, classes, mode, target)
    elif dec.grey is not None:
        labels = _analyse_grey(dec.grey, a, classes, mode, target)
        if labels is not None and mode == "auto" and dec.grey_from_rgb:
            alt = MaskAnalysis(width=a.width, height=a.height)
            alt_labels = _analyse_rgb(np.repeat(dec.grey[:, :, None], 3, axis=2), alt, classes, "colour", target)
            if alt_labels is not None and alt.detected == "colour" and not np.array_equal(alt_labels, labels):
                a.warnings.append("The file is also an exact match for the project's class colours, which would "
                                  "give different labels. Choose Colour mask to read it by colour.")
                a.confirm("Confirm the greyscale reading shown here.")
    else:
        labels = _analyse_rgb(dec.rgb, a, classes, mode, target)
    if labels is None:
        return a, None

    if a.invert and a.detected not in BINARY_ENCODINGS:
        a.warnings.append("Foreground is black applies only to binary and threshold masks, so it was ignored.")
        a.invert = False
    a.ok, a.error = True, ""
    a.class_pixels = class_pixels(labels)
    foreground = int(np.count_nonzero(labels))
    a.foreground_fraction = round(foreground / labels.size, 6)
    if foreground == 0:
        a.warnings.append("The mask is empty: every pixel becomes background. Importing it clears the labels.")
    elif foreground == labels.size:
        a.warnings.append("Every pixel becomes a class; the mask has no background at all.")
    elif a.detected in BINARY_ENCODINGS and a.foreground_fraction > 0.5:
        a.warnings.append(f"The foreground covers {a.foreground_fraction * 100:.1f}% of the image. If the mask "
                          "draws the features in black on white, "
                          + ("untick" if a.invert else "tick") + " Foreground is black.")
    return a, labels
