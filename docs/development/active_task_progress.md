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
- [~] 8. Release: OnlineAnnotator v1.0.0 tagged + pushed (99e485e); suite v1.7.0 release build pending

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
| ml_server_deploy | manifest validation, 62 unit tests, text hygiene clean |

## ml_server notes

- ml_server `main` already failed its own pre-commit hooks on ~30 unrelated files (vendor
  bundles, trailing whitespace, black) before this goal; left untouched (not in scope).
  Only files changed by this goal were formatted with the pinned black 23.7.

## Current state / next action

- OnlineAnnotator: `main` pushed, tag `v1.0.0` -> 99e485e.
- ml_server: `main` pushed (2e7b6e3, 8f05d8b), tag `v1.3.0`.
- ml_server_deploy: `main` 22e9f3f (suite 1.7.0 with component `annotator`).
- Next: after ml_server_deploy CI passes, tag suite `v1.7.0` so the release workflow runs the
  dependency gate and builds the office archive; record the result here and close the goal.
