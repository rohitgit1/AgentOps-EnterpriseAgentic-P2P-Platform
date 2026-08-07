# Supplier Risk Agent

> **Build specification.** Generated from `backend/app/agents/supplier_risk.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`supplier_risk` · P2P AgentOps · class `SupplierRiskAgent`

**Role.** Continuously screens the vendor master for compliance and fraud exposure.

**Mission.** Detect supplier compliance and fraud risk before money moves.

**Module intent.**

```
Agent 7 — Supplier Risk.

Mission: monitor sanctions, insurance, tax forms and vendor-master changes,
and propose the block *before* the payment leaves.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| supplier_id | data | no | — | Screen one supplier. Omit to sweep the vendor master. | — |
| vendor master & registries | data | no | — | Sanctions, insurance, tax forms and bank-change log. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Screening findings | record | — | Per-supplier findings with severity and the action each implies. | — |
| Payment-blocking verdict | record | — | Whether the supplier may be paid right now. | — |
| Checkpoint | proposal | — | Block supplier / freeze invoice / request documentation. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `validation` | Workflow stage its checkpoints are filed under |
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
| `block_supplier` | Block supplier | **no — irreversible** | Controller | `_block_supplier` |
| `hold_invoice` | Place invoice on hold | yes | AP Clerk | `_hold_invoice` |
| `create_exception` | Open exception | yes | AP Clerk | `_create_exception` |
| `send_supplier_message` | Send supplier message | **no — irreversible** | AP Clerk | `_send_supplier_message` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `send_supplier_message`

Raised on 1 branch.

```json
{
  "supplier_id": …,
  "channel": …,
  "intent": …,
  "body": …
}
```

- Confidence: `0.93`
- Due in: `24` hours

#### `block_supplier`

Raised on 1 branch.

```json
{
  "supplier_id": …,
  "reason": …
}
```

- Diff preview: `on_hold`
- Confidence: `0.97`
- Due in: `2` hours
- Sets extra flags the policy engine reads

#### `create_exception`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "supplier_id": …,
  "exception_type": …,
  "severity": …,
  "title": …,
  "description": …,
  "financial_impact_usd": …,
  "proposed_resolution": …,
  "sla_hours": …
}
```

- Confidence: `0.95`
- Due in: `4` hours
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `block_supplier` | `suppliers` |
| `hold_invoice` | `invoices` |
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
| 1 | Select suppliers in scope | `vendor_scan` | Either one supplier or a full vendor-master sweep. |
| 2 | Run restricted-party screening | `sanction_screening` | A sanctions hit is an absolute payment bar. |
| 3 | Check document expiry and bank-change recency | `document_expiry_monitoring` | Fresh bank details are the strongest fraud signal in AP. |
| 4 | Score aggregate supplier risk | `vendor_risk` | One number that Procurement and Treasury can act on. |
| 5 | Propose blocks and holds for approval | `hitl_checkpoint` | Blocking a supplier stops their revenue — a person owns that call. |

### `gather()` — evidence collection

Screens the active vendor master through `vendor_risk.assess()`: sanctions and
watchlist hits, recent bank-detail changes inside the freeze window, expiring or
missing tax forms and insurance certificates, and performance signals. Returns
one assessment per supplier with a findings list carrying severities.

### `decide()` — the reasoning

Two distinct populations, handled differently:

**Payment-blocking findings** (`critical` or `high`). For each affected
supplier it computes live exposure — the sum of unpaid invoice totals — and:

- a **`block_supplier`** proposal when the headline finding is a sanctions hit.
  Nothing else is proportionate to a sanctions match;
- plus a **`create_exception`** on each of the first five unpaid invoices, so
  the block is visible where the money actually is rather than only on the
  supplier record. Five is a deliberate cap: the point is to make the exposure
  visible, not to flood the inbox.

**Document expiry** (`tax_form_missing`, `tax_form_expiring`,
`tax_form_expired`, `insurance_expiring`) → a **`send_supplier_message`** draft
chasing the document. These are administrative, not blocking, and are proposed
separately so a reviewer can clear them in a batch.

If nothing qualifies, it says so explicitly and proposes nothing. Silence and
"no risk found" are different messages.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Bank-change freeze window | 10 days | `risk.bank_change_freeze_days` policy key |
| Exposure invoices per supplier | 5 | `decide()` — a cap, not a limit on risk |
| Agent confidence threshold | 0.95 | class attribute |

### Escalation

Escalates whenever any payment-blocking finding exists.

### Handoff

`payment_readiness`, which must not schedule against a blocked supplier.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `vendor_risk` | Monitor sanctions, insurance, tax forms and vendor-master changes for fraud and compliance risk. | [contract](../../skills/vendor_risk/SKILL.md) |
| `sanction_screening` | _Declared by the agent; not in the shared catalogue._ | — |
| `document_expiry_monitoring` | _Declared by the agent; not in the shared catalogue._ | — |

Imported skill modules: `vendor_risk`

### Data it reads

- `invoices`
- `suppliers`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `risk.bank_change_freeze_days` | `10` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- Sanctions screening
- Vendor master change log
- Insurance registry
- Tax form registry

---

## 6 · Worked example

**Scenario.** A supplier changed bank details three days ago.

**Given.** Kestrel Print & Media · bank account changed within the 10-day freeze window

**It does:**

1. Sweeps the vendor master for sanctions, insurance, tax forms and bank changes.
2. Finds the bank change inside the freeze window — the strongest fraud signal in AP.
3. Calculates unpaid exposure to that supplier.

**Produces.** A payment-freeze exception per open invoice, with the verification step named.

**Decided by.** AP Clerk freezes; verification happens out-of-band with a known contact.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Supplier Risk Agent.

Mission:
Detect supplier compliance and fraud risk before money moves.

You have access to:
- Sanctions screening
- Vendor master change log
- Insurance registry
- Tax form registry

Goals:
1. Zero payments to sanctioned or unverified parties.
2. Catch every bank-detail change inside the verification freeze window.
3. Keep tax and insurance documentation current across the vendor base.

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

1. Subclass `BaseAgent` in `backend/app/agents/supplier_risk.py` with
   `key = "supplier_risk"` and the identity, governance and `allowed_actions`
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

