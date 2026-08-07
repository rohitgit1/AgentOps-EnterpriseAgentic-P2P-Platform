"""Procurement Agent 6 — Procurement Command Center.

Rolls the whole procurement portfolio into the executive KPI set from the
specification and drafts the brief. Publishing it is a CFO decision.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, Role, WorkflowStage
from ..models import (
    Contract,
    ContractDraft,
    RiskAssessment,
    SavingsOpportunity,
    SourcingEvent,
    SpendTransaction,
    Supplier,
    TailSpendFinding,
)
from ..services import artifacts as artifact_service
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)

# Executive KPI targets, straight from the specification.
TARGETS = {
    "spend_under_management": 95.0,
    "contract_compliance": 98.0,
    "supplier_risk_score": 20.0,       # lower is better
    "tail_spend_reduction": 40.0,
    "sourcing_cycle_time_reduction": 60.0,
    "procurement_savings": 5.0,
}


class ProcurementCommandCenterAgent(BaseAgent):
    key = "procurement_command_center"
    name = "Procurement Command Center Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Rolls the procurement portfolio into executive KPIs and a briefing."
    mission = "Give the executive a number for every procurement commitment, and its gap to target."
    goals = [
        "Report all six executive KPIs against their targets every cycle.",
        "Name the categories and suppliers driving each gap.",
        "Keep the savings pipeline and renewal forecast in one view.",
    ]
    tools = ["Sourcing pipeline", "Savings pipeline", "Risk register", "Contract register",
             "Tail spend findings", "Spend cube"]
    skills = ["kpi_generation", "portfolio_rollup", "renewal_forecasting"]
    default_stage = WorkflowStage.APPROVAL
    escalation_role = Role.CFO
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.88
    allowed_actions = [ActionKind.PUBLISH_EXECUTIVE_BRIEF]

    inputs = [
        IOSpec("portfolio state",
               "Reads the sourcing, savings, risk, contract, tail-spend and spend records "
               "already in the platform. No attachment required.",
               kind="data", required=False),
        IOSpec("board_pack_context",
               "Optional narrative or prior-period commentary to fold into the brief.",
               kind="attachment", formats=["md", "txt"], required=False,
               example="q2-commentary.md"),
    ]
    outputs = [
        IOSpec("Executive brief", "Six KPIs against target, with the drivers behind each gap.",
               kind="artifact", formats=["md"], example="procurement-executive-brief.md"),
        IOSpec("KPI pack", "Machine-readable KPI values, targets and variances.",
               kind="artifact", formats=["csv"], example="procurement-kpis.csv"),
        IOSpec("Risk heatmap data", "Per-supplier domain scores for the heatmap.",
               kind="artifact", formats=["json"], example="risk-heatmap.json"),
        IOSpec("Checkpoint", "Publish the executive brief — CFO approves.", kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        return ("procurement", None, "Procurement Command Center")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Roll up the sourcing pipeline", "portfolio_rollup",
                     "Cycle-time reduction is measured against the manual baseline."),
            PlanStep(2, "Roll up savings and spend coverage", "kpi_generation",
                     "Spend under management is the headline governance number."),
            PlanStep(3, "Roll up supplier risk", "portfolio_rollup",
                     "One portfolio risk score, with the outliers named."),
            PlanStep(4, "Forecast contract renewals", "renewal_forecasting",
                     "A renewal inside its notice window is a live commitment."),
            PlanStep(5, "Draft the executive brief", "kpi_generation",
                     "Every number carries its target and the gap."),
            PlanStep(6, "Submit for publication", "hitl_checkpoint",
                     "Executive communication goes out under a person's name."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []

        # ---- Sourcing --------------------------------------------------------
        events = db.execute(select(SourcingEvent)).scalars().all()
        awarded = [e for e in events if e.status == "awarded" and e.cycle_days]
        baseline = sum(e.baseline_cycle_days for e in awarded) / len(awarded) if awarded else 56.0
        actual = sum(e.cycle_days for e in awarded) / len(awarded) if awarded else None
        cycle_reduction = round((1 - actual / baseline) * 100, 1) if actual else 0.0
        sourcing_savings = round(sum(e.expected_savings_usd for e in events), 2)
        context["sourcing"] = {
            "total": len(events), "in_flight": len([e for e in events if e.status == "issued"]),
            "awarded": len(awarded), "cycle_reduction_pct": cycle_reduction,
            "avg_cycle_days": round(actual, 1) if actual else None,
            "baseline_days": round(baseline, 1), "expected_savings_usd": sourcing_savings,
        }
        observations.append(
            Observation("portfolio_rollup",
                        f"{len(events)} sourcing event(s): {context['sourcing']['in_flight']} in "
                        f"flight, {len(awarded)} awarded. Cycle-time reduction "
                        f"{cycle_reduction:.1f}% against a {baseline:.0f}-day baseline.",
                        context["sourcing"], ok=cycle_reduction >= TARGETS["sourcing_cycle_time_reduction"])
        )

        # ---- Spend & savings -------------------------------------------------
        transactions = db.execute(select(SpendTransaction)).scalars().all()
        total_spend = sum(t.amount_usd for t in transactions)
        classified = sum(t.amount_usd for t in transactions if t.category)
        on_contract = sum(t.amount_usd for t in transactions if t.on_contract)
        sum_ = total_spend or 1.0
        opportunities = db.execute(select(SavingsOpportunity)).scalars().all()
        approved_savings = sum(o.estimated_savings_usd for o in opportunities
                               if o.status == "approved")
        pipeline_savings = sum(o.estimated_savings_usd for o in opportunities)

        context["spend"] = {
            "total_spend_usd": round(total_spend, 2),
            "spend_under_management_pct": round(classified / sum_ * 100, 1),
            "contract_compliance_pct": round(on_contract / sum_ * 100, 1),
            "savings_pipeline_usd": round(pipeline_savings, 2),
            "savings_approved_usd": round(approved_savings, 2),
            "savings_pct_of_spend": round(pipeline_savings / sum_ * 100, 2),
        }
        observations.append(
            Observation("kpi_generation",
                        f"Spend under management {context['spend']['spend_under_management_pct']:.1f}%, "
                        f"contract compliance {context['spend']['contract_compliance_pct']:.1f}%, "
                        f"savings pipeline {pipeline_savings:,.0f} USD "
                        f"({context['spend']['savings_pct_of_spend']:.2f}% of spend).",
                        context["spend"],
                        ok=context["spend"]["spend_under_management_pct"] >= TARGETS["spend_under_management"])
        )

        # ---- Risk ------------------------------------------------------------
        assessments = db.execute(select(RiskAssessment)).scalars().all()
        avg_risk = round(sum(a.overall_risk for a in assessments) / len(assessments), 1) \
            if assessments else 0.0
        elevated = [a for a in assessments if a.risk_band in {"high", "critical"}]
        context["risk"] = {
            "assessed": len(assessments), "average_risk": avg_risk,
            "elevated": len(elevated),
            "bands": dict(Counter(a.risk_band for a in assessments)),
            "spend_at_risk_usd": round(sum(a.spend_at_risk_usd for a in elevated), 2),
        }
        context["assessments"] = assessments
        observations.append(
            Observation("risk_rollup",
                        f"{len(assessments)} supplier(s) assessed; average risk {avg_risk:.1f} "
                        f"against a <{TARGETS['supplier_risk_score']:.0f} target; "
                        f"{len(elevated)} elevated."
                        if assessments else
                        "No risk assessments on file — run the Supplier Risk & Compliance Agent first.",
                        context["risk"], ok=bool(assessments) and avg_risk < TARGETS["supplier_risk_score"])
        )

        # ---- Contracts & renewals -------------------------------------------
        contracts = db.execute(select(Contract)).scalars().all()
        today = date.today()
        expiring = [c for c in contracts if c.end_date and 0 <= (c.end_date - today).days <= 120]
        expired = [c for c in contracts if c.end_date and c.end_date < today]
        drafts = db.execute(select(ContractDraft)).scalars().all()
        context["contracts"] = {
            "active": len([c for c in contracts if c.status == "active"]),
            "expiring_120d": len(expiring), "expired": len(expired),
            "drafts_in_flight": len([d for d in drafts if d.status in {"drafted", "approved_draft"}]),
            "expiring_detail": [
                {"contract": c.contract_number, "supplier": c.supplier.name if c.supplier else None,
                 "end_date": c.end_date.isoformat(), "days": (c.end_date - today).days}
                for c in sorted(expiring, key=lambda c: c.end_date)
            ],
        }
        observations.append(
            Observation("renewal_forecasting",
                        f"{context['contracts']['active']} active contract(s); "
                        f"{len(expiring)} expiring within 120 days; {len(expired)} already expired.",
                        context["contracts"], ok=not expired)
        )

        # ---- Tail spend ------------------------------------------------------
        findings = db.execute(select(TailSpendFinding)).scalars().all()
        tail_spend_value = sum(t.amount_usd for t in transactions if t.tail_spend)
        addressable = sum(f.consolidation_savings_usd for f in findings)
        context["tail"] = {
            "findings": len(findings),
            "open": len([f for f in findings if f.status == "open"]),
            "tail_spend_usd": round(tail_spend_value, 2),
            "addressable_savings_usd": round(addressable, 2),
            "reduction_potential_pct": round(addressable / (tail_spend_value or 1) * 100, 1),
        }
        observations.append(
            Observation("tail_rollup",
                        f"{len(findings)} tail spend finding(s); "
                        f"{addressable:,.0f} USD addressable.",
                        context["tail"])
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        sourcing = context["sourcing"]
        spend = context["spend"]
        risk = context["risk"]
        contracts = context["contracts"]
        tail = context["tail"]
        execution_id = context.get("_execution_id")

        kpis = [
            {"kpi": "Spend under management", "value": spend["spend_under_management_pct"],
             "target": TARGETS["spend_under_management"], "unit": "%", "direction": "up"},
            {"kpi": "Contract compliance", "value": spend["contract_compliance_pct"],
             "target": TARGETS["contract_compliance"], "unit": "%", "direction": "up"},
            {"kpi": "Supplier risk score", "value": risk["average_risk"],
             "target": TARGETS["supplier_risk_score"], "unit": "", "direction": "down"},
            {"kpi": "Tail spend reduction potential", "value": tail["reduction_potential_pct"],
             "target": TARGETS["tail_spend_reduction"], "unit": "%", "direction": "up"},
            {"kpi": "Sourcing cycle time reduction", "value": sourcing["cycle_reduction_pct"],
             "target": TARGETS["sourcing_cycle_time_reduction"], "unit": "%", "direction": "up"},
            {"kpi": "Procurement savings", "value": spend["savings_pct_of_spend"],
             "target": TARGETS["procurement_savings"], "unit": "%", "direction": "up"},
        ]
        for row in kpis:
            row["meets_target"] = (row["value"] >= row["target"]) if row["direction"] == "up" \
                else (row["value"] <= row["target"])
            row["variance"] = round(row["value"] - row["target"], 2)

        off_target = [k for k in kpis if not k["meets_target"]]
        context["kpis"] = kpis

        evidence = [
            evidence_item(k["kpi"], f"{k['value']}{k['unit']} vs target {k['target']}{k['unit']} "
                                    f"({'on target' if k['meets_target'] else 'gap ' + str(k['variance'])})",
                          "kpi_generation")
            for k in kpis
        ]
        rules = [
            "Targets are the specification's executive KPI set.",
            "Supplier risk is a lower-is-better measure; the rest are higher-is-better.",
            "Publishing an executive brief goes out under a named person — CFO approval.",
        ]

        kpi_csv = artifact_service.to_csv(
            [{"kpi": k["kpi"], "value": k["value"], "unit": k["unit"], "target": k["target"],
              "direction": k["direction"], "variance": k["variance"],
              "meets_target": k["meets_target"]} for k in kpis]
        )
        kpi_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Procurement KPI pack", filename="procurement-kpis.csv",
            content=kpi_csv, kind="dataset",
            summary=f"{len(kpis) - len(off_target)}/{len(kpis)} KPIs on target.",
            entity_type="procurement",
        )

        heatmap = artifact_service.to_json([
            {"supplier": a.supplier_name, "financial": a.financial_risk,
             "operational": a.operational_risk, "compliance": a.compliance_risk,
             "esg": a.esg_risk, "overall": a.overall_risk, "band": a.risk_band}
            for a in context.get("assessments", [])
        ])
        heatmap_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Risk heatmap data", filename="risk-heatmap.json",
            content=heatmap, kind="dataset",
            summary=f"{risk['assessed']} supplier(s) across four risk domains.",
            entity_type="procurement",
        )

        gaps_md = "\n".join(
            f"- **{k['kpi']}** at {k['value']}{k['unit']} against a {k['target']}{k['unit']} "
            f"target — gap of {abs(k['variance'])}{k['unit']}."
            for k in off_target) or "- All six KPIs are on or ahead of target."

        renewals_md = artifact_service.markdown_table(
            ["Contract", "Supplier", "Expires", "Days"],
            [[c["contract"], c["supplier"], c["end_date"], c["days"]]
             for c in contracts["expiring_detail"][:10]],
        ) if contracts["expiring_detail"] else "_No contracts expiring in the next 120 days._"

        brief = f"""# Procurement executive brief

**Period ending:** {date.today().isoformat()}
**KPIs on target:** {len(kpis) - len(off_target)} of {len(kpis)}

## Executive KPIs

{artifact_service.markdown_table(
    ["KPI", "Actual", "Target", "Status"],
    [[k["kpi"], f"{k['value']}{k['unit']}", f"{k['target']}{k['unit']}",
      "On target" if k["meets_target"] else f"Gap {k['variance']}{k['unit']}"] for k in kpis],
)}

## Where the gaps are

{gaps_md}

## Sourcing pipeline

{sourcing['total']} event(s): {sourcing['in_flight']} in market, {sourcing['awarded']} awarded.
Average cycle {sourcing['avg_cycle_days'] or 'n/a'} days against a
{sourcing['baseline_days']:.0f}-day manual baseline — a
{sourcing['cycle_reduction_pct']:.1f}% reduction. Expected savings from awarded events:
{sourcing['expected_savings_usd']:,.2f} USD.

## Savings pipeline

Identified {spend['savings_pipeline_usd']:,.2f} USD, of which
{spend['savings_approved_usd']:,.2f} USD is approved — {spend['savings_pct_of_spend']:.2f}%
of {spend['total_spend_usd']:,.2f} USD analysed spend.

## Supplier risk

{risk['assessed']} supplier(s) assessed, average score {risk['average_risk']:.1f}
(target &lt;{TARGETS['supplier_risk_score']:.0f}). {risk['elevated']} at high or critical,
carrying {risk['spend_at_risk_usd']:,.2f} USD of unpaid exposure.
Band distribution: {risk['bands'] or 'n/a'}.

## Contract renewals

{contracts['active']} active, {contracts['expiring_120d']} expiring within 120 days,
{contracts['expired']} already expired, {contracts['drafts_in_flight']} draft(s) in flight.

{renewals_md}

## Tail spend

{tail['tail_spend_usd']:,.2f} USD identified as tail, with
{tail['addressable_savings_usd']:,.2f} USD addressable through consolidation
({tail['reduction_potential_pct']:.1f}% reduction potential). {tail['open']} finding(s) open.

---
*Prepared by the Procurement Command Center Agent. Draft until published by the CFO.*
"""
        brief_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Procurement executive brief", filename="procurement-executive-brief.md",
            content=brief, kind="report",
            summary=f"{len(kpis) - len(off_target)}/{len(kpis)} KPIs on target; "
                    f"{len(off_target)} gap(s).",
            entity_type="procurement",
        )

        summary = (
            f"{len(kpis) - len(off_target)} of {len(kpis)} executive KPIs on target. "
            + (f"Gaps: {', '.join(k['kpi'] for k in off_target)}." if off_target
               else "No gaps this period.")
        )

        return AgentDecision(
            conclusion=summary,
            confidence=0.93,
            decision_rules=rules,
            evidence=evidence,
            proposals=[
                ProposedAction(
                    action_kind=ActionKind.PUBLISH_EXECUTIVE_BRIEF,
                    title=f"Publish executive brief — {len(kpis) - len(off_target)}/{len(kpis)} KPIs on target",
                    summary=summary + f" Savings pipeline {spend['savings_pipeline_usd']:,.0f} USD; "
                                      f"{risk['elevated']} supplier(s) at elevated risk; "
                                      f"{contracts['expiring_120d']} renewal(s) inside 120 days.",
                    payload={"title": "Procurement executive brief", "summary": summary},
                    diff_preview=[
                        {"field": k["kpi"], "label": "vs target",
                         "before": f"target {k['target']}{k['unit']}",
                         "after": f"actual {k['value']}{k['unit']}"}
                        for k in kpis
                    ],
                    confidence=0.93,
                    financial_impact_usd=spend["savings_pipeline_usd"],
                    stage=WorkflowStage.APPROVAL,
                    entity_type="procurement", entity_label="Procurement Command Center",
                    due_in_hours=48,
                    artifact_ids=[brief_artifact.id, kpi_artifact.id, heatmap_artifact.id],
                )
            ],
            escalate=len(off_target) >= 3,
            escalation_reason=f"{len(off_target)} KPIs are off target." if len(off_target) >= 3 else None,
        )
