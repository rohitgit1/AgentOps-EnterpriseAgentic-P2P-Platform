# Supplier Normalization Skill

> Generated from `backend/app/skills/supplier_normalization.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Collapse supplier name variants onto a single vendor master identity.

## Inputs
- supplier_raw strings
- vendor master

## Output
```json
{
  "supplier_id",
  "match_score",
  "duplicate_clusters"
}
```

## Success Criteria
Duplicate vendor clusters surfaced with their combined spend.

## Failure Handling
Ambiguous matches are listed as candidates, never merged automatically.

## Used By
- Spend Analytics Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
