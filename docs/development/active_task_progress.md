# Active Task Progress Ledger — OnlineAnnotator

> Cardinal rule (inherited from `ml_server/docs/PLATFORM_VISION_AND_GOVERNANCE.md` §3.1):
> every goal is resumable; no context lives only in chat. Update this file before and after
> every substantial step, and commit it with the code it describes.

## Goal (set 2026-09-11)

Turn OnlineAnnotator into a state-of-the-art, intranet-deployable semantic-segmentation
annotation tool: creation, review and export must be easy, intuitive and self-explanatory for
ordinary users, with inline help at critical points and a dedicated Help menu. Bake cardinal
principles into AGENTS.md and other docs (aligned with pytex, HydrideSegmentation, ml_server
practice). Commit + push to GitHub (`kvmani/OnlineAnnotator`), integrate as a tool in
`ml_server` (catalog, scientific help, deploy manifest), test through a real browser like a
human, fix usability issues. Done = usable, deployable, maintainable, documented, integrated,
and shown to work.

## Review findings on the inherited prototype (2026-09-11)

The prototype (FastAPI + vanilla JS, ~7.3k lines, not under git) had fundamental defects:

1. **Masks were not ground truth.** Client "mask" = anti-aliased RGB canvas of class colours,
   saved verbatim; eraser only deleted whole polygons / stroke points. Semantic-segmentation
   labels must be exact per-pixel class indices.
2. **Auth hole.** `/email-otp/request` auto-created any account and returned the OTP in the
   response (`dev_otp`) whenever SMTP was disabled (the default) → anyone could log in as
   `admin@office.local`. Hard-coded seeded admin password `Admin@123`.
3. **Locks not enforced** on draft save/commit; image files, masks and export downloads were
   unauthenticated.
4. **Export misrepresented data**: used latest (unapproved) version, silently fell back to
   exporting *all* images with empty masks, COCO area = bbox area, brush strokes exported as
   polygons, "numpy"/"yolo"/"coco" options all produced the same zip.
5. Hard-coded `C:/Users/kvman/HydrideSegmentation/...` path; private sample images copied in.
6. No packaging, version source, CHANGELOG, security headers, or git history.

Decision: re-architect (keep FastAPI/SQLAlchemy/SQLite-WAL, lease locks, audit ledger ideas).

## Architecture decisions (v1.0.0)

- `src/online_annotator/` package, `python -m online_annotator serve`, console script,
  single version source `_version.py`, health `{"status","tool_id":"online-annotator","version"}`
  at `/api/health` (+ `/health`).
- **Raster-first labels**: canonical annotation = 8-bit label map (0 = background, 1..N classes)
  stored as PNG. Browser edits a `Uint8Array`, uploads raw bytes (gzip) — no canvas read-back,
  so no colour management / anti-aliasing / fingerprint-noise corruption. Server validates size
  and class values.
- Workflow: new → in_progress → submitted → approved | changes_requested. Submissions create
  immutable versions (sha256 recorded). Export uses latest **approved** version by default.
- Lease locks enforced server-side for every mutation + optimistic revision check.
- Roles: annotator, reviewer, admin. No self-approval unless configured.
- Auth: password (bcrypt) primary; e-mail OTP only when SMTP configured; no silent account
  creation; first-run admin bootstrap with random one-time password + forced change.
- Vanilla ES-module frontend, no build step, no CDN (air-gapped), hash router, relative URLs
  (works behind a path prefix).
- Exports: HydrideSegmentation flat pairs (`stem.png` + `stem_mask.png`, binary 0/255 or red RGB),
  split folders, indexed/colour masks, COCO (RLE, exact), optional YOLO-seg (needs OpenCV),
  manifest with full provenance.
- Help: contextual hint bar per tool, `?` popovers at critical decisions, shortcut sheet,
  first-run quick-start, full in-app Help centre.

## Plan / status

- [x] 0. Survey prototype + sibling repos (ml_server governance, pytex AGENTS, Hydride pairing contract, deploy manifest)
- [x] 1. git init, baseline commit 5c9e2ad; public repo github.com/kvmani/OnlineAnnotator created with the user's approval (2026-09-12); main pushed; GitHub Actions CI green
- [x] 2. Governance docs: AGENTS.md (cardinal principles), CLAUDE.md, CONTRIBUTING, CHANGELOG, SPECIFICATIONS, docs/ - commit 65836f4
- [x] 3. Backend re-architecture (package, models, auth, locks, labels, workflow, exports, audit, CLI) - commit 568bd0c
- [x] 4. Backend tests (pytest) green - 51 tests incl. Node-run label-engine tests
- [x] 5. Frontend rewrite (dashboard, project, workspace tools, review, export, admin, help)
- [x] 6. Browser testing as a human: annotator, reviewer, export, admin, upload (16-bit TIFF), mask import, lock conflict + take-over, changes-requested loop, session expiry re-login - all PASS; automated as 6 Playwright journeys
- [x] 7. ml_server integration pushed (ml_server 2e7b6e3 + 8f05d8b, tag v1.3.0; coordinating ledger ml_server/docs/development/online_annotator_integration.md); ml_server_deploy 22e9f3f adds component `annotator`, suite 1.7.0
- [x] 8. Released: OnlineAnnotator v1.0.0 (99e485e) and v1.0.1 (fe20215, stroke fix found by 12 MP perf test); ml_server v1.3.0; ml_server_deploy suite v1.7.0 published https://github.com/kvmani/ml_server_deploy/releases/tag/v1.7.0 (all release gates green)

## Browser-test log (demo server on :5071, data in the session scratchpad)

Found and fixed during human-style testing:
- Magic wand grew +-tolerance around the clicked grey level, so an edge click missed the
  platelet core. Now grows over connected pixels at least as dark (bright) as the seed,
  dark/bright decided from the 31x31 neighbourhood. Help texts updated; unit test added.
- Toasts overlapped the workspace hint bar; moved up/left in the workspace.
- ES-module imports carry no version query: /static now served with Cache-Control: no-cache.
- Help pages had no breadcrumb; "1 images" plural; brand wrapped on narrow panes; side panel
  crowded narrow screens -> collapsible panel toggle.
- Manifest lost the original annotator for reviewer-corrected versions -> `contributors`;
  timestamps now tz-aware and approved_at >= annotated_at.
Note: the browser harness's `key`/`type` actions inject stray clicks; drive the workspace with
DOM events (element.click / PointerEvent / KeyboardEvent) for deterministic tests.

## Blockers

- None. (GitHub repository creation was resolved by the user's approval on 2026-09-12.)

## Verification record (2026-09-12)

| Check | Result |
| --- | --- |
| `python -m pytest` (OnlineAnnotator) | 51 passed (Windows, Python 3.13) |
| Node label-engine tests | 8 passed |
| `npm run test:browser` (Playwright, Chromium) | 6 passed locally; CI green on GitHub (ubuntu, Python 3.12, Node 22) |
| `ruff check` | clean |
| Wheel build | all web assets packaged |
| Suite-style launch smoke test | health, one-time admin, host-relative portal link, data in shared/ |
| ml_server full suite | 82 passed; flake8/black clean on changed files |
| ml_server_deploy | manifest validation, 62 unit tests, text hygiene clean; full rehearsal 28/28 under real systemd (WSL); suite v1.7.0 release workflow green incl. dependency gate |
| Large image (4000x3000) | API upload 16-bit TIFF 1.2 s, save 0.14 s; browser stroke ~4.6 ms/move, undo 8 ms |

## ml_server notes

- ml_server `main` already failed its own pre-commit hooks on ~30 unrelated files (vendor
  bundles, trailing whitespace, black) before this goal; left untouched (not in scope).
  Only files changed by this goal were formatted with the pinned black 23.7.
- Resolved on 2026-09-12 (ml_server 2343fec): the whitespace/EOF hooks were rewriting vendored
  bundles and the EBSD fixture (now excluded), isort had no config so it fought black forever
  (now `profile = "black"` at 100 columns), and one unused import failed flake8. CI is green
  end to end for the first time: pre-commit, `pytest -q` (82) and the docker build all run.

## Outcome — GOAL COMPLETE (2026-09-12)

- OnlineAnnotator `main` at github.com/kvmani/OnlineAnnotator, tags v1.0.0, v1.0.1; CI green.
- ml_server `main` 2e7b6e3/8f05d8b + ledger commit, tag v1.3.0 (catalog card, scientific help).
- ml_server_deploy `main` 6de553e, tag v1.7.0, release archive published.
- Office rollout: download ml-server-suite-v1.7.0.tar.gz + .sha256, run `./update.sh` on the server;
  first admin password in shared/data/online_annotator/initial_admin_password.txt (RUNBOOK).
- Rollback: previous suite release (data dir in shared/ is untouched).
- Follow-ups (not blocking): ml_server CI fails at pre-commit on pre-existing files (suggested as
  a separate task); possible future features: label overlay in gallery thumbnails, pinch-zoom for
  tablets, inter-annotator agreement metrics.

---

# Goal (set 2026-09-12) — import pre-existing masks and record their provenance

## Objective

Annotators should not have to start from scratch when a mask for a micrograph already exists —
produced by an external tool, an in-house script (for example the user's own hydride
segmentation program) or a model. They import it, correct its mistakes, and the metadata
records that the original source of the mask was **imported**, together with **user remarks**
about the tool used. Release it and roll it into the ml_server_deploy suite.

## Decisions

1. **Provenance is structured, not a free-text origin string.** 1.0.x had only
   `Image.working_origin` ("imported from x.png (binary)"), which no consumer could rely on.
   Added `mask_source` (`manual` | `imported`), `mask_source_tool`, `mask_source_remarks`,
   `mask_source_file`, `mask_imported_by`, `mask_imported_at` on `Image`, and the first four
   frozen onto `Version` at snapshot time.
2. **Provenance is sticky.** Hand-correcting an imported mask does not make it `manual`;
   that is the whole point of the record (cardinal rule 1, traceability). Only an explicit
   restore of a manual version returns the image to `manual`, and it does so by copying that
   version's frozen provenance along with its pixels.
3. **Per-image import, not just bulk.** 1.0.x had a project-wide bulk import only, which is a
   reviewer/admin batch operation. The annotator who is looking at one image now imports from
   the workspace side panel (**Mask source**), which is where the need actually arises.
   Both paths share `labels.decode_mask_file`, so the size check and interpretation rules
   cannot drift apart.
4. **No silent conversions.** A mask whose size differs from its image is refused with a message
   saying masks are never resized, because resizing would change the ground truth. Unknown grey
   values and unmatched colours are refused rather than guessed (unchanged from 1.0.x).
5. **Export manifest keys are additive; schema stays `online-annotator.export/1`.** Bumping the
   schema string would break consumers that assert on it (HydrideSegmentation), while new keys
   are ignored by existing readers. Recorded here because AGENTS.md lists the manifest as a
   contract needing a deliberate decision.
6. **Schema version 2 with an in-place additive migration.** `create_all` only creates missing
   tables, so `db.ADDED_COLUMNS` now drives `ALTER TABLE ... ADD COLUMN` for databases written by
   1.0.x. Every column has a default, so 1.0.x can still read a migrated database (one release
   of backward readability, as the contract requires).

## Completed work

- `models.py`: provenance columns on `Image` and `Version`; `MASK_SOURCES`.
- `db.py`: `SCHEMA_VERSION = 2`, `ADDED_COLUMNS`, `_add_missing_columns`, logged on upgrade.
- `services/labels.py`: `decode_mask_file` (shared decode + size check).
- `services/workflow.py`: `import_working` records provenance; `_snapshot` freezes it;
  `restore` restores it; `describe_source`; `set_source_remarks`.
- `api/images.py`: `POST /images/{id}/mask-import`, `PATCH /images/{id}/mask-source`.
- `api/projects.py`: bulk import takes `source_tool` and `remarks`, shares the decoder.
- `api/serialize.py`, `services/exports.py`: provenance in API responses and the manifest.
- UI: **Mask source** side section in the workspace (badge, tool, remarks, who and when),
  import dialog, edit-remarks dialog; tool and remarks fields on the bulk import dialog;
  Help centre section "Starting from masks you already have".
- Docs: `SPECIFICATIONS.md` (capability + three endpoints), `docs/EXPORT_FORMAT.md`
  (manifest keys and their meaning), `CHANGELOG.md` 1.1.0.

## Verification record (2026-09-12)

| Check | Result |
| --- | --- |
| `python -m pytest` | 71 passed (51 pre-existing + 20 new in `tests/test_mask_import.py`) |
| `npm run test:browser` (Playwright, Chromium) | 7 passed, including the new import journey |
| `ruff check src tests` | clean |
| Schema migration | tested against a database rewound to schema 1: columns added, idempotent |
| Visual check | workspace screenshot: imported mask overlaid, panel shows file/tool/remarks |

New tests cover: binary/indexed/colour/red-dominant interpretation, refusal of a wrong-sized
mask and of unreadable or ambiguous files, provenance surviving hand-correction, provenance
frozen into a submitted version, restore returning manual provenance, remarks editing and its
refusal on hand-drawn images, approved images never overwritten, lease held by someone else,
the audit entry, bulk import provenance, and the export manifest.

## Post-release note: the v1.1.0 tag's CI run (2026-09-12)

The `v1.1.0` tag run failed while `main` passed on the identical commit `092e994` (the repo
has one workflow, so both ran the same steps). Lint and `pytest` passed on both; only the
Playwright step failed, so this was a harness flake in the journey added for mask import, not
a product defect. Two one-shot races in that journey were found and fixed:

- it asserted on `.toast` `.first()`, but an earlier toast ("Project created") can still be on
  screen when the import toast appears (a screenshot of the flow shows both) -- 3afa4fd;
- it read the class-coverage title once immediately after a synthetic stroke, before the event
  is necessarily delivered and recomputed; it now polls -- 7e10aa5.

Which assertion actually fired is **not** confirmed: downloading the job log returns
`403 Must have admin rights to Repository` unauthenticated. The run's Playwright report
artifact has it (7-day retention):
https://github.com/kvmani/OnlineAnnotator/actions/runs/34674822566

The tag was deliberately **not** moved: suite v1.8.0 already resolved `v1.1.0` to `092e994`,
and the deploy contract is that a release pins exact immutable component commits, so retagging
would silently invalidate the published archive. Both fixes are test-only and ride the next
release. If the tag must carry green CI, the clean route is a `v1.1.1` patch tag plus a suite
bump, never a moved tag.

## Release 1.1.1 (2026-09-12)

Cut so the shipped tag carries a green CI run, which `v1.1.0` does not (see the note above).
Product code is identical to 1.1.0; only the two Playwright fixes differ. Suite bumped to
1.8.1 to take it. Full verification re-run before tagging: pytest 71, Playwright 7, node 8,
ruff clean.

## Git state

- OnlineAnnotator `main`: 1.1.1, tag `v1.1.1` (green); `v1.1.0` at `092e994` left in place
  with its red Playwright run, because suite v1.8.0 pinned that commit and tags are immutable.
- ml_server_deploy: `annotator` `ref` = `v1.1.0`, suite `v1.8.0` tagged; release build succeeded.
- ml_server `main`: `2343fec`, CI green end to end (pre-commit, pytest 82, docker build).

## Next action

- None; goal complete. Follow-ups unchanged from the previous goal.

---

# Goal (set 2026-09-14) — every user can Annotate and Review

## Objective

Ordinary users are no longer permanently `annotator` or `reviewer`. Every active user can both
annotate and review, and switches an **active working mode** (Annotate / Review) from the web
UI. Account privilege (administrator) is separate from working mode. Nobody reviews their own
submission under the normal configuration. Establish a maintainable schema migration approach.
Extend pytest, JS and Playwright coverage (two users alternately annotating and reviewing each
other's work), update README/specs/architecture/help, release, tag, and roll the release into
`ml_server_deploy` so the whole suite installs in one go at the office.

## Decisions

1. **Schema 3: `users.role` is replaced by `is_admin` (privilege) and `active_mode`
   (`annotate` | `review`, persisted server-side).** A per-user server-side mode means the
   server can enforce it (cardinal rule 4) and it survives sign-out and a different desk.
2. **The mode is enforced on the server, not only shown.** Annotate mode: edit images that are
   not waiting for review, import masks, submit. Review mode: correct a submission and approve
   or request changes. Withdrawing your own submission works in either mode (it only takes back
   your own work). Admin privileges (projects, classes, users, delete images, break leases) do
   not depend on mode. Uploading images, splits, assignments and exports, formerly reviewer-only,
   are open to every active user in either mode, because every user now has the former reviewer
   capability.
3. **Own-submission protection.** Unless `allow_self_approval: true`, a user can neither approve
   nor request changes on their own submission, and their own submissions never appear in their
   review queue or its counts. With the setting on, they appear (the old semantics).
   Withdraw is limited to the submitter or an administrator. It used to be open to any reviewer,
   and now that everyone can review, keeping that would have let anyone take back anyone's work.
4. **Numbered migration registry** (`db.MIGRATIONS`): a fresh database is created from the
   models and stamped with the current version. An older database first gets a consistent
   SQLite backup under `<data>/backups/`, then each step runs in its own transaction and stamps
   `PRAGMA user_version` as it goes. A newer database still refuses to start. The CLI gains
   `db-status` and `migrate` for operators. No Alembic: it is not in the small runtime set, and
   SQLite-only numbered steps are enough.
5. **Migration 3 maps old roles:** `admin` → `is_admin`, `reviewer` → starts in Review mode,
   then drops `role` (SQLite ≥ 3.35; refused with a clear message otherwise). This keeps the
   users table from carrying a dead NOT NULL column that would break inserts.
6. **Version 2.0.0:** the user JSON loses `role`, `create-user --role` becomes `--admin`, and
   the schema goes to 3. Health contract and export manifest are unchanged (`reviewer_edit`
   stays as a stored version kind: it describes the edit, not a person's role).
7. Demo accounts become two ordinary users (`arun@demo.local`, `riya@demo.local`) plus the
   administrator, so the two-person workflow can be tried and E2E-tested.

## Plan / status

- [x] 1. Backend: `models.User` (`is_admin`, `active_mode`), `db.py` migration registry (schema 3,
  backup, `schema_status`), `services/access.py`, workflow rules (mode, own submission, withdraw),
  `projects.review_queue/annotate_queue/queue_counts`, `PUT /auth/mode`, `next` defaults to mode,
  project `queue`, CLI `create-user --admin`, `db-status`, `migrate`, demo users arun/riya/admin
- [x] 2. pytest: fixtures alice/bob/carol/admin; new `test_modes.py` (19) and `test_migrations.py`
  (upgrades SQL dumps written by the real v1.0.1 and v1.1.1 code, `tests/fixtures/db_v*.sql`)
- [x] 3. Frontend: top-bar Annotate/Review radio switch (save + leave + switch + redraw, other tabs
  follow), mode notes and mode-led actions on dashboard/project, "For me to review" filter,
  "yours" tag, workspace banners per mode, Users page privilege + mode, Help centre section
- [x] 4. Playwright: journeys updated; `modes.spec.js` (two users in both directions, return and
  resubmission, own submission, remembered mode, mode switch with unsaved work, admin)
- [x] 5. Docs: README, SPECIFICATIONS (v2.0, §10 schema), ARCHITECTURE, DEPLOYMENT, EXPORT_FORMAT,
  AGENTS.md, config.example.yml, CHANGELOG 2.0.0, `_version.py` 2.0.0
- [x] 6. Full verification, release 2.0.0 (commit 044b502, tag v2.0.0), pushed; GitHub CI green
  on both `main` (run 34817363159) and the tag (run 34817365481)
- [x] 7. ml_server_deploy aea8c34: annotator ref v2.0.0 (resolves to 044b502), suite 1.10.0,
  RUNBOOK rollback/accounts notes; tag v1.10.0; release build green (run 34817706371), archive
  published: https://github.com/kvmani/ml_server_deploy/releases/tag/v1.10.0

## Outcome — GOAL COMPLETE (2026-09-14)

- OnlineAnnotator 2.0.0 on `main`, tag `v2.0.0`, CI green.
- Suite 1.10.0: download `ml-server-suite-v1.10.0.tar.gz` + `.sha256` and run `./update.sh` on
  the office server. The annotator backs up and upgrades its database to schema 3 on first start;
  a fresh install simply creates schema 3. Rollback past 1.10.0: RUNBOOK "Rollback".
- ml_server (portal) unchanged: its help for this tool already says "a second person approves".
- Follow-ups (not blocking): none new.

## Defects found while testing (fixed)

- Router dropped a hash navigation that arrived while a view was still being drawn (exposed by
  switching mode and then immediately navigating): `main.js` now renders again afterwards.
- A project page left open never updated "Review next (n)": the 20 s gallery refresh now also
  refreshes the header counts.

## Verification so far (2026-09-14)

| Check | Result |
| --- | --- |
| `python -m pytest` | 96 passed (incl. Node label-engine tests) |
| `ruff check src tests` | clean |
| ml_server_deploy `pytest tests/unit`, text hygiene, `manifest.py --validate` | 72 passed, clean, OK |
| `node --test tests/js/labelmap.test.mjs` | 8 passed |
| `npm run test:browser` (Playwright, Chromium) | 13 passed (7 journeys + 6 two-person mode journeys); earlier runs 9/13 failed on the two defects above |
| Visual check | screenshots of Annotate dashboard, Review project page, review workspace |

Note: this session overwrote the untracked, git-ignored `.claude/launch.json` (it held an
`annotator-demo` preview entry on port 5071 from the 2026-09-11 session) without reading it
first; it was re-created with an equivalent entry.

---

## Goal (set 2026-09-15): mask interoperability with HydrideSegmentation

Users upload the mask they already have; the system says what it detected, how it will be
interpreted and which class values will be stored. Common cases import automatically; ambiguous
ones ask. Semantic class IDs are kept separate from display pixel values; nothing is resized.

### Baseline (before any change)

- OnlineAnnotator `python -m pytest`: 96 passed.
- HydrideSegmentation (`.venv`, web/report/API tests): 73 passed, 1 failed **pre-existing**:
  `test_workspace_places_run_button_near_input_and_exposes_split_zoom_and_version` expects
  "v1.0.0" but the uncommitted local 1.0.1 version bump (not ours) renders "v1.0.1".
- HydrideSegmentation working tree carries someone's uncommitted 1.0.1 release work
  (CHANGELOG, README, version files, pptx, book chapter files). We never stage those files.

### Decisions

1. **One analysis result.** `labels.analyze_mask_file()` returns `MaskAnalysis` (detected
   encoding, file format/mode/dtype, observed values/colours, mapping, target class, threshold,
   invert, warnings, requires_confirmation, ok/error, final class pixels). The same object feeds
   the preview endpoints, the import, the audit entry, stored provenance and the tests.
   It lives in `services/labels.py` because that module owns all label decoding (AGENTS rule 1).
2. **Auto-detect order:** (1) values all valid project class IDs -> preserved exactly;
   (2) {0,1} -> binary; (3) {0,255} -> binary display, foreground -> chosen class;
   (4) other two-value zero-background ({0,128}, {0,7}) -> binary-like, **needs confirmation**
   (mirrors HydrideSegmentation, where `two_value_zero_background` is an explicit opt-in, and a
   stray value may be a class ID from another project); (5) exact project colours; (6) red-on-black
   (R>=200, G<=60, B<=60, everything else near-black); (7) palette PNG: indices are read first
   and used when they are valid class IDs, otherwise the palette colours are interpreted;
   (8) multi-level grey -> refused in auto, explicit threshold mode required.
3. **Modes:** auto | indexed | binary | threshold | colour, plus `invert` for binary/threshold.
4. **Refusals are actionable:** every error names what was found and the next step.
5. **Provenance:** new JSON column `mask_import_details` on images and versions (schema 4,
   additive migration), frozen into versions and written to the export manifest as
   `mask_import`. Audit entries carry the same dict.
6. **HydrideSegmentation:** commits stay local (repository owned by Pushpalathadevi, dirty tree);
   pushing is left to the user.

### Plan / status

- [x] 1. `labels.py` analysis engine (`analyze_mask_file`, `MaskAnalysis`, `MaskClass`) replacing
  `interpret_mask_image`/`decode_mask_file`; `tests/test_mask_analysis.py` (34 tests)
- [x] 2. `services/mask_import.py` (single + bulk share `import_file`; batch preview/import; mask name
  suffixes `_mask_labels`, `_mask_preview`, `_mask`); `POST .../mask-import/analyze` and
  `.../masks/analyze`; `mode`/`threshold`/`invert`/`confirm` on both imports (`409` until confirmed);
  migration 4 `mask_import_details` on images + versions (frozen, restored, remarks kept in sync);
  `mask_import` in image/version JSON, audit entries and export manifest; `tests/test_mask_import.py`
  +14 tests (analyze, confirmation, threshold, provenance everywhere, single-vs-bulk parity x6,
  bulk confirm, HydrideSegmentation names)
- [x] 3. UI: `views/maskimport.js` shared by both dialogs (reading choice, live preview, suggested
  reading button, confirmation box, per-file batch list); "Read as" in Mask source; Help centre
  "How a mask file is read"; SPECIFICATIONS, EXPORT_FORMAT, AGENTS service map, CHANGELOG
  (Unreleased); Playwright mask journey extended (gradient refused -> threshold -> confirmation;
  binary preview; "Read as")
- [x] 4. HydrideSegmentation **b7f7886 (local, not pushed)**: `src/microseg/io/mask_download.py`
  (`binary_labels` reuses `to_index_mask` + `normalize_binary_index_mask(two_value_zero_background)`,
  refuses non-binary), routes `/api/jobs/<id>/mask_labels.png|mask_preview.png|masks.zip`
  (`422 MASK_NOT_BINARY`), "Download mask" menu keeping the old download, help + intranet_web_app.md,
  `tests/test_web_mask_downloads.py` (18). Its CHANGELOG is left untouched because it carries
  someone's uncommitted 1.0.1 entry.
- [x] 5. Final verification recorded below; OnlineAnnotator committed and pushed to `main` together
  with this ledger entry

### Verification (2026-09-15, final code)

| Check | Result |
| --- | --- |
| OnlineAnnotator `python -m pytest` | 142 passed (96 before + 34 analysis + 12 net new import tests; incl. Node label-engine tests) |
| `python -m ruff check src tests` | clean |
| Playwright `journeys.spec.js` + `modes.spec.js` | 13 passed (mask journey extended); see the browser-suite note for the untracked spec |
| Visual check (demo server, Browser pane) | {0,128} mask: "Two-value mask", 128 -> class 1 Hydride, foreground 3.3%, "nothing is resized", confirmation box shown |
| Demonstration script (10 cases, real API) | as in the table above |
| HydrideSegmentation `tests/test_web_mask_downloads.py` | 18 passed |
| HydrideSegmentation web/report/API/jobs/library/corrections suites | 135 passed, 1 skipped, 1 failed **pre-existing** (version string, uncommitted 1.0.1 bump) |

### Outcome

Goal complete in code, tests and docs (OnlineAnnotator `f7dcea9`, CI green).

## Release for office rollout (2026-09-15, rollout 2026-09-16 morning)

User asked to push the HydrideSegmentation commit and prepare a suite release.

- HydrideSegmentation: `b7f7886` pushed; annotated tag **v1.1.0** at `b7f7886` pushed (user chose
  this over "annotator only"). Its version files still read 1.0.0 because the 1.0.1 bump and
  release edits in that working tree are someone else's uncommitted work; the CHANGELOG line
  there is still to be written once that work is committed.
- OnlineAnnotator **2.1.0**: `_version.py`, CHANGELOG `[2.1.0] — 2026-09-15`; tag `v2.1.0`.
  Verification before tagging: ruff, pytest, Node engine, Playwright journeys + modes.
- ml_server_deploy **suite 1.12.0**: `annotator` ref v2.1.0, `hydride` ref v1.1.0 (comments
  explain both), RUNBOOK rollback note for schema 4; tag `v1.12.0` builds the office archive.
- 2.1.0 verification (2026-09-15): ruff clean; pytest 142 passed; Node engine 8 passed;
  Playwright journeys + modes 13 passed.
- CI made lean at the user's request (office target is air-gapped Ubuntu, Python 3.12): here one
  ubuntu-24.04 job, ruff + pytest, on pushes to `main` and tags, cancelling superseded runs;
  Playwright left CI and stays a local pre-release gate (AGENTS.md). ml_server_deploy CI is one job
  (manifest, hygiene, shell syntax, unit tests; no ShellCheck/actionlint downloads, no rehearsal
  job); its release workflow drops the duplicate lint, the second reproducibility build (covered by
  a unit test) and the fixture rehearsal (run locally in WSL).
- Released (2026-09-15): OnlineAnnotator `e4352a2` tag `v2.1.0` (CI green on `main` and tag);
  HydrideSegmentation tag `v1.1.0` -> `b7f7886`; ml_server_deploy `507991f` (CI green) tag
  `v1.12.0`, release workflow green (run 34996524891), published
  https://github.com/kvmani/ml_server_deploy/releases/tag/v1.12.0 with
  `ml-server-suite-v1.12.0.tar.gz` (64.9 MB) + `.sha256`
  (`e29068c7779a27dfff3f4d7d75f3dad95d4670eca2c6a07b1c12b6e941fb6a43`).
- Rollout: download `ml-server-suite-v1.12.0.tar.gz` + `.sha256`, `./update.sh`. The annotator
  backs up and upgrades its database to schema 4 on first start. Rolling back past 1.12.0
  needs that copy restored (RUNBOOK "Rollback").

### Defects found while testing (fixed)

- Mapping pixel counts were zipped from a Python `set` against numpy's ordered counts (wrong
  count per colour/palette index possible) and the palette mapping indexed a 32-entry listing
  (IndexError beyond 32 used indices). Found by ruff B905; regression assertions added.
- `field()` puts a `(?)` button inside the `<label>`, so the label named the button, not the
  control (Playwright `getByLabel` found the button). The import controls now carry explicit
  `aria-label`s.

### Browser-suite note

`tests/browser/capture_screenshots.spec.js` is an **untracked file that is not ours** (writes to a
`.gemini` path). `npm run test:browser` picks it up; it creates a project as admin on the shared
demo server, after which three older journeys fail on "Annotate next resolved to 2 elements". The
tracked suite is run explicitly: `npx playwright test tests/browser/journeys.spec.js
tests/browser/modes.spec.js`. The file is left untouched.

### Demonstration (real API, `scratchpad/mask_demo.py`; classes 1 Hydride #FF0000, 2 Pore #0000FF)

| Mask | Detected | Action | Stored values | Provenance (`mask_import`) |
| --- | --- | --- | --- | --- |
| {0,1} | indexed | imported as is | {0,1} | indexed, "stored exactly", class_pixels {1:180} |
| {0,255} | binary_0_255 | 255 -> class 1 | {0,1} | mapping 255 -> class 1 Hydride, "Binary normalization" |
| {0,128} | binary_like | 409 "only 0 and 128 ... confirm"; confirm=true -> imported | {0,1} | confirmation_required, confirmed=true |
| {0,2} (class 2 valid) | indexed | kept as class 2 | {0,2} | mapping 2 -> class 2 Pore |
| {0,1,2} | indexed | kept | {0,1,2} | class_pixels {1:180, 2:40} |
| grey 0..255 ramp | grayscale_multilevel | 400 "choose Grayscale threshold (suggested 126)"; threshold 128 + confirm -> imported | {0,1} | encoding threshold, threshold 128, confirmed |
| RGB class colours | colour | colours -> classes | {0,1,2} | mapping #FF0000 -> 1, #0000FF -> 2 |
| red on black | red_on_black | red -> class 1 | {0,1} | HydrideSegmentation red rule in normalization |
| palette PNG idx {0,1,2} | palette_indexed | indices kept | {0,1,2} | warning: palette colours differ, numbers stored |
| 32x24 on 64x48 | wrong_size | 400 "never resized ... export at full resolution" | unchanged {0} | none (nothing imported) |

## Polygon threshold tool and typed tool sizes (2026-09-16) — annotator 2.2.0, suite 1.13.0

User request: a threshold tool like Box threshold but with an arbitrary polygon ROI (analysed
first: pros, cons, risks), numeric entry for brush/eraser sizes, and keyboard shortcuts for the
current tool size. Then release so ml_server_deploy builds the new version.

### Decisions (user: same size for brush and eraser; separate tool; shortcut scope left to me)
- Separate tool **Polygon threshold (R)** (R was free). Reuses the polygon clicking model; the
  preview/apply state is shared with Box threshold (`thresholdState.shape` = box | polygon).
- One rasteriser `polygonSpans` in `labelmap.js` now drives Polygon, Lasso and the polygon ROI
  (`polygonRegion`), so one outline always means the same pixels (Node test compares them on
  convex, concave, self-intersecting and off-image shapes).
- Otsu over ROI pixels only; strict cut at the outline, before speck removal. Warning above 70 %
  selected (tight outline -> unimodal histogram). Minimum 16 inside pixels. Clicks during a preview
  do not discard it. No vertex editing after closing (deliberately out of scope).
- `[`/`]` are contextual (brush/eraser diameter, wand tolerance, previewed threshold); Shift =
  big step; matched on `e.code` too because AltGr layouts never reached the old handler.
- Size stored as a diameter 1–160 (pref `brushDiameter`, old `brush` radius migrated); disc centre
  snapped (odd -> pixel centre, even -> corner) so a 1 px brush is exactly one pixel.
- Found while testing: a focused range slider swallowed all shortcuts (`isTyping`), and the
  threshold panel was rebuilt on every slider input (broke dragging). Both fixed.
- Not changed: ml_server `tool_help.py` still describes the box threshold only; still accurate,
  so no portal release was cut for it.

### Verification (2026-09-16)
- ruff clean; Node engine 11 passed (3 new); pytest 142 passed; Playwright journeys + modes +
  new `tools.spec.js` 17 passed (the untracked `capture_screenshots.spec.js` excluded as before).
- Looked at in a real browser on demo image 3: outline drawn, preview cut along it
  (917 of 66,355 px), grain boundaries not selected, number boxes in the panel.

### Release
- Released (2026-09-16): OnlineAnnotator `6a41be4` tag `v2.2.0` (CI green on `main` and tag);
  ml_server_deploy `e59b51b` (CI green) tag `v1.13.0`, release workflow green (run 35108525145),
  published https://github.com/kvmani/ml_server_deploy/releases/tag/v1.13.0 with
  `ml-server-suite-v1.13.0.tar.gz` (64.9 MB) + `.sha256` (`bddcb1636129ce5c80f072221798154a7cf11b88d2ac272f1e817f7a9c9de49e`).
- Rollout: download both files, `./update.sh`. No schema change, so rolling back to 1.12.0 needs
  nothing restored.
- Goal complete.

