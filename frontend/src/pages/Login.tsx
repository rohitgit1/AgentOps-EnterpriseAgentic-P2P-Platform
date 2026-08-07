import { useSession } from '../store'
import { Spinner } from '../components/ui'

export default function Login() {
  const { personas, signIn, loading } = useSession()

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-3xl">
        <div className="mb-7 text-center">
          <span className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-accent to-violet text-2xl font-bold text-white">
            ◈
          </span>
          <h1 className="text-2xl font-semibold text-slate-100">AgentOps</h1>
          <p className="mt-1.5 text-[13px] text-slate-400">
            Enterprise agentic Procure-to-Pay and Strategic Procurement. Sixteen specialised agents
            across two suites propose; qualified people decide; every decision is audited.
          </p>
        </div>

        <div className="panel p-5">
          <p className="mb-1 text-[13px] font-semibold text-slate-100">Choose a persona to begin</p>
          <p className="subtle mb-4">
            Authority is enforced per role — an AP Clerk cannot release a payment, and a Controller
            sees checkpoints a clerk never will. Switch personas any time from the top bar.
          </p>

          {loading && <Spinner label="Connecting to the platform…" />}

          <div className="grid gap-2 sm:grid-cols-2">
            {personas.map((p) => (
              <button
                key={p.id}
                onClick={() => signIn(p)}
                className="flex items-start gap-3 rounded-xl border border-ink-700 bg-ink-850/50 p-3.5 text-left transition-colors hover:border-accent/45 hover:bg-ink-800"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/15 text-[12px] font-bold text-accent-soft">
                  {p.initials}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-slate-100">
                    {p.full_name}
                    {p.out_of_office && <span className="ml-1.5 text-[11px] text-amber">· out of office</span>}
                  </span>
                  <span className="block text-[11.5px] text-slate-400">{p.title}</span>
                  <span className="mt-1 block text-[11px] leading-snug text-slate-500">{p.blurb}</span>
                  {p.approval_limit_usd > 0 && (
                    <span className="mt-1 block text-[10.5px] text-slate-600">
                      approval limit ${p.approval_limit_usd.toLocaleString()}
                    </span>
                  )}
                </span>
              </button>
            ))}
          </div>

          {!loading && personas.length === 0 && (
            <p className="rounded-lg border border-rose/30 bg-rose/10 p-3 text-[12.5px] text-rose">
              Cannot reach the API. Start the backend with{' '}
              <code className="mono">python -m app.main</code> from the <code className="mono">backend/</code> folder.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
