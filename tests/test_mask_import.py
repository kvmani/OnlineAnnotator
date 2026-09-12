"""Importing an externally produced mask, correcting it, and keeping that provenance.

Annotators often already have a mask for a micrograph -- from another segmentation tool,
an in-house script or a model prediction. They import it and fix its mistakes rather than
labelling from scratch. What must never be lost is that the ground truth *started* as
machine output: every version and every export has to say so.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np

from .conftest import get_labels, png_bytes, put_labels


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
def test_import_binary_mask_becomes_the_working_copy(ann, image_id):
    r = import_mask(ann, image_id, binary_mask())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "binary"

    labels = get_labels(ann, image_id).reshape(48, 64)
    assert (labels[10:14, 5:50] == 1).all()
    assert labels.sum() == 4 * 45  # exactly the foreground, nothing invented elsewhere

    img = body["image"]
    assert img["status"] == "in_progress"
    assert img["mask_source"] == "imported"
    assert img["mask_source_tool"] == "HydrideSegmentation v2.3"
    assert img["mask_source_remarks"] == "Misses faint tips."
    assert img["mask_source_file"] == "sample one_mask.png"
    assert img["mask_imported_by"] == "ann@lab.test"
    assert img["mask_imported_at"]
    assert "Imported from sample one_mask.png" in img["mask_source_description"]


def test_indexed_multiclass_mask_keeps_every_class(ann, image_id):
    arr = np.zeros((48, 64), dtype=np.uint8)
    arr[0:5, 0:5] = 1
    arr[20:25, 20:25] = 2
    r = import_mask(ann, image_id, arr, name="sample one.png")
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "indexed"
    labels = get_labels(ann, image_id).reshape(48, 64)
    assert (labels[0:5, 0:5] == 1).all() and (labels[20:25, 20:25] == 2).all()


def test_exact_class_colours_are_read_as_those_classes(ann, image_id):
    """Pure red is the Hydride colour in this project, so the colour path claims it."""
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[5:9, 5:9] = (255, 0, 0)    # class 1, Hydride
    rgb[20:24, 20:24] = (0, 0, 255)  # class 2, Pore
    r = ann.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("m.png", png_bytes(rgb), "image/png"))],
                 data={"import_class": "2", "source_tool": "", "remarks": ""})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "colour"
    labels = get_labels(ann, image_id).reshape(48, 64)
    assert (labels[5:9, 5:9] == 1).all()
    assert (labels[20:24, 20:24] == 2).all()


def test_red_dominant_mask_maps_to_the_chosen_class(ann, image_id):
    """The HydrideSegmentation convention: red-ish, not exactly a class colour."""
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[5:9, 5:9] = (220, 30, 30)
    r = ann.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("m.png", png_bytes(rgb), "image/png"))],
                 data={"import_class": "2", "source_tool": "", "remarks": ""})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "red-dominant"
    labels = get_labels(ann, image_id).reshape(48, 64)
    assert (labels[5:9, 5:9] == 2).all()


# ------------------------------------------------------------------- refusing to guess
def test_wrong_size_mask_is_refused_not_resized(ann, image_id):
    r = import_mask(ann, image_id, binary_mask(width=32, height=24))
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "does not match the image" in detail
    assert "never resized" in detail
    # the working copy is untouched
    assert ann.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "manual"


def test_mask_with_unknown_grey_values_is_refused(ann, image_id):
    arr = np.full((48, 64), 77, dtype=np.uint8)
    r = import_mask(ann, image_id, arr)
    assert r.status_code == 400
    assert "neither class indices" in r.json()["detail"]


def test_unreadable_file_is_refused_with_a_plain_message(ann, image_id):
    r = ann.post(f"/api/v1/images/{image_id}/mask-import",
                 files=[("file", ("notes.png", b"this is not a png", "image/png"))],
                 data={"import_class": "1"})
    assert r.status_code == 400
    assert "not a readable image" in r.json()["detail"]


# -------------------------------------------------------------- provenance is traceable
def test_correcting_an_imported_mask_keeps_it_imported(ann, image_id):
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    revision = ann.get(f"/api/v1/images/{image_id}").json()["image"]["working_revision"]

    corrected = np.zeros((48, 64), dtype=np.uint8)
    corrected[10:14, 5:60] = 1  # the annotator extends the hydride
    assert put_labels(ann, image_id, corrected, revision).status_code == 200

    img = ann.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "imported", "hand-correction must not erase the import record"
    assert img["mask_source_tool"] == "HydrideSegmentation v2.3"


def test_submitted_version_freezes_the_provenance(ann, image_id):
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/submit", json={"note": "corrected"}).status_code == 200

    version = ann.get(f"/api/v1/images/{image_id}").json()["image"]["versions"][0]
    assert version["mask_source"] == "imported"
    assert version["mask_source_tool"] == "HydrideSegmentation v2.3"
    assert version["mask_source_remarks"] == "Misses faint tips."
    assert version["mask_source_file"] == "sample one_mask.png"


def test_a_hand_drawn_image_stays_manual(ann, image_id):
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(ann, image_id, labels, 0).status_code == 200
    img = ann.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "manual"
    assert img["mask_source_description"] == "Drawn in Online Annotator."


def test_restoring_a_manual_version_restores_manual_provenance(ann, image_id):
    # v1 is hand drawn and submitted
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(ann, image_id, labels, 0).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/submit", json={"note": "v1"}).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/withdraw", json={}).status_code == 200
    # then a mask is imported over the top
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    assert ann.get(f"/api/v1/images/{image_id}").json()["image"]["mask_source"] == "imported"
    # restoring the hand-drawn version brings its provenance back with its pixels
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200  # submitting released it
    assert ann.post(f"/api/v1/images/{image_id}/restore/1").status_code == 200
    img = ann.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "manual"
    assert img["mask_source_tool"] == ""


# ----------------------------------------------------------------------- remarks editing
def test_remarks_can_be_corrected_afterwards(ann, image_id):
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    r = ann.patch(f"/api/v1/images/{image_id}/mask-source",
                  json={"source_tool": "HydrideSegmentation v2.4", "remarks": "Re-run with the fixed threshold."})
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    assert img["mask_source_tool"] == "HydrideSegmentation v2.4"
    assert img["mask_source_remarks"] == "Re-run with the fixed threshold."


def test_remarks_are_refused_on_a_hand_drawn_image(ann, image_id):
    r = ann.patch(f"/api/v1/images/{image_id}/mask-source", json={"remarks": "invented"})
    assert r.status_code >= 400
    assert "not imported" in r.json()["detail"]


# ------------------------------------------------------------------------ workflow rules
def test_an_approved_image_is_never_overwritten_by_an_import(ann, rev, image_id):
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    labels = np.zeros((48, 64), dtype=np.uint8)
    labels[0:4, 0:4] = 1
    assert put_labels(ann, image_id, labels, 0).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/submit", json={"note": ""}).status_code == 200
    assert rev.post(f"/api/v1/images/{image_id}/review",
                    json={"decision": "approve", "comment": "good"}).status_code == 200

    r = import_mask(ann, image_id, binary_mask())
    assert r.status_code >= 400
    assert "approved" in r.json()["detail"]


def test_import_is_refused_while_someone_else_holds_the_lease(ann, rev, image_id):
    assert rev.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    r = import_mask(ann, image_id, binary_mask())
    assert r.status_code >= 400
    assert "being edited by" in r.json()["detail"]


def test_import_is_recorded_in_the_audit_trail(ann, image_id, project_id):
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    events = ann.get(f"/api/v1/projects/{project_id}/activity").json()["events"]
    entry = next(e for e in events if e["action"] == "mask_imported")
    assert entry["user_email"] == "ann@lab.test"
    assert entry["details"]["source_tool"] == "HydrideSegmentation v2.3"
    assert entry["details"]["remarks"] == "Misses faint tips."


# ------------------------------------------------------------------------- bulk import
def test_bulk_import_records_the_same_provenance(ann, project_id, image_id):
    r = ann.post(
        f"/api/v1/projects/{project_id}/masks",
        files=[("files", ("sample one_mask.png", png_bytes(binary_mask()), "image/png"))],
        data={"import_class": "1", "source_tool": "in-house script", "remarks": "batch of 2026-09-12"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] and not r.json()["errors"]
    img = ann.get(f"/api/v1/images/{image_id}").json()["image"]
    assert img["mask_source"] == "imported"
    assert img["mask_source_tool"] == "in-house script"
    assert img["mask_source_remarks"] == "batch of 2026-09-12"


# ----------------------------------------------------------------------- export manifest
def test_export_manifest_reports_the_mask_source(ann, rev, admin, project_id, image_id):
    assert import_mask(ann, image_id, binary_mask()).status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/lock").status_code == 200
    assert ann.post(f"/api/v1/images/{image_id}/submit", json={"note": "corrected"}).status_code == 200
    assert rev.post(f"/api/v1/images/{image_id}/review",
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


# ------------------------------------------------------------------- schema migration
def test_schema_2_adds_the_columns_to_an_existing_database(tmp_path):
    """A database written by 1.0.x must gain the provenance columns, not be recreated."""
    import sqlite3

    from sqlalchemy import text

    from online_annotator.db import SCHEMA_VERSION, init_schema, make_engine

    url = f"sqlite:///{tmp_path / 'oa.db'}"
    engine = make_engine(url)
    init_schema(engine)
    engine.dispose()

    # Rewind to what release 1.0.1 stored: no provenance columns, schema version 1.
    new_columns = ["mask_source", "mask_source_tool", "mask_source_remarks", "mask_source_file",
                   "mask_imported_by", "mask_imported_at"]
    with sqlite3.connect(tmp_path / "oa.db") as conn:
        for column in new_columns:
            conn.execute(f"ALTER TABLE images DROP COLUMN {column}")
        for column in new_columns[:4]:
            conn.execute(f"ALTER TABLE versions DROP COLUMN {column}")
        conn.execute("PRAGMA user_version=1")
        conn.commit()

    engine = make_engine(url)
    init_schema(engine)
    with engine.begin() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == SCHEMA_VERSION
        images = {row[1] for row in conn.execute(text("PRAGMA table_info(images)"))}
        versions = {row[1] for row in conn.execute(text("PRAGMA table_info(versions)"))}
    assert set(new_columns) <= images
    assert set(new_columns[:4]) <= versions
    engine.dispose()


def test_migration_is_idempotent(tmp_path):
    from online_annotator.db import init_schema, make_engine

    url = f"sqlite:///{tmp_path / 'oa.db'}"
    for _ in range(3):
        engine = make_engine(url)
        init_schema(engine)  # must not raise "duplicate column name"
        engine.dispose()
