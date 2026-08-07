import { useMemo, useState } from 'react'
import TaskDrawer from '../components/TaskDrawer'
import { Chip, Confidence, Empty, Panel, RiskChip, Spinner } from '../components/ui'
import { HumanTask, api } from '../lib/api'
import { dateTime, money, relative, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

type Feed = { count: number; actionable_by_me: number; items: HumanTask[] }
type Summary = {
  pending_total: number; pending_for_me: number; value_awaiting_decision: number
  irreversible_pending: number; dual_approval_pending: number
  by_action: Record<string, number>; by_risk: Record<string, number>
}

const STATUS_TABS = [
  { key: 'pending', label: 'Awaiting decision' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'modified', label: 'Modified' },
  { key: 'all', label: 'All' },
]

export default function Inbox() {
  const { user, refresh, notify } = useSession()
  const [status, setStatus] = useState('pending')
  const [mineOnly, setMineOnly] = useState(false)
  const [risk, setRisk] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const query = `/hitl/tasks?status=${status}&mine_only=${mineOnly}${risk ? `&risk_level=${risk}` : ''}`
  const { data, loading } = useApi<Feed>(query, [status, mineOnly, risk])
  const { data: summary } = useApi<Summary>('/hitl/summary')

  const items = data?.items ?? []
  const bulkEligible = useMemo(
    () => items.filter((t) => t.status === 'pending' && t.can_decide && t.reversible
      && !['high', 'critical'].includes(t.risk_level) && !t.dual_approval_required),
    [items],
  )

  async function bulkApprove() {
    const ids = [...checked]
    if (!ids.length) return
    setBusy(true)
    try {
      const res = await api.post<{ applied: unknown[]; refused: { reason: string }[] }>(
        `/hitl/tasks/bulk-decide?decision=approve&notes=${encodeURIComponent('Batch approved from inbox')}`,
        ids,
      )
      notify(
        `${res.applied.length} approved${res.refused.length ? `, ${res.refused.length} held back for individual review` : ''}.`,
        res.refused.length ? 'accent' : 'mint',
      )
      setChecked(new Set())
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-4">
      {/* Governance banner — the point of the screen */}
      <div className="panel flex flex-wrap items-center gap-x-6 gap-y-3 border-accent/25 bg-gradient-to-r from-accent/[0.07] to-violet/[0.05] px-4 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-slate-100">
            Every agent action stops here first
          </p>
          <p className="subtle mt-0.5">
            Agents have already done the analysis. Nothing below has touched the ERP, the ledger or a
            supplier — it happens only when you decide.
          </p>
        </div>
        <div className="flex gap-5">
          <Metric label="Awaiting you" value={summary?.pending_for_me ?? 0} tone="text-amber" />
          <Metric label="Open total" value={summary?.pending_total ?? 0} />
          <Metric label="Value held" value={money(summary?.value_awaiting_decision)} />
          <Metric label="Irreversible" value={summary?.irreversible_pending ?? 0} tone="text-rose" />
        </div>
      </div>

      <Panel
        bodyClass=""
        title="Approval inbox"
        subtitle={`${items.length} checkpoint${items.length === 1 ? '' : 's'} · signed in as ${user?.role_label}`}
        actions={
          <>
            <select className="field w-auto py-1" value={risk} onChange={(e) => setRisk(e.target.value)}>
              <option value="">All risk levels</option>
              {['low', 'medium', 'high', 'critical'].map((r) => (
                <option key={r} value={r}>{titleCase(r)} risk</option>
              ))}
            </select>
            <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-slate-400">
              <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
              Only what I can decide
            </label>
            {checked.size > 0 && (
              <button className="btn-mint" onClick={bulkApprove} disabled={busy}>
                Approve {checked.size} low-risk
              </button>
            )}
          </>
        }
      >
        <div className="flex gap-1 border-b border-ink-700 px-4">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => { setStatus(t.key); setChecked(new Set()) }}
              className={`-mb-px border-b-2 px-3 py-2 text-[12px] font-medium transition-colors ${
                status === t.key ? 'border-accent text-accent-soft' : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading && <Spinner />}
        {!loading && items.length === 0 && (
          <Empty
            icon="✓"
            title="Nothing waiting on a human here"
            hint="Run an agent sweep from the top bar to generate new proposals, or change the filter above."
          />
        )}

        {!loading && items.length > 0 && (
          <div className="divide-y divide-ink-800">
            {items.map((t) => (
              <div
                key={t.id}
                className="group flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-ink-850/50"
                onClick={() => setSelected(t.id)}
              >
                {bulkEligible.some((b) => b.id === t.id) && (
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={checked.has(t.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggle(t.id)}
                  />
                )}

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                    <RiskChip level={t.risk_level} />
                    {!t.reversible && <Chip tone="rose">irreversible</Chip>}
                    {t.dual_approval_required && <Chip tone="amber">dual approval</Chip>}
                    {t.overdue && <Chip tone="rose">overdue</Chip>}
                    {t.status !== 'pending' && <Chip tone={t.status === 'rejected' ? 'rose' : 'mint'}>{titleCase(t.status)}</Chip>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-slate-400">{t.summary}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                    <span className="text-violet">⬢ {t.agent_name}</span>
                    <span>{t.entity_label}</span>
                    <span className="mono">{t.action_label}</span>
                    <span>{t.stage_label}</span>
                    <span>{relative(t.created_at)}</span>
                    {t.status === 'pending' && t.due_at && <span>due {dateTime(t.due_at)}</span>}
                  </div>
                </div>

                <div className="flex w-40 shrink-0 flex-col items-end gap-1.5">
                  <span className="text-[13px] font-semibold tabular-nums text-slate-200">
                    {money(t.financial_impact_usd)}
                  </span>
                  <Confidence value={t.confidence} />
                  <Chip tone={t.can_decide ? 'mint' : 'slate'}>
                    {t.can_decide ? 'you can decide' : t.required_role_label}
                  </Chip>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <TaskDrawer taskId={selected} open={Boolean(selected)} onClose={() => setSelected(null)} />
    </div>
  )
}

function Metric({ label, value, tone = 'text-slate-100' }: { label: string; value: unknown; tone?: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${tone}`}>{String(value)}</p>
    </div>
  )
}
