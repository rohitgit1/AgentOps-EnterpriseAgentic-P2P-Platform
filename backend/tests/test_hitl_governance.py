"""Tests for the guarantee the platform is built on: agents cannot act alone."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("P2P_DATABASE_URL", "sqlite://")

from app import models  # noqa: E402
from app.agents.orchestrator import orchestrator  # noqa: E402
from app.agents.registry import get_agent, seed_agent_configs  # noqa: E402
from app.database import Base  # noqa: E402
from app.enums import (  # noqa: E402
    IRREVERSIBLE_ACTIONS,
    ActionKind,
    AutonomyLevel,
    HumanDecision,
    HumanTaskStatus,
    InvoiceStatus,
    Role,
    WorkflowStage,
)
from app.services import hitl, policy  # noqa: E402
from app.services.audit import verify_chain  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, future=True)()
    seed_agent_configs(session)
    policy.seed_policies(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    from app.seed import seed_all

    seed_all(db, force=True)
    return db


def user(db, role: str) -> models.User:
    return db.execute(select(models.User).where(models.User.role == role)).scalars().first()


# ==========================================================================
# Policy engine
# ==========================================================================
def test_default_posture_blocks_auto_execution(db):
    verdict = policy.evaluate(
        db, agent_key="invoice_intake", action_kind=ActionKind.ADVANCE_STAGE,
        confidence=0.99, financial_impact_usd=10.0,
    )
    assert verdict.allow_auto_execute is False
    assert verdict.requires_human is True
    assert verdict.blocked_reasons, "a blocked action must always say why"


@pytest.mark.parametrize("action", sorted(IRREVERSIBLE_ACTIONS))
def test_irreversible_actions_never_auto_execute(db, action):
    """Even with enforcement off, max autonomy and perfect confidence."""
    from app.config import settings

    config = policy.get_agent_config(db, "payment_readiness")
    config.autonomy_level = AutonomyLevel.FULL_AUTO
    config.max_auto_amount_usd = 10_000_000
    config.confidence_threshold = 0.0
    config.allowed_actions = []
    db.flush()

    original = settings.enforce_human_in_the_loop
    settings.enforce_human_in_the_loop = False
    try:
        verdict = policy.evaluate(
            db, agent_key="payment_readiness", action_kind=action,
            confidence=1.0, financial_impact_usd=1.0,
        )
    finally:
        settings.enforce_human_in_the_loop = original

    assert verdict.allow_auto_execute is False
    assert verdict.reversible is False
    assert any("irreversible" in r.lower() or "outward-facing" in r.lower()
               for r in verdict.blocked_reasons)


def test_low_confidence_always_requires_a_human(db):
    verdict = policy.evaluate(
        db, agent_key="invoice_intake", action_kind=ActionKind.ADVANCE_STAGE,
        confidence=0.40, financial_impact_usd=0.0,
    )
    assert "low_confidence" in verdict.flags


def test_required_role_escalates_with_financial_impact(db):
    small = policy.evaluate(db, agent_key="three_way_match",
                            action_kind=ActionKind.ADVANCE_STAGE,
                            confidence=0.99, financial_impact_usd=100.0)
    large = policy.evaluate(db, agent_key="three_way_match",
                            action_kind=ActionKind.ADVANCE_STAGE,
                            confidence=0.99, financial_impact_usd=300_000.0)
    assert small.required_role == Role.AP_CLERK
    assert large.required_role == Role.CFO


def test_dual_approval_above_threshold(db):
    verdict = policy.evaluate(db, agent_key="payment_readiness",
                              action_kind=ActionKind.RELEASE_PAYMENT,
                              confidence=0.99, financial_impact_usd=250_000.0)
    assert verdict.dual_approval_required is True


# ==========================================================================
# Agent behaviour
# ==========================================================================
def test_agent_run_creates_checkpoints_not_mutations(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    before_stage, before_status = invoice.stage, invoice.status

    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    db.flush()

    assert result.tasks, "the agent must produce a proposal"
    assert result.auto_executed == [], "nothing may auto-execute under default policy"
    db.refresh(invoice)
    assert (invoice.stage, invoice.status) == (before_stage, before_status), \
        "the agent must not have changed business state"
    assert all(t.status == HumanTaskStatus.PENDING for t in result.tasks)


def test_agent_run_records_plan_evidence_and_policy(seeded):
    db = seeded
    invoice = db.execute(select(models.Invoice)).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    execution = result.execution
    assert execution.plan and execution.observations
    assert execution.evidence and execution.reasoning
    assert execution.policy_evaluation["proposals"], "policy verdict must be persisted"


def test_disabled_agent_produces_nothing(seeded):
    db = seeded
    config = policy.get_agent_config(db, "invoice_intake")
    config.enabled = False
    db.flush()
    invoice = db.execute(select(models.Invoice)).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    assert result.tasks == []
    assert result.execution.status == "blocked_by_policy"


# ==========================================================================
# Human decisions
# ==========================================================================
def test_role_without_authority_cannot_decide(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    task = result.tasks[0]
    task.required_role = Role.CONTROLLER
    db.flush()

    with pytest.raises(hitl.HITLError, match="cannot decide"):
        hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.AP_CLERK))
    assert task.status == HumanTaskStatus.PENDING


def test_approval_applies_the_payload_and_advances(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.invoice_number == "VIS-2026-08841")
    ).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    task = next(t for t in result.tasks if t.action_kind in
                {ActionKind.ADVANCE_STAGE, ActionKind.UPDATE_INVOICE_FIELDS})

    hitl.decide(db, task=task, decision=HumanDecision.APPROVE,
                user=user(db, Role.AP_MANAGER), notes="verified")
    db.flush()
    db.refresh(invoice)

    assert task.status == HumanTaskStatus.APPROVED
    assert task.decided_by
    assert invoice.stage == WorkflowStage.MATCHING
    assert invoice.human_touches == 1


def test_rejection_requires_and_records_a_reason(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    task = result.tasks[0]

    hitl.decide(db, task=task, decision=HumanDecision.REJECT,
                user=user(db, Role.AP_MANAGER), notes="Supplier is wrong.")
    db.flush()
    db.refresh(invoice)

    assert task.status == HumanTaskStatus.REJECTED
    assert invoice.on_hold is True
    assert "Supplier is wrong." in (invoice.hold_reason or "")


def test_modify_and_approve_applies_the_edited_payload(seeded):
    db = seeded
    # Find any intake invoice whose proposal is a field correction.
    task = None
    invoice = None
    for candidate in db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().all():
        result = get_agent("invoice_intake").run(db, {"invoice_id": candidate.id})
        task = next((t for t in result.tasks
                     if t.action_kind == ActionKind.UPDATE_INVOICE_FIELDS), None)
        if task is not None:
            invoice = candidate
            break
    assert task is not None, "the demo dataset must contain at least one correctable invoice"

    edited = dict(task.proposed_payload)
    edited["fields"] = {**edited.get("fields", {}), "total_amount": 4242.42}
    hitl.decide(db, task=task, decision=HumanDecision.MODIFY_AND_APPROVE,
                user=user(db, Role.AP_MANAGER), modified_payload=edited)
    db.flush()
    db.refresh(invoice)

    assert task.status == HumanTaskStatus.MODIFIED
    assert invoice.total_amount == pytest.approx(4242.42)


def test_a_decided_task_cannot_be_decided_twice(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    task = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id}).tasks[0]
    hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.AP_MANAGER))
    with pytest.raises(hitl.HITLError, match="already decided"):
        hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.AP_MANAGER))


def test_dual_approval_needs_two_distinct_people(seeded):
    db = seeded
    invoice = db.execute(select(models.Invoice)).scalars().first()
    payment = models.Payment(
        payment_number="PAY-TEST-1", invoice_id=invoice.id, supplier_id=invoice.supplier_id,
        amount=250_000.0, currency="USD", status="scheduled",
    )
    db.add(payment)
    db.flush()

    verdict = policy.evaluate(db, agent_key="payment_readiness",
                              action_kind=ActionKind.RELEASE_PAYMENT,
                              confidence=0.99, financial_impact_usd=250_000.0)
    task = hitl.create_checkpoint(
        db, execution=None, agent_key="payment_readiness", agent_name="Payment Readiness Agent",
        stage=WorkflowStage.PAYMENT, action_kind=ActionKind.RELEASE_PAYMENT,
        title="Release", summary="", rationale="", policy=verdict, confidence=0.99,
        proposed_payload={"payment_id": payment.id},
        entity_type="invoice", entity_id=invoice.id, financial_impact_usd=250_000.0,
    )
    # At this value the required role has already escalated to CFO.
    assert task.required_role == Role.CFO
    cfo = user(db, Role.CFO)
    first = hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=cfo)
    assert first["status"] == "awaiting_second_approval"

    with pytest.raises(hitl.HITLError, match="two distinct approvers"):
        hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=cfo)

    # A second, distinct approver with sufficient authority completes it.
    second = hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.ADMIN))
    assert second["status"] == HumanTaskStatus.APPROVED


# ==========================================================================
# Audit
# ==========================================================================
def test_audit_chain_verifies_after_a_full_workflow(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    result = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id})
    hitl.decide(db, task=result.tasks[0], decision=HumanDecision.APPROVE,
                user=user(db, Role.AP_MANAGER), notes="ok")
    db.commit()

    report = verify_chain(db)
    assert report["valid"] is True
    assert report["entries_checked"] > 0


def test_every_human_decision_is_audited(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    task = get_agent("invoice_intake").run(db, {"invoice_id": invoice.id}).tasks[0]
    actor = user(db, Role.AP_MANAGER)
    hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=actor, notes="ok")
    db.flush()

    rows = db.execute(
        select(models.AuditLog).where(models.AuditLog.human_task_id == task.id)
    ).scalars().all()
    actions = {r.action for r in rows}
    assert "hitl.checkpoint_created" in actions
    assert any(a.startswith("hitl.approve") for a in actions)
    assert any(r.actor == actor.full_name and r.actor_type == "human" for r in rows)


# ==========================================================================
# Orchestration
# ==========================================================================
def test_orchestrator_stops_at_the_first_checkpoint(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.stage == WorkflowStage.INTAKE)
    ).scalars().first()
    runs = orchestrator.advance_invoice(db, invoice.id)
    db.flush()
    assert len(runs) == 1, "the orchestrator must not run past an open checkpoint"

    again = orchestrator.advance_invoice(db, invoice.id)
    assert again == [], "a pending checkpoint blocks any further agent work"


def test_full_lifecycle_reaches_payment_only_via_humans(seeded):
    db = seeded
    invoice = db.execute(
        select(models.Invoice).where(models.Invoice.invoice_number == "VIS-2026-08841")
    ).scalars().first()

    roles = [Role.AP_CLERK, Role.AP_MANAGER, Role.CONTROLLER, Role.CFO]
    decisions = 0
    for _ in range(10):
        pending = db.execute(
            select(models.HumanTask).where(
                models.HumanTask.entity_id == invoice.id,
                models.HumanTask.status == HumanTaskStatus.PENDING,
            )
        ).scalars().all()
        for task in pending:
            actor = next(
                (user(db, r) for r in roles
                 if policy.can_decide(r, task.required_role)), user(db, Role.ADMIN)
            )
            hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=actor)
            decisions += 1
        db.flush()
        db.refresh(invoice)
        if invoice.stage == WorkflowStage.APPROVAL and invoice.status == InvoiceStatus.PENDING_APPROVAL:
            break
        if not orchestrator.advance_invoice(db, invoice.id) and not pending:
            break

    assert decisions >= 3, "the path to approval must pass several human checkpoints"
    assert invoice.status == InvoiceStatus.PENDING_APPROVAL
    assert invoice.human_touches == decisions


def test_registered_actions_cover_every_proposable_action():
    """Any ActionKind an agent may propose must have an executor, or it can never run."""
    from app.agents.registry import list_agents

    registered = set(hitl.registered_actions())
    for agent in list_agents():
        for action in agent.allowed_actions:
            assert str(action) in registered, f"{agent.key} may propose unexecutable '{action}'"
