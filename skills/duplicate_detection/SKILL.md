# Duplicate Detection Skill

> Generated from `backend/app/skills/duplicate_detection.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Detect exact and near-duplicate invoices before they reach payment.

## Inputs
- invoice_number
- supplier_id
- total_amount
- invoice_date
- po_number

## Output
```json
{
  "is_duplicate",
  "score",
  "matched_invoice",
  "signals"
}
```

## Success Criteria
Zero duplicate payments; false-positive rate below 2%.

## Failure Handling
Any score above the policy threshold blocks the invoice for human confirmation.

## Used By
- Invoice Intake Agent
- Exception Resolution Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
