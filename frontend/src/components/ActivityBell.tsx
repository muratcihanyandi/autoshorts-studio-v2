import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { usePulse } from '../pulse/PulseProvider'
import { pulseStory, relativeTime } from '../pulse/narrative'

/** Zil düğmesi + "Son olup bitenler" çekmecesi: stüdyonun sesinin
 * arşivi. Okunmamış olay sayısı hapla gösterilir; açınca sıfırlanır.
 * Bildirime tıklanınca doğrudan ilgili çalışma ekranına (medya, youtube,
 * otomasyon vb.) yönlendirir. */
export function ActivityBell() {
  const { events, unread, markSeen } = usePulse()
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!open) return
    markSeen()
    panelRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
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
    }
  }, [open, markSeen])

  const handleItemClick = (link: string | null) => {
    setOpen(false)
    if (link) {
      navigate(link)
    }
  }

  return (
    <div className="activity-wrap">
      <button
        ref={buttonRef}
        type="button"
        className={`activity-bell${open ? ' open' : ''}`}
        aria-label={`Son olup bitenler${unread > 0 ? ` (${unread} yeni)` : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        title="Stüdyo Bildirimleri & Son Gelişmeler"
      >
        <svg
          viewBox="0 0 24 24"
          width="17"
          height="17"
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
            <div className="activity-head-titles">
              <b>Son Olup Bitenler</b>
              <small>stüdyonun canlı işlem akışı</small>
            </div>
            {unread > 0 && (
              <span className="activity-unread-pill nums">{unread} yeni</span>
            )}
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
                const hasLink = Boolean(story.link)
                return (
                  <li
                    key={event.id}
                    className={`activity-item tone--${story.tone}${hasLink ? ' activity-item--clickable' : ''}`}
                    onClick={() => handleItemClick(story.link)}
                    role={hasLink ? 'button' : undefined}
                    tabIndex={hasLink ? 0 : undefined}
                    onKeyDown={(e) => {
                      if (hasLink && (e.key === 'Enter' || e.key === ' ')) {
                        e.preventDefault()
                        handleItemClick(story.link)
                      }
                    }}
                    title={hasLink ? 'İlgili ekrana git' : undefined}
                  >
                    <span className="activity-dot" aria-hidden="true" />
                    <div className="activity-item-content">
                      <p>
                        {story.icon ? (
                          <span className="activity-icon" aria-hidden="true">
                            {story.icon}{' '}
                          </span>
                        ) : null}
                        {story.sentence}
                      </p>
                      <div className="activity-meta-line">
                        <small>
                          {event.channel_name ? `${event.channel_name} · ` : ''}
                          {relativeTime(event.created_at)}
                        </small>
                        {hasLink && (
                          <span className="activity-action-hint">
                            İncele →
                          </span>
                        )}
                      </div>
                      {story.note && (
                        <small className="activity-note">{story.note}</small>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          <div className="activity-footer">
            <Link
              to="/gunlukler"
              className="activity-all-link"
              onClick={() => setOpen(false)}
            >
              Tüm Olay Günlüğünü Gör →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
