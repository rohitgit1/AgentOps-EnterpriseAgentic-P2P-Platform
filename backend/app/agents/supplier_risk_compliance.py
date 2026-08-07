"""Procurement Agent 3 — Supplier Risk & Compliance.

Scores suppliers across financial, operational, compliance and ESG risk and
recommends a disposition: approve, monitor, watchlist or block. Distinct from
the operational Supplier Risk Agent, which screens at payment time — this is the
periodic scorecard that decides whether to keep buying at all.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, RiskLevel, Role, WorkflowStage
from ..models import Invoice, RiskAssessment, Supplier
from ..services import artifacts as artifact_service
from ..skills import strategic_risk
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)


class SupplierRiskComplianceAgent(BaseAgent):
    key = "supplier_risk_compliance"
    name = "Supplier Risk & Compliance Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Scores suppliers across financial, operational, compliance and ESG risk."
    mission = "Keep a current, defensible risk position on every supplier the company depends on."
    goals = [
        "Hold the portfolio-average supplier risk score below 20.",
        "Detect financial distress and certificate lapse before they interrupt supply.",
        "Make every score traceable to named findings.",
    ]
    tools = ["Vendor master", "Financial indicators", "Certificate registry", "Delivery history",
             "Sanctions screening", "ESG disclosures"]
    skills = ["supplier_risk_assessment", "esg_scoring"]
    default_stage = WorkflowStage.VALIDATION
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.SET_SUPPLIER_DISPOSITION]

    inputs = [
        IOSpec("financial_indicators",
               "Credit ratings and distress signals per supplier. Columns: supplier, "
               "credit_rating, days_beyond_terms, bankruptcy_flag.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="credit-report-q3.csv → supplier,credit_rating,days_beyond_terms"),
        IOSpec("delivery_performance",
               "Operational performance. Columns: supplier, otif_pct, capacity_utilisation_pct, "
               "single_source.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="otif-fy26.csv → supplier,otif_pct,single_source"),
        IOSpec("supplier_id", "Assess one supplier. Omit to sweep the whole vendor master.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Risk scorecard", "Per-supplier scores across all four domains plus the "
                                 "recommended disposition.",
               kind="artifact", formats=["csv"], example="supplier-risk-scorecard.csv"),
        IOSpec("Risk report", "Narrative report with the findings behind each elevated score.",
               kind="artifact", formats=["md"], example="supplier-risk-report.md"),
        IOSpec("RiskAssessment records", "Persisted scorecards the portfolio view reads.",
               kind="record"),
        IOSpec("Checkpoint", "Set supplier disposition (approve / monitor / watchlist / block).",
               kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        if context.get("supplier_id"):
            supplier = db.get(Supplier, context["supplier_id"])
            if supplier:
                return ("supplier", supplier.id, supplier.name)
        return ("supplier", None, "Supplier risk sweep")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Select suppliers in scope", "vendor_scan",
                     "One supplier, or the whole master."),
            PlanStep(2, "Ingest financial and delivery feeds", "feed_ingest",
                     "A missing feed is reported as a gap, never scored as clean."),
            PlanStep(3, "Score four risk domains", "supplier_risk_assessment",
                     "Compliance is weighted hardest — it stops trade outright."),
            PlanStep(4, "Assess ESG exposure", "esg_scoring",
                     "Absent disclosure raises uncertainty rather than passing silently."),
            PlanStep(5, "Recommend a disposition for approval", "hitl_checkpoint",
                     "Blocking a supplier stops their revenue — a person owns that."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []

        if context.get("supplier_id"):
            suppliers = [s for s in [db.get(Supplier, context["supplier_id"])] if s]
        else:
            suppliers = db.execute(select(Supplier)).scalars().all()

        # ---- Attachments: financial and delivery feeds --------------------
        financials: dict[str, dict] = {}
        delivery: dict[str, dict] = {}
        feeds: list[str] = []
        for attachment in context.get("attachments", []):
            if attachment["format"] not in {"csv", "json"}:
                continue
            fields = " ".join(attachment["fields"]).lower()
            for row in attachment["rows"]:
                name = (row.get("supplier") or row.get("supplier_name") or "").strip()
                if not name:
                    continue
                if any(k in fields for k in ("credit", "bankrupt", "beyond_terms", "dso")):
                    financials[name.lower()] = {
                        "credit_rating": row.get("credit_rating"),
                        "days_beyond_terms": _num(row.get("days_beyond_terms")),
                        "bankruptcy_flag": str(row.get("bankruptcy_flag", "")).lower()
                        in {"true", "yes", "1", "y"},
                    }
                if any(k in fields for k in ("otif", "delivery", "capacity", "single_source")):
                    delivery[name.lower()] = {
                        "otif_pct": _num(row.get("otif_pct") or row.get("otif")),
                        "capacity_utilisation_pct": _num(row.get("capacity_utilisation_pct")),
                        "single_source": str(row.get("single_source", "")).lower()
                        in {"true", "yes", "1", "y"},
                    }
            feeds.append(attachment["filename"])

        observations.append(
            Observation("feed_ingest",
                        f"Ingested {len(feeds)} feed(s): {', '.join(feeds)}. "
                        f"{len(financials)} financial record(s), {len(delivery)} delivery record(s)."
                        if feeds else
                        "No external feeds attached — financial and operational domains scored on "
                        "what is on file, with the gaps reported.",
                        {"feeds": feeds, "financials": len(financials), "delivery": len(delivery)},
                        ok=bool(feeds))
        )

        # ---- Score ---------------------------------------------------------
        assessments = []
        for supplier in suppliers:
            key = supplier.name.lower()
            unpaid = db.execute(
                select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(
                    Invoice.supplier_id == supplier.id, Invoice.paid_at.is_(None))
            ).scalar_one() or 0.0
            result = strategic_risk.assess(
                {
                    "id": supplier.id, "name": supplier.name, "country": supplier.country,
                    "sanctions_status": supplier.sanctions_status,
                    "tax_form_status": supplier.tax_form_status,
                    "insurance_expiry": supplier.insurance_expiry,
                    "esg_disclosure": False,
                    "diverse_supplier": False,
                },
                financials=financials.get(key),
                delivery=delivery.get(key),
            )
            result["spend_at_risk_usd"] = round(float(unpaid), 2)
            result["annual_spend_usd"] = supplier.spend_ytd_usd
            assessments.append(result)

        assessments.sort(key=lambda a: a["overall_risk"], reverse=True)
        context["assessments"] = assessments
        elevated = [a for a in assessments if a["recommended_disposition"] in {"watchlist", "block"}]
        context["elevated"] = elevated

        average = round(sum(a["overall_risk"] for a in assessments) / max(1, len(assessments)), 1)
        context["average_risk"] = average
        observations.append(
            Observation("supplier_risk_assessment",
                        f"Scored {len(assessments)} supplier(s). Portfolio average risk {average:.1f} "
                        f"against a <20 target. {len(elevated)} at watchlist or block.",
                        [{"supplier": a["supplier_name"], "overall": a["overall_risk"],
                          "band": a["risk_band"], "disposition": a["recommended_disposition"]}
                         for a in assessments[:12]],
                        ok=average < 20 and not elevated)
        )
        observations.append(
            Observation("esg_scoring",
                        f"ESG exposure scored for {len(assessments)} supplier(s); "
                        f"{len([a for a in assessments if a['esg_risk'] >= 30])} carry elevated "
                        f"inherent exposure.",
                        [{"supplier": a["supplier_name"], "esg_risk": a["esg_risk"]}
                         for a in assessments if a["esg_risk"] >= 30][:8])
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        assessments = context.get("assessments", [])
        elevated = context.get("elevated", [])
        average = context.get("average_risk", 0.0)
        execution_id = context.get("_execution_id")

        if not assessments:
            return AgentDecision("No suppliers in scope.", 0.5,
                                 decision_rules=["Nothing to assess."], evidence=[])

        # Persist the scorecards so the portfolio view has something to read.
        for result in assessments:
            record = db.execute(
                select(RiskAssessment).where(RiskAssessment.supplier_id == result["supplier_id"])
            ).scalars().first()
            if record is None:
                record = RiskAssessment(supplier_id=result["supplier_id"])
                db.add(record)
            record.supplier_name = result["supplier_name"]
            record.financial_risk = result["financial_risk"]
            record.operational_risk = result["operational_risk"]
            record.compliance_risk = result["compliance_risk"]
            record.esg_risk = result["esg_risk"]
            record.overall_risk = result["overall_risk"]
            record.risk_band = result["risk_band"]
            record.findings = result["findings"]
            record.recommended_disposition = result["recommended_disposition"]
            record.spend_at_risk_usd = result["spend_at_risk_usd"]
            db.flush()
            result["_assessment_id"] = record.id

        evidence = [
            evidence_item("Suppliers scored", str(len(assessments)), "supplier_risk_assessment"),
            evidence_item("Portfolio average risk", f"{average:.1f} (target <20)",
                          "supplier_risk_assessment"),
            evidence_item("At watchlist or block", str(len(elevated)), "supplier_risk_assessment"),
            evidence_item("Spend at risk",
                          f"{sum(a['spend_at_risk_usd'] for a in elevated):,.2f} USD",
                          "supplier_risk_assessment"),
        ]
        for result in elevated[:4]:
            top = result["findings"][0]["detail"] if result["findings"] else "elevated composite score"
            evidence.append(evidence_item(result["supplier_name"], top, "supplier_risk_assessment"))

        rules = [
            "Domain weights: financial 30%, compliance 30%, operational 25%, ESG 15%.",
            "A compliance score at or above 70 forces a block recommendation on its own.",
            "Missing feeds are reported as findings — an absent signal is not a clean one.",
            "Disposition is a recommendation; approve/monitor/watchlist/block is a human call.",
        ]

        scorecard = artifact_service.to_csv([
            {"supplier": a["supplier_name"], "financial_risk": a["financial_risk"],
             "operational_risk": a["operational_risk"], "compliance_risk": a["compliance_risk"],
             "esg_risk": a["esg_risk"], "overall_risk": a["overall_risk"],
             "risk_band": a["risk_band"], "recommended_disposition": a["recommended_disposition"],
             "spend_at_risk_usd": a["spend_at_risk_usd"],
             "finding_count": len(a["findings"])}
            for a in assessments
        ])
        scorecard_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Supplier risk scorecard", filename="supplier-risk-scorecard.csv",
            content=scorecard, kind="scorecard",
            summary=f"{len(assessments)} suppliers, average {average:.1f}, {len(elevated)} elevated.",
            entity_type="supplier",
        )

        sections = []
        for result in assessments[:15]:
            findings = "\n".join(
                f"- **{f['domain']}** ({f['severity']}): {f['detail']}" for f in result["findings"]
            ) or "- No findings."
            sections.append(
                f"### {result['supplier_name']} — {result['overall_risk']:.0f} "
                f"({result['risk_band']})\n\n"
                f"Financial {result['financial_risk']:.0f} · Operational {result['operational_risk']:.0f} "
                f"· Compliance {result['compliance_risk']:.0f} · ESG {result['esg_risk']:.0f}\n\n"
                f"Recommended disposition: **{result['recommended_disposition']}**\n\n{findings}\n"
            )

        report = f"""# Supplier risk & compliance report

**Generated:** {date.today().isoformat()}
**Suppliers assessed:** {len(assessments)}
**Portfolio average risk:** {average:.1f} (target &lt;20)
**At watchlist or block:** {len(elevated)}

## Portfolio

{artifact_service.markdown_table(
    ["Supplier", "Overall", "Band", "Financial", "Operational", "Compliance", "ESG", "Disposition"],
    [[a["supplier_name"], f"{a['overall_risk']:.0f}", a["risk_band"],
      f"{a['financial_risk']:.0f}", f"{a['operational_risk']:.0f}",
      f"{a['compliance_risk']:.0f}", f"{a['esg_risk']:.0f}",
      a["recommended_disposition"]] for a in assessments]
)}

## Findings by supplier

{"".join(sections)}

## Method

Domain weights are financial 30%, compliance 30%, operational 25%, ESG 15%. A
compliance score of 70 or above forces a block recommendation regardless of the
composite. Where a feed is absent the domain records a finding rather than a
pass, so an unmeasured supplier never reads as a safe one.

---
*Prepared by the Supplier Risk & Compliance Agent. Dispositions require human approval.*
"""
        report_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=execution_id,
            title="Supplier risk report", filename="supplier-risk-report.md",
            content=report, kind="report",
            summary=f"Average {average:.1f}; {len(elevated)} supplier(s) need a disposition decision.",
            entity_type="supplier",
        )

        proposals: list[ProposedAction] = []
        for result in elevated[:6]:
            findings_text = "; ".join(f["detail"] for f in result["findings"][:3])
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.SET_SUPPLIER_DISPOSITION,
                    title=f"{result['supplier_name']} → {result['recommended_disposition']}",
                    summary=(
                        f"Overall risk {result['overall_risk']:.0f} ({result['risk_band']}). "
                        f"Financial {result['financial_risk']:.0f}, operational "
                        f"{result['operational_risk']:.0f}, compliance "
                        f"{result['compliance_risk']:.0f}, ESG {result['esg_risk']:.0f}. "
                        f"{findings_text}. Unpaid exposure {result['spend_at_risk_usd']:,.2f} USD."
                    ),
                    payload={
                        "assessment_id": result["_assessment_id"],
                        "disposition": result["recommended_disposition"],
                        "reason": findings_text,
                    },
                    diff_preview=[
                        {"field": "disposition", "label": "Disposition",
                         "before": "approve", "after": result["recommended_disposition"]},
                        {"field": "risk_score", "label": "Risk score",
                         "before": "—", "after": f"{result['overall_risk']:.0f}"},
                    ],
                    alternatives=[
                        {"option": disposition.title(),
                         "detail": {"approve": "Continue trading with no restriction.",
                                    "monitor": "Continue, review next cycle.",
                                    "watchlist": "Continue but no new commitments.",
                                    "block": "Stop new POs and freeze payment."}[disposition]}
                        for disposition in strategic_risk.DISPOSITIONS
                    ],
                    confidence=result["confidence"],
                    financial_impact_usd=result["spend_at_risk_usd"],
                    stage=WorkflowStage.VALIDATION,
                    entity_type="supplier", entity_id=result["supplier_id"],
                    entity_label=result["supplier_name"],
                    due_in_hours=12,
                    artifact_ids=[scorecard_artifact.id, report_artifact.id],
                    extra_flags=[result["risk_band"]],
                )
            )

        return AgentDecision(
            conclusion=(
                f"{len(assessments)} supplier(s) scored; portfolio average {average:.1f}. "
                f"{len(elevated)} need a disposition decision."
                if elevated else
                f"{len(assessments)} supplier(s) scored; portfolio average {average:.1f}. "
                f"No disposition change required."
            ),
            confidence=round(sum(a["confidence"] for a in assessments) / len(assessments), 4),
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=any(a["recommended_disposition"] == "block" for a in elevated),
            escalation_reason="A block recommendation is on the table." if any(
                a["recommended_disposition"] == "block" for a in elevated) else None,
        )


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0
