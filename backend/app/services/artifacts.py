"""Artifact service — how documents get into an agent and out of it.

Two directions, one table:

* **input**  — a human uploads an attachment (requirements doc, spend extract,
  supplier list, a draft contract) and hands it to an agent.
* **output** — an agent produces a deliverable (RFP package, scorecard, savings
  register, contract draft, executive brief).

An output artifact is born a **draft**. It becomes ``released`` only when a
human approves the checkpoint that owns it — so a generated document cannot
reach a supplier, or be treated as final, without a named person signing it off.
That keeps the platform's central guarantee intact for documents as well as for
database rows.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import EventType
from ..models import Artifact, utcnow
from .events import record_event

# What we can meaningfully parse for an agent to reason over.
TEXTUAL = {
    "text/csv", "text/plain", "text/markdown", "application/json",
    "text/tab-separated-values", "application/xml", "text/xml",
}

EXTENSION_TYPES = {
    "csv": "text/csv", "tsv": "text/tab-separated-values", "json": "application/json",
    "md": "text/markdown", "markdown": "text/markdown", "txt": "text/plain",
    "xml": "application/xml", "eml": "text/plain", "log": "text/plain",
    "pdf": "application/pdf",
}


def guess_content_type(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return EXTENSION_TYPES.get(ext, "text/plain")


def _next_reference(db: Session, prefix: str) -> str:
    count = db.execute(select(func.count(Artifact.id))).scalar_one() or 0
    return f"{prefix}-{count + 4001}"


# ==========================================================================
# Creation
# ==========================================================================
def store_input(
    db: Session,
    *,
    filename: str,
    content: str,
    title: str = "",
    kind: str = "attachment",
    uploaded_by: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
) -> Artifact:
    """Register an uploaded attachment so agents can read it."""
    content_type = guess_content_type(filename)
    artifact = Artifact(
        reference=_next_reference(db, "ATT"),
        direction="input",
        kind=kind,
        title=title or filename,
        filename=filename,
        content_type=content_type,
        content=content,
        size_bytes=len(content.encode("utf-8")),
        status="available",
        uploaded_by=uploaded_by,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=meta or {},
    )
    preview = parse(artifact)
    artifact.row_count = preview.get("row_count")
    artifact.summary = preview.get("summary")
    db.add(artifact)
    db.flush()
    return artifact


def produce_output(
    db: Session,
    *,
    agent_key: str,
    execution_id: str | None,
    title: str,
    filename: str,
    content: str,
    kind: str = "document",
    summary: str = "",
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
) -> Artifact:
    """Register an agent deliverable. Starts as a draft — never released."""
    artifact = Artifact(
        reference=_next_reference(db, "OUT"),
        direction="output",
        kind=kind,
        title=title,
        filename=filename,
        content_type=guess_content_type(filename),
        content=content,
        size_bytes=len(content.encode("utf-8")),
        summary=summary,
        agent_key=agent_key,
        execution_id=execution_id,
        entity_type=entity_type,
        entity_id=entity_id,
        status="draft",
        meta=meta or {},
    )
    if artifact.content_type == "text/csv":
        artifact.row_count = max(0, content.strip().count("\n"))
    db.add(artifact)
    db.flush()

    record_event(
        db,
        event_type=EventType.ARTIFACT_PRODUCED,
        title=f"Draft produced · {title}",
        message=f"{filename} ({artifact.size_bytes:,} bytes) — draft, awaiting human release.",
        entity_type=entity_type,
        entity_id=entity_id,
        actor=agent_key,
        actor_type="agent",
        payload={"artifact_id": artifact.id, "reference": artifact.reference},
    )
    return artifact


def release(db: Session, artifact_ids: list[str], *, released_by: str, human_task_id: str | None = None) -> list[dict]:
    """Mark deliverables final. Called only from an approved HITL checkpoint."""
    released = []
    for artifact_id in artifact_ids or []:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.direction != "output":
            continue
        artifact.status = "released"
        artifact.released_by = released_by
        artifact.released_at = utcnow()
        artifact.human_task_id = human_task_id
        released.append({"reference": artifact.reference, "title": artifact.title,
                         "filename": artifact.filename})
        record_event(
            db,
            event_type=EventType.ARTIFACT_RELEASED,
            title=f"Released · {artifact.title}",
            message=f"{artifact.filename} released by {released_by}.",
            entity_type=artifact.entity_type,
            entity_id=artifact.entity_id,
            actor=released_by,
            actor_type="human",
            severity="success",
            payload={"artifact_id": artifact.id, "reference": artifact.reference},
        )
    return released


# ==========================================================================
# Reading
# ==========================================================================
def parse(artifact: Artifact) -> dict:
    """Turn an attachment into something an agent can reason over.

    Returns ``{format, rows, fields, text, row_count, summary}``. Never raises —
    an unreadable attachment degrades to raw text with a stated reason, because
    an agent must be able to say "I could not read this" rather than crash.
    """
    content = artifact.content or ""
    ctype = artifact.content_type or "text/plain"

    if ctype == "application/json":
        try:
            data = json.loads(content)
            rows = data if isinstance(data, list) else [data]
            fields = sorted({k for r in rows if isinstance(r, dict) for k in r})
            return {"format": "json", "rows": rows, "fields": fields,
                    "row_count": len(rows), "text": content,
                    "summary": f"JSON with {len(rows)} record(s), {len(fields)} field(s)."}
        except json.JSONDecodeError as exc:
            return {"format": "invalid_json", "rows": [], "fields": [], "text": content,
                    "row_count": None, "summary": f"Malformed JSON: {exc.msg}"}

    if ctype in {"text/csv", "text/tab-separated-values"}:
        delimiter = "\t" if ctype.endswith("tab-separated-values") else ","
        try:
            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            rows = [dict(r) for r in reader]
            fields = list(reader.fieldnames or [])
            return {"format": "csv", "rows": rows, "fields": fields,
                    "row_count": len(rows), "text": content,
                    "summary": f"{len(rows)} row(s) × {len(fields)} column(s): "
                               f"{', '.join(fields[:6])}{'…' if len(fields) > 6 else ''}"}
        except csv.Error as exc:
            return {"format": "invalid_csv", "rows": [], "fields": [], "text": content,
                    "row_count": None, "summary": f"Unreadable CSV: {exc}"}

    if ctype == "application/pdf":
        # No OCR engine is bundled; only an embedded text layer is usable.
        return {"format": "pdf_text", "rows": [], "fields": [], "text": content,
                "row_count": None,
                "summary": "PDF — only the embedded text layer is read (no OCR bundled)."}

    words = len(content.split())
    return {"format": "text", "rows": [], "fields": [], "text": content,
            "row_count": None, "summary": f"{words:,} words of free text."}


def load_for_agent(db: Session, artifact_ids: list[str]) -> list[dict]:
    """Resolve attachment ids into parsed payloads for an agent run."""
    loaded = []
    for artifact_id in artifact_ids or []:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            continue
        parsed = parse(artifact)
        loaded.append({
            "id": artifact.id,
            "reference": artifact.reference,
            "filename": artifact.filename,
            "title": artifact.title,
            "content_type": artifact.content_type,
            "kind": artifact.kind,
            **parsed,
        })
    return loaded


# ==========================================================================
# Small builders the agents share
# ==========================================================================
def to_csv(rows: list[dict], fields: list[str] | None = None) -> str:
    if not rows:
        return ",".join(fields or []) + "\n"
    fields = fields or list(rows[0].keys())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def to_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(out)
