"""Procurement Agent 1 — Sourcing Event (RFP/RFQ).

Takes a requirements brief as an attachment, produces an issuable RFP package,
a supplier shortlist and a scored bid comparison, and recommends an award.
Issuing and awarding both reach outside the company, so both stop for a human.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AgentSuite, AutonomyLevel, EventType, Role, WorkflowStage
from ..models import SourcingBid, SourcingEvent, Supplier, utcnow
from ..services import artifacts as artifact_service
from ..skills import sourcing
from .base import (
    AgentDecision,
    BaseAgent,
    IOSpec,
    Observation,
    PlanStep,
    ProposedAction,
    evidence_item,
)


class SourcingEventAgent(BaseAgent):
    key = "sourcing_rfp"
    name = "Sourcing Event Agent"
    suite = AgentSuite.PROCUREMENT
    role = "Runs RFP/RFQ events from requirements brief to award recommendation."
    mission = "Compress sourcing cycle time without losing competitive tension or auditability."
    goals = [
        "Cut sourcing cycle time by 50-80% against the 4-12 week baseline.",
        "Keep bid participation above 80% by shortlisting suppliers that actually fit.",
        "Make every award reproducible from the published evaluation weights.",
    ]
    tools = ["Requirements brief", "Vendor master", "Bid responses", "Category strategy", "Risk screening"]
    skills = ["rfp_orchestration", "supplier_discovery", "bid_evaluation"]
    default_stage = WorkflowStage.INTAKE
    escalation_role = Role.PROCUREMENT
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.92
    allowed_actions = [ActionKind.ISSUE_RFP, ActionKind.AWARD_SOURCING_EVENT]

    inputs = [
        IOSpec("requirements_brief", "Business requirements document describing scope, volume, "
                                     "term, budget and service levels.",
               kind="attachment", formats=["md", "txt", "csv", "json"], required=False,
               example="requirements-logistics-2026.md"),
        IOSpec("bid_responses", "Supplier bid responses to score, one row per supplier.",
               kind="attachment", formats=["csv", "json"], required=False,
               example="bids-SRC-9001.csv → supplier_name,bid_amount_usd,lead_time_days,technical_score"),
        IOSpec("event_id", "Existing sourcing event to progress. Omit to draft a new one.",
               kind="data", required=False, example="event_id=<uuid>"),
        IOSpec("category / budget / compliance_rules",
               "Category, indicative budget and mandatory compliance rules.",
               kind="data", required=False, example='{"category": "Freight & Logistics", "budget": 850000}'),
    ]
    outputs = [
        IOSpec("RFP package", "Issuable RFP document with scope, compliance, response format "
                              "and published evaluation weights.",
               kind="artifact", formats=["md"], example="RFP-SRC-9001.md"),
        IOSpec("Supplier shortlist", "Ranked candidates with fit score, rationale and exclusions.",
               kind="artifact", formats=["csv"], example="shortlist-SRC-9001.csv"),
        IOSpec("Bid scorecard", "Every bid scored on commercial, technical and risk components.",
               kind="artifact", formats=["csv"], example="scorecard-SRC-9001.csv"),
        IOSpec("Award recommendation", "Winner, margin over runner-up, expected savings, confidence.",
               kind="artifact", formats=["json"], example='{"recommended_supplier": "...", "expected_savings": "$1.4M"}'),
        IOSpec("Checkpoint", "Issue RFP / Award event — both require Procurement approval.",
               kind="proposal"),
    ]

    def entity_ref(self, db: Session, context: dict):
        event = db.get(SourcingEvent, context.get("event_id", "")) if context.get("event_id") else None
        return ("sourcing_event", event.id, event.event_number) if event else \
               ("sourcing_event", None, "New sourcing event")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Read the requirements brief", "rfp_orchestration",
                     "Structured parameters are what make the RFP specific enough to bid against."),
            PlanStep(2, "Shortlist qualified suppliers", "supplier_discovery",
                     "Compliance is a gate, not a weighting — blocked suppliers never make the list."),
            PlanStep(3, "Generate the RFP package", "rfp_orchestration",
                     "Publishing the weights up front is what makes the award defensible."),
            PlanStep(4, "Score any bids received", "bid_evaluation",
                     "Commercial, technical and risk components are shown separately."),
            PlanStep(5, "Recommend an award for approval", "hitl_checkpoint",
                     "Issuing and awarding both reach a supplier — a person owns each."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        observations: list[Observation] = []
        event = db.get(SourcingEvent, context.get("event_id", "")) if context.get("event_id") else None
        context["event"] = event

        # ---- 1. Requirements, from an attachment when supplied -----------
        brief_text = context.get("requirements") or (event.requirements if event else "")
        source = "event record"
        for attachment in context.get("attachments", []):
            if attachment["format"] in {"text", "pdf_text"} or attachment["filename"].endswith((".md", ".txt")):
                brief_text = attachment["text"]
                source = attachment["filename"]
                break
        analysis = sourcing.analyze_requirements(brief_text)
        context["analysis"], context["brief_text"] = analysis, brief_text
        observations.append(
            Observation(
                "rfp_orchestration",
                f"Read {source}: {analysis['requirement_count']} requirement(s), "
                f"parameters {list(analysis['parameters'])}, "
                f"completeness {analysis['completeness']:.0%}."
                + (f" Missing: {', '.join(analysis['missing_parameters'])}."
                   if analysis["missing_parameters"] else ""),
                analysis,
                ok=not analysis["requires_human_review"],
            )
        )

        category = context.get("category") or (event.category if event else "") or "General"
        budget = float(context.get("budget") or (event.budget_usd if event else 0.0)
                       or analysis["parameters"].get("budget") or 0.0)
        context["category"], context["budget"] = category, budget

        # ---- 2. Supplier discovery ---------------------------------------
        candidates = [
            {
                "id": s.id, "name": s.name, "legal_name": s.legal_name, "category": s.category,
                "tier": s.tier, "on_hold": s.on_hold, "sanctions_status": s.sanctions_status,
                "risk_score": s.risk_score, "spend_ytd_usd": s.spend_ytd_usd,
            }
            for s in db.execute(select(Supplier)).scalars().all()
        ]
        discovery = sourcing.shortlist_suppliers(candidates, category=category)
        context["discovery"] = discovery
        observations.append(
            Observation(
                "supplier_discovery",
                f"Shortlisted {len(discovery['shortlist'])} of {discovery['considered']} suppliers "
                f"for {category}; {len(discovery['excluded'])} excluded on compliance.",
                discovery,
                ok=len(discovery["shortlist"]) >= 3,
            )
        )

        # ---- 3. Bids: from an attachment, or already on the event --------
        bids: list[dict] = []
        bid_source = None
        for attachment in context.get("attachments", []):
            if attachment["format"] in {"csv", "json"} and any(
                f in " ".join(attachment["fields"]).lower() for f in ("bid", "amount", "supplier")
            ):
                for row in attachment["rows"]:
                    bids.append({
                        "supplier_name": row.get("supplier_name") or row.get("supplier") or "",
                        "bid_amount_usd": _num(row.get("bid_amount_usd") or row.get("amount")),
                        "lead_time_days": _num(row.get("lead_time_days") or row.get("lead_time")),
                        "technical_score": _num(row.get("technical_score") or row.get("technical")),
                        "risk_score": _num(row.get("risk_score") or row.get("risk")),
                    })
                bid_source = attachment["filename"]
                break

        if not bids and event is not None:
            bids = [
                {"id": b.id, "supplier_id": b.supplier_id, "supplier_name": b.supplier_name,
                 "bid_amount_usd": b.bid_amount_usd, "lead_time_days": b.lead_time_days,
                 "technical_score": b.technical_score, "risk_score": b.risk_score}
                for b in event.bids
            ]
            bid_source = "event record" if bids else None

        context["bids"] = bids
        if bids:
            evaluation = sourcing.score_bids(
                bids,
                budget=budget,
                weights=(event.weighting if event and event.weighting else None),
                incumbent_spend=(event.incumbent_spend_usd if event else 0.0),
            )
            context["evaluation"] = evaluation
            observations.append(
                Observation(
                    "bid_evaluation",
                    f"Scored {len(bids)} bid(s) from {bid_source}. Leader "
                    f"{evaluation['winner']['supplier_name']} at "
                    f"{evaluation['winner']['total_score']:.1f}"
                    + (f", margin {evaluation['margin']:.1f} over runner-up."
                       if evaluation["margin"] is not None else " (sole bid).")
                    + f" Expected savings {evaluation['expected_savings_usd']:,.0f} USD.",
                    evaluation,
                    ok=not evaluation["close_call"],
                )
            )
        else:
            observations.append(
                Observation("bid_evaluation", "No bids available yet — this is a pre-issue run.",
                            {"bids": 0})
            )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        event: SourcingEvent | None = context.get("event")
        analysis = context.get("analysis", {})
        discovery = context.get("discovery", {})
        evaluation = context.get("evaluation")
        category = context.get("category", "General")
        budget = float(context.get("budget") or 0.0)

        evidence = [
            evidence_item("Category", category, "rfp_orchestration"),
            evidence_item("Budget", f"{budget:,.2f} USD", "rfp_orchestration"),
            evidence_item("Requirements parsed", str(analysis.get("requirement_count", 0)),
                          "rfp_orchestration"),
            evidence_item("Shortlisted suppliers", str(len(discovery.get("shortlist", []))),
                          "supplier_discovery"),
            evidence_item("Excluded on compliance", str(len(discovery.get("excluded", []))),
                          "supplier_discovery"),
        ]
        rules: list[str] = []
        proposals: list[ProposedAction] = []

        # ================= Award path =====================================
        if evaluation and evaluation.get("winner"):
            winner = evaluation["winner"]
            rules.append(f"Weights applied: {evaluation['weights']}.")
            rules.append("Award always requires Procurement sign-off, whatever the score.")
            if evaluation["close_call"]:
                rules.append(f"Margin of {evaluation['margin']:.1f} points is inside the 4-point "
                             f"band — treated as a judgement call, not a clear winner.")

            scorecard = artifact_service.to_csv([
                {
                    "supplier": b["supplier_name"],
                    "bid_amount_usd": b.get("bid_amount_usd"),
                    "lead_time_days": b.get("lead_time_days"),
                    "commercial_score": b["commercial_score"],
                    "technical_score": b["technical_score"],
                    "risk_component": b["risk_component"],
                    "total_score": b["total_score"],
                    "over_budget": b["over_budget"],
                    "flags": "; ".join(b.get("compliance_flags") or []),
                }
                for b in evaluation["scored"]
            ])
            label = event.event_number if event else "SRC"
            scorecard_artifact = artifact_service.produce_output(
                db, agent_key=self.key, execution_id=context.get("_execution_id"),
                title=f"Bid scorecard · {label}", filename=f"scorecard-{label}.csv",
                content=scorecard, kind="scorecard",
                summary=f"{len(evaluation['scored'])} bids scored on published weights.",
                entity_type="sourcing_event", entity_id=event.id if event else None,
            )
            recommendation = artifact_service.to_json({
                "recommended_supplier": winner["supplier_name"],
                "bid_amount_usd": winner.get("bid_amount_usd"),
                "total_score": winner["total_score"],
                "runner_up": evaluation["runner_up"]["supplier_name"] if evaluation["runner_up"] else None,
                "margin": evaluation["margin"],
                "expected_savings_usd": evaluation["expected_savings_usd"],
                "expected_savings_pct": evaluation["savings_pct"],
                "weights": evaluation["weights"],
                "confidence": evaluation["confidence"],
                "compliance_flags": winner.get("compliance_flags", []),
            })
            recommendation_artifact = artifact_service.produce_output(
                db, agent_key=self.key, execution_id=context.get("_execution_id"),
                title=f"Award recommendation · {label}",
                filename=f"award-recommendation-{label}.json",
                content=recommendation, kind="recommendation",
                summary=f"{winner['supplier_name']} recommended; "
                        f"{evaluation['expected_savings_usd']:,.0f} USD expected savings.",
                entity_type="sourcing_event", entity_id=event.id if event else None,
            )

            evidence.append(evidence_item("Winning score", f"{winner['total_score']:.1f}", "bid_evaluation"))
            evidence.append(evidence_item("Expected savings",
                                          f"{evaluation['expected_savings_usd']:,.2f} USD "
                                          f"({evaluation['savings_pct']:.1f}%)", "bid_evaluation"))

            if event is not None:
                bid_row = next((b for b in event.bids if b.supplier_name == winner["supplier_name"]), None)
                proposals.append(
                    ProposedAction(
                        action_kind=ActionKind.AWARD_SOURCING_EVENT,
                        title=f"Award {event.event_number} to {winner['supplier_name']}",
                        summary=(
                            f"{winner['supplier_name']} scores {winner['total_score']:.1f} on the "
                            f"published weights"
                            + (f", {evaluation['margin']:.1f} ahead of "
                               f"{evaluation['runner_up']['supplier_name']}"
                               if evaluation["runner_up"] else " as the sole compliant bid")
                            + f". Bid {winner.get('bid_amount_usd', 0):,.2f} USD against a "
                              f"{budget:,.2f} USD budget; expected savings "
                              f"{evaluation['expected_savings_usd']:,.2f} USD."
                            + (" Winner carries compliance flags: "
                               + "; ".join(winner["compliance_flags"]) + "."
                               if winner.get("compliance_flags") else "")
                        ),
                        payload={
                            "event_id": event.id,
                            "bid_id": bid_row.id if bid_row else None,
                            "expected_savings_usd": evaluation["expected_savings_usd"],
                        },
                        diff_preview=[
                            {"field": "status", "label": "Event status",
                             "before": event.status, "after": "awarded"},
                            {"field": "supplier", "label": "Awarded supplier",
                             "before": "—", "after": winner["supplier_name"]},
                        ],
                        alternatives=[
                            {"option": b["supplier_name"],
                             "detail": f"score {b['total_score']:.1f} · "
                                       f"{b.get('bid_amount_usd', 0):,.0f} USD",
                             "impact_usd": float(b.get("bid_amount_usd") or 0.0)}
                            for b in evaluation["scored"][:4]
                        ],
                        confidence=evaluation["confidence"],
                        financial_impact_usd=float(winner.get("bid_amount_usd") or 0.0),
                        stage=WorkflowStage.APPROVAL,
                        entity_type="sourcing_event", entity_id=event.id,
                        entity_label=event.event_number,
                        due_in_hours=24,
                        artifact_ids=[scorecard_artifact.id, recommendation_artifact.id],
                        extra_flags=["close_call"] if evaluation["close_call"] else [],
                    )
                )

            return AgentDecision(
                conclusion=f"Recommend awarding to {winner['supplier_name']} — "
                           f"{evaluation['expected_savings_usd']:,.0f} USD expected savings at "
                           f"{evaluation['confidence']:.0%} confidence.",
                confidence=evaluation["confidence"],
                decision_rules=rules,
                evidence=evidence,
                proposals=proposals,
                escalate=evaluation["close_call"] or bool(winner.get("compliance_flags")),
                escalation_reason="Narrow margin or compliance flags on the leading bid."
                if evaluation["close_call"] or winner.get("compliance_flags") else None,
            )

        # ================= Issue path =====================================
        if not discovery.get("shortlist"):
            return AgentDecision(
                conclusion=f"No qualified suppliers for {category} — sourcing cannot proceed.",
                confidence=0.5, decision_rules=["Shortlist is empty after the compliance gate."],
                evidence=evidence, escalate=True,
                escalation_reason="No compliant suppliers available in this category.",
            )

        if event is None:
            count = db.execute(select(func.count(SourcingEvent.id))).scalar_one() or 0
            event = SourcingEvent(
                event_number=f"SRC-{count + 9001}",
                title=context.get("title") or f"{category} sourcing event",
                category=category,
                event_type=context.get("event_type", "RFP"),
                budget_usd=budget,
                requirements=context.get("brief_text", ""),
                compliance_rules=context.get("compliance_rules") or [],
                weighting=sourcing.DEFAULT_WEIGHTS,
                status="draft",
                response_due=date.today() + timedelta(days=14),
            )
            db.add(event)
            db.flush()
            context["event"] = event
            rules.append("No event existed — a draft event record was created to hold the package.")

        rfp = sourcing.rfp_document(
            event_title=event.title, category=category, budget=budget,
            requirements=analysis.get("requirements", []),
            compliance_rules=event.compliance_rules or [],
            response_due=event.response_due, weights=event.weighting,
            event_number=event.event_number,
        )
        rfp_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=context.get("_execution_id"),
            title=f"RFP package · {event.event_number}",
            filename=f"RFP-{event.event_number}.md", content=rfp, kind="rfp_package",
            summary=f"{analysis.get('requirement_count', 0)} requirements, "
                    f"{len(discovery['shortlist'])} suppliers, {budget:,.0f} USD budget.",
            entity_type="sourcing_event", entity_id=event.id,
        )
        shortlist_csv = artifact_service.to_csv([
            {"supplier": s["name"], "tier": s["tier"], "category": s.get("category"),
             "fit_score": s["fit_score"], "risk_score": s.get("risk_score"),
             "rationale": s["rationale"]}
            for s in discovery["shortlist"]
        ])
        shortlist_artifact = artifact_service.produce_output(
            db, agent_key=self.key, execution_id=context.get("_execution_id"),
            title=f"Supplier shortlist · {event.event_number}",
            filename=f"shortlist-{event.event_number}.csv", content=shortlist_csv, kind="shortlist",
            summary=f"{len(discovery['shortlist'])} shortlisted, "
                    f"{len(discovery['excluded'])} excluded on compliance.",
            entity_type="sourcing_event", entity_id=event.id,
        )

        confidence = round(0.55 + 0.40 * analysis.get("completeness", 0.0), 4)
        rules.append(f"Requirements completeness {analysis.get('completeness', 0):.0%} drives confidence.")
        rules.append("Issuing an RFP is outward-facing and irreversible — always a human decision.")
        if analysis.get("missing_parameters"):
            rules.append(f"Missing {', '.join(analysis['missing_parameters'])} — the reviewer should "
                         f"confirm before this goes to suppliers.")

        invited = [s["name"] for s in discovery["shortlist"]]
        baseline = event.baseline_cycle_days or 56.0
        proposals.append(
            ProposedAction(
                action_kind=ActionKind.ISSUE_RFP,
                title=f"Issue {event.event_number} to {len(invited)} suppliers",
                summary=(
                    f"RFP package ready for {event.title} ({category}, {budget:,.0f} USD budget) "
                    f"with {analysis.get('requirement_count', 0)} requirements and published "
                    f"weights. Shortlist: {', '.join(invited)}. "
                    f"{len(discovery['excluded'])} supplier(s) excluded on compliance. "
                    f"Responses due {event.response_due}. Drafted in one run against a "
                    f"{baseline:.0f}-day manual baseline."
                ),
                payload={
                    "event_id": event.id,
                    "invited_suppliers": invited,
                    "response_due": event.response_due.isoformat() if event.response_due else None,
                },
                diff_preview=[
                    {"field": "status", "label": "Event status", "before": event.status, "after": "issued"},
                    {"field": "invited", "label": "Suppliers invited", "before": "0",
                     "after": str(len(invited))},
                ],
                alternatives=[
                    {"option": "Issue to the top 3 only",
                     "detail": "Narrower field, faster evaluation, less price tension."},
                    {"option": "Add an incumbent not on the shortlist",
                     "detail": "Requires a documented reason if they failed the compliance gate."},
                ],
                confidence=confidence,
                # Issuing an RFP invites bids; it commits nothing. The award is
                # where money is committed, so that is where the value-based
                # authority ladder applies.
                financial_impact_usd=0.0,
                stage=WorkflowStage.INTAKE,
                entity_type="sourcing_event", entity_id=event.id, entity_label=event.event_number,
                due_in_hours=24,
                artifact_ids=[rfp_artifact.id, shortlist_artifact.id],
            )
        )

        return AgentDecision(
            conclusion=f"{event.event_number} package prepared for {len(invited)} suppliers; "
                       f"awaiting Procurement approval to issue.",
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=analysis.get("completeness", 1.0) < 0.67,
            escalation_reason="Requirements brief is incomplete." if analysis.get("completeness", 1) < 0.67 else None,
        )


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0
