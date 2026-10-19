import { useCallback, useEffect } from 'react'

import { fetchPipeline, type PipelineSource } from '../api/pipeline'
import { usePolling } from '../hooks/usePolling'
import { formatBytes, formatDuration } from '../format'
import { jobAction } from '../jobNarrative'
import { StaleNote } from './States'

const PLATFORM_LABEL: Record<string, string> = {
  youtube: 'YouTube',
  twitch: 'Twitch',
  kick: 'Kick',
}

/** Boru hattı özetindeki sayıların açılımı: izlenen kaynak kanallar,
 * o an sürünen işler ve sırada bekleyenler. Genel Bakış'taki özet
 * tablo sade kalır; ayrıntı burada istenince açılır. */
export function PipelineDetailModal({ onClose }: { onClose: () => void }) {
  const fetchCb = useCallback(() => fetchPipeline(), [])
  const view = usePolling(fetchCb, 10000)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const data = view.state.status === 'ok' ? view.state.data : null
  const sources: PipelineSource[] = data?.sources ?? []
  const active = data?.active ?? []
  const queued = data?.queued ?? []

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Boru hattı detayı"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="modal">
        <div className="modal-head">
          <h2>Boru hattı detayı</h2>
          <button className="btn btn--ghost" onClick={onClose}>
            Kapat
          </button>
        </div>
        <div className="modal-body">
          {view.state.status === 'loading' && (
            <p className="plate-note">Boru hattı sorgulanıyor…</p>
          )}
          {view.state.status === 'error' && (
            <p className="plate-note">
              Boru hattı durumu alınamıyor ({view.state.message}).
            </p>
          )}
          {view.state.status === 'ok' && (
            <>
              {view.state.stale && <StaleNote onRetry={view.retry} />}

              <div className="flow-section">
                <h3>İzlenen kaynaklar</h3>
                {sources.length === 0 ? (
                  <p className="plate-note">
                    Henüz yetkili kaynak yok. Kanallar ekranından kaynak
                    eklenince izleme başlar.
                  </p>
                ) : (
                  sources.map((s) => (
                    <div className="flow-row" key={s.id}>
                      <b>{s.title}</b>
                      <span className="pill pill--idle">
                        {PLATFORM_LABEL[s.platform] ?? s.platform}
                      </span>
                      {s.channel_name && (
                        <span className="flow-soft">
                          <i
                            style={{ background: s.ribbon_color ?? undefined }}
                            aria-hidden="true"
                          />
                          {s.channel_name}
                        </span>
                      )}
                      <span className="flow-soft nums">
                        {s.videos} video izlendi
                      </span>
                    </div>
                  ))
                )}
              </div>

              <div className="flow-section">
                <h3>Şu an sürüyor</h3>
                {active.length === 0 ? (
                  <p className="plate-note">
                    Motor boşta — çalışan iş yok.
                  </p>
                ) : (
                  active.map((card) => (
                    <div className="flow-row" key={card.job_id}>
                      <span className="pill pill--run">sürüyor</span>
                      {card.title ? (
                        <b>{card.title}</b>
                      ) : (
                        <b>{jobAction(card)}</b>
                      )}
                      {card.title && (
                        <span className="flow-soft">
                          {jobAction(card)}
                        </span>
                      )}
                      {card.channel_name && (
                        <span className="flow-soft">
                          <i
                            style={{
                              background: card.ribbon_color ?? undefined,
                            }}
                            aria-hidden="true"
                          />
                          {card.channel_name}
                        </span>
                      )}
                      <span className="flow-soft nums">
                        {formatDuration(card.elapsed_seconds)} sürüyor
                        {card.eta_seconds !== null
                          ? ` · ≈${formatDuration(card.eta_seconds)} kaldı`
                          : ''}
                      </span>
                      {card.download && (
                        <span className="flow-soft nums">
                          {formatBytes(card.download.bytes)}
                          {card.download.expected_bytes
                            ? ` / ≈${formatBytes(card.download.expected_bytes)}`
                            : ''}
                        </span>
                      )}
                      {card.youtube_video_id && (
                        <a
                          href={`https://www.youtube.com/watch?v=${card.youtube_video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="lib-yt-link nums"
                          title="YouTube'da izle"
                        >
                          YouTube ↗
                        </a>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div className="flow-section">
                <h3>Sırada bekleyen</h3>
                {queued.length === 0 ? (
                  <p className="plate-note">Bekleyen iş yok.</p>
                ) : (
                  queued.map((card) => (
                    <div className="flow-row" key={card.job_id}>
                      <span className="flow-pos nums">{card.position}.</span>
                      {card.title ? (
                        <b>{card.title}</b>
                      ) : (
                        <b>{jobAction(card)}</b>
                      )}
                      {card.title && (
                        <span className="flow-soft">{jobAction(card)}</span>
                      )}
                      {card.channel_name && (
                        <span className="flow-soft">{card.channel_name}</span>
                      )}
                      {card.youtube_video_id && (
                        <a
                          href={`https://www.youtube.com/watch?v=${card.youtube_video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="lib-yt-link nums"
                          title="YouTube'da izle"
                        >
                          YouTube ↗
                        </a>
                      )}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
