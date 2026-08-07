"""SLA prediction skill — forecast breach risk before it happens."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..enums import RiskLevel, WorkflowStage
from ..models import utcnow

SKILL = {
    "name": "sla_prediction",
    "title": "SLA Prediction",
    "purpose": "Forecast which invoices will breach cycle-time SLA and why.",
    "inputs": ["stage", "age_hours", "sla_target", "open_exceptions", "approver_availability"],
    "output": ["risk_score", "risk_level", "predicted_breach_at", "drivers", "recommended_action"],
    "success_criteria": "Breaches predicted at least 8 hours ahead with < 15% false-positive rate.",
    "failure_handling": "Every high-risk forecast surfaces to a human with a recommended intervention.",
    "used_by": ["sla_command_center", "approval_acceleration"],
}

# Historical mean hours each remaining stage consumes (demo baseline).
STAGE_COST_HOURS: dict[str, float] = {
    WorkflowStage.INTAKE: 0.5,
    WorkflowStage.EXTRACTION_REVIEW: 2.0,
    WorkflowStage.VALIDATION: 1.5,
    WorkflowStage.MATCHING: 2.0,
    WorkflowStage.EXCEPTION: 14.0,
    WorkflowStage.APPROVAL: 6.0,
    WorkflowStage.PAYMENT: 2.0,
    WorkflowStage.POSTED: 0.5,
}

STAGE_ORDER = list(STAGE_COST_HOURS)


def remaining_effort_hours(stage: str) -> float:
    """Baseline hours left on the *happy path* from this stage onward.

    Exception handling is deliberately excluded unless the invoice is actually
    sitting in it — otherwise every clean invoice would carry the cost of an
    exception it never had, and everything would forecast as at-risk.
    """
    stage = str(stage)
    if stage not in STAGE_ORDER:
        return 0.0
    idx = STAGE_ORDER.index(stage)
    remaining = STAGE_ORDER[idx:]
    return round(
        sum(
            STAGE_COST_HOURS[s]
            for s in remaining
            if s != WorkflowStage.EXCEPTION or stage == WorkflowStage.EXCEPTION
        ),
        2,
    )


def predict(
    *,
    stage: str,
    received_at: datetime,
    sla_target_hours: float,
    open_exceptions: int = 0,
    approver_out_of_office: bool = False,
    approver_workload: int = 0,
    supplier_risk_level: str = RiskLevel.LOW,
    on_hold: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or utcnow()
    age_hours = max(0.0, (now - received_at).total_seconds() / 3600.0)
    deadline = received_at + timedelta(hours=sla_target_hours)
    hours_remaining = round((deadline - now).total_seconds() / 3600.0, 2)

    effort = remaining_effort_hours(stage)
    drivers: list[dict] = []

    # Adjust the effort estimate by the friction we can actually see.
    if open_exceptions:
        penalty = 6.0 * open_exceptions
        effort += penalty
        drivers.append({"driver": "open_exceptions", "impact_hours": penalty,
                        "detail": f"{open_exceptions} unresolved exception(s)"})
    if approver_out_of_office:
        effort += 16.0
        drivers.append({"driver": "approver_out_of_office", "impact_hours": 16.0,
                        "detail": "Assigned approver is out of office"})
    if approver_workload >= 8:
        penalty = min(8.0, 0.6 * approver_workload)
        effort += penalty
        drivers.append({"driver": "approver_queue_depth", "impact_hours": round(penalty, 2),
                        "detail": f"Approver holds {approver_workload} open items"})
    if str(supplier_risk_level) in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        effort += 4.0
        drivers.append({"driver": "supplier_risk", "impact_hours": 4.0,
                        "detail": f"Supplier risk level {supplier_risk_level}"})
    if on_hold:
        effort += 12.0
        drivers.append({"driver": "on_hold", "impact_hours": 12.0,
                        "detail": "Invoice is on hold pending human action"})

    predicted_completion = now + timedelta(hours=effort)
    slack = round((deadline - predicted_completion).total_seconds() / 3600.0, 2)

    # Risk score: 0 (comfortable) → 100 (certain breach).
    if hours_remaining <= 0:
        risk = 100.0
    elif slack >= sla_target_hours * 0.5:
        risk = 5.0
    else:
        ratio = effort / max(hours_remaining, 0.25)
        risk = max(0.0, min(100.0, 100 * (1 - 1 / (1 + ratio ** 2))))
        risk = round(risk, 1)

    if risk >= 85:
        level = RiskLevel.CRITICAL
    elif risk >= 60:
        level = RiskLevel.HIGH
    elif risk >= 35:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    if hours_remaining <= 0:
        recommendation = "SLA already breached — escalate to Controller and record the root cause."
    elif level == RiskLevel.CRITICAL:
        recommendation = "Escalate now and reassign the approval; the projected path does not fit the window."
    elif level == RiskLevel.HIGH:
        recommendation = "Send a reminder and clear blocking exceptions ahead of other work."
    elif level == RiskLevel.MEDIUM:
        recommendation = "Monitor; prioritise this item in the next queue sweep."
    else:
        recommendation = "No intervention required."

    drivers.insert(
        0,
        {
            "driver": "remaining_workflow_effort",
            "impact_hours": round(remaining_effort_hours(stage), 2),
            "detail": f"Baseline effort left from stage '{stage}'",
        },
    )

    return {
        "age_hours": round(age_hours, 2),
        "hours_remaining": hours_remaining,
        "estimated_effort_hours": round(effort, 2),
        "slack_hours": slack,
        "risk_score": risk,
        "risk_level": str(level),
        "predicted_breach_at": (deadline.isoformat() if slack < 0 else None),
        "predicted_completion_at": predicted_completion.isoformat(),
        "deadline_at": deadline.isoformat(),
        "drivers": drivers,
        "recommended_action": recommendation,
        "requires_human_review": level in {RiskLevel.HIGH, RiskLevel.CRITICAL},
    }
