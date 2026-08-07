# Running P2P AgentOps locally

Everything below runs on a laptop with **no cloud account, no API key, no
database server and no outbound network call**. The platform ships with a
deterministic reasoning engine and a bundled SQLite database, so a client demo
works on airplane wifi.

---

## TL;DR

```bash
git clone https://github.com/CloudKatasani/AgentOps-EnterpriseAgentic-P2P-Platform.git
cd AgentOps-EnterpriseAgentic-P2P-Platform
./run.sh
```

Open **<http://localhost:8000>** and pick a persona. That's it.

First run takes 1–3 minutes (virtualenv + npm install + UI build). Subsequent
runs start in a few seconds.

---

## 1 · Prerequisites

| Requirement | Minimum | Check with | Notes |
|---|---|---|---|
| **Python** | 3.10+ | `python3 --version` | 3.11 recommended; 3.11.15 used in development |
| **Node.js** | 18+ | `node --version` | Only needed to build the UI. 22.x used in development |
| **npm** | 9+ | `npm --version` | Ships with Node |
| Disk | ~500 MB | | venv + node_modules + demo database |
| Ports | `8000` free | `lsof -i :8000` | plus `5173` in `--dev` mode |

> **No Node?** `./run.sh` still starts the API and serves `/api/docs`. You just
> won't get the UI. Install Node 18+ to get the full application.

**Docker alternative:** if you'd rather not install Python or Node at all, skip
to [§3 Docker](#3--docker).

---

## 2 · The three ways to run it

### A. Standard — one command, one port *(use this for client demos)*

```bash
./run.sh                    # macOS / Linux / WSL
```
```powershell
.\run.ps1                   # Windows PowerShell
```

The script is idempotent — safe to re-run any time. It:

1. creates `.venv/` if missing and installs `backend/requirements.txt`
2. runs `npm install` in `frontend/` if `node_modules/` is missing
3. builds the React SPA into `frontend/dist/`
4. seeds the demo dataset if the database is empty
5. starts FastAPI on port **8000**, serving both the API and the built UI

```
  P2P AgentOps → http://localhost:8000
  API docs     → http://localhost:8000/api/docs
```

Stop it with **Ctrl-C**.

### B. Development — hot reload

```bash
./run.sh --dev              # or:  .\run.ps1 -Dev
```

- **UI → <http://localhost:5173>** (Vite dev server, hot module reload)
- **API → <http://localhost:8000>** (Vite proxies `/api` to it)

Use `http://localhost:5173` in this mode — port 8000 serves the last *built*
UI, which will be stale.

For backend auto-reload as well:

```bash
P2P_RELOAD=1 ./run.sh --dev
```

### C. Manual — full control

```bash
# backend
python3 -m venv .venv
./.venv/bin/pip install -r backend/requirements.txt

# frontend
cd frontend && npm install && npm run build && cd ..

# serve
cd backend && ../.venv/bin/python -m app.main
```

Windows: use `.\.venv\Scripts\pip.exe` and `.\.venv\Scripts\python.exe`.

---

## 3 · Docker

No Python or Node needed on the host:

```bash
docker compose up --build
```

→ **<http://localhost:8000>**

The demo database persists in the named volume `p2p-data`, so decisions survive
a restart. To start completely fresh:

```bash
docker compose down -v && docker compose up --build
```

`docker-compose.yml` also contains a commented-out PostgreSQL service — uncomment
it and the `P2P_DATABASE_URL` line for a shared, multi-user demo.

---

## 4 · First five minutes

1. **Pick a persona.** Start as **Priya Raman (AP Clerk)** — that's where the
   routine flow begins, and it makes the authority limits visible as soon as you
   hit one. (Higher roles see *more* checkpoints, not fewer: a Controller can
   decide everything a clerk can, plus payment releases and master-data changes.)
2. **Press ▶ Run agent sweep** in the top bar. All ten agents analyse the
   portfolio. Watch the **Live activity** rail on the right fill in real time.
3. **Go to Approval Inbox.** Every agent proposal is waiting there. Nothing has
   touched the ERP, the ledger or a supplier yet.
4. **Open any checkpoint.** Read the amber *"Why a human is deciding this"*
   panel, then the **Agent Reasoning** and **Policy & Audit** tabs.
5. **Approve one.** Return to **Invoices** and watch the invoice advance a stage.
6. **Switch persona** (top right) to see how authority changes what you can act on.
7. **Under the Hood → Agents Academy** when someone asks *"what does this agent
   actually do?"* — input, output, the steps it runs, a worked example against
   the seeded data, and who has to approve each action.
8. **Under the Hood → Data Model** when someone asks *"what's behind it?"* — the
   live schema grouped by domain, with row counts read from the database at the
   moment you open the page.

`docs/DEMO_SCRIPT.md` is a 15-minute walkthrough built around the seeded
scenarios. `docs/HITL.md` explains exactly how the guarantees are enforced.

### The demo personas

| Persona | Role | Can decide |
|---|---|---|
| Priya Raman / Marcus Hale | AP Clerk | Extraction, matching, exceptions, supplier drafts |
| Dana Okafor | AP Manager | + ERP posting, escalations, reroutes, invoice approvals |
| Tomas Lindqvist | AP Manager | *(deliberately out of office — drives the delegation demo)* |
| Rivka Stein | Treasury Analyst | + payment scheduling |
| Sasha Mbeki | Controller | + payment release, supplier master changes |
| Ken Oyelaran | Procurement Lead | + contract breaches, purchase requests |
| Elena Duarte | CFO | Everything; receives executive alerts |
| Platform Service Account | Admin | Agent autonomy, governance switch, demo reset |

No passwords. Personas are *selected*, not authenticated — role **authority** is
fully enforced server-side, identity is not. Production would put SSO in front
of `get_current_user`.

---

## 5 · Resetting the demo

**From the UI** *(easiest — do this between client meetings)*
Sign in as **Platform Service Account** → **Governance** → **Rebuild**.

**On startup**
```bash
./run.sh --reset
```

**By hand**
```bash
rm -f backend/data/p2p_agentops.db*
./run.sh
```

All three rebuild the 9 personas, 10 suppliers, 5 contracts, 10 POs with goods
receipts, 15 live invoices and 30 days of settled history.

---

## 6 · Configuration

Every setting has a demo-safe default. Override with `P2P_`-prefixed environment
variables, or a `.env` file in `backend/`.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `P2P_DATABASE_URL` | bundled SQLite | e.g. `postgresql+psycopg://user:pw@host/db` |
| `P2P_SEED_ON_STARTUP` | `true` | Seed the demo data if the database is empty |
| `P2P_RESET_DATABASE_ON_STARTUP` | `false` | Drop and rebuild on every boot |
| `P2P_CORS_ORIGINS` | `*` | Comma-separated allow-list |
| `P2P_RELOAD` | `0` | Uvicorn auto-reload for backend development |

### Governance

| Variable | Default | Purpose |
|---|---|---|
| `P2P_ENFORCE_HUMAN_IN_THE_LOOP` | `true` | Master switch — no agent action reaches a system of record unreviewed |
| `P2P_GLOBAL_CONFIDENCE_FLOOR` | `0.90` | Below this, always a human |
| `P2P_AGENTS_PAUSED` | `false` | Fleet kill switch |

> Turning enforcement off does **not** make agents autonomous. Per-agent
> autonomy levels, confidence thresholds, financial ceilings and the
> irreversible-action rule all still apply — see `docs/HITL.md`.

### Reasoning engine (optional)

Deterministic by default: reproducible, offline, and templated strictly from
observed evidence. To enable live LLM narration:

```bash
pip install anthropic          # or: pip install openai
export P2P_LLM_PROVIDER=anthropic
export P2P_ANTHROPIC_API_KEY=sk-ant-...
```

| Variable | Default |
|---|---|
| `P2P_LLM_PROVIDER` | `deterministic` \| `anthropic` \| `openai` |
| `P2P_ANTHROPIC_MODEL` | `claude-sonnet-5` |
| `P2P_OPENAI_MODEL` | `gpt-4o` |

Decisions always come from the deterministic policy engine — the language model
only narrates the rationale, and the engine falls back to deterministic on any
error. **Recommendation: leave this on `deterministic` for client demos** so the
narrative is identical every time you present it.

### Business policy

Editable live in the UI under **Governance** (no restart needed), or set at boot:

| Variable | Default |
|---|---|
| `P2P_AMOUNT_VARIANCE_TOLERANCE_PCT` | `3.0` |
| `P2P_QUANTITY_VARIANCE_TOLERANCE_PCT` | `2.0` |
| `P2P_SLA_INVOICE_CYCLE_HOURS` | `24` |
| `P2P_SLA_APPROVAL_REMINDER_HOURS` | `48` |
| `P2P_SLA_APPROVAL_ESCALATION_HOURS` | `72` |
| `P2P_AUTO_APPROVE_UNDER_USD` | `5000` |
| `P2P_MANAGER_REVIEW_UNDER_USD` | `10000` |

---

## 7 · Running on PostgreSQL

```bash
docker run -d --name p2p-pg -p 5432:5432 \
  -e POSTGRES_USER=p2p -e POSTGRES_PASSWORD=p2p -e POSTGRES_DB=p2p \
  postgres:16-alpine

./.venv/bin/pip install "psycopg[binary]"
export P2P_DATABASE_URL="postgresql+psycopg://p2p:p2p@localhost:5432/p2p"
./run.sh
```

Tables are created automatically on first boot. No migration step, no schema
change — the models are backend-agnostic.

---

## 8 · Verifying the install

```bash
# API is alive
curl http://localhost:8000/api/health

# Test suite — 79 tests over the policy gates, the irreversible-action rule,
# role authority, the audit hash chain, the attachment → deliverable pipeline
# and the full intake-to-payment path
cd backend && ../.venv/bin/python -m pytest tests -q

# The audit chain verifies from genesis
curl -H "X-User-Id: <any-persona-id>" http://localhost:8000/api/audit/verify
```

Expected: `79 passed`, and `"valid": true` from the audit chain.

Interactive API reference: **<http://localhost:8000/api/docs>**

---

## 9 · Troubleshooting

**`Address already in use` / port 8000 busy**
```bash
lsof -ti :8000 | xargs kill        # macOS / Linux
netstat -ano | findstr :8000       # Windows — then: taskkill /PID <pid> /F
```
To use another port, edit the `uvicorn.run(...)` call in `backend/app/main.py`.

**"Cannot reach the API" on the sign-in screen**
The backend isn't running or isn't on 8000. Check `curl http://localhost:8000/api/health`.
In `--dev` mode make sure you're on **5173**, not 8000.

**UI shows stale content after a code change**
You're on port 8000, which serves the last build. Either re-run `./run.sh` to
rebuild, or use `./run.sh --dev` and browse port 5173.

**`npm install` fails or is very slow**
Behind a corporate proxy, set `npm config set proxy` / `https-proxy`. To skip the
UI entirely and run API-only, delete `frontend/node_modules` and re-run —
`run.sh` degrades to serving just the API.

**`ModuleNotFoundError: No module named 'app'`**
`app.main` must be run from inside `backend/`:
```bash
cd backend && ../.venv/bin/python -m app.main
```

**`database is locked` (SQLite)**
Two servers are sharing one file. Stop all instances (`pkill -f app.main`), or
move to PostgreSQL (§7) for concurrent users.

**Agents produce no proposals**
Check the fleet kill switch in **Agent Control Room** (Platform Admin persona),
that the agent is enabled, and that the invoice has no open checkpoint — a
pending checkpoint deliberately blocks all further agent work on that entity.

**Everything is broken and I have a demo in five minutes**
```bash
rm -rf .venv frontend/node_modules frontend/dist backend/data/*.db*
./run.sh
```

**PowerShell: "running scripts is disabled on this system"**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run.ps1
```

---

## 10 · What runs where

| Port | Serves | When |
|---|---|---|
| `8000` | FastAPI + built SPA + `/api/docs` | always |
| `5173` | Vite dev server (hot reload) | `--dev` only |

| Path | Contents |
|---|---|
| `backend/data/p2p_agentops.db` | The demo database — safe to delete |
| `frontend/dist/` | Built SPA, served by FastAPI at port 8000 |
| `.venv/` | Python virtualenv |

None of these are committed; all are rebuilt by `./run.sh`.

---

## 11 · Demoing on another machine

The platform binds `0.0.0.0`, so a colleague on the same network can reach it at
`http://<your-lan-ip>:8000`. There is no authentication — only do this on a
trusted network, and treat it as a demo, not a deployment.

For a shared, persistent demo, run the Docker compose stack with the PostgreSQL
service enabled so state is not tied to one laptop.
