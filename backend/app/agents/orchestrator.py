"""Agent orchestrator.

A stage-driven state machine (the LangGraph role in the reference architecture)
that decides which agent owns an invoice at its current stage, and hands off
between agents — but only ever up to the next human checkpoint.

The invariant the orchestrator preserves: an invoice advances a stage **only**
because a human approved the proposal that advances it. The orchestrator can
therefore run freely without ever losing human control.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import EventType, ExceptionStatus, HumanTaskStatus, WorkflowStage
from ..models import ExceptionCase, HumanTask, Invoice, SupplierMessage
from ..services.events import record_event
from .base import AgentRunResult
from .registry import AGENTS, get_agent

# Which agent owns an invoice at each stage.
STAGE_OWNER: dict[str, str] = {
    WorkflowStage.INTAKE: "invoice_intake",
    WorkflowStage.EXTRACTION_REVIEW: "invoice_intake",
    WorkflowStage.VALIDATION: "invoice_intake",
    WorkflowStage.MATCHING: "three_way_match",
    WorkflowStage.EXCEPTION: "exception_resolution",
    WorkflowStage.APPROVAL: "approval_acceleration",
    WorkflowStage.PAYMENT: "payment_readiness",
}


class Orchestrator:
    def next_agent_for(self, invoice: Invoice) -> str | None:
        return STAGE_OWNER.get(str(invoice.stage))

    def pending_checkpoints(self, db: Session, invoice_id: str) -> int:
        return len(
            db.execute(
                select(HumanTask).where(
                    HumanTask.entity_id == invoice_id,
                    HumanTask.status == HumanTaskStatus.PENDING,
                )
            ).scalars().all()
        )

    def advance_invoice(
        self,
        db: Session,
        invoice_id: str,
        *,
        triggered_by: str | None = None,
        max_hops: int = 4,
    ) -> list[AgentRunResult]:
        """Run the owning agent for the invoice's current stage, then follow
        hand-offs until a human checkpoint blocks further progress."""
        results: list[AgentRunResult] = []
        seen: set[str] = set()

        for _ in range(max_hops):
            invoice = db.get(Invoice, invoice_id)
            if invoice is None:
                break

            if self.pending_checkpoints(db, invoice_id):
                record_event(
                    db,
                    event_type=EventType.SYSTEM,
                    title="Workflow paused for human review",
                    message=f"{invoice.invoice_number} is waiting on an open approval checkpoint.",
                    entity_type="invoice",
                    entity_id=invoice.id,
                    entity_label=invoice.invoice_number,
                    actor="Orchestrator",
                    actor_type="system",
                )
                break

            agent_key = self.next_agent_for(invoice)
            if agent_key is None or agent_key in seen:
                break
            seen.add(agent_key)

            agent = get_agent(agent_key)
            if agent is None:
                break

            result = agent.run(
                db,
                {"invoice_id": invoice.id},
                trigger="orchestrator",
                triggered_by=triggered_by,
                parent_run_id=results[-1].execution.id if results else None,
            )
            results.append(result)

            if result.tasks:  # a human now owns the next move
                break

            handoff = result.decision.handoff_to
            if not handoff or handoff not in AGENTS or handoff in seen:
                break

        return results

    def run_exception_triage(
        self, db: Session, *, triggered_by: str | None = None, limit: int = 25
    ) -> list[AgentRunResult]:
        cases = db.execute(
            select(ExceptionCase)
            .where(ExceptionCase.status.in_([ExceptionStatus.OPEN, ExceptionStatus.AWAITING_HUMAN]))
            .order_by(ExceptionCase.created_at.asc())
            .limit(limit)
        ).scalars().all()

        agent = get_agent("exception_resolution")
        results = []
        for case in cases:
            existing = db.execute(
                select(HumanTask).where(
                    HumanTask.entity_id == case.id, HumanTask.status == HumanTaskStatus.PENDING
                )
            ).scalars().first()
            if existing is not None:
                continue
            results.append(
                agent.run(db, {"exception_id": case.id}, trigger="triage_sweep", triggered_by=triggered_by)
            )
        return results

    def run_supplier_inbox(
        self, db: Session, *, triggered_by: str | None = None, limit: int = 20
    ) -> list[AgentRunResult]:
        messages = db.execute(
            select(SupplierMessage)
            .where(SupplierMessage.direction == "inbound", SupplierMessage.status == "received")
            .order_by(SupplierMessage.created_at.asc())
            .limit(limit)
        ).scalars().all()

        agent = get_agent("supplier_experience")
        results = []
        for message in messages:
            results.append(
                agent.run(db, {"message_id": message.id}, trigger="inbox_sweep", triggered_by=triggered_by)
            )
            message.status = "answered_draft"
        return results

    def run_sweep(self, db: Session, *, triggered_by: str | None = None) -> dict:
        """The 'run the whole shop' action behind the Control Room button."""
        summary = {"invoices": 0, "runs": 0, "checkpoints": 0, "agents": []}

        invoices = db.execute(
            select(Invoice).where(
                Invoice.stage.notin_([WorkflowStage.CLOSED, WorkflowStage.POSTED, WorkflowStage.REJECTED])
            )
        ).scalars().all()
        for invoice in invoices:
            results = self.advance_invoice(db, invoice.id, triggered_by=triggered_by)
            if results:
                summary["invoices"] += 1
                summary["runs"] += len(results)
                summary["checkpoints"] += sum(len(r.tasks) for r in results)

        for key in ("supplier_risk", "sla_command_center"):
            agent = get_agent(key)
            if agent is None:
                continue
            result = agent.run(db, {}, trigger="sweep", triggered_by=triggered_by)
            summary["runs"] += 1
            summary["checkpoints"] += len(result.tasks)
            summary["agents"].append({"agent": key, "conclusion": result.decision.conclusion})

        record_event(
            db,
            event_type=EventType.SYSTEM,
            title="Fleet sweep completed",
            message=f"{summary['runs']} agent run(s) produced {summary['checkpoints']} "
                    f"checkpoint(s) awaiting human decision.",
            actor="Orchestrator",
            actor_type="system",
            severity="info",
            payload=summary,
        )
        return summary


orchestrator = Orchestrator()
