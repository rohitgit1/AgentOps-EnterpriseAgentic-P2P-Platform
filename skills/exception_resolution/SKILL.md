# Exception Resolution Skill

> Generated from `backend/app/skills/exception_resolution.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Diagnose an AP exception and propose the resolution a human should confirm.

## Inputs
- exception_type
- variance detail
- contract terms
- supplier history

## Output
```json
{
  "recommended_action",
  "confidence",
  "alternatives",
  "supplier_message_draft"
}
```

## Success Criteria
60% of exceptions resolved on the agent's first proposal.

## Failure Handling
Low-confidence diagnoses escalate with the evidence attached, never a guess.

## Used By
- Exception Resolution Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
