# SLA Prediction Skill

> Generated from `backend/app/skills/sla_prediction.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Forecast which invoices will breach cycle-time SLA and why.

## Inputs
- stage
- age_hours
- sla_target
- open_exceptions
- approver_availability

## Output
```json
{
  "risk_score",
  "risk_level",
  "predicted_breach_at",
  "drivers",
  "recommended_action"
}
```

## Success Criteria
Breaches predicted at least 8 hours ahead with < 15% false-positive rate.

## Failure Handling
Every high-risk forecast surfaces to a human with a recommended intervention.

## Used By
- SLA Command Center Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
