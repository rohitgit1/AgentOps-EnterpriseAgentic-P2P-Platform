# Catalog Compliance Skill

> Generated from `backend/app/skills/catalog_compliance.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Detect off-catalog buying where a contracted catalog item already exists.

## Inputs
- spend transactions
- catalog

## Output
```json
{
  "off_catalog_transactions",
  "substitutable_items",
  "price_delta_usd"
}
```

## Success Criteria
Every off-catalog flag names the catalog item it should have used.

## Failure Handling
No substitute found means no flag — a false positive costs credibility.

## Used By
- Tail Spend Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
