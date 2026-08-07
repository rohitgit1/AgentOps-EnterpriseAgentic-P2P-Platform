"""Human-in-the-loop API — the approval inbox and the decision endpoint.

This is the control surface for the whole platform: no agent action reaches a
system of record except through `POST /hitl/tasks/{id}/decide`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import (
    ACTION_LABELS,
    HumanDecision,
    HumanTaskStatus,
    ROLE_AUTHORITY,
    ROLE_LABELS,
)
from ..models import AgentExecution, HumanTask, User
from ..serializers import execution_out, human_task_out
from ..services import hitl as hitl_service
from ..services.policy import can_decide
from .deps import get_current_user

router = APIRouter(prefix="/hitl", tags=["human-in-the-loop"])


class DecisionRequest(BaseModel):
    decision: str = Field(..., description="approve | reject | modify_and_approve | request_info | escalate")
    notes: str | None = None
    modified_payload: dict | None = None


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: str | None = Query(default="pending"),
    stage: str | None = None,
    agent_key: str | None = None,
    risk_level: str | None = None,
    mine_only: bool = Query(default=False, description="Only tasks this persona is authorised to decide"),
    limit: int = 200,
) -> dict:
    query = select(HumanTask).order_by(HumanTask.created_at.desc())
    if status and status != "all":
        query = query.where(HumanTask.status == status)
    if stage:
        query = query.where(HumanTask.stage == stage)
    if agent_key:
        query = query.where(HumanTask.agent_key == agent_key)
    if risk_level:
        query = query.where(HumanTask.risk_level == risk_level)

    tasks = db.execute(query.limit(limit)).scalars().all()
    if mine_only:
        tasks = [t for t in tasks if can_decide(user.role, t.required_role)]

    items = []
    for task in tasks:
        data = human_task_out(task)
        data["can_decide"] = can_decide(user.role, task.required_role)
        data["blocked_reason"] = (
            None if data["can_decide"]
            else f"Requires {ROLE_LABELS.get(task.required_role, task.required_role)} authority."
        )
        items.append(data)

    return {
        "count": len(items),
        "actionable_by_me": len([i for i in items if i["can_decide"]]),
        "items": items,
    }


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    task = db.get(HumanTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found.")
    data = human_task_out(task, detail=True)
    data["can_decide"] = can_decide(user.role, task.required_role)
    data["your_role"] = user.role
    data["authority_gap"] = max(
        0, ROLE_AUTHORITY.get(task.required_role, 0) - ROLE_AUTHORITY.get(user.role, 0)
    )
    if task.execution_id:
        execution = db.get(AgentExecution, task.execution_id)
        data["execution"] = execution_out(execution, detail=True) if execution else None
    return data


@router.post("/tasks/{task_id}/decide")
def decide_task(
    task_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    task = db.get(HumanTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found.")

    valid = {
        HumanDecision.APPROVE, HumanDecision.REJECT, HumanDecision.MODIFY_AND_APPROVE,
        HumanDecision.REQUEST_INFO, HumanDecision.ESCALATE,
    }
    if payload.decision not in valid:
        raise HTTPException(status_code=422, detail=f"decision must be one of {sorted(valid)}")

    if payload.decision in {HumanDecision.REJECT, HumanDecision.REQUEST_INFO} and not payload.notes:
        raise HTTPException(
            status_code=422,
            detail="A written reason is required when rejecting or requesting more information.",
        )

    try:
        result = hitl_service.decide(
            db,
            task=task,
            decision=payload.decision,
            user=user,
            notes=payload.notes,
            modified_payload=payload.modified_payload,
        )
    except hitl_service.HITLError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    db.commit()
    return {**result, "task": human_task_out(db.get(HumanTask, task_id), detail=True)}


@router.post("/tasks/bulk-decide")
def bulk_decide(
    task_ids: list[str],
    decision: str = Query(default=HumanDecision.APPROVE),
    notes: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Batch approval for low-risk, high-volume checkpoints.

    Anything irreversible, high-risk or requiring dual approval is refused here
    on purpose — bulk actions must not become a way around individual review.
    """
    applied, refused = [], []
    for task_id in task_ids:
        task = db.get(HumanTask, task_id)
        if task is None:
            refused.append({"task_id": task_id, "reason": "not found"})
            continue
        if not task.reversible or task.risk_level in {"high", "critical"} or task.dual_approval_required:
            refused.append({
                "task_id": task_id,
                "task_number": task.task_number,
                "reason": "Irreversible, high-risk or dual-approval items must be reviewed individually.",
            })
            continue
        try:
            hitl_service.decide(db, task=task, decision=decision, user=user, notes=notes)
            applied.append({"task_id": task_id, "task_number": task.task_number})
        except hitl_service.HITLError as exc:
            refused.append({"task_id": task_id, "task_number": task.task_number, "reason": str(exc)})
    db.commit()
    return {"applied": applied, "refused": refused}


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    tasks = db.execute(
        select(HumanTask).where(HumanTask.status == HumanTaskStatus.PENDING)
    ).scalars().all()
    mine = [t for t in tasks if can_decide(user.role, t.required_role)]
    by_action: dict[str, int] = {}
    for task in tasks:
        label = ACTION_LABELS.get(task.action_kind, task.action_kind)
        by_action[label] = by_action.get(label, 0) + 1
    return {
        "pending_total": len(tasks),
        "pending_for_me": len(mine),
        "value_awaiting_decision": round(sum(t.financial_impact_usd or 0.0 for t in tasks), 2),
        "irreversible_pending": len([t for t in tasks if not t.reversible]),
        "dual_approval_pending": len([t for t in tasks if t.dual_approval_required]),
        "by_action": by_action,
        "by_risk": {
            level: len([t for t in tasks if t.risk_level == level])
            for level in ("low", "medium", "high", "critical")
        },
    }
