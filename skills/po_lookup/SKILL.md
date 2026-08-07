# Purchase Order Lookup Skill

> Generated from `backend/app/skills/po_lookup.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Find the PO an invoice bills against, directly or by supplier + amount inference.

## Inputs
- po_number
- supplier_id
- invoice_total
- invoice_date

## Output
```json
{
  "po_id",
  "po_number",
  "open_amount",
  "lines",
  "inference_basis"
}
```

## Success Criteria
PO resolved for >= 95% of PO-backed invoices.

## Failure Handling
If no PO is found, raise a missing_po exception for human triage.

## Used By
- Invoice Intake Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
