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

/** Tek YouTube videosu satırı: künye, izlenme verileri ve yönetim.
 * Kayıt dışı (stüdyo kaydında olmayan) videolar uyarı tonuyla öne
 * çıkar — "siteden silinmiş ama YouTube'ta kalan" videolar burada. */
function VideoRow({
  video,
  onDelete,
  deleting,
}: {
  video: YoutubeVideo
  onDelete: (video: YoutubeVideo) => void
  deleting: boolean
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const privacy = privacyView(video.privacy_status)
  return (
    <div className={`yt-row${video.managed ? '' : ' yt-row--orphan'}`}>
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
        <small className="nums">{formatDateTime(video.published_at)}</small>
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
          <>
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
          </>
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
  // Free planda kapı notu gösterilir — analytics ucu 403 {feature}
  // şekliyle döner.
  const [analytics, setAnalytics] = useState<YoutubeAnalyticsResponse | null>(
    null,
  )
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
  const orphanCount = data ? data.videos.filter((v) => !v.managed).length : 0
  const filteredVideos =
    data?.videos.filter((video) =>
      filter === 'tumu'
        ? true
        : filter === 'yonetim'
          ? video.managed
          : !video.managed,
    ) ?? []

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
      setActionError(
        err instanceof Error ? err.message : 'Video silinemedi.',
      )
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>YouTube</h1>
          <span className="screen-sub">
            Kanalının gören yüzü — videolar, analizler ve temizlik
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
                      <div className="stat-grid" aria-label="Kanal analizi">
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
                            {formatCount(data.youtube?.view_count ?? 0)}
                          </b>
                          <small>kanal geneli</small>
                        </div>
                        <div className="stat-card">
                          <span>Video sayısı</span>
                          <b className="nums">
                            {formatCount(data.youtube?.video_count ?? 0)}
                          </b>
                          <small>YouTube’ta görünür</small>
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
                          {filter !== 'kayit-disi' && (
                            <button
                              type="button"
                              className="btn--ghost yt-orphan-btn"
                              onClick={() => setFilter('kayit-disi')}
                            >
                              Kayıt dışı videoları filtrele →
                            </button>
                          )}
                        </div>
                      )}

                      <section className="ink-panel" aria-label="Kanal videoları">
                        <div className="panel-head-row">
                          <h2>Videolar</h2>
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
                                onDelete={(v) => void handleDelete(v)}
                                deleting={deletingId === video.youtube_video_id}
                              />
                            ))}
                          </div>
                        )}
                        <p className="plate-note">
                          Liste YouTube’dan 60 saniyelik önbellekle okunur;
                          silinen video en geç bir dakika içinde kaybolur.
                          Silme işlemi günlük kota bütçesinden 50 birim harcar.
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
