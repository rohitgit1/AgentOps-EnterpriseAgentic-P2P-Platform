"""Persona sign-in for the demo."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import ROLE_LABELS
from ..models import Notification, User
from ..serializers import notification_out, user_out
from .deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str


@router.get("/personas")
def list_personas(db: Session = Depends(get_db)) -> list[dict]:
    """The persona switcher. Each one exercises a different HITL authority level."""
    users = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    blurbs = {
        "ap_clerk": "Reviews extraction, matching and exception proposals.",
        "ap_manager": "Approves ERP posting, escalations and reroutes.",
        "controller": "Releases payments and approves supplier master changes.",
        "procurement": "Owns contract breaches and purchase request approvals.",
        "treasury": "Owns the payment run and discount capture.",
        "cfo": "Receives executive alerts; unlimited approval authority.",
        "admin": "Configures agent autonomy and platform policy.",
    }
    return [
        {**user_out(user), "blurb": blurbs.get(user.role, ""), "role_label": ROLE_LABELS.get(user.role, user.role)}
        for user in sorted(users, key=lambda u: u.full_name)
    ]


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="No such persona.")
    return {"token": user.id, "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_out(user)


@router.get("/notifications")
def notifications(
    db: Session = Depends(get_db), user: User = Depends(get_current_user), limit: int = 30
) -> list[dict]:
    rows = db.execute(
        select(Notification)
        .where((Notification.user_id == user.id) | (Notification.target_role == user.role))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [notification_out(n) for n in rows]


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    note = db.get(Notification, notification_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    note.read = True
    db.commit()
    return {"ok": True}
