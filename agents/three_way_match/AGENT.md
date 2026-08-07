# Three-Way Match Agent

> **Build specification.** Generated from `backend/app/agents/three_way_match.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`three_way_match` · P2P AgentOps · class `ThreeWayMatchAgent`

**Role.** Reconciles invoice, purchase order and goods receipt within policy tolerance.

**Mission.** Match Invoice ⇄ PO ⇄ Receipt and quantify every variance before anything is approved.

**Module intent.**

```
Agent 2 — Three-Way Match.

Mission: reconcile Invoice ⇄ PO ⇄ Receipt line by line, and be explicit about
what falls outside tolerance and what it costs.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| invoice_id | data | yes | — | The invoice to match. | — |
| PO & goods receipt | data | no | — | Fetched from the ERP connector — no attachment needed. | — |
| tolerance policy | data | no | — | Amount and quantity tolerances, read from policy-as-code. | `amount 3% / quantity 2% / 50 USD floor` |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Line-level variance analysis | record | — | Per-line price and quantity variance in percent and dollars. | — |
| Match result | record | — | matched / within_tolerance / price_variance / missing_receipt / no_match. | — |
| Checkpoint | proposal | — | Clear the match or open an exception — AP Clerk decides. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `matching` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.93` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `ap_manager` — AP Manager | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `advance_stage` | Advance workflow stage | yes | AP Clerk | `_advance_stage` |
| `create_exception` | Open exception | yes | AP Clerk | `_create_exception` |
| `request_goods_receipt` | Request goods receipt | yes | AP Clerk | `_request_goods_receipt` |
| `hold_invoice` | Place invoice on hold | yes | AP Clerk | `_hold_invoice` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `create_exception`

Raised on 2 branches, e.g. *Cannot match — purchase order missing*.

```json
{
  "invoice_id": …,
  "supplier_id": …,
  "exception_type": …,
  "severity": …,
  "title": …,
  "description": …,
  "financial_impact_usd": …,
  "match_result": …,
  "match_details": …,
  "proposed_resolution": …
}
```

- Due in: `4` hours
- Carries priced alternatives for the reviewer
- Sets extra flags the policy engine reads

#### `request_goods_receipt`

Raised on 1 branch, e.g. *Chase the goods receipt*.

```json
{
  "invoice_id": …,
  "requester_id": …,
  "message": …
}
```

- Confidence: `0.92`
- Due in: `4` hours

#### `advance_stage`

Raised on 1 branch, e.g. *Clear three-way match and route to approval*.

```json
{
  "invoice_id": …,
  "stage": …,
  "status": …,
  "match_result": …,
  "match_details": …
}
```

- Diff preview: `match_result`, `stage`
- Due in: `6` hours

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `advance_stage` | `invoices` |
| `create_exception` | `exceptions`, `invoices` |
| `request_goods_receipt` | `notifications` |
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
| 1 | Fetch the purchase order and its lines | `po_fetch` | The PO is the contractual basis for what may be billed. |
| 2 | Fetch goods receipts posted against the PO | `gr_fetch` | Receipt confirms the goods or services actually arrived. |
| 3 | Run line-level variance analysis | `variance_analysis` | Header totals hide offsetting line errors. |
| 4 | Apply tolerance policy | `policy_compliance` | Tolerance is a governance decision, not an agent preference. |
| 5 | Propose clearance or an exception | `hitl_checkpoint` | Either outcome is reviewed by AP before it takes effect. |

### `gather()` — evidence collection

Reads tolerances from policy-as-code first, so a governance change takes effect
without a deploy. Then:

1. Uses `invoice.po_id` if set; otherwise falls back to `po_lookup.lookup()` to
   recover the PO. If neither finds one, returns early with what it has.
2. Sums received quantity **per PO line** across all goods receipts
   (`receipt.lines_json`), not per receipt — a partial receipt against one line
   must not appear to satisfy another.
3. `variance_analysis.analyze()` line by line, given the invoice lines, the PO
   lines, the received-quantity map and all three tolerances.
4. Records the tolerances actually applied as their own observation, so the
   reviewer sees the rule that was used rather than having to assume it.

### `decide()` — the reasoning

1. **No PO** → `create_exception` of type `missing_po`, escalate, hand off.
   Returns.
2. **Clean** (`analysis["clean"]`) → `advance_stage` to `approval` with status
   `matched`, carrying `match_result` and the full `match_details` so the
   analysis is preserved on the invoice for audit.
3. **Otherwise** → map the match result to an exception type
   (`missing_receipt` → `missing_receipt`, `price_variance` → `price_mismatch`,
   `quantity_variance` → `quantity_mismatch`, `no_match` → `price_mismatch`),
   pick the worst line by absolute variance, and ask
   `exception_resolution.playbook()` for a resolution and priced alternatives.
   When the result is specifically `missing_receipt`, a second
   `request_goods_receipt` proposal is added — chasing the receipt is the action
   that actually unblocks the invoice, and it carries zero financial impact.

A variance is judged against **all three** tolerances: percentage, absolute
floor, and per-line quantity percentage. The absolute floor exists so a small
percentage on a large invoice still stops.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Amount variance tolerance | 3.0 % | `match.amount_variance_pct` policy key |
| Quantity variance tolerance | 2.0 % | `match.quantity_variance_pct` policy key |
| Absolute variance floor | 50 USD | `match.amount_variance_abs` policy key |
| Confidence — exact match | 0.97 | `decide()` |
| Confidence — within tolerance | 0.94 | `decide()` |
| Confidence — exception path | `min(0.96, 0.80 + 0.16 × has_worst_line)` | `decide()` |
| Manager escalation | variance ≥ 10,000 USD | `decide()` |

### Escalation

Escalates when the absolute net variance reaches 10,000 USD, and always when no PO could be resolved.

### Handoff

`approval_acceleration` on a clean match; `exception_resolution` otherwise.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `po_fetch` | _Declared by the agent; not in the shared catalogue._ | — |
| `gr_fetch` | _Declared by the agent; not in the shared catalogue._ | — |
| `variance_analysis` | Compare invoice lines against PO lines and goods receipts, line by line. | [contract](../../skills/variance_analysis/SKILL.md) |
| `policy_compliance` | _Declared by the agent; not in the shared catalogue._ | — |

Imported skill modules: `exception_resolution`, `po_lookup`, `variance_analysis`

### Data it reads

- `invoices`
- `purchase_orders`
- `receipts`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `match.amount_variance_abs` | `50.0` |
| `match.amount_variance_pct` | `3.0` |
| `match.quantity_variance_pct` | `2.0` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- ERP purchase orders
- Goods receipts
- Contract rate card
- Tolerance policy

---

## 6 · Worked example

**Scenario.** A chemicals supplier bills 8% above the PO rate.

**Given.** BWC-449021 · 60 drums at 1,274.40 against a PO rate of 1,180.00

**It does:**

1. Fetches PO-44213 and its goods receipts.
2. Compares line by line: line 1 price variance +8.0%, line 2 clean.
3. Applies the 3% amount tolerance and the 50 USD absolute floor.
4. Variance of 5,664.00 is outside both.

**Produces.** Exception proposal: price_variance, 5,664.00 at stake, with the failing line and the tolerance it broke.

**Decided by.** AP Clerk — short-pay to PO, accept the increase, or query the supplier.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Three-Way Match Agent.

Mission:
Match Invoice ⇄ PO ⇄ Receipt and quantify every variance before anything is approved.

You have access to:
- ERP purchase orders
- Goods receipts
- Contract rate card
- Tolerance policy

Goals:
1. Clear clean matches quickly so they never age.
2. Quantify every variance in dollars, not just percentages.
3. Never absorb a variance outside tolerance without a human decision.

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

1. Subclass `BaseAgent` in `backend/app/agents/three_way_match.py` with
   `key = "three_way_match"` and the identity, governance and `allowed_actions`
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

