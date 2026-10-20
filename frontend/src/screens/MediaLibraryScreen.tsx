import { useCallback, useState } from 'react'

import {
  fetchMedia,
  removeSourceVideo,
  type LibraryClip,
  type LibrarySource,
} from '../api/media'
import { formatClock, formatDuration } from '../format'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'
import { ClipDetailModal } from '../components/ClipDetailModal'
import { StageTrack } from '../components/StageTrack'

const TAG_VIEW: Record<string, { tone: string; label: string }> = {
  '#queued': { tone: 'idle', label: 'Sırada' },
  '#downloading': { tone: 'run', label: 'İndiriliyor' },
  '#processing': { tone: 'run', label: 'İşleniyor' },
  '#done': { tone: 'ok', label: 'Stokta' },
  '#confirmed': { tone: 'ok', label: 'Tamamlandı' },
  '#error': { tone: 'error', label: 'Hata' },
}

const RENDER_VIEW: Record<string, { tone: string; label: string }> = {
  rendered: { tone: 'ok', label: 'Hazır' },
  rendering: { tone: 'run', label: 'Render' },
  review: { tone: 'warn', label: 'İnceleme' },
  failed: { tone: 'error', label: 'Hata' },
}

function sourceView(tag: string) {
  return TAG_VIEW[tag] ?? { tone: 'idle', label: tag }
}

function renderView(status: string | null) {
  if (!status) return { tone: 'idle', label: 'Sırada' }
  return RENDER_VIEW[status] ?? { tone: 'idle', label: status }
}

function publishView(clip: LibraryClip) {
  if (clip.visibility === 'public') return { tone: 'ok', label: 'Yayında' }
  if (clip.published_status === 'verified') {
    return { tone: 'run', label: 'Gizli · saat bekliyor' }
  }
  if (clip.published_status === 'uploaded') {
    return { tone: 'run', label: 'Gizli yüklendi' }
  }
  if (clip.published_status === 'failed') {
    return { tone: 'error', label: 'Yükleme hatası' }
  }
  if (clip.metadata_status === 'approved') {
    return { tone: 'warn', label: 'Yüklemeye hazır' }
  }
  return { tone: 'idle', label: 'Hazırlanıyor' }
}

function youtubeThumb(videoId: string | null): string | null {
  return videoId ? `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg` : null
}

function SelectedMoments({ source }: { source: LibrarySource }) {
  if (source.selected_candidates.length === 0) {
    return (
      <p className="product-note">
        Motor henüz klip anı seçmedi; adaylar değerlendiriliyor.
      </p>
    )
  }
  return (
    <div className="moment-list" aria-label="Seçilen klip anları">
      {source.selected_candidates.map((candidate) => {
        const view = renderView(candidate.render_status)
        return (
          <span key={candidate.id} className="moment-chip">
            <span className="nums">
              {formatClock(candidate.start_seconds)}–{formatClock(candidate.end_seconds)}
            </span>
            <span className={`pill pill--${view.tone}`}>{view.label}</span>
          </span>
        )
      })}
    </div>
  )
}

function SourceCard({
  source,
  featured = false,
  onRemove,
}: {
  source: LibrarySource
  featured?: boolean
  onRemove: (source: LibrarySource) => void
}) {
  const view = sourceView(source.tag)
  const thumb = youtubeThumb(source.youtube_video_id)
  const href = source.youtube_url ?? undefined
  const [confirmRemove, setConfirmRemove] = useState(false)
  return (
    <article className={`source-card${featured ? ' source-card--featured' : ''}`}>
      <a
        className="source-thumb"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        title="Kaynak videoyu YouTube'da aç"
      >
        {thumb ? (
          <img
            src={thumb}
            alt=""
            loading="lazy"
            onError={(event) => {
              event.currentTarget.style.display = 'none'
            }}
          />
        ) : (
          <span className="source-thumb-fallback" aria-hidden="true">
            ▶
          </span>
        )}
        {thumb && (
          <span className="source-play" aria-hidden="true">
            ▶
          </span>
        )}
      </a>
      <div className="source-body">
        <div className="source-heading">
          <a
            className="source-title"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {source.title}
          </a>
          <span className={`pill pill--${view.tone}`}>{view.label}</span>
        </div>
        <a
          className="source-channel"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          title="Kanalı YouTube'da aç"
        >
          {source.source_channel_title ?? 'Kaynak kanal'}
          <span aria-hidden="true"> ↗</span>
        </a>
        <StageTrack steps={source.stages} />
        <SelectedMoments source={source} />
        <div className="source-foot">
          <span>{source.selected_count} klip anı seçildi</span>
          {source.full_cut_ready && <span>Yatay tam kesit hazır</span>}
          {source.is_current && <span className="current-mark">Şu an motorda</span>}
          <span className="source-remove">
            {confirmRemove ? (
              <>
                <button
                  type="button"
                  className="btn--ghost"
                  onClick={() => onRemove(source)}
                  title="Videoyu dosyaları, klipleri ve kayıtlarıyla birlikte kalıcı olarak kaldırır."
                >
                  Kalıcı olarak kaldır
                </button>
                <button
                  type="button"
                  className="btn--ghost"
                  onClick={() => setConfirmRemove(false)}
                >
                  Vazgeç
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn--ghost"
                onClick={() => setConfirmRemove(true)}
                title="Videoyu sistemden kaldır: dosyalar, klipler ve kayıtlar silinir."
              >
                Kaldır
              </button>
            )}
          </span>
        </div>
      </div>
    </article>
  )
}

function ClipCard({
  clip,
  onOpen,
}: {
  clip: LibraryClip
  onOpen: (clip: LibraryClip) => void
}) {
  const view = publishView(clip)
  return (
    <button
      type="button"
      className="clip-card"
      onClick={() => onOpen(clip)}
      aria-label={`${clip.title} detayını aç`}
    >
      <span className="clip-card-thumb">
        {clip.thumbnail_url ? (
          <img
            src={clip.thumbnail_url}
            alt=""
            loading="lazy"
            onError={(event) => {
              const fallback =
                clip.source_platform === 'youtube'
                  ? youtubeThumb(clip.source_youtube_video_id)
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
          <span className="clip-card-placeholder" aria-hidden="true">
            ▶
          </span>
        )}
        <span className="clip-card-play" aria-hidden="true">
          ▶
        </span>
        <span className="clip-card-duration nums">
          {formatDuration(clip.duration_seconds)}
        </span>
      </span>
      <span className="clip-card-body">
        <b>{clip.title}</b>
        <small>
          {clip.channel_name ?? 'Kanal'} ·{' '}
          {clip.orientation === 'vertical' ? 'Dikey' : 'Yatay'}
        </small>
        <span className={`pill pill--${view.tone}`}>{view.label}</span>
      </span>
    </button>
  )
}

export function MediaLibraryScreen() {
  const [openClipId, setOpenClipId] = useState<number | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const fetchCb = useCallback(
    () => fetchMedia(60, 0, false, false, true, true),
    [],
  )
  const library = usePolling(fetchCb, 10000)

  const handleRemove = useCallback(
    async (source: LibrarySource) => {
      setRemoveError(null)
      try {
        await removeSourceVideo(source.id)
      } catch (err) {
        setRemoveError(
          err instanceof Error ? err.message : 'Video kaldırılamadı.',
        )
        return
      }
      library.retry()
    },
    [library.retry],
  )

  const data = library.state.status === 'ok' ? library.state.data : null
  const current =
    data?.sources.find((source) => source.id === data.current_source_id) ?? null
  const previous = data?.sources.filter((source) => source.id !== current?.id) ?? []
  const readyCount = data ? data.summary.shorts_ready + data.summary.full_cuts_ready : 0

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>Medya Kütüphanesi</h1>
          <span className="screen-sub">
            Motorun seçtiği videolar ve yayına hazır klipler
          </span>
        </div>
      </div>

      {removeError && (
        <p className="action-error" role="alert">
          {removeError}
        </p>
      )}

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

          <div className="stat-grid product-stat-grid" aria-label="Kütüphane özeti">
            <div className="stat-card">
              <span>Motorda</span>
              <b className="nums">{current ? 1 : 0}</b>
              <small>{current ? 'video işleniyor' : 'motor beklemede'}</small>
            </div>
            <div className="stat-card">
              <span>Motorun seçtiği</span>
              <b className="nums">{data.sources_total}</b>
              <small>video</small>
            </div>
            <div className="stat-card">
              <span>Hazır klip</span>
              <b className="nums">{readyCount}</b>
              <small>dikey Shorts ve tam kesit</small>
            </div>
          </div>

          {current && (
            <section className="current-panel" aria-label="Şu an motorda">
              <div className="current-panel-head">
                <h2>Şu an motorda</h2>
                <span className="live-dot">canlı</span>
              </div>
              <SourceCard source={current} featured onRemove={handleRemove} />
            </section>
          )}

          <section className="ink-panel" aria-label="Motorun seçtiği videolar">
            <h2>Motorun seçtiği videolar</h2>
            {data.sources_total === 0 && data.clips.length === 0 ? (
              <EmptyState title="Motor henüz klip seçmedi">
                Keşif havuzundaki videolar arka planda değerlendirilir. Motor
                bir videoyu seçtiğinde burada işlem aşamalarıyla görünür;
                seçilmeyen videolar kütüphaneye taşınmaz.
              </EmptyState>
            ) : previous.length > 0 ? (
              <div className="source-grid">
                {previous.map((source) => (
                  <SourceCard
                    key={source.id}
                    source={source}
                    onRemove={handleRemove}
                  />
                ))}
              </div>
            ) : (
              <p className="product-note">
                {current
                  ? 'Şu an işlenen video yukarıda. Tamamlanan seçimler burada listelenecek.'
                  : 'Henüz tamamlanmış bir seçim yok.'}
              </p>
            )}
          </section>

          <div className="panel-gap" />

          <section className="ink-panel" aria-label="Hazır videolar">
            <div className="panel-head-row">
              <h2>Hazır videolar</h2>
              <span className="panel-count">{data.clips.length} klip</span>
            </div>
            {data.clips.length === 0 ? (
              <p className="product-note">
                Hazır klip yok. Motor bir sonraki seçimi tamamladığında
                videolar burada oynatılabilir kartlar olarak görünür.
              </p>
            ) : (
              <div className="clip-grid">
                {data.clips.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    clip={clip}
                    onOpen={(selected) => setOpenClipId(selected.id)}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {openClipId !== null && (
        <ClipDetailModal
          key={openClipId}
          clipId={openClipId}
          onClose={() => setOpenClipId(null)}
        />
      )}
    </>
  )
}
