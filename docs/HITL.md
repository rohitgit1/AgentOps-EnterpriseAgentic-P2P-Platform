# Human-in-the-Loop: how it is enforced

This document exists because "human-in-the-loop" is usually a claim. Here it is
a set of code paths you can read.

## The invariant

> An agent cannot mutate a system of record. Its only output is a proposal.

Not "does not by convention" — **cannot**. There is no method on any agent that
writes business data. `BaseAgent.run()` returns `ProposedAction` objects; the
only consumer of those is `hitl.create_checkpoint()`, which writes a `HumanTask`
row describing what *would* change.

## The seven gates

`services/policy.evaluate()` runs for every proposed action. It is **default
deny**: `allow_auto_execute` is true only when every gate opens. Each gate's
outcome is recorded so the decision is explainable months later.

| # | Gate | Holds the action when |
|---|---|---|
| 1 | Global HITL enforcement | The tenant-wide switch is on (default) |
| 2 | Agent enabled + autonomy level | Agent disabled, fleet paused, or autonomy ≤ L2 |
| 3 | **Irreversibility** | The action is irreversible or outward-facing |
| 4 | Confidence | Below the agent's threshold |
| 5 | Financial envelope | Impact exceeds the agent's auto-execution ceiling |
| 6 | Risk level | Computed risk is high or critical |
| 7 | Action allow-list | The action is not in the agent's permitted set |

Gate 3 is unconditional. These actions always require a person, at any autonomy
level and with enforcement off:

```
post_to_erp · release_payment · schedule_payment · send_supplier_message
update_supplier_master · block_supplier · approve_purchase_request
```

## Autonomy levels

| Level | Behaviour |
|---|---|
| **L0 · Observe Only** | Analyse and report; never propose |
| **L1 · Suggest** | Propose; a human must act on every item |
| **L2 · Human Approval** | Propose with a staged payload; a human approves. **Default for all ten agents** |
| **L3 · Auto within Guardrails** | Auto-execute only inside the policy envelope; irreversible actions still stop |
| **L4 · Full Auto** | Disabled while global enforcement is on |

Raising an agent above L2 requires Controller authority and is audited.

## Role authority

`ROLE_AUTHORITY` ranks roles; `ACTION_MIN_ROLE` maps each action to a floor. The
floor escalates with financial impact — past $50k it becomes Controller, past
$250k it becomes CFO — and above the dual-approval threshold an irreversible
action needs two *distinct* approvers.

```
supplier(0) < ap_clerk(10) < procurement/treasury(20)
            < ap_manager(30) < controller(40) < cfo(50) < admin(60)
```

Enforcement is server-side in `hitl.decide()`. The UI disables the buttons as a
courtesy; the API refuses regardless.

## The five decisions

| Decision | Effect |
|---|---|
| **Approve** | Executes the proposed payload exactly as staged |
| **Modify & approve** | Human edits the payload, then it executes — recorded as `modified` |
| **Reject** | Nothing executes; the entity is placed on hold with the stated reason. A written reason is **required** |
| **Request info** | Parks the checkpoint. A written reason is required |
| **Escalate** | Raises the required role and re-queues for a senior reviewer |

Rejections and modifications are first-class signals: the per-agent
acceptance/modification rates on the Command Center are how you decide whether
an agent has earned more autonomy.

## Bulk approval, deliberately limited

`POST /hitl/tasks/bulk-decide` exists for volume, but refuses anything
irreversible, high/critical risk, or requiring dual approval. Batch actions must
not become a way around individual review.

## The audit trail

Every checkpoint creation, every human decision and every applied action writes
an `AuditLog` row containing actor, role, before/after state, the agent, the
confidence, and whether HITL was enforced. Each row's `hash_chain` is
`sha256(previous_hash | canonical_payload)`.

`GET /api/audit/verify` recomputes the chain from genesis and reports the first
divergence, if any. `GET /api/audit/export` produces the CSV for an audit pack.

## What "enforcement off" actually does

Turning off the master switch does **not** make agents autonomous. It opens gate
1 only. Gates 2–7 still apply, so an agent still needs: to be enabled, an
autonomy level of L3+, a reversible action, confidence above its threshold,
financial impact inside its ceiling, non-high risk, and the action on its
allow-list. In the shipped configuration every agent sits at L2 with a $0
ceiling, so nothing auto-executes even with the switch off. The switch exists so
the governance story can be demonstrated, and flipping it is audited.
