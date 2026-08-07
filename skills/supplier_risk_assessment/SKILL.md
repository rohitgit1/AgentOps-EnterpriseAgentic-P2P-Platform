# Strategic Supplier Risk Assessment Skill

> Generated from `backend/app/skills/supplier_risk_assessment.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Score a supplier across financial, operational, compliance and ESG risk.

## Inputs
- supplier master
- financial indicators
- certificates
- delivery history

## Output
```json
{
  "domain_scores",
  "overall_risk",
  "risk_band",
  "findings",
  "recommended_disposition"
}
```

## Success Criteria
Every score traces to named findings; no unexplained numbers.

## Failure Handling
Disposition is a recommendation — approve/monitor/watchlist/block is a human call.

## Used By
- Supplier Risk & Compliance Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
