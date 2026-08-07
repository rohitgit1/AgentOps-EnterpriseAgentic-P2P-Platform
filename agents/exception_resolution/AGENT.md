# Exception Resolution Agent

> **Build specification.** Generated from `backend/app/agents/exception_agent.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`exception_resolution` · P2P AgentOps · class `ExceptionResolutionAgent`

**Role.** Diagnoses AP exceptions and proposes the resolution for human confirmation.

**Mission.** Resolve AP exceptions the same day they are raised, with a defensible rationale.

**Module intent.**

```
Agent 4 — Exception Resolution.

Mission: diagnose open AP exceptions and propose the resolution, with the
alternatives a human would otherwise have to construct themselves.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| exception_id | data | yes | — | The exception case to diagnose. | — |
| contract & PO context | data | no | — | Rate card and purchase order, fetched automatically. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Diagnosis | record | — | Recommended resolution with confidence and the priced alternatives. | — |
| Supplier message draft | record | — | Where the resolution needs the supplier, a drafted message. | — |
| Checkpoint | proposal | — | Resolve / chase receipt / correct / send message — AP decides. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `exception` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.9` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `ap_manager` — AP Manager | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `resolve_exception` | Resolve exception | yes | AP Clerk | `_resolve_exception` |
| `send_supplier_message` | Send supplier message | **no — irreversible** | AP Clerk | `_send_supplier_message` |
| `request_goods_receipt` | Request goods receipt | yes | AP Clerk | `_request_goods_receipt` |
| `update_invoice_fields` | Correct invoice fields | yes | AP Clerk | `_update_invoice_fields` |
| `hold_invoice` | Place invoice on hold | yes | AP Clerk | `_hold_invoice` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `resolve_exception`

Raised on 2 branches, e.g. *Short-pay to the contracted rate*; *Accept the variance and clear the exception*.

```json
{
  "exception_id": …,
  "resolution_notes": …,
  "adjust_total": …,
  "match_result": …
}
```

- Due in: `6` hours
- Carries priced alternatives for the reviewer

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
- Due in: `6` hours

#### `request_goods_receipt`

Raised on 1 branch, e.g. *Request the goods receipt*.

```json
{
  "invoice_id": …,
  "requester_id": …,
  "message": …
}
```

- Due in: `4` hours
- Carries priced alternatives for the reviewer

#### `hold_invoice`

Raised on 1 branch, e.g. *Hold pending duplicate confirmation*.

```json
{
  "invoice_id": …,
  "reason": …
}
```

- Due in: `4` hours
- Carries priced alternatives for the reviewer

#### `update_invoice_fields`

Raised on 1 branch, e.g. *Post the corrected tax figure*.

```json
{
  "invoice_id": …,
  "fields": …
}
```

- Carries priced alternatives for the reviewer

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `resolve_exception` | `exceptions`, `invoices` |
| `send_supplier_message` | `supplier_messages` |
| `request_goods_receipt` | `notifications` |
| `update_invoice_fields` | `invoices` |
| `hold_invoice` | `invoices` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Read the exception and its originating invoice | `exception_lookup` | Resolution depends on what actually failed, not the label. |
| 2 | Pull contract and PO context | `contract_parsing` | The contract usually decides who is right about price. |
| 3 | Apply the resolution playbook | `exception_resolution` | Codified AP practice beats ad-hoc judgement under time pressure. |
| 4 | Draft any supplier communication | `correspondence` | A draft saves the analyst the writing, not the decision. |
| 5 | Submit resolution and alternatives for approval | `hitl_checkpoint` | The analyst picks the option; the agent shows the trade-off. |

### `gather()` — evidence collection

Loads the exception, its invoice, the supplier and any governing contract, then
asks `exception_resolution.playbook()` for the recommended action and its priced
alternatives given the exception type and its financial context. Where a
contract exists, the contract unit price is pulled so a short-pay can be quoted
against a real number rather than an assumption.

### `decide()` — the reasoning

Confidence is computed first and gates everything: **below 0.70 the agent
proposes no resolution at all** and instead asks for the case to be assigned to
a human owner. A confident-sounding wrong resolution on an exception is worse
than no resolution.

Above that floor, it dispatches on the playbook's `recommended` value:

| Recommendation | Proposal |
|---|---|
| `short_pay_to_contract` | `resolve_exception` paying the contract price, with the delta quoted |
| `accept_within_tolerance` | `resolve_exception` absorbing the variance |
| `chase_receiver` | `request_goods_receipt` |
| `hold_and_confirm` | `hold_invoice` |
| `correct_tax` | `resolve_exception` with the recalculated tax |
| anything else | no proposal; escalate with "no playbook action applies" |

`short_pay_to_contract` additionally requires a contested line *and* a known
contract price — without both, the short-pay amount would be invented.

Every proposal carries the playbook's alternatives, so the reviewer can pick a
different resolution without leaving the checkpoint.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Minimum confidence to propose a resolution | 0.70 | `decide()` |
| Agent confidence threshold | 0.88 | class attribute |
| Escalation | financial impact ≥ 25,000 USD | `decide()` |

### Escalation

Escalates at 25,000 USD of financial impact, when confidence is below 0.70, and when no playbook action applies.

### Handoff

Back to the stage the exception blocks once resolved.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `exception_resolution` | Diagnose an AP exception and propose the resolution a human should confirm. | [contract](../../skills/exception_resolution/SKILL.md) |
| `variance_analysis` | Compare invoice lines against PO lines and goods receipts, line by line. | [contract](../../skills/variance_analysis/SKILL.md) |
| `contract_parsing` | Compare billed lines against the contracted rate card, term dates and allowed charges. | [contract](../../skills/contract_parsing/SKILL.md) |
| `duplicate_detection` | Detect exact and near-duplicate invoices before they reach payment. | [contract](../../skills/duplicate_detection/SKILL.md) |

Imported skill modules: `exception_resolution`

### Data it reads

- `contracts`
- `exceptions`
- `invoices`
- `purchase_orders`
- `suppliers`

### External systems

- Exception queue
- Contract rate card
- PO / receipt history
- Supplier correspondence

---

## 6 · Worked example

**Scenario.** A price-mismatch exception where a contract rate exists.

**Given.** EXC-5001 · invoiced 312.00/hr against a contracted 285.00/hr

**It does:**

1. Reads the exception and its originating invoice.
2. Finds the governing contract and its rate card.
3. Playbook: contract price governs where a rate-card entry exists.
4. Prices the three options a human would otherwise construct by hand.

**Produces.** Resolution proposal 'short-pay to contract' at 93% confidence, plus a drafted supplier message, plus two priced alternatives.

**Decided by.** AP Clerk — pick an option; the message sends separately.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Exception Resolution Agent.

Mission:
Resolve AP exceptions the same day they are raised, with a defensible rationale.

You have access to:
- Exception queue
- Contract rate card
- PO / receipt history
- Supplier correspondence

Goals:
1. Propose a correct first-time resolution for 60% of exceptions.
2. Cut exception aging by 70%.
3. Never write off value without an explicit human decision.

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

1. Subclass `BaseAgent` in `backend/app/agents/exception_agent.py` with
   `key = "exception_resolution"` and the identity, governance and `allowed_actions`
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

