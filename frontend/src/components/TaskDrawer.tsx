import { useEffect, useMemo, useState } from 'react'
import { HumanTask, api } from '../lib/api'
import { confidencePct, dateTime, money, titleCase } from '../lib/format'
import { useSession } from '../store'
import { Chip, Confidence, Drawer, KeyValue, RiskChip, Spinner } from './ui'

const DECISIONS = [
  { key: 'approve', label: 'Approve & apply', tone: 'btn-mint' },
  { key: 'modify_and_approve', label: 'Modify & approve', tone: 'btn-primary' },
  { key: 'escalate', label: 'Escalate', tone: 'btn-ghost' },
  { key: 'request_info', label: 'Request info', tone: 'btn-ghost' },
  { key: 'reject', label: 'Reject', tone: 'btn-danger' },
] as const

type Decision = (typeof DECISIONS)[number]['key']

export default function TaskDrawer({
  taskId, open, onClose,
}: { taskId: string | null; open: boolean; onClose: () => void }) {
  const { refresh, notify, user } = useSession()
  const [task, setTask] = useState<HumanTask | null>(null)
  const [loading, setLoading] = useState(false)
  const [decision, setDecision] = useState<Decision>('approve')
  const [notes, setNotes] = useState('')
  const [edits, setEdits] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<'proposal' | 'reasoning' | 'policy'>('proposal')

  useEffect(() => {
    if (!taskId || !open) return
    setLoading(true)
    setNotes('')
    setDecision('approve')
    setTab('proposal')
    api
      .get<HumanTask>(`/hitl/tasks/${taskId}`)
      .then((t) => {
        setTask(t)
        setEdits(JSON.stringify(t.proposed_payload ?? {}, null, 2))
      })
      .catch((e) => notify((e as Error).message, 'rose'))
      .finally(() => setLoading(false))
  }, [taskId, open, notify])

  const verdict = useMemo(
    () => task?.execution?.policy_evaluation?.proposals?.find((p) => p.action === task.action_kind),
    [task],
  )

  async function submit() {
    if (!task) return
    if ((decision === 'reject' || decision === 'request_info') && !notes.trim()) {
      notify('A written reason is required to reject or request information.', 'rose')
      return
    }
    let modified: Record<string, unknown> | undefined
    if (decision === 'modify_and_approve') {
      try {
        modified = JSON.parse(edits)
      } catch {
        notify('The modified payload is not valid JSON.', 'rose')
        return
      }
    }
    setBusy(true)
    try {
      const res = await api.post<{ status: string }>(`/hitl/tasks/${task.id}/decide`, {
        decision, notes: notes.trim() || null, modified_payload: modified ?? null,
      })
      notify(
        res.status === 'awaiting_second_approval'
          ? 'First approval recorded — a second, different approver is required.'
          : `${task.task_number} ${titleCase(decision)}d and written to the audit trail.`,
        decision === 'reject' ? 'rose' : 'mint',
      )
      refresh()
      onClose()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  const decidable = task?.can_decide !== false
  const settled = task && task.status !== 'pending'

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={task ? task.title : 'Checkpoint'}
      subtitle={
        task && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone="violet">{task.agent_name}</Chip>
            <Chip tone="slate">{task.task_number}</Chip>
            <RiskChip level={task.risk_level} />
            {!task.reversible && <Chip tone="rose">Irreversible</Chip>}
            {task.dual_approval_required && <Chip tone="amber">Dual approval</Chip>}
            <Chip tone={decidable ? 'mint' : 'rose'}>Requires {task.required_role_label}</Chip>
          </div>
        )
      }
      footer={
        task && !settled ? (
          <div className="space-y-2.5">
            {!decidable && (
              <p className="rounded-lg border border-rose/30 bg-rose/10 px-3 py-2 text-[12px] text-rose">
                You are signed in as {user?.role_label}. This decision requires{' '}
                {task.required_role_label} authority or above — switch persona to act on it.
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {DECISIONS.map((d) => (
                <button
                  key={d.key}
                  onClick={() => setDecision(d.key)}
                  className={`${d.tone} ${decision === d.key ? 'ring-2 ring-accent/60' : 'opacity-70'}`}
                  disabled={!decidable}
                >
                  {d.label}
                </button>
              ))}
            </div>
            <textarea
              className="field h-[52px] resize-none"
              placeholder={
                decision === 'reject' || decision === 'request_info'
                  ? 'Required: why are you rejecting or what do you need?'
                  : 'Optional note for the audit trail…'
              }
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
            <div className="flex items-center justify-between gap-3">
              <p className="subtle">
                Your name, role, reason and the resulting state change are written to the immutable audit log.
              </p>
              <button className="btn-primary shrink-0" onClick={submit} disabled={busy || !decidable}>
                {busy ? 'Applying…' : `Submit ${titleCase(decision)}`}
              </button>
            </div>
          </div>
        ) : task ? (
          <div className="flex items-center justify-between gap-3">
            <p className="text-[12.5px] text-slate-300">
              <span className="font-semibold text-slate-100">{titleCase(task.decision ?? task.status)}</span>
              {' by '}{task.decided_by} · {dateTime(task.decided_at)}
              {task.decision_notes && <span className="text-slate-400"> — “{task.decision_notes}”</span>}
            </p>
            <Chip tone={task.status === 'rejected' ? 'rose' : 'mint'}>{titleCase(task.status)}</Chip>
          </div>
        ) : null
      }
    >
      {loading && <Spinner label="Loading checkpoint…" />}
      {task && !loading && (
        <div className="space-y-4">
          {/* Header facts */}
          <div className="panel p-4">
            <KeyValue
              items={[
                ['Proposed action', <span className="font-medium text-accent-soft">{task.action_label}</span>],
                ['Subject', task.entity_label ?? '—'],
                ['Financial impact', <span className="tabular-nums">{money(task.financial_impact_usd)}</span>],
                ['Stage', task.stage_label],
                ['Agent confidence', <Confidence value={task.confidence} />],
                ['Review due', dateTime(task.due_at)],
              ]}
            />
          </div>

          {/* Why this stopped here — the governance answer */}
          <div className="rounded-xl border border-amber/25 bg-amber/[0.06] p-3.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber">
              Why a human is deciding this
            </p>
            <ul className="mt-1.5 space-y-1">
              {(verdict?.blocked_reasons ?? [task.auto_blocked_reason ?? 'Policy requires review.']).map((r, i) => (
                <li key={i} className="flex gap-2 text-[12px] leading-snug text-slate-300">
                  <span className="text-amber">•</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex gap-1 border-b border-ink-700">
            {(['proposal', 'reasoning', 'policy'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`-mb-px border-b-2 px-3 py-1.5 text-[12px] font-medium capitalize transition-colors ${
                  tab === t
                    ? 'border-accent text-accent-soft'
                    : 'border-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {t === 'reasoning' ? 'Agent reasoning' : t === 'policy' ? 'Policy & audit' : 'Proposal'}
              </button>
            ))}
          </div>

          {tab === 'proposal' && (
            <div className="space-y-4">
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Summary</p>
                <p className="text-[13px] leading-relaxed text-slate-200">{task.summary}</p>
              </div>

              {task.diff_preview?.length > 0 && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    What changes if you approve
                  </p>
                  <div className="overflow-hidden rounded-lg border border-ink-700">
                    <table className="w-full">
                      <thead className="bg-ink-850/70">
                        <tr>
                          <th className="th">Field</th>
                          <th className="th">Current</th>
                          <th className="th">Proposed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {task.diff_preview.map((d, i) => (
                          <tr key={i} className="table-row last:border-0">
                            <td className="td text-slate-400">{d.label ?? d.field}</td>
                            <td className="td text-slate-500 line-through decoration-rose/50">
                              {String(d.before ?? '—').slice(0, 120)}
                            </td>
                            <td className="td font-medium text-mint">{String(d.after ?? '—').slice(0, 200)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {task.alternatives && task.alternatives.length > 0 && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Options the agent considered
                  </p>
                  <div className="space-y-1.5">
                    {task.alternatives.map((alt, i) => (
                      <div key={i} className="flex items-start gap-3 rounded-lg border border-ink-700 bg-ink-850/50 p-2.5">
                        <span className={`chip ${i === 0 ? 'border-mint/35 bg-mint/10 text-mint' : 'border-slate-600/30 bg-slate-600/10 text-slate-400'}`}>
                          {i === 0 ? 'recommended' : `alt ${i}`}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[12.5px] font-medium text-slate-200">{titleCase(alt.option)}</p>
                          {alt.detail && <p className="subtle mt-0.5">{alt.detail}</p>}
                        </div>
                        {alt.impact_usd !== undefined && alt.impact_usd !== 0 && (
                          <span className={`mono shrink-0 tabular-nums ${alt.impact_usd < 0 ? 'text-mint' : 'text-amber'}`}>
                            {alt.impact_usd > 0 ? '+' : ''}{money(alt.impact_usd)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {decision === 'modify_and_approve' && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Edit the payload before applying
                  </p>
                  <textarea
                    className="field mono h-44 resize-y"
                    value={edits}
                    onChange={(e) => setEdits(e.target.value)}
                    spellCheck={false}
                  />
                </div>
              )}

              {/* When there is no field diff to show, the evidence is what the
                  reviewer needs in front of them — don't make them switch tabs. */}
              {!task.diff_preview?.length && !task.alternatives?.length && task.evidence?.length ? (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Evidence behind this proposal
                  </p>
                  <div className="overflow-hidden rounded-lg border border-ink-700">
                    <table className="w-full">
                      <tbody>
                        {task.evidence.map((e, i) => (
                          <tr key={i} className="table-row last:border-0">
                            <td className="td w-1/3 text-slate-400">{e.label}</td>
                            <td className="td text-slate-200">{String(e.detail)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              {task.execution_result && Object.keys(task.execution_result).length > 0 && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Applied result
                  </p>
                  <pre className="mono overflow-x-auto rounded-lg border border-mint/25 bg-mint/[0.05] p-3 text-mint">
                    {JSON.stringify(task.execution_result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}

          {tab === 'reasoning' && (
            <div className="space-y-4">
              {task.execution?.plan && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Plan</p>
                  <ol className="space-y-1.5">
                    {task.execution.plan.map((s) => (
                      <li key={s.step} className="flex gap-2.5 rounded-lg border border-ink-800 bg-ink-850/40 p-2.5">
                        <span className="mono grid h-5 w-5 shrink-0 place-items-center rounded bg-ink-700 text-slate-400">
                          {s.step}
                        </span>
                        <div className="min-w-0">
                          <p className="text-[12.5px] text-slate-200">{s.action}</p>
                          <p className="subtle mt-0.5">
                            <span className="mono text-accent-soft">{s.tool}</span> — {s.rationale}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {task.execution?.observations && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Tool observations
                  </p>
                  <div className="space-y-1.5">
                    {task.execution.observations.map((o, i) => (
                      <div key={i} className="rounded-lg border border-ink-800 bg-ink-850/40 p-2.5">
                        <div className="flex items-center gap-2">
                          <span className={`h-1.5 w-1.5 rounded-full ${o.ok ? 'bg-mint' : 'bg-amber'}`} />
                          <span className="mono text-accent-soft">{o.tool}</span>
                        </div>
                        <p className="mt-1 text-[12.5px] leading-snug text-slate-300">{o.summary}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {task.evidence && task.evidence.length > 0 && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Evidence cited
                  </p>
                  <div className="overflow-hidden rounded-lg border border-ink-700">
                    <table className="w-full">
                      <tbody>
                        {task.evidence.map((e, i) => (
                          <tr key={i} className="table-row last:border-0">
                            <td className="td w-1/3 text-slate-400">{e.label}</td>
                            <td className="td text-slate-200">{String(e.detail)}</td>
                            <td className="td mono w-1/4 text-slate-500">{e.source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {task.rationale && (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    Narrative rationale
                    <span className="ml-2 font-normal normal-case tracking-normal text-slate-600">
                      engine: {task.execution?.reasoning_engine ?? 'deterministic'}
                    </span>
                  </p>
                  <pre className="whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-950/60 p-3 text-[12px] leading-relaxed text-slate-300">
                    {task.rationale}
                  </pre>
                </div>
              )}
            </div>
          )}

          {tab === 'policy' && (
            <div className="space-y-4">
              <div className="panel p-4">
                <KeyValue
                  items={[
                    ['Reversible', task.reversible ? 'Yes' : 'No — cannot be undone'],
                    ['Auto-execution eligible', task.auto_eligible ? 'Yes' : 'No'],
                    ['Required authority', task.required_role_label],
                    ['Dual approval', task.dual_approval_required ? 'Required' : 'Not required'],
                    ['Confidence vs floor', confidencePct(task.confidence)],
                    ['Policy flags', task.policy_flags?.length ? task.policy_flags.join(', ') : 'none'],
                  ]}
                />
              </div>
              {verdict && (
                <>
                  <div>
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-mint">
                      Gates that opened
                    </p>
                    <ul className="space-y-1">
                      {verdict.reasons.map((r, i) => (
                        <li key={i} className="flex gap-2 text-[12px] text-slate-300">
                          <span className="text-mint">✓</span>{r}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-rose">
                      Gates that held it
                    </p>
                    <ul className="space-y-1">
                      {verdict.blocked_reasons.map((r, i) => (
                        <li key={i} className="flex gap-2 text-[12px] text-slate-300">
                          <span className="text-rose">✕</span>{r}
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              )}
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Exact payload to be applied
                </p>
                <pre className="mono overflow-x-auto rounded-lg border border-ink-700 bg-ink-950/60 p-3 text-slate-400">
                  {JSON.stringify(task.proposed_payload ?? {}, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </Drawer>
  )
}
