"""Procurement Agent 5 — Tail Spend Management.

80% of the transactions, 20% of the spend. Finds the tail on a Pareto cut,
prices consolidation onto preferred suppliers, and drafts spot-buy RFQs.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, Role, WorkflowStage
from ..models import Contract, SpendTransaction, Supplier, TailSpendFinding
from ..services import artifacts as artifact_service
from ..skills import spend_analysis, tail_spend
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)


class TailSpendAgent(BaseAgent):
    key = "tail_spend"
    name = "Tail Spend Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Governs the long tail of low-value, high-volume, off-contract buying."
    mission = "Bring unmanaged spend under control without adding friction to small purchases."
    goals = [
        "Reduce tail spend by 40%.",
        "Move fragmented categories onto preferred suppliers.",
        "Give every off-catalog flag a named catalog substitute.",
    ]
    tools = ["Spend extract", "Catalog", "Preferred supplier list", "Contract register"]
    skills = ["tail_spend_detection", "catalog_compliance", "vendor_consolidation",
              "spot_buy_automation"]
    default_stage = WorkflowStage.VALIDATION
    escalation_role = Role.PROCUREMENT
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.CONSOLIDATE_SUPPLIERS, ActionKind.ENFORCE_CATALOG]

    inputs = [
        IOSpec("spend_extract", "Transaction-level spend to analyse for tail behaviour.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="spend-fy26-q3.csv → supplier,description,amount_usd,po_number"),
        IOSpec("catalog", "Contracted catalog items used to test substitutability.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="catalog.csv → item_code,description,category,unit_price"),
        IOSpec("stored transactions", "Falls back to the loaded spend cube when nothing is attached.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Tail spend analysis", "Head/tail split with the Pareto point and one-time vendors.",
               kind="artifact", formats=["csv"], example="tail-spend-analysis.csv"),
        IOSpec("Consolidation plan", "Category clusters with target supplier and priced savings.",
               kind="artifact", formats=["md"], example="consolidation-plan.md"),
        IOSpec("Off-catalog report", "Transactions with a named catalog substitute and price delta.",
               kind="artifact", formats=["csv"], example="off-catalog.csv"),
        IOSpec("Spot-buy RFQ", "Three-quote RFQ draft for a repeated one-off cluster.",
               kind="artifact", formats=["md"], example="spot-buy-rfq.md"),
        IOSpec("Checkpoints", "Consolidate suppliers / enforce catalog — Procurement approves.",
               kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        return ("tail_spend", None, "Tail spend analysis")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Load spend and catalog", "ingest",
                     "Attachments win over the stored cube."),
            PlanStep(2, "Split head from tail on a Pareto cut", "tail_spend_detection",
                     "A defensible cut beats an arbitrary value threshold."),
            PlanStep(3, "Cluster the tail by category", "vendor_consolidation",
                     "Consolidation only means something within a category."),
            PlanStep(4, "Test off-catalog buying for substitutes", "catalog_compliance",
                     "No substitute, no flag — false positives cost credibility."),
            PlanStep(5, "Draft a spot-buy RFQ where it pays", "spot_buy_automation",
                     "Repeated one-offs deserve competitive tension."),
            PlanStep(6, "Submit interventions for approval", "hitl_checkpoint",
                     "Moving spend between suppliers is a commercial decision."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []

        rows: list[dict] = []
        catalog: list[dict] = []
        source = "stored spend cube"
        for attachment in context.get("attachments", []):
            if attachment["format"] not in {"csv", "json"} or not attachment["rows"]:
                continue
            fields = " ".join(attachment["fields"]).lower()
            if "item_code" in fields or "unit_price" in fields:
                catalog = [
                    {"item_code": r.get("item_code"), "description": r.get("description"),
                     "category": r.get("category"), "unit_price": _num(r.get("unit_price"))}
                    for r in attachment["rows"]
                ]
                continue
            for raw in attachment["rows"]:
                rows.append({
                    "external_id": raw.get("external_id") or raw.get("id"),
                    "supplier_raw": raw.get("supplier") or raw.get("supplier_name") or "",
                    "description": raw.get("description") or "",
                    "amount_usd": _num(raw.get("amount_usd") or raw.get("amount")),
                    "po_number": raw.get("po_number") or "",
                    "on_contract": str(raw.get("on_contract", "")).lower() in {"true", "yes", "1", "y"},
                })
            source = attachment["filename"]

        if not rows:
            stored = db.execute(select(SpendTransaction)).scalars().all()
            rows = [{
                "id": t.id, "external_id": t.external_id, "supplier_raw": t.supplier_raw,
                "description": t.description, "amount_usd": t.amount_usd,
                "po_number": t.po_number, "on_contract": t.on_contract, "category": t.category,
            } for t in stored]

        # Classify anything that arrived unclassified — the tail is analysed by category.
        for row in rows:
            if not row.get("category"):
                row["category"] = spend_analysis.classify(
                    row["description"], row["supplier_raw"])["category"] or "Uncategorised"

        context["rows"] = rows
        observations.append(
            Observation("ingest",
                        f"Loaded {len(rows):,} transaction(s) from {source}"
                        + (f" and {len(catalog)} catalog item(s)." if catalog else "; no catalog supplied."),
                        {"transactions": len(rows), "catalog_items": len(catalog)},
                        ok=bool(rows))
        )
        if not rows:
            return observations

        detection = tail_spend.detect(rows)
        context["detection"] = detection
        observations.append(
            Observation("tail_spend_detection",
                        f"Tail is {detection['tail_share_pct']:.1f}% of spend "
                        f"({detection['tail_spend_usd']:,.2f} USD) across "
                        f"{detection['tail_supplier_count']} supplier(s), but "
                        f"{detection['tail_transaction_share_pct']:.1f}% of transactions. "
                        f"Pareto point at supplier {detection['pareto_point']}.",
                        {k: v for k, v in detection.items() if k != "tail_transactions"},
                        ok=detection["tail_share_pct"] < 20)
        )

        # Preferred supplier per category = the contracted supplier with most spend.
        preferred: dict[str, str] = {}
        for contract in db.execute(
            select(Contract).where(Contract.status == "active")
        ).scalars().all():
            supplier = db.get(Supplier, contract.supplier_id)
            if supplier and supplier.category and not supplier.on_hold:
                preferred.setdefault(supplier.category, supplier.name)
        context["preferred"] = preferred

        plan = tail_spend.consolidation_plan(detection["tail_transactions"], preferred)
        context["plan"] = plan
        observations.append(
            Observation("vendor_consolidation",
                        f"{len(plan['findings'])} consolidation cluster(s) worth "
                        f"{plan['total_savings_usd']:,.2f} USD at a "
                        f"{plan['consolidation_rate']:.0%} rate.",
                        plan["findings"][:10], ok=bool(plan["findings"]))
        )

        gaps = tail_spend.catalog_gaps(rows, catalog) if catalog else {
            "off_catalog": [], "off_catalog_count": 0, "price_delta_usd": 0.0,
            "requires_human_review": False,
        }
        context["gaps"] = gaps
        observations.append(
            Observation("catalog_compliance",
                        f"{gaps['off_catalog_count']} off-catalog transaction(s) have a catalog "
                        f"substitute, worth {gaps['price_delta_usd']:,.2f} USD of price delta."
                        if catalog else
                        "No catalog attached — off-catalog testing skipped rather than guessed.",
                        gaps["off_catalog"][:10], ok=gaps["off_catalog_count"] == 0)
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        rows = context.get("rows", [])
        if not rows:
            return AgentDecision(
                conclusion="No spend data available for tail analysis.",
                confidence=0.4, decision_rules=["Attach a spend extract or load the cube."],
                evidence=[], escalate=True, escalation_reason="No spend data.",
            )

        detection = context["detection"]
        plan = context["plan"]
        gaps = context["gaps"]
        execution_id = context.get("_execution_id")

        evidence = [
            evidence_item("Total spend", f"{detection['total_spend_usd']:,.2f} USD", "ingest"),
            evidence_item("Tail spend",
                          f"{detection['tail_spend_usd']:,.2f} USD "
                          f"({detection['tail_share_pct']:.1f}%)", "tail_spend_detection"),
            evidence_item("Tail transaction share",
                          f"{detection['tail_transaction_share_pct']:.1f}%", "tail_spend_detection"),
            evidence_item("Tail suppliers", str(detection["tail_supplier_count"]),
                          "tail_spend_detection"),
            evidence_item("One-time vendors", str(len(detection["one_time_vendors"])),
                          "tail_spend_detection"),
            evidence_item("Consolidation savings", f"{plan['total_savings_usd']:,.2f} USD",
                          "vendor_consolidation"),
        ]
        rules = [
            f"The tail is the spend beyond the {tail_spend.PARETO_CUT:.0%} cumulative Pareto point, "
            f"by supplier.",
            f"Consolidation is priced at {tail_spend.CONSOLIDATION_RATE:.0%} of the moved spend.",
            "A category with no qualified preferred supplier is reported, not forced.",
        ]

        analysis_csv = artifact_service.to_csv([
            {"supplier": t.get("tail_supplier"), "description": t.get("description"),
             "category": t.get("category"), "amount_usd": t.get("amount_usd"),
             "po_number": t.get("po_number"), "on_contract": t.get("on_contract")}
            for t in detection["tail_transactions"]
        ])
        analysis_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Tail spend analysis", filename="tail-spend-analysis.csv",
            content=analysis_csv, kind="dataset",
            summary=f"{len(detection['tail_transactions'])} tail transactions, "
                    f"{detection['tail_spend_usd']:,.0f} USD.",
            entity_type="tail_spend",
        )

        plan_md = f"""# Tail spend consolidation plan

**Generated:** {date.today().isoformat()}
**Total spend analysed:** {detection['total_spend_usd']:,.2f} USD
**Tail spend:** {detection['tail_spend_usd']:,.2f} USD ({detection['tail_share_pct']:.1f}% of value,
{detection['tail_transaction_share_pct']:.1f}% of transactions)
**Tail suppliers:** {detection['tail_supplier_count']} · **Head suppliers:** {detection['head_supplier_count']}

## Consolidation opportunities

{artifact_service.markdown_table(
    ["Category", "Suppliers", "Transactions", "Spend (USD)", "Target supplier", "Savings (USD)"],
    [[f["category"], len(f["supplier_names"]), f["transaction_count"],
      f"{f['spend_usd']:,.0f}", f["recommended_supplier"] or "— none on file —",
      f"{f['consolidation_savings_usd']:,.0f}"] for f in plan["findings"]],
) if plan["findings"] else "_No cluster above the materiality threshold._"}

**Total projected savings: {plan['total_savings_usd']:,.2f} USD** at a
{plan['consolidation_rate']:.0%} consolidation rate.

## One-time vendors

{artifact_service.markdown_table(
    ["Supplier", "Spend (USD)"],
    [[v["supplier"], f"{v['spend_usd']:,.2f}"] for v in detection["one_time_vendors"][:15]],
) if detection["one_time_vendors"] else "_None._"}

## Method

The tail is everything beyond the {tail_spend.PARETO_CUT:.0%} cumulative spend point when
suppliers are ranked by value — supplier {detection['pareto_point']} in this dataset.
Savings are priced at {tail_spend.CONSOLIDATION_RATE:.0%} of the spend actually moved, and only
where a qualified preferred supplier exists.

---
*Prepared by the Tail Spend Agent. Every move requires Procurement approval.*
"""
        plan_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Consolidation plan", filename="consolidation-plan.md",
            content=plan_md, kind="report",
            summary=f"{len(plan['findings'])} cluster(s), {plan['total_savings_usd']:,.0f} USD.",
            entity_type="tail_spend",
        )

        artifacts = [analysis_artifact.id, plan_artifact.id]
        if gaps["off_catalog"]:
            artifacts.append(artifact_service.produce_output(
                db, agent_key=self.key, execution_id=execution_id,
                title="Off-catalog report", filename="off-catalog.csv",
                content=artifact_service.to_csv(gaps["off_catalog"]), kind="dataset",
                summary=f"{gaps['off_catalog_count']} substitutable transactions, "
                        f"{gaps['price_delta_usd']:,.0f} USD delta.",
                entity_type="tail_spend",
            ).id)

        # Persist findings and raise a checkpoint per material cluster.
        proposals: list[ProposedAction] = []
        for finding in plan["findings"][:5]:
            count = db.execute(select(func.count(TailSpendFinding.id))).scalar_one() or 0
            record = TailSpendFinding(
                reference=f"TSF-{count + 8001}",
                finding_type=finding["finding_type"],
                category=finding["category"],
                supplier_names=finding["supplier_names"],
                transaction_count=finding["transaction_count"],
                spend_usd=finding["spend_usd"],
                recommended_supplier=finding["recommended_supplier"],
                consolidation_savings_usd=finding["consolidation_savings_usd"],
                recommendation=finding["recommendation"],
            )
            db.add(record)
            db.flush()

            if finding["recommended_supplier"]:
                proposals.append(
                    ProposedAction(
                        action_kind=ActionKind.CONSOLIDATE_SUPPLIERS,
                        title=f"Consolidate {finding['category']} onto "
                              f"{finding['recommended_supplier']}",
                        summary=finding["recommendation"],
                        payload={"finding_id": record.id},
                        diff_preview=[
                            {"field": "suppliers", "label": "Suppliers in category",
                             "before": str(len(finding["supplier_names"])), "after": "1"},
                            {"field": "savings", "label": "Projected savings",
                             "before": "0", "after": f"{finding['consolidation_savings_usd']:,.0f} USD"},
                        ],
                        alternatives=[
                            {"option": "Run a mini-competition first",
                             "detail": "Test the market before moving the volume."},
                            {"option": "Consolidate to two suppliers",
                             "detail": "Keeps a second source; roughly half the saving."},
                        ],
                        confidence=0.88,
                        financial_impact_usd=finding["spend_usd"],
                        stage=WorkflowStage.VALIDATION,
                        entity_type="tail_spend", entity_id=record.id,
                        entity_label=record.reference,
                        due_in_hours=48,
                        artifact_ids=artifacts,
                    )
                )
            else:
                # No preferred supplier exists for this category. Catalog
                # enforcement only makes sense where a catalog substitute was
                # actually found — otherwise the finding stands on its own and
                # the honest next step is a sourcing event, not an enforcement
                # action the buyer cannot comply with.
                substitutable = [
                    g for g in gaps["off_catalog"]
                    if (g.get("category") or "") == finding["category"]
                ]
                if not substitutable:
                    continue
                recoverable = round(sum(g["estimated_saving_usd"] for g in substitutable), 2)
                proposals.append(
                    ProposedAction(
                        action_kind=ActionKind.ENFORCE_CATALOG,
                        title=f"Restrict {finding['category']} to catalog buying",
                        summary=(
                            f"{len(substitutable)} off-catalog transaction(s) in "
                            f"{finding['category']} have a contracted catalog substitute "
                            f"(e.g. {substitutable[0]['catalog_item']}), worth "
                            f"{recoverable:,.2f} USD of price delta. "
                            f"{finding['recommendation']}"
                        ),
                        payload={"finding_id": record.id},
                        diff_preview=[
                            {"field": "channel", "label": "Buying channel",
                             "before": "open", "after": "catalog only"},
                            {"field": "recoverable", "label": "Price delta recoverable",
                             "before": "0", "after": f"{recoverable:,.2f} USD"},
                        ],
                        confidence=0.85,
                        financial_impact_usd=finding["spend_usd"],
                        stage=WorkflowStage.VALIDATION,
                        entity_type="tail_spend", entity_id=record.id,
                        entity_label=record.reference,
                        due_in_hours=48,
                        artifact_ids=artifacts,
                    )
                )

        return AgentDecision(
            conclusion=(
                f"Tail is {detection['tail_share_pct']:.1f}% of spend "
                f"({detection['tail_spend_usd']:,.0f} USD) but "
                f"{detection['tail_transaction_share_pct']:.1f}% of transactions. "
                f"{len(plan['findings'])} consolidation cluster(s) worth "
                f"{plan['total_savings_usd']:,.0f} USD."
            ),
            confidence=0.89,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=detection["tail_share_pct"] >= 25,
            escalation_reason=f"Tail is {detection['tail_share_pct']:.1f}% of spend — above the "
                              f"25% intervention threshold."
            if detection["tail_share_pct"] >= 25 else None,
        )


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0
