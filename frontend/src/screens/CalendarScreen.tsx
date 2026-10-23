import { useCallback, useMemo, useState } from 'react'

import {
  fetchCalendar,
  rescheduleCalendar,
  type CalendarEntry,
  type CalendarData,
} from '../api/calendar'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'
import { ClipDetailModal } from '../components/ClipDetailModal'

const WEEKDAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']

const STATUS_VIEW: Record<string, { tone: string; label: string }> = {
  scheduled: { tone: 'run', label: 'Saat bekliyor' },
  planned: { tone: 'warn', label: 'Stokta' },
  published: { tone: 'ok', label: 'Yayında' },
  empty: { tone: 'idle', label: 'Boş' },
}

function entryTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('tr-TR', {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

function isoDate(date: Date): string {
  const year = date.getUTCFullYear()
  const month = String(date.getUTCMonth() + 1).padStart(2, '0')
  const day = String(date.getUTCDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Ay ızgarası: Pazartesi başlangıçlı 42 hücre. */
function monthGrid(year: number, month: number) {
  const first = new Date(Date.UTC(year, month - 1, 1))
  const offset = (first.getUTCDay() + 6) % 7
  const start = new Date(first)
  start.setUTCDate(first.getUTCDate() - offset)
  const today = isoDate(new Date())
  const cells: { date: string; inMonth: boolean; isToday: boolean }[] = []
  for (let index = 0; index < 42; index += 1) {
    const cell = new Date(start)
    cell.setUTCDate(start.getUTCDate() + index)
    const date = isoDate(cell)
    cells.push({
      date,
      inMonth: cell.getUTCMonth() === month - 1,
      isToday: date === today,
    })
  }
  return cells
}

function shiftMonth(year: number, month: number, delta: number) {
  const total = year * 12 + (month - 1) + delta
  return { year: Math.floor(total / 12), month: (total % 12 + 12) % 12 + 1 }
}

/** Elle planlanabilir mi: saat bekleyen ya da stoktaki hazır video. */
function canSchedule(entry: CalendarEntry): boolean {
  if (entry.status !== 'scheduled' && entry.status !== 'planned') return false
  return entry.published_video_id !== null || entry.clip_render_id !== null
}

function scheduleTarget(
  entry: CalendarEntry,
): { publishedVideoId?: number; clipRenderId?: number } | null {
  if (entry.published_video_id !== null) {
    return { publishedVideoId: entry.published_video_id }
  }
  if (entry.clip_render_id !== null) {
    return { clipRenderId: entry.clip_render_id }
  }
  return null
}

function localDateToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function CalendarChip({
  entry,
  draggable,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  entry: CalendarEntry
  draggable: boolean
  onOpen: (entry: CalendarEntry) => void
  onDragStart: (entry: CalendarEntry) => void
  onDragEnd: () => void
}) {
  const view = STATUS_VIEW[entry.status] ?? {
    tone: 'idle',
    label: entry.status,
  }
  const orientationClass =
    entry.orientation === 'horizontal'
      ? 'cal-chip--horizontal'
      : 'cal-chip--vertical'
  const clickable = entry.status !== 'empty'
  return (
    <button
      type="button"
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) return
        onDragStart(entry)
        event.dataTransfer.setData('text/plain', String(entry.id))
        event.dataTransfer.effectAllowed = 'move'
      }}
      onDragEnd={onDragEnd}
      className={`cal-chip ${orientationClass}${
        entry.status === 'empty' ? ' cal-chip--empty' : ''
      }${clickable ? '' : ' cal-chip--static'}${
        entry.manual ? ' cal-chip--manual' : ''
      }${draggable ? ' cal-chip--draggable' : ''}`}
      onClick={() => onOpen(entry)}
      title={
        entry.title
          ? `${entryTime(entry.scheduled_at)} · ${entry.title} — ${view.label}`
          : `${entryTime(entry.scheduled_at)} — ${entry.note}`
      }
    >
      <span className="cal-chip-time nums">{entryTime(entry.scheduled_at)}</span>
      {entry.status === 'empty' ? (
        <span className="cal-chip-title">{entry.note}</span>
      ) : (
        <>
          <span className="cal-chip-title">{entry.title ?? 'Video'}</span>
          <span className={`pill pill--${view.tone}`}>
            {entry.manual ? 'Elle' : view.label}
          </span>
        </>
      )}
    </button>
  )
}

/** Sürükle-bırak sonrası saat seçici: video, seçilen güne yerleşir. */
function ScheduleModal({
  entry,
  initialDate,
  onClose,
  onSaved,
}: {
  entry: CalendarEntry
  initialDate: string
  onClose: () => void
  onSaved: () => void
}) {
  const target = scheduleTarget(entry)
  const [date, setDate] = useState(initialDate)
  const [time, setTime] = useState(() => {
    if (entry.status === 'scheduled' || entry.manual) {
      const current = entryTime(entry.scheduled_at)
      if (/^\d{2}:\d{2}$/.test(current)) return current
    }
    return '18:00'
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (!target) return
    setBusy(true)
    setError(null)
    try {
      const moment = new Date(`${date}T${time}`)
      if (Number.isNaN(moment.getTime())) {
        throw new Error('Geçersiz tarih veya saat.')
      }
      if (moment.getTime() <= Date.now()) {
        throw new Error('Yayın saati gelecekte olmalı.')
      }
      await rescheduleCalendar(target, moment.toISOString())
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Planlama başarısız.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cal-schedule-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <span className="clip-eyebrow">
              {entry.channel_name} ·{' '}
              {entry.orientation === 'horizontal' ? 'Yatay' : 'Dikey'} ·{' '}
              {entry.status === 'planned' ? 'Stoktaki klip' : 'Gizli yüklü'}
            </span>
            <h2 id="cal-schedule-title">{entry.title ?? 'Video'}</h2>
          </div>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="Kapat"
          >
            ×
          </button>
        </div>
        <div className="modal-body">
          <p className="detail-note">
            Video bu saatte herkese açılacak. Elle planlanan videolar günlük
            limit ve yayın saatlerinden bağımsız çıkar.
            {entry.status === 'planned' &&
              ' Stoktaki klip önce gizli yüklenir; saat yüklenince uygulanır.'}
          </p>
          <div className="schedule-form">
            <label className="field">
              <span>Gün</span>
              <input
                type="date"
                value={date}
                min={localDateToday()}
                onChange={(event) => setDate(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Saat</span>
              <input
                type="time"
                value={time}
                onChange={(event) => setTime(event.target.value)}
              />
            </label>
          </div>
          {error && (
            <p className="action-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Vazgeç
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={!target || busy}
            onClick={() => void save()}
          >
            {busy ? 'Planlanıyor…' : 'Bu saate planla'}
          </button>
        </div>
      </div>
    </div>
  )
}

function EntryDetailModal({
  entry,
  onClose,
  onReschedule,
}: {
  entry: CalendarEntry
  onClose: () => void
  onReschedule: (entry: CalendarEntry) => void
}) {
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cal-entry-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <span className="clip-eyebrow">
              {entry.channel_name} ·{' '}
              {entry.orientation === 'horizontal' ? 'Yatay' : 'Dikey'}
            </span>
            <h2 id="cal-entry-title">{entry.title ?? 'Yayın dilimi'}</h2>
          </div>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="Kapat"
          >
            ×
          </button>
        </div>
        <div className="modal-body">
          <p className="detail-note">
            {entryTime(entry.scheduled_at)} · {entry.note}
          </p>
          {entry.metadata ? (
            <>
              <section className="detail-section">
                <h3>Başlık ve açıklama</h3>
                <p className="detail-title">{entry.metadata.title}</p>
                <p className="detail-description">{entry.metadata.description}</p>
                {entry.metadata.hook && (
                  <p className="detail-hook">
                    <b>Kanca:</b> {entry.metadata.hook}
                  </p>
                )}
              </section>
              <section className="detail-section">
                <h3>Etiketler</h3>
                {entry.metadata.tags.length > 0 ? (
                  <div className="tag-row">
                    {entry.metadata.tags.map((tag) => (
                      <span key={tag} className="tag-chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="detail-note">Etiket yok.</p>
                )}
              </section>
            </>
          ) : (
            <p className="detail-note">Bu kayıt için metaveri özeti yok.</p>
          )}
          {entry.youtube_url && (
            <a
              href={entry.youtube_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn--ghost"
            >
              YouTube'da aç ↗
            </a>
          )}
        </div>
        {canSchedule(entry) && (
          <div className="modal-actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => onReschedule(entry)}
            >
              Yayın saatini değiştir
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function CalendarScreen() {
  const now = new Date()
  const [cursor, setCursor] = useState({
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  })
  const [openRenderId, setOpenRenderId] = useState<number | null>(null)
  const [openEntry, setOpenEntry] = useState<CalendarEntry | null>(null)
  const [schedule, setSchedule] = useState<{
    entry: CalendarEntry
    date: string
  } | null>(null)
  const [dragEntry, setDragEntry] = useState<CalendarEntry | null>(null)
  const [dragOverDate, setDragOverDate] = useState<string | null>(null)

  const fetchCb = useCallback(
    () => fetchCalendar(cursor.year, cursor.month),
    [cursor],
  )
  const calendar = usePolling(fetchCb, 60000)

  const data: CalendarData | null =
    calendar.state.status === 'ok' ? calendar.state.data : null

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>()
    if (data) {
      for (const entry of data.entries) {
        const list = map.get(entry.local_date) ?? []
        list.push(entry)
        map.set(entry.local_date, list)
      }
    }
    return map
  }, [data])

  const grid = useMemo(
    () => monthGrid(cursor.year, cursor.month),
    [cursor],
  )

  const counts = useMemo(() => {
    if (!data) return { scheduled: 0, planned: 0, published: 0, empty: 0 }
    const result = { scheduled: 0, planned: 0, published: 0, empty: 0 }
    for (const entry of data.entries) {
      if (entry.status in result) result[entry.status as keyof typeof result] += 1
    }
    return result
  }, [data])

  function openDetail(entry: CalendarEntry) {
    if (entry.clip_render_id !== null) {
      setOpenRenderId(entry.clip_render_id)
    } else {
      setOpenEntry(entry)
    }
  }

  function openReschedule(entry: CalendarEntry, date: string) {
    if (!canSchedule(entry)) return
    setOpenEntry(null)
    setSchedule({ entry, date })
  }

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>Takvim</h1>
          <span className="screen-sub">
            Planlanan ve gerçekleşen yayınlar — videoyu sürükleyip istediğin
            saate koy
          </span>
        </div>
        <div className="cal-nav" role="group" aria-label="Ay gezinme">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() =>
              setCursor((current) =>
                shiftMonth(current.year, current.month, -1),
              )
            }
          >
            ‹ Önceki
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() =>
              setCursor({
                year: new Date().getFullYear(),
                month: new Date().getMonth() + 1,
              })
            }
          >
            Bugün
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() =>
              setCursor((current) =>
                shiftMonth(current.year, current.month, 1),
              )
            }
          >
            Sonraki ›
          </button>
        </div>
      </div>

      {calendar.state.status === 'loading' && (
        <LoadingState label="Takvim yükleniyor…" />
      )}
      {calendar.state.status === 'error' && (
        <ErrorState
          title="Takvim alınamadı"
          message={`Arka uca ulaşılamadı: ${calendar.state.message}.`}
          onRetry={calendar.retry}
        />
      )}

      {data && (
        <>
          {calendar.state.status === 'ok' && calendar.state.stale && (
            <StaleNote onRetry={calendar.retry} />
          )}

          {data.channels.length === 0 ? (
            <EmptyState title="Takvim henüz boş">
              Çalışan bir kanal ve yayın saatleri tanımlandığında planlanan
              yayınlar burada görünecek. Kanalı Başlat ve yayın profiline
              saat ekle.
            </EmptyState>
          ) : (
            <>
              <div className="cal-legend" aria-label="Yayın durumu göstergesi">
                <span className="cal-legend-item">
                  <i className="cal-dot cal-dot--vertical" aria-hidden="true" />
                  Dikey
                </span>
                <span className="cal-legend-item">
                  <i className="cal-dot cal-dot--horizontal" aria-hidden="true" />
                  Yatay
                </span>
                <span className="cal-legend-item nums">
                  {counts.scheduled} saat bekliyor
                </span>
                <span className="cal-legend-item nums">
                  {counts.planned} stokta
                </span>
                <span className="cal-legend-item nums">
                  {counts.published} yayında
                </span>
                <span className="cal-legend-item nums">
                  {counts.empty} boş dilim
                </span>
              </div>

              <section className="ink-panel cal-panel" aria-label="Ay görünümü">
                <div className="cal-month-head">
                  <h2>{data.month_label}</h2>
                </div>
                <div className="cal-scroll">
                  <div className="cal-grid" role="grid">
                    {WEEKDAYS.map((day) => (
                      <div key={day} className="cal-weekday" role="columnheader">
                        {day}
                      </div>
                    ))}
                    {grid.map((cell) => {
                      const entries = byDate.get(cell.date) ?? []
                      return (
                        <div
                          key={cell.date}
                          className={`cal-cell${
                            cell.inMonth ? '' : ' cal-cell--out'
                          }${cell.isToday ? ' cal-cell--today' : ''}${
                            dragOverDate === cell.date
                              ? ' cal-cell--dragover'
                              : ''
                          }`}
                          role="gridcell"
                          aria-label={cell.date}
                          onDragOver={(event) => {
                            if (!dragEntry) return
                            event.preventDefault()
                            setDragOverDate(cell.date)
                          }}
                          onDragLeave={() =>
                            setDragOverDate((current) =>
                              current === cell.date ? null : current,
                            )
                          }
                          onDrop={(event) => {
                            event.preventDefault()
                            const entry = dragEntry
                            setDragEntry(null)
                            setDragOverDate(null)
                            if (entry && canSchedule(entry)) {
                              openReschedule(entry, cell.date)
                            }
                          }}
                        >
                          <span className="cal-daynum nums">
                            {Number(cell.date.slice(-2))}
                          </span>
                          {entries.map((entry) => (
                            <CalendarChip
                              key={entry.id}
                              entry={entry}
                              draggable={canSchedule(entry)}
                              onOpen={openDetail}
                              onDragStart={setDragEntry}
                              onDragEnd={() => setDragEntry(null)}
                            />
                          ))}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </section>

              <div className="panel-gap" />

              <section className="ink-panel" aria-label="Kanal yayın saatleri">
                <h2>Kanal yayın saatleri</h2>
                <table className="info-table">
                  <thead>
                    <tr>
                      <th>Kanal</th>
                      <th>Shorts saatleri</th>
                      <th>Yatay saatleri</th>
                      <th>Günlük dikey</th>
                      <th>Günlük yatay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.channels.map((channel) => (
                      <tr key={channel.id}>
                        <td>
                          <span className="lib-channel">
                            {channel.ribbon_color && (
                              <i
                                style={{ background: channel.ribbon_color }}
                                aria-hidden="true"
                              />
                            )}
                            {channel.name}
                          </span>
                        </td>
                        <td className="nums">
                          {channel.publish_times_vertical.join(' · ')}
                          <small className="cal-tz"> ({channel.timezone})</small>
                        </td>
                        <td className="nums">
                          {channel.publish_times.join(' · ')}
                        </td>
                        <td className="nums">{channel.daily_vertical_limit}</td>
                        <td className="nums">{channel.daily_horizontal_limit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </>
          )}
        </>
      )}

      {openRenderId !== null && (
        <ClipDetailModal
          key={openRenderId}
          clipId={openRenderId}
          onClose={() => setOpenRenderId(null)}
        />
      )}
      {openEntry !== null && (
        <EntryDetailModal
          entry={openEntry}
          onClose={() => setOpenEntry(null)}
          onReschedule={(entry) =>
            openReschedule(entry, entry.local_date || localDateToday())
          }
        />
      )}
      {schedule !== null && (
        <ScheduleModal
          key={schedule.entry.id}
          entry={schedule.entry}
          initialDate={schedule.date}
          onClose={() => setSchedule(null)}
          onSaved={() => {
            setSchedule(null)
            calendar.retry()
          }}
        />
      )}
    </>
  )
}
