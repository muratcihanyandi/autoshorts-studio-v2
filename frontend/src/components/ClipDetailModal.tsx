import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import { fetchClipDetail, type ClipDetail } from '../api/media'
import { rescheduleCalendar } from '../api/calendar'
import { formatBytes, formatClock, formatDuration, formatTimeShort } from '../format'

const UPLOAD_LABEL: Record<string, string> = {
  not_uploaded: 'Henüz yüklenmedi',
  uploading: 'Yükleniyor',
  uploaded: 'Gizli yüklendi',
  verified: 'Doğrulandı',
  failed: 'Yükleme hatası',
}

function filterChips(filters: Record<string, unknown>): string[] {
  const chips: string[] = []
  if (filters.reaction_source === true) chips.push('Yalnız tepki videoları')
  const maxAge = filters.max_age_days
  if (typeof maxAge === 'number') chips.push(`Son ${maxAge} gün`)
  const patterns = filters.exclude_title_patterns
  if (Array.isArray(patterns)) {
    for (const pattern of patterns) chips.push(`Hariç: ${String(pattern)}`)
  }
  const trimStart = filters.trim_start_seconds
  const trimEnd = filters.trim_end_seconds
  if (typeof trimStart === 'number' && trimStart > 0) {
    chips.push(`Baştan ${formatClock(trimStart)} kırpma`)
  }
  if (typeof trimEnd === 'number' && trimEnd > 0) {
    chips.push(`Sondan ${formatClock(trimEnd)} kırpma`)
  }
  return chips
}

function planState(
  detail: ClipDetail,
  index: 'metadata' | 'upload' | 'public',
): 'done' | 'active' | 'pending' | 'failed' {
  const { publishing, metadata } = detail
  if (index === 'metadata') {
    if (metadata?.status === 'approved') return 'done'
    return metadata ? 'active' : 'pending'
  }
  if (index === 'upload') {
    if (publishing.upload_status === 'failed') return 'failed'
    if (['uploaded', 'verified'].includes(publishing.upload_status)) return 'done'
    return metadata?.status === 'approved' ? 'active' : 'pending'
  }
  if (publishing.visibility === 'public') return 'done'
  if (publishing.upload_status === 'verified') return 'active'
  return 'pending'
}

export function ClipDetailModal({
  clipId,
  onClose,
}: {
  clipId: number
  onClose: () => void
}) {
  const [detail, setDetail] = useState<ClipDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [planDate, setPlanDate] = useState('')
  const [planTime, setPlanTime] = useState('')
  const [planBusy, setPlanBusy] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchClipDetail(clipId).then(
      (payload) => {
        if (!cancelled) setDetail(payload)
      },
      (err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Klip yüklenemedi.')
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [clipId])

  async function savePlan() {
    setPlanBusy(true)
    setPlanError(null)
    try {
      const moment = new Date(`${planDate}T${planTime}`)
      if (Number.isNaN(moment.getTime())) {
        throw new Error('Geçersiz tarih veya saat.')
      }
      if (moment.getTime() <= Date.now()) {
        throw new Error('Yayın saati gelecekte olmalı.')
      }
      await rescheduleCalendar({ clipRenderId: clipId }, moment.toISOString())
      const payload = await fetchClipDetail(clipId)
      setDetail(payload)
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : 'Planlama başarısız.')
    } finally {
      setPlanBusy(false)
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const title =
    detail?.metadata?.title ?? detail?.source?.title ?? 'Hazır klip'
  const orientation =
    detail?.render.orientation === 'horizontal' ? 'Yatay tam kesit' : 'Dikey Shorts'
  const chips = detail ? filterChips(detail.filters) : []

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal clip-detail"
        role="dialog"
        aria-modal="true"
        aria-labelledby="clip-detail-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <span className="clip-eyebrow">
              {detail?.channel?.name ?? 'Kanal'} · {orientation}
            </span>
            <h2 id="clip-detail-title">{title}</h2>
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

        <div className="modal-body clip-detail-body">
          {error && (
            <div className="state-box error" role="alert">
              <h3>Klip açılamadı</h3>
              <p>{error}</p>
              <button type="button" onClick={onClose}>
                Kapat
              </button>
            </div>
          )}
          {!detail && !error && (
            <div className="ink-loading" aria-live="polite">
              Klip hazırlanıyor…
            </div>
          )}

          {detail && (
            <>
              <div className="clip-detail-main">
                {detail.render.stream_url ? (
                  <video
                    className="clip-player"
                    controls
                    preload="metadata"
                    poster={detail.render.thumbnail_url ?? undefined}
                    src={detail.render.stream_url}
                  >
                    Tarayıcın video oynatmayı desteklemiyor.
                  </video>
                ) : (
                  <div className="clip-player clip-player--empty">
                    Video henüz oynatılabilir değil.
                  </div>
                )}

                <div className="clip-player-meta">
                  <span>{formatDuration(detail.render.duration_seconds)}</span>
                  <span>
                    {detail.render.width} × {detail.render.height}
                  </span>
                  <span>{formatBytes(detail.render.file_bytes)}</span>
                  {detail.render.validation.ok === true && (
                    <span className="pill pill--ok">Doğrulandı</span>
                  )}
                </div>

                <section className="detail-section">
                  <h3>YouTube'a gidiş</h3>
                  <ol className="publish-plan">
                    <li className={`publish-step publish-step--${planState(detail, 'metadata')}`}>
                      <b>Metaveri</b>
                      <span>
                        {detail.metadata
                          ? detail.metadata.status === 'approved'
                            ? 'Onaylı'
                            : 'Onay bekliyor'
                          : 'Hazırlanıyor'}
                      </span>
                    </li>
                    <li className={`publish-step publish-step--${planState(detail, 'upload')}`}>
                      <b>Gizli yükleme</b>
                      <span>{UPLOAD_LABEL[detail.publishing.upload_status] ?? detail.publishing.upload_status}</span>
                    </li>
                    <li className={`publish-step publish-step--${planState(detail, 'public')}`}>
                      <b>Herkese açık</b>
                      <span>
                        {detail.publishing.visibility === 'public'
                          ? 'Yayında'
                          : detail.publishing.next_slot
                            ? formatTimeShort(detail.publishing.next_slot)
                            : 'Plan bekliyor'}
                      </span>
                    </li>
                  </ol>
                  <p className="detail-note">{detail.note}</p>
                  <div className="detail-inline">
                    <span>
                      Yayın saatleri:{' '}
                      {detail.publishing.publish_times.length > 0
                        ? detail.publishing.publish_times.join(' · ')
                        : 'varsayılan'}
                    </span>
                    <span>
                      Bugün: {detail.publishing.today_count}
                      {detail.publishing.daily_limit > 0
                        ? ` / ${detail.publishing.daily_limit}`
                        : ''}
                    </span>
                  </div>
                  {detail.publishing.scheduled_at && (
                    <p className="detail-note">
                      <b>Elle planlandı:</b>{' '}
                      {formatTimeShort(detail.publishing.scheduled_at)}
                    </p>
                  )}
                  {detail.publishing.visibility !== 'public' && (
                    <div className="schedule-form">
                      <label className="field">
                        <span>Yayın günü</span>
                        <input
                          type="date"
                          value={planDate}
                          onChange={(event) => setPlanDate(event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Yayın saati</span>
                        <input
                          type="time"
                          value={planTime}
                          onChange={(event) => setPlanTime(event.target.value)}
                        />
                      </label>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={planBusy || !planDate || !planTime}
                        onClick={() => void savePlan()}
                        title="Video bu saatte herkese açılacak."
                      >
                        {planBusy ? 'Planlanıyor…' : 'Bu saate planla'}
                      </button>
                    </div>
                  )}
                  {planError && (
                    <p className="action-error" role="alert">
                      {planError}
                    </p>
                  )}
                  {detail.publishing.youtube_url && (
                    <a
                      href={detail.publishing.youtube_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn--ghost"
                    >
                      YouTube'da aç ↗
                    </a>
                  )}
                </section>

                <section className="detail-section">
                  <h3>Başlık ve açıklama</h3>
                  {detail.metadata ? (
                    <>
                      <p className="detail-title">{detail.metadata.title}</p>
                      <p className="detail-description">{detail.metadata.description}</p>
                      {detail.metadata.hook && (
                        <p className="detail-hook">
                          <b>Kanca:</b> {detail.metadata.hook}
                        </p>
                      )}
                      <div className="detail-badges">
                        <span className="pill pill--idle">
                          Revizyon {detail.metadata.revision}
                        </span>
                        <span
                          className={`pill ${
                            detail.metadata.content_warning ? 'pill--warn' : 'pill--idle'
                          }`}
                        >
                          {detail.metadata.content_warning ? '+18' : '+18 değil'}
                        </span>
                        <span
                          className={`pill ${
                            detail.metadata.ai_disclosure ? 'pill--warn' : 'pill--idle'
                          }`}
                        >
                          {detail.metadata.ai_disclosure ? 'AI bildirimi' : 'AI bildirimi yok'}
                        </span>
                      </div>
                    </>
                  ) : (
                    <p className="detail-note">Bu klip için henüz metaveri üretilmedi.</p>
                  )}
                </section>

                <section className="detail-section">
                  <h3>Etiketler</h3>
                  {detail.metadata?.tags.length ? (
                    <div className="tag-row">
                      {detail.metadata.tags.map((tag) => (
                        <span key={tag} className="tag-chip">
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="detail-note">Etiket yok.</p>
                  )}
                </section>
              </div>

              <aside className="clip-detail-side">
                <section className="detail-section">
                  <h3>Kapak</h3>
                  {detail.render.thumbnail_url ? (
                    <img
                      className="detail-thumb"
                      src={detail.render.thumbnail_url}
                      alt={`${title} kapak görseli`}
                      onError={(event) => {
                        const sourceId = detail.source?.youtube_video_id
                        const fallback = sourceId
                          ? `https://i.ytimg.com/vi/${sourceId}/mqdefault.jpg`
                          : null
                        const image = event.currentTarget
                        if (fallback && image.src !== fallback) {
                          image.src = fallback
                        } else {
                          image.style.display = 'none'
                        }
                      }}
                    />
                  ) : (
                    <div className="detail-thumb detail-thumb--empty">Kapak yok</div>
                  )}
                  {detail.metadata?.thumbnail_text && (
                    <p className="detail-note">
                      Kapak metni: <b>{detail.metadata.thumbnail_text}</b>
                    </p>
                  )}
                </section>

                {detail.candidate && (
                  <section className="detail-section">
                    <h3>Motorun seçtiği an</h3>
                    <p className="detail-range">
                      {formatClock(detail.candidate.start_seconds)} –{' '}
                      {formatClock(detail.candidate.end_seconds)}
                    </p>
                    <p className="detail-note">
                      {detail.candidate.reason ?? 'Gerekçe kaydedilmedi.'}
                    </p>
                    <div className="detail-inline">
                      <span>Skor {detail.candidate.score.toFixed(2)}</span>
                      {detail.candidate.hype_confidence !== null && (
                        <span>Güven {Math.round(detail.candidate.hype_confidence * 100)}%</span>
                      )}
                    </div>
                  </section>
                )}

                <section className="detail-section">
                  <h3>Filtreler</h3>
                  {chips.length > 0 ? (
                    <div className="tag-row">
                      {chips.map((chip) => (
                        <span key={chip} className="tag-chip">
                          {chip}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="detail-note">Kaynakta ek filtre kuralı yok.</p>
                  )}
                </section>

                {detail.source && (
                  <section className="detail-section">
                    <h3>Kaynak video</h3>
                    <p className="detail-title">{detail.source.title}</p>
                    {detail.source.youtube_url ? (
                      <a
                        href={detail.source.youtube_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="detail-source-link"
                      >
                        {detail.source.channel_title ?? 'Kaynak kanal'}
                        <span aria-hidden="true"> ↗</span>
                      </a>
                    ) : (
                      <span className="detail-source-link">
                        {detail.source.channel_title ?? 'Kaynak kanal'}
                      </span>
                    )}
                    <p className="detail-note">
                      {formatTimeShort(detail.source.published_at)} ·{' '}
                      {formatDuration(detail.source.duration_seconds)}
                    </p>
                  </section>
                )}
              </aside>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
