# Supplier Experience Agent

> **Build specification.** Generated from `backend/app/agents/supplier_experience.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`supplier_experience` · P2P AgentOps · class `SupplierExperienceAgent`

**Role.** Answers supplier enquiries from system-of-record facts, never from guesswork.

**Mission.** Resolve supplier enquiries on first contact and cut inquiry volume reaching the AP team.

**Module intent.**

```
Agent 5 — Supplier Experience.

Mission: answer supplier enquiries accurately across channels. Every outbound
message is a draft until a human approves it — the supplier never receives
unreviewed text.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| message_id | data | yes | — | The inbound supplier enquiry to answer. | — |
| invoice & payment ledger | data | no | — | The system-of-record facts the reply may cite. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Intent classification | record | — | invoice_status / payment_date / missing_information / banking_verification / po_details / dispute. | — |
| Drafted reply | record | — | Reply grounded only in retrieved records — never sent unreleased. | — |
| Checkpoint | proposal | — | Release the reply to the supplier — a human sends it. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `validation` | Workflow stage its checkpoints are filed under |
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
| `send_supplier_message` | Send supplier message | **no — irreversible** | AP Clerk | `_send_supplier_message` |
| `no_op` | No action required | yes | AP Clerk | `_no_op` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `send_supplier_message`

Raised on 2 branches, e.g. *Reply with the banking-change protocol (no details disclosed)*.

```json
{
  "supplier_id": …,
  "invoice_id": …,
  "thread_id": …,
  "channel": …,
  "intent": …,
  "body": …
}
```

- Diff preview: `message`
- Due in: `6` hours
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `send_supplier_message` | `supplier_messages` |
| `no_op` | — |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Identify the supplier and authenticate the channel | `supplier_lookup` | Answers must never go to an unverified party. |
| 2 | Classify the enquiry intent | `intent_classification` | The intent decides which ledger to read. |
| 3 | Retrieve the facts from the system of record | `invoice_status` | Every statement in the reply must be traceable. |
| 4 | Draft a reply grounded only in retrieved facts | `correspondence` | No speculative dates or commitments. |
| 5 | Submit the draft for human release | `hitl_checkpoint` | Outbound supplier communication is irreversible. |

### `gather()` — evidence collection

Classifies the inbound message's intent, then retrieves only what that intent
needs: the referenced invoice, its payment record, its open exceptions, its PO,
and the supplier's contractual terms. Nothing is fetched speculatively — the
reply must be grounded in retrieved records, and a record that was not retrieved
cannot appear in it.

### `decide()` — the reasoning

**Banking-change requests are a hard stop.** Any message asking to change bank
details is never handled over an inbound channel, at any confidence — it is the
single highest-value fraud vector in accounts payable. The agent escalates and
proposes a reply that says the change must be verified out of band.

Otherwise it builds a reply whose every sentence is traceable to a retrieved
record, dispatching on intent:

- **`payment_status`** — in strict precedence: a released payment quotes the
  settled facts; a scheduled payment quotes the scheduled date; open blockers
  mean **no date is promised at all**, only the blockers; failing all of those,
  contractual terms are quoted as terms, never as a commitment.
- **`missing_information`** — quotes the open exceptions verbatim. They already
  say exactly what is missing.
- **`po_details`** — reads the PO reference off the matched record.
- **`dispute`** — acknowledges receipt and hands to a human. A dispute is a
  commercial conversation, not a lookup.
- **no invoice identified** — replies with a verified summary and asks for the
  invoice number.

The proposal is always a *draft* reply. The agent never sends.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Agent confidence threshold | 0.90 | class attribute |
| Confidence — banking change | 0.97 | `decide()` |
| Confidence — no invoice identified | `max(0.75, base)` | `decide()` |

### Escalation

Always on a banking-change request or a dispute; otherwise when the message cannot be grounded in a retrieved record.

### Handoff

`exception_resolution` when the message reveals a blocker not yet raised as an exception.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `supplier_lookup` | Resolve an extracted supplier name to a vendor master record. | [contract](../../skills/supplier_lookup/SKILL.md) |
| `invoice_status` | _Declared by the agent; not in the shared catalogue._ | — |
| `payment_forecast` | _Declared by the agent; not in the shared catalogue._ | — |
| `correspondence` | _Declared by the agent; not in the shared catalogue._ | — |

Imported skill modules: `supplier_lookup`

### Data it reads

- `exceptions`
- `invoices`
- `payments`
- `supplier_messages`
- `suppliers`

### External systems

- Vendor portal
- Email
- Microsoft Teams
- Invoice ledger
- Payment ledger

---

## 6 · Worked example

**Scenario.** A supplier asks when they will be paid.

**Given.** Portal message from Cascade Packaging about CSP-77120

**It does:**

1. Authenticates the portal session against vendor master.
2. Classifies intent as payment_date at 86%.
3. Reads the invoice and payment ledger for facts it may cite.
4. Finds an open exception blocking payment — so it will not promise a date.

**Produces.** A drafted reply stating the blocker in the supplier's own terms, with no speculative payment date.

**Decided by.** AP Clerk — release the reply. The supplier sees nothing until then.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Supplier Experience Agent.

Mission:
Resolve supplier enquiries on first contact and cut inquiry volume reaching the AP team.

You have access to:
- Vendor portal
- Email
- Microsoft Teams
- Invoice ledger
- Payment ledger

Goals:
1. Reduce supplier inquiry volume reaching humans by 60%.
2. Answer only from verified system-of-record data.
3. Never disclose banking details or confirm a bank change over an inbound channel.

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

1. Subclass `BaseAgent` in `backend/app/agents/supplier_experience.py` with
   `key = "supplier_experience"` and the identity, governance and `allowed_actions`
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

