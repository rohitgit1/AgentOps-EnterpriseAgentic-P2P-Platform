# Client Demo Script — 15 minutes

Everything below runs against the seeded dataset with no setup. Reset between
meetings from **Governance → Rebuild** as the Platform Admin persona.

> **The line to open with:** "Ten agents run this AP shop. None of them can
> change anything. Watch what that looks like."

---

## 0 · Before they arrive (1 min)

```bash
./run.sh        # http://localhost:8000
```

Sign in as **Priya Raman (AP Clerk)**. Press **▶ Run agent sweep** in the top
bar once so the inbox is populated. Leave it on the **Command Center**.

---

## 1 · The state of the shop (2 min)

**Command Center.**

- Point at **Awaiting human decision — 23**, and the value held behind those
  checkpoints. *"The agents have already done the work. None of it has touched
  the ERP."*
- **Operational KPIs** — each meter carries the target marker plus the industry
  average and best-in-class band. Touchless is at ~48% against an 80% target;
  cycle time is already inside 24h.
- **Workflow pipeline** shows where the population sits; amber is off-track.
- **HITL scoreboard** is the number a CFO cares about: acceptance rate, how
  often humans *modify* before approving, median review time. *"This is how you
  measure whether the agents deserve more autonomy."*

---

## 2 · The heart of it — one checkpoint (4 min)

**Approval Inbox.** Tick **Only what I can decide**.

Open **"Suspected duplicate of VIS-2026-08841"**.

Walk the drawer top to bottom:

1. **Header facts** — proposed action, subject, financial impact, confidence.
2. **Why a human is deciding this** — the amber panel. Read the gates aloud:
   global HITL enforcement, autonomy level L2, the agent's auto-execution
   allowance, risk level. *"That's the auditor's question answered in the
   product, not in a policy document."*
3. **Proposal tab** — the summary quantifies the exposure: identical invoice
   number, identical amount, same PO, would double-pay $36,588.94.
4. **Agent Reasoning tab** — the plan it made, each tool it called and what came
   back, the evidence it cited, and the narrative rationale. *"Nothing here is a
   black box. The duplicate score is 100% and you can see the four signals that
   produced it."*
5. **Policy & Audit tab** — the gates that opened, the gates that held, and the
   exact JSON payload that would be applied.

Approve it with a note. Point out the toast: *written to the audit trail.*

---

## 3 · Authority is real, not cosmetic (2 min)

Still as the AP Clerk, open **"Executive alert · SLA compliance forecast"**.

The footer turns red: *"You are signed in as AP Clerk. This decision requires
CFO authority or above."* The buttons are disabled.

Switch persona (top right) to **Elena Duarte (CFO)** and reopen it — now
decidable. *"Same screen, different authority. It is enforced server-side; the
UI is just being honest about it."*

Also worth showing: **Payments** → a `release_payment` proposal is marked
**irreversible** and requires the Controller. Irreversible actions never
auto-execute regardless of how much autonomy you grant an agent.

---

## 4 · A full invoice, end to end (3 min)

**Invoices** → open **KPM-CA-7781** (or any invoice at Intake).

- **Timeline** — every event from receipt onward.
- **Agent Runs** — each run with its tool observations and confidence.
- **Audit** — the per-invoice audit slice.
- **Document** — the source document the extraction actually parsed.

Close the drawer and press **Run agents** on the row. Watch the **Live activity**
rail on the right fill in real time as the agent plans, calls tools, reasons and
stops at a checkpoint.

To show the full chain, approve the resulting checkpoints in sequence as the
right personas:

| Stage | Persona |
|---|---|
| Release to three-way matching | AP Clerk |
| Clear match → route for approval | AP Clerk |
| Business approval (My Approvals) | AP Manager |
| Post to ERP | AP Manager |
| Schedule payment | Treasury |
| Release payment | Controller |

Six people touched it; the agents did the analysis for all six.

---

## 5 · The governance dial (2 min)

**Agent Control Room.**

- Every agent sits at **L2 · Human Approval** by default.
- Open **Invoice Intake Agent → Configure**. Show the autonomy ladder L0→L4,
  the confidence threshold, and the auto-execution ceiling.
- Note L4 is greyed out while global enforcement is on, and that raising an
  agent above L2 requires Controller authority.
- **Pause all agents** — the fleet kill switch (Platform Admin persona).

**Governance** — policy-as-code. Change `match.amount_variance_pct` from 3 to 1
and re-run the match agent: invoices that cleared now raise exceptions. *"The
tolerance lives in policy, not in the model."*

---

## 6 · The assurance close (1 min)

**Audit Trail.**

- The green banner: *"Audit chain verified — N entries recomputed."* Each record
  hashes the previous one, so a retroactive edit is detectable.
- Filter to **Agents only** vs **Humans only** — the agent rows are all
  `hitl.checkpoint_created`; the state changes are all human.
- **Export CSV** for the audit pack.

Close on the SLA Command Center: forecast compliance, the risk register with
per-invoice breach drivers, and the interventions the agent recommends — each
one, again, a proposal.

---

## Scenario cheat-sheet

| Show this | Open |
|---|---|
| Duplicate payment prevented | `VIS-2026-08841` (the EMAIL copy) |
| Price variance vs contract | `BWC-449021` |
| Missing goods receipt | `CSP-77120` |
| Low-confidence OCR + ambiguous supplier | `NFS-3391-B` |
| Contract breach + unauthorised charge | `MCP-INV-5540` |
| Tax that doesn't reconcile | `ASG-DE-99120` |
| No PO reference | `PSS-2026-1187` |
| Expired contract pricing | `HLG-88-40213` |
| Sanctions review freeze | `TCS-SG-4402` |
| Bank-change fraud window | `KPM-CA-7781` |
| Out-of-office approver → delegate → escalation | `VIS-2026-08702` |
| Supplier asks to change bank details | Suppliers → Kestrel Print & Media |

---

## Questions you will be asked

**"What if the model hallucinates?"**
Decisions come from the deterministic policy engine, never from a model. The
language model — when enabled at all — only narrates the rationale, and the
default engine is fully offline and templated from observed evidence. A
hallucinated sentence cannot become a posted invoice, because posting requires a
human to approve a typed payload.

**"How do we get to real autonomy?"**
Measure it. The HITL scoreboard gives per-agent acceptance and modification
rates. When an agent's proposals are accepted unmodified consistently, raise its
autonomy for that class of action — and the irreversible ones still stop.

**"Does this work with our ERP?"**
The ERP layer is a protocol with SAP S/4HANA, Oracle Fusion, Coupa and Ariba
adapters. In the demo they run against the local store; swapping a live adapter
does not change any agent code.

**"Can we run it in our environment?"**
Yes — SQLite by default, PostgreSQL via one env var, Docker compose included,
and no outbound network call is required for the platform to work.
