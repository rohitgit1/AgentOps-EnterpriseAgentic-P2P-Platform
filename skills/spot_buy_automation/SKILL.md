# Spot Buy Automation Skill

> Generated from `backend/app/skills/spot_buy_automation.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Turn a repeated one-off purchase into a quick three-quote RFQ.

## Inputs
- tail transaction cluster
- supplier shortlist

## Output
```json
{
  "rfq_document",
  "suggested_suppliers"
}
```

## Success Criteria
Spot buys above the threshold get competitive tension.

## Failure Handling
The RFQ is a draft; issuing it to suppliers needs approval.

## Used By
- Tail Spend Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
