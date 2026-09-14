# Online Annotator

**Create, review and export pixel-exact semantic-segmentation ground truth for microstructure
images — on your office intranet, in the browser, with no installation for users.**

Part of the office scientific-tools platform (`ml_server`); first customer:
[HydrideSegmentation](../HydrideSegmentation). Version **2.0.0**.

## What it does

- **Annotate** — brush, eraser, polygon, lasso, a microstructure-aware magic wand, an
  Otsu box threshold, fill, speck removal and hole filling; unlimited classes per project;
  undo/redo; zoom, pan, contrast and outline views; autosave. What you see is exactly what is
  saved: labels are integer class values per pixel, never blended colours.
- **Review** — every user both annotates and reviews, switching with an **Annotate / Review**
  control at the top of the page. Submissions are approved, corrected or returned with a
  comment by someone else — nobody reviews their own work — and every submission is an
  immutable, fingerprinted version.
- **Collaborate** — each image is reserved for one editor at a time; the gallery shows who is
  working where; "Annotate next" and "Review next" hand everyone the right image for their
  current mode.
- **Export** — approved ground truth as a ZIP ready for HydrideSegmentation (`pairs/x.png` +
  `pairs/x_mask.png`) or train/val/test folders, with binary, red, indexed or colour masks,
  exact COCO RLE, optional YOLO polygons, and a manifest recording who annotated and approved
  every image.
- **Active learning** — import model predictions as a starting point, correct, approve, export,
  retrain.
- **Self-explanatory** — a first-run quick start, `(?)` explanations at every decision, a hint
  bar for the active tool, and a full Help centre (`/help`).
- **Intranet-native** — one Python process, SQLite, no internet, no CDN, no external identity
  provider; office e-mail accounts, optional e-mail sign-in codes through your SMTP relay.

## Try it in two minutes (demo mode)

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m online_annotator serve --demo --data-dir dev-data
```

Windows: `.\scripts\start_dev.ps1`. Open <http://127.0.0.1:5070/> and pick a demo account:
Arun or Riya (ordinary users who can both annotate and review — submit as one, review as the
other in a private window) or the administrator. Demo mode generates synthetic Zr-hydride
micrographs; never use it on a production server.

## Install for real use

```bash
python -m pip install .                      # provides the `online-annotator` command
online-annotator serve --host 0.0.0.0 --port 5070 --data-dir /var/lib/online-annotator
```

The first start creates an administrator with a one-time password (printed and written to
`<data-dir>/initial_admin_password.txt`) unless `ONLINE_ANNOTATOR_ADMIN_EMAIL` and
`ONLINE_ANNOTATOR_ADMIN_PASSWORD` are set. Other commands:

```bash
online-annotator create-user name@lab.example --name "Full Name"          # annotates and reviews
online-annotator create-user lead@lab.example --name "Lead" --admin       # also administers
online-annotator reset-password name@lab.example
online-annotator db-status            # stored database schema and any pending upgrade
online-annotator migrate              # back up and upgrade the database without starting
online-annotator seed-demo            # add the demo project to an existing installation
```

(Without installing, use `python -m online_annotator …` with `PYTHONPATH=src`.)

Configuration: `config.example.yml` (all keys and defaults) or `ONLINE_ANNOTATOR_*` environment
variables. Operations, systemd, backups, upgrades: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Platform integration

- **ml_server portal** — catalog card `online-annotator` links to `ONLINE_ANNOTATOR_URL`
  (default `http://127.0.0.1:5070`); scientific help at `/tools/online-annotator/help`.
- **ml_server_deploy** — component `annotator`, port 5070, health `/api/health`.
- **Health contract** — `GET /api/health` → `{"status": "ok", "tool_id": "online-annotator", "version": "2.0.0"}`.
- **HydrideSegmentation** — exports feed `prepare_dataset` directly
  ([docs/EXPORT_FORMAT.md](docs/EXPORT_FORMAT.md)); model predictions can be imported as
  pre-annotations.

## Development

```bash
python -m pip install -r requirements-test.txt
python -m pytest                 # API, services, workflow, modes, migrations, exports + Node label-engine tests
python -m ruff check src tests
npm install && npm run test:browser   # Playwright journeys in Chromium (fresh demo server)
```

Read [AGENTS.md](AGENTS.md) first: it holds the cardinal rules (exact ground truth, resumable
work landed on `main`, ordinary-user-first UX with help in the same change, server-side
enforcement, intranet self-sufficiency). Progress of the current goal:
[docs/development/active_task_progress.md](docs/development/active_task_progress.md).

## Documentation

| Document | Contents |
| --- | --- |
| In-app Help centre (`/help`) | the user guide: getting started, Annotate and Review modes, tools, reviewing, exporting, troubleshooting |
| [SPECIFICATIONS.md](SPECIFICATIONS.md) | privilege and working modes, workflow, API, schema, requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | components, raster-label design, privilege vs mode, migrations, concurrency |
| [docs/EXPORT_FORMAT.md](docs/EXPORT_FORMAT.md) | dataset ZIP and manifest contract |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | installation, configuration, backups, upgrade/rollback |
| [CHANGELOG.md](CHANGELOG.md) | release history |

## Licence

MIT.
