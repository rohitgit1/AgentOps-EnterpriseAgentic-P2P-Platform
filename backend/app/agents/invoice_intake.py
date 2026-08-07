"""Agent 1 — Invoice Intake.

Mission: convert an incoming document into a validated ERP-ready transaction,
stopping at a human checkpoint whenever the evidence is thin.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    AutonomyLevel,
    ExceptionType,
    InvoiceStatus,
    RiskLevel,
    Role,
    WorkflowStage,
)
from ..models import Invoice, Supplier
from ..services.policy import PolicyStore
from ..skills import duplicate_detection, invoice_extraction, po_lookup, supplier_lookup, tax_validation
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item


class InvoiceIntakeAgent(BaseAgent):
    key = "invoice_intake"
    name = "Invoice Intake Agent"
    role = "Converts incoming invoices into validated, ERP-ready transactions."
    mission = "Convert incoming invoices into validated ERP transactions without letting a bad record through."
    goals = [
        "Reach 80%+ touchless intake without lowering accuracy.",
        "Never let a duplicate or unresolved supplier past validation.",
        "Surface every low-confidence field to a human before it becomes a posting error.",
    ]
    tools = ["Document OCR / EDI parser", "Vendor master", "ERP purchase orders", "Invoice history", "Tax rules"]
    skills = ["invoice_extraction", "supplier_lookup", "po_lookup", "duplicate_detection", "tax_validation"]
    default_stage = WorkflowStage.EXTRACTION_REVIEW
    escalation_role = Role.AP_MANAGER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.95
    allowed_actions = [
        ActionKind.UPDATE_INVOICE_FIELDS,
        ActionKind.ADVANCE_STAGE,
        ActionKind.CREATE_EXCEPTION,
        ActionKind.HOLD_INVOICE,
    ]

    def entity_ref(self, db: Session, context: dict):
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        return ("invoice", invoice.id, invoice.invoice_number) if invoice else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Extract header and line data from the source document",
                     "invoice_extraction", "Structured fields are the basis for every later check."),
            PlanStep(2, "Resolve the supplier against vendor master",
                     "supplier_lookup", "An unresolved supplier cannot be paid or risk-screened."),
            PlanStep(3, "Locate the backing purchase order",
                     "po_lookup", "PO context enables the three-way match downstream."),
            PlanStep(4, "Screen for duplicates across invoice history",
                     "duplicate_detection", "Duplicate payment is the costliest AP failure mode."),
            PlanStep(5, "Validate tax arithmetic and rate band",
                     "tax_validation", "Tax errors block posting and create restatement risk."),
            PlanStep(6, "Propose the next action for human review",
                     "hitl_checkpoint", "The agent proposes; a person decides."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return [Observation("lookup", "Invoice not found.", ok=False)]

        store = PolicyStore(db)
        observations: list[Observation] = []

        extraction = invoice_extraction.extract(
            invoice.document_text or "",
            channel=invoice.source_channel,
            hints={
                "invoice_number": invoice.invoice_number,
                "supplier_name": invoice.supplier_name_raw,
                "po_number": invoice.po_number_raw,
                "total_amount": invoice.total_amount or None,
                "subtotal": invoice.subtotal or None,
                "tax_amount": invoice.tax_amount or None,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "currency": invoice.currency,
            },
        )
        context["extraction"] = extraction
        observations.append(
            Observation(
                "invoice_extraction",
                f"Extracted {len([v for v in extraction['fields'].values() if v not in (None, '')])} fields "
                f"from a {invoice.source_channel} document at {extraction['confidence']:.0%} header confidence.",
                extraction,
                ok=not extraction["requires_human_review"],
            )
        )

        supplier_result = supplier_lookup.lookup(
            db,
            extraction["fields"].get("supplier_name") or invoice.supplier_name_raw or "",
        )
        context["supplier_lookup"] = supplier_result
        resolved = supplier_result.get("resolved")
        observations.append(
            Observation(
                "supplier_lookup",
                f"Resolved to {resolved['name']} ({resolved['code']}) at {resolved['score']:.0%}."
                if resolved
                else f"No confident vendor match; {len(supplier_result['candidates'])} candidate(s) returned.",
                supplier_result,
                ok=resolved is not None,
            )
        )

        supplier_id = resolved["supplier_id"] if resolved else invoice.supplier_id
        po_result = po_lookup.lookup(
            db,
            po_number=extraction["fields"].get("po_number") or invoice.po_number_raw,
            supplier_id=supplier_id,
            invoice_total=extraction["fields"].get("total_amount") or invoice.total_amount,
            erp_system=invoice.erp_system,
        )
        context["po_lookup"] = po_result
        observations.append(
            Observation(
                "po_lookup",
                f"Matched purchase order {po_result['po_number']} "
                f"(open value {po_result.get('open_amount', 0):,.2f})."
                if po_result["found"]
                else "No purchase order could be resolved for this invoice.",
                po_result,
                ok=po_result["found"],
            )
        )

        # Duplicate screening uses the resolved supplier, so apply it in-memory first.
        original_supplier = invoice.supplier_id
        if supplier_id:
            invoice.supplier_id = supplier_id
        dup = duplicate_detection.detect(
            db, invoice, threshold=store.number("intake.duplicate_similarity", 0.92)
        )
        invoice.supplier_id = original_supplier
        context["duplicate"] = dup
        observations.append(
            Observation(
                "duplicate_detection",
                f"Duplicate risk {dup['score']:.0%}"
                + (f" against {dup['matched_invoice']['invoice_number']}." if dup.get("matched_invoice") else " — no close match."),
                dup,
                ok=not dup["is_duplicate"],
            )
        )

        supplier = db.get(Supplier, supplier_id) if supplier_id else None
        tax = tax_validation.validate(
            subtotal=extraction["fields"].get("subtotal") or invoice.subtotal,
            tax_amount=extraction["fields"].get("tax_amount") or invoice.tax_amount,
            total_amount=extraction["fields"].get("total_amount") or invoice.total_amount,
            freight_amount=extraction["fields"].get("freight_amount") or invoice.freight_amount or 0.0,
            supplier_country=supplier.country if supplier else "United States",
            tax_id=supplier.tax_id if supplier else None,
        )
        context["tax"] = tax
        observations.append(
            Observation(
                "tax_validation",
                "Tax reconciles."
                if tax["valid"]
                else f"Tax check failed: {tax['findings'][0] if tax['findings'] else 'unknown'}",
                tax,
                ok=tax["valid"],
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        invoice = db.get(Invoice, context.get("invoice_id", ""))
        if invoice is None:
            return AgentDecision("Invoice not found.", 0.0, escalate=True,
                                 escalation_reason="Missing invoice record.")

        extraction = context.get("extraction", {})
        supplier_result = context.get("supplier_lookup", {})
        po_result = context.get("po_lookup", {})
        dup = context.get("duplicate", {})
        tax = context.get("tax", {})
        fields = extraction.get("fields", {})
        resolved = supplier_result.get("resolved")

        evidence = [
            evidence_item("Source channel", f"{invoice.source_channel} · {invoice.source_filename or 'inline'}",
                          "intake"),
            evidence_item("Header confidence", f"{extraction.get('confidence', 0):.0%}", "invoice_extraction"),
            evidence_item("Supplier match",
                          f"{resolved['name']} @ {resolved['score']:.0%}" if resolved else "unresolved",
                          "supplier_lookup"),
            evidence_item("Purchase order",
                          po_result.get("po_number") or "not found", "po_lookup"),
            evidence_item("Duplicate score", f"{dup.get('score', 0):.0%}", "duplicate_detection"),
            evidence_item("Tax check", "pass" if tax.get("valid") else "; ".join(tax.get("findings", [])),
                          "tax_validation"),
        ]
        rules: list[str] = []
        proposals: list[ProposedAction] = []
        amount = float(fields.get("total_amount") or invoice.total_amount or 0.0)

        # ---- Blocking condition: duplicate ------------------------------
        if dup.get("is_duplicate"):
            matched = dup.get("matched_invoice") or {}
            rules.append(
                f"Duplicate score {dup['score']:.0%} met or exceeded the "
                f"{dup['threshold']:.0%} policy threshold → block before payment."
            )
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.CREATE_EXCEPTION,
                    title=f"Suspected duplicate of {matched.get('invoice_number', 'a prior invoice')}",
                    summary=(
                        f"{invoice.invoice_number} scores {dup['score']:.0%} against "
                        f"{matched.get('invoice_number')} ({', '.join(dup.get('signals', []))}). "
                        f"Paying both would double-pay {amount:,.2f} {invoice.currency}."
                    ),
                    payload={
                        "invoice_id": invoice.id,
                        "supplier_id": resolved["supplier_id"] if resolved else invoice.supplier_id,
                        "exception_type": ExceptionType.DUPLICATE_INVOICE,
                        "severity": RiskLevel.CRITICAL,
                        "title": "Suspected duplicate invoice",
                        "description": f"Signals: {', '.join(dup.get('signals', []))}.",
                        "financial_impact_usd": amount,
                        "proposed_resolution": "Confirm against the original; reject if confirmed duplicate.",
                        "sla_hours": 8,
                    },
                    confidence=min(0.98, 0.55 + dup["score"] * 0.45),
                    financial_impact_usd=amount,
                    stage=WorkflowStage.VALIDATION,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    due_in_hours=4,
                    alternatives=[
                        {"option": "Confirm duplicate and reject", "detail": "Notify the supplier of the rejection."},
                        {"option": "Not a duplicate", "detail": "Recurring charge — clear and continue intake."},
                    ],
                    extra_flags=["duplicate_suspected"],
                )
            )
            return AgentDecision(
                conclusion=f"Held {invoice.invoice_number}: duplicate risk {dup['score']:.0%}. "
                           f"AP must confirm before this can proceed.",
                confidence=min(0.98, 0.55 + dup["score"] * 0.45),
                decision_rules=rules,
                evidence=evidence,
                proposals=proposals,
                escalate=True,
                escalation_reason="Potential duplicate payment.",
            )

        # ---- Blocking condition: unresolved supplier --------------------
        if resolved is None:
            rules.append("Supplier could not be resolved above the 0.85 auto-resolve threshold → human selection.")
            candidates = supplier_result.get("candidates", [])
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.UPDATE_INVOICE_FIELDS,
                    title="Select the correct supplier",
                    summary=(
                        f"'{fields.get('supplier_name') or invoice.supplier_name_raw}' did not resolve "
                        f"confidently. Best candidate: "
                        + (f"{candidates[0]['name']} at {candidates[0]['score']:.0%}." if candidates
                           else "none above threshold.")
                    ),
                    payload={
                        "invoice_id": invoice.id,
                        "fields": {"supplier_id": candidates[0]["supplier_id"]} if candidates else {},
                        "advance_to": WorkflowStage.VALIDATION,
                        "status": InvoiceStatus.VALIDATED,
                    },
                    diff_preview=[{
                        "field": "supplier_id",
                        "before": invoice.supplier_id,
                        "after": candidates[0]["supplier_id"] if candidates else None,
                        "label": "Supplier",
                        "before_label": invoice.supplier_name_raw,
                        "after_label": candidates[0]["name"] if candidates else "— select —",
                    }],
                    alternatives=[
                        {"option": c["name"], "detail": f"match {c['score']:.0%} · {c['code']}",
                         "payload": {"fields": {"supplier_id": c["supplier_id"]}}}
                        for c in candidates
                    ],
                    confidence=max(0.35, supplier_result.get("match_score", 0.0)),
                    financial_impact_usd=amount,
                    stage=WorkflowStage.EXTRACTION_REVIEW,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    due_in_hours=6,
                    extra_flags=["supplier_unresolved"],
                )
            )
            return AgentDecision(
                conclusion=f"Cannot resolve the supplier for {invoice.invoice_number}. "
                           f"AP must confirm the vendor before validation continues.",
                confidence=max(0.35, supplier_result.get("match_score", 0.0)),
                decision_rules=rules,
                evidence=evidence,
                proposals=proposals,
                escalate=True,
                escalation_reason="Supplier could not be resolved automatically.",
            )

        # ---- Field corrections + advance --------------------------------
        diff: list[dict] = []
        proposed_fields: dict = {}

        def stage_field(name: str, new_value, label: str):
            current = getattr(invoice, name, None)
            if new_value in (None, "", 0) or new_value == current:
                return
            proposed_fields[name] = new_value.isoformat() if hasattr(new_value, "isoformat") else new_value
            diff.append({"field": name, "label": label, "before": _fmt(current), "after": _fmt(new_value)})

        if resolved["supplier_id"] != invoice.supplier_id:
            proposed_fields["supplier_id"] = resolved["supplier_id"]
            diff.append({"field": "supplier_id", "label": "Supplier",
                         "before": invoice.supplier_name_raw or "—", "after": resolved["name"]})
        if po_result.get("found") and po_result["po_id"] != invoice.po_id:
            proposed_fields["po_id"] = po_result["po_id"]
            diff.append({"field": "po_id", "label": "Purchase order",
                         "before": invoice.po_number_raw or "—", "after": po_result["po_number"]})
        if po_result.get("contract_id"):
            proposed_fields["contract_id"] = po_result["contract_id"]

        stage_field("invoice_number", fields.get("invoice_number"), "Invoice number")
        stage_field("total_amount", fields.get("total_amount"), "Total amount")
        stage_field("subtotal", fields.get("subtotal"), "Subtotal")
        stage_field("tax_amount", fields.get("tax_amount"), "Tax")
        stage_field("invoice_date", fields.get("invoice_date"), "Invoice date")
        stage_field("due_date", fields.get("due_date"), "Due date")

        confidence = float(extraction.get("confidence", 0.0))
        rules.append(f"Header confidence {confidence:.0%} vs {self.default_confidence_threshold:.0%} agent threshold.")
        rules.append(f"Supplier resolved at {resolved['score']:.0%} (auto-resolve floor 85%).")

        # Tax problem → exception rather than a silent advance.
        if not tax.get("valid", True):
            rules.append("Tax validation failed → open a tax exception instead of advancing.")
            impact = abs(float(tax.get("arithmetic_delta") or 0.0))
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.CREATE_EXCEPTION,
                    title="Tax does not reconcile",
                    summary=" ".join(tax.get("findings", [])) or "Tax validation failed.",
                    payload={
                        "invoice_id": invoice.id,
                        "supplier_id": resolved["supplier_id"],
                        "exception_type": ExceptionType.TAX_ERROR,
                        "severity": RiskLevel.MEDIUM,
                        "title": "Tax validation failure",
                        "description": " ".join(tax.get("findings", [])),
                        "financial_impact_usd": impact,
                        "proposed_resolution": (
                            f"Recalculated tax: {tax['suggested_tax_amount']:,.2f}."
                            if tax.get("suggested_tax_amount") else
                            "Request a corrected invoice from the supplier."
                        ),
                    },
                    confidence=0.9,
                    financial_impact_usd=impact,
                    stage=WorkflowStage.VALIDATION,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    extra_flags=["tax_error"],
                )
            )

        if not po_result.get("found"):
            rules.append("No PO resolved → open a missing_po exception; a non-PO path needs human election.")
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.CREATE_EXCEPTION,
                    title="No purchase order reference",
                    summary=f"{invoice.invoice_number} arrived without a resolvable PO. "
                            f"Either the supplier omitted it or this is a non-PO spend.",
                    payload={
                        "invoice_id": invoice.id,
                        "supplier_id": resolved["supplier_id"],
                        "exception_type": ExceptionType.MISSING_PO,
                        "severity": RiskLevel.MEDIUM,
                        "title": "Missing purchase order",
                        "description": f"Raw PO reference on the document: "
                                       f"'{invoice.po_number_raw or fields.get('po_number') or 'none'}'.",
                        "financial_impact_usd": amount,
                        "proposed_resolution": "Request the PO number from the supplier, or route as non-PO spend.",
                    },
                    confidence=0.86,
                    financial_impact_usd=amount,
                    stage=WorkflowStage.VALIDATION,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    extra_flags=["missing_po"],
                )
            )

        if not proposals:
            action_title = (
                "Confirm extracted data and release to matching"
                if diff
                else "Release to three-way matching"
            )
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.UPDATE_INVOICE_FIELDS if diff else ActionKind.ADVANCE_STAGE,
                    title=action_title,
                    summary=(
                        f"All intake checks passed for {invoice.invoice_number} "
                        f"({invoice.currency} {amount:,.2f}, supplier {resolved['name']}, "
                        f"PO {po_result.get('po_number')}). "
                        + (f"{len(diff)} field(s) would be corrected on approval." if diff else
                           "No corrections needed.")
                    ),
                    payload=(
                        {
                            "invoice_id": invoice.id,
                            "fields": proposed_fields,
                            "advance_to": WorkflowStage.MATCHING,
                            "status": InvoiceStatus.VALIDATED,
                        }
                        if diff
                        else {
                            "invoice_id": invoice.id,
                            "stage": WorkflowStage.MATCHING,
                            "status": InvoiceStatus.VALIDATED,
                        }
                    ),
                    diff_preview=diff,
                    confidence=confidence,
                    financial_impact_usd=amount,
                    stage=WorkflowStage.EXTRACTION_REVIEW,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    due_in_hours=6,
                )
            )

        low_confidence = confidence < self.default_confidence_threshold
        if low_confidence:
            rules.append("Confidence below agent threshold → flagged for closer human inspection.")

        return AgentDecision(
            conclusion=(
                f"{invoice.invoice_number} passed intake checks at {confidence:.0%} confidence; "
                f"{len(proposals)} proposal(s) queued for AP review."
                if not any(p.action_kind == ActionKind.CREATE_EXCEPTION for p in proposals)
                else f"{invoice.invoice_number} raised {len(proposals)} intake issue(s) needing AP judgement."
            ),
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=low_confidence,
            escalation_reason="Extraction confidence below threshold." if low_confidence else None,
            handoff_to="three_way_match" if not any(
                p.action_kind == ActionKind.CREATE_EXCEPTION for p in proposals
            ) else "exception_resolution",
        )


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
