/**
 * Secondary operational surfaces: exceptions, approvals, payments, SLA command
 * center, suppliers, skills library, audit trail and governance.
 */
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import TaskDrawer from '../components/TaskDrawer'
import { Chip, Confidence, Drawer, Empty, KeyValue, Panel, RiskChip, Spinner, StatusChip } from '../components/ui'
import { AXIS, ChartTooltip, GRID, SEQUENTIAL, STATUS } from '../lib/chart'
import { api } from '../lib/api'
import { SLA_STYLES, STATUS_STYLES, dateOnly, dateTime, hours, money, num, pct, relative, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

/* ==================================================================== */
/* Exceptions                                                            */
/* ==================================================================== */
export function Exceptions() {
  const { notify, refresh } = useSession()
  const [busy, setBusy] = useState(false)
  const [task, setTask] = useState<string | null>(null)
  const { data, loading } = useApi<{ count: number; exposure: number; items: any[] }>('/exceptions?status=open_only')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')

  async function triage() {
    setBusy(true)
    try {
      const res = await api.post<{ runs: number; checkpoints: any[] }>('/orchestrator/triage-exceptions')
      notify(`Exception agent triaged ${res.runs} case(s) → ${res.checkpoints.length} resolution proposal(s).`, 'accent')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  const proposalFor = (caseId: string) => pending?.items.find((t) => t.entity_id === caseId)

  return (
    <div className="space-y-4">
      <Panel
        bodyClass=""
        title="Exception queue"
        subtitle={`${data?.count ?? 0} open · ${money(data?.exposure)} of value at stake`}
        actions={<button className="btn-primary" onClick={triage} disabled={busy}>▶ Triage with agent</button>}
      >
        {loading && <Spinner />}
        {!loading && !data?.items.length && (
          <Empty icon="✓" title="No open exceptions" hint="Approve an agent's 'open exception' proposal to see one land here." />
        )}
        {!loading && !!data?.items.length && (
          <div className="divide-y divide-ink-800">
            {data.items.map((x) => {
              const proposal = proposalFor(x.id)
              return (
                <div key={x.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mono text-slate-500">{x.case_number}</span>
                    <span className="text-[13px] font-medium text-slate-100">{x.title}</span>
                    <RiskChip level={x.severity} />
                    <Chip tone="slate">{titleCase(x.exception_type)}</Chip>
                    <span className="ml-auto font-semibold tabular-nums text-slate-200">{money(x.financial_impact_usd)}</span>
                  </div>
                  <p className="mt-1 text-[12px] text-slate-400">{x.description}</p>
                  {x.proposed_resolution && (
                    <div className="mt-2 rounded-lg border border-accent/25 bg-accent/[0.06] p-2.5">
                      <p className="text-[10.5px] font-semibold uppercase tracking-wider text-accent-soft">
                        Agent-proposed resolution · {Math.round((x.agent_confidence ?? 0) * 100)}% confidence
                      </p>
                      <p className="mt-1 text-[12.5px] text-slate-300">{x.proposed_resolution}</p>
                    </div>
                  )}
                  <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
                    <span>{x.invoice_number ?? '—'}</span>
                    <span>open {hours(x.age_hours)}</span>
                    <span>detected by {x.detected_by}</span>
                    {proposal && (
                      <button className="btn-primary ml-auto" onClick={() => setTask(proposal.id)}>
                        Review resolution proposal
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>
      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* Approvals (the business approval, distinct from agent checkpoints)    */
/* ==================================================================== */
export function Approvals() {
  const { notify, refresh, user } = useSession()
  const [mineOnly, setMineOnly] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const { data, loading } = useApi<{ items: any[] }>(`/approvals?mine_only=${mineOnly}&status=pending`, [mineOnly])

  async function decide(id: string, approved: boolean) {
    const notes = approved ? 'Approved by assigned approver.' : window.prompt('Reason for rejection?') || ''
    if (!approved && !notes) return
    setBusy(id)
    try {
      await api.post(`/approvals/${id}/decide`, { approved, notes })
      notify(approved ? 'Invoice approved and released to payment readiness.' : 'Invoice rejected.', approved ? 'mint' : 'rose')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(null) }
  }

  return (
    <Panel
      bodyClass=""
      title="Invoice approvals"
      subtitle={`Business approvals assigned to a person — signed in as ${user?.full_name}`}
      actions={
        <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-slate-400">
          <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
          Assigned to me
        </label>
      }
    >
      {loading && <Spinner />}
      {!loading && !data?.items.length && <Empty icon="✓" title="No approvals waiting" />}
      {!loading && !!data?.items.length && (
        <div className="divide-y divide-ink-800">
          {data.items.map((a) => (
            <div key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-slate-100">{a.invoice_number}</p>
                <p className="subtle mt-0.5">{a.routing_reason}</p>
                <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-500">
                  <span>Level {a.level}</span>
                  <span>pending {hours(a.age_hours)}</span>
                  {a.reminders_sent > 0 && <Chip tone="amber">{a.reminders_sent} reminder</Chip>}
                  {a.escalated && <Chip tone="rose">escalated</Chip>}
                  <span>→ {a.approver_name}</span>
                </div>
              </div>
              <span className="text-[15px] font-semibold tabular-nums text-slate-100">{money(a.amount, a.currency)}</span>
              <div className="flex gap-1.5">
                <button className="btn-mint" onClick={() => decide(a.id, true)} disabled={busy === a.id}>Approve</button>
                <button className="btn-danger" onClick={() => decide(a.id, false)} disabled={busy === a.id}>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

/* ==================================================================== */
/* Payments                                                              */
/* ==================================================================== */
export function Payments() {
  const { notify, refresh } = useSession()
  const [busy, setBusy] = useState(false)
  const [task, setTask] = useState<string | null>(null)
  const { data, loading } = useApi<{ count: number; scheduled_value: number; discount_captured: number; items: any[] }>('/payments')
  const { data: pending } = useApi<{ items: any[] }>('/hitl/tasks?status=pending&limit=200')

  const paymentProposals = pending?.items.filter((t) =>
    ['schedule_payment', 'release_payment', 'post_to_erp'].includes(t.action_kind)) ?? []

  async function buildRun() {
    setBusy(true)
    try {
      const res = await api.post<{ checkpoints: any[] }>('/agents/payment_readiness/run', {})
      notify(`Payment run proposal ready — ${res.checkpoints.length} item(s) for Treasury review.`, 'accent')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Tile label="Scheduled value" value={money(data?.scheduled_value)} />
        <Tile label="Early-pay discount captured" value={money(data?.discount_captured)} tone="text-mint" />
        <Tile label="Payment decisions pending" value={String(paymentProposals.length)} tone="text-amber" />
      </div>

      <Panel
        bodyClass=""
        title="Payment decisions awaiting a human"
        subtitle="Money never moves without a named approver"
        actions={<button className="btn-primary" onClick={buildRun} disabled={busy}>▶ Build payment run</button>}
      >
        {paymentProposals.length === 0 && <Empty title="No payment proposals" hint="Build a payment run to have the agent rank and propose." />}
        <div className="divide-y divide-ink-800">
          {paymentProposals.map((t) => (
            <button key={t.id} onClick={() => setTask(t.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-850/50">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                  <RiskChip level={t.risk_level} />
                  {!t.reversible && <Chip tone="rose">irreversible</Chip>}
                </div>
                <p className="mt-1 line-clamp-2 text-[12px] text-slate-400">{t.summary}</p>
              </div>
              <span className="shrink-0 text-[13px] font-semibold tabular-nums text-slate-100">{money(t.financial_impact_usd)}</span>
              <Chip tone="slate">{t.required_role_label}</Chip>
            </button>
          ))}
        </div>
      </Panel>

      <Panel bodyClass="" title="Payment ledger" subtitle={`${data?.count ?? 0} records`}>
        {loading && <Spinner />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead className="border-b border-ink-700">
              <tr><th className="th">Payment</th><th className="th">Invoice</th><th className="th text-right">Amount</th>
                <th className="th text-right">Discount</th><th className="th">Scheduled</th><th className="th">Status</th><th className="th">Released by</th></tr>
            </thead>
            <tbody>
              {data?.items.slice(0, 40).map((p) => (
                <tr key={p.id} className="table-row">
                  <td className="td mono text-slate-400">{p.payment_number}</td>
                  <td className="td text-slate-300">{p.invoice_number}</td>
                  <td className="td text-right font-medium tabular-nums">{money(p.amount, p.currency)}</td>
                  <td className="td text-right tabular-nums text-mint">{p.discount_captured ? money(p.discount_captured, p.currency) : '—'}</td>
                  <td className="td text-slate-400">{dateOnly(p.scheduled_date)}</td>
                  <td className="td"><StatusChip value={p.status} map={STATUS_STYLES} /></td>
                  <td className="td text-slate-400">{p.released_by ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <TaskDrawer taskId={task} open={Boolean(task)} onClose={() => setTask(null)} />
    </div>
  )
}

/* ==================================================================== */
/* SLA Command Center                                                    */
/* ==================================================================== */
export function SLA() {
  const { notify, refresh } = useSession()
  const [busy, setBusy] = useState(false)
  const { data, loading } = useApi<any>('/slas')

  async function forecast() {
    setBusy(true)
    try {
      const res = await api.post<{ checkpoints: any[] }>('/agents/sla_command_center/run', {})
      notify(`SLA forecast refreshed — ${res.checkpoints.length} intervention(s) proposed.`, 'accent')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  if (loading) return <Spinner />
  if (!data) return <Empty title="No SLA data" />

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Tile label="Forecast compliance" value={pct(data.forecast_compliance, 1)}
          tone={data.forecast_compliance >= data.target ? 'text-mint' : 'text-rose'} sub={`target ${data.target}%`} />
        <Tile label="In flight" value={num(data.in_flight, 0)} />
        <Tile label="At risk" value={num(data.at_risk, 0)} tone="text-amber" />
        <Tile label="Breached" value={num(data.breached, 0)} tone="text-rose" sub={`${money(data.exposure)} exposed`} />
      </div>

      <Panel
        title="Stage distribution"
        subtitle="In-flight population by workflow stage"
        actions={<button className="btn-primary" onClick={forecast} disabled={busy}>▶ Refresh forecast</button>}
      >
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.by_stage} margin={{ top: 16, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="label" {...AXIS} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={54} />
            <YAxis {...AXIS} axisLine={false} tickLine={false} width={30} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: '#161f3d55' }}
              content={({ active, payload, label }) => (
                <ChartTooltip active={active} label={label as string} rows={[
                  { name: 'Invoices', value: num(payload?.[0]?.value as number, 0), color: SEQUENTIAL[2] },
                  { name: 'Value', value: money((payload?.[0]?.payload as any)?.value) },
                ]} />
              )}
            />
            <Bar dataKey="count" barSize={24} radius={[4, 4, 0, 0]}>
              {data.by_stage.map((s: any, i: number) => (
                <Cell key={i} fill={s.at_risk > 0 ? STATUS.warning : SEQUENTIAL[2]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <p className="subtle mt-1">Amber columns contain at least one at-risk or breached invoice.</p>
      </Panel>

      <Panel bodyClass="" title="Risk register" subtitle="Forecast drivers, ranked — each with the intervention the agent recommends">
        {data.risks.length === 0 && <Empty icon="✓" title="Nothing forecast to breach" />}
        <div className="divide-y divide-ink-800">
          {data.risks.map((r: any) => (
            <div key={r.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-medium text-slate-100">{r.invoice_number}</span>
                <RiskChip level={r.risk_level} />
                <Chip tone="accent">{r.stage_label}</Chip>
                <StatusChip value={r.status} map={SLA_STYLES} />
                <span className="ml-auto mono tabular-nums text-slate-300">
                  {r.hours_remaining < 0 ? `${hours(Math.abs(r.hours_remaining))} over` : `${hours(r.hours_remaining)} left`}
                </span>
              </div>
              <p className="mt-1.5 text-[12.5px] text-slate-300">{r.recommended_action}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(r.drivers ?? []).map((d: any, i: number) => (
                  <Chip key={i} tone="slate">{titleCase(d.driver)} +{d.impact_hours}h</Chip>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}

/* ==================================================================== */
/* Suppliers                                                             */
/* ==================================================================== */
export function Suppliers() {
  const { notify, refresh } = useSession()
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const { data, loading } = useApi<any[]>('/suppliers/scorecard')

  async function open(id: string) {
    setOpenId(id)
    setDetail(null)
    setDetail(await api.get(`/suppliers/${id}`))
  }

  async function sendEnquiry() {
    if (!openId || !message.trim()) return
    setBusy(true)
    try {
      const res = await api.post<{ checkpoints: any[] }>('/supplier/chat', {
        supplier_id: openId, body: message, channel: 'portal',
      })
      notify(
        `Supplier Experience Agent drafted a reply — ${res.checkpoints.length} release approval queued. The supplier has not been contacted yet.`,
        'accent',
      )
      setMessage('')
      refresh()
      setDetail(await api.get(`/suppliers/${openId}`))
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <Panel bodyClass="" title="Supplier scorecard" subtitle={`${data?.length ?? 0} suppliers in the vendor master`}>
        {loading && <Spinner />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px]">
            <thead className="border-b border-ink-700">
              <tr><th className="th">Supplier</th><th className="th">Category</th><th className="th">Tier</th>
                <th className="th">Terms</th><th className="th text-right">Open</th><th className="th text-right">Open value</th>
                <th className="th text-right">YTD spend</th><th className="th">Risk</th><th className="th">Screening</th></tr>
            </thead>
            <tbody>
              {data?.map((s) => (
                <tr key={s.supplier_id} className="table-row cursor-pointer" onClick={() => open(s.supplier_id)}>
                  <td className="td">
                    <span className="font-medium text-slate-100">{s.name}</span>
                    <span className="mono ml-2 text-slate-500">{s.code}</span>
                    {s.on_hold && <Chip tone="rose" className="ml-2">blocked</Chip>}
                  </td>
                  <td className="td text-slate-400">{s.category}</td>
                  <td className="td"><Chip tone={s.tier === 'platinum' ? 'accent' : s.tier === 'gold' ? 'amber' : 'slate'}>{s.tier}</Chip></td>
                  <td className="td mono text-slate-400">{s.payment_terms}</td>
                  <td className="td text-right tabular-nums">{s.open_invoices}</td>
                  <td className="td text-right tabular-nums">{money(s.open_value)}</td>
                  <td className="td text-right tabular-nums text-slate-400">{money(s.spend_ytd_usd)}</td>
                  <td className="td"><RiskChip level={s.risk_level} /></td>
                  <td className="td">
                    <Chip tone={s.sanctions_status === 'clear' ? 'mint' : 'rose'}>{s.sanctions_status}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Drawer open={Boolean(openId)} onClose={() => { setOpenId(null); setDetail(null) }} title={detail?.name ?? 'Supplier'}>
        {!detail && <Spinner />}
        {detail && (
          <div className="space-y-4">
            <div className="panel p-4">
              <KeyValue items={[
                ['Code', detail.code], ['Tier', titleCase(detail.tier)],
                ['Country', detail.country], ['Terms', detail.payment_terms],
                ['Early-pay discount', detail.early_pay_discount_pct ? `${detail.early_pay_discount_pct}% / ${detail.early_pay_discount_days}d` : 'none'],
                ['Bank last 4', detail.bank_account_last4 ?? '—'],
                ['Tax form', titleCase(detail.tax_form_status)],
                ['Insurance expiry', dateOnly(detail.insurance_expiry)],
              ]} />
            </div>

            <div className={`rounded-xl border p-3.5 ${detail.risk_assessment.payment_blocking ? 'border-rose/35 bg-rose/[0.07]' : 'border-ink-700 bg-ink-850/40'}`}>
              <div className="flex items-center gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Risk assessment</p>
                <RiskChip level={detail.risk_assessment.risk_level} />
                <span className="mono ml-auto text-slate-400">score {detail.risk_assessment.risk_score}/100</span>
              </div>
              <p className="mt-2 text-[12.5px] text-slate-300">{detail.risk_assessment.recommended_action}</p>
              <ul className="mt-2 space-y-1">
                {detail.risk_assessment.findings.map((f: any, i: number) => (
                  <li key={i} className="flex gap-2 text-[12px] text-slate-400">
                    <span className={f.severity === 'critical' || f.severity === 'high' ? 'text-rose' : 'text-amber'}>•</span>
                    <span>{f.detail}</span>
                  </li>
                ))}
                {detail.risk_assessment.findings.length === 0 && <li className="text-[12px] text-mint">No findings.</li>}
              </ul>
            </div>

            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                Simulate a supplier enquiry
              </p>
              <textarea
                className="field h-20 resize-none"
                placeholder="e.g. When will invoice CSP-77120 be paid?"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <p className="subtle">The agent drafts; the reply is only sent once a human releases it.</p>
                <button className="btn-primary" onClick={sendEnquiry} disabled={busy || !message.trim()}>Send enquiry</button>
              </div>
            </div>

            {detail.messages?.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Correspondence</p>
                <div className="space-y-1.5">
                  {detail.messages.map((m: any) => (
                    <div key={m.id} className={`rounded-lg border p-2.5 ${m.direction === 'inbound' ? 'border-ink-700 bg-ink-850/40' : 'border-accent/25 bg-accent/[0.06]'}`}>
                      <div className="flex items-center gap-2 text-[11px]">
                        <Chip tone={m.direction === 'inbound' ? 'slate' : 'accent'}>{m.direction}</Chip>
                        <span className="text-slate-400">{m.author}</span>
                        <Chip tone="slate">{m.channel}</Chip>
                        <span className="ml-auto text-slate-600">{relative(m.created_at)}</span>
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-[12px] text-slate-300">{m.body}</p>
                      {m.approved_by && <p className="subtle mt-1">Released by {m.approved_by}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  )
}

/* ==================================================================== */
/* Skills library                                                        */
/* ==================================================================== */
export function Skills() {
  const { data, loading } = useApi<any[]>('/agents/skills')
  if (loading) return <Spinner />
  return (
    <div className="space-y-4">
      <Panel title="Shared skills framework" subtitle="Reusable capabilities agents compose. Skills analyse; they never write to a system of record.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data?.map((s) => (
            <div key={s.name} className="panel p-4">
              <p className="text-[13px] font-semibold text-slate-100">{s.title}</p>
              <p className="mono mt-0.5 text-accent-soft">{s.name}</p>
              <p className="mt-2 text-[12px] leading-snug text-slate-400">{s.purpose}</p>
              <div className="mt-3 space-y-1.5 border-t border-ink-800 pt-2.5 text-[11.5px]">
                <p className="text-slate-500">
                  <span className="text-slate-400">Inputs:</span> {(s.inputs ?? []).join(', ')}
                </p>
                <p className="text-slate-500">
                  <span className="text-slate-400">Output:</span> {(s.output ?? []).join(', ')}
                </p>
                <p className="text-mint">✓ {s.success_criteria}</p>
                <p className="text-amber">⚠ {s.failure_handling}</p>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1">
                {(s.used_by_agents ?? []).map((a: string) => <Chip key={a} tone="violet">{a}</Chip>)}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}

/* ==================================================================== */
/* Audit trail                                                           */
/* ==================================================================== */
export function Audit() {
  const [actorType, setActorType] = useState('')
  const { data, loading } = useApi<{ count: number; items: any[] }>(
    `/audit?limit=250${actorType ? `&actor_type=${actorType}` : ''}`, [actorType])
  const { data: chain } = useApi<{ valid: boolean; entries_checked: number; head_hash: string }>('/audit/verify')

  return (
    <div className="space-y-4">
      {chain && (
        <div className={`panel flex flex-wrap items-center gap-4 px-4 py-3 ${chain.valid ? 'border-mint/30' : 'border-rose/40'}`}>
          <span className={`text-lg ${chain.valid ? 'text-mint' : 'text-rose'}`}>{chain.valid ? '⛓' : '⚠'}</span>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-slate-100">
              {chain.valid ? 'Audit chain verified' : 'Audit chain broken'}
            </p>
            <p className="subtle mt-0.5">
              {chain.entries_checked} entries recomputed. Each record hashes the previous one, so any
              retroactive edit is detectable.
            </p>
          </div>
          <span className="mono max-w-[280px] truncate text-slate-500">head {chain.head_hash}</span>
          <a className="btn-ghost" href="/api/audit/export" target="_blank" rel="noreferrer">Export CSV</a>
        </div>
      )}

      <Panel
        bodyClass=""
        title="Audit trail"
        subtitle={`${data?.count ?? 0} most recent entries`}
        actions={
          <select className="field w-auto py-1" value={actorType} onChange={(e) => setActorType(e.target.value)}>
            <option value="">All actors</option>
            <option value="human">Humans only</option>
            <option value="agent">Agents only</option>
            <option value="system">System</option>
          </select>
        }
      >
        {loading && <Spinner />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px]">
            <thead className="border-b border-ink-700">
              <tr><th className="th">#</th><th className="th">When</th><th className="th">Actor</th>
                <th className="th">Action</th><th className="th">Subject</th><th className="th">Description</th><th className="th">HITL</th></tr>
            </thead>
            <tbody>
              {data?.items.map((a) => (
                <tr key={a.id} className="table-row">
                  <td className="td mono text-slate-600">{a.sequence}</td>
                  <td className="td whitespace-nowrap text-slate-500">{dateTime(a.timestamp)}</td>
                  <td className="td">
                    <Chip tone={a.actor_type === 'agent' ? 'violet' : a.actor_type === 'human' ? 'mint' : 'slate'}>
                      {a.actor_type}
                    </Chip>
                    <span className="ml-1.5 text-slate-300">{a.actor}</span>
                  </td>
                  <td className="td mono text-accent-soft">{a.action}</td>
                  <td className="td text-slate-400">{a.entity_label ?? '—'}</td>
                  <td className="td max-w-[420px] text-slate-400">{a.description}</td>
                  <td className="td">
                    {a.hitl_enforced
                      ? <span className="text-mint" title="Human decided">✓</span>
                      : <span className="text-amber" title="Auto-executed inside the policy envelope">auto</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

/* ==================================================================== */
/* Governance                                                            */
/* ==================================================================== */
export function Governance() {
  const { notify, refresh, user } = useSession()
  const [busy, setBusy] = useState(false)
  const { data, loading } = useApi<any>('/admin/policies')

  async function savePolicy(key: string, value: string) {
    setBusy(true)
    try {
      await api.patch(`/admin/policies/${key}`, { value })
      notify('Policy updated — the change is in the audit trail and takes effect on the next agent run.', 'mint')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  async function setEnforcement(on: boolean) {
    try {
      await api.patch('/admin/governance', { enforce_human_in_the_loop: on })
      notify(on ? 'Human-in-the-loop enforcement is ON.' : 'Enforcement OFF — agents at L3 may now auto-execute reversible, in-envelope actions.', on ? 'mint' : 'rose')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') }
  }

  async function resetDemo() {
    if (!window.confirm('Rebuild the demo dataset from scratch? All decisions and history will be discarded.')) return
    setBusy(true)
    try {
      await api.post('/admin/reset-demo')
      notify('Demo dataset rebuilt.', 'mint')
      refresh()
    } catch (e) { notify((e as Error).message, 'rose') } finally { setBusy(false) }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">
      <Panel title="Platform governance" subtitle="The controls an auditor asks about first">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-ink-700 bg-ink-850/40 p-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-slate-100">Global human-in-the-loop enforcement</p>
              <p className="subtle mt-0.5">
                When ON, no agent action reaches a system of record without an explicit human decision —
                regardless of any agent's autonomy level. Turning it off does not make agents autonomous:
                per-agent levels, confidence floors, financial ceilings and the irreversible-action rule all still apply.
              </p>
            </div>
            <button
              className={data.governance.enforce_human_in_the_loop ? 'btn-mint' : 'btn-danger'}
              onClick={() => setEnforcement(!data.governance.enforce_human_in_the_loop)}
              disabled={user?.role !== 'admin'}
              title={user?.role !== 'admin' ? 'Platform Admin only' : ''}
            >
              {data.governance.enforce_human_in_the_loop ? 'ON — every action reviewed' : 'OFF'}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-ink-700 bg-ink-850/40 p-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-slate-100">Reset demo dataset</p>
              <p className="subtle mt-0.5">Rebuild suppliers, POs, contracts and the invoice scenarios from scratch.</p>
            </div>
            <button className="btn-ghost" onClick={resetDemo} disabled={busy || user?.role !== 'admin'}>Rebuild</button>
          </div>
        </div>
      </Panel>

      {Object.entries(data.by_category as Record<string, any[]>).map(([category, rules]) => (
        <Panel key={category} title={`${titleCase(category)} policy`} subtitle="Policy-as-code — edited here, enforced by the policy engine on every proposal">
          <div className="space-y-2.5">
            {rules.map((r) => (
              <div key={r.key} className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-850/30 p-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium text-slate-200">{r.name}</p>
                  <p className="subtle mt-0.5">{r.description}</p>
                  <p className="mono mt-0.5 text-slate-600">{r.key}</p>
                </div>
                {r.value_type === 'bool' ? (
                  <Chip tone={r.value === 'true' ? 'mint' : 'slate'}>{r.value}</Chip>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <input
                      className="field w-28 text-right"
                      defaultValue={r.value}
                      onBlur={(e) => e.target.value !== r.value && savePolicy(r.key, e.target.value)}
                      disabled={!r.editable || busy}
                    />
                    <span className="w-10 text-[11px] text-slate-500">{r.unit ?? ''}</span>
                  </div>
                )}
                {r.last_changed_by && <span className="w-full text-[10.5px] text-slate-600">last changed by {r.last_changed_by}</span>}
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  )
}

/* ==================================================================== */
function Tile({ label, value, sub, tone = 'text-slate-100' }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="panel p-4">
      <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="subtle mt-1">{sub}</p>}
    </div>
  )
}
