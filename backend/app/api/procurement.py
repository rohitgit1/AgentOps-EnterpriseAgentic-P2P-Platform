"""Procurement AgentOps API — artifacts, the agent I/O catalogue, and the
sourcing / spend / risk / contract / tail-spend resources."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.registry import get_agent, list_agents, suites
from ..database import get_db
from ..enums import SUITE_BLURBS, SUITE_LABELS, AgentSuite
from ..models import (
    Artifact,
    ContractDraft,
    RiskAssessment,
    SavingsOpportunity,
    SourcingBid,
    SourcingEvent,
    SpendTransaction,
    Supplier,
    TailSpendFinding,
)
from ..serializers import iso
from ..services import artifacts as artifact_service
from ..services.audit import write_audit
from ..skills import catalog as skills_catalog
from .deps import get_current_user
from ..models import User

router = APIRouter(tags=["procurement"])


# ==========================================================================
# Artifacts — the input/output plumbing
# ==========================================================================
def artifact_out(artifact: Artifact, *, include_content: bool = False) -> dict:
    data = {
        "id": artifact.id,
        "reference": artifact.reference,
        "direction": artifact.direction,
        "kind": artifact.kind,
        "title": artifact.title,
        "filename": artifact.filename,
        "content_type": artifact.content_type,
        "size_bytes": artifact.size_bytes,
        "summary": artifact.summary,
        "row_count": artifact.row_count,
        "agent_key": artifact.agent_key,
        "execution_id": artifact.execution_id,
        "human_task_id": artifact.human_task_id,
        "entity_type": artifact.entity_type,
        "entity_id": artifact.entity_id,
        "status": artifact.status,
        "uploaded_by": artifact.uploaded_by,
        "released_by": artifact.released_by,
        "released_at": iso(artifact.released_at),
        "created_at": iso(artifact.created_at),
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }
    if include_content:
        data["content"] = artifact.content
    return data


@router.get("/artifacts")
def list_artifacts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    direction: str | None = None,
    agent_key: str | None = None,
    execution_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> dict:
    query = select(Artifact).order_by(Artifact.created_at.desc())
    if direction:
        query = query.where(Artifact.direction == direction)
    if agent_key:
        query = query.where(Artifact.agent_key == agent_key)
    if execution_id:
        query = query.where(Artifact.execution_id == execution_id)
    if status:
        query = query.where(Artifact.status == status)
    rows = db.execute(query.limit(limit)).scalars().all()
    return {
        "count": len(rows),
        "inputs": len([r for r in rows if r.direction == "input"]),
        "outputs": len([r for r in rows if r.direction == "output"]),
        "drafts": len([r for r in rows if r.status == "draft"]),
        "items": [artifact_out(r) for r in rows],
    }


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)) -> dict:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    data = artifact_out(artifact, include_content=True)
    data["parsed"] = {k: v for k, v in artifact_service.parse(artifact).items() if k != "text"}
    return data


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    """Serve the artifact as a file.

    Deliberately unauthenticated so a browser download link works without
    custom headers; artifact ids are unguessable and this is demo-scoped.
    """
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return StreamingResponse(
        io.BytesIO((artifact.content or "").encode("utf-8")),
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.post("/artifacts/upload", status_code=201)
async def upload_artifact(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    kind: str = Form(default="attachment"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Upload an attachment for an agent to read.

    Text-based formats (csv, json, md, txt) are parsed. Binary PDFs contribute
    only their embedded text layer — no OCR engine is bundled.
    """
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 8 MB limit.")
    content = raw.decode("utf-8", errors="ignore")

    artifact = artifact_service.store_input(
        db, filename=file.filename or "attachment.txt", content=content,
        title=title, kind=kind, uploaded_by=user.full_name,
    )
    write_audit(
        db, action="artifact.uploaded",
        description=f"{user.full_name} uploaded {artifact.filename} "
                    f"({artifact.size_bytes:,} bytes) — {artifact.summary}",
        actor=user.full_name, actor_type="human", actor_role=user.role,
        entity_type="artifact", entity_id=artifact.id, entity_label=artifact.reference,
        after_state={"filename": artifact.filename, "rows": artifact.row_count},
    )
    db.commit()
    return artifact_out(db.get(Artifact, artifact.id))


# ==========================================================================
# Agent I/O catalogue — "what goes in, what comes out"
# ==========================================================================
@router.get("/agent-io")
def agent_io_catalog(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """The contract for every agent: declared inputs, declared outputs, and the
    artifacts each has actually produced so far."""
    produced = db.execute(
        select(Artifact.agent_key, func.count(Artifact.id))
        .where(Artifact.direction == "output")
        .group_by(Artifact.agent_key)
    ).all()
    counts = {key: count for key, count in produced}

    recent: dict[str, list[dict]] = {}
    for artifact in db.execute(
        select(Artifact).where(Artifact.direction == "output")
        .order_by(Artifact.created_at.desc()).limit(120)
    ).scalars().all():
        recent.setdefault(artifact.agent_key or "", []).append(artifact_out(artifact))

    result = {}
    for suite_key, agents in suites().items():
        result[suite_key] = {
            "label": SUITE_LABELS[suite_key],
            "blurb": SUITE_BLURBS[suite_key],
            "agents": [
                {
                    **agent.describe(),
                    "artifacts_produced": counts.get(agent.key, 0),
                    "recent_artifacts": recent.get(agent.key, [])[:4],
                }
                for agent in agents
            ],
        }
    return {
        "suites": result,
        "totals": {
            "agents": len(list_agents()),
            "with_attachments": len([a for a in list_agents()
                                     if any(i.kind == "attachment" for i in a.inputs)]),
            "producing_artifacts": len([a for a in list_agents()
                                        if any(o.kind == "artifact" for o in a.outputs)]),
            "artifacts_produced": sum(counts.values()),
        },
    }


@router.get("/suites")
def list_suites(_: User = Depends(get_current_user)) -> list[dict]:
    return [
        {
            "key": key,
            "label": SUITE_LABELS[key],
            "blurb": SUITE_BLURBS[key],
            "agent_count": len(agents),
            "skill_count": len(skills_catalog(key)),
            "agents": [{"key": a.key, "name": a.name, "role": a.role} for a in agents],
        }
        for key, agents in suites().items()
    ]


# ==========================================================================
# Sourcing
# ==========================================================================
class SourcingEventIn(BaseModel):
    title: str
    category: str
    budget_usd: float = 0.0
    event_type: str = "RFP"
    requirements: str = ""
    compliance_rules: list[str] = []
    attachment_ids: list[str] = []
    run_agent: bool = True


@router.get("/sourcing-events")
def list_sourcing_events(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(SourcingEvent).order_by(SourcingEvent.created_at.desc())).scalars().all()
    return {
        "count": len(rows),
        "expected_savings_usd": round(sum(r.expected_savings_usd for r in rows), 2),
        "items": [_event_out(db, e) for e in rows],
    }


@router.get("/sourcing-events/{event_id}")
def get_sourcing_event(event_id: str, db: Session = Depends(get_db),
                       _: User = Depends(get_current_user)) -> dict:
    event = db.get(SourcingEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Sourcing event not found.")
    data = _event_out(db, event)
    data["artifacts"] = [
        artifact_out(a) for a in db.execute(
            select(Artifact).where(Artifact.entity_id == event.id)
            .order_by(Artifact.created_at.desc())
        ).scalars().all()
    ]
    return data


def _event_out(db: Session, event: SourcingEvent) -> dict:
    supplier = db.get(Supplier, event.awarded_supplier_id) if event.awarded_supplier_id else None
    return {
        "id": event.id, "event_number": event.event_number, "title": event.title,
        "category": event.category, "event_type": event.event_type,
        "budget_usd": event.budget_usd, "status": event.status,
        "issued_at": iso(event.issued_at), "response_due": iso(event.response_due),
        "awarded_supplier": supplier.name if supplier else None,
        "awarded_at": iso(event.awarded_at),
        "expected_savings_usd": event.expected_savings_usd,
        "cycle_days": event.cycle_days, "baseline_cycle_days": event.baseline_cycle_days,
        "cycle_reduction_pct": round((1 - event.cycle_days / event.baseline_cycle_days) * 100, 1)
        if event.cycle_days and event.baseline_cycle_days else None,
        "bid_count": len(event.bids),
        "bids": [
            {"id": b.id, "supplier_name": b.supplier_name, "bid_amount_usd": b.bid_amount_usd,
             "lead_time_days": b.lead_time_days, "technical_score": b.technical_score,
             "commercial_score": b.commercial_score, "risk_score": b.risk_score,
             "total_score": b.total_score, "status": b.status}
            for b in sorted(event.bids, key=lambda b: b.total_score, reverse=True)
        ],
        "created_at": iso(event.created_at),
    }


@router.post("/sourcing-events", status_code=201)
def create_sourcing_event(
    payload: SourcingEventIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Start a sourcing event and hand it straight to the agent."""
    from ..serializers import execution_out, human_task_out

    count = db.execute(select(func.count(SourcingEvent.id))).scalar_one() or 0
    event = SourcingEvent(
        event_number=f"SRC-{count + 9001}",
        title=payload.title, category=payload.category, event_type=payload.event_type,
        budget_usd=payload.budget_usd, requirements=payload.requirements,
        compliance_rules=payload.compliance_rules, status="draft",
        owner_id=user.id,
    )
    db.add(event)
    db.flush()

    response: dict = {"event": _event_out(db, event)}
    if payload.run_agent:
        result = get_agent("sourcing_rfp").run(
            db, {"event_id": event.id, "attachment_ids": payload.attachment_ids},
            trigger="sourcing_request", triggered_by=user.full_name,
        )
        response["run"] = execution_out(result.execution, detail=True)
        response["checkpoints"] = [human_task_out(t, detail=True) for t in result.tasks]
    db.commit()
    response["event"] = _event_out(db, db.get(SourcingEvent, event.id))
    return response


# ==========================================================================
# Spend, savings, risk, contracts, tail spend
# ==========================================================================
@router.get("/spend")
def list_spend(db: Session = Depends(get_db), _: User = Depends(get_current_user),
               limit: int = 500) -> dict:
    rows = db.execute(select(SpendTransaction).limit(limit)).scalars().all()
    total = sum(r.amount_usd for r in rows) or 1.0
    classified = sum(r.amount_usd for r in rows if r.category)
    by_category: dict[str, float] = {}
    for row in rows:
        by_category[row.category or "Unclassified"] = \
            by_category.get(row.category or "Unclassified", 0.0) + row.amount_usd
    return {
        "count": len(rows),
        "total_usd": round(total, 2),
        "classified_pct": round(classified / total * 100, 1),
        "maverick_usd": round(sum(r.amount_usd for r in rows if r.maverick), 2),
        "tail_usd": round(sum(r.amount_usd for r in rows if r.tail_spend), 2),
        "by_category": [
            {"category": k, "spend_usd": round(v, 2)}
            for k, v in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "items": [
            {"id": r.id, "external_id": r.external_id, "supplier": r.supplier_raw,
             "description": r.description, "amount_usd": r.amount_usd,
             "category": r.category, "unspsc": r.unspsc,
             "confidence": r.classification_confidence, "on_contract": r.on_contract,
             "maverick": r.maverick, "tail_spend": r.tail_spend,
             "date": iso(r.transaction_date)}
            for r in rows[:200]
        ],
    }


@router.get("/savings")
def list_savings(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(
        select(SavingsOpportunity).order_by(SavingsOpportunity.estimated_savings_usd.desc())
    ).scalars().all()
    return {
        "count": len(rows),
        "pipeline_usd": round(sum(r.estimated_savings_usd for r in rows), 2),
        "approved_usd": round(sum(r.estimated_savings_usd for r in rows if r.status == "approved"), 2),
        "items": [
            {"id": r.id, "reference": r.reference, "title": r.title, "lever": r.lever,
             "category": r.category, "annual_spend_usd": r.annual_spend_usd,
             "estimated_savings_usd": r.estimated_savings_usd, "confidence": r.confidence,
             "rationale": r.rationale, "status": r.status,
             "identified_by_agent": r.identified_by_agent, "approved_by": r.approved_by,
             "created_at": iso(r.created_at)}
            for r in rows
        ],
    }


@router.get("/risk-assessments")
def list_risk_assessments(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(
        select(RiskAssessment).order_by(RiskAssessment.overall_risk.desc())
    ).scalars().all()
    return {
        "count": len(rows),
        "average_risk": round(sum(r.overall_risk for r in rows) / len(rows), 1) if rows else 0.0,
        "elevated": len([r for r in rows if r.risk_band in {"high", "critical"}]),
        "items": [
            {"id": r.id, "supplier_id": r.supplier_id, "supplier_name": r.supplier_name,
             "financial_risk": r.financial_risk, "operational_risk": r.operational_risk,
             "compliance_risk": r.compliance_risk, "esg_risk": r.esg_risk,
             "overall_risk": r.overall_risk, "risk_band": r.risk_band,
             "findings": r.findings or [],
             "recommended_disposition": r.recommended_disposition,
             "applied_disposition": r.applied_disposition, "decided_by": r.decided_by,
             "spend_at_risk_usd": r.spend_at_risk_usd, "updated_at": iso(r.updated_at)}
            for r in rows
        ],
    }


@router.get("/contract-drafts")
def list_contract_drafts(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(ContractDraft).order_by(ContractDraft.created_at.desc())).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {"id": r.id, "reference": r.reference, "title": r.title,
             "contract_type": r.contract_type, "supplier_name": r.supplier_name,
             "value_usd": r.value_usd, "term_months": r.term_months,
             "legal_risk_score": r.legal_risk_score,
             "missing_clauses": r.missing_clauses or [],
             "clause_findings": r.clause_findings or [],
             "obligations": r.obligations or [],
             "renewal_date": iso(r.renewal_date), "status": r.status,
             "issued_by": r.issued_by, "created_at": iso(r.created_at)}
            for r in rows
        ],
    }


@router.get("/contract-drafts/{draft_id}/body", response_class=PlainTextResponse)
def contract_draft_body(draft_id: str, db: Session = Depends(get_db),
                        _: User = Depends(get_current_user)) -> str:
    draft = db.get(ContractDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Contract draft not found.")
    return draft.body


@router.get("/tail-spend")
def list_tail_spend(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(
        select(TailSpendFinding).order_by(TailSpendFinding.consolidation_savings_usd.desc())
    ).scalars().all()
    return {
        "count": len(rows),
        "open": len([r for r in rows if r.status == "open"]),
        "spend_usd": round(sum(r.spend_usd for r in rows), 2),
        "savings_usd": round(sum(r.consolidation_savings_usd for r in rows), 2),
        "items": [
            {"id": r.id, "reference": r.reference, "finding_type": r.finding_type,
             "category": r.category, "supplier_names": r.supplier_names or [],
             "transaction_count": r.transaction_count, "spend_usd": r.spend_usd,
             "recommended_supplier": r.recommended_supplier,
             "consolidation_savings_usd": r.consolidation_savings_usd,
             "recommendation": r.recommendation, "status": r.status,
             "resolved_by": r.resolved_by, "created_at": iso(r.created_at)}
            for r in rows
        ],
    }


@router.get("/procurement/dashboard")
def procurement_dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Executive KPI rollup for the Procurement Command Center screen."""
    from ..agents.procurement_command_center import TARGETS

    events = db.execute(select(SourcingEvent)).scalars().all()
    awarded = [e for e in events if e.status == "awarded" and e.cycle_days]
    transactions = db.execute(select(SpendTransaction)).scalars().all()
    opportunities = db.execute(select(SavingsOpportunity)).scalars().all()
    assessments = db.execute(select(RiskAssessment)).scalars().all()
    drafts = db.execute(select(ContractDraft)).scalars().all()
    findings = db.execute(select(TailSpendFinding)).scalars().all()

    total_spend = sum(t.amount_usd for t in transactions) or 1.0
    classified = sum(t.amount_usd for t in transactions if t.category)
    on_contract = sum(t.amount_usd for t in transactions if t.on_contract)
    pipeline = sum(o.estimated_savings_usd for o in opportunities)
    avg_risk = round(sum(a.overall_risk for a in assessments) / len(assessments), 1) if assessments else 0.0
    tail_value = sum(t.amount_usd for t in transactions if t.tail_spend)
    addressable = sum(f.consolidation_savings_usd for f in findings)
    baseline = (sum(e.baseline_cycle_days for e in awarded) / len(awarded)) if awarded else 56.0
    actual = (sum(e.cycle_days for e in awarded) / len(awarded)) if awarded else None

    kpis = [
        {"key": "spend_under_management", "label": "Spend under management",
         "value": round(classified / total_spend * 100, 1),
         "target": TARGETS["spend_under_management"], "unit": "%", "direction": "up"},
        {"key": "contract_compliance", "label": "Contract compliance",
         "value": round(on_contract / total_spend * 100, 1),
         "target": TARGETS["contract_compliance"], "unit": "%", "direction": "up"},
        {"key": "supplier_risk_score", "label": "Supplier risk score",
         "value": avg_risk, "target": TARGETS["supplier_risk_score"], "unit": "", "direction": "down"},
        {"key": "tail_spend_reduction", "label": "Tail spend reduction potential",
         "value": round(addressable / (tail_value or 1) * 100, 1),
         "target": TARGETS["tail_spend_reduction"], "unit": "%", "direction": "up"},
        {"key": "sourcing_cycle_time_reduction", "label": "Sourcing cycle time reduction",
         "value": round((1 - actual / baseline) * 100, 1) if actual else 0.0,
         "target": TARGETS["sourcing_cycle_time_reduction"], "unit": "%", "direction": "up"},
        {"key": "procurement_savings", "label": "Procurement savings",
         "value": round(pipeline / total_spend * 100, 2),
         "target": TARGETS["procurement_savings"], "unit": "%", "direction": "up"},
    ]
    for kpi in kpis:
        kpi["meets_target"] = (kpi["value"] >= kpi["target"]) if kpi["direction"] == "up" \
            else (kpi["value"] <= kpi["target"])

    today = date.today()
    return {
        "kpis": kpis,
        "headline": {
            "sourcing_events": len(events),
            "in_market": len([e for e in events if e.status == "issued"]),
            "awarded": len(awarded),
            "savings_pipeline_usd": round(pipeline, 2),
            "savings_approved_usd": round(
                sum(o.estimated_savings_usd for o in opportunities if o.status == "approved"), 2),
            "suppliers_assessed": len(assessments),
            "suppliers_elevated": len([a for a in assessments if a.risk_band in {"high", "critical"}]),
            "contract_drafts": len(drafts),
            "tail_findings": len(findings),
            "tail_spend_usd": round(tail_value, 2),
            "total_spend_usd": round(total_spend, 2),
        },
        "risk_heatmap": [
            {"supplier": a.supplier_name, "financial": a.financial_risk,
             "operational": a.operational_risk, "compliance": a.compliance_risk,
             "esg": a.esg_risk, "overall": a.overall_risk, "band": a.risk_band}
            for a in sorted(assessments, key=lambda a: a.overall_risk, reverse=True)[:12]
        ],
        "savings_by_lever": [
            {"lever": lever,
             "value": round(sum(o.estimated_savings_usd for o in opportunities if o.lever == lever), 2)}
            for lever in sorted({o.lever for o in opportunities})
        ],
        "renewals": [
            {"reference": d.reference, "supplier": d.supplier_name,
             "renewal_date": iso(d.renewal_date),
             "days": (d.renewal_date - today).days if d.renewal_date else None}
            for d in sorted([d for d in drafts if d.renewal_date], key=lambda d: d.renewal_date)[:8]
        ],
    }
