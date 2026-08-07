"""Immutable, hash-chained audit trail.

Every applied action and every human decision writes one row. Each row's hash
covers the previous row's hash, so tampering with history is detectable — the
control the audit team asks about first.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog
from .events import _jsonable


def _digest(previous_hash: str | None, row: dict[str, Any]) -> str:
    body = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(f"{previous_hash or 'genesis'}|{body}".encode()).hexdigest()


def write_audit(
    db: Session,
    *,
    action: str,
    description: str = "",
    actor: str = "system",
    actor_type: str = "system",
    actor_role: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    agent_key: str | None = None,
    execution_id: str | None = None,
    human_task_id: str | None = None,
    confidence: float | None = None,
    hitl_enforced: bool = True,
) -> AuditLog:
    previous = db.execute(
        select(AuditLog.hash_chain).order_by(AuditLog.sequence.desc()).limit(1)
    ).scalar_one_or_none()

    payload = {
        "action": action,
        "actor": actor,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": _jsonable(before_state or {}),
        "after": _jsonable(after_state or {}),
    }

    entry = AuditLog(
        action=action,
        description=description,
        actor=actor,
        actor_type=actor_type,
        actor_role=str(actor_role) if actor_role else None,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        before_state=_jsonable(before_state or {}),
        after_state=_jsonable(after_state or {}),
        agent_key=agent_key,
        execution_id=execution_id,
        human_task_id=human_task_id,
        confidence=confidence,
        hitl_enforced=hitl_enforced,
        hash_chain=_digest(previous, payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session, limit: int = 5000) -> dict:
    """Recompute the chain to prove the trail has not been altered."""
    rows = db.execute(select(AuditLog).order_by(AuditLog.sequence.asc()).limit(limit)).scalars().all()
    previous: str | None = None
    broken_at: str | None = None
    for row in rows:
        payload = {
            "action": row.action,
            "actor": row.actor,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "before": row.before_state or {},
            "after": row.after_state or {},
        }
        expected = _digest(previous, payload)
        if expected != row.hash_chain:
            broken_at = row.id
            break
        previous = row.hash_chain
    return {
        "entries_checked": len(rows),
        "valid": broken_at is None,
        "broken_at": broken_at,
        "head_hash": previous,
    }


def snapshot(obj: Any, fields: list[str]) -> dict:
    return {field: _jsonable(getattr(obj, field, None)) for field in fields}
