# Variance Analysis Skill

> Generated from `backend/app/skills/variance_analysis.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Compare invoice lines against PO lines and goods receipts, line by line.

## Inputs
- invoice_lines
- po_lines
- receipts
- tolerances

## Output
```json
{
  "match_result",
  "line_results",
  "total_variance",
  "worst_variance_pct"
}
```

## Success Criteria
Every material price or quantity variance surfaced with its dollar impact.

## Failure Handling
Variances outside tolerance never auto-clear; they open an exception.

## Used By
- Three-Way Match Agent
- Exception Resolution Agent
- Contract Intelligence Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
