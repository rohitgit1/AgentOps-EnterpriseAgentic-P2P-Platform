"""Agent 10 — SLA Command Center.

Mission: forecast SLA breaches across the whole portfolio, rebalance workload,
and raise executive alerts with the number attached.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import (
    ActionKind,
    ApprovalStatus,
    AutonomyLevel,
    InvoiceStatus,
    RiskLevel,
    Role,
    SLAStatus,
    WorkflowStage,
)
from ..models import Approval, Invoice, SLARisk, User, utcnow
from ..services.policy import PolicyStore
from ..skills import sla_prediction
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec

TERMINAL_STATUSES = {InvoiceStatus.PAID, InvoiceStatus.REJECTED, InvoiceStatus.CANCELLED}


class SLACommandCenterAgent(BaseAgent):
    key = "sla_command_center"
    name = "SLA Command Center Agent"
    role = "Forecasts portfolio-wide SLA risk and proposes the intervention that protects it."
    mission = "Predict SLA breaches early enough that a human can still prevent them."
    goals = [
        "Hold SLA compliance above 99%.",
        "Redistribute workload before a queue becomes the bottleneck.",
        "Give executives a number, not an anecdote.",
    ]
    tools = ["Invoice portfolio", "Approval queues", "Workload model", "Executive alerting"]
    skills = ["sla_prediction", "workload_balancing", "forecasting"]
    default_stage = WorkflowStage.APPROVAL
    escalation_role = Role.CONTROLLER
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.88
    allowed_actions = [ActionKind.REBALANCE_WORKLOAD, ActionKind.RAISE_EXECUTIVE_ALERT,
                       ActionKind.ESCALATE_APPROVAL]

    inputs = [
        IOSpec("in-flight portfolio", "Every open invoice, its stage, approver and exceptions.",
               kind="data", required=False),
        IOSpec("SLA policy", "Cycle target and thresholds, read from policy-as-code.",
               kind="data", required=False),
    ]
    outputs = [
        IOSpec("Risk register", "Per-invoice breach forecast with the drivers and hours remaining.",
               kind="record"),
        IOSpec("Workload analysis", "Queue depth per approver and the rebalancing moves available.",
               kind="record"),
        IOSpec("Checkpoint", "Rebalance workload / escalate / raise an executive alert.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        return ("sla", None, "SLA Command Center")

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Sweep every in-flight invoice", "portfolio_scan",
                     "SLA is a portfolio property, not a per-invoice one."),
            PlanStep(2, "Forecast breach risk per invoice", "sla_prediction",
                     "Risk must be quantified before it can be triaged."),
            PlanStep(3, "Measure queue depth per approver", "workload_balancing",
                     "Most breaches are a queue problem, not an effort problem."),
            PlanStep(4, "Compose the intervention set", "forecasting",
                     "Rebalancing is cheaper than escalating."),
            PlanStep(5, "Submit interventions for approval", "hitl_checkpoint",
                     "Reassigning someone's work is a management decision."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        store = PolicyStore(db)
        target_hours = store.number("sla.invoice_cycle_hours", 24)
        context["target_hours"] = target_hours

        invoices = db.execute(
            select(Invoice).where(Invoice.status.notin_(list(TERMINAL_STATUSES)))
        ).scalars().all()

        forecasts: list[dict] = []
        for invoice in invoices:
            approver = db.get(User, invoice.approver_id) if invoice.approver_id else None
            open_exceptions = len([
                e for e in invoice.exceptions if e.status not in {"resolved", "written_off"}
            ])
            prediction = sla_prediction.predict(
                stage=invoice.stage,
                received_at=invoice.received_at,
                sla_target_hours=target_hours,
                open_exceptions=open_exceptions,
                approver_out_of_office=bool(approver and approver.out_of_office),
                approver_workload=(approver.active_workload if approver else 0) or 0,
                supplier_risk_level=invoice.supplier.risk_level if invoice.supplier else RiskLevel.LOW,
                on_hold=invoice.on_hold,
            )
            forecasts.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "stage": invoice.stage,
                "amount": float(invoice.total_amount or 0.0),
                "supplier": invoice.supplier.name if invoice.supplier else None,
                "approver": approver.full_name if approver else None,
                "approver_id": approver.id if approver else None,
                **prediction,
            })
            # Persist the forecast so the dashboard and the invoice card agree.
            invoice.sla_risk_score = prediction["risk_score"]
            invoice.sla_status = (
                SLAStatus.BREACHED if prediction["hours_remaining"] <= 0
                else SLAStatus.AT_RISK if prediction["risk_level"] in {RiskLevel.HIGH, RiskLevel.CRITICAL}
                else SLAStatus.ON_TRACK
            )
            invoice.sla_due_at = invoice.received_at + timedelta(hours=target_hours)

        forecasts.sort(key=lambda f: f["risk_score"], reverse=True)
        context["forecasts"] = forecasts

        at_risk = [f for f in forecasts if f["risk_level"] in {RiskLevel.HIGH, RiskLevel.CRITICAL}]
        breached = [f for f in forecasts if f["hours_remaining"] <= 0]
        context["at_risk"], context["breached"] = at_risk, breached

        observations = [
            Observation("portfolio_scan", f"{len(invoices)} invoice(s) in flight.", {"count": len(invoices)}),
            Observation(
                "sla_prediction",
                f"{len(at_risk)} at risk, {len(breached)} already past deadline. "
                f"Portfolio compliance forecast: "
                f"{(1 - len(breached) / max(1, len(invoices))) * 100:.1f}%.",
                {"at_risk": at_risk[:10], "breached": len(breached)},
                ok=not at_risk,
            ),
        ]

        # Queue depth per approver.
        pending = db.execute(
            select(Approval).where(Approval.status.in_([ApprovalStatus.PENDING, ApprovalStatus.DELEGATED]))
        ).scalars().all()
        queues: dict[str, list[Approval]] = {}
        for approval in pending:
            queues.setdefault(approval.approver_id or "unassigned", []).append(approval)

        depths = []
        for user_id, items in queues.items():
            user = db.get(User, user_id) if user_id != "unassigned" else None
            depths.append({
                "user_id": user_id,
                "name": user.full_name if user else "Unassigned",
                "role": user.role if user else None,
                "limit": user.approval_limit_usd if user else 0.0,
                "out_of_office": bool(user and user.out_of_office),
                "depth": len(items),
                "approval_ids": [a.id for a in items],
            })
        depths.sort(key=lambda d: d["depth"], reverse=True)
        context["queues"] = depths
        observations.append(
            Observation(
                "workload_balancing",
                f"Deepest queue: {depths[0]['name']} with {depths[0]['depth']} item(s)."
                if depths else "No open approval queues.",
                depths,
                ok=not depths or depths[0]["depth"] < 8,
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        forecasts = context.get("forecasts", [])
        at_risk = context.get("at_risk", [])
        breached = context.get("breached", [])
        queues = context.get("queues", [])
        target_hours = context.get("target_hours", 24)

        total = max(1, len(forecasts))
        compliance = round((1 - len(breached) / total) * 100, 2)
        exposure = round(sum(f["amount"] for f in at_risk), 2)

        evidence = [
            evidence_item("In-flight invoices", str(len(forecasts)), "portfolio_scan"),
            evidence_item("Forecast compliance", f"{compliance:.1f}% against a 99% target", "sla_prediction"),
            evidence_item("At-risk value", f"{exposure:,.2f}", "sla_prediction"),
            evidence_item("Breached", str(len(breached)), "sla_prediction"),
            evidence_item("SLA target", f"{target_hours:.0f}h receipt-to-posted", "policy"),
        ]
        rules = [
            "Rebalancing is attempted before escalation — it costs nobody authority.",
            "An executive alert fires only when forecast compliance drops below the 99% target.",
            "Every intervention is proposed, never applied silently.",
        ]
        proposals: list[ProposedAction] = []

        # --- Workload rebalancing ----------------------------------------
        if queues:
            overloaded = [q for q in queues if q["depth"] >= 6 or q["out_of_office"]]
            receivers = [q for q in queues if q["depth"] <= 2 and not q["out_of_office"] and q["user_id"] != "unassigned"]
            if not receivers:
                candidates = db.execute(
                    select(User).where(User.is_active.is_(True), User.out_of_office.is_(False))
                ).scalars().all()
                busy_ids = {q["user_id"] for q in queues}
                receivers = [
                    {"user_id": u.id, "name": u.full_name, "depth": u.active_workload or 0,
                     "limit": u.approval_limit_usd, "role": u.role}
                    for u in candidates
                    if u.id not in busy_ids and u.approval_limit_usd > 0
                ]

            moves: list[dict] = []
            for source in overloaded:
                movable = source["approval_ids"][2:] if not source["out_of_office"] else source["approval_ids"]
                for index, approval_id in enumerate(movable[:4]):
                    if not receivers:
                        break
                    target = receivers[index % len(receivers)]
                    approval = db.get(Approval, approval_id)
                    invoice = db.get(Invoice, approval.invoice_id) if approval else None
                    if invoice is None:
                        continue
                    if (target.get("limit") or 0) < float(invoice.total_amount or 0.0):
                        continue
                    moves.append({
                        "approval_id": approval_id,
                        "to_user_id": target["user_id"],
                        "from": source["name"],
                        "to": target["name"],
                        "invoice_number": invoice.invoice_number,
                        "amount": float(invoice.total_amount or 0.0),
                    })

            if moves:
                rules.append(f"{len(moves)} approval(s) can move from a deep queue to an idle one within limits.")
                proposals.append(
                    ProposedAction(
                        action_kind=ActionKind.REBALANCE_WORKLOAD,
                        title=f"Rebalance {len(moves)} approval(s) across the queue",
                        summary="; ".join(
                            f"{m['invoice_number']} {m['from']} → {m['to']}" for m in moves[:5]
                        ),
                        payload={"moves": moves},
                        diff_preview=[
                            {"field": m["invoice_number"], "label": "Approver",
                             "before": m["from"], "after": m["to"]}
                            for m in moves[:6]
                        ],
                        confidence=0.92,
                        financial_impact_usd=round(sum(m["amount"] for m in moves), 2),
                        stage=WorkflowStage.APPROVAL,
                        entity_type="workload", entity_id=None, entity_label="Approval queue",
                        due_in_hours=6,
                    )
                )

        # --- Critical individual escalations ------------------------------
        for item in [f for f in forecasts if f["risk_level"] == RiskLevel.CRITICAL][:3]:
            approval = db.execute(
                select(Approval).where(
                    Approval.invoice_id == item["invoice_id"],
                    Approval.status.in_([ApprovalStatus.PENDING, ApprovalStatus.DELEGATED]),
                )
            ).scalars().first()
            if approval is None:
                continue
            controller = db.execute(
                select(User).where(User.role == Role.CONTROLLER, User.out_of_office.is_(False))
            ).scalars().first()
            if controller is None:
                continue
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.ESCALATE_APPROVAL,
                    title=f"Escalate {item['invoice_number']} to {controller.full_name}",
                    summary=f"Risk {item['risk_score']:.0f}/100 · {item['hours_remaining']:.1f}h remaining "
                            f"against {item['estimated_effort_hours']:.1f}h of remaining work. "
                            f"{item['recommended_action']}",
                    payload={
                        "approval_id": approval.id,
                        "escalate_to_id": controller.id,
                        "due_in_hours": 4,
                        "reason": f"SLA forecast risk {item['risk_score']:.0f}/100.",
                        "message": f"SLA-critical: {item['invoice_number']} "
                                   f"({item['amount']:,.2f}) needs a decision today.",
                    },
                    confidence=0.9,
                    financial_impact_usd=item["amount"],
                    stage=WorkflowStage.APPROVAL,
                    entity_type="invoice", entity_id=item["invoice_id"],
                    entity_label=item["invoice_number"],
                    due_in_hours=2,
                )
            )

        # --- Executive alert ----------------------------------------------
        if compliance < 99.0 or len(breached) > 0:
            top = ", ".join(f"{f['invoice_number']} ({f['risk_score']:.0f})" for f in at_risk[:5])
            rules.append(f"Forecast compliance {compliance:.1f}% is below the 99% target → executive alert.")
            proposals.append(
                ProposedAction(
                    action_kind=ActionKind.RAISE_EXECUTIVE_ALERT,
                    title=f"Executive alert · SLA compliance forecast {compliance:.1f}%",
                    summary=(
                        f"{len(at_risk)} invoice(s) worth {exposure:,.2f} are at risk and "
                        f"{len(breached)} have already breached. Highest risk: {top or 'n/a'}."
                    ),
                    payload={
                        "title": f"SLA compliance forecast {compliance:.1f}%",
                        "body": (
                            f"{len(at_risk)} at-risk invoices ({exposure:,.2f} exposure), "
                            f"{len(breached)} breached. Primary drivers: "
                            + "; ".join(
                                d["driver"] for f in at_risk[:3] for d in f.get("drivers", [])[:2]
                            )
                        ),
                        "target_role": Role.CFO,
                    },
                    confidence=0.94,
                    financial_impact_usd=exposure,
                    stage=WorkflowStage.APPROVAL,
                    entity_type="sla", entity_id=None, entity_label="SLA Command Center",
                    due_in_hours=4,
                )
            )

        # Persist the risk register so the dashboard can render it.
        db.query(SLARisk).delete()
        for item in at_risk[:50]:
            db.add(SLARisk(
                invoice_id=item["invoice_id"],
                entity_label=item["invoice_number"],
                stage=item["stage"],
                risk_score=item["risk_score"],
                risk_level=item["risk_level"],
                hours_remaining=item["hours_remaining"],
                drivers=item.get("drivers", []),
                recommended_action=item.get("recommended_action"),
                status=SLAStatus.BREACHED if item["hours_remaining"] <= 0 else SLAStatus.AT_RISK,
            ))

        if not proposals:
            return AgentDecision(
                conclusion=f"Portfolio SLA compliance forecast {compliance:.1f}% — no intervention needed.",
                confidence=0.95, decision_rules=rules, evidence=evidence,
            )

        return AgentDecision(
            conclusion=(
                f"SLA forecast {compliance:.1f}% with {exposure:,.2f} at risk; "
                f"{len(proposals)} intervention(s) proposed."
            ),
            confidence=0.93,
            decision_rules=rules,
            evidence=evidence,
            proposals=proposals,
            escalate=compliance < 95.0,
            escalation_reason=f"Forecast compliance {compliance:.1f}% is materially below target."
            if compliance < 95.0 else None,
        )
