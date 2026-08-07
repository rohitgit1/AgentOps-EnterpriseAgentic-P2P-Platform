"""Agent Control Room API — status, runs, governance settings, manual triggers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.orchestrator import orchestrator
from ..agents.registry import AGENTS, get_agent, list_agents
from ..config import settings
from ..database import get_db
from ..enums import AUTONOMY_LABELS, AutonomyLevel, EventType, Role
from ..models import AgentConfig, AgentExecution, User
from ..serializers import agent_config_out, execution_out, human_task_out
from ..services import llm
from ..services.audit import write_audit
from ..services.erp import connector_health
from ..services.events import record_event
from ..services.hitl import registered_actions
from ..skills import catalog as skills_catalog
from .deps import get_current_user, require_manager, require_admin

router = APIRouter(prefix="/agents", tags=["agents"])


class ConfigUpdate(BaseModel):
    enabled: bool | None = None
    autonomy_level: str | None = None
    confidence_threshold: float | None = None
    max_auto_amount_usd: float | None = None
    require_dual_approval_above_usd: float | None = None
    escalation_role: str | None = None
    notes: str | None = None


class RunRequest(BaseModel):
    # P2P context
    invoice_id: str | None = None
    exception_id: str | None = None
    message_id: str | None = None
    supplier_id: str | None = None
    request_id: str | None = None
    # Procurement context
    event_id: str | None = None
    draft_id: str | None = None
    category: str | None = None
    budget: float | None = None
    title: str | None = None
    contract_type: str | None = None
    value_usd: float | None = None
    term_months: int | None = None
    supplier_name: str | None = None
    requirements: str | None = None
    compliance_rules: list[str] | None = None
    # Input attachments the agent should read
    attachment_ids: list[str] | None = None


@router.get("")
def list_agent_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    configs = {c.agent_key: c for c in db.execute(select(AgentConfig)).scalars().all()}
    output = []
    for agent in list_agents():
        config = configs.get(agent.key)
        if config is None:
            config = AgentConfig(**agent.default_config())
            db.add(config)
            db.flush()
        recent = db.execute(
            select(AgentExecution)
            .where(AgentExecution.agent_key == agent.key)
            .order_by(AgentExecution.created_at.desc())
            .limit(1)
        ).scalars().first()
        data = agent_config_out(config, agent.describe())
        data["last_run"] = execution_out(recent) if recent else None
        data["health"] = "paused" if settings.agents_paused else ("enabled" if config.enabled else "disabled")
        output.append(data)
    db.commit()
    return output


@router.get("/status")
def fleet_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    configs = db.execute(select(AgentConfig)).scalars().all()
    executions = db.execute(
        select(AgentExecution).order_by(AgentExecution.created_at.desc()).limit(50)
    ).scalars().all()
    return {
        "fleet_paused": settings.agents_paused,
        "global_hitl_enforced": settings.enforce_human_in_the_loop,
        "confidence_floor": settings.global_confidence_floor,
        "agents_total": len(configs),
        "agents_enabled": len([c for c in configs if c.enabled]),
        "autonomy_distribution": {
            level: len([c for c in configs if c.autonomy_level == level])
            for level in AUTONOMY_LABELS
        },
        "reasoning_engine": llm.engine_status(),
        "erp_connectors": connector_health(),
        "executable_actions": registered_actions(),
        "recent_runs": [execution_out(e) for e in executions[:15]],
    }


@router.get("/skills")
def skills(_: User = Depends(get_current_user), suite: str | None = None) -> list[dict]:
    catalog = skills_catalog(suite)
    for entry in catalog:
        entry["used_by_agents"] = [
            agent.name for agent in list_agents() if entry["name"] in (agent.skills or [])
        ]
    return catalog


@router.get("/{agent_key}")
def get_agent_detail(
    agent_key: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    agent = get_agent(agent_key)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")
    config = db.execute(
        select(AgentConfig).where(AgentConfig.agent_key == agent_key)
    ).scalar_one_or_none()
    if config is None:
        config = AgentConfig(**agent.default_config())
        db.add(config)
        db.commit()
    runs = db.execute(
        select(AgentExecution)
        .where(AgentExecution.agent_key == agent_key)
        .order_by(AgentExecution.created_at.desc())
        .limit(25)
    ).scalars().all()
    data = agent_config_out(config, agent.describe())
    data["runs"] = [execution_out(r) for r in runs]
    return data


@router.patch("/{agent_key}/config")
def update_config(
    agent_key: str,
    payload: ConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> dict:
    config = db.execute(
        select(AgentConfig).where(AgentConfig.agent_key == agent_key)
    ).scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")

    before = agent_config_out(config)
    updates = payload.model_dump(exclude_none=True)

    if "autonomy_level" in updates:
        if updates["autonomy_level"] not in AUTONOMY_LABELS:
            raise HTTPException(status_code=422, detail="Unknown autonomy level.")
        if (
            updates["autonomy_level"] in {AutonomyLevel.AUTO_WITHIN_GUARDRAILS, AutonomyLevel.FULL_AUTO}
            and user.role not in {Role.CONTROLLER, Role.CFO, Role.ADMIN}
        ):
            raise HTTPException(
                status_code=403,
                detail="Raising an agent above 'Human Approval' requires Controller authority.",
            )
    if "confidence_threshold" in updates and not 0.0 <= updates["confidence_threshold"] <= 1.0:
        raise HTTPException(status_code=422, detail="confidence_threshold must be between 0 and 1.")

    for key, value in updates.items():
        setattr(config, key, value)

    write_audit(
        db,
        action="agent.config_updated",
        description=f"{user.full_name} updated governance settings for {config.display_name}: "
                    + ", ".join(f"{k}={v}" for k, v in updates.items()),
        actor=user.full_name,
        actor_type="human",
        actor_role=user.role,
        entity_type="agent",
        entity_id=config.id,
        entity_label=config.display_name,
        before_state=before,
        after_state=updates,
        agent_key=agent_key,
    )
    record_event(
        db,
        event_type=EventType.SYSTEM,
        title=f"Agent governance changed · {config.display_name}",
        message=", ".join(f"{k} → {v}" for k, v in updates.items()),
        actor=user.full_name,
        actor_type="human",
        severity="warning",
    )
    db.commit()
    return agent_config_out(config, get_agent(agent_key).describe())


@router.post("/{agent_key}/run")
def run_agent(
    agent_key: str,
    payload: RunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    agent = get_agent(agent_key)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")
    if settings.agents_paused:
        raise HTTPException(status_code=409, detail="The agent fleet is paused by the kill switch.")

    context = payload.model_dump(exclude_none=True)
    result = agent.run(db, context, trigger="manual", triggered_by=user.full_name)
    db.flush()

    from ..models import Artifact
    from .procurement import artifact_out

    produced = db.execute(
        select(Artifact).where(Artifact.execution_id == result.execution.id)
        .order_by(Artifact.created_at.asc())
    ).scalars().all()
    db.commit()
    return {
        "execution": execution_out(result.execution, detail=True),
        "checkpoints": [human_task_out(t, detail=True) for t in result.tasks],
        "auto_executed": result.auto_executed,
        "artifacts": [artifact_out(a) for a in produced],
        "inputs_used": context.get("attachment_ids") or [],
    }


@router.get("/runs/all")
def list_runs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    agent_key: str | None = None,
    entity_id: str | None = None,
    limit: int = 60,
) -> list[dict]:
    query = select(AgentExecution).order_by(AgentExecution.created_at.desc())
    if agent_key:
        query = query.where(AgentExecution.agent_key == agent_key)
    if entity_id:
        query = query.where(AgentExecution.entity_id == entity_id)
    return [execution_out(e) for e in db.execute(query.limit(limit)).scalars().all()]


@router.get("/runs/{execution_id}")
def get_run(execution_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return execution_out(execution, detail=True)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
orchestration = APIRouter(prefix="/orchestrator", tags=["agents"])


@orchestration.post("/invoices/{invoice_id}/advance")
def advance_invoice(
    invoice_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    results = orchestrator.advance_invoice(db, invoice_id, triggered_by=user.full_name)
    db.commit()
    return {
        "runs": [execution_out(r.execution, detail=True) for r in results],
        "checkpoints": [human_task_out(t) for r in results for t in r.tasks],
    }


@orchestration.post("/sweep")
def sweep(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Run the whole fleet.

    Open to any signed-in user: a sweep only produces *proposals*. Nothing
    reaches a system of record until someone with the right authority decides
    on the resulting checkpoints.
    """
    if settings.agents_paused:
        raise HTTPException(status_code=409, detail="The agent fleet is paused by the kill switch.")
    summary = orchestrator.run_sweep(db, triggered_by=user.full_name)
    db.commit()
    return summary


@orchestration.post("/triage-exceptions")
def triage(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    results = orchestrator.run_exception_triage(db, triggered_by=user.full_name)
    db.commit()
    return {
        "runs": len(results),
        "checkpoints": [human_task_out(t) for r in results for t in r.tasks],
    }


@orchestration.post("/answer-supplier-inbox")
def answer_inbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    results = orchestrator.run_supplier_inbox(db, triggered_by=user.full_name)
    db.commit()
    return {
        "runs": len(results),
        "checkpoints": [human_task_out(t) for r in results for t in r.tasks],
    }


@orchestration.post("/kill-switch")
def kill_switch(
    paused: bool = Query(...), db: Session = Depends(get_db), user: User = Depends(require_admin)
) -> dict:
    settings.agents_paused = paused
    write_audit(
        db,
        action="fleet.kill_switch",
        description=f"{user.full_name} {'paused' if paused else 'resumed'} the entire agent fleet.",
        actor=user.full_name,
        actor_type="human",
        actor_role=user.role,
        entity_type="system",
        entity_label="Agent fleet",
        after_state={"paused": paused},
    )
    record_event(
        db,
        event_type=EventType.SYSTEM,
        title="Agent fleet " + ("paused" if paused else "resumed"),
        message=f"{user.full_name} operated the kill switch.",
        actor=user.full_name,
        actor_type="human",
        severity="critical" if paused else "success",
    )
    db.commit()
    return {"agents_paused": settings.agents_paused}
