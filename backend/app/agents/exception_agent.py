"""Agent 4 — Exception Resolution.

Mission: diagnose open AP exceptions and propose the resolution, with the
alternatives a human would otherwise have to construct themselves.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    AutonomyLevel,
    ExceptionStatus,
    ExceptionType,
    MatchResult,
    Role,
    WorkflowStage,
)
from ..models import Contract, ExceptionCase, Invoice, PurchaseOrder, Supplier, utcnow
from ..skills import exception_resolution
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec


class ExceptionResolutionAgent(BaseAgent):
    key = "exception_resolution"
    name = "Exception Resolution Agent"
    role = "Diagnoses AP exceptions and proposes the resolution for human confirmation."
    mission = "Resolve AP exceptions the same day they are raised, with a defensible rationale."
    goals = [
        "Propose a correct first-time resolution for 60% of exceptions.",
        "Cut exception aging by 70%.",
        "Never write off value without an explicit human decision.",
    ]
    tools = ["Exception queue", "Contract rate card", "PO / receipt history", "Supplier correspondence"]
    skills = ["exception_resolution", "variance_analysis", "contract_parsing", "duplicate_detection"]
    default_stage = WorkflowStage.EXCEPTION
    escalation_role = Role.AP_MANAGER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [
        ActionKind.RESOLVE_EXCEPTION,
        ActionKind.SEND_SUPPLIER_MESSAGE,
        ActionKind.REQUEST_GOODS_RECEIPT,
        ActionKind.UPDATE_INVOICE_FIELDS,
        ActionKind.HOLD_INVOICE,
    ]

    inputs = [
        IOSpec("exception_id", "The exception case to diagnose.", kind="data", required=True),
        IOSpec("contract & PO context", "Rate card and purchase order, fetched automatically.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Diagnosis", "Recommended resolution with confidence and the priced alternatives.",
               kind="record"),
        IOSpec("Supplier message draft", "Where the resolution needs the supplier, a drafted message.",
               kind="record"),
        IOSpec("Checkpoint", "Resolve / chase receipt / correct / send message — AP decides.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        case = db.get(ExceptionCase, context.get("exception_id", ""))
        return ("exception", case.id, case.case_number) if case else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Read the exception and its originating invoice", "exception_lookup",
                     "Resolution depends on what actually failed, not the label."),
            PlanStep(2, "Pull contract and PO context", "contract_parsing",
                     "The contract usually decides who is right about price."),
            PlanStep(3, "Apply the resolution playbook", "exception_resolution",
                     "Codified AP practice beats ad-hoc judgement under time pressure."),
            PlanStep(4, "Draft any supplier communication", "correspondence",
                     "A draft saves the analyst the writing, not the decision."),
            PlanStep(5, "Submit resolution and alternatives for approval", "hitl_checkpoint",
                     "The analyst picks the option; the agent shows the trade-off."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        case = db.get(ExceptionCase, context.get("exception_id", ""))
        if case is None:
            return [Observation("exception_lookup", "Exception not found.", ok=False)]

        observations: list[Observation] = []
        invoice = db.get(Invoice, case.invoice_id) if case.invoice_id else None
        supplier = db.get(Supplier, case.supplier_id or (invoice.supplier_id if invoice else "")) \
            if (case.supplier_id or invoice) else None
        context["case"], context["invoice"], context["supplier"] = case, invoice, supplier

        age_hours = round((utcnow() - case.created_at).total_seconds() / 3600.0, 2)
        context["age_hours"] = age_hours
        observations.append(
            Observation(
                "exception_lookup",
                f"{case.case_number} · {case.exception_type} · severity {case.severity} · "
                f"open {age_hours:.1f}h · impact {case.financial_impact_usd:,.2f}.",
                {
                    "case_number": case.case_number,
                    "type": case.exception_type,
                    "severity": case.severity,
                    "age_hours": age_hours,
                    "impact": case.financial_impact_usd,
                    "description": case.description,
                },
                ok=age_hours < 24,
            )
        )

        contract = None
        po = None
        if invoice is not None:
            po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
            contract_id = invoice.contract_id or (po.contract_id if po else None)
            if contract_id:
                contract = db.get(Contract, contract_id)
            if contract is None and supplier is not None:
                contract = db.execute(
                    select(Contract).where(Contract.supplier_id == supplier.id, Contract.status == "active")
                ).scalars().first()
        context["contract"], context["po"] = contract, po

        observations.append(
            Observation(
                "contract_parsing",
                f"Contract {contract.contract_number} applies "
                f"({len(contract.rate_card or {})} rate-card items, expires {contract.end_date})."
                if contract else "No active contract governs this spend.",
                {
                    "contract_number": contract.contract_number if contract else None,
                    "rate_card": contract.rate_card if contract else {},
                    "end_date": contract.end_date.isoformat() if contract and contract.end_date else None,
                },
                ok=contract is not None,
            )
        )

        # Locate the specific contested line, where one exists.
        contested = None
        if invoice is not None and (invoice.match_details or {}).get("line_results"):
            failures = [ln for ln in invoice.match_details["line_results"] if ln.get("status") != "matched"]
            if failures:
                contested = max(failures, key=lambda ln: abs(ln.get("variance_amount", 0.0)))
        context["contested"] = contested

        contract_price = None
        if contested and contract and contract.rate_card:
            contract_price = (contract.rate_card or {}).get(str(contested.get("item_code") or "").upper())
        if contract_price is None and contested:
            contract_price = contested.get("po_unit_price")
        context["contract_price"] = contract_price

        play = exception_resolution.playbook(
            exception_type=case.exception_type,
            context={
                "variance_amount": case.financial_impact_usd
                if case.exception_type != ExceptionType.DUPLICATE_INVOICE else 0.0,
                "tolerance_abs": 50.0,
                "invoice_unit_price": contested.get("invoice_unit_price") if contested else None,
                "contract_unit_price": contract_price,
                "supplier_name": supplier.name if supplier else "the supplier",
                "invoice_number": invoice.invoice_number if invoice else case.case_number,
                "amount": invoice.total_amount if invoice else 0.0,
                "suggested_tax_amount": (invoice.match_details or {}).get("suggested_tax_amount")
                if invoice else None,
            },
        )
        context["play"] = play
        observations.append(
            Observation(
                "exception_resolution",
                f"Playbook recommends '{play['recommended']}' at {play['confidence']:.0%} confidence.",
                play,
                ok=play["confidence"] >= 0.85,
            )
        )

        history = db.execute(
            select(ExceptionCase).where(
                ExceptionCase.supplier_id == (supplier.id if supplier else ""),
                ExceptionCase.exception_type == case.exception_type,
                ExceptionCase.status == ExceptionStatus.RESOLVED,
            ).limit(5)
        ).scalars().all()
        observations.append(
            Observation(
                "precedent_lookup",
                f"{len(history)} comparable exception(s) previously resolved for this supplier."
                if history else "No prior precedent for this supplier and exception type.",
                [{"case_number": h.case_number, "resolution": h.resolution_notes} for h in history],
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        case: ExceptionCase | None = context.get("case")
        if case is None:
            return AgentDecision("Exception not found.", 0.0, escalate=True)

        invoice: Invoice | None = context.get("invoice")
        supplier: Supplier | None = context.get("supplier")
        play = context.get("play", {})
        contested = context.get("contested")
        contract_price = context.get("contract_price")
        age_hours = context.get("age_hours", 0.0)
        confidence = float(play.get("confidence", 0.5))

        evidence = [
            evidence_item("Exception", f"{case.case_number} · {case.exception_type}", "exception_lookup"),
            evidence_item("Financial impact", f"{case.financial_impact_usd:,.2f}", "exception_lookup"),
            evidence_item("Age", f"{age_hours:.1f}h open", "exception_lookup"),
            evidence_item("Playbook recommendation", play.get("recommended", "—"), "exception_resolution"),
        ]
        if contested:
            evidence.append(
                evidence_item(
                    "Contested line",
                    f"line {contested.get('line_number')} · invoiced "
                    f"{contested.get('invoice_unit_price', 0):,.2f} vs PO "
                    f"{contested.get('po_unit_price', 0):,.2f}",
                    "variance_analysis",
                )
            )
        if contract_price is not None:
            evidence.append(evidence_item("Contracted unit price", f"{contract_price:,.2f}", "contract_parsing"))

        rules = [play.get("summary", "")]
        rules.append(f"Confidence {confidence:.0%} against a {self.default_confidence_threshold:.0%} threshold.")

        if confidence < 0.70:
            rules.append("Confidence below 70% → no resolution proposed; assign to a human owner.")
            return AgentDecision(
                conclusion=f"{case.case_number} needs human judgement — the evidence does not support "
                           f"a confident recommendation.",
                confidence=confidence,
                decision_rules=rules,
                evidence=evidence,
                escalate=True,
                escalation_reason="Insufficient evidence for an automated recommendation.",
            )

        proposals: list[ProposedAction] = []
        recommended = play.get("recommended")
        entity_label = case.case_number

        if recommended == "short_pay_to_contract" and contested and contract_price is not None:
            adjusted_total = round(
                float(invoice.total_amount or 0.0)
                - (float(contested.get("invoice_unit_price", 0)) - float(contract_price))
                * float(contested.get("invoice_qty", 0)),
                2,
            ) if invoice else None
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.RESOLVE_EXCEPTION,
                    title="Short-pay to the contracted rate",
                    summary=(
                        f"Pay line {contested.get('line_number')} at the contracted "
                        f"{contract_price:,.2f} rather than the billed "
                        f"{contested.get('invoice_unit_price', 0):,.2f}, reducing the payable by "
                        f"{abs(case.financial_impact_usd):,.2f}."
                    ),
                    payload={
                        "exception_id": case.id,
                        "resolution_notes": f"Short-paid to contracted rate {contract_price:,.2f}; "
                                            f"supplier notified of the adjustment.",
                        "adjust_total": adjusted_total,
                        "match_result": MatchResult.WITHIN_TOLERANCE,
                    },
                    diff_preview=(
                        [{"field": "total_amount", "label": "Invoice total",
                          "before": f"{invoice.total_amount:,.2f}", "after": f"{adjusted_total:,.2f}"}]
                        if invoice and adjusted_total is not None else []
                    ),
                    alternatives=play.get("alternatives", []),
                    confidence=confidence,
                    financial_impact_usd=abs(case.financial_impact_usd),
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                    due_in_hours=6,
                )
            )
        elif recommended == "accept_within_tolerance":
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.RESOLVE_EXCEPTION,
                    title="Accept the variance and clear the exception",
                    summary=play.get("summary", ""),
                    payload={
                        "exception_id": case.id,
                        "resolution_notes": "Variance accepted as immaterial under tolerance policy.",
                        "match_result": MatchResult.WITHIN_TOLERANCE,
                    },
                    alternatives=play.get("alternatives", []),
                    confidence=confidence,
                    financial_impact_usd=abs(case.financial_impact_usd),
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                )
            )
        elif recommended == "chase_receiver":
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.REQUEST_GOODS_RECEIPT,
                    title="Request the goods receipt",
                    summary=play.get("summary", ""),
                    payload={
                        "invoice_id": invoice.id if invoice else None,
                        "requester_id": (context.get("po").requester_id if context.get("po") else None),
                        "message": f"Please confirm receipt for "
                                   f"{invoice.invoice_number if invoice else case.case_number} so the "
                                   f"three-way match can complete.",
                    },
                    alternatives=play.get("alternatives", []),
                    confidence=confidence,
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                    due_in_hours=4,
                )
            )
        elif recommended == "hold_and_confirm":
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.HOLD_INVOICE,
                    title="Hold pending duplicate confirmation",
                    summary=play.get("summary", ""),
                    payload={
                        "invoice_id": invoice.id if invoice else None,
                        "reason": "Held pending confirmation against the suspected original invoice.",
                    },
                    alternatives=play.get("alternatives", []),
                    confidence=confidence,
                    financial_impact_usd=abs(case.financial_impact_usd),
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                    due_in_hours=4,
                )
            )
        elif recommended == "correct_tax":
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.UPDATE_INVOICE_FIELDS,
                    title="Post the corrected tax figure",
                    summary=play.get("summary", ""),
                    payload={
                        "invoice_id": invoice.id if invoice else None,
                        "fields": {},
                    },
                    alternatives=play.get("alternatives", []),
                    confidence=confidence,
                    financial_impact_usd=abs(case.financial_impact_usd),
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                )
            )

        # A supplier-facing draft is a separate, separately-approved action.
        if play.get("draft") and supplier is not None:
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.SEND_SUPPLIER_MESSAGE,
                    title=f"Send drafted message to {supplier.name}",
                    summary="Outbound supplier communication drafted by the agent — review the wording before it sends.",
                    payload={
                        "supplier_id": supplier.id,
                        "invoice_id": invoice.id if invoice else None,
                        "channel": "portal",
                        "intent": str(case.exception_type),
                        "body": play["draft"],
                    },
                    diff_preview=[{"field": "message", "label": "Message body",
                                   "before": "—", "after": play["draft"][:400]}],
                    confidence=confidence,
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.EXCEPTION,
                    entity_type="exception", entity_id=case.id, entity_label=entity_label,
                    due_in_hours=6,
                )
            )

        if not proposals:
            return AgentDecision(
                conclusion=f"{case.case_number} has no automatable path; assigning to AP.",
                confidence=confidence, decision_rules=rules, evidence=evidence,
                escalate=True, escalation_reason="No playbook action applies.",
            )

        return AgentDecision(
            conclusion=f"{case.case_number}: recommend '{recommended}' — "
                       f"{play.get('summary', '')[:160]}",
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=case.financial_impact_usd >= 25_000,
            escalation_reason=f"Financial impact {case.financial_impact_usd:,.2f} exceeds the manager threshold."
            if case.financial_impact_usd >= 25_000 else None,
        )
