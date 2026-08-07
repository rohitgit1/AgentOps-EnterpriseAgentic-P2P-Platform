# Procurement Request Agent

> **Build specification.** Generated from `backend/app/agents/procurement_request.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`procurement_request` · P2P AgentOps · class `ProcurementRequestAgent`

**Role.** Triages purchase requests against the spend-authority ladder.

**Mission.** Route purchase requests to the right authority with the policy basis stated.

**Module intent.**

```
Agent 8 — Procurement Request.

Mission: triage intake requests against the approval policy ladder. Note that
even the "auto_approve" band still lands on a human checkpoint here: the policy
decides the *route*, governance decides whether anything executes unattended.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| request_id | data | yes | — | The purchase request to triage. | — |
| spend policy | data | no | — | The authority ladder, read from policy-as-code. | `under 5k / under 10k / above 10k` |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Routing decision | record | — | The policy band and the authority the request routes to. | — |
| Contract-cover note | record | — | Whether the nominated supplier is on contract. | — |
| Checkpoint | proposal | — | Approve the purchase request at the applicable authority. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `intake` | Workflow stage its checkpoints are filed under |
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
| `approve_purchase_request` | Approve purchase request | **no — irreversible** | Procurement Lead | `_approve_purchase_request` |
| `create_purchase_request` | Create purchase request | yes | AP Clerk | `_create_purchase_request` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `approve_purchase_request`

Raised on 1 branch.

```json
{
  "request_id": …,
  "routing_decision": …,
  "policy_notes": …
}
```

- Diff preview: `status`
- Due in: `12` hours
- Carries priced alternatives for the reviewer
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `approve_purchase_request` | `purchase_requests` |
| `create_purchase_request` | `purchase_requests` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Read the request and its value | `request_lookup` | Value determines which authority band applies. |
| 2 | Apply the spend-authority policy ladder | `policy_routing` | Under 5k / under 10k / above 10k routes differently. |
| 3 | Check for an existing contract with this supplier | `contract_parsing` | Contracted spend is cheaper and faster than new sourcing. |
| 4 | Propose the routing decision for approval | `hitl_checkpoint` | Committing spend is irreversible. |

### `gather()` — evidence collection

Loads the purchase request, the nominated supplier and any contract covering the
category, then reads the two approval bands from policy. `policy_routing`
determines the approval band from the request amount.

### `decide()` — the reasoning

A single `approve_purchase_request` proposal, routed to a band by value:

| Amount | Band |
|---|---|
| below the auto-approve threshold | AP Manager |
| below the manager-review threshold | Controller |
| at or above | CFO |

Two conditions modify it rather than blocking it:

- **No contract covers the category** → `extra_flags=["off_contract"]`, so the
  policy engine and the reviewer both see it. Off-contract is a fact to surface,
  not a veto — sometimes it is the right answer.
- **Supplier is on hold** → stated prominently in the summary. The agent does
  not silently drop the request; a human decides whether to substitute.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Auto-approve band ceiling | 5,000 USD | `procurement.auto_approve_under` policy key |
| Manager-review band ceiling | 10,000 USD | `procurement.manager_review_under` policy key |
| Agent confidence threshold | 0.91 | class attribute |

### Escalation

Escalates at or above the manager-review ceiling.

### Handoff

None — an approved request becomes a purchase order outside this agent.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `policy_routing` | _Declared by the agent; not in the shared catalogue._ | — |
| `contract_parsing` | Compare billed lines against the contracted rate card, term dates and allowed charges. | [contract](../../skills/contract_parsing/SKILL.md) |
| `supplier_lookup` | Resolve an extracted supplier name to a vendor master record. | [contract](../../skills/supplier_lookup/SKILL.md) |

### Data it reads

- `contracts`
- `purchase_requests`
- `suppliers`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `procurement.auto_approve_under` | `5000.0` |
| `procurement.manager_review_under` | `10000.0` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- Purchase request queue
- Contract catalogue
- Preferred supplier list
- Budget policy

---

## 6 · Worked example

**Scenario.** A 9,080 USD software request.

**Given.** PR-3002 · 40 additional seats · Aurora Software Systems

**It does:**

1. Reads the request value against the spend-authority ladder.
2. 9,080 falls in the under-10k band → manager review.
3. Checks contract cover — the supplier is on an active agreement.

**Produces.** A routing decision naming the band and the authority, with the contract note.

**Decided by.** AP Manager approves at the applicable authority.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Procurement Request Agent.

Mission:
Route purchase requests to the right authority with the policy basis stated.

You have access to:
- Purchase request queue
- Contract catalogue
- Preferred supplier list
- Budget policy

Goals:
1. Apply the spend ladder consistently and visibly.
2. Steer demand toward contracted, pre-negotiated suppliers.
3. Keep requisition cycle time under one day.

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

1. Subclass `BaseAgent` in `backend/app/agents/procurement_request.py` with
   `key = "procurement_request"` and the identity, governance and `allowed_actions`
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

