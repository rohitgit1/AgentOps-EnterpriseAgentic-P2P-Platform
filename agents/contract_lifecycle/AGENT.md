# Contract Lifecycle Agent

> **Build specification.** Generated from `backend/app/agents/contract_lifecycle_agent.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`contract_lifecycle` · Procurement AgentOps · class `ContractLifecycleAgent`

**Role.** Authors, reviews and tracks contracts across their whole lifecycle.

**Mission.** Get defensible paper in place quickly, and never miss a renewal or a risky clause.

**Module intent.**

```
Procurement Agent 4 — Contract Lifecycle.

Authors drafts from the standard clause library, and reviews an uploaded
third-party paper for missing clauses, risky language and obligations. Issuing
for signature is irreversible and needs Controller authority.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| contract_document | attachment | no | `.md`, `.txt`, `.pdf` | A third-party or existing contract to review for missing and risky clauses. | `acme-msa-redline.md` |
| contract_request | data | no | — | Parameters for a new draft: supplier, type, value, term, category. | `{"supplier_id": "...", "contract_type": "MSA", "value_usd": 480000, "term_months": 24}` |
| draft_id | data | no | — | Existing draft to progress toward signature. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Contract draft | artifact | `.md` | Full document generated from the standard clause library. | `MSA-CDR-6001.md` |
| Clause review | artifact | `.md` | Missing clauses, risky language with excerpts, legal risk score. | `clause-review-CDR-6001.md` |
| Obligation register | artifact | `.csv` | Deliverables, SLAs, rebates, renewal and notice dates. | `obligations-CDR-6001.csv` |
| Checkpoints | proposal | — | Accept draft / issue for signature — the latter needs Controller. | — |

Accepts attachments: **yes** · Produces downloadable files: **yes**

Attachments arrive already parsed. `run()` resolves `context["attachment_ids"]`
through `artifacts.load_for_agent()` and puts the result in
`context["attachments"]` — CSV/TSV as typed rows plus a field list, JSON as
records, Markdown/text as full text, PDF as its embedded text layer. An
unreadable file degrades to raw text with a stated reason rather than raising,
so the agent can report *"I could not read this"* instead of crashing.

---

## 2 · Governance envelope

| Setting | Value | Meaning |
|---|---|---|
| `default_stage` | `approval` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.9` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `controller` — Controller | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `draft_contract` | Save contract draft | yes | Procurement Lead | `_draft_contract` |
| `issue_contract_for_signature` | Issue contract for signature | **no — irreversible** | Controller | `_issue_contract_for_signature` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `draft_contract`

Raised on 1 branch.

```json
{
  "draft_id": …
}
```

- Diff preview: `status`, `legal_risk`
- Due in: `24` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval

#### `issue_contract_for_signature`

Raised on 1 branch.

```json
{
  "draft_id": …
}
```

- Diff preview: `status`
- Due in: `48` hours
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `draft_contract` | `contract_drafts` |
| `issue_contract_for_signature` | `contract_drafts` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Determine the mode: author or review | `triage` | An attached document is reviewed; parameters produce a draft. |
| 2 | Generate or read the contract body | `contract_authoring` | The clause library is the standard the paper is measured against. |
| 3 | Analyse clauses | `clause_analysis` | Missing mandatory clauses and vendor-favouring language both carry weight. |
| 4 | Extract obligations and the renewal clock | `obligation_tracking` | An auto-renewal inside its notice window is the expensive failure. |
| 5 | Submit for approval | `hitl_checkpoint` | Issuing for signature commits the company — Controller authority. |

### `gather()` — evidence collection

Parses the contract document — uploaded, or authored from request parameters —
and runs `clause_analysis` for missing mandatory clauses and risky present ones,
plus `obligation_tracking` for the obligation register, renewal dates and notice
periods.

### `decide()` — the reasoning

Produces a contract draft, a clause review and an obligation register as drafts,
then:

- **`draft_contract`** — always, to record the paper that was considered.
- **`issue_contract_for_signature`** — **only when the paper is fit to sign.**
  Signature is withheld while mandatory clauses are missing or risky clauses are
  present. This is the agent's most important behaviour: it will not offer a
  path that ends in a signed bad contract, and no reviewer can approve a
  checkpoint that was never proposed.

The legal risk score is additive: each risky clause contributes its own weight,
and each missing mandatory clause contributes too — an omission is a risk, not a
neutral absence. A silent auto-renewal is flagged with its notice period,
because the risk is the date passing unnoticed rather than the clause existing.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Escalation | legal risk score ≥ 35 | `decide()` |
| Signature withheld | any mandatory clause missing, or any risky clause present | `decide()` |
| Risk scoring | additive per risky clause, plus weight per missing mandatory clause | `skills/contract_lifecycle.py` |
| Agent confidence threshold | 0.90 | class attribute |

### Escalation

Escalates at a legal risk score of 35.

### Handoff

`contract_intelligence`, which enforces the terms once the contract is live.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `contract_authoring` | Generate MSA, SOW, NDA and amendment drafts from the standard clause library. | [contract](../../skills/contract_authoring/SKILL.md) |
| `clause_analysis` | Detect missing, risky, non-standard and vendor-favouring language in a contract. | [contract](../../skills/clause_analysis/SKILL.md) |
| `obligation_tracking` | Extract deliverables, SLAs, rebates and dates, and forecast renewal actions. | [contract](../../skills/obligation_tracking/SKILL.md) |

Imported skill modules: `contract_lifecycle`

### Data it reads

- `contract_drafts`
- `contracts`
- `suppliers`

### External systems

- Clause library
- Contract register
- Supplier master
- Renewal calendar

---

## 6 · Worked example

**Scenario.** Reviewing a supplier's own paper before signing it.

**Given.** 📎 trident-msa-draft.md — a third-party MSA

**It does:**

1. Tests the document against the 12-clause mandatory set — 9 are missing.
2. Finds unlimited liability, unilateral price changes, and a buyer-indemnifies clause.
3. Detects a silent auto-renewal with no notice window.
4. Scores legal risk at 100/100.

**Produces.** ⬇ clause-review.md with excerpts and redlines · obligations.csv. Signature is deliberately not offered on paper this bad.

**Decided by.** Procurement accepts the draft with redlines; Controller issues for signature.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Contract Lifecycle Agent.

Mission:
Get defensible paper in place quickly, and never miss a renewal or a risky clause.

You have access to:
- Clause library
- Contract register
- Supplier master
- Renewal calendar

Goals:
1. Every draft carries the full mandatory clause set.
2. No auto-renewal passes its notice window unflagged.
3. Surface vendor-favouring language before signature, not at dispute.

Decision Rules:
- Never mutate a system of record directly; propose an action for human review.
- Prefer the least invasive action that resolves the issue.
- Escalate when confidence falls below the governance floor.
- Cite every fact you rely on.

Output:
Action
Reasoning
Confidence
Audit Record
```

---

## 8 · Rebuild checklist

1. Subclass `BaseAgent` in `backend/app/agents/contract_lifecycle_agent.py` with
   `key = "contract_lifecycle"` and the identity, governance and `allowed_actions`
   from sections 2 and 3.
2. Declare `inputs` and `outputs` as `IOSpec` objects matching section 1 — these
   drive the Agent I/O Catalogue and the Academy, and are the contract an
   evaluator reads before running anything.
3. Implement `plan()` returning the `PlanStep` list in section 4, verbatim. It is
   a static declaration and is read without a live context.
4. Implement `gather()` per section 4, returning one `Observation` per tool.
   Persist anything `decide()` needs on `context`, never on `self` — agents are
   singletons and a run must not leak into the next.
5. Implement `decide()` per section 4, returning an `AgentDecision` whose
   `proposals` carry exactly the payload keys in section 3.
6. Confirm every action has an executor registered with `@action(...)` in
   `backend/app/services/hitl.py`. An agent that proposes an unexecutable
   action fails `test_every_procurement_action_has_an_executor`.
7. Register the class in `backend/app/agents/registry.py`.

**Invariants a rebuild must not break:**

- `decide()` returns proposals. It must never write to a business table, call an
  executor, or mutate an ORM object it did not create as a draft artifact.
- Confidence is a real number the agent stands behind, not a constant. The
  policy engine gates on it.
- Every claim in `evidence` cites the observation it came from, so a reviewer
  months later can reconstruct the decision.
- Financial impact is the amount actually at risk. It drives role escalation and
  the dual-approval threshold, so an inflated figure blocks work and a deflated
  one under-reviews it.

