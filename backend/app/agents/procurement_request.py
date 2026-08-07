"""Agent 8 — Procurement Request.

Mission: triage intake requests against the approval policy ladder. Note that
even the "auto_approve" band still lands on a human checkpoint here: the policy
decides the *route*, governance decides whether anything executes unattended.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ActionKind, AutonomyLevel, RiskLevel, Role, WorkflowStage
from ..models import Contract, PurchaseRequest, Supplier
from ..services.policy import PolicyStore
from .base import AgentDecision, BaseAgent, Observation, PlanStep, ProposedAction, evidence_item, IOSpec


class ProcurementRequestAgent(BaseAgent):
    key = "procurement_request"
    name = "Procurement Request Agent"
    role = "Triages purchase requests against the spend-authority ladder."
    mission = "Route purchase requests to the right authority with the policy basis stated."
    goals = [
        "Apply the spend ladder consistently and visibly.",
        "Steer demand toward contracted, pre-negotiated suppliers.",
        "Keep requisition cycle time under one day.",
    ]
    tools = ["Purchase request queue", "Contract catalogue", "Preferred supplier list", "Budget policy"]
    skills = ["policy_routing", "contract_parsing", "supplier_lookup"]
    default_stage = WorkflowStage.INTAKE
    escalation_role = Role.PROCUREMENT
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.APPROVE_PURCHASE_REQUEST, ActionKind.CREATE_PURCHASE_REQUEST]

    inputs = [
        IOSpec("request_id", "The purchase request to triage.", kind="data", required=True),
        IOSpec("spend policy", "The authority ladder, read from policy-as-code.",
               kind="data", required=False, example="under 5k / under 10k / above 10k"),
    ]
    outputs = [
        IOSpec("Routing decision", "The policy band and the authority the request routes to.",
               kind="record"),
        IOSpec("Contract-cover note", "Whether the nominated supplier is on contract.", kind="record"),
        IOSpec("Checkpoint", "Approve the purchase request at the applicable authority.",
               kind="proposal"),
    ]


    def entity_ref(self, db: Session, context: dict):
        request = db.get(PurchaseRequest, context.get("request_id", ""))
        return ("purchase_request", request.id, request.request_number) if request else (None, None, None)

    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        return [
            PlanStep(1, "Read the request and its value", "request_lookup",
                     "Value determines which authority band applies."),
            PlanStep(2, "Apply the spend-authority policy ladder", "policy_routing",
                     "Under 5k / under 10k / above 10k routes differently."),
            PlanStep(3, "Check for an existing contract with this supplier", "contract_parsing",
                     "Contracted spend is cheaper and faster than new sourcing."),
            PlanStep(4, "Propose the routing decision for approval", "hitl_checkpoint",
                     "Committing spend is irreversible."),
        ]

    def gather(self, db: Session, context: dict) -> list[Observation]:
        request = db.get(PurchaseRequest, context.get("request_id", ""))
        if request is None:
            return [Observation("request_lookup", "Purchase request not found.", ok=False)]
        context["request"] = request

        store = PolicyStore(db)
        auto_under = store.number("procurement.auto_approve_under", 5000.0)
        manager_under = store.number("procurement.manager_review_under", 10000.0)
        context["bands"] = {"auto_under": auto_under, "manager_under": manager_under}

        amount = float(request.amount or 0.0)
        if amount < auto_under:
            band, target_role = "under_5000_usd → light-touch approval", Role.AP_MANAGER
        elif amount < manager_under:
            band, target_role = "under_10000_usd → manager review", Role.AP_MANAGER
        else:
            band, target_role = "above_10000_usd → procurement review", Role.PROCUREMENT
        context["band"], context["target_role"] = band, target_role

        observations = [
            Observation("request_lookup",
                        f"{request.request_number} · {request.currency} {amount:,.2f} · "
                        f"{request.category or 'uncategorised'} · requested by {request.requester_name}.",
                        {"amount": amount, "category": request.category}),
            Observation("policy_routing",
                        f"Policy band: {band}. Decision authority: {target_role}.",
                        {"band": band, "target_role": str(target_role),
                         "auto_under": auto_under, "manager_under": manager_under}),
        ]

        supplier = db.get(Supplier, request.supplier_id) if request.supplier_id else None
        contract = None
        if supplier is not None:
            contract = db.execute(
                select(Contract).where(Contract.supplier_id == supplier.id, Contract.status == "active")
            ).scalars().first()
        context["supplier"], context["contract"] = supplier, contract

        observations.append(
            Observation(
                "contract_parsing",
                f"Active contract {contract.contract_number} covers this supplier "
                f"(terms {contract.payment_terms}, expires {contract.end_date})."
                if contract else
                (f"{supplier.name} has no active contract — this would be off-contract spend."
                 if supplier else "No supplier nominated on the request."),
                {"contract_number": contract.contract_number if contract else None,
                 "supplier": supplier.name if supplier else None},
                ok=contract is not None,
            )
        )
        return observations

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        request: PurchaseRequest | None = context.get("request")
        if request is None:
            return AgentDecision("Purchase request not found.", 0.0, escalate=True)

        supplier: Supplier | None = context.get("supplier")
        contract: Contract | None = context.get("contract")
        bands = context.get("bands", {})
        band = context.get("band", "")
        target_role = context.get("target_role", Role.PROCUREMENT)
        amount = float(request.amount or 0.0)

        evidence = [
            evidence_item("Request value", f"{request.currency} {amount:,.2f}", "request_lookup"),
            evidence_item("Policy band", band, "policy_routing"),
            evidence_item("Supplier", supplier.name if supplier else "none nominated", "request_lookup"),
            evidence_item("Contract cover",
                          contract.contract_number if contract else "off-contract", "contract_parsing"),
        ]
        rules = [
            f"under_{bands.get('auto_under', 5000):.0f}_usd → light-touch approval.",
            f"under_{bands.get('manager_under', 10000):.0f}_usd → manager_review.",
            f"above_{bands.get('manager_under', 10000):.0f}_usd → procurement_review.",
            "Global HITL enforcement means even the light-touch band records an explicit approver.",
        ]
        notes: list[str] = [f"Routed by policy: {band}."]
        confidence = 0.95

        if contract is None and supplier is not None:
            notes.append(f"{supplier.name} is off-contract — Procurement should consider a contracted alternative.")
            confidence = 0.90
        if supplier is not None and supplier.on_hold:
            notes.append(f"{supplier.name} is currently blocked; this request cannot proceed as nominated.")
            confidence = 0.94

        return AgentDecision(
            conclusion=f"{request.request_number} ({request.currency} {amount:,.2f}) routes to "
                       f"{target_role} under the '{band}' band.",
            confidence=confidence,
            decision_rules=rules,
            evidence=evidence,
            proposals=[
                ProposedAction(
                    action_kind=ActionKind.APPROVE_PURCHASE_REQUEST,
                    title=f"Approve {request.request_number} ({band.split('→')[0].strip()})",
                    summary=" ".join(notes) + f" Description: {request.description}",
                    payload={
                        "request_id": request.id,
                        "routing_decision": band,
                        "policy_notes": " ".join(notes),
                    },
                    diff_preview=[{"field": "status", "label": "Request status",
                                   "before": request.status, "after": "approved"}],
                    alternatives=[
                        {"option": "Reject", "detail": "Send back to the requester with a reason."},
                        {"option": "Re-source", "detail": "Redirect to a contracted supplier."},
                    ],
                    confidence=confidence,
                    financial_impact_usd=amount,
                    stage=WorkflowStage.INTAKE,
                    entity_type="purchase_request", entity_id=request.id,
                    entity_label=request.request_number,
                    due_in_hours=12,
                    extra_flags=["off_contract"] if contract is None and supplier else [],
                )
            ],
            escalate=amount >= bands.get("manager_under", 10000.0),
            escalation_reason=f"Value {amount:,.2f} requires procurement review."
            if amount >= bands.get("manager_under", 10000.0) else None,
        )
