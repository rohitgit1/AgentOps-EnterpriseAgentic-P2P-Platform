"""Agent registry and configuration bootstrap."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentConfig
from .approval_acceleration import ApprovalAccelerationAgent
from .base import BaseAgent
from .contract_intelligence import ContractIntelligenceAgent
from .exception_agent import ExceptionResolutionAgent
from .invoice_intake import InvoiceIntakeAgent
from .payment_readiness import PaymentReadinessAgent
from .procurement_request import ProcurementRequestAgent
from .sla_command_center import SLACommandCenterAgent
from .supplier_experience import SupplierExperienceAgent
from .supplier_risk import SupplierRiskAgent
from .three_way_match import ThreeWayMatchAgent

AGENT_CLASSES: list[type[BaseAgent]] = [
    InvoiceIntakeAgent,
    ThreeWayMatchAgent,
    ApprovalAccelerationAgent,
    ExceptionResolutionAgent,
    SupplierExperienceAgent,
    PaymentReadinessAgent,
    SupplierRiskAgent,
    ProcurementRequestAgent,
    ContractIntelligenceAgent,
    SLACommandCenterAgent,
]

AGENTS: dict[str, BaseAgent] = {cls.key: cls() for cls in AGENT_CLASSES}


def get_agent(key: str) -> BaseAgent | None:
    return AGENTS.get(key)


def list_agents() -> list[BaseAgent]:
    return list(AGENTS.values())


def seed_agent_configs(db: Session) -> None:
    existing = set(db.execute(select(AgentConfig.agent_key)).scalars().all())
    for agent in AGENTS.values():
        if agent.key in existing:
            continue
        db.add(AgentConfig(**agent.default_config()))
    db.flush()
