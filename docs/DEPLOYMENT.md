# Deployment and operations

Online Annotator is one Python process with a data directory. It needs no internet access,
no external services and no JavaScript build. Two supported ways to run it:

1. **Inside the ml_server suite** — deployed, upgraded and rolled back by `ml_server_deploy`
   (`manifest.yml`, component `annotator`), linked from the portal catalog.
2. **Standalone** — on any Linux or Windows machine, as below.

## Requirements

- Python ≥ 3.10 (the office suite uses 3.12) and the packages in `requirements.txt`, all on the
  office pip mirror. OpenCV (`opencv-python-headless`) is optional and only enables YOLO export.
- Disk: originals + masks + exports. Budget roughly 3 × the total size of the uploaded images.
- Browsers: current Chrome, Edge or Firefox.

## Standalone installation (Ubuntu)

```bash
sudo useradd --system --home /var/lib/online-annotator --create-home annotator
sudo mkdir -p /opt/online-annotator /etc/online-annotator
sudo tar -xzf online-annotator-1.0.0.tar.gz -C /opt/online-annotator   # or git clone on the internet side
sudo ln -sfn /opt/online-annotator/OnlineAnnotator-1.0.0 /opt/online-annotator/current
sudo python3 -m venv /opt/online-annotator/venv
sudo /opt/online-annotator/venv/bin/pip install -r /opt/online-annotator/current/requirements.txt
sudo cp /opt/online-annotator/current/deploy/online-annotator.env.example /etc/online-annotator/online-annotator.env
sudo chmod 600 /etc/online-annotator/online-annotator.env      # edit: portal URL, admin e-mail …
sudo cp /opt/online-annotator/current/deploy/online-annotator.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now online-annotator
curl -s http://127.0.0.1:5070/api/health    # {"status":"ok","tool_id":"online-annotator","version":"1.0.0"}
```

### First administrator

When the user table is empty the service creates the first administrator:

- from `ONLINE_ANNOTATOR_ADMIN_EMAIL` / `ONLINE_ANNOTATOR_ADMIN_PASSWORD` if set (remove them
  from the env file afterwards), or
- with a generated one-time password printed to the journal and written to
  `<data_dir>/initial_admin_password.txt`. The administrator must change it at first sign-in;
  then delete the file.

Command-line helpers (run as the service user, same env file):

```bash
python -m online_annotator create-user lead@lab.example --role admin --name "Lead Scientist"
python -m online_annotator reset-password someone@lab.example     # also re-enables a disabled account
```

## Inside the ml_server suite

`ml_server_deploy/manifest.yml` declares the component:

```yaml
annotator:
  repo: kvmani/OnlineAnnotator
  ref: v1.0.0
  port: 5070
  health: /api/health
  public_url_env: ONLINE_ANNOTATOR_URL          # the portal catalog links here
  start: "{venv}/bin/python -m online_annotator serve --host {bind} --port {port}"
  env_file: shared/config/ml-platform.env
  environment:
    PYTHONPATH: "{current}/apps/OnlineAnnotator/src"
    ONLINE_ANNOTATOR_DATA_DIR: "{root}/shared/data/online_annotator"
    ONLINE_ANNOTATOR_PORTAL_URL: ":5000/"        # same host the user typed, portal port
```

The data directory lives under `shared/`, so upgrades and rollbacks never touch it. The
portal link is host-relative, so it works from every desk without knowing the server's
address. Optional settings (first administrator, SMTP) go into
`shared/config/ml-platform.env` as `ONLINE_ANNOTATOR_*` lines; values there override the
unit's `Environment=` lines. On the first start, read the generated administrator password
from `shared/data/online_annotator/initial_admin_password.txt` (or the journal).

## Configuration

See `config.example.yml` (every key, with its default) and `deploy/online-annotator.env.example`.
Production checklist:

- [ ] `demo` is **false** (the banner "Demo mode" must not appear).
- [ ] `host: 0.0.0.0` only if other machines connect directly; otherwise keep the gateway in front.
- [ ] `portal_url` set so users can get back to the tools portal.
- [ ] `cookie_secure: true` when served over HTTPS.
- [ ] `allow_self_approval: false` unless a single person does all the work.
- [ ] SMTP configured before enabling `self_registration`.
- [ ] Backups scheduled (below) and a restore rehearsed once.

## Reverse proxy / gateway

Host-based routing (e.g. `annotator.tools.<domain>` → `127.0.0.1:5070`) is the platform default.
All browser URLs are relative, so a path prefix also works when the proxy strips it. Allow request
bodies of at least `max_upload_mb`, and timeouts of ≥ 300 s for large exports. Forwarded headers are
trusted only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`).

## Backups

Everything is in `data_dir`. A consistent backup while running:

```bash
D=/var/lib/online-annotator; B=/backup/online-annotator/$(date +%F)
mkdir -p "$B"
sqlite3 "$D/online_annotator.sqlite3" ".backup '$B/online_annotator.sqlite3'"
rsync -a --exclude 'online_annotator.sqlite3*' "$D/" "$B/"
```

Restore: stop the service, copy the backup back into `data_dir`, start the service. The label
PNGs and the audit log are plain files and can be inspected without the application.

## Upgrade and rollback

1. Back up (above). 2. Install the new release next to the old one and switch the `current`
link. 3. Restart and check `/api/health` shows the new version. 4. Rollback = switch the link
back and restart. The database records its schema version; a release refuses to start on a
schema newer than it understands, so an accidental downgrade fails loudly instead of corrupting
data.

## Monitoring

- `GET /api/health` — liveness (cheap).
- `GET /api/health/deep` — database query and storage check.
- Journal: `journalctl -u online-annotator` (sign-ins, errors). Activity per project is in the UI
  and in `data_dir/audit/audit.jsonl` (one JSON object per line).

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| "Request blocked: missing client header" | A proxy strips `X-Requested-With`; allow the header. |
| Users are signed out quickly | `session_hours` too small, or clocks differ between proxy and server. |
| "Database schema … is newer than this release" | A newer release ran on this data; start that release or restore a matching backup. |
| Uploads fail at the proxy | Raise the proxy body-size limit to `max_upload_mb`. |
| YOLO option greyed out | Install `opencv-python-headless` in the service environment. |
