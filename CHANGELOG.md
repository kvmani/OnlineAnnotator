# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/);
the running version is `src/online_annotator/_version.py`.

## [Unreleased]

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
- Platform contract: `/api/health` `{status, tool_id, version}`, `/help`, security headers,
  CSRF header guard, `python -m online_annotator` and `online-annotator` entry points.
- Tests: pytest suite, Node tests of the label engine, Playwright end-to-end journeys.
- Documentation: AGENTS.md cardinal rules, specification, architecture, export format,
  deployment guide, systemd and environment templates.

### Removed
- Prototype vector-shape storage, WebSocket channel, hard-coded sample paths and the seeded
  `Admin@123` account.

### Security
- Fixed the prototype's e-mail OTP flow, which auto-created accounts and returned the code to the
  browser; image, mask and export downloads now require a session.
