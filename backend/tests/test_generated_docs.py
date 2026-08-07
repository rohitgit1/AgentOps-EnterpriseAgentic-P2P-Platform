"""Guards on the generated documentation.

`agents/<key>/AGENT.md` and `skills/<name>/SKILL.md` are generated from the code
so they cannot drift. That only holds if someone regenerates them — so this test
regenerates into a temporary tree and fails if the committed files differ.

A failure here is not a bug, it is a missed step:

    python scripts/generate_agent_specs.py
    python scripts/generate_skill_docs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("P2P_DATABASE_URL", "sqlite://")

from app.agents.registry import list_agents  # noqa: E402
from app.skills import catalog  # noqa: E402

import generate_agent_specs as gen  # noqa: E402
from agent_build_notes import BUILD_NOTES  # noqa: E402


def test_every_agent_has_build_notes():
    """The reasoning is the part of a build spec that cannot be extracted."""
    missing = [a.key for a in list_agents() if a.key not in BUILD_NOTES]
    assert not missing, (
        f"agents without build notes: {missing}. A spec without the branch "
        f"conditions and thresholds is not one someone can rebuild from."
    )
    stale = [k for k in BUILD_NOTES if k not in {a.key for a in list_agents()}]
    assert not stale, f"build notes for agents that no longer exist: {stale}"


def test_build_notes_carry_the_reasoning():
    for agent in list_agents():
        notes = BUILD_NOTES[agent.key]
        for field in ("gather", "decide", "thresholds", "escalation", "handoff"):
            assert notes.get(field), f"{agent.key} build notes have no '{field}'"
        for row in notes["thresholds"]:
            assert len(row) == 3, f"{agent.key} threshold row is not (quantity, value, source)"


def test_every_agent_has_a_committed_spec():
    for agent in list_agents():
        path = ROOT / "agents" / agent.key / "AGENT.md"
        assert path.exists(), f"no build specification at {path}"
        body = path.read_text()
        # The sections a rebuild depends on.
        for heading in ("## 1 · What it consumes and what it returns",
                        "## 2 · Governance envelope",
                        "## 3 · Actions it may propose",
                        "## 4 · Lifecycle",
                        "## 5 · Dependencies",
                        "## 7 · Operating brief",
                        "## 8 · Rebuild checklist"):
            assert heading in body, f"{agent.key} spec is missing '{heading}'"
        for action in agent.allowed_actions:
            assert f"`{action}`" in body, f"{agent.key} spec omits action '{action}'"


@pytest.mark.parametrize("agent_key", [a.key for a in list_agents()])
def test_committed_spec_matches_the_code(agent_key):
    """Regenerate and compare — a changed agent must ship a regenerated spec."""
    agent = next(a for a in list_agents() if a.key == agent_key)
    expected = gen.render(agent, BUILD_NOTES[agent_key])
    committed = (ROOT / "agents" / agent_key / "AGENT.md").read_text()
    assert committed == expected, (
        f"agents/{agent_key}/AGENT.md is stale — run "
        f"`python scripts/generate_agent_specs.py`"
    )


def test_every_catalogued_skill_has_a_committed_contract():
    for skill in catalog():
        path = ROOT / "skills" / skill["name"] / "SKILL.md"
        assert path.exists(), f"no contract at {path}"
        assert skill["purpose"] in path.read_text(), \
            f"skills/{skill['name']}/SKILL.md is stale — run generate_skill_docs.py"


def test_the_specification_of_record_exists():
    spec = (ROOT / "docs" / "SPECIFICATION.md").read_text()
    # The invariant is the reason the document exists; it must survive edits.
    assert "An agent returns proposals, never mutations." in spec
    assert str(len(list_agents())) in spec
