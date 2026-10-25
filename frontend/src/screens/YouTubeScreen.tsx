import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  fetchChannelVideos,
  fetchChannelAnalytics,
  deleteYoutubeVideo,
  type YoutubeAnalyticsResponse,
  type YoutubeVideo,
} from '../api/youtube'
import { fetchChannels, type Channel } from '../api/channels'
import { usePolling } from '../hooks/usePolling'
import { formatCount, formatDateTime } from '../format'
import { notifyPulse } from '../pulse/bus'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'
import { GateNotice } from '../components/GateNotice'
import { gateFromError, type GateInfo } from '../gates'

type VideoFilter = 'tumu' | 'yonetim' | 'kayit-disi'

const PRIVACY_VIEW: Record<string, { tone: string; label: string }> = {
  public: { tone: 'ok', label: 'Yayında' },
  private: { tone: 'idle', label: 'Gizli' },
  unlisted: { tone: 'warn', label: 'Liste dışı' },
}

function privacyView(status: string) {
  return PRIVACY_VIEW[status] ?? { tone: 'idle', label: status }
}

const EMPTY_VIDEOS: YoutubeVideo[] = []

/** Tek YouTube videosu satırı: seçim kutusu, künye, izlenme verileri ve yönetim. */
function VideoRow({
  video,
  selected,
  onToggleSelect,
  onDelete,
  deleting,
}: {
  video: YoutubeVideo
  selected: boolean
  onToggleSelect: (id: string) => void
  onDelete: (video: YoutubeVideo) => void
  deleting: boolean
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const privacy = privacyView(video.privacy_status)

  return (
    <div className={`yt-row${video.managed ? '' : ' yt-row--orphan'}${selected ? ' yt-row--selected' : ''}`}>
      <div className="yt-row-select">
        <input
          type="checkbox"
          id={`check-${video.youtube_video_id}`}
          checked={selected}
          onChange={() => onToggleSelect(video.youtube_video_id)}
          aria-label={`${video.title} seç`}
          className="yt-checkbox"
        />
      </div>
      <a
        className="yt-thumb"
        href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
        target="_blank"
        rel="noopener noreferrer"
        title="YouTube'da aç"
      >
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <span aria-hidden="true">▶</span>
        )}
      </a>
      <div className="yt-info">
        <a
          className="yt-title"
          href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {video.title}
        </a>
        <div className="yt-meta-row">
          <small className="nums">{formatDateTime(video.published_at)}</small>
          {video.orientation && (
            <span className="yt-orientation-badge">
              {video.orientation === 'vertical' ? 'Shorts' : 'Yatay'}
            </span>
          )}
        </div>
      </div>
      <span className={`pill pill--${privacy.tone}`}>{privacy.label}</span>
      <span
        className={`pill pill--${video.managed ? 'ok' : 'warn'}`}
        title={
          video.managed
            ? 'Bu video stüdyonun yayın kayıtlarında yönetiliyor.'
            : 'Stüdyo kaydında yok: siteden silinmiş ya da elle yüklenmiş.'
        }
      >
        {video.managed ? 'Stüdyo yönetiminde' : 'Kayıt dışı'}
      </span>
      <div className="yt-stats nums" aria-label="İzlenme verileri">
        <span title="İzlenme">{formatCount(video.view_count)} izlenme</span>
        <span title="Beğeni">{formatCount(video.like_count)} beğeni</span>
        <span title="Yorum">{formatCount(video.comment_count)} yorum</span>
      </div>
      <span className="yt-actions">
        {confirmDelete ? (
          <div className="delete-confirm-group">
            <button
              type="button"
              className="btn--danger"
              disabled={deleting}
              onClick={() => onDelete(video)}
              title="Videoyu YouTube'tan kalıcı olarak siler."
            >
              {deleting ? 'Siliniyor…' : 'YouTube’tan sil'}
            </button>
            <button
              type="button"
              className="btn--ghost"
              onClick={() => setConfirmDelete(false)}
            >
              Vazgeç
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="btn--ghost"
            onClick={() => setConfirmDelete(true)}
            title="Videoyu YouTube'tan sil."
          >
            Sil
          </button>
        )}
      </span>
    </div>
  )
}

export function YouTubeScreen() {
  const channelsCb = useCallback(() => fetchChannels(), [])
  const channels = usePolling(channelsCb, 30000)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState<VideoFilter>('tumu')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // Toplu seçim ve silme durumları
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState<{ current: number; total: number } | null>(null)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [confirmOrphanDelete, setConfirmOrphanDelete] = useState(false)

  const channelList =
    channels.state.status === 'ok' ? channels.state.data.channels : []

  // Varsayılan kanal: ilk bağlı kanal (yoksa ilk kanal).
  useEffect(() => {
    if (selectedId !== null) return
    if (channelList.length === 0) return
    const connected = channelList.find((c) => c.status === 'connected')
    setSelectedId((connected ?? channelList[0]).id)
  }, [channelList, selectedId])

  // Kanal silinmişse seçimi sıfırla.
  useEffect(() => {
    if (
      selectedId !== null &&
      channelList.length > 0 &&
      !channelList.some((c) => c.id === selectedId)
    ) {
      setSelectedId(null)
    }
  }, [channelList, selectedId])

  const videosCb = useCallback(
    () => (selectedId === null ? Promise.resolve(null) : fetchChannelVideos(selectedId)),
    [selectedId],
  )
  const videos = usePolling(videosCb, 60000)

  // Analiz paneli (Pro): stüdyo yönetimindeki videoların toplamı.
  const [analytics, setAnalytics] = useState<YoutubeAnalyticsResponse | null>(null)
  const [analyticsGate, setAnalyticsGate] = useState<GateInfo | null>(null)
  useEffect(() => {
    if (selectedId === null) {
      setAnalytics(null)
      setAnalyticsGate(null)
      return
    }
    let cancelled = false
    setAnalytics(null)
    setAnalyticsGate(null)
    fetchChannelAnalytics(selectedId)
      .then((result) => {
        if (!cancelled) setAnalytics(result)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setAnalyticsGate(gateFromError(err))
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const selectedChannel: Channel | undefined = useMemo(
    () => channelList.find((c) => c.id === selectedId),
    [channelList, selectedId],
  )

  const data = videos.state.status === 'ok' ? videos.state.data : null
  const allVideos = data?.videos ?? EMPTY_VIDEOS
  const orphanVideos = useMemo(() => allVideos.filter((v) => !v.managed), [allVideos])
  const orphanCount = orphanVideos.length

  const filteredVideos = useMemo(
    () =>
      allVideos.filter((video) =>
        filter === 'tumu'
          ? true
          : filter === 'yonetim'
            ? video.managed
            : !video.managed,
      ),
    [allVideos, filter],
  )

  // Minimum API kotasıyla yerel video listesinden hesaplanan kapsamlı kanal analizleri:
  const localAnalytics = useMemo(() => {
    if (allVideos.length === 0) return null
    const totalViews = allVideos.reduce((acc, v) => acc + (v.view_count || 0), 0)
    const totalLikes = allVideos.reduce((acc, v) => acc + (v.like_count || 0), 0)
    const totalComments = allVideos.reduce((acc, v) => acc + (v.comment_count || 0), 0)
    const avgViews = Math.round(totalViews / allVideos.length)
    const avgLikes = Math.round(totalLikes / allVideos.length)
    const engagementRate =
      totalViews > 0
        ? (((totalLikes + totalComments) / totalViews) * 100).toFixed(2)
        : '0.00'
    const likeRatio =
      totalViews > 0 ? ((totalLikes / totalViews) * 100).toFixed(2) : '0.00'

    // Format dağılımı
    const shorts = allVideos.filter((v) => v.orientation === 'vertical')
    const horizontals = allVideos.filter((v) => v.orientation === 'horizontal')
    const shortsViews = shorts.reduce((acc, v) => acc + (v.view_count || 0), 0)
    const horizontalViews = horizontals.reduce((acc, v) => acc + (v.view_count || 0), 0)

    // Gizlilik durumu
    const publicVideos = allVideos.filter((v) => v.privacy_status === 'public')
    const privateVideos = allVideos.filter((v) => v.privacy_status === 'private')
    const unlistedVideos = allVideos.filter((v) => v.privacy_status === 'unlisted')

    return {
      totalViews,
      totalLikes,
      totalComments,
      avgViews,
      avgLikes,
      engagementRate,
      likeRatio,
      shortsCount: shorts.length,
      shortsViews,
      shortsAvgViews: shorts.length > 0 ? Math.round(shortsViews / shorts.length) : 0,
      horizontalCount: horizontals.length,
      horizontalViews,
      horizontalAvgViews: horizontals.length > 0 ? Math.round(horizontalViews / horizontals.length) : 0,
      publicCount: publicVideos.length,
      privateCount: privateVideos.length,
      unlistedCount: unlistedVideos.length,
    }
  }, [allVideos])

  // Seçim yönetimi
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const selectAllFiltered = () => {
    if (selectedIds.size === filteredVideos.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredVideos.map((v) => v.youtube_video_id)))
    }
  }

  const selectAllOrphans = () => {
    setSelectedIds(new Set(orphanVideos.map((v) => v.youtube_video_id)))
  }

  const clearSelection = () => {
    setSelectedIds(new Set())
    setConfirmBulkDelete(false)
    setConfirmOrphanDelete(false)
  }

  // Tekil video silme
  async function handleDelete(video: YoutubeVideo) {
    if (selectedId === null) return
    setDeletingId(video.youtube_video_id)
    setActionError(null)
    try {
      const result = await deleteYoutubeVideo(selectedId, video.youtube_video_id)
      notifyPulse({
        tone: 'ok',
        sentence: `“${video.title}” YouTube’tan silindi`,
        note: result.managed
          ? 'Stüdyo kayıtları ve yerel dosyalar da temizlendi.'
          : 'Kayıt dışı videoydu; yalnızca YouTube tarafı silindi.',
      })
      videos.retry()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Video silinemedi.')
    } finally {
      setDeletingId(null)
    }
  }

  // Toplu video silme (sıralı işlemle kota aşımını önler ve ilerleme bildirir)
  async function executeBulkDelete(ids: string[], isOrphanCleanup = false) {
    if (selectedId === null || ids.length === 0) return
    setBulkDeleting({ current: 0, total: ids.length })
    setActionError(null)

    let deletedCount = 0
    let lastError: string | null = null

    for (let index = 0; index < ids.length; index += 1) {
      const videoId = ids[index]
      setBulkDeleting({ current: index + 1, total: ids.length })
      try {
        await deleteYoutubeVideo(selectedId, videoId)
        deletedCount += 1
      } catch (err) {
        lastError = err instanceof Error ? err.message : 'Silinemedi'
      }
    }

    setBulkDeleting(null)
    setConfirmBulkDelete(false)
    setConfirmOrphanDelete(false)
    setSelectedIds(new Set())

    if (deletedCount > 0) {
      notifyPulse({
        tone: 'ok',
        sentence: isOrphanCleanup
          ? `${deletedCount} kayıt dışı video YouTube'tan toplu temizlendi.`
          : `${deletedCount} video YouTube'tan toplu silindi.`,
        note: lastError ? `Bazı videolarda hata oluştu: ${lastError}` : undefined,
      })
    }

    if (lastError && deletedCount === 0) {
      setActionError(`Toplu silme başarısız: ${lastError}`)
    }

    videos.retry()
  }

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>YouTube</h1>
          <span className="screen-sub">
            Kanalının gören yüzü — minimum kotayla derin analizler, video yönetimi ve toplu temizlik
          </span>
        </div>
      </div>

      {actionError && (
        <p className="action-error" role="alert">
          {actionError}
        </p>
      )}

      {channels.state.status === 'loading' && (
        <LoadingState label="Kanallar okunuyor…" />
      )}
      {channels.state.status === 'error' && (
        <ErrorState
          title="Kanallar alınamadı"
          message={`Arka uca ulaşılamadı: ${channels.state.message}.`}
          onRetry={channels.retry}
        />
      )}

      {channels.state.status === 'ok' && channelList.length === 0 && (
        <EmptyState title="Henüz kanal yok" action={<Link to="/kanallar">Kanallar ekranına git</Link>}>
          YouTube yönetimi kanal bazında çalışır. İlk kanalını ekleyip
          YouTube hesabına bağladığında burada videolarını, izlenmelerini
          ve kayıt dışı kalanları göreceksin.
        </EmptyState>
      )}

      {channelList.length > 0 && (
        <>
          <div className="chip-row yt-channel-row" role="group" aria-label="Kanal seçimi">
            {channelList.map((channel) => (
              <button
                key={channel.id}
                type="button"
                className={`chip yt-chip${selectedId === channel.id ? ' chip--on' : ''}`}
                onClick={() => {
                  setSelectedId(channel.id)
                  setFilter('tumu')
                  setSelectedIds(new Set())
                }}
                title={
                  channel.status === 'connected'
                    ? undefined
                    : 'Bu kanalın YouTube bağlantısı yok'
                }
              >
                <i style={{ background: channel.ribbon_color }} aria-hidden="true" />
                {channel.name}
                {channel.status !== 'connected' && <small>bağlı değil</small>}
              </button>
            ))}
          </div>

          {selectedId !== null && (
            <>
              {videos.state.status === 'loading' && (
                <LoadingState label="YouTube kanalı sorgulanıyor…" />
              )}
              {videos.state.status === 'error' && (
                <ErrorState
                  title="YouTube verisi alınamadı"
                  message={`${videos.state.message}`}
                  onRetry={videos.retry}
                />
              )}
              {videos.state.status === 'ok' && (
                <>
                  {videos.state.stale && <StaleNote onRetry={videos.retry} />}
                  {data &&
                    (() => {
                      if (!data.channel.connected) {
                        return (
                          <EmptyState
                            title="Bu kanalın YouTube bağlantısı yok"
                            action={
                              <Link to="/kanallar">Kanallar ekranından bağla</Link>
                            }
                          >
                            Videoları ve analizleri görebilmek için kanalın
                            YouTube hesabına OAuth ile bağlanması gerekir.
                          </EmptyState>
                        )
                      }
                      return null
                    })()}

                  {data?.channel.connected && (
                    <>
                      {/* Üst Analiz Kartları (Temel & Türetilmiş Metrikler) */}
                      <div className="stat-grid yt-stat-grid" aria-label="Kanal analizi">
                        <div className="stat-card">
                          <span>Abone</span>
                          <b className="nums">
                            {formatCount(data.youtube?.subscriber_count ?? 0)}
                          </b>
                          <small>{data.youtube?.channel_title ?? selectedChannel?.name}</small>
                        </div>
                        <div className="stat-card">
                          <span>Toplam izlenme</span>
                          <b className="nums">
                            {formatCount(data.youtube?.view_count ?? localAnalytics?.totalViews ?? 0)}
                          </b>
                          <small>kanal geneli</small>
                        </div>
                        <div className="stat-card">
                          <span>Video sayısı</span>
                          <b className="nums">
                            {formatCount(data.youtube?.video_count ?? allVideos.length)}
                          </b>
                          <small>YouTube’ta görünür</small>
                        </div>
                        <div className="stat-card">
                          <span>Ort. İzlenme</span>
                          <b className="nums">
                            {formatCount(localAnalytics?.avgViews ?? 0)}
                          </b>
                          <small>video başına ortalama</small>
                        </div>
                        <div className="stat-card">
                          <span>Etkileşim Oranı</span>
                          <b className="nums">
                            %{localAnalytics?.engagementRate ?? '0.00'}
                          </b>
                          <small>beğeni + yorum / izlenme</small>
                        </div>
                        <div className="stat-card">
                          <span>Kota kullanımı</span>
                          <b className="nums">
                            {formatCount(data.quota?.used_today ?? 0)}
                            <small>
                              / {formatCount(data.quota?.daily_limit ?? 0)}
                            </small>
                          </b>
                          <small>bugünlük YouTube API bütçesi</small>
                        </div>
                      </div>

                      {/* Derin Analiz Kırılımları (0 İlave Kota Tüketimi) */}
                      {localAnalytics && (
                        <div className="yt-breakdowns-panel" aria-label="Format ve gizlilik kırılımları">
                          <div className="yt-breakdown-card">
                            <span className="breakdown-title">İçerik Format Performansı</span>
                            <div className="breakdown-metrics">
                              <div className="breakdown-row">
                                <span className="breakdown-pill pill-vertical">📱 Shorts (9:16)</span>
                                <b>{localAnalytics.shortsCount} video</b>
                                <span className="nums">{formatCount(localAnalytics.shortsViews)} izlenme</span>
                                <small className="nums">Ort. {formatCount(localAnalytics.shortsAvgViews)}</small>
                              </div>
                              <div className="breakdown-row">
                                <span className="breakdown-pill pill-horizontal">🎬 Yatay (16:9)</span>
                                <b>{localAnalytics.horizontalCount} video</b>
                                <span className="nums">{formatCount(localAnalytics.horizontalViews)} izlenme</span>
                                <small className="nums">Ort. {formatCount(localAnalytics.horizontalAvgViews)}</small>
                              </div>
                            </div>
                          </div>

                          <div className="yt-breakdown-card">
                            <span className="breakdown-title">Yayın & Gizlilik Durumu</span>
                            <div className="breakdown-metrics">
                              <div className="breakdown-row">
                                <span className="breakdown-pill pill-public">✓ Yayında</span>
                                <b>{localAnalytics.publicCount} video</b>
                                <small>herkese açık</small>
                              </div>
                              <div className="breakdown-row">
                                <span className="breakdown-pill pill-private">🔒 Gizli</span>
                                <b>{localAnalytics.privateCount} video</b>
                                <small>yayın saatini bekliyor</small>
                              </div>
                              <div className="breakdown-row">
                                <span className="breakdown-pill pill-unlisted">🔗 Liste dışı</span>
                                <b>{localAnalytics.unlistedCount} video</b>
                                <small>yalnız bağlantıyla</small>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {analytics && (
                        <div className="yt-managed-strip" role="status">
                          <span>
                            Stüdyo yönetiminde{' '}
                            <b className="nums">
                              {analytics.managed_totals.video_count}
                            </b>{' '}
                            video
                          </span>
                          <span>
                            Toplam{' '}
                            <b className="nums">
                              {formatCount(
                                analytics.managed_totals.total_view_count,
                              )}
                            </b>{' '}
                            izlenme
                          </span>
                          <span>
                            Beğeniler{' '}
                            <b className="nums">
                              {formatCount(
                                analytics.managed_totals.total_like_count,
                              )}
                            </b>
                          </span>
                        </div>
                      )}
                      {analyticsGate && <GateNotice gate={analyticsGate} />}

                      {analytics?.top_videos && analytics.top_videos.length > 0 && (
                        <section className="ink-panel yt-top-panel" aria-label="En çok izlenen videolar">
                          <div className="panel-head-row">
                            <h2>Kanalın En Çok İzlenenleri</h2>
                            <small className="nums">İlk {analytics.top_videos.length} video</small>
                          </div>
                          <div className="yt-top-grid">
                            {analytics.top_videos.map((vid, idx) => (
                              <div key={vid.youtube_video_id} className="yt-top-card">
                                <span className="yt-top-rank nums">#{idx + 1}</span>
                                <div className="yt-top-body">
                                  <a
                                    href={`https://www.youtube.com/watch?v=${vid.youtube_video_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="yt-title"
                                  >
                                    {vid.title}
                                  </a>
                                  <div className="yt-stats nums">
                                    <span>{formatCount(vid.view_count)} izlenme</span>
                                    <span>{formatCount(vid.like_count)} beğeni</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </section>
                      )}

                      {/* Kayıt Dışı Videolar Uyarısı ve Tek Tuşla Toplu Temizleme */}
                      {orphanCount > 0 && (
                        <div className="yt-orphan-note" role="status">
                          <div className="yt-orphan-lead">
                            <span className="yt-orphan-icon" aria-hidden="true">⚠️</span>
                            <div>
                              <b className="nums">{orphanCount}</b> video stüdyo
                              kaydında yok — siteden silinmiş ya da elle yüklenmiş
                              olabilir. Yayınlanmasını istemediklerini buradan
                              YouTube’tan silebilirsin.
                            </div>
                          </div>
                          <div className="yt-orphan-actions">
                            {filter !== 'kayit-disi' && (
                              <button
                                type="button"
                                className="btn--ghost yt-orphan-btn"
                                onClick={() => setFilter('kayit-disi')}
                              >
                                Kayıt dışı videoları filtrele →
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn--ghost yt-orphan-select-btn"
                              onClick={selectAllOrphans}
                            >
                              Tüm Kayıt Dışıları Seç ({orphanCount})
                            </button>
                            {confirmOrphanDelete ? (
                              <div className="delete-confirm-group">
                                <button
                                  type="button"
                                  className="btn--danger"
                                  disabled={Boolean(bulkDeleting)}
                                  onClick={() =>
                                    void executeBulkDelete(
                                      orphanVideos.map((v) => v.youtube_video_id),
                                      true,
                                    )
                                  }
                                >
                                  {bulkDeleting
                                    ? `Siliniyor: ${bulkDeleting.current}/${bulkDeleting.total}`
                                    : 'Evet, Tümünü YouTube’tan Sil'}
                                </button>
                                <button
                                  type="button"
                                  className="btn--ghost"
                                  onClick={() => setConfirmOrphanDelete(false)}
                                >
                                  Vazgeç
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                className="btn--danger yt-orphan-bulk-btn"
                                onClick={() => setConfirmOrphanDelete(true)}
                              >
                                Kayıt Dışıları Toplu Sil ({orphanCount})
                              </button>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Toplu İşlem Çubuğu (Seçili Video Varsa Görünür) */}
                      {selectedIds.size > 0 && (
                        <div className="yt-batch-bar" role="toolbar" aria-label="Toplu video işlemleri">
                          <span className="batch-selected-count">
                            <b>{selectedIds.size}</b> video seçildi
                          </span>
                          <div className="batch-actions">
                            {confirmBulkDelete ? (
                              <div className="delete-confirm-group">
                                <button
                                  type="button"
                                  className="btn--danger"
                                  disabled={Boolean(bulkDeleting)}
                                  onClick={() => void executeBulkDelete(Array.from(selectedIds))}
                                >
                                  {bulkDeleting
                                    ? `Siliniyor: ${bulkDeleting.current}/${bulkDeleting.total}`
                                    : `Onayla (${selectedIds.size} Videoyu Sil)`}
                                </button>
                                <button
                                  type="button"
                                  className="btn--ghost"
                                  onClick={() => setConfirmBulkDelete(false)}
                                >
                                  Vazgeç
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                className="btn--danger"
                                onClick={() => setConfirmBulkDelete(true)}
                              >
                                Seçilenleri YouTube’tan Sil ({selectedIds.size})
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn--ghost"
                              onClick={clearSelection}
                            >
                              Seçimi Temizle
                            </button>
                          </div>
                        </div>
                      )}

                      <section className="ink-panel" aria-label="Kanal videoları">
                        <div className="panel-head-row">
                          <div className="panel-head-left">
                            <h2>Videolar</h2>
                            <button
                              type="button"
                              className="btn--ghost btn-sm select-all-toggle-btn"
                              onClick={selectAllFiltered}
                            >
                              {selectedIds.size === filteredVideos.length && filteredVideos.length > 0
                                ? 'Seçimi Kaldır'
                                : 'Listedekilerin Tümünü Seç'}
                            </button>
                          </div>
                          <div
                            className="chip-row"
                            role="group"
                            aria-label="Kayıt filtresi"
                          >
                            {(
                              [
                                ['tumu', 'Tümü'],
                                ['yonetim', 'Stüdyo yönetiminde'],
                                ['kayit-disi', 'Kayıt dışı'],
                              ] as [VideoFilter, string][]
                            ).map(([key, label]) => (
                              <button
                                key={key}
                                type="button"
                                className={`chip${filter === key ? ' chip--on' : ''}`}
                                aria-pressed={filter === key}
                                onClick={() => setFilter(key)}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>

                        {filteredVideos.length === 0 ? (
                          <p className="product-note">
                            {data.videos.length === 0
                              ? 'Kanalda video görünmüyor.'
                              : 'Bu filtrede video yok.'}
                          </p>
                        ) : (
                          <div className="yt-list">
                            {filteredVideos.map((video) => (
                              <VideoRow
                                key={video.youtube_video_id}
                                video={video}
                                selected={selectedIds.has(video.youtube_video_id)}
                                onToggleSelect={toggleSelect}
                                onDelete={(v) => void handleDelete(v)}
                                deleting={
                                  deletingId === video.youtube_video_id ||
                                  (Boolean(bulkDeleting) && selectedIds.has(video.youtube_video_id))
                                }
                              />
                            ))}
                          </div>
                        )}
                        <p className="plate-note">
                          Liste YouTube’dan 60 saniyelik önbellekle okunur;
                          silinen video en geç bir dakika içinde kaybolur.
                          Her silme işlemi günlük kota bütçesinden 50 birim harcar.
                        </p>
                      </section>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </>
  )
}
