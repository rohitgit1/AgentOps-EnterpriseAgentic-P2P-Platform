# ESG Assessment Skill

> Generated from `backend/app/skills/esg_scoring.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Assess sustainability, human-rights and diversity exposure for a supplier.

## Inputs
- esg disclosures
- country risk
- diversity certification

## Output
```json
{
  "esg_risk",
  "esg_findings"
}
```

## Success Criteria
Disclosure gaps are reported as gaps, not scored as zero risk.

## Failure Handling
Absent data raises uncertainty rather than silently passing.

## Used By
- Supplier Risk & Compliance Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
