# RFP Orchestration Skill

> Generated from `backend/app/skills/rfp_orchestration.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Create and manage sourcing events end to end, from requirements to award.

## Inputs
- business requirements
- budget
- category strategy
- compliance rules

## Output
```json
{
  "rfp_package",
  "supplier_shortlist",
  "bid_scorecard",
  "award_recommendation"
}
```

## Success Criteria
Sourcing cycle reduced >50%; bid participation >80%.

## Failure Handling
Never issues an RFP or awards business itself — both require sign-off.

## Used By
- Sourcing Event Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
