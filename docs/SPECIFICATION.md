# AgentOps — Enterprise Agentic P2P & Procurement Platform
## Application Specification

**Version 1.1.0** · Specification of record for the system as built.

This document specifies the whole platform: what it guarantees, how it is
layered, every enumerated value the system reasons over, the data model, the
governance machinery, the API surface, and the operational envelope. It is
written to be sufficient on its own — someone with this document and
[`agents/`](../agents/README.md) can rebuild the system without reading the
source.

| Companion document | What it covers |
|---|---|
| [`agents/README.md`](../agents/README.md) | One build specification per agent — 16 documents |
| [`skills/README.md`](../skills/README.md) | The 28 shared skills and their contracts |
| [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) | Layer diagram and request flow |
| [`docs/HITL.md`](./HITL.md) | The human-in-the-loop guarantees in narrative form |
| [`docs/PROCUREMENT.md`](./PROCUREMENT.md) | The procurement suite and the document pipeline |
| [`RUNNING.md`](../RUNNING.md) | Local launch, configuration, troubleshooting |

---

## 1 · What this system is

An agentic automation platform for the procure-to-pay and strategic procurement
lifecycle, built so that **no agent can change a system of record**. Sixteen
agents across two suites analyse work and produce *proposals*; qualified humans
decide; every decision is written to a hash-chained audit trail.

The automation is real — extraction, matching, duplicate detection, risk
scoring, spend classification, clause analysis, bid evaluation. The authority is
not delegated. That separation is the product.

### 1.1 The central invariant

> **An agent returns proposals, never mutations.**

This is structural, not a convention:

- `BaseAgent.decide()` returns an `AgentDecision` containing `ProposedAction`
  objects. A `ProposedAction` is a dataclass. It has no database session, no
  ORM object and no executor reference.
- The only consumer of a `ProposedAction` is `hitl.create_checkpoint()`, which
  writes a `HumanTask` row and nothing else.
- The only code that writes to a business table is an executor registered with
  `@action(...)` in `services/hitl.py`, and the only caller of an executor is
  `hitl.execute_action()`, reached exclusively from `hitl.decide()` after an
  authority check.

There is no code path from an agent to a business table. An agent that wanted to
write to one would have to be rewritten to do so.

### 1.2 What the system guarantees

| Guarantee | Mechanism | Where enforced |
|---|---|---|
| No agent writes business data | Proposals are inert dataclasses; executors are reachable only through an approved checkpoint | `agents/base.py`, `services/hitl.py` |
| Every proposal is gated | Seven-gate, default-deny policy engine evaluated per proposal | `services/policy.py` |
| Irreversible actions always stop | 12 action kinds bypass every autonomy setting | `enums.IRREVERSIBLE_ACTIONS` |
| Authority is enforced, not advisory | Role ladder + per-action minimum + value-based escalation + dual approval | `services/hitl.decide()`, `api/deps.py` |
| The record cannot be edited silently | `sha256(previous_hash ‖ canonical_payload)` chain, verifiable by replay | `services/audit.py`, `GET /api/audit/verify` |
| A generated document is not final | Outputs are born `draft`; released only by the approval of the checkpoint that owns them | `services/artifacts.py` |
| Reasoning does not change outcomes | The policy engine decides; the language model only narrates | `services/llm.py` |

### 1.3 What it is not

- **Not an ERP.** It proposes ERP postings; the posting adapters are simulated.
- **Not an OCR system.** PDF handling reads the embedded text layer only. A
  production deployment substitutes Azure Document Intelligence or Textract
  behind the same skill interface.
- **Not authenticated.** Personas are *selected*, not authenticated. Role
  **authority** is fully enforced server-side; identity is not. Production puts
  SSO in front of `get_current_user` and changes nothing else.

---

## 2 · Architecture

### 2.1 Layers

```
React 18 + TypeScript + Tailwind (Vite SPA, 22 screens) · SSE activity stream
                              │ /api
FastAPI gateway — auth · core · hitl · agents · procurement · analytics
                  · admin · explain.   Authority enforced at the dependency layer.
                              │
Agent Orchestrator — stage-driven state machine. Runs the agent that owns an
invoice's stage and follows hand-offs until a human checkpoint blocks progress.
        │                                       │
16 Agents                              Policy Engine — 7 gates, default deny.
plan/execute/observe/          ──────▶ Produces an explained verdict recorded
reason/escalate/report                 with every proposal.
        │                                       │
28 Shared Skills                       HITL Checkpoint Service
                                       create_checkpoint / decide / execute_action
                                              │
Hash-chained Audit Trail + Workflow Event log + Artifact lifecycle
                                              │
ERP Integration Layer — SAP S/4HANA · Oracle Fusion · Coupa · Ariba
(one protocol, simulated adapters)
                                              │
Data Layer — SQLAlchemy 2.0. SQLite by default, PostgreSQL via P2P_DATABASE_URL.
```

### 2.2 Technology

| Concern | Choice | Note |
|---|---|---|
| API | FastAPI | OpenAPI at `/api/docs` |
| ORM | SQLAlchemy 2.0 | Backend-agnostic models; no migration step |
| Database | SQLite (default) / PostgreSQL | `P2P_DATABASE_URL` switches; schema is identical |
| Frontend | React 18 · TypeScript · Tailwind · Recharts · Vite | Built to `frontend/dist`, served by the API on one port |
| Live updates | Server-Sent Events | `GET /api/events/stream` |
| Reasoning | Deterministic by default | `P2P_LLM_PROVIDER=anthropic\|openai` enables narration only |
| Packaging | `run.sh` / `run.ps1` / Docker | Single command, zero external services |

### 2.3 The run loop

`BaseAgent.run()` is the same for every agent:

1. **Resolve attachments.** `context["attachment_ids"]` is parsed through
   `artifacts.load_for_agent()` into `context["attachments"]`.
2. **Check the config.** A disabled agent returns `blocked_by_policy` without
   running.
3. **Plan.** `plan()` returns `PlanStep`s. Persisted to `agent_executions.plan`.
4. **Execute / observe.** `gather()` returns `Observation`s. Each is persisted
   and emitted to the event stream as it happens.
5. **Reason.** `decide()` returns an `AgentDecision`. `llm.reason()` narrates it.
6. **Escalate.** If the decision escalates, an event is recorded. Escalation
   annotates; it does not change what a human is asked to decide.
7. **Propose.** Each `ProposedAction` is evaluated by `policy.evaluate()` and
   becomes a `HumanTask`. The verdict is stored on the task.
8. **Report.** An audit entry and a completion event.

Every step is persisted, so a run is reconstructable months later: the plan it
made, each tool and what came back, the evidence it cited, its confidence, and
the policy verdict on every proposal.

### 2.4 Concurrency and consistency

One SQLAlchemy session per request, committed at the end of the request. Agent
runs are synchronous within a request; the orchestrator's fleet sweep runs
agents sequentially within one transaction, so a sweep either lands whole or not
at all. The event stream is read-only and derived.

---

## 3 · Domain model

29 tables in seven domains. The **Data Model** screen (`/data-model`) renders
this live from SQLAlchemy metadata with row counts read at request time.

| Domain | Tables |
|---|---|
| **People & Authority** | `users` |
| **Master Data** | `suppliers`, `purchase_orders`, `po_lines`, `receipts`, `contracts` |
| **P2P Transactions** | `invoices`, `invoice_lines`, `exceptions`, `approvals`, `payments`, `purchase_requests`, `supplier_messages` |
| **Procurement** | `sourcing_events`, `sourcing_bids`, `spend_transactions`, `savings_opportunities`, `risk_assessments`, `contract_drafts`, `tail_spend_findings` |
| **Agent Control Plane** | `agent_configs`, `agent_executions`, `human_tasks`, `policy_rules` |
| **Documents** | `artifacts` |
| **Assurance** | `audit_logs`, `workflow_events`, `sla_risks`, `notifications` |

**Agents write only to `agent_executions`, `human_tasks` and `artifacts`.**
Every other table is written by an approved checkpoint.

### 3.1 The tables that carry the guarantees

**`human_tasks`** — the checkpoint. An agent's only way to express intent. Holds
the proposed payload, the policy verdict, the diff preview, the alternatives,
the evidence, the required role, and — after a decision — the applied payload
and who decided. Nothing in the business tables changes until a row here is
approved.

**`agent_executions`** — one agent run: its plan, every observation, the
evidence, the confidence, the reasoning narrative and engine, the policy
evaluation. This is what makes a decision reconstructable.

**`audit_logs`** — append-only and hash-chained. Each row's `hash` covers the
previous row's, so any retroactive edit breaks the chain and is detectable by
replay.

**`artifacts`** — one table, two directions. `direction=input` for uploaded
attachments, `direction=output` for agent deliverables. An output is born
`status=draft` and becomes `released` only when a human approves the checkpoint
that owns it.

**`policy_rules`** — policy-as-code. Tolerances, thresholds and the master HITL
switch are rows here, read on every proposal. Changing governance is a data
change, not a deploy.

### 3.2 A note on two primary keys

`workflow_events` and `audit_logs` use an **integer primary key `sequence`** with
a separate unique string `id`. This is not stylistic: SQLite only autoincrements
an integer *primary key*, so an `autoincrement=True` integer column that is not
the primary key silently produces `NULL` and violates the NOT NULL constraint on
insert. Both tables need a monotonic sequence — one for stream ordering, one for
chain verification — so the sequence is the primary key.

---

## 4 · Enumerations

Every value the system reasons over is enumerated. A rebuild must reproduce
these exactly; they are referenced by payloads, policies and the UI.

### 4.1 Suites

| Key | Label |
|---|---|
| `p2p` | P2P AgentOps — operational accounts payable, intake to payment |
| `procurement` | Procurement AgentOps — strategic sourcing, spend, risk, contracts, tail spend |

### 4.2 Roles and authority

| Role | Authority | May decide |
|---|---|---|
| `supplier` | 0 | Nothing — external party |
| `ap_clerk` | 10 | Extraction, matching, exceptions, supplier drafts |
| `procurement` | 20 | + contract breaches, purchase requests, sourcing, savings, dispositions |
| `treasury` | 20 | + payment scheduling |
| `ap_manager` | 30 | + ERP posting, escalations, reroutes, invoice approvals |
| `controller` | 40 | + payment release, supplier master changes, contract signature |
| `cfo` | 50 | Everything, including executive briefs |
| `admin` | 60 | + agent autonomy, governance switch, demo reset |

Authority is a **ladder, not a set**: a Controller can decide everything a clerk
can. `ROLE_AUTHORITY` is the ordering; `ACTION_MIN_ROLE` is the floor per action.

### 4.3 Workflow stages

`intake → extraction_review → validation → matching → exception → approval →
payment → posted → closed`, plus the terminal `rejected`.

The orchestrator maps a stage to the agent that owns it.

### 4.4 Autonomy levels

| Level | Meaning |
|---|---|
| `observe_only` | L0 — analyses, proposes nothing |
| `suggest` | L1 — proposes; every proposal waits |
| `human_approval` | L2 — proposes; every proposal waits. **The default for all 16 agents.** |
| `auto_within_guardrails` | L3 — may auto-execute inside the financial ceiling, if global enforcement is off |
| `full_auto` | L4 — disabled while global HITL enforcement is on |

### 4.5 Action kinds

33 action kinds. **12 are irreversible** and always require a human, at any
autonomy level, with enforcement off:

```
post_to_erp · schedule_payment · release_payment · block_supplier
update_supplier_master · send_supplier_message · approve_purchase_request
issue_rfp · award_sourcing_event · issue_contract_for_signature
consolidate_suppliers · publish_executive_brief
```

The reasoning is uniform: each one reaches outside the system — a ledger, a bank,
a supplier, a signature, a boardroom — and cannot be taken back by editing a row.

Minimum approver per action is declared in `ACTION_MIN_ROLE` and rendered in each
agent's build specification.

---

## 5 · Governance

### 5.1 The seven gates

`policy.evaluate()` returns a fully explained `PolicyDecision`.
`allow_auto_execute=True` requires **every** gate to open; anything else stops at
a `HumanTask`. Default deny.

| # | Gate | Opens when |
|---|---|---|
| 1 | Global HITL enforcement | `hitl.enforce_global` is off |
| 2 | Agent autonomy | The agent is at L3 or above |
| 3 | Irreversibility | The action is not in `IRREVERSIBLE_ACTIONS` |
| 4 | Confidence | Proposal confidence ≥ the agent's threshold |
| 5 | Financial envelope | Impact ≤ the agent's `max_auto_amount_usd` |
| 6 | Risk level | Computed risk is not high or critical |
| 7 | Action allow-list | The action is in the agent's permitted set |

Every gate that blocks records **why**, and the reason is stored on the task and
shown to the reviewer. A checkpoint always explains itself.

### 5.2 Value-based escalation

On top of the per-action minimum role:

| Financial impact | Effect |
|---|---|
| ≥ 50,000 USD | Minimum approver raised to Controller (flag `controller_threshold`) |
| ≥ 250,000 USD | Minimum approver raised to CFO (flag `cfo_threshold`) |
| ≥ `hitl.dual_approval_above` (default 100,000 USD) **and irreversible** | Two **distinct** approvers required (flag `dual_approval`) |

Dual approval compares `user.id`, not role — the same person approving twice is
one approval.

### 5.3 The five decisions

A reviewer may `approve`, `reject`, `modify_and_approve`, `request_info`, or
`escalate`. `modify_and_approve` executes the reviewer's edited payload, and both
the proposed and the applied payload are retained, so a later reader can see what
the agent asked for *and* what the human actually did.

### 5.4 Policy-as-code

15 seeded rules in `policy_rules`, editable from the Governance screen:

| Key | Default | Category |
|---|---|---|
| `hitl.enforce_global` | `true` | governance |
| `hitl.confidence_floor` | `0.90` | governance |
| `hitl.dual_approval_above` | `100000` | governance |
| `match.amount_variance_pct` | `3.0` | matching |
| `match.quantity_variance_pct` | `2.0` | matching |
| `match.amount_variance_abs` | `50.0` | matching |
| `intake.duplicate_similarity` | `0.92` | intake |
| `sla.invoice_cycle_hours` | `24` | sla |
| `sla.approval_reminder_hours` | `48` | sla |
| `sla.approval_escalation_hours` | `72` | sla |
| `sla.exception_resolution_hours` | `24` | sla |
| `procurement.auto_approve_under` | `5000` | procurement |
| `procurement.manager_review_under` | `10000` | procurement |
| `payment.max_auto_release` | `0` | payment |
| `risk.bank_change_freeze_days` | `10` | risk |

### 5.5 The audit chain

Each `audit_logs` row stores `hash = sha256(previous_hash ‖ canonical_payload)`.
`GET /api/audit/verify` replays the chain from genesis and reports the first
divergence. Editing any historical row — including through the database
directly — breaks verification at that row.

Every entry records the actor and whether they were human or agent, the entity,
the before and after state, the agent key and execution, the confidence, and
whether HITL enforcement was on at the time.

### 5.6 What "enforcement off" actually does

Turning off `hitl.enforce_global` opens gate 1 only. Gates 2–7 still apply, so
an L2 agent still stops, an irreversible action still stops, a low-confidence
proposal still stops, and an over-ceiling amount still stops. The switch exists
so the governance story is demonstrable end-to-end, not as a bypass.

---

## 6 · The agent fleet

16 agents. Each has a full build specification in
[`agents/<key>/AGENT.md`](../agents/README.md).

### 6.1 P2P AgentOps — 10 agents

| Agent | Owns | Proposes |
|---|---|---|
| Invoice Intake | `intake`, `extraction_review` | field corrections, stage advance, exceptions, holds |
| Three-Way Match | `matching` | stage advance, exceptions, receipt chases, holds |
| Approval Acceleration | `approval` | routing, reminders, escalations, reassignment |
| Exception Resolution | `exception` | resolutions, supplier messages, receipt chases, holds |
| Supplier Experience | inbound correspondence | supplier message drafts |
| Payment Readiness | `payment` | ERP posting, scheduling, release, holds |
| Supplier Risk | vendor master | blocks, holds, exceptions, document chases |
| Procurement Request | purchase requests | request approval routing |
| Contract Intelligence | billing vs contract | breach flags, exceptions, recovery messages |
| SLA Command Center | portfolio | workload rebalancing, executive alerts, escalations |

### 6.2 Procurement AgentOps — 6 agents

| Agent | Owns | Proposes |
|---|---|---|
| Sourcing Event | RFP → award | issue RFP, award event |
| Spend Analytics | the spend cube | publish classification, log savings |
| Supplier Risk & Compliance | four-domain scorecard | supplier disposition |
| Contract Lifecycle | contract paper | draft contract, issue for signature |
| Tail Spend | the long tail | consolidate suppliers, enforce catalogue |
| Procurement Command Center | executive KPIs | publish executive brief |

### 6.3 The shared framework

Every agent subclasses `BaseAgent` and implements exactly three methods:
`plan()`, `gather()`, `decide()`. Everything else — execution, persistence,
event emission, policy evaluation, checkpoint creation, auditing — is the base
class, which is why the guarantees hold uniformly.

Declared class attributes form the contract: `key`, `name`, `suite`, `role`,
`mission`, `goals`, `tools`, `skills`, `default_stage`, `escalation_role`,
`default_autonomy`, `default_confidence_threshold`, `max_auto_amount_usd`,
`allowed_actions`, `inputs`, `outputs`.

---

## 7 · Skills

28 shared skills in `backend/app/skills/`, each with a declared contract in
[`skills/<name>/SKILL.md`](../skills/README.md). A skill analyses and returns
evidence. It never mutates a system of record — whatever it returns becomes
evidence attached to a proposal.

Notable published constants a rebuild must reproduce:

| Constant | Value | Module |
|---|---|---|
| Supplier auto-resolve floor | `0.85` | `supplier_lookup` |
| Bid evaluation weights | commercial `0.45` / technical `0.35` / risk `0.20` | `sourcing` |
| Supplier risk composite | financial `0.30` / operational `0.25` / compliance `0.30` / ESG `0.15` | `strategic_risk` |
| Payment tier weights | platinum `25` / gold `18` / silver `10` / bronze `5` | `payment_prioritization` |
| Pareto head cut | `0.80` of cumulative spend | `tail_spend` |
| Cluster materiality floor | `4,000` USD | `tail_spend` |
| Modelled consolidation rate | `0.11` | `tail_spend` |

---

## 8 · Documents

### 8.1 The lifecycle

```
human uploads              agent reads               agent writes
 attachment    ──parsed──▶   gather()    ──produces──▶  deliverable
 direction=input             decide()                   direction=output
                                 │                      status=DRAFT
                                 ▼                            │
                            HumanTask ◀────────linked─────────┘
                            checkpoint
                                 │ approved by a qualified human
                                 ▼
                            status = RELEASED
```

A generated document is **never final on creation**. Rejecting the checkpoint
leaves the files as drafts — they stay in the artifact library as evidence of
what was considered, but nothing was issued. The same guarantee that stops an
agent writing to the ledger stops it issuing a document.

### 8.2 Parsing

| Format | Treatment |
|---|---|
| `.csv` / `.tsv` | Parsed to rows plus a field list; the agent sees typed records |
| `.json` | Parsed to records |
| `.md` / `.txt` | Full text |
| `.pdf` | **Embedded text layer only** — no OCR engine is bundled |

An unreadable attachment degrades to raw text with a stated reason rather than
raising, so an agent can report *"I could not read this"* instead of crashing.

---

## 9 · API

Full OpenAPI at `/api/docs`. Authentication is a persona id in `X-User-Id` or a
bearer token carrying the same value.

| Group | Endpoints |
|---|---|
| **Auth** | `GET /auth/personas` · `POST /auth/login` · `GET /auth/me` · `GET /auth/notifications` |
| **Core** | `GET /dashboard` · `/invoices` · `/exceptions` · `/approvals` · `/payments` · `/suppliers` · `/slas` · `POST /invoices/process` · `POST /invoices/upload` |
| **HITL** | `GET /hitl/tasks` · `GET /hitl/summary` · **`POST /hitl/tasks/{id}/decide`** |
| **Agents** | `GET /agents` · `GET /agents/status` · `POST /agents/{key}/run` · `POST /orchestrator/sweep` · `GET /agent-io` |
| **Procurement** | `/procurement/dashboard` · `/sourcing-events` · `/spend` · `/savings` · `/risk-assessments` · `/contract-drafts` · `/tail-spend` |
| **Artifacts** | `POST /artifacts/upload` · `GET /artifacts/{id}` · `GET /artifacts/{id}/download` |
| **Assurance** | `GET /audit` · `GET /audit/verify` · `GET /audit/export` · `GET /events/stream` |
| **Governance** | `GET /admin/policies` · `PATCH /admin/policies/{key}` · `GET /admin/governance` · `PATCH /agents/{key}/config` |
| **Explainers** | `GET /data-model` · `GET /academy` · `GET /academy/{agent_key}` |

**`POST /api/hitl/tasks/{id}/decide` is the only route through which an agent's
proposal can reach a system of record.** Everything else reads, proposes, or
configures.

---

## 10 · User interface

22 screens. Four are reference surfaces introspected from the running
application, so they cannot drift from the code they describe.

| Group | Screens |
|---|---|
| **P2P AgentOps** | Command Center · Approval Inbox · Invoices · Exceptions · My Approvals · Payments |
| **Procurement AgentOps** | Command Center · Sourcing Events · Spend & Savings · Supplier Risk · Contracts · Tail Spend |
| **Intelligence** | Agent Control Room · Agent I/O Catalogue · Artifact Library · SLA Command Center · Suppliers · Skills Library |
| **Assurance** | Audit Trail · Governance |
| **Under the Hood** | Agents Academy · Data Model |

The **Approval Inbox** is the heart of the platform: every pending proposal with
its evidence, its diff preview, its priced alternatives and the policy verdict
that sent it there.

### 10.1 A UI invariant worth preserving

The application header carries `relative z-40`, and it is load-bearing.
`backdrop-blur` puts a `backdrop-filter` on the header, which creates a stacking
context — so the persona dropdown's own `z-index` is confined inside it and
paints beneath page content. The overlay order is **header 40 < Drawer 50 <
Toast 60**. A rebuild that drops the explicit z-index reintroduces a bug where
the persona switcher renders behind the page.

A routed error boundary wraps every screen: a render failure degrades to a
readable message with the application still usable, rather than a blank page.

---

## 11 · Operations

### 11.1 Running

```bash
./run.sh                 # macOS / Linux — installs, builds, seeds, serves on :8000
./run.ps1                # Windows
docker compose up        # containerised
```

One process, one port, no external services. SQLite by default so a client demo
needs no database server.

### 11.2 Configuration

All settings are `P2P_`-prefixed environment variables or `.env` entries.

| Variable | Default | Effect |
|---|---|---|
| `P2P_DATABASE_URL` | SQLite file | `postgresql+psycopg://…` switches backend with no schema change |
| `P2P_LLM_PROVIDER` | `deterministic` | `anthropic` / `openai` enable narration only |
| `P2P_ENFORCE_HUMAN_IN_THE_LOOP` | `true` | The master switch |
| `P2P_AGENTS_PAUSED` | `false` | Fleet kill switch |
| `P2P_GLOBAL_CONFIDENCE_FLOOR` | `0.90` | Escalation floor |
| `P2P_SEED_ON_STARTUP` | `true` | Seed the demo dataset |
| `P2P_RESET_DATABASE_ON_STARTUP` | `false` | Rebuild from scratch each boot |

### 11.3 Testing

```bash
.venv/bin/python -m pytest backend/tests -q
```

58 tests over the policy gates, the irreversible-action rule across every
irreversible kind, role authority, dual approval, the audit hash chain, agent
lifecycles, the end-to-end intake → payment path, attachment parsing, the
attachment → agent → deliverable → release flow, and the two explainer surfaces.

Three are **drift guards** that fail the build rather than the demo:

- a new table that lands outside a data-model domain,
- a new agent that ships without an Academy lesson,
- a lesson field that should be a list arriving as something else.

### 11.4 Regenerating the documentation

```bash
python scripts/generate_skill_docs.py     # skills/<name>/SKILL.md
python scripts/generate_agent_specs.py    # agents/<key>/AGENT.md
```

Both are generated from the live code. The only hand-written input is
`scripts/agent_build_notes.py`, which holds the reasoning that cannot be
extracted — branch conditions, thresholds, confidence formulas, escalation
triggers.

---

## 12 · Known limitations

- **Document extraction is text-driven.** Native binary PDFs use only their
  embedded text layer; no OCR engine is bundled.
- **ERP adapters are simulated.** They implement one protocol and record what
  they would have sent. The checkpoint, the authority check and the audit entry
  around them are real.
- **Personas are selected, not authenticated.** Role authority is fully
  enforced; identity is not.
- **The reasoner is deterministic by default.** This is a feature for a demo —
  reproducible, offline, no key — and a limitation for production narration
  quality. The policy engine decides either way.
- **Row counts on the Data Model screen are `COUNT(*)` per table per request.**
  Cheap at demo scale, and it makes the model concrete rather than theoretical;
  it would need caching at production volume.

---

## 13 · Rebuilding this system

In dependency order:

1. **`enums.py`** — suites, roles and `ROLE_AUTHORITY`, stages, autonomy levels,
   the 33 action kinds, `IRREVERSIBLE_ACTIONS`, `ACTION_MIN_ROLE`,
   `ACTION_LABELS`, event types. Everything downstream references these.
2. **`models.py`** — the 29 tables of section 3. Note the integer-primary-key
   requirement on `workflow_events` and `audit_logs` (§3.2).
3. **`services/audit.py`** — the hash chain, before anything writes.
4. **`services/policy.py`** — the seven gates and the 15 default rules.
5. **`services/hitl.py`** — `create_checkpoint`, `decide`, and one executor per
   action kind registered with `@action(...)`. This is the *only* place business
   data is written.
6. **`services/artifacts.py`** — the draft → released lifecycle and the parsers.
7. **`agents/base.py`** — `IOSpec`, `PlanStep`, `Observation`, `ProposedAction`,
   `AgentDecision`, and `BaseAgent.run()`.
8. **`skills/`** — the 28 analysis capabilities.
9. **The 16 agents** — each from its own `agents/<key>/AGENT.md`.
10. **`api/`** — the routers of section 9, with authority enforced in `deps.py`.
11. **The frontend** — the screens of section 10.

**Check the rebuild against the invariant, not the feature list.** If an agent
can write to a business table, the system has the same screens and none of the
guarantees.
