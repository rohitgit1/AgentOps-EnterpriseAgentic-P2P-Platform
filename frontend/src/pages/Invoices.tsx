import { useEffect, useState } from 'react'
import TaskDrawer from '../components/TaskDrawer'
import { Chip, Confidence, Drawer, Empty, KeyValue, Panel, Spinner, StatusChip } from '../components/ui'
import { AgentRun, HumanTask, Invoice, api } from '../lib/api'
import { STATUS_STYLES, SLA_STYLES, dateOnly, dateTime, hours, money, relative, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

type List = { count: number; items: Invoice[] }
type Timeline = {
  invoice: Invoice & { lines?: any[]; exceptions?: any[]; approvals?: any[]; po?: any; supplier?: any; document_text?: string }
  events: { id: string; title: string; message: string; actor: string; actor_type: string; severity: string; created_at: string }[]
  agent_runs: AgentRun[]
  checkpoints: HumanTask[]
  audit: { id: string; action: string; actor: string; actor_role?: string; description: string; timestamp: string; hitl_enforced: boolean }[]
}

const STAGES = ['intake', 'extraction_review', 'validation', 'matching', 'exception', 'approval', 'payment', 'posted', 'closed']

export default function Invoices() {
  const { notify, refresh } = useSession()
  const [stage, setStage] = useState('')
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const q = `/invoices?${stage ? `stage=${stage}&` : ''}${search ? `search=${encodeURIComponent(search)}&` : ''}limit=200`
  const { data, loading } = useApi<List>(q, [stage, search])

  async function advance(id: string, label: string) {
    setBusy(true)
    try {
      const res = await api.post<{ checkpoints: HumanTask[] }>(`/orchestrator/invoices/${id}/advance`)
      notify(
        res.checkpoints.length
          ? `${label}: ${res.checkpoints.length} proposal(s) now awaiting a human decision.`
          : `${label}: agents found nothing to propose — it is blocked on an open checkpoint or a human action.`,
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
    <div className="space-y-4">
      <Panel
        bodyClass=""
        title="Invoices"
        subtitle={`${data?.count ?? 0} in the working set`}
        actions={
          <>
            <input
              className="field w-52"
              placeholder="Search number or supplier…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select className="field w-auto py-1" value={stage} onChange={(e) => setStage(e.target.value)}>
              <option value="">All stages</option>
              {STAGES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </select>
          </>
        }
      >
        {loading && <Spinner />}
        {!loading && !data?.items.length && <Empty title="No invoices match" hint="Clear the filters or ingest a new document." />}
        {!loading && !!data?.items.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Invoice</th><th className="th">Supplier</th><th className="th">PO</th>
                  <th className="th text-right">Amount</th><th className="th">Stage</th><th className="th">Status</th>
                  <th className="th">SLA</th><th className="th">Extraction</th><th className="th">Age</th>
                  <th className="th"></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((inv) => (
                  <tr key={inv.id} className="table-row cursor-pointer" onClick={() => setOpenId(inv.id)}>
                    <td className="td">
                      <span className="font-medium text-slate-100">{inv.invoice_number}</span>
                      <div className="mt-0.5 flex gap-1">
                        <Chip tone="slate">{inv.source_channel}</Chip>
                        {inv.on_hold && <Chip tone="rose">on hold</Chip>}
                        {inv.open_exception_count > 0 && <Chip tone="amber">{inv.open_exception_count} exception</Chip>}
                      </div>
                    </td>
                    <td className="td text-slate-300">{inv.supplier_name ?? '—'}</td>
                    <td className="td mono text-slate-400">{inv.po_number ?? '—'}</td>
                    <td className="td text-right font-medium tabular-nums text-slate-100">
                      {money(inv.total_amount, inv.currency)}
                    </td>
                    <td className="td"><Chip tone="accent">{inv.stage_label}</Chip></td>
                    <td className="td"><StatusChip value={inv.status} map={STATUS_STYLES} /></td>
                    <td className="td"><StatusChip value={inv.sla_status} map={SLA_STYLES} /></td>
                    <td className="td"><Confidence value={inv.extraction_confidence} /></td>
                    <td className="td tabular-nums text-slate-400">{hours(inv.age_hours)}</td>
                    <td className="td text-right">
                      <button
                        className="btn-ghost"
                        disabled={busy}
                        onClick={(e) => { e.stopPropagation(); advance(inv.id, inv.invoice_number) }}
                      >
                        Run agents
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <InvoiceDrawer id={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}

function InvoiceDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { revision } = useSession()
  const [data, setData] = useState<Timeline | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<'overview' | 'timeline' | 'runs' | 'audit' | 'document'>('overview')
  const [task, setTask] = useState<string | null>(null)

  useEffect(() => {
    if (!id) {
      setData(null)
      return
    }
    let cancelled = false
    setLoading(true)
    api
      .get<Timeline>(`/invoices/${id}/timeline`)
      .then((res) => !cancelled && setData(res))
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [id, revision])

  const inv = data?.invoice

  return (
    <>
      <Drawer
        open={Boolean(id)}
        onClose={() => { setData(null); onClose() }}
        width="max-w-4xl"
        title={inv ? inv.invoice_number : 'Invoice'}
        subtitle={
          inv && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone="accent">{inv.stage_label}</Chip>
              <StatusChip value={inv.status} map={STATUS_STYLES} />
              <StatusChip value={inv.sla_status} map={SLA_STYLES} />
              <span className="text-[12px] text-slate-400">
                {inv.supplier_name} · {money(inv.total_amount, inv.currency)}
              </span>
            </div>
          )
        }
      >
        {loading && <Spinner />}
        {inv && (
          <div className="space-y-4">
            <div className="flex gap-1 border-b border-ink-700">
              {(['overview', 'timeline', 'runs', 'audit', 'document'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-3 py-1.5 text-[12px] font-medium capitalize transition-colors ${
                    tab === t ? 'border-accent text-accent-soft' : 'border-transparent text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {t === 'runs' ? `Agent runs (${data?.agent_runs.length ?? 0})` : t}
                </button>
              ))}
            </div>

            {tab === 'overview' && (
              <div className="space-y-4">
                <div className="panel p-4">
                  <KeyValue items={[
                    ['Supplier', inv.supplier_name ?? '—'],
                    ['Purchase order', inv.po_number ?? 'none'],
                    ['Invoice date', dateOnly(inv.invoice_date as string)],
                    ['Due date', dateOnly(inv.due_date as string)],
                    ['Amount', money(inv.total_amount, inv.currency)],
                    ['Tax', money(inv.tax_amount as number, inv.currency)],
                    ['Match result', titleCase(inv.match_result)],
                    ['ERP document', inv.erp_document_number ?? 'not posted'],
                    ['Channel', titleCase(inv.source_channel)],
                    ['Human touches', String(inv.human_touches)],
                  ]} />
                </div>

                {inv.on_hold && (
                  <div className="rounded-lg border border-rose/30 bg-rose/10 p-3 text-[12.5px] text-rose">
                    <strong>On hold.</strong> {inv.hold_reason}
                  </div>
                )}

                {(inv.lines?.length ?? 0) > 0 && (
                  <div>
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Lines</p>
                    <div className="overflow-hidden rounded-lg border border-ink-700">
                      <table className="w-full">
                        <thead className="bg-ink-850/70">
                          <tr><th className="th">#</th><th className="th">Item</th><th className="th">Description</th>
                            <th className="th text-right">Qty</th><th className="th text-right">Unit</th><th className="th text-right">Total</th></tr>
                        </thead>
                        <tbody>
                          {inv.lines!.map((l: any) => (
                            <tr key={l.id} className="table-row last:border-0">
                              <td className="td text-slate-500">{l.line_number}</td>
                              <td className="td mono text-slate-300">{l.item_code}</td>
                              <td className="td text-slate-300">{l.description}</td>
                              <td className="td text-right tabular-nums">{l.quantity}</td>
                              <td className="td text-right tabular-nums">{money(l.unit_price, inv.currency)}</td>
                              <td className="td text-right font-medium tabular-nums">{money(l.line_total, inv.currency)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {(data?.checkpoints.length ?? 0) > 0 && (
                  <div>
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                      Human checkpoints
                    </p>
                    <div className="space-y-1.5">
                      {data!.checkpoints.map((c) => (
                        <button
                          key={c.id}
                          onClick={() => setTask(c.id)}
                          className="flex w-full items-center gap-2.5 rounded-lg border border-ink-700 bg-ink-850/50 p-2.5 text-left hover:bg-ink-800"
                        >
                          <Chip tone={c.status === 'pending' ? 'amber' : c.status === 'rejected' ? 'rose' : 'mint'}>
                            {titleCase(c.status)}
                          </Chip>
                          <span className="min-w-0 flex-1 truncate text-[12.5px] text-slate-200">{c.title}</span>
                          <span className="shrink-0 text-[11px] text-slate-500">{c.agent_name}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {tab === 'timeline' && (
              <ol className="relative space-y-3 border-l border-ink-700 pl-4">
                {data!.events.map((e) => (
                  <li key={e.id} className="relative">
                    <span className={`absolute -left-[21px] top-1.5 h-2 w-2 rounded-full ring-4 ring-ink-900 ${
                      e.severity === 'critical' ? 'bg-rose' : e.severity === 'warning' ? 'bg-amber'
                        : e.severity === 'success' ? 'bg-mint' : 'bg-accent'
                    }`} />
                    <p className="text-[12.5px] font-medium text-slate-200">{e.title}</p>
                    <p className="subtle mt-0.5">{e.message}</p>
                    <p className="mt-0.5 text-[10.5px] text-slate-600">
                      {e.actor} · {dateTime(e.created_at)}
                    </p>
                  </li>
                ))}
              </ol>
            )}

            {tab === 'runs' && (
              <div className="space-y-2.5">
                {data!.agent_runs.map((r) => (
                  <div key={r.id} className="panel p-3.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip tone="violet">{r.agent_name}</Chip>
                      <Chip tone="slate">{r.run_number}</Chip>
                      <Chip tone={r.status === 'completed' ? 'mint' : r.status === 'awaiting_human' ? 'amber' : 'slate'}>
                        {titleCase(r.status)}
                      </Chip>
                      <span className="ml-auto text-[11px] text-slate-500">
                        {r.duration_ms}ms · {relative(r.created_at)}
                      </span>
                    </div>
                    <p className="mt-2 text-[12.5px] text-slate-200">{r.conclusion}</p>
                    <div className="mt-2 flex items-center gap-3">
                      <Confidence value={r.confidence} />
                      <span className="mono text-slate-500">engine: {r.reasoning_engine}</span>
                      {r.handoff_to && <Chip tone="accent">→ {r.handoff_to}</Chip>}
                    </div>
                    {r.observations && (
                      <div className="mt-2.5 space-y-1">
                        {r.observations.map((o, i) => (
                          <div key={i} className="flex gap-2 text-[11.5px]">
                            <span className={o.ok ? 'text-mint' : 'text-amber'}>{o.ok ? '✓' : '!'}</span>
                            <span className="mono text-accent-soft">{o.tool}</span>
                            <span className="text-slate-400">{o.summary}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {tab === 'audit' && (
              <div className="overflow-hidden rounded-lg border border-ink-700">
                <table className="w-full">
                  <thead className="bg-ink-850/70">
                    <tr><th className="th">When</th><th className="th">Actor</th><th className="th">Action</th><th className="th">Detail</th></tr>
                  </thead>
                  <tbody>
                    {data!.audit.map((a) => (
                      <tr key={a.id} className="table-row last:border-0">
                        <td className="td whitespace-nowrap text-slate-500">{dateTime(a.timestamp)}</td>
                        <td className="td text-slate-300">
                          {a.actor}
                          {a.actor_role && <span className="block text-[10.5px] text-slate-500">{titleCase(a.actor_role)}</span>}
                        </td>
                        <td className="td mono text-accent-soft">{a.action}</td>
                        <td className="td text-slate-400">{a.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {tab === 'document' && (
              <pre className="mono overflow-x-auto whitespace-pre rounded-lg border border-ink-700 bg-ink-950/70 p-4 text-slate-400">
                {inv.document_text ?? 'No source document captured.'}
              </pre>
            )}
          </div>
        )}
      </Drawer>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </>
  )
}
