import { ReactNode, useEffect } from 'react'
import { RISK_STYLES, confidencePct, titleCase } from '../lib/format'

export function Panel({
  title, subtitle, actions, children, className = '', bodyClass = '',
}: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode
  children: ReactNode; className?: string; bodyClass?: string
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          <div className="min-w-0">
            <h2 className="panel-title truncate">{title}</h2>
            {subtitle && <p className="subtle mt-0.5 truncate">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass || 'p-4'}>{children}</div>
    </section>
  )
}

export function Chip({ tone = 'slate', children, className = '' }: {
  tone?: string; children: ReactNode; className?: string
}) {
  const tones: Record<string, string> = {
    slate: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
    accent: 'border-accent/35 bg-accent/10 text-accent-soft',
    mint: 'border-mint/35 bg-mint/10 text-mint',
    amber: 'border-amber/35 bg-amber/10 text-amber',
    rose: 'border-rose/35 bg-rose/10 text-rose',
    violet: 'border-violet/35 bg-violet/10 text-violet',
  }
  return <span className={`chip ${tones[tone] ?? tones.slate} ${className}`}>{children}</span>
}

export function RiskChip({ level }: { level?: string }) {
  return (
    <span className={`chip ${RISK_STYLES[level ?? 'medium'] ?? RISK_STYLES.medium}`}>
      {level === 'critical' && '▲ '}
      {level ?? 'medium'}
    </span>
  )
}

export function StatusChip({ value, map }: { value?: string; map?: Record<string, string> }) {
  const cls = map?.[value ?? ''] ?? 'border-slate-500/30 bg-slate-500/10 text-slate-300'
  return <span className={`chip ${cls}`}>{titleCase(value)}</span>
}

/** Confidence as a compact meter — the number the reviewer actually acts on. */
export function Confidence({ value, showLabel = true }: { value: number; showLabel?: boolean }) {
  const p = Math.max(0, Math.min(1, value ?? 0))
  const tone = p >= 0.93 ? 'bg-mint' : p >= 0.85 ? 'bg-amber' : 'bg-rose'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-700">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${p * 100}%` }} />
      </div>
      {showLabel && <span className="mono tabular-nums text-slate-300">{confidencePct(value)}</span>}
    </div>
  )
}

export function Stat({
  label, value, sub, tone = 'slate', trend,
}: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; trend?: ReactNode }) {
  const accents: Record<string, string> = {
    slate: 'text-slate-100', mint: 'text-mint', amber: 'text-amber',
    rose: 'text-rose', accent: 'text-accent-soft', violet: 'text-violet',
  }
  return (
    <div className="panel p-4">
      <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold tabular-nums ${accents[tone] ?? accents.slate}`}>{value}</p>
      {sub && <p className="subtle mt-1">{sub}</p>}
      {trend}
    </div>
  )
}

export function Empty({ icon = '◌', title, hint }: { icon?: string; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <span className="text-2xl text-slate-600">{icon}</span>
      <p className="text-[13px] font-medium text-slate-300">{title}</p>
      {hint && <p className="subtle max-w-sm">{hint}</p>}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-12 text-slate-400">
      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-600 border-t-accent" />
      <span className="text-[12.5px]">{label ?? 'Loading…'}</span>
    </div>
  )
}

export function Drawer({
  open, onClose, title, subtitle, children, footer, width = 'max-w-3xl',
}: {
  open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode
  children: ReactNode; footer?: ReactNode; width?: string
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    if (open) window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-[2px]" onClick={onClose} />
      <aside
        className={`relative flex h-full w-full ${width} flex-col border-l border-ink-700 bg-ink-900 shadow-lift animate-fade-up`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-ink-700 px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>
            {subtitle && <div className="mt-1">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="btn-ghost shrink-0" aria-label="Close">✕</button>
        </header>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="border-t border-ink-700 bg-ink-850/60 px-5 py-3.5">{footer}</footer>}
      </aside>
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      {children}
      {hint && <span className="subtle mt-1 block">{hint}</span>}
    </label>
  )
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-5 gap-y-2.5">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{k}</dt>
          <dd className="mt-0.5 truncate text-[12.5px] text-slate-200">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Toast({ message, tone = 'mint', onDone }: {
  message: string; tone?: 'mint' | 'rose' | 'accent'; onDone: () => void
}) {
  useEffect(() => {
    const t = setTimeout(onDone, 4200)
    return () => clearTimeout(t)
  }, [message, onDone])
  const tones = {
    mint: 'border-mint/40 bg-mint/10 text-mint',
    rose: 'border-rose/40 bg-rose/10 text-rose',
    accent: 'border-accent/40 bg-accent/10 text-accent-soft',
  }
  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 animate-fade-up">
      <div className={`rounded-lg border px-4 py-2.5 text-[12.5px] font-medium shadow-lift backdrop-blur ${tones[tone]}`}>
        {message}
      </div>
    </div>
  )
}
