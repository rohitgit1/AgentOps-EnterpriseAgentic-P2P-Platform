// Shared content for the developer walkthrough (deck + PDF).
// Screenshots are live captures from the running application.

const path = require('path')
const ROOT = path.resolve(__dirname, '..', '..')
// Screenshots written by capture.mjs, optimised by build.sh.
const IMG = process.env.WALKTHROUGH_IMG || path.join(ROOT, 'build', 'walkthrough', 'img')

const P = {
  bg:      '0C1120',   // the product's own surface — the deck matches the screenshots
  card:    '141C30',
  card2:   '1A2440',
  line:    '2A3550',
  accent:  '4F8EF7',
  mint:    '22A074',
  amber:   'C07F22',
  violet:  '9370F0',
  rose:    'E05260',
  text:    'E7EDF8',
  muted:   '93A1BD',
  faint:   '6B7A99',
  white:   'FFFFFF',
}

const F = { head: 'Cambria', body: 'Calibri', mono: 'Courier New' }

// --------------------------------------------------------------------------
// Screen-by-screen tour. `look` is what a developer should actually notice.
// --------------------------------------------------------------------------
const TOUR = [
  { img: '01-login', part: 'Getting started', title: 'Sign in — personas, not passwords',
    lede: 'Nine seeded personas across the authority ladder. Identity is selected; authority is enforced.',
    look: [
      ['The persona *is* the auth token', 'The client sends the chosen id in `X-User-Id`; `get_current_user` resolves it. Production puts SSO here and changes nothing else.'],
      ['Role drives everything downstream', 'What each persona can *decide* is enforced server-side in `hitl.decide()`, not hidden in the UI.'],
      ['Start as Priya (AP Clerk)', 'The lowest rung makes the authority limits visible within two clicks.'],
    ]},

  { img: '02-dashboard', part: 'P2P AgentOps', title: 'Command Center — the portfolio at a glance',
    lede: 'KPIs against industry benchmarks, the invoice pipeline, aging, and the human-in-the-loop scoreboard.',
    look: [
      ['Touchless rate is real', 'Computed from `invoices.human_touches`, not a constant. Approving proposals moves it.'],
      ['The HITL scoreboard', 'Open checkpoints, value held, and how many are irreversible — the number that matters in a governance conversation.'],
      ['Live activity rail', 'Server-Sent Events from `GET /api/events/stream`, fed by `workflow_events`.'],
    ]},

  { img: '03-inbox', part: 'P2P AgentOps', title: 'Approval Inbox — where every agent action stops',
    lede: 'Nothing below has touched the ERP, the ledger or a supplier. That happens only when a human decides.',
    look: [
      ['One row per `human_tasks` record', 'The inbox is a straight read of the checkpoint table, filtered by what your role may decide.'],
      ['Risk and irreversibility are badges', 'Both come from the policy verdict stored on the task at creation time.'],
      ['"Only what I can decide"', 'Toggles the role filter. Higher roles see *more* checkpoints, not fewer.'],
    ]},

  { img: '04-checkpoint-proposal', part: 'The checkpoint', title: 'Proposal — what would change, and why it stopped',
    lede: 'The amber panel answers the auditor\'s question directly: why is a human deciding this?',
    look: [
      ['"Why a human is deciding this"', 'Each line is a policy gate that blocked, rendered from the stored `PolicyDecision`. Not marketing copy — the actual verdict.'],
      ['Authority is enforced here', 'Signed in as Controller, this CFO-level decision is refused. The buttons are present; the server rejects it.'],
      ['Evidence, not assertion', 'Every row cites the observation it came from, so the decision is reconstructable months later.'],
    ]},

  { img: '05-checkpoint-reasoning', part: 'The checkpoint', title: 'Agent reasoning — the plan, the tools, the confidence',
    lede: 'The full run: what it planned, each tool call and what came back, and the decision rules it applied.',
    look: [
      ['Persisted, not regenerated', 'Read from `agent_executions.plan` / `.observations` / `.evidence`. Re-opening this in a year shows the same thing.'],
      ['Decision rules are quantitative', 'e.g. "Amount variance +8.00% against a 3% tolerance" — a rule you can argue with.'],
      ['The narrator cannot change the outcome', 'The policy engine decided before the LLM was asked to explain it.'],
    ]},

  { img: '06-checkpoint-policy', part: 'The checkpoint', title: 'Policy & audit — every gate, opened or blocked',
    lede: 'All seven gates with their verdicts, the required role, and the audit entries this decision will write.',
    look: [
      ['Default deny', '`allow_auto_execute` needs *every* gate to open. Any single block sends it here.'],
      ['Value-based escalation is visible', 'The flags — `controller_threshold`, `cfo_threshold`, `dual_approval` — are the ones the engine actually set.'],
      ['The decision writes the chain', 'Approving appends a hash-chained `audit_logs` row covering the previous row\'s hash.'],
    ]},

  { img: '07-invoices', part: 'P2P AgentOps', title: 'Invoices — the working set',
    lede: 'Every in-flight invoice with its stage, match result, owner and agent activity.',
    look: [
      ['`stage` decides which agent owns it', 'The orchestrator maps stage → agent. `matching` belongs to Three-Way Match, and nothing else touches it.'],
      ['Match result is stored, not derived', 'The full line-level analysis is kept on `invoices.match_details` for audit.'],
      ['Filter by stage to follow one agent', 'The fastest way to see a single agent\'s working set.'],
    ]},

  { img: '08-invoice-detail', part: 'P2P AgentOps', title: 'Invoice detail — timeline, runs and source document',
    lede: 'Every event, every agent run and every human decision against one invoice, in order.',
    look: [
      ['The timeline is `workflow_events`', 'Append-only and derived. Nothing in it can be edited from the UI.'],
      ['Agent runs link to their checkpoints', 'Run → proposal → decision → applied payload, all navigable.'],
      ['The source document is retained', 'Extraction is auditable against the text it actually read.'],
    ]},

  { img: '09-exceptions', part: 'P2P AgentOps', title: 'Exceptions — the agent\'s diagnosis, priced',
    lede: 'Open cases with the proposed resolution and the alternatives costed out.',
    look: [
      ['Alternatives carry payloads', 'Picking one substitutes its payload into the checkpoint — the reviewer never retypes anything.'],
      ['Below 70% confidence it proposes nothing', 'Exception Resolution asks for a human owner instead. A confident wrong answer is worse than none.'],
      ['Severity is computed from impact', 'Not a label the agent picked; a function of the money at stake.'],
    ]},

  { img: '10-payments', part: 'P2P AgentOps', title: 'Payments — scheduling, discounts and release',
    lede: 'Payment-run proposals ranked by priority score, with the early-pay discount at stake quoted.',
    look: [
      ['`due_risk + supplier_tier + discount_value + sla_risk`', 'The breakdown is shown, not just the total — a total on its own is not reviewable.'],
      ['Blocked suppliers never appear', 'Payment Readiness skips them entirely rather than proposing a release that would be rejected.'],
      ['Release is irreversible', 'Always a Controller, always a human, at any autonomy level.'],
    ]},

  { img: '11-procurement', part: 'Procurement AgentOps', title: 'Procurement Command Center — six executive KPIs',
    lede: 'Spend under management, contract compliance, supplier risk, tail spend, cycle time and savings.',
    look: [
      ['Most start off target on purpose', 'Approving the agents\' proposals is what closes the gaps — that is the story worth showing.'],
      ['Publishing the brief is CFO-level', 'It reaches an audience that will act on it and cannot be unsent.'],
      ['Heatmap data is an artifact', 'Produced as a downloadable `.json`, born a draft like every other deliverable.'],
    ]},

  { img: '12-sourcing', part: 'Procurement AgentOps', title: 'Sourcing Events — RFP to award',
    lede: 'The RFP pipeline, bid scorecards and the award decision, with weights published up front.',
    look: [
      ['Compliance is a gate, not a weight', 'A supplier failing a mandatory rule is excluded, not scored down. A weight can be outvoted by price; a gate cannot.'],
      ['Issuing an RFP has zero financial impact', 'It invites bids and commits nothing. The award is where the money moves — and where CFO escalation applies.'],
      ['Above $100k the award needs two approvers', 'Compared by `user.id`, so one person signing twice is one approval.'],
    ]},

  { img: '13-spend', part: 'Procurement AgentOps', title: 'Spend & Savings — classification and the savings pipeline',
    lede: 'Classified spend by category, coverage, and savings priced per lever.',
    look: [
      ['The unclassified residual ships as a file', 'A coverage percentage you cannot see inside cannot be acted on.'],
      ['Savings are modelled, not estimated', 'Published rates per lever, so two runs over the same data agree and the method is auditable.'],
      ['Below 85% coverage it escalates', 'The savings numbers would rest on too little classified spend.'],
    ]},

  { img: '14-supplier-risk', part: 'Procurement AgentOps', title: 'Supplier Risk — four domains, one disposition',
    lede: 'Financial, operational, compliance and ESG risk scored separately, then blended.',
    look: [
      ['0.30 / 0.25 / 0.30 / 0.15', 'A weighted blend, so one bad domain does not by itself condemn a supplier — but each domain is carried through.'],
      ['`applied_disposition` stays null', 'The assessment records the recommendation. The vendor master changes only on approval.'],
      ['Thin evidence lowers confidence', 'Two or more "no data" findings drop it to 0.72 rather than scoring confidently on nothing.'],
    ]},

  { img: '15-contracts', part: 'Procurement AgentOps', title: 'Contracts — clause review that withholds signature',
    lede: 'Drafts, clause findings, obligations and renewals, with the legal risk score built additively.',
    look: [
      ['Signature is not offered on bad paper', 'While mandatory clauses are missing or risky ones present, the proposal is never made — so it cannot be approved.'],
      ['A missing clause carries weight too', 'An omission is a risk, not a neutral absence.'],
      ['Silent auto-renewal is flagged with its notice period', 'The risk is the date passing unnoticed, not the clause existing.'],
    ]},

  { img: '16-tail-spend', part: 'Procurement AgentOps', title: 'Tail Spend — the long tail, governed',
    lede: 'Head/tail split on a Pareto cut, consolidation clusters and off-catalogue enforcement.',
    look: [
      ['$4,000 materiality floor', 'Without it, clustering surfaces dozens of clusters that cost more to action than they save.'],
      ['No preferred supplier → zero savings claimed', 'The finding is recorded honestly rather than claiming savings nobody can realise.'],
      ['Enforcement needs a substitute', 'Where no catalogue item exists, the buyer had no compliant option — so nothing is proposed.'],
    ]},

  { img: '17-control-room', part: 'Intelligence', title: 'Agent Control Room — governance per agent',
    lede: 'Autonomy level, confidence threshold, financial ceiling, permitted actions and run history.',
    look: [
      ['All 16 ship at L2 · Human Approval', 'Every proposal waits. L4 is disabled entirely while global enforcement is on.'],
      ['The fleet kill switch', '`P2P_AGENTS_PAUSED` or the button — a disabled agent returns `blocked_by_policy` without running.'],
      ['Run one agent on demand', 'The fastest development loop: change `decide()`, click run, read the checkpoint.'],
    ]},

  { img: '18-agent-config', part: 'Intelligence', title: 'Agent configuration — the envelope you can move',
    lede: 'Everything the policy engine reads about this agent, editable and audited.',
    look: [
      ['These are `agent_configs` rows', 'Seeded from the class defaults, then owned by the database. Governance is data.'],
      ['Raising autonomy does not bypass HITL', 'Gate 1 is the global switch; gates 2–7 still apply either way.'],
      ['The prompt is shown, not hidden', 'Generated by `BaseAgent.prompt_template()` from the declared identity.'],
    ]},

  { img: '19-agent-io', part: 'Intelligence', title: 'Agent I/O Catalogue — the contract, all 16 agents',
    lede: 'What each agent consumes and what it hands back, with formats and the files it has produced.',
    look: [
      ['Rendered from `IOSpec` declarations', 'Not a written document — the same objects the agent declares in code.'],
      ['Five kinds', '`attachment`, `data`, `artifact`, `record`, `proposal` — the last one is always a checkpoint.'],
      ['Produced files are downloadable', 'Straight from `artifacts`, with their draft/released state visible.'],
    ]},

  { img: '20-artifacts', part: 'Intelligence', title: 'Artifact Library — documents in and out',
    lede: 'One table, two directions. Uploaded attachments and agent deliverables side by side.',
    look: [
      ['Outputs are born `draft`', 'They become `released` only when the checkpoint that owns them is approved.'],
      ['Rejection leaves them as drafts', 'Evidence of what was considered, with nothing issued.'],
      ['Seven samples ship seeded', 'So a demo can run an agent against real input with no preparation.'],
    ]},

  { img: '21-sla', part: 'Intelligence', title: 'SLA Command Center — forecast, not report',
    lede: 'Breach forecast per invoice with its drivers, and the interventions that would protect it.',
    look: [
      ['Costs remaining stages only', 'Charging every invoice for exception handling forecasts the whole portfolio at risk — wrong and useless.'],
      ['Rebalancing respects approval limits', 'A move that creates an unapprovable assignment has relocated the problem, not solved it.'],
      ['Below 95% forecast compliance it escalates', 'That is an executive condition, not a queue item.'],
    ]},

  { img: '22-skills', part: 'Intelligence', title: 'Skills Library — 28 shared capabilities',
    lede: 'The analysis layer the agents compose. A skill returns evidence; it never writes.',
    look: [
      ['Contracts are generated', '`skills/<name>/SKILL.md` from the live descriptors, so documentation cannot drift.'],
      ['Skills are pure functions of their inputs', 'No session, no writes — which is why they are trivially testable.'],
      ['Reused across agents', '`variance_analysis` serves Three-Way Match, Exception Resolution and Contract Intelligence.'],
    ]},

  { img: '23-audit', part: 'Assurance', title: 'Audit Trail — hash-chained and verifiable',
    lede: 'Every decision, who made it, on what evidence, and whether enforcement was on at the time.',
    look: [
      ['`sha256(previous_hash ‖ payload)`', 'Each row covers the one before it. Editing history breaks verification at that row.'],
      ['`GET /api/audit/verify` replays from genesis', 'And reports the first divergence, if any.'],
      ['Agent and human entries are distinguished', '`actor_type` separates what the agent concluded from what a person decided.'],
    ]},

  { img: '24-governance', part: 'Assurance', title: 'Governance — policy as data',
    lede: 'Fifteen rules, the master HITL switch, and the thresholds every agent reads on every run.',
    look: [
      ['Changing governance is a data change', 'Tolerances and thresholds are rows in `policy_rules`, not constants in code.'],
      ['The master switch opens gate 1 only', 'An L2 agent still stops; an irreversible action still stops; a low-confidence proposal still stops.'],
      ['Every edit is audited', 'Who loosened the tolerance, when, and from what to what.'],
    ]},

  { img: '25-academy', part: 'Under the Hood', title: 'Agents Academy — six foundations, then each agent',
    lede: 'What is true of every agent before you look at any one of them.',
    look: [
      ['Read from the agents\' own declarations', 'A lesson cannot describe behaviour the agent does not have.'],
      ['The foundations are the mental model', 'An agent cannot act · the lifecycle · seven gates · irreversible means irreversible · documents follow the same rule · rules decide, not a model.'],
      ['This is the onboarding path', 'New developer, no context: read the six, then pick the agent you are changing.'],
    ]},

  { img: '26-academy-io', part: 'Under the Hood', title: 'Academy — input and output, per agent',
    lede: 'The question the screen exists to answer: what do I give it, and what do I get back?',
    look: [
      ['Kind, format and example per field', 'Enough to construct a call without reading the source.'],
      ['Attachments arrive parsed', 'CSV as typed rows, JSON as records, PDF as its text layer — the agent never touches storage.'],
      ['Outputs name the checkpoint they need', 'So the approval path is visible before you run anything.'],
    ]},

  { img: '27-academy-example', part: 'Under the Hood', title: 'Academy — a worked example against seeded data',
    lede: 'Given → it does → produces → decided by. Runnable in the demo as written.',
    look: [
      ['The lifecycle is the declared `plan()`', 'With the tool and the rationale for each step.'],
      ['The example uses shipped fixtures', 'You can reproduce it in the running demo in under a minute.'],
      ['"Decided by" names the authority', 'Including when two approvers are required.'],
    ]},

  { img: '28-data-model', part: 'Under the Hood', title: 'Data Model — the live schema, seven domains',
    lede: '29 tables introspected from SQLAlchemy metadata, with row counts read at request time.',
    look: [
      ['Agent-writable tables are marked', 'Only `agent_executions`, `human_tasks` and `artifacts`. Everything else needs an approved checkpoint.'],
      ['Nothing here is hand-maintained', 'A new table appears the moment it exists — and a test fails if it has no domain.'],
      ['Row counts are live', '`COUNT(*)` per table per request. Cheap at demo scale; cache it at volume.'],
    ]},

  { img: '29-data-model-drawer', part: 'Under the Hood', title: 'Data Model — one table, both directions',
    lede: 'Columns with types, keys, indexes and defaults, and foreign keys resolved both ways.',
    look: [
      ['`human_tasks` is the checkpoint', 'Proposed payload, policy verdict, human decision, applied payload — the whole story in one row.'],
      ['Both ends of every foreign key', 'Points-at and pointed-at-by, each clickable to jump.'],
      ['Watch the primary keys', '`workflow_events` and `audit_logs` use an integer PK because SQLite only autoincrements a primary key.'],
    ]},
]

// --------------------------------------------------------------------------
// Code sections
// --------------------------------------------------------------------------
const CODE = {
  proposal: `@dataclass
class ProposedAction:
    action_kind: str          # one of 33 ActionKinds
    title: str
    summary: str
    payload: dict             # what the executor will apply
    diff_preview: list[dict]  # before/after for the reviewer
    alternatives: list[dict]  # priced options, each with its own payload
    confidence: float
    financial_impact_usd: float
    artifact_ids: list[str]   # drafts this action releases on approval

# No session. No ORM object. No executor reference.
# It cannot write anything, because there is nothing here to write with.`,

  plan: `def plan(self, db: Session, context: dict) -> list[PlanStep]:
    return [
        PlanStep(1, "Fetch the purchase order and its lines", "po_fetch",
                 "The PO is the contractual basis for what may be billed."),
        PlanStep(2, "Fetch goods receipts posted against the PO", "gr_fetch",
                 "Receipt confirms the goods or services actually arrived."),
        PlanStep(3, "Run line-level variance analysis", "variance_analysis",
                 "Header totals hide offsetting line errors."),
        PlanStep(4, "Apply tolerance policy", "policy_compliance",
                 "Tolerance is a governance decision, not an agent preference."),
        PlanStep(5, "Propose clearance or an exception", "hitl_checkpoint",
                 "Either outcome is reviewed by AP before it takes effect."),
    ]`,

  gather: `def gather(self, db: Session, context: dict) -> list[Observation]:
    store = PolicyStore(db)              # governance is data, read every run
    context["tolerances"] = {
        "amount_pct":   store.number("match.amount_variance_pct", 3.0),
        "quantity_pct": store.number("match.quantity_variance_pct", 2.0),
        "amount_abs":   store.number("match.amount_variance_abs", 50.0),
    }

    analysis = variance_analysis.analyze(
        invoice_lines=..., po_lines=..., received_qty_by_line=...,
        **context["tolerances"])
    context["analysis"] = analysis       # state on context, never on self

    return [Observation("variance_analysis",
                        f"Match '{analysis['match_result']}'",
                        analysis, ok=analysis["clean"])]`,

  decide: `def decide(self, db, context, observations) -> AgentDecision:
    analysis = context["analysis"]
    if not analysis["clean"]:
        ...                                  # exception path

    return AgentDecision(
        conclusion=f"{invoice.invoice_number} matches within tolerance.",
        confidence=0.97 if result == MatchResult.MATCHED else 0.94,
        decision_rules=[
            f"Amount variance {analysis['total_variance_pct']:+.2f}% "
            f"against a {tolerances['amount_pct']}% tolerance.",
        ],
        evidence=[evidence_item("Total variance", ..., "variance_analysis")],
        proposals=[ProposedAction(
            action_kind=ActionKind.ADVANCE_STAGE,
            payload={"invoice_id": invoice.id,
                     "stage": WorkflowStage.APPROVAL,
                     "match_result": result, "match_details": analysis},
            confidence=0.97, financial_impact_usd=amount)],
        handoff_to="approval_acceleration",
    )`,

  policy: `# services/policy.py — every gate must open. Default deny.

if store.flag("hitl.enforce_global", settings.enforce_human_in_the_loop):
    blocked.append("Global human-in-the-loop enforcement is ON.")

if action_kind in IRREVERSIBLE_ACTIONS:
    blocked.append(f"'{action_kind}' is irreversible — always a human.")

if confidence < threshold:
    blocked.append(f"Confidence {confidence:.0%} below {threshold:.0%}.")

# Authority escalates with value, on top of the per-action minimum.
if financial_impact_usd >= 250_000:
    required_role, flag = Role.CFO, "cfo_threshold"
elif financial_impact_usd >= 50_000:
    required_role, flag = Role.CONTROLLER, "controller_threshold"

dual_approval = (financial_impact_usd >= dual_threshold
                 and action_kind in IRREVERSIBLE_ACTIONS)

return PolicyDecision(allow_auto_execute=not blocked, reasons=..., ...)`,

  executor: `# services/hitl.py — the ONLY place business data is written.

_HANDLERS: dict[str, Handler] = {}

def action(kind: str):                       # registration decorator
    def wrapper(fn): _HANDLERS[str(kind)] = fn; return fn
    return wrapper

@action(ActionKind.ADVANCE_STAGE)
def _advance_stage(db, task, payload, actor) -> dict:
    invoice = _invoice(db, task, payload)
    before  = snapshot(invoice, INVOICE_AUDIT_FIELDS)
    _advance(db, invoice, payload["stage"], payload.get("status"), actor.full_name)
    write_audit(db, action="invoice.stage_advanced", actor=actor.full_name,
                actor_type="human", before_state=before,
                after_state=snapshot(invoice, INVOICE_AUDIT_FIELDS), ...)
    return {"stage": invoice.stage, "status": invoice.status}

# An action with no registered handler simply cannot happen.`,

  addagent: `# 1. backend/app/agents/my_agent.py
class MyAgent(BaseAgent):
    key   = "my_agent"
    name  = "My Agent"
    suite = AgentSuite.P2P
    default_autonomy = AutonomyLevel.HUMAN_APPROVAL
    default_confidence_threshold = 0.90
    allowed_actions = [ActionKind.CREATE_EXCEPTION]
    inputs  = [IOSpec("invoice_id", "The invoice to inspect.", required=True)]
    outputs = [IOSpec("Checkpoint", "Open an exception — AP Clerk decides.",
                      kind="proposal")]

    def plan(self, db, context):    ...   # static declaration
    def gather(self, db, context):  ...   # one Observation per tool
    def decide(self, db, ctx, obs): ...   # returns proposals, never writes

# 2. registry.py     → add MyAgent to P2P_AGENT_CLASSES
# 3. explain.py      → add a WORKED_EXAMPLES["my_agent"] entry
# 4. agent_build_notes.py → add BUILD_NOTES["my_agent"]
# 5. python scripts/generate_agent_specs.py
# 6. pytest — three drift guards will tell you what you missed`,

  test: `def test_agent_cannot_mutate_state(seeded):
    before = db.execute(select(SavingsOpportunity)).all()
    get_agent("spend_analytics").run(db, {...})
    after = db.execute(select(SavingsOpportunity)).all()
    assert len(after) == len(before)


def test_spec_matches_the_code(agent_key):
    """Change an agent, forget to regenerate
       its spec, and this fails."""
    expected = gen.render(agent, BUILD_NOTES[key])
    committed = (ROOT / "agents" / key /
                 "AGENT.md").read_text()
    assert committed == expected`,
}

const TREE = `AgentOps-EnterpriseAgentic-P2P-Platform/
├── backend/app/
│   ├── enums.py          roles, stages, 33 action kinds, IRREVERSIBLE_ACTIONS
│   ├── models.py         29 tables in seven domains
│   ├── agents/           base.py + 16 agents + registry + orchestrator
│   ├── skills/           28 analysis capabilities — no writes
│   ├── services/
│   │   ├── policy.py     the seven gates, default deny
│   │   ├── hitl.py       checkpoints + the ONLY business writes
│   │   ├── artifacts.py  draft → released lifecycle, parsers
│   │   └── audit.py      the hash chain
│   └── api/              auth · core · hitl · agents · procurement
│                         · analytics · admin · explain
├── frontend/src/         22 screens, React + TS + Tailwind
├── agents/<key>/AGENT.md 16 generated build specifications
├── skills/<name>/SKILL.md 28 generated skill contracts
├── docs/SPECIFICATION.md the platform specification of record
└── scripts/              the two documentation generators`

const RUNLOOP = [
  ['Resolve attachments', '`context["attachment_ids"]` → parsed records in `context["attachments"]`'],
  ['Check the config', 'A disabled agent returns `blocked_by_policy` without running'],
  ['Plan', '`plan()` → `PlanStep`s, persisted to `agent_executions.plan`'],
  ['Execute / observe', '`gather()` → `Observation`s, each persisted and streamed live'],
  ['Reason', '`decide()` → `AgentDecision`; `llm.reason()` narrates what was already decided'],
  ['Escalate', 'Records an event. It annotates — it does not change what a human decides'],
  ['Propose', 'Each proposal → `policy.evaluate()` → a `HumanTask` carrying the verdict'],
  ['Report', 'An audit entry and a completion event'],
]

const ROLES = [
  ['supplier', '0', 'Nothing — external party'],
  ['ap_clerk', '10', 'Extraction, matching, exceptions, supplier drafts'],
  ['procurement / treasury', '20', '+ sourcing, savings, dispositions / payment scheduling'],
  ['ap_manager', '30', '+ ERP posting, escalations, invoice approvals'],
  ['controller', '40', '+ payment release, master data, contract signature'],
  ['cfo', '50', 'Everything, including executive briefs'],
  ['admin', '60', '+ agent autonomy, the governance switch'],
]

const GATES = [
  ['Global HITL enforcement', '`hitl.enforce_global` is off'],
  ['Agent autonomy', 'The agent is at L3 or above'],
  ['Irreversibility', 'The action is not in `IRREVERSIBLE_ACTIONS`'],
  ['Confidence', 'Proposal confidence ≥ the agent threshold'],
  ['Financial envelope', 'Impact ≤ the agent\'s `max_auto_amount_usd`'],
  ['Risk level', 'Computed risk is not high or critical'],
  ['Action allow-list', 'The action is in the agent\'s permitted set'],
]

module.exports = { IMG, P, F, TOUR, CODE, TREE, RUNLOOP, ROLES, GATES }
