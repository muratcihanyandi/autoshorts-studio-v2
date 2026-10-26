import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  fetchCalendar,
  rebuildCalendar,
  rescheduleCalendar,
  type CalendarEntry,
  type CalendarData,
} from '../api/calendar'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'
import { GateNotice } from '../components/GateNotice'
import { gateFromError, type GateInfo } from '../gates'
import { ClipDetailModal } from '../components/ClipDetailModal'
import { notifyPulse } from '../pulse/bus'

const WEEKDAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']

/** Günlük 1 saat aralıklı zaman dilimleri (00:00 - 23:00) */
const HOURLY_SLOTS = Array.from(
  { length: 24 },
  (_, i) => `${String(i).padStart(2, '0')}:00`,
)

/** Ay etiketleri (planlama penceresinde "27 Ekim 2026" gibi okunur). */
const MONTH_NAMES = [
  'Ocak',
  'Şubat',
  'Mart',
  'Nisan',
  'Mayıs',
  'Haziran',
  'Temmuz',
  'Ağustos',
  'Eylül',
  'Ekim',
  'Kasım',
  'Aralık',
]

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

/** ISO gün (YYYY-MM-DD) -> "27 Ekim 2026" (yerel okunur etiket). */
function formatScheduleDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return value
  const month = Number(match[2])
  const label = MONTH_NAMES[month - 1] ?? match[2]
  return `${Number(match[3])} ${label} ${match[1]}`
}

/** Çipin saati (yerel): sürükleme sırasında bırakma hedefi olur. */
function slotTimeOf(entry: CalendarEntry): string | null {
  const time = entryTime(entry.scheduled_at)
  return /^\d{2}:\d{2}$/.test(time) ? time : null
}

function CalendarChip({
  entry,
  draggable,
  onOpen,
  onDragStart,
  onDragEnd,
  onHoverTime,
}: {
  entry: CalendarEntry
  draggable: boolean
  onOpen: (entry: CalendarEntry) => void
  onDragStart: (entry: CalendarEntry) => void
  onDragEnd: () => void
  /** Sürükleme bir çipin üzerindeyken o çipin saatini bildirir: bırakılan
   * dilimin saati yeni yayın saati olur ("09:00 dilimine bırak" = 09:00). */
  onHoverTime: (time: string | null) => void
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
      onDragEnd={() => {
        onHoverTime(null)
        onDragEnd()
      }}
      onDragEnter={(event) => {
        event.stopPropagation()
        onHoverTime(slotTimeOf(entry))
      }}
      onDragOver={(event) => {
        event.preventDefault()
        event.stopPropagation()
        onHoverTime(slotTimeOf(entry))
      }}
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
  initialTime,
  onClose,
  onSaved,
}: {
  entry: CalendarEntry
  initialDate: string
  /** Bırakılan dilimin saati; yoksa kaydın kendi saati/varsayılan. */
  initialTime: string | null
  onClose: () => void
  onSaved: (movedTo: { date: string; time: string }) => void
}) {
  const target = scheduleTarget(entry)
  const [date, setDate] = useState(initialDate)
  const [time, setTime] = useState(() => {
    if (initialTime && /^\d{2}:\d{2}$/.test(initialTime)) return initialTime
    if (entry.status === 'scheduled' || entry.manual) {
      const current = entryTime(entry.scheduled_at)
      if (/^\d{2}:\d{2}$/.test(current)) return current
    }
    return '18:00'
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gate, setGate] = useState<GateInfo | null>(null)

  async function save() {
    if (!target) return
    setBusy(true)
    setError(null)
    setGate(null)
    try {
      const moment = new Date(`${date}T${time}`)
      if (Number.isNaN(moment.getTime())) {
        throw new Error('Geçersiz tarih veya saat.')
      }
      if (moment.getTime() <= Date.now()) {
        throw new Error('Yayın saati gelecekte olmalı.')
      }
      await rescheduleCalendar(target, moment.toISOString())
      onSaved({ date, time })
    } catch (err) {
      // Free planda manuel planlama kapalı: hata değil plan notu.
      const gateInfo = gateFromError(err)
      if (gateInfo) {
        setGate(gateInfo)
      } else {
        setError(err instanceof Error ? err.message : 'Planlama başarısız.')
      }
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
          {/* Hedef net görünsün: kullanıcı hangi gün/saate taşıdığını
              onaylamadan önce okur (2026-10-25 bildirimi: bırakılan gün
              ile kaydedilen gün karışıyordu). */}
          <p className="schedule-target" aria-live="polite">
            Yeni yayın: <b>{formatScheduleDate(date)}</b> · <b>{time}</b>
            {entryTime(entry.scheduled_at) !== '—' && (
              <span className="schedule-target-old">
                {' '}
                (şu an {formatScheduleDate(entry.local_date)} ·{' '}
                {entryTime(entry.scheduled_at)})
              </span>
            )}
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
          {gate && <GateNotice gate={gate} />}
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
    /** Sürüklenen çipin bırakıldığı dilimin saati (varsa). */
    time: string | null
  } | null>(null)
  /** Kayıt sonrası taşıma onayı: tarih gerçekten değişti mi görünsün. */
  const [notice, setNotice] = useState<string | null>(null)
  const [dragOverDate, setDragOverDate] = useState<string | null>(null)
  const [draggingEntry, setDraggingEntry] = useState<CalendarEntry | null>(null)
  const [hoveredSlotTime, setHoveredSlotTime] = useState<string | null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  const [toastMessage, setToastMessage] = useState<{
    id: number
    text: string
    tone: 'ok' | 'error'
  } | null>(null)

  useEffect(() => {
    if (!toastMessage) return
    const timer = setTimeout(() => {
      setToastMessage(null)
    }, 4500)
    return () => clearTimeout(timer)
  }, [toastMessage])

  async function handleRebuildCalendar() {
    setRebuilding(true)
    try {
      const res = await rebuildCalendar()
      setToastMessage({
        id: Date.now(),
        text: `Takvim yeniden oluşturuldu! En çok izlenen saat (${res.peak_hour}) 1. sıraya yerleştirildi (${res.rebuilt_count} video planlandı).`,
        tone: 'ok',
      })
      notifyPulse({
        tone: 'ok',
        sentence: res.message,
        link: '/takvim',
      })
      await calendar.refresh()
    } catch (err) {
      setToastMessage({
        id: Date.now(),
        text:
          err instanceof Error
            ? err.message
            : 'Takvim yeniden oluşturulamadı.',
        tone: 'error',
      })
    } finally {
      setRebuilding(false)
    }
  }

  async function handleDropSchedule(
    entry: CalendarEntry,
    targetDate: string,
    targetSlotTime: string | null,
  ) {
    if (!canSchedule(entry)) return
    const target = scheduleTarget(entry)
    if (!target) return

    let finalTime = targetSlotTime
    if (!finalTime || !/^\d{2}:\d{2}$/.test(finalTime)) {
      const current = entryTime(entry.scheduled_at)
      if (/^\d{2}:\d{2}$/.test(current)) {
        finalTime = current
      } else {
        finalTime = '18:00'
      }
    }

    let moment = new Date(`${targetDate}T${finalTime}:00`)
    if (Number.isNaN(moment.getTime())) {
      moment = new Date(`${targetDate}T18:00:00`)
    }
    if (moment.getTime() <= Date.now()) {
      moment = new Date(Date.now() + 10 * 60 * 1000)
      const h = String(moment.getHours()).padStart(2, '0')
      const m = String(moment.getMinutes()).padStart(2, '0')
      finalTime = `${h}:${m}`
    }

    try {
      const targetEntries = byDate.get(targetDate) ?? []
      const existingVideo = targetEntries.find(
        (e) =>
          e.channel_id === entry.channel_id &&
          e.id !== entry.id &&
          e.status !== 'empty' &&
          entryTime(e.scheduled_at) === finalTime,
      )

      if (existingVideo && canSchedule(existingVideo)) {
        const oldTime = entryTime(entry.scheduled_at)
        const oldDate = entry.local_date
        let oldMoment =
          /^\d{2}:\d{2}$/.test(oldTime) && oldDate
            ? new Date(`${oldDate}T${oldTime}:00`)
            : null

        if (!oldMoment || Number.isNaN(oldMoment.getTime()) || oldMoment.getTime() <= Date.now()) {
          oldMoment = new Date(Date.now() + 15 * 60 * 1000)
        }

        await rescheduleCalendar(target, moment.toISOString())
        await rescheduleCalendar(scheduleTarget(existingVideo)!, oldMoment.toISOString())

        const entryTitle = entry.title?.trim() || 'Video'
        const existingTitle = existingVideo.title?.trim() || 'Video'
        const swapTimeStr = /^\d{2}:\d{2}$/.test(oldTime) ? oldTime : 'yeni saat'
        const msg = `“${entryTitle}” (${finalTime}) ve “${existingTitle}” (${swapTimeStr}) saatleri takas edildi.`
        setToastMessage({
          id: Date.now(),
          text: msg,
          tone: 'ok',
        })
        notifyPulse({
          tone: 'ok',
          sentence: msg,
          link: '/takvim',
        })
      } else {
        await rescheduleCalendar(target, moment.toISOString())
        const title = entry.title?.trim() || 'Video'
        const readableDate = formatScheduleDate(targetDate)
        const msg = `“${title}” ${readableDate} (${finalTime}) tarihine alındı.`
        setToastMessage({
          id: Date.now(),
          text: msg,
          tone: 'ok',
        })
        notifyPulse({
          tone: 'ok',
          sentence: msg,
          link: '/takvim',
        })
      }
        await calendar.refresh()
    } catch (err) {
      const gateInfo = gateFromError(err)
      if (gateInfo) {
        setToastMessage({
          id: Date.now(),
          text: `Planlama yükseltme gerektirir: ${gateInfo.requiredPlan}`,
          tone: 'error',
        })
      } else {
        setToastMessage({
          id: Date.now(),
          text: err instanceof Error ? err.message : 'Planlama başarısız oldu.',
          tone: 'error',
        })
      }
    }
  }
  // Sürükleme olayları aynı tikte state görmediği için ref'ler de tutulur:
  // aksi halde drop sırasında kayıt null görünüp planlama sessizce
  // atlanıyordu (kullanıcı bildirimi 2026-10-25: "tarihi değişmiyor").
  const dragEntryRef = useRef<CalendarEntry | null>(null)
  const hoveredSlotTimeRef = useRef<string | null>(null)

  const cleanupDrag = useCallback(() => {
    dragEntryRef.current = null
    setDraggingEntry(null)
    hoveredSlotTimeRef.current = null
    setHoveredSlotTime(null)
    setDragOverDate(null)
  }, [])

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

  // Yön göstergeleri yalnız gerçekten var olan yönler için: kanalda yatay
  // üretim yeteneği yoksa (tüm kaynaklar dikey) yatay dilim de yoktur.
  // Geçmişte yayınlanmış yatay video varsa turuncu çip görünür, göstergesi
  // de kalmalı.
  const { showsVertical, showsHorizontal } = useMemo(() => {
    const channels = data?.channels ?? []
    const entries = data?.entries ?? []
    const supported = (orientation: 'vertical' | 'horizontal') =>
      channels.some((channel) =>
        channel.orientations
          ? channel.orientations.includes(orientation)
          : true,
      ) ||
      entries.some((entry) => entry.orientation === orientation)
    return {
      showsVertical: supported('vertical'),
      showsHorizontal: supported('horizontal'),
    }
  }, [data])

  function openDetail(entry: CalendarEntry) {
    if (entry.clip_render_id !== null) {
      setOpenRenderId(entry.clip_render_id)
    } else {
      setOpenEntry(entry)
    }
  }

  function openReschedule(
    entry: CalendarEntry,
    date: string,
    time: string | null = null,
  ) {
    if (!canSchedule(entry)) return
    setOpenEntry(null)
    setSchedule({ entry, date, time })
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
        <div className="cal-actions-head">
          <button
            type="button"
            className="btn btn--primary cal-rebuild-btn"
            disabled={rebuilding}
            onClick={() => void handleRebuildCalendar()}
            title="Kanal ayarlarındaki kotalarla takvimi baştan kurar ve zirve saate 1 video yerleştirir"
          >
            {rebuilding
              ? 'Yeniden Oluşturuluyor…'
              : '⚡ Takvimi Yeniden Oluştur'}
          </button>
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
      </div>

      {notice && (
        <p className="schedule-notice" role="status">
          <span>Taşındı: {notice}</span>
          <button
            type="button"
            className="btn--ghost"
            onClick={() => setNotice(null)}
            aria-label="Bildirimi kapat"
          >
            ×
          </button>
        </p>
      )}

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
                {showsVertical && (
                  <span className="cal-legend-item">
                    <i
                      className="cal-dot cal-dot--vertical"
                      aria-hidden="true"
                    />
                    Dikey
                  </span>
                )}
                {showsHorizontal && (
                  <span className="cal-legend-item">
                    <i
                      className="cal-dot cal-dot--horizontal"
                      aria-hidden="true"
                    />
                    Yatay
                  </span>
                )}
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
                <div
                  className="cal-scroll"
                  onDragLeave={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                      setDragOverDate(null)
                      setHoveredSlotTime(null)
                      hoveredSlotTimeRef.current = null
                    }
                  }}
                >
                  <div className="cal-grid" role="grid">
                    {WEEKDAYS.map((day) => (
                      <div key={day} className="cal-weekday" role="columnheader">
                        {day}
                      </div>
                    ))}
                    {grid.map((cell, cellIndex) => {
                      const entries = byDate.get(cell.date) ?? []
                      const isHoveredDay =
                        dragOverDate === cell.date && draggingEntry !== null
                      const colIndex = cellIndex % 7
                      const rowIndex = Math.floor(cellIndex / 7)
                      const totalRows = Math.ceil(grid.length / 7)
                      const alignRight = colIndex >= 4
                      const alignBottom = rowIndex >= totalRows - 2

                      return (
                        <div
                          key={cell.date}
                          className={`cal-cell${
                            cell.inMonth ? '' : ' cal-cell--out'
                          }${cell.isToday ? ' cal-cell--today' : ''}${
                            isHoveredDay ? ' cal-cell--dragover' : ''
                          }`}
                          role="gridcell"
                          aria-label={cell.date}
                          onDragEnter={(event) => {
                            if (!dragEntryRef.current && !draggingEntry) return
                            event.preventDefault()
                            if (dragOverDate !== cell.date) {
                              setDragOverDate(cell.date)
                            }
                          }}
                          onDragOver={(event) => {
                            if (!dragEntryRef.current && !draggingEntry) return
                            event.preventDefault()
                            event.dataTransfer.dropEffect = 'move'
                            if (dragOverDate !== cell.date) {
                              setDragOverDate(cell.date)
                            }
                          }}
                          onDrop={(event) => {
                            event.preventDefault()
                            const entry =
                              dragEntryRef.current || draggingEntry
                            const hoveredTime =
                              hoveredSlotTimeRef.current || hoveredSlotTime
                            cleanupDrag()
                            if (entry && canSchedule(entry)) {
                              void handleDropSchedule(
                                entry,
                                cell.date,
                                hoveredTime,
                              )
                            }
                          }}
                        >
                          <span className="cal-daynum nums">
                            {Number(cell.date.slice(-2))}
                          </span>

                          {isHoveredDay && (
                            <div
                              className={`cal-hourly-overlay${
                                alignRight
                                  ? ' cal-hourly-overlay--right'
                                  : ' cal-hourly-overlay--left'
                              }${
                                alignBottom
                                  ? ' cal-hourly-overlay--bottom'
                                  : ' cal-hourly-overlay--top'
                              }`}
                              onDragOver={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                e.dataTransfer.dropEffect = 'move'
                              }}
                            >
                              <div
                                className="cal-hourly-head"
                                onDragOver={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  e.dataTransfer.dropEffect = 'move'
                                }}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  const entry =
                                    dragEntryRef.current || draggingEntry
                                  cleanupDrag()
                                  if (entry && canSchedule(entry)) {
                                    void handleDropSchedule(
                                      entry,
                                      cell.date,
                                      null,
                                    )
                                  }
                                }}
                              >
                                <div className="cal-hourly-head-top">
                                  <span className="cal-hourly-title">
                                    {formatScheduleDate(cell.date)}
                                  </span>
                                  <span className="cal-hourly-drop-hint">
                                    Güne Bırak
                                  </span>
                                </div>
                                <span className="cal-hourly-sub">
                                  Saate Bırakın (1 Saat Aralıklarla)
                                </span>
                              </div>
                              <div className="cal-hourly-grid">
                                {HOURLY_SLOTS.map((hour) => {
                                  const activeEntryId =
                                    dragEntryRef.current?.id ||
                                    draggingEntry?.id
                                  const isCurrentSlot =
                                    dragEntryRef.current &&
                                    dragEntryRef.current.local_date ===
                                      cell.date &&
                                    entryTime(
                                      dragEntryRef.current.scheduled_at,
                                    ) === hour
                                  const occupied = entries.find(
                                    (e) =>
                                      e.status !== 'empty' &&
                                      e.id !== activeEntryId &&
                                      entryTime(e.scheduled_at) === hour,
                                  )
                                  const isCardHover =
                                    (hoveredSlotTimeRef.current ||
                                      hoveredSlotTime) === hour
                                  return (
                                    <div
                                      key={hour}
                                      className={`cal-hour-card${
                                        isCurrentSlot
                                          ? ' cal-hour-card--current'
                                          : occupied
                                          ? ' cal-hour-card--occupied'
                                          : ' cal-hour-card--free'
                                      }${
                                        isCardHover
                                          ? ' cal-hour-card--hover'
                                          : ''
                                      }`}
                                      onDragEnter={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        if (
                                          hoveredSlotTimeRef.current !== hour
                                        ) {
                                          hoveredSlotTimeRef.current = hour
                                          setHoveredSlotTime(hour)
                                        }
                                      }}
                                      onDragOver={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        e.dataTransfer.dropEffect = 'move'
                                      }}
                                      onDrop={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        const entry =
                                          dragEntryRef.current ||
                                          draggingEntry
                                        cleanupDrag()
                                        if (entry && canSchedule(entry)) {
                                          void handleDropSchedule(
                                            entry,
                                            cell.date,
                                            hour,
                                          )
                                        }
                                      }}
                                    >
                                      <span className="cal-hour-time nums">
                                        {hour}
                                      </span>
                                      {isCurrentSlot ? (
                                        <span className="cal-hour-curr">
                                          Şu anki
                                        </span>
                                      ) : occupied ? (
                                        <span
                                          className="cal-hour-tag"
                                          title={occupied.title ?? ''}
                                        >
                                          {occupied.title
                                            ? occupied.title.slice(0, 8)
                                            : 'Dolu'}
                                        </span>
                                      ) : (
                                        <span className="cal-hour-free">
                                          + Boş
                                        </span>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            </div>
                          )}

                          {entries.map((entry) => (
                            <CalendarChip
                              key={entry.id}
                              entry={entry}
                              draggable={canSchedule(entry)}
                              onOpen={openDetail}
                              onDragStart={(picked) => {
                                dragEntryRef.current = picked
                                setDraggingEntry(picked)
                              }}
                              onDragEnd={() => {
                                cleanupDrag()
                              }}
                              onHoverTime={(time) => {
                                hoveredSlotTimeRef.current = time
                                setHoveredSlotTime(time)
                              }}
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
                      {showsHorizontal && <th>Yatay saatleri</th>}
                      <th>Günlük dikey</th>
                      {showsHorizontal && <th>Günlük yatay</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {data.channels.map((channel) => {
                      // Alan yoksa (eski API) yatay destekli varsayilir.
                      const hasHorizontal =
                        channel.orientations?.includes('horizontal') ?? true
                      return (
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
                            <small className="cal-tz">
                              {' '}
                              ({channel.timezone})
                            </small>
                          </td>
                          {showsHorizontal && (
                            <td className="nums">
                              {hasHorizontal ? (
                                channel.publish_times.join(' · ')
                              ) : (
                                <span className="cal-tz">
                                  Bu kanalda yatay üretim yok
                                </span>
                              )}
                            </td>
                          )}
                          <td className="nums">
                            {channel.daily_vertical_limit}
                          </td>
                          {showsHorizontal && (
                            <td className="nums">
                              {hasHorizontal
                                ? channel.daily_horizontal_limit
                                : '—'}
                            </td>
                          )}
                        </tr>
                      )
                    })}
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
      {toastMessage && (
        <div
          className={`cal-toast-popup cal-toast--${toastMessage.tone}`}
          role="status"
          aria-live="polite"
        >
          <span className="cal-toast-icon">
            {toastMessage.tone === 'ok' ? '✓' : '⚠️'}
          </span>
          <span className="cal-toast-text">{toastMessage.text}</span>
          <button
            type="button"
            className="cal-toast-close"
            onClick={() => setToastMessage(null)}
            aria-label="Kapat"
          >
            ×
          </button>
        </div>
      )}
      {schedule !== null && (
        <ScheduleModal
          key={`${schedule.entry.id}-${schedule.date}-${schedule.time ?? ''}`}
          entry={schedule.entry}
          initialDate={schedule.date}
          initialTime={schedule.time}
          onClose={() => setSchedule(null)}
          onSaved={(movedTo) => {
            setSchedule(null)
            // Tasiyici onay: kullanici yeni gun/saati ekranda gorur.
            setNotice(
              `${schedule.entry.title ?? 'Video'} → ${formatScheduleDate(
                movedTo.date,
              )} · ${movedTo.time}`,
            )
            void calendar.refresh()
          }}
        />
      )}
    </>
  )
}
