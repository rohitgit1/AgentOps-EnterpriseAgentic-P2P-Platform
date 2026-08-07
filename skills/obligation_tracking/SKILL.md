# Obligation & Renewal Tracking Skill

> Generated from `backend/app/skills/obligation_tracking.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Extract deliverables, SLAs, rebates and dates, and forecast renewal actions.

## Inputs
- executed contract
- term dates

## Output
```json
{
  "obligation_register",
  "renewal_date",
  "notice_deadline"
}
```

## Success Criteria
No auto-renewal passes its notice window unflagged.

## Failure Handling
Ambiguous dates are surfaced for confirmation rather than assumed.

## Used By
- Contract Lifecycle Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
