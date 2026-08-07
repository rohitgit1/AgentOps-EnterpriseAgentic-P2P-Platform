import { useState } from 'react'
import { Chip, Confidence, Drawer, Empty, KeyValue, Panel, Spinner } from '../components/ui'
import { AgentRun, api } from '../lib/api'
import { money, relative, titleCase } from '../lib/format'
import { useApi, useSession } from '../store'

type AgentCard = {
  agent_key: string; display_name: string; enabled: boolean
  autonomy_level: string; autonomy_label: string; confidence_threshold: number
  max_auto_amount_usd: number; require_dual_approval_above_usd: number
  escalation_role: string; role: string; mission: string; goals: string[]
  tools: string[]; skills: string[]; prompt: string; allowed_actions: string[]
  runs_total: number; proposals_total: number; approved_total: number
  rejected_total: number; modified_total: number; acceptance_rate: number | null
  last_run: AgentRun | null; health: string
}

type Fleet = {
  fleet_paused: boolean; global_hitl_enforced: boolean; confidence_floor: number
  agents_total: number; agents_enabled: number
  autonomy_distribution: Record<string, number>
  reasoning_engine: { active_engine: string; model: string; offline_capable: boolean; note: string }
  erp_connectors: { system: string; status: string; mode: string; latency_ms: number }[]
  executable_actions: string[]
  recent_runs: AgentRun[]
}

const AUTONOMY = [
  { key: 'observe_only', label: 'L0 · Observe Only', hint: 'Analyse and report; never propose an action.' },
  { key: 'suggest', label: 'L1 · Suggest', hint: 'Propose; a human must act on every item.' },
  { key: 'human_approval', label: 'L2 · Human Approval', hint: 'Propose with a staged payload; a human approves. Default.' },
  { key: 'auto_within_guardrails', label: 'L3 · Auto within Guardrails', hint: 'Auto-execute only inside the policy envelope. Irreversible actions still stop.' },
  { key: 'full_auto', label: 'L4 · Full Auto', hint: 'Disabled while global HITL enforcement is on.' },
]

export default function Agents() {
  const { notify, refresh, user } = useSession()
  const { data: agents, loading } = useApi<AgentCard[]>('/agents')
  const { data: fleet } = useApi<Fleet>('/agents/status')
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const selected = agents?.find((a) => a.agent_key === openKey) ?? null

  async function patch(key: string, body: Record<string, unknown>) {
    setBusy(true)
    try {
      await api.patch(`/agents/${key}/config`, body)
      notify('Agent governance updated and recorded in the audit trail.', 'mint')
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  async function run(key: string, name: string) {
    setBusy(true)
    try {
      const res = await api.post<{ checkpoints: unknown[] }>(`/agents/${key}/run`, {})
      notify(`${name} ran — ${res.checkpoints.length} proposal(s) queued for review.`, 'accent')
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  async function killSwitch(paused: boolean) {
    try {
      await api.post(`/orchestrator/kill-switch?paused=${paused}`)
      notify(paused ? 'Agent fleet paused. No agent will run until resumed.' : 'Agent fleet resumed.', paused ? 'rose' : 'mint')
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    }
  }

  if (loading) return <Spinner label="Loading the agent fleet…" />

  return (
    <div className="space-y-4">
      {/* Fleet governance bar */}
      {fleet && (
        <div className="panel flex flex-wrap items-center gap-x-7 gap-y-3 px-4 py-3.5">
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-slate-100">Agent Control Room</p>
            <p className="subtle mt-0.5">{fleet.reasoning_engine.note}</p>
          </div>
          <Fact label="Reasoning engine" value={fleet.reasoning_engine.active_engine} sub={fleet.reasoning_engine.model} />
          <Fact label="HITL enforcement" value={fleet.global_hitl_enforced ? 'ON' : 'OFF'} tone={fleet.global_hitl_enforced ? 'text-mint' : 'text-rose'} />
          <Fact label="Confidence floor" value={`${Math.round(fleet.confidence_floor * 100)}%`} />
          <Fact label="Executable actions" value={String(fleet.executable_actions.length)} sub="explicit allow-list" />
          <button
            className={fleet.fleet_paused ? 'btn-mint' : 'btn-danger'}
            onClick={() => killSwitch(!fleet.fleet_paused)}
            disabled={user?.role !== 'admin'}
            title={user?.role !== 'admin' ? 'Platform Admin only' : ''}
          >
            {fleet.fleet_paused ? '▶ Resume fleet' : '■ Pause all agents'}
          </button>
        </div>
      )}

      {fleet?.fleet_paused && (
        <div className="rounded-lg border border-rose/40 bg-rose/10 px-4 py-2.5 text-[12.5px] text-rose">
          <strong>Kill switch engaged.</strong> Every agent is halted. Existing checkpoints remain decidable.
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {agents?.map((a) => (
          <div key={a.agent_key} className="panel flex flex-col p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-[13.5px] font-semibold text-slate-100">{a.display_name}</p>
                <p className="subtle mt-0.5 line-clamp-2">{a.role}</p>
              </div>
              <span className={`h-2 w-2 shrink-0 rounded-full ${a.enabled ? 'bg-mint' : 'bg-slate-600'}`} title={a.health} />
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              <Chip tone={a.autonomy_level === 'human_approval' ? 'accent' : a.autonomy_level === 'auto_within_guardrails' ? 'amber' : 'slate'}>
                {a.autonomy_label}
              </Chip>
              <Chip tone="slate">≥{Math.round(a.confidence_threshold * 100)}% conf</Chip>
              <Chip tone="slate">escalates to {titleCase(a.escalation_role)}</Chip>
            </div>

            <div className="mt-3 grid grid-cols-4 gap-2 border-y border-ink-800 py-2.5 text-center">
              <Metric label="Runs" value={a.runs_total} />
              <Metric label="Proposed" value={a.proposals_total} />
              <Metric label="Approved" value={a.approved_total} tone="text-mint" />
              <Metric label="Rejected" value={a.rejected_total} tone="text-rose" />
            </div>

            {a.last_run && (
              <p className="mt-2.5 line-clamp-2 text-[11.5px] leading-snug text-slate-400">
                <span className="text-slate-500">Last:</span> {a.last_run.conclusion}
              </p>
            )}

            <div className="mt-auto flex gap-1.5 pt-3">
              <button className="btn-ghost flex-1" onClick={() => setOpenKey(a.agent_key)}>Configure</button>
              <button className="btn-primary" onClick={() => run(a.agent_key, a.display_name)} disabled={busy || !a.enabled}>
                Run
              </button>
            </div>
          </div>
        ))}
      </div>

      {fleet && (
        <Panel title="Recent agent runs" subtitle="Every run is recorded with its plan, evidence and confidence" bodyClass="">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="border-b border-ink-700">
                <tr>
                  <th className="th">Run</th><th className="th">Agent</th><th className="th">Subject</th>
                  <th className="th">Conclusion</th><th className="th">Confidence</th><th className="th">Status</th><th className="th">When</th>
                </tr>
              </thead>
              <tbody>
                {fleet.recent_runs.map((r) => (
                  <tr key={r.id} className="table-row">
                    <td className="td mono text-slate-500">{r.run_number}</td>
                    <td className="td"><Chip tone="violet">{r.agent_name}</Chip></td>
                    <td className="td text-slate-300">{r.entity_label ?? '—'}</td>
                    <td className="td max-w-[380px] truncate text-slate-400">{r.conclusion}</td>
                    <td className="td"><Confidence value={r.confidence} /></td>
                    <td className="td">
                      <Chip tone={r.status === 'awaiting_human' ? 'amber' : r.status === 'completed' ? 'mint' : 'slate'}>
                        {titleCase(r.status)}
                      </Chip>
                    </td>
                    <td className="td text-slate-500">{relative(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {/* Config drawer */}
      <Drawer
        open={Boolean(selected)}
        onClose={() => setOpenKey(null)}
        title={selected?.display_name ?? ''}
        subtitle={selected && <Chip tone="accent">{selected.autonomy_label}</Chip>}
      >
        {selected && (
          <div className="space-y-4">
            <div className="panel p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Mission</p>
              <p className="mt-1 text-[13px] leading-relaxed text-slate-200">{selected.mission}</p>
              <ul className="mt-3 space-y-1">
                {selected.goals.map((g, i) => (
                  <li key={i} className="flex gap-2 text-[12px] text-slate-400"><span className="text-accent">›</span>{g}</li>
                ))}
              </ul>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Autonomy level</p>
              <div className="space-y-1.5">
                {AUTONOMY.map((level) => {
                  const active = selected.autonomy_level === level.key
                  const locked = level.key === 'full_auto'
                  return (
                    <button
                      key={level.key}
                      disabled={busy || locked}
                      onClick={() => patch(selected.agent_key, { autonomy_level: level.key })}
                      className={`flex w-full items-start gap-3 rounded-lg border p-2.5 text-left transition-colors ${
                        active ? 'border-accent/50 bg-accent/10' : 'border-ink-700 bg-ink-850/40 hover:bg-ink-800'
                      } ${locked ? 'opacity-40' : ''}`}
                    >
                      <span className={`mt-0.5 h-3 w-3 shrink-0 rounded-full border-2 ${active ? 'border-accent bg-accent' : 'border-ink-600'}`} />
                      <span className="min-w-0">
                        <span className="block text-[12.5px] font-medium text-slate-200">{level.label}</span>
                        <span className="block text-[11.5px] text-slate-500">{level.hint}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
              <p className="subtle mt-2">
                Raising an agent above L2 requires Controller authority, and irreversible actions
                (ERP posting, payment release, supplier messages) always stop for a person regardless of level.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Confidence threshold
                </span>
                <input
                  type="range" min={0.5} max={1} step={0.01}
                  defaultValue={selected.confidence_threshold}
                  onMouseUp={(e) => patch(selected.agent_key, { confidence_threshold: Number((e.target as HTMLInputElement).value) })}
                  className="w-full"
                />
                <span className="subtle">{Math.round(selected.confidence_threshold * 100)}% — below this, always a human</span>
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Auto-execution ceiling
                </span>
                <input
                  type="number" className="field" defaultValue={selected.max_auto_amount_usd}
                  onBlur={(e) => patch(selected.agent_key, { max_auto_amount_usd: Number(e.target.value) })}
                />
                <span className="subtle">{money(selected.max_auto_amount_usd)} maximum financial impact</span>
              </label>
            </div>

            <div className="panel p-4">
              <KeyValue items={[
                ['Skills used', selected.skills.join(', ')],
                ['Tools', selected.tools.join(', ')],
                ['Permitted actions', String(selected.allowed_actions.length)],
                ['Acceptance rate', selected.acceptance_rate === null ? 'no decisions yet' : `${selected.acceptance_rate}%`],
                ['Modified before approval', String(selected.modified_total)],
                ['Dual approval above', money(selected.require_dual_approval_above_usd)],
              ]} />
            </div>

            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                System prompt
              </p>
              <pre className="mono whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/60 p-3 text-slate-400">
                {selected.prompt}
              </pre>
            </div>

            <button
              className={selected.enabled ? 'btn-danger w-full' : 'btn-mint w-full'}
              onClick={() => patch(selected.agent_key, { enabled: !selected.enabled })}
              disabled={busy}
            >
              {selected.enabled ? 'Disable this agent' : 'Enable this agent'}
            </button>
          </div>
        )}
      </Drawer>
    </div>
  )
}

function Fact({ label, value, sub, tone = 'text-slate-100' }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-[13.5px] font-semibold ${tone}`}>{value}</p>
      {sub && <p className="text-[10.5px] text-slate-600">{sub}</p>}
    </div>
  )
}

function Metric({ label, value, tone = 'text-slate-200' }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <p className={`text-[15px] font-semibold tabular-nums ${tone}`}>{value}</p>
      <p className="text-[9.5px] uppercase tracking-wider text-slate-600">{label}</p>
    </div>
  )
}
