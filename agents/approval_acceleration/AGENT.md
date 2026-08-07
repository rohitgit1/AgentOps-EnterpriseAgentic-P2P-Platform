# Approval Acceleration Agent

> **Build specification.** Generated from `backend/app/agents/approval_acceleration.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`approval_acceleration` · P2P AgentOps · class `ApprovalAccelerationAgent`

**Role.** Keeps approvals moving without breaching delegation or audit policy.

**Mission.** Prevent invoices from breaching SLA while they sit in an approval queue.

**Module intent.**

```
Agent 3 — Approval Acceleration.

Mission: prevent approval-related SLA breaches. Reminder before escalation,
no duplicate notifications, delegation policy respected.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| invoice_id | data | yes | — | The invoice whose approval is being chased. | — |
| approval queue & calendar | data | no | — | Approver availability, delegation matrix and queue depth. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Routing decision | record | — | Chosen approver, level, and the authority basis for the choice. | — |
| SLA forecast | record | — | Breach risk score with the drivers behind it. | — |
| Checkpoint | proposal | — | Route / remind / reroute to delegate / escalate. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `approval` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.9` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `controller` — Controller | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `route_for_approval` | Route for approval | yes | AP Clerk | `_route_for_approval` |
| `send_approval_reminder` | Send approval reminder | yes | AP Clerk | `_send_reminder` |
| `escalate_approval` | Escalate approval | yes | AP Manager | `_escalate_approval` |
| `reassign_approver` | Reroute to delegate | yes | AP Manager | `_reassign_approver` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `route_for_approval`

Raised on 1 branch.

```json
{
  "invoice_id": …,
  "approver_id": …,
  "level": …,
  "due_in_hours": …,
  "routing_reason": …
}
```

- Diff preview: `approver_id`
- Confidence: `0.94`
- Due in: `4` hours
- Carries priced alternatives for the reviewer

#### `escalate_approval`

Raised on 1 branch.

```json
{
  "approval_id": …,
  "escalate_to_id": …,
  "due_in_hours": …,
  "reason": …,
  "message": …
}
```

- Confidence: `0.93`
- Due in: `2` hours

#### `send_approval_reminder`

Raised on 1 branch.

```json
{
  "approval_id": …,
  "message": …
}
```

- Confidence: `0.95`
- Due in: `4` hours

#### `reassign_approver`

Raised on 1 branch.

```json
{
  "approval_id": …,
  "delegate_id": …,
  "reason": …,
  "message": …
}
```

- Diff preview: `approver`
- Confidence: `0.95`
- Due in: `3` hours

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `route_for_approval` | `approvals`, `invoices`, `notifications` |
| `send_approval_reminder` | `approvals`, `notifications` |
| `escalate_approval` | `approvals`, `invoices`, `notifications` |
| `reassign_approver` | `approvals`, `invoices`, `notifications`, `users` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Read the current approval state | `approval_lookup` | Decides whether this is a routing problem or a chasing problem. |
| 2 | Check approver availability and delegation | `calendar_access` | Chasing someone who is out of office wastes the SLA window. |
| 3 | Forecast SLA breach risk | `sla_prediction` | Intervention should be proportionate to real risk. |
| 4 | Choose reminder, reroute or escalation | `escalation_planning` | Policy: reminder before escalation; never both at once. |
| 5 | Submit the intervention for approval | `hitl_checkpoint` | Even a reminder is an outbound action a human signs off on. |

### `gather()` — evidence collection

Reads the three SLA windows from policy, then assembles: the invoice's current
approver and their out-of-office and delegate state, the queue depth of every
qualified approver, how long the invoice has been waiting, whether a reminder
has already gone out, and an SLA forecast from `sla_prediction`.
`approval_routing.route()` returns the preferred approver.

### `decide()` — the reasoning

Ordered branches, first match wins. The order encodes a real preference: never
chase someone who cannot act.

1. **Not yet routed** → `route_for_approval` to the routing skill's choice. The
   chosen approver is the **lowest-authority qualified approver with the
   shortest queue** — routing to the CFO because they can approve anything is a
   bottleneck, not a control.
2. **Approver out of office with a qualified delegate** → `reassign_approver`.
   A reminder to an absent approver is wasted, so rerouting is evaluated before
   either reminder or escalation. If there is no delegate whose approval limit
   covers the amount, it escalates instead.
3. **Age ≥ escalation window, or forecast risk is critical** →
   `escalate_approval`. If the invoice has already been escalated, it proposes
   nothing rather than escalating twice.
4. **Age ≥ reminder window, or forecast risk is high** →
   `send_approval_reminder`, **unless one went out in the last 12 hours** — a
   duplicate nudge trains people to ignore the channel.
5. **Otherwise** → no action, stated explicitly with the remaining headroom.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Reminder window | 48 h | `sla.approval_reminder_hours` policy key |
| Escalation window | 72 h | `sla.approval_escalation_hours` policy key |
| Target cycle time | 24 h | `sla.invoice_cycle_hours` policy key |
| Reminder suppression | 12 h since last reminder | `decide()` |
| Confidence | 0.90 – 0.96 by branch | `decide()` |

### Escalation

Escalates when the approver is absent with no qualified delegate, and when no escalation target exists at all — both are situations no automated action can resolve.

### Handoff

None. The invoice stays with approval until a human acts.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `approval_lookup` | _Declared by the agent; not in the shared catalogue._ | — |
| `calendar_access` | _Declared by the agent; not in the shared catalogue._ | — |
| `escalation_planning` | _Declared by the agent; not in the shared catalogue._ | — |
| `delegation_management` | _Declared by the agent; not in the shared catalogue._ | — |

Imported skill modules: `approval_routing`, `sla_prediction`

### Data it reads

- `approvals`
- `invoices`
- `users`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `sla.approval_escalation_hours` | `72` |
| `sla.approval_reminder_hours` | `48` |
| `sla.invoice_cycle_hours` | `24` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- ERP
- Approval queue
- User calendar
- Delegation matrix
- Notification service

---

## 6 · Worked example

**Scenario.** An invoice has been sitting 79 hours with an approver who is out of office.

**Given.** VIS-2026-08702 · pending with Tomas Lindqvist (OOO for 5 days)

**It does:**

1. Reads the open approval: 79h old, 1 reminder already sent.
2. Checks the calendar — approver is out of office.
3. Reads the delegation matrix — Dana Okafor is named, limit covers the value.
4. Policy says reroute before escalating; a reminder to an absent approver is wasted.

**Produces.** Reroute proposal to the named delegate, with the SLA hours remaining.

**Decided by.** AP Clerk — approve the reroute, or escalate instead.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Approval Acceleration Agent.

Mission:
Prevent invoices from breaching SLA while they sit in an approval queue.

You have access to:
- ERP
- Approval queue
- User calendar
- Delegation matrix
- Notification service

Goals:
1. Reduce approval cycle time from days to hours.
2. Escalate proactively rather than retrospectively.
3. Preserve audit compliance and delegation policy at all times.

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

1. Subclass `BaseAgent` in `backend/app/agents/approval_acceleration.py` with
   `key = "approval_acceleration"` and the identity, governance and `allowed_actions`
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

