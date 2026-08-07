"""KPI computation for the executive and operational dashboards."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import (
    STAGE_LABELS,
    STAGE_SEQUENCE,
    AgentRunStatus,
    ApprovalStatus,
    ExceptionStatus,
    HumanTaskStatus,
    InvoiceStatus,
    PaymentStatus,
    RiskLevel,
    SLAStatus,
    WorkflowStage,
)
from ..models import (
    AgentConfig,
    AgentExecution,
    Approval,
    ExceptionCase,
    HumanTask,
    Invoice,
    Payment,
    SLARisk,
    Supplier,
    utcnow,
)

# Industry reference points used for the "vs benchmark" framing on the dashboard.
BENCHMARKS = {
    "touchless_rate": {"average": 32.6, "best_in_class": 80.0, "target": 80.0},
    "cycle_time_hours": {"average": 261.6, "best_in_class": 74.4, "target": 24.0},
    "sla_compliance": {"average": 90.0, "best_in_class": 99.0, "target": 99.0},
    "cost_per_invoice": {"average": 10.89, "best_in_class": 2.78, "target": 3.00},
    "on_time_payment": {"average": 88.0, "best_in_class": 98.0, "target": 98.0},
}

TERMINAL = {InvoiceStatus.PAID, InvoiceStatus.REJECTED, InvoiceStatus.CANCELLED}


def dashboard(db: Session) -> dict:
    now = utcnow()
    invoices = db.execute(select(Invoice)).scalars().all()
    in_flight = [i for i in invoices if i.status not in TERMINAL]
    settled = [i for i in invoices if i.status == InvoiceStatus.PAID]

    # --- Touchless -------------------------------------------------------
    touchless = len([i for i in settled if i.touchless])
    touchless_rate = round(touchless / len(settled) * 100, 1) if settled else 0.0

    # --- Cycle time ------------------------------------------------------
    cycles = [i.cycle_time_hours for i in settled if i.cycle_time_hours]
    avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else 0.0

    # --- SLA -------------------------------------------------------------
    met = len([i for i in settled if i.sla_status == SLAStatus.MET])
    breached_settled = len([i for i in settled if i.sla_status == SLAStatus.BREACHED])
    sla_denominator = met + breached_settled
    sla_compliance = round(met / sla_denominator * 100, 1) if sla_denominator else 100.0
    at_risk = [i for i in in_flight if i.sla_status == SLAStatus.AT_RISK]
    breached_live = [i for i in in_flight if i.sla_status == SLAStatus.BREACHED]

    # --- Exceptions ------------------------------------------------------
    exceptions = db.execute(select(ExceptionCase)).scalars().all()
    open_exceptions = [
        e for e in exceptions
        if e.status not in {ExceptionStatus.RESOLVED, ExceptionStatus.WRITTEN_OFF}
    ]
    resolved_exceptions = [e for e in exceptions if e.status == ExceptionStatus.RESOLVED]
    agent_resolved = len([e for e in resolved_exceptions if e.resolved_by_agent])
    auto_resolution_rate = (
        round(agent_resolved / len(resolved_exceptions) * 100, 1) if resolved_exceptions else 0.0
    )
    exception_ages = [
        (now - e.created_at).total_seconds() / 3600.0 for e in open_exceptions if e.created_at
    ]
    avg_exception_age = round(sum(exception_ages) / len(exception_ages), 1) if exception_ages else 0.0

    # --- Human-in-the-loop -----------------------------------------------
    tasks = db.execute(select(HumanTask)).scalars().all()
    pending_tasks = [t for t in tasks if t.status == HumanTaskStatus.PENDING]
    decided = [t for t in tasks if t.status in {
        HumanTaskStatus.APPROVED, HumanTaskStatus.REJECTED, HumanTaskStatus.MODIFIED
    }]
    approved = len([t for t in decided if t.status == HumanTaskStatus.APPROVED])
    modified = len([t for t in decided if t.status == HumanTaskStatus.MODIFIED])
    rejected = len([t for t in decided if t.status == HumanTaskStatus.REJECTED])
    acceptance_rate = round((approved + modified) / len(decided) * 100, 1) if decided else None

    review_times = [
        (t.decided_at - t.created_at).total_seconds() / 60.0
        for t in decided if t.decided_at and t.created_at
    ]
    avg_review_minutes = round(sum(review_times) / len(review_times), 1) if review_times else 0.0

    # --- Payments --------------------------------------------------------
    payments = db.execute(select(Payment)).scalars().all()
    paid = [p for p in payments if p.status in {PaymentStatus.PAID, PaymentStatus.RELEASED}]
    discount_captured = round(sum(p.discount_captured or 0.0 for p in paid), 2)
    scheduled = [p for p in payments if p.status == PaymentStatus.SCHEDULED]
    on_time = len([
        p for p in paid
        if p.invoice and p.invoice.due_date and p.released_at
        and p.released_at.date() <= p.invoice.due_date
    ])
    on_time_rate = round(on_time / len(paid) * 100, 1) if paid else 100.0

    # --- Agents ----------------------------------------------------------
    executions = db.execute(select(AgentExecution)).scalars().all()
    configs = db.execute(select(AgentConfig)).scalars().all()

    # --- Value ------------------------------------------------------------
    open_value = round(sum(i.total_amount or 0.0 for i in in_flight), 2)
    at_risk_value = round(sum(i.total_amount or 0.0 for i in at_risk + breached_live), 2)
    exception_value = round(sum(e.financial_impact_usd or 0.0 for e in open_exceptions), 2)

    return {
        "generated_at": now.isoformat(),
        "headline": {
            "invoices_in_flight": len(in_flight),
            "open_value": open_value,
            "pending_human_decisions": len(pending_tasks),
            "open_exceptions": len(open_exceptions),
            "at_risk_invoices": len(at_risk) + len(breached_live),
            "at_risk_value": at_risk_value,
            "exception_exposure": exception_value,
        },
        "kpis": {
            "touchless_rate": {
                "value": touchless_rate, "unit": "%", "label": "Touchless processing",
                "direction": "up", **BENCHMARKS["touchless_rate"],
            },
            "avg_cycle_time_hours": {
                "value": avg_cycle, "unit": "h", "label": "Avg invoice cycle time",
                "direction": "down", **BENCHMARKS["cycle_time_hours"],
            },
            "sla_compliance": {
                "value": sla_compliance, "unit": "%", "label": "SLA compliance",
                "direction": "up", **BENCHMARKS["sla_compliance"],
            },
            "auto_resolution_rate": {
                "value": auto_resolution_rate, "unit": "%", "label": "Agent-proposed exception resolutions",
                "direction": "up", "average": 25.0, "best_in_class": 60.0, "target": 60.0,
            },
            "on_time_payment": {
                "value": on_time_rate, "unit": "%", "label": "On-time payment",
                "direction": "up", **BENCHMARKS["on_time_payment"],
            },
            "avg_exception_age_hours": {
                "value": avg_exception_age, "unit": "h", "label": "Avg open exception age",
                "direction": "down", "average": 96.0, "best_in_class": 24.0, "target": 24.0,
            },
        },
        "hitl": {
            "pending": len(pending_tasks),
            "overdue": len([t for t in pending_tasks if t.due_at and t.due_at < now]),
            "decided": len(decided),
            "approved": approved,
            "modified": modified,
            "rejected": rejected,
            "acceptance_rate": acceptance_rate,
            "avg_review_minutes": avg_review_minutes,
            "by_risk": dict(Counter(t.risk_level for t in pending_tasks)),
            "by_role": dict(Counter(t.required_role for t in pending_tasks)),
            "by_agent": dict(Counter(t.agent_name for t in pending_tasks)),
        },
        "pipeline": _pipeline(in_flight),
        "exceptions": {
            "open": len(open_exceptions),
            "by_type": dict(Counter(e.exception_type for e in open_exceptions)),
            "by_severity": dict(Counter(e.severity for e in open_exceptions)),
            "resolved_total": len(resolved_exceptions),
            "agent_resolved": agent_resolved,
            "exposure": exception_value,
        },
        "payments": {
            "scheduled_count": len(scheduled),
            "scheduled_value": round(sum(p.amount or 0.0 for p in scheduled), 2),
            "discount_captured": discount_captured,
            "paid_count": len(paid),
            "paid_value": round(sum(p.amount or 0.0 for p in paid), 2),
        },
        "agents": {
            "total": len(configs),
            "enabled": len([c for c in configs if c.enabled]),
            "runs": len(executions),
            "awaiting_human": len([e for e in executions if e.status == AgentRunStatus.AWAITING_HUMAN]),
            "failed": len([e for e in executions if e.status == AgentRunStatus.FAILED]),
            "avg_confidence": round(
                sum(e.confidence for e in executions) / len(executions), 3
            ) if executions else 0.0,
        },
        "trend": _trend(settled),
        "aging": _aging(in_flight, now),
    }


def _pipeline(in_flight: list[Invoice]) -> list[dict]:
    counts: dict[str, list[Invoice]] = defaultdict(list)
    for invoice in in_flight:
        counts[str(invoice.stage)].append(invoice)
    return [
        {
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage),
            "count": len(counts.get(stage, [])),
            "value": round(sum(i.total_amount or 0.0 for i in counts.get(stage, [])), 2),
            "at_risk": len([i for i in counts.get(stage, []) if i.sla_status != SLAStatus.ON_TRACK]),
        }
        for stage in STAGE_SEQUENCE
        if stage not in {WorkflowStage.CLOSED}
    ]


def _trend(settled: list[Invoice], days: int = 14) -> list[dict]:
    now = utcnow()
    buckets: dict[str, list[Invoice]] = defaultdict(list)
    for invoice in settled:
        if invoice.paid_at and (now - invoice.paid_at).days < days:
            buckets[invoice.paid_at.date().isoformat()].append(invoice)

    series = []
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        items = buckets.get(day, [])
        cycles = [i.cycle_time_hours for i in items if i.cycle_time_hours]
        series.append({
            "date": day,
            "processed": len(items),
            "value": round(sum(i.total_amount or 0.0 for i in items), 2),
            "touchless_rate": round(
                len([i for i in items if i.touchless]) / len(items) * 100, 1
            ) if items else None,
            "avg_cycle_hours": round(sum(cycles) / len(cycles), 1) if cycles else None,
        })
    return series


def _aging(in_flight: list[Invoice], now) -> list[dict]:
    buckets = [("0-8h", 0, 8), ("8-24h", 8, 24), ("24-48h", 24, 48), ("48-72h", 48, 72), ("72h+", 72, 10**6)]
    result = []
    for label, low, high in buckets:
        items = [
            i for i in in_flight
            if i.received_at and low <= (now - i.received_at).total_seconds() / 3600.0 < high
        ]
        result.append({
            "bucket": label,
            "count": len(items),
            "value": round(sum(i.total_amount or 0.0 for i in items), 2),
        })
    return result


def sla_overview(db: Session) -> dict:
    now = utcnow()
    risks = db.execute(select(SLARisk).order_by(SLARisk.risk_score.desc())).scalars().all()
    in_flight = db.execute(
        select(Invoice).where(Invoice.status.notin_(list(TERMINAL)))
    ).scalars().all()

    approvals = db.execute(
        select(Approval).where(Approval.status.in_([ApprovalStatus.PENDING, ApprovalStatus.DELEGATED]))
    ).scalars().all()
    queue_depth: dict[str, int] = Counter(a.approver_id or "unassigned" for a in approvals)

    breached = [i for i in in_flight if i.sla_status == SLAStatus.BREACHED]
    forecast_compliance = round(
        (1 - len(breached) / max(1, len(in_flight))) * 100, 2
    )
    return {
        "generated_at": now.isoformat(),
        "forecast_compliance": forecast_compliance,
        "target": 99.0,
        "in_flight": len(in_flight),
        "at_risk": len([i for i in in_flight if i.sla_status == SLAStatus.AT_RISK]),
        "breached": len(breached),
        "exposure": round(sum(i.total_amount or 0.0 for i in in_flight
                              if i.sla_status != SLAStatus.ON_TRACK), 2),
        "risks": [
            {
                "invoice_id": r.invoice_id,
                "invoice_number": r.entity_label,
                "stage": r.stage,
                "stage_label": STAGE_LABELS.get(r.stage, r.stage),
                "risk_score": r.risk_score,
                "risk_level": r.risk_level,
                "hours_remaining": r.hours_remaining,
                "drivers": r.drivers or [],
                "recommended_action": r.recommended_action,
                "status": r.status,
            }
            for r in risks
        ],
        "queues": [
            {"approver_id": key, "depth": value}
            for key, value in sorted(queue_depth.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "by_stage": _pipeline(in_flight),
    }


def supplier_scorecard(db: Session) -> list[dict]:
    suppliers = db.execute(select(Supplier)).scalars().all()
    rows = []
    for supplier in suppliers:
        invoices = db.execute(
            select(Invoice).where(Invoice.supplier_id == supplier.id)
        ).scalars().all()
        open_invoices = [i for i in invoices if i.status not in TERMINAL]
        exceptions = db.execute(
            select(func.count(ExceptionCase.id)).where(ExceptionCase.supplier_id == supplier.id)
        ).scalar_one()
        rows.append({
            "supplier_id": supplier.id,
            "code": supplier.code,
            "name": supplier.name,
            "tier": supplier.tier,
            "category": supplier.category,
            "risk_level": supplier.risk_level,
            "risk_score": supplier.risk_score,
            "on_hold": supplier.on_hold,
            "sanctions_status": supplier.sanctions_status,
            "open_invoices": len(open_invoices),
            "open_value": round(sum(i.total_amount or 0.0 for i in open_invoices), 2),
            "spend_ytd_usd": supplier.spend_ytd_usd,
            "exception_count": exceptions,
            "on_time_payment_pct": supplier.on_time_payment_pct,
            "payment_terms": supplier.payment_terms,
        })
    rows.sort(key=lambda r: r["open_value"], reverse=True)
    return rows
