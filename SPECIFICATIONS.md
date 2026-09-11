# SPECIFICATIONS — Online Annotator

Version 1.0 of the product specification. Behaviour described here is implemented and tested;
changes follow the contract rules in `AGENTS.md`.

## 1. Purpose and scope

Online Annotator lets a team on an office intranet **create, review and export
semantic-segmentation ground truth** for microstructure images (optical, SEM, TEM …).

In scope:
- pixel-exact labelling of one or more classes per project, with assisted tools;
- a two-person review workflow producing immutable, approved versions;
- multi-user operation with exclusive editing leases;
- import of model predictions as pre-annotations (active-learning loop);
- export of approved data in HydrideSegmentation, split-folder, COCO and YOLO forms with a
  provenance manifest;
- self-explanatory UI with inline help and an in-app Help centre.

Out of scope (v1): instance segmentation IDs, 3-D stacks, video, bounding-box detection
labelling, model training or inference inside this tool, external identity providers.

## 2. Users and roles

| Role | Can |
| --- | --- |
| annotator | view projects; upload images; import pre-annotation masks; annotate (with a lease); submit; withdraw own submission |
| reviewer | everything an annotator can, plus approve / request changes, correct during review, set splits and assignments, export |
| admin | everything, plus create/edit/archive projects, manage classes and guidelines, manage users, delete images, break locks |

Identity is the office e-mail address. Accounts are created by an administrator (temporary
password, must be changed at first sign-in) or, only when `self_registration` is enabled
together with an SMTP relay and optionally `allowed_email_domains`, by e-mail code.

## 3. Core concepts

- **Project**: a dataset — images, classes (`index` 1..255, name, colour, description) and
  written annotation guidelines. Class indices never change once used; names/colours can.
- **Image**: the stored original (byte-identical, SHA-256 identity, deduplicated per
  project), a display copy when needed, a thumbnail, a unique export `stem`, a split
  (`unassigned|train|val|test`), an optional assignee, notes, and a status.
- **Label map**: `uint8[height, width]`; 0 = background; values = class indices.
- **Working copy**: the current label map of an image (`working_revision` increments on every
  save).
- **Version**: an immutable snapshot (PNG + label SHA-256 + class pixel counts), created on
  submission or on approval of reviewer corrections.
- **Lease (lock)**: exclusive right to edit one image, `lock_lease_seconds` long (default 300 s),
  renewed by the browser every lease/3 while the image is open, released on leave.

## 4. Workflow

```
new ──save──▶ in_progress ──submit──▶ submitted ──approve──▶ approved
                 ▲    ▲                  │  │                   │
                 │    └─────withdraw─────┘  └─request changes─▶ changes_requested
                 └───────────save (re-opens an approved image)───┘       │
                                                              submit ◀────┘
```

Server-enforced rules:
1. Saving labels requires the caller's live lease and the `base_revision` the edit started
   from; otherwise `423` (lease) or `409` (stale revision) with an actionable message.
2. Only reviewers edit a `submitted` image; annotators must withdraw first.
3. Submitting requires at least one save; it releases the submitter's lease.
4. `request_changes` requires a comment.
5. Nobody approves a submission they made unless `allow_self_approval: true`.
6. If the reviewer changed the working copy, approval snapshots the corrected labels as a new
   `reviewer_edit` version (approved) and marks the submission `superseded`.
7. Editing an approved image returns it to `in_progress`; its approved version stays in history
   and remains the one exported until a newer one is approved.
8. Restoring a version copies it into the working copy (history unchanged).

"Annotate next" order: my returned work → my work in progress → new images assigned to me →
new unassigned images → returned unassigned images, skipping images leased by others.
"Review next": oldest submissions by others first.

## 5. Browser application

- Hash-routed single page, vanilla ES modules, no external assets; relative URLs so it also
  runs behind a path prefix.
- **Projects dashboard** with a dismissible "How it works" quick start.
- **Project page**: status summary with help, Images (filters, search, lock indicators,
  reviewer bulk split/assign, upload with drag-and-drop and progress, mask import), Classes &
  guidelines, Export dataset (reviewers), Activity, Settings (admin).
- **Workspace**: tools Pan (V), Brush (B), Eraser (E), Polygon (P), Lasso (L), Magic wand (W),
  Box threshold (T), Fill (G); Shift erases with any tool; Alt+click picks a class; keys 1–9
  select classes; `[`/`]` brush size; undo/redo (patch-based, ≥100 steps); zoom at cursor,
  Space/middle/right-drag pan; fit (F); show/hide labels (H); outlines (O); brightness,
  contrast, invert (display only); protect-other-classes mode; speck removal and hole filling;
  live per-class coverage; hint bar for the active tool; banners for every lease and review
  state; autosave 2.5 s after the last edit, manual save Ctrl+S, visible save state; version
  history with restore and mask download; guidelines panel; collapsible side panel.
- **Magic wand**: classifies the seed as dark/bright against its 31×31 neighbourhood mean and
  grows 4-connected over pixels at least as dark (bright) as the seed plus `tolerance`; refuses
  regions over 25 % of the image.
- **Box threshold**: Otsu threshold of the box's grey levels, dark/bright choice, speck
  filter, live preview, apply/cancel.
- **Help**: `(?)` popovers at decisions, Help centre (`#/help`, also `/help`), keyboard sheet (`?`).

## 6. HTTP API (`/api/v1`, JSON unless stated)

All mutating requests need header `X-Requested-With: OnlineAnnotator`; the session is an
HttpOnly cookie (or `Authorization: Bearer <token>`).

| Method & path | Purpose | Role |
| --- | --- | --- |
| GET `/api/health`, `/health` | `{"status":"ok","tool_id":"online-annotator","version"}` | public |
| GET `/api/health/deep` | database and storage check | public |
| GET `/meta` | version, limits, feature flags, portal/feedback URLs | public |
| GET `/auth/options`; POST `/auth/login`, `/auth/logout`, `/auth/change-password`; GET `/auth/me` | sessions | — |
| POST `/auth/otp/request`, `/auth/otp/verify` | e-mail code sign-in (only with SMTP) | — |
| GET/POST `/users`; PATCH `/users/{id}`; POST `/users/{id}/reset-password` | accounts | admin (GET: any) |
| GET/POST `/projects`; GET/PATCH `/projects/{id}` | projects | POST/PATCH admin |
| POST/PATCH/DELETE `/projects/{id}/classes[/{cid}]` | classes (delete only if unused) | admin |
| GET/POST `/projects/{id}/images` | list / multipart upload (`files`, `split`) | any |
| POST `/projects/{id}/images/bulk` | split / assignment for many images | reviewer |
| GET `/projects/{id}/next?mode=annotate|review&after=` | next image id | any / reviewer |
| POST `/projects/{id}/masks` | import pre-annotation masks (`files`, `import_class`) | any |
| GET `/projects/{id}/activity`, `/projects/{id}/summary` | audit trail; approved class fractions | any |
| POST `/projects/{id}/exports/preview`, `/projects/{id}/exports`; GET `/projects/{id}/exports`; GET `/exports/{id}/download` | datasets | reviewer (list/download: any) |
| GET/PATCH/DELETE `/images/{id}` | detail incl. versions and lease; notes/split/assignee; delete (admin) | any |
| GET `/images/{id}/display|original|thumb` | pixels | any |
| GET `/images/{id}/grey` | raw 8-bit luminance, gzip (assisted tools) | any |
| GET `/images/{id}/labels[?version=n]` | raw `uint8` labels, gzip, header `X-Revision` | any |
| PUT `/images/{id}/labels?base_revision=r` | save raw labels (optional `Content-Encoding: gzip`) | lease holder |
| GET `/images/{id}/mask.png?style=colour|binary|indexed&target=&version=` | download | any |
| POST/DELETE `/images/{id}/lock`; POST `/images/{id}/lock/release` (beacon) | leases | any / admin `force` |
| POST `/images/{id}/submit`, `/withdraw`, `/review`, `/restore/{n}` | workflow | see §4 |

Errors are `{"detail": "<plain-language message>"}` with codes 400/401/403/404/409/413/422/423.

## 7. Export

See `docs/EXPORT_FORMAT.md` for the full contract. Summary: ZIP with `pairs/` or
`train|val|test/{images,masks}/`, masks binary (0/255), red (255,0,0), indexed or colour, optional
`coco_annotations.json` (uncompressed RLE per class per image, exact) and YOLO-seg polygons
(needs OpenCV; lossy), `manifest.json` (schema `online-annotator.export/1`) and `README.txt`.
Default selection is **approved versions only**. Automatic splits are deterministic:
images ordered by SHA-256(`seed:image-sha256`) and cut by the ratios.

## 8. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Deployment | single process (Uvicorn), SQLite WAL, data directory outside the release; Python ≥ 3.10; no internet |
| Browsers | current Chrome, Edge, Firefox (pointer events, `CompressionStream` optional) |
| Limits | upload ≤ `max_upload_mb` (200) per file, ≤ `max_image_megapixels` (80); images ≥ 8×8 |
| Concurrency | tens of simultaneous users; SQLite busy timeout 30 s; leases prevent edit collisions |
| Durability | atomic PNG writes (temp + rename); audit in DB and `audit/audit.jsonl` |
| Security | see AGENTS.md rule 8; login rate limit (10 failures / 15 min per e-mail + client) |
| Privacy | only e-mail, name and activity are stored; nothing leaves the server |
| Accessibility | keyboard shortcuts for all tools; every button has an accessible name (E2E-tested); visible focus |

## 9. Configuration

`config.example.yml` documents every key. Precedence: defaults < YAML (`--config` or
`ONLINE_ANNOTATOR_CONFIG`) < `ONLINE_ANNOTATOR_<KEY>` environment variables (nested keys with
`__`). First administrator: `ONLINE_ANNOTATOR_ADMIN_EMAIL` / `ONLINE_ANNOTATOR_ADMIN_PASSWORD`
or a generated one-time password written to `<data>/initial_admin_password.txt`.
