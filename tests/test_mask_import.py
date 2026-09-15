"""Importing an externally produced mask, correcting it, and keeping that provenance.

People often already have a mask for a micrograph -- from another segmentation tool,
an in-house script or a model prediction. They import it and fix its mistakes rather than
labelling from scratch. What must never be lost is that the ground truth *started* as
machine output: every version and every export has to say so.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from .conftest import get_labels, png_bytes, put_labels, set_mode, upload


def import_mask(client, image_id, arr, *, name="sample one_mask.png", import_class=1,
                source_tool="HydrideSegmentation v2.3", remarks="Misses faint tips."):
    return client.post(
        f"/api/v1/images/{image_id}/mask-import",
        files=[("file", (name, png_bytes(arr), "image/png"))],
        data={"import_class": str(import_class), "source_tool": source_tool, "remarks": remarks},
    )


def binary_mask(width=64, height=48):
    arr = np.zeros((height, width), dtype=np.uint8)
    arr[10:14, 5:50] = 255
    return arr


# --------------------------------------------------------------------------- the happy path
def test_import_binary_mask_becomes_the_working_copy(alice, image_id):
    r = import_mask(alice, image_id, binary_mask())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "binary"

    labels = get_labels(alice, image_id).reshape(48, 64)
    assert (labels[10:14, 5:50] == 1).all()
    assert labels.sum() == 4 * 45  # exactly the foreground, nothing invented elsewhere

    img = body["image"]
    assert img["status"] == "in_progress"
    assert img["mask_source"] == "imported"
    assert img["mask_source_tool"] == "HydrideSegmentation v2.3"
    assert img["mask_source_remarks"] == "Misses faint tips."
    assert img["mask_source_file"] == "sample one_mask.png"
    assert img["mask_imported_by"] == "alice@lab.test"
    assert img["mask_imported_at"]
    assert "Imported from sample one_mask.png" in img["mask_source_description"]


def test_indexed_multiclass_mask_keeps_every_class(alice, image_id):
    arr = np.zeros((48, 64), dtype=np.uint8)
    arr[0:5, 0:5] = 1
    arr[20:25, 20:25] = 2
    r = import_mask(alice, image_id, arr, name="sample one.png")
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "indexed"
    labels = get_labels(alice, image_id).reshape(48, 64)
    assert (labels[0:5, 0:5] == 1).all() and (labels[20:25, 20:25] == 2).all()


def test_exact_class_colours_are_read_as_those_classes(alice, image_id):
    """Pure red is the Hydride colour in this project, so the colour path claims it."""
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[5:9, 5:9] = (255, 0, 0)    # class 1, Hydride
    rgb[20:24, 20:24] = (0, 0, 255)  # class 2, Pore
    r = alice.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("m.png", png_bytes(rgb), "image/png"))],
                 data={"import_class": "2", "source_tool": "", "remarks": ""})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "colour"
    labels = get_labels(alice, image_id).reshape(48, 64)
    assert (labels[5:9, 5:9] == 1).all()
    assert (labels[20:24, 20:24] == 2).all()


def test_red_dominant_mask_maps_to_the_chosen_class(alice, image_id):
    """The HydrideSegmentation convention: red-ish, not exactly a class colour."""
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[5:9, 5:9] = (220, 30, 30)
    r = alice.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("m.png", png_bytes(rgb), "image/png"))],
                 data={"import_class": "2", "source_tool": "", "remarks": ""})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "red-dominant"
    labels = get_labels(alice, image_id).reshape(48, 64)
    assert (labels[5:9, 5:9] == 2).all()


# ------------------------------------------------------------------- refusing to guess
def test_wrong_size_mask_is_refused_not_resized(alice, image_id):
    r = import_mask(alice, image_id, binary_mask(width=32, height=24))
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "does not match the image" in detail
    assert "never resized" in detail
    # the working copy is untouched
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "manual"


def test_mask_with_unknown_grey_values_is_refused(alice, image_id):
    arr = np.full((48, 64), 77, dtype=np.uint8)
    r = import_mask(alice, image_id, arr)
    assert r.status_code == 400
    detail = r.json()["detail"]
    # The refusal names the value, the project's classes and what to do next.
    assert "77" in detail and "not a class number" in detail and "Grayscale threshold" in detail
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "manual"


def test_unreadable_file_is_refused_with_a_plain_message(alice, image_id):
    r = alice.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("notes.png", b"this is not a png", "image/png"))],
                 data={"import_class": "1"})
    assert r.status_code == 400
    assert "not a readable image" in r.json()["detail"]


# -------------------------------------------------------------- provenance is traceable
def test_correcting_an_imported_mask_keeps_it_imported(alice, image_id):
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    revision = alice.get(f"/api/v1/images/{image_id}").json()["image"]["working_revision"]

    corrected = np.zeros((48, 64), dtype=np.uint8)
    corrected[10:14, 5:60] = 1  # the user extends the hydride
    assert put_labels(alice, image_id, corrected, revision).status_code == 200

    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "imported", "hand-correction must not erase the import record"
    assert img["mask_source_tool"] == "HydrideSegmentation v2.3"


def test_submitted_version_freezes_the_provenance(alice, image_id):
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={"note": "corrected"}).status_code == 200

    version = alice.get(f"/api/v1/images/{image_id}").json()["image"]["versions"][0]
    assert version["mask_source"] == "imported"
    assert version["mask_source_tool"] == "HydrideSegmentation v2.3"
    assert version["mask_source_remarks"] == "Misses faint tips."
    assert version["mask_source_file"] == "sample one_mask.png"


def test_a_hand_drawn_image_stays_manual(alice, image_id):
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(alice, image_id, labels, 0).status_code == 200
    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "manual"
    assert img["mask_source_description"] == "Drawn in Online Annotator."


def test_restoring_a_manual_version_restores_manual_provenance(alice, image_id):
    # v1 is hand drawn and submitted
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(alice, image_id, labels, 0).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={"note": "v1"}).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/withdraw", json={}).status_code == 200
    # then a mask is imported over the top
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "imported"
    # restoring the hand-drawn version brings its provenance back with its pixels
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200  # submitting released it
    assert alice.post(f"/api/v1/images/{image_id}/restore/1").status_code == 200
    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "manual"
    assert img["mask_source_tool"] == ""


# ----------------------------------------------------------------------- remarks editing
def test_remarks_can_be_corrected_afterwards(alice, image_id):
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    r = alice.patch(f"/api/v1/images/{image_id}/mask-source",
                  json={"source_tool": "HydrideSegmentation v2.4", "remarks": "Re-run with the fixed threshold."})
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    assert img["mask_source_tool"] == "HydrideSegmentation v2.4"
    assert img["mask_source_remarks"] == "Re-run with the fixed threshold."


def test_remarks_are_refused_on_a_hand_drawn_image(alice, image_id):
    r = alice.patch(f"/api/v1/images/{image_id}/mask-source", json={"remarks": "invented"})
    assert r.status_code >= 400
    assert "not imported" in r.json()["detail"]


# ------------------------------------------------------------------------ workflow rules
def test_an_approved_image_is_never_overwritten_by_an_import(alice, bob, image_id):
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(alice, image_id, labels, 0).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={"note": ""}).status_code == 200
    set_mode(bob, "review")
    assert bob.post(f"/api/v1/images/{image_id}/review",
                    json={"decision": "approve", "comment": "good"}).status_code == 200

    r = import_mask(alice, image_id, binary_mask())
    assert r.status_code >= 400
    assert "approved" in r.json()["detail"]


def test_import_is_refused_while_someone_else_holds_the_lease(alice, bob, image_id):
    assert bob.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    r = import_mask(alice, image_id, binary_mask())
    assert r.status_code >= 400
    assert "being edited by" in r.json()["detail"]


def test_import_is_recorded_in_the_audit_trail(alice, image_id, project_id):
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    events = alice.get(f"/api/v1/projects/{project_id}/activity").json()["events"]
    entry = next(e for e in events if e["action"] == "mask_imported")
    assert entry["user_email"] == "alice@lab.test"
    assert entry["details"]["source_tool"] == "HydrideSegmentation v2.3"
    assert entry["details"]["remarks"] == "Misses faint tips."


# ------------------------------------------------------------------------- bulk import
def test_bulk_import_records_the_same_provenance(alice, project_id, image_id):
    r = alice.post(
        f"/api/v1/projects/{project_id}/masks",
        files=[("files", ("sample one_mask.png", png_bytes(binary_mask()), "image/png"))],
        data={"import_class": "1", "source_tool": "in-house script", "remarks": "batch of 2026-09-12"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] and not r.json()["errors"]
    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "imported"
    assert img["mask_source_tool"] == "in-house script"
    assert img["mask_source_remarks"] == "batch of 2026-09-12"


# ----------------------------------------------------------------------- export manifest
def test_export_manifest_reports_the_mask_source(alice, bob, admin, project_id, image_id):
    assert import_mask(alice, image_id, binary_mask()).status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={"note": "corrected"}).status_code == 200
    set_mode(bob, "review")
    assert bob.post(f"/api/v1/images/{image_id}/review",
                    json={"decision": "approve", "comment": "ok"}).status_code == 200

    created = admin.post(f"/api/v1/projects/{project_id}/exports", json={"target_class": 1})
    assert created.status_code == 200, created.text
    export_id = created.json()["export"]["id"]
    blob = admin.get(f"/api/v1/exports/{export_id}/download").content
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    record = manifest["images"][0]
    assert record["mask_source"] == "imported"
    assert record["mask_source_tool"] == "HydrideSegmentation v2.3"
    assert record["mask_source_file"] == "sample one_mask.png"
    assert record["mask_source_remarks"] == "Misses faint tips."


# --------------------------------------------------------------- interpretation, end to end
def analyze(client, image_id, arr, **data):
    return client.post(f"/api/v1/images/{image_id}/mask-import/analyze",
                       files=[("file", ("m.png", png_bytes(arr), "image/png"))],
                       data={k: str(v) for k, v in data.items()})


def test_analyze_describes_the_file_and_changes_nothing(alice, image_id):
    r = analyze(alice, image_id, binary_mask(), import_class=2)
    assert r.status_code == 200, r.text
    analysis = r.json()["analysis"]
    assert analysis["detected"] == "binary_0_255" and analysis["ok"] and not analysis["requires_confirmation"]
    assert analysis["mapping"][0] == {"source": "255", "class_index": 2, "target": "class 2 Pore", "pixels": 180}
    assert any("nothing is resized" in line for line in analysis["summary"])
    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "manual" and img["working_revision"] == 0


def test_ambiguous_two_value_mask_needs_confirmation(alice, image_id):
    arr = np.zeros((48, 64), dtype=np.uint8)
    arr[10:14, 5:50] = 128
    refused = import_mask(alice, image_id, arr)
    assert refused.status_code == 409
    assert "only 0 and 128" in refused.json()["detail"] and "Nothing was imported" in refused.json()["detail"]
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "manual"

    r = alice.post(f"/api/v1/images/{image_id}/mask-import",
                   files=[("file", ("m.png", png_bytes(arr), "image/png"))],
                   data={"import_class": "1", "confirm": "true"})
    assert r.status_code == 200, r.text
    assert get_labels(alice, image_id).reshape(48, 64).sum() == 180
    details = r.json()["image"]["mask_import"]
    assert details["detected_encoding"] == "binary_like" and details["confirmed"] is True


def test_many_level_greyscale_imports_only_with_an_explicit_confirmed_threshold(alice, image_id):
    ramp = np.tile(np.linspace(0, 255, 64).astype(np.uint8), (48, 1))
    auto = import_mask(alice, image_id, ramp)
    assert auto.status_code == 400 and "Grayscale threshold" in auto.json()["detail"]

    data = {"mode": "threshold", "threshold": "128", "import_class": "2"}
    unconfirmed = alice.post(f"/api/v1/images/{image_id}/mask-import",
                             files=[("file", ("prob.png", png_bytes(ramp), "image/png"))], data=data)
    assert unconfirmed.status_code == 409
    r = alice.post(f"/api/v1/images/{image_id}/mask-import",
                   files=[("file", ("prob.png", png_bytes(ramp), "image/png"))], data=data | {"confirm": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "threshold"
    labels = get_labels(alice, image_id).reshape(48, 64)
    assert np.array_equal(labels, np.where(ramp >= 128, 2, 0).astype(np.uint8))
    details = r.json()["image"]["mask_import"]
    assert details["threshold"] == 128 and details["requested_mode"] == "threshold"
    assert details["target_class"] == 2 and details["class_pixels"] == {"2": int((ramp >= 128).sum())}


def test_provenance_is_recorded_in_image_version_audit_and_manifest(alice, bob, admin, project_id, image_id):
    assert import_mask(alice, image_id, binary_mask(), import_class=2).status_code == 200
    img = alice.get(f"/api/v1/images/{image_id}").json()["image"]
    details = img["mask_import"]
    assert details["schema"] == "online-annotator.mask-import/1"
    assert details["file"] == "sample one_mask.png" and len(details["file_sha256"]) == 64
    assert details["source_tool"] == "HydrideSegmentation v2.3" and details["remarks"] == "Misses faint tips."
    assert details["detected_encoding"] == "binary_0_255" and details["observed_values"] == [0, 255]
    assert details["mapping"][0]["source"] == "255" and details["target_class"] == 2
    assert "Binary normalization" in details["normalization"] and details["resized"] is False
    assert details["imported_by"] == "alice@lab.test"

    events = alice.get(f"/api/v1/projects/{project_id}/activity").json()["events"]
    entry = next(e for e in events if e["action"] == "mask_imported")
    assert entry["details"]["interpretation"]["detected_encoding"] == "binary_0_255"

    # Remarks edited later stay consistent with the interpretation record.
    alice.patch(f"/api/v1/images/{image_id}/mask-source", json={"remarks": "re-run"})
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_import"]["remarks"] == "re-run"

    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert alice.post(f"/api/v1/images/{image_id}/submit", json={"note": ""}).status_code == 200
    version = alice.get(f"/api/v1/images/{image_id}").json()["image"]["versions"][0]
    assert version["mask_import"]["detected_encoding"] == "binary_0_255"
    set_mode(bob, "review")
    assert bob.post(f"/api/v1/images/{image_id}/review",
                    json={"decision": "approve", "comment": ""}).status_code == 200
    created = admin.post(f"/api/v1/projects/{project_id}/exports", json={"target_class": 2})
    blob = admin.get(f"/api/v1/exports/{created.json()['export']['id']}/download").content
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        record = json.loads(zf.read("manifest.json"))["images"][0]
    assert record["mask_import"]["mapping"][0]["target"] == "class 2 Pore"
    assert record["mask_import"]["file_sha256"] == details["file_sha256"]


def test_a_hand_drawn_image_has_no_import_record(alice, image_id):
    assert alice.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(alice, image_id, labels, 0).status_code == 200
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_import"] is None


CASES = {
    "binary_255": binary_mask(),
    "binary_128": np.where(binary_mask() > 0, 128, 0).astype(np.uint8),
    "indexed_0_2": np.where(binary_mask() > 0, 2, 0).astype(np.uint8),
    "unknown_7": np.where(binary_mask() > 0, 7, 1).astype(np.uint8),
    "ramp": np.tile(np.linspace(0, 255, 64).astype(np.uint8), (48, 1)),
    "wrong_size": binary_mask(width=32, height=24),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_single_and_bulk_import_read_every_file_identically(alice, project_id, case):
    """The same file, sent through both doors, gives the same analysis, outcome and labels."""
    single_id = upload(alice, project_id, name="single.png", seed=1)
    bulk_id = upload(alice, project_id, name="bulk.png", seed=2)
    arr = CASES[case]

    preview_single = analyze(alice, single_id, arr, import_class=2).json()["analysis"]
    preview_bulk = alice.post(f"/api/v1/projects/{project_id}/masks/analyze",
                              files=[("files", ("bulk_mask.png", png_bytes(arr), "image/png"))],
                              data={"import_class": "2"}).json()["results"][0]["analysis"]
    comparable = ("detected", "ok", "requires_confirmation", "mapping", "class_pixels", "warnings",
                  "normalization", "error", "observed_values")
    assert {k: preview_single[k] for k in comparable} == {k: preview_bulk[k] for k in comparable}

    single = alice.post(f"/api/v1/images/{single_id}/mask-import",
                        files=[("file", ("single_mask.png", png_bytes(arr), "image/png"))],
                        data={"import_class": "2"})
    bulk = alice.post(f"/api/v1/projects/{project_id}/masks",
                      files=[("files", ("bulk_mask.png", png_bytes(arr), "image/png"))],
                      data={"import_class": "2"}).json()
    assert (single.status_code == 200) == bool(bulk["imported"])
    if single.status_code == 200:
        assert np.array_equal(get_labels(alice, single_id), get_labels(alice, bulk_id))
        assert bulk["results"][0]["status"] == "imported"
    else:
        assert bulk["results"][0]["status"] in ("refused", "needs_confirmation")
        assert single.json()["detail"].split(": ", 1)[1] == bulk["errors"][0].split(": ", 1)[1]


def test_bulk_import_confirms_ambiguous_files_only_when_asked(alice, project_id, image_id):
    arr = np.where(binary_mask() > 0, 128, 0).astype(np.uint8)
    files = [("files", ("sample one_mask.png", png_bytes(arr), "image/png"))]
    first = alice.post(f"/api/v1/projects/{project_id}/masks", files=files).json()
    assert not first["imported"] and first["results"][0]["status"] == "needs_confirmation"
    assert alice.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "manual"
    second = alice.post(f"/api/v1/projects/{project_id}/masks", files=files, data={"confirm": "true"}).json()
    assert second["imported"] and get_labels(alice, image_id).sum() == 180


def test_bulk_import_pairs_hydride_segmentation_label_and_preview_names(alice, project_id, image_id):
    labels01 = (binary_mask() > 0).astype(np.uint8)
    r = alice.post(f"/api/v1/projects/{project_id}/masks",
                   files=[("files", ("sample one_mask_labels.png", png_bytes(labels01), "image/png"))]).json()
    assert r["errors"] == [] and r["results"][0]["image_id"] == image_id
    preview = alice.post(f"/api/v1/projects/{project_id}/masks/analyze",
                         files=[("files", ("sample one_mask_preview.png", png_bytes(binary_mask()), "image/png"))])
    assert preview.json()["results"][0]["status"] == "ready"
