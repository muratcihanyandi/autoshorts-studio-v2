import { useCallback, useState } from 'react'

import {
  bulkClipAction,
  bulkVideoStatus,
  clipDownloadUrl,
  fetchMedia,
  removeClip,
  removeSourceVideo,
  type BulkClipActionResult,
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
  removed: { tone: 'idle', label: 'Kaldırıldı' },
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
  onRemove,
  selectable = false,
  selected = false,
  onToggleSelect,
}: {
  clip: LibraryClip
  onOpen: (clip: LibraryClip) => void
  onRemove: (clip: LibraryClip) => void
  selectable?: boolean
  selected?: boolean
  onToggleSelect?: (clip: LibraryClip) => void
}) {
  const view = publishView(clip)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const activate = () => {
    if (selectable) {
      onToggleSelect?.(clip)
    } else {
      onOpen(clip)
    }
  }

  return (
    <div
      className={`clip-card${selectable ? ' clip-card--selectable' : ''}${selected ? ' clip-card--selected' : ''}`}
      role="button"
      tabIndex={0}
      onClick={activate}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          activate()
        }
      }}
      aria-label={
        selectable
          ? `${clip.title} ${selected ? 'seçimi kaldır' : 'seç'}`
          : `${clip.title} detayını aç`
      }
    >
      {selectable && (
        <span
          className={`clip-check${selected ? ' clip-check--on' : ''}`}
          aria-hidden="true"
        >
          {selected ? '✓' : ''}
        </span>
      )}
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
        <span
          className="clip-card-remove"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          {confirmRemove ? (
            <>
              <button
                type="button"
                className="btn--ghost"
                onClick={() => onRemove(clip)}
                title="Klibi YouTube'tan ve yerelden kalıcı olarak kaldırır."
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
              title="Klibi kaldır: YouTube'taki gizli video ve yerel dosya silinir."
            >
              Kaldır
            </button>
          )}
        </span>
      </span>
    </div>
  )
}

export function MediaLibraryScreen() {
  const [openClipId, setOpenClipId] = useState<number | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [bulkResult, setBulkResult] = useState<BulkClipActionResult | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)
  const [reincludeBusy, setReincludeBusy] = useState(false)
  const [reincludeNote, setReincludeNote] = useState<string | null>(null)

  const fetchCb = useCallback(
    () => fetchMedia(60, 0, false, false, true, true),
    [],
  )
  const library = usePolling(fetchCb, 10000)
  const excludedCb = useCallback(
    () => fetchMedia(100, 0, false, false, false, false, true),
    [],
  )
  const excludedList = usePolling(excludedCb, 30000)

  const data = library.state.status === 'ok' ? library.state.data : null
  const retryLibrary = library.retry
  const excludedData =
    excludedList.state.status === 'ok' ? excludedList.state.data : null
  const current =
    data?.sources.find((source) => source.id === data.current_source_id) ?? null
  const previous = data?.sources.filter((source) => source.id !== current?.id) ?? []
  const readyCount = data ? data.summary.shorts_ready + data.summary.full_cuts_ready : 0

  const selectedSet = new Set(selectedIds)
  const toggleSelect = useCallback((clip: LibraryClip) => {
    setBulkResult(null)
    setSelectedIds((ids) =>
      ids.includes(clip.id)
        ? ids.filter((id) => id !== clip.id)
        : [...ids, clip.id],
    )
  }, [])

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelectedIds([])
    setConfirmBulkDelete(false)
    setBulkResult(null)
  }

  const runBulk = async (
    action: 'delete' | 'public' | 'private',
  ) => {
    setBulkBusy(true)
    setBulkResult(null)
    try {
      const result = await bulkClipAction(action, selectedIds)
      setBulkResult(result)
      if (action === 'delete') {
        setSelectedIds([])
        setConfirmBulkDelete(false)
      }
      retryLibrary()
    } catch (err) {
      setRemoveError(
        err instanceof Error ? err.message : 'Toplu eylem başarısız oldu.',
      )
    } finally {
      setBulkBusy(false)
    }
  }

  const downloadSelected = () => {
    for (const id of selectedIds) {
      const anchor = document.createElement('a')
      anchor.href = clipDownloadUrl(id)
      anchor.rel = 'noopener'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    }
  }

  /** Hariç videoları üretime geri al (kalıcı çözüm 2026-10-21):
   * kütüphane boşaldığında kullanıcının kendini kurtarma yolu. */
  const reincludeAll = async (ids: number[]) => {
    setReincludeBusy(true)
    setReincludeNote(null)
    try {
      const result = await bulkVideoStatus(ids, 'planned')
      setReincludeNote(
        `${result.updated} video işleme alındı` +
          (result.errors > 0 ? `, ${result.errors} atlandı` : '') +
          '.',
      )
      retryLibrary()
      excludedList.retry()
    } catch (err) {
      setRemoveError(
        err instanceof Error ? err.message : 'Geri alma başarısız oldu.',
      )
    } finally {
      setReincludeBusy(false)
    }
  }

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
      retryLibrary()
    },
    [retryLibrary],
  )

  const handleClipRemove = useCallback(
    async (clip: LibraryClip) => {
      setRemoveError(null)
      try {
        await removeClip(clip.id)
      } catch (err) {
        setRemoveError(
          err instanceof Error ? err.message : 'Klip kaldırılamadı.',
        )
        return
      }
      retryLibrary()
    },
    [retryLibrary],
  )

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
              {data.clips.length > 0 && !selectMode && (
                <button
                  type="button"
                  className="btn--ghost"
                  onClick={() => {
                    setSelectMode(true)
                    setSelectedIds([])
                    setBulkResult(null)
                  }}
                >
                  Toplu seç
                </button>
              )}
            </div>

            {selectMode && (
              <div className="bulk-bar" role="toolbar" aria-label="Toplu klip eylemleri">
                <span className="bulk-count">
                  <b className="nums">{selectedIds.length}</b> klip seçildi
                </span>
                <button
                  type="button"
                  className="btn--ghost"
                  onClick={() =>
                    setSelectedIds(
                      selectedIds.length === data.clips.length
                        ? []
                        : data.clips.map((clip) => clip.id),
                    )
                  }
                >
                  {selectedIds.length === data.clips.length
                    ? 'Temizle'
                    : 'Tümünü seç'}
                </button>
                <button
                  type="button"
                  className="btn--ghost"
                  disabled={selectedIds.length === 0 || bulkBusy}
                  onClick={downloadSelected}
                  title="Seçili klipleri bu bilgisayara indir."
                >
                  İndir
                </button>
                <button
                  type="button"
                  className="btn--ghost"
                  disabled={selectedIds.length === 0 || bulkBusy}
                  onClick={() => void runBulk('public')}
                  title="Seçili klipleri YouTube'da herkese açık yapar."
                >
                  Herkese Aç
                </button>
                <button
                  type="button"
                  className="btn--ghost"
                  disabled={selectedIds.length === 0 || bulkBusy}
                  onClick={() => void runBulk('private')}
                  title="Seçili klipleri YouTube'da gizliye alır."
                >
                  Gizliye Al
                </button>
                {confirmBulkDelete ? (
                  <>
                    <button
                      type="button"
                      className="btn--danger"
                      disabled={selectedIds.length === 0 || bulkBusy}
                      onClick={() => void runBulk('delete')}
                      title="Klipleri YouTube'tan ve yerelden kalıcı olarak kaldırır."
                    >
                      {bulkBusy
                        ? 'Kaldırılıyor…'
                        : `${selectedIds.length} klibi kalıcı olarak kaldır`}
                    </button>
                    <button
                      type="button"
                      className="btn--ghost"
                      onClick={() => setConfirmBulkDelete(false)}
                    >
                      Vazgeç
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn--ghost"
                    disabled={selectedIds.length === 0 || bulkBusy}
                    onClick={() => setConfirmBulkDelete(true)}
                    title="Klipleri kaldır: YouTube'taki videolar ve yerel dosyalar silinir."
                  >
                    Kaldır
                  </button>
                )}
                <button
                  type="button"
                  className="btn--ghost"
                  onClick={exitSelectMode}
                >
                  Bitti
                </button>
              </div>
            )}

            {bulkResult && (
              <p className="bulk-result" role="status">
                {bulkResult.ok} klip{' '}
                {bulkResult.action === 'delete'
                  ? 'kaldırıldı'
                  : bulkResult.action === 'public'
                    ? 'herkese açıldı'
                    : 'gizliye alındı'}
                {bulkResult.skipped > 0 && `, ${bulkResult.skipped} atlandı`}
                {bulkResult.errors > 0 && `, ${bulkResult.errors} hata`}
                .
              </p>
            )}

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
                    onRemove={handleClipRemove}
                    selectable={selectMode}
                    selected={selectedSet.has(clip.id)}
                    onToggleSelect={toggleSelect}
                  />
                ))}
              </div>
            )}
          </section>

          <div className="panel-gap" />

          <section className="ink-panel" aria-label="Hariç tutulan videolar">
            <div className="panel-head-row">
              <h2>Hariç tutulanlar</h2>
              <span className="panel-count nums">
                {excludedList.state.status === 'ok'
                  ? `${excludedList.state.data.sources_total} video`
                  : '…'}
              </span>
              <button
                type="button"
                className="btn--ghost"
                onClick={() => {
                  setShowExcluded((open) => !open)
                  setReincludeNote(null)
                }}
              >
                {showExcluded ? 'Gizle' : 'Göster'}
              </button>
            </div>

            {!showExcluded ? (
              <p className="product-note">
                Kural dışı kalan, kaldırılan ya da dosyaları silindiği için
                temizlenen videolar. Gerekirse işleme geri alınabilir.
              </p>
            ) : excludedData === null ? (
              <p className="product-note">Hariç listesi okunuyor…</p>
            ) : excludedData.sources.length === 0 ? (
              <p className="product-note">Hariç tutulan video yok.</p>
            ) : (
              <>
                <div className="excluded-actions">
                  <button
                    type="button"
                    className="btn--ghost"
                    disabled={reincludeBusy}
                    onClick={() =>
                      void reincludeAll(excludedData.sources.map((s) => s.id))
                    }
                    title="Listedeki tüm hariç videoları üretime geri alır."
                  >
                    {reincludeBusy
                      ? 'Geri alınıyor…'
                      : 'Tümünü İşleme Al'}
                  </button>
                  {reincludeNote && (
                    <span className="bulk-result" role="status">
                      {reincludeNote}
                    </span>
                  )}
                </div>
                <ul className="excluded-list">
                  {excludedData.sources.map((source) => (
                    <li key={source.id} className="excluded-row">
                      <span className="excluded-title" title={source.title}>
                        {source.title}
                      </span>
                      <small>{source.source_channel_title ?? 'Kaynak'}</small>
                      <button
                        type="button"
                        className="btn--ghost"
                        disabled={reincludeBusy}
                        onClick={() => void reincludeAll([source.id])}
                        title="Bu videoyu üretime geri alır."
                      >
                        İşleme Al
                      </button>
                    </li>
                  ))}
                </ul>
              </>
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
