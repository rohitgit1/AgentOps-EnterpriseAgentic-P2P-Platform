"""Explainer surfaces: the live database model, and the Agents Academy.

Both are introspected from the running application rather than hand-maintained,
so they cannot drift from the code they describe. The schema comes from
SQLAlchemy metadata plus live row counts; the academy comes from each agent's
own declarations — its plan, skills, I/O contract and permitted actions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..agents.registry import get_agent, list_agents, suites
from ..database import Base, get_db
from ..enums import (
    ACTION_LABELS,
    ACTION_MIN_ROLE,
    AUTONOMY_LABELS,
    IRREVERSIBLE_ACTIONS,
    ROLE_LABELS,
    SUITE_BLURBS,
    SUITE_LABELS,
)
from ..models import AgentConfig, User
from ..services.hitl import registered_actions
from ..services.policy import DEFAULT_POLICIES
from ..skills import catalog as skills_catalog
from .deps import get_current_user

router = APIRouter(tags=["explain"])


# ==========================================================================
# Database model
# ==========================================================================
# Every table belongs to exactly one domain. Explicit rather than inferred, so
# the grouping reflects how the business thinks, not how the ORM imports.
DOMAINS: list[dict] = [
    {
        "key": "people",
        "label": "People & Authority",
        "blurb": "Who may decide what. The authority ladder is enforced from these rows.",
        "tables": ["users"],
    },
    {
        "key": "master_data",
        "label": "Master Data",
        "blurb": "Suppliers, purchase orders, receipts and contracts — the reference data every "
                 "match is measured against.",
        "tables": ["suppliers", "purchase_orders", "po_lines", "receipts", "contracts"],
    },
    {
        "key": "p2p_transactions",
        "label": "P2P Transactions",
        "blurb": "The operational accounts-payable lifecycle, from received document to released "
                 "payment.",
        "tables": ["invoices", "invoice_lines", "exceptions", "approvals", "payments",
                   "purchase_requests", "supplier_messages"],
    },
    {
        "key": "procurement",
        "label": "Procurement",
        "blurb": "Strategic sourcing, spend, supplier risk scorecards, contract drafts and tail "
                 "spend findings.",
        "tables": ["sourcing_events", "sourcing_bids", "spend_transactions",
                   "savings_opportunities", "risk_assessments", "contract_drafts",
                   "tail_spend_findings"],
    },
    {
        "key": "control_plane",
        "label": "Agent Control Plane",
        "blurb": "How agents are governed and what they proposed. An agent writes here — never to "
                 "the business tables above.",
        "tables": ["agent_configs", "agent_executions", "human_tasks", "policy_rules"],
    },
    {
        "key": "documents",
        "label": "Documents",
        "blurb": "Attachments in and deliverables out. One table, two directions.",
        "tables": ["artifacts"],
    },
    {
        "key": "assurance",
        "label": "Assurance",
        "blurb": "The append-only record. The audit log is hash-chained, so retroactive edits are "
                 "detectable.",
        "tables": ["audit_logs", "workflow_events", "sla_risks", "notifications"],
    },
]

# Notes on the tables that carry the platform's guarantees.
TABLE_NOTES: dict[str, str] = {
    "human_tasks":
        "The checkpoint. An agent's only way to express intent — it holds the proposed payload, "
        "the policy verdict and the human decision. Nothing in the business tables changes until a "
        "row here is approved.",
    "agent_executions":
        "One agent run: its plan, every tool observation, the evidence cited, the confidence and "
        "the policy evaluation. This is what makes a decision reconstructable months later.",
    "audit_logs":
        "Append-only and hash-chained — each row's hash covers the previous row's, so any "
        "retroactive edit breaks the chain and is detectable.",
    "artifacts":
        "Both uploaded attachments (direction=input) and agent deliverables (direction=output). "
        "An output is born status=draft and becomes released only when a human approves the "
        "checkpoint that owns it.",
    "policy_rules":
        "Policy-as-code. Tolerances, thresholds and the master HITL switch live here and are read "
        "on every proposal, so governance is data rather than code.",
    "agent_configs":
        "Per-agent governance: autonomy level, confidence threshold, financial ceiling and "
        "permitted actions. Editable from the Agent Control Room.",
    "invoices":
        "The central P2P record. `stage` decides which agent owns it; `human_touches` drives the "
        "touchless-rate KPI.",
    "suppliers":
        "Vendor master. Both operational AP screening and strategic risk scoring read from here.",
    "workflow_events":
        "The append-only stream behind the live activity rail and every timeline.",
    "spend_transactions":
        "The spend cube. Categories are written only after a human approves a classification "
        "proposal.",
    "risk_assessments":
        "A point-in-time four-domain scorecard. `applied_disposition` stays null until someone "
        "decides.",
    "sourcing_events":
        "An RFP/RFQ event. `status` moves draft → issued → awarded, and each transition is a human "
        "decision.",
    "contract_drafts":
        "Authored or uploaded contract paper with its clause findings and legal risk score.",
}


def _column_out(column) -> dict:
    return {
        "name": column.name,
        "type": str(column.type),
        "nullable": column.nullable,
        "primary_key": column.primary_key,
        "indexed": bool(column.index),
        "unique": bool(column.unique),
        "foreign_key": next(
            (f"{fk.column.table.name}.{fk.column.name}" for fk in column.foreign_keys), None
        ),
        "default": str(column.default.arg) if column.default is not None
        and not callable(getattr(column.default, "arg", None)) else None,
    }


@router.get("/data-model")
def data_model(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """The live schema: tables, columns, keys, relationships and row counts.

    Read from SQLAlchemy metadata, so it is always the schema actually running.
    """
    tables = {name: table for name, table in Base.metadata.tables.items()}

    # Live row counts — cheap on SQLite at demo scale, and it makes the model
    # concrete rather than theoretical.
    counts: dict[str, int] = {}
    for name in tables:
        try:
            counts[name] = db.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
        except Exception:  # pragma: no cover - table may not exist yet
            counts[name] = 0

    def describe(name: str) -> dict:
        table = tables[name]
        columns = [_column_out(c) for c in table.columns]
        outgoing = [
            {
                "from_column": fk.parent.name,
                "to_table": fk.column.table.name,
                "to_column": fk.column.name,
            }
            for fk in table.foreign_keys
        ]
        incoming = [
            {"from_table": other.name, "from_column": fk.parent.name, "to_column": fk.column.name}
            for other in tables.values()
            for fk in other.foreign_keys
            if fk.column.table.name == name
        ]
        return {
            "name": name,
            "row_count": counts.get(name, 0),
            "column_count": len(columns),
            "columns": columns,
            "primary_key": [c.name for c in table.primary_key.columns],
            "references": outgoing,
            "referenced_by": incoming,
            "note": TABLE_NOTES.get(name),
        }

    grouped = []
    assigned: set[str] = set()
    for domain in DOMAINS:
        present = [t for t in domain["tables"] if t in tables]
        assigned.update(present)
        grouped.append({
            **domain,
            "tables": [describe(t) for t in present],
            "row_total": sum(counts.get(t, 0) for t in present),
        })

    # Anything not explicitly placed still shows up, rather than disappearing.
    unassigned = sorted(set(tables) - assigned)
    if unassigned:
        grouped.append({
            "key": "other", "label": "Other", "blurb": "Tables not yet grouped.",
            "tables": [describe(t) for t in unassigned],
            "row_total": sum(counts.get(t, 0) for t in unassigned),
        })

    edges = [
        {"from": name, "to": fk.column.table.name, "column": fk.parent.name}
        for name, table in tables.items()
        for fk in table.foreign_keys
    ]

    return {
        "domains": grouped,
        "totals": {
            "tables": len(tables),
            "columns": sum(len(t.columns) for t in tables.values()),
            "rows": sum(counts.values()),
            "relationships": len(edges),
        },
        "relationships": edges,
        "dialect": db.bind.dialect.name if db.bind else "unknown",
        "invariant": (
            "Agents write only to the control-plane tables — agent_executions, human_tasks and "
            "artifacts. Every business table is written by an approved checkpoint, never by an "
            "agent directly."
        ),
    }


# ==========================================================================
# Agents Academy
# ==========================================================================
# One worked example per agent: what you hand it, what it does with it, and
# what comes back. Concrete on purpose — a reader should recognise their own
# data in it.
WORKED_EXAMPLES: dict[str, dict] = {
    "invoice_intake": {
        "scenario": "A supplier emails an invoice that duplicates one already in flight.",
        "given": "VIS-2026-08841 · Vertex Industrial Supply · USD 36,588.94 · PO-44210",
        "steps": [
            "Extracts header and lines; header confidence 93% from a clean EDI payload.",
            "Resolves 'Vertex Industrial Supply Inc.' to vendor master at 100%.",
            "Finds PO-44210 with 36,588.94 of open value.",
            "Duplicate screen scores 97% against an invoice received 1 hour earlier — identical "
            "number, identical amount, same PO.",
            "Tax arithmetic reconciles.",
        ],
        "produces": "Exception proposal: 'Suspected duplicate of VIS-2026-08841', severity "
                    "critical, financial impact 36,588.94.",
        "decided_by": "AP Clerk — confirm against the original, or clear it as a recurring charge.",
    },
    "three_way_match": {
        "scenario": "A chemicals supplier bills 8% above the PO rate.",
        "given": "BWC-449021 · 60 drums at 1,274.40 against a PO rate of 1,180.00",
        "steps": [
            "Fetches PO-44213 and its goods receipts.",
            "Compares line by line: line 1 price variance +8.0%, line 2 clean.",
            "Applies the 3% amount tolerance and the 50 USD absolute floor.",
            "Variance of 5,664.00 is outside both.",
        ],
        "produces": "Exception proposal: price_variance, 5,664.00 at stake, with the failing line "
                    "and the tolerance it broke.",
        "decided_by": "AP Clerk — short-pay to PO, accept the increase, or query the supplier.",
    },
    "approval_acceleration": {
        "scenario": "An invoice has been sitting 79 hours with an approver who is out of office.",
        "given": "VIS-2026-08702 · pending with Tomas Lindqvist (OOO for 5 days)",
        "steps": [
            "Reads the open approval: 79h old, 1 reminder already sent.",
            "Checks the calendar — approver is out of office.",
            "Reads the delegation matrix — Dana Okafor is named, limit covers the value.",
            "Policy says reroute before escalating; a reminder to an absent approver is wasted.",
        ],
        "produces": "Reroute proposal to the named delegate, with the SLA hours remaining.",
        "decided_by": "AP Clerk — approve the reroute, or escalate instead.",
    },
    "exception_resolution": {
        "scenario": "A price-mismatch exception where a contract rate exists.",
        "given": "EXC-5001 · invoiced 312.00/hr against a contracted 285.00/hr",
        "steps": [
            "Reads the exception and its originating invoice.",
            "Finds the governing contract and its rate card.",
            "Playbook: contract price governs where a rate-card entry exists.",
            "Prices the three options a human would otherwise construct by hand.",
        ],
        "produces": "Resolution proposal 'short-pay to contract' at 93% confidence, plus a drafted "
                    "supplier message, plus two priced alternatives.",
        "decided_by": "AP Clerk — pick an option; the message sends separately.",
    },
    "supplier_experience": {
        "scenario": "A supplier asks when they will be paid.",
        "given": "Portal message from Cascade Packaging about CSP-77120",
        "steps": [
            "Authenticates the portal session against vendor master.",
            "Classifies intent as payment_date at 86%.",
            "Reads the invoice and payment ledger for facts it may cite.",
            "Finds an open exception blocking payment — so it will not promise a date.",
        ],
        "produces": "A drafted reply stating the blocker in the supplier's own terms, with no "
                    "speculative payment date.",
        "decided_by": "AP Clerk — release the reply. The supplier sees nothing until then.",
    },
    "payment_readiness": {
        "scenario": "Building the week's payment run.",
        "given": "Approved, ERP-posted, unpaid invoices across ten suppliers",
        "steps": [
            "Screens each supplier for compliance blocks — a sanctions review removes one outright.",
            "Scores the rest: due_risk + supplier_tier + discount_value + sla_risk.",
            "Flags a 2/10 discount expiring in two days.",
            "Separates unposted invoices — they need an ERP posting first.",
        ],
        "produces": "A ranked run with each score component shown, plus the discount capture number.",
        "decided_by": "Treasury schedules; Controller releases. Both are irreversible.",
    },
    "supplier_risk": {
        "scenario": "A supplier changed bank details three days ago.",
        "given": "Kestrel Print & Media · bank account changed within the 10-day freeze window",
        "steps": [
            "Sweeps the vendor master for sanctions, insurance, tax forms and bank changes.",
            "Finds the bank change inside the freeze window — the strongest fraud signal in AP.",
            "Calculates unpaid exposure to that supplier.",
        ],
        "produces": "A payment-freeze exception per open invoice, with the verification step named.",
        "decided_by": "AP Clerk freezes; verification happens out-of-band with a known contact.",
    },
    "procurement_request": {
        "scenario": "A 9,080 USD software request.",
        "given": "PR-3002 · 40 additional seats · Aurora Software Systems",
        "steps": [
            "Reads the request value against the spend-authority ladder.",
            "9,080 falls in the under-10k band → manager review.",
            "Checks contract cover — the supplier is on an active agreement.",
        ],
        "produces": "A routing decision naming the band and the authority, with the contract note.",
        "decided_by": "AP Manager approves at the applicable authority.",
    },
    "contract_intelligence": {
        "scenario": "A consultancy bills above its rate card and adds a surcharge.",
        "given": "MCP-INV-5540 · senior consultants at 312.00 against 285.00 contracted, plus a "
                 "4,800 admin surcharge",
        "steps": [
            "Locates the governing contract and its rate card and allowed-charge list.",
            "Line 1 is 27.00/hr over the contracted rate across 320 hours.",
            "The admin surcharge matches no allowed charge type.",
            "Totals what is recoverable by short-paying to contract.",
        ],
        "produces": "A contract-breach flag with 13,440.00 recoverable, itemised, plus a drafted "
                    "supplier notification.",
        "decided_by": "Procurement — short-pay, pursue a credit note, or accept as a variation.",
    },
    "sla_command_center": {
        "scenario": "The portfolio is forecast to miss its SLA target.",
        "given": "15 invoices in flight, one approver holding 7 items",
        "steps": [
            "Forecasts breach risk per invoice from stage, age, exceptions and approver load.",
            "Measures queue depth per approver and finds the bottleneck.",
            "Prefers rebalancing over escalation — it costs nobody authority.",
        ],
        "produces": "A rebalancing plan, targeted escalations, and an executive alert with the "
                    "exposure number.",
        "decided_by": "AP Manager rebalances; CFO receives the alert.",
    },
    "sourcing_rfp": {
        "scenario": "Sourcing regional freight for FY27 from a requirements brief.",
        "given": "📎 requirements-freight-fy27.md — 850,000 USD budget, 98% OTIF, 24-month term",
        "steps": [
            "Parses the brief: 7 requirements, volume, term, budget and service level extracted.",
            "Shortlists 5 suppliers on category fit, tier and risk; compliance is a gate, not a weight.",
            "Generates the RFP with the evaluation weights published up front.",
            "Later, given a bid CSV, scores commercial / technical / risk separately.",
        ],
        "produces": "⬇ RFP-SRC-9002.md · shortlist.csv · scorecard.csv · award-recommendation.json",
        "decided_by": "Procurement issues the RFP; the award needs two approvers above the "
                      "dual-approval threshold.",
    },
    "spend_analytics": {
        "scenario": "Turning a raw spend export into priced opportunity.",
        "given": "📎 spend-extract-q4.csv — 120 transactions, 161,912 USD",
        "steps": [
            "Normalises supplier strings — three 'Vertex' variants collapse to one master record.",
            "Classifies 95.2% of value against the taxonomy, naming the token each match came from.",
            "Holds back rows below the 75% confidence floor rather than guessing.",
            "Measures contract compliance on value, not transaction count.",
            "Prices consolidation, coverage and demand levers at published rates.",
        ],
        "produces": "⬇ classified-spend.csv · unclassified-residual.csv · savings-register.csv · "
                    "spend-insight-brief.md",
        "decided_by": "Procurement publishes the classification and accepts opportunities into the "
                      "pipeline.",
    },
    "supplier_risk_compliance": {
        "scenario": "Quarterly supplier risk review with external feeds.",
        "given": "📎 credit-report.csv + 📎 otif-performance.csv",
        "steps": [
            "Scores four domains: financial, operational, compliance, ESG.",
            "A CCC credit rating with a bankruptcy flag drives financial risk to 90.",
            "73% OTIF and single-source status drive operational risk.",
            "Compliance is weighted hardest — it is the domain that stops trade outright.",
        ],
        "produces": "⬇ supplier-risk-scorecard.csv · supplier-risk-report.md, with every score "
                    "traced to a named finding.",
        "decided_by": "Procurement sets the disposition: approve, monitor, watchlist or block.",
    },
    "contract_lifecycle": {
        "scenario": "Reviewing a supplier's own paper before signing it.",
        "given": "📎 trident-msa-draft.md — a third-party MSA",
        "steps": [
            "Tests the document against the 12-clause mandatory set — 9 are missing.",
            "Finds unlimited liability, unilateral price changes, and a buyer-indemnifies clause.",
            "Detects a silent auto-renewal with no notice window.",
            "Scores legal risk at 100/100.",
        ],
        "produces": "⬇ clause-review.md with excerpts and redlines · obligations.csv. "
                    "Signature is deliberately not offered on paper this bad.",
        "decided_by": "Procurement accepts the draft with redlines; Controller issues for signature.",
    },
    "tail_spend": {
        "scenario": "Finding the unmanaged long tail.",
        "given": "📎 spend-extract-q4.csv + 📎 catalog.csv",
        "steps": [
            "Ranks suppliers by value and cuts the tail at the 80% cumulative Pareto point.",
            "The tail is 12.7% of spend but 75.8% of transactions — the classic shape.",
            "Clusters the tail by category and prices consolidation at 11% of moved spend.",
            "Tests off-catalog buying — a flag is only raised where a catalog substitute exists.",
        ],
        "produces": "⬇ tail-spend-analysis.csv · consolidation-plan.md · off-catalog.csv",
        "decided_by": "Procurement approves consolidation or catalog enforcement.",
    },
    "procurement_command_center": {
        "scenario": "Closing the quarter for the executive.",
        "given": "The whole procurement portfolio — no attachment needed",
        "steps": [
            "Rolls up sourcing cycle time against the 56-day manual baseline.",
            "Computes spend under management and contract compliance from the spend cube.",
            "Averages supplier risk and names the outliers.",
            "Forecasts contract renewals inside their notice windows.",
        ],
        "produces": "⬇ procurement-executive-brief.md · procurement-kpis.csv · risk-heatmap.json, "
                    "each KPI shown against target with the gap named.",
        "decided_by": "CFO publishes the brief.",
    },
}

# The concepts a newcomer needs before any individual agent makes sense.
FOUNDATIONS: list[dict] = [
    {
        "title": "An agent cannot act",
        "body": "Every agent returns proposals, never mutations. There is no code path from an "
                "agent to a business table. Its only output is a HumanTask holding the payload "
                "that *would* be applied. This is structural, not a convention.",
    },
    {
        "title": "The lifecycle",
        "body": "plan() → execute() → observe() → reason() → escalate() → report(). Every step is "
                "persisted: the plan it made, each tool it called and what came back, the evidence "
                "it cited, its confidence, and the policy verdict.",
    },
    {
        "title": "Seven gates, default deny",
        "body": "Each proposal passes HITL enforcement, agent autonomy, irreversibility, "
                "confidence, financial envelope, risk level and the action allow-list. "
                "Auto-execution requires every gate to open; anything else stops at a human.",
    },
    {
        "title": "Irreversible means irreversible",
        "body": "Posting to the ERP, releasing payment, messaging a supplier, editing vendor "
                "master, issuing an RFP, awarding an event, issuing a contract and publishing an "
                "executive brief always require a person — at any autonomy level, with enforcement "
                "off.",
    },
    {
        "title": "Documents follow the same rule",
        "body": "A deliverable an agent produces is born a draft. It becomes released only when a "
                "human approves the checkpoint that owns it. Reject, and the file stays a draft — "
                "evidence of what was considered, with nothing issued.",
    },
    {
        "title": "Decisions come from rules, not from a model",
        "body": "The deterministic policy engine decides. The language model, when enabled at all, "
                "only narrates the rationale — it cannot invent an action or change an outcome.",
    },
]


@router.get("/academy")
def academy(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Per-agent curriculum: what it does, how it works, what goes in and out."""
    configs = {c.agent_key: c for c in db.execute(select(AgentConfig)).scalars().all()}
    skills_by_name = {s["name"]: s for s in skills_catalog()}

    # "po_fetch" reads badly as "Po Fetch"; these tokens are always acronyms.
    acronyms = {"po", "gr", "rfp", "rfq", "sla", "kpi", "erp", "otif", "msa", "ap", "io"}

    def humanise(name: str) -> str:
        return " ".join(
            part.upper() if part in acronyms else part.title() for part in name.split("_")
        )

    def skill_out(name: str) -> dict:
        """A skill entry with every field always present.

        Agents declare more skills than the shared catalogue documents. An
        undocumented one still belongs in the lesson — the agent really does use
        it — but it must be labelled as undocumented rather than rendered as a
        catalogued skill with empty inputs and outputs.
        """
        entry = skills_by_name.get(name)
        if entry is None:
            return {
                "name": name,
                "title": humanise(name),
                "purpose": "Declared by the agent; not yet in the shared skills catalogue.",
                "inputs": [],
                "output": [],
                "guardrails": [],
                "documented": False,
            }
        return {
            "name": entry.get("name", name),
            "title": entry.get("title") or humanise(name),
            "purpose": entry.get("purpose") or "",
            "inputs": entry.get("inputs") or [],
            "output": entry.get("output") or [],
            "guardrails": entry.get("guardrails") or [],
            "documented": True,
        }

    def curriculum(agent) -> dict:
        described = agent.describe()
        config = configs.get(agent.key)

        # plan() is a static declaration in every agent, so it is safe to read
        # without a live context — and it is the honest source for "how it works".
        try:
            steps = [s.to_dict() for s in agent.plan(db, {})]
        except Exception:  # pragma: no cover - defensive
            steps = []

        actions = []
        for action in agent.allowed_actions:
            key = str(action)
            actions.append({
                "action": key,
                "label": ACTION_LABELS.get(key, key),
                "reversible": key not in IRREVERSIBLE_ACTIONS,
                "min_role": ACTION_MIN_ROLE.get(key, "ap_manager"),
                "min_role_label": ROLE_LABELS.get(ACTION_MIN_ROLE.get(key, "ap_manager"), ""),
                "executable": key in registered_actions(),
            })

        return {
            "key": agent.key,
            "name": agent.name,
            "suite": str(agent.suite),
            "role": agent.role,
            "mission": agent.mission,
            "goals": agent.goals,
            "tools": agent.tools,
            "lifecycle": steps,
            "skills": [skill_out(name) for name in agent.skills],
            "inputs": described["inputs"],
            "outputs": described["outputs"],
            "accepts_attachments": described["accepts_attachments"],
            "produces_artifacts": described["produces_artifacts"],
            "actions": actions,
            "governance": {
                "autonomy_level": config.autonomy_level if config else str(agent.default_autonomy),
                "autonomy_label": AUTONOMY_LABELS.get(
                    config.autonomy_level if config else str(agent.default_autonomy), ""),
                "confidence_threshold": config.confidence_threshold if config
                else agent.default_confidence_threshold,
                "max_auto_amount_usd": config.max_auto_amount_usd if config else 0.0,
                "escalation_role": str(agent.escalation_role),
                "escalation_role_label": ROLE_LABELS.get(str(agent.escalation_role), ""),
            },
            "worked_example": WORKED_EXAMPLES.get(agent.key),
            "prompt": described["prompt"],
        }

    return {
        "foundations": FOUNDATIONS,
        "suites": {
            key: {
                "label": SUITE_LABELS[key],
                "blurb": SUITE_BLURBS[key],
                "agents": [curriculum(a) for a in agents],
            }
            for key, agents in suites().items()
        },
        "totals": {
            "agents": len(list_agents()),
            "skills": len(skills_catalog()),
            "executable_actions": len(registered_actions()),
            "policy_rules": len(DEFAULT_POLICIES),
        },
    }


@router.get("/academy/{agent_key}")
def academy_agent(agent_key: str, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)) -> dict:
    if get_agent(agent_key) is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")
    full = academy(db=db, _=_)
    for suite in full["suites"].values():
        for entry in suite["agents"]:
            if entry["key"] == agent_key:
                return entry
    raise HTTPException(status_code=404, detail="Unknown agent.")
