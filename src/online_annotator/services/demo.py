"""Synthetic demonstration data and first-run bootstrap.

Demo micrographs are generated from a fixed seed, so no real (possibly restricted)
specimen image ever needs to be distributed with the source code.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFilter
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import LabelClass, Project, User
from . import audit
from .auth import generate_temporary_password, hash_password

logger = logging.getLogger(__name__)

DEMO_PROJECT = "Demo - Hydride platelets in Zr alloy"
# (e-mail, name, is administrator, password). Two ordinary users, so one can submit work
# and the other review it -- each of them can do both.
DEMO_USERS = (
    ("admin@demo.local", "Demo Administrator", True, "admin-demo-1"),
    ("arun@demo.local", "Arun Kumar", False, "arun-demo-1"),
    ("riya@demo.local", "Riya Sharma", False, "riya-demo-1"),
)
DEMO_CLASSES = (
    (1, "Hydride", "#FF0000", "Dark, thin, elongated platelets. Trace the full visible length; include the "
                             "faint tips. Do not include grain-boundary lines."),
    (2, "Pore / crack", "#2F80ED", "Round or irregular dark voids and cracks that are clearly not platelets."),
)
DEMO_GUIDELINES = """1. Label every hydride platelet with class 1 (Hydride), including faint tips.
2. Leave grain boundaries and polishing scratches as background.
3. Pores and cracks are class 2.
4. When unsure, leave the pixel unlabelled and write a note on submission.
5. Use the Box threshold (T) or Polygon threshold (R) tool for dense regions, then clean up with the brush."""


def synthetic_micrograph(seed: int, width: int = 640, height: int = 480) -> bytes:
    """Grainy matrix with dark oriented platelets and a few pores (PNG bytes)."""
    rng = np.random.default_rng(seed)
    n_grains = 36
    sx = rng.uniform(0, width, n_grains)
    sy = rng.uniform(0, height, n_grains)
    yy, xx = np.mgrid[0:height, 0:width]
    grain = np.argmin((xx[..., None] - sx) ** 2 + (yy[..., None] - sy) ** 2, axis=2)
    tone = rng.uniform(165, 205, n_grains)
    base = tone[grain]
    boundary = np.zeros_like(grain, dtype=bool)
    boundary[:, 1:] |= grain[:, 1:] != grain[:, :-1]
    boundary[1:, :] |= grain[1:, :] != grain[:-1, :]
    base[boundary] -= 28

    img = PILImage.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    angle0 = rng.uniform(-20, 20)
    for _ in range(rng.integers(14, 22)):
        cx, cy = rng.uniform(20, width - 20), rng.uniform(20, height - 20)
        length = rng.uniform(40, 150)
        angle = np.radians(angle0 + rng.normal(0, 12))
        pts = []
        for t in np.linspace(-0.5, 0.5, 8):
            bend = 6 * np.sin(t * np.pi * 2 + rng.uniform(0, 3))
            pts.append((cx + t * length * np.cos(angle) - bend * np.sin(angle),
                        cy + t * length * np.sin(angle) + bend * np.cos(angle)))
        draw.line(pts, fill=int(rng.uniform(35, 70)), width=int(rng.integers(2, 5)), joint="curve")
    for _ in range(rng.integers(2, 5)):
        cx, cy, r = rng.uniform(30, width - 30), rng.uniform(30, height - 30), rng.uniform(4, 10)
        draw.ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8), fill=25)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    arr = np.asarray(img, dtype=np.float64) + rng.normal(0, 6, (height, width))
    out = PILImage.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class BootstrapResult:
    created: bool
    email: str | None = None
    password: str | None = None


def bootstrap_admin(db: Session, settings: Settings, email: str | None, password: str | None) -> BootstrapResult:
    """Create the first administrator when the user table is empty.

    With no password supplied a random one-time password is generated; it is printed
    to the server console and written to ``<data>/initial_admin_password.txt`` and
    must be changed at first sign-in.
    """
    if db.query(User).count():
        return BootstrapResult(created=False)
    email = (email or "admin@localhost.localdomain").strip().lower()
    generated = password is None
    password = password or generate_temporary_password()
    db.add(User(email=email, full_name="Administrator", is_admin=True, password_hash=hash_password(password),
                must_change_password=generated))
    db.commit()
    audit.record(db, settings.audit_file, "system", "user_created", f"First administrator {email} created.")
    if generated:
        note = settings.data_dir / "initial_admin_password.txt"
        note.write_text(
            f"First administrator for Online Annotator\n  e-mail:   {email}\n  password: {password}\n"
            "You will be asked to change it at first sign-in. Delete this file afterwards.\n",
            encoding="utf-8",
        )
    return BootstrapResult(created=True, email=email, password=password if generated else None)


def seed_demo(db: Session, settings: Settings, image_count: int = 6) -> Project:
    """Create demo accounts and a demo project with synthetic micrographs (idempotent)."""
    from .projects import add_uploaded_image  # local import avoids a cycle

    for email, name, is_admin, password in DEMO_USERS:
        if not db.query(User).filter(User.email == email).first():
            db.add(User(email=email, full_name=name, is_admin=is_admin, password_hash=hash_password(password)))
    db.commit()
    project = db.query(Project).filter(Project.name == DEMO_PROJECT).first()
    if project is None:
        project = Project(name=DEMO_PROJECT, created_by="admin@demo.local",
                          description="Synthetic Zircaloy-like micrographs for trying the workflow safely.",
                          guidelines=DEMO_GUIDELINES)
        for index, name, color, desc in DEMO_CLASSES:
            project.classes.append(LabelClass(index=index, name=name, color=color, description=desc))
        db.add(project)
        db.commit()
        admin = db.query(User).filter(User.email == "admin@demo.local").one()
        splits = ["train", "train", "train", "train", "val", "test"]
        for i in range(image_count):
            add_uploaded_image(db, settings, project, admin, synthetic_micrograph(1000 + i),
                               f"zr_hydride_demo_{i + 1:02d}.png", split=splits[i % len(splits)])
        audit.record(db, settings.audit_file, "system", "demo_seeded",
                     f"Demo project with {image_count} synthetic micrographs created.", project_id=project.id)
    return project
