# Payment Prioritization Skill

> Generated from `backend/app/skills/payment_prioritization.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Rank approved invoices for the payment run by urgency, discount value and risk.

## Inputs
- due_date
- supplier_tier
- discount_terms
- sla_risk
- amount

## Output
```json
{
  "priority_score",
  "score_breakdown",
  "recommended_pay_date",
  "discount_opportunity"
}
```

## Success Criteria
Capture >95% of available early-pay discounts with zero late payments on tier-1 suppliers.

## Failure Handling
Never schedules payment itself — Treasury approves the run.

## Used By
- payment_readiness

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
