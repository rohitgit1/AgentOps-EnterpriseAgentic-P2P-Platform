import { ReactNode } from 'react'

/**
 * Chart theme.
 *
 * CATEGORICAL is a fixed order, validated against the dark surface #0c1120 with
 * the six checks (lightness band, chroma floor, CVD separation, normal-vision
 * floor, contrast). Worst adjacent pair ΔE 19.9 deutan. Assign in order; never
 * cycle, never re-map on filter change.
 */
export const SURFACE = '#0c1120'
export const CATEGORICAL = ['#4f8ef7', '#c07f22', '#9370f0', '#22a074'] as const

/** Status colors are reserved — never reused as a series hue. */
export const STATUS = {
  good: '#22a074',
  warning: '#c07f22',
  serious: '#e0495e',
  critical: '#e0495e',
} as const

/** Single-hue sequential ramp for ordered magnitude (light → dark). */
export const SEQUENTIAL = ['#a8c8fb', '#7ba9f7', '#4f8ef7', '#3a6fd0', '#2a53a0'] as const

export const AXIS = {
  stroke: '#2b3a66',
  tick: { fill: '#7f8db0', fontSize: 11 },
  line: false as const,
}

export const GRID = { stroke: '#1e2a4f', strokeWidth: 1, vertical: false }

/** Shared tooltip shell — one visual language across every chart. */
export function ChartTooltip({
  active, label, rows,
}: { active?: boolean; label?: ReactNode; rows: { name: string; value: ReactNode; color?: string }[] }) {
  if (!active) return null
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-2.5 py-2 shadow-lift backdrop-blur">
      {label !== undefined && (
        <p className="mb-1 text-[11px] font-semibold text-slate-200">{label}</p>
      )}
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-2 text-[11.5px]">
          {r.color && <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: r.color }} />}
          <span className="text-slate-400">{r.name}</span>
          <span className="ml-auto tabular-nums font-medium text-slate-100">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

/** Legend — always present for two or more series; identity never color-alone. */
export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((i) => (
        <span key={i.name} className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <span className="h-2 w-2 rounded-sm" style={{ background: i.color }} />
          {i.name}
        </span>
      ))}
    </div>
  )
}

/**
 * Progress meter against a target. Fill carries severity; the track is a
 * lighter step of the same ramp so the state reads across the whole bar.
 */
export function Meter({
  value, target, direction = 'up', max,
}: { value: number; target: number; direction?: 'up' | 'down'; max?: number }) {
  const ceiling = max ?? Math.max(value, target) * 1.15
  const pos = Math.max(0, Math.min(1, value / ceiling))
  const targetPos = Math.max(0, Math.min(1, target / ceiling))
  const meets = direction === 'up' ? value >= target : value <= target
  const near = direction === 'up' ? value >= target * 0.85 : value <= target * 1.25
  const fill = meets ? STATUS.good : near ? STATUS.warning : STATUS.serious

  return (
    <div className="relative mt-2 h-1.5 w-full rounded-full bg-ink-700">
      <div className="h-full rounded-full transition-all" style={{ width: `${pos * 100}%`, background: fill }} />
      <span
        className="absolute -top-0.5 h-2.5 w-0.5 rounded-full bg-slate-300"
        style={{ left: `${targetPos * 100}%` }}
        title={`Target ${target}`}
      />
    </div>
  )
}
