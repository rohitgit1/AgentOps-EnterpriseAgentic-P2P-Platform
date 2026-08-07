# Bid Evaluation Skill

> Generated from `backend/app/skills/bid_evaluation.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Score bids on commercial, technical and risk dimensions against declared weights.

## Inputs
- bids
- evaluation weights
- budget
- supplier risk

## Output
```json
{
  "scored_bids",
  "ranking",
  "award_recommendation",
  "savings_estimate"
}
```

## Success Criteria
Award recommendation is reproducible from the published weights.

## Failure Handling
A tie or a sub-threshold winner escalates rather than picking arbitrarily.

## Used By
- Sourcing Event Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
