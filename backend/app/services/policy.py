"""Policy engine — the guardrail layer between an agent's intent and reality.

Every proposed action passes through `evaluate()`. The result decides whether
the action may auto-execute or must stop at a human checkpoint, and records the
reasons either way so the decision is explainable in an audit.

The default posture is deny: an action auto-executes only if EVERY gate opens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..enums import (
    ACTION_MIN_ROLE,
    IRREVERSIBLE_ACTIONS,
    ROLE_AUTHORITY,
    ActionKind,
    AutonomyLevel,
    RiskLevel,
    Role,
)
from ..models import AgentConfig, PolicyRule


@dataclass
class PolicyDecision:
    allow_auto_execute: bool
    requires_human: bool
    required_role: str
    risk_level: str
    reversible: bool
    dual_approval_required: bool
    reasons: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allow_auto_execute": self.allow_auto_execute,
            "requires_human": self.requires_human,
            "required_role": str(self.required_role),
            "risk_level": str(self.risk_level),
            "reversible": self.reversible,
            "dual_approval_required": self.dual_approval_required,
            "reasons": self.reasons,
            "blocked_reasons": self.blocked_reasons,
            "flags": self.flags,
        }


# --------------------------------------------------------------------------
# Tunable policy values (DB-backed, seeded with defaults)
# --------------------------------------------------------------------------
DEFAULT_POLICIES: list[dict] = [
    {
        "key": "match.amount_variance_pct",
        "name": "Amount variance tolerance",
        "category": "matching",
        "description": "Invoice vs PO amount variance accepted without an exception.",
        "value_type": "percent",
        "value": str(settings.amount_variance_tolerance_pct),
        "unit": "%",
    },
    {
        "key": "match.quantity_variance_pct",
        "name": "Quantity variance tolerance",
        "category": "matching",
        "description": "Invoice vs receipt quantity variance accepted without an exception.",
        "value_type": "percent",
        "value": str(settings.quantity_variance_tolerance_pct),
        "unit": "%",
    },
    {
        "key": "match.amount_variance_abs",
        "name": "Absolute variance floor",
        "category": "matching",
        "description": "Variances below this dollar amount are immaterial regardless of percentage.",
        "value_type": "money",
        "value": str(settings.amount_variance_tolerance_abs),
        "unit": "USD",
    },
    {
        "key": "intake.duplicate_similarity",
        "name": "Duplicate similarity threshold",
        "category": "intake",
        "description": "Similarity score at which an invoice is flagged as a suspected duplicate.",
        "value_type": "number",
        "value": str(settings.duplicate_similarity_threshold),
    },
    {
        "key": "hitl.confidence_floor",
        "name": "Global confidence floor",
        "category": "governance",
        "description": "Any agent proposal below this confidence must be reviewed by a human.",
        "value_type": "number",
        "value": str(settings.global_confidence_floor),
    },
    {
        "key": "hitl.enforce_global",
        "name": "Enforce human-in-the-loop globally",
        "category": "governance",
        "description": "Master switch. When on, no agent action reaches a system of record unreviewed.",
        "value_type": "bool",
        "value": "true" if settings.enforce_human_in_the_loop else "false",
    },
    {
        "key": "hitl.dual_approval_above",
        "name": "Dual approval threshold",
        "category": "governance",
        "description": "Financial impact above which two distinct approvers are required.",
        "value_type": "money",
        "value": "100000",
        "unit": "USD",
    },
    {
        "key": "sla.invoice_cycle_hours",
        "name": "Invoice cycle SLA",
        "category": "sla",
        "description": "Target hours from receipt to posted.",
        "value_type": "number",
        "value": str(settings.sla_invoice_cycle_hours),
        "unit": "h",
    },
    {
        "key": "sla.approval_reminder_hours",
        "name": "Approval reminder threshold",
        "category": "sla",
        "description": "Invoice age at which the Approval agent proposes a reminder.",
        "value_type": "number",
        "value": str(settings.sla_approval_reminder_hours),
        "unit": "h",
    },
    {
        "key": "sla.approval_escalation_hours",
        "name": "Approval escalation threshold",
        "category": "sla",
        "description": "Invoice age at which the Approval agent proposes an escalation.",
        "value_type": "number",
        "value": str(settings.sla_approval_escalation_hours),
        "unit": "h",
    },
    {
        "key": "sla.exception_resolution_hours",
        "name": "Exception resolution SLA",
        "category": "sla",
        "description": "Target hours to close an exception case.",
        "value_type": "number",
        "value": str(settings.sla_exception_resolution_hours),
        "unit": "h",
    },
    {
        "key": "procurement.auto_approve_under",
        "name": "Purchase request auto-approve ceiling",
        "category": "procurement",
        "description": "Requests under this value follow the light-touch path.",
        "value_type": "money",
        "value": str(settings.auto_approve_under_usd),
        "unit": "USD",
    },
    {
        "key": "procurement.manager_review_under",
        "name": "Purchase request manager review ceiling",
        "category": "procurement",
        "description": "Requests under this value route to manager review; above goes to procurement.",
        "value_type": "money",
        "value": str(settings.manager_review_under_usd),
        "unit": "USD",
    },
    {
        "key": "payment.max_auto_release",
        "name": "Maximum auto-release payment",
        "category": "payment",
        "description": "Payments above this value always require a Controller release.",
        "value_type": "money",
        "value": "0",
        "unit": "USD",
    },
    {
        "key": "risk.bank_change_freeze_days",
        "name": "Bank change payment freeze",
        "category": "risk",
        "description": "Days after a supplier bank change during which payments are frozen.",
        "value_type": "number",
        "value": "10",
        "unit": "days",
    },
]


def seed_policies(db: Session) -> None:
    existing = {row for row in db.execute(select(PolicyRule.key)).scalars().all()}
    for spec in DEFAULT_POLICIES:
        if spec["key"] in existing:
            continue
        db.add(PolicyRule(**spec))
    db.flush()


class PolicyStore:
    """Reads DB-backed policy values with typed accessors and settings fallback."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[str, PolicyRule] = {
            rule.key: rule
            for rule in db.execute(select(PolicyRule)).scalars().all()
        }

    def raw(self, key: str, default: str = "") -> str:
        rule = self._cache.get(key)
        if rule is None or not rule.enabled:
            return default
        return rule.value

    def number(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.raw(key, str(default)))
        except (TypeError, ValueError):
            return default

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.raw(key, "true" if default else "false")
        return str(value).strip().lower() in {"true", "1", "yes", "on"}


def get_agent_config(db: Session, agent_key: str) -> AgentConfig | None:
    return db.execute(
        select(AgentConfig).where(AgentConfig.agent_key == agent_key)
    ).scalar_one_or_none()


def risk_for_action(action_kind: str, financial_impact: float, confidence: float) -> str:
    if action_kind in {ActionKind.RELEASE_PAYMENT, ActionKind.UPDATE_SUPPLIER_MASTER, ActionKind.BLOCK_SUPPLIER}:
        return RiskLevel.CRITICAL if financial_impact >= 50_000 else RiskLevel.HIGH
    if action_kind in IRREVERSIBLE_ACTIONS:
        return RiskLevel.HIGH if financial_impact >= 25_000 else RiskLevel.MEDIUM
    if confidence < 0.75:
        return RiskLevel.HIGH
    if financial_impact >= 100_000:
        return RiskLevel.HIGH
    if financial_impact >= 10_000 or confidence < 0.90:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def evaluate(
    db: Session,
    *,
    agent_key: str,
    action_kind: str,
    confidence: float,
    financial_impact_usd: float = 0.0,
    reversible: bool | None = None,
    extra_flags: list[str] | None = None,
) -> PolicyDecision:
    """Decide whether a proposed action may bypass the human checkpoint.

    Returns a fully-explained decision. `allow_auto_execute=True` requires every
    gate to open; anything else stops at a HumanTask.
    """
    store = PolicyStore(db)
    config = get_agent_config(db, agent_key)
    flags = list(extra_flags or [])
    reasons: list[str] = []
    blocked: list[str] = []

    action_kind = str(action_kind)
    autonomy = str(config.autonomy_level) if config else str(AutonomyLevel.HUMAN_APPROVAL)
    threshold = config.confidence_threshold if config else store.number("hitl.confidence_floor", 0.90)
    max_auto = config.max_auto_amount_usd if config else 0.0
    dual_threshold = (
        config.require_dual_approval_above_usd if config else store.number("hitl.dual_approval_above", 100_000)
    )

    if reversible is None:
        reversible = action_kind not in IRREVERSIBLE_ACTIONS

    required_role = ACTION_MIN_ROLE.get(action_kind, Role.AP_MANAGER)
    risk_level = risk_for_action(action_kind, financial_impact_usd, confidence)

    # Escalate the required role as financial impact climbs.
    if financial_impact_usd >= 250_000 and ROLE_AUTHORITY[required_role] < ROLE_AUTHORITY[Role.CFO]:
        required_role = Role.CFO
        flags.append("cfo_threshold")
    elif financial_impact_usd >= 50_000 and ROLE_AUTHORITY[required_role] < ROLE_AUTHORITY[Role.CONTROLLER]:
        required_role = Role.CONTROLLER
        flags.append("controller_threshold")

    dual_approval = financial_impact_usd >= dual_threshold and action_kind in IRREVERSIBLE_ACTIONS
    if dual_approval:
        flags.append("dual_approval")

    # ---- Gate 1: global HITL enforcement -------------------------------
    if store.flag("hitl.enforce_global", settings.enforce_human_in_the_loop):
        blocked.append("Global human-in-the-loop enforcement is ON — every action needs a reviewer.")
    else:
        reasons.append("Global HITL enforcement is off for this tenant.")

    # ---- Gate 2: agent enabled & autonomy level ------------------------
    if config is not None and not config.enabled:
        blocked.append(f"Agent '{agent_key}' is disabled.")
    if settings.agents_paused:
        blocked.append("Fleet kill switch engaged — all agents paused.")

    if autonomy in {AutonomyLevel.OBSERVE_ONLY, AutonomyLevel.SUGGEST, AutonomyLevel.HUMAN_APPROVAL}:
        blocked.append(
            f"Autonomy level is {autonomy} — proposals require an explicit human decision."
        )
    else:
        reasons.append(f"Autonomy level {autonomy} permits bounded auto-execution.")

    # ---- Gate 3: irreversibility ---------------------------------------
    if action_kind in IRREVERSIBLE_ACTIONS:
        blocked.append(
            f"'{action_kind}' is irreversible or outward-facing — human sign-off is mandatory at any autonomy level."
        )
        flags.append("irreversible")
    else:
        reasons.append("Action is reversible and internally scoped.")

    # ---- Gate 4: confidence --------------------------------------------
    if confidence < threshold:
        blocked.append(
            f"Confidence {confidence:.0%} is below the {threshold:.0%} threshold for this agent."
        )
        flags.append("low_confidence")
    else:
        reasons.append(f"Confidence {confidence:.0%} clears the {threshold:.0%} threshold.")

    # ---- Gate 5: financial envelope ------------------------------------
    if financial_impact_usd > max_auto:
        blocked.append(
            f"This agent holds no auto-execution allowance, so any action with financial "
            f"impact (${financial_impact_usd:,.2f} here) needs a person."
            if max_auto <= 0
            else f"Financial impact ${financial_impact_usd:,.2f} exceeds the agent's "
                 f"${max_auto:,.2f} auto-execution ceiling."
        )
        flags.append("over_auto_limit")
    else:
        reasons.append(f"Financial impact ${financial_impact_usd:,.2f} is inside the auto ceiling.")

    # ---- Gate 6: risk level --------------------------------------------
    if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        blocked.append(f"Risk level '{risk_level}' always routes to a human.")

    # ---- Gate 7: allow-list --------------------------------------------
    if config is not None and config.allowed_actions and action_kind not in (config.allowed_actions or []):
        blocked.append(f"'{action_kind}' is not in this agent's permitted action list.")
        flags.append("action_not_permitted")

    allow_auto = not blocked and action_kind != ActionKind.NO_OP

    return PolicyDecision(
        allow_auto_execute=allow_auto,
        requires_human=not allow_auto,
        required_role=str(required_role),
        risk_level=str(risk_level),
        reversible=bool(reversible),
        dual_approval_required=dual_approval,
        reasons=reasons,
        blocked_reasons=blocked,
        flags=sorted(set(flags)),
    )


def can_decide(user_role: str, required_role: str) -> bool:
    return ROLE_AUTHORITY.get(str(user_role), 0) >= ROLE_AUTHORITY.get(str(required_role), 99)
