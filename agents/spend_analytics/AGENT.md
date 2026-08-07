# Spend Analytics Agent

> **Build specification.** Generated from `backend/app/agents/spend_analytics.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`spend_analytics` · Procurement AgentOps · class `SpendAnalyticsAgent`

**Role.** Classifies spend, normalises suppliers and prices the savings levers.

**Mission.** Turn a raw spend extract into classified, addressable, priced opportunity.

**Module intent.**

```
Procurement Agent 2 — Spend Analytics & Classification.

Takes a raw spend extract as an attachment, classifies it against a taxonomy,
normalises supplier identities, measures contract compliance and prices the
savings levers it finds.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| spend_extract | attachment | no | `.csv`, `.json` | Transaction-level spend export. Recognised columns: supplier, description, amount, date, cost_center, po_number, on_contract. | `spend-fy26-q3.csv → external_id,supplier,description,amount_usd,date,po_number` |
| stored transactions | data | no | — | When no attachment is supplied, the agent analyses spend already loaded. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Classified spend | artifact | `.csv` | Every transaction with category, UNSPSC, confidence and the token the classification was based on. | `classified-spend.csv` |
| Savings register | artifact | `.csv` | Priced opportunities with lever, addressable spend and rate. | `savings-register.csv` |
| Spend insight brief | artifact | `.md` | Narrative analysis: concentration, compliance, leakage. | `spend-insight-brief.md` |
| Unclassified residual | artifact | `.csv` | Rows below the confidence floor, for a human to resolve. | `unclassified-residual.csv` |
| Checkpoints | proposal | — | Publish classification / log savings — Procurement approves. | — |

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
| `publish_spend_classification` | Publish spend classification | yes | Procurement Lead | `_publish_spend_classification` |
| `create_savings_opportunity` | Log savings opportunity | yes | Procurement Lead | `_create_savings_opportunity` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `publish_spend_classification`

Raised on 1 branch.

```json
{
  "classifications": …
}
```

- Diff preview: `classified`, `coverage`
- Due in: `24` hours
- Releases linked draft deliverables on approval

#### `create_savings_opportunity`

Raised on 1 branch.

```json
{
  "opportunities": …
}
```

- Due in: `48` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `publish_spend_classification` | `spend_transactions` |
| `create_savings_opportunity` | `savings_opportunities` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Load the spend extract | `spend_classification` | An attachment takes precedence over stored data. |
| 2 | Normalise supplier identities | `supplier_normalization` | Fragmented names hide both duplicates and leverage. |
| 3 | Classify against the taxonomy | `spend_classification` | Category is the unit of analysis for every downstream lever. |
| 4 | Measure contract compliance | `maverick_detection` | Compliance is measured on value — count flatters the number. |
| 5 | Price the savings levers | `savings_identification` | An opportunity without an addressable base and a rate is an opinion. |
| 6 | Submit for approval | `hitl_checkpoint` | Nothing enters the spend cube or the savings pipeline unreviewed. |

### `gather()` — evidence collection

Reads the spend extract from an attachment or, failing that, from
`spend_transactions`. Runs `supplier_normalization` to collapse name variants
onto one entity, `spend_classification` against the category taxonomy, and
`savings_identification` across the savings levers.

### `decide()` — the reasoning

1. **No spend data at all** → says so and escalates. It does not classify an
   empty set and report 100 % coverage.
2. Otherwise it produces four deliverables as drafts — classified spend,
   savings register, an insight brief and the **unclassified residual** — and
   two proposals:
   - **`publish_spend_classification`**, carrying the classification and the
     coverage achieved;
   - **`create_savings_opportunity`** for the identified savings, each with its
     lever and modelled rate.

Shipping the unclassified residual as its own file is the point of the residual:
a coverage percentage with no way to see what fell outside it cannot be acted
on.

Savings are modelled per lever at published rates rather than estimated per
line, so two runs over the same data produce the same number and the method is
auditable.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Confidence floor | 0.75 | `CONFIDENCE_FLOOR` module constant |
| Escalation | classification coverage < 85 % | `decide()` |
| Savings lever rates | consolidation 8 % · contract coverage 6 % · … | `LEVER_RATES` in `skills/spend_analysis.py` |
| Agent confidence threshold | 0.90 | class attribute |

### Escalation

Escalates when classification coverage falls below 85 % — below that the savings numbers rest on too little classified spend.

### Handoff

`tail_spend` for the long tail the classification exposes.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `spend_classification` | Map raw spend transactions to a category taxonomy (UNSPSC / NAICS / custom). | [contract](../../skills/spend_classification/SKILL.md) |
| `supplier_normalization` | Collapse supplier name variants onto a single vendor master identity. | [contract](../../skills/supplier_normalization/SKILL.md) |
| `savings_identification` | Quantify consolidation, contract-coverage, volume-discount and rationalization levers. | [contract](../../skills/savings_identification/SKILL.md) |
| `maverick_detection` | Detect off-contract and off-catalog buying that bypasses negotiated channels. | [contract](../../skills/maverick_detection/SKILL.md) |

Imported skill modules: `spend_analysis`

### Data it reads

- `contracts`
- `spend_transactions`
- `suppliers`

### External systems

- Spend extract
- Vendor master
- Contract register
- Category taxonomy

---

## 6 · Worked example

**Scenario.** Turning a raw spend export into priced opportunity.

**Given.** 📎 spend-extract-q4.csv — 120 transactions, 161,912 USD

**It does:**

1. Normalises supplier strings — three 'Vertex' variants collapse to one master record.
2. Classifies 95.2% of value against the taxonomy, naming the token each match came from.
3. Holds back rows below the 75% confidence floor rather than guessing.
4. Measures contract compliance on value, not transaction count.
5. Prices consolidation, coverage and demand levers at published rates.

**Produces.** ⬇ classified-spend.csv · unclassified-residual.csv · savings-register.csv · spend-insight-brief.md

**Decided by.** Procurement publishes the classification and accepts opportunities into the pipeline.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Spend Analytics Agent.

Mission:
Turn a raw spend extract into classified, addressable, priced opportunity.

You have access to:
- Spend extract
- Vendor master
- Contract register
- Category taxonomy

Goals:
1. Classify 95%+ of spend value against the taxonomy.
2. Surface consolidation, coverage and rationalisation levers with a stated basis.
3. Measure contract compliance on value, not transaction count.

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

1. Subclass `BaseAgent` in `backend/app/agents/spend_analytics.py` with
   `key = "spend_analytics"` and the identity, governance and `allowed_actions`
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

