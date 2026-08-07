"""ORM → JSON serializers used by the API layer."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .enums import (
    ACTION_LABELS,
    AUTONOMY_LABELS,
    ROLE_LABELS,
    STAGE_LABELS,
    HumanTaskStatus,
)
from .models import (
    AgentConfig,
    AgentExecution,
    Approval,
    AuditLog,
    Contract,
    ExceptionCase,
    HumanTask,
    Invoice,
    InvoiceLine,
    Notification,
    Payment,
    PolicyRule,
    PurchaseOrder,
    PurchaseRequest,
    Receipt,
    SLARisk,
    Supplier,
    SupplierMessage,
    User,
    WorkflowEvent,
    utcnow,
)


def iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def user_out(user: User | None) -> dict | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "title": user.title,
        "department": user.department,
        "initials": user.avatar_initials or "".join(p[0] for p in user.full_name.split()[:2]).upper(),
        "approval_limit_usd": user.approval_limit_usd,
        "out_of_office": user.out_of_office,
        "ooo_until": iso(user.ooo_until),
        "delegate_id": user.delegate_id,
        "active_workload": user.active_workload,
    }


def supplier_out(supplier: Supplier | None, *, detail: bool = False) -> dict | None:
    if supplier is None:
        return None
    data = {
        "id": supplier.id,
        "code": supplier.code,
        "name": supplier.name,
        "country": supplier.country,
        "currency": supplier.currency,
        "category": supplier.category,
        "tier": supplier.tier,
        "payment_terms": supplier.payment_terms,
        "early_pay_discount_pct": supplier.early_pay_discount_pct,
        "early_pay_discount_days": supplier.early_pay_discount_days,
        "risk_score": supplier.risk_score,
        "risk_level": supplier.risk_level,
        "sanctions_status": supplier.sanctions_status,
        "on_hold": supplier.on_hold,
        "hold_reason": supplier.hold_reason,
        "spend_ytd_usd": supplier.spend_ytd_usd,
        "invoice_count_ytd": supplier.invoice_count_ytd,
        "on_time_payment_pct": supplier.on_time_payment_pct,
    }
    if detail:
        data.update({
            "legal_name": supplier.legal_name,
            "contact_name": supplier.contact_name,
            "contact_email": supplier.contact_email,
            "bank_account_last4": supplier.bank_account_last4,
            "bank_changed_at": iso(supplier.bank_changed_at),
            "tax_id": supplier.tax_id,
            "tax_form_status": supplier.tax_form_status,
            "tax_form_expiry": iso(supplier.tax_form_expiry),
            "insurance_expiry": iso(supplier.insurance_expiry),
            "sanctions_checked_at": iso(supplier.sanctions_checked_at),
        })
    return data


def invoice_line_out(line: InvoiceLine) -> dict:
    return {
        "id": line.id,
        "line_number": line.line_number,
        "item_code": line.item_code,
        "description": line.description,
        "uom": line.uom,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "line_total": line.line_total,
        "tax_rate": line.tax_rate,
        "match_status": line.match_status,
        "variance_notes": line.variance_notes,
    }


def invoice_out(invoice: Invoice, *, detail: bool = False, db: Session | None = None) -> dict:
    age_hours = round((utcnow() - invoice.received_at).total_seconds() / 3600.0, 2) if invoice.received_at else 0.0
    open_exceptions = [e for e in invoice.exceptions if e.status not in {"resolved", "written_off"}]
    data = {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "supplier_id": invoice.supplier_id,
        "supplier_name": invoice.supplier.name if invoice.supplier else invoice.supplier_name_raw,
        "supplier_tier": invoice.supplier.tier if invoice.supplier else None,
        "po_number": invoice.po.po_number if invoice.po else invoice.po_number_raw,
        "po_id": invoice.po_id,
        "invoice_date": iso(invoice.invoice_date),
        "due_date": iso(invoice.due_date),
        "received_at": iso(invoice.received_at),
        "currency": invoice.currency,
        "subtotal": invoice.subtotal,
        "tax_amount": invoice.tax_amount,
        "freight_amount": invoice.freight_amount,
        "total_amount": invoice.total_amount,
        "amount_usd": invoice.amount_usd,
        "status": invoice.status,
        "stage": invoice.stage,
        "stage_label": STAGE_LABELS.get(invoice.stage, invoice.stage),
        "match_result": invoice.match_result,
        "source_channel": invoice.source_channel,
        "extraction_confidence": invoice.extraction_confidence,
        "touchless": invoice.touchless,
        "human_touches": invoice.human_touches,
        "on_hold": invoice.on_hold,
        "hold_reason": invoice.hold_reason,
        "sla_status": invoice.sla_status,
        "sla_risk_score": invoice.sla_risk_score,
        "sla_due_at": iso(invoice.sla_due_at),
        "age_hours": age_hours,
        "open_exception_count": len(open_exceptions),
        "erp_document_number": invoice.erp_document_number,
        "erp_system": invoice.erp_system,
        "approver_id": invoice.approver_id,
        "paid_at": iso(invoice.paid_at),
        "cycle_time_hours": invoice.cycle_time_hours,
    }
    if detail:
        data.update({
            "supplier": supplier_out(invoice.supplier, detail=True),
            "document_text": invoice.document_text,
            "source_filename": invoice.source_filename,
            "extraction_fields": invoice.extraction_fields,
            "match_details": invoice.match_details,
            "duplicate_of_id": invoice.duplicate_of_id,
            "duplicate_score": invoice.duplicate_score,
            "contract_id": invoice.contract_id,
            "lines": [invoice_line_out(line) for line in sorted(invoice.lines, key=lambda l: l.line_number)],
            "exceptions": [exception_out(e) for e in invoice.exceptions],
            "approvals": [approval_out(a, db) for a in invoice.approvals],
            "po": po_out(invoice.po) if invoice.po else None,
        })
    return data


def po_out(po: PurchaseOrder, *, detail: bool = True) -> dict:
    data = {
        "id": po.id,
        "po_number": po.po_number,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier.name if po.supplier else None,
        "description": po.description,
        "cost_center": po.cost_center,
        "gl_account": po.gl_account,
        "currency": po.currency,
        "total_amount": po.total_amount,
        "invoiced_amount": po.invoiced_amount,
        "received_amount": po.received_amount,
        "open_amount": round((po.total_amount or 0) - (po.invoiced_amount or 0), 2),
        "status": po.status,
        "order_date": iso(po.order_date),
        "erp_system": po.erp_system,
        "contract_id": po.contract_id,
    }
    if detail:
        data["lines"] = [
            {
                "id": line.id,
                "line_number": line.line_number,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
                "received_qty": line.received_qty,
                "invoiced_qty": line.invoiced_qty,
            }
            for line in sorted(po.lines, key=lambda l: l.line_number)
        ]
        data["receipts"] = [receipt_out(r) for r in po.receipts]
    return data


def receipt_out(receipt: Receipt) -> dict:
    return {
        "id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "po_id": receipt.po_id,
        "received_date": iso(receipt.received_date),
        "received_by": receipt.received_by,
        "total_quantity": receipt.total_quantity,
        "total_value": receipt.total_value,
        "lines": receipt.lines_json or [],
        "status": receipt.status,
    }


def contract_out(contract: Contract) -> dict:
    return {
        "id": contract.id,
        "contract_number": contract.contract_number,
        "supplier_id": contract.supplier_id,
        "supplier_name": contract.supplier.name if contract.supplier else None,
        "title": contract.title,
        "start_date": iso(contract.start_date),
        "end_date": iso(contract.end_date),
        "currency": contract.currency,
        "total_value": contract.total_value,
        "payment_terms": contract.payment_terms,
        "rate_card": contract.rate_card or {},
        "allowed_charges": contract.allowed_charges or [],
        "volume_discounts": contract.volume_discounts or [],
        "auto_renew": contract.auto_renew,
        "status": contract.status,
    }


def exception_out(case: ExceptionCase) -> dict:
    return {
        "id": case.id,
        "case_number": case.case_number,
        "invoice_id": case.invoice_id,
        "invoice_number": case.invoice.invoice_number if case.invoice else None,
        "supplier_id": case.supplier_id,
        "exception_type": case.exception_type,
        "severity": case.severity,
        "status": case.status,
        "title": case.title,
        "description": case.description,
        "detected_by": case.detected_by,
        "financial_impact_usd": case.financial_impact_usd,
        "proposed_resolution": case.proposed_resolution,
        "proposed_by_agent": case.proposed_by_agent,
        "agent_confidence": case.agent_confidence,
        "resolution_notes": case.resolution_notes,
        "resolved_by": case.resolved_by,
        "resolved_at": iso(case.resolved_at),
        "created_at": iso(case.created_at),
        "sla_due_at": iso(case.sla_due_at),
        "age_hours": round((utcnow() - case.created_at).total_seconds() / 3600.0, 2) if case.created_at else 0.0,
    }


def approval_out(approval: Approval, db: Session | None = None) -> dict:
    approver = db.get(User, approval.approver_id) if db and approval.approver_id else None
    return {
        "id": approval.id,
        "invoice_id": approval.invoice_id,
        "invoice_number": approval.invoice.invoice_number if approval.invoice else None,
        "amount": approval.invoice.total_amount if approval.invoice else None,
        "currency": approval.invoice.currency if approval.invoice else None,
        "approver_id": approval.approver_id,
        "approver_name": approver.full_name if approver else None,
        "level": approval.level,
        "status": approval.status,
        "requested_at": iso(approval.requested_at),
        "decided_at": iso(approval.decided_at),
        "decision_notes": approval.decision_notes,
        "due_at": iso(approval.due_at),
        "reminders_sent": approval.reminders_sent,
        "escalated": approval.escalated,
        "routing_reason": approval.routing_reason,
        "age_hours": round((utcnow() - approval.requested_at).total_seconds() / 3600.0, 2)
        if approval.requested_at else 0.0,
    }


def payment_out(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "payment_number": payment.payment_number,
        "invoice_id": payment.invoice_id,
        "invoice_number": payment.invoice.invoice_number if payment.invoice else None,
        "supplier_id": payment.supplier_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "discount_captured": payment.discount_captured,
        "method": payment.method,
        "scheduled_date": iso(payment.scheduled_date),
        "released_at": iso(payment.released_at),
        "released_by": payment.released_by,
        "status": payment.status,
        "priority_score": payment.priority_score,
        "score_breakdown": payment.score_breakdown or {},
    }


def human_task_out(task: HumanTask, *, detail: bool = False) -> dict:
    overdue = bool(task.due_at and task.due_at < utcnow() and task.status == HumanTaskStatus.PENDING)
    data = {
        "id": task.id,
        "task_number": task.task_number,
        "execution_id": task.execution_id,
        "agent_key": task.agent_key,
        "agent_name": task.agent_name,
        "stage": task.stage,
        "stage_label": STAGE_LABELS.get(task.stage, task.stage),
        "action_kind": task.action_kind,
        "action_label": ACTION_LABELS.get(task.action_kind, task.action_kind),
        "title": task.title,
        "summary": task.summary,
        "entity_type": task.entity_type,
        "entity_id": task.entity_id,
        "entity_label": task.entity_label,
        "confidence": task.confidence,
        "risk_level": task.risk_level,
        "financial_impact_usd": task.financial_impact_usd,
        "reversible": task.reversible,
        "required_role": task.required_role,
        "required_role_label": ROLE_LABELS.get(task.required_role, task.required_role),
        "dual_approval_required": task.dual_approval_required,
        "second_approver_id": task.second_approver_id,
        "status": task.status,
        "decision": task.decision,
        "decided_by": task.decided_by,
        "decided_by_role": task.decided_by_role,
        "decided_at": iso(task.decided_at),
        "decision_notes": task.decision_notes,
        "due_at": iso(task.due_at),
        "created_at": iso(task.created_at),
        "overdue": overdue,
        "policy_flags": task.policy_flags or [],
        "auto_eligible": task.auto_eligible,
        "auto_blocked_reason": task.auto_blocked_reason,
        "diff_preview": task.diff_preview or [],
    }
    if detail:
        data.update({
            "rationale": task.rationale,
            "evidence": task.evidence or [],
            "proposed_payload": task.proposed_payload or {},
            "applied_payload": task.applied_payload or {},
            "alternatives": task.alternatives or [],
            "execution_result": task.execution_result or {},
            "execution_error": task.execution_error,
        })
    return data


def execution_out(execution: AgentExecution, *, detail: bool = False) -> dict:
    data = {
        "id": execution.id,
        "run_number": execution.run_number,
        "agent_key": execution.agent_key,
        "agent_name": execution.agent_name,
        "trigger": execution.trigger,
        "triggered_by": execution.triggered_by,
        "entity_type": execution.entity_type,
        "entity_id": execution.entity_id,
        "entity_label": execution.entity_label,
        "status": execution.status,
        "goal": execution.goal,
        "conclusion": execution.conclusion,
        "confidence": execution.confidence,
        "reasoning_engine": execution.reasoning_engine,
        "escalated": execution.escalated,
        "escalation_reason": execution.escalation_reason,
        "duration_ms": execution.duration_ms,
        "tokens_used": execution.tokens_used,
        "handoff_to": execution.handoff_to,
        "created_at": iso(execution.created_at),
        "error": execution.error,
        "task_count": len(execution.tasks),
    }
    if detail:
        data.update({
            "plan": execution.plan or [],
            "observations": execution.observations or [],
            "reasoning": execution.reasoning,
            "evidence": execution.evidence or [],
            "policy_evaluation": execution.policy_evaluation or {},
            "tasks": [human_task_out(t) for t in execution.tasks],
        })
    return data


def agent_config_out(config: AgentConfig, descriptor: dict | None = None) -> dict:
    total_decided = config.approved_total + config.rejected_total + config.modified_total
    data = {
        "id": config.id,
        "agent_key": config.agent_key,
        "display_name": config.display_name,
        "enabled": config.enabled,
        "autonomy_level": config.autonomy_level,
        "autonomy_label": AUTONOMY_LABELS.get(config.autonomy_level, config.autonomy_level),
        "confidence_threshold": config.confidence_threshold,
        "max_auto_amount_usd": config.max_auto_amount_usd,
        "require_dual_approval_above_usd": config.require_dual_approval_above_usd,
        "allowed_actions": config.allowed_actions or [],
        "escalation_role": config.escalation_role,
        "notes": config.notes,
        "runs_total": config.runs_total,
        "proposals_total": config.proposals_total,
        "approved_total": config.approved_total,
        "rejected_total": config.rejected_total,
        "modified_total": config.modified_total,
        "acceptance_rate": round(
            (config.approved_total + config.modified_total) / total_decided * 100, 1
        ) if total_decided else None,
    }
    if descriptor:
        data.update({
            "suite": descriptor.get("suite", "p2p"),
            "role": descriptor["role"],
            "mission": descriptor["mission"],
            "goals": descriptor["goals"],
            "tools": descriptor["tools"],
            "skills": descriptor["skills"],
            "prompt": descriptor["prompt"],
            "inputs": descriptor.get("inputs", []),
            "outputs": descriptor.get("outputs", []),
            "accepts_attachments": descriptor.get("accepts_attachments", False),
            "produces_artifacts": descriptor.get("produces_artifacts", False),
        })
    return data


def event_out(event: WorkflowEvent) -> dict:
    return {
        "id": event.id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "entity_label": event.entity_label,
        "actor": event.actor,
        "actor_type": event.actor_type,
        "title": event.title,
        "message": event.message,
        "severity": event.severity,
        "payload": event.payload or {},
        "created_at": iso(event.created_at),
    }


def audit_out(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "sequence": entry.sequence,
        "timestamp": iso(entry.timestamp),
        "actor": entry.actor,
        "actor_type": entry.actor_type,
        "actor_role": entry.actor_role,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "entity_label": entry.entity_label,
        "description": entry.description,
        "before_state": entry.before_state or {},
        "after_state": entry.after_state or {},
        "agent_key": entry.agent_key,
        "execution_id": entry.execution_id,
        "human_task_id": entry.human_task_id,
        "confidence": entry.confidence,
        "hitl_enforced": entry.hitl_enforced,
        "hash_chain": entry.hash_chain,
    }


def sla_risk_out(risk: SLARisk) -> dict:
    return {
        "id": risk.id,
        "invoice_id": risk.invoice_id,
        "entity_label": risk.entity_label,
        "stage": risk.stage,
        "stage_label": STAGE_LABELS.get(risk.stage, risk.stage),
        "risk_score": risk.risk_score,
        "risk_level": risk.risk_level,
        "hours_remaining": risk.hours_remaining,
        "drivers": risk.drivers or [],
        "recommended_action": risk.recommended_action,
        "status": risk.status,
    }


def message_out(message: SupplierMessage) -> dict:
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "supplier_id": message.supplier_id,
        "invoice_id": message.invoice_id,
        "channel": message.channel,
        "direction": message.direction,
        "author": message.author,
        "body": message.body,
        "intent": message.intent,
        "drafted_by_agent": message.drafted_by_agent,
        "agent_confidence": message.agent_confidence,
        "approved_by": message.approved_by,
        "sent_at": iso(message.sent_at),
        "status": message.status,
        "created_at": iso(message.created_at),
    }


def purchase_request_out(request: PurchaseRequest) -> dict:
    return {
        "id": request.id,
        "request_number": request.request_number,
        "requester_name": request.requester_name,
        "supplier_id": request.supplier_id,
        "description": request.description,
        "category": request.category,
        "amount": request.amount,
        "currency": request.currency,
        "needed_by": iso(request.needed_by),
        "cost_center": request.cost_center,
        "routing_decision": request.routing_decision,
        "status": request.status,
        "policy_notes": request.policy_notes,
        "approved_by": request.approved_by,
        "approved_at": iso(request.approved_at),
        "created_at": iso(request.created_at),
    }


def policy_out(rule: PolicyRule) -> dict:
    return {
        "id": rule.id,
        "key": rule.key,
        "name": rule.name,
        "category": rule.category,
        "description": rule.description,
        "value_type": rule.value_type,
        "value": rule.value,
        "unit": rule.unit,
        "enabled": rule.enabled,
        "editable": rule.editable,
        "last_changed_by": rule.last_changed_by,
        "updated_at": iso(rule.updated_at),
    }


def notification_out(note: Notification) -> dict:
    return {
        "id": note.id,
        "user_id": note.user_id,
        "target_role": note.target_role,
        "title": note.title,
        "body": note.body,
        "severity": note.severity,
        "link_entity_type": note.link_entity_type,
        "link_entity_id": note.link_entity_id,
        "read": note.read,
        "created_at": iso(note.created_at),
    }
