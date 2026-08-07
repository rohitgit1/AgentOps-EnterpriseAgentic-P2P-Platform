# Spend Classification Skill

> Generated from `backend/app/skills/spend_classification.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Map raw spend transactions to a category taxonomy (UNSPSC / NAICS / custom).

## Inputs
- spend extract (CSV)
- supplier master
- category taxonomy

## Output
```json
{
  "category",
  "unspsc",
  "classification_confidence",
  "unclassified_residual"
}
```

## Success Criteria
≥95% of spend value classified; low-confidence rows never auto-published.

## Failure Handling
Rows below the confidence floor are returned as unclassified for a human.

## Used By
- Spend Analytics Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
