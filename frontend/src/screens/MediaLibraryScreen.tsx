import { useCallback, useState } from 'react'

import { fetchMedia, type LibrarySource } from '../api/media'
import { formatBytes, formatDuration, formatTimeShort } from '../format'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'

/** Kaynak video etiketi -> (hap tonu, Türkçe etiket). */
const TAG_VIEW: Record<string, { tone: string; label: string }> = {
  '#queued': { tone: 'idle', label: 'Sırada' },
  '#downloading': { tone: 'run', label: 'İndiriliyor' },
  '#processing': { tone: 'run', label: 'İşleniyor' },
  '#done': { tone: 'ok', label: 'Stokta' },
  '#confirmed': { tone: 'ok', label: 'Onaylı' },
  '#error': { tone: 'error', label: 'Hata' },
  '#excluded': { tone: 'idle', label: 'Hariç' },
}

/** Kullanıcının etiket filtresi: null = tümü. */
const FILTERS: { tag: string | null; label: string }[] = [
  { tag: null, label: 'Tümü' },
  { tag: '#queued', label: 'Sırada' },
  { tag: '#downloading', label: 'İndiriliyor' },
  { tag: '#processing', label: 'İşleniyor' },
  { tag: '#done', label: 'Stokta' },
  { tag: '#error', label: 'Hata' },
]

const CLIP_STATUS_VIEW: Record<string, { tone: string; label: string }> = {
  rendered: { tone: 'ok', label: 'Hazır' },
  rendering: { tone: 'run', label: 'Render' },
  review: { tone: 'warn', label: 'İnceleme' },
  failed: { tone: 'error', label: 'Hata' },
}

function sourceView(tag: string) {
  return TAG_VIEW[tag] ?? { tone: 'idle', label: tag }
}

function SourceRow({ source }: { source: LibrarySource }) {
  const view = sourceView(source.tag)
  return (
    <tr>
      <td>
        <div className="lib-title">
          <b>{source.title}</b>
          <small className="nums">{source.youtube_video_id}</small>
        </div>
      </td>
      <td>
        {source.channel_name ? (
          <span className="lib-channel">
            {source.ribbon_color && (
              <i style={{ background: source.ribbon_color }} aria-hidden="true" />
            )}
            {source.channel_name}
          </span>
        ) : (
          '—'
        )}
      </td>
      <td>
        <span className={`pill pill--${view.tone}`}>{view.label}</span>
        {source.asset_stage_label && source.tag === '#processing' && (
          <small className="lib-stage">{source.asset_stage_label}</small>
        )}
      </td>
      <td className="nums">{formatDuration(source.duration_seconds)}</td>
      <td className="nums">
        {source.file_bytes > 0 ? formatBytes(source.file_bytes) : '—'}
      </td>
      <td className="nums">{formatTimeShort(source.updated_at)}</td>
    </tr>
  )
}

export function MediaLibraryScreen() {
  const [limit] = useState(60)
  const [extraPages, setExtraPages] = useState(0)
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  const fetchCb = useCallback(
    () => fetchMedia(limit + extraPages * limit, 0),
    [limit, extraPages],
  )
  const library = usePolling(fetchCb, 10000)

  const data = library.state.status === 'ok' ? library.state.data : null
  const sources = data
    ? data.sources.filter((s) => tagFilter === null || s.tag === tagFilter)
    : []
  const hasMore = data ? data.sources.length < data.sources_total : false

  return (
    <>
      <div className="screen-head">
        <h1>Medya Kütüphanesi</h1>
        <span className="screen-sub">
          İndirilen kaynaklar, üretilen klipler ve özel stok
        </span>
      </div>

      {library.state.status === 'loading' && (
        <LoadingState label="Kütüphane sorgulanıyor…" />
      )}
      {library.state.status === 'error' && (
        <ErrorState
          title="Kütüphane alınamadı"
          message={`Arka uca ulaşılamadı: ${library.state.message}.`}
          onRetry={library.retry}
        />
      )}

      {data && (
        <>
          {library.state.status === 'ok' && library.state.stale && (
            <StaleNote onRetry={library.retry} />
          )}

          {data.sources_total === 0 ? (
            <EmptyState title="Kütüphane boş">
              Yetkili kaynak kanallardan indirilen videolar, üretilen
              klipler ve yayın için bekleyen özel stok burada listelenecek.
              Otomasyon çalışırken ilk indirme işlemi kendi kendine
              başlar — yapman gereken bir şey yok.
            </EmptyState>
          ) : (
            <>
              <div className="stat-grid" aria-label="Kütüphane özeti">
                <div className="stat-card">
                  <span>Kaynak video</span>
                  <b className="nums">{data.summary.sources_total}</b>
                  <small>yetkili kanallardan</small>
                </div>
                <div className="stat-card">
                  <span>İşlenmiş</span>
                  <b className="nums">{data.summary.processed}</b>
                  <small>analizi tamamlanan</small>
                </div>
                <div className="stat-card">
                  <span>Shorts stoğu</span>
                  <b className="nums">{data.summary.shorts_ready}</b>
                  <small>dikey klip hazır</small>
                </div>
                <div className="stat-card">
                  <span>Tam kesit</span>
                  <b className="nums">{data.summary.full_cuts_ready}</b>
                  <small>reaksiyon kaynağı</small>
                </div>
              </div>

              <section className="ink-panel" aria-label="Kaynak videolar">
                <h2>Kaynak videolar</h2>
                <div className="filter-row" role="group" aria-label="Durum filtresi">
                  {FILTERS.map((f) => (
                    <button
                      key={f.label}
                      className={`filter-pill${tagFilter === f.tag ? ' active' : ''}`}
                      onClick={() => setTagFilter(f.tag)}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
                {sources.length === 0 ? (
                  <p className="plate-note">
                    Bu durumda video yok. Filtreyi değiştirip yeniden bak.
                  </p>
                ) : (
                  <table className="info-table">
                    <thead>
                      <tr>
                        <th>Video</th>
                        <th>Kanal</th>
                        <th>Durum</th>
                        <th>Süre</th>
                        <th>Boyut</th>
                        <th>Güncelleme</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((s) => (
                        <SourceRow key={s.id} source={s} />
                      ))}
                    </tbody>
                  </table>
                )}
                {hasMore && tagFilter === null && (
                  <button
                    className="btn btn--ghost more-button"
                    onClick={() => setExtraPages((n) => n + 1)}
                  >
                    Daha fazla yükle ({data.sources.length}/{data.sources_total})
                  </button>
                )}
              </section>

              <div className="panel-gap" />

              <section className="ink-panel" aria-label="Klipler">
                <h2>Klipler</h2>
                {data.clips.length === 0 ? (
                  <p className="plate-note">
                    Henüz klip yok — işlenen kaynak videolardan seçilen
                    adaylar render edildikçe dikey Shorts ve yatay tam
                    kesitler burada listelenir.
                  </p>
                ) : (
                  <table className="info-table">
                    <thead>
                      <tr>
                        <th>Video</th>
                        <th>Kanal</th>
                        <th>Yön</th>
                        <th>Durum</th>
                        <th>Süre</th>
                        <th>Boyut</th>
                        <th>Tarih</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.clips.map((clip) => {
                        const view =
                          CLIP_STATUS_VIEW[clip.status] ?? {
                            tone: 'idle',
                            label: clip.status,
                          }
                        return (
                          <tr key={clip.id}>
                            <td>
                              <div className="lib-title">
                                <b>{clip.title ?? 'Tam kesit'}</b>
                                {clip.candidate_reason && (
                                  <small>{clip.candidate_reason}</small>
                                )}
                              </div>
                            </td>
                            <td>
                              {clip.channel_name ? (
                                <span className="lib-channel">
                                  {clip.ribbon_color && (
                                    <i
                                      style={{ background: clip.ribbon_color }}
                                      aria-hidden="true"
                                    />
                                  )}
                                  {clip.channel_name}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td>{clip.orientation === 'vertical' ? 'Dikey' : 'Yatay'}</td>
                            <td>
                              <span className={`pill pill--${view.tone}`}>
                                {view.label}
                              </span>
                            </td>
                            <td className="nums">
                              {formatDuration(clip.duration_seconds)}
                            </td>
                            <td className="nums">
                              {clip.file_bytes > 0 ? formatBytes(clip.file_bytes) : '—'}
                            </td>
                            <td className="nums">{formatTimeShort(clip.created_at)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  )
}
