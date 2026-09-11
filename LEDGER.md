# LEDGER.md - Project Working Ledger

## 1. Project Metadata
- **Project**: OnlineAnnotator
- **Description**: Online Microstructural Semantic Segmentation Annotator & Ground-Truth Dataset Preparation Workbench
- **Initial Target Domain**: Hydride Morphology in Zirconium Alloys (`HydrideSegmentation`)
- **Primary Integration**: `ml_server` Intranet Tool Platform (`http://127.0.0.1:5000`)
- **Ledger Version**: 1.1.0
- **Last Updated**: 2026-09-11

---

## 2. Completed Milestones & Architectural Records
- [x] **Milestone 1: Discovery & Specification Alignment**
  - Inspected reference repositories: `project_management_software`, `ml_server`, `HydrideSegmentation`.
  - Defined strict office email authentication contract (stored password + 6-digit OTP).
  - Drafted `AGENTS.md` specifying non-negotiable engineering principles.
  - Drafted `SPECIFICATIONS.md` detailing data schemas, API routes, and ML export requirements.
- [x] **Milestone 2: Backend Architecture & Database Engine**
  - Configuration management (`config.yml`, `backend/app/config.py`).
  - SQLAlchemy 2.0 ORM with SQLite WAL mode (`backend/app/db.py`).
  - Data models: User, SessionToken, LoginOtpChallenge, DatasetProject, DatasetClass, MicrographImage, ImageLock, AnnotationDraft, AnnotationVersion, LedgerRecord.
  - Pydantic v2 schemas with `ConfigDict(from_attributes=True)` and pattern validation.
- [x] **Milestone 3: Authentication, Security & Concurrency Services**
  - Native `bcrypt` password hashing & session management.
  - Email OTP generation (6-digit HMAC-SHA256) with SMTP delivery and local dev fallback.
  - Multi-user lease locking with heartbeat renewal and automatic expiration.
- [x] **Milestone 4: Computer Vision & ML Export Services**
  - Otsu and adaptive thresholding assistance for hydride platelets.
  - Raster-to-polygon and polygon-to-raster conversions.
  - Export engine producing HydrideSegmentation-ready binary/RGB masks, COCO, YOLO, NumPy, and split ZIP packages.
- [x] **Milestone 5: Interactive Web Frontend (Canvas Workspace)**
  - Responsive single-page layout matching intranet styling (`frontend/index.html`, `static/css/app.css`).
  - 2D Canvas engine with Pan, Zoom, Brush, Eraser, Polygon, Wand, Undo/Redo, and Layer Opacity (`canvas.js`).
  - Session auto-save, draft restoration, and "Resume Work" navigation (`ledger_view.js`).
  - Real-time WebSocket lock indicators and multi-annotator awareness (`ws.js`).
- [x] **Milestone 6: ml_server Integration & Test Suite**
  - Catalog registration in `ml_server/src/ml_server/catalog.py` (id: `online-annotator`, href: `http://127.0.0.1:5070`).
  - Tool help entry in `ml_server/src/ml_server/tool_help.py`.
  - SVG icon in `ml_server/src/ml_server/static/images/annotator-mark.svg`.
  - Comprehensive automated pytest suite covering all components (16 passing tests with 100% pass rate).

---

## 3. Active Working State & Resumption Point
- **Status**: Production-ready and verified.
- **Port Allocation**: `5070` (`http://127.0.0.1:5070`).
- **Seeded Credentials**:
  - `admin@office.local` / `Admin@123`
  - Or request a 6-digit OTP for any valid office email ID.
- **Seeded Datasets**: "Hydride Microstructures (Zircaloy)" with optical sample and pre-computed Otsu pre-segmentation.
- **Next Operational Steps**: Run `python run.py` or `.\start_annotator.ps1` to start the live intranet service.
