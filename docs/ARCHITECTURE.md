# Architecture

## Overview

```
 Browser (vanilla ES modules, no build step)             Server (one Python process)
 ┌───────────────────────────────────────────┐          ┌──────────────────────────────────────┐
 │ views/*.js  screens, help, dialogs        │  JSON    │ api/*.py     thin FastAPI routers      │
 │ editor/editor.js  canvas view + tools     │ ───────▶ │ services/    all behaviour:            │
 │ editor/labelmap.js  exact label ops, undo │  raw     │   access     privilege + working mode  │
 │ api.js  fetch, gzip, CSRF header          │  bytes   │   workflow   leases + state machine    │
 └───────────────────────────────────────────┘ ◀─────── │   labels     encode/validate/stats     │
                                                         │   imaging    ingest, display, grey     │
                                                         │   exports    ZIP + manifest            │
                                                         │   auth, projects, audit, demo          │
                                                         │ models.py    SQLAlchemy (SQLite WAL)   │
                                                         │ db.py        engine + migrations       │
                                                         └──────────────┬───────────────────────┘
                                                                        │
                                          data_dir/ ┌───────────────────┴─────────────────────────┐
                                                    │ online_annotator.sqlite3  (+ -wal, -shm)     │
                                                    │ backups/  pre-upgrade database copies        │
                                                    │ images/<project>/<id>_original.<ext>         │
                                                    │ images/<project>/<id>_display.png, _thumb.jpg│
                                                    │ masks/<image>/working.png, v0001.png …       │
                                                    │ exports/*.zip                                │
                                                    │ audit/audit.jsonl   secret_key               │
                                                    └──────────────────────────────────────────────┘
```

## Why raster labels

Semantic segmentation ground truth is a class per pixel. Storing vector shapes (the prototype's
approach) forces a lossy rasterisation later, makes erasing and overlapping classes ambiguous,
and let an anti-aliased colour canvas masquerade as a mask. Here the label map *is* the data:

- the browser holds a `Uint8Array(width × height)`; every tool writes class indices into it
  through `LabelMap` (brush discs sampled at pixel centres, even-odd scanline polygons,
  4-connected floods) — no canvas drawing is ever read back;
- the overlay is rendered from the label map through a colour look-up table into an
  `ImageData` (only the dirty rectangle is refreshed);
- saving sends the raw bytes, gzip-compressed with `CompressionStream` where available;
- the server validates size and class values and writes an 8-bit greyscale PNG atomically;
- undo stores only the changed rectangle before/after each operation (bounded by steps and bytes).

## Privilege and working mode

A single `role` (annotator / reviewer / admin) used to mix two unrelated questions: *what is this
person allowed to do?* and *what are they doing right now?* They are now separate columns on
`users` and separate code paths:

- **`is_admin`** is a privilege: projects, classes, accounts, deleting images, breaking leases.
  It is checked by the `admin` dependency in `api/deps.py` and never looks at the mode.
- **`active_mode`** (`annotate` | `review`) is chosen by the user (`PUT /auth/mode`) and stored
  on the server. Every user may annotate and review; `services/access.py` decides whether they
  may do so *now*: `require_mode` guards annotating (edit a non-submitted image, import,
  submit) and reviewing (correct or decide on a submission), and `may_review` applies the
  second-person rule (`allow_self_approval`). `services/workflow.py` calls them before any
  lease, revision or label check, so a stale tab in the wrong mode is refused with a message
  that names the mode to switch to.
- Queues (`services/projects.py`: `annotate_queue`, `review_queue`, `queue_counts`) apply the
  same rule, so a user's own submissions never appear as work for them to review.

Keeping the mode on the server (not only in the browser) is what makes it enforceable
(AGENTS.md rule 4) and lets it follow the person between tabs and desks. `services.access.Refused`
is the base of `workflow.WorkflowError`, so routers translate every refusal to its HTTP status in
one place.

## Database schema and migrations

`db.init_schema` runs at every start and from `online-annotator migrate`:

1. No database yet → tables from the models, stamped `SCHEMA_VERSION` (`PRAGMA user_version`).
2. Older database → a consistent copy under `data_dir/backups/` (SQLite backup API, safe with the
   WAL), then each pending `db.MIGRATIONS` step in order, the version stamped after each one.
3. Newer database → refused, so an accidental downgrade cannot write data an older release
   misunderstands.

Steps are idempotent, so an interrupted upgrade is simply started again. A new schema change adds
one step, bumps `SCHEMA_VERSION`, changes the models in the same commit and extends
`tests/test_migrations.py`, which upgrades real databases written by earlier releases
(`tests/fixtures/db_v*.sql`, produced by those releases' own code) and checks the result has the
same shape as a fresh database. `online-annotator db-status` shows the stored version and pending
steps without changing anything.

## Concurrency

- **Leases** (`image_locks`): acquiring is required before any label change; the browser renews
  every lease/3 and releases on leave (`sendBeacon` on tab close). Expired leases are reclaimed
  lazily.
- **Revisions**: each save names the `working_revision` it started from; a mismatch is refused
  with 409, so an administrator breaking a lease can never cause a silent lost update.
- SQLite runs in WAL mode with a 30 s busy timeout; writes are short transactions.

## Request pipeline

`app.guard` middleware: rejects mutating `/api/` requests without
`X-Requested-With: OnlineAnnotator` (CSRF), adds CSP and security headers, `no-store` for API
responses, `no-cache` (ETag revalidation) for static files so upgrades never mix old and new
modules. Validation errors are rewritten into one plain-language sentence.

## Frontend structure

| Module | Responsibility |
| --- | --- |
| `main.js` | boot, hash router, top bar with the Annotate / Review switch (saves and leaves the view, switches on the server, redraws), help menu, re-authentication dialog |
| `nav.js`, `state.js`, `ui.js`, `api.js` | navigation and `switchMode`/`modeButton`, shared state (`isAdmin`, `mode`, mode texts), DOM toolkit (`h`, `modal`, `toast`, `helpTip`), HTTP |
| `views/home.js` | projects, mode note, quick start, new-project wizard, "annotate/review next" |
| `views/project.js` | mode-led header, gallery, upload, mask import, classes, export, activity, settings |
| `views/workspace.js` | editor chrome: edit/review/view decision from status and mode, banners, autosave, lease heartbeat, workflow dialogs |
| `views/help.js` | Help centre content and keyboard sheet (the user guide) |
| `views/users.js`, `views/login.js` | accounts (administrator privilege, current mode), sign-in, password change |
| `editor/editor.js` | view transform, rendering, pointer/keyboard input for tools |
| `editor/labelmap.js` | pure label-map algorithms and history (Node-tested) |

## Testing layers

1. `tests/test_*.py` — services and HTTP API through FastAPI's TestClient with an isolated
   temporary data directory per test (`test_modes.py`: privilege, working mode, own-submission
   protection, both directions of the two-person cycle; `test_migrations.py`: upgrades).
2. `tests/js/labelmap.test.mjs` — label engine under Node (`node --test`), run from pytest.
3. `tests/browser/*.spec.js` — Playwright journeys in Chromium against a fresh demo server;
   `modes.spec.js` has two users alternately annotating and reviewing each other's work.
