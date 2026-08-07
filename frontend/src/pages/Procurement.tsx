/**
 * Procurement AgentOps surfaces: command centre, sourcing, spend & savings,
 * strategic supplier risk, contracts, tail spend, and the artifact library.
 */
import { ChangeEvent, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, Cell, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import TaskDrawer from '../components/TaskDrawer'
import { Chip, Confidence, Drawer, Empty, KeyValue, Panel, RiskChip, Spinner } from '../components/ui'
import { AXIS, ChartTooltip, GRID, Meter, SEQUENTIAL, STATUS } from '../lib/chart'
import { api } from '../lib/api'
import { bytes, dateOnly, dateTime, money, num, pct, relative, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

/* ==================================================================== */
/* Shared: run an agent with attachments                                 */
/* ==================================================================== */
type ArtifactRow = {
  id: string; reference: string; title: string; filename: string; content_type: string
  size_bytes: number; status: string; summary?: string; direction: string
  agent_key?: string; uploaded_by?: string; released_by?: string; created_at?: string
  download_url: string; row_count?: number | null; kind: string
}

export function RunAgentPanel({
  agentKey, label, hint, extraContext,
}: { agentKey: string; label: string; hint: string; extraContext?: Record<string, unknown> }) {
  const { notify, refresh } = useSession()
  const { data: library } = useApi<{ items: ArtifactRow[] }>('/artifacts?direction=input&limit=60')
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ artifacts: ArtifactRow[]; conclusion: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    setBusy(true)
    try {
      const res = await fetch('/api/artifacts/upload', {
        method: 'POST',
        headers: { 'X-User-Id': localStorage.getItem('p2p.token') ?? '' },
        body: form,
      })
      if (!res.ok) throw new Error((await res.json()).detail ?? 'Upload failed')
      const artifact = (await res.json()) as ArtifactRow
      setPicked((p) => [...p, artifact.id])
      notify(`${artifact.filename} uploaded — ${artifact.summary}`, 'mint')
      refresh()
    } catch (err) {
      notify((err as Error).message, 'rose')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function run() {
    setBusy(true)
    setResult(null)
    try {
      const res = await api.post<{
        execution: { conclusion: string }; artifacts: ArtifactRow[]; checkpoints: unknown[]
      }>(`/agents/${agentKey}/run`, { attachment_ids: picked, ...(extraContext ?? {}) })
      setResult({ artifacts: res.artifacts ?? [], conclusion: res.execution.conclusion })
      notify(
        `${label}: ${res.artifacts?.length ?? 0} file(s) produced, ${res.checkpoints.length} decision(s) queued.`,
        'accent',
      )
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title={`Run ${label}`} subtitle={hint}>
      <div className="space-y-3">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-accent-soft">
            → Input attachments
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(library?.items ?? []).map((a) => {
              const on = picked.includes(a.id)
              return (
                <button
                  key={a.id}
                  onClick={() => setPicked((p) => (on ? p.filter((x) => x !== a.id) : [...p, a.id]))}
                  className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11.5px] transition-colors ${
                    on
                      ? 'border-accent/50 bg-accent/12 text-accent-soft'
                      : 'border-ink-700 bg-ink-850/50 text-slate-400 hover:text-slate-200'
                  }`}
                  title={a.summary}
                >
                  <span>{on ? '✓' : '📎'}</span>
                  <span className="mono">{a.filename}</span>
                  <span className="text-slate-600">{bytes(a.size_bytes)}</span>
                </button>
              )
            })}
            <label className="cursor-pointer rounded-lg border border-dashed border-ink-600 px-2 py-1 text-[11.5px] text-slate-400 hover:border-accent/50 hover:text-accent-soft">
              + Upload file
              <input ref={fileRef} type="file" className="hidden" onChange={upload}
                     accept=".csv,.json,.md,.txt,.tsv,.pdf" />
            </label>
          </div>
          <p className="subtle mt-1.5">
            CSV, JSON, Markdown and text are parsed. A PDF contributes only its embedded text layer —
            no OCR engine is bundled.
          </p>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-ink-800 pt-3">
          <p className="subtle">
            {picked.length} attachment(s) selected. Output files are produced as drafts and released
            only when a human approves the checkpoint.
          </p>
          <button className="btn-primary shrink-0" onClick={run} disabled={busy}>
            {busy ? 'Running…' : `▶ Run ${label}`}
          </button>
        </div>

        {result && (
          <div className="rounded-lg border border-mint/25 bg-mint/[0.05] p-3">
            <p className="text-[12.5px] text-slate-200">{result.conclusion}</p>
            {result.artifacts.length > 0 && (
              <>
                <p className="mt-2.5 mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-mint">
                  ← Output files produced
                </p>
                <div className="space-y-1">
                  {result.artifacts.map((a) => (
                    <ArtifactRowView key={a.id} artifact={a} />
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}

function ArtifactRowView({ artifact }: { artifact: ArtifactRow }) {
  const { notify } = useSession()
  const [content, setContent] = useState<string | null>(null)

  async function view() {
    try {
      const full = await api.get<{ content: string }>(`/artifacts/${artifact.id}`)
      setContent(full.content)
    } catch (e) {
      notify((e as Error).message, 'rose')
    }
  }

  return (
    <>
      <div className="flex items-center gap-2.5 rounded-lg border border-ink-700 bg-ink-900/60 p-2">
        <span>📄</span>
        <div className="min-w-0 flex-1">
          <p className="mono truncate text-slate-200">{artifact.filename}</p>
          <p className="subtle truncate">{artifact.summary}</p>
        </div>
        <Chip tone={artifact.status === 'released' ? 'mint' : 'amber'}>{artifact.status}</Chip>
        <span className="shrink-0 text-[11px] text-slate-500">{bytes(artifact.size_bytes)}</span>
        <button className="btn-ghost" onClick={view}>View</button>
        <a className="btn-ghost" href={artifact.download_url} download>↓</a>
      </div>
      <Drawer open={Boolean(content)} onClose={() => setContent(null)} width="max-w-4xl"
              title={`${artifact.title} · ${artifact.filename}`}>
        <pre className="mono whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/70 p-4 text-[11.5px] leading-relaxed text-slate-300">
          {content}
        </pre>
      </Drawer>
    </>
  )
}

/* ==================================================================== */
/* Procurement Command Center                                            */
/* ==================================================================== */
export function ProcurementCommandCenter() {
  const { data, loading } = useApi<any>('/procurement/dashboard')
  if (loading) return <Spinner label="Rolling up the procurement portfolio…" />
  if (!data) return <Empty title="No procurement data" />

  const h = data.headline
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Tile label="Savings pipeline" value={money(h.savings_pipeline_usd)}
              sub={`${money(h.savings_approved_usd)} approved`} tone="text-mint" />
        <Tile label="Sourcing events" value={num(h.sourcing_events, 0)}
              sub={`${h.in_market} in market · ${h.awarded} awarded`} />
        <Tile label="Suppliers at risk" value={num(h.suppliers_elevated, 0)}
              sub={`of ${h.suppliers_assessed} assessed`}
              tone={h.suppliers_elevated ? 'text-rose' : 'text-slate-100'} />
        <Tile label="Tail spend" value={money(h.tail_spend_usd)}
              sub={`${h.tail_findings} finding(s)`} tone="text-amber" />
      </div>

      <Panel title="Executive KPIs" subtitle="Against the specification's procurement targets">
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
          {data.kpis.map((k: any) => (
            <div key={k.key}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-[11.5px] text-slate-400">{k.label}</p>
                <p className={`text-xl font-semibold tabular-nums ${k.meets_target ? 'text-mint' : 'text-slate-100'}`}>
                  {k.value}{k.unit}
                </p>
              </div>
              <Meter value={k.value} target={k.target} direction={k.direction} />
              <p className="subtle mt-1.5">
                target {k.direction === 'down' ? '<' : ''}{k.target}{k.unit}
                {k.meets_target ? ' · on target' : ` · gap ${Math.abs(k.value - k.target).toFixed(1)}${k.unit}`}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Panel title="Supplier risk heatmap" subtitle="Four domains per supplier — darker is riskier">
          {data.risk_heatmap.length === 0 ? (
            <Empty title="No assessments yet"
                   hint="Run the Supplier Risk & Compliance Agent to populate this." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px]">
                <thead>
                  <tr>
                    <th className="th">Supplier</th>
                    <th className="th text-center">Financial</th>
                    <th className="th text-center">Operational</th>
                    <th className="th text-center">Compliance</th>
                    <th className="th text-center">ESG</th>
                    <th className="th text-center">Overall</th>
                  </tr>
                </thead>
                <tbody>
                  {data.risk_heatmap.map((r: any) => (
                    <tr key={r.supplier} className="table-row">
                      <td className="td text-slate-300">{r.supplier}</td>
                      {['financial', 'operational', 'compliance', 'esg', 'overall'].map((d) => (
                        <td key={d} className="td text-center">
                          <span
                            className="inline-block w-12 rounded px-1 py-0.5 text-[11px] font-semibold tabular-nums"
                            style={{
                              background: heat(r[d]),
                              color: r[d] >= 45 ? '#fff' : '#cbd5e1',
                            }}
                          >
                            {Math.round(r[d])}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Savings by lever" subtitle="Where the identified value comes from">
          {data.savings_by_lever.length === 0 ? (
            <Empty title="No savings identified yet"
                   hint="Run the Spend Analytics Agent against a spend extract." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.savings_by_lever} layout="vertical"
                        margin={{ top: 4, right: 24, left: 8, bottom: 4 }} barCategoryGap="26%">
                <CartesianGrid {...GRID} horizontal={false} vertical />
                <XAxis type="number" {...AXIS} axisLine={false} tickLine={false}
                       tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
                <YAxis type="category" dataKey="lever" width={140} {...AXIS}
                       axisLine={false} tickLine={false}
                       tickFormatter={(v: string) => titleCase(v)} />
                <Tooltip cursor={{ fill: '#161f3d55' }}
                         content={({ active, payload, label }) => (
                           <ChartTooltip active={active} label={titleCase(label as string)}
                                         rows={[{ name: 'Savings', value: money(payload?.[0]?.value as number), color: SEQUENTIAL[2] }]} />
                         )} />
                <Bar dataKey="value" barSize={18} radius={[0, 4, 4, 0]} fill={SEQUENTIAL[2]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </div>

      <RunAgentPanel agentKey="procurement_command_center" label="Command Center Agent"
                     hint="Rolls the portfolio into the six executive KPIs and drafts the brief for CFO release." />
    </div>
  )
}

function heat(value: number) {
  if (value >= 65) return 'rgba(224,73,94,0.85)'
  if (value >= 45) return 'rgba(224,73,94,0.55)'
  if (value >= 25) return 'rgba(192,127,34,0.5)'
  return 'rgba(34,160,116,0.35)'
}

/* ==================================================================== */
/* Sourcing                                                              */
/* ==================================================================== */
export function Sourcing() {
  const { data, loading } = useApi<any>('/sourcing-events')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [task, setTask] = useState<string | null>(null)

  const sourcingTasks = (pending?.items ?? []).filter((t) =>
    ['issue_rfp', 'award_sourcing_event'].includes(t.action_kind))

  async function open(id: string) {
    setOpenId(id)
    setDetail(null)
    setDetail(await api.get(`/sourcing-events/${id}`))
  }

  return (
    <div className="space-y-4">
      <RunAgentPanel agentKey="sourcing_rfp" label="Sourcing Event Agent"
                     hint="Attach a requirements brief to draft an RFP, or a bid CSV to score responses and recommend an award." />

      {sourcingTasks.length > 0 && (
        <Panel bodyClass="" title="Sourcing decisions awaiting a human"
               subtitle="Issuing and awarding both reach outside the company">
          <div className="divide-y divide-ink-800">
            {sourcingTasks.map((t) => (
              <button key={t.id} onClick={() => setTask(t.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                    <RiskChip level={t.risk_level} />
                    {!t.reversible && <Chip tone="rose">irreversible</Chip>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
                </div>
                <Chip tone="slate">{t.required_role_label}</Chip>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel bodyClass="" title="Sourcing events"
             subtitle={`${data?.count ?? 0} event(s) · ${money(data?.expected_savings_usd)} expected savings`}>
        {loading && <Spinner />}
        {!loading && !data?.items?.length && <Empty title="No sourcing events yet" />}
        {!loading && !!data?.items?.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Event</th><th className="th">Category</th>
                  <th className="th text-right">Budget</th><th className="th">Status</th>
                  <th className="th text-right">Bids</th><th className="th">Awarded to</th>
                  <th className="th text-right">Savings</th><th className="th">Cycle</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e: any) => (
                  <tr key={e.id} className="table-row cursor-pointer" onClick={() => open(e.id)}>
                    <td className="td">
                      <span className="mono text-slate-400">{e.event_number}</span>
                      <span className="ml-2 font-medium text-slate-100">{e.title}</span>
                    </td>
                    <td className="td text-slate-400">{e.category}</td>
                    <td className="td text-right tabular-nums">{money(e.budget_usd)}</td>
                    <td className="td">
                      <Chip tone={e.status === 'awarded' ? 'mint' : e.status === 'issued' ? 'accent' : 'slate'}>
                        {titleCase(e.status)}
                      </Chip>
                    </td>
                    <td className="td text-right tabular-nums">{e.bid_count}</td>
                    <td className="td text-slate-300">{e.awarded_supplier ?? '—'}</td>
                    <td className="td text-right tabular-nums text-mint">
                      {e.expected_savings_usd ? money(e.expected_savings_usd) : '—'}
                    </td>
                    <td className="td text-slate-400">
                      {e.cycle_days ? `${e.cycle_days}d (−${e.cycle_reduction_pct}%)` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Drawer open={Boolean(openId)} onClose={() => { setOpenId(null); setDetail(null) }}
              width="max-w-3xl" title={detail?.title ?? 'Sourcing event'}
              subtitle={detail && <Chip tone="accent">{detail.event_number}</Chip>}>
        {!detail && <Spinner />}
        {detail && (
          <div className="space-y-4">
            <div className="panel p-4">
              <KeyValue items={[
                ['Category', detail.category], ['Type', detail.event_type],
                ['Budget', money(detail.budget_usd)], ['Status', titleCase(detail.status)],
                ['Issued', dateTime(detail.issued_at)], ['Responses due', dateOnly(detail.response_due)],
                ['Awarded to', detail.awarded_supplier ?? '—'],
                ['Expected savings', money(detail.expected_savings_usd)],
              ]} />
            </div>

            {detail.bids?.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Bids
                </p>
                <div className="overflow-hidden rounded-lg border border-ink-700">
                  <table className="w-full">
                    <thead className="bg-ink-850/70">
                      <tr><th className="th">Supplier</th><th className="th text-right">Bid</th>
                        <th className="th text-right">Lead</th><th className="th text-right">Technical</th>
                        <th className="th text-right">Total</th><th className="th">Status</th></tr>
                    </thead>
                    <tbody>
                      {detail.bids.map((b: any) => (
                        <tr key={b.id} className="table-row last:border-0">
                          <td className="td text-slate-200">{b.supplier_name}</td>
                          <td className="td text-right tabular-nums">{money(b.bid_amount_usd)}</td>
                          <td className="td text-right tabular-nums text-slate-400">{b.lead_time_days}d</td>
                          <td className="td text-right tabular-nums">{b.technical_score}</td>
                          <td className="td text-right font-medium tabular-nums">
                            {b.total_score ? b.total_score.toFixed(1) : '—'}
                          </td>
                          <td className="td">
                            <Chip tone={b.status === 'awarded' ? 'mint' : 'slate'}>{titleCase(b.status)}</Chip>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {detail.artifacts?.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Files produced for this event
                </p>
                <div className="space-y-1">
                  {detail.artifacts.map((a: ArtifactRow) => (
                    <ArtifactRowView key={a.id} artifact={a} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Spend & savings                                                       */
/* ==================================================================== */
export function SpendAnalytics() {
  const { data: spend, loading } = useApi<any>('/spend')
  const { data: savings } = useApi<any>('/savings')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')
  const [task, setTask] = useState<string | null>(null)

  const spendTasks = (pending?.items ?? []).filter((t) =>
    ['publish_spend_classification', 'create_savings_opportunity'].includes(t.action_kind))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Tile label="Spend analysed" value={money(spend?.total_usd)} />
        <Tile label="Classified" value={pct(spend?.classified_pct, 1)} tone="text-mint" />
        <Tile label="Maverick spend" value={money(spend?.maverick_usd)} tone="text-amber" />
        <Tile label="Savings pipeline" value={money(savings?.pipeline_usd)} tone="text-mint"
              sub={`${money(savings?.approved_usd)} approved`} />
      </div>

      <RunAgentPanel agentKey="spend_analytics" label="Spend Analytics Agent"
                     hint="Attach a spend extract (CSV) to classify it, normalise suppliers, measure contract compliance and price the savings levers." />

      {spendTasks.length > 0 && (
        <Panel bodyClass="" title="Spend decisions awaiting a human">
          <div className="divide-y divide-ink-800">
            {spendTasks.map((t) => (
              <button key={t.id} onClick={() => setTask(t.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
                <div className="min-w-0 flex-1">
                  <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
                </div>
                <span className="shrink-0 tabular-nums text-slate-200">{money(t.financial_impact_usd)}</span>
                <Chip tone="slate">{t.required_role_label}</Chip>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Panel title="Spend by category" subtitle="After classification">
          {loading && <Spinner />}
          {!loading && (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={(spend?.by_category ?? []).slice(0, 10)} layout="vertical"
                        margin={{ top: 4, right: 28, left: 8, bottom: 4 }} barCategoryGap="24%">
                <CartesianGrid {...GRID} horizontal={false} vertical />
                <XAxis type="number" {...AXIS} axisLine={false} tickLine={false}
                       tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
                <YAxis type="category" dataKey="category" width={140} {...AXIS}
                       axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: '#161f3d55' }}
                         content={({ active, payload, label }) => (
                           <ChartTooltip active={active} label={label as string}
                                         rows={[{ name: 'Spend', value: money(payload?.[0]?.value as number), color: SEQUENTIAL[2] }]} />
                         )} />
                <Bar dataKey="spend_usd" barSize={16} radius={[0, 4, 4, 0]}>
                  {(spend?.by_category ?? []).slice(0, 10).map((c: any, i: number) => (
                    <Cell key={i} fill={c.category === 'Unclassified' ? STATUS.warning : SEQUENTIAL[2]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          <p className="subtle mt-1">Amber marks spend that is still unclassified.</p>
        </Panel>

        <Panel bodyClass="" title="Savings pipeline"
               subtitle={`${savings?.count ?? 0} opportunity(ies)`}>
          {!savings?.items?.length && <Empty title="No savings logged yet"
                                             hint="Run the Spend Analytics Agent, then approve its proposal." />}
          <div className="divide-y divide-ink-800">
            {(savings?.items ?? []).map((o: any) => (
              <div key={o.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="mono text-slate-500">{o.reference}</span>
                  <span className="text-[12.5px] font-medium text-slate-100">{o.title}</span>
                  <Chip tone="accent">{titleCase(o.lever)}</Chip>
                  <Chip tone={o.status === 'approved' ? 'mint' : 'slate'}>{titleCase(o.status)}</Chip>
                  <span className="ml-auto font-semibold tabular-nums text-mint">
                    {money(o.estimated_savings_usd)}
                  </span>
                </div>
                <p className="subtle mt-1">{o.rationale}</p>
                <div className="mt-1.5 flex items-center gap-3">
                  <Confidence value={o.confidence} />
                  <span className="text-[11px] text-slate-500">
                    on {money(o.annual_spend_usd)} addressable
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Strategic supplier risk                                               */
/* ==================================================================== */
export function StrategicRisk() {
  const { data, loading } = useApi<any>('/risk-assessments')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')
  const [task, setTask] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const riskTasks = (pending?.items ?? []).filter((t) => t.action_kind === 'set_supplier_disposition')
  const selected = (data?.items ?? []).find((a: any) => a.id === openId)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Tile label="Suppliers assessed" value={num(data?.count, 0)} />
        <Tile label="Portfolio average risk" value={num(data?.average_risk, 1)}
              sub="target below 20"
              tone={(data?.average_risk ?? 0) < 20 ? 'text-mint' : 'text-amber'} />
        <Tile label="At high or critical" value={num(data?.elevated, 0)}
              tone={data?.elevated ? 'text-rose' : 'text-slate-100'} />
      </div>

      <RunAgentPanel agentKey="supplier_risk_compliance" label="Supplier Risk & Compliance Agent"
                     hint="Attach a credit report and an OTIF performance file to score financial, operational, compliance and ESG risk." />

      {riskTasks.length > 0 && (
        <Panel bodyClass="" title="Disposition decisions awaiting a human">
          <div className="divide-y divide-ink-800">
            {riskTasks.map((t) => (
              <button key={t.id} onClick={() => setTask(t.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
                <div className="min-w-0 flex-1">
                  <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
                </div>
                <Chip tone="slate">{t.required_role_label}</Chip>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel bodyClass="" title="Risk scorecard" subtitle="Four domains per supplier">
        {loading && <Spinner />}
        {!loading && !data?.items?.length && (
          <Empty title="No assessments yet" hint="Run the agent above to build the scorecard." />
        )}
        {!loading && !!data?.items?.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Supplier</th><th className="th text-right">Financial</th>
                  <th className="th text-right">Operational</th><th className="th text-right">Compliance</th>
                  <th className="th text-right">ESG</th><th className="th text-right">Overall</th>
                  <th className="th">Band</th><th className="th">Recommended</th><th className="th">Applied</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a: any) => (
                  <tr key={a.id} className="table-row cursor-pointer" onClick={() => setOpenId(a.id)}>
                    <td className="td text-slate-200">{a.supplier_name}</td>
                    <td className="td text-right tabular-nums">{a.financial_risk}</td>
                    <td className="td text-right tabular-nums">{a.operational_risk}</td>
                    <td className="td text-right tabular-nums">{a.compliance_risk}</td>
                    <td className="td text-right tabular-nums">{a.esg_risk}</td>
                    <td className="td text-right font-semibold tabular-nums">{a.overall_risk}</td>
                    <td className="td"><RiskChip level={a.risk_band} /></td>
                    <td className="td"><Chip tone="accent">{titleCase(a.recommended_disposition)}</Chip></td>
                    <td className="td">
                      {a.applied_disposition
                        ? <Chip tone="mint">{titleCase(a.applied_disposition)}</Chip>
                        : <span className="subtle">pending</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Drawer open={Boolean(selected)} onClose={() => setOpenId(null)}
              title={selected?.supplier_name ?? ''}
              subtitle={selected && <RiskChip level={selected.risk_band} />}>
        {selected && (
          <div className="space-y-4">
            <div className="panel p-4">
              <KeyValue items={[
                ['Financial risk', String(selected.financial_risk)],
                ['Operational risk', String(selected.operational_risk)],
                ['Compliance risk', String(selected.compliance_risk)],
                ['ESG risk', String(selected.esg_risk)],
                ['Overall', String(selected.overall_risk)],
                ['Spend at risk', money(selected.spend_at_risk_usd)],
              ]} />
            </div>
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Findings
              </p>
              <div className="space-y-1.5">
                {(selected.findings ?? []).map((f: any, i: number) => (
                  <div key={i} className="rounded-lg border border-ink-700 bg-ink-850/50 p-2.5">
                    <div className="flex items-center gap-2">
                      <Chip tone="slate">{f.domain}</Chip>
                      <RiskChip level={f.severity} />
                    </div>
                    <p className="mt-1 text-[12.5px] text-slate-300">{f.detail}</p>
                  </div>
                ))}
                {!(selected.findings ?? []).length && <p className="subtle">No findings.</p>}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Contract lifecycle                                                    */
/* ==================================================================== */
export function ContractLifecycle() {
  const { data, loading } = useApi<any>('/contract-drafts')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')
  const [task, setTask] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [body, setBody] = useState<string | null>(null)

  const contractTasks = (pending?.items ?? []).filter((t) =>
    ['draft_contract', 'issue_contract_for_signature'].includes(t.action_kind))
  const selected = (data?.items ?? []).find((d: any) => d.id === openId)

  async function openDraft(id: string) {
    setOpenId(id)
    setBody(null)
    const res = await fetch(`/api/contract-drafts/${id}/body`, {
      headers: { 'X-User-Id': localStorage.getItem('p2p.token') ?? '' },
    })
    setBody(await res.text())
  }

  return (
    <div className="space-y-4">
      <RunAgentPanel agentKey="contract_lifecycle" label="Contract Lifecycle Agent"
                     hint="Attach a third-party contract to review it for missing and risky clauses, or run with no attachment to author a draft from the standard clause library." />

      {contractTasks.length > 0 && (
        <Panel bodyClass="" title="Contract decisions awaiting a human">
          <div className="divide-y divide-ink-800">
            {contractTasks.map((t) => (
              <button key={t.id} onClick={() => setTask(t.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                    {!t.reversible && <Chip tone="rose">irreversible</Chip>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
                </div>
                <span className="shrink-0 tabular-nums text-slate-200">{money(t.financial_impact_usd)}</span>
                <Chip tone="slate">{t.required_role_label}</Chip>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel bodyClass="" title="Contract drafts" subtitle={`${data?.count ?? 0} draft(s)`}>
        {loading && <Spinner />}
        {!loading && !data?.items?.length && <Empty title="No drafts yet" />}
        {!loading && !!data?.items?.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Reference</th><th className="th">Title</th><th className="th">Type</th>
                  <th className="th text-right">Value</th><th className="th text-right">Legal risk</th>
                  <th className="th text-right">Missing</th><th className="th text-right">Risky</th>
                  <th className="th">Renewal</th><th className="th">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((d: any) => (
                  <tr key={d.id} className="table-row cursor-pointer" onClick={() => openDraft(d.id)}>
                    <td className="td mono text-slate-400">{d.reference}</td>
                    <td className="td text-slate-200">{d.title}</td>
                    <td className="td"><Chip tone="slate">{d.contract_type}</Chip></td>
                    <td className="td text-right tabular-nums">{money(d.value_usd)}</td>
                    <td className="td text-right">
                      <span className={`font-semibold tabular-nums ${
                        d.legal_risk_score >= 60 ? 'text-rose'
                          : d.legal_risk_score >= 35 ? 'text-amber' : 'text-mint'}`}>
                        {d.legal_risk_score}
                      </span>
                    </td>
                    <td className="td text-right tabular-nums text-rose">{d.missing_clauses.length}</td>
                    <td className="td text-right tabular-nums text-amber">{d.clause_findings.length}</td>
                    <td className="td text-slate-400">{dateOnly(d.renewal_date)}</td>
                    <td className="td"><Chip tone="slate">{titleCase(d.status)}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Drawer open={Boolean(selected)} onClose={() => { setOpenId(null); setBody(null) }}
              width="max-w-4xl" title={selected?.title ?? ''}
              subtitle={selected && (
                <div className="flex items-center gap-1.5">
                  <Chip tone="accent">{selected.reference}</Chip>
                  <Chip tone={selected.legal_risk_score >= 35 ? 'rose' : 'mint'}>
                    legal risk {selected.legal_risk_score}
                  </Chip>
                </div>
              )}>
        {selected && (
          <div className="space-y-4">
            {selected.missing_clauses.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-rose">
                  Missing mandatory clauses
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {selected.missing_clauses.map((m: any) => (
                    <Chip key={m.key} tone="rose">{m.label}</Chip>
                  ))}
                </div>
              </div>
            )}
            {selected.clause_findings.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber">
                  Risky language
                </p>
                <div className="space-y-1.5">
                  {selected.clause_findings.map((f: any) => (
                    <div key={f.key} className="rounded-lg border border-amber/25 bg-amber/[0.06] p-2.5">
                      <p className="text-[12.5px] font-medium text-slate-200">
                        {f.label} <span className="text-amber">+{f.weight}</span>
                      </p>
                      <p className="mono mt-1 text-slate-400">“{f.excerpt}”</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {selected.obligations?.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Obligations tracked
                </p>
                <div className="overflow-hidden rounded-lg border border-ink-700">
                  <table className="w-full">
                    <tbody>
                      {selected.obligations.map((o: any, i: number) => (
                        <tr key={i} className="table-row last:border-0">
                          <td className="td w-28"><Chip tone="slate">{o.type}</Chip></td>
                          <td className="td text-slate-300">{o.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Document
              </p>
              <pre className="mono whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/70 p-4 text-slate-300">
                {body ?? 'Loading…'}
              </pre>
            </div>
          </div>
        )}
      </Drawer>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Tail spend                                                            */
/* ==================================================================== */
export function TailSpend() {
  const { data, loading } = useApi<any>('/tail-spend')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')
  const [task, setTask] = useState<string | null>(null)

  const tailTasks = (pending?.items ?? []).filter((t) =>
    ['consolidate_suppliers', 'enforce_catalog'].includes(t.action_kind))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Tile label="Tail spend identified" value={money(data?.spend_usd)} tone="text-amber" />
        <Tile label="Consolidation savings" value={money(data?.savings_usd)} tone="text-mint" />
        <Tile label="Open findings" value={num(data?.open, 0)} />
      </div>

      <RunAgentPanel agentKey="tail_spend" label="Tail Spend Agent"
                     hint="Attach a spend extract and a catalog to split head from tail, cluster the tail by category and price consolidation." />

      {tailTasks.length > 0 && (
        <Panel bodyClass="" title="Tail spend decisions awaiting a human">
          <div className="divide-y divide-ink-800">
            {tailTasks.map((t) => (
              <button key={t.id} onClick={() => setTask(t.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
                <div className="min-w-0 flex-1">
                  <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                  <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
                </div>
                <span className="shrink-0 tabular-nums text-slate-200">{money(t.financial_impact_usd)}</span>
                <Chip tone="slate">{t.required_role_label}</Chip>
              </button>
            ))}
          </div>
        </Panel>
      )}

      <Panel bodyClass="" title="Tail spend findings" subtitle={`${data?.count ?? 0} finding(s)`}>
        {loading && <Spinner />}
        {!loading && !data?.items?.length && (
          <Empty title="No findings yet" hint="Run the Tail Spend Agent above." />
        )}
        <div className="divide-y divide-ink-800">
          {(data?.items ?? []).map((f: any) => (
            <div key={f.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="mono text-slate-500">{f.reference}</span>
                <span className="text-[13px] font-medium text-slate-100">{f.category}</span>
                <Chip tone={f.finding_type === 'consolidation' ? 'accent' : 'amber'}>
                  {titleCase(f.finding_type)}
                </Chip>
                <Chip tone={f.status === 'open' ? 'slate' : 'mint'}>{titleCase(f.status)}</Chip>
                <span className="ml-auto tabular-nums text-slate-200">{money(f.spend_usd)}</span>
                {f.consolidation_savings_usd > 0 && (
                  <span className="tabular-nums text-mint">
                    → {money(f.consolidation_savings_usd)}
                  </span>
                )}
              </div>
              <p className="mt-1 text-[12px] text-slate-400">{f.recommendation}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-slate-500">{f.transaction_count} transactions ·</span>
                {(f.supplier_names ?? []).slice(0, 5).map((s: string) => (
                  <Chip key={s} tone="slate">{s}</Chip>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Artifact library                                                      */
/* ==================================================================== */
export function Artifacts() {
  const { notify, refresh } = useSession()
  const [direction, setDirection] = useState('')
  const { data, loading } = useApi<any>(
    `/artifacts?limit=250${direction ? `&direction=${direction}` : ''}`, [direction])
  const fileRef = useRef<HTMLInputElement>(null)

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch('/api/artifacts/upload', {
        method: 'POST',
        headers: { 'X-User-Id': localStorage.getItem('p2p.token') ?? '' },
        body: form,
      })
      if (!res.ok) throw new Error((await res.json()).detail ?? 'Upload failed')
      const a = await res.json()
      notify(`${a.filename} uploaded — ${a.summary}`, 'mint')
      refresh()
    } catch (err) {
      notify((err as Error).message, 'rose')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Tile label="Total files" value={num(data?.count, 0)} />
        <Tile label="Inputs" value={num(data?.inputs, 0)} tone="text-accent-soft" />
        <Tile label="Outputs" value={num(data?.outputs, 0)} tone="text-mint" />
        <Tile label="Drafts awaiting release" value={num(data?.drafts, 0)} tone="text-amber" />
      </div>

      <Panel
        bodyClass=""
        title="Artifact library"
        subtitle="Everything that has flowed into or out of an agent"
        actions={
          <>
            <select className="field w-auto py-1" value={direction}
                    onChange={(e) => setDirection(e.target.value)}>
              <option value="">All</option>
              <option value="input">Inputs only</option>
              <option value="output">Outputs only</option>
            </select>
            <label className="btn-primary cursor-pointer">
              + Upload attachment
              <input ref={fileRef} type="file" className="hidden" onChange={upload}
                     accept=".csv,.json,.md,.txt,.tsv,.pdf" />
            </label>
          </>
        }
      >
        {loading && <Spinner />}
        {!loading && !data?.items?.length && <Empty title="No files yet" />}
        {!loading && !!data?.items?.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Ref</th><th className="th">File</th><th className="th">Direction</th>
                  <th className="th">Kind</th><th className="th">Agent</th><th className="th">Summary</th>
                  <th className="th text-right">Size</th><th className="th">Status</th>
                  <th className="th">When</th><th className="th"></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a: ArtifactRow) => (
                  <tr key={a.id} className="table-row">
                    <td className="td mono text-slate-500">{a.reference}</td>
                    <td className="td">
                      <span className="mono text-slate-200">{a.filename}</span>
                      <span className="block text-[11px] text-slate-500">{a.title}</span>
                    </td>
                    <td className="td">
                      <Chip tone={a.direction === 'input' ? 'accent' : 'mint'}>
                        {a.direction === 'input' ? '📎 in' : '⬇ out'}
                      </Chip>
                    </td>
                    <td className="td"><Chip tone="slate">{titleCase(a.kind)}</Chip></td>
                    <td className="td text-slate-400">{a.agent_key ?? a.uploaded_by ?? '—'}</td>
                    <td className="td max-w-[300px] truncate text-slate-400">{a.summary}</td>
                    <td className="td text-right tabular-nums text-slate-400">{bytes(a.size_bytes)}</td>
                    <td className="td">
                      <Chip tone={a.status === 'released' ? 'mint' : a.status === 'draft' ? 'amber' : 'slate'}>
                        {a.status}
                      </Chip>
                    </td>
                    <td className="td text-slate-500">{relative(a.created_at)}</td>
                    <td className="td text-right">
                      <a className="btn-ghost" href={a.download_url} download>↓</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

/* ==================================================================== */
function Tile({ label, value, sub, tone = 'text-slate-100' }: {
  label: string; value: string; sub?: string; tone?: string
}) {
  return (
    <div className="panel p-4">
      <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="subtle mt-1">{sub}</p>}
    </div>
  )
}
