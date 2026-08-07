"""Tests for the Procurement suite and the attachment → agent → deliverable flow."""
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
from app.agents.registry import get_agent, list_agents, seed_agent_configs, suites  # noqa: E402
from app.database import Base  # noqa: E402
from app.enums import ActionKind, AgentSuite, HumanDecision, HumanTaskStatus, Role  # noqa: E402
from app.services import artifacts as artifact_service  # noqa: E402
from app.services import hitl, policy  # noqa: E402


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


def attachment(db, filename: str) -> models.Artifact:
    return db.execute(
        select(models.Artifact).where(models.Artifact.filename == filename)
    ).scalars().first()


# ==========================================================================
# Suite registration and I/O contracts
# ==========================================================================
def test_both_suites_are_registered():
    grouped = suites()
    assert len(grouped[str(AgentSuite.P2P)]) == 10
    assert len(grouped[str(AgentSuite.PROCUREMENT)]) == 6


def test_every_agent_declares_inputs_and_outputs():
    for agent in list_agents():
        assert agent.inputs, f"{agent.key} declares no inputs"
        assert agent.outputs, f"{agent.key} declares no outputs"
        for spec in agent.inputs + agent.outputs:
            assert spec.description, f"{agent.key}:{spec.name} has no description"
            assert spec.kind in {"attachment", "data", "artifact", "record", "proposal"}


def test_describe_exposes_the_io_contract():
    agent = get_agent("spend_analytics")
    described = agent.describe()
    assert described["suite"] == str(AgentSuite.PROCUREMENT)
    assert described["accepts_attachments"] is True
    assert described["produces_artifacts"] is True
    assert any(o["formats"] for o in described["outputs"])


# ==========================================================================
# Attachment parsing
# ==========================================================================
def test_csv_attachment_is_parsed_into_rows(db):
    artifact = artifact_service.store_input(
        db, filename="spend.csv",
        content="supplier,amount_usd\nAcme,100.00\nBeta,250.50\n",
        uploaded_by="tester",
    )
    parsed = artifact_service.parse(artifact)
    assert parsed["format"] == "csv"
    assert parsed["row_count"] == 2
    assert parsed["fields"] == ["supplier", "amount_usd"]
    assert parsed["rows"][1]["supplier"] == "Beta"


def test_malformed_json_degrades_with_a_reason_instead_of_raising(db):
    artifact = artifact_service.store_input(
        db, filename="broken.json", content="{not valid json", uploaded_by="tester")
    parsed = artifact_service.parse(artifact)
    assert parsed["format"] == "invalid_json"
    assert "Malformed JSON" in parsed["summary"]
    assert parsed["rows"] == []


def test_agent_receives_parsed_attachments_in_context(seeded):
    db = seeded
    extract = attachment(db, "spend-extract-q4.csv")
    result = get_agent("spend_analytics").run(
        db, {"attachment_ids": [extract.id]}, trigger="test")
    loaded = [o for o in (result.execution.observations or [])
              if o["tool"] == "spend_extract_load"]
    assert loaded, "the agent must report what it loaded"
    assert extract.filename in loaded[0]["summary"]


# ==========================================================================
# Deliverables
# ==========================================================================
@pytest.mark.parametrize("agent_key,attachments", [
    ("spend_analytics", ["spend-extract-q4.csv"]),
    ("supplier_risk_compliance", ["credit-report.csv", "otif-performance.csv"]),
    ("contract_lifecycle", ["trident-msa-draft.md"]),
    ("tail_spend", ["spend-extract-q4.csv", "catalog.csv"]),
    ("procurement_command_center", []),
])
def test_procurement_agents_produce_downloadable_artifacts(seeded, agent_key, attachments):
    db = seeded
    ids = [attachment(db, name).id for name in attachments]
    result = get_agent(agent_key).run(db, {"attachment_ids": ids}, trigger="test")
    db.flush()

    produced = db.execute(
        select(models.Artifact).where(models.Artifact.execution_id == result.execution.id)
    ).scalars().all()
    assert produced, f"{agent_key} produced no deliverable"
    for artifact in produced:
        assert artifact.direction == "output"
        assert artifact.content.strip(), f"{artifact.filename} is empty"
        assert artifact.filename
        assert artifact.summary


def test_deliverables_start_as_drafts_and_release_only_on_approval(seeded):
    db = seeded
    extract = attachment(db, "spend-extract-q4.csv")
    result = get_agent("spend_analytics").run(
        db, {"attachment_ids": [extract.id]}, trigger="test")
    db.flush()

    produced = db.execute(
        select(models.Artifact).where(models.Artifact.execution_id == result.execution.id)
    ).scalars().all()
    assert produced and all(a.status == "draft" for a in produced), \
        "a generated document must start as a draft"

    task = next(t for t in result.tasks if (t.proposed_payload or {}).get("artifact_ids"))
    linked = task.proposed_payload["artifact_ids"]

    hitl.decide(db, task=task, decision=HumanDecision.APPROVE,
                user=user(db, Role.PROCUREMENT), notes="reviewed")
    db.flush()

    for artifact_id in linked:
        artifact = db.get(models.Artifact, artifact_id)
        assert artifact.status == "released"
        assert artifact.released_by
        assert artifact.human_task_id == task.id


def test_rejecting_a_proposal_leaves_its_deliverables_as_drafts(seeded):
    db = seeded
    result = get_agent("procurement_command_center").run(db, {}, trigger="test")
    db.flush()
    task = result.tasks[0]
    linked = (task.proposed_payload or {}).get("artifact_ids") or []
    assert linked

    hitl.decide(db, task=task, decision=HumanDecision.REJECT,
                user=user(db, Role.CFO), notes="Numbers need re-basing.")
    db.flush()

    for artifact_id in linked:
        assert db.get(models.Artifact, artifact_id).status == "draft", \
            "a rejected proposal must not release its documents"


# ==========================================================================
# Governance still holds for the procurement suite
# ==========================================================================
def test_procurement_agents_do_not_mutate_state_before_approval(seeded):
    db = seeded
    before = db.execute(select(models.SavingsOpportunity)).scalars().all()
    extract = attachment(db, "spend-extract-q4.csv")
    get_agent("spend_analytics").run(db, {"attachment_ids": [extract.id]}, trigger="test")
    db.flush()
    after = db.execute(select(models.SavingsOpportunity)).scalars().all()
    assert len(after) == len(before), "no savings may be logged without a human decision"


def test_issuing_an_rfp_requires_procurement_authority(seeded):
    db = seeded
    brief = attachment(db, "requirements-freight-fy27.md")
    result = get_agent("sourcing_rfp").run(
        db, {"attachment_ids": [brief.id], "category": "Freight & Logistics",
             "budget": 850000, "title": "Test event"},
        trigger="test",
    )
    task = next(t for t in result.tasks if t.action_kind == ActionKind.ISSUE_RFP)
    assert task.required_role == Role.PROCUREMENT
    assert task.reversible is False, "issuing an RFP reaches suppliers — irreversible"

    with pytest.raises(hitl.HITLError, match="cannot decide"):
        hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.AP_CLERK))


def test_awarding_applies_only_after_approval(seeded):
    db = seeded
    event = db.execute(
        select(models.SourcingEvent).where(models.SourcingEvent.status == "issued")
    ).scalars().first()
    result = get_agent("sourcing_rfp").run(db, {"event_id": event.id}, trigger="test")
    task = next(t for t in result.tasks if t.action_kind == ActionKind.AWARD_SOURCING_EVENT)
    db.flush()
    db.refresh(event)
    assert event.status == "issued", "the agent must not award anything itself"

    # A ~800k award is above the dual-approval threshold, so one signature is
    # not enough — the event must still be unawarded after the first.
    assert task.dual_approval_required is True
    first = hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.CFO))
    db.flush()
    db.refresh(event)
    assert first["status"] == "awaiting_second_approval"
    assert event.status == "issued"

    hitl.decide(db, task=task, decision=HumanDecision.APPROVE, user=user(db, Role.ADMIN))
    db.flush()
    db.refresh(event)
    assert event.status == "awarded"
    assert event.awarded_supplier_id
    assert event.cycle_days is not None


def test_supplier_disposition_reaches_the_vendor_master_only_on_approval(seeded):
    db = seeded
    credit = attachment(db, "credit-report.csv")
    otif = attachment(db, "otif-performance.csv")
    result = get_agent("supplier_risk_compliance").run(
        db, {"attachment_ids": [credit.id, otif.id]}, trigger="test")
    task = next((t for t in result.tasks
                 if t.action_kind == ActionKind.SET_SUPPLIER_DISPOSITION), None)
    assert task is not None, "the seeded distressed supplier must trigger a disposition"

    assessment = db.get(models.RiskAssessment, task.entity_id or "") or db.execute(
        select(models.RiskAssessment).where(
            models.RiskAssessment.supplier_id == task.entity_id)
    ).scalars().first()
    assert assessment.applied_disposition is None

    hitl.decide(db, task=task, decision=HumanDecision.APPROVE,
                user=user(db, Role.PROCUREMENT), notes="agreed")
    db.flush()
    db.refresh(assessment)
    assert assessment.applied_disposition in {"monitor", "watchlist", "block"}
    assert assessment.decided_by


def test_clause_analysis_finds_the_planted_risks_in_the_sample_msa(seeded):
    db = seeded
    msa = attachment(db, "trident-msa-draft.md")
    result = get_agent("contract_lifecycle").run(db, {"attachment_ids": [msa.id]}, trigger="test")
    db.flush()
    draft = db.execute(select(models.ContractDraft)).scalars().first()

    risky = {f["key"] for f in (draft.clause_findings or [])}
    # The sample paper deliberately contains each of these.
    assert "unlimited_liability" in risky
    assert "unilateral_price" in risky
    assert "buyer_indemnifies" in risky
    assert draft.legal_risk_score > 35
    assert draft.missing_clauses, "the sample omits several mandatory clauses"

    # Signature must not be offered on paper this bad.
    assert not any(t.action_kind == ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE
                   for t in result.tasks)


def test_every_procurement_action_has_an_executor():
    registered = set(hitl.registered_actions())
    for agent in list_agents(AgentSuite.PROCUREMENT):
        for action in agent.allowed_actions:
            assert str(action) in registered, f"{agent.key} may propose unexecutable '{action}'"
