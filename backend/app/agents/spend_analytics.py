"""Procurement Agent 2 — Spend Analytics & Classification.

Takes a raw spend extract as an attachment, classifies it against a taxonomy,
normalises supplier identities, measures contract compliance and prices the
savings levers it finds.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, Role, WorkflowStage
from ..models import Contract, SpendTransaction, Supplier
from ..services import artifacts as artifact_service
from ..skills import spend_analysis
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)

CONFIDENCE_FLOOR = 0.75


class SpendAnalyticsAgent(BaseAgent):
    key = "spend_analytics"
    name = "Spend Analytics Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Classifies spend, normalises suppliers and prices the savings levers."
    mission = "Turn a raw spend extract into classified, addressable, priced opportunity."
    goals = [
        "Classify 95%+ of spend value against the taxonomy.",
        "Surface consolidation, coverage and rationalisation levers with a stated basis.",
        "Measure contract compliance on value, not transaction count.",
    ]
    tools = ["Spend extract", "Vendor master", "Contract register", "Category taxonomy"]
    skills = ["spend_classification", "supplier_normalization", "savings_identification",
              "maverick_detection"]
    default_stage = WorkflowStage.VALIDATION
    escalation_role = Role.PROCUREMENT
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.PUBLISH_SPEND_CLASSIFICATION, ActionKind.CREATE_SAVINGS_OPPORTUNITY]

    inputs = [
        IOSpec("spend_extract",
               "Transaction-level spend export. Recognised columns: supplier, description, "
               "amount, date, cost_center, po_number, on_contract.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="spend-fy26-q3.csv → external_id,supplier,description,amount_usd,date,po_number"),
        IOSpec("stored transactions",
               "When no attachment is supplied, the agent analyses spend already loaded.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Classified spend", "Every transaction with category, UNSPSC, confidence and the "
                                   "token the classification was based on.",
               kind="artifact", formats=["csv"], example="classified-spend.csv"),
        IOSpec("Savings register", "Priced opportunities with lever, addressable spend and rate.",
               kind="artifact", formats=["csv"], example="savings-register.csv"),
        IOSpec("Spend insight brief", "Narrative analysis: concentration, compliance, leakage.",
               kind="artifact", formats=["md"], example="spend-insight-brief.md"),
        IOSpec("Unclassified residual", "Rows below the confidence floor, for a human to resolve.",
               kind="artifact", formats=["csv"], example="unclassified-residual.csv"),
        IOSpec("Checkpoints", "Publish classification / log savings — Procurement approves.",
               kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        return ("spend", None, "Spend analysis")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Load the spend extract", "spend_classification",
                     "An attachment takes precedence over stored data."),
            PlanStep(2, "Normalise supplier identities", "supplier_normalization",
                     "Fragmented names hide both duplicates and leverage."),
            PlanStep(3, "Classify against the taxonomy", "spend_classification",
                     "Category is the unit of analysis for every downstream lever."),
            PlanStep(4, "Measure contract compliance", "maverick_detection",
                     "Compliance is measured on value — count flatters the number."),
            PlanStep(5, "Price the savings levers", "savings_identification",
                     "An opportunity without an addressable base and a rate is an opinion."),
            PlanStep(6, "Submit for approval", "hitl_checkpoint",
                     "Nothing enters the spend cube or the savings pipeline unreviewed."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []
        suppliers = db.execute(select(Supplier)).scalars().all()
        master = [{"id": s.id, "name": s.name, "legal_name": s.legal_name,
                   "category": s.category, "on_contract": False} for s in suppliers]
        contracted = {
            c.supplier_id for c in db.execute(
                select(Contract).where(Contract.status == "active")
            ).scalars().all()
        }

        # ---- 1. Source the transactions ----------------------------------
        rows: list[dict] = []
        source = "stored spend cube"
        for attachment in context.get("attachments", []):
            if attachment["format"] in {"csv", "json"} and attachment["rows"]:
                for raw in attachment["rows"]:
                    rows.append({
                        "external_id": raw.get("external_id") or raw.get("id") or raw.get("txn_id"),
                        "supplier_raw": raw.get("supplier") or raw.get("supplier_name") or raw.get("vendor") or "",
                        "description": raw.get("description") or raw.get("item") or "",
                        "amount_usd": _num(raw.get("amount_usd") or raw.get("amount") or raw.get("value")),
                        "transaction_date": raw.get("date") or raw.get("transaction_date"),
                        "cost_center": raw.get("cost_center") or raw.get("costcentre"),
                        "po_number": raw.get("po_number") or raw.get("po") or "",
                        "on_contract": str(raw.get("on_contract", "")).strip().lower() in {"true", "yes", "1", "y"},
                        "source_artifact_id": attachment["id"],
                    })
                source = attachment["filename"]
                break

        persisted = False
        if not rows:
            stored = db.execute(select(SpendTransaction)).scalars().all()
            rows = [{
                "id": t.id, "external_id": t.external_id, "supplier_raw": t.supplier_raw,
                "supplier_id": t.supplier_id, "description": t.description,
                "amount_usd": t.amount_usd, "transaction_date": t.transaction_date,
                "cost_center": t.cost_center, "po_number": t.po_number,
                "on_contract": t.on_contract, "category": t.category,
            } for t in stored]
            persisted = True

        context["rows"], context["persisted"] = rows, persisted
        total = round(sum(r["amount_usd"] for r in rows), 2)
        observations.append(
            Observation("spend_extract_load",
                        f"Loaded {len(rows):,} transaction(s) worth {total:,.2f} USD from {source}.",
                        {"count": len(rows), "total_usd": total, "source": source},
                        ok=bool(rows))
        )
        if not rows:
            return observations

        # ---- 2. Supplier normalisation ------------------------------------
        normalization = spend_analysis.normalize_suppliers(
            [r["supplier_raw"] for r in rows], master)
        context["normalization"] = normalization
        for row in rows:
            resolved = normalization["resolutions"].get(row["supplier_raw"], {})
            if resolved.get("supplier_id"):
                row["supplier_id"] = resolved["supplier_id"]
        observations.append(
            Observation("supplier_normalization",
                        f"{normalization['resolved_pct']:.1f}% of supplier strings resolved to "
                        f"vendor master; {len(normalization['duplicate_clusters'])} duplicate "
                        f"cluster(s); {len(normalization['unresolved'])} unresolved.",
                        normalization,
                        ok=not normalization["unresolved"])
        )

        # ---- 3. Classification --------------------------------------------
        supplier_categories = {s.id: s.category for s in suppliers}
        classified, unclassified = [], []
        for row in rows:
            result = spend_analysis.classify(
                row["description"], row["supplier_raw"],
                hint_category=supplier_categories.get(row.get("supplier_id")),
            )
            row.update(result)
            (classified if result["confidence"] >= CONFIDENCE_FLOOR else unclassified).append(row)

        classified_value = sum(r["amount_usd"] for r in classified)
        coverage = round(classified_value / (total or 1) * 100, 2)
        context["classified"], context["unclassified"] = classified, unclassified
        observations.append(
            Observation("spend_classification",
                        f"{len(classified):,} of {len(rows):,} rows classified above the "
                        f"{CONFIDENCE_FLOOR:.0%} floor — {coverage:.1f}% of spend value. "
                        f"{len(unclassified)} row(s) held back as unclassified.",
                        {"coverage_pct": coverage, "unclassified": len(unclassified)},
                        ok=coverage >= 90)
        )

        # ---- 4. Contract compliance ---------------------------------------
        maverick = spend_analysis.detect_maverick(rows, contracted_suppliers=contracted)
        context["maverick"] = maverick
        observations.append(
            Observation("maverick_detection",
                        f"Contract compliance {maverick['contract_compliance_pct']:.1f}% by value. "
                        f"{maverick['maverick_count']} maverick transaction(s) worth "
                        f"{maverick['maverick_spend_usd']:,.2f} USD.",
                        {k: v for k, v in maverick.items() if k != "maverick_transactions"},
                        ok=maverick["contract_compliance_pct"] >= 90)
        )

        # ---- 5. Savings levers --------------------------------------------
        by_category: dict[str, dict] = defaultdict(lambda: {"spend_usd": 0.0, "suppliers": set()})
        uncontracted: dict[str, float] = defaultdict(float)
        for row in classified:
            bucket = by_category[row["category"]]
            bucket["spend_usd"] += row["amount_usd"]
            bucket["suppliers"].add(row["supplier_raw"])
            if not row.get("on_contract") and row.get("supplier_id") not in contracted:
                uncontracted[row["category"]] += row["amount_usd"]
        category_stats = {
            k: {"spend_usd": round(v["spend_usd"], 2), "supplier_count": len(v["suppliers"])}
            for k, v in by_category.items()
        }
        context["category_stats"] = category_stats

        clusters = []
        for cluster in normalization["duplicate_clusters"]:
            spend = sum(r["amount_usd"] for r in rows
                        if r["supplier_raw"] in cluster["variants"])
            supplier = db.get(Supplier, cluster["supplier_id"])
            clusters.append({**cluster, "spend_usd": spend,
                             "name": supplier.name if supplier else "supplier",
                             "category": supplier.category if supplier else None})

        savings = spend_analysis.identify_savings(
            by_category=category_stats,
            duplicate_clusters=clusters,
            maverick_spend=maverick["maverick_spend_usd"],
            uncontracted_by_category=dict(uncontracted),
        )
        context["savings"] = savings
        observations.append(
            Observation("savings_identification",
                        f"{len(savings['opportunities'])} opportunity(ies) worth "
                        f"{savings['total_estimated_savings_usd']:,.2f} USD across "
                        f"{len(category_stats)} categories.",
                        savings, ok=bool(savings["opportunities"]))
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        rows = context.get("rows", [])
        if not rows:
            return AgentDecision(
                conclusion="No spend data supplied — attach a spend extract or load the cube.",
                confidence=0.4,
                decision_rules=["The agent needs transactions to analyse."],
                evidence=[evidence_item("Transactions", "0", "spend_extract_load")],
                escalate=True, escalation_reason="No spend data available.",
            )

        classified = context["classified"]
        unclassified = context["unclassified"]
        maverick = context["maverick"]
        savings = context["savings"]
        stats = context.get("category_stats", {})
        total = round(sum(r["amount_usd"] for r in rows), 2)
        coverage = round(sum(r["amount_usd"] for r in classified) / (total or 1) * 100, 2)
        execution_id = context.get("_execution_id")

        evidence = [
            evidence_item("Transactions analysed", f"{len(rows):,}", "spend_extract_load"),
            evidence_item("Spend under analysis", f"{total:,.2f} USD", "spend_extract_load"),
            evidence_item("Classification coverage", f"{coverage:.1f}% of value", "spend_classification"),
            evidence_item("Contract compliance", f"{maverick['contract_compliance_pct']:.1f}%",
                          "maverick_detection"),
            evidence_item("Maverick spend", f"{maverick['maverick_spend_usd']:,.2f} USD",
                          "maverick_detection"),
            evidence_item("Identified savings", f"{savings['total_estimated_savings_usd']:,.2f} USD",
                          "savings_identification"),
        ]
        rules = [
            f"Rows below {CONFIDENCE_FLOOR:.0%} classification confidence are never published — "
            f"{len(unclassified)} held back.",
            "Contract compliance is measured on spend value, not transaction count.",
            f"Savings rates are published per lever: {savings['lever_rates']}.",
        ]

        # ---- Deliverables --------------------------------------------------
        classified_csv = artifact_service.to_csv([
            {"external_id": r.get("external_id"), "supplier": r["supplier_raw"],
             "description": r["description"], "amount_usd": r["amount_usd"],
             "category": r["category"], "unspsc": r["unspsc"],
             "confidence": r["confidence"], "matched_on": r["matched_on"],
             "basis": r["basis"], "on_contract": r.get("on_contract")}
            for r in classified
        ])
        classified_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Classified spend", filename="classified-spend.csv",
            content=classified_csv, kind="dataset",
            summary=f"{len(classified):,} rows, {coverage:.1f}% of value classified.",
            entity_type="spend",
        )

        residual_artifact = None
        if unclassified:
            residual_artifact = artifact_service.produce_output(
                db, agent_key=self.key, execution_id=execution_id,
                title="Unclassified residual", filename="unclassified-residual.csv",
                content=artifact_service.to_csv([
                    {"external_id": r.get("external_id"), "supplier": r["supplier_raw"],
                     "description": r["description"], "amount_usd": r["amount_usd"],
                     "reason": r["basis"]}
                    for r in unclassified
                ]),
                kind="dataset",
                summary=f"{len(unclassified)} row(s) below the {CONFIDENCE_FLOOR:.0%} floor.",
                entity_type="spend",
            )

        savings_csv = artifact_service.to_csv([
            {"title": o["title"], "lever": o["lever"], "category": o.get("category"),
             "annual_spend_usd": o["annual_spend_usd"],
             "estimated_savings_usd": o["estimated_savings_usd"],
             "confidence": o["confidence"], "rationale": o["rationale"]}
            for o in savings["opportunities"]
        ])
        savings_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Savings register", filename="savings-register.csv",
            content=savings_csv, kind="dataset",
            summary=f"{len(savings['opportunities'])} opportunities, "
                    f"{savings['total_estimated_savings_usd']:,.0f} USD.",
            entity_type="savings",
        )

        top_categories = sorted(stats.items(), key=lambda kv: kv[1]["spend_usd"], reverse=True)[:8]
        brief = f"""# Spend insight brief

**Generated:** {date.today().isoformat()}
**Transactions analysed:** {len(rows):,}
**Spend under analysis:** {total:,.2f} USD

## Headline

| Measure | Value |
|---|---|
| Classification coverage | {coverage:.1f}% of value |
| Contract compliance | {maverick['contract_compliance_pct']:.1f}% |
| Maverick spend | {maverick['maverick_spend_usd']:,.2f} USD |
| Identified savings | {savings['total_estimated_savings_usd']:,.2f} USD |
| Unclassified rows | {len(unclassified)} |

## Category concentration

{artifact_service.markdown_table(
    ["Category", "Spend (USD)", "Suppliers"],
    [[c, f"{s['spend_usd']:,.2f}", s["supplier_count"]] for c, s in top_categories],
)}

## Savings levers

{artifact_service.markdown_table(
    ["Opportunity", "Lever", "Addressable (USD)", "Savings (USD)", "Confidence"],
    [[o["title"], o["lever"], f"{o['annual_spend_usd']:,.0f}",
      f"{o['estimated_savings_usd']:,.0f}", f"{o['confidence']:.0%}"]
     for o in savings["opportunities"][:10]],
) if savings["opportunities"] else "_No opportunities above the materiality threshold._"}

## What a reviewer should check

- The {len(unclassified)} unclassified row(s) — they are excluded from every number above.
- Savings rates are indicative per lever, not commitments: {savings['lever_rates']}.
- Contract compliance counts a transaction as compliant only with both an active
  contract and a purchase order.

---
*Prepared by the Spend Analytics Agent. Draft until released by Procurement.*
"""
        brief_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Spend insight brief", filename="spend-insight-brief.md",
            content=brief, kind="report",
            summary=f"{coverage:.1f}% classified, {maverick['contract_compliance_pct']:.1f}% "
                    f"compliant, {savings['total_estimated_savings_usd']:,.0f} USD identified.",
            entity_type="spend",
        )

        # ---- Proposals -----------------------------------------------------
        proposals: list[ProposedAction] = []
        if context.get("persisted") and classified:
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.PUBLISH_SPEND_CLASSIFICATION,
                    title=f"Publish classification for {len(classified):,} transactions",
                    summary=(
                        f"{coverage:.1f}% of {total:,.0f} USD classified above the "
                        f"{CONFIDENCE_FLOOR:.0%} confidence floor. {len(unclassified)} row(s) "
                        f"held back as unclassified rather than guessed."
                    ),
                    payload={"classifications": [
                        {"transaction_id": r.get("id"), "category": r["category"],
                         "unspsc": r["unspsc"], "confidence": r["confidence"],
                         "supplier_id": r.get("supplier_id"),
                         "maverick": any(m.get("id") == r.get("id")
                                         for m in maverick["maverick_transactions"])}
                        for r in classified if r.get("id")
                    ]},
                    diff_preview=[
                        {"field": "classified", "label": "Rows classified", "before": "0",
                         "after": f"{len(classified):,}"},
                        {"field": "coverage", "label": "Coverage of value", "before": "—",
                         "after": f"{coverage:.1f}%"},
                    ],
                    confidence=round(min(0.97, coverage / 100), 4),
                    financial_impact_usd=0.0,
                    stage=WorkflowStage.VALIDATION,
                    entity_type="spend", entity_label="Spend classification",
                    due_in_hours=24,
                    artifact_ids=[a.id for a in [classified_artifact, residual_artifact, brief_artifact] if a],
                )
            )

        if savings["opportunities"]:
            top = savings["opportunities"][:6]
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.CREATE_SAVINGS_OPPORTUNITY,
                    title=f"Accept {len(top)} savings opportunities "
                          f"({sum(o['estimated_savings_usd'] for o in top):,.0f} USD)",
                    summary="; ".join(
                        f"{o['title']} — {o['estimated_savings_usd']:,.0f} USD at "
                        f"{o['confidence']:.0%}" for o in top[:3]
                    ) + (f"; and {len(top) - 3} more." if len(top) > 3 else ""),
                    payload={"opportunities": top},
                    diff_preview=[
                        {"field": o["title"], "label": o["lever"],
                         "before": f"{o['annual_spend_usd']:,.0f} USD addressable",
                         "after": f"{o['estimated_savings_usd']:,.0f} USD target"}
                        for o in top
                    ],
                    alternatives=[
                        {"option": "Accept the top 3 only",
                         "detail": "Higher-confidence subset; leaves the rest in analysis."},
                        {"option": "Reject and re-baseline",
                         "detail": "Reject if the addressable base is wrong."},
                    ],
                    confidence=round(sum(o["confidence"] for o in top) / len(top), 4),
                    financial_impact_usd=round(sum(o["estimated_savings_usd"] for o in top), 2),
                    stage=WorkflowStage.VALIDATION,
                    entity_type="savings", entity_label="Savings pipeline",
                    due_in_hours=48,
                    artifact_ids=[savings_artifact.id],
                )
            )

        return AgentDecision(
            conclusion=(
                f"{coverage:.1f}% of {total:,.0f} USD classified; contract compliance "
                f"{maverick['contract_compliance_pct']:.1f}%; "
                f"{savings['total_estimated_savings_usd']:,.0f} USD of savings identified across "
                f"{len(savings['opportunities'])} lever(s)."
            ),
            confidence=round(min(0.96, 0.5 + coverage / 200), 4),
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=coverage < 85,
            escalation_reason=f"Classification coverage {coverage:.1f}% is below the 85% floor."
            if coverage < 85 else None,
        )


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0
