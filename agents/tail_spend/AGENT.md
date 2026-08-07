# Tail Spend Agent

> **Build specification.** Generated from `backend/app/agents/tail_spend_agent.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`tail_spend` · Procurement AgentOps · class `TailSpendAgent`

**Role.** Governs the long tail of low-value, high-volume, off-contract buying.

**Mission.** Bring unmanaged spend under control without adding friction to small purchases.

**Module intent.**

```
Procurement Agent 5 — Tail Spend Management.

80% of the transactions, 20% of the spend. Finds the tail on a Pareto cut,
prices consolidation onto preferred suppliers, and drafts spot-buy RFQs.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| spend_extract | attachment | no | `.csv`, `.json` | Transaction-level spend to analyse for tail behaviour. | `spend-fy26-q3.csv → supplier,description,amount_usd,po_number` |
| catalog | attachment | no | `.csv`, `.json` | Contracted catalog items used to test substitutability. | `catalog.csv → item_code,description,category,unit_price` |
| stored transactions | data | no | — | Falls back to the loaded spend cube when nothing is attached. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Tail spend analysis | artifact | `.csv` | Head/tail split with the Pareto point and one-time vendors. | `tail-spend-analysis.csv` |
| Consolidation plan | artifact | `.md` | Category clusters with target supplier and priced savings. | `consolidation-plan.md` |
| Off-catalog report | artifact | `.csv` | Transactions with a named catalog substitute and price delta. | `off-catalog.csv` |
| Spot-buy RFQ | artifact | `.md` | Three-quote RFQ draft for a repeated one-off cluster. | `spot-buy-rfq.md` |
| Checkpoints | proposal | — | Consolidate suppliers / enforce catalog — Procurement approves. | — |

Accepts attachments: **yes** · Produces downloadable files: **yes**

Attachments arrive already parsed. `run()` resolves `context["attachment_ids"]`
through `artifacts.load_for_agent()` and puts the result in
`context["attachments"]` — CSV/TSV as typed rows plus a field list, JSON as
records, Markdown/text as full text, PDF as its embedded text layer. An
unreadable file degrades to raw text with a stated reason rather than raising,
so the agent can report *"I could not read this"* instead of crashing.

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `validation` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.9` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `procurement` — Procurement Lead | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `consolidate_suppliers` | Consolidate suppliers | **no — irreversible** | Procurement Lead | `_consolidate_suppliers` |
| `enforce_catalog` | Enforce catalog buying | yes | Procurement Lead | `_enforce_catalog` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `consolidate_suppliers`

Raised on 1 branch.

```json
{
  "finding_id": …
}
```

- Diff preview: `suppliers`, `savings`
- Confidence: `0.88`
- Due in: `48` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval

#### `enforce_catalog`

Raised on 1 branch.

```json
{
  "finding_id": …
}
```

- Diff preview: `channel`, `recoverable`
- Confidence: `0.85`
- Due in: `48` hours
- Releases linked draft deliverables on approval

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `consolidate_suppliers` | `tail_spend_findings` |
| `enforce_catalog` | `tail_spend_findings` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Load spend and catalog | `ingest` | Attachments win over the stored cube. |
| 2 | Split head from tail on a Pareto cut | `tail_spend_detection` | A defensible cut beats an arbitrary value threshold. |
| 3 | Cluster the tail by category | `vendor_consolidation` | Consolidation only means something within a category. |
| 4 | Test off-catalog buying for substitutes | `catalog_compliance` | No substitute, no flag — false positives cost credibility. |
| 5 | Draft a spot-buy RFQ where it pays | `spot_buy_automation` | Repeated one-offs deserve competitive tension. |
| 6 | Submit interventions for approval | `hitl_checkpoint` | Moving spend between suppliers is a commercial decision. |

### `gather()` — evidence collection

Splits spend into head and tail on a Pareto cut by supplier, clusters the tail by
category, and checks each transaction against the catalogue to find off-catalogue
buying where a catalogue item existed.

### `decide()` — the reasoning

1. **No spend data** → says so and escalates.
2. **`consolidate_suppliers`** per material cluster. A cluster qualifies only
   if it is worth at least the materiality floor **and** contains at least two
   suppliers — consolidating a single supplier onto itself is not an
   intervention. Modelled savings apply the consolidation rate to the cluster,
   and only where a preferred supplier actually exists; without one the finding
   is recorded as `no_preferred_supplier` with **zero** savings rather than a
   savings claim nobody can realise.
3. **`enforce_catalog`** for off-catalogue purchases where a catalogue
   substitute exists. Where no substitute exists, enforcement is not proposed —
   the buyer had no compliant option.

The materiality floor exists because an unfiltered clustering surfaces dozens of
sub-thousand-dollar clusters that cost more to action than they save.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Pareto cut | 80 % of cumulative spend defines the head | `PARETO_CUT` in `skills/tail_spend.py` |
| Cluster materiality floor | 4,000 USD | `CLUSTER_MATERIALITY` in `skills/tail_spend.py` |
| Minimum suppliers per cluster | 2 | `skills/tail_spend.py` |
| Modelled consolidation saving | 11 % of cluster spend | `CONSOLIDATION_RATE` in `skills/tail_spend.py` |
| Escalation | tail share ≥ 25 % of spend | `decide()` |
| Agent confidence threshold | 0.89 | class attribute |

### Escalation

Escalates when the tail exceeds a quarter of total spend — that is a category-strategy problem, not a purchasing one.

### Handoff

`sourcing_rfp` for clusters large enough to competitively source.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `tail_spend_detection` | Isolate the long tail — the transactions that are most of the volume and least of the value. | [contract](../../skills/tail_spend_detection/SKILL.md) |
| `catalog_compliance` | Detect off-catalog buying where a contracted catalog item already exists. | [contract](../../skills/catalog_compliance/SKILL.md) |
| `vendor_consolidation` | Group fragmented category spend onto a preferred supplier and price the move. | [contract](../../skills/vendor_consolidation/SKILL.md) |
| `spot_buy_automation` | Turn a repeated one-off purchase into a quick three-quote RFQ. | [contract](../../skills/spot_buy_automation/SKILL.md) |

Imported skill modules: `spend_analysis`, `tail_spend`

### Data it reads

- `contracts`
- `spend_transactions`
- `suppliers`
- `tail_spend_findings`

### External systems

- Spend extract
- Catalog
- Preferred supplier list
- Contract register

---

## 6 · Worked example

**Scenario.** Finding the unmanaged long tail.

**Given.** 📎 spend-extract-q4.csv + 📎 catalog.csv

**It does:**

1. Ranks suppliers by value and cuts the tail at the 80% cumulative Pareto point.
2. The tail is 12.7% of spend but 75.8% of transactions — the classic shape.
3. Clusters the tail by category and prices consolidation at 11% of moved spend.
4. Tests off-catalog buying — a flag is only raised where a catalog substitute exists.

**Produces.** ⬇ tail-spend-analysis.csv · consolidation-plan.md · off-catalog.csv

**Decided by.** Procurement approves consolidation or catalog enforcement.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Tail Spend Agent.

Mission:
Bring unmanaged spend under control without adding friction to small purchases.

You have access to:
- Spend extract
- Catalog
- Preferred supplier list
- Contract register

Goals:
1. Reduce tail spend by 40%.
2. Move fragmented categories onto preferred suppliers.
3. Give every off-catalog flag a named catalog substitute.

Decision Rules:
- Never mutate a system of record directly; propose an action for human review.
- Prefer the least invasive action that resolves the issue.
- Escalate when confidence falls below the governance floor.
- Cite every fact you rely on.

Output:
Action
Reasoning
Confidence
Audit Record
```

---

## 8 · Rebuild checklist

1. Subclass `BaseAgent` in `backend/app/agents/tail_spend_agent.py` with
   `key = "tail_spend"` and the identity, governance and `allowed_actions`
   from sections 2 and 3.
2. Declare `inputs` and `outputs` as `IOSpec` objects matching section 1 — these
   drive the Agent I/O Catalogue and the Academy, and are the contract an
   evaluator reads before running anything.
3. Implement `plan()` returning the `PlanStep` list in section 4, verbatim. It is
   a static declaration and is read without a live context.
4. Implement `gather()` per section 4, returning one `Observation` per tool.
   Persist anything `decide()` needs on `context`, never on `self` — agents are
   singletons and a run must not leak into the next.
5. Implement `decide()` per section 4, returning an `AgentDecision` whose
   `proposals` carry exactly the payload keys in section 3.
6. Confirm every action has an executor registered with `@action(...)` in
   `backend/app/services/hitl.py`. An agent that proposes an unexecutable
   action fails `test_every_procurement_action_has_an_executor`.
7. Register the class in `backend/app/agents/registry.py`.

**Invariants a rebuild must not break:**

- `decide()` returns proposals. It must never write to a business table, call an
  executor, or mutate an ORM object it did not create as a draft artifact.
- Confidence is a real number the agent stands behind, not a constant. The
  policy engine gates on it.
- Every claim in `evidence` cites the observation it came from, so a reviewer
  months later can reconstruct the decision.
- Financial impact is the amount actually at risk. It drives role escalation and
  the dual-approval threshold, so an inflated figure blocks work and a deflated
  one under-reviews it.

