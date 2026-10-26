import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchPulse, type PulseEvent } from '../api/pulse'
import { subscribePulse } from './bus'
import { pulseStory, type PulseStory } from './narrative'

/** Stüdyonun ruhu: arka planda olup biteni yakalar, kullanıcıya seslenir.
 *
 * - /api/pulse'u imleçle yoklar (sekme gizliyken durur),
 * - yeni olayları toast olarak yaşatır (en fazla 3 tanesi),
 * - tüm akış çekmecede "Son olup bitenler" olarak kalır,
 * - ekranlar kullanıcı eylemleri için notify() ile katılır.
 */

export interface LocalPulse {
  tone: PulseStory['tone']
  sentence: string
  subject?: string | null
  note?: string | null
  link?: string | null
  /** Ekran aynı mesajı kendi pop-up'ında gösteriyor: toast açma. */
  silent?: boolean
  /** Bu eylemin sunucudaki karşılığı olan olay türleri; kısa süre
   * içinde gelen aynı tür olaylar ikinci kez toast olmaz. */
  echoTypes?: string[]
}

interface ToastItem {
  key: string
  tone: PulseStory['tone']
  sentence: string
  note: string | null
  link: string | null
  /** Yerel eylem geri bildirimi mi, sunucudan gelen olay mı. */
  local: boolean
  icon?: string
}

interface PulseContextValue {
  events: PulseEvent[]
  unread: number
  markSeen: () => void
  notify: (pulse: LocalPulse) => void
}

const PulseContext = createContext<PulseContextValue | null>(null)

const POLL_INTERVAL_MS = 20000
const MAX_EVENTS = 50
const MAX_TOASTS = 3
const TOAST_LIFE_MS = 6000

/** Kullanıcının kendi eyleminin sunucudan geri dönen yankısı.
 *
 * Ekranlar eylemi bitirir bitirmez bildirir; aynı eylem arka planda
 * audit kaydı da bırakır ve bir sonraki yoklamada ikinci kez toast
 * olarak gelirdi (ör. takvimden planlama + "yayın saati güncellendi").
 * Kısa bir pencerede yalnız o eylemin karşılık türleri susar; olay
 * "Son olup bitenler" çekmecesinde yine görünür. */
const ECHO_WINDOW_MS = 120000

export function usePulse(): PulseContextValue {
  const context = useContext(PulseContext)
  if (context === null) {
    throw new Error('usePulse, PulseProvider içinde kullanılmalı.')
  }
  return context
}

export function PulseProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const [events, setEvents] = useState<PulseEvent[]>([])
  const [unread, setUnread] = useState(0)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const cursorRef = useRef<string | null>(null)
  const seenIdsRef = useRef<Set<string>>(new Set())
  const bootedRef = useRef(false)
  /** Yerel eylemin yankı türleri ve zamanı (sunucu tekrarını susturur). */
  const echoRef = useRef<{ types: Set<string>; at: number }>({
    types: new Set(),
    at: 0,
  })

  const pushToast = useCallback((items: ToastItem[]) => {
    if (items.length === 0) return
    setToasts((current) => [...items, ...current].slice(0, MAX_TOASTS))
  }, [])

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      if (typeof document !== 'undefined' && document.hidden) return
      let feed
      try {
        feed = await fetchPulse(cursorRef.current ?? undefined)
      } catch {
        // Nabız arka planda sessizce düşer; sonraki tur yine denenir.
        return
      }
      if (cancelled) return
      if (!feed || !Array.isArray(feed.events)) return
      cursorRef.current = feed.now ?? cursorRef.current
      const fresh = feed.events.filter(
        (event) => !seenIdsRef.current.has(event.id),
      )
      for (const event of feed.events) seenIdsRef.current.add(event.id)
      if (fresh.length === 0) return
      const ordered = [...feed.events].reverse()
      setEvents(ordered.slice(-MAX_EVENTS).reverse())
      const echo = echoRef.current
      const echoing =
        echo.types.size > 0 && Date.now() - echo.at < ECHO_WINDOW_MS
      const speakable = fresh.filter(
        (event) => !(echoing && echo.types.has(event.event_type)),
      )
      if (bootedRef.current) {
        setUnread((count) => count + speakable.length)
        // Uzun süre uzak kalındıysa yalnız en yeni üçü konuşur; gerisi
        // çekmeceyi bekler.
        const speak = speakable
          .slice(0, MAX_TOASTS)
          .reverse()
          .map((event) => {
            const story = pulseStory(event)
            return {
              key: `toast-${event.id}`,
              tone: story.tone,
              sentence: story.sentence,
              note: story.note,
              link: story.link,
              local: false,
              icon: story.icon,
            }
          })
        pushToast(speak)
      }
      bootedRef.current = true
    }

    void poll()
    const id = window.setInterval(() => void poll(), POLL_INTERVAL_MS)
    const onVisible = () => {
      if (!document.hidden) void poll()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [pushToast])

  const notify = useCallback((pulse: LocalPulse) => {
    if (pulse.echoTypes && pulse.echoTypes.length > 0) {
      echoRef.current = { types: new Set(pulse.echoTypes), at: Date.now() }
    }
    if (pulse.silent) return
    pushToast([
      {
        key: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        tone: pulse.tone,
        sentence: pulse.sentence,
        note: pulse.note ?? null,
        link: pulse.link ?? null,
        local: true,
      },
    ])
  }, [pushToast])

  useEffect(() => subscribePulse(notify), [notify])

  const markSeen = useCallback(() => setUnread(0), [])

  const value = useMemo(
    () => ({ events, unread, markSeen, notify }),
    [events, unread, markSeen, notify],
  )

  return (
    <PulseContext.Provider value={value}>
      {children}
      <Toaster
        toasts={toasts}
        onExpire={(key) =>
          setToasts((current) => current.filter((item) => item.key !== key))
        }
        onVisit={(link) => {
          setToasts([])
          navigate(link)
        }}
      />
    </PulseContext.Provider>
  )
}

const TONE_ICON: Record<PulseStory['tone'], string> = {
  ok: '✓',
  error: '!',
  warn: '!',
  run: '•',
}

function ToastCard({
  toast,
  onExpire,
  onVisit,
}: {
  toast: ToastItem
  onExpire: (key: string) => void
  onVisit: (link: string) => void
}) {
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused) return
    const id = window.setTimeout(() => onExpire(toast.key), TOAST_LIFE_MS)
    return () => window.clearTimeout(id)
  }, [paused, toast.key, onExpire])

  return (
    <div
      className={`toast toast--${toast.tone}`}
      role={toast.tone === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="toast-icon" aria-hidden="true">
        {toast.icon ?? TONE_ICON[toast.tone]}
      </span>
      <div className="toast-body">
        <p>{toast.sentence}</p>
        {toast.note && <small>{toast.note}</small>}
        {toast.link && (
          <button
            type="button"
            className="toast-link"
            onClick={() => onVisit(toast.link as string)}
          >
            Gör
          </button>
        )}
      </div>
      <button
        type="button"
        className="toast-close"
        aria-label="Bildirimi kapat"
        onClick={() => onExpire(toast.key)}
      >
        ×
      </button>
    </div>
  )
}

function Toaster({
  toasts,
  onExpire,
  onVisit,
}: {
  toasts: ToastItem[]
  onExpire: (key: string) => void
  onVisit: (link: string) => void
}) {
  if (toasts.length === 0) return null
  return (
    <div className="toaster" aria-label="Stüdyo bildirimleri">
      {toasts.map((toast) => (
        <ToastCard
          key={toast.key}
          toast={toast}
          onExpire={onExpire}
          onVisit={onVisit}
        />
      ))}
    </div>
  )
}
