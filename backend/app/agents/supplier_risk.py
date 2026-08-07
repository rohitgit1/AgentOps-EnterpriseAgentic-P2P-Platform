"""Agent 7 — Supplier Risk.

Mission: monitor sanctions, insurance, tax forms and vendor-master changes,
and propose the block *before* the payment leaves.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AutonomyLevel, ExceptionType, RiskLevel, Role, WorkflowStage
from ..models import Invoice, Supplier
from ..services.policy import PolicyStore
from ..skills import vendor_risk
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec


class SupplierRiskAgent(BaseAgent):
    key = "supplier_risk"
    name = "Supplier Risk Agent"
    role = "Continuously screens the vendor master for compliance and fraud exposure."
    mission = "Detect supplier compliance and fraud risk before money moves."
    goals = [
        "Zero payments to sanctioned or unverified parties.",
        "Catch every bank-detail change inside the verification freeze window.",
        "Keep tax and insurance documentation current across the vendor base.",
    ]
    tools = ["Sanctions screening", "Vendor master change log", "Insurance registry", "Tax form registry"]
    skills = ["vendor_risk", "sanction_screening", "document_expiry_monitoring"]
    default_stage = WorkflowStage.VALIDATION
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.92
    allowed_actions = [
        ActionKind.BLOCK_SUPPLIER,
        ActionKind.HOLD_INVOICE,
        ActionKind.CREATE_EXCEPTION,
        ActionKind.SEND_SUPPLIER_MESSAGE,
    ]

    inputs = [
        IOSpec("supplier_id", "Screen one supplier. Omit to sweep the vendor master.",
               kind="data", required=False),
        IOSpec("vendor master & registries", "Sanctions, insurance, tax forms and bank-change log.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Screening findings", "Per-supplier findings with severity and the action each implies.",
               kind="record"),
        IOSpec("Payment-blocking verdict", "Whether the supplier may be paid right now.",
               kind="record"),
        IOSpec("Checkpoint", "Block supplier / freeze invoice / request documentation.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        if context.get("supplier_id"):
            supplier = db.get(Supplier, context["supplier_id"])
            if supplier:
                return ("supplier", supplier.id, supplier.name)
        return ("supplier", None, "Vendor master sweep")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Select suppliers in scope", "vendor_scan",
                     "Either one supplier or a full vendor-master sweep."),
            PlanStep(2, "Run restricted-party screening", "sanction_screening",
                     "A sanctions hit is an absolute payment bar."),
            PlanStep(3, "Check document expiry and bank-change recency", "document_expiry_monitoring",
                     "Fresh bank details are the strongest fraud signal in AP."),
            PlanStep(4, "Score aggregate supplier risk", "vendor_risk",
                     "One number that Procurement and Treasury can act on."),
            PlanStep(5, "Propose blocks and holds for approval", "hitl_checkpoint",
                     "Blocking a supplier stops their revenue — a person owns that call."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        store = PolicyStore(db)
        freeze_days = int(store.number("risk.bank_change_freeze_days", 10))

        if context.get("supplier_id"):
            suppliers = [db.get(Supplier, context["supplier_id"])]
            suppliers = [s for s in suppliers if s is not None]
        else:
            suppliers = db.execute(select(Supplier)).scalars().all()

        assessments = [vendor_risk.assess(s, bank_freeze_days=freeze_days) for s in suppliers]
        context["assessments"] = assessments
        context["suppliers"] = {s.id: s for s in suppliers}

        flagged = [a for a in assessments if a["findings"]]
        blocking = [a for a in assessments if a["payment_blocking"]]
        context["flagged"], context["blocking"] = flagged, blocking

        observations = [
            Observation("vendor_scan", f"Screened {len(suppliers)} supplier(s).", {"count": len(suppliers)}),
            Observation(
                "sanction_screening",
                f"{len([a for a in assessments if any(f['code'].startswith('sanctions') for f in a['findings'])])} "
                f"supplier(s) returned a restricted-party signal.",
                [
                    {"supplier": a["supplier_name"], "findings":
                        [f for f in a["findings"] if f["code"].startswith("sanctions")]}
                    for a in assessments
                    if any(f["code"].startswith("sanctions") for f in a["findings"])
                ],
                ok=not any(f["code"] == "sanctions_hit" for a in assessments for f in a["findings"]),
            ),
            Observation(
                "document_expiry_monitoring",
                f"{len([a for a in flagged if any(f['code'].startswith(('tax_', 'insurance_')) for f in a['findings'])])} "
                f"supplier(s) have expiring or missing documentation.",
                [
                    {"supplier": a["supplier_name"],
                     "findings": [f for f in a["findings"] if f["code"].startswith(("tax_", "insurance_"))]}
                    for a in flagged
                ],
            ),
            Observation(
                "vendor_risk",
                f"{len(blocking)} supplier(s) carry payment-blocking risk; "
                f"{len(flagged)} carry at least one finding.",
                [{"supplier": a["supplier_name"], "score": a["risk_score"], "level": a["risk_level"]}
                 for a in sorted(assessments, key=lambda a: a["risk_score"], reverse=True)[:10]],
                ok=not blocking,
            ),
        ]
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        assessments = context.get("assessments", [])
        blocking = context.get("blocking", [])
        flagged = context.get("flagged", [])
        suppliers: dict[str, Supplier] = context.get("suppliers", {})

        evidence = [
            evidence_item("Suppliers screened", str(len(assessments)), "vendor_scan"),
            evidence_item("Payment-blocking findings", str(len(blocking)), "vendor_risk"),
            evidence_item("Total findings", str(sum(len(a["findings"]) for a in assessments)), "vendor_risk"),
        ]
        rules = [
            "A sanctions hit is an absolute bar — block, do not down-rank.",
            "A bank change inside the freeze window requires out-of-band verification before payment.",
            "Document lapses are chased, not blocked, unless insurance has expired.",
        ]
        proposals: list[ProposedAction] = []

        for assessment in blocking:
            supplier = suppliers.get(assessment["supplier_id"])
            if supplier is None:
                continue
            critical = [f for f in assessment["findings"]
                        if f["severity"] in {RiskLevel.CRITICAL, RiskLevel.HIGH}]
            headline = critical[0] if critical else assessment["findings"][0]
            unpaid = db.execute(
                select(Invoice).where(Invoice.supplier_id == supplier.id, Invoice.paid_at.is_(None))
            ).scalars().all()
            exposure = round(sum(float(i.total_amount or 0.0) for i in unpaid), 2)
            evidence.append(
                evidence_item(f"{supplier.name} finding", headline["detail"], "vendor_risk")
            )

            if headline["code"] == "sanctions_hit":
                proposals.append(
                    ProposedAction(
                        action_kind=ActionKind.BLOCK_SUPPLIER,
                        title=f"Block {supplier.name} — restricted-party match",
                        summary=f"{headline['detail']} Unpaid exposure is {exposure:,.2f}. "
                                f"{headline['action']}",
                        payload={"supplier_id": supplier.id,
                                 "reason": f"Restricted-party screening hit. {headline['detail']}"},
                        diff_preview=[{"field": "on_hold", "label": "Supplier status",
                                       "before": "active", "after": "blocked"}],
                        confidence=0.97,
                        financial_impact_usd=exposure,
                        stage=WorkflowStage.VALIDATION,
                        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
                        due_in_hours=2,
                        extra_flags=["sanctions"],
                    )
                )
            else:
                for invoice in unpaid[:5]:
                    proposals.append(
                        ProposedAction(
                            action_kind=ActionKind.CREATE_EXCEPTION,
                            title=f"Freeze {invoice.invoice_number} — {headline['code'].replace('_', ' ')}",
                            summary=f"{headline['detail']} {headline['action']}",
                            payload={
                                "invoice_id": invoice.id,
                                "supplier_id": supplier.id,
                                "exception_type": (
                                    ExceptionType.BANKING_CHANGE
                                    if headline["code"] == "bank_change_recent"
                                    else ExceptionType.SANCTIONS_HIT
                                ),
                                "severity": headline["severity"],
                                "title": f"Payment freeze · {supplier.name}",
                                "description": headline["detail"],
                                "financial_impact_usd": float(invoice.total_amount or 0.0),
                                "proposed_resolution": headline["action"],
                                "sla_hours": 8,
                            },
                            confidence=0.95,
                            financial_impact_usd=float(invoice.total_amount or 0.0),
                            stage=WorkflowStage.PAYMENT,
                            entity_type="invoice", entity_id=invoice.id,
                            entity_label=invoice.invoice_number,
                            due_in_hours=4,
                            extra_flags=[headline["code"]],
                        )
                    )

        # Documentation chases — low risk, still human-released.
        doc_chases = [
            (a, f)
            for a in flagged
            for f in a["findings"]
            if f["code"] in {"tax_form_missing", "tax_form_expiring", "tax_form_expired", "insurance_expiring"}
        ][:4]
        for assessment, finding in doc_chases:
            supplier = suppliers.get(assessment["supplier_id"])
            if supplier is None:
                continue
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.SEND_SUPPLIER_MESSAGE,
                    title=f"Request documentation from {supplier.name}",
                    summary=f"{finding['detail']} {finding['action']}",
                    payload={
                        "supplier_id": supplier.id,
                        "channel": "email",
                        "intent": finding["code"],
                        "body": (
                            f"Hello,\n\n{finding['detail']} To avoid any interruption to payment, "
                            f"please upload the current document to the supplier portal at your earliest "
                            f"convenience.\n\nKind regards,\nSupplier Maintenance"
                        ),
                    },
                    confidence=0.93,
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.VALIDATION,
                    entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
                    due_in_hours=24,
                )
            )

        if not proposals:
            return AgentDecision(
                conclusion=f"Screened {len(assessments)} supplier(s); no risk requires intervention.",
                confidence=0.96, decision_rules=rules, evidence=evidence,
            )

        return AgentDecision(
            conclusion=(
                f"{len(blocking)} supplier(s) carry payment-blocking risk; "
                f"{len(proposals)} protective action(s) proposed for approval."
            ),
            confidence=0.95,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=bool(blocking),
            escalation_reason="Payment-blocking supplier risk detected." if blocking else None,
        )
