"""Governance & platform administration: policy-as-code, demo reset, health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import drop_all, get_db, init_db
from ..enums import EventType
from ..models import PolicyRule, User
from ..serializers import policy_out
from ..services import llm
from ..services.audit import write_audit
from ..services.erp import connector_health
from ..services.events import record_event
from ..services.hitl import expire_overdue_tasks, registered_actions
from .deps import get_current_user, require_admin, require_controller

router = APIRouter(prefix="/admin", tags=["governance"])


class PolicyUpdate(BaseModel):
    value: str | None = None
    enabled: bool | None = None


class GovernanceUpdate(BaseModel):
    enforce_human_in_the_loop: bool | None = None
    global_confidence_floor: float | None = None


@router.get("/policies")
def list_policies(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(PolicyRule).order_by(PolicyRule.category, PolicyRule.name)).scalars().all()
    grouped: dict[str, list[dict]] = {}
    for rule in rows:
        grouped.setdefault(rule.category, []).append(policy_out(rule))
    return {
        "count": len(rows),
        "by_category": grouped,
        "governance": {
            "enforce_human_in_the_loop": settings.enforce_human_in_the_loop,
            "global_confidence_floor": settings.global_confidence_floor,
            "agents_paused": settings.agents_paused,
        },
    }


@router.patch("/policies/{key}")
def update_policy(
    key: str,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_controller),
) -> dict:
    rule = db.execute(select(PolicyRule).where(PolicyRule.key == key)).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if not rule.editable:
        raise HTTPException(status_code=403, detail="This policy is locked.")

    before = {"value": rule.value, "enabled": rule.enabled}
    if payload.value is not None:
        if rule.value_type in {"number", "percent", "money"}:
            try:
                float(payload.value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Value must be numeric.") from exc
        rule.value = payload.value
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    rule.last_changed_by = user.full_name

    write_audit(
        db,
        action="policy.updated",
        description=f"{user.full_name} changed policy '{rule.name}' from {before} to "
                    f"{{'value': '{rule.value}', 'enabled': {rule.enabled}}}.",
        actor=user.full_name,
        actor_type="human",
        actor_role=user.role,
        entity_type="policy",
        entity_id=rule.id,
        entity_label=rule.key,
        before_state=before,
        after_state={"value": rule.value, "enabled": rule.enabled},
    )
    record_event(
        db,
        event_type=EventType.SYSTEM,
        title=f"Policy changed · {rule.name}",
        message=f"{before['value']} → {rule.value}",
        actor=user.full_name,
        actor_type="human",
        severity="warning",
    )
    db.commit()
    return policy_out(rule)


@router.patch("/governance")
def update_governance(
    payload: GovernanceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """The master HITL switch.

    Turning enforcement off does *not* make agents autonomous by itself — each
    agent's autonomy level and every other guardrail still apply. It exists so
    the governance story can be demonstrated, and every flip is audited.
    """
    before = {
        "enforce_human_in_the_loop": settings.enforce_human_in_the_loop,
        "global_confidence_floor": settings.global_confidence_floor,
    }
    if payload.enforce_human_in_the_loop is not None:
        settings.enforce_human_in_the_loop = payload.enforce_human_in_the_loop
        rule = db.execute(
            select(PolicyRule).where(PolicyRule.key == "hitl.enforce_global")
        ).scalar_one_or_none()
        if rule is not None:
            rule.value = "true" if payload.enforce_human_in_the_loop else "false"
            rule.last_changed_by = user.full_name
    if payload.global_confidence_floor is not None:
        if not 0.0 <= payload.global_confidence_floor <= 1.0:
            raise HTTPException(status_code=422, detail="Confidence floor must be between 0 and 1.")
        settings.global_confidence_floor = payload.global_confidence_floor

    write_audit(
        db,
        action="governance.updated",
        description=f"{user.full_name} changed platform governance settings.",
        actor=user.full_name,
        actor_type="human",
        actor_role=user.role,
        entity_type="system",
        entity_label="Governance",
        before_state=before,
        after_state={
            "enforce_human_in_the_loop": settings.enforce_human_in_the_loop,
            "global_confidence_floor": settings.global_confidence_floor,
        },
    )
    record_event(
        db,
        event_type=EventType.SYSTEM,
        title="Governance settings changed",
        message=f"Human-in-the-loop enforcement is now "
                f"{'ON' if settings.enforce_human_in_the_loop else 'OFF'}.",
        actor=user.full_name,
        actor_type="human",
        severity="critical" if not settings.enforce_human_in_the_loop else "success",
    )
    db.commit()
    return {
        "enforce_human_in_the_loop": settings.enforce_human_in_the_loop,
        "global_confidence_floor": settings.global_confidence_floor,
        "agents_paused": settings.agents_paused,
    }


@router.post("/housekeeping")
def housekeeping(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    expired = expire_overdue_tasks(db)
    db.commit()
    return {"checkpoints_marked_overdue": expired}


@router.post("/reset-demo")
def reset_demo(db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    """Drop and rebuild the demo dataset — the button you press between client meetings."""
    from ..seed import seed_all

    db.close()
    drop_all()
    init_db()
    from ..database import SessionLocal

    fresh = SessionLocal()
    try:
        result = seed_all(fresh, force=True)
    finally:
        fresh.close()
    return {"reset": True, **result}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    return {
        "status": "ok",
        "version": settings.version,
        "environment": settings.environment,
        "database": settings.database_url.split("://")[0],
        "reasoning_engine": llm.engine_status(),
        "erp_connectors": connector_health(),
        "governance": {
            "enforce_human_in_the_loop": settings.enforce_human_in_the_loop,
            "agents_paused": settings.agents_paused,
            "global_confidence_floor": settings.global_confidence_floor,
        },
        "executable_actions": len(registered_actions()),
    }
