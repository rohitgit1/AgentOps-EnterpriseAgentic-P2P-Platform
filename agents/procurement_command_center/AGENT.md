# Procurement Command Center Agent

> **Build specification.** Generated from `backend/app/agents/procurement_command_center.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`procurement_command_center` · Procurement AgentOps · class `ProcurementCommandCenterAgent`

**Role.** Rolls the procurement portfolio into executive KPIs and a briefing.

**Mission.** Give the executive a number for every procurement commitment, and its gap to target.

**Module intent.**

```
Procurement Agent 6 — Procurement Command Center.

Rolls the whole procurement portfolio into the executive KPI set from the
specification and drafts the brief. Publishing it is a CFO decision.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| portfolio state | data | no | — | Reads the sourcing, savings, risk, contract, tail-spend and spend records already in the platform. No attachment required. | — |
| board_pack_context | attachment | no | `.md`, `.txt` | Optional narrative or prior-period commentary to fold into the brief. | `q2-commentary.md` |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Executive brief | artifact | `.md` | Six KPIs against target, with the drivers behind each gap. | `procurement-executive-brief.md` |
| KPI pack | artifact | `.csv` | Machine-readable KPI values, targets and variances. | `procurement-kpis.csv` |
| Risk heatmap data | artifact | `.json` | Per-supplier domain scores for the heatmap. | `risk-heatmap.json` |
| Checkpoint | proposal | — | Publish the executive brief — CFO approves. | — |

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
| `default_stage` | `approval` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.88` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `cfo` — CFO | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `publish_executive_brief` | Publish executive brief | **no — irreversible** | CFO | `_publish_executive_brief` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `publish_executive_brief`

Raised on 1 branch.

```json
{
  "title": …,
  "summary": …
}
```

- Confidence: `0.93`
- Due in: `48` hours
- Releases linked draft deliverables on approval

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `publish_executive_brief` | `notifications` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Roll up the sourcing pipeline | `portfolio_rollup` | Cycle-time reduction is measured against the manual baseline. |
| 2 | Roll up savings and spend coverage | `kpi_generation` | Spend under management is the headline governance number. |
| 3 | Roll up supplier risk | `portfolio_rollup` | One portfolio risk score, with the outliers named. |
| 4 | Forecast contract renewals | `renewal_forecasting` | A renewal inside its notice window is a live commitment. |
| 5 | Draft the executive brief | `kpi_generation` | Every number carries its target and the gap. |
| 6 | Submit for publication | `hitl_checkpoint` | Executive communication goes out under a person's name. |

### `gather()` — evidence collection

Rolls up the whole procurement portfolio: spend under management, contract
compliance, the supplier risk composite, tail spend reduction, sourcing cycle
time reduction and realised savings. Needs no attachment; an optional
`board_pack_context` document is folded into the narrative when supplied.

### `decide()` — the reasoning

Measures all six KPIs against their targets, then produces an executive brief, a
KPI pack and risk heatmap data as drafts, and one
**`publish_executive_brief`** proposal.

Publishing is CFO-level and irreversible — an executive brief reaches an
audience that will act on it, and it cannot be unsent. The brief states which
targets are missed as prominently as those met; a command centre that only
reports green is not a control.

| KPI | Target |
|---|---|
| Spend under management | 95 % |
| Contract compliance | 98 % |
| Supplier risk score | below 20 |
| Tail spend reduction | 40 % |
| Sourcing cycle time reduction | 60 % |
| Procurement savings | above 5 % |

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Targets | see the table above | `TARGETS` module constant |
| Escalation | three or more KPIs off target | `decide()` |
| Agent confidence threshold | 0.90 | class attribute |

### Escalation

Escalates when three or more KPIs are off target.

### Handoff

None — this agent is the top of the reporting chain.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `kpi_generation` | _Declared by the agent; not in the shared catalogue._ | — |
| `portfolio_rollup` | _Declared by the agent; not in the shared catalogue._ | — |
| `renewal_forecasting` | _Declared by the agent; not in the shared catalogue._ | — |

### Data it reads

- `contract_drafts`
- `contracts`
- `risk_assessments`
- `savings_opportunities`
- `sourcing_events`
- `spend_transactions`
- `suppliers`
- `tail_spend_findings`

### External systems

- Sourcing pipeline
- Savings pipeline
- Risk register
- Contract register
- Tail spend findings
- Spend cube

---

## 6 · Worked example

**Scenario.** Closing the quarter for the executive.

**Given.** The whole procurement portfolio — no attachment needed

**It does:**

1. Rolls up sourcing cycle time against the 56-day manual baseline.
2. Computes spend under management and contract compliance from the spend cube.
3. Averages supplier risk and names the outliers.
4. Forecasts contract renewals inside their notice windows.

**Produces.** ⬇ procurement-executive-brief.md · procurement-kpis.csv · risk-heatmap.json, each KPI shown against target with the gap named.

**Decided by.** CFO publishes the brief.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Procurement Command Center Agent.

Mission:
Give the executive a number for every procurement commitment, and its gap to target.

You have access to:
- Sourcing pipeline
- Savings pipeline
- Risk register
- Contract register
- Tail spend findings
- Spend cube

Goals:
1. Report all six executive KPIs against their targets every cycle.
2. Name the categories and suppliers driving each gap.
3. Keep the savings pipeline and renewal forecast in one view.

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

1. Subclass `BaseAgent` in `backend/app/agents/procurement_command_center.py` with
   `key = "procurement_command_center"` and the identity, governance and `allowed_actions`
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

