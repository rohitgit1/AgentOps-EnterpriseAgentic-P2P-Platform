# Vendor Consolidation Skill

> Generated from `backend/app/skills/vendor_consolidation.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Group fragmented category spend onto a preferred supplier and price the move.

## Inputs
- tail transactions
- preferred suppliers
- category

## Output
```json
{
  "consolidation_clusters",
  "recommended_supplier",
  "savings_usd"
}
```

## Success Criteria
Recommendations name the target supplier and the spend being moved.

## Failure Handling
Categories with no qualified preferred supplier are reported, not forced.

## Used By
- Tail Spend Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
