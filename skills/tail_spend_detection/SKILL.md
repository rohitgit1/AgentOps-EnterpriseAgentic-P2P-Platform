# Tail Spend Detection Skill

> Generated from `backend/app/skills/tail_spend_detection.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Isolate the long tail — the transactions that are most of the volume and least of the value.

## Inputs
- classified spend
- supplier master
- contract coverage

## Output
```json
{
  "tail_transactions",
  "tail_spend_usd",
  "one_time_vendors",
  "pareto_point"
}
```

## Success Criteria
Tail identified on a defensible Pareto cut, not an arbitrary threshold.

## Failure Handling
Findings are advisory until a human approves consolidation or enforcement.

## Used By
- Tail Spend Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
