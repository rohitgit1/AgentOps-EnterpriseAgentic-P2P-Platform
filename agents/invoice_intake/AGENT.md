# Invoice Intake Agent

> **Build specification.** Generated from `backend/app/agents/invoice_intake.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`invoice_intake` · P2P AgentOps · class `InvoiceIntakeAgent`

**Role.** Converts incoming invoices into validated, ERP-ready transactions.

**Mission.** Convert incoming invoices into validated ERP transactions without letting a bad record through.

**Module intent.**

```
Agent 1 — Invoice Intake.

Mission: convert an incoming document into a validated ERP-ready transaction,
stopping at a human checkpoint whenever the evidence is thin.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| invoice_document | attachment | no | `.pdf`, `.txt`, `.md`, `.csv`, `.json` | Supplier invoice as received — PDF text layer, scanned image, email body or EDI 810 payload. | `VIS-2026-08841.pdf` |
| invoice_id | data | yes | — | An invoice already in the queue to re-analyse. | `invoice_id=<uuid>` |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Extracted fields | record | — | supplier, invoice_number, dates, subtotal, tax, total, currency, with per-field confidence. | `{"invoice_number": "VIS-2026-08841", "total_amount": 36588.94}` |
| Resolution result | record | — | Matched supplier and purchase order, with match scores. | — |
| Duplicate verdict | record | — | Similarity score against invoice history and the signals behind it. | `{"is_duplicate": true, "score": 0.97}` |
| Checkpoint | proposal | — | Confirm fields / open exception / hold — AP Clerk decides. | — |

Accepts attachments: **yes** · Produces downloadable files: **no**

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
| `default_stage` | `extraction_review` | Workflow stage its checkpoints are filed under |
| `default_autonomy` | `human_approval` — L2 · Human Approval | Seeded into `agent_configs`; editable in the Agent Control Room |
| `default_confidence_threshold` | `0.95` | Below this the proposal must reach a human regardless of anything else |
| `max_auto_amount_usd` | `0` | Financial ceiling for auto-execution; `0` means never |
| `escalation_role` | `ap_manager` — AP Manager | Who this agent escalates to |

The global HITL switch overrides all of it. While
`enforce_human_in_the_loop` is on — the default — no proposal from this agent
executes without an explicit human decision, whatever its autonomy level says.

---

## 3 · Actions it may propose

| Action | Label | Reversible | Minimum approver | Executor |
|---|---|---|---|---|
| `update_invoice_fields` | Correct invoice fields | yes | AP Clerk | `_update_invoice_fields` |
| `advance_stage` | Advance workflow stage | yes | AP Clerk | `_advance_stage` |
| `create_exception` | Open exception | yes | AP Clerk | `_create_exception` |
| `hold_invoice` | Place invoice on hold | yes | AP Clerk | `_hold_invoice` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `create_exception`

Raised on 3 branches, e.g. *Tax does not reconcile*; *No purchase order reference*.

```json
{
  "invoice_id": …,
  "supplier_id": …,
  "exception_type": …,
  "severity": …,
  "title": …,
  "description": …,
  "financial_impact_usd": …,
  "proposed_resolution": …,
  "sla_hours": …
}
```

- Due in: `4` hours
- Carries priced alternatives for the reviewer
- Sets extra flags the policy engine reads

#### `update_invoice_fields`

Raised on 1 branch, e.g. *Select the correct supplier*.

```json
{
  "invoice_id": …,
  "fields": …,
  "advance_to": …,
  "status": …
}
```

- Diff preview: `supplier_id`
- Due in: `6` hours
- Carries priced alternatives for the reviewer
- Sets extra flags the policy engine reads

#### `?`

Raised on 1 branch.

_Empty payload — the executor works from `task.entity_id`._

- Due in: `6` hours

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `update_invoice_fields` | `invoices` |
| `advance_stage` | `invoices` |
| `create_exception` | `exceptions`, `invoices` |
| `hold_invoice` | `invoices` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Extract header and line data from the source document | `invoice_extraction` | Structured fields are the basis for every later check. |
| 2 | Resolve the supplier against vendor master | `supplier_lookup` | An unresolved supplier cannot be paid or risk-screened. |
| 3 | Locate the backing purchase order | `po_lookup` | PO context enables the three-way match downstream. |
| 4 | Screen for duplicates across invoice history | `duplicate_detection` | Duplicate payment is the costliest AP failure mode. |
| 5 | Validate tax arithmetic and rate band | `tax_validation` | Tax errors block posting and create restatement risk. |
| 6 | Propose the next action for human review | `hitl_checkpoint` | The agent proposes; a person decides. |

### `gather()` — evidence collection

Runs five skills in sequence, each producing one `Observation`, and stashes each
result on `context` for `decide()`:

1. `invoice_extraction.extract()` over `invoice.document_text`, seeded with
   hints from the already-known header fields and told which channel the
   document arrived on (channel drives a base quality score — EDI is trusted
   more than a scanned image). Returns `fields`, a per-field `confidence`, and
   `requires_human_review`.
2. `supplier_lookup.lookup()` on the extracted supplier name against the vendor
   master. Returns a `resolved` match or a ranked `candidates` list.
3. `po_lookup.lookup()` using the extracted PO number, the resolved supplier,
   the invoice total and the ERP system. Recovers a PO even when the reference
   on the document is malformed.
4. `duplicate_detection.detect()` against invoice history. **The resolved
   supplier is applied to the invoice in memory before the call and restored
   immediately after** — screening on the raw name misses duplicates whose
   supplier was never resolved, which is exactly the population most at risk.
5. `tax_validation.validate()` on subtotal / tax / total / freight, with the
   supplier's country and tax ID.

### `decide()` — the reasoning

Branches are evaluated in this order and the **first blocking one returns
immediately** — a duplicate is not worth correcting fields on.

1. **Duplicate** (`dup["is_duplicate"]`) → `create_exception` with
   `severity=critical`, `extra_flags=["duplicate_suspected"]`, and two priced
   alternatives (confirm-and-reject / not-a-duplicate). Returns.
2. **Supplier unresolved** (no `resolved`) → `update_invoice_fields` proposing
   the best candidate, with every candidate offered as a selectable alternative
   carrying its own payload. `extra_flags=["supplier_unresolved"]`. Returns.
3. Otherwise it stages field corrections. `stage_field()` adds a field to the
   proposed payload **only if the extracted value is non-empty and differs from
   what is already stored** — a correction that changes nothing is noise in the
   reviewer's diff.
4. **Tax invalid** → adds a `tax_error` exception proposal.
5. **No PO resolved** → adds a `missing_po` exception proposal.
6. **Only if no exception was raised** → a single clean-path proposal:
   `update_invoice_fields` when there are corrections to make, otherwise
   `advance_stage`. Both move the invoice to `matching` with status `validated`.

Confidence on the clean path is the extraction's own header confidence,
unmodified. On the duplicate path it is `min(0.98, 0.55 + score × 0.45)`, so a
borderline duplicate score produces a borderline confidence rather than false
certainty.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Duplicate similarity | 0.92 | `intake.duplicate_similarity` policy key |
| Supplier auto-resolve floor | 0.85 | `AUTO_RESOLVE_THRESHOLD` in `skills/supplier_lookup.py` |
| Agent confidence threshold | 0.92 | class attribute |
| Duplicate-path confidence | `min(0.98, 0.55 + score × 0.45)` | `decide()` |
| Unresolved-supplier confidence | `max(0.35, match_score)` | `decide()` |

### Escalation

Escalates on a duplicate, on an unresolved supplier, and when header confidence
falls below the agent threshold. Escalation records an event and marks the
execution — it does **not** change what a human is asked to decide, which is
always the proposal itself.

### Handoff

`three_way_match` on the clean path; `exception_resolution` when an exception is opened.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `invoice_extraction` | Extract structured invoice data from PDF, image, email body or EDI payload. | [contract](../../skills/invoice_extraction/SKILL.md) |
| `supplier_lookup` | Resolve an extracted supplier name to a vendor master record. | [contract](../../skills/supplier_lookup/SKILL.md) |
| `po_lookup` | Find the PO an invoice bills against, directly or by supplier + amount inference. | [contract](../../skills/po_lookup/SKILL.md) |
| `duplicate_detection` | Detect exact and near-duplicate invoices before they reach payment. | [contract](../../skills/duplicate_detection/SKILL.md) |
| `tax_validation` | Validate tax arithmetic, applicable rate and supplier tax registration. | [contract](../../skills/tax_validation/SKILL.md) |

Imported skill modules: `duplicate_detection`, `invoice_extraction`, `po_lookup`, `supplier_lookup`, `tax_validation`

### Data it reads

- `invoices`
- `suppliers`

### Policy-as-code keys it consults

| Key | Fallback |
|---|---|
| `intake.duplicate_similarity` | `0.92` |

These are rows in `policy_rules`, read on every run. Changing governance is a
data change, not a code change.

### External systems

- Document OCR / EDI parser
- Vendor master
- ERP purchase orders
- Invoice history
- Tax rules

---

## 6 · Worked example

**Scenario.** A supplier emails an invoice that duplicates one already in flight.

**Given.** VIS-2026-08841 · Vertex Industrial Supply · USD 36,588.94 · PO-44210

**It does:**

1. Extracts header and lines; header confidence 93% from a clean EDI payload.
2. Resolves 'Vertex Industrial Supply Inc.' to vendor master at 100%.
3. Finds PO-44210 with 36,588.94 of open value.
4. Duplicate screen scores 97% against an invoice received 1 hour earlier — identical number, identical amount, same PO.
5. Tax arithmetic reconciles.

**Produces.** Exception proposal: 'Suspected duplicate of VIS-2026-08841', severity critical, financial impact 36,588.94.

**Decided by.** AP Clerk — confirm against the original, or clear it as a recurring charge.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Invoice Intake Agent.

Mission:
Convert incoming invoices into validated ERP transactions without letting a bad record through.

You have access to:
- Document OCR / EDI parser
- Vendor master
- ERP purchase orders
- Invoice history
- Tax rules

Goals:
1. Reach 80%+ touchless intake without lowering accuracy.
2. Never let a duplicate or unresolved supplier past validation.
3. Surface every low-confidence field to a human before it becomes a posting error.

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

1. Subclass `BaseAgent` in `backend/app/agents/invoice_intake.py` with
   `key = "invoice_intake"` and the identity, governance and `allowed_actions`
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

