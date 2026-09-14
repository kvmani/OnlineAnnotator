# Export format — `online-annotator.export/1`

An export is one ZIP file. It can be created by any user, in either working mode, on the project's **Export dataset** tab
(or `POST /api/v1/projects/{id}/exports`) and recorded in the export history with its SHA-256.

## Selection

| `include` | Version exported per image | Use |
| --- | --- | --- |
| `approved` (default) | latest version with status `approved` | ground truth |
| `approved_and_submitted` | latest approved, else latest `submitted` | experiments only |

Images with neither are left out and counted in `manifest.summary.skipped`
(`not_approved`, `no_annotation`). The working copy is **never** exported.

## Layouts

`layout: hydride_pairs` (default) — the input format of HydrideSegmentation's
`prepare_dataset` (`PairCollector`): one flat folder, image and mask side by side.

```
pairs/<stem>.png | .jpg
pairs/<stem>_mask.png
pairs_yolo/<stem>.txt          (only with include_yolo)
coco_annotations.json          (only with include_coco)
manifest.json
README.txt
```

`layout: split_folders` — the layout HydrideSegmentation's dataset preparation *produces* and
most training code expects.

```
train/images/<stem>.png        train/masks/<stem>_mask.png     train/labels/<stem>.txt (YOLO)
val/…                          test/…                           unassigned/… (see below)
```

`<stem>` is the image's unique, sanitised name (`[A-Za-z0-9._-]`); the substring `_mask` is
rewritten to `-mask` at upload so a pairing tool never mistakes an image for a mask. The
original filename is kept in the manifest.

Images: PNG/JPEG originals are exported byte-for-byte; every other format (TIFF, BMP, 16-bit,
palette …) is exported as the 8-bit PNG display copy, and `conversion_note` says how it was made.

## Splits

- `split_mode: assigned` — the split stored on each image (set by selecting images on the Images tab or
  at upload). Images still `unassigned` go to an `unassigned/` folder and the preview warns.
- `split_mode: auto` — deterministic: images are ordered by `SHA-256("<seed>:<image sha256>")`
  and the first `round(n·train/total)` go to train, the next `round(n·val/total)` to val, the rest
  to test. Same seed + same images ⇒ same split.

HydrideSegmentation performs its own seeded split when given `pairs/`; the manifest still records
the split this tool would have used.

## Mask styles

| `mask_style` | Encoding | Classes |
| --- | --- | --- |
| `binary` | 8-bit, 255 = `target_class`, 0 = everything else | one |
| `red` | RGB, (255,0,0) = `target_class`, black elsewhere — satisfies HydrideSegmentation `rgb_mask_mode` (R≥200, G≤60, B≤60) | one |
| `indexed` | 8-bit, pixel = class index, 0 = background | all |
| `colour` | RGB in project class colours, black background | all (for viewing) |

`target_class` defaults to the project's first class.

## COCO (`include_coco`, default on)

`coco_annotations.json`: `categories` = project classes (`id` = class index); `images` with
`file_name` relative to the ZIP root; `annotations` = **one per class per image** (COCO-stuff
style) with `segmentation` as **uncompressed RLE** (`{"size":[h,w],"counts":[...]}`,
column-major, first run counts zeros), `area` = exact pixel count, `bbox` = `[x, y, w, h]` of the
class pixels, `iscrowd: 0`. Decoding the RLE reproduces the label map exactly.

## YOLO segmentation (`include_yolo`, needs OpenCV)

One `.txt` per image, one line per outer contour: `<class index − 1> x1 y1 x2 y2 …` normalised to
[0,1]; `yolo_data.yaml` lists the names. Lossy: holes and sub-pixel detail are not represented.

## `manifest.json`

```json
{
  "schema": "online-annotator.export/1",
  "tool": {"id": "online-annotator", "version": "1.0.0"},
  "project": {"id": 1, "name": "…", "description": "…"},
  "created_at": "2026-09-11T17:35:15+00:00",
  "created_by": "riya@lab.example",
  "options": {"layout": "hydride_pairs", "mask_style": "binary", "target_class": 1, "include": "approved",
              "split_mode": "assigned", "train": 0.8, "val": 0.1, "test": 0.1, "seed": 42,
              "include_coco": true, "include_yolo": false, "extra": {}},
  "mask_encoding": "binary PNG, 255 = Hydride, 0 = everything else",
  "classes": [{"index": 1, "name": "Hydride", "color": "#FF0000", "description": "…"}],
  "background_value": 0,
  "summary": {"images": 12, "splits": {"train": 10, "val": 1, "test": 1},
              "skipped": {"not_approved": 3, "no_annotation": 5}},
  "images": [{
    "stem": "sample_01", "original_filename": "sample 01.tif",
    "image_file": "pairs/sample_01.png", "mask_file": "pairs/sample_01_mask.png",
    "split": "train", "width": 640, "height": 480,
    "image_sha256": "…", "original_sha256": "…", "mask_png_sha256": "…", "label_sha256": "…",
    "conversion_note": "",
    "version": 2, "version_status": "approved", "version_kind": "reviewer_edit",
    "mask_source": "imported", "mask_source_tool": "HydrideSegmentation v2.3",
    "mask_source_file": "sample_01_mask.png",
    "mask_source_remarks": "Model run of 2026-09-10; misses faint tips near grain boundaries.",
    "annotated_by": "riya@lab.example", "annotated_at": "…+00:00",
    "contributors": ["arun@lab.example", "riya@lab.example"],
    "approved_by": "riya@lab.example", "approved_at": "…+00:00",
    "class_pixels": {"1": 1726, "2": 150}, "class_fractions": {"1": 0.005618, "2": 0.000488}
  }]
}
```

`mask_source` says where the ground truth started: `"manual"` for labels drawn from scratch in
Online Annotator, `"imported"` when an externally produced mask (another segmentation tool, an
in-house script, a model prediction) was loaded and then corrected by hand.
`mask_source_tool`, `mask_source_file` and `mask_source_remarks` are what the importing user
recorded about it; all three are empty strings for `"manual"`. The value is frozen when the
version is created and never changes afterwards, and hand-correcting an imported mask does not
make it `"manual"` — so a training pipeline can weight, audit or exclude corrected machine
output separately from labels drawn from scratch.

`label_sha256` hashes the label values themselves (`"<w>x<h>:"` + raw bytes), independent of PNG
encoder settings, and equals the version's `mask_sha256` in the application database.

## Using an export with HydrideSegmentation

```yaml
# configs/hydride/prepare_dataset.*.yml
input_dir: /path/to/unzipped/pairs
rgb_mask_mode: false          # true if exported with mask_style: red
mask_foreground_value: 255
mask_name_patterns: ["{stem}_mask.png"]
```

## Compatibility promise

`version_kind` is `submission` for labels exactly as submitted, or `reviewer_edit` when the person
reviewing corrected the labels before approving them. The stored value names the kind of edit,
not a role: since 2.0.0 every user can both annotate and review (never their own submission), and
`contributors` lists everyone whose labels are in the exported version.

Additive fields may appear in a minor release. Renaming or removing a field, changing a layout
or an encoding requires `schema` → `online-annotator.export/2`, a major version bump and a
CHANGELOG entry.
