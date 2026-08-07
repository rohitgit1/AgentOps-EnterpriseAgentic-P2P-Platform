const BASE = '/api'

let token: string | null = localStorage.getItem('p2p.token')

export function setToken(next: string | null) {
  token = next
  if (next) localStorage.setItem('p2p.token', next)
  else localStorage.removeItem('p2p.token')
}
export function getToken() {
  return token
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (token) headers['X-User-Id'] = token

  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* keep status text */
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) =>
    request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T,>(p: string, body?: unknown) =>
    request<T>(p, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
}

/* ------------------------------------------------------------------ */
/* Domain shapes (only what the UI reads)                              */
/* ------------------------------------------------------------------ */
export type Persona = {
  id: string
  full_name: string
  email: string
  role: string
  role_label: string
  title?: string
  initials: string
  approval_limit_usd: number
  out_of_office: boolean
  blurb?: string
  active_workload?: number
}

export type HumanTask = {
  id: string
  task_number: string
  agent_key: string
  agent_name: string
  stage: string
  stage_label: string
  action_kind: string
  action_label: string
  title: string
  summary: string
  entity_type?: string
  entity_id?: string
  entity_label?: string
  confidence: number
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  financial_impact_usd: number
  reversible: boolean
  required_role: string
  required_role_label: string
  dual_approval_required: boolean
  second_approver_id?: string
  status: string
  decision?: string
  decided_by?: string
  decided_at?: string
  decision_notes?: string
  due_at?: string
  created_at?: string
  overdue: boolean
  policy_flags: string[]
  auto_eligible: boolean
  auto_blocked_reason?: string
  diff_preview: { field: string; label?: string; before?: unknown; after?: unknown }[]
  can_decide?: boolean
  blocked_reason?: string
  rationale?: string
  evidence?: { label: string; detail: unknown; source?: string }[]
  proposed_payload?: Record<string, unknown>
  alternatives?: { option: string; detail?: string; impact_usd?: number }[]
  execution?: AgentRun
  execution_result?: Record<string, unknown>
}

export type AgentRun = {
  id: string
  run_number: string
  agent_key: string
  agent_name: string
  status: string
  goal: string
  conclusion: string
  confidence: number
  reasoning_engine: string
  escalated: boolean
  escalation_reason?: string
  duration_ms: number
  entity_label?: string
  entity_id?: string
  created_at?: string
  trigger?: string
  triggered_by?: string
  task_count?: number
  plan?: { step: number; action: string; tool: string; rationale: string }[]
  observations?: { tool: string; summary: string; ok: boolean; detail?: unknown }[]
  reasoning?: string
  evidence?: { label: string; detail: unknown; source?: string }[]
  policy_evaluation?: { proposals?: PolicyVerdict[] }
  handoff_to?: string
}

export type PolicyVerdict = {
  action: string
  allow_auto_execute: boolean
  requires_human: boolean
  required_role: string
  risk_level: string
  reversible: boolean
  dual_approval_required: boolean
  reasons: string[]
  blocked_reasons: string[]
  flags: string[]
}

export type Invoice = {
  id: string
  invoice_number: string
  supplier_name?: string
  supplier_id?: string
  supplier_tier?: string
  po_number?: string
  currency: string
  total_amount: number
  status: string
  stage: string
  stage_label: string
  match_result: string
  source_channel: string
  extraction_confidence: number
  touchless: boolean
  human_touches: number
  on_hold: boolean
  hold_reason?: string
  sla_status: string
  sla_risk_score: number
  age_hours: number
  open_exception_count: number
  erp_document_number?: string
  due_date?: string
  received_at?: string
  invoice_date?: string
  cycle_time_hours?: number
  [k: string]: unknown
}

export type LiveEvent = {
  id: string
  event_type: string
  title: string
  message: string
  actor: string
  actor_type: 'agent' | 'human' | 'system'
  severity: string
  entity_label?: string
  entity_id?: string
  created_at?: string
}
