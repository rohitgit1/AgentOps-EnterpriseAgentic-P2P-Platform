"""Agent 9 — Contract Intelligence.

Mission: detect expired pricing, unauthorised charges, incorrect rates and
missed discounts by reading the invoice against the contract that governs it.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AutonomyLevel, RiskLevel, Role, WorkflowStage
from ..models import Contract, Invoice, PurchaseOrder, Supplier
from ..skills import contract_parsing
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item


class ContractIntelligenceAgent(BaseAgent):
    key = "contract_intelligence"
    name = "Contract Intelligence Agent"
    role = "Enforces the contract against what is actually billed."
    mission = "Detect expired pricing, unauthorised charges, incorrect rates and missed discounts."
    goals = [
        "Recover every dollar billed above the contracted rate card.",
        "Catch charges that no contract clause permits.",
        "Claim volume discounts the supplier did not apply.",
    ]
    tools = ["Contract repository", "Rate card", "Invoice lines", "PO history"]
    skills = ["contract_parsing", "variance_analysis"]
    default_stage = WorkflowStage.MATCHING
    escalation_role = Role.PROCUREMENT
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.FLAG_CONTRACT_BREACH, ActionKind.CREATE_EXCEPTION,
                       ActionKind.SEND_SUPPLIER_MESSAGE]

    def entity_ref(self, db: Session, context: dict):
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        return ("invoice", invoice.id, invoice.invoice_number) if invoice else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Locate the governing contract", "contract_lookup",
                     "Without a contract there is no rate to enforce."),
            PlanStep(2, "Check term validity against the invoice date", "term_check",
                     "Expired pricing is the most common silent overcharge."),
            PlanStep(3, "Compare each line to the rate card and allowed charges", "contract_parsing",
                     "Line-level comparison catches what header totals hide."),
            PlanStep(4, "Test volume-discount eligibility", "discount_check",
                     "Suppliers rarely apply tier discounts unprompted."),
            PlanStep(5, "Propose recovery actions for approval", "hitl_checkpoint",
                     "Short-paying a supplier is a commercial decision."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return [Observation("contract_lookup", "Invoice not found.", ok=False)]

        po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
        contract_id = invoice.contract_id or (po.contract_id if po else None)
        contract = db.get(Contract, contract_id) if contract_id else None
        if contract is None and invoice.supplier_id:
            contract = db.execute(
                select(Contract).where(
                    Contract.supplier_id == invoice.supplier_id, Contract.status == "active"
                )
            ).scalars().first()
        context["contract"], context["invoice"] = contract, invoice

        observations = [
            Observation(
                "contract_lookup",
                f"Contract {contract.contract_number} governs this spend "
                f"({contract.start_date} → {contract.end_date})."
                if contract else "No contract governs this invoice.",
                {"contract_number": contract.contract_number if contract else None},
                ok=contract is not None,
            )
        ]
        if contract is None:
            return observations

        expired = bool(contract.end_date and invoice.invoice_date and invoice.invoice_date > contract.end_date)
        observations.append(
            Observation(
                "term_check",
                f"Contract expired on {contract.end_date}; the invoice is dated {invoice.invoice_date}."
                if expired else f"Contract is in term on the invoice date ({invoice.invoice_date}).",
                {"expired": expired, "end_date": contract.end_date.isoformat() if contract.end_date else None},
                ok=not expired,
            )
        )

        analysis = contract_parsing.analyze(
            contract={
                "contract_number": contract.contract_number,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "rate_card": contract.rate_card or {},
                "allowed_charges": contract.allowed_charges or [],
                "volume_discounts": contract.volume_discounts or [],
            },
            invoice_lines=[
                {
                    "line_number": line.line_number,
                    "item_code": line.item_code,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                }
                for line in sorted(invoice.lines, key=lambda l: l.line_number)
            ],
            invoice_date=invoice.invoice_date,
            invoice_total=float(invoice.total_amount or 0.0),
        )
        context["analysis"] = analysis

        observations.append(
            Observation(
                "contract_parsing",
                f"{len(analysis['findings'])} finding(s); {analysis['recoverable_amount']:,.2f} recoverable."
                if analysis["findings"] else "All billed lines conform to the contract.",
                analysis,
                ok=not analysis["findings"],
            )
        )
        observations.append(
            Observation(
                "discount_check",
                f"{len(analysis['missed_discounts'])} volume-discount tier(s) reached but not applied."
                if analysis["missed_discounts"] else "No volume-discount tier reached on this invoice.",
                analysis["missed_discounts"],
                ok=not analysis["missed_discounts"],
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        invoice: Invoice | None = context.get("invoice")
        contract: Contract | None = context.get("contract")
        analysis = context.get("analysis")

        if invoice is None:
            return AgentDecision("Invoice not found.", 0.0, escalate=True)
        if contract is None or analysis is None:
            return AgentDecision(
                conclusion=f"No contract governs {invoice.invoice_number}; nothing to enforce.",
                confidence=0.9,
                decision_rules=["Contract enforcement requires an active agreement."],
                evidence=[evidence_item("Contract", "none", "contract_lookup")],
            )

        findings = analysis["findings"]
        recoverable = analysis["recoverable_amount"]
        evidence = [
            evidence_item("Contract", contract.contract_number, "contract_lookup"),
            evidence_item("Invoice total", f"{invoice.currency} {invoice.total_amount:,.2f}", "contract_parsing"),
            evidence_item("Recoverable", f"{recoverable:,.2f}", "contract_parsing"),
            evidence_item("Findings", str(len(findings)), "contract_parsing"),
        ]
        for finding in findings[:4]:
            evidence.append(evidence_item(finding["code"], finding["detail"], "contract_parsing"))

        rules = [
            "Contracted rate governs where a rate-card entry exists.",
            "Charges outside the allowed-charge list are unauthorised until Procurement says otherwise.",
            "Volume discounts reached are claimable whether or not the supplier applied them.",
        ]

        if not findings:
            return AgentDecision(
                conclusion=f"{invoice.invoice_number} conforms to contract {contract.contract_number}.",
                confidence=0.96, decision_rules=rules, evidence=evidence,
            )

        severity = RiskLevel.HIGH if recoverable >= 5_000 else RiskLevel.MEDIUM
        detail = " ".join(f["detail"] for f in findings[:4])
        supplier = db.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None

        proposals = [
            ProposedAction(
                action_kind=ActionKind.FLAG_CONTRACT_BREACH,
                title=f"Contract breach on {invoice.invoice_number} · {recoverable:,.2f} recoverable",
                summary=detail,
                payload={
                    "invoice_id": invoice.id,
                    "supplier_id": invoice.supplier_id,
                    "severity": severity,
                    "title": f"Contract breach vs {contract.contract_number}",
                    "description": detail,
                    "financial_impact_usd": recoverable,
                    "proposed_resolution": f"Short-pay to contracted rates, recovering {recoverable:,.2f}, "
                                           f"and notify the supplier.",
                },
                alternatives=[
                    {"option": "Short-pay to contract", "detail": f"Recover {recoverable:,.2f} now.",
                     "impact_usd": -recoverable},
                    {"option": "Pay in full, pursue credit note",
                     "detail": "Preserves the relationship; recovery becomes a receivable.", "impact_usd": 0.0},
                    {"option": "Accept as a commercial variation",
                     "detail": "Requires the contract owner to document the reason.", "impact_usd": recoverable},
                ],
                confidence=0.93,
                financial_impact_usd=recoverable,
                stage=WorkflowStage.MATCHING,
                entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                due_in_hours=8,
                extra_flags=[f["code"] for f in findings[:3]],
            )
        ]

        if supplier is not None and recoverable > 0:
            body = (
                f"Hello,\n\nWe have reviewed invoice {invoice.invoice_number} against agreement "
                f"{contract.contract_number}. The following items do not align with the agreed terms:\n\n"
                + "\n".join(f"  • {f['detail']}" for f in findings[:5])
                + f"\n\nWe propose an adjustment of {recoverable:,.2f} {invoice.currency}. "
                  f"Please confirm or issue a corrected invoice.\n\nKind regards,\nAccounts Payable"
            )
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.SEND_SUPPLIER_MESSAGE,
                    title=f"Notify {supplier.name} of the contract adjustment",
                    summary="Drafted supplier notification itemising each contract deviation.",
                    payload={
                        "supplier_id": supplier.id,
                        "invoice_id": invoice.id,
                        "channel": "email",
                        "intent": "contract_adjustment",
                        "body": body,
                    },
                    diff_preview=[{"field": "message", "label": "Draft", "before": "—", "after": body[:400]}],
                    confidence=0.91,
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.MATCHING,
                    entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                    due_in_hours=12,
                )
            )

        return AgentDecision(
            conclusion=f"{len(findings)} contract deviation(s) on {invoice.invoice_number}; "
                       f"{recoverable:,.2f} is recoverable subject to Procurement's decision.",
            confidence=0.93,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=recoverable >= 10_000,
            escalation_reason=f"Recoverable value {recoverable:,.2f} warrants contract-owner review."
            if recoverable >= 10_000 else None,
        )
