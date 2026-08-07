# Contract Intelligence Skill

> Generated from `backend/app/skills/contract_parsing.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Compare billed lines against the contracted rate card, term dates and allowed charges.

## Inputs
- contract
- invoice_lines
- invoice_date

## Output
```json
{
  "findings",
  "recoverable_amount",
  "expired",
  "missed_discounts"
}
```

## Success Criteria
Every unauthorised charge and off-rate line detected before payment.

## Failure Handling
Findings are proposals; Procurement decides whether to short-pay or accept.

## Used By
- Exception Resolution Agent
- Procurement Request Agent
- Contract Intelligence Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
