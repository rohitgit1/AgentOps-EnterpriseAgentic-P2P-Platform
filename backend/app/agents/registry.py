"""Agent registry and configuration bootstrap."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import AgentSuite
from ..models import AgentConfig
from .approval_acceleration import ApprovalAccelerationAgent
from .base import BaseAgent
from .contract_intelligence import ContractIntelligenceAgent
from .contract_lifecycle_agent import ContractLifecycleAgent
from .exception_agent import ExceptionResolutionAgent
from .invoice_intake import InvoiceIntakeAgent
from .payment_readiness import PaymentReadinessAgent
from .procurement_command_center import ProcurementCommandCenterAgent
from .procurement_request import ProcurementRequestAgent
from .sla_command_center import SLACommandCenterAgent
from .sourcing_rfp import SourcingEventAgent
from .spend_analytics import SpendAnalyticsAgent
from .supplier_experience import SupplierExperienceAgent
from .supplier_risk import SupplierRiskAgent
from .supplier_risk_compliance import SupplierRiskComplianceAgent
from .tail_spend_agent import TailSpendAgent
from .three_way_match import ThreeWayMatchAgent

# --- P2P AgentOps: operational accounts payable ---------------------------
P2P_AGENT_CLASSES: list[type[BaseAgent]] = [
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

# --- Procurement AgentOps: strategic sourcing & category management -------
PROCUREMENT_AGENT_CLASSES: list[type[BaseAgent]] = [
    SourcingEventAgent,
    SpendAnalyticsAgent,
    SupplierRiskComplianceAgent,
    ContractLifecycleAgent,
    TailSpendAgent,
    ProcurementCommandCenterAgent,
]

AGENT_CLASSES: list[type[BaseAgent]] = P2P_AGENT_CLASSES + PROCUREMENT_AGENT_CLASSES

AGENTS: dict[str, BaseAgent] = {cls.key: cls() for cls in AGENT_CLASSES}


def get_agent(key: str) -> BaseAgent | None:
    return AGENTS.get(key)


def list_agents(suite: str | None = None) -> list[BaseAgent]:
    agents = list(AGENTS.values())
    if suite:
        agents = [a for a in agents if str(a.suite) == str(suite)]
    return agents


def suites() -> dict[str, list[BaseAgent]]:
    return {
        str(AgentSuite.P2P): list_agents(AgentSuite.P2P),
        str(AgentSuite.PROCUREMENT): list_agents(AgentSuite.PROCUREMENT),
    }


def seed_agent_configs(db: Session) -> None:
    existing = set(db.execute(select(AgentConfig.agent_key)).scalars().all())
    for agent in AGENTS.values():
        if agent.key in existing:
            continue
        db.add(AgentConfig(**agent.default_config()))
    db.flush()
