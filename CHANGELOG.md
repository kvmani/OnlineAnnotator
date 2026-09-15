# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/);
the running version is `src/online_annotator/_version.py`.

## [Unreleased]

## [2.1.0] — 2026-09-15

Upload the mask you already have: the import says what it detected, how it will read the file and
which class numbers will be stored. Common masks import on their own; ambiguous ones ask.

### Added
- **Mask interpretation preview.** Both import dialogs show, before anything is stored, the
  detected encoding, the file's format/mode/dtype, the values or colours found, each value → class
  mapping with pixel counts, the foreground share, warnings and "nothing is resized". New
  `POST /api/v1/images/{id}/mask-import/analyze` and `POST /api/v1/projects/{id}/masks/analyze`
  return this analysis without changing anything.
- **Reading modes:** Auto detect (default), Indexed class mask, Binary mask, Grayscale threshold and
  Colour mask, plus *Foreground is black* for black-on-white masks. Import endpoints accept `mode`,
  `threshold`, `invert` and `confirm`.
- Palette PNGs are read by their indices when those are class numbers (warning or asking when the
  palette colours tell a different story); 16-bit, 1-bit and alpha-channel masks are understood.
- Bulk import pairs HydrideSegmentation's `<stem>_mask_labels.png` and `<stem>_mask_preview.png`.
- **Import provenance** `mask_import` on images, versions (frozen), the audit trail and every export
  manifest record: file SHA-256, detected encoding, mapping, normalization, target class, threshold,
  warnings, confirmation. Database schema 4 (additive migration, backed up first).

### Changed
- Auto detection keeps any mask whose values are all class numbers exactly (a `{0, 2}` mask in a
  project with classes 1 and 2 stays class 2), and asks for confirmation instead of guessing for
  two-value masks such as `{0, 128}` or `{0, 7}`, red masks with soft edges, and palette PNGs whose
  colours disagree with their indices (`409` until `confirm=true`). Greyscale images with many
  levels are refused in auto mode and import only with an explicit, confirmed threshold.
- Red-on-black masks must be red and (near-)black only: a picture that merely contains some red
  (a photograph, an overlay) is refused instead of being imported as a mask.
- Refusals are actionable: an unknown class value names the project's classes and the reading to
  choose; photographs, the image itself, multi-page files and wrong sizes each say what to do.
- Single-image and bulk import share one decoding path (`services/mask_import.py`).
- CI is lean: one Ubuntu 24.04 / Python 3.12 job (lint + pytest) on pushes to `main` and tags,
  matching the air-gapped office server. Browser journeys run locally before every release.

## [2.0.0] — 2026-09-14

Every user can annotate **and** review. There are no annotator or reviewer accounts any more.

### Changed (breaking)
- **Working modes replace roles.** `users.role` (`annotator` | `reviewer` | `admin`) is replaced by
  an `is_admin` privilege and a per-account `active_mode` (`annotate` | `review`) that each person
  switches from an **Annotate / Review** control in the top bar. The mode is stored on the server
  and enforced there: annotating (editing an image that is not waiting for review, importing
  masks, submitting) needs Annotate mode; correcting, approving and returning a submission needs
  Review mode. Administrator rights never depend on the mode.
- API: user objects carry `is_admin` and `active_mode` instead of `role`; `POST /users` and
  `PATCH /users/{id}` take `is_admin`; new `PUT /api/v1/auth/mode`; `GET /projects/{id}/next`
  defaults `mode` to the caller's working mode; project responses add the caller's `queue`
  counts (`annotate`, `review`, `own_pending`). A refusal because of the mode is `409` and names
  the mode to switch to.
- CLI: `create-user --role …` is replaced by `create-user [--admin]`.
- Splits, assignments and exports, formerly reviewer-only, are open to every user in either mode.
- Withdrawing someone else's submission now needs an administrator (formerly any reviewer).
- Nobody reviews their own submission (approve, request changes or correct it) unless
  `allow_self_approval` is set, and their own submissions are left out of **Review next** and the
  review counts. Previously only approval was blocked and own submissions were queued last.
- Demo accounts are two ordinary users, `arun@demo.local` and `riya@demo.local`, plus
  `admin@demo.local`.

### Added
- Mode-led screens: the dashboard and project page lead with **Annotate next** or
  **Review next (n)** and a note of what waits in the current mode, with a button to the other
  mode when that is where the work is; the gallery gains a **For me to review** filter and a
  **yours** tag; workspace banners explain own submissions and images that are not waiting for
  review, with a one-click mode switch. Switching mode saves and releases an open image and
  redraws the same page; another tab follows the change when it is looked at again.
- Users page: an Administrator checkbox and each person's current working mode.
- Help centre section **Annotate and Review modes**; help, inline tips and messages no longer
  describe people as annotators or reviewers.
- **Database migrations**: schema version 3 and a numbered, idempotent migration registry
  (`db.MIGRATIONS`). An older database is copied to `<data>/backups/` and then upgraded step by
  step at start-up; `online-annotator db-status` and `online-annotator migrate` for operators.
  Migration 3 keeps former administrators as administrators and starts former reviewers in
  Review mode. Tests upgrade real databases written by v1.0.1 and v1.1.1.
- Tests for privilege, working modes, own-submission protection and both directions of the
  two-person cycle (`tests/test_modes.py`), and Playwright journeys in which two users alternately
  annotate and review each other's work, including return and resubmission, the remembered mode
  and switching mode with unsaved work (`tests/browser/modes.spec.js`).

### Upgrade notes
- The upgrade is automatic at the first start. Release 1.x refuses to start on a schema-3
  database; to roll back, restore the copy the upgrade saved in `<data>/backups/`.
- Needs SQLite 3.35 or newer (Ubuntu 22.04 and later ship it).

## [1.1.1] — 2026-09-12

### Fixed
- Two races in the Playwright journey added for mask import made the suite fail intermittently
  under CI load (the `v1.1.0` tag run failed on the Playwright step while the identical commit
  passed on `main`): it asserted on the first toast when an earlier one could still be on
  screen, and it read the class-coverage title once immediately after a synthetic stroke. Both
  now match by text and poll. Test-only; no product code differs from 1.1.0.

## [1.1.0] — 2026-09-12

### Added
- **Import an existing mask and correct it.** An annotator who already has a mask for a
  micrograph — from another segmentation tool, an in-house script such as a hydride
  segmentation program, or a model prediction — can load it as the starting point instead of
  labelling from scratch. New in the workspace side panel (**Mask source → Import a mask**) for
  the image being annotated; the project-wide bulk import gained the same provenance fields.
  Binary (0/255), indexed, class-colour and red-on-black masks are understood; a mask whose size
  differs from its image is refused rather than resized.
- **Mask provenance recorded and exported.** Every image and every frozen version now carries
  `mask_source` (`manual` or `imported`), the tool that produced the original mask, the file it
  came from, who imported it and when, and free-text **user remarks** (the model version, the
  settings, known weaknesses). The record is sticky: hand-correcting an imported mask never
  turns it back into hand-drawn work. Remarks can be edited afterwards
  (**Edit remarks**, `PATCH /api/v1/images/{id}/mask-source`).
- Export manifests report `mask_source`, `mask_source_tool`, `mask_source_file` and
  `mask_source_remarks` per image, so a training pipeline can weight, audit or exclude corrected
  machine output separately from labels drawn from scratch. These are additive keys; the manifest
  schema stays `online-annotator.export/1` so existing readers keep working.
- Help centre, inline `(?)` help and a Playwright journey covering the import flow.

### Changed
- Database schema version 2. Upgrading adds the provenance columns to an existing database in
  place; the columns have defaults, so release 1.0.x can still read a migrated database.
- Restoring an earlier version now restores the provenance frozen with that version, not
  whatever the working copy happened to say.

## [1.0.1] — 2026-09-12

### Fixed
- Brush and eraser strokes painted only their first disc when the browser delivered an empty
  coalesced-event list (synthetic input, some browsers); strokes now fall back to the event
  itself. Verified on a 12-megapixel image (continuous stroke, 8 ms undo, save 0.14 s).

## [1.0.0] — 2026-09-11

First production release: a re-architecture of the inherited prototype.

### Added
- Raster-first annotation: 8-bit label maps edited exactly in the browser and transferred as
  raw bytes; server-side validation of size and class values.
- Tools: brush, eraser, polygon, lasso, microstructure-aware magic wand, Otsu box threshold with
  live preview, fill, speck removal, hole filling, protect-other-classes mode, patch-based
  undo/redo, outline and contrast views, collapsible side panel.
- Review workflow with immutable SHA-256-fingerprinted versions, reviewer corrections as new
  versions, request-changes with mandatory comment, withdraw, restore; no self-approval by default.
- Exclusive editing leases with heartbeat and beacon release; optimistic revision checks.
- Exports: HydrideSegmentation pairs or train/val/test folders; binary, red, indexed or colour
  masks; exact COCO RLE; optional YOLO-seg; deterministic auto-split; provenance manifest
  `online-annotator.export/1`; export history with SHA-256; approved-area statistics.
- Upload of PNG/JPEG/TIFF (incl. 16-bit)/BMP with recorded display conversion; duplicate
  detection; import of model predictions as pre-annotations.
- Accounts: bcrypt passwords, admin-issued one-time passwords, optional SMTP sign-in codes,
  login rate limiting, first-run administrator bootstrap, CLI user tools.
- Self-explanatory UI: quick start, `(?)` help at decisions, tool hint bar, state banners, Help
  centre, keyboard sheet; re-sign-in dialog that keeps unsaved work.
- `portal_url` may be host-relative (`:5000/`), resolved in the browser, so the "All tools"
  link works from every desk in the ml_server suite.
- Platform contract: `/api/health` `{status, tool_id, version}`, `/help`, security headers,
  CSRF header guard, `python -m online_annotator` and `online-annotator` entry points.
- Tests: pytest suite, Node tests of the label engine, Playwright end-to-end journeys; GitHub
  Actions CI runs all three.
- Documentation: AGENTS.md cardinal rules, specification, architecture, export format,
  deployment guide, systemd and environment templates.

### Removed
- Prototype vector-shape storage, WebSocket channel, hard-coded sample paths and the seeded
  `Admin@123` account.

### Security
- Fixed the prototype's e-mail OTP flow, which auto-created accounts and returned the code to the
  browser; image, mask and export downloads now require a session.
