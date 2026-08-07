"""Shared API dependencies.

Demo authentication: the client presents a persona id in `X-User-Id` (or a
bearer token holding the same value). Role-based authority is fully enforced
from that point on — swapping personas is the point of the demo, so switching
is cheap, but what each persona may *decide* is not.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import ROLE_AUTHORITY, Role
from ..models import User


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    authorization: str | None = Header(default=None),
) -> User:
    token = x_user_id
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in as one of the demo personas to continue.",
        )

    user = db.get(User, token)
    if user is None:
        user = db.execute(select(User).where(User.email == token)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or inactive user.")
    return user


def require_role(minimum: str):
    def guard(user: User = Depends(get_current_user)) -> User:
        if ROLE_AUTHORITY.get(user.role, 0) < ROLE_AUTHORITY.get(str(minimum), 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{minimum}' role or above; you are '{user.role}'.",
            )
        return user

    return guard


require_manager = require_role(Role.AP_MANAGER)
require_controller = require_role(Role.CONTROLLER)
require_admin = require_role(Role.ADMIN)
