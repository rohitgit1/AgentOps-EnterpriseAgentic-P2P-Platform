export const money = (value: number | undefined | null, currency = 'USD') => {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: Math.abs(value) >= 10000 ? 0 : 2,
  }).format(value)
}

export const num = (value: number | undefined | null, digits = 1) =>
  value === undefined || value === null || Number.isNaN(value)
    ? '—'
    : value.toLocaleString('en-US', { maximumFractionDigits: digits })

export const pct = (value: number | undefined | null, digits = 0) =>
  value === undefined || value === null ? '—' : `${value.toFixed(digits)}%`

export const confidencePct = (value: number | undefined | null) =>
  value === undefined || value === null ? '—' : `${Math.round(value * 100)}%`

export const hours = (value: number | undefined | null) => {
  if (value === undefined || value === null) return '—'
  const abs = Math.abs(value)
  if (abs < 1) return `${Math.round(value * 60)}m`
  if (abs < 48) return `${value.toFixed(abs < 10 ? 1 : 0)}h`
  return `${(value / 24).toFixed(1)}d`
}

export const dateTime = (iso?: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export const dateOnly = (iso?: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso.endsWith('Z') ? iso : `${iso}Z`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export const relative = (iso?: string | null) => {
  if (!iso) return '—'
  const then = new Date(iso.endsWith('Z') ? iso : `${iso}Z`).getTime()
  const diff = (Date.now() - then) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export const titleCase = (value?: string | null) =>
  (value ?? '').replace(/[_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export const RISK_STYLES: Record<string, string> = {
  low: 'border-mint/35 bg-mint/10 text-mint',
  medium: 'border-amber/35 bg-amber/10 text-amber',
  high: 'border-rose/35 bg-rose/10 text-rose',
  critical: 'border-rose/60 bg-rose/20 text-rose',
}

export const STATUS_STYLES: Record<string, string> = {
  received: 'border-slate-500/35 bg-slate-500/10 text-slate-300',
  pending_review: 'border-amber/35 bg-amber/10 text-amber',
  validated: 'border-accent/35 bg-accent/10 text-accent-soft',
  matched: 'border-accent/35 bg-accent/10 text-accent-soft',
  in_exception: 'border-rose/35 bg-rose/10 text-rose',
  on_hold: 'border-rose/35 bg-rose/10 text-rose',
  pending_approval: 'border-violet/35 bg-violet/10 text-violet',
  approved: 'border-mint/35 bg-mint/10 text-mint',
  scheduled_for_payment: 'border-mint/35 bg-mint/10 text-mint',
  paid: 'border-mint/45 bg-mint/15 text-mint',
  rejected: 'border-rose/45 bg-rose/15 text-rose',
}

export const SLA_STYLES: Record<string, string> = {
  on_track: 'border-mint/35 bg-mint/10 text-mint',
  at_risk: 'border-amber/35 bg-amber/10 text-amber',
  breached: 'border-rose/45 bg-rose/15 text-rose',
  met: 'border-mint/35 bg-mint/10 text-mint',
}
