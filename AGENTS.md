# AGENTS.md - Repository Working Contract

This document provides authoritative, non-negotiable guidance for automated agents and developers working in the **OnlineAnnotator** repository.

---

## 1. Core Mission & Founding Principles

1. **Scientific Traceability & Reproducibility**:
   All microstructural semantic segmentation annotations serve as ground-truth for machine learning models (such as `HydrideSegmentation`). Data integrity, versioning, provenance, and exact mask reproduction are paramount.

2. **Intranet-First Deployment**:
   The software runs inside an air-gapped or restricted office intranet. It must not depend on external CDNs, cloud authentication services, or remote APIs. All assets (fonts, icons, JS/CSS libraries, demo data) must be self-contained within this repository.

3. **Multi-User Safe Concurrency**:
   Multiple annotators work concurrently across browser sessions. To prevent data corruption or overwritten annotations, **image lease locking** is mandatory. No agent may bypass the locking contract when mutating annotation records.

4. **Office Email Identity**:
   Usernames are strictly office email addresses (e.g. `user@barc.gov.in`, `analyst@office.local`). No arbitrary username strings without valid domain structures are permitted. Dual authentication (stored password and 6-digit email OTP) must be preserved.

5. **Working Ledger Continuity**:
   Every state modification (user creation, image lease, draft save, review request, approval, dataset export) must be written to the database ledger and mirrored to `data/ledger.json`. Furthermore, when agent tasks pause or conclude, `LEDGER.md` must be updated with the latest progress state.

---

## 2. Priority Hierarchy

When goals or requirements appear to conflict, apply this strict priority order:
1. **Data Safety, Traceability, and Scientific Accuracy**
2. **Multi-User Concurrency Integrity (Locking & Leases)**
3. **ML Pipeline Compatibility (HydrideSegmentation paired format, COCO, YOLO)**
4. **Intranet Self-Sufficiency (Zero external CDN or cloud dependencies)**
5. **Execution Speed & Feature Additions**

---

## 3. Mandatory Architectural Boundaries

### 3.1 Backend & Database
- **FastAPI** provides the REST API and WebSocket services.
- **SQLAlchemy 2.0** ORM manages SQLite in `WAL` (Write-Ahead Logging) mode to support concurrent intranet reads and serialized atomic writes.
- **Pydantic v2** models define strict input/output data validation contracts.
- **Computer Vision Operations**: Raster/vector processing, Otsu thresholding, morphological operations, and format conversions reside exclusively in `backend/app/services/cv_service.py` and `export_service.py`. Core computation must never be coupled to HTTP route handlers.

### 3.2 Frontend Architecture
- The frontend is served directly by the backend as a single-page application (SPA).
- No external CDN scripts (Tailwind CDN, Google Fonts, Unpkg, etc.) are allowed. All CSS and JavaScript must be served locally from `/static`.
- The 2D canvas workspace must maintain decoupling between:
  1. The rendering engine (`canvas.js`)
  2. The tool implementations (`tools.js`)
  3. The API client & synchronization layer (`api.js`, `ws.js`)
  4. The UI layout and modal states (`app.js`, `auth.js`)

---

## 4. ML Pipeline Integration Standards

### 4.1 HydrideSegmentation Alignment
All exports intended for hydride segmentation must strictly conform to the contracts in `configs/hydride/prepare_dataset.paired_rgb_mask.mado.yml`:
- **Paired File Pattern**: Image `{stem}.png` or `{stem}.jpg` paired with `{stem}_mask.png`.
- **Binary Mask Mode**: 8-bit single channel PNG where `0 = background / matrix` and `255 = hydride`.
- **RGB Mask Mode**: 3-channel 24-bit PNG where the red channel dominates for hydrides (`R >= 200, G <= 60, B <= 60`).
- **Multiclass Indexed Mode**: 8-bit PNG where pixel values correspond strictly to the assigned class IDs.

### 4.2 Standard ML Formats
Exports must also support:
- **COCO JSON**: Categories list, image dimensions, polygon segmentation coordinates or RLE, and bounding boxes.
- **YOLO Segmentation**: Normalized polygon coordinates (`class_id x1 y1 x2 y2 ... xn yn`).
- **NumPy Archive (`.npz`)**: Arrays `images`, `masks`, `classes`, and `metadata`.
- **Packaged Dataset Bundle (`.zip`)**: Structured splits (`train/`, `val/`, `test/`) with paired `images/` and `masks/` and a `dataset_manifest.json` report containing area fractions, sample counts, and class statistics.

---

## 5. Testing & Quality Requirements

1. **Automated Test Suite**:
   Every new endpoint, schema change, or service method must have corresponding unit or integration tests in `tests/`.
2. **Non-Regression Verification**:
   Before completing any task, execute:
   ```powershell
   python -m pytest tests -v
   ```
   All tests must pass with zero failures.
3. **Ledger Update**:
   Always record task completion, schema changes, and resumed state in `LEDGER.md`.
