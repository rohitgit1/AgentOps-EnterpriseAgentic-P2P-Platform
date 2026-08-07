# Procurement AgentOps

The strategic suite, running on the same control plane as the operational P2P
suite: agents propose, qualified humans decide, every decision is audited.

Six agents, sixteen skills, and a document pipeline — agents read the
attachments you give them and hand back files you can download.

---

## Agent I/O at a glance

Every agent declares what it consumes and what it produces. The
**Agent I/O Catalogue** screen (`/agent-io`) renders this live for all sixteen
agents across both suites; the table below is the procurement half.

| Agent | Input | Output |
|---|---|---|
| **Sourcing Event** | `requirements_brief` (md/txt) · `bid_responses` (csv/json) · category, budget, compliance rules | **RFP package** (md) · **Supplier shortlist** (csv) · **Bid scorecard** (csv) · **Award recommendation** (json) → *Issue RFP / Award event* |
| **Spend Analytics** | `spend_extract` (csv/json) — supplier, description, amount, date, po_number, on_contract | **Classified spend** (csv) · **Savings register** (csv) · **Spend insight brief** (md) · **Unclassified residual** (csv) → *Publish classification / Log savings* |
| **Supplier Risk & Compliance** | `financial_indicators` (csv) · `delivery_performance` (csv) · supplier_id | **Risk scorecard** (csv) · **Risk report** (md) · RiskAssessment records → *Set supplier disposition* |
| **Contract Lifecycle** | `contract_document` (md/txt/pdf) · contract request parameters | **Contract draft** (md) · **Clause review** (md) · **Obligation register** (csv) → *Accept draft / Issue for signature* |
| **Tail Spend** | `spend_extract` (csv) · `catalog` (csv) | **Tail spend analysis** (csv) · **Consolidation plan** (md) · **Off-catalog report** (csv) → *Consolidate suppliers / Enforce catalog* |
| **Procurement Command Center** | portfolio state (no attachment needed) · optional `board_pack_context` (md) | **Executive brief** (md) · **KPI pack** (csv) · **Risk heatmap data** (json) → *Publish executive brief* |

---

## How documents flow

```
   human uploads                agent reads                  agent writes
  ┌──────────────┐            ┌────────────┐              ┌──────────────┐
  │  attachment  │──parsed──▶ │   agent    │──produces──▶ │  deliverable │
  │ direction=   │            │  gather()  │              │ direction=   │
  │   "input"    │            │  decide()  │              │   "output"   │
  └──────────────┘            └────────────┘              │ status=DRAFT │
                                     │                    └──────┬───────┘
                                     ▼                           │
                              ┌─────────────┐                    │
                              │ HumanTask   │◀───────linked──────┘
                              │ checkpoint  │
                              └──────┬──────┘
                                     │ approved by a qualified human
                                     ▼
                              status = RELEASED
```

A generated document is **never final on creation.** It is born a draft and
becomes `released` only when someone with the required authority approves the
checkpoint that owns it. The same guarantee that stops an agent writing to the
ledger also stops it issuing a document.

Rejecting the checkpoint leaves the files as drafts — they stay in the artifact
library as evidence of what was considered, but nothing was issued.

### Parsing

| Format | Treatment |
|---|---|
| `.csv` / `.tsv` | Parsed to rows + field list; the agent sees typed records |
| `.json` | Parsed to records |
| `.md` / `.txt` | Full text |
| `.pdf` | **Embedded text layer only** — no OCR engine is bundled |

An unreadable attachment degrades to raw text with a stated reason rather than
raising, so an agent can report *"I could not read this"* instead of crashing.

---

## Sample attachments

Seven files ship in the artifact library so a demo can run an agent against real
input immediately — no preparation needed.

| File | Rows | Feeds |
|---|---|---|
| `requirements-freight-fy27.md` | — | Sourcing Event (drafts the RFP) |
| `bids-SRC-9002.csv` | 4 | Sourcing Event (scores and recommends the award) |
| `spend-extract-q4.csv` | 120 | Spend Analytics, Tail Spend |
| `catalog.csv` | 8 | Tail Spend (off-catalog substitution) |
| `credit-report.csv` | 10 | Supplier Risk (financial domain) |
| `otif-performance.csv` | 10 | Supplier Risk (operational domain) |
| `trident-msa-draft.md` | — | Contract Lifecycle (clause review) |

`trident-msa-draft.md` deliberately contains unlimited liability, a unilateral
price-change clause, a buyer-indemnifies-supplier clause and a silent
auto-renewal, so the clause analysis has something real to find. It scores
100/100 legal risk, and the agent will not offer it for signature.

---

## Governance, unchanged

Five procurement actions are **irreversible** and always stop for a human, at any
autonomy level:

```
issue_rfp · award_sourcing_event · issue_contract_for_signature
consolidate_suppliers · publish_executive_brief
```

Authority follows the same ladder, escalating with financial impact:

| Action | Minimum role |
|---|---|
| Issue RFP, award event, log savings, set disposition, consolidate | Procurement Lead |
| Issue contract for signature | Controller |
| Publish executive brief | CFO |

Issuing an RFP carries a financial impact of **zero** — it invites bids and
commits nothing. The award is where money is committed, so that is where the
value-based escalation applies (past $250k it reaches the CFO; past the dual
threshold it needs two distinct approvers).

---

## Executive KPIs

The Command Center reports the specification's six targets:

| KPI | Target |
|---|---|
| Spend under management | 95% |
| Contract compliance | 98% |
| Supplier risk score | below 20 |
| Tail spend reduction | 40% |
| Sourcing cycle time reduction | 60% |
| Procurement savings | above 5% |

The demo starts with most of these off target on purpose — approving the agents'
proposals is what closes the gaps, which is the story worth showing.

---

## Demo path (5 minutes)

1. Sign in as **Ken Oyelaran (Procurement Lead)**.
2. **Spend & Savings** → select `spend-extract-q4.csv` → **Run Spend Analytics
   Agent**. Four files come back as drafts; open one.
3. Approve *"Accept N savings opportunities"* — the files flip to **released**
   and the savings pipeline fills.
4. **Contracts** → select `trident-msa-draft.md` → run. The clause review finds
   the planted risks; signature is not offered.
5. **Sourcing Events** → open `SRC-9002` → run with `bids-SRC-9002.csv`. The
   award recommendation needs two approvers because of its value.
6. **Agent I/O Catalogue** → the whole contract for all sixteen agents.
7. **Artifact Library** → every file in and out, with who released it.
