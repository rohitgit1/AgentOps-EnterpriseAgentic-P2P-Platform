# Payment Readiness Agent

> **Build specification.** Generated from `backend/app/agents/payment_readiness.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`payment_readiness` · P2P AgentOps · class `PaymentReadinessAgent`

**Role.** Builds the payment run proposal; Treasury approves every release.

**Mission.** Pay the right invoices on the right day — capturing discounts, avoiding late fees, blocking risk.

**Module intent.**

```
Agent 6 — Payment Readiness.

Mission: rank approved invoices for the payment run and never let a
compliance-blocked supplier through. Treasury releases; the agent ranks.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| approved invoices | data | no | — | Approved, ERP-posted, unpaid invoices — read automatically. | — |
| invoice_id | data | no | — | Restrict the run to one invoice. | — |
| supplier terms & risk | data | no | — | Discount terms, tier and compliance screening. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Payment run ranking | record | — | priority_score = due_risk + supplier_tier + discount_value + sla_risk, with each component shown. | — |
| Discount capture | record | — | Available early-pay discount and its deadline per invoice. | — |
| Checkpoint | proposal | — | Post to ERP / schedule payment / release payment / hold on compliance. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `payment` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.92` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `controller` — Controller | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `schedule_payment` | Schedule payment | **no — irreversible** | Treasury Analyst | `_schedule_payment` |
| `release_payment` | Release payment | **no — irreversible** | Controller | `_release_payment` |
| `hold_invoice` | Place invoice on hold | yes | AP Clerk | `_hold_invoice` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `post_to_erp`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "erp_system": …
}
```

- Diff preview: `erp_document_number`, `status`
- Confidence: `0.96`
- Due in: `6` hours
- Sets extra flags the policy engine reads

#### `release_payment`

Raised on 1 branch.

```json
{
  "payment_id": …
}
```

- Diff preview: `status`, `amount`
- Confidence: `0.95`
- Due in: `4` hours
- Sets extra flags the policy engine reads

#### `hold_invoice`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "reason": …
}
```

- Confidence: `0.96`
- Due in: `4` hours
- Sets extra flags the policy engine reads

#### `schedule_payment`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "amount": …,
  "scheduled_date": …,
  "discount_captured": …,
  "method": …,
  "priority_score": …,
  "score_breakdown": …
}
```

- Diff preview: `scheduled_date`, `discount_captured`
- Due in: `8` hours
- Carries priced alternatives for the reviewer

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `schedule_payment` | `invoices`, `payments` |
| `release_payment` | `invoices`, `payments`, `suppliers` |
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
| 1 | Collect approved, unpaid invoices | `ledger_scan` | Only approved and ERP-posted items are eligible. |
| 2 | Screen each supplier for payment blockers | `vendor_risk` | Compliance blocks outrank cash optimisation. |
| 3 | Score urgency, tier, discount and SLA risk | `payment_priority_scoring` | Score = due_risk + supplier_tier + discount_value + sla_risk. |
| 4 | Assemble the run and quantify discount capture | `run_assembly` | Treasury needs the cash number, not a list. |
| 5 | Submit the run for Treasury approval | `hitl_checkpoint` | Money never moves without a named approver. |

### `gather()` — evidence collection

Builds the payment picture in four passes: invoices approved but not yet posted
to the ERP; payments already scheduled and now due; invoices blocked by supplier
compliance (`vendor_risk`, including the bank-change freeze window); and, for
everything payable, a `payment_prioritization` score plus a
`discount_detection` result.

### `decide()` — the reasoning

Emits proposals in payment-lifecycle order so the inbox reads as a sequence
rather than a pile:

1. **`post_to_erp`** for approved-but-unposted invoices. Posting is the step
   that makes an invoice payable and it is irreversible, so it is its own
   checkpoint rather than being folded into scheduling.
2. **`release_payment`** for scheduled payments that have reached their date —
   but **a payment whose supplier is on hold is skipped entirely**, never
   proposed and then rejected. A release proposal for a blocked supplier is a
   trap for a distracted reviewer.
3. **`hold_invoice`** for each compliance-blocked invoice, with the blocking
   finding quoted.
4. **`schedule_payment`** for the rest, ordered by priority score, quoting the
   score breakdown and — when a discount is live — the deadline and the exact
   amount at stake.

The priority score is `due_risk + supplier_tier + discount_value + sla_risk`;
the breakdown is shown to the reviewer rather than just the total, because the
total on its own is not reviewable.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Bank-change payment freeze | 10 days | `risk.bank_change_freeze_days` policy key |
| Supplier tier weight | platinum 25 / gold 18 / silver 10 / bronze 5 | `TIER_WEIGHT` in `skills/payment_prioritization.py` |
| Agent confidence threshold | 0.93 | class attribute |
| Confidence | 0.93 – 0.96 by branch | `decide()` |

### Escalation

Escalates whenever any invoice is blocked by supplier compliance — that is a treasury-visible condition, not a queue item.

### Handoff

`supplier_risk` when a block originates in the vendor master.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `due_date_analysis` | _Declared by the agent; not in the shared catalogue._ | — |
| `discount_detection` | _Declared by the agent; not in the shared catalogue._ | — |
| `payment_priority_scoring` | _Declared by the agent; not in the shared catalogue._ | — |
| `vendor_risk` | Monitor sanctions, insurance, tax forms and vendor-master changes for fraud and compliance risk. | [contract](../../skills/vendor_risk/SKILL.md) |

Imported skill modules: `payment_prioritization`, `vendor_risk`

### Data it reads

- `invoices`
- `payments`
- `suppliers`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `risk.bank_change_freeze_days` | `10` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- Invoice ledger
- Supplier terms
- Vendor risk screening
- Cash calendar

---

## 6 · Worked example

**Scenario.** Building the week's payment run.

**Given.** Approved, ERP-posted, unpaid invoices across ten suppliers

**It does:**

1. Screens each supplier for compliance blocks — a sanctions review removes one outright.
2. Scores the rest: due_risk + supplier_tier + discount_value + sla_risk.
3. Flags a 2/10 discount expiring in two days.
4. Separates unposted invoices — they need an ERP posting first.

**Produces.** A ranked run with each score component shown, plus the discount capture number.

**Decided by.** Treasury schedules; Controller releases. Both are irreversible.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Payment Readiness Agent.

Mission:
Pay the right invoices on the right day — capturing discounts, avoiding late fees, blocking risk.

You have access to:
- Invoice ledger
- Supplier terms
- Vendor risk screening
- Cash calendar

Goals:
1. Capture available early-payment discounts before they expire.
2. Keep on-time payment above 98% for tier-1 suppliers.
3. Block any payment to a supplier under compliance review.

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

1. Subclass `BaseAgent` in `backend/app/agents/payment_readiness.py` with
   `key = "payment_readiness"` and the identity, governance and `allowed_actions`
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

