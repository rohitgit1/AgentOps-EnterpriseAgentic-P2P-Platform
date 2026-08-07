# Supplier Lookup Skill

> Generated from `backend/app/skills/supplier_lookup.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Resolve an extracted supplier name to a vendor master record.

## Inputs
- supplier_name
- tax_id
- bank_last4
- remit_to_address

## Output
```json
{
  "supplier_id",
  "match_score",
  "candidates",
  "compliance_flags"
}
```

## Success Criteria
Correct vendor resolved at score >= 0.85 with no false positives.

## Failure Handling
Below 0.85, return ranked candidates and require human selection.

## Used By
- Invoice Intake Agent
- Supplier Experience Agent
- Procurement Request Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
