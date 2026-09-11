# SPECIFICATIONS.md - Online Microstructure Semantic Segmentation Annotator

## 1. Project Overview & Scope
**OnlineAnnotator** is a modern, intranet-hosted web application for the manual and AI-assisted annotation of metallurgical microstructures to generate semantic segmentation ground-truth datasets for machine learning workflows.

Its primary initial domain application is **Hydride Morphology Segmentation** in zirconium alloys (`HydrideSegmentation`), enabling active learning loops where human annotators review and refine candidate predictions and export standardized datasets.

---

## 2. Technical Stack & Invariants
- **Backend**: Python 3.10+ / 3.13, FastAPI, Uvicorn, SQLAlchemy 2.0 (SQLite in WAL mode).
- **Computer Vision**: OpenCV (`cv2`), NumPy, Pillow (`PIL`), SciPy.
- **Frontend**: Responsive Single-Page Application (HTML5, Modern CSS, ES6+ Modular JavaScript).
- **Authentication**: Dual-mode (bcrypt stored password + 6-digit Office Email OTP).
- **Concurrency**: Lease-based image locking with auto-timeout and WebSockets.
- **Persistence**: SQLite database + JSON mirror records in `data/ledger.json`.

---

## 3. Data Models & Database Schemas

### 3.1 User & Authentication
- **User**:
  - `id` (int, primary key)
  - `email` (string, unique, indexed; must match email regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`)
  - `full_name` (string)
  - `role` (enum: `admin`, `lead_annotator`, `annotator`, `reviewer`)
  - `hashed_password` (string, bcrypt hash)
  - `is_active` (bool, default `True`)
  - `created_at`, `updated_at` (datetime)
- **LoginOtpChallenge**:
  - `challenge_id` (string, uuid/token_urlsafe, primary key)
  - `user_id` (int, foreign key -> `user.id`)
  - `otp_hash` (string, HMAC-SHA256 hash)
  - `expires_at` (datetime, 10 minutes from issue)
  - `is_used` (bool, default `False`)
- **SessionToken**:
  - `token` (string, token_urlsafe(32), primary key)
  - `user_id` (int, foreign key -> `user.id`)
  - `created_at` (datetime)
  - `expires_at` (datetime, 7 days from issue)
  - `last_activity` (datetime)

### 3.2 Dataset Project & Classes
- **DatasetProject**:
  - `id` (int, primary key)
  - `name` (string, unique)
  - `description` (string)
  - `created_by` (string, user email)
  - `created_at` (datetime)
- **DatasetClass**:
  - `id` (int, primary key)
  - `project_id` (int, foreign key -> `datasetproject.id`)
  - `class_index` (int, unique per project; e.g. 1, 2, 3...)
  - `name` (string; e.g. "Hydride", "Matrix", "Pore")
  - `color_hex` (string, hex color code; e.g. `#FF0000`)
  - `is_default` (bool)

### 3.3 Micrograph Image & Concurrency Locks
- **MicrographImage**:
  - `id` (int, primary key)
  - `project_id` (int, foreign key -> `datasetproject.id`)
  - `filename` (string)
  - `original_filename` (string)
  - `file_path` (string, relative to storage root)
  - `width` (int), `height` (int)
  - `checksum_sha256` (string)
  - `status` (enum: `unannotated`, `in_progress`, `under_review`, `completed`)
  - `assigned_to` (string, nullable, user email)
  - `metadata_json` (string/JSON: magnification, material, etching notes)
  - `created_at` (datetime)
- **ImageLock**:
  - `id` (int, primary key)
  - `image_id` (int, unique, foreign key -> `micrographimage.id`)
  - `user_email` (string)
  - `acquired_at` (datetime)
  - `expires_at` (datetime, lease duration: default 10 minutes)
  - `client_heartbeat` (datetime)

### 3.4 Annotations & Revision History
- **AnnotationDraft**:
  - `id` (int, primary key)
  - `image_id` (int, unique, foreign key -> `micrographimage.id`)
  - `user_email` (string)
  - `vector_data` (JSON: polygons, vertices, labels)
  - `mask_path` (string, rasterized mask cache)
  - `zoom_level` (float), `pan_x` (float), `pan_y` (float)
  - `updated_at` (datetime)
- **AnnotationVersion**:
  - `id` (int, primary key)
  - `image_id` (int, foreign key -> `micrographimage.id`)
  - `version_number` (int)
  - `created_by` (string, user email)
  - `vector_data` (JSON)
  - `mask_path` (string)
  - `status` (enum: `draft`, `submitted_for_review`, `approved`, `rejected`)
  - `review_comment` (string, nullable)
  - `reviewed_by` (string, nullable)
  - `created_at` (datetime)

### 3.5 Working Ledger
- **LedgerRecord**:
  - `id` (int, primary key)
  - `timestamp` (datetime)
  - `event_type` (string: `USER_CREATED`, `LOCK_ACQUIRED`, `DRAFT_SAVED`, `VERSION_COMMITTED`, `STATUS_CHANGED`, `DATASET_EXPORTED`)
  - `user_email` (string)
  - `project_id` (int, nullable)
  - `image_id` (int, nullable)
  - `details_json` (JSON)

---

## 4. REST API & WebSocket Protocol

### 4.1 Authentication (`/api/v1/auth`)
- `POST /login`: Stored password authentication (`{email, password}`).
- `POST /email-otp/request`: Trigger 6-digit OTP delivery (`{email}`).
- `POST /email-otp/confirm`: Exchange challenge ID and OTP for a session (`{challenge_id, otp}`).
- `GET /me`: Return the authenticated user profile and roles.
- `POST /logout`: Terminate session and invalidate cookie.

### 4.2 Projects & Images (`/api/v1/projects`)
- `GET /`: List all annotation projects and completion statistics.
- `POST /`: Create a new project with custom classes.
- `GET /{id}`: Project details, image list, classes.
- `POST /{id}/images`: Upload micrographs (single or batch).
- `GET /{id}/images/{img_id}`: Retrieve image metadata, current lock state, and draft.
- `POST /{id}/images/{img_id}/lock`: Acquire or renew exclusive editing lease.
- `DELETE /{id}/images/{img_id}/lock`: Release editing lease.

### 4.3 Annotations (`/api/v1/annotations`)
- `POST /{img_id}/draft`: Save work-in-progress draft (vector + canvas state).
- `POST /{img_id}/commit`: Commit version and submit for review.
- `GET /{img_id}/versions`: Get revision history.
- `POST /{img_id}/review`: Approve or reject with feedback.
- `GET /{img_id}/mask`: Fetch raster mask PNG (binary or multiclass).

### 4.4 Computer Vision Assistance (`/api/v1/tools`)
- `POST /otsu-threshold`: Run automatic Otsu thresholding on an image or specified bounding box ROI.
- `POST /adaptive-threshold`: Run adaptive Gaussian/Mean thresholding with block size & constant C.
- `POST /morphology`: Perform hole filling or small speckle removal on a mask region.
- `POST /vectorize-mask`: Convert binary raster mask into clean polygon contours.

### 4.5 Dataset Export (`/api/v1/export`)
- `POST /{project_id}`: Export dataset archive.
  - Parameters: `format` (`hydride_paired`, `coco`, `yolo`, `numpy`, `zip`), `split` (`{"train": 0.8, "val": 0.1, "test": 0.1}`).
  - Generates ZIP package matching `HydrideSegmentation` paired layout with `dataset_manifest.json`.

### 4.6 WebSocket Live Sync (`/api/v1/ws/collaborate`)
- Broadcasts lock acquisitions, lock releases, and annotation completions to all active clients.

---

## 5. ML Export Contracts (HydrideSegmentation Parity)
The exported dataset bundle structure:
```
dataset_export_<project_id>_<timestamp>/
├── dataset_manifest.json       # Summary, classes, statistics, split manifests
├── train/
│   ├── images/
│   │   ├── img_001.png
│   │   └── img_002.png
│   └── masks/
│       ├── img_001_mask.png   # 0/255 binary or red-dominant RGB
│       └── img_002_mask.png
├── val/
│   ├── images/
│   └── masks/
└── test/
    ├── images/
    └── masks/
```
In `dataset_manifest.json`:
- Class mapping: `{ "0": "Background/Matrix", "1": "Hydride", ... }`
- Image metrics: `width`, `height`, `hydride_area_fraction`, `feature_count`
- Provenance: Export date, project ID, annotator emails, software version.
