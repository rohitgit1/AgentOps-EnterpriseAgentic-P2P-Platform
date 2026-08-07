"""The reasoning behind each agent, for `generate_agent_specs.py`.

Everything mechanical about an agent — its identity, governance envelope, I/O
contract, proposal payloads, permitted actions — is extracted from the code and
does not belong here. What cannot be extracted is *why* it decides what it
decides: the branch conditions, the thresholds, the confidence formulas, the
conditions under which it escalates or hands off.

That is what this file holds, one entry per agent key. It is the only part of an
agent's build specification a maintainer writes by hand, and the only part that
can go stale — so when an agent's logic changes, change its entry here and
regenerate.

Each entry may contain:

    gather      markdown — what evidence it collects and from where
    decide      markdown — the branches, in the order they are evaluated
    thresholds  list of (quantity, value, source) rows
    escalation  markdown — when `escalate=True` and what that means
    handoff     markdown — which agent picks the work up next
"""
from __future__ import annotations

BUILD_NOTES: dict[str, dict] = {}


# ==========================================================================
# P2P AgentOps
# ==========================================================================
BUILD_NOTES["invoice_intake"] = {
    "gather": """
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
""",
    "decide": """
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
""",
    "thresholds": [
        ("Duplicate similarity", "0.92", "`intake.duplicate_similarity` policy key"),
        ("Supplier auto-resolve floor", "0.85",
         "`AUTO_RESOLVE_THRESHOLD` in `skills/supplier_lookup.py`"),
        ("Agent confidence threshold", "0.92", "class attribute"),
        ("Duplicate-path confidence", "`min(0.98, 0.55 + score × 0.45)`", "`decide()`"),
        ("Unresolved-supplier confidence", "`max(0.35, match_score)`", "`decide()`"),
    ],
    "escalation": """
Escalates on a duplicate, on an unresolved supplier, and when header confidence
falls below the agent threshold. Escalation records an event and marks the
execution — it does **not** change what a human is asked to decide, which is
always the proposal itself.
""",
    "handoff": "`three_way_match` on the clean path; `exception_resolution` when an "
               "exception is opened.",
}

BUILD_NOTES["three_way_match"] = {
    "gather": """
Reads tolerances from policy-as-code first, so a governance change takes effect
without a deploy. Then:

1. Uses `invoice.po_id` if set; otherwise falls back to `po_lookup.lookup()` to
   recover the PO. If neither finds one, returns early with what it has.
2. Sums received quantity **per PO line** across all goods receipts
   (`receipt.lines_json`), not per receipt — a partial receipt against one line
   must not appear to satisfy another.
3. `variance_analysis.analyze()` line by line, given the invoice lines, the PO
   lines, the received-quantity map and all three tolerances.
4. Records the tolerances actually applied as their own observation, so the
   reviewer sees the rule that was used rather than having to assume it.
""",
    "decide": """
1. **No PO** → `create_exception` of type `missing_po`, escalate, hand off.
   Returns.
2. **Clean** (`analysis["clean"]`) → `advance_stage` to `approval` with status
   `matched`, carrying `match_result` and the full `match_details` so the
   analysis is preserved on the invoice for audit.
3. **Otherwise** → map the match result to an exception type
   (`missing_receipt` → `missing_receipt`, `price_variance` → `price_mismatch`,
   `quantity_variance` → `quantity_mismatch`, `no_match` → `price_mismatch`),
   pick the worst line by absolute variance, and ask
   `exception_resolution.playbook()` for a resolution and priced alternatives.
   When the result is specifically `missing_receipt`, a second
   `request_goods_receipt` proposal is added — chasing the receipt is the action
   that actually unblocks the invoice, and it carries zero financial impact.

A variance is judged against **all three** tolerances: percentage, absolute
floor, and per-line quantity percentage. The absolute floor exists so a small
percentage on a large invoice still stops.
""",
    "thresholds": [
        ("Amount variance tolerance", "3.0 %", "`match.amount_variance_pct` policy key"),
        ("Quantity variance tolerance", "2.0 %", "`match.quantity_variance_pct` policy key"),
        ("Absolute variance floor", "50 USD", "`match.amount_variance_abs` policy key"),
        ("Confidence — exact match", "0.97", "`decide()`"),
        ("Confidence — within tolerance", "0.94", "`decide()`"),
        ("Confidence — exception path", "`min(0.96, 0.80 + 0.16 × has_worst_line)`", "`decide()`"),
        ("Manager escalation", "variance ≥ 10,000 USD", "`decide()`"),
    ],
    "escalation": "Escalates when the absolute net variance reaches 10,000 USD, and "
                  "always when no PO could be resolved.",
    "handoff": "`approval_acceleration` on a clean match; `exception_resolution` "
               "otherwise.",
}

BUILD_NOTES["approval_acceleration"] = {
    "gather": """
Reads the three SLA windows from policy, then assembles: the invoice's current
approver and their out-of-office and delegate state, the queue depth of every
qualified approver, how long the invoice has been waiting, whether a reminder
has already gone out, and an SLA forecast from `sla_prediction`.
`approval_routing.route()` returns the preferred approver.
""",
    "decide": """
Ordered branches, first match wins. The order encodes a real preference: never
chase someone who cannot act.

1. **Not yet routed** → `route_for_approval` to the routing skill's choice. The
   chosen approver is the **lowest-authority qualified approver with the
   shortest queue** — routing to the CFO because they can approve anything is a
   bottleneck, not a control.
2. **Approver out of office with a qualified delegate** → `reassign_approver`.
   A reminder to an absent approver is wasted, so rerouting is evaluated before
   either reminder or escalation. If there is no delegate whose approval limit
   covers the amount, it escalates instead.
3. **Age ≥ escalation window, or forecast risk is critical** →
   `escalate_approval`. If the invoice has already been escalated, it proposes
   nothing rather than escalating twice.
4. **Age ≥ reminder window, or forecast risk is high** →
   `send_approval_reminder`, **unless one went out in the last 12 hours** — a
   duplicate nudge trains people to ignore the channel.
5. **Otherwise** → no action, stated explicitly with the remaining headroom.
""",
    "thresholds": [
        ("Reminder window", "48 h", "`sla.approval_reminder_hours` policy key"),
        ("Escalation window", "72 h", "`sla.approval_escalation_hours` policy key"),
        ("Target cycle time", "24 h", "`sla.invoice_cycle_hours` policy key"),
        ("Reminder suppression", "12 h since last reminder", "`decide()`"),
        ("Confidence", "0.90 – 0.96 by branch", "`decide()`"),
    ],
    "escalation": "Escalates when the approver is absent with no qualified delegate, "
                  "and when no escalation target exists at all — both are situations "
                  "no automated action can resolve.",
    "handoff": "None. The invoice stays with approval until a human acts.",
}

BUILD_NOTES["exception_resolution"] = {
    "gather": """
Loads the exception, its invoice, the supplier and any governing contract, then
asks `exception_resolution.playbook()` for the recommended action and its priced
alternatives given the exception type and its financial context. Where a
contract exists, the contract unit price is pulled so a short-pay can be quoted
against a real number rather than an assumption.
""",
    "decide": """
Confidence is computed first and gates everything: **below 0.70 the agent
proposes no resolution at all** and instead asks for the case to be assigned to
a human owner. A confident-sounding wrong resolution on an exception is worse
than no resolution.

Above that floor, it dispatches on the playbook's `recommended` value:

| Recommendation | Proposal |
|---|---|
| `short_pay_to_contract` | `resolve_exception` paying the contract price, with the delta quoted |
| `accept_within_tolerance` | `resolve_exception` absorbing the variance |
| `chase_receiver` | `request_goods_receipt` |
| `hold_and_confirm` | `hold_invoice` |
| `correct_tax` | `resolve_exception` with the recalculated tax |
| anything else | no proposal; escalate with "no playbook action applies" |

`short_pay_to_contract` additionally requires a contested line *and* a known
contract price — without both, the short-pay amount would be invented.

Every proposal carries the playbook's alternatives, so the reviewer can pick a
different resolution without leaving the checkpoint.
""",
    "thresholds": [
        ("Minimum confidence to propose a resolution", "0.70", "`decide()`"),
        ("Agent confidence threshold", "0.88", "class attribute"),
        ("Escalation", "financial impact ≥ 25,000 USD", "`decide()`"),
    ],
    "escalation": "Escalates at 25,000 USD of financial impact, when confidence is "
                  "below 0.70, and when no playbook action applies.",
    "handoff": "Back to the stage the exception blocks once resolved.",
}

BUILD_NOTES["supplier_experience"] = {
    "gather": """
Classifies the inbound message's intent, then retrieves only what that intent
needs: the referenced invoice, its payment record, its open exceptions, its PO,
and the supplier's contractual terms. Nothing is fetched speculatively — the
reply must be grounded in retrieved records, and a record that was not retrieved
cannot appear in it.
""",
    "decide": """
**Banking-change requests are a hard stop.** Any message asking to change bank
details is never handled over an inbound channel, at any confidence — it is the
single highest-value fraud vector in accounts payable. The agent escalates and
proposes a reply that says the change must be verified out of band.

Otherwise it builds a reply whose every sentence is traceable to a retrieved
record, dispatching on intent:

- **`payment_status`** — in strict precedence: a released payment quotes the
  settled facts; a scheduled payment quotes the scheduled date; open blockers
  mean **no date is promised at all**, only the blockers; failing all of those,
  contractual terms are quoted as terms, never as a commitment.
- **`missing_information`** — quotes the open exceptions verbatim. They already
  say exactly what is missing.
- **`po_details`** — reads the PO reference off the matched record.
- **`dispute`** — acknowledges receipt and hands to a human. A dispute is a
  commercial conversation, not a lookup.
- **no invoice identified** — replies with a verified summary and asks for the
  invoice number.

The proposal is always a *draft* reply. The agent never sends.
""",
    "thresholds": [
        ("Agent confidence threshold", "0.90", "class attribute"),
        ("Confidence — banking change", "0.97", "`decide()`"),
        ("Confidence — no invoice identified", "`max(0.75, base)`", "`decide()`"),
    ],
    "escalation": "Always on a banking-change request or a dispute; otherwise when the "
                  "message cannot be grounded in a retrieved record.",
    "handoff": "`exception_resolution` when the message reveals a blocker not yet "
               "raised as an exception.",
}

BUILD_NOTES["payment_readiness"] = {
    "gather": """
Builds the payment picture in four passes: invoices approved but not yet posted
to the ERP; payments already scheduled and now due; invoices blocked by supplier
compliance (`vendor_risk`, including the bank-change freeze window); and, for
everything payable, a `payment_prioritization` score plus a
`discount_detection` result.
""",
    "decide": """
Emits proposals in payment-lifecycle order so the inbox reads as a sequence
rather than a pile:

1. **`post_to_erp`** for approved-but-unposted invoices. Posting is the step
   that makes an invoice payable and it is irreversible, so it is its own
   checkpoint rather than being folded into scheduling.
2. **`release_payment`** for scheduled payments that have reached their date —
   but **a payment whose supplier is on hold is skipped entirely**, never
   proposed and then rejected. A release proposal for a blocked supplier is a
   trap for a distracted reviewer.
3. **`hold_invoice`** for each compliance-blocked invoice, with the blocking
   finding quoted.
4. **`schedule_payment`** for the rest, ordered by priority score, quoting the
   score breakdown and — when a discount is live — the deadline and the exact
   amount at stake.

The priority score is `due_risk + supplier_tier + discount_value + sla_risk`;
the breakdown is shown to the reviewer rather than just the total, because the
total on its own is not reviewable.
""",
    "thresholds": [
        ("Bank-change payment freeze", "10 days", "`risk.bank_change_freeze_days` policy key"),
        ("Supplier tier weight", "platinum 25 / gold 18 / silver 10 / bronze 5",
         "`TIER_WEIGHT` in `skills/payment_prioritization.py`"),
        ("Agent confidence threshold", "0.93", "class attribute"),
        ("Confidence", "0.93 – 0.96 by branch", "`decide()`"),
    ],
    "escalation": "Escalates whenever any invoice is blocked by supplier compliance — "
                  "that is a treasury-visible condition, not a queue item.",
    "handoff": "`supplier_risk` when a block originates in the vendor master.",
}

BUILD_NOTES["supplier_risk"] = {
    "gather": """
Screens the active vendor master through `vendor_risk.assess()`: sanctions and
watchlist hits, recent bank-detail changes inside the freeze window, expiring or
missing tax forms and insurance certificates, and performance signals. Returns
one assessment per supplier with a findings list carrying severities.
""",
    "decide": """
Two distinct populations, handled differently:

**Payment-blocking findings** (`critical` or `high`). For each affected
supplier it computes live exposure — the sum of unpaid invoice totals — and:

- a **`block_supplier`** proposal when the headline finding is a sanctions hit.
  Nothing else is proportionate to a sanctions match;
- plus a **`create_exception`** on each of the first five unpaid invoices, so
  the block is visible where the money actually is rather than only on the
  supplier record. Five is a deliberate cap: the point is to make the exposure
  visible, not to flood the inbox.

**Document expiry** (`tax_form_missing`, `tax_form_expiring`,
`tax_form_expired`, `insurance_expiring`) → a **`send_supplier_message`** draft
chasing the document. These are administrative, not blocking, and are proposed
separately so a reviewer can clear them in a batch.

If nothing qualifies, it says so explicitly and proposes nothing. Silence and
"no risk found" are different messages.
""",
    "thresholds": [
        ("Bank-change freeze window", "10 days", "`risk.bank_change_freeze_days` policy key"),
        ("Exposure invoices per supplier", "5", "`decide()` — a cap, not a limit on risk"),
        ("Agent confidence threshold", "0.95", "class attribute"),
    ],
    "escalation": "Escalates whenever any payment-blocking finding exists.",
    "handoff": "`payment_readiness`, which must not schedule against a blocked supplier.",
}

BUILD_NOTES["procurement_request"] = {
    "gather": """
Loads the purchase request, the nominated supplier and any contract covering the
category, then reads the two approval bands from policy. `policy_routing`
determines the approval band from the request amount.
""",
    "decide": """
A single `approve_purchase_request` proposal, routed to a band by value:

| Amount | Band |
|---|---|
| below the auto-approve threshold | AP Manager |
| below the manager-review threshold | Controller |
| at or above | CFO |

Two conditions modify it rather than blocking it:

- **No contract covers the category** → `extra_flags=["off_contract"]`, so the
  policy engine and the reviewer both see it. Off-contract is a fact to surface,
  not a veto — sometimes it is the right answer.
- **Supplier is on hold** → stated prominently in the summary. The agent does
  not silently drop the request; a human decides whether to substitute.
""",
    "thresholds": [
        ("Auto-approve band ceiling", "5,000 USD", "`procurement.auto_approve_under` policy key"),
        ("Manager-review band ceiling", "10,000 USD", "`procurement.manager_review_under` policy key"),
        ("Agent confidence threshold", "0.91", "class attribute"),
    ],
    "escalation": "Escalates at or above the manager-review ceiling.",
    "handoff": "None — an approved request becomes a purchase order outside this agent.",
}

BUILD_NOTES["contract_intelligence"] = {
    "gather": """
Resolves the contract governing the invoice, parses its commercial terms with
`contract_parsing`, and compares the invoice against them: unit prices against
the rate card, rebate and volume-discount entitlements, payment terms, and any
billing outside the contract's scope. Produces findings with a recoverable
amount attached to each.
""",
    "decide": """
1. **No contract governs the invoice** → says so and proposes nothing. Absence
   of a contract is not a breach.
2. **No findings** → confirms conformance explicitly. A clean result is worth
   stating.
3. **Findings present** → a **`flag_contract_breach`** proposal carrying the
   first four findings and the total recoverable amount, with severity `high`
   at or above 5,000 USD recoverable and `medium` below. The first three finding
   codes go into `extra_flags` so the policy engine can act on the kind of
   breach, not just its size.
4. **Recoverable amount above zero and a supplier on file** → additionally a
   **`send_supplier_message`** draft itemising the first five findings, so the
   recovery conversation starts from a specific list rather than a general
   complaint.
""",
    "thresholds": [
        ("Severity `high`", "recoverable ≥ 5,000 USD", "`decide()`"),
        ("Escalation", "recoverable ≥ 10,000 USD", "`decide()`"),
        ("Findings quoted in the proposal", "4", "`decide()`"),
        ("Findings itemised to the supplier", "5", "`decide()`"),
        ("Agent confidence threshold", "0.90", "class attribute"),
    ],
    "escalation": "Escalates at 10,000 USD recoverable.",
    "handoff": "`exception_resolution` where a finding is best resolved as a short-pay.",
}

BUILD_NOTES["sla_command_center"] = {
    "gather": """
Forecasts every in-flight invoice with `sla_prediction`, which costs the
**remaining** stages rather than the whole workflow. The exception stage is
excluded from the remaining-effort estimate unless the invoice is actually in
it — charging every invoice for exception handling forecasts the entire
portfolio at risk, which is both wrong and useless. Also measures queue depth
and out-of-office state per approver.
""",
    "decide": """
Three independent outputs, all proposals:

1. **Workload rebalancing.** A queue with depth ≥ 6, or any queue whose owner is
   out of office, is a donor; a queue with depth ≤ 2 whose owner is present is a
   receiver. Moves are only proposed where the receiver's approval limit covers
   the invoice — a rebalance that creates an unapprovable assignment has moved
   the problem, not solved it. Emitted as `rebalance_workload`.
2. **SLA risk register.** Each at-risk or breached invoice is written to the
   register with its drivers, `breached` when hours remaining has reached zero
   and `at_risk` otherwise.
3. **Executive alert.** When forecast compliance falls below the 99 % target,
   a `raise_executive_alert` proposal with the compliance figure and the drivers
   behind it.
""",
    "thresholds": [
        ("Target cycle time", "24 h", "`sla.invoice_cycle_hours` policy key"),
        ("Compliance target", "99 %", "`decide()`"),
        ("Overloaded queue", "depth ≥ 6, or owner out of office", "`decide()`"),
        ("Receiving queue", "depth ≤ 2, owner present, not unassigned", "`decide()`"),
        ("Breached", "hours remaining ≤ 0", "`decide()`"),
        ("Escalation", "forecast compliance < 95 %", "`decide()`"),
    ],
    "escalation": "Escalates when forecast compliance falls below 95 %.",
    "handoff": "`approval_acceleration` for the individual invoices it identifies.",
}


# ==========================================================================
# Procurement AgentOps
# ==========================================================================
BUILD_NOTES["sourcing_rfp"] = {
    "gather": """
Two modes, chosen by what it is given.

**Draft mode** (no `event_id`, or an event still in draft): parses the
requirements brief attachment with `sourcing.parse_requirements()` for scope,
volume, term, budget and service levels, then runs `supplier_discovery` over the
vendor master to shortlist candidates on category fit, tier and risk.

**Evaluation mode** (an issued event, with bid responses): loads the bids —
from the `bid_responses` attachment or from `sourcing_bids` — and scores them
with `bid_evaluation`.
""",
    "decide": """
**Draft mode** produces four deliverables as drafts — the RFP package, the
supplier shortlist, the bid scorecard template and the award recommendation
skeleton — and one `issue_rfp` proposal that would release them.

Two things are deliberate here:

- **Compliance is a gate, not a weight.** A supplier failing a mandatory
  compliance rule is excluded from the shortlist, not scored down. A weighted
  score can always be outvoted by a good price; a gate cannot.
- **Issuing an RFP carries a financial impact of zero.** It invites bids and
  commits nothing. Putting the budget on it would escalate the invitation to the
  CFO while leaving the award — where money is actually committed — at the same
  level. The value-based escalation belongs on the award.

**Evaluation mode** scores every bid on commercial, technical and risk
separately and proposes `award_sourcing_event` for the winner, with the full
scorecard as evidence. The margin over the runner-up is computed and a margin
inside 4 points is called out as a close call — at that distance the ranking is
not a mandate.

If no supplier qualifies, it says so and proposes nothing. A sourcing event with
no qualified suppliers is a finding, not a failure to try harder.
""",
    "thresholds": [
        ("Evaluation weights", "commercial 0.45 / technical 0.35 / risk 0.20",
         "`DEFAULT_WEIGHTS` in `skills/sourcing.py`; publishable per event"),
        ("Close call", "margin < 4 points over the runner-up", "`decide()`"),
        ("Escalation — draft", "requirements completeness < 0.67", "`decide()`"),
        ("`issue_rfp` financial impact", "0.00 USD", "`decide()` — deliberate"),
        ("Agent confidence threshold", "0.92", "class attribute"),
    ],
    "escalation": "Escalates when the requirements brief is less than two-thirds "
                  "complete, when the award is a close call, and when the winner "
                  "carries any compliance flag.",
    "handoff": "`contract_lifecycle` once an award is approved.",
}

BUILD_NOTES["spend_analytics"] = {
    "gather": """
Reads the spend extract from an attachment or, failing that, from
`spend_transactions`. Runs `supplier_normalization` to collapse name variants
onto one entity, `spend_classification` against the category taxonomy, and
`savings_identification` across the savings levers.
""",
    "decide": """
1. **No spend data at all** → says so and escalates. It does not classify an
   empty set and report 100 % coverage.
2. Otherwise it produces four deliverables as drafts — classified spend,
   savings register, an insight brief and the **unclassified residual** — and
   two proposals:
   - **`publish_spend_classification`**, carrying the classification and the
     coverage achieved;
   - **`create_savings_opportunity`** for the identified savings, each with its
     lever and modelled rate.

Shipping the unclassified residual as its own file is the point of the residual:
a coverage percentage with no way to see what fell outside it cannot be acted
on.

Savings are modelled per lever at published rates rather than estimated per
line, so two runs over the same data produce the same number and the method is
auditable.
""",
    "thresholds": [
        ("Confidence floor", "0.75", "`CONFIDENCE_FLOOR` module constant"),
        ("Escalation", "classification coverage < 85 %", "`decide()`"),
        ("Savings lever rates", "consolidation 8 % · contract coverage 6 % · …",
         "`LEVER_RATES` in `skills/spend_analysis.py`"),
        ("Agent confidence threshold", "0.90", "class attribute"),
    ],
    "escalation": "Escalates when classification coverage falls below 85 % — below "
                  "that the savings numbers rest on too little classified spend.",
    "handoff": "`tail_spend` for the long tail the classification exposes.",
}

BUILD_NOTES["supplier_risk_compliance"] = {
    "gather": """
Scores suppliers across four domains from the supplied evidence — financial
indicators, delivery performance, compliance state and ESG — using
`supplier_risk_assessment`. Attachments feed the financial and operational
domains directly; compliance and ESG come from the vendor master.
""",
    "decide": """
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
""",
    "thresholds": [
        ("Composite weighting",
         "financial 0.30 · operational 0.25 · compliance 0.30 · ESG 0.15",
         "`skills/strategic_risk.py`"),
        ("Dispositions", "`approve` · `monitor` · `watchlist` · `block`",
         "`DISPOSITIONS` in `skills/strategic_risk.py`"),
        ("Reduced confidence on thin evidence", "0.72 when ≥ 2 findings report missing data",
         "`skills/strategic_risk.py`"),
        ("Agent confidence threshold", "0.91", "class attribute"),
    ],
    "escalation": "Escalates when any supplier's recommended disposition is `block`.",
    "handoff": "`supplier_risk` for the operational AP consequences of a block.",
}

BUILD_NOTES["contract_lifecycle"] = {
    "gather": """
Parses the contract document — uploaded, or authored from request parameters —
and runs `clause_analysis` for missing mandatory clauses and risky present ones,
plus `obligation_tracking` for the obligation register, renewal dates and notice
periods.
""",
    "decide": """
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
""",
    "thresholds": [
        ("Escalation", "legal risk score ≥ 35", "`decide()`"),
        ("Signature withheld", "any mandatory clause missing, or any risky clause present",
         "`decide()`"),
        ("Risk scoring", "additive per risky clause, plus weight per missing mandatory clause",
         "`skills/contract_lifecycle.py`"),
        ("Agent confidence threshold", "0.90", "class attribute"),
    ],
    "escalation": "Escalates at a legal risk score of 35.",
    "handoff": "`contract_intelligence`, which enforces the terms once the contract "
               "is live.",
}

BUILD_NOTES["tail_spend"] = {
    "gather": """
Splits spend into head and tail on a Pareto cut by supplier, clusters the tail by
category, and checks each transaction against the catalogue to find off-catalogue
buying where a catalogue item existed.
""",
    "decide": """
1. **No spend data** → says so and escalates.
2. **`consolidate_suppliers`** per material cluster. A cluster qualifies only
   if it is worth at least the materiality floor **and** contains at least two
   suppliers — consolidating a single supplier onto itself is not an
   intervention. Modelled savings apply the consolidation rate to the cluster,
   and only where a preferred supplier actually exists; without one the finding
   is recorded as `no_preferred_supplier` with **zero** savings rather than a
   savings claim nobody can realise.
3. **`enforce_catalog`** for off-catalogue purchases where a catalogue
   substitute exists. Where no substitute exists, enforcement is not proposed —
   the buyer had no compliant option.

The materiality floor exists because an unfiltered clustering surfaces dozens of
sub-thousand-dollar clusters that cost more to action than they save.
""",
    "thresholds": [
        ("Pareto cut", "80 % of cumulative spend defines the head",
         "`PARETO_CUT` in `skills/tail_spend.py`"),
        ("Cluster materiality floor", "4,000 USD",
         "`CLUSTER_MATERIALITY` in `skills/tail_spend.py`"),
        ("Minimum suppliers per cluster", "2", "`skills/tail_spend.py`"),
        ("Modelled consolidation saving", "11 % of cluster spend",
         "`CONSOLIDATION_RATE` in `skills/tail_spend.py`"),
        ("Escalation", "tail share ≥ 25 % of spend", "`decide()`"),
        ("Agent confidence threshold", "0.89", "class attribute"),
    ],
    "escalation": "Escalates when the tail exceeds a quarter of total spend — that is "
                  "a category-strategy problem, not a purchasing one.",
    "handoff": "`sourcing_rfp` for clusters large enough to competitively source.",
}

BUILD_NOTES["procurement_command_center"] = {
    "gather": """
Rolls up the whole procurement portfolio: spend under management, contract
compliance, the supplier risk composite, tail spend reduction, sourcing cycle
time reduction and realised savings. Needs no attachment; an optional
`board_pack_context` document is folded into the narrative when supplied.
""",
    "decide": """
Measures all six KPIs against their targets, then produces an executive brief, a
KPI pack and risk heatmap data as drafts, and one
**`publish_executive_brief`** proposal.

Publishing is CFO-level and irreversible — an executive brief reaches an
audience that will act on it, and it cannot be unsent. The brief states which
targets are missed as prominently as those met; a command centre that only
reports green is not a control.

| KPI | Target |
|---|---|
| Spend under management | 95 % |
| Contract compliance | 98 % |
| Supplier risk score | below 20 |
| Tail spend reduction | 40 % |
| Sourcing cycle time reduction | 60 % |
| Procurement savings | above 5 % |
""",
    "thresholds": [
        ("Targets", "see the table above", "`TARGETS` module constant"),
        ("Escalation", "three or more KPIs off target", "`decide()`"),
        ("Agent confidence threshold", "0.90", "class attribute"),
    ],
    "escalation": "Escalates when three or more KPIs are off target.",
    "handoff": "None — this agent is the top of the reporting chain.",
}
