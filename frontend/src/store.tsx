import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode,
} from 'react'
import { LiveEvent, Persona, api, getToken, setToken } from './lib/api'

type Session = {
  personas: Persona[]
  user: Persona | null
  loading: boolean
  signIn: (persona: Persona) => void
  signOut: () => void
  /** Bumped whenever data changes so pages can refetch. */
  revision: number
  refresh: () => void
  events: LiveEvent[]
  connected: boolean
  toast: { message: string; tone: 'mint' | 'rose' | 'accent' } | null
  notify: (message: string, tone?: 'mint' | 'rose' | 'accent') => void
  clearToast: () => void
}

const Ctx = createContext<Session>(null as unknown as Session)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [user, setUser] = useState<Persona | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [events, setEvents] = useState<LiveEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [toast, setToast] = useState<Session['toast']>(null)
  const sourceRef = useRef<EventSource | null>(null)

  const refresh = useCallback(() => setRevision((r) => r + 1), [])
  const notify = useCallback(
    (message: string, tone: 'mint' | 'rose' | 'accent' = 'mint') => setToast({ message, tone }),
    [],
  )
  const clearToast = useCallback(() => setToast(null), [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const list = await api.get<Persona[]>('/auth/personas')
        if (cancelled) return
        setPersonas(list)
        const stored = getToken()
        const match = stored ? list.find((p) => p.id === stored) : null
        setUser(match ?? null)
        if (stored && !match) setToken(null)
      } catch {
        /* backend not up yet */
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Live activity feed. Reconnects on its own if the stream drops.
  useEffect(() => {
    if (!user) return
    const source = new EventSource('/api/events/stream')
    sourceRef.current = source
    source.onopen = () => setConnected(true)
    source.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data) as LiveEvent
        setEvents((prev) => [payload, ...prev].slice(0, 160))
      } catch {
        /* keep-alive frame */
      }
    }
    source.onerror = () => setConnected(false)
    return () => {
      source.close()
      sourceRef.current = null
      setConnected(false)
    }
  }, [user])

  const signIn = useCallback((persona: Persona) => {
    setToken(persona.id)
    setUser(persona)
    setEvents([])
    setRevision((r) => r + 1)
  }, [])

  const signOut = useCallback(() => {
    setToken(null)
    setUser(null)
    setEvents([])
  }, [])

  const value = useMemo<Session>(
    () => ({
      personas, user, loading, signIn, signOut, revision, refresh,
      events, connected, toast, notify, clearToast,
    }),
    [personas, user, loading, signIn, signOut, revision, refresh, events, connected, toast, notify, clearToast],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useSession = () => useContext(Ctx)

/** Small fetch helper that re-runs whenever the global revision changes. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const { revision } = useSession()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))

  useEffect(() => {
    if (!path) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    api
      .get<T>(path)
      .then((res) => !cancelled && (setData(res), setError(null)))
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, revision, ...deps])

  return { data, error, loading }
}
