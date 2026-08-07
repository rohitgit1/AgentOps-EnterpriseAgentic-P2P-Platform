"""Tests for the two explainer surfaces: the data model and the Agents Academy.

Both are introspected rather than hand-written, so the thing worth testing is
that they stay complete as the code grows: a new table must not fall out of the
schema map, and a new agent must not ship without a lesson.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("P2P_DATABASE_URL", "sqlite://")

from app.agents.registry import list_agents, seed_agent_configs  # noqa: E402
from app.api.explain import DOMAINS, WORKED_EXAMPLES  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.services import policy  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """A client on its own seeded in-memory database.

    The app's lifespan is deliberately not run — these endpoints are read-only
    and must not touch the demo database sitting on disk.
    """
    from app.main import app
    from app.seed import seed_all

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)

    with Session() as setup:
        seed_agent_configs(setup)
        policy.seed_policies(setup)
        seed_all(setup, force=True)
        setup.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture(scope="module")
def auth(client):
    persona = client.get("/api/auth/personas").json()[0]
    return {"X-User-Id": persona["id"]}


# ==========================================================================
# Data model
# ==========================================================================
def test_every_table_is_assigned_to_exactly_one_domain():
    """A new model must be placed deliberately, not land in the 'Other' bucket."""
    assigned: list[str] = [t for d in DOMAINS for t in d["tables"]]
    assert len(assigned) == len(set(assigned)), "a table is listed in two domains"

    known = set(Base.metadata.tables)
    assert set(assigned) == known, (
        f"unmapped tables: {sorted(known - set(assigned))}; "
        f"stale entries: {sorted(set(assigned) - known)}"
    )


def test_data_model_reports_live_schema_and_row_counts(client, auth):
    body = client.get("/api/data-model", headers=auth).json()
    assert body["totals"]["tables"] == len(Base.metadata.tables)
    assert not any(d["key"] == "other" for d in body["domains"])

    tables = {t["name"]: t for d in body["domains"] for t in d["tables"]}
    assert tables["users"]["row_count"] > 0, "row counts must come from the database"
    assert tables["users"]["primary_key"] == ["id"]
    assert all(c["name"] for c in tables["invoices"]["columns"])

    # A foreign key must appear from both ends.
    invoices = tables["invoices"]
    assert any(r["to_table"] == "suppliers" for r in invoices["references"])
    assert any(r["from_table"] == "invoices" for r in tables["suppliers"]["referenced_by"])


def test_data_model_states_the_write_boundary(client, auth):
    body = client.get("/api/data-model", headers=auth).json()
    assert "human_tasks" in body["invariant"]
    assert "never" in body["invariant"].lower()


def test_data_model_requires_a_signed_in_persona(client):
    assert client.get("/api/data-model").status_code == 401


# ==========================================================================
# Academy
# ==========================================================================
def test_every_agent_has_a_worked_example():
    missing = [a.key for a in list_agents() if a.key not in WORKED_EXAMPLES]
    assert not missing, f"agents shipped without a lesson: {missing}"


def test_academy_covers_every_agent_with_a_full_lesson(client, auth):
    body = client.get("/api/academy", headers=auth).json()
    assert body["foundations"], "the shared foundations must be present"
    assert body["totals"]["agents"] == len(list_agents())

    lessons = [a for suite in body["suites"].values() for a in suite["agents"]]
    assert len(lessons) == len(list_agents())
    for lesson in lessons:
        assert lesson["lifecycle"], f"{lesson['key']} explains no steps"
        assert lesson["inputs"] and lesson["outputs"], f"{lesson['key']} has no I/O contract"
        assert lesson["worked_example"]["steps"], f"{lesson['key']} has an empty example"
        assert lesson["prompt"].strip()
        assert lesson["governance"]["autonomy_label"]


def test_academy_marks_irreversible_actions_and_their_approver(client, auth):
    lesson = client.get("/api/academy/sourcing_rfp", headers=auth).json()
    award = next(a for a in lesson["actions"] if a["action"] == "award_sourcing_event")
    assert award["reversible"] is False
    assert award["min_role_label"], "a reviewer must be told who may approve"
    assert award["executable"] is True, "an agent must not advertise an unexecutable action"


def test_unknown_agent_is_a_404(client, auth):
    assert client.get("/api/academy/no_such_agent", headers=auth).status_code == 404
