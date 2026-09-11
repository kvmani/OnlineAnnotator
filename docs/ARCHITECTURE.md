# Architecture

## Overview

```
 Browser (vanilla ES modules, no build step)             Server (one Python process)
 ┌───────────────────────────────────────────┐          ┌──────────────────────────────────────┐
 │ views/*.js  screens, help, dialogs        │  JSON    │ api/*.py     thin FastAPI routers      │
 │ editor/editor.js  canvas view + tools     │ ───────▶ │ services/    all behaviour:            │
 │ editor/labelmap.js  exact label ops, undo │  raw     │   workflow   leases + state machine    │
 │ api.js  fetch, gzip, CSRF header          │  bytes   │   labels     encode/validate/stats     │
 └───────────────────────────────────────────┘ ◀─────── │   imaging    ingest, display, grey     │
                                                         │   exports    ZIP + manifest            │
                                                         │   auth, projects, audit, demo          │
                                                         │ models.py    SQLAlchemy (SQLite WAL)   │
                                                         └──────────────┬───────────────────────┘
                                                                        │
                                          data_dir/ ┌───────────────────┴─────────────────────────┐
                                                    │ online_annotator.sqlite3  (+ -wal, -shm)     │
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
| `main.js` | boot, hash router, top bar, help menu, re-authentication dialog |
| `nav.js`, `state.js`, `ui.js`, `api.js` | navigation, shared state/preferences, DOM toolkit (`h`, `modal`, `toast`, `helpTip`), HTTP |
| `views/home.js` | projects, quick start, new-project wizard, "annotate/review next" |
| `views/project.js` | gallery, upload, mask import, classes, export, activity, settings |
| `views/workspace.js` | editor chrome: modes, banners, autosave, lease heartbeat, workflow dialogs |
| `views/help.js` | Help centre content and keyboard sheet (the user guide) |
| `views/users.js`, `views/login.js` | accounts, sign-in, password change |
| `editor/editor.js` | view transform, rendering, pointer/keyboard input for tools |
| `editor/labelmap.js` | pure label-map algorithms and history (Node-tested) |

## Testing layers

1. `tests/test_*.py` — services and HTTP API through FastAPI's TestClient with an isolated
   temporary data directory per test.
2. `tests/js/labelmap.test.mjs` — label engine under Node (`node --test`), run from pytest.
3. `tests/browser/journeys.spec.js` — Playwright journeys in Chromium against a fresh demo server.
