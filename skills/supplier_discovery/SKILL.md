# Supplier Discovery Skill

> Generated from `backend/app/skills/supplier_discovery.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Shortlist qualified suppliers for a category from vendor master and market signals.

## Inputs
- category
- budget
- compliance rules
- incumbent suppliers

## Output
```json
{
  "shortlist",
  "qualification_flags",
  "coverage_rationale"
}
```

## Success Criteria
Every shortlisted supplier passes compliance pre-screen.

## Failure Handling
Blocked or sanctioned suppliers are excluded with the reason stated.

## Used By
- Sourcing Event Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
