"""Agent 3 — Approval Acceleration.

Mission: prevent approval-related SLA breaches. Reminder before escalation,
no duplicate notifications, delegation policy respected.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    ApprovalStatus,
    AutonomyLevel,
    Role,
    WorkflowStage,
)
from ..models import Approval, Invoice, User, utcnow
from ..services.policy import PolicyStore
from ..skills import approval_routing, sla_prediction
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item


class ApprovalAccelerationAgent(BaseAgent):
    key = "approval_acceleration"
    name = "Approval Acceleration Agent"
    role = "Keeps approvals moving without breaching delegation or audit policy."
    mission = "Prevent invoices from breaching SLA while they sit in an approval queue."
    goals = [
        "Reduce approval cycle time from days to hours.",
        "Escalate proactively rather than retrospectively.",
        "Preserve audit compliance and delegation policy at all times.",
    ]
    tools = ["ERP", "Approval queue", "User calendar", "Delegation matrix", "Notification service"]
    skills = ["approval_lookup", "calendar_access", "escalation_planning", "delegation_management"]
    default_stage = WorkflowStage.APPROVAL
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [
        ActionKind.ROUTE_FOR_APPROVAL,
        ActionKind.SEND_APPROVAL_REMINDER,
        ActionKind.ESCALATE_APPROVAL,
        ActionKind.REASSIGN_APPROVER,
    ]

    def entity_ref(self, db: Session, context: dict):
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        return ("invoice", invoice.id, invoice.invoice_number) if invoice else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Read the current approval state", "approval_lookup",
                     "Decides whether this is a routing problem or a chasing problem."),
            PlanStep(2, "Check approver availability and delegation", "calendar_access",
                     "Chasing someone who is out of office wastes the SLA window."),
            PlanStep(3, "Forecast SLA breach risk", "sla_prediction",
                     "Intervention should be proportionate to real risk."),
            PlanStep(4, "Choose reminder, reroute or escalation", "escalation_planning",
                     "Policy: reminder before escalation; never both at once."),
            PlanStep(5, "Submit the intervention for approval", "hitl_checkpoint",
                     "Even a reminder is an outbound action a human signs off on."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return [Observation("approval_lookup", "Invoice not found.", ok=False)]

        observations: list[Observation] = []
        store = PolicyStore(db)
        context["thresholds"] = {
            "reminder_hours": store.number("sla.approval_reminder_hours", 48),
            "escalation_hours": store.number("sla.approval_escalation_hours", 72),
            "cycle_hours": store.number("sla.invoice_cycle_hours", 24),
        }

        approval = db.execute(
            select(Approval)
            .where(Approval.invoice_id == invoice.id, Approval.status.in_([
                ApprovalStatus.PENDING, ApprovalStatus.DELEGATED, ApprovalStatus.ESCALATED
            ]))
            .order_by(Approval.requested_at.desc())
        ).scalars().first()
        context["approval"] = approval

        age_hours = round((utcnow() - invoice.received_at).total_seconds() / 3600.0, 2)
        context["age_hours"] = age_hours

        if approval is None:
            observations.append(
                Observation("approval_lookup",
                            f"No open approval exists; invoice has been in flight {age_hours:.1f}h.",
                            {"age_hours": age_hours}, ok=False)
            )
            routing = approval_routing.route(
                db, amount_usd=float(invoice.amount_usd or invoice.total_amount or 0.0)
            )
            context["routing"] = routing
            observations.append(
                Observation("approval_routing",
                            f"Recommended approver: {routing['approver']['name']} "
                            f"({routing['approver']['title'] or routing['approver']['role']})."
                            if routing.get("approver") else "No qualified approver available.",
                            routing, ok=bool(routing.get("approver")))
            )
        else:
            approver = db.get(User, approval.approver_id) if approval.approver_id else None
            context["approver"] = approver
            pending_hours = round((utcnow() - approval.requested_at).total_seconds() / 3600.0, 2)
            context["pending_hours"] = pending_hours
            observations.append(
                Observation(
                    "approval_lookup",
                    f"Pending with {approver.full_name if approver else 'unassigned'} for "
                    f"{pending_hours:.1f}h · {approval.reminders_sent} reminder(s) sent"
                    + (" · already escalated" if approval.escalated else "."),
                    {
                        "approval_id": approval.id,
                        "approver": approver.full_name if approver else None,
                        "pending_hours": pending_hours,
                        "reminders_sent": approval.reminders_sent,
                        "escalated": approval.escalated,
                        "due_at": approval.due_at.isoformat() if approval.due_at else None,
                    },
                )
            )
            if approver is not None:
                delegate = db.get(User, approver.delegate_id) if approver.delegate_id else None
                observations.append(
                    Observation(
                        "calendar_access",
                        f"{approver.full_name} is out of office"
                        + (f" until {approver.ooo_until:%Y-%m-%d}" if approver.ooo_until else "")
                        + (f"; delegate on file is {delegate.full_name}." if delegate else "; no delegate on file.")
                        if approver.out_of_office
                        else f"{approver.full_name} is available · queue depth {approver.active_workload or 0}.",
                        {
                            "out_of_office": approver.out_of_office,
                            "ooo_until": approver.ooo_until.isoformat() if approver.ooo_until else None,
                            "delegate": delegate.full_name if delegate else None,
                            "delegate_id": delegate.id if delegate else None,
                            "workload": approver.active_workload or 0,
                        },
                        ok=not approver.out_of_office,
                    )
                )
                context["delegate"] = db.get(User, approver.delegate_id) if approver.delegate_id else None

        approver = context.get("approver")
        forecast = sla_prediction.predict(
            stage=invoice.stage,
            received_at=invoice.received_at,
            sla_target_hours=context["thresholds"]["cycle_hours"],
            open_exceptions=len([e for e in invoice.exceptions if e.status not in {"resolved", "written_off"}]),
            approver_out_of_office=bool(approver and approver.out_of_office),
            approver_workload=(approver.active_workload if approver else 0) or 0,
            supplier_risk_level=invoice.supplier.risk_level if invoice.supplier else "low",
            on_hold=invoice.on_hold,
        )
        context["forecast"] = forecast
        observations.append(
            Observation(
                "sla_prediction",
                f"SLA risk {forecast['risk_score']:.0f}/100 ({forecast['risk_level']}), "
                f"{forecast['hours_remaining']:.1f}h remaining against "
                f"{forecast['estimated_effort_hours']:.1f}h of estimated work.",
                forecast,
                ok=forecast["risk_level"] in {"low", "medium"},
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return AgentDecision("Invoice not found.", 0.0, escalate=True)

        approval: Approval | None = context.get("approval")
        approver: User | None = context.get("approver")
        delegate: User | None = context.get("delegate")
        forecast = context.get("forecast", {})
        thresholds = context.get("thresholds", {})
        age_hours = context.get("age_hours", 0.0)
        pending_hours = context.get("pending_hours", 0.0)
        amount = float(invoice.amount_usd or invoice.total_amount or 0.0)

        evidence = [
            evidence_item("Invoice age", f"{age_hours:.1f}h since receipt", "approval_lookup"),
            evidence_item("SLA risk", f"{forecast.get('risk_score', 0):.0f}/100 "
                                      f"({forecast.get('risk_level')})", "sla_prediction"),
            evidence_item("Hours remaining", f"{forecast.get('hours_remaining', 0):.1f}h", "sla_prediction"),
            evidence_item("Reminder threshold", f"{thresholds.get('reminder_hours')}h", "policy"),
            evidence_item("Escalation threshold", f"{thresholds.get('escalation_hours')}h", "policy"),
        ]
        rules: list[str] = []

        # ---- Not yet routed ----------------------------------------------
        if approval is None:
            routing = context.get("routing", {})
            if not routing.get("approver"):
                return AgentDecision(
                    conclusion="No approver with sufficient authority is available; Controller must intervene.",
                    confidence=0.6,
                    decision_rules=["No qualified, available approver → escalate to Controller."],
                    evidence=evidence,
                    escalate=True,
                    escalation_reason="No qualified approver available.",
                )
            chosen = routing["approver"]
            rules.append(f"Invoice value {amount:,.2f} requires an approver with at least that limit.")
            rules.append("Lowest-authority qualified approver with the shortest queue is preferred.")
            if routing.get("rerouted_from"):
                rules.append(f"Primary approver {routing['rerouted_from']['name']} is out of office → delegate used.")
            return AgentDecision(
                conclusion=f"Route {invoice.invoice_number} to {chosen['name']} for approval.",
                confidence=0.94,
                decision_rules=rules,
                evidence=evidence + [evidence_item("Routing basis", routing["reason"], "approval_routing")],
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.ROUTE_FOR_APPROVAL,
                        title=f"Route to {chosen['name']} for approval",
                        summary=routing["reason"],
                        payload={
                            "invoice_id": invoice.id,
                            "approver_id": chosen["id"],
                            "level": routing.get("level", 1),
                            "due_in_hours": max(4.0, forecast.get("hours_remaining", 12) * 0.6),
                            "routing_reason": routing["reason"],
                        },
                        alternatives=[
                            {"option": alt["name"], "detail": f"{alt['role']} · queue {alt['workload']}",
                             "payload": {"approver_id": alt["id"]}}
                            for alt in routing.get("alternates", [])
                        ],
                        diff_preview=[{"field": "approver_id", "label": "Approver",
                                       "before": "—", "after": chosen["name"]}],
                        confidence=0.94,
                        financial_impact_usd=amount,
                        stage=WorkflowStage.APPROVAL,
                        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                        due_in_hours=4,
                    )
                ],
            )

        # ---- Approver is out of office → reroute before chasing ----------
        if approver is not None and approver.out_of_office:
            if delegate is not None and delegate.approval_limit_usd >= amount:
                rules.append("Policy: if approver_ooo → reroute (a reminder to an absent approver is wasted).")
                return AgentDecision(
                    conclusion=f"{approver.full_name} is out of office; reroute to delegate {delegate.full_name}.",
                    confidence=0.95,
                    decision_rules=rules,
                    evidence=evidence,
                    proposals=[
                        ProposedAction(
                            action_kind=ActionKind.REASSIGN_APPROVER,
                            title=f"Reroute to delegate {delegate.full_name}",
                            summary=(
                                f"{approver.full_name} is out of office"
                                + (f" until {approver.ooo_until:%d %b}" if approver.ooo_until else "")
                                + f". The delegation matrix names {delegate.full_name} "
                                  f"(limit ${delegate.approval_limit_usd:,.0f}) as cover."
                            ),
                            payload={
                                "approval_id": approval.id,
                                "delegate_id": delegate.id,
                                "reason": "Primary approver out of office; delegation matrix applied.",
                                "message": f"You are covering approval of {invoice.invoice_number} "
                                           f"({invoice.currency} {invoice.total_amount:,.2f}).",
                            },
                            diff_preview=[{"field": "approver", "label": "Approver",
                                           "before": approver.full_name, "after": delegate.full_name}],
                            confidence=0.95,
                            financial_impact_usd=amount,
                            stage=WorkflowStage.APPROVAL,
                            entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                            due_in_hours=3,
                        )
                    ],
                )
            rules.append("Approver is out of office with no qualified delegate → escalate.")

        # ---- Escalation threshold ----------------------------------------
        escalation_hours = thresholds.get("escalation_hours", 72)
        reminder_hours = thresholds.get("reminder_hours", 48)

        if age_hours >= escalation_hours or forecast.get("risk_level") == "critical":
            if approval.escalated:
                rules.append("Already escalated → avoid duplicate escalation; hold for the current owner.")
                return AgentDecision(
                    conclusion=f"{invoice.invoice_number} is already escalated with "
                               f"{approver.full_name if approver else 'the escalation owner'}. No further action.",
                    confidence=0.9,
                    decision_rules=rules,
                    evidence=evidence,
                )
            target = approval_routing.route(
                db, amount_usd=amount, exclude_ids=[approval.approver_id or ""],
                minimum_role=Role.CONTROLLER,
            )
            if not target.get("approver"):
                return AgentDecision(
                    conclusion="Escalation required but no Controller is available.",
                    confidence=0.55, decision_rules=rules, evidence=evidence,
                    escalate=True, escalation_reason="No escalation target available.",
                )
            rules.append(f"Policy: invoice_age {age_hours:.0f}h ≥ {escalation_hours}h → escalate().")
            return AgentDecision(
                conclusion=f"Escalate {invoice.invoice_number} to {target['approver']['name']} — "
                           f"{forecast.get('hours_remaining', 0):.1f}h of SLA remain.",
                confidence=0.93,
                decision_rules=rules,
                evidence=evidence,
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.ESCALATE_APPROVAL,
                        title=f"Escalate to {target['approver']['name']}",
                        summary=(
                            f"Pending {pending_hours:.1f}h with "
                            f"{approver.full_name if approver else 'the approver'} after "
                            f"{approval.reminders_sent} reminder(s). SLA risk is "
                            f"{forecast.get('risk_score', 0):.0f}/100 with "
                            f"{forecast.get('hours_remaining', 0):.1f}h left."
                        ),
                        payload={
                            "approval_id": approval.id,
                            "escalate_to_id": target["approver"]["id"],
                            "due_in_hours": 6,
                            "reason": f"Age {age_hours:.0f}h exceeded the {escalation_hours:.0f}h policy threshold.",
                            "message": f"Escalated approval: {invoice.invoice_number} "
                                       f"({invoice.currency} {invoice.total_amount:,.2f}).",
                        },
                        confidence=0.93,
                        financial_impact_usd=amount,
                        stage=WorkflowStage.APPROVAL,
                        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                        due_in_hours=2,
                    )
                ],
                escalate=True,
                escalation_reason=f"Approval aged {age_hours:.0f}h.",
            )

        # ---- Reminder threshold ------------------------------------------
        if age_hours >= reminder_hours or forecast.get("risk_level") == "high":
            hours_since_last = (
                (utcnow() - approval.last_reminder_at).total_seconds() / 3600.0
                if approval.last_reminder_at else 999.0
            )
            if hours_since_last < 12:
                rules.append("A reminder went out within the last 12h → suppress to avoid duplicate notification.")
                return AgentDecision(
                    conclusion=f"Reminder already sent {hours_since_last:.1f}h ago; suppressing a duplicate.",
                    confidence=0.9, decision_rules=rules, evidence=evidence,
                )
            rules.append(f"Policy: invoice_age {age_hours:.0f}h ≥ {reminder_hours}h → send_reminder().")
            rules.append("Reminder is preferred over escalation while the escalation threshold is unmet.")
            return AgentDecision(
                conclusion=f"Send reminder #{approval.reminders_sent + 1} to "
                           f"{approver.full_name if approver else 'the approver'}.",
                confidence=0.95,
                decision_rules=rules,
                evidence=evidence,
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.SEND_APPROVAL_REMINDER,
                        title=f"Remind {approver.full_name if approver else 'the approver'}",
                        summary=f"{invoice.invoice_number} has been pending {pending_hours:.1f}h. "
                                f"{forecast.get('hours_remaining', 0):.1f}h of SLA remain.",
                        payload={
                            "approval_id": approval.id,
                            "message": (
                                f"{invoice.invoice_number} ({invoice.currency} "
                                f"{invoice.total_amount:,.2f}) is awaiting your approval and has "
                                f"{forecast.get('hours_remaining', 0):.0f}h of SLA remaining."
                            ),
                        },
                        confidence=0.95,
                        financial_impact_usd=0.0,
                        stage=WorkflowStage.APPROVAL,
                        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                        due_in_hours=4,
                    )
                ],
            )

        rules.append(f"Age {age_hours:.0f}h is below the {reminder_hours:.0f}h reminder threshold → no action.")
        return AgentDecision(
            conclusion=f"{invoice.invoice_number} is tracking on time; no intervention warranted.",
            confidence=0.96,
            decision_rules=rules,
            evidence=evidence,
        )
