# Contract Authoring Skill

> Generated from `backend/app/skills/contract_authoring.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
Generate MSA, SOW, NDA and amendment drafts from the standard clause library.

## Inputs
- contract request
- supplier
- value
- term
- category

## Output
```json
{
  "contract_draft",
  "clause_manifest",
  "obligation_register"
}
```

## Success Criteria
Every generated draft contains the full mandatory clause set.

## Failure Handling
A draft is never issued for signature without a human approval.

## Used By
- Contract Lifecycle Agent

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
