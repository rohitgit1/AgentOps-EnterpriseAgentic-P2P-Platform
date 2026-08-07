# P2P AgentOps

**Enterprise Agentic Procure-to-Pay Operations Platform**

Ten specialised AI agents run the accounts-payable shop end to end — intake,
matching, exceptions, approvals, supplier communication, payments, risk and SLA
forecasting. Every one of them **proposes**; a qualified human **decides**; the
decision is written to an immutable, hash-chained audit trail.

Runs entirely on your laptop with no cloud account, no API key and no database
server. One command, one port, a seeded demo dataset that tells a story.

```bash
./run.sh          # macOS / Linux
.\run.ps1         # Windows PowerShell
# → http://localhost:8000
```

📘 **[RUNNING.md](RUNNING.md)** — prerequisites, every launch path, configuration
reference and troubleshooting.
📗 **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)** — a 15-minute client walkthrough.
📕 **[docs/HITL.md](docs/HITL.md)** — how the human-in-the-loop guarantees are enforced.

---

## The controlling idea: agents cannot act

This is the design constraint the whole platform is built around, and it is
enforced structurally rather than by convention:

> An agent has **no write access to any system of record.** Its only output is a
> `HumanTask` — a proposal describing what it *would* change. The change happens
> when, and only when, someone with the required authority approves it.

Concretely:

| Mechanism | Where it lives | What it guarantees |
|---|---|---|
| Agents return `ProposedAction`s, never mutations | `backend/app/agents/base.py` | No code path lets an agent write business data |
| Explicit executor allow-list | `backend/app/services/hitl.py` | An action with no registered handler simply cannot happen |
| Seven-gate policy engine | `backend/app/services/policy.py` | Default-deny: auto-execution needs *every* gate to open |
| Irreversible-action rule | `backend/app/enums.py` | ERP posting, payment release, supplier messages and vendor-master edits **always** stop for a human — at any autonomy level |
| Role authority ladder | `backend/app/api/deps.py` | A clerk cannot release a payment however hard they click |
| Hash-chained audit log | `backend/app/services/audit.py` | Every record hashes the previous one; retroactive edits are detectable |

Open any checkpoint in the UI and the drawer answers the auditor's question
directly — **"Why is a human deciding this?"** — by listing the exact gates that
held the action, alongside the gates that opened.

### Human checkpoints exist at every stage

```
Intake → Extraction Review → Validation → 3-Way Match → Exception
       → Approval → ERP Posting → Payment Scheduling → Payment Release
   ▲          ▲            ▲           ▲          ▲         ▲          ▲
   └──────────┴────────────┴───────────┴──────────┴─────────┴──────────┘
                     a human decision is required at each
```

Outward-facing actions (supplier messages, reminders, escalations) are drafted
by agents and released by people — a supplier never receives unreviewed text.

---

## The ten agents

| # | Agent | Mission | Escalates to |
|---|---|---|---|
| 1 | **Invoice Intake** | Turn a document into a validated transaction; catch duplicates and unresolved suppliers | AP Manager |
| 2 | **Three-Way Match** | Reconcile Invoice ⇄ PO ⇄ Receipt line by line, price variance in dollars | AP Manager |
| 3 | **Approval Acceleration** | Reminder before escalation; reroute around out-of-office approvers | Controller |
| 4 | **Exception Resolution** | Diagnose the exception and propose the fix, with the alternatives priced | AP Manager |
| 5 | **Supplier Experience** | Answer enquiries from system-of-record facts only; never handle bank changes conversationally | AP Manager |
| 6 | **Payment Readiness** | Rank the payment run (`due_risk + supplier_tier + discount_value + sla_risk`) | Controller |
| 7 | **Supplier Risk** | Sanctions, insurance, tax forms, vendor-master change monitoring | Controller |
| 8 | **Procurement Request** | Apply the spend-authority ladder (5k / 10k / above) | Procurement |
| 9 | **Contract Intelligence** | Expired pricing, unauthorised charges, off-rate lines, missed volume discounts | Procurement |
| 10 | **SLA Command Center** | Forecast breaches, rebalance queues, raise executive alerts | Controller |

Each implements the specified lifecycle — `plan() → execute() → observe() →
reason() → escalate() → report()` — and each run persists its plan, every tool
observation, the evidence it cited, its confidence, and the policy verdict.

---

## Reasoning: deterministic by default

The platform ships with a **deterministic reasoner** as the default engine and
runs fully offline. That is deliberate, not a limitation:

- **Reproducible.** The same facts always produce the same narrative, so a demo
  never surprises you and an audit can be replayed.
- **Non-fabricating.** The narrative is templated strictly from observed
  evidence; it cannot invent an amount that no tool returned.
- **Decisions never come from a model.** The deterministic policy engine decides;
  the language model, when enabled, only *narrates the rationale*.

To enable live LLM narration, install the optional SDK and set:

```bash
export P2P_LLM_PROVIDER=anthropic
export P2P_ANTHROPIC_API_KEY=sk-ant-…
# or: P2P_LLM_PROVIDER=openai  P2P_OPENAI_API_KEY=…
```

The engine degrades back to deterministic on any error — the demo cannot break
because a network call failed.

---

## Architecture

```
React + TypeScript + Tailwind (Vite SPA)
                 │
        FastAPI API Gateway  ── SSE live event stream
                 │
        Agent Orchestrator (stage-driven state machine)
                 │
   ┌─────────────┼──────────────────────────────┐
   ▼             ▼                              ▼
 10 Agents   Policy Engine (7 gates)   HITL Checkpoint Service
   │             │                              │
   ▼             ▼                              ▼
 12 Shared Skills          Immutable hash-chained Audit Trail
                 │
        ERP Integration Layer (SAP S/4HANA · Oracle Fusion · Coupa · Ariba)
                 │
        Data Layer — SQLite by default, PostgreSQL-ready via SQLAlchemy
```

Event publishing is broker-shaped (`EventBus.publish`) so the in-process bus can
be swapped for Kafka or Azure Event Hub without touching agent code.

### Repository layout

```
backend/app/
  agents/      10 agents + base framework + orchestrator + registry
  skills/      12 shared skills, each with a declared contract
  services/    policy · hitl · audit · events · llm · erp · metrics
  api/         auth · core · hitl · agents · analytics · admin
  models.py    Invoice PO Receipt Supplier Contract Payment Exception
               Approval AuditLog AgentExecution WorkflowEvent SLARisk
               HumanTask AgentConfig PolicyRule …
  seed.py      the demo dataset
frontend/src/  React SPA — 12 screens
skills/        generated SKILL.md contracts (see scripts/generate_skill_docs.py)
docs/          ARCHITECTURE.md · DEMO_SCRIPT.md · HITL.md
```

---

## Running it

### One command

```bash
./run.sh
```

Creates a virtualenv, installs backend dependencies, builds the frontend, seeds
the demo data and serves everything from **http://localhost:8000**.

### Development mode (hot reload)

```bash
./run.sh --dev      # API on :8000, Vite dev server on :5173
```

### Docker

```bash
docker compose up --build     # → http://localhost:8000
```

### Manual

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
cd backend && ../.venv/bin/python -m app.main
```

### Configuration

Every setting has a demo-safe default. Override with `P2P_`-prefixed env vars:

| Variable | Default | Purpose |
|---|---|---|
| `P2P_DATABASE_URL` | bundled SQLite file | Point at PostgreSQL for a shared demo |
| `P2P_LLM_PROVIDER` | `deterministic` | `anthropic` / `openai` for live narration |
| `P2P_ENFORCE_HUMAN_IN_THE_LOOP` | `true` | The master governance switch |
| `P2P_GLOBAL_CONFIDENCE_FLOOR` | `0.90` | Below this, always a human |
| `P2P_SEED_ON_STARTUP` | `true` | Load the demo dataset if the DB is empty |
| `P2P_RESET_DATABASE_ON_STARTUP` | `false` | Rebuild from scratch on boot |

---

## The demo dataset

Nine personas across six authority levels, ten suppliers, five contracts, ten
POs with goods receipts, 15 live invoices and 30 days of settled history. Each
live invoice is engineered to exercise a different agent path:

| Invoice | Scenario |
|---|---|
| `VIS-2026-08841` | Clean three-way match — the touchless path, still confirmed by a person |
| `VIS-2026-08841` (2nd) | **Duplicate** arriving on another channel — held before payment |
| `BWC-449021` | **Price variance** 8% above the contracted rate |
| `CSP-77120` | **Missing goods receipt** — match cannot complete |
| `NFS-3391-B` | **Low-confidence scan** with an ambiguous supplier name |
| `MCP-INV-5540` | **Contract breach** — off-rate consultants plus an unauthorised surcharge |
| `ASG-DE-99120` | **Tax error** — effective rate outside the German band |
| `PSS-2026-1187` | **No PO reference** |
| `HLG-88-40213` | **Expired contract pricing** — the freight agreement lapsed |
| `TCS-SG-4402` | Supplier under **sanctions review** |
| `KPM-CA-7781` | Supplier **changed bank details three days ago** — payment freeze |
| `VIS-2026-08702` | 79h old, approver **out of office** — reminder → reroute → escalation |

Reset it any time from **Governance → Rebuild** (Platform Admin persona).

See **[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)** for a 15-minute walkthrough
built around these scenarios.

---

## What each screen is for

| Screen | Purpose |
|---|---|
| **Command Center** | KPIs against industry benchmarks, pipeline, aging, HITL scoreboard |
| **Approval Inbox** | The heart of the platform — every pending agent proposal, with evidence, diff, alternatives and the policy verdict |
| **Invoices** | Working set, full timeline, agent runs, per-invoice audit, source document |
| **Exceptions** | Open cases with the agent's proposed resolution and priced alternatives |
| **My Approvals** | Business invoice approvals assigned to the signed-in person |
| **Payments** | Payment-run proposals, discount capture, release decisions |
| **Agent Control Room** | Per-agent autonomy level, confidence threshold, ceilings, prompt, run history, fleet kill switch |
| **SLA Command Center** | Breach forecast, risk register with drivers, recommended interventions |
| **Suppliers** | Scorecard, live risk assessment, correspondence; simulate an enquiry |
| **Skills Library** | The 12 shared skills and their contracts |
| **Audit Trail** | Hash-chain verification and CSV export |
| **Governance** | Policy-as-code editing and the master HITL switch |

---

## API

Full OpenAPI at **`/api/docs`**. The endpoints from the specification:

```http
POST /api/invoices/process          POST /api/supplier/chat
POST /api/invoices/upload           GET  /api/slas
POST /api/agents/{key}/run          GET  /api/dashboard
POST /api/orchestrator/sweep        GET  /api/agents/status
POST /api/hitl/tasks/{id}/decide    GET  /api/audit/verify
POST /api/approvals/{id}/decide     GET  /api/audit/export
```

`POST /api/hitl/tasks/{id}/decide` is the only route through which an agent's
proposal can reach a system of record.

---

## Testing

```bash
.venv/bin/python -m pytest backend/tests -q
```

Covers the policy gates, the irreversible-action rule, role authority, the
audit hash chain, agent lifecycles and the end-to-end intake → payment path.

---

## Known limitations

- **Document extraction is text-driven.** Uploading a native binary PDF uses
  only its embedded text layer; there is no OCR engine bundled. Real deployments
  would put Azure Document Intelligence or Textract behind the same skill
  interface.
- **ERP connectors are simulated.** They implement the real `ERPConnector`
  protocol against the local store, so swapping in a live SAP/Oracle adapter is
  an implementation task, not a redesign.
- **Demo authentication.** Personas are selected, not authenticated. Role
  *authority* is fully enforced server-side; identity is not. Production would
  put SSO/OIDC in front of `get_current_user`.
- The event bus is in-process; Kafka/Event Hub is a `publish()` swap.
