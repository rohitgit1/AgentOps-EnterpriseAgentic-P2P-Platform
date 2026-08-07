// Builds the developer walkthrough as a paginated HTML document, which
// Playwright then prints to PDF. Same content as the deck, more prose.
const fs = require('fs')
const { IMG, TOUR, CODE, TREE, RUNLOOP, ROLES, GATES } = require('./content.js')

const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const md = (t) => esc(t)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*([^*]+)\*/g, '<em>$1</em>')

const img = (name) => `file://${IMG}/${name}.jpg`

// --------------------------------------------------------------------------
// Extra prose the deck has no room for.
// --------------------------------------------------------------------------
const PROSE = {
  '01-login': 'There are no passwords. The login screen lists nine seeded personas spanning the authority ladder, and picking one sets a single header on every subsequent request. This is a deliberate demo affordance, and it is also exactly where a production deployment differs: swap the persona picker for SSO, keep `get_current_user`, and every authority check downstream is unchanged. What is <em>not</em> a demo affordance is the enforcement — what each persona may decide is checked server-side on every decision, and no UI state can loosen it.',
  '02-dashboard': 'The Command Center is the first screen a stakeholder sees, so it answers the two questions they arrive with: is this working, and what is waiting on me. The KPI row measures against published industry benchmarks rather than internal targets, which makes "80% touchless" mean something outside the room. The right-hand rail is a live Server-Sent Events stream — leave it open during a sweep and you watch each agent plan, call its tools and land its proposals in real time.',
  '03-inbox': 'This is the screen the platform exists to produce. Every proposal from every agent lands here and stops. The banner is literal rather than reassuring: at the moment you are reading the list, nothing in it has touched the ERP, the ledger or a supplier. Each row is one `human_tasks` record; the risk badge and the irreversible flag are the policy verdict computed when the proposal was created, stored on the row, and never recomputed — so what you see is what the engine actually decided.',
  '04-checkpoint-proposal': 'Open a checkpoint and the amber panel is the first thing you read. It is generated from the stored `PolicyDecision`, listing the gates that <em>blocked</em> this action in the engine\'s own words. That is what makes the screen defensible in an audit: it is not an explanation written afterwards, it is the verdict itself. Note the red band above the buttons. Signed in as a Controller against a CFO-level decision, the platform tells you plainly that you cannot act — and if you posted the request anyway, `hitl.decide()` would refuse it.',
  '05-checkpoint-reasoning': 'The reasoning tab is the agent\'s working shown in full: the plan it declared before starting, every tool it called with what came back, the evidence it chose to cite, and the decision rules it applied. All of it is read from `agent_executions`, not regenerated — open this checkpoint in a year and it says the same thing. The decision rules are deliberately quantitative. "Amount variance +8.00% against a 3% tolerance" is a claim a supplier can dispute; "looks incorrect" is not.',
  '06-checkpoint-policy': 'Seven gates, each with its verdict. `allow_auto_execute` is true only when every one opens, which is why in the default configuration this tab is a list of reasons the action stopped. The flags shown — `controller_threshold`, `cfo_threshold`, `dual_approval` — are the ones the engine actually set for this proposal, driven by its financial impact. Approving from here appends a row to `audit_logs` whose hash covers the previous row, which is what makes the history tamper-evident.',
  '07-invoices': 'The working set. `stage` is the single most important column: the orchestrator maps a stage to exactly one owning agent, so an invoice in `matching` belongs to Three-Way Match and nothing else will act on it. That mapping is the whole state machine — there is no separate workflow engine to reason about. Filtering by stage is the fastest way to see one agent\'s caseload.',
  '08-invoice-detail': 'Everything that has happened to one invoice, in order: events, agent runs, human decisions, and the source document the extraction actually read. The timeline is a projection of `workflow_events`, which is append-only — nothing in this view can be edited, from the UI or otherwise. Each agent run links to the checkpoints it produced, and each checkpoint to the payload that was ultimately applied, so a reader can walk from "why is this invoice on hold" back to the observation that caused it.',
  '09-exceptions': 'An exception is a case, not an error. The agent diagnoses it, proposes a resolution, and prices the alternatives — and each alternative carries its own payload, so choosing one substitutes it into the checkpoint without the reviewer retyping anything. The confidence floor here is worth internalising: below 0.70 the agent proposes no resolution at all and asks for a human owner instead. A confidently wrong resolution on a disputed invoice costs more than no resolution.',
  '10-payments': 'Payment Readiness produces the run in lifecycle order — post to ERP, then release what is due, then hold what is blocked, then schedule the rest. The priority score is shown decomposed rather than as a single number, because a single number is not something a treasury analyst can review. One behaviour is easy to miss and matters: a payment whose supplier is on hold is never proposed at all. Proposing it and expecting the reviewer to catch it would be a trap.',
  '11-procurement': 'The strategic half of the platform, on the same control plane. Six KPIs against the specification\'s targets, and most of them start off target on purpose — the demo\'s story is that approving the agents\' proposals is what closes the gaps. Publishing the executive brief is a CFO-level, irreversible action for the obvious reason: it reaches an audience that will act on it and cannot be recalled.',
  '12-sourcing': 'Two design decisions here are worth arguing about, so they are made explicitly. First, compliance is a gate and not a weight — a supplier failing a mandatory rule is excluded from the shortlist rather than scored down, because a weighted score can always be outvoted by an attractive price. Second, issuing an RFP carries a financial impact of zero. It invites bids and commits nothing; the award is where money moves, so that is where value-based escalation and dual approval apply.',
  '13-spend': 'Classification, savings and — importantly — the residual. Shipping the unclassified remainder as its own downloadable file is the point: a coverage percentage you cannot look inside is not something a category manager can act on. Savings are modelled per lever at published rates rather than estimated per line, so two runs over the same extract produce the same number and the method can be argued with.',
  '14-supplier-risk': 'Four domains scored separately, then blended 0.30 / 0.25 / 0.30 / 0.15. The blend prevents one bad domain from condemning a supplier by itself, and carrying each domain through to the scorecard prevents the blend from hiding which one drove the result. The recommendation is written to `risk_assessments`; `applied_disposition` stays null until a human approves, which is why the recommendation and the applied outcome are separate columns.',
  '15-contracts': 'The clause review is the most opinionated agent in the platform, and deliberately so: while mandatory clauses are missing or risky ones are present, the "issue for signature" proposal is <em>never made</em>. A reviewer cannot approve a checkpoint that does not exist. The sample MSA shipped with the demo contains unlimited liability, a unilateral price-change clause, a buyer-indemnifies-supplier clause and a silent auto-renewal, so the analysis has something real to find — and it scores badly enough that signature is withheld.',
  '16-tail-spend': 'A Pareto cut splits head from tail, then the tail is clustered by category. Two floors keep the output actionable: a cluster must be worth at least $4,000 and contain at least two suppliers. Without the materiality floor the screen fills with sub-thousand-dollar clusters that cost more to action than they save. Where no preferred supplier exists the finding is recorded with zero modelled savings rather than a number nobody can realise.',
  '17-control-room': 'Per-agent governance, and the fastest development loop in the platform: change a `decide()` branch, click Run, read the resulting checkpoint. All sixteen agents ship at L2 — every proposal waits for a human — and L4 is disabled outright while global enforcement is on. The fleet kill switch is here too; a disabled agent returns `blocked_by_policy` without executing its plan.',
  '18-agent-config': 'These fields are rows in `agent_configs`, seeded from the class defaults and then owned by the database. That is the important part: governance is data, so tightening a confidence threshold or lowering a ceiling is an audited edit rather than a deploy. Raising autonomy does not bypass human review — the global switch is gate 1, and gates 2 through 7 apply regardless of where it is set.',
  '19-agent-io': 'The contract for all sixteen agents on one screen, rendered from the `IOSpec` objects each agent declares in code. There are five kinds — `attachment`, `data`, `artifact`, `record`, `proposal` — and the last is always a checkpoint, which is how you can tell at a glance what each agent will ask a human to decide. Files the agent has actually produced are listed underneath, downloadable, with their draft or released state visible.',
  '20-artifacts': 'One table, two directions. Uploads arrive as `direction=input`; deliverables are written as `direction=output` with `status=draft`. A draft becomes released only when the checkpoint that owns it is approved, and rejecting that checkpoint leaves the files as drafts — evidence of what was considered, with nothing issued. Seven sample attachments ship seeded so an agent can be run against real input immediately.',
  '21-sla': 'A forecast, not a report. The prediction costs the stages an invoice has left rather than the whole workflow, and it excludes exception handling unless the invoice is actually in exception — charging every invoice for the worst case forecasts the entire portfolio at risk, which is both wrong and useless. Rebalancing proposals only move work to an approver whose limit covers the invoice; a move that creates an unapprovable assignment has relocated the problem.',
  '22-skills': 'Twenty-eight analysis capabilities that the agents compose. A skill takes plain data and returns plain data — no session, no writes — which is why they are trivial to unit test and why the same `variance_analysis` serves Three-Way Match, Exception Resolution and Contract Intelligence. Their contracts in `skills/<name>/SKILL.md` are generated from the live descriptors, so the documentation cannot drift from the implementation.',
  '23-audit': 'Every decision, human or agent, with the actor, the entity, the before and after state, the confidence, and whether enforcement was on at the time. Each row stores `sha256(previous_hash ‖ canonical_payload)`, so the log is a chain rather than a table. `GET /api/audit/verify` replays it from genesis and names the first row that fails — which is what makes an out-of-band edit detectable rather than merely discouraged.',
  '24-governance': 'Fifteen rules, editable, audited, and read on every agent run. Loosening a match tolerance here changes agent behaviour on the next run with no deploy and a record of who changed it. The master switch is the one people ask about: turning it off opens gate 1 only. An L2 agent still stops, an irreversible action still stops, a low-confidence proposal still stops. It exists so the governance story can be demonstrated end to end, not as a bypass.',
  '25-academy': 'The onboarding path for a developer with no context. Six foundations that hold for every agent, then a curriculum per agent — all of it read from the agents\' own declarations, so a lesson cannot describe behaviour an agent does not have. Read the six foundations, then jump straight to the agent you are about to change.',
  '26-academy-io': 'The question this screen exists to answer: what do I give this agent, and what do I get back? Each field carries its kind, accepted formats and a worked example — enough to construct a call without opening the source. Attachments arrive already parsed: CSV as typed rows with a field list, JSON as records, Markdown as text, PDF as its embedded text layer. An agent never touches storage.',
  '27-academy-example': 'Every agent ships with a worked example against the seeded fixtures, in four beats: given, it does, produces, decided by. These are runnable as written — the files named in "given" are in the artifact library when the demo boots. The lifecycle above it is the agent\'s declared `plan()`, with the tool and the rationale for each step.',
  '28-data-model': 'The schema, live. Tables, columns, keys and foreign keys come from SQLAlchemy metadata; row counts are `COUNT(*)` executed when you open the page. Nothing is hand-maintained, so a new table appears the moment it exists — and a test fails if it was added without being placed in a domain. The three agent-writable tables are marked; every other table in the system is written only by an approved checkpoint.',
  '29-data-model-drawer': 'One table in full, with foreign keys resolved in both directions and clickable to jump. `human_tasks` is the one to read first — proposed payload, policy verdict, human decision and applied payload are all columns on the same row, which is the entire governance story in one place. Note the primary keys on `workflow_events` and `audit_logs`: they are integer PKs because SQLite only autoincrements a primary key, and both tables need a monotonic sequence.',
}

// --------------------------------------------------------------------------
const tourPages = TOUR.map((t) => `
<section class="page">
  <div class="kicker">Part 02 · ${esc(t.part)}</div>
  <h2>${esc(t.title)}</h2>
  <p class="lede">${md(t.lede)}</p>
  <figure><img src="${img(t.img)}" alt="${esc(t.title)}"></figure>
  <p class="prose">${PROSE[t.img] || ''}</p>
  <div class="look">
    <div class="look-h">What to look at</div>
    ${t.look.map(([h, b], i) => `
      <div class="look-row"><span class="n">${i + 1}</span>
        <div><strong>${md(h)}</strong><span>${md(b)}</span></div>
      </div>`).join('')}
  </div>
</section>`).join('\n')

const html = `<!doctype html><html><head><meta charset="utf-8">
<title>AgentOps — Developer Walkthrough</title>
<style>
  @page { size: A4; margin: 16mm 15mm 18mm; }
  :root{
    --ink:#0C1120; --body:#2C3648; --mute:#5A6880; --faint:#8E9AB0;
    --accent:#2B62C4; --mint:#127A5A; --amber:#9A6410; --rose:#B0323F;
    --violet:#6B45C0; --rule:#D9DFEA; --tint:#F3F6FC;
  }
  *{box-sizing:border-box}
  body{margin:0;font:10.5pt/1.62 Calibri,"Segoe UI",Arial,sans-serif;color:var(--body);
       -webkit-print-color-adjust:exact;print-color-adjust:exact}
  code{font:9.4pt/1.45 "Courier New",monospace;color:var(--accent);
       background:#EEF3FC;padding:0 3px;border-radius:3px}
  em{font-style:italic;color:var(--ink)}
  h1,h2,h3{font-family:Cambria,Georgia,serif;color:var(--ink);margin:0}
  .page{page-break-after:always;break-after:page}
  .page:last-child{page-break-after:auto}

  /* Cover */
  .cover{background:var(--ink);color:#E7EDF8;margin:-16mm -15mm;padding:34mm 20mm 20mm;
         height:297mm;position:relative;overflow:hidden}
  .cover .halo{position:absolute;border-radius:50%;opacity:.14}
  .cover h1{color:#fff;font-size:52pt;line-height:1.02;margin:6mm 0 0}
  .cover .sub{font-family:Cambria,Georgia,serif;font-size:20pt;color:#93A1BD;margin:5mm 0 0}
  .cover .tag{font-size:13pt;font-style:italic;color:#3FBF92;margin:4mm 0 0}
  .cover .eyebrow{font-size:10.5pt;font-weight:700;letter-spacing:.24em;color:#7FB0FF}
  .cover .stats{display:flex;gap:11mm;margin:22mm 0 0}
  .cover .stats b{display:block;font-family:Cambria,Georgia,serif;font-size:30pt;color:#7FB0FF;line-height:1}
  .cover .stats span{font-size:9.5pt;color:#8E9AB0}
  .cover .foot{position:absolute;left:20mm;right:20mm;bottom:18mm;font-size:9.5pt;color:#6B7A99;
               border-top:1px solid #26314C;padding-top:4mm}

  .kicker{font-size:8.6pt;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
          color:var(--accent);margin:0 0 2.5mm}
  h2{font-size:20pt;line-height:1.2;margin:0 0 2.5mm}
  h3{font-size:13pt;margin:6mm 0 2mm}
  .lede{font-size:11.4pt;color:var(--mute);margin:0 0 4mm}
  .prose{margin:4mm 0 0;text-align:justify}
  p{margin:0 0 3mm}

  figure{margin:0;border:1px solid var(--rule);border-radius:4px;overflow:hidden;background:var(--ink)}
  figure img{display:block;width:100%}

  .look{margin:5mm 0 0;background:var(--tint);border:1px solid var(--rule);
        border-radius:4px;padding:4mm 5mm}
  .look-h{font-size:8.6pt;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
          color:var(--faint);margin:0 0 2.5mm}
  .look-row{display:flex;gap:3mm;margin:0 0 2.5mm}
  .look-row:last-child{margin-bottom:0}
  .look-row .n{flex:0 0 5mm;height:5mm;border-radius:50%;background:var(--accent);color:#fff;
               font-size:8pt;font-weight:700;text-align:center;line-height:5mm}
  .look-row strong{display:block;color:var(--ink);font-size:10.4pt}
  .look-row span{display:block;color:var(--mute);font-size:9.8pt;line-height:1.5}

  pre{background:var(--ink);color:#C3CDE0;border-radius:4px;padding:4mm 5mm;overflow:hidden;
      font:8.6pt/1.6 "Courier New",monospace;margin:3mm 0;white-space:pre-wrap}
  pre .c{color:#7FB0FF}
  table{width:100%;border-collapse:collapse;margin:3mm 0;font-size:10pt}
  th{text-align:left;font-size:8.4pt;letter-spacing:.12em;text-transform:uppercase;
     color:var(--faint);border-bottom:1.5px solid var(--rule);padding:2mm 3mm 1.5mm}
  td{border-bottom:1px solid var(--rule);padding:2mm 3mm;vertical-align:top}
  td:first-child{color:var(--ink)}

  .callout{border:1px solid var(--accent);background:#F0F5FE;border-radius:4px;
           padding:4mm 5mm;margin:4mm 0}
  .callout.warn{border-color:var(--rose);background:#FDF2F3}
  .callout.good{border-color:var(--mint);background:#F0F9F5}
  .callout b{color:var(--ink)}

  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:4mm}
  .cardbox{border:1px solid var(--rule);border-radius:4px;padding:4mm;background:#fff}
  .cardbox h4{margin:0 0 1.5mm;font-family:Cambria,Georgia,serif;font-size:11.5pt;color:var(--ink)}
  .cardbox p{margin:0;font-size:9.8pt;color:var(--mute);line-height:1.5}

  .divider{display:flex;align-items:center;min-height:245mm}
  .toc li{margin:0 0 2.6mm;list-style:none}
  .toc .num{display:inline-block;width:11mm;font-family:Cambria,Georgia,serif;
            font-weight:700;color:var(--accent)}
  .toc b{color:var(--ink);font-size:11.5pt}
  .toc span{display:block;margin-left:11mm;color:var(--mute);font-size:10pt}
  ol.steps{padding-left:5mm;margin:3mm 0}
  ol.steps li{margin:0 0 2.4mm}
</style></head><body>

<!-- Cover -->
<section class="page cover">
  <div class="halo" style="width:120mm;height:120mm;right:-30mm;top:-40mm;background:#4F8EF7"></div>
  <div class="halo" style="width:80mm;height:80mm;right:-10mm;bottom:20mm;background:#9370F0"></div>
  <div class="eyebrow">DEVELOPER WALKTHROUGH</div>
  <h1>AgentOps</h1>
  <div class="sub">Enterprise Agentic P2P &amp; Procurement Platform</div>
  <div class="tag">Sixteen agents. Twenty-eight skills. Zero write access.</div>
  <div class="stats">
    ${[['16','agents'],['28','skills'],['33','actions'],['29','tables'],['79','tests']]
      .map(([n,l])=>`<div><b>${n}</b><span>${l}</span></div>`).join('')}
  </div>
  <div class="foot">Version 1.1.0 · 30 screenshots captured live from the running application ·
    Companion to <code style="background:none;color:#7FB0FF">docs/SPECIFICATION.md</code> and
    <code style="background:none;color:#7FB0FF">agents/&lt;key&gt;/AGENT.md</code></div>
</section>

<!-- Contents -->
<section class="page">
  <div class="kicker">How this guide runs</div>
  <h2>Contents</h2>
  <p class="lede">Three parts, in the order a new developer needs them.</p>
  <ul class="toc" style="padding:0;margin:6mm 0 0">
    <li><span class="num">01</span><b>Orientation</b>
      <span>The one rule that explains the system · repository layout · the three ways to run it · the authority ladder</span></li>
    <li><span class="num">02</span><b>The product, screen by screen</b>
      <span>All 22 screens from live captures, each with what a developer should actually notice</span></li>
    <li><span class="num">03</span><b>The code</b>
      <span>The run loop · anatomy of an agent · the policy engine · the executor registry · adding your own · testing</span></li>
    <li><span class="num">04</span><b>Reference</b>
      <span>Troubleshooting by symptom · where to read next</span></li>
  </ul>
  <div class="callout" style="margin-top:8mm">
    <b>Every screenshot in Part 02 was captured from this application running locally</b>,
    after a live agent sweep against the seeded dataset. Nothing in this guide is a mock-up,
    and the terminal output in Part 03 is real output from the commands shown.
  </div>
  <h3>Companion documents</h3>
  <table>
    <tr><th>Document</th><th>What it covers</th></tr>
    <tr><td><code>docs/SPECIFICATION.md</code></td><td>The platform specification of record — guarantees, architecture, every enumerated value, the data model, governance, API, and a rebuild order</td></tr>
    <tr><td><code>agents/&lt;key&gt;/AGENT.md</code></td><td>One complete build specification per agent. Enough to rebuild any agent without reading its source</td></tr>
    <tr><td><code>skills/&lt;name&gt;/SKILL.md</code></td><td>The 28 shared capabilities and their contracts</td></tr>
    <tr><td><code>RUNNING.md</code></td><td>Prerequisites, every launch path, configuration reference, troubleshooting</td></tr>
  </table>
</section>

<!-- The invariant -->
<section class="page">
  <div class="kicker">Part 01 · Orientation</div>
  <h2>One rule explains the whole system</h2>
  <div class="callout" style="padding:6mm">
    <div style="font-family:Cambria,Georgia,serif;font-size:17pt;color:var(--ink);margin-bottom:2mm">
      An agent returns proposals, never mutations.</div>
    There is no code path from an agent to a business table. This is not a convention
    or a review rule — it is a structural fact about how the code is shaped.
  </div>
  <div class="grid2" style="margin-top:5mm">
    <div class="cardbox"><h4>1 · A proposal is inert</h4><p><code>ProposedAction</code> is a
      dataclass. No database session, no ORM object, no executor reference. It cannot write
      because there is nothing in it to write with.</p></div>
    <div class="cardbox"><h4>2 · One consumer</h4><p>The only code that reads a proposal is
      <code>hitl.create_checkpoint()</code>, which writes a <code>HumanTask</code> row and
      nothing else.</p></div>
  </div>
  <div class="cardbox" style="margin-top:4mm"><h4>3 · One writer</h4><p>Business data is
    written only by an executor registered with <code>@action(...)</code> in
    <code>services/hitl.py</code>, and the only caller of an executor is
    <code>hitl.execute_action()</code> — reached exclusively from <code>hitl.decide()</code>,
    after an authority check.</p></div>
  <pre>${esc(CODE.proposal)}</pre>
  <p class="prose">Three consequences follow, and they are the reason the guarantee is worth
  having. An agent that wanted to write to a business table would have to be
  <em>rewritten</em> to do so, which means this is not a matter of developer discipline. A code
  reviewer does not have to scan an agent for stray writes. And testing the guarantee is
  trivial: run the agent, count the rows, assert nothing moved.</p>
  <div class="callout good"><b>Check any change against this sentence, not the feature list.</b>
    An agent that can write to a business table gives you the same screens and none of the
    guarantees.</div>
</section>

<!-- Repository layout -->
<section class="page">
  <div class="kicker">Part 01 · Orientation</div>
  <h2>Where everything lives</h2>
  <p class="lede">Roughly 25,000 lines across a FastAPI backend and a React SPA.</p>
  <pre>${esc(TREE)}</pre>
  <h3>The four files that carry the guarantees</h3>
  <table>
    <tr><th>File</th><th>Why it matters</th></tr>
    <tr><td><code>services/policy.py</code></td><td>The seven gates. Read this before changing any threshold — it is the only place that decides whether an action may bypass a human.</td></tr>
    <tr><td><code>services/hitl.py</code></td><td>The only place business data is written. Thirty-three executors, one per action kind, each registered by decorator.</td></tr>
    <tr><td><code>agents/base.py</code></td><td>The run loop every agent shares. Because it is shared, the guarantees hold uniformly rather than per agent.</td></tr>
    <tr><td><code>enums.py</code></td><td>Roles, stages, action kinds, the irreversible set. Everything downstream references it; change here and regenerate the docs.</td></tr>
  </table>
</section>

<!-- Running -->
<section class="page">
  <div class="kicker">Part 01 · Orientation</div>
  <h2>Three ways to run it</h2>
  <p class="lede">No cloud account, no API key, no database server. SQLite by default, one process, one port.</p>
  <h3>Standard — use this for a demo</h3>
  <pre>./run.sh          # macOS / Linux / WSL
.\\run.ps1         # Windows PowerShell
# → http://localhost:8000</pre>
  <p>Creates the virtualenv, installs dependencies, builds the SPA, seeds the demo dataset if
  the database is empty, and serves both the API and the UI on port 8000. Idempotent — safe to
  re-run at any time. First run takes one to three minutes; later runs start in seconds.</p>
  <h3>Development — hot reload</h3>
  <pre>./run.sh --dev              # or:  .\\run.ps1 -Dev
# UI  → http://localhost:5173   (Vite, hot module reload)
# API → http://localhost:8000   (Vite proxies /api to it)

P2P_RELOAD=1 ./run.sh --dev    # backend auto-reload too</pre>
  <p>Use port 5173 in this mode. Port 8000 serves the last <em>built</em> UI, which will be stale.</p>
  <h3>Docker</h3>
  <pre>docker compose up --build
docker compose down -v && docker compose up --build   # fresh start</pre>
  <p>Nothing needed on the host. The demo database persists in the named volume
  <code>p2p-data</code>, so decisions survive a restart. The compose file also contains a
  commented-out PostgreSQL service — uncomment it and the <code>P2P_DATABASE_URL</code> line
  for a shared multi-user demo. The schema is identical either way; there is no migration step.</p>
  <div class="callout">Between client meetings, reset from the UI: sign in as
    <b>Platform Service Account</b> → <b>Governance</b> → <b>Rebuild</b>. Or
    <code>./run.sh --reset</code>.</div>
</section>

<!-- Authority -->
<section class="page">
  <div class="kicker">Part 01 · Orientation</div>
  <h2>The authority ladder</h2>
  <p class="lede">A ladder, not a set — a Controller can decide everything a clerk can, plus more.
  Enforced server-side on every decision, not in the UI.</p>
  <table>
    <tr><th>Role</th><th>Authority</th><th>May decide</th></tr>
    ${ROLES.map(([r, a, d]) => `<tr><td><code>${r}</code></td><td><b>${a}</b></td><td>${esc(d)}</td></tr>`).join('')}
  </table>
  <h3>Escalation by value</h3>
  <p>On top of the per-action minimum in <code>ACTION_MIN_ROLE</code>, the required approver
  rises with the money at stake:</p>
  <table>
    <tr><th>Financial impact</th><th>Effect</th><th>Flag</th></tr>
    <tr><td>≥ $50,000</td><td>Minimum approver raised to Controller</td><td><code>controller_threshold</code></td></tr>
    <tr><td>≥ $250,000</td><td>Minimum approver raised to CFO</td><td><code>cfo_threshold</code></td></tr>
    <tr><td>≥ $100,000 <em>and irreversible</em></td><td>Two distinct approvers required</td><td><code>dual_approval</code></td></tr>
  </table>
  <div class="callout warn"><b>Dual approval compares <code>user.id</code>, not role.</b>
    The same person approving twice is one approval. This is checked in
    <code>hitl.decide()</code>, which reads the prior approver off the task before accepting
    a second signature.</div>
  <p class="prose">The dual-approval threshold itself is a policy row
  (<code>hitl.dual_approval_above</code>), so it can be tightened from the Governance screen
  without a deploy — and the change is audited.</p>
</section>

<!-- Part 2 divider -->
<section class="page divider">
  <div>
    <div class="kicker">Part 02</div>
    <h2 style="font-size:34pt">The product, screen by screen</h2>
    <p class="lede" style="font-size:13pt;max-width:130mm">All 22 screens, captured live after an
    agent sweep against the seeded dataset. For each: what it shows, why it is shaped that way,
    and what a developer should notice.</p>
  </div>
</section>

${tourPages}

<!-- Part 3 divider -->
<section class="page divider">
  <div>
    <div class="kicker">Part 03</div>
    <h2 style="font-size:34pt">The code</h2>
    <p class="lede" style="font-size:13pt;max-width:130mm">The run loop, the anatomy of an agent,
    the policy engine, the executor registry — and how to add your own without breaking the
    guarantee.</p>
  </div>
</section>

<!-- Run loop -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>The run loop</h2>
  <p class="lede">Identical for all sixteen agents. Everything except <code>plan()</code>,
  <code>gather()</code> and <code>decide()</code> is the base class — which is why the
  guarantees hold uniformly rather than per agent.</p>
  <table>
    <tr><th>#</th><th>Step</th><th>What happens</th></tr>
    ${RUNLOOP.map(([h, b], i) => `<tr><td><b>${i + 1}</b></td><td><b>${esc(h)}</b></td><td>${md(b)}</td></tr>`).join('')}
  </table>
  <p class="prose">Every step is persisted. Re-opening a run months later shows the plan it made,
  each tool and what came back, the evidence it cited, its confidence and the policy verdict on
  every proposal — which is what makes an agent decision auditable rather than merely logged.</p>
  <div class="callout"><b>Step 7 is where the guarantee lives.</b>
    <code>policy.evaluate()</code> runs on every proposal, and the result is a
    <code>HumanTask</code> carrying the verdict — never a write. Auto-execution is reachable
    only when every gate opens, which the default configuration makes impossible.</div>
  <h3>Failure handling</h3>
  <p>An exception anywhere in the loop marks the execution <code>failed</code>, records the error
  on the row, emits a critical event and re-raises. Partial work is visible rather than
  discarded — the plan and any observations already made are persisted, so a failed run is
  still diagnosable.</p>
</section>

<!-- plan -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>Anatomy of an agent — <code style="font-size:15pt">plan()</code></h2>
  <p class="lede">Three-Way Match, the clearest of the sixteen. <code>plan()</code> declares the
  steps; it does not run them.</p>
  <pre>${esc(CODE.plan)}</pre>
  <div class="callout warn"><b><code>plan()</code> is called with an empty context</b> by the
    Agents Academy screen and by the build-specification generator. If it queried the database
    both would break — and it would no longer be a plan, it would be a trace.</div>
  <h3>Every step answers three things</h3>
  <table>
    <tr><th>Field</th><th>What it is for</th></tr>
    <tr><td><b>action</b></td><td>What the step does, written for a reviewer rather than as a log line.</td></tr>
    <tr><td><b>tool</b></td><td>The name shown in the Academy, in the run timeline and in the live activity rail.</td></tr>
    <tr><td><b>rationale</b></td><td>Why the step belongs. "Header totals hide offsetting line errors" is a reason a reader can judge; "fetch data" is not.</td></tr>
  </table>
</section>

<!-- gather -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>Anatomy of an agent — <code style="font-size:15pt">gather()</code></h2>
  <p class="lede">Collects evidence and returns one <code>Observation</code> per tool. Still writes nothing.</p>
  <pre>${esc(CODE.gather)}</pre>
  <div class="grid2" style="margin-top:4mm">
    <div class="cardbox"><h4>State on <code>context</code>, never <code>self</code></h4>
      <p>Agents are singletons in the registry. Anything stored on the instance leaks into the
      next run — a bug that only appears under load or in a fleet sweep.</p></div>
    <div class="cardbox"><h4>Policy is read per run</h4>
      <p>Tolerances come from <code>policy_rules</code> every time, so loosening one from the
      Governance screen takes effect on the next run with no deploy.</p></div>
    <div class="cardbox"><h4>One Observation per tool</h4>
      <p>Each is persisted and streamed to the activity rail as it happens, so a reviewer sees
      what was asked and what came back — not just the conclusion.</p></div>
    <div class="cardbox"><h4>Failure is an observation too</h4>
      <p><code>ok=False</code> with a summary. An agent that cannot read its input reports that
      it could not, rather than raising and losing the run.</p></div>
  </div>
</section>

<!-- decide -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>Anatomy of an agent — <code style="font-size:15pt">decide()</code></h2>
  <p class="lede">Returns an <code>AgentDecision</code>. Every field on it is something a
  reviewer will read.</p>
  <pre>${esc(CODE.decide)}</pre>
  <h3>Four rules for writing one</h3>
  <table>
    <tr><th>Rule</th><th>Why</th></tr>
    <tr><td><b>Confidence is a real number</b></td><td>One the agent stands behind. The policy engine gates on it, so a hard-coded 0.95 quietly defeats the control it is meant to feed.</td></tr>
    <tr><td><b>Evidence cites its source</b></td><td>Every item names the observation it came from, so a reader can trace a claim back to the tool call that produced it.</td></tr>
    <tr><td><b>Impact is what is actually at risk</b></td><td>It drives role escalation and dual approval. Inflated, it blocks routine work; deflated, it under-reviews real exposure.</td></tr>
    <tr><td><b>Decision rules are quantitative</b></td><td>"+8.00% against a 3% tolerance" is a claim a supplier can dispute. "Looks wrong" is not.</td></tr>
  </table>
  <div class="callout"><b>Branch order matters.</b> A blocking condition should return
    immediately rather than accumulating proposals — a suspected duplicate invoice is not worth
    correcting extraction fields on.</div>
</section>

<!-- policy -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>The policy engine — seven gates, default deny</h2>
  <p class="lede"><code>allow_auto_execute</code> requires <em>every</em> gate to open. Anything
  else becomes a checkpoint.</p>
  <table>
    <tr><th>#</th><th>Gate</th><th>Opens when</th></tr>
    ${GATES.map(([g, o], i) => `<tr><td><b>${i + 1}</b></td><td><b>${esc(g)}</b></td><td>${md(o)}</td></tr>`).join('')}
  </table>
  <pre>${esc(CODE.policy)}</pre>
  <div class="callout"><b>Turning global enforcement off opens gate 1 only.</b> An L2 agent still
    stops, an irreversible action still stops, a low-confidence proposal still stops, and an
    over-ceiling amount still stops. The switch exists so the governance story is demonstrable
    end to end — not as a bypass.</div>
  <p class="prose">Every gate that blocks records <em>why</em>, and that reason is stored on the
  task and rendered in the amber panel a reviewer reads. A checkpoint always explains itself,
  which is what makes the seventh gate — the action allow-list — safe to keep narrow.</p>
</section>

<!-- executors -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>The executor registry — the only writer</h2>
  <p class="lede">Thirty-three executors, one per action kind. If you are writing business data,
  you are writing one of these.</p>
  <pre>${esc(CODE.executor)}</pre>
  <h3>Twelve actions are irreversible</h3>
  <pre style="color:#F0B0B8">post_to_erp · schedule_payment · release_payment · block_supplier
update_supplier_master · send_supplier_message · approve_purchase_request
issue_rfp · award_sourcing_event · issue_contract_for_signature
consolidate_suppliers · publish_executive_brief</pre>
  <p>The reasoning is uniform: each one reaches outside the system — a ledger, a bank, a
  supplier, a signature, a boardroom — and cannot be taken back by editing a row. None may
  execute without a person, at any autonomy level, with enforcement off.</p>
  <div class="callout good"><b>An action with no registered handler simply cannot happen.</b>
    A test asserts that every action an agent declares in <code>allowed_actions</code> has an
    executor, so an agent cannot advertise something the platform cannot apply.</div>
</section>

<!-- adding an agent -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>Adding your own agent</h2>
  <p class="lede">Six steps. The test suite tells you what you forgot.</p>
  <pre>${esc(CODE.addagent)}</pre>
  <h3>The guards that catch you</h3>
  <table>
    <tr><th>If you skip</th><th>What fails</th></tr>
    <tr><td>Registering an executor</td><td>An agent may not advertise an action nothing can apply.</td></tr>
    <tr><td>The Academy lesson</td><td>A new agent must not ship undocumented.</td></tr>
    <tr><td>The build notes</td><td>A specification without the reasoning is not one anyone can rebuild from.</td></tr>
    <tr><td>Regenerating the spec</td><td>Specs are regenerated in memory and compared to what you committed.</td></tr>
  </table>
  <h3>Adding a new action kind</h3>
  <ol class="steps">
    <li>Add the member to <code>ActionKind</code> and a label to <code>ACTION_LABELS</code>.</li>
    <li>Set its floor in <code>ACTION_MIN_ROLE</code>. If it reaches outside the system, add it
      to <code>IRREVERSIBLE_ACTIONS</code> — that is the decision that matters.</li>
    <li>Write the executor in <code>services/hitl.py</code> under <code>@action(...)</code>.
      Snapshot before, mutate, <code>write_audit</code> with both states.</li>
    <li>Add it to the proposing agent's <code>allowed_actions</code> and regenerate the specs.</li>
  </ol>
</section>

<!-- testing -->
<section class="page">
  <div class="kicker">Part 03 · The code</div>
  <h2>Testing</h2>
  <p class="lede">79 tests. Three of them fail the build rather than the demo.</p>
  <figure><img src="${img('30-verification')}" alt="Verification output"></figure>
  <p class="prose" style="margin-top:4mm">Real output from the commands shown: the full suite,
  the audit chain replayed from genesis, the live schema totals, and both documentation
  generators.</p>
  <pre>${esc(CODE.test)}</pre>
  <div class="callout good"><b>Three drift guards.</b> A new table that lands outside a
    data-model domain; a new agent that ships without an Academy lesson or build notes; a
    committed <code>AGENT.md</code> or <code>SKILL.md</code> that no longer matches the code it
    describes. Each is a missed step rather than a bug — run the generators in
    <code>scripts/</code> and commit the result.</div>
</section>

<!-- troubleshooting -->
<section class="page">
  <div class="kicker">Part 04 · Reference</div>
  <h2>Where to look when something is wrong</h2>
  <table>
    <tr><th>Symptom</th><th>Where to look</th></tr>
    <tr><td><b>An agent proposes nothing</b></td><td>Its <code>decide()</code> returned no proposals, or the agent is disabled in <code>agent_configs</code>. Check the run in the Agent Control Room — a blocked run says so explicitly.</td></tr>
    <tr><td><b>A proposal will not execute</b></td><td>The checkpoint's <b>Policy &amp; audit</b> tab names the gate that held it and the role required. That is the verdict itself, not a reconstruction.</td></tr>
    <tr><td><b>A decision is refused</b></td><td>Authority. <code>ACTION_MIN_ROLE</code>, plus value-based escalation, plus dual approval above the threshold on irreversible actions.</td></tr>
    <tr><td><b>The audit chain is broken</b></td><td><code>GET /api/audit/verify</code> names the first divergent row. Something wrote history out of band.</td></tr>
    <tr><td><b>A deliverable stays a draft</b></td><td>Its checkpoint was rejected, or the proposal never carried <code>artifact_ids</code> — only a linked artifact is released on approval.</td></tr>
    <tr><td><b>A documentation test fails</b></td><td>Not a bug, a missed step. Run <code>scripts/generate_agent_specs.py</code> and <code>scripts/generate_skill_docs.py</code>, then commit.</td></tr>
    <tr><td><b>Port 8000 is busy</b></td><td><code>lsof -ti :8000 | xargs kill</code>, or edit the <code>uvicorn.run(...)</code> call in <code>backend/app/main.py</code>.</td></tr>
    <tr><td><b>The UI looks stale in --dev</b></td><td>You are on port 8000, which serves the last built SPA. Use port 5173.</td></tr>
  </table>
  <h3>Read next, in this order</h3>
  <ol class="steps">
    <li><code>docs/SPECIFICATION.md</code> — the platform: guarantees, enumerations, data model, governance, API, and a rebuild order.</li>
    <li><code>agents/&lt;key&gt;/AGENT.md</code> — one complete build specification per agent, enough to rebuild it without the source.</li>
    <li><code>skills/&lt;name&gt;/SKILL.md</code> — the 28 shared capabilities and their contracts.</li>
    <li>The <b>Agents Academy</b> screen — the same material, live, against seeded data you can actually run.</li>
  </ol>
  <div class="callout good" style="margin-top:6mm"><b>Check any rebuild against the invariant,
    not the feature list.</b> An agent that can write to a business table gives you the same
    screens and none of the guarantees.</div>
</section>

</body></html>`

const out = process.argv[2] || '/tmp/walkthrough.html'
fs.writeFileSync(out, html)
console.log('wrote', out, '·', (html.length / 1024).toFixed(0), 'KB of HTML')
