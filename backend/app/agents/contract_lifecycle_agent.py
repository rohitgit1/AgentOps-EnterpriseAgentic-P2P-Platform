"""Procurement Agent 4 — Contract Lifecycle.

Authors drafts from the standard clause library, and reviews an uploaded
third-party paper for missing clauses, risky language and obligations. Issuing
for signature is irreversible and needs Controller authority.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, EventType, Role, WorkflowStage
from ..models import Contract, ContractDraft, Supplier
from ..services import artifacts as artifact_service
from ..skills import contract_lifecycle as clm
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)


class ContractLifecycleAgent(BaseAgent):
    key = "contract_lifecycle"
    name = "Contract Lifecycle Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Authors, reviews and tracks contracts across their whole lifecycle."
    mission = "Get defensible paper in place quickly, and never miss a renewal or a risky clause."
    goals = [
        "Every draft carries the full mandatory clause set.",
        "No auto-renewal passes its notice window unflagged.",
        "Surface vendor-favouring language before signature, not at dispute.",
    ]
    tools = ["Clause library", "Contract register", "Supplier master", "Renewal calendar"]
    skills = ["contract_authoring", "clause_analysis", "obligation_tracking"]
    default_stage = WorkflowStage.APPROVAL
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.DRAFT_CONTRACT, ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE]

    inputs = [
        IOSpec("contract_document",
               "A third-party or existing contract to review for missing and risky clauses.",
               kind="attachment", formats=["md", "txt", "pdf"], required=False,
               example="acme-msa-redline.md"),
        IOSpec("contract_request",
               "Parameters for a new draft: supplier, type, value, term, category.",
               kind="data", required=False,
               example='{"supplier_id": "...", "contract_type": "MSA", "value_usd": 480000, "term_months": 24}'),
        IOSpec("draft_id", "Existing draft to progress toward signature.", kind="data", required=False),
    ]
    outputs = [
        IOSpec("Contract draft", "Full document generated from the standard clause library.",
               kind="artifact", formats=["md"], example="MSA-CDR-6001.md"),
        IOSpec("Clause review", "Missing clauses, risky language with excerpts, legal risk score.",
               kind="artifact", formats=["md"], example="clause-review-CDR-6001.md"),
        IOSpec("Obligation register", "Deliverables, SLAs, rebates, renewal and notice dates.",
               kind="artifact", formats=["csv"], example="obligations-CDR-6001.csv"),
        IOSpec("Checkpoints", "Accept draft / issue for signature — the latter needs Controller.",
               kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        draft = db.get(ContractDraft, context.get("draft_id", "")) if context.get("draft_id") else None
        return ("contract_draft", draft.id, draft.reference) if draft else \
               ("contract_draft", None, "Contract lifecycle")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Determine the mode: author or review", "triage",
                     "An attached document is reviewed; parameters produce a draft."),
            PlanStep(2, "Generate or read the contract body", "contract_authoring",
                     "The clause library is the standard the paper is measured against."),
            PlanStep(3, "Analyse clauses", "clause_analysis",
                     "Missing mandatory clauses and vendor-favouring language both carry weight."),
            PlanStep(4, "Extract obligations and the renewal clock", "obligation_tracking",
                     "An auto-renewal inside its notice window is the expensive failure."),
            PlanStep(5, "Submit for approval", "hitl_checkpoint",
                     "Issuing for signature commits the company — Controller authority."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []
        draft = db.get(ContractDraft, context.get("draft_id", "")) if context.get("draft_id") else None

        uploaded = None
        for attachment in context.get("attachments", []):
            if attachment["format"] in {"text", "pdf_text"} or \
               attachment["filename"].lower().endswith((".md", ".txt", ".pdf")):
                uploaded = attachment
                break

        mode = "review" if uploaded else ("progress" if draft else "author")
        context["mode"] = mode
        observations.append(
            Observation("triage",
                        {"review": f"Reviewing uploaded paper: {uploaded['filename']}."
                                   if uploaded else "",
                         "progress": f"Progressing existing draft {draft.reference}."
                                     if draft else "",
                         "author": "No document supplied — authoring a new draft from the "
                                   "standard clause library."}[mode],
                        {"mode": mode})
        )

        supplier = None
        if context.get("supplier_id"):
            supplier = db.get(Supplier, context["supplier_id"])
        elif draft and draft.supplier_id:
            supplier = db.get(Supplier, draft.supplier_id)
        elif uploaded:
            # Best effort: match a supplier named in the document.
            body = (uploaded["text"] or "").lower()
            supplier = next(
                (s for s in db.execute(select(Supplier)).scalars().all()
                 if s.name.split()[0].lower() in body), None,
            )
        context["supplier"] = supplier

        # ---- Body -----------------------------------------------------------
        if uploaded:
            body = uploaded["text"]
            context["source_artifact_id"] = uploaded["id"]
        elif draft:
            body = draft.body
        else:
            contract_type = context.get("contract_type", "MSA")
            value = float(context.get("value_usd") or 0.0)
            term = int(context.get("term_months") or 12)
            active = db.execute(
                select(Contract).where(Contract.supplier_id == supplier.id)
            ).scalars().first() if supplier else None
            body = clm.author(
                contract_type=contract_type,
                supplier_name=supplier.name if supplier else context.get("supplier_name", "Supplier"),
                title=context.get("title") or f"{contract_type} — "
                                              f"{supplier.name if supplier else 'Supplier'}",
                value_usd=value, term_months=term,
                category=supplier.category if supplier else context.get("category", ""),
                rate_card=(active.rate_card if active else None),
            )
        context["body"] = body
        observations.append(
            Observation("contract_authoring",
                        f"Working document is {len(body.split()):,} words "
                        f"({'uploaded' if uploaded else 'generated from the clause library'}).",
                        {"words": len(body.split()), "generated": uploaded is None},
                        ok=bool(body.strip()))
        )

        analysis = clm.analyze_clauses(body)
        context["analysis"] = analysis
        observations.append(
            Observation("clause_analysis",
                        f"{len(analysis['present_clauses'])}/{len(clm.MANDATORY_CLAUSES)} mandatory "
                        f"clauses present, {len(analysis['missing_clauses'])} missing, "
                        f"{len(analysis['risky_clauses'])} risky. Legal risk "
                        f"{analysis['legal_risk_score']:.0f} ({analysis['risk_band']}).",
                        analysis, ok=analysis["legal_risk_score"] < 35)
        )

        obligations = clm.extract_obligations(
            body, term_months=int(context.get("term_months") or (draft.term_months if draft else 12)))
        context["obligations"] = obligations
        observations.append(
            Observation("obligation_tracking",
                        f"{obligations['obligation_count']} obligation(s) extracted. Renewal "
                        f"{obligations['renewal_date']}, notice deadline "
                        f"{obligations['notice_deadline']} "
                        f"({obligations['days_to_notice']} days away)"
                        + (" — AUTO-RENEWS." if obligations["auto_renew"] else "."),
                        obligations,
                        ok=not (obligations["auto_renew"] and obligations["days_to_notice"] < 60))
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        analysis = context.get("analysis", {})
        obligations = context.get("obligations", {})
        supplier = context.get("supplier")
        body = context.get("body", "")
        mode = context.get("mode")
        execution_id = context.get("_execution_id")

        if not body.strip():
            return AgentDecision("No contract body to work with.", 0.3,
                                 decision_rules=["Nothing to author or review."],
                                 evidence=[], escalate=True,
                                 escalation_reason="Empty contract document.")

        draft = db.get(ContractDraft, context.get("draft_id", "")) if context.get("draft_id") else None
        if draft is None:
            count = db.execute(select(func.count(ContractDraft.id))).scalar_one() or 0
            draft = ContractDraft(
                reference=f"CDR-{count + 6001}",
                title=context.get("title") or f"{context.get('contract_type', 'MSA')} — "
                                              f"{supplier.name if supplier else 'Supplier'}",
                contract_type=context.get("contract_type", "MSA"),
                supplier_id=supplier.id if supplier else None,
                supplier_name=supplier.name if supplier else context.get("supplier_name", "Supplier"),
                value_usd=float(context.get("value_usd") or 0.0),
                term_months=int(context.get("term_months") or 12),
                body=body,
                source_artifact_id=context.get("source_artifact_id"),
            )
            db.add(draft)
            db.flush()
        draft.clause_findings = analysis.get("risky_clauses", [])
        draft.missing_clauses = analysis.get("missing_clauses", [])
        draft.legal_risk_score = analysis.get("legal_risk_score", 0.0)
        draft.obligations = obligations.get("obligations", [])
        try:
            draft.renewal_date = date.fromisoformat(obligations["renewal_date"])
        except (KeyError, ValueError):
            pass
        db.flush()

        evidence = [
            evidence_item("Mode", mode, "triage"),
            evidence_item("Supplier", supplier.name if supplier else draft.supplier_name, "triage"),
            evidence_item("Legal risk score",
                          f"{analysis['legal_risk_score']:.0f} ({analysis['risk_band']})",
                          "clause_analysis"),
            evidence_item("Missing mandatory clauses", str(len(analysis["missing_clauses"])),
                          "clause_analysis"),
            evidence_item("Risky clauses", str(len(analysis["risky_clauses"])), "clause_analysis"),
            evidence_item("Renewal / notice",
                          f"{obligations.get('renewal_date')} / "
                          f"{obligations.get('notice_deadline')}", "obligation_tracking"),
        ]
        for risky in analysis["risky_clauses"][:3]:
            evidence.append(evidence_item(risky["label"], risky["excerpt"][:160], "clause_analysis"))

        rules = [
            f"Mandatory clause set is {len(clm.MANDATORY_CLAUSES)} clauses; each omission adds 6 "
            f"points of legal risk.",
            "Vendor-favouring language is weighted by how much risk it transfers.",
            "Issuing for signature is irreversible and requires Controller authority.",
        ]
        if obligations.get("auto_renew"):
            rules.append(f"Document auto-renews with a {obligations['notice_days']}-day notice "
                         f"window — {obligations['days_to_notice']} days remain.")

        # ---- Deliverables ---------------------------------------------------
        artifacts = []
        if mode == "author":
            artifacts.append(artifact_service.produce_output(
                db, agent_key=self.key, execution_id=execution_id,
                title=f"{draft.contract_type} draft · {draft.reference}",
                filename=f"{draft.contract_type}-{draft.reference}.md",
                content=body, kind="contract_draft",
                summary=f"{draft.contract_type} for {draft.supplier_name}, "
                        f"{draft.value_usd:,.0f} USD over {draft.term_months} months.",
                entity_type="contract_draft", entity_id=draft.id,
            ))

        missing_md = "\n".join(f"- **{m['label']}** — {m['impact']}"
                               for m in analysis["missing_clauses"]) or "- None. Full set present."
        risky_md = "\n".join(
            f"- **{r['label']}** (+{r['weight']} risk)\n  > {r['excerpt']}"
            for r in analysis["risky_clauses"]) or "- None detected."
        redlines = "\n".join(f"{i}. {n}" for i, n in enumerate(analysis["redline_notes"], 1)) \
            or "_No redlines required._"

        review = f"""# Clause review — {draft.reference}

**Document:** {draft.title}
**Supplier:** {draft.supplier_name}
**Reviewed:** {date.today().isoformat()}
**Legal risk score:** {analysis['legal_risk_score']:.0f} / 100 ({analysis['risk_band']})

## Missing mandatory clauses

{missing_md}

## Risky language

{risky_md}

## Recommended redlines

{redlines}

## Obligations and renewal

| Item | Value |
|---|---|
| Obligations extracted | {obligations.get('obligation_count', 0)} |
| Renewal date | {obligations.get('renewal_date')} |
| Notice period | {obligations.get('notice_days')} days |
| Notice deadline | {obligations.get('notice_deadline')} |
| Auto-renews | {'Yes' if obligations.get('auto_renew') else 'No'} |

---
*Prepared by the Contract Lifecycle Agent. Advisory — Legal and Procurement own the redline.*
"""
        artifacts.append(artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title=f"Clause review · {draft.reference}",
            filename=f"clause-review-{draft.reference}.md",
            content=review, kind="review",
            summary=f"{len(analysis['missing_clauses'])} missing, "
                    f"{len(analysis['risky_clauses'])} risky, score "
                    f"{analysis['legal_risk_score']:.0f}.",
            entity_type="contract_draft", entity_id=draft.id,
        ))

        if obligations.get("obligations"):
            artifacts.append(artifact_service.produce_output(
                db, agent_key=self.key, execution_id=execution_id,
                title=f"Obligation register · {draft.reference}",
                filename=f"obligations-{draft.reference}.csv",
                content=artifact_service.to_csv([
                    {"type": o.get("type"), "metric": o.get("metric"),
                     "target": o.get("target"), "detail": o.get("detail")}
                    for o in obligations["obligations"]
                ]),
                kind="dataset",
                summary=f"{obligations['obligation_count']} trackable commitment(s).",
                entity_type="contract_draft", entity_id=draft.id,
            ))

        artifact_ids = [a.id for a in artifacts]
        clean = not analysis["missing_clauses"] and not analysis["risky_clauses"]
        confidence = 0.94 if clean else round(max(0.72, 0.94 - 0.03 * (
            len(analysis["missing_clauses"]) + len(analysis["risky_clauses"]))), 4)

        proposals = [
            ProposedAction(
                action_kind=ActionKind.DRAFT_CONTRACT,
                title=f"Accept {draft.reference} ({draft.contract_type}) "
                      f"— legal risk {analysis['legal_risk_score']:.0f}",
                summary=(
                    f"{draft.title}. "
                    + (f"{len(analysis['missing_clauses'])} mandatory clause(s) missing: "
                       f"{', '.join(m['label'] for m in analysis['missing_clauses'][:4])}. "
                       if analysis["missing_clauses"] else "Full mandatory clause set present. ")
                    + (f"{len(analysis['risky_clauses'])} risky clause(s): "
                       f"{', '.join(r['label'] for r in analysis['risky_clauses'][:3])}. "
                       if analysis["risky_clauses"] else "No vendor-favouring language detected. ")
                    + f"Renewal {obligations.get('renewal_date')}, notice by "
                      f"{obligations.get('notice_deadline')}."
                ),
                payload={"draft_id": draft.id},
                diff_preview=[
                    {"field": "status", "label": "Draft status",
                     "before": draft.status, "after": "approved_draft"},
                    {"field": "legal_risk", "label": "Legal risk score",
                     "before": "—", "after": f"{analysis['legal_risk_score']:.0f}"},
                ],
                alternatives=[
                    {"option": "Accept with redlines",
                     "detail": f"{len(analysis['redline_notes'])} change(s) recommended."},
                    {"option": "Reject and re-author",
                     "detail": "Send back to the clause library baseline."},
                ],
                confidence=confidence,
                financial_impact_usd=draft.value_usd,
                stage=WorkflowStage.APPROVAL,
                entity_type="contract_draft", entity_id=draft.id, entity_label=draft.reference,
                due_in_hours=24,
                artifact_ids=artifact_ids,
            )
        ]

        # Only offer signature when the paper is actually defensible.
        if clean or analysis["legal_risk_score"] < 20:
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE,
                    title=f"Issue {draft.reference} to {draft.supplier_name} for signature",
                    summary=(
                        f"Legal risk {analysis['legal_risk_score']:.0f} is inside the tolerance for "
                        f"issue. {draft.value_usd:,.2f} USD over {draft.term_months} months. "
                        f"Sending this commits the company and cannot be recalled."
                    ),
                    payload={"draft_id": draft.id},
                    diff_preview=[{"field": "status", "label": "Draft status",
                                   "before": draft.status, "after": "issued_for_signature"}],
                    confidence=confidence,
                    financial_impact_usd=draft.value_usd,
                    stage=WorkflowStage.APPROVAL,
                    entity_type="contract_draft", entity_id=draft.id, entity_label=draft.reference,
                    due_in_hours=48,
                    extra_flags=["irreversible"],
                )
            )
        else:
            rules.append("Signature is not offered while mandatory clauses are missing or risky "
                         "language stands — the redline comes first.")

        return AgentDecision(
            conclusion=(
                f"{draft.reference}: legal risk {analysis['legal_risk_score']:.0f} "
                f"({analysis['risk_band']}), {len(analysis['missing_clauses'])} missing and "
                f"{len(analysis['risky_clauses'])} risky clause(s), "
                f"{obligations.get('obligation_count', 0)} obligation(s) tracked."
            ),
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=analysis["legal_risk_score"] >= 35,
            escalation_reason=f"Legal risk {analysis['legal_risk_score']:.0f} warrants Legal review."
            if analysis["legal_risk_score"] >= 35 else None,
        )
