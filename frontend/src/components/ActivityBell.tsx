import { useEffect, useRef, useState } from 'react'

import { usePulse } from '../pulse/PulseProvider'
import { pulseStory, relativeTime } from '../pulse/narrative'

/** Zil düğmesi + "Son olup bitenler" çekmecesi: stüdyonun sesinin
 * arşivi. Okunmamış olay sayısı hapla gösterilir; açınca sıfırlanır. */
export function ActivityBell() {
  const { events, unread, markSeen } = usePulse()
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    markSeen()
    panelRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (
        panelRef.current?.contains(target) === false &&
        buttonRef.current?.contains(target) === false
      ) {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDown)
      buttonRef.current?.focus()
    }
  }, [open, markSeen])

  return (
    <div className="activity-wrap">
      <button
        ref={buttonRef}
        type="button"
        className={`activity-bell${open ? ' open' : ''}`}
        aria-label={`Son olup bitenler${unread > 0 ? ` (${unread} yeni)` : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="activity-badge nums" aria-hidden="true">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          ref={panelRef}
          className="activity-panel"
          tabIndex={-1}
          role="dialog"
          aria-label="Son olup bitenler"
        >
          <div className="activity-head">
            <b>Son olup bitenler</b>
            <small>stüdyo kendi devam ederken buraya yazar</small>
          </div>
          {events.length === 0 ? (
            <p className="activity-empty">
              Henüz kayda değer bir şey olmadı. Motor işleri tamamladıkça
              burada doğal cümlelerle göreceksin.
            </p>
          ) : (
            <ul className="activity-list">
              {events.map((event) => {
                const story = pulseStory(event)
                return (
                  <li key={event.id} className={`activity-item tone--${story.tone}`}>
                    <span className="activity-dot" aria-hidden="true" />
                    <div>
                      <p>
                        {story.icon ? <span className="activity-icon" aria-hidden="true">{story.icon} </span> : null}
                        {story.sentence}
                      </p>
                      <small>
                        {event.channel_name ? `${event.channel_name} · ` : ''}
                        {relativeTime(event.created_at)}
                      </small>
                      {story.note && (
                        <small className="activity-note">{story.note}</small>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
