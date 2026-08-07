# SLA Command Center Agent

> **Build specification.** Generated from `backend/app/agents/sla_command_center.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`sla_command_center` · P2P AgentOps · class `SLACommandCenterAgent`

**Role.** Forecasts portfolio-wide SLA risk and proposes the intervention that protects it.

**Mission.** Predict SLA breaches early enough that a human can still prevent them.

**Module intent.**

```
Agent 10 — SLA Command Center.

Mission: forecast SLA breaches across the whole portfolio, rebalance workload,
and raise executive alerts with the number attached.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| in-flight portfolio | data | no | — | Every open invoice, its stage, approver and exceptions. | — |
| SLA policy | data | no | — | Cycle target and thresholds, read from policy-as-code. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Risk register | record | — | Per-invoice breach forecast with the drivers and hours remaining. | — |
| Workload analysis | record | — | Queue depth per approver and the rebalancing moves available. | — |
| Checkpoint | proposal | — | Rebalance workload / escalate / raise an executive alert. | — |

Accepts attachments: **no** · Produces downloadable files: **no**

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `approval` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.88` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `controller` — Controller | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `rebalance_workload` | Rebalance workload | yes | AP Manager | `_rebalance_workload` |
| `raise_executive_alert` | Raise executive alert | yes | AP Manager | `_raise_executive_alert` |
| `escalate_approval` | Escalate approval | yes | AP Manager | `_escalate_approval` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

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

- Confidence: `0.9`
- Due in: `2` hours

#### `raise_executive_alert`

Raised on 1 branch.

```json
{
  "title": …,
  "body": …,
  "target_role": …
}
```

- Confidence: `0.94`
- Due in: `4` hours

#### `rebalance_workload`

Raised on 1 branch.

```json
{
  "moves": …
}
```

- Confidence: `0.92`
- Due in: `6` hours

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `rebalance_workload` | `approvals`, `invoices`, `users` |
| `raise_executive_alert` | `notifications` |
| `escalate_approval` | `approvals`, `invoices`, `notifications` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Sweep every in-flight invoice | `portfolio_scan` | SLA is a portfolio property, not a per-invoice one. |
| 2 | Forecast breach risk per invoice | `sla_prediction` | Risk must be quantified before it can be triaged. |
| 3 | Measure queue depth per approver | `workload_balancing` | Most breaches are a queue problem, not an effort problem. |
| 4 | Compose the intervention set | `forecasting` | Rebalancing is cheaper than escalating. |
| 5 | Submit interventions for approval | `hitl_checkpoint` | Reassigning someone's work is a management decision. |

### `gather()` — evidence collection

Forecasts every in-flight invoice with `sla_prediction`, which costs the
**remaining** stages rather than the whole workflow. The exception stage is
excluded from the remaining-effort estimate unless the invoice is actually in
it — charging every invoice for exception handling forecasts the entire
portfolio at risk, which is both wrong and useless. Also measures queue depth
and out-of-office state per approver.

### `decide()` — the reasoning

Three independent outputs, all proposals:

1. **Workload rebalancing.** A queue with depth ≥ 6, or any queue whose owner is
   out of office, is a donor; a queue with depth ≤ 2 whose owner is present is a
   receiver. Moves are only proposed where the receiver's approval limit covers
   the invoice — a rebalance that creates an unapprovable assignment has moved
   the problem, not solved it. Emitted as `rebalance_workload`.
2. **SLA risk register.** Each at-risk or breached invoice is written to the
   register with its drivers, `breached` when hours remaining has reached zero
   and `at_risk` otherwise.
3. **Executive alert.** When forecast compliance falls below the 99 % target,
   a `raise_executive_alert` proposal with the compliance figure and the drivers
   behind it.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Target cycle time | 24 h | `sla.invoice_cycle_hours` policy key |
| Compliance target | 99 % | `decide()` |
| Overloaded queue | depth ≥ 6, or owner out of office | `decide()` |
| Receiving queue | depth ≤ 2, owner present, not unassigned | `decide()` |
| Breached | hours remaining ≤ 0 | `decide()` |
| Escalation | forecast compliance < 95 % | `decide()` |

### Escalation

Escalates when forecast compliance falls below 95 %.

### Handoff

`approval_acceleration` for the individual invoices it identifies.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `sla_prediction` | Forecast which invoices will breach cycle-time SLA and why. | [contract](../../skills/sla_prediction/SKILL.md) |
| `workload_balancing` | _Declared by the agent; not in the shared catalogue._ | — |
| `forecasting` | _Declared by the agent; not in the shared catalogue._ | — |

Imported skill modules: `sla_prediction`

### Data it reads

- `approvals`
- `invoices`
- `sla_risks`
- `users`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `sla.invoice_cycle_hours` | `24` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- Invoice portfolio
- Approval queues
- Workload model
- Executive alerting

---

## 6 · Worked example

**Scenario.** The portfolio is forecast to miss its SLA target.

**Given.** 15 invoices in flight, one approver holding 7 items

**It does:**

1. Forecasts breach risk per invoice from stage, age, exceptions and approver load.
2. Measures queue depth per approver and finds the bottleneck.
3. Prefers rebalancing over escalation — it costs nobody authority.

**Produces.** A rebalancing plan, targeted escalations, and an executive alert with the exposure number.

**Decided by.** AP Manager rebalances; CFO receives the alert.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the SLA Command Center Agent.

Mission:
Predict SLA breaches early enough that a human can still prevent them.

You have access to:
- Invoice portfolio
- Approval queues
- Workload model
- Executive alerting

Goals:
1. Hold SLA compliance above 99%.
2. Redistribute workload before a queue becomes the bottleneck.
3. Give executives a number, not an anecdote.

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

1. Subclass `BaseAgent` in `backend/app/agents/sla_command_center.py` with
   `key = "sla_command_center"` and the identity, governance and `allowed_actions`
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

