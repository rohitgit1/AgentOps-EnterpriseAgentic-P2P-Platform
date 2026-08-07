# Architecture

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│  React 18 + TypeScript + Tailwind (Vite SPA, 12 screens)     │
│  Live activity via Server-Sent Events                        │
└───────────────────────────┬──────────────────────────────────┘
                            │  /api
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI gateway — auth · core · hitl · agents · analytics    │
│  · admin.  Role authority enforced at the dependency layer.   │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Agent Orchestrator — stage-driven state machine.             │
│  Runs the owning agent for an invoice's stage and follows     │
│  hand-offs until a human checkpoint blocks progress.          │
└───────┬───────────────────────────────────┬──────────────────┘
        │                                   │
┌───────▼──────────┐   ┌────────────────────▼─────────────────┐
│  10 Agents       │   │  Policy Engine — 7 gates, default    │
│  plan/execute/   │──▶│  deny. Produces an explained verdict │
│  observe/reason/ │   │  recorded with every proposal.       │
│  escalate/report │   └────────────────────┬─────────────────┘
└───────┬──────────┘                        │
        │                     ┌─────────────▼──────────────────┐
┌───────▼──────────┐          │  HITL Checkpoint Service       │
│  12 Shared       │          │  create_checkpoint / decide /  │
│  Skills          │          │  execute_action (allow-list)   │
└──────────────────┘          └─────────────┬──────────────────┘
                                            │
┌───────────────────────────────────────────▼──────────────────┐
│  Immutable hash-chained Audit Trail + Workflow Event log      │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  ERP Integration Layer — SAP S/4HANA · Oracle Fusion ·        │
│  Coupa · Ariba (one protocol, simulated adapters)             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Data Layer — SQLAlchemy 2.0. SQLite by default,              │
│  PostgreSQL via P2P_DATABASE_URL. No schema change needed.    │
└──────────────────────────────────────────────────────────────┘
```

## Request flow: an invoice arrives

1. `POST /api/invoices/process` writes the `Invoice` row and emits
   `invoice.received` on the event bus.
2. The orchestrator resolves the stage owner (`intake → invoice_intake`) and
   calls `BaseAgent.run()`.
3. The agent **plans** (persisted), **executes** its skills and records every
   **observation**, then **decides** — producing a conclusion, a confidence, the
   evidence it cited, and zero or more `ProposedAction`s.
4. The **reasoner** narrates the rationale. Deterministic by default; the LLM,
   when enabled, may only explain — never change the outcome.
5. Each proposal goes through `policy.evaluate()`. The verdict is stored on the
   execution so the decision is explainable later.
6. `hitl.create_checkpoint()` writes a `HumanTask`, emits `hitl.task_created`,
   notifies the required role, and writes an audit record. **The invoice has not
   changed.**
7. The orchestrator halts — an open checkpoint blocks all further agent work on
   that entity.
8. A qualified human calls `POST /api/hitl/tasks/{id}/decide`. On approval,
   `execute_action()` looks up the registered handler and applies the payload,
   then writes the audit record with before/after state.

## Concurrency and consistency

- Each agent run is one transaction; the orchestrator commits between hops.
- An entity with a pending checkpoint is inert to agents, which removes the
  agent-vs-agent race entirely.
- Dual approval is enforced by requiring two distinct `user.id` values on the
  same task.
- The audit chain is append-only and ordered by an integer primary key, so
  verification is a linear replay.

## Swapping the demo pieces for production ones

| Demo component | Production replacement | Change surface |
|---|---|---|
| SQLite | PostgreSQL + pgvector | one env var |
| In-process `EventBus` | Kafka / Azure Event Hub | `EventBus.publish()` |
| Simulated ERP adapters | Live SAP/Oracle/Coupa/Ariba clients | implement `ERPConnector` |
| Deterministic reasoner | Claude / GPT narration | `P2P_LLM_PROVIDER` |
| Regex extraction skill | Azure Document Intelligence / Textract | `skills/invoice_extraction.extract()` |
| Persona selection | SSO / OIDC | `api/deps.get_current_user` |

No agent, policy or HITL code changes in any row of that table — which is the
point of the layering.

## Data model

Transactional: `Invoice`, `InvoiceLine`, `PurchaseOrder`, `POLine`, `Receipt`,
`Supplier`, `Contract`, `Payment`, `ExceptionCase`, `Approval`,
`PurchaseRequest`, `SupplierMessage`, `User`.

Control plane: `AgentConfig` (autonomy governance), `AgentExecution` (the run
record), `HumanTask` (the checkpoint), `PolicyRule` (policy-as-code),
`AuditLog` (hash-chained), `WorkflowEvent` (the stream), `SLARisk`,
`Notification`.
