"""Command-line entry point: ``online-annotator`` / ``python -m online_annotator``."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from ._version import __version__
from .config import load_settings


def _settings(args: argparse.Namespace):
    overrides = {}
    for key in ("host", "port", "data_dir"):
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    if getattr(args, "demo", False):
        overrides["demo"] = True
    return load_settings(getattr(args, "config", None), **overrides)


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    from .app import create_app

    settings = _settings(args)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(settings, admin_email=os.environ.get("ONLINE_ANNOTATOR_ADMIN_EMAIL"),
                     admin_password=os.environ.get("ONLINE_ANNOTATOR_ADMIN_PASSWORD"))
    print(f"Online Annotator {__version__} -> http://{settings.host}:{settings.port}/  (data: {settings.data_dir})")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))
    return 0


def _session(settings):
    from .db import init_schema, make_engine, make_session_factory

    settings.prepare_storage()
    engine = make_engine(settings.resolved_database_url)
    init_schema(engine)
    return make_session_factory(engine)()


def cmd_create_user(args: argparse.Namespace) -> int:
    from .models import User
    from .services.auth import AuthError, hash_password, normalize_email, validate_password

    settings = _settings(args)
    with _session(settings) as db:
        try:
            email = normalize_email(args.email)
        except AuthError as exc:
            print(exc, file=sys.stderr)
            return 2
        if db.query(User).filter(User.email == email).first():
            print(f"{email} already exists; use reset-password instead.", file=sys.stderr)
            return 2
        password = args.password or getpass.getpass(f"Password for {email}: ")
        try:
            validate_password(password)
        except AuthError as exc:
            print(exc, file=sys.stderr)
            return 2
        db.add(User(email=email, full_name=args.name or email.split("@")[0], is_admin=args.admin,
                    password_hash=hash_password(password)))
        db.commit()
    kind = "administrator" if args.admin else "user (can annotate and review)"
    print(f"Created {kind} {email}.")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    from .models import User
    from .services.auth import end_all_sessions, generate_temporary_password, hash_password

    settings = _settings(args)
    with _session(settings) as db:
        user = db.query(User).filter(User.email == args.email.strip().lower()).first()
        if user is None:
            print(f"No account {args.email}.", file=sys.stderr)
            return 2
        password = generate_temporary_password()
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.is_active = True
        db.commit()
        end_all_sessions(db, user.id)
    print(f"Temporary password for {args.email}: {password}\n(They must change it at next sign-in.)")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    from .services.demo import DEMO_USERS, seed_demo

    settings = _settings(args)
    with _session(settings) as db:
        project = seed_demo(db, settings)
    print(f"Demo project ready: {project.name}")
    for email, _name, is_admin, password in DEMO_USERS:
        print(f"  {'admin' if is_admin else 'user':<6} {email:<24} {password}")
    return 0


def cmd_db_status(args: argparse.Namespace) -> int:
    """Exit 0: up to date (or no database yet); 1: an upgrade will run; 2: database is newer."""
    from .db import SCHEMA_VERSION, make_engine, schema_status

    settings = _settings(args)
    if settings.resolved_database_url.startswith("sqlite:///"):
        folder = settings.data_dir
        if not folder.exists():
            print(f"No database yet in {folder}; the first start creates schema {SCHEMA_VERSION}.")
            return 0
    engine = make_engine(settings.resolved_database_url)
    try:
        status = schema_status(engine)
    finally:
        engine.dispose()
    print(f"Release {__version__} writes database schema {SCHEMA_VERSION}.")
    if status.stored is None:
        print("No database yet; the first start creates it.")
        return 0
    print(f"Stored schema: {status.stored}.")
    if status.newer_than_release:
        print("The database is newer than this release: start the release that wrote it, or restore a backup.")
        return 2
    if status.pending:
        print("Pending upgrade (a backup is saved to <data>/backups/ first):")
        for step in status.pending:
            print(f"  {step.version}: {step.description}")
        return 1
    print("Up to date.")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from .db import SCHEMA_VERSION, init_schema, make_engine

    settings = _settings(args)
    settings.prepare_storage()
    engine = make_engine(settings.resolved_database_url)
    try:
        result = init_schema(engine)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    if result.applied:
        print(f"Upgraded to schema {SCHEMA_VERSION} (steps {', '.join(map(str, result.applied))}).")
        if result.backup:
            print(f"Backup of the previous database: {result.backup}")
    else:
        print(f"Database is at schema {SCHEMA_VERSION}; nothing to do.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="online-annotator", description="Online Annotator server and tools.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", help="YAML configuration file (default: ./config.yml if present)")
        p.add_argument("--data-dir", dest="data_dir", help="where images, masks and the database live")

    serve = sub.add_parser("serve", help="run the web server (upgrades an older database first)")
    common(serve)
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--demo", action="store_true", help="seed demo accounts and synthetic images")
    serve.set_defaults(func=cmd_serve)

    create = sub.add_parser("create-user", help="create an account (every user can annotate and review)")
    common(create)
    create.add_argument("email")
    create.add_argument("--name")
    create.add_argument("--admin", action="store_true",
                        help="also allow administration: projects, classes, accounts")
    create.add_argument("--password", help="omit to be prompted")
    create.set_defaults(func=cmd_create_user)

    reset = sub.add_parser("reset-password", help="issue a temporary password (also re-enables the account)")
    common(reset)
    reset.add_argument("email")
    reset.set_defaults(func=cmd_reset_password)

    demo = sub.add_parser("seed-demo", help="add the demo project and demo accounts")
    common(demo)
    demo.set_defaults(func=cmd_seed_demo)

    status = sub.add_parser("db-status", help="show the stored database schema and any pending upgrade")
    common(status)
    status.set_defaults(func=cmd_db_status)

    migrate = sub.add_parser("migrate", help="back up and upgrade the database without starting the server")
    common(migrate)
    migrate.set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
