"""Human-in-the-loop control plane.

Two responsibilities:

1. ``create_checkpoint`` — turn an agent's *proposed* action into a HumanTask.
   This is the only way an agent can express intent; agents never write to the
   system of record themselves.
2. ``decide`` / ``execute_action`` — apply an approved action, then write the
   audit record. Rejections and modifications are recorded with equal weight.

The action registry below is an explicit allow-list. If an ActionKind has no
handler here, it simply cannot happen.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import (
    ACTION_LABELS,
    ROLE_AUTHORITY,
    ActionKind,
    AgentRunStatus,
    ApprovalStatus,
    EventType,
    ExceptionStatus,
    HumanDecision,
    HumanTaskStatus,
    InvoiceStatus,
    MatchResult,
    PaymentStatus,
    RiskLevel,
    Role,
    SLAStatus,
    STAGE_LABELS,
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
    PurchaseOrder,
    PurchaseRequest,
    Supplier,
    SupplierMessage,
    User,
    utcnow,
)
from . import erp as erp_service
from .audit import snapshot, write_audit
from .events import jsonable, notify, record_event
from .policy import PolicyDecision, can_decide

INVOICE_AUDIT_FIELDS = [
    "invoice_number", "status", "stage", "total_amount", "tax_amount", "currency",
    "supplier_id", "po_id", "due_date", "match_result", "on_hold", "approver_id",
    "erp_document_number", "sla_status",
]


class HITLError(Exception):
    """Raised when a decision is not permitted."""


# ==========================================================================
# Checkpoint creation
# ==========================================================================
def _next_task_number(db: Session) -> str:
    count = db.execute(select(func.count(HumanTask.id))).scalar_one() or 0
    return f"HITL-{count + 1001}"


def create_checkpoint(
    db: Session,
    *,
    execution: AgentExecution | None,
    agent_key: str,
    agent_name: str,
    stage: str,
    action_kind: str,
    title: str,
    summary: str,
    rationale: str,
    policy: PolicyDecision,
    confidence: float,
    proposed_payload: dict | None = None,
    diff_preview: list[dict] | None = None,
    evidence: list[dict] | None = None,
    alternatives: list[dict] | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    financial_impact_usd: float = 0.0,
    due_in_hours: float = 8.0,
    assigned_to_id: str | None = None,
) -> HumanTask:
    """Register a pending human decision. Nothing has changed in the business
    data at this point — the payload describes what *would* change."""
    task = HumanTask(
        task_number=_next_task_number(db),
        execution_id=execution.id if execution else None,
        agent_key=agent_key,
        agent_name=agent_name,
        stage=str(stage),
        action_kind=str(action_kind),
        title=title,
        summary=summary,
        rationale=rationale,
        evidence=jsonable(evidence or []),
        proposed_payload=jsonable(proposed_payload or {}),
        diff_preview=jsonable(diff_preview or []),
        alternatives=jsonable(alternatives or []),
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        confidence=round(float(confidence), 4),
        risk_level=policy.risk_level,
        financial_impact_usd=float(financial_impact_usd),
        reversible=policy.reversible,
        required_role=policy.required_role,
        assigned_to_id=assigned_to_id,
        dual_approval_required=policy.dual_approval_required,
        status=HumanTaskStatus.PENDING,
        due_at=utcnow() + timedelta(hours=due_in_hours),
        policy_flags=policy.flags,
        auto_eligible=policy.allow_auto_execute,
        auto_blocked_reason=" ".join(policy.blocked_reasons) or None,
    )
    db.add(task)
    db.flush()

    config = db.execute(select(AgentConfig).where(AgentConfig.agent_key == agent_key)).scalar_one_or_none()
    if config:
        config.proposals_total += 1

    record_event(
        db,
        event_type=EventType.HUMAN_TASK_CREATED,
        title=f"Approval needed · {ACTION_LABELS.get(str(action_kind), str(action_kind))}",
        message=f"{agent_name} proposed: {title}",
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        actor=agent_name,
        actor_type="agent",
        severity="warning" if policy.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} else "info",
        payload={
            "task_id": task.id,
            "task_number": task.task_number,
            "action_kind": str(action_kind),
            "stage": str(stage),
            "confidence": task.confidence,
            "required_role": task.required_role,
            "risk_level": task.risk_level,
        },
    )
    notify(
        db,
        title=f"{agent_name} needs your decision",
        body=title,
        target_role=task.required_role,
        severity="warning" if policy.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} else "info",
        link_entity_type="human_task",
        link_entity_id=task.id,
    )
    write_audit(
        db,
        action="hitl.checkpoint_created",
        description=f"{agent_name} proposed '{title}' and paused for human review.",
        actor=agent_name,
        actor_type="agent",
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        agent_key=agent_key,
        execution_id=execution.id if execution else None,
        human_task_id=task.id,
        confidence=task.confidence,
        after_state=jsonable({"proposed": proposed_payload or {}, "policy": policy.to_dict()}),
    )
    return task


# ==========================================================================
# Decisions
# ==========================================================================
def decide(
    db: Session,
    *,
    task: HumanTask,
    decision: str,
    user: User,
    notes: str | None = None,
    modified_payload: dict | None = None,
) -> dict:
    """Record a human decision and, when approved, execute the action."""
    if task.status != HumanTaskStatus.PENDING:
        raise HITLError(f"Task {task.task_number} was already decided ({task.status}).")

    if not can_decide(user.role, task.required_role):
        raise HITLError(
            f"Role '{user.role}' cannot decide this task — it requires '{task.required_role}' or above."
        )

    if task.dual_approval_required and decision in {HumanDecision.APPROVE, HumanDecision.MODIFY_AND_APPROVE}:
        if not task.second_approver_id:
            task.second_approver_id = user.id
            task.second_approved_at = utcnow()
            task.decision_notes = notes
            db.flush()
            write_audit(
                db,
                action="hitl.first_of_two_approvals",
                description=f"{user.full_name} gave the first of two required approvals.",
                actor=user.full_name,
                actor_type="human",
                actor_role=user.role,
                entity_type=task.entity_type,
                entity_id=task.entity_id,
                entity_label=task.entity_label,
                human_task_id=task.id,
                agent_key=task.agent_key,
            )
            record_event(
                db,
                event_type=EventType.HUMAN_TASK_DECIDED,
                title="First approval recorded",
                message=f"{task.task_number} requires a second approver (impact ${task.financial_impact_usd:,.0f}).",
                entity_type=task.entity_type,
                entity_id=task.entity_id,
                entity_label=task.entity_label,
                actor=user.full_name,
                actor_type="human",
            )
            return {"status": "awaiting_second_approval", "task_id": task.id}
        if task.second_approver_id == user.id:
            raise HITLError("Dual approval requires two distinct approvers.")

    before = {
        "status": task.status,
        "payload": task.proposed_payload,
    }

    task.decided_by = user.full_name
    task.decided_by_role = user.role
    task.decided_at = utcnow()
    task.decision = str(decision)
    task.decision_notes = notes

    config = db.execute(
        select(AgentConfig).where(AgentConfig.agent_key == task.agent_key)
    ).scalar_one_or_none()

    result: dict[str, Any] = {"task_id": task.id, "task_number": task.task_number}

    if decision in {HumanDecision.APPROVE, HumanDecision.MODIFY_AND_APPROVE}:
        payload = dict(task.proposed_payload or {})
        if decision == HumanDecision.MODIFY_AND_APPROVE and modified_payload:
            payload.update(modified_payload)
            task.status = HumanTaskStatus.MODIFIED
            if config:
                config.modified_total += 1
        else:
            task.status = HumanTaskStatus.APPROVED
            if config:
                config.approved_total += 1
        task.applied_payload = jsonable(payload)

        try:
            outcome = execute_action(db, task=task, payload=payload, actor=user)
            task.execution_result = jsonable(outcome)
            result["execution"] = outcome
        except Exception as exc:  # pragma: no cover - defensive
            task.execution_error = str(exc)
            task.status = HumanTaskStatus.PENDING
            task.decided_at = None
            task.decided_by = None
            db.flush()
            raise HITLError(f"Action failed and was not applied: {exc}") from exc

    elif decision == HumanDecision.REJECT:
        task.status = HumanTaskStatus.REJECTED
        if config:
            config.rejected_total += 1
        _on_rejection(db, task, user, notes)

    elif decision == HumanDecision.REQUEST_INFO:
        task.status = HumanTaskStatus.INFO_REQUESTED

    elif decision == HumanDecision.ESCALATE:
        task.status = HumanTaskStatus.ESCALATED
        escalation_role = config.escalation_role if config else Role.CONTROLLER
        task.required_role = escalation_role
        task.status = HumanTaskStatus.PENDING
        task.decided_at = None
        task.decided_by = None
        task.decision = None
        notify(
            db,
            title="Escalated agent proposal",
            body=f"{user.full_name} escalated {task.task_number}: {task.title}",
            target_role=escalation_role,
            severity="warning",
            link_entity_type="human_task",
            link_entity_id=task.id,
        )
        result["escalated_to"] = str(escalation_role)
    else:
        raise HITLError(f"Unknown decision '{decision}'.")

    # Unblock the originating agent run.
    if task.execution_id:
        execution = db.get(AgentExecution, task.execution_id)
        if execution is not None:
            outstanding = db.execute(
                select(func.count(HumanTask.id)).where(
                    HumanTask.execution_id == execution.id,
                    HumanTask.status == HumanTaskStatus.PENDING,
                )
            ).scalar_one()
            if outstanding == 0 and execution.status == AgentRunStatus.AWAITING_HUMAN:
                execution.status = AgentRunStatus.COMPLETED

    # Count a human touch against the invoice (drives the touchless-rate KPI).
    if task.entity_type == "invoice" and task.entity_id:
        invoice = db.get(Invoice, task.entity_id)
        if invoice is not None:
            invoice.human_touches = (invoice.human_touches or 0) + 1

    write_audit(
        db,
        action=f"hitl.{decision}",
        description=f"{user.full_name} ({user.role}) chose '{decision}' on {task.task_number}: {task.title}."
        + (f" Notes: {notes}" if notes else ""),
        actor=user.full_name,
        actor_type="human",
        actor_role=user.role,
        entity_type=task.entity_type,
        entity_id=task.entity_id,
        entity_label=task.entity_label,
        before_state=before,
        after_state={"status": task.status, "applied": task.applied_payload or {}},
        agent_key=task.agent_key,
        execution_id=task.execution_id,
        human_task_id=task.id,
        confidence=task.confidence,
    )
    record_event(
        db,
        event_type=EventType.HUMAN_TASK_DECIDED,
        title=f"Human decision · {decision}",
        message=f"{user.full_name} {decision.replace('_', ' ')}d {task.task_number}: {task.title}",
        entity_type=task.entity_type,
        entity_id=task.entity_id,
        entity_label=task.entity_label,
        actor=user.full_name,
        actor_type="human",
        severity="success" if decision.startswith("approve") or decision == HumanDecision.MODIFY_AND_APPROVE else "info",
        payload={"task_number": task.task_number, "decision": str(decision), "notes": notes},
    )
    db.flush()
    result["status"] = task.status
    return result


def _on_rejection(db: Session, task: HumanTask, user: User, notes: str | None) -> None:
    """A rejection is a signal, not a dead end — park the entity for a human."""
    if task.entity_type == "invoice" and task.entity_id:
        invoice = db.get(Invoice, task.entity_id)
        if invoice is not None:
            invoice.on_hold = True
            invoice.hold_reason = (
                f"Agent proposal rejected by {user.full_name}: {notes or 'no reason supplied'}"
            )
            invoice.status = InvoiceStatus.ON_HOLD


# ==========================================================================
# Action execution — the allow-list
# ==========================================================================
Handler = Callable[[Session, HumanTask, dict, User], dict]
_HANDLERS: dict[str, Handler] = {}


def action(kind: str):
    def wrapper(fn: Handler) -> Handler:
        _HANDLERS[str(kind)] = fn
        return fn

    return wrapper


def execute_action(db: Session, *, task: HumanTask, payload: dict, actor: User) -> dict:
    handler = _HANDLERS.get(str(task.action_kind))
    if handler is None:
        raise HITLError(f"No executor registered for action '{task.action_kind}'.")
    return handler(db, task, payload, actor)


def _invoice(db: Session, task: HumanTask, payload: dict) -> Invoice:
    invoice_id = payload.get("invoice_id") or task.entity_id
    invoice = db.get(Invoice, invoice_id) if invoice_id else None
    if invoice is None:
        raise HITLError("Invoice not found for this action.")
    return invoice


def _advance(db: Session, invoice: Invoice, stage: str, status: str | None, actor_name: str) -> None:
    previous = invoice.stage
    invoice.stage = str(stage)
    if status:
        invoice.status = str(status)
    record_event(
        db,
        event_type=EventType.STAGE_CHANGED,
        title=f"{STAGE_LABELS.get(str(stage), stage)}",
        message=f"{invoice.invoice_number} moved {STAGE_LABELS.get(previous, previous)} → "
                f"{STAGE_LABELS.get(str(stage), stage)}",
        entity_type="invoice",
        entity_id=invoice.id,
        entity_label=invoice.invoice_number,
        actor=actor_name,
        actor_type="human",
    )


# --- Intake / extraction ---------------------------------------------------
@action(ActionKind.UPDATE_INVOICE_FIELDS)
def _update_invoice_fields(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    before = snapshot(invoice, INVOICE_AUDIT_FIELDS)
    fields = payload.get("fields", {}) or {}
    applied: dict[str, Any] = {}

    editable = {
        "invoice_number", "supplier_id", "po_id", "currency", "subtotal", "tax_amount",
        "freight_amount", "total_amount", "invoice_date", "due_date", "contract_id",
    }
    for key, value in fields.items():
        if key not in editable:
            continue
        if key in {"invoice_date", "due_date"} and isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError:
                continue
        setattr(invoice, key, value)
        applied[key] = value

    if "total_amount" in applied:
        invoice.amount_usd = float(applied["total_amount"])
    invoice.extraction_confidence = max(invoice.extraction_confidence, 0.99)

    if payload.get("advance_to"):
        _advance(db, invoice, payload["advance_to"], payload.get("status"), actor.full_name)

    write_audit(
        db,
        action="invoice.fields_updated",
        description=f"Invoice fields corrected on human approval: {', '.join(applied) or 'no change'}.",
        actor=actor.full_name,
        actor_type="human",
        actor_role=actor.role,
        entity_type="invoice",
        entity_id=invoice.id,
        entity_label=invoice.invoice_number,
        before_state=before,
        after_state=snapshot(invoice, INVOICE_AUDIT_FIELDS),
        agent_key=task.agent_key,
        human_task_id=task.id,
    )
    return {"applied_fields": applied, "stage": invoice.stage}


@action(ActionKind.ADVANCE_STAGE)
def _advance_stage(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    before = snapshot(invoice, INVOICE_AUDIT_FIELDS)
    _advance(db, invoice, payload.get("stage", WorkflowStage.VALIDATION), payload.get("status"), actor.full_name)
    if payload.get("match_result"):
        invoice.match_result = payload["match_result"]
    if payload.get("match_details"):
        invoice.match_details = payload["match_details"]
    write_audit(
        db,
        action="invoice.stage_advanced",
        description=f"Stage advanced to {invoice.stage} on human approval.",
        actor=actor.full_name,
        actor_type="human",
        actor_role=actor.role,
        entity_type="invoice",
        entity_id=invoice.id,
        entity_label=invoice.invoice_number,
        before_state=before,
        after_state=snapshot(invoice, INVOICE_AUDIT_FIELDS),
        agent_key=task.agent_key,
        human_task_id=task.id,
    )
    return {"stage": invoice.stage, "status": invoice.status}


@action(ActionKind.HOLD_INVOICE)
def _hold_invoice(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    before = snapshot(invoice, INVOICE_AUDIT_FIELDS)
    invoice.on_hold = True
    invoice.hold_reason = payload.get("reason", "Placed on hold following agent recommendation.")
    invoice.status = InvoiceStatus.ON_HOLD
    write_audit(
        db, action="invoice.held", description=invoice.hold_reason,
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        before_state=before, after_state=snapshot(invoice, INVOICE_AUDIT_FIELDS),
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"on_hold": True, "reason": invoice.hold_reason}


@action(ActionKind.RELEASE_HOLD)
def _release_hold(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    invoice.on_hold = False
    invoice.hold_reason = None
    invoice.status = payload.get("status", InvoiceStatus.VALIDATED)
    write_audit(
        db, action="invoice.hold_released", description=payload.get("reason", "Hold released."),
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"on_hold": False}


# --- Exceptions ------------------------------------------------------------
@action(ActionKind.CREATE_EXCEPTION)
def _create_exception(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    count = db.execute(select(func.count(ExceptionCase.id))).scalar_one() or 0
    case = ExceptionCase(
        case_number=f"EXC-{count + 5001}",
        invoice_id=payload.get("invoice_id") or task.entity_id,
        supplier_id=payload.get("supplier_id"),
        exception_type=payload.get("exception_type", "price_mismatch"),
        severity=payload.get("severity", RiskLevel.MEDIUM),
        status=ExceptionStatus.OPEN,
        title=payload.get("title", "Exception"),
        description=payload.get("description", ""),
        detected_by=task.agent_name,
        financial_impact_usd=float(payload.get("financial_impact_usd", 0.0)),
        proposed_resolution=payload.get("proposed_resolution"),
        proposed_by_agent=task.agent_key,
        agent_confidence=task.confidence,
        sla_due_at=utcnow() + timedelta(hours=float(payload.get("sla_hours", 24))),
    )
    db.add(case)
    db.flush()

    invoice_id = case.invoice_id
    if invoice_id:
        invoice = db.get(Invoice, invoice_id)
        if invoice is not None:
            invoice.status = InvoiceStatus.IN_EXCEPTION
            invoice.stage = WorkflowStage.EXCEPTION
            if payload.get("match_result"):
                invoice.match_result = payload["match_result"]
            if payload.get("match_details"):
                invoice.match_details = payload["match_details"]

    record_event(
        db, event_type=EventType.EXCEPTION_OPENED,
        title=f"Exception opened · {case.exception_type}",
        message=f"{case.case_number}: {case.title}",
        entity_type="invoice", entity_id=case.invoice_id, entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human", severity="warning",
    )
    write_audit(
        db, action="exception.created", description=f"{case.case_number} opened: {case.title}",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="exception", entity_id=case.id, entity_label=case.case_number,
        after_state={"type": case.exception_type, "impact": case.financial_impact_usd},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"exception_id": case.id, "case_number": case.case_number}


@action(ActionKind.RESOLVE_EXCEPTION)
def _resolve_exception(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    case = db.get(ExceptionCase, payload.get("exception_id") or task.entity_id or "")
    if case is None:
        raise HITLError("Exception case not found.")
    before = {"status": case.status, "resolution": case.resolution_notes}
    case.status = ExceptionStatus.RESOLVED
    case.resolution_notes = payload.get("resolution_notes", case.proposed_resolution or "")
    case.resolved_by = actor.full_name
    case.resolved_at = utcnow()
    case.resolved_by_agent = True  # agent-proposed, human-confirmed

    if case.invoice_id:
        invoice = db.get(Invoice, case.invoice_id)
        if invoice is not None:
            remaining = db.execute(
                select(func.count(ExceptionCase.id)).where(
                    ExceptionCase.invoice_id == invoice.id,
                    ExceptionCase.status.notin_([ExceptionStatus.RESOLVED, ExceptionStatus.WRITTEN_OFF]),
                    ExceptionCase.id != case.id,
                )
            ).scalar_one()
            if remaining == 0:
                invoice.status = InvoiceStatus.MATCHED
                invoice.match_result = payload.get("match_result", MatchResult.WITHIN_TOLERANCE)
                _advance(db, invoice, WorkflowStage.APPROVAL, InvoiceStatus.MATCHED, actor.full_name)
            if payload.get("adjust_total") is not None:
                invoice.total_amount = float(payload["adjust_total"])
                invoice.amount_usd = float(payload["adjust_total"])

    record_event(
        db, event_type=EventType.EXCEPTION_RESOLVED,
        title="Exception resolved",
        message=f"{case.case_number} closed by {actor.full_name}",
        entity_type="invoice", entity_id=case.invoice_id, entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human", severity="success",
    )
    write_audit(
        db, action="exception.resolved", description=case.resolution_notes or "",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="exception", entity_id=case.id, entity_label=case.case_number,
        before_state=before, after_state={"status": case.status},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"exception_id": case.id, "status": case.status}


# --- Approval --------------------------------------------------------------
@action(ActionKind.ROUTE_FOR_APPROVAL)
def _route_for_approval(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    approver_id = payload.get("approver_id")
    approver = db.get(User, approver_id) if approver_id else None
    if approver is None:
        raise HITLError("Approver not found for routing.")

    approval = Approval(
        invoice_id=invoice.id,
        approver_id=approver.id,
        original_approver_id=approver.id,
        level=int(payload.get("level", 1)),
        status=ApprovalStatus.PENDING,
        due_at=utcnow() + timedelta(hours=float(payload.get("due_in_hours", 24))),
        routing_reason=payload.get("routing_reason", ""),
    )
    db.add(approval)
    invoice.approver_id = approver.id
    invoice.status = InvoiceStatus.PENDING_APPROVAL
    invoice.stage = WorkflowStage.APPROVAL
    approver.active_workload = (approver.active_workload or 0) + 1

    record_event(
        db, event_type=EventType.APPROVAL_REQUESTED,
        title="Routed for approval",
        message=f"{invoice.invoice_number} → {approver.full_name} ({approver.title or approver.role})",
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=actor.full_name, actor_type="human",
    )
    notify(
        db, title="Invoice awaiting your approval",
        body=f"{invoice.invoice_number} · {invoice.currency} {invoice.total_amount:,.2f}",
        user_id=approver.id, link_entity_type="invoice", link_entity_id=invoice.id,
    )
    write_audit(
        db, action="approval.routed",
        description=f"{invoice.invoice_number} routed to {approver.full_name}. "
                    f"{payload.get('routing_reason', '')}",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        after_state={"approver": approver.full_name, "level": approval.level},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    db.flush()
    return {"approval_id": approval.id, "approver": approver.full_name}


@action(ActionKind.SEND_APPROVAL_REMINDER)
def _send_reminder(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    approval = db.get(Approval, payload.get("approval_id") or "")
    if approval is None:
        raise HITLError("Approval record not found.")
    approval.reminders_sent += 1
    approval.last_reminder_at = utcnow()
    approver = db.get(User, approval.approver_id) if approval.approver_id else None
    notify(
        db, title="Reminder: invoice approval pending",
        body=payload.get("message", "This invoice is approaching its SLA deadline."),
        user_id=approval.approver_id, severity="warning",
        link_entity_type="invoice", link_entity_id=approval.invoice_id,
    )
    record_event(
        db, event_type=EventType.SYSTEM, title="Approval reminder sent",
        message=f"Reminder #{approval.reminders_sent} sent to {approver.full_name if approver else 'approver'}.",
        entity_type="invoice", entity_id=approval.invoice_id, entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human",
    )
    write_audit(
        db, action="approval.reminder_sent",
        description=f"Reminder #{approval.reminders_sent} sent.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=approval.invoice_id, entity_label=task.entity_label,
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"reminders_sent": approval.reminders_sent}


@action(ActionKind.ESCALATE_APPROVAL)
def _escalate_approval(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    approval = db.get(Approval, payload.get("approval_id") or "")
    if approval is None:
        raise HITLError("Approval record not found.")
    escalate_to = db.get(User, payload.get("escalate_to_id") or "")
    if escalate_to is None:
        raise HITLError("Escalation target not found.")
    before = {"approver_id": approval.approver_id, "status": approval.status}
    approval.status = ApprovalStatus.ESCALATED
    approval.escalated = True
    approval.approver_id = escalate_to.id
    approval.due_at = utcnow() + timedelta(hours=float(payload.get("due_in_hours", 8)))

    invoice = db.get(Invoice, approval.invoice_id)
    if invoice is not None:
        invoice.approver_id = escalate_to.id

    notify(
        db, title="Escalated approval",
        body=payload.get("message", "An invoice approval has been escalated to you."),
        user_id=escalate_to.id, severity="warning",
        link_entity_type="invoice", link_entity_id=approval.invoice_id,
    )
    record_event(
        db, event_type=EventType.SYSTEM, title="Approval escalated",
        message=f"Escalated to {escalate_to.full_name}.",
        entity_type="invoice", entity_id=approval.invoice_id, entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human", severity="warning",
    )
    write_audit(
        db, action="approval.escalated",
        description=f"Escalated to {escalate_to.full_name}: {payload.get('reason', '')}",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=approval.invoice_id, entity_label=task.entity_label,
        before_state=before, after_state={"approver_id": escalate_to.id},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"escalated_to": escalate_to.full_name}


@action(ActionKind.REASSIGN_APPROVER)
def _reassign_approver(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    approval = db.get(Approval, payload.get("approval_id") or "")
    if approval is None:
        raise HITLError("Approval record not found.")
    delegate = db.get(User, payload.get("delegate_id") or "")
    if delegate is None:
        raise HITLError("Delegate not found.")
    before = {"approver_id": approval.approver_id}
    previous = db.get(User, approval.approver_id) if approval.approver_id else None
    if previous is not None:
        previous.active_workload = max(0, (previous.active_workload or 0) - 1)
    approval.approver_id = delegate.id
    approval.status = ApprovalStatus.DELEGATED
    delegate.active_workload = (delegate.active_workload or 0) + 1

    invoice = db.get(Invoice, approval.invoice_id)
    if invoice is not None:
        invoice.approver_id = delegate.id

    notify(
        db, title="Invoice delegated to you",
        body=payload.get("message", "You are covering an approval while a colleague is out of office."),
        user_id=delegate.id, link_entity_type="invoice", link_entity_id=approval.invoice_id,
    )
    write_audit(
        db, action="approval.delegated",
        description=f"Rerouted to delegate {delegate.full_name}: {payload.get('reason', '')}",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=approval.invoice_id, entity_label=task.entity_label,
        before_state=before, after_state={"approver_id": delegate.id},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"delegate": delegate.full_name}


# --- Supplier communications ----------------------------------------------
@action(ActionKind.SEND_SUPPLIER_MESSAGE)
def _send_supplier_message(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    message = SupplierMessage(
        thread_id=payload.get("thread_id") or task.entity_id or "",
        supplier_id=payload.get("supplier_id"),
        invoice_id=payload.get("invoice_id"),
        channel=payload.get("channel", "portal"),
        direction="outbound",
        author=f"{actor.full_name} (approved {task.agent_name} draft)",
        body=payload.get("body", ""),
        intent=payload.get("intent"),
        drafted_by_agent=task.agent_key,
        agent_confidence=task.confidence,
        approved_by=actor.full_name,
        sent_at=utcnow(),
        status="sent",
    )
    db.add(message)
    db.flush()
    record_event(
        db, event_type=EventType.SUPPLIER_MESSAGE, title="Supplier message sent",
        message=payload.get("body", "")[:180],
        entity_type="invoice", entity_id=payload.get("invoice_id"), entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human",
    )
    write_audit(
        db, action="supplier.message_sent",
        description=f"Outbound {message.channel} message approved and sent by {actor.full_name}.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="supplier", entity_id=payload.get("supplier_id"), entity_label=task.entity_label,
        after_state={"body": message.body, "channel": message.channel},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"message_id": message.id, "channel": message.channel}


@action(ActionKind.REQUEST_GOODS_RECEIPT)
def _request_goods_receipt(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    notify(
        db, title="Goods receipt requested",
        body=payload.get("message", "Please confirm receipt so the invoice can be matched."),
        user_id=payload.get("requester_id"), severity="warning",
        link_entity_type="invoice", link_entity_id=payload.get("invoice_id"),
    )
    record_event(
        db, event_type=EventType.SYSTEM, title="Goods receipt chased",
        message=payload.get("message", ""),
        entity_type="invoice", entity_id=payload.get("invoice_id"), entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human",
    )
    write_audit(
        db, action="receipt.requested", description=payload.get("message", ""),
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=payload.get("invoice_id"), entity_label=task.entity_label,
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"requested": True}


# --- ERP / payment ---------------------------------------------------------
@action(ActionKind.POST_TO_ERP)
def _post_to_erp(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    before = snapshot(invoice, INVOICE_AUDIT_FIELDS)
    connector = erp_service.get_connector(payload.get("erp_system") or invoice.erp_system)
    result = connector.post_invoice(db, invoice)
    if not result.success:
        raise HITLError(result.message or "ERP posting failed.")

    invoice.erp_document_number = result.document_number
    invoice.erp_posted_at = utcnow()
    invoice.erp_system = result.system
    invoice.status = InvoiceStatus.APPROVED
    _advance(db, invoice, WorkflowStage.PAYMENT, InvoiceStatus.APPROVED, actor.full_name)

    if invoice.po_id:
        po = db.get(PurchaseOrder, invoice.po_id)
        if po is not None:
            po.invoiced_amount = (po.invoiced_amount or 0.0) + invoice.total_amount

    write_audit(
        db, action="erp.invoice_posted", description=result.message,
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        before_state=before, after_state=snapshot(invoice, INVOICE_AUDIT_FIELDS),
        agent_key=task.agent_key, human_task_id=task.id,
    )
    record_event(
        db, event_type=EventType.SYSTEM, title="Posted to ERP",
        message=result.message,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=actor.full_name, actor_type="human", severity="success",
    )
    return {"erp_document_number": result.document_number, "system": result.system}


@action(ActionKind.SCHEDULE_PAYMENT)
def _schedule_payment(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    invoice = _invoice(db, task, payload)
    count = db.execute(select(func.count(Payment.id))).scalar_one() or 0
    scheduled = payload.get("scheduled_date")
    if isinstance(scheduled, str):
        try:
            scheduled = date.fromisoformat(scheduled)
        except ValueError:
            scheduled = None

    payment = Payment(
        payment_number=f"PAY-{count + 9001}",
        invoice_id=invoice.id,
        supplier_id=invoice.supplier_id,
        amount=float(payload.get("amount", invoice.total_amount)),
        currency=invoice.currency,
        discount_captured=float(payload.get("discount_captured", 0.0)),
        method=payload.get("method", "ACH"),
        scheduled_date=scheduled or (invoice.due_date or date.today()),
        status=PaymentStatus.SCHEDULED,
        priority_score=float(payload.get("priority_score", 0.0)),
        score_breakdown=payload.get("score_breakdown", {}),
    )
    db.add(payment)
    invoice.status = InvoiceStatus.SCHEDULED_FOR_PAYMENT
    db.flush()

    record_event(
        db, event_type=EventType.PAYMENT_SCHEDULED, title="Payment scheduled",
        message=f"{payment.payment_number} · {payment.currency} {payment.amount:,.2f} on "
                f"{payment.scheduled_date}",
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=actor.full_name, actor_type="human", severity="success",
    )
    write_audit(
        db, action="payment.scheduled",
        description=f"{payment.payment_number} scheduled for {payment.scheduled_date}. "
                    f"Discount captured: {payment.discount_captured:,.2f}.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="payment", entity_id=payment.id, entity_label=payment.payment_number,
        after_state={"amount": payment.amount, "date": str(payment.scheduled_date)},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"payment_id": payment.id, "payment_number": payment.payment_number}


@action(ActionKind.RELEASE_PAYMENT)
def _release_payment(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    payment = db.get(Payment, payload.get("payment_id") or "")
    if payment is None:
        raise HITLError("Payment not found.")
    before = {"status": payment.status}
    payment.status = PaymentStatus.RELEASED
    payment.released_at = utcnow()
    payment.released_by = actor.full_name

    invoice = db.get(Invoice, payment.invoice_id)
    if invoice is not None:
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = utcnow()
        invoice.closed_at = utcnow()
        invoice.stage = WorkflowStage.CLOSED
        if invoice.received_at:
            invoice.cycle_time_hours = round(
                (utcnow() - invoice.received_at).total_seconds() / 3600.0, 2
            )
        invoice.touchless = (invoice.human_touches or 0) <= 1
        supplier = db.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None
        if supplier is not None:
            supplier.spend_ytd_usd = (supplier.spend_ytd_usd or 0.0) + invoice.amount_usd

    record_event(
        db, event_type=EventType.PAYMENT_RELEASED, title="Payment released",
        message=f"{payment.payment_number} released by {actor.full_name}.",
        entity_type="invoice", entity_id=payment.invoice_id, entity_label=task.entity_label,
        actor=actor.full_name, actor_type="human", severity="success",
    )
    write_audit(
        db, action="payment.released",
        description=f"{payment.payment_number} ({payment.currency} {payment.amount:,.2f}) released.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="payment", entity_id=payment.id, entity_label=payment.payment_number,
        before_state=before, after_state={"status": payment.status},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"payment_number": payment.payment_number, "status": payment.status}


# --- Supplier master / risk ------------------------------------------------
@action(ActionKind.BLOCK_SUPPLIER)
def _block_supplier(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    supplier = db.get(Supplier, payload.get("supplier_id") or task.entity_id or "")
    if supplier is None:
        raise HITLError("Supplier not found.")
    before = {"on_hold": supplier.on_hold, "reason": supplier.hold_reason}
    supplier.on_hold = True
    supplier.hold_reason = payload.get("reason", "Blocked following risk agent finding.")
    write_audit(
        db, action="supplier.blocked", description=supplier.hold_reason,
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
        before_state=before, after_state={"on_hold": True},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    record_event(
        db, event_type=EventType.RISK_ALERT, title="Supplier blocked",
        message=f"{supplier.name}: {supplier.hold_reason}",
        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
        actor=actor.full_name, actor_type="human", severity="critical",
    )
    return {"supplier": supplier.name, "on_hold": True}


@action(ActionKind.UPDATE_SUPPLIER_MASTER)
def _update_supplier_master(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    supplier = db.get(Supplier, payload.get("supplier_id") or task.entity_id or "")
    if supplier is None:
        raise HITLError("Supplier not found.")
    editable = {
        "contact_email", "contact_name", "payment_terms", "bank_account_last4",
        "tax_id", "tax_form_status", "sanctions_status", "risk_level", "tier",
    }
    before = snapshot(supplier, sorted(editable))
    applied = {}
    for key, value in (payload.get("fields") or {}).items():
        if key in editable:
            setattr(supplier, key, value)
            applied[key] = value
    if "bank_account_last4" in applied:
        supplier.bank_changed_at = utcnow()
    write_audit(
        db, action="supplier.master_updated",
        description=f"Vendor master fields updated: {', '.join(applied) or 'none'}.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
        before_state=before, after_state=applied,
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"applied": applied}


@action(ActionKind.FLAG_CONTRACT_BREACH)
def _flag_contract_breach(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    result = _create_exception(
        db,
        task,
        {
            "invoice_id": payload.get("invoice_id") or task.entity_id,
            "supplier_id": payload.get("supplier_id"),
            "exception_type": "contract_rate_breach",
            "severity": payload.get("severity", RiskLevel.HIGH),
            "title": payload.get("title", "Contract rate breach"),
            "description": payload.get("description", ""),
            "financial_impact_usd": payload.get("financial_impact_usd", 0.0),
            "proposed_resolution": payload.get("proposed_resolution"),
        },
        actor,
    )
    return result


# --- Procurement -----------------------------------------------------------
@action(ActionKind.CREATE_PURCHASE_REQUEST)
def _create_purchase_request(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    count = db.execute(select(func.count(PurchaseRequest.id))).scalar_one() or 0
    request = PurchaseRequest(
        request_number=f"PR-{count + 3001}",
        requester_id=payload.get("requester_id"),
        requester_name=payload.get("requester_name", actor.full_name),
        supplier_id=payload.get("supplier_id"),
        description=payload.get("description", ""),
        category=payload.get("category"),
        amount=float(payload.get("amount", 0.0)),
        cost_center=payload.get("cost_center"),
        routing_decision=payload.get("routing_decision"),
        policy_notes=payload.get("policy_notes"),
        status="pending_review",
    )
    db.add(request)
    db.flush()
    write_audit(
        db, action="purchase_request.created", description=request.description,
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="purchase_request", entity_id=request.id, entity_label=request.request_number,
        after_state={"amount": request.amount, "routing": request.routing_decision},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"request_number": request.request_number}


@action(ActionKind.APPROVE_PURCHASE_REQUEST)
def _approve_purchase_request(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    request = db.get(PurchaseRequest, payload.get("request_id") or task.entity_id or "")
    if request is None:
        raise HITLError("Purchase request not found.")
    before = {"status": request.status}
    request.status = "approved"
    request.approved_by = actor.full_name
    request.approved_at = utcnow()
    write_audit(
        db, action="purchase_request.approved",
        description=f"{request.request_number} approved ({request.currency} {request.amount:,.2f}).",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="purchase_request", entity_id=request.id, entity_label=request.request_number,
        before_state=before, after_state={"status": request.status},
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"request_number": request.request_number, "status": request.status}


# --- Command-centre actions ------------------------------------------------
@action(ActionKind.REBALANCE_WORKLOAD)
def _rebalance_workload(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    moves = payload.get("moves", []) or []
    applied = []
    for move in moves:
        approval = db.get(Approval, move.get("approval_id", ""))
        target = db.get(User, move.get("to_user_id", ""))
        if approval is None or target is None:
            continue
        source = db.get(User, approval.approver_id) if approval.approver_id else None
        if source is not None:
            source.active_workload = max(0, (source.active_workload or 0) - 1)
        approval.approver_id = target.id
        target.active_workload = (target.active_workload or 0) + 1
        invoice = db.get(Invoice, approval.invoice_id)
        if invoice is not None:
            invoice.approver_id = target.id
        applied.append({"approval_id": approval.id, "to": target.full_name})
    write_audit(
        db, action="workload.rebalanced",
        description=f"{len(applied)} approvals reassigned to balance queue depth.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="workload", entity_id=None, entity_label="Approval queue",
        after_state={"moves": applied}, agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"moves_applied": len(applied), "detail": applied}


@action(ActionKind.RAISE_EXECUTIVE_ALERT)
def _raise_executive_alert(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    notify(
        db, title=payload.get("title", "SLA risk alert"),
        body=payload.get("body", ""), target_role=payload.get("target_role", Role.CFO),
        severity="critical",
    )
    record_event(
        db, event_type=EventType.SLA_AT_RISK, title=payload.get("title", "Executive alert"),
        message=payload.get("body", ""), actor=actor.full_name, actor_type="human",
        severity="critical",
    )
    write_audit(
        db, action="alert.executive_raised", description=payload.get("body", ""),
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="sla", entity_id=None, entity_label="SLA Command Center",
        agent_key=task.agent_key, human_task_id=task.id,
    )
    return {"alert_sent": True}


@action(ActionKind.NO_OP)
def _no_op(db: Session, task: HumanTask, payload: dict, actor: User) -> dict:
    return {"noted": True}


def expire_overdue_tasks(db: Session) -> int:
    """Housekeeping — mark checkpoints that blew their own review SLA."""
    now = utcnow()
    overdue = db.execute(
        select(HumanTask).where(
            HumanTask.status == HumanTaskStatus.PENDING,
            HumanTask.due_at.isnot(None),
            HumanTask.due_at < now,
        )
    ).scalars().all()
    for task in overdue:
        task.sla_status = SLAStatus.BREACHED
    return len(overdue)


def registered_actions() -> list[str]:
    return sorted(_HANDLERS)
