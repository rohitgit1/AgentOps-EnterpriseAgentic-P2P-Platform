"""Agent framework.

Implements the lifecycle from the specification — plan / execute / observe /
reason / escalate / report — with one non-negotiable rule bolted into the base
class: **an agent cannot mutate the system of record.**

`run()` produces observations and `ProposedAction`s. Each proposal goes through
the policy engine; the outcome is either a HumanTask checkpoint (the normal
path) or, only if every guardrail opens, a policy-logged auto-execution. Either
way the audit trail records who or what decided, on what evidence, and why.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import (
    ACTION_LABELS,
    ActionKind,
    AgentRunStatus,
    AutonomyLevel,
    EventType,
    Role,
    WorkflowStage,
)
from ..models import AgentConfig, AgentExecution, HumanTask, User, utcnow
from ..services import hitl, llm, policy
from ..services.events import jsonable
from ..services.audit import write_audit
from ..services.events import record_event


# ==========================================================================
# Value objects
# ==========================================================================
@dataclass
class PlanStep:
    step: int
    action: str
    tool: str
    rationale: str

    def to_dict(self) -> dict:
        return {"step": self.step, "action": self.action, "tool": self.tool, "rationale": self.rationale}


@dataclass
class Observation:
    tool: str
    summary: str
    detail: Any = None
    ok: bool = True

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "summary": self.summary,
            "detail": self.detail,
            "ok": self.ok,
            "observed_at": utcnow().isoformat(),
        }


@dataclass
class ProposedAction:
    action_kind: str
    title: str
    summary: str
    payload: dict = field(default_factory=dict)
    diff_preview: list[dict] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    confidence: float = 0.9
    financial_impact_usd: float = 0.0
    stage: str = WorkflowStage.INTAKE
    entity_type: str | None = None
    entity_id: str | None = None
    entity_label: str | None = None
    due_in_hours: float = 8.0
    assigned_to_id: str | None = None
    extra_flags: list[str] = field(default_factory=list)


@dataclass
class AgentDecision:
    conclusion: str
    confidence: float
    decision_rules: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    proposals: list[ProposedAction] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: str | None = None
    handoff_to: str | None = None


@dataclass
class AgentRunResult:
    execution: AgentExecution
    tasks: list[HumanTask]
    auto_executed: list[dict]
    decision: AgentDecision


# ==========================================================================
# Base agent
# ==========================================================================
class BaseAgent:
    key: str = "base"
    name: str = "Base Agent"
    role: str = "Generic P2P agent"
    mission: str = ""
    goals: list[str] = []
    tools: list[str] = []
    skills: list[str] = []
    default_stage: str = WorkflowStage.INTAKE
    escalation_role: str = Role.AP_MANAGER
    default_autonomy: str = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold: float = 0.90
    max_auto_amount_usd: float = 0.0
    allowed_actions: list[str] = []

    # ---- lifecycle hooks the concrete agents implement --------------------
    def plan(self, db: Session, context: dict) -> list[PlanStep]:
        raise NotImplementedError

    def gather(self, db: Session, context: dict) -> list[Observation]:
        raise NotImplementedError

    def decide(self, db: Session, context: dict, observations: list[Observation]) -> AgentDecision:
        raise NotImplementedError

    def entity_ref(self, db: Session, context: dict) -> tuple[str | None, str | None, str | None]:
        """(entity_type, entity_id, entity_label) for the run header."""
        return (None, None, None)

    # ---- shared machinery -------------------------------------------------
    def run(
        self,
        db: Session,
        context: dict | None = None,
        *,
        trigger: str = "manual",
        triggered_by: str | None = None,
        parent_run_id: str | None = None,
    ) -> AgentRunResult:
        context = dict(context or {})
        started = time.perf_counter()

        config = policy.get_agent_config(db, self.key)
        if config is not None and not config.enabled:
            execution = self._new_execution(db, context, trigger, triggered_by, parent_run_id)
            execution.status = AgentRunStatus.BLOCKED_BY_POLICY
            execution.conclusion = f"{self.name} is disabled in the Agent Control Room."
            db.flush()
            record_event(
                db, event_type=EventType.AGENT_BLOCKED, title=f"{self.name} blocked",
                message=execution.conclusion, actor=self.name, actor_type="agent", severity="warning",
            )
            return AgentRunResult(execution, [], [], AgentDecision(execution.conclusion, 0.0))

        execution = self._new_execution(db, context, trigger, triggered_by, parent_run_id)
        record_event(
            db,
            event_type=EventType.AGENT_STARTED,
            title=f"{self.name} started",
            message=self.mission,
            entity_type=execution.entity_type,
            entity_id=execution.entity_id,
            entity_label=execution.entity_label,
            actor=self.name,
            actor_type="agent",
            payload={"run_number": execution.run_number, "agent_key": self.key},
        )

        try:
            # --- plan -------------------------------------------------------
            execution.status = AgentRunStatus.PLANNING
            steps = self.plan(db, context)
            execution.plan = jsonable([s.to_dict() for s in steps])
            db.flush()

            # --- execute / observe ------------------------------------------
            execution.status = AgentRunStatus.EXECUTING
            observations = self.gather(db, context)
            execution.observations = jsonable([o.to_dict() for o in observations])
            for obs in observations:
                record_event(
                    db,
                    event_type=EventType.AGENT_STEP,
                    title=f"{self.name} · {obs.tool}",
                    message=obs.summary,
                    entity_type=execution.entity_type,
                    entity_id=execution.entity_id,
                    entity_label=execution.entity_label,
                    actor=self.name,
                    actor_type="agent",
                    severity="info" if obs.ok else "warning",
                    payload={"run_number": execution.run_number, "tool": obs.tool},
                )
            db.flush()

            # --- reason ------------------------------------------------------
            decision = self.decide(db, context, observations)
            reasoning = llm.reason(
                agent_name=self.name,
                goal=self.mission,
                evidence=decision.evidence,
                conclusion=decision.conclusion,
                confidence=decision.confidence,
                decision_rules=decision.decision_rules,
            )
            execution.reasoning = reasoning.narrative
            execution.reasoning_engine = reasoning.engine
            execution.tokens_used = reasoning.tokens
            execution.conclusion = decision.conclusion
            execution.confidence = round(float(decision.confidence), 4)
            execution.evidence = jsonable(decision.evidence)
            execution.handoff_to = decision.handoff_to

            # --- escalate ----------------------------------------------------
            if decision.escalate:
                execution.escalated = True
                execution.escalation_reason = decision.escalation_reason
                self.escalate(db, execution, decision)

            # --- propose (policy gate) ---------------------------------------
            tasks: list[HumanTask] = []
            auto_executed: list[dict] = []
            policy_summaries: list[dict] = []

            for proposal in decision.proposals:
                verdict = policy.evaluate(
                    db,
                    agent_key=self.key,
                    action_kind=proposal.action_kind,
                    confidence=proposal.confidence,
                    financial_impact_usd=proposal.financial_impact_usd,
                    extra_flags=proposal.extra_flags,
                )
                policy_summaries.append(
                    {"action": str(proposal.action_kind), **verdict.to_dict()}
                )

                task = hitl.create_checkpoint(
                    db,
                    execution=execution,
                    agent_key=self.key,
                    agent_name=self.name,
                    stage=proposal.stage,
                    action_kind=proposal.action_kind,
                    title=proposal.title,
                    summary=proposal.summary,
                    rationale=reasoning.narrative,
                    policy=verdict,
                    confidence=proposal.confidence,
                    proposed_payload=jsonable(proposal.payload),
                    diff_preview=jsonable(proposal.diff_preview),
                    evidence=jsonable(decision.evidence),
                    alternatives=jsonable(proposal.alternatives),
                    entity_type=proposal.entity_type or execution.entity_type,
                    entity_id=proposal.entity_id or execution.entity_id,
                    entity_label=proposal.entity_label or execution.entity_label,
                    financial_impact_usd=proposal.financial_impact_usd,
                    due_in_hours=proposal.due_in_hours,
                    assigned_to_id=proposal.assigned_to_id,
                )
                tasks.append(task)

                if verdict.allow_auto_execute:
                    outcome = self._auto_execute(db, task)
                    if outcome is not None:
                        auto_executed.append(outcome)

            execution.policy_evaluation = {"proposals": policy_summaries}
            pending = [t for t in tasks if t.status == "pending"]
            execution.status = (
                AgentRunStatus.AWAITING_HUMAN if pending else AgentRunStatus.COMPLETED
            )
            execution.duration_ms = int((time.perf_counter() - started) * 1000)
            db.flush()

            self.report(db, execution, decision, tasks)
            return AgentRunResult(execution, tasks, auto_executed, decision)

        except Exception as exc:  # pragma: no cover - defensive
            execution.status = AgentRunStatus.FAILED
            execution.error = f"{type(exc).__name__}: {exc}"
            execution.duration_ms = int((time.perf_counter() - started) * 1000)
            db.flush()
            record_event(
                db, event_type=EventType.AGENT_FAILED, title=f"{self.name} failed",
                message=execution.error, actor=self.name, actor_type="agent", severity="critical",
                entity_type=execution.entity_type, entity_id=execution.entity_id,
            )
            raise

    # ---- hooks with sensible defaults -------------------------------------
    def escalate(self, db: Session, execution: AgentExecution, decision: AgentDecision) -> None:
        record_event(
            db,
            event_type=EventType.AGENT_STEP,
            title=f"{self.name} escalated",
            message=decision.escalation_reason or "Escalated for human judgement.",
            entity_type=execution.entity_type,
            entity_id=execution.entity_id,
            entity_label=execution.entity_label,
            actor=self.name,
            actor_type="agent",
            severity="warning",
        )

    def report(
        self,
        db: Session,
        execution: AgentExecution,
        decision: AgentDecision,
        tasks: list[HumanTask],
    ) -> None:
        config = policy.get_agent_config(db, self.key)
        if config is not None:
            config.runs_total += 1

        record_event(
            db,
            event_type=EventType.AGENT_COMPLETED,
            title=f"{self.name} · {len(tasks)} proposal(s) awaiting review"
            if tasks
            else f"{self.name} · no action required",
            message=decision.conclusion,
            entity_type=execution.entity_type,
            entity_id=execution.entity_id,
            entity_label=execution.entity_label,
            actor=self.name,
            actor_type="agent",
            severity="info",
            payload={
                "run_number": execution.run_number,
                "confidence": execution.confidence,
                "proposals": [
                    {"task_number": t.task_number, "action": t.action_kind, "title": t.title}
                    for t in tasks
                ],
            },
        )
        write_audit(
            db,
            action="agent.run_completed",
            description=f"{self.name} completed run {execution.run_number}: {decision.conclusion}",
            actor=self.name,
            actor_type="agent",
            entity_type=execution.entity_type,
            entity_id=execution.entity_id,
            entity_label=execution.entity_label,
            agent_key=self.key,
            execution_id=execution.id,
            confidence=execution.confidence,
            after_state={
                "conclusion": decision.conclusion,
                "proposals": [str(p.action_kind) for p in decision.proposals],
            },
        )

    # ---- internals --------------------------------------------------------
    def _new_execution(
        self,
        db: Session,
        context: dict,
        trigger: str,
        triggered_by: str | None,
        parent_run_id: str | None,
    ) -> AgentExecution:
        count = db.execute(select(func.count(AgentExecution.id))).scalar_one() or 0
        entity_type, entity_id, entity_label = self.entity_ref(db, context)
        execution = AgentExecution(
            run_number=f"RUN-{count + 10001}",
            agent_key=self.key,
            agent_name=self.name,
            trigger=trigger,
            triggered_by=triggered_by,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            status=AgentRunStatus.QUEUED,
            goal=self.mission,
            parent_run_id=parent_run_id,
        )
        db.add(execution)
        db.flush()
        return execution

    def _auto_execute(self, db: Session, task: HumanTask) -> dict | None:
        """Apply an action that cleared every guardrail.

        Never reachable while global HITL enforcement is on — kept so the
        governance story is demonstrable end-to-end ("turn the switch off and
        watch what changes").
        """
        system_actor = db.execute(
            select(User).where(User.role == Role.ADMIN)
        ).scalars().first()
        if system_actor is None:
            return None
        try:
            result = hitl.execute_action(db, task=task, payload=task.proposed_payload or {}, actor=system_actor)
        except Exception as exc:  # pragma: no cover - defensive
            task.execution_error = str(exc)
            return None
        task.status = "approved"
        task.decision = "approve"
        task.decided_by = f"{self.name} (auto · within guardrails)"
        task.decided_by_role = "agent"
        task.decided_at = utcnow()
        task.applied_payload = task.proposed_payload
        task.execution_result = result
        write_audit(
            db,
            action="agent.auto_executed",
            description=f"{self.name} auto-executed '{ACTION_LABELS.get(str(task.action_kind), task.action_kind)}' "
                        f"inside the policy envelope.",
            actor=self.name,
            actor_type="agent",
            entity_type=task.entity_type,
            entity_id=task.entity_id,
            entity_label=task.entity_label,
            agent_key=self.key,
            human_task_id=task.id,
            confidence=task.confidence,
            hitl_enforced=False,
            after_state=result,
        )
        return {"task_number": task.task_number, "result": result}

    # ---- descriptor -------------------------------------------------------
    def describe(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "role": self.role,
            "mission": self.mission,
            "goals": self.goals,
            "tools": self.tools,
            "skills": self.skills,
            "default_stage": str(self.default_stage),
            "default_autonomy": str(self.default_autonomy),
            "escalation_role": str(self.escalation_role),
            "allowed_actions": [str(a) for a in self.allowed_actions],
            "prompt": self.prompt_template(),
        }

    def prompt_template(self) -> str:
        goals = "\n".join(f"{i}. {g}" for i, g in enumerate(self.goals, start=1))
        tools = "\n".join(f"- {t}" for t in self.tools)
        return (
            f"You are the {self.name}.\n\n"
            f"Mission:\n{self.mission}\n\n"
            f"You have access to:\n{tools}\n\n"
            f"Goals:\n{goals}\n\n"
            "Decision Rules:\n"
            "- Never mutate a system of record directly; propose an action for human review.\n"
            "- Prefer the least invasive action that resolves the issue.\n"
            "- Escalate when confidence falls below the governance floor.\n"
            "- Cite every fact you rely on.\n\n"
            "Output:\nAction\nReasoning\nConfidence\nAudit Record"
        )

    def default_config(self) -> dict:
        return {
            "agent_key": self.key,
            "display_name": self.name,
            "autonomy_level": str(self.default_autonomy),
            "confidence_threshold": self.default_confidence_threshold,
            "max_auto_amount_usd": self.max_auto_amount_usd,
            "escalation_role": str(self.escalation_role),
            "allowed_actions": [str(a) for a in self.allowed_actions],
            "notes": self.role,
        }


def evidence_item(label: str, detail: Any, source: str = "") -> dict:
    return {"label": label, "detail": detail, "source": source or label}
