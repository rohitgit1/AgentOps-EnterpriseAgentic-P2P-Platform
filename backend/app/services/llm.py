"""Reasoning layer.

Three interchangeable engines behind one interface:

* ``deterministic`` (default) — a rule/heuristic reasoner that produces the same
  narrative for the same facts. No API key, no network, no variance. This is
  what a client demo should run on: reproducible, auditable, and it never
  fabricates a number that isn't in the evidence.
* ``anthropic`` / ``openai`` — live LLM narration when keys are configured.

Crucially the *decision* always comes from the deterministic rule engine in the
agents. The LLM only ever narrates or ranks; it cannot invent an action. That
keeps the audit story clean: policy decides, the model explains.
"""
from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class Reasoning:
    narrative: str
    engine: str
    tokens: int = 0


class DeterministicReasoner:
    """Templated chain-of-evidence narration built strictly from observed facts."""

    engine = "deterministic"

    def reason(self, *, agent_name: str, goal: str, evidence: list[dict], conclusion: str,
               confidence: float, decision_rules: list[str]) -> Reasoning:
        lines: list[str] = []
        lines.append(f"{agent_name} — objective: {goal}")
        lines.append("")
        lines.append("Evidence gathered:")
        if evidence:
            for idx, item in enumerate(evidence, start=1):
                label = item.get("label") or item.get("source") or f"signal {idx}"
                detail = item.get("detail") or item.get("value") or ""
                source = item.get("source")
                suffix = f"  [source: {source}]" if source and source != label else ""
                lines.append(f"  {idx}. {label}: {detail}{suffix}")
        else:
            lines.append("  (no supporting signals returned by tools)")

        lines.append("")
        lines.append("Decision rules applied:")
        for rule in decision_rules or ["default policy path"]:
            lines.append(f"  • {rule}")

        lines.append("")
        lines.append(f"Conclusion: {conclusion}")
        lines.append(f"Confidence: {confidence:.0%}")
        if confidence < settings.global_confidence_floor:
            lines.append(
                "Confidence is below the governance floor — routing to a human reviewer "
                "rather than acting."
            )
        return Reasoning(narrative="\n".join(lines), engine=self.engine)


class AnthropicReasoner:
    engine = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic  # imported lazily; optional dependency

        self.client = Anthropic(api_key=api_key, timeout=settings.llm_timeout_seconds)
        self.model = model

    def reason(self, *, agent_name: str, goal: str, evidence: list[dict], conclusion: str,
               confidence: float, decision_rules: list[str]) -> Reasoning:
        prompt = textwrap.dedent(
            f"""
            You are the {agent_name} in an enterprise Procure-to-Pay operation.

            Mission: {goal}

            Evidence collected by your tools (this is the ONLY factual basis you may use):
            {json.dumps(evidence, indent=2, default=str)}

            Deterministic policy engine outcome: {conclusion}
            Computed confidence: {confidence:.2f}
            Decision rules that fired: {json.dumps(decision_rules)}

            Write the audit-facing rationale for this outcome in 4-7 sentences.
            Rules:
            - Do not introduce facts, amounts, dates or names that are absent from the evidence.
            - Do not change the outcome; explain it.
            - State explicitly what a human reviewer should verify before approving.
            """
        ).strip()
        message = self.client.messages.create(
            model=self.model,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        tokens = getattr(message.usage, "input_tokens", 0) + getattr(message.usage, "output_tokens", 0)
        return Reasoning(narrative=text.strip(), engine=self.engine, tokens=tokens)


class OpenAIReasoner:
    engine = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI  # imported lazily; optional dependency

        self.client = OpenAI(api_key=api_key, timeout=settings.llm_timeout_seconds)
        self.model = model

    def reason(self, *, agent_name: str, goal: str, evidence: list[dict], conclusion: str,
               confidence: float, decision_rules: list[str]) -> Reasoning:
        prompt = (
            f"You are the {agent_name} in an enterprise Procure-to-Pay operation.\n"
            f"Mission: {goal}\n"
            f"Evidence (only factual basis allowed):\n{json.dumps(evidence, indent=2, default=str)}\n"
            f"Policy engine outcome: {conclusion}\nConfidence: {confidence:.2f}\n"
            f"Rules fired: {json.dumps(decision_rules)}\n\n"
            "Write the audit-facing rationale in 4-7 sentences. Introduce no new facts, "
            "do not change the outcome, and state what the human reviewer must verify."
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        tokens = getattr(response.usage, "total_tokens", 0) if response.usage else 0
        return Reasoning(narrative=text.strip(), engine=self.engine, tokens=tokens)


_fallback = DeterministicReasoner()
_active: object | None = None


def get_reasoner():
    """Resolve the configured engine, degrading to deterministic on any problem."""
    global _active
    if _active is not None:
        return _active

    provider = (settings.llm_provider or "deterministic").lower()
    try:
        if provider == "anthropic" and settings.anthropic_api_key:
            _active = AnthropicReasoner(settings.anthropic_api_key, settings.anthropic_model)
        elif provider == "openai" and settings.openai_api_key:
            _active = OpenAIReasoner(settings.openai_api_key, settings.openai_model)
        else:
            _active = _fallback
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("LLM provider %s unavailable (%s); using deterministic reasoner", provider, exc)
        _active = _fallback
    return _active


def reason(**kwargs) -> Reasoning:
    engine = get_reasoner()
    try:
        return engine.reason(**kwargs)
    except Exception as exc:  # pragma: no cover - network/runtime failure
        logger.warning("Reasoning engine failed (%s); falling back to deterministic", exc)
        return _fallback.reason(**kwargs)


def engine_status() -> dict:
    engine = get_reasoner()
    return {
        "configured_provider": settings.llm_provider,
        "active_engine": getattr(engine, "engine", "deterministic"),
        "model": (
            settings.anthropic_model
            if getattr(engine, "engine", "") == "anthropic"
            else settings.openai_model
            if getattr(engine, "engine", "") == "openai"
            else "built-in rule engine"
        ),
        "offline_capable": getattr(engine, "engine", "deterministic") == "deterministic",
        "note": (
            "Decisions always come from the deterministic policy engine. "
            "The language model, when enabled, only narrates the rationale."
        ),
    }
