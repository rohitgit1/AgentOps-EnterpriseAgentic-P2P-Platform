# Contract Intelligence Agent

> **Build specification.** Generated from `backend/app/agents/contract_intelligence.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`contract_intelligence` · P2P AgentOps · class `ContractIntelligenceAgent`

**Role.** Enforces the contract against what is actually billed.

**Mission.** Detect expired pricing, unauthorised charges, incorrect rates and missed discounts.

**Module intent.**

```
Agent 9 — Contract Intelligence.

Mission: detect expired pricing, unauthorised charges, incorrect rates and
missed discounts by reading the invoice against the contract that governs it.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| invoice_id | data | yes | — | The invoice to test against its governing contract. | — |
| contract rate card | data | no | — | Agreed rates, allowed charges and volume tiers. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Contract findings | record | — | Expired pricing, incorrect rates, unauthorised charges, missed discounts — each with its dollar impact. | — |
| Recoverable amount | record | — | Total value recoverable by short-paying to contract. | — |
| Checkpoint | proposal | — | Flag the breach / notify the supplier — Procurement decides. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `matching` | Workflow stage its checkpoints are filed under |
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
| `flag_contract_breach` | Flag contract breach | yes | Procurement Lead | `_flag_contract_breach` |
| `create_exception` | Open exception | yes | AP Clerk | `_create_exception` |
| `send_supplier_message` | Send supplier message | **no — irreversible** | AP Clerk | `_send_supplier_message` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `flag_contract_breach`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "supplier_id": …,
  "severity": …,
  "title": …,
  "description": …,
  "financial_impact_usd": …,
  "proposed_resolution": …
}
```

- Confidence: `0.93`
- Due in: `8` hours
- Carries priced alternatives for the reviewer
- Sets extra flags the policy engine reads

#### `send_supplier_message`

Raised on 1 branch.

```json
{
  "supplier_id": …,
  "invoice_id": …,
  "channel": …,
  "intent": …,
  "body": …
}
```

- Diff preview: `message`
- Confidence: `0.91`
- Due in: `12` hours

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `flag_contract_breach` | — |
| `create_exception` | `exceptions`, `invoices` |
| `send_supplier_message` | `supplier_messages` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Locate the governing contract | `contract_lookup` | Without a contract there is no rate to enforce. |
| 2 | Check term validity against the invoice date | `term_check` | Expired pricing is the most common silent overcharge. |
| 3 | Compare each line to the rate card and allowed charges | `contract_parsing` | Line-level comparison catches what header totals hide. |
| 4 | Test volume-discount eligibility | `discount_check` | Suppliers rarely apply tier discounts unprompted. |
| 5 | Propose recovery actions for approval | `hitl_checkpoint` | Short-paying a supplier is a commercial decision. |

### `gather()` — evidence collection

Resolves the contract governing the invoice, parses its commercial terms with
`contract_parsing`, and compares the invoice against them: unit prices against
the rate card, rebate and volume-discount entitlements, payment terms, and any
billing outside the contract's scope. Produces findings with a recoverable
amount attached to each.

### `decide()` — the reasoning

1. **No contract governs the invoice** → says so and proposes nothing. Absence
   of a contract is not a breach.
2. **No findings** → confirms conformance explicitly. A clean result is worth
   stating.
3. **Findings present** → a **`flag_contract_breach`** proposal carrying the
   first four findings and the total recoverable amount, with severity `high`
   at or above 5,000 USD recoverable and `medium` below. The first three finding
   codes go into `extra_flags` so the policy engine can act on the kind of
   breach, not just its size.
4. **Recoverable amount above zero and a supplier on file** → additionally a
   **`send_supplier_message`** draft itemising the first five findings, so the
   recovery conversation starts from a specific list rather than a general
   complaint.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Severity `high` | recoverable ≥ 5,000 USD | `decide()` |
| Escalation | recoverable ≥ 10,000 USD | `decide()` |
| Findings quoted in the proposal | 4 | `decide()` |
| Findings itemised to the supplier | 5 | `decide()` |
| Agent confidence threshold | 0.90 | class attribute |

### Escalation

Escalates at 10,000 USD recoverable.

### Handoff

`exception_resolution` where a finding is best resolved as a short-pay.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `contract_parsing` | Compare billed lines against the contracted rate card, term dates and allowed charges. | [contract](../../skills/contract_parsing/SKILL.md) |
| `variance_analysis` | Compare invoice lines against PO lines and goods receipts, line by line. | [contract](../../skills/variance_analysis/SKILL.md) |

Imported skill modules: `contract_parsing`

### Data it reads

- `contracts`
- `invoices`
- `purchase_orders`
- `suppliers`

### External systems

- Contract repository
- Rate card
- Invoice lines
- PO history

---

## 6 · Worked example

**Scenario.** A consultancy bills above its rate card and adds a surcharge.

**Given.** MCP-INV-5540 · senior consultants at 312.00 against 285.00 contracted, plus a 4,800 admin surcharge

**It does:**

1. Locates the governing contract and its rate card and allowed-charge list.
2. Line 1 is 27.00/hr over the contracted rate across 320 hours.
3. The admin surcharge matches no allowed charge type.
4. Totals what is recoverable by short-paying to contract.

**Produces.** A contract-breach flag with 13,440.00 recoverable, itemised, plus a drafted supplier notification.

**Decided by.** Procurement — short-pay, pursue a credit note, or accept as a variation.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Contract Intelligence Agent.

Mission:
Detect expired pricing, unauthorised charges, incorrect rates and missed discounts.

You have access to:
- Contract repository
- Rate card
- Invoice lines
- PO history

Goals:
1. Recover every dollar billed above the contracted rate card.
2. Catch charges that no contract clause permits.
3. Claim volume discounts the supplier did not apply.

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

1. Subclass `BaseAgent` in `backend/app/agents/contract_intelligence.py` with
   `key = "contract_intelligence"` and the identity, governance and `allowed_actions`
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

