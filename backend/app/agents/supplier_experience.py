"""Agent 5 — Supplier Experience.

Mission: answer supplier enquiries accurately across channels. Every outbound
message is a draft until a human approves it — the supplier never receives
unreviewed text.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AutonomyLevel, InvoiceStatus, Role, WorkflowStage
from ..models import ExceptionCase, Invoice, Payment, Supplier, SupplierMessage
from ..skills import supplier_lookup
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec

INTENTS = {
    "invoice_status": ["status", "where is", "received", "processing", "progress", "stuck"],
    "payment_date": ["pay", "payment", "when will", "remittance", "paid", "settle"],
    "missing_information": ["missing", "need", "require", "what do you need", "rejected", "on hold"],
    "banking_verification": ["bank", "account", "routing", "iban", "remit to", "change our"],
    "po_details": ["po", "purchase order", "order number"],
    "dispute": ["dispute", "disagree", "incorrect", "wrong amount", "short pay", "shortpaid"],
}


def classify(text: str) -> tuple[str, float]:
    body = (text or "").lower()
    scores = {
        intent: sum(1 for kw in keywords if kw in body)
        for intent, keywords in INTENTS.items()
    }
    best = max(scores, key=lambda k: scores[k]) if scores else "invoice_status"
    hits = scores.get(best, 0)
    if hits == 0:
        return "invoice_status", 0.45
    confidence = min(0.97, 0.62 + 0.12 * hits)
    return best, round(confidence, 4)


class SupplierExperienceAgent(BaseAgent):
    key = "supplier_experience"
    name = "Supplier Experience Agent"
    role = "Answers supplier enquiries from system-of-record facts, never from guesswork."
    mission = "Resolve supplier enquiries on first contact and cut inquiry volume reaching the AP team."
    goals = [
        "Reduce supplier inquiry volume reaching humans by 60%.",
        "Answer only from verified system-of-record data.",
        "Never disclose banking details or confirm a bank change over an inbound channel.",
    ]
    tools = ["Vendor portal", "Email", "Microsoft Teams", "Invoice ledger", "Payment ledger"]
    skills = ["supplier_lookup", "invoice_status", "payment_forecast", "correspondence"]
    default_stage = WorkflowStage.VALIDATION
    escalation_role = Role.AP_MANAGER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.SEND_SUPPLIER_MESSAGE, ActionKind.NO_OP]

    inputs = [
        IOSpec("message_id", "The inbound supplier enquiry to answer.", kind="data", required=True),
        IOSpec("invoice & payment ledger", "The system-of-record facts the reply may cite.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Intent classification", "invoice_status / payment_date / missing_information / "
                                        "banking_verification / po_details / dispute.",
               kind="record"),
        IOSpec("Drafted reply", "Reply grounded only in retrieved records — never sent unreleased.",
               kind="record"),
        IOSpec("Checkpoint", "Release the reply to the supplier — a human sends it.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        message = db.get(SupplierMessage, context.get("message_id", ""))
        if message is None:
            return (None, None, None)
        supplier = db.get(Supplier, message.supplier_id) if message.supplier_id else None
        return ("supplier_message", message.id, supplier.name if supplier else "Supplier enquiry")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Identify the supplier and authenticate the channel", "supplier_lookup",
                     "Answers must never go to an unverified party."),
            PlanStep(2, "Classify the enquiry intent", "intent_classification",
                     "The intent decides which ledger to read."),
            PlanStep(3, "Retrieve the facts from the system of record", "invoice_status",
                     "Every statement in the reply must be traceable."),
            PlanStep(4, "Draft a reply grounded only in retrieved facts", "correspondence",
                     "No speculative dates or commitments."),
            PlanStep(5, "Submit the draft for human release", "hitl_checkpoint",
                     "Outbound supplier communication is irreversible."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        message = db.get(SupplierMessage, context.get("message_id", ""))
        if message is None:
            return [Observation("lookup", "Supplier message not found.", ok=False)]
        context["message"] = message

        observations: list[Observation] = []
        supplier = db.get(Supplier, message.supplier_id) if message.supplier_id else None
        if supplier is None:
            resolution = supplier_lookup.lookup(db, message.author or "")
            if resolution.get("resolved"):
                supplier = db.get(Supplier, resolution["resolved"]["supplier_id"])
            observations.append(
                Observation("supplier_lookup",
                            f"Sender resolved to {supplier.name}." if supplier
                            else "Sender could not be matched to a vendor master record.",
                            resolution, ok=supplier is not None)
            )
        else:
            observations.append(
                Observation("supplier_lookup",
                            f"Authenticated portal session for {supplier.name} ({supplier.code}).",
                            {"supplier_id": supplier.id, "tier": supplier.tier})
            )
        context["supplier"] = supplier

        intent, intent_conf = classify(message.body)
        context["intent"], context["intent_confidence"] = intent, intent_conf
        observations.append(
            Observation("intent_classification",
                        f"Intent '{intent}' at {intent_conf:.0%} confidence.",
                        {"intent": intent, "confidence": intent_conf},
                        ok=intent_conf >= 0.7)
        )

        invoice = db.get(Invoice, message.invoice_id) if message.invoice_id else None
        invoices: list[Invoice] = []
        if supplier is not None:
            invoices = db.execute(
                select(Invoice).where(Invoice.supplier_id == supplier.id)
                .order_by(Invoice.received_at.desc()).limit(10)
            ).scalars().all()
        if invoice is None and invoices:
            # Try to pin the enquiry to a specific invoice number mentioned in the body.
            body = (message.body or "").upper()
            invoice = next((inv for inv in invoices if inv.invoice_number.upper() in body), None)
        context["invoice"], context["invoices"] = invoice, invoices

        observations.append(
            Observation(
                "invoice_status",
                f"{invoice.invoice_number}: {invoice.status} at stage {invoice.stage}."
                if invoice else f"{len(invoices)} open invoice(s) found for this supplier.",
                {
                    "invoice": {
                        "invoice_number": invoice.invoice_number,
                        "status": invoice.status,
                        "stage": invoice.stage,
                        "total": invoice.total_amount,
                        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                    } if invoice else None,
                    "recent": [
                        {"invoice_number": i.invoice_number, "status": i.status,
                         "total": i.total_amount} for i in invoices[:5]
                    ],
                },
                ok=invoice is not None or bool(invoices),
            )
        )

        payment = None
        if invoice is not None:
            payment = db.execute(
                select(Payment).where(Payment.invoice_id == invoice.id)
                .order_by(Payment.created_at.desc())
            ).scalars().first()
        context["payment"] = payment

        blockers: list[ExceptionCase] = []
        if invoice is not None:
            blockers = [e for e in invoice.exceptions if e.status not in {"resolved", "written_off"}]
        context["blockers"] = blockers
        observations.append(
            Observation(
                "blocker_check",
                f"{len(blockers)} open exception(s) blocking this invoice."
                if blockers else "No open exceptions blocking this invoice.",
                [{"case_number": b.case_number, "type": b.exception_type} for b in blockers],
                ok=not blockers,
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        message: SupplierMessage | None = context.get("message")
        supplier: Supplier | None = context.get("supplier")
        invoice: Invoice | None = context.get("invoice")
        payment: Payment | None = context.get("payment")
        blockers = context.get("blockers", [])
        intent = context.get("intent", "invoice_status")
        confidence = float(context.get("intent_confidence", 0.5))

        if message is None:
            return AgentDecision("Message not found.", 0.0, escalate=True)

        evidence = [
            evidence_item("Channel", message.channel, "intake"),
            evidence_item("Supplier", supplier.name if supplier else "unresolved", "supplier_lookup"),
            evidence_item("Intent", f"{intent} ({confidence:.0%})", "intent_classification"),
            evidence_item("Invoice", invoice.invoice_number if invoice else "not identified", "invoice_status"),
        ]
        rules: list[str] = []

        if supplier is None:
            return AgentDecision(
                conclusion="Sender is not an authenticated supplier — no information may be disclosed.",
                confidence=0.95,
                decision_rules=["Unauthenticated sender → disclose nothing; route to AP."],
                evidence=evidence,
                escalate=True,
                escalation_reason="Unauthenticated supplier enquiry.",
            )

        # Banking verification is never handled conversationally.
        if intent == "banking_verification":
            rules.append("Banking-change requests are never handled over an inbound channel → hard escalation.")
            draft = (
                f"Hello,\n\nThank you for contacting us. For your protection, we cannot action or confirm "
                f"changes to banking details over this channel. A member of our supplier maintenance team "
                f"will contact you using the details already on file to verify the request.\n\n"
                f"Kind regards,\nAccounts Payable"
            )
            return AgentDecision(
                conclusion="Banking enquiry detected — replying with the verification protocol only, "
                           "and escalating to supplier maintenance.",
                confidence=0.97,
                decision_rules=rules,
                evidence=evidence,
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.SEND_SUPPLIER_MESSAGE,
                        title="Reply with the banking-change protocol (no details disclosed)",
                        summary="The draft neither confirms nor changes bank details; it routes the request "
                                "to out-of-band verification.",
                        payload={
                            "supplier_id": supplier.id,
                            "invoice_id": invoice.id if invoice else None,
                            "thread_id": message.thread_id,
                            "channel": message.channel,
                            "intent": intent,
                            "body": draft,
                        },
                        diff_preview=[{"field": "message", "label": "Draft reply", "before": "—", "after": draft}],
                        confidence=0.97,
                        stage=WorkflowStage.VALIDATION,
                        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
                        due_in_hours=4,
                        extra_flags=["banking_request"],
                    )
                ],
                escalate=True,
                escalation_reason="Supplier requested a banking change.",
            )

        if invoice is None:
            recent = context.get("invoices", [])[:5]
            listing = "\n".join(
                f"  • {i.invoice_number} — {i.currency} {i.total_amount:,.2f} — {i.status.replace('_', ' ')}"
                for i in recent
            ) or "  • no invoices currently in process"
            draft = (
                f"Hello,\n\nThank you for your enquiry. We could not identify a specific invoice number in "
                f"your message. Here is the current status of your most recent submissions:\n\n{listing}\n\n"
                f"If the invoice you are asking about is not listed, please reply with the invoice number "
                f"and date and we will investigate.\n\nKind regards,\nAccounts Payable"
            )
            rules.append("No specific invoice identified → reply with a verified summary and request the number.")
            return AgentDecision(
                conclusion="Replying with a verified summary of open invoices and asking for the invoice number.",
                confidence=max(0.75, confidence),
                decision_rules=rules,
                evidence=evidence,
                proposals=[_draft_action(supplier, None, message, intent, draft, max(0.75, confidence))],
            )

        # ---- Build a fact-grounded reply --------------------------------
        status_text = invoice.status.replace("_", " ")
        lines = [f"Hello,\n\nThank you for your enquiry about invoice {invoice.invoice_number} "
                 f"({invoice.currency} {invoice.total_amount:,.2f})."]

        if intent == "payment_date":
            if payment is not None and payment.status in {"released", "paid"}:
                lines.append(
                    f"\nThis invoice was paid on "
                    f"{payment.released_at:%d %B %Y} by {payment.method}, reference {payment.payment_number}."
                )
                confidence = max(confidence, 0.96)
                rules.append("Payment ledger holds a released payment → state the settled facts.")
            elif payment is not None and payment.scheduled_date:
                lines.append(
                    f"\nPayment is scheduled for {payment.scheduled_date:%d %B %Y} "
                    f"({payment.method}), reference {payment.payment_number}."
                )
                confidence = max(confidence, 0.94)
                rules.append("Payment is scheduled → quote the scheduled date, not an estimate.")
            elif blockers:
                lines.append(
                    f"\nWe cannot confirm a payment date yet because the invoice is held pending: "
                    + "; ".join(b.title for b in blockers) + "."
                )
                rules.append("Open blockers exist → do not promise a payment date.")
                confidence = min(confidence, 0.88)
            elif invoice.due_date:
                lines.append(
                    f"\nThe invoice is currently at the '{status_text}' stage and carries a due date of "
                    f"{invoice.due_date:%d %B %Y} under {supplier.payment_terms} terms. "
                    f"We expect to settle on or before that date."
                )
                rules.append("No payment record yet → quote contractual terms only, never a promise.")
            else:
                lines.append(f"\nThe invoice is currently at the '{status_text}' stage.")

        elif intent == "missing_information":
            if blockers:
                needed = "\n".join(f"  • {b.title}: {b.description or b.proposed_resolution or ''}"
                                   for b in blockers)
                lines.append(f"\nWe need the following before we can continue:\n\n{needed}")
                confidence = max(confidence, 0.92)
                rules.append("Open exceptions describe exactly what is missing → quote them verbatim.")
            else:
                lines.append("\nNothing is outstanding from your side — the invoice is progressing normally.")

        elif intent == "po_details":
            po_number = invoice.po.po_number if invoice.po else (invoice.po_number_raw or "not recorded")
            lines.append(f"\nThis invoice is matched to purchase order {po_number}.")
            rules.append("PO reference read directly from the matched record.")

        elif intent == "dispute":
            lines.append(
                f"\nWe have logged your dispute regarding invoice {invoice.invoice_number}. "
                f"An accounts payable specialist will review the detail and respond directly."
            )
            confidence = min(confidence, 0.80)
            rules.append("Disputes are commercial conversations → acknowledge only, hand to a human.")

        else:  # invoice_status
            lines.append(f"\nCurrent status: {status_text} (stage: {invoice.stage.replace('_', ' ')}).")
            if blockers:
                lines.append("\nOutstanding items holding progress:\n" +
                             "\n".join(f"  • {b.title}" for b in blockers))
            elif invoice.due_date:
                lines.append(f"\nExpected payment date: {invoice.due_date:%d %B %Y}.")
            rules.append("Status read directly from the invoice record; no forecast offered beyond due date.")

        lines.append("\n\nKind regards,\nAccounts Payable")
        draft = "".join(lines)

        rules.append(f"Reply contains only facts drawn from {len(evidence)} retrieved record(s).")
        escalate = intent == "dispute" or bool(blockers and intent == "payment_date")

        return AgentDecision(
            conclusion=f"Drafted a '{intent}' reply for {supplier.name} regarding "
                       f"{invoice.invoice_number}; awaiting release approval.",
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=[_draft_action(supplier, invoice, message, intent, draft, confidence)],
            escalate=escalate,
            escalation_reason="Supplier dispute requires an AP owner." if intent == "dispute" else None,
        )


def _draft_action(
    supplier: Supplier,
    invoice: Invoice | None,
    message: SupplierMessage,
    intent: str,
    draft: str,
    confidence: float,
) -> ProposedAction:
    return ProposedAction(
        action_kind=ActionKind.SEND_SUPPLIER_MESSAGE,
        title=f"Release reply to {supplier.name}",
        summary=f"Drafted answer to a '{intent}' enquiry on the {message.channel} channel. "
                f"Every statement is sourced from the system of record.",
        payload={
            "supplier_id": supplier.id,
            "invoice_id": invoice.id if invoice else None,
            "thread_id": message.thread_id,
            "channel": message.channel,
            "intent": intent,
            "body": draft,
        },
        diff_preview=[{"field": "message", "label": "Draft reply", "before": "—", "after": draft}],
        confidence=confidence,
        stage=WorkflowStage.VALIDATION,
        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
        due_in_hours=6,
    )
