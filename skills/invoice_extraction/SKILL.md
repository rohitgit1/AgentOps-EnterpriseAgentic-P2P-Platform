# Invoice Extraction Skill

> Generated from `backend/app/skills/invoice_extraction.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Extract structured invoice data from PDF, image, email body or EDI payload.

## Inputs
- PDF
- JPEG
- TIFF
- email body
- EDI 810

## Output
```json
{
  "supplier_name",
  "invoice_number",
  "invoice_date",
  "due_date",
  "po_number",
  "subtotal",
  "tax_amount",
  "total_amount",
  "currency",
  "lines"
}
```

## Success Criteria
Field-level accuracy > 98%; header confidence > 0.90.

## Failure Handling
If confidence < 0.90, route to human review rather than proposing an advance.

## Used By
- Invoice Intake Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
