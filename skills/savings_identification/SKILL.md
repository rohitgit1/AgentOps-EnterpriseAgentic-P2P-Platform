# Savings Identification Skill

> Generated from `backend/app/skills/savings_identification.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Quantify consolidation, contract-coverage, volume-discount and rationalization levers.

## Inputs
- classified spend
- contracts
- supplier master

## Output
```json
{
  "opportunities",
  "estimated_savings_usd",
  "confidence",
  "rationale"
}
```

## Success Criteria
Every opportunity carries an addressable-spend basis and a stated rate.

## Failure Handling
Opportunities are proposals — none enters the savings pipeline unapproved.

## Used By
- Spend Analytics Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
