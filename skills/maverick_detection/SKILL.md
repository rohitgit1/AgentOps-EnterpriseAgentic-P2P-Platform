# Maverick Spend Detection Skill

> Generated from `backend/app/skills/maverick_detection.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Detect off-contract and off-catalog buying that bypasses negotiated channels.

## Inputs
- classified spend
- contract coverage
- preferred supplier list

## Output
```json
{
  "maverick_transactions",
  "maverick_spend_usd",
  "contract_compliance_pct"
}
```

## Success Criteria
Contract compliance measured on value, not transaction count.

## Failure Handling
Flags are advisory until a human approves an enforcement action.

## Used By
- Spend Analytics Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
