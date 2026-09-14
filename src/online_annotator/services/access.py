"""Account privilege and working mode: who may do what, kept deliberately apart.

Every active user can annotate *and* review. What they are doing right now is their
``active_mode``:

* **Annotate** -- edit images that are not waiting for review, import masks, submit;
* **Review** -- correct a submission from someone else and approve it or request changes.

The mode is persisted per account and enforced here on the server (AGENTS.md rule 4), so a
stale browser tab can never approve while its owner believes they are annotating.

Being an **administrator** is a separate privilege (projects, classes, accounts, deleting
images, breaking leases). It never depends on the working mode, and switching mode never adds
or removes a privilege.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import WORKING_MODES, User

ANNOTATE = "annotate"
REVIEW = "review"
MODE_NAMES = {ANNOTATE: "Annotate", REVIEW: "Review"}


class Refused(Exception):
    """An action the rules do not allow. The message is safe to show; ``status`` is the HTTP code."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def set_mode(db: Session, user: User, mode: str) -> bool:
    """Switch the user's working mode. Returns whether it changed."""
    if mode not in WORKING_MODES:
        raise Refused("Choose Annotate or Review mode.", 422)
    changed = user.active_mode != mode
    user.active_mode = mode
    db.commit()
    return changed


def require_admin(user: User) -> None:
    if not user.is_admin:
        raise Refused("This action needs an administrator.", 403)


def require_mode(user: User, mode: str, action: str) -> None:
    """Refuse ``action`` unless the user is working in ``mode``."""
    if user.active_mode != mode:
        current = MODE_NAMES.get(user.active_mode, user.active_mode)
        raise Refused(f"You are in {current} mode. Switch to {MODE_NAMES[mode]} mode at the top of the page "
                      f"to {action}.")


def may_review(settings: Settings, user: User, submitted_by: str) -> bool:
    """A second person reviews every submission, unless self-approval is configured."""
    return submitted_by != user.email or settings.allow_self_approval
