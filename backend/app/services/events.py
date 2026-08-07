"""In-process event bus + workflow event log.

Stands in for Kafka / Azure Event Hub in the local demo. The publish API is
deliberately broker-shaped so `EventBus.publish` can be swapped for a real
producer without touching agent code.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..enums import EventType
from ..models import Notification, WorkflowEvent


def jsonable(value: Any) -> Any:
    """Recursively coerce values into JSON-storable primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class EventBus:
    """Fan-out to SSE subscribers, with a replay buffer for late joiners."""

    def __init__(self, buffer_size: int = 400) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def recent(self, limit: int = 50) -> list[dict]:
        return list(self._buffer)[-limit:]

    def publish(self, event: dict) -> None:
        payload = jsonable(event)
        self._buffer.append(payload)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                self.unsubscribe(queue)

    def sse_format(self, event: dict) -> str:
        return f"event: {event.get('event_type', 'message')}\ndata: {json.dumps(event)}\n\n"


bus = EventBus()


def record_event(
    db: Session,
    *,
    event_type: str = EventType.SYSTEM,
    title: str = "",
    message: str = "",
    entity_type: str | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    actor: str = "system",
    actor_type: str = "system",
    severity: str = "info",
    payload: dict | None = None,
    commit: bool = False,
) -> WorkflowEvent:
    """Append to the workflow event log and fan out to live subscribers."""
    event = WorkflowEvent(
        event_type=str(event_type),
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        actor=actor,
        actor_type=actor_type,
        title=title,
        message=message,
        severity=severity,
        payload=jsonable(payload or {}),
    )
    db.add(event)
    db.flush()
    if commit:
        db.commit()

    bus.publish(
        {
            "id": event.id,
            "event_type": str(event_type),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_label": entity_label,
            "actor": actor,
            "actor_type": actor_type,
            "title": title,
            "message": message,
            "severity": severity,
            "payload": jsonable(payload or {}),
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
    )
    return event


def notify(
    db: Session,
    *,
    title: str,
    body: str,
    target_role: str | None = None,
    user_id: str | None = None,
    severity: str = "info",
    link_entity_type: str | None = None,
    link_entity_id: str | None = None,
) -> Notification:
    note = Notification(
        title=title,
        body=body,
        target_role=str(target_role) if target_role else None,
        user_id=user_id,
        severity=severity,
        link_entity_type=link_entity_type,
        link_entity_id=link_entity_id,
    )
    db.add(note)
    db.flush()
    return note


# Backwards-compatible alias used internally.
_jsonable = jsonable
