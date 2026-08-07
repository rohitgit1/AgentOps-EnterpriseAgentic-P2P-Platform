# Clause Analysis Skill

> Generated from `backend/app/skills/clause_analysis.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Detect missing, risky, non-standard and vendor-favouring language in a contract.

## Inputs
- contract document (text)
- clause library
- risk policy

## Output
```json
{
  "missing_clauses",
  "risky_clauses",
  "legal_risk_score",
  "redline_notes"
}
```

## Success Criteria
No mandatory clause omission goes undetected.

## Failure Handling
Findings are advisory; Legal and Procurement decide the redline.

## Used By
- Contract Lifecycle Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
