# SPECIFICATIONS — Online Annotator

Version 2.0 of the product specification. Behaviour described here is implemented and tested;
changes follow the contract rules in `AGENTS.md`.

## 1. Purpose and scope

Online Annotator lets a team on an office intranet **create, review and export
semantic-segmentation ground truth** for microstructure images (optical, SEM, TEM …).

In scope:
- pixel-exact labelling of one or more classes per project, with assisted tools;
- a two-person review workflow producing immutable, approved versions, in which every user
  both annotates and reviews and nobody reviews their own work;
- multi-user operation with exclusive editing leases;
- import of an existing mask — from another segmentation tool, an in-house script or a model
  prediction — as the starting point for correction, either in bulk or for one image from the
  workspace, with the originating tool and the user's remarks recorded as `mask_source`
  provenance that follows the labels into every version and export; before anything is stored
  the import shows what it detected (class numbers, 0/1 or 0/255 binary, class colours, red on
  black, palette PNG, many-level greyscale) and which class numbers will be stored, asks for
  confirmation when a file reads two ways, needs an explicit threshold for greyscale images,
  never resizes, and records that interpretation as `mask_import`;
- export of approved data in HydrideSegmentation, split-folder, COCO and YOLO forms with a
  provenance manifest;
- self-explanatory UI with inline help and an in-app Help centre.

Out of scope (v2): instance segmentation IDs, 3-D stacks, video, bounding-box detection
labelling, model training or inference inside this tool, external identity providers.

## 2. Users, privilege and working mode

There are no annotator or reviewer roles. Two independent things describe a user:

**Privilege** (`is_admin`, set by an administrator):

| Account | Can, in either working mode |
| --- | --- |
| user | view projects; upload images; set splits and assignments; export datasets; everything in §2's working modes |
| administrator | everything a user can, plus create/edit/archive projects, manage classes and guidelines, manage accounts (including granting and removing administrator), delete images, break another person's lease |

**Working mode** (`active_mode`, chosen by each user for themselves from the top bar, stored
per account on the server, `annotate` for new accounts):

| Mode | The user does |
| --- | --- |
| Annotate | edit images that are not waiting for review (with a lease); import masks; submit; withdraw their own submission |
| Review | correct a submission from someone else (with a lease); approve it or request changes |

The server enforces the working mode (§4); switching mode never adds or removes a privilege,
and administrators annotate and review under the same rules as everyone else. An
administrator can see each person's current mode but cannot change it.

Identity is the office e-mail address. Accounts are created by an administrator (temporary
password, must be changed at first sign-in) or, only when `self_registration` is enabled
together with an SMTP relay and optionally `allowed_email_domains`, by e-mail code; such
accounts are ordinary users.

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
  submission or on approval of review corrections (kind `reviewer_edit`).
- **Lease (lock)**: exclusive right to edit one image, `lock_lease_seconds` long (default 300 s),
  renewed by the browser every lease/3 while the image is open, released on leave.
- **Working mode**: see §2.

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
2. An image that is not `submitted` is edited, imported into and submitted only in **Annotate**
   mode. A `submitted` image is edited only in **Review** mode, as a review correction, and
   never by its submitter; the submitter withdraws it instead. A refusal because of the mode
   is `409` and names the mode to switch to.
3. Submitting requires at least one save; it releases the submitter's lease.
4. Approving or requesting changes requires **Review** mode; `request_changes` requires a
   comment.
5. Nobody approves, returns or corrects a submission they made unless
   `allow_self_approval: true` (`403` otherwise).
6. If the working copy was corrected during review, approval snapshots the corrected labels as a
   new `reviewer_edit` version (approved) and marks the submission `superseded`.
7. Editing an approved image returns it to `in_progress`; its approved version stays in history
   and remains the one exported until a newer one is approved.
8. Restoring a version copies it into the working copy (history unchanged; rule 2 applies).
9. Only the submitter (in either mode) or an administrator withdraws a submission.

"Annotate next" order: my returned work → my work in progress → new images assigned to me →
new unassigned images → returned unassigned images, skipping images leased by others.
"Review next": submissions by other people, oldest submission first, skipping images leased by
others. The user's own submissions are never offered (unless `allow_self_approval`), and the
counts shown to a user (`queue`) exclude them in the same way.

## 5. Browser application

- Hash-routed single page, vanilla ES modules, no external assets; relative URLs so it also
  runs behind a path prefix.
- **Top bar**: an always-visible **Annotate / Review** switch (radio group) showing the
  current mode, with a mode-coloured edge (blue / purple). Switching saves and leaves the
  current view (releasing any lease), stores the mode on the server, and redraws the same page
  in the new mode without signing out. A tab that becomes visible again follows a mode changed
  elsewhere. Administrators also see **Users**.
- **Projects dashboard** with a dismissible "How it works" quick start and a mode note
  (what waits for me in this mode, a button to the other mode when that is where the work is).
  Cards lead with **Annotate next** or **Review next (n)** according to the mode.
- **Project page**: the same mode-led header and note, status summary with help, Images
  (filters — Review mode starts on "For me to review" — search, lock indicators, "yours" tag
  on own pending submissions, bulk split/assign, upload with drag-and-drop and progress, mask
  import in Annotate mode), Classes & guidelines, Export dataset, Activity, Settings (admin).
- **Workspace**: tools Pan (V), Brush (B), Eraser (E), Polygon (P), Lasso (L), Magic wand (W),
  Box threshold (T), Polygon threshold (R), Fill (G); Shift erases with any tool; Alt+click
  picks a class; keys 1–9 select classes; tool values (brush/eraser diameter 1–160 px, shared;
  wand tolerance; threshold) have a slider and a number box, and `[`/`]` change the active
  tool's value (Shift: halve/double the diameter, ±10 otherwise; matched on the physical key so
  non-US layouts work); undo/redo (patch-based, ≥100 steps); zoom at cursor,
  Space/middle/right-drag pan; fit (F); show/hide labels (H); outlines (O); brightness,
  contrast, invert (display only); protect-other-classes mode; speck removal and hole filling;
  live per-class coverage; hint bar for the active tool; banners for every lease, review and
  mode state (waiting for review with Withdraw or "Switch to Review mode"; own submission in
  Review mode; image not waiting for review in Review mode; changes requested; approved);
  autosave 2.5 s after the last edit, manual save Ctrl+S, visible save state; version history
  with restore and mask download; guidelines panel; collapsible side panel.
- **Users** (administrators): Administrator checkbox per account (not for oneself), current
  working mode shown read-only, status, reset password, disable.
- **Magic wand**: classifies the seed as dark/bright against its 31×31 neighbourhood mean and
  grows 4-connected over pixels at least as dark (bright) as the seed plus `tolerance`; refuses
  regions over 25 % of the image.
- **Brush and eraser**: a diameter in image pixels; the disc centre snaps (odd diameters to a
  pixel centre, even ones to a pixel corner) so a diameter always covers the same pixels, and a
  1 px brush changes exactly one pixel.
- **Box threshold**: Otsu threshold of the box's grey levels, dark/bright choice, speck
  filter, live preview, apply/cancel.
- **Polygon threshold**: the same, inside a clicked polygon. The outline is rasterised by the
  rule the Polygon and Lasso tools fill with (even-odd, pixel centres, clipped to the image), and
  only those pixels enter the Otsu histogram and can be selected; the selection is cut at the
  outline before speck removal. Outlines enclosing fewer than 16 pixels are refused. The panel
  shows selected/inside pixels and warns when more than 70 % of the region is selected (too
  little background for Otsu). While a preview is open, clicks do not start a new outline;
  Enter applies, Esc cancels. The undo step is "polygon threshold".
- **Help**: `(?)` popovers at decisions, Help centre (`#/help`, also `/help`) including
  "Annotate and Review modes", keyboard sheet (`?`).

## 6. HTTP API (`/api/v1`, JSON unless stated)

All mutating requests need header `X-Requested-With: OnlineAnnotator`; the session is an
HttpOnly cookie (or `Authorization: Bearer <token>`). "Mode" is the working mode the server
requires (§4).

| Method & path | Purpose | Who |
| --- | --- | --- |
| GET `/api/health`, `/health` | `{"status":"ok","tool_id":"online-annotator","version"}` | public |
| GET `/api/health/deep` | database and storage check | public |
| GET `/meta` | version, limits, feature flags (`allow_self_approval`), portal/feedback URLs | public |
| GET `/auth/options`; POST `/auth/login`, `/auth/logout`, `/auth/change-password`; GET `/auth/me` | sessions; user objects carry `is_admin` and `active_mode` | — |
| PUT `/auth/mode` `{"mode": "annotate" \| "review"}` | switch the signed-in user's working mode | any user |
| POST `/auth/otp/request`, `/auth/otp/verify` | e-mail code sign-in (only with SMTP) | — |
| GET/POST `/users`; PATCH `/users/{id}` (`full_name`, `is_admin`, `is_active`); POST `/users/{id}/reset-password` | accounts | admin (GET: any) |
| GET/POST `/projects`; GET/PATCH `/projects/{id}` | projects; GET adds the caller's `queue` `{annotate, review, own_pending}` | POST/PATCH admin |
| POST/PATCH/DELETE `/projects/{id}/classes[/{cid}]` | classes (delete only if unused) | admin |
| GET/POST `/projects/{id}/images` | list / multipart upload (`files`, `split`) | any |
| POST `/projects/{id}/images/bulk` | split / assignment for many images | any |
| GET `/projects/{id}/next?mode=annotate\|review&after=` | next image id; `mode` defaults to the caller's working mode | any |
| POST `/projects/{id}/masks/analyze` | preview a bulk import: matched image and interpretation per file; stores nothing | any |
| POST `/projects/{id}/masks` | import pre-annotation masks in bulk (`files`, `import_class`, `mode`, `threshold`, `invert`, `confirm`, `source_tool`, `remarks`); per-file `results` | any, Annotate mode |
| POST `/images/{id}/mask-import/analyze` | how one mask file would be read (`labels.MaskAnalysis`); stores nothing | any |
| POST `/images/{id}/mask-import` | import one existing mask as this image's working copy (same options; `409` while a required confirmation is missing) | any, Annotate mode |
| PATCH `/images/{id}/mask-source` | edit the tool name and remarks recorded for an imported mask | any |
| GET `/projects/{id}/activity`, `/projects/{id}/summary` | audit trail; approved class fractions | any |
| POST `/projects/{id}/exports/preview`, `/projects/{id}/exports`; GET `/projects/{id}/exports`; GET `/exports/{id}/download` | datasets | any |
| GET/PATCH/DELETE `/images/{id}` | detail incl. versions and lease; notes/split/assignee; delete (admin) | any |
| GET `/images/{id}/display\|original\|thumb` | pixels | any |
| GET `/images/{id}/grey` | raw 8-bit luminance, gzip (assisted tools) | any |
| GET `/images/{id}/labels[?version=n]` | raw `uint8` labels, gzip, header `X-Revision` | any |
| PUT `/images/{id}/labels?base_revision=r` | save raw labels (optional `Content-Encoding: gzip`) | lease holder; mode per §4 rule 2 |
| GET `/images/{id}/mask.png?style=colour\|binary\|indexed&target=&version=` | download | any |
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
| Deployment | single process (Uvicorn), SQLite WAL, data directory outside the release; Python ≥ 3.10, SQLite ≥ 3.35; no internet |
| Browsers | current Chrome, Edge, Firefox (pointer events, `CompressionStream` optional) |
| Limits | upload ≤ `max_upload_mb` (200) per file, ≤ `max_image_megapixels` (80); images ≥ 8×8 |
| Concurrency | tens of simultaneous users; SQLite busy timeout 30 s; leases prevent edit collisions |
| Durability | atomic PNG writes (temp + rename); audit in DB and `audit/audit.jsonl` |
| Security | see AGENTS.md rule 8; login rate limit (10 failures / 15 min per e-mail + client) |
| Privacy | only e-mail, name, working mode and activity are stored; nothing leaves the server |
| Accessibility | keyboard shortcuts for all tools; every button has an accessible name (E2E-tested); the mode switch is a labelled radio group; visible focus |

## 9. Configuration

`config.example.yml` documents every key. Precedence: defaults < YAML (`--config` or
`ONLINE_ANNOTATOR_CONFIG`) < `ONLINE_ANNOTATOR_<KEY>` environment variables (nested keys with
`__`). First administrator: `ONLINE_ANNOTATOR_ADMIN_EMAIL` / `ONLINE_ANNOTATOR_ADMIN_PASSWORD`
or a generated one-time password written to `<data>/initial_admin_password.txt`.
`allow_self_approval` (default `false`) lets people review their own submissions.

## 10. Database schema and upgrades

- The stored schema version is SQLite's `PRAGMA user_version`; this release writes schema **3**
  (`db.SCHEMA_VERSION`).
- `db.MIGRATIONS` holds one numbered, idempotent step per version after 1: 2 = mask provenance
  (1.1.0), 3 = working modes (2.0.0: `users.role` → `is_admin` + `active_mode`; former
  administrators stay administrators, former reviewers start in Review mode).
- At every start (and with `online-annotator migrate`) a fresh database is created at the
  current version; an older one is first copied to `<data>/backups/<db>.schema<N>.<UTC>.sqlite3`
  with SQLite's backup API, then upgraded one step at a time, the version stamped after each
  step; a newer one is refused. `online-annotator db-status` reports the stored version and the
  pending steps without changing anything (exit 0 current, 1 upgrade pending, 2 newer).
- Tests upgrade real databases written by v1.0.1 (schema 1) and v1.1.1 (schema 2) and prove the
  result has exactly the shape of a fresh database.
