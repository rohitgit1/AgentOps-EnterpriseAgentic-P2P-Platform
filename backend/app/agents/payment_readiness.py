"""Agent 6 — Payment Readiness.

Mission: rank approved invoices for the payment run and never let a
compliance-blocked supplier through. Treasury releases; the agent ranks.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    AutonomyLevel,
    InvoiceStatus,
    PaymentStatus,
    RiskLevel,
    Role,
    WorkflowStage,
)
from ..models import Invoice, Payment, Supplier
from ..services.policy import PolicyStore
from ..skills import payment_prioritization, vendor_risk
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec


class PaymentReadinessAgent(BaseAgent):
    key = "payment_readiness"
    name = "Payment Readiness Agent"
    role = "Builds the payment run proposal; Treasury approves every release."
    mission = "Pay the right invoices on the right day — capturing discounts, avoiding late fees, blocking risk."
    goals = [
        "Capture available early-payment discounts before they expire.",
        "Keep on-time payment above 98% for tier-1 suppliers.",
        "Block any payment to a supplier under compliance review.",
    ]
    tools = ["Invoice ledger", "Supplier terms", "Vendor risk screening", "Cash calendar"]
    skills = ["due_date_analysis", "discount_detection", "payment_priority_scoring", "vendor_risk"]
    default_stage = WorkflowStage.PAYMENT
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.92
    allowed_actions = [ActionKind.SCHEDULE_PAYMENT, ActionKind.RELEASE_PAYMENT, ActionKind.HOLD_INVOICE]

    inputs = [
        IOSpec("approved invoices", "Approved, ERP-posted, unpaid invoices — read automatically.",
               kind="data", required=False),
        IOSpec("invoice_id", "Restrict the run to one invoice.", kind="data", required=False),
        IOSpec("supplier terms & risk", "Discount terms, tier and compliance screening.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Payment run ranking", "priority_score = due_risk + supplier_tier + discount_value + sla_risk, "
                                      "with each component shown.",
               kind="record"),
        IOSpec("Discount capture", "Available early-pay discount and its deadline per invoice.",
               kind="record"),
        IOSpec("Checkpoint", "Post to ERP / schedule payment / release payment / hold on compliance.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        if context.get("invoice_id"):
            invoice = db.get(Invoice, context["invoice_id"])
            if invoice:
                return ("invoice", invoice.id, invoice.invoice_number)
        return ("payment_run", None, "Payment run proposal")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Collect approved, unpaid invoices", "ledger_scan",
                     "Only approved and ERP-posted items are eligible."),
            PlanStep(2, "Screen each supplier for payment blockers", "vendor_risk",
                     "Compliance blocks outrank cash optimisation."),
            PlanStep(3, "Score urgency, tier, discount and SLA risk", "payment_priority_scoring",
                     "Score = due_risk + supplier_tier + discount_value + sla_risk."),
            PlanStep(4, "Assemble the run and quantify discount capture", "run_assembly",
                     "Treasury needs the cash number, not a list."),
            PlanStep(5, "Submit the run for Treasury approval", "hitl_checkpoint",
                     "Money never moves without a named approver."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []
        store = PolicyStore(db)
        freeze_days = int(store.number("risk.bank_change_freeze_days", 10))

        query = select(Invoice).where(
            Invoice.status.in_([InvoiceStatus.APPROVED, InvoiceStatus.SCHEDULED_FOR_PAYMENT]),
            Invoice.paid_at.is_(None),
        )
        if context.get("invoice_id"):
            query = select(Invoice).where(Invoice.id == context["invoice_id"])
        candidates = db.execute(query).scalars().all()

        already_scheduled = {
            p.invoice_id
            for p in db.execute(
                select(Payment).where(Payment.status.in_(["scheduled", "released", "paid"]))
            ).scalars().all()
        }
        candidates = [inv for inv in candidates if inv.id not in already_scheduled]

        # An approved invoice that has not reached the ERP cannot be paid — the
        # posting is its own checkpoint before any cash decision is considered.
        unposted = [inv for inv in candidates if not inv.erp_document_number]
        candidates = [inv for inv in candidates if inv.erp_document_number]
        context["unposted"] = unposted

        observations.append(
            Observation("ledger_scan",
                        f"{len(candidates)} ERP-posted invoice(s) awaiting a payment decision; "
                        f"{len(unposted)} approved but not yet posted.",
                        {"count": len(candidates), "unposted": len(unposted)},
                        ok=bool(candidates) or bool(unposted))
        )

        scored: list[dict] = []
        blocked: list[dict] = []
        today = date.today()

        for invoice in candidates:
            supplier = db.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None
            if supplier is None:
                blocked.append({"invoice": invoice.invoice_number, "reason": "Supplier not resolved."})
                continue

            risk = vendor_risk.assess(supplier, bank_freeze_days=freeze_days, today=today)
            if risk["payment_blocking"] or supplier.on_hold:
                blocked.append({
                    "invoice_id": invoice.id,
                    "invoice": invoice.invoice_number,
                    "supplier": supplier.name,
                    "amount": invoice.total_amount,
                    "reason": supplier.hold_reason or risk["recommended_action"],
                    "risk_level": risk["risk_level"],
                })
                continue

            score = payment_prioritization.score(
                amount=float(invoice.total_amount or 0.0),
                due_date=invoice.due_date,
                supplier_tier=supplier.tier,
                early_pay_discount_pct=supplier.early_pay_discount_pct or 0.0,
                early_pay_discount_days=supplier.early_pay_discount_days or 0,
                invoice_date=invoice.invoice_date,
                sla_risk_score=invoice.sla_risk_score or 0.0,
                today=today,
            )
            scored.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "supplier_id": supplier.id,
                "supplier": supplier.name,
                "tier": supplier.tier,
                "amount": float(invoice.total_amount or 0.0),
                "currency": invoice.currency,
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                **score,
            })

        scored.sort(key=lambda s: s["priority_score"], reverse=True)
        context["scored"], context["blocked"] = scored, blocked

        # Scheduled payments whose date has arrived need a release decision.
        due_releases = [
            p for p in db.execute(
                select(Payment).where(Payment.status == PaymentStatus.SCHEDULED)
            ).scalars().all()
            if p.scheduled_date and p.scheduled_date <= today
        ]
        if context.get("invoice_id"):
            due_releases = [p for p in due_releases if p.invoice_id == context["invoice_id"]]
        context["due_releases"] = due_releases
        observations.append(
            Observation(
                "release_queue",
                f"{len(due_releases)} scheduled payment(s) have reached their pay date and "
                f"need a Controller release." if due_releases
                else "No scheduled payments are due for release today.",
                [{"payment_number": p.payment_number, "amount": p.amount,
                  "scheduled_date": p.scheduled_date.isoformat()} for p in due_releases],
            )
        )

        observations.append(
            Observation(
                "vendor_risk",
                f"{len(blocked)} invoice(s) blocked by supplier compliance conditions."
                if blocked else "No supplier compliance blocks in this run.",
                blocked, ok=not blocked,
            )
        )
        discount_total = sum(s["discount_opportunity"]["amount"] for s in scored
                             if s["discount_opportunity"]["available"])
        overdue = [s for s in scored if s["overdue"]]
        context["discount_total"], context["overdue"] = discount_total, overdue
        observations.append(
            Observation(
                "payment_priority_scoring",
                f"Scored {len(scored)} invoice(s). {len(overdue)} overdue. "
                f"{discount_total:,.2f} of early-pay discount is still capturable.",
                {"top": scored[:8], "discount_total": discount_total, "overdue": len(overdue)},
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        scored = context.get("scored", [])
        blocked = context.get("blocked", [])
        discount_total = context.get("discount_total", 0.0)
        overdue = context.get("overdue", [])

        evidence = [
            evidence_item("Eligible invoices", str(len(scored)), "ledger_scan"),
            evidence_item("Blocked by compliance", str(len(blocked)), "vendor_risk"),
            evidence_item("Overdue", str(len(overdue)), "payment_priority_scoring"),
            evidence_item("Discount at stake", f"{discount_total:,.2f}", "discount_detection"),
        ]
        rules = [
            "payment_score = due_risk + supplier_tier + discount_value + sla_risk.",
            "Compliance blocks are absolute — they are removed from the run, not down-ranked.",
            "Treasury approval is mandatory for every scheduled payment.",
        ]
        proposals: list[ProposedAction] = []

        # Post-to-ERP is irreversible and always requires an AP Manager sign-off.
        for invoice in context.get("unposted", []):
            amount = float(invoice.total_amount or 0.0)
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.POST_TO_ERP,
                    title=f"Post {invoice.invoice_number} to {invoice.erp_system}",
                    summary=(
                        f"{invoice.invoice_number} is approved and matched "
                        f"({invoice.currency} {amount:,.2f}) but has no ERP document. "
                        f"Posting creates the payable and cannot be reversed without a journal entry."
                    ),
                    payload={"invoice_id": invoice.id, "erp_system": invoice.erp_system},
                    diff_preview=[
                        {"field": "erp_document_number", "label": "ERP document",
                         "before": "—", "after": "assigned on posting"},
                        {"field": "status", "label": "Status",
                         "before": invoice.status, "after": "approved · posted"},
                    ],
                    confidence=0.96,
                    financial_impact_usd=amount,
                    stage=WorkflowStage.PAYMENT,
                    entity_type="invoice", entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    due_in_hours=6,
                    extra_flags=["irreversible"],
                )
            )

        for payment in context.get("due_releases", []):
            invoice = db.get(Invoice, payment.invoice_id)
            supplier = db.get(Supplier, payment.supplier_id) if payment.supplier_id else None
            if supplier is not None and supplier.on_hold:
                continue  # a blocked supplier never reaches a release proposal
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.RELEASE_PAYMENT,
                    title=f"Release {payment.payment_number} · "
                          f"{payment.currency} {payment.amount:,.2f}",
                    summary=(
                        f"{payment.payment_number} for "
                        f"{invoice.invoice_number if invoice else 'invoice'} "
                        f"({supplier.name if supplier else 'supplier'}) reached its scheduled date "
                        f"{payment.scheduled_date}. "
                        + (f"Releasing captures {payment.discount_captured:,.2f} of early-pay discount. "
                           if payment.discount_captured else "")
                        + "Funds leave the account on approval and cannot be recalled."
                    ),
                    payload={"payment_id": payment.id},
                    diff_preview=[
                        {"field": "status", "label": "Payment status",
                         "before": payment.status, "after": "released"},
                        {"field": "amount", "label": "Amount",
                         "before": "—", "after": f"{payment.currency} {payment.amount:,.2f}"},
                    ],
                    confidence=0.95,
                    financial_impact_usd=float(payment.amount or 0.0),
                    stage=WorkflowStage.PAYMENT,
                    entity_type="invoice", entity_id=payment.invoice_id,
                    entity_label=invoice.invoice_number if invoice else payment.payment_number,
                    due_in_hours=4,
                    extra_flags=["irreversible", "cash_movement"],
                )
            )

        for item in blocked:
            if not item.get("invoice_id"):
                continue
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.HOLD_INVOICE,
                    title=f"Hold payment · {item['invoice']}",
                    summary=f"{item['supplier']} is not payable: {item['reason']}",
                    payload={"invoice_id": item["invoice_id"], "reason": item["reason"]},
                    confidence=0.96,
                    financial_impact_usd=float(item.get("amount") or 0.0),
                    stage=WorkflowStage.PAYMENT,
                    entity_type="invoice", entity_id=item["invoice_id"], entity_label=item["invoice"],
                    due_in_hours=4,
                    extra_flags=["compliance_block"],
                )
            )

        # Top-ranked items become individual scheduling proposals so Treasury can
        # approve, modify the date, or reject them one by one.
        for item in scored[: int(context.get("limit", 8))]:
            breakdown = item["score_breakdown"]
            discount = item["discount_opportunity"]
            summary = (
                f"{item['supplier']} ({item['tier']}) · {item['currency']} {item['amount']:,.2f} · "
                f"due {item['due_date'] or 'n/a'} ({item['days_to_due']} days). "
                f"Score {item['priority_score']:.1f} = due {breakdown['due_risk']:.0f} "
                f"+ tier {breakdown['supplier_tier']:.0f} + discount {breakdown['discount_value']:.0f} "
                f"+ SLA {breakdown['sla_risk']:.0f}."
            )
            if discount["available"]:
                summary += (
                    f" Paying by {discount['deadline']} captures {discount['amount']:,.2f} "
                    f"({discount['pct']:.1f}%)."
                )
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.SCHEDULE_PAYMENT,
                    title=f"Schedule {item['invoice_number']} for {item['recommended_pay_date']}",
                    summary=summary,
                    payload={
                        "invoice_id": item["invoice_id"],
                        "amount": item["amount"],
                        "scheduled_date": item["recommended_pay_date"],
                        "discount_captured": discount["amount"] if discount["available"] else 0.0,
                        "method": "ACH",
                        "priority_score": item["priority_score"],
                        "score_breakdown": breakdown,
                    },
                    diff_preview=[
                        {"field": "scheduled_date", "label": "Pay date", "before": item["due_date"] or "—",
                         "after": item["recommended_pay_date"]},
                        {"field": "discount_captured", "label": "Discount captured", "before": "0.00",
                         "after": f"{discount['amount']:,.2f}" if discount["available"] else "0.00"},
                    ],
                    alternatives=[
                        {"option": "Pay on due date",
                         "detail": f"Forgo {discount['amount']:,.2f} discount" if discount["available"]
                         else "No discount impact",
                         "payload": {"scheduled_date": item["due_date"], "discount_captured": 0.0}},
                        {"option": "Defer one cycle", "detail": "Preserves cash; risks late payment.",
                         "payload": {}},
                    ],
                    confidence=0.95 if item["overdue"] or discount["available"] else 0.93,
                    financial_impact_usd=item["amount"],
                    stage=WorkflowStage.PAYMENT,
                    entity_type="invoice", entity_id=item["invoice_id"],
                    entity_label=item["invoice_number"],
                    due_in_hours=8,
                )
            )

        rules.insert(0, "An approved invoice must reach the ERP before it can enter a payment run.")

        if not proposals:
            return AgentDecision(
                conclusion="No invoices are ready for a payment decision right now.",
                confidence=0.95, decision_rules=rules, evidence=evidence,
            )

        return AgentDecision(
            conclusion=(
                f"Payment run proposal: {len([p for p in proposals if p.action_kind == ActionKind.SCHEDULE_PAYMENT])} "
                f"invoice(s) recommended for scheduling, {len(blocked)} blocked on compliance, "
                f"{discount_total:,.2f} of discount capturable."
            ),
            confidence=0.94,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=bool(blocked),
            escalation_reason=f"{len(blocked)} supplier(s) failed compliance screening." if blocked else None,
        )
