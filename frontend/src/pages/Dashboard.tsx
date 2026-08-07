import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Chip, Empty, Panel, Spinner } from '../components/ui'
import { AXIS, CATEGORICAL, ChartTooltip, GRID, Legend, Meter, SEQUENTIAL, STATUS } from '../lib/chart'
import { hours, money, num, pct, titleCase } from '../lib/format'
import { useApi } from '../store'

type Kpi = {
  value: number; unit: string; label: string; direction: 'up' | 'down'
  average: number; best_in_class: number; target: number
}
type Dashboard = {
  headline: Record<string, number>
  kpis: Record<string, Kpi>
  hitl: {
    pending: number; overdue: number; decided: number; approved: number; modified: number
    rejected: number; acceptance_rate: number | null; avg_review_minutes: number
    by_risk: Record<string, number>; by_role: Record<string, number>; by_agent: Record<string, number>
  }
  pipeline: { stage: string; label: string; count: number; value: number; at_risk: number }[]
  exceptions: { open: number; by_type: Record<string, number>; exposure: number; agent_resolved: number }
  payments: { scheduled_count: number; scheduled_value: number; discount_captured: number }
  agents: { total: number; enabled: number; runs: number; awaiting_human: number; avg_confidence: number }
  trend: { date: string; processed: number; value: number; touchless_rate: number | null; avg_cycle_hours: number | null }[]
  aging: { bucket: string; count: number; value: number }[]
}

const TREND_MEASURES = [
  { key: 'processed', label: 'Invoices processed', unit: '', fmt: (v: number) => num(v, 0) },
  { key: 'avg_cycle_hours', label: 'Average cycle time', unit: 'h', fmt: (v: number) => hours(v), target: 24 },
  { key: 'touchless_rate', label: 'Touchless rate', unit: '%', fmt: (v: number) => pct(v), target: 80 },
] as const

export default function DashboardPage() {
  const { data, loading } = useApi<Dashboard>('/dashboard')
  const [measure, setMeasure] = useState<(typeof TREND_MEASURES)[number]>(TREND_MEASURES[1])

  if (loading) return <Spinner label="Building the command center…" />
  if (!data) return <Empty title="No data yet" hint="Start the backend and reload." />

  const h = data.headline
  const kpiOrder = ['touchless_rate', 'avg_cycle_time_hours', 'sla_compliance', 'auto_resolution_rate', 'on_time_payment', 'avg_exception_age_hours']

  return (
    <div className="space-y-4">
      {/* ---- Hero row: what needs a person right now ---- */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Link to="/inbox" className="panel group border-amber/30 bg-amber/[0.06] p-4 transition-colors hover:bg-amber/[0.1]">
          <p className="text-[10.5px] font-semibold uppercase tracking-wider text-amber">Awaiting human decision</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-slate-100">{h.pending_human_decisions}</p>
          <p className="subtle mt-1">
            {money(h.at_risk_value)} of value held behind these checkpoints →
          </p>
        </Link>
        <StatTile label="Invoices in flight" value={num(h.invoices_in_flight, 0)} sub={`${money(h.open_value)} open payable`} />
        <StatTile label="Open exceptions" value={num(data.exceptions.open, 0)} sub={`${money(data.exceptions.exposure)} at stake`} tone={data.exceptions.open ? 'text-rose' : 'text-slate-100'} />
        <StatTile label="Agent runs today" value={num(data.agents.runs, 0)} sub={`${data.agents.enabled}/${data.agents.total} agents active · avg confidence ${Math.round(data.agents.avg_confidence * 100)}%`} />
      </div>

      {/* ---- KPI tiles with target meters ---- */}
      <Panel title="Operational KPIs" subtitle="Marker on each meter is the target; the band behind it is your current state">
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
          {kpiOrder.map((key) => {
            const k = data.kpis[key]
            if (!k) return null
            const meets = k.direction === 'up' ? k.value >= k.target : k.value <= k.target
            return (
              <div key={key}>
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[11.5px] text-slate-400">{k.label}</p>
                  <p className={`text-xl font-semibold tabular-nums ${meets ? 'text-mint' : 'text-slate-100'}`}>
                    {k.value}{k.unit}
                  </p>
                </div>
                <Meter value={k.value} target={k.target} direction={k.direction} />
                <p className="subtle mt-1.5">
                  target {k.target}{k.unit} · industry avg {k.average}{k.unit} · best-in-class {k.best_in_class}{k.unit}
                </p>
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-3">
        {/* ---- Pipeline funnel ---- */}
        <Panel
          className="xl:col-span-2"
          title="Workflow pipeline"
          subtitle="Where the in-flight population is sitting, and how much of it is off track"
          actions={<Legend items={[{ name: 'On track', color: CATEGORICAL[0] }, { name: 'At risk / breached', color: STATUS.warning }]} />}
        >
          <ResponsiveContainer width="100%" height={264}>
            <BarChart
              data={data.pipeline.map((p) => ({ ...p, on_track: Math.max(0, p.count - p.at_risk) }))}
              layout="vertical"
              margin={{ top: 4, right: 42, left: 8, bottom: 4 }}
              barCategoryGap="28%"
            >
              <CartesianGrid {...GRID} horizontal={false} vertical />
              <XAxis type="number" allowDecimals={false} {...AXIS} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="label" width={116} {...AXIS} axisLine={false} tickLine={false} />
              <Tooltip
                cursor={{ fill: '#161f3d55' }}
                content={({ active, payload, label }) => (
                  <ChartTooltip
                    active={active}
                    label={label as string}
                    rows={[
                      { name: 'On track', value: num(payload?.[0]?.value as number, 0), color: CATEGORICAL[0] },
                      { name: 'At risk', value: num(payload?.[1]?.value as number, 0), color: STATUS.warning },
                      { name: 'Value', value: money((payload?.[0]?.payload as { value: number })?.value) },
                    ]}
                  />
                )}
              />
              {/* 2px surface gap between touching segments */}
              <Bar dataKey="on_track" stackId="s" fill={CATEGORICAL[0]} barSize={18} stroke={SURFACE_GAP} strokeWidth={1} />
              <Bar dataKey="at_risk" stackId="s" fill={STATUS.warning} barSize={18} radius={[0, 4, 4, 0]} stroke={SURFACE_GAP} strokeWidth={1} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        {/* ---- HITL scoreboard ---- */}
        <Panel title="Human-in-the-loop scoreboard" subtitle="How the team is responding to agent proposals">
          <div className="grid grid-cols-2 gap-x-5 gap-y-4">
            <Mini label="Decisions made" value={num(data.hitl.decided, 0)} />
            <Mini label="Acceptance rate" value={data.hitl.acceptance_rate === null ? '—' : pct(data.hitl.acceptance_rate)} tone="text-mint" />
            <Mini label="Approved as proposed" value={num(data.hitl.approved, 0)} />
            <Mini label="Modified before approving" value={num(data.hitl.modified, 0)} tone="text-amber" />
            <Mini label="Rejected" value={num(data.hitl.rejected, 0)} tone="text-rose" />
            <Mini label="Median review time" value={data.hitl.avg_review_minutes ? `${num(data.hitl.avg_review_minutes)}m` : '—'} />
          </div>

          <div className="mt-5 border-t border-ink-800 pt-4">
            <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
              Open checkpoints by risk
            </p>
            <div className="space-y-1.5">
              {(['critical', 'high', 'medium', 'low'] as const).map((level) => {
                const count = data.hitl.by_risk[level] ?? 0
                const total = Math.max(1, data.hitl.pending)
                return (
                  <div key={level} className="flex items-center gap-2.5">
                    <span className="w-14 text-[11px] capitalize text-slate-400">{level}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-800">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(count / total) * 100}%`,
                          background: level === 'low' ? STATUS.good : level === 'medium' ? STATUS.warning : STATUS.serious,
                        }}
                      />
                    </div>
                    <span className="w-6 text-right text-[11.5px] tabular-nums text-slate-300">{count}</span>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="mt-4 border-t border-ink-800 pt-4">
            <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
              Waiting on which role
            </p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(data.hitl.by_role).map(([role, count]) => (
                <Chip key={role} tone="slate">{titleCase(role)} · {count}</Chip>
              ))}
              {Object.keys(data.hitl.by_role).length === 0 && <span className="subtle">Nothing pending</span>}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-3">
        {/* ---- Trend: one measure at a time, never a second y-axis ---- */}
        <Panel
          className="xl:col-span-2"
          title={measure.label}
          subtitle="Last 14 days of settled invoices"
          actions={
            <div className="flex gap-1">
              {TREND_MEASURES.map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMeasure(m)}
                  className={`rounded-md px-2 py-1 text-[11px] transition-colors ${
                    measure.key === m.key ? 'bg-accent/15 font-medium text-accent-soft' : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          }
        >
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={data.trend} margin={{ top: 10, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid {...GRID} />
              <XAxis
                dataKey="date"
                {...AXIS}
                axisLine={false}
                tickLine={false}
                tickFormatter={(d: string) => d.slice(5).replace('-', '/')}
              />
              <YAxis {...AXIS} axisLine={false} tickLine={false} width={44} />
              {'target' in measure && measure.target !== undefined && (
                <ReferenceLine
                  y={measure.target}
                  stroke="#7f8db0"
                  strokeWidth={1}
                  label={{ value: `target ${measure.target}${measure.unit}`, fill: '#7f8db0', fontSize: 10, position: 'insideTopRight' }}
                />
              )}
              <Tooltip
                cursor={{ stroke: '#3d4f80', strokeWidth: 1 }}
                content={({ active, payload, label }) => (
                  <ChartTooltip
                    active={active}
                    label={label as string}
                    rows={[{
                      name: measure.label,
                      value: payload?.[0]?.value === null || payload?.[0]?.value === undefined
                        ? 'no activity'
                        : measure.fmt(payload[0].value as number),
                      color: CATEGORICAL[0],
                    }]}
                  />
                )}
              />
              <Line
                type="monotone"
                dataKey={measure.key}
                stroke={CATEGORICAL[0]}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                connectNulls
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE_GAP, fill: CATEGORICAL[0] }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        {/* ---- Aging: ordered magnitude, single sequential hue ---- */}
        <Panel title="Invoice aging" subtitle="In-flight population by time since receipt">
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={data.aging} margin={{ top: 18, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid {...GRID} />
              <XAxis dataKey="bucket" {...AXIS} axisLine={false} tickLine={false} />
              <YAxis {...AXIS} axisLine={false} tickLine={false} width={30} allowDecimals={false} />
              <Tooltip
                cursor={{ fill: '#161f3d55' }}
                content={({ active, payload, label }) => (
                  <ChartTooltip
                    active={active}
                    label={label as string}
                    rows={[
                      { name: 'Invoices', value: num(payload?.[0]?.value as number, 0), color: SEQUENTIAL[2] },
                      { name: 'Value', value: money((payload?.[0]?.payload as { value: number })?.value) },
                    ]}
                  />
                )}
              />
              <Bar dataKey="count" barSize={24} radius={[4, 4, 0, 0]}>
                {data.aging.map((_, i) => (
                  <Cell key={i} fill={SEQUENTIAL[Math.min(i, SEQUENTIAL.length - 1)]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="subtle mt-1">Older buckets are darker — the tail is where SLA is lost.</p>
        </Panel>
      </div>
    </div>
  )
}

const SURFACE_GAP = '#0c1120'

function StatTile({ label, value, sub, tone = 'text-slate-100' }: {
  label: string; value: string; sub?: string; tone?: string
}) {
  return (
    <div className="panel p-4">
      <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="subtle mt-1">{sub}</p>}
    </div>
  )
}

function Mini({ label, value, tone = 'text-slate-100' }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[10.5px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}
