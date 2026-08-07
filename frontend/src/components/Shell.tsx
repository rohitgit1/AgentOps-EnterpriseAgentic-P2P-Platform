import { ReactNode, useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useApi, useSession } from '../store'
import { api } from '../lib/api'
import { relative } from '../lib/format'
import { Chip, Toast } from './ui'

const NAV = [
  { section: 'Operate', items: [
    { to: '/', label: 'Command Center', icon: '◈', end: true },
    { to: '/inbox', label: 'Approval Inbox', icon: '⧉', badge: 'hitl' },
    { to: '/invoices', label: 'Invoices', icon: '▤' },
    { to: '/exceptions', label: 'Exceptions', icon: '⚠' },
    { to: '/approvals', label: 'My Approvals', icon: '✓' },
    { to: '/payments', label: 'Payments', icon: '⇄' },
  ]},
  { section: 'Intelligence', items: [
    { to: '/agents', label: 'Agent Control Room', icon: '⬢' },
    { to: '/sla', label: 'SLA Command Center', icon: '◔' },
    { to: '/suppliers', label: 'Suppliers', icon: '⬡' },
    { to: '/skills', label: 'Skills Library', icon: '❋' },
  ]},
  { section: 'Assurance', items: [
    { to: '/audit', label: 'Audit Trail', icon: '⛓' },
    { to: '/governance', label: 'Governance', icon: '⚖' },
  ]},
]

export default function Shell({ children }: { children: ReactNode }) {
  const { user, personas, signIn, signOut, connected, events, toast, clearToast, refresh, notify } = useSession()
  const { data: summary } = useApi<{ pending_for_me: number; pending_total: number }>('/hitl/summary')
  const [switching, setSwitching] = useState(false)
  const [busy, setBusy] = useState(false)
  const location = useLocation()

  useEffect(() => {
    if (!switching) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setSwitching(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [switching])

  async function runSweep() {
    setBusy(true)
    try {
      const res = await api.post<{ runs: number; checkpoints: number }>('/orchestrator/sweep')
      notify(`Fleet sweep: ${res.runs} agent runs → ${res.checkpoints} decisions awaiting review`, 'accent')
      refresh()
    } catch (e) {
      notify((e as Error).message, 'rose')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* ---------------- Sidebar ---------------- */}
      <nav className="hidden w-[236px] shrink-0 flex-col border-r border-ink-800 bg-ink-900/60 lg:flex">
        <div className="flex items-center gap-2.5 border-b border-ink-800 px-4 py-4">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-violet text-[15px] font-bold text-white">
            ◈
          </span>
          <div className="leading-tight">
            <p className="text-[13.5px] font-semibold text-slate-100">P2P AgentOps</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Procure-to-Pay</p>
          </div>
        </div>

        <div className="scroll-thin flex-1 overflow-y-auto px-2.5 py-3">
          {NAV.map((group) => (
            <div key={group.section} className="mb-4">
              <p className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                {group.section}
              </p>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12.5px] transition-colors ${
                      isActive
                        ? 'bg-accent/12 font-semibold text-accent-soft ring-1 ring-inset ring-accent/25'
                        : 'text-slate-400 hover:bg-ink-850 hover:text-slate-200'
                    }`
                  }
                >
                  <span className="w-4 text-center text-[13px] opacity-80">{item.icon}</span>
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.badge === 'hitl' && (summary?.pending_for_me ?? 0) > 0 && (
                    <span className="rounded-full bg-amber px-1.5 py-px text-[10px] font-bold text-ink-950">
                      {summary?.pending_for_me}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </div>

        <div className="border-t border-ink-800 px-3 py-3">
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'animate-ping2 bg-mint' : 'bg-slate-600'}`} />
            {connected ? 'Live event stream' : 'Stream offline'}
            <span className="ml-auto tabular-nums">{events.length}</span>
          </div>
        </div>
      </nav>

      {/* ---------------- Main ---------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/*
          `relative z-40` is load-bearing, not decoration. `backdrop-blur` puts a
          backdrop-filter on this header, which creates a stacking context — so
          the persona dropdown's own z-index is confined inside it. While the
          header stayed non-positioned, its whole subtree painted in the block
          layer and <main>, a later sibling, painted straight over the open menu.
          Positioning the header lifts the entire subtree above main and the
          activity rail. Overlay order: header 40 < Drawer 50 < Toast 60.
        */}
        <header className="relative z-40 flex items-center gap-3 border-b border-ink-800 bg-ink-900/50 px-4 py-2.5 backdrop-blur">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-slate-100">
              {NAV.flatMap((g) => g.items).find((i) => i.to === location.pathname)?.label ?? 'P2P AgentOps'}
            </p>
            <p className="subtle truncate">
              Human-in-the-loop enforced · agents propose, qualified people decide
            </p>
          </div>

          <button className="btn-ghost" onClick={runSweep} disabled={busy}>
            {busy ? 'Running…' : '▶ Run agent sweep'}
          </button>

          {summary && (
            <Chip tone={summary.pending_for_me ? 'amber' : 'slate'}>
              {summary.pending_for_me} for you / {summary.pending_total} open
            </Chip>
          )}

          {/* Persona switcher — central to the HITL story */}
          <div className="relative">
            <button
              onClick={() => setSwitching((s) => !s)}
              className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-850/70 py-1 pl-1 pr-2.5 text-left hover:bg-ink-800"
            >
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent/20 text-[11px] font-bold text-accent-soft">
                {user?.initials}
              </span>
              <span className="leading-tight">
                <span className="block text-[12px] font-medium text-slate-200">{user?.full_name}</span>
                <span className="block text-[10px] text-slate-500">{user?.role_label}</span>
              </span>
              <span className="text-slate-500">▾</span>
            </button>

            {switching && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setSwitching(false)} />
                <div
                  role="menu"
                  className="absolute right-0 top-full z-50 mt-1.5 max-h-[min(560px,calc(100vh-4rem))] w-[330px]
                             overflow-y-auto rounded-xl border border-ink-700 bg-ink-900 p-1.5 shadow-lift scroll-thin"
                >
                  <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Switch persona — authority changes with the role
                  </p>
                  {personas.map((p) => (
                    <button
                      key={p.id}
                      role="menuitem"
                      onClick={() => { signIn(p); setSwitching(false) }}
                      className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-ink-850 ${
                        p.id === user?.id ? 'bg-ink-850 ring-1 ring-inset ring-accent/30' : ''
                      }`}
                    >
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-ink-700 text-[10.5px] font-bold text-slate-300">
                        {p.initials}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12.5px] font-medium text-slate-200">
                          {p.full_name} {p.out_of_office && <span className="text-amber">· OOO</span>}
                        </span>
                        <span className="block truncate text-[11px] text-slate-500">{p.blurb ?? p.title}</span>
                      </span>
                      {p.id === user?.id && <span className="mt-1 shrink-0 text-[11px] text-accent-soft">✓</span>}
                    </button>
                  ))}

                  <div className="mt-1.5 border-t border-ink-800 pt-1.5">
                    <button
                      role="menuitem"
                      onClick={() => { setSwitching(false); signOut() }}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-slate-400 hover:bg-ink-850 hover:text-rose"
                    >
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-ink-800 text-[12px]">⏻</span>
                      <span className="text-[12.5px] font-medium">Sign out</span>
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="scroll-thin flex-1 overflow-y-auto p-4 lg:p-5">{children}</main>
      </div>

      {/* ---------------- Live rail ---------------- */}
      <aside className="hidden w-[280px] shrink-0 flex-col border-l border-ink-800 bg-ink-900/40 xl:flex">
        <div className="flex items-center justify-between border-b border-ink-800 px-3.5 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Live activity</p>
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'animate-ping2 bg-mint' : 'bg-slate-600'}`} />
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto px-2.5 py-2.5">
          {events.length === 0 && (
            <p className="px-2 py-6 text-center text-[11.5px] text-slate-600">
              Waiting for agent activity…
            </p>
          )}
          {events.map((e, i) => (
            <div key={`${e.id}-${i}`} className="mb-1.5 rounded-lg border border-ink-800 bg-ink-900/60 p-2.5 animate-fade-up">
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    e.severity === 'critical' ? 'bg-rose'
                      : e.severity === 'warning' ? 'bg-amber'
                      : e.severity === 'success' ? 'bg-mint' : 'bg-accent'
                  }`}
                />
                <p className="min-w-0 flex-1 truncate text-[11.5px] font-medium text-slate-200">{e.title}</p>
                <span className="shrink-0 text-[10px] text-slate-600">{relative(e.created_at)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-400">{e.message}</p>
              <div className="mt-1.5 flex items-center gap-1.5">
                <span
                  className={`chip ${
                    e.actor_type === 'agent' ? 'border-violet/30 bg-violet/10 text-violet'
                      : e.actor_type === 'human' ? 'border-mint/30 bg-mint/10 text-mint'
                      : 'border-slate-600/30 bg-slate-600/10 text-slate-400'
                  }`}
                >
                  {e.actor_type}
                </span>
                <span className="truncate text-[10.5px] text-slate-500">{e.actor}</span>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {toast && <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />}
    </div>
  )
}
