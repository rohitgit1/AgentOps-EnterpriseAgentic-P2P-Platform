/**
 * Backend Data Model — the live schema, introspected from the running database.
 *
 * Nothing here is hand-maintained: the tables, columns, keys and row counts are
 * read from SQLAlchemy metadata and the database itself on every request, so
 * this screen cannot drift from the code it describes.
 */
import { useMemo, useState } from 'react'
import { Chip, Drawer, Empty, Panel, Spinner } from '../components/ui'
import { num } from '../lib/format'
import { useApi } from '../store'

type Column = {
  name: string
  type: string
  nullable: boolean
  primary_key: boolean
  indexed: boolean
  unique: boolean
  foreign_key: string | null
  default: string | null
}

type Reference = { from_column: string; to_table: string; to_column: string }
type Backreference = { from_table: string; from_column: string; to_column: string }

type Table = {
  name: string
  row_count: number
  column_count: number
  primary_key: string[]
  columns: Column[]
  references: Reference[]
  referenced_by: Backreference[]
  note: string | null
}

type Domain = { key: string; label: string; blurb: string; tables: Table[] }

type DataModel = {
  domains: Domain[]
  totals: { tables: number; columns: number; rows: number; relationships: number }
  relationships: { from: string; to: string; column: string }[]
  dialect: string
  invariant: string
}

/** Domains an agent may write to directly. Everything else needs an approval. */
const AGENT_WRITABLE = new Set(['agent_executions', 'human_tasks', 'artifacts'])

const rows = (n: number) => `${num(n, 0)} row${n === 1 ? '' : 's'}`

const DOMAIN_TONE: Record<string, string> = {
  people: 'violet',
  master_data: 'slate',
  p2p_transactions: 'accent',
  procurement: 'mint',
  control_plane: 'amber',
  documents: 'accent',
  assurance: 'rose',
}

export default function DataModel() {
  const { data, loading } = useApi<DataModel>('/data-model')
  const [query, setQuery] = useState('')
  const [openTable, setOpenTable] = useState<string | null>(null)

  const needle = query.trim().toLowerCase()

  /** A table matches on its own name, its note, or any of its column names. */
  const domains = useMemo(() => {
    if (!data) return []
    if (!needle) return data.domains
    return data.domains
      .map((d) => ({
        ...d,
        tables: d.tables.filter(
          (t) =>
            t.name.includes(needle) ||
            (t.note ?? '').toLowerCase().includes(needle) ||
            t.columns.some((c) => c.name.includes(needle)),
        ),
      }))
      .filter((d) => d.tables.length > 0)
  }, [data, needle])

  const selected = useMemo(() => {
    if (!data || !openTable) return null
    for (const d of data.domains) {
      const hit = d.tables.find((t) => t.name === openTable)
      if (hit) return { table: hit, domain: d }
    }
    return null
  }, [data, openTable])

  if (loading) return <Spinner label="Introspecting the database…" />
  if (!data) return <Empty title="No schema available" />

  const shown = domains.reduce((n, d) => n + d.tables.length, 0)

  return (
    <div className="space-y-4">
      {/* The guarantee this schema exists to enforce. */}
      <div className="panel border-accent/25 bg-gradient-to-r from-accent/[0.07] to-violet/[0.05] px-4 py-3.5">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <div className="min-w-[280px] flex-1">
            <p className="text-[13px] font-semibold text-slate-100">
              Backend data model
              <span className="ml-2 rounded border border-ink-700 bg-ink-850 px-1.5 py-px font-mono text-[10px] font-normal text-slate-400">
                {data.dialect}
              </span>
            </p>
            <p className="subtle mt-0.5">
              Read live from the running database. {data.invariant}
            </p>
          </div>
          <Metric label="Tables" value={data.totals.tables} />
          <Metric label="Columns" value={data.totals.columns} />
          <Metric label="Rows" value={num(data.totals.rows, 0)} tone="text-mint" />
          <Metric label="Foreign keys" value={data.totals.relationships} tone="text-accent-soft" />
        </div>
      </div>

      {/* Search */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by table, column or note…"
          className="field w-full max-w-sm"
        />
        {needle && (
          <span className="subtle">
            {shown} of {data.totals.tables} tables
            <button className="btn-ghost ml-2" onClick={() => setQuery('')}>
              Clear
            </button>
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Chip tone="amber">⬢ agent-writable</Chip>
          <span className="subtle">everything else needs an approved checkpoint</span>
        </div>
      </div>

      {domains.length === 0 && (
        <Panel>
          <Empty title="Nothing matches that" hint="Try a table name like invoices, or a column like supplier_id." />
        </Panel>
      )}

      {domains.map((domain) => (
        <Panel
          key={domain.key}
          title={domain.label}
          subtitle={domain.blurb}
          bodyClass="p-3"
          actions={
            <Chip tone={DOMAIN_TONE[domain.key] ?? 'slate'}>
              {domain.tables.length} table{domain.tables.length === 1 ? '' : 's'}
            </Chip>
          }
        >
          <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
            {domain.tables.map((table) => (
              <button
                key={table.name}
                onClick={() => setOpenTable(table.name)}
                className="rounded-xl border border-ink-700 bg-ink-850/40 p-3 text-left transition-colors hover:border-accent/40 hover:bg-ink-850"
              >
                <div className="flex items-center gap-2">
                  <span className="mono truncate text-[12.5px] font-semibold text-slate-100">
                    {table.name}
                  </span>
                  {AGENT_WRITABLE.has(table.name) && (
                    <span title="Agents write here directly" className="text-[11px] text-amber">
                      ⬢
                    </span>
                  )}
                  <span className="ml-auto shrink-0 tabular-nums text-[11px] text-slate-500">
                    {rows(table.row_count)}
                  </span>
                </div>
                <p className="subtle mt-1 line-clamp-2">
                  {table.note ?? `${table.column_count} columns · key ${table.primary_key.join(', ') || '—'}`}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  <MiniChip>{table.column_count} cols</MiniChip>
                  {table.references.length > 0 && (
                    <MiniChip tone="text-accent-soft">→ {table.references.length} fk</MiniChip>
                  )}
                  {table.referenced_by.length > 0 && (
                    <MiniChip tone="text-violet">← {table.referenced_by.length} ref</MiniChip>
                  )}
                </div>
              </button>
            ))}
          </div>
        </Panel>
      ))}

      <Drawer
        open={!!selected}
        onClose={() => setOpenTable(null)}
        width="max-w-4xl"
        title={<span className="mono">{selected?.table.name}</span>}
        subtitle={
          selected && (
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone={DOMAIN_TONE[selected.domain.key] ?? 'slate'}>{selected.domain.label}</Chip>
              <Chip tone="slate">{selected.table.column_count} columns</Chip>
              <Chip tone="slate">{rows(selected.table.row_count)}</Chip>
              {AGENT_WRITABLE.has(selected.table.name) ? (
                <Chip tone="amber">⬢ agents write here</Chip>
              ) : (
                <Chip tone="mint">written only by an approved checkpoint</Chip>
              )}
            </div>
          )
        }
      >
        {selected && <TableDetail table={selected.table} onJump={setOpenTable} />}
      </Drawer>
    </div>
  )
}

function TableDetail({ table, onJump }: { table: Table; onJump: (name: string) => void }) {
  return (
    <div className="space-y-5">
      {table.note && (
        <p className="rounded-lg border border-accent/25 bg-accent/[0.06] px-3 py-2.5 text-[12.5px] text-slate-200">
          {table.note}
        </p>
      )}

      <div>
        <SectionLabel>Columns</SectionLabel>
        <div className="overflow-hidden rounded-lg border border-ink-700">
          <table className="w-full text-[12px]">
            <thead className="bg-ink-850/70 text-[10.5px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Column</th>
                <th className="px-3 py-2 text-left font-semibold">Type</th>
                <th className="px-3 py-2 text-left font-semibold">Constraints</th>
                <th className="px-3 py-2 text-left font-semibold">References</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800">
              {table.columns.map((c) => (
                <tr key={c.name} className="align-top">
                  <td className="px-3 py-2">
                    <span className="mono text-slate-100">{c.name}</span>
                    {c.primary_key && <span className="ml-1.5 text-[10px] text-amber">PK</span>}
                    {c.foreign_key && <span className="ml-1.5 text-[10px] text-accent-soft">FK</span>}
                  </td>
                  <td className="mono px-3 py-2 text-slate-400">{c.type}</td>
                  <td className="px-3 py-2 text-slate-400">
                    <div className="flex flex-wrap gap-1">
                      {!c.nullable && <MiniChip tone="text-slate-300">required</MiniChip>}
                      {c.unique && <MiniChip tone="text-violet">unique</MiniChip>}
                      {c.indexed && !c.primary_key && <MiniChip>indexed</MiniChip>}
                      {c.default !== null && (
                        <MiniChip tone="text-slate-400">
                          default {c.default === '' ? '""' : c.default}
                        </MiniChip>
                      )}
                    </div>
                  </td>
                  <td className="mono px-3 py-2 text-slate-400">{c.foreign_key ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <SectionLabel>Points at ({table.references.length})</SectionLabel>
          {table.references.length === 0 ? (
            <p className="subtle">Nothing — this table stands alone.</p>
          ) : (
            <ul className="space-y-1.5">
              {table.references.map((r, i) => (
                <li key={`${r.from_column}-${i}`} className="text-[12px]">
                  <span className="mono text-slate-300">{r.from_column}</span>
                  <span className="mx-1.5 text-slate-600">→</span>
                  <button className="mono text-accent-soft hover:underline" onClick={() => onJump(r.to_table)}>
                    {r.to_table}.{r.to_column}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <SectionLabel>Pointed at by ({table.referenced_by.length})</SectionLabel>
          {table.referenced_by.length === 0 ? (
            <p className="subtle">Nothing references this table.</p>
          ) : (
            <ul className="space-y-1.5">
              {table.referenced_by.map((r, i) => (
                <li key={`${r.from_table}-${r.from_column}-${i}`} className="text-[12px]">
                  <button className="mono text-violet hover:underline" onClick={() => onJump(r.from_table)}>
                    {r.from_table}.{r.from_column}
                  </button>
                  <span className="mx-1.5 text-slate-600">→</span>
                  <span className="mono text-slate-300">{r.to_column}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">{children}</p>
  )
}

function MiniChip({ children, tone = 'text-slate-500' }: { children: React.ReactNode; tone?: string }) {
  return (
    <span className={`rounded border border-ink-700 bg-ink-900/70 px-1.5 py-px text-[10px] ${tone}`}>
      {children}
    </span>
  )
}

function Metric({ label, value, tone = 'text-slate-100' }: {
  label: string; value: React.ReactNode; tone?: string
}) {
  return (
    <div className="shrink-0">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}
