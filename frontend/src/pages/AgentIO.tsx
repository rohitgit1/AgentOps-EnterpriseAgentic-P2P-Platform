/**
 * Agent I/O Catalogue — what goes into each agent, and what comes out.
 *
 * The single screen that answers "what is the input and output for each agent",
 * across both suites, with the artifacts each has actually produced.
 */
import { useMemo, useState } from 'react'
import { Chip, Drawer, Empty, Panel, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { bytes, dateTime, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

type IOSpec = {
  name: string
  description: string
  kind: 'attachment' | 'data' | 'artifact' | 'record' | 'proposal'
  formats: string[]
  required: boolean
  example?: string | null
}

type AgentIO = {
  key: string
  name: string
  suite: string
  role: string
  mission: string
  skills: string[]
  inputs: IOSpec[]
  outputs: IOSpec[]
  accepts_attachments: boolean
  produces_artifacts: boolean
  artifacts_produced: number
  recent_artifacts: ArtifactRow[]
}

type ArtifactRow = {
  id: string
  reference: string
  title: string
  filename: string
  content_type: string
  size_bytes: number
  status: string
  summary?: string
  created_at?: string
  download_url: string
}

type Catalog = {
  suites: Record<string, { label: string; blurb: string; agents: AgentIO[] }>
  totals: {
    agents: number
    with_attachments: number
    producing_artifacts: number
    artifacts_produced: number
  }
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

export default function AgentIO() {
  const { notify } = useSession()
  const { data, loading } = useApi<Catalog>('/agent-io')
  const [suite, setSuite] = useState<string>('all')
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ title: string; content: string } | null>(null)

  const agents = useMemo(() => {
    if (!data) return []
    return Object.entries(data.suites)
      .filter(([key]) => suite === 'all' || key === suite)
      .flatMap(([, s]) => s.agents)
  }, [data, suite])

  const selected = agents.find((a) => a.key === openKey) ?? null

  async function showArtifact(a: ArtifactRow) {
    try {
      const full = await api.get<{ content: string }>(`/artifacts/${a.id}`)
      setPreview({ title: `${a.title} · ${a.filename}`, content: full.content })
    } catch (e) {
      notify((e as Error).message, 'rose')
    }
  }

  if (loading) return <Spinner label="Loading the agent I/O catalogue…" />
  if (!data) return <Empty title="No catalogue available" />

  return (
    <div className="space-y-4">
      {/* Explainer */}
      <div className="panel border-accent/25 bg-gradient-to-r from-accent/[0.07] to-violet/[0.05] px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-slate-100">Agent I/O contract</p>
            <p className="subtle mt-0.5">
              What each agent consumes and what it hands back. Attachments go in; deliverables come
              out as <span className="text-amber">drafts</span> and become{' '}
              <span className="text-mint">released</span> only when a human approves the checkpoint
              that owns them.
            </p>
          </div>
          <Metric label="Agents" value={data.totals.agents} />
          <Metric label="Accept attachments" value={data.totals.with_attachments} tone="text-accent-soft" />
          <Metric label="Produce files" value={data.totals.producing_artifacts} tone="text-mint" />
          <Metric label="Artifacts produced" value={data.totals.artifacts_produced} />
        </div>
      </div>

      {/* Suite filter */}
      <div className="flex flex-wrap gap-1.5">
        {[['all', 'All suites'], ...Object.entries(data.suites).map(([k, v]) => [k, v.label])].map(
          ([key, label]) => (
            <button
              key={key}
              onClick={() => setSuite(key as string)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                suite === key
                  ? 'bg-accent/15 text-accent-soft ring-1 ring-inset ring-accent/30'
                  : 'border border-ink-700 bg-ink-850/50 text-slate-400 hover:text-slate-200'
              }`}
            >
              {label as string}
              {key !== 'all' && (
                <span className="ml-1.5 text-slate-500">
                  {data.suites[key as string].agents.length}
                </span>
              )}
            </button>
          ),
        )}
      </div>

      {Object.entries(data.suites)
        .filter(([key]) => suite === 'all' || key === suite)
        .map(([key, s]) => (
          <Panel key={key} title={s.label} subtitle={s.blurb} bodyClass="p-3">
            <div className="space-y-2.5">
              {s.agents.map((agent) => (
                <div key={agent.key} className="rounded-xl border border-ink-700 bg-ink-850/40">
                  <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 px-3.5 py-2.5">
                    <span className="text-[13px] font-semibold text-slate-100">{agent.name}</span>
                    {agent.accepts_attachments && <Chip tone="accent">📎 takes attachments</Chip>}
                    {agent.produces_artifacts && <Chip tone="mint">⬇ produces files</Chip>}
                    {agent.artifacts_produced > 0 && (
                      <Chip tone="slate">{agent.artifacts_produced} produced</Chip>
                    )}
                    <button
                      className="btn-ghost ml-auto"
                      onClick={() => setOpenKey(agent.key)}
                    >
                      Detail & samples
                    </button>
                  </div>

                  <div className="grid gap-px bg-ink-800 md:grid-cols-2">
                    <IOColumn heading="Input" icon="→" specs={agent.inputs} />
                    <IOColumn heading="Output" icon="←" specs={agent.outputs} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        ))}

      {/* Agent detail */}
      <Drawer
        open={Boolean(selected)}
        onClose={() => setOpenKey(null)}
        width="max-w-3xl"
        title={selected?.name ?? ''}
        subtitle={
          selected && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone="violet">{titleCase(selected.suite)}</Chip>
              {selected.accepts_attachments && <Chip tone="accent">accepts attachments</Chip>}
              {selected.produces_artifacts && <Chip tone="mint">produces files</Chip>}
            </div>
          )
        }
      >
        {selected && (
          <div className="space-y-4">
            <p className="text-[13px] leading-relaxed text-slate-300">{selected.mission}</p>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-accent-soft">
                → Inputs
              </p>
              <div className="space-y-1.5">
                {selected.inputs.map((spec) => (
                  <SpecCard key={spec.name} spec={spec} />
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-mint">
                ← Outputs
              </p>
              <div className="space-y-1.5">
                {selected.outputs.map((spec) => (
                  <SpecCard key={spec.name} spec={spec} />
                ))}
              </div>
            </div>

            {selected.recent_artifacts.length > 0 && (
              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Files this agent has actually produced
                </p>
                <div className="space-y-1.5">
                  {selected.recent_artifacts.map((a) => (
                    <div
                      key={a.id}
                      className="flex items-center gap-2.5 rounded-lg border border-ink-700 bg-ink-850/50 p-2.5"
                    >
                      <span className="text-[14px]">📄</span>
                      <div className="min-w-0 flex-1">
                        <p className="mono truncate text-slate-200">{a.filename}</p>
                        <p className="subtle truncate">{a.summary}</p>
                      </div>
                      <Chip tone={a.status === 'released' ? 'mint' : 'amber'}>{a.status}</Chip>
                      <span className="shrink-0 text-[11px] text-slate-500">{bytes(a.size_bytes)}</span>
                      <button className="btn-ghost" onClick={() => showArtifact(a)}>View</button>
                      <a className="btn-ghost" href={a.download_url} download>↓</a>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Skills composed
              </p>
              <div className="flex flex-wrap gap-1">
                {selected.skills.map((s) => (
                  <Chip key={s} tone="slate">{s}</Chip>
                ))}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      {/* Artifact preview */}
      <Drawer
        open={Boolean(preview)}
        onClose={() => setPreview(null)}
        width="max-w-4xl"
        title={preview?.title ?? ''}
      >
        <pre className="mono whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/70 p-4 text-[11.5px] leading-relaxed text-slate-300">
          {preview?.content}
        </pre>
      </Drawer>
    </div>
  )
}

function IOColumn({ heading, icon, specs }: { heading: string; icon: string; specs: IOSpec[] }) {
  return (
    <div className="bg-ink-900/60 p-3.5">
      <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
        <span className={heading === 'Input' ? 'text-accent-soft' : 'text-mint'}>{icon}</span> {heading}
      </p>
      <div className="space-y-1.5">
        {specs.map((spec) => (
          <div key={spec.name} className="flex items-start gap-2">
            <span className="mt-0.5 text-[11px]">{KIND_ICON[spec.kind]}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[12px] font-medium text-slate-200">{spec.name}</span>
                <Chip tone={KIND_TONE[spec.kind]}>{spec.kind}</Chip>
                {spec.formats.map((f) => (
                  <span key={f} className="mono text-[10px] text-slate-500">.{f}</span>
                ))}
                {spec.required && <Chip tone="rose">required</Chip>}
              </div>
              <p className="mt-0.5 text-[11.5px] leading-snug text-slate-400">{spec.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SpecCard({ spec }: { spec: IOSpec }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850/50 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12.5px]">{KIND_ICON[spec.kind]}</span>
        <span className="text-[12.5px] font-medium text-slate-200">{spec.name}</span>
        <Chip tone={KIND_TONE[spec.kind]}>{spec.kind}</Chip>
        {spec.formats.map((f) => (
          <span key={f} className="mono text-[10px] text-slate-500">.{f}</span>
        ))}
        {spec.required && <Chip tone="rose">required</Chip>}
      </div>
      <p className="mt-1 text-[12px] leading-snug text-slate-400">{spec.description}</p>
      {spec.example && (
        <pre className="mono mt-1.5 overflow-x-auto rounded border border-ink-800 bg-ink-950/60 px-2 py-1 text-[10.5px] text-slate-500">
          {spec.example}
        </pre>
      )}
    </div>
  )
}

function Metric({ label, value, tone = 'text-slate-100' }: {
  label: string; value: number; tone?: string
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}
