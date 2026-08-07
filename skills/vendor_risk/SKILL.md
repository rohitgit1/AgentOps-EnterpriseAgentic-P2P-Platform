# Vendor Risk Monitoring Skill

> Generated from `backend/app/skills/vendor_risk.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Monitor sanctions, insurance, tax forms and vendor-master changes for fraud and compliance risk.

## Inputs
- supplier record
- recent master-data changes
- payment history

## Output
```json
{
  "risk_score",
  "risk_level",
  "findings",
  "recommended_action"
}
```

## Success Criteria
No payment released to a sanctioned or freshly-rebanked supplier without review.

## Failure Handling
Any sanctions hit or bank change inside the freeze window blocks payment.

## Used By
- Payment Readiness Agent
- Supplier Risk Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
