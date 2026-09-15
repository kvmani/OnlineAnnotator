# AGENTS.md — Repository Working Contract

This file tells human contributors and automation agents how to work in **OnlineAnnotator**.
It is authoritative for this repository. Read it completely before changing anything.

OnlineAnnotator is the office intranet's tool for creating, reviewing and exporting
pixel-exact **semantic-segmentation ground truth** for microstructure images. Its first
customer is `HydrideSegmentation`; it must stay general enough for any phase, defect or
feature a materials scientist wants to label. It is a long-lived scientific instrument, not
a prototype: the labels it produces train models whose outputs are published and relied on.

## Primary references

Read these before substantial work, in this order:

1. `../ml_server/docs/PLATFORM_VISION_AND_GOVERNANCE.md` — platform governance (policy 1.1).
   This repository is a member tool of the ml_server platform and adopts it. Where this file
   is stricter, this file wins; a genuine conflict stops work until it is reconciled.
2. `SPECIFICATIONS.md` — what the product does and the contracts it keeps.
3. `docs/ARCHITECTURE.md` — how the code is organised and why.
4. `docs/EXPORT_FORMAT.md` — the dataset contract consumed by training pipelines.
5. `docs/DEPLOYMENT.md` — how it runs on the office server.
6. `docs/development/active_task_progress.md` — the live progress ledger.

## Cardinal rules

These outrank convenience, speed and tidiness. A change that breaks one is a defect even if
every test passes.

### 1. Ground truth is exact, validated and traceable

- The canonical annotation is an **8-bit label map**: one integer per pixel, `0` = background,
  `1..255` = the project's class numbers. No anti-aliasing, blending, resampling or colour
  round-trip may ever sit between what the annotator drew and what is stored or exported.
- The browser sends raw label bytes; it never reads labels back from a canvas (colour
  management and anti-fingerprinting noise corrupt canvas read-back). All client-side label
  mutation lives in `web/static/js/editor/labelmap.js`; all server-side encoding and decoding
  lives in `services/labels.py`. Nothing else touches label bytes.
- The server validates every label map (size, allowed class values) before storing it.
- Submissions freeze **immutable versions** with a content SHA-256. History is never rewritten;
  "restore" copies a version into the working copy.
- Exports read the latest **approved** version only, unless the user explicitly chooses
  otherwise, and every export carries a manifest recording who annotated, who approved, which
  version, the SHA-256 of every file, the class map and the options used.
- An uploaded original is stored byte-for-byte; any display conversion (16-bit, TIFF, EXIF
  orientation) is described in `conversion_note`. No silent fallbacks for scientific steps:
  when something cannot be done faithfully, refuse with a clear message.

### 2. Every goal is resumable; progress lands on `main`

Inherited from platform governance §3.1–3.2 and pytex's cardinal rule.

- Keep `docs/development/active_task_progress.md` current for every multi-step goal:
  objective, decisions, completed work, verification results, Git state, blockers, next action.
  Update it before long-running work and in the same commit as the code it describes.
- Commit **and push** to `main` after each self-consistent, verified increment. An unpushed
  commit is not durable progress. No feature branches for ordinary work.
- Stage explicit paths (`git add <file>`), never `git add -A` / `git add .`.
- When a goal ends, is deferred or abandoned, say so in the ledger and commit it.

### 3. Ordinary users first: the tool explains itself

Most users are materials scientists, students or technicians, not annotation experts. Every user
both annotates and reviews, choosing a working mode (Annotate / Review) in the UI.

- Every screen states what to do next; primary actions are obvious (**Annotate next**,
  **Review next**, **Submit for review**, **Approve**, **Create export**).
- Every decision with scientific consequences (mask format, split, which annotations to
  export, class numbers, self-approval, protect mode, tool parameters) has an inline `(?)`
  explanation (`helpTip` in `ui.js`) in plain language.
- The workspace hint bar always explains the active tool; banners explain every lock and
  review state and offer the next action.
- Error messages say what happened **and what to do**. No stack traces, codes or jargon.
- Work is never lost: autosave with a visible save state, lost-session re-login in a dialog,
  refusal to leave with unsaved work, optimistic revision checks instead of silent overwrites.
- The in-app **Help centre** (`web/static/js/views/help.js`) is the canonical user guide. A
  change to user-visible behaviour updates the help text, the inline hints and the E2E
  journeys **in the same commit**.

### 4. Rules are enforced on the server

The browser mirrors rules for convenience; the server is the only authority. Editing leases,
workflow transitions, privilege and working-mode checks, self-approval, revision checks and label validation live in
`services/` and are unit-tested. A UI-only guard is a bug.

### 5. Intranet self-sufficiency

No CDN, web font, analytics, telemetry or external URL — at build time or run time. All assets
ship in `src/online_annotator/web/`. `tests/test_frontend_engine.py` fails on any external URL
in HTML/JS/CSS. Python dependencies must be available from the office pip mirror; keep the
runtime set small (FastAPI, Uvicorn, SQLAlchemy, Pydantic, bcrypt, PyYAML, NumPy, Pillow).
OpenCV is optional (YOLO export only).

### 6. Standalone by default, composable by integration

Platform governance §3.5. The tool installs, runs, tests and deploys without `ml_server`.
The portal only links to it by URL. The tool owns its health contract
(`/api/health` → `{"status","tool_id","version"}`), its version (`_version.py`), its
changelog, its deployment and rollback documentation.

### 7. The repository holds sources and canonical assets only

Inherited from pytex. Never commit runtime data (`data/`), databases, uploads, exports, audit
logs, screenshots, build output, caches, `node_modules/`, test results, or **any real specimen
image** — demo micrographs are generated deterministically by `services/demo.py`. Add the
`.gitignore` entry before or with the change that first produces an artefact.

### 8. Secure by default

bcrypt passwords; only SHA-256 of session tokens stored; one-time e-mail codes never reach
the browser; no account is created implicitly unless `self_registration` is configured;
first-run admin gets a random one-time password; mutating API calls require the
`X-Requested-With: OnlineAnnotator` header (CSRF guard); security headers on every response.
Secrets never enter git, logs, or the audit trail.

## Priority order when goals conflict

1. Scientific correctness, data safety and traceability
2. Multi-user integrity (leases, revisions, workflow)
3. Usability for ordinary users and never losing work
4. Compatibility of export contracts (HydrideSegmentation, COCO, YOLO)
5. Intranet self-sufficiency and security
6. Maintainability
7. Speed of delivery and new features

## Architectural boundaries

```
src/online_annotator/
  _version.py      single release identity (read by UI, health, manifests, packaging)
  config.py        defaults < YAML < ONLINE_ANNOTATOR_* env vars
  models.py        SQLAlchemy models (SQLite WAL by default)
  db.py            engine, schema version and numbered migrations (db.MIGRATIONS)
  services/        ALL behaviour: auth, access (privilege + working mode), workflow (leases +
                   state machine), labels (incl. mask-file analysis), mask_import, imaging,
                   projects, exports, audit, demo. Pure, unit-tested, no HTTP knowledge.
  api/             thin FastAPI routers: validate, call a service, serialise.
  app.py           factory: middleware (CSRF guard, headers, caching), routers, static SPA.
  cli.py           serve, create-user, reset-password, seed-demo, db-status, migrate.
  web/             vanilla ES-module SPA, no build step:
    static/js/editor/labelmap.js   exact label operations + undo history (Node-tested)
    static/js/editor/editor.js     canvas view, rendering and tool interaction
    static/js/views/*.js           screens; help.js is the user guide
```

- Route handlers never contain business rules; services never import FastAPI.
- The frontend never computes anything the server must trust.
- New dependencies need a reason recorded in the ledger and must exist on the office mirror.

## Contracts that need a deliberate, versioned change

Changing any of these requires: a schema/version bump where applicable, tests, `CHANGELOG.md`
entry, documentation update, and a note in the ledger.

- Health response shape and `tool_id` (`online-annotator`).
- Label transport: raw row-major `uint8`, optional gzip, `base_revision` query parameter.
- Stored label PNG format (8-bit greyscale, pixel = class index).
- Export manifest schema `online-annotator.export/1` and layouts in `docs/EXPORT_FORMAT.md`.
- HydrideSegmentation pairing: `<stem>.png` + `<stem>_mask.png`, binary 0/255 or red
  (R≥200, G≤60, B≤60); image stems never contain `_mask`.
- Database schema (`db.SCHEMA_VERSION`, `db.MIGRATIONS`): every change is a new numbered, idempotent
  migration step (backup first, then upgrade), tested against databases written by earlier
  releases in `tests/test_migrations.py`; a newer schema must refuse to start on an older release.
- Account model: `is_admin` privilege and per-account `active_mode`; there are no annotator or
  reviewer roles, and nobody reviews their own submission unless `allow_self_approval`.

## Testing (proportional, per platform governance §9)

| Command | What it proves | When |
| --- | --- | --- |
| `python -m pytest` | services, API, workflow, exports, auth, CLI; runs the Node engine tests if Node is present | every change |
| `node --test tests/js/labelmap.test.mjs` | exact label operations and undo | editor changes |
| `npm run test:browser` | real-browser user journeys (Playwright, fresh demo server) | any UI or workflow change; before every release |
| `python -m ruff check src tests` | lint | every commit |

- Behaviour changes add or update tests in the same commit; bug fixes add a regression test.
- Tests must not leave warnings, open resources or stray files.
- Before a release or deployment run **all** of the above and record results in the ledger.
- GitHub CI is deliberately lean: one Ubuntu 24.04 / Python 3.12 job (the office platform) running
  `ruff` and `pytest` on pushes to `main` and tags. The Playwright journeys are not in CI; running
  them locally before every release is part of the release checklist.
- Browser testing tip: some automation harnesses inject clicks when sending key presses; drive
  the workspace with DOM events or Playwright's own keyboard, never with a harness that clicks.

## Definition of done for a change

- [ ] Behaviour implemented in `services/` with server-side enforcement and unit tests.
- [ ] UI updated; hint bar, `(?)` help and Help centre describe the new behaviour.
- [ ] Playwright journey added or updated when a user flow changed.
- [ ] Docs updated (`SPECIFICATIONS.md`, `docs/*`), `CHANGELOG.md` under *Unreleased*.
- [ ] `pytest`, `ruff`, and when relevant `npm run test:browser` pass.
- [ ] Ledger updated; explicit-path commit; pushed to `main`.

## Releases

1. Update `src/online_annotator/_version.py` (SemVer) and move *Unreleased* in `CHANGELOG.md`.
2. Run the full verification set above; record it in the ledger.
3. Commit, tag `vX.Y.Z`, push `main` and the tag.
4. Bump the `annotator` component `ref` in `ml_server_deploy/manifest.yml` and follow that
   repository's release procedure. Rollback = previous suite release (data directory is shared
   and never touched by upgrades). A schema bump makes the previous release refuse the upgraded
   database, so say in the suite RUNBOOK that rolling back past it means restoring the copy the
   upgrade saved in `<data>/backups/`.

## Anti-goals

- No vector-first annotation model for semantic segmentation (shapes are an input method,
  the label map is the truth).
- No build toolchain, framework or bundler for the frontend.
- No cloud services, external identity providers or telemetry.
- No silent "best guess" conversions of masks, images or class maps.
- No feature that bypasses review for data presented as ground truth.
