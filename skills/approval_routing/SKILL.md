# Approval Routing Skill

> Generated from `backend/app/skills/approval_routing.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Select an approver with sufficient authority who is available and not overloaded.

## Inputs
- invoice_amount
- cost_center
- requester
- delegation_matrix
- calendar

## Output
```json
{
  "approver",
  "level",
  "reason",
  "alternates"
}
```

## Success Criteria
No invoice routed to an approver who is out of office or under-authorised.

## Failure Handling
If nobody qualifies, escalate to Controller with a documented reason.

## Used By
- approval_acceleration
- sla_command_center

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
