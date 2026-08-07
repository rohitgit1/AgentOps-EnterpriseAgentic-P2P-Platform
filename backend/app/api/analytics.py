"""Dashboards, SLA command centre, audit trail and the live event stream."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User, WorkflowEvent
from ..serializers import audit_out, event_out
from ..services import metrics
from ..services.audit import verify_chain
from ..services.events import bus
from .deps import get_current_user

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    return metrics.dashboard(db)


@router.get("/slas")
def slas(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    return metrics.sla_overview(db)


@router.get("/events")
def list_events(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    entity_id: str | None = None,
    event_type: str | None = None,
    limit: int = 120,
) -> list[dict]:
    query = select(WorkflowEvent).order_by(WorkflowEvent.created_at.desc())
    if entity_id:
        query = query.where(WorkflowEvent.entity_id == entity_id)
    if event_type:
        query = query.where(WorkflowEvent.event_type == event_type)
    rows = db.execute(query.limit(limit)).scalars().all()
    return [event_out(e) for e in rows]


@router.get("/events/stream")
async def stream_events(request: Request) -> StreamingResponse:
    """Server-sent events feed powering the live activity rail.

    Deliberately unauthenticated so the demo's live feed keeps flowing across
    persona switches; it carries the same data as `GET /events`.
    """
    queue = bus.subscribe()

    async def generator():
        try:
            for event in bus.recent(25):
                yield f"data: {json.dumps(event)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/audit")
def audit_trail(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    entity_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    limit: int = 200,
) -> dict:
    query = select(AuditLog).order_by(AuditLog.sequence.desc())
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor_type:
        query = query.where(AuditLog.actor_type == actor_type)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    rows = db.execute(query.limit(limit)).scalars().all()
    return {
        "count": len(rows),
        "items": [audit_out(a) for a in rows],
    }


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Recompute the audit hash chain to prove nothing was altered after the fact."""
    return verify_chain(db)


@router.get("/audit/export")
def audit_export(
    db: Session = Depends(get_db), _: User = Depends(get_current_user), limit: int = Query(default=5000)
) -> StreamingResponse:
    """CSV export for the audit pack."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.sequence.asc()).limit(limit)).scalars().all()

    def generate():
        yield "sequence,timestamp,actor,actor_type,actor_role,action,entity_type,entity_label," \
              "description,confidence,hitl_enforced,hash\n"
        for row in rows:
            description = (row.description or "").replace('"', "'").replace("\n", " ")
            yield (
                f"{row.sequence},{row.timestamp.isoformat()},\"{row.actor}\",{row.actor_type},"
                f"{row.actor_role or ''},{row.action},{row.entity_type or ''},"
                f"\"{row.entity_label or ''}\",\"{description}\","
                f"{row.confidence if row.confidence is not None else ''},{row.hitl_enforced},"
                f"{row.hash_chain}\n"
            )

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=p2p-agentops-audit-trail.csv"},
    )
