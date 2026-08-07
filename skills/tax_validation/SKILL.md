# Tax Validation Skill

> Generated from `backend/app/skills/tax_validation.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Validate tax arithmetic, applicable rate and supplier tax registration.

## Inputs
- subtotal
- tax_amount
- total_amount
- supplier_country
- tax_id

## Output
```json
{
  "valid",
  "effective_rate",
  "expected_rate_band",
  "findings"
}
```

## Success Criteria
Every material tax error detected before posting.

## Failure Handling
Raise a tax_error exception with the recalculated figure for human confirmation.

## Used By
- Invoice Intake Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
