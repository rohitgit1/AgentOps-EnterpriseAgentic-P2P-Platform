# Supplier Risk & Compliance Agent

> **Build specification.** Generated from `backend/app/agents/supplier_risk_compliance.py` by
> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the
> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.

`supplier_risk_compliance` · Procurement AgentOps · class `SupplierRiskComplianceAgent`

**Role.** Scores suppliers across financial, operational, compliance and ESG risk.

**Mission.** Keep a current, defensible risk position on every supplier the company depends on.

**Module intent.**

```
Procurement Agent 3 — Supplier Risk & Compliance.

Scores suppliers across financial, operational, compliance and ESG risk and
recommends a disposition: approve, monitor, watchlist or block. Distinct from
the operational Supplier Risk Agent, which screens at payment time — this is the
periodic scorecard that decides whether to keep buying at all.
```

---

## 1 · What it consumes and what it returns

### Inputs

| Name | Kind | Required | Formats | Description | Example |
|---|---|---|---|---|---|
| financial_indicators | attachment | no | `.csv`, `.json` | Credit ratings and distress signals per supplier. Columns: supplier, credit_rating, days_beyond_terms, bankruptcy_flag. | `credit-report-q3.csv → supplier,credit_rating,days_beyond_terms` |
| delivery_performance | attachment | no | `.csv`, `.json` | Operational performance. Columns: supplier, otif_pct, capacity_utilisation_pct, single_source. | `otif-fy26.csv → supplier,otif_pct,single_source` |
| supplier_id | data | no | — | Assess one supplier. Omit to sweep the whole vendor master. | — |

### Outputs

| Name | Kind | Formats | Description | Example |
|---|---|---|---|---|
| Risk scorecard | artifact | `.csv` | Per-supplier scores across all four domains plus the recommended disposition. | `supplier-risk-scorecard.csv` |
| Risk report | artifact | `.md` | Narrative report with the findings behind each elevated score. | `supplier-risk-report.md` |
| RiskAssessment records | record | — | Persisted scorecards the portfolio view reads. | — |
| Checkpoint | proposal | — | Set supplier disposition (approve / monitor / watchlist / block). | — |

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
| `default_stage` | `validation` | Workflow stage its checkpoints are filed under |
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
| `set_supplier_disposition` | Set supplier disposition | yes | Procurement Lead | `_set_supplier_disposition` |

Authority escalates with value on top of the minimum above: at or above
$50,000 a Controller is required, at or above $250,000 the CFO, and above
$100,000 two distinct approvers are required (`hitl.dual_approval_above`, editable in Governance).

### Proposal payloads

The payload each proposal carries. The executor reads exactly these keys, so
a rebuild must produce them under the same names.

#### `set_supplier_disposition`

Raised on 1 branch.

```json
{
  "assessment_id": …,
  "disposition": …,
  "reason": …
}
```

- Diff preview: `disposition`, `risk_score`
- Due in: `12` hours
- Carries priced alternatives for the reviewer
- Releases linked draft deliverables on approval
- Sets extra flags the policy engine reads

### What approval actually changes

| Action | Tables the executor touches |
|---|---|
| `set_supplier_disposition` | `risk_assessments`, `suppliers` |

Every executor also appends to `audit_logs` (hash-chained) and
`workflow_events`. Nothing above happens before approval.

---

## 4 · Lifecycle

`plan() → gather() → decide()` inside the base class's
`plan / execute / observe / reason / escalate / report` run loop.

### Declared plan

| # | Action | Tool | Why |
|---|---|---|---|
| 1 | Select suppliers in scope | `vendor_scan` | One supplier, or the whole master. |
| 2 | Ingest financial and delivery feeds | `feed_ingest` | A missing feed is reported as a gap, never scored as clean. |
| 3 | Score four risk domains | `supplier_risk_assessment` | Compliance is weighted hardest — it stops trade outright. |
| 4 | Assess ESG exposure | `esg_scoring` | Absent disclosure raises uncertainty rather than passing silently. |
| 5 | Recommend a disposition for approval | `hitl_checkpoint` | Blocking a supplier stops their revenue — a person owns that. |

### `gather()` — evidence collection

Scores suppliers across four domains from the supplied evidence — financial
indicators, delivery performance, compliance state and ESG — using
`supplier_risk_assessment`. Attachments feed the financial and operational
domains directly; compliance and ESG come from the vendor master.

### `decide()` — the reasoning

Produces a risk scorecard and a narrative report as drafts, writes a
`RiskAssessment` per supplier with `applied_disposition` left **null**, and
proposes **`set_supplier_disposition`** for each elevated supplier.

The disposition ladder is `approve → monitor → watchlist → block`. The
assessment records what the agent recommends; the vendor master is not touched
until a human approves, which is why `applied_disposition` and `decided_by` are
separate columns from the recommendation.

The composite score is a weighted blend rather than a maximum, so a single bad
domain does not by itself condemn a supplier — but each domain's own score is
carried through to the scorecard, so a reviewer can see the domain that drove
the result rather than only the blend.

### Thresholds and formulas

| Quantity | Value | Where it comes from |
|---|---|---|
| Composite weighting | financial 0.30 · operational 0.25 · compliance 0.30 · ESG 0.15 | `skills/strategic_risk.py` |
| Dispositions | `approve` · `monitor` · `watchlist` · `block` | `DISPOSITIONS` in `skills/strategic_risk.py` |
| Reduced confidence on thin evidence | 0.72 when ≥ 2 findings report missing data | `skills/strategic_risk.py` |
| Agent confidence threshold | 0.91 | class attribute |

### Escalation

Escalates when any supplier's recommended disposition is `block`.

### Handoff

`supplier_risk` for the operational AP consequences of a block.

---

## 5 · Dependencies

### Skills

| Skill | Purpose | Contract |
|---|---|---|
| `supplier_risk_assessment` | Score a supplier across financial, operational, compliance and ESG risk. | [contract](../../skills/supplier_risk_assessment/SKILL.md) |
| `esg_scoring` | Assess sustainability, human-rights and diversity exposure for a supplier. | [contract](../../skills/esg_scoring/SKILL.md) |

Imported skill modules: `strategic_risk`

### Data it reads

- `invoices`
- `risk_assessments`
- `suppliers`

### External systems

- Vendor master
- Financial indicators
- Certificate registry
- Delivery history
- Sanctions screening
- ESG disclosures

---

## 6 · Worked example

**Scenario.** Quarterly supplier risk review with external feeds.

**Given.** 📎 credit-report.csv + 📎 otif-performance.csv

**It does:**

1. Scores four domains: financial, operational, compliance, ESG.
2. A CCC credit rating with a bankruptcy flag drives financial risk to 90.
3. 73% OTIF and single-source status drive operational risk.
4. Compliance is weighted hardest — it is the domain that stops trade outright.

**Produces.** ⬇ supplier-risk-scorecard.csv · supplier-risk-report.md, with every score traced to a named finding.

**Decided by.** Procurement sets the disposition: approve, monitor, watchlist or block.

---

## 7 · Operating brief

Generated by `BaseAgent.prompt_template()` from the identity above. Used
verbatim when a live LLM provider is configured; the deterministic reasoner
narrates from the same evidence when one is not.

```text
You are the Supplier Risk & Compliance Agent.

Mission:
Keep a current, defensible risk position on every supplier the company depends on.

You have access to:
- Vendor master
- Financial indicators
- Certificate registry
- Delivery history
- Sanctions screening
- ESG disclosures

Goals:
1. Hold the portfolio-average supplier risk score below 20.
2. Detect financial distress and certificate lapse before they interrupt supply.
3. Make every score traceable to named findings.

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

1. Subclass `BaseAgent` in `backend/app/agents/supplier_risk_compliance.py` with
   `key = "supplier_risk_compliance"` and the identity, governance and `allowed_actions`
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

