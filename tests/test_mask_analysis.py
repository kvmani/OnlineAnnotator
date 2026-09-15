"""How an externally produced mask file is interpreted, before anything is stored.

Class numbers (what a pixel means) are kept apart from display values (how a viewer shows it).
Every case here states the detected encoding, the labels that would be stored, and whether the
user is asked to confirm. Common masks import on their own; ambiguous ones never do silently.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image as PILImage
from PIL.PngImagePlugin import PngInfo

from online_annotator.services import labels
from online_annotator.services.labels import MaskClass

W, H = 64, 48
HYDRIDE_PORE = {1: MaskClass(1, "Hydride", "#FF0000"), 2: MaskClass(2, "Pore", "#0000FF")}
# A project whose classes are 2 and 3, so {0, 1} is not already a set of class numbers.
PHASES = {2: MaskClass(2, "Alpha", "#00FF00"), 3: MaskClass(3, "Beta", "#FFFF00")}


def encode(arr: np.ndarray, mode: str | None = None, fmt: str = "PNG", **save) -> bytes:
    buf = io.BytesIO()
    image = PILImage.fromarray(arr, mode) if mode else PILImage.fromarray(arr)
    image.save(buf, format=fmt, **save)
    return buf.getvalue()


def analyse(data: bytes, classes=HYDRIDE_PORE, **options):
    return labels.analyze_mask_file(data, width=W, height=H, classes=classes, filename="m.png", **options)


def grey(values: dict[tuple[slice, slice], int], dtype=np.uint8) -> np.ndarray:
    arr = np.zeros((H, W), dtype=dtype)
    for (rows, cols), value in values.items():
        arr[rows, cols] = value
    return arr


BLOCK = (slice(10, 14), slice(5, 50))  # 4 x 45 = 180 pixels
OTHER = (slice(30, 34), slice(5, 15))  # 4 x 10 = 40 pixels


def values_of(arr: np.ndarray) -> set[int]:
    return {int(v) for v in np.unique(arr)}


# ------------------------------------------------------------------ grey, the common cases
def test_zero_one_mask_whose_values_are_classes_is_kept_exactly():
    analysis, out = analyse(encode(grey({BLOCK: 1})), target_class=2)
    assert analysis.ok and not analysis.requires_confirmation
    assert analysis.detected == "indexed"  # rule 1 comes before rule 2
    assert values_of(out) == {0, 1} and int(out.sum()) == 180


def test_zero_one_mask_becomes_the_chosen_class_when_one_is_not_a_class():
    analysis, out = analyse(encode(grey({BLOCK: 1})), classes=PHASES, target_class=3)
    assert analysis.ok and not analysis.requires_confirmation
    assert analysis.detected == "binary_0_1" and analysis.kind == "binary"
    assert values_of(out) == {0, 3} and int((out == 3).sum()) == 180
    assert analysis.mapping[0] == {"source": "1", "class_index": 3, "target": "class 3 Beta", "pixels": 180}


def test_zero_255_display_mask_maps_foreground_to_the_chosen_class():
    analysis, out = analyse(encode(grey({BLOCK: 255})), target_class=2)
    assert analysis.ok and not analysis.requires_confirmation
    assert analysis.detected == "binary_0_255"
    assert values_of(out) == {0, 2} and int((out == 2).sum()) == 180
    assert analysis.observed_values == [0, 255]
    assert analysis.mapping[0]["source"] == "255" and analysis.mapping[0]["target"] == "class 2 Pore"
    assert analysis.foreground_fraction == pytest.approx(180 / (W * H), abs=1e-6)
    summary = "\n".join(analysis.summary())
    assert "Binary display mask (0/255)" in summary and "255 -> class 2 Pore (180 px)" in summary
    assert "nothing is resized" in summary


@pytest.mark.parametrize("value", [128, 7])
def test_other_two_value_masks_are_binary_like_but_need_confirmation(value):
    analysis, out = analyse(encode(grey({BLOCK: value})))
    assert analysis.ok and analysis.requires_confirmation
    assert analysis.detected == "binary_like"
    assert f"only 0 and {value}" in analysis.confirmation
    assert values_of(out) == {0, 1} and int(out.sum()) == 180


def test_class_two_alone_is_class_two_not_a_binary_foreground():
    """Project classes {1, 2}; a mask of {0, 2} keeps class 2, whatever class is chosen for binaries."""
    analysis, out = analyse(encode(grey({BLOCK: 2})), target_class=1)
    assert analysis.ok and not analysis.requires_confirmation
    assert analysis.detected == "indexed"
    assert values_of(out) == {0, 2} and int((out == 2).sum()) == 180


def test_multiclass_indexed_mask_is_preserved_exactly():
    arr = grey({BLOCK: 1, OTHER: 2})
    analysis, out = analyse(encode(arr))
    assert analysis.ok and analysis.detected == "indexed"
    assert np.array_equal(out, arr)
    assert analysis.class_pixels == {"1": 180, "2": 40}


def test_unknown_class_value_is_refused_with_guidance():
    analysis, out = analyse(encode(grey({BLOCK: 1, OTHER: 7})))
    assert out is None and not analysis.ok
    assert analysis.detected == "indexed_unknown"
    assert "value 7" in analysis.error and "1 Hydride, 2 Pore" in analysis.error
    assert "Grayscale threshold" in analysis.error and "Binary mask" in analysis.error


def test_a_single_unknown_value_is_refused():
    analysis, out = analyse(encode(np.full((H, W), 77, dtype=np.uint8)))
    assert out is None and analysis.detected == "indexed_unknown" and "77" in analysis.error


# ------------------------------------------------------------------- grey, many levels
def ramp() -> np.ndarray:
    return np.tile(np.linspace(0, 255, W).astype(np.uint8), (H, 1))


def test_many_level_greyscale_is_never_binarized_automatically():
    analysis, out = analyse(encode(ramp()))
    assert out is None and not analysis.ok
    assert analysis.detected == "grayscale_multilevel"
    assert analysis.suggested_mode == "threshold" and analysis.suggested_threshold is not None
    assert analysis.value_count == W and analysis.value_range == [0, 255]
    assert "Grayscale threshold" in analysis.error


def test_threshold_mode_needs_a_value_then_a_confirmation():
    missing, out = analyse(encode(ramp()), mode="threshold")
    assert out is None and "enter a threshold" in missing.error and missing.suggested_threshold is not None

    analysis, out = analyse(encode(ramp()), mode="threshold", threshold=128, target_class=2)
    assert analysis.ok and analysis.requires_confirmation
    assert analysis.detected == "threshold" and analysis.threshold == 128
    assert np.array_equal(out, np.where(ramp() >= 128, 2, 0).astype(np.uint8))
    assert "values >= 128" in analysis.confirmation

    inverted, out = analyse(encode(ramp()), mode="threshold", threshold=128, invert=True)
    assert np.array_equal(out, np.where(ramp() < 128, 1, 0).astype(np.uint8))


def test_explicit_modes_refuse_files_that_do_not_fit_them():
    indexed, _ = analyse(encode(grey({BLOCK: 255})), mode="indexed")
    assert not indexed.ok and "Binary mask" in indexed.error
    binary, _ = analyse(encode(grey({BLOCK: 1, OTHER: 2})), mode="binary")
    assert not binary.ok and "not a binary mask" in binary.error
    explicit, out = analyse(encode(grey({BLOCK: 7})), mode="binary")
    assert explicit.ok and not explicit.requires_confirmation and values_of(out) == {0, 1}


def test_black_on_white_can_be_inverted():
    arr = np.full((H, W), 255, dtype=np.uint8)
    arr[BLOCK] = 0
    plain, _ = analyse(encode(arr))
    assert any("Foreground is black" in w for w in plain.warnings)
    analysis, out = analyse(encode(arr), invert=True)
    assert analysis.ok and int(out.sum()) == 180 and out[BLOCK].all()


# ------------------------------------------------------------------------ colour masks
def test_exact_project_colours_become_those_classes():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[BLOCK] = (255, 0, 0)
    rgb[OTHER] = (0, 0, 255)
    analysis, out = analyse(encode(rgb), target_class=2)
    assert analysis.ok and analysis.detected == "colour" and not analysis.requires_confirmation
    assert (out[BLOCK] == 1).all() and (out[OTHER] == 2).all() and analysis.class_pixels == {"1": 180, "2": 40}
    # Every mapping row carries the pixel count of its own colour.
    assert {m["source"]: m["pixels"] for m in analysis.mapping} == {
        "colour #000000": W * H - 220, "colour #0000FF": 40, "colour #FF0000": 180}


def test_red_on_black_follows_the_hydride_segmentation_convention():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[BLOCK] = (220, 30, 30)
    rgb[0, 0] = (40, 40, 40)  # near-black is background
    analysis, out = analyse(encode(rgb), target_class=2)
    assert analysis.ok and not analysis.requires_confirmation
    assert analysis.detected == "red_on_black" and analysis.kind == "red-dominant"
    assert values_of(out) == {0, 2} and int((out == 2).sum()) == 180


def test_red_on_black_with_soft_edges_asks_first():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[BLOCK] = (220, 30, 30)
    rgb[9, 5:25] = (120, 20, 20)  # 20 anti-aliased pixels, 0.65 %
    analysis, out = analyse(encode(rgb))
    assert analysis.ok and analysis.requires_confirmation
    assert "neither red nor black" in analysis.warnings[0] and int(out.sum()) == 180


def test_an_accidental_photograph_is_refused():
    rng = np.random.default_rng(1)
    photo = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
    analysis, out = analyse(encode(photo))
    assert out is None and analysis.detected == "photo"
    assert "photograph" in analysis.error and "#FF0000" in analysis.error


def test_an_overlay_of_red_on_a_micrograph_is_refused():
    base = np.tile(np.linspace(60, 200, W).astype(np.uint8), (H, 1))
    rgb = np.repeat(base[:, :, None], 3, axis=2)
    rgb[BLOCK] = (230, 20, 20)
    analysis, out = analyse(encode(rgb))
    assert out is None and not analysis.ok


def test_unknown_colours_are_named():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[BLOCK] = (0, 200, 0)
    analysis, out = analyse(encode(rgb))
    assert out is None and analysis.detected == "colour_unknown" and "#00C800" in analysis.error


def test_equal_channel_rgb_black_and_white_still_reads_as_binary():
    rgb = np.repeat(grey({BLOCK: 255})[:, :, None], 3, axis=2)
    analysis, out = analyse(encode(rgb))
    assert analysis.ok and analysis.detected == "binary_0_255" and int(out.sum()) == 180


# -------------------------------------------------------------------------- palette PNG
def palette_png(indices: np.ndarray, palette: dict[int, tuple[int, int, int]]) -> bytes:
    image = PILImage.fromarray(indices.astype(np.uint8), "P")
    flat = [0] * 768
    for index, rgb in palette.items():
        flat[index * 3: index * 3 + 3] = rgb
    image.putpalette(flat)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_palette_png_indices_are_the_class_numbers():
    """A VOC-style palette PNG: indices 1 and 2 shown dark red and dark green."""
    indices = grey({BLOCK: 1, OTHER: 2})
    data = palette_png(indices, {0: (0, 0, 0), 1: (128, 0, 0), 2: (0, 128, 0)})
    assert PILImage.open(io.BytesIO(data)).mode == "P"
    analysis, out = analyse(data, target_class=2)
    assert analysis.ok and analysis.detected == "palette_indexed" and not analysis.requires_confirmation
    assert np.array_equal(out, indices)
    assert any("Only the numbers are stored" in w for w in analysis.warnings)
    assert analysis.palette[1] == {"index": 1, "rgb": "#800000", "pixels": 180}
    assert [(m["source"], m["pixels"]) for m in analysis.mapping] == [
        ("index 0 (shown #000000)", W * H - 220), ("index 1 (shown #800000)", 180), ("index 2 (shown #008000)", 40)]


def test_palette_png_with_many_used_indices_that_are_all_classes():
    classes = {i: MaskClass(i, f"Phase {i}", f"#{i:02X}{i:02X}{i:02X}") for i in range(1, 41)}
    indices = (np.arange(W * H) % 41).reshape(H, W).astype(np.uint8)
    data = palette_png(indices, {i: (i, 0, 0) for i in range(41)})
    analysis, out = labels.analyze_mask_file(data, width=W, height=H, classes=classes)
    assert analysis.ok and np.array_equal(out, indices) and len(analysis.mapping) == 41
    assert len(analysis.palette) == 32  # the stored listing is capped; the mapping is complete


def test_palette_png_whose_colours_disagree_with_its_indices_asks():
    indices = grey({BLOCK: 1})
    data = palette_png(indices, {0: (0, 0, 0), 1: (0, 0, 255)})  # index 1 drawn in the Pore colour
    analysis, out = analyse(data)
    assert analysis.ok and analysis.requires_confirmation and (out[BLOCK] == 1).all()
    by_colour, out = analyse(data, mode="colour")
    assert by_colour.ok and by_colour.detected == "colour" and (out[BLOCK] == 2).all()


def test_palette_png_with_arbitrary_indices_is_read_by_colour():
    indices = grey({BLOCK: 9})
    data = palette_png(indices, {0: (0, 0, 0), 9: (255, 0, 0)})
    analysis, out = analyse(data)
    assert analysis.ok and analysis.detected == "colour" and (out[BLOCK] == 1).all()
    assert "not class numbers" in analysis.normalization


# ------------------------------------------------------------------- refusals and edges
def test_wrong_size_is_refused_never_resized():
    analysis, out = labels.analyze_mask_file(encode(np.zeros((24, 32), np.uint8)), width=W, height=H,
                                             classes=HYDRIDE_PORE)
    assert out is None and analysis.detected == "wrong_size"
    assert "does not match the image" in analysis.error and "never resized" in analysis.error
    assert (analysis.width, analysis.height) == (32, 24)


def test_empty_and_full_masks_import_with_a_warning():
    empty, out = analyse(encode(np.zeros((H, W), np.uint8)))
    assert empty.ok and empty.detected == "indexed" and not out.any()
    assert any("empty" in w for w in empty.warnings)
    full, out = analyse(encode(np.full((H, W), 255, np.uint8)))
    assert full.ok and full.detected == "binary_0_255" and (out == 1).all()
    assert any("no background" in w for w in full.warnings)


def test_the_image_itself_is_not_accepted_as_its_mask():
    data = encode(grey({BLOCK: 1}))
    analysis, out = labels.analyze_mask_file(data, width=W, height=H, classes=HYDRIDE_PORE,
                                             image_sha256=__import__("hashlib").sha256(data).hexdigest())
    assert out is None and "the image itself" in analysis.error


def test_unreadable_and_multi_page_files_are_refused():
    broken, out = analyse(b"this is not a png")
    assert out is None and broken.detected == "unreadable" and "not a readable image" in broken.error
    buf = io.BytesIO()
    pages = [PILImage.fromarray(np.zeros((H, W), np.uint8)) for _ in range(2)]
    pages[0].save(buf, format="TIFF", save_all=True, append_images=pages[1:])
    multi, out = analyse(buf.getvalue())
    assert out is None and "2 pages" in multi.error


def test_one_bit_png_is_a_binary_mask():
    data = encode(grey({BLOCK: 255}) > 0, mode=None)
    assert PILImage.open(io.BytesIO(data)).mode == "1"
    analysis, out = analyse(data, target_class=2)
    assert analysis.ok and analysis.detected == "binary_0_255" and int((out == 2).sum()) == 180


def test_sixteen_bit_masks():
    indexed, out = analyse(encode(grey({BLOCK: 1, OTHER: 2}, dtype=np.uint16)))
    assert indexed.ok and indexed.detected == "indexed" and indexed.dtype == "uint16"
    assert out.dtype == np.uint8 and indexed.class_pixels == {"1": 180, "2": 40}
    display, out = analyse(encode(grey({BLOCK: 65535}, dtype=np.uint16)))
    assert display.ok and display.detected == "binary" and int(out.sum()) == 180


def test_mask_drawn_as_transparency_is_read_from_alpha():
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[:, :, 0] = 255
    rgba[BLOCK + (3,)] = 255
    analysis, out = analyse(encode(rgba))
    assert analysis.ok and analysis.detected == "binary_0_255" and int(out.sum()) == 180
    assert "alpha" in analysis.normalization


def test_embedded_png_text_is_kept_and_provenance_is_complete():
    info = PngInfo()
    info.add_text("Software", "HydrideSegmentation 1.1.0")
    analysis, _ = analyse(encode(grey({BLOCK: 255}), pnginfo=info))
    assert analysis.embedded_metadata["Software"] == "HydrideSegmentation 1.1.0"
    record = analysis.provenance(source_tool="HydrideSegmentation", remarks="r", confirmed=False,
                                 imported_by="a@b", imported_at="2026-09-15T00:00:00+00:00", tool_version="x")
    for key in ("schema", "file", "file_sha256", "source_tool", "detected_encoding", "file_format",
                "observed_values", "mapping", "normalization", "target_class", "threshold", "warnings",
                "confirmed", "resized", "class_pixels", "remarks"):
        assert key in record, key
    assert record["schema"] == "online-annotator.mask-import/1"
    assert record["resized"] is False and record["threshold"] is None
    assert record["file_format"] == {"format": "PNG", "mode": "L", "dtype": "uint8", "channels": 1,
                                     "width": W, "height": H}


def test_analysis_serialises_for_the_browser():
    import json

    analysis, _ = analyse(encode(ramp()), mode="threshold", threshold=100)
    payload = json.loads(json.dumps(analysis.to_dict()))
    assert payload["kind"] == "threshold" and payload["summary"] and payload["mode_name"] == "Grayscale threshold"
