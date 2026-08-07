# Sourcing Event Agent

> **Build specification.** Generated from `backend/app/agents/sourcing_rfp.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`sourcing_rfp` · Procurement AgentOps · class `SourcingEventAgent`

**Role.** Runs RFP/RFQ events from requirements brief to award recommendation.

**Mission.** Compress sourcing cycle time without losing competitive tension or auditability.

**Module intent.**

```
Procurement Agent 1 — Sourcing Event (RFP/RFQ).

Takes a requirements brief as an attachment, produces an issuable RFP package,
a supplier shortlist and a scored bid comparison, and recommends an award.
Issuing and awarding both reach outside the company, so both stop for a human.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| requirements_brief | attachment | no | `.md`, `.txt`, `.csv`, `.json` | Business requirements document describing scope, volume, term, budget and service levels. | `requirements-logistics-2026.md` |
| bid_responses | attachment | no | `.csv`, `.json` | Supplier bid responses to score, one row per supplier. | `bids-SRC-9001.csv → supplier_name,bid_amount_usd,lead_time_days,technical_score` |
| event_id | data | no | — | Existing sourcing event to progress. Omit to draft a new one. | `event_id=<uuid>` |
| category / budget / compliance_rules | data | no | — | Category, indicative budget and mandatory compliance rules. | `{"category": "Freight & Logistics", "budget": 850000}` |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| RFP package | artifact | `.md` | Issuable RFP document with scope, compliance, response format and published evaluation weights. | `RFP-SRC-9001.md` |
| Supplier shortlist | artifact | `.csv` | Ranked candidates with fit score, rationale and exclusions. | `shortlist-SRC-9001.csv` |
| Bid scorecard | artifact | `.csv` | Every bid scored on commercial, technical and risk components. | `scorecard-SRC-9001.csv` |
| Award recommendation | artifact | `.json` | Winner, margin over runner-up, expected savings, confidence. | `{"recommended_supplier": "...", "expected_savings": "$1.4M"}` |
| Checkpoint | proposal | — | Issue RFP / Award event — both require Procurement approval. | — |

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
| `default_stage` | `intake` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.92` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `procurement` — Procurement Lead | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `issue_rfp` | Issue RFP to suppliers | **no — irreversible** | Procurement Lead | `_issue_rfp` |
| `award_sourcing_event` | Award sourcing event | **no — irreversible** | Procurement Lead | `_award_sourcing_event` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `issue_rfp`

Raised on 1 branch.

```json
{
  "event_id": …,
  "invited_suppliers": …,
  "response_due": …
}
```

- Diff preview: `status`, `invited`
- Due in: `24` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval

#### `award_sourcing_event`

Raised on 1 branch.

```json
{
  "event_id": …,
  "bid_id": …,
  "expected_savings_usd": …
}
```

- Diff preview: `status`, `supplier`
- Due in: `24` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `issue_rfp` | `sourcing_events` |
| `award_sourcing_event` | `sourcing_bids`, `sourcing_events` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Read the requirements brief | `rfp_orchestration` | Structured parameters are what make the RFP specific enough to bid against. |
| 2 | Shortlist qualified suppliers | `supplier_discovery` | Compliance is a gate, not a weighting — blocked suppliers never make the list. |
| 3 | Generate the RFP package | `rfp_orchestration` | Publishing the weights up front is what makes the award defensible. |
| 4 | Score any bids received | `bid_evaluation` | Commercial, technical and risk components are shown separately. |
| 5 | Recommend an award for approval | `hitl_checkpoint` | Issuing and awarding both reach a supplier — a person owns each. |

### `gather()` — evidence collection

Two modes, chosen by what it is given.

**Draft mode** (no `event_id`, or an event still in draft): parses the
requirements brief attachment with `sourcing.parse_requirements()` for scope,
volume, term, budget and service levels, then runs `supplier_discovery` over the
vendor master to shortlist candidates on category fit, tier and risk.

**Evaluation mode** (an issued event, with bid responses): loads the bids —
from the `bid_responses` attachment or from `sourcing_bids` — and scores them
with `bid_evaluation`.

### `decide()` — the reasoning

**Draft mode** produces four deliverables as drafts — the RFP package, the
supplier shortlist, the bid scorecard template and the award recommendation
skeleton — and one `issue_rfp` proposal that would release them.

Two things are deliberate here:

- **Compliance is a gate, not a weight.** A supplier failing a mandatory
  compliance rule is excluded from the shortlist, not scored down. A weighted
  score can always be outvoted by a good price; a gate cannot.
- **Issuing an RFP carries a financial impact of zero.** It invites bids and
  commits nothing. Putting the budget on it would escalate the invitation to the
  CFO while leaving the award — where money is actually committed — at the same
  level. The value-based escalation belongs on the award.

**Evaluation mode** scores every bid on commercial, technical and risk
separately and proposes `award_sourcing_event` for the winner, with the full
scorecard as evidence. The margin over the runner-up is computed and a margin
inside 4 points is called out as a close call — at that distance the ranking is
not a mandate.

If no supplier qualifies, it says so and proposes nothing. A sourcing event with
no qualified suppliers is a finding, not a failure to try harder.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Evaluation weights | commercial 0.45 / technical 0.35 / risk 0.20 | `DEFAULT_WEIGHTS` in `skills/sourcing.py`; publishable per event |
| Close call | margin < 4 points over the runner-up | `decide()` |
| Escalation — draft | requirements completeness < 0.67 | `decide()` |
| `issue_rfp` financial impact | 0.00 USD | `decide()` — deliberate |
| Agent confidence threshold | 0.92 | class attribute |

### Escalation

Escalates when the requirements brief is less than two-thirds complete, when the award is a close call, and when the winner carries any compliance flag.

### Handoff

`contract_lifecycle` once an award is approved.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `rfp_orchestration` | Create and manage sourcing events end to end, from requirements to award. | [contract](../../skills/rfp_orchestration/SKILL.md) |
| `supplier_discovery` | Shortlist qualified suppliers for a category from vendor master and market signals. | [contract](../../skills/supplier_discovery/SKILL.md) |
| `bid_evaluation` | Score bids on commercial, technical and risk dimensions against declared weights. | [contract](../../skills/bid_evaluation/SKILL.md) |

Imported skill modules: `sourcing`

### Data it reads

- `sourcing_bids`
- `sourcing_events`
- `suppliers`

### External systems

- Requirements brief
- Vendor master
- Bid responses
- Category strategy
- Risk screening

---

## 6 · Worked example

**Scenario.** Sourcing regional freight for FY27 from a requirements brief.

**Given.** 📎 requirements-freight-fy27.md — 850,000 USD budget, 98% OTIF, 24-month term

**It does:**

1. Parses the brief: 7 requirements, volume, term, budget and service level extracted.
2. Shortlists 5 suppliers on category fit, tier and risk; compliance is a gate, not a weight.
3. Generates the RFP with the evaluation weights published up front.
4. Later, given a bid CSV, scores commercial / technical / risk separately.

**Produces.** ⬇ RFP-SRC-9002.md · shortlist.csv · scorecard.csv · award-recommendation.json

**Decided by.** Procurement issues the RFP; the award needs two approvers above the dual-approval threshold.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Sourcing Event Agent.

Mission:
Compress sourcing cycle time without losing competitive tension or auditability.

You have access to:
- Requirements brief
- Vendor master
- Bid responses
- Category strategy
- Risk screening

Goals:
1. Cut sourcing cycle time by 50-80% against the 4-12 week baseline.
2. Keep bid participation above 80% by shortlisting suppliers that actually fit.
3. Make every award reproducible from the published evaluation weights.

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

1. Subclass `BaseAgent` in `backend/app/agents/sourcing_rfp.py` with
   `key = "sourcing_rfp"` and the identity, governance and `allowed_actions`
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

