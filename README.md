# OnlineAnnotator

**Online Microstructural Semantic Segmentation Annotator & ML Ground-Truth Preparation Workbench**

*Intranet-Native • Multi-User Concurrency • HydrideSegmentation Ready • ml_server Integrated*

---

## 1. Overview

**OnlineAnnotator** is a high-performance web application designed for office intranets to create, review, and curate pixel-precise ground-truth annotations for metallurgical microstructures.

### Key Capabilities:
- **Intranet-First Architecture**: Zero external cloud or CDN dependencies; self-contained FastAPI backend with integrated SQLite (WAL mode) and modular HTML5 Canvas SPA frontend.
- **Office Email Identity**: Usernames are strictly corporate email addresses (e.g. `user@barc.gov.in`, `analyst@office.local`).
- **Dual Authentication**: Stored password login (`bcrypt`) + 6-digit Office Email OTP challenge delivery with development console fallback.
- **Multi-User Parallel Annotation**: Exclusive lease-based image locking with automatic timeout and WebSocket synchronization prevents annotators from colliding or overwriting each other's work.
- **Material Science & Hydride Tooling**:
  - Interactive Brush, Eraser, Polygon, and Freehand tools.
  - Smart Otsu Wand auto-thresholding specially tuned for dark hydride platelets in zirconium matrices.
  - Micrograph visual enhancements (contrast, brightness, color inversion) to highlight faint phases.
- **Persistent Data & Session Resumption**:
  - Auto-save drafts and full revision history (Draft -> Review -> Approved / Changes Requested).
  - "Resume Work" button instantly restores an annotator's exact active image, pan, and zoom level.
  - Working ledger mirrored in `data/ledger.json` for continuous auditability.
- **Direct ML Dataset Packaging**:
  - HydrideSegmentation paired folder structure (`images/` and `masks/`, `{stem}_mask.png`).
  - Binary masks (0/255), Red-dominant RGB masks (matching Mado pipeline), and Indexed Multiclass masks.
  - Standard COCO JSON, YOLO segmentation polygons, NumPy (`.npz`), and partitioned ZIP dataset bundles.

---

## 2. Quick Start

### 2.1 Starting the Server
Run with Python:
```powershell
python run.py
```
Or use the PowerShell launcher:
```powershell
.\start_annotator.ps1
```
The server will start at `http://127.0.0.1:5070`.

### 2.2 Default Accounts (Seeded)
- **Email**: `admin@office.local`
- **Password**: `Admin@123`
- *Or log in using any office email address via 6-digit Email OTP!*

---

## 3. Keyboard Shortcuts Reference

| Shortcut | Action |
|---|---|
| `B` | Brush Tool |
| `E` | Eraser Tool |
| `P` | Polygon Tool (Click points, Double-click to close) |
| `W` | Smart Otsu Wand Tool (Drag box to threshold ROI) |
| `Space` or `V` | Pan Tool (Click and drag to pan canvas) |
| `[` / `]` | Decrease / Increase Brush Radius |
| `Ctrl + Z` | Undo last action |
| `Ctrl + Y` | Redo action |
| `Ctrl + S` | Save Draft |
| `Left Arrow` | Previous Image |
| `Right Arrow` | Next Image |
| `1`, `2`, `3`, `4` | Select Microstructure Class |

---

## 4. Platform Integration

### 4.1 Integration with `ml_server`
OnlineAnnotator is registered as a first-class tool in the central `ml_server` catalog:
- **Tool ID**: `online-annotator`
- **URL**: `http://127.0.0.1:5070` (configurable via `ONLINE_ANNOTATOR_URL`)
- **Category**: Microstructure

### 4.2 Integration with `HydrideSegmentation`
Exported dataset packages strictly match the expectations of `C:\Users\kvman\HydrideSegmentation\configs\hydride\prepare_dataset.paired_rgb_mask.mado.yml`:
- Paired folders: `train/images`, `train/masks`, `val/images`, `val/masks`, `test/images`, `test/masks`
- Binary or Red-dominant masks (`R >= 200, G <= 60, B <= 60`)
- `dataset_manifest.json` reporting total features, hydride area fractions, and sample metadata.

---

## 5. Automated Tests

Execute the full verification suite:
```powershell
python -m pytest tests -v
```
