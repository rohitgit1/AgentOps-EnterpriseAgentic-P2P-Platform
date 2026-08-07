/**
 * Agents Academy — how each agent works, in the order you need to learn it.
 *
 * Six foundations that apply to every agent, then per agent: what goes in, what
 * comes out, the steps it runs, a worked example against the seeded data, the
 * actions it may propose and who has to approve them.
 *
 * Everything is read from the agents' own declarations, so a curriculum entry
 * cannot describe behaviour the agent does not have.
 */
import { useMemo, useState } from 'react'
import { Chip, Empty, Panel, Spinner } from '../components/ui'
import { money, pct } from '../lib/format'
import { useApi } from '../store'

type IOSpec = {
  name: string
  description: string
  kind: 'attachment' | 'data' | 'artifact' | 'record' | 'proposal'
  formats: string[]
  required: boolean
  example?: string | null
}

type LifecycleStep = { step: number; action: string; tool: string; rationale: string }

type Skill = {
  name: string
  title: string
  purpose: string
  inputs: string[]
  output: string[]
  guardrails?: string[]
}

type Action = {
  action: string
  label: string
  reversible: boolean
  min_role: string
  min_role_label: string
  executable: boolean
}

type Governance = {
  autonomy_level: string
  autonomy_label: string
  confidence_threshold: number
  max_auto_amount_usd: number
  escalation_role: string
  escalation_role_label: string
}

type WorkedExample = {
  scenario: string
  given: string
  steps: string[]
  produces: string
  decided_by: string
}

type AgentLesson = {
  key: string
  name: string
  suite: string
  role: string
  mission: string
  goals: string[]
  tools: string[]
  lifecycle: LifecycleStep[]
  skills: Skill[]
  inputs: IOSpec[]
  outputs: IOSpec[]
  accepts_attachments: boolean
  produces_artifacts: boolean
  actions: Action[]
  governance: Governance
  worked_example: WorkedExample | null
  prompt: string
}

type Academy = {
  foundations: { title: string; body: string }[]
  suites: Record<string, { label: string; blurb: string; agents: AgentLesson[] }>
  totals: { agents: number; skills: number; executable_actions: number; policy_rules: number }
}

const KIND_TONE: Record<string, string> = {
  attachment: 'accent',
  data: 'slate',
  artifact: 'mint',
  record: 'violet',
  proposal: 'amber',
}

const KIND_ICON: Record<string, string> = {
  attachment: '📎',
  data: '⛁',
  artifact: '⬇',
  record: '▤',
  proposal: '⧉',
}

export default function Academy() {
  const { data, loading } = useApi<Academy>('/academy')
  const [selected, setSelected] = useState<string | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const suiteList = useMemo(() => (data ? Object.entries(data.suites) : []), [data])
  const allAgents = useMemo(
    () => suiteList.flatMap(([, s]) => s.agents),
    [suiteList],
  )
  const current = allAgents.find((a) => a.key === selected) ?? allAgents[0] ?? null

  if (loading) return <Spinner label="Opening the academy…" />
  if (!data || !current) return <Empty title="No curriculum available" />

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="panel border-violet/25 bg-gradient-to-r from-violet/[0.07] to-accent/[0.05] px-4 py-3.5">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <div className="min-w-[280px] flex-1">
            <p className="text-[13px] font-semibold text-slate-100">Agents Academy</p>
            <p className="subtle mt-0.5">
              How every agent works, what it consumes, what it hands back, and who has to approve
              the result. Read from each agent's own declarations — a lesson cannot describe
              behaviour the agent does not have.
            </p>
          </div>
          <Metric label="Agents" value={data.totals.agents} />
          <Metric label="Skills" value={data.totals.skills} tone="text-violet" />
          <Metric label="Executable actions" value={data.totals.executable_actions} tone="text-mint" />
          <Metric label="Policy rules" value={data.totals.policy_rules} tone="text-amber" />
        </div>
      </div>

      {/* Foundations — true for all sixteen */}
      <Panel
        title="Foundations"
        subtitle="Six things that are true of every agent on the platform, before you look at any one of them."
        bodyClass="p-3"
      >
        <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
          {data.foundations.map((f, i) => (
            <div key={f.title} className="rounded-xl border border-ink-700 bg-ink-850/40 p-3.5">
              <p className="flex items-center gap-2 text-[12.5px] font-semibold text-slate-100">
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-violet/15 text-[10px] font-bold text-violet">
                  {i + 1}
                </span>
                {f.title}
              </p>
              <p className="subtle mt-1.5 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[236px_minmax(0,1fr)]">
        {/* Curriculum index */}
        <nav className="space-y-3 lg:sticky lg:top-4 lg:self-start">
          {suiteList.map(([key, suite]) => (
            <div key={key} className="panel p-2">
              <p className="px-1.5 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                {suite.label}
              </p>
              {suite.agents.map((agent) => (
                <button
                  key={agent.key}
                  onClick={() => {
                    setSelected(agent.key)
                    setShowPrompt(false)
                  }}
                  className={`mb-0.5 block w-full rounded-lg px-2.5 py-2 text-left text-[12px] transition-colors ${
                    agent.key === current.key
                      ? 'bg-violet/12 font-semibold text-violet ring-1 ring-inset ring-violet/25'
                      : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
                  }`}
                >
                  {agent.name.replace(/ Agent$/, '')}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Lesson */}
        <div className="min-w-0 space-y-4">
          <Panel
            title={current.name}
            subtitle={current.role}
            actions={
              <>
                {current.accepts_attachments && <Chip tone="accent">📎 takes attachments</Chip>}
                {current.produces_artifacts && <Chip tone="mint">⬇ produces files</Chip>}
                <Chip tone="amber">{current.governance.autonomy_label}</Chip>
              </>
            }
          >
            <p className="text-[12.5px] leading-relaxed text-slate-300">{current.mission}</p>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <SectionLabel>What it is trying to achieve</SectionLabel>
                <ul className="space-y-1.5">
                  {current.goals.map((g) => (
                    <li key={g} className="flex gap-2 text-[12px] text-slate-300">
                      <span className="text-mint">▸</span>
                      <span>{g}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <SectionLabel>What it can reach</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {current.tools.map((t) => (
                    <span
                      key={t}
                      className="rounded-md border border-ink-700 bg-ink-900/70 px-2 py-1 text-[11px] text-slate-400"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </Panel>

          {/* The question the screen exists to answer */}
          <Panel
            title="Input and output"
            subtitle="What you give it, and what you get back."
            bodyClass="grid gap-px bg-ink-800 md:grid-cols-2"
          >
            <IOColumn heading="Input" icon="→" specs={current.inputs} />
            <IOColumn heading="Output" icon="←" specs={current.outputs} />
          </Panel>

          {/* How it works */}
          <Panel title="How it works" subtitle={`${current.lifecycle.length} steps, in order, every run.`}>
            <ol className="space-y-0">
              {current.lifecycle.map((step, i) => (
                <li key={step.step} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent/15 text-[10.5px] font-bold text-accent-soft">
                      {step.step}
                    </span>
                    {i < current.lifecycle.length - 1 && <span className="w-px flex-1 bg-ink-700" />}
                  </div>
                  <div className={i < current.lifecycle.length - 1 ? 'pb-4' : ''}>
                    <p className="text-[12.5px] font-medium text-slate-100">{step.action}</p>
                    <p className="subtle mt-0.5">{step.rationale}</p>
                    <span className="mono mt-1 inline-block rounded border border-ink-700 bg-ink-900/70 px-1.5 py-px text-slate-500">
                      {step.tool}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>

          {/* Worked example */}
          {current.worked_example && (
            <Panel
              title="Worked example"
              subtitle={current.worked_example.scenario}
              className="border-mint/25"
            >
              <div className="space-y-3">
                <ExampleRow label="Given" tone="text-accent-soft">
                  {current.worked_example.given}
                </ExampleRow>
                <div>
                  <SectionLabel>It does</SectionLabel>
                  <ol className="space-y-1.5">
                    {current.worked_example.steps.map((s, i) => (
                      <li key={s} className="flex gap-2 text-[12px] text-slate-300">
                        <span className="tabular-nums text-slate-600">{i + 1}.</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ol>
                </div>
                <ExampleRow label="Produces" tone="text-mint">
                  {current.worked_example.produces}
                </ExampleRow>
                <ExampleRow label="Decided by" tone="text-amber">
                  {current.worked_example.decided_by}
                </ExampleRow>
              </div>
            </Panel>
          )}

          {/* Actions and authority */}
          <Panel
            title="What it may propose"
            subtitle="Every one of these is a proposal. None of them is applied until a qualified human approves it."
            bodyClass="p-0"
          >
            {current.actions.length === 0 ? (
              <Empty title="Proposes nothing" hint="This agent only reports; it never asks for a change." />
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-ink-800">
                    <th className="th">Action</th>
                    <th className="th">Reversible</th>
                    <th className="th">Minimum approver</th>
                  </tr>
                </thead>
                <tbody>
                  {current.actions.map((a) => (
                    <tr key={a.action} className="table-row">
                      <td className="td">
                        <span className="text-slate-100">{a.label}</span>
                        <span className="mono ml-2 text-slate-500">{a.action}</span>
                      </td>
                      <td className="td">
                        {a.reversible ? (
                          <Chip tone="mint">reversible</Chip>
                        ) : (
                          <Chip tone="rose">⚠ irreversible</Chip>
                        )}
                      </td>
                      <td className="td text-slate-300">{a.min_role_label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          {/* Governance */}
          <Panel title="Governance" subtitle="The envelope this agent runs inside.">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Autonomy" value={current.governance.autonomy_label} />
              <Fact
                label="Confidence floor"
                value={pct(current.governance.confidence_threshold * 100, 0)}
                hint="Below this it must escalate."
              />
              <Fact
                label="Auto-execute ceiling"
                value={
                  current.governance.max_auto_amount_usd > 0
                    ? money(current.governance.max_auto_amount_usd)
                    : 'None'
                }
                hint={
                  current.governance.max_auto_amount_usd > 0
                    ? 'Only if HITL enforcement is off.'
                    : 'Nothing executes without a human.'
                }
              />
              <Fact label="Escalates to" value={current.governance.escalation_role_label} />
            </div>
          </Panel>

          {/* Skills */}
          {current.skills.length > 0 && (
            <Panel
              title="Skills"
              subtitle={`${current.skills.length} declared capabilities, each with its own inputs and outputs.`}
              bodyClass="p-3"
            >
              <div className="space-y-2.5">
                {current.skills.map((skill) => (
                  <div key={skill.name} className="rounded-xl border border-ink-700 bg-ink-850/40 p-3.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[12.5px] font-semibold text-slate-100">{skill.title}</span>
                      <span className="mono text-slate-500">{skill.name}</span>
                    </div>
                    <p className="subtle mt-1">{skill.purpose}</p>
                    <div className="mt-2.5 grid gap-3 md:grid-cols-2">
                      <TokenList label="Takes" tone="text-accent-soft" items={skill.inputs} />
                      <TokenList label="Returns" tone="text-mint" items={skill.output} />
                    </div>
                    {skill.guardrails && skill.guardrails.length > 0 && (
                      <div className="mt-2.5">
                        <SectionLabel>Guardrails</SectionLabel>
                        <ul className="space-y-1">
                          {skill.guardrails.map((g) => (
                            <li key={g} className="flex gap-2 text-[11.5px] text-slate-400">
                              <span className="text-amber">⚠</span>
                              <span>{g}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {/* The brief the agent runs against */}
          <Panel
            title="Operating brief"
            subtitle="The exact instructions this agent works from."
            actions={
              <button className="btn-ghost" onClick={() => setShowPrompt((v) => !v)}>
                {showPrompt ? 'Hide' : 'Show'}
              </button>
            }
          >
            {showPrompt ? (
              <pre className="scroll-thin max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/70 p-3.5 font-mono text-[11.5px] leading-relaxed text-slate-300">
                {current.prompt}
              </pre>
            ) : (
              <p className="subtle">
                {current.prompt.split('\n')[0]} — {current.prompt.length.toLocaleString()} characters.
              </p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}

function IOColumn({ heading, icon, specs }: { heading: string; icon: string; specs: IOSpec[] }) {
  return (
    <div className="bg-ink-900 p-3.5">
      <p className="mb-2.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
        <span className="text-slate-600">{icon}</span>
        {heading}
      </p>
      <div className="space-y-2.5">
        {specs.map((spec) => (
          <div key={spec.name}>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px]">{KIND_ICON[spec.kind]}</span>
              <span className="text-[12px] font-medium text-slate-100">{spec.name}</span>
              <Chip tone={KIND_TONE[spec.kind] ?? 'slate'}>{spec.kind}</Chip>
              {spec.required && <Chip tone="rose">required</Chip>}
              {spec.formats.map((f) => (
                <span key={f} className="mono rounded border border-ink-700 px-1 py-px text-slate-500">
                  .{f}
                </span>
              ))}
            </div>
            <p className="subtle mt-0.5">{spec.description}</p>
            {spec.example && (
              <p className="mono mt-0.5 truncate text-slate-500" title={spec.example}>
                {spec.example}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function TokenList({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <div className="flex flex-wrap gap-1">
        {items.map((i) => (
          <span
            key={i}
            className={`mono rounded border border-ink-700 bg-ink-900/70 px-1.5 py-px ${tone}`}
          >
            {i}
          </span>
        ))}
      </div>
    </div>
  )
}

function ExampleRow({ label, children, tone }: {
  label: string; children: React.ReactNode; tone: string
}) {
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <p className={`text-[12px] ${tone}`}>{children}</p>
    </div>
  )
}

function Fact({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-0.5 text-[13px] font-semibold text-slate-100">{value}</p>
      {hint && <p className="subtle mt-0.5">{hint}</p>}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
      {children}
    </p>
  )
}

function Metric({ label, value, tone = 'text-slate-100' }: {
  label: string; value: React.ReactNode; tone?: string
}) {
  return (
    <div className="shrink-0">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}
