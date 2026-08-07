"""Agent 2 — Three-Way Match.

Mission: reconcile Invoice ⇄ PO ⇄ Receipt line by line, and be explicit about
what falls outside tolerance and what it costs.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    AutonomyLevel,
    ExceptionType,
    InvoiceStatus,
    MatchResult,
    RiskLevel,
    Role,
    WorkflowStage,
)
from ..models import Invoice, PurchaseOrder, Receipt
from ..services.policy import PolicyStore
from ..skills import exception_resolution, po_lookup, variance_analysis
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item


class ThreeWayMatchAgent(BaseAgent):
    key = "three_way_match"
    name = "Three-Way Match Agent"
    role = "Reconciles invoice, purchase order and goods receipt within policy tolerance."
    mission = "Match Invoice ⇄ PO ⇄ Receipt and quantify every variance before anything is approved."
    goals = [
        "Clear clean matches quickly so they never age.",
        "Quantify every variance in dollars, not just percentages.",
        "Never absorb a variance outside tolerance without a human decision.",
    ]
    tools = ["ERP purchase orders", "Goods receipts", "Contract rate card", "Tolerance policy"]
    skills = ["po_fetch", "gr_fetch", "variance_analysis", "policy_compliance"]
    default_stage = WorkflowStage.MATCHING
    escalation_role = Role.AP_MANAGER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.93
    allowed_actions = [
        ActionKind.ADVANCE_STAGE,
        ActionKind.CREATE_EXCEPTION,
        ActionKind.REQUEST_GOODS_RECEIPT,
        ActionKind.HOLD_INVOICE,
    ]

    def entity_ref(self, db: Session, context: dict):
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        return ("invoice", invoice.id, invoice.invoice_number) if invoice else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Fetch the purchase order and its lines", "po_fetch",
                     "The PO is the contractual basis for what may be billed."),
            PlanStep(2, "Fetch goods receipts posted against the PO", "gr_fetch",
                     "Receipt confirms the goods or services actually arrived."),
            PlanStep(3, "Run line-level variance analysis", "variance_analysis",
                     "Header totals hide offsetting line errors."),
            PlanStep(4, "Apply tolerance policy", "policy_compliance",
                     "Tolerance is a governance decision, not an agent preference."),
            PlanStep(5, "Propose clearance or an exception", "hitl_checkpoint",
                     "Either outcome is reviewed by AP before it takes effect."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return [Observation("lookup", "Invoice not found.", ok=False)]

        observations: list[Observation] = []
        store = PolicyStore(db)
        context["tolerances"] = {
            "amount_pct": store.number("match.amount_variance_pct", 3.0),
            "quantity_pct": store.number("match.quantity_variance_pct", 2.0),
            "amount_abs": store.number("match.amount_variance_abs", 50.0),
        }

        po = db.get(PurchaseOrder, invoice.po_id) if invoice.po_id else None
        if po is None:
            result = po_lookup.lookup(
                db, po_number=invoice.po_number_raw, supplier_id=invoice.supplier_id,
                invoice_total=invoice.total_amount, erp_system=invoice.erp_system,
            )
            if result["found"]:
                po = db.get(PurchaseOrder, result["po_id"])
            observations.append(
                Observation("po_fetch",
                            f"Recovered PO {result['po_number']}." if result["found"]
                            else "No purchase order on file for this invoice.",
                            result, ok=result["found"])
            )
        else:
            observations.append(
                Observation("po_fetch",
                            f"PO {po.po_number}: ordered {po.total_amount:,.2f}, "
                            f"invoiced to date {po.invoiced_amount:,.2f}.",
                            {"po_number": po.po_number, "total": po.total_amount,
                             "invoiced": po.invoiced_amount, "status": po.status})
            )

        context["po"] = po
        if po is None:
            return observations

        receipts: list[Receipt] = list(po.receipts)
        received_by_line: dict[str, float] = {}
        for receipt in receipts:
            for line in receipt.lines_json or []:
                key = str(line.get("po_line_id"))
                received_by_line[key] = received_by_line.get(key, 0.0) + float(line.get("quantity") or 0.0)
        context["received_by_line"] = received_by_line
        observations.append(
            Observation(
                "gr_fetch",
                f"{len(receipts)} goods receipt(s) totalling {sum(r.total_value or 0 for r in receipts):,.2f} "
                f"across {len(received_by_line)} PO line(s)."
                if receipts else "No goods receipt has been posted against this PO.",
                {
                    "receipts": [
                        {"receipt_number": r.receipt_number,
                         "received_date": r.received_date.isoformat() if r.received_date else None,
                         "total_value": r.total_value, "total_quantity": r.total_quantity}
                        for r in receipts
                    ],
                    "received_by_line": received_by_line,
                },
                ok=bool(receipts),
            )
        )

        analysis = variance_analysis.analyze(
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
            po_lines=[
                {
                    "id": line.id,
                    "line_number": line.line_number,
                    "item_code": line.item_code,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "received_qty": line.received_qty,
                }
                for line in sorted(po.lines, key=lambda l: l.line_number)
            ],
            received_qty_by_line=received_by_line,
            amount_tolerance_pct=context["tolerances"]["amount_pct"],
            quantity_tolerance_pct=context["tolerances"]["quantity_pct"],
            amount_tolerance_abs=context["tolerances"]["amount_abs"],
        )
        context["analysis"] = analysis
        observations.append(
            Observation(
                "variance_analysis",
                f"Match result '{analysis['match_result']}' · total variance "
                f"{analysis['total_variance']:+,.2f} ({analysis['total_variance_pct']:+.2f}%).",
                analysis,
                ok=analysis["clean"],
            )
        )

        observations.append(
            Observation(
                "policy_compliance",
                f"Tolerances applied — amount {context['tolerances']['amount_pct']}% / "
                f"{context['tolerances']['amount_abs']:,.0f} absolute, "
                f"quantity {context['tolerances']['quantity_pct']}%.",
                context["tolerances"],
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        po: PurchaseOrder | None = context.get("po")
        analysis = context.get("analysis")
        tolerances = context.get("tolerances", {})
        amount = float(invoice.total_amount or 0.0) if invoice else 0.0

        if invoice is None:
            return AgentDecision("Invoice not found.", 0.0, escalate=True)

        if po is None:
            return AgentDecision(
                conclusion=f"{invoice.invoice_number} cannot be matched — no purchase order is on file.",
                confidence=0.9,
                decision_rules=["Three-way match requires a PO; none resolved → missing_po exception."],
                evidence=[evidence_item("PO reference", invoice.po_number_raw or "none", "po_fetch")],
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.CREATE_EXCEPTION,
                        title="Cannot match — purchase order missing",
                        summary=f"No PO could be resolved for {invoice.invoice_number} "
                                f"({invoice.currency} {amount:,.2f}).",
                        payload={
                            "invoice_id": invoice.id,
                            "supplier_id": invoice.supplier_id,
                            "exception_type": ExceptionType.MISSING_PO,
                            "severity": RiskLevel.MEDIUM,
                            "title": "Missing purchase order",
                            "description": "Three-way match blocked — no PO on file.",
                            "financial_impact_usd": amount,
                            "match_result": MatchResult.MISSING_PO,
                            "proposed_resolution": "Obtain the PO number, or approve as non-PO spend.",
                        },
                        confidence=0.9,
                        financial_impact_usd=amount,
                        stage=WorkflowStage.MATCHING,
                        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                    )
                ],
                escalate=True,
                escalation_reason="No purchase order available for matching.",
                handoff_to="exception_resolution",
            )

        result = analysis["match_result"]
        variance = analysis["total_variance"]
        failed_lines = [ln for ln in analysis["line_results"] if ln["status"] != "matched"]

        evidence = [
            evidence_item("Purchase order", f"{po.po_number} · ordered {po.total_amount:,.2f}", "po_fetch"),
            evidence_item("Invoice total", f"{invoice.currency} {analysis['total_invoice']:,.2f}",
                          "variance_analysis"),
            evidence_item("PO-priced expectation", f"{analysis['total_expected']:,.2f}", "variance_analysis"),
            evidence_item("Total variance", f"{variance:+,.2f} ({analysis['total_variance_pct']:+.2f}%)",
                          "variance_analysis"),
            evidence_item("Tolerance", f"{tolerances.get('amount_pct')}% amount / "
                                       f"{tolerances.get('quantity_pct')}% quantity", "policy_compliance"),
            evidence_item("Lines outside tolerance", f"{len(failed_lines)} of {len(analysis['line_results'])}",
                          "variance_analysis"),
        ]
        rules = [
            f"Amount variance {analysis['total_variance_pct']:+.2f}% against a "
            f"{tolerances.get('amount_pct')}% tolerance.",
            f"Absolute variance {abs(variance):,.2f} against a {tolerances.get('amount_abs'):,.0f} floor.",
            f"Worst line-level quantity variance {analysis['worst_quantity_variance_pct']:.2f}% "
            f"against {tolerances.get('quantity_pct')}%.",
        ]

        # ---- Clean match -------------------------------------------------
        if analysis["clean"]:
            rules.append("All lines inside tolerance → propose clearance to approval routing.")
            return AgentDecision(
                conclusion=(
                    f"{invoice.invoice_number} matches PO {po.po_number} within tolerance "
                    f"({variance:+,.2f}). Ready for approval routing on AP confirmation."
                ),
                confidence=0.97 if result == MatchResult.MATCHED else 0.94,
                decision_rules=rules,
                evidence=evidence,
                proposals=[
                    ProposedAction(
                        action_kind=ActionKind.ADVANCE_STAGE,
                        title="Clear three-way match and route to approval",
                        summary=(
                            f"Invoice {analysis['total_invoice']:,.2f} vs PO-priced "
                            f"{analysis['total_expected']:,.2f}; variance {variance:+,.2f} "
                            f"({analysis['total_variance_pct']:+.2f}%) is inside the "
                            f"{tolerances.get('amount_pct')}% tolerance across all "
                            f"{len(analysis['line_results'])} line(s)."
                        ),
                        payload={
                            "invoice_id": invoice.id,
                            "stage": WorkflowStage.APPROVAL,
                            "status": InvoiceStatus.MATCHED,
                            "match_result": result,
                            "match_details": analysis,
                        },
                        diff_preview=[
                            {"field": "match_result", "label": "Match result",
                             "before": invoice.match_result, "after": result},
                            {"field": "stage", "label": "Stage", "before": invoice.stage,
                             "after": str(WorkflowStage.APPROVAL)},
                        ],
                        confidence=0.97 if result == MatchResult.MATCHED else 0.94,
                        financial_impact_usd=amount,
                        stage=WorkflowStage.MATCHING,
                        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                        due_in_hours=6,
                    )
                ],
                handoff_to="approval_acceleration",
            )

        # ---- Exception path ---------------------------------------------
        type_map = {
            MatchResult.MISSING_RECEIPT: ExceptionType.MISSING_RECEIPT,
            MatchResult.PRICE_VARIANCE: ExceptionType.PRICE_MISMATCH,
            MatchResult.QUANTITY_VARIANCE: ExceptionType.QUANTITY_MISMATCH,
            MatchResult.NO_MATCH: ExceptionType.PRICE_MISMATCH,
        }
        exception_type = type_map.get(result, ExceptionType.PRICE_MISMATCH)
        worst = max(failed_lines, key=lambda ln: abs(ln.get("variance_amount", 0.0)), default=None)

        play = exception_resolution.playbook(
            exception_type=exception_type,
            context={
                "variance_amount": variance,
                "tolerance_abs": tolerances.get("amount_abs", 50.0),
                "invoice_unit_price": worst.get("invoice_unit_price") if worst else None,
                "contract_unit_price": worst.get("po_unit_price") if worst else None,
                "invoice_number": invoice.invoice_number,
                "amount": amount,
            },
        )
        rules.append(f"Result '{result}' is outside tolerance → open a {exception_type} exception.")

        detail_lines = "; ".join(
            f"line {ln['line_number']} {ln['status']} "
            f"({ln.get('variance_amount', 0):+,.2f})"
            for ln in failed_lines[:5]
        )

        proposals = [
            ProposedAction(
                action_kind=ActionKind.CREATE_EXCEPTION,
                title=f"Three-way match failed · {result.replace('_', ' ')}",
                summary=(
                    f"{len(failed_lines)} line(s) outside tolerance on {invoice.invoice_number}: "
                    f"{detail_lines}. Net variance {variance:+,.2f}. {play['summary']}"
                ),
                payload={
                    "invoice_id": invoice.id,
                    "supplier_id": invoice.supplier_id,
                    "exception_type": exception_type,
                    "severity": exception_resolution.severity_for(exception_type, abs(variance)),
                    "title": f"{result.replace('_', ' ').title()} on {invoice.invoice_number}",
                    "description": f"{detail_lines}. {play['summary']}",
                    "financial_impact_usd": abs(variance),
                    "match_result": result,
                    "match_details": analysis,
                    "proposed_resolution": play["summary"],
                },
                alternatives=play.get("alternatives", []),
                confidence=round(min(0.96, 0.80 + 0.16 * (1 if worst else 0)), 4),
                financial_impact_usd=abs(variance),
                stage=WorkflowStage.MATCHING,
                entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                due_in_hours=4,
                extra_flags=[str(result)],
            )
        ]

        if result == MatchResult.MISSING_RECEIPT:
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.REQUEST_GOODS_RECEIPT,
                    title="Chase the goods receipt",
                    summary=f"Ask {po.requester_id and 'the requester' or 'the receiving team'} to confirm "
                            f"receipt against PO {po.po_number} so matching can complete.",
                    payload={
                        "invoice_id": invoice.id,
                        "requester_id": po.requester_id,
                        "message": f"Invoice {invoice.invoice_number} for PO {po.po_number} is waiting on a "
                                   f"goods receipt. Please confirm the goods or services were received.",
                    },
                    confidence=0.92,
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.MATCHING,
                    entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
                    due_in_hours=4,
                )
            )

        return AgentDecision(
            conclusion=(
                f"{invoice.invoice_number} failed the three-way match ({result}); "
                f"{abs(variance):,.2f} is at stake and AP must decide."
            ),
            confidence=round(min(0.96, 0.80 + 0.16 * (1 if worst else 0)), 4),
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=abs(variance) >= 10_000,
            escalation_reason=f"Variance of {abs(variance):,.2f} exceeds the manager review threshold."
            if abs(variance) >= 10_000 else None,
            handoff_to="exception_resolution",
        )
