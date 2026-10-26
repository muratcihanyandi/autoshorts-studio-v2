import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import '../styles/achievements.css'
import { useActiveChannel } from '../context/ChannelContext'
import {
  fetchChannelVideos,
  type YoutubeVideosResponse,
} from '../api/youtube'
import { fetchMe, type UserProfile } from '../api/auth'
import { computeAchievements } from '../achievements/achievementsList'
import { TrophyIcon } from '../components/TrophyIcons'
import { TrophyNotification } from '../components/TrophyNotification'
import { ChannelPill } from '../components/ChannelPill'
import type {
  ChannelMetrics,
  ComputedAchievement,
  TrophyTier,
} from '../types/achievements'
import { EmptyState, LoadingState } from '../components/States'

type FilterTier = 'all' | TrophyTier | 'unlocked' | 'locked'

const TIER_NAMES: Record<TrophyTier, string> = {
  bronze: 'Bronz',
  silver: 'Gümüş',
  gold: 'Altın',
  platinum: 'Platin',
}

/**
 * YouTube kanal ve video verilerinden başarım metriklerini üretir.
 * Her kanalın verisi tamamen kendi videoları ve kendi istatistiklerinden hesaplanır.
 */
function deriveMetrics(data: YoutubeVideosResponse | null): ChannelMetrics {
  if (!data) {
    return {
      totalVideos: 0,
      totalViews: 0,
      subscriberCount: 0,
      totalLikes: 0,
      totalComments: 0,
      shortsCount: 0,
      shortsViews: 0,
      horizontalCount: 0,
      horizontalViews: 0,
      watchHours: 0,
      maxDailyViews: 0,
      engagementRate: 0,
    }
  }

  const videos = data.videos ?? []
  const ytStats = data.youtube

  const totalViews =
    ytStats?.view_count && ytStats.view_count > 0
      ? ytStats.view_count
      : videos.reduce((sum, v) => sum + (v.view_count || 0), 0)

  const subscriberCount = ytStats?.subscriber_count ?? 0
  const totalVideos =
    ytStats?.video_count && ytStats.video_count > 0 ? ytStats.video_count : videos.length

  const totalLikes = videos.reduce((sum, v) => sum + (v.like_count || 0), 0)
  const totalComments = videos.reduce((sum, v) => sum + (v.comment_count || 0), 0)

  const shorts = videos.filter((v) => v.orientation === 'vertical')
  const horizontals = videos.filter((v) => v.orientation === 'horizontal')

  const shortsViews = shorts.reduce((sum, v) => sum + (v.view_count || 0), 0)
  const horizontalViews = horizontals.reduce((sum, v) => sum + (v.view_count || 0), 0)

  // 1 Günde alınan en yüksek izlenme (o kanaldaki tepe izlenme)
  const dailyBuckets: Record<string, number> = {}
  let maxSingleVideoViews = 0

  for (const v of videos) {
    if (v.view_count > maxSingleVideoViews) {
      maxSingleVideoViews = v.view_count
    }
    if (v.published_at) {
      const day = v.published_at.slice(0, 10)
      dailyBuckets[day] = (dailyBuckets[day] || 0) + (v.view_count || 0)
    }
  }

  const maxBucketViews = Object.values(dailyBuckets).reduce(
    (max, val) => Math.max(max, val),
    0,
  )
  const maxDailyViews = Math.max(maxSingleVideoViews, maxBucketViews)

  // İzlenme Saati tahmini (Uzun video izlenmeleri * ortalama 4.5 dk / 60)
  const watchHours = Math.round((horizontalViews * 4.5) / 60)

  // Etkileşim oranı: (Likes + Comments) / max(totalViews, 1) * 100
  const engagementRate =
    totalViews > 0
      ? parseFloat((((totalLikes + totalComments) / totalViews) * 100).toFixed(2))
      : 0

  return {
    totalVideos,
    totalViews,
    subscriberCount,
    totalLikes,
    totalComments,
    shortsCount: shorts.length,
    shortsViews,
    horizontalCount: horizontals.length,
    horizontalViews,
    watchHours,
    maxDailyViews,
    engagementRate,
  }
}

export function AchievementsScreen() {
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null)
  const { channels, activeChannelId, activeChannel, loading: loadingChannels } =
    useActiveChannel()

  const [videoData, setVideoData] = useState<YoutubeVideosResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Filtreler
  const [tierFilter, setTierFilter] = useState<FilterTier>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Ses ayarları
  const [soundEnabled, setSoundEnabled] = useState(true)

  // Kupa bildirimi (otomatik tek seferlik duyulur)
  const [activeToast, setActiveToast] = useState<ComputedAchievement | null>(null)

  // Kullanıcı profilini yükle
  useEffect(() => {
    let cancelled = false
    void fetchMe()
      .then((user) => {
        if (!cancelled) setCurrentUser(user)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  // Seçili kanalın YouTube verilerini yükle (Kanala Özel Başarım Ağacı)
  const loadChannelData = useCallback(async (channelId: number) => {
    setErrorMsg(null)
    try {
      const res = await fetchChannelVideos(channelId)
      setVideoData(res)
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : 'Kanalın YouTube verisi alınamadı. Kanalın bağlı olduğundan emin olun.',
      )
    }
  }, [])

  useEffect(() => {
    if (activeChannelId !== null) {
      void loadChannelData(activeChannelId)
    } else {
      setVideoData(null)
    }
  }, [activeChannelId, loadChannelData])

  // Seçili kanala ait metrikler ve başarımları bağımsız hesapla
  const metrics = useMemo(() => deriveMetrics(videoData), [videoData])

  // Hem HESABA hem KANALA özel LocalStorage anahtarı:
  // Bir kanalın açılan kupaları diğer kanalın kupa ağacına kesinlikle karışmaz!
  const storageKey = useMemo(() => {
    const uid = currentUser?.id ?? 'me'
    const chId = activeChannelId ?? 'none'
    return `autoshorts_seen_trophies_u_${uid}_ch_${chId}`
  }, [currentUser?.id, activeChannelId])

  const { achievements, summary } = useMemo(() => {
    return computeAchievements(metrics)
  }, [metrics])

  // Yeni açılan kupa tespiti ve otomatik bildirim/ses tetikleme
  useEffect(() => {
    if (!videoData) return

    try {
      const seenRaw = localStorage.getItem(storageKey)
      const seenIds: string[] = seenRaw ? JSON.parse(seenRaw) : []
      const newlyUnlocked = achievements.find(
        (a) => a.unlocked && !seenIds.includes(a.id),
      )

      if (newlyUnlocked) {
        setActiveToast(newlyUnlocked)
        const updated = [...seenIds, newlyUnlocked.id]
        localStorage.setItem(storageKey, JSON.stringify(updated))
      }
    } catch {
      // LocalStorage hataları yoksayılır
    }
  }, [achievements, videoData, storageKey])

  // Filtreleme
  const filteredAchievements = useMemo(() => {
    return achievements.filter((ach) => {
      if (tierFilter === 'unlocked' && !ach.unlocked) return false
      if (tierFilter === 'locked' && ach.unlocked) return false
      if (
        tierFilter !== 'all' &&
        tierFilter !== 'unlocked' &&
        tierFilter !== 'locked' &&
        ach.tier !== tierFilter
      ) {
        return false
      }

      if (categoryFilter !== 'all' && ach.category !== categoryFilter) {
        return false
      }

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim()
        const matchTitle = ach.title.toLowerCase().includes(q)
        const matchDesc = ach.description.toLowerCase().includes(q)
        if (!matchTitle && !matchDesc) return false
      }

      return true
    })
  }, [achievements, tierFilter, categoryFilter, searchQuery])

  const selectedChannel = activeChannel

  return (
    <div className="achievements-page">
      {/* Kupa Bildirimi (otomatik tek seferlik duyulur) */}
      <TrophyNotification
        achievement={activeToast}
        onDismiss={() => setActiveToast(null)}
        soundEnabled={soundEnabled}
      />

      {/* Sayfa başlığı: mevcut screen-head dili */}
      <header className="achievements-header">
        <div className="achievements-title-wrap">
          <h1 className="achievements-h1">Başarımlar</h1>
          <p className="achievements-sub">
            {currentUser
              ? `${currentUser.username} · ${currentUser.plan} planı`
              : 'Kupa ilerlemesi kanal bazında takip edilir'}
          </p>
          {activeChannel && <ChannelPill channel={activeChannel} />}
        </div>

        <div className="achievements-controls">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setSoundEnabled((v) => !v)}
            aria-pressed={soundEnabled}
            title={soundEnabled ? 'Kupa sesleri açık' : 'Kupa sesleri kapalı'}
          >
            {soundEnabled ? 'Ses açık' : 'Ses kapalı'}
          </button>
        </div>
      </header>

      {/* Yükleniyor veya Boş Durum */}
      {loadingChannels ? (
        <LoadingState label="Kanallar yükleniyor…" />
      ) : channels.length === 0 ? (
        <EmptyState
          title="Bağlı kanal bulunamadı"
          action={<Link to="/kanallar" className="btn btn--ghost">Kanallara git</Link>}
        >
          Başarımları görüntülemek için bir kanal bağlayın.
        </EmptyState>
      ) : (
        <>
          {errorMsg && (
            <div className="ach-error-banner" role="alert">
              <span>{errorMsg}</span>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => activeChannelId && void loadChannelData(activeChannelId)}
              >
                Tekrar dene
              </button>
            </div>
          )}

          {/* KUPA ÖZETİ PANOSU */}
          <section
            className="ink-panel"
            aria-label={`${selectedChannel?.name ?? 'Kanal'} kupa istatistiği`}
          >
            <h2>Kupa durumu</h2>
            <div className="ach-summary-body">
              <div className="ps-level-badge">
                <TrophyIcon
                  tier="platinum"
                  size={32}
                  unlocked={summary.isMonetized}
                />
                <div className="ps-level-content">
                  <span className="ps-level-tag">Seviye</span>
                  <span className="ps-level-num">{summary.level}</span>
                </div>
              </div>

              <div className="ps-progress-box">
                <div className="ps-progress-labels">
                  <span>Genel ilerleme</span>
                  <span className="ps-progress-percent">
                    %{summary.completionPercentage} ({summary.unlockedCount}/
                    {summary.total})
                  </span>
                </div>
                <div
                  className="ps-progress-bar-wrap"
                  role="meter"
                  aria-valuenow={summary.completionPercentage}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Kupa ilerlemesi"
                >
                  <div
                    className="ps-progress-bar-fill"
                    style={{ width: `${summary.completionPercentage}%` }}
                  />
                </div>
              </div>

              <div className="ps-trophy-counters">
                <div className="ps-counter" title="Bronz kupalar">
                  <TrophyIcon tier="bronze" size={22} unlocked={true} />
                  <div className="ps-counter-info">
                    <span className="ps-counter-val">
                      {summary.bronze.unlocked}/{summary.bronze.total}
                    </span>
                    <span className="ps-counter-name">Bronz</span>
                  </div>
                </div>

                <div className="ps-counter" title="Gümüş kupalar">
                  <TrophyIcon tier="silver" size={22} unlocked={true} />
                  <div className="ps-counter-info">
                    <span className="ps-counter-val">
                      {summary.silver.unlocked}/{summary.silver.total}
                    </span>
                    <span className="ps-counter-name">Gümüş</span>
                  </div>
                </div>

                <div className="ps-counter" title="Altın kupalar">
                  <TrophyIcon tier="gold" size={22} unlocked={true} />
                  <div className="ps-counter-info">
                    <span className="ps-counter-val">
                      {summary.gold.unlocked}/{summary.gold.total}
                    </span>
                    <span className="ps-counter-name">Altın</span>
                  </div>
                </div>

                <div className="ps-counter" title="Platin kupalar">
                  <TrophyIcon
                    tier="platinum"
                    size={22}
                    unlocked={summary.isMonetized}
                  />
                  <div className="ps-counter-info">
                    <span className="ps-counter-val">
                      {summary.platinum.unlocked}/{summary.platinum.total}
                    </span>
                    <span className="ps-counter-name">Platin</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* PARA KAZANMA TAKİBİ */}
          <section className="ink-panel">
            <div className="panel-head-row">
              <h2>Para kazanma (YPP)</h2>
              <span
                className={`pill ${summary.isMonetized ? 'pill--ok' : 'pill--warn'}`}
              >
                {summary.isMonetized ? 'Açık' : 'Hedefe doğru'}
              </span>
            </div>
            <div className="monetization-tracks">
              {/* Kriter 1: Abone Eşiği */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">1.000 abone</span>
                  <span className="monetization-track-val">
                    {metrics.subscriberCount.toLocaleString('tr-TR')} / 1.000
                  </span>
                </div>
                <div className="monetization-track-bar">
                  <div
                    className="monetization-track-fill"
                    style={{
                      width: `${Math.min(100, (metrics.subscriberCount / 1000) * 100)}%`,
                    }}
                  />
                </div>
                <small
                  className={`monetization-track-note ${
                    metrics.subscriberCount >= 1000
                      ? 'monetization-track-note--done'
                      : ''
                  }`}
                >
                  {metrics.subscriberCount >= 1000
                    ? 'Tamamlandı'
                    : `Kalan: ${Math.max(0, 1000 - metrics.subscriberCount).toLocaleString('tr-TR')}`}
                </small>
              </div>

              {/* Kriter 2A: 4000 Saat Yatay İzlenme */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">4.000 saat (yatay)</span>
                  <span className="monetization-track-val">
                    {metrics.watchHours.toLocaleString('tr-TR')} / 4.000 saat
                  </span>
                </div>
                <div className="monetization-track-bar">
                  <div
                    className="monetization-track-fill"
                    style={{
                      width: `${Math.min(100, (metrics.watchHours / 4000) * 100)}%`,
                    }}
                  />
                </div>
                <small
                  className={`monetization-track-note ${
                    metrics.watchHours >= 4000
                      ? 'monetization-track-note--done'
                      : ''
                  }`}
                >
                  {metrics.watchHours >= 4000
                    ? 'Tamamlandı'
                    : `Kalan: ${Math.max(0, 4000 - metrics.watchHours).toLocaleString('tr-TR')} saat`}
                </small>
              </div>

              {/* Kriter 2B: 10 Milyon Shorts İzlenmesi */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">10 milyon Shorts</span>
                  <span className="monetization-track-val">
                    {metrics.shortsViews.toLocaleString('tr-TR')} / 10.000.000
                  </span>
                </div>
                <div className="monetization-track-bar">
                  <div
                    className="monetization-track-fill"
                    style={{
                      width: `${Math.min(100, (metrics.shortsViews / 10000000) * 100)}%`,
                    }}
                  />
                </div>
                <small
                  className={`monetization-track-note ${
                    metrics.shortsViews >= 10000000
                      ? 'monetization-track-note--done'
                      : ''
                  }`}
                >
                  {metrics.shortsViews >= 10000000
                    ? 'Tamamlandı'
                    : `Kalan: ${Math.max(0, 10000000 - metrics.shortsViews).toLocaleString(
                        'tr-TR',
                      )}`}
                </small>
              </div>
            </div>
          </section>

          {/* FİLTRE & ARAMA ÇUBUĞU */}
          <div className="achievements-filter-bar">
            <div className="ach-filter-group chip-row">
              <button
                type="button"
                className={`chip ${tierFilter === 'all' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('all')}
              >
                Tümü ({achievements.length})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'unlocked' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('unlocked')}
              >
                Açılanlar ({summary.unlockedCount})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'locked' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('locked')}
              >
                Kilitliler ({summary.total - summary.unlockedCount})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'bronze' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('bronze')}
              >
                Bronz ({summary.bronze.total})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'silver' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('silver')}
              >
                Gümüş ({summary.silver.total})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'gold' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('gold')}
              >
                Altın ({summary.gold.total})
              </button>
              <button
                type="button"
                className={`chip ${tierFilter === 'platinum' ? 'chip--on' : ''}`}
                onClick={() => setTierFilter('platinum')}
              >
                Platin ({summary.platinum.total})
              </button>
            </div>

            <div className="ach-search-group">
              <input
                type="search"
                className="ach-search-input"
                placeholder="Kupa veya açıklama ara…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* KUPA KARTLARI LİSTESİ */}
          <div className="trophy-grid">
            {filteredAchievements.map((ach) => (
              <article
                key={ach.id}
                className={`trophy-card ${
                  ach.unlocked ? 'trophy-card--unlocked' : 'trophy-card--locked'
                }`}
              >
                <div className="trophy-card-icon-col">
                  <TrophyIcon
                    tier={ach.tier}
                    size={40}
                    unlocked={ach.unlocked}
                  />
                  <span
                    className={`trophy-card-tier-pill trophy-card-tier-pill--${ach.tier}`}
                  >
                    {TIER_NAMES[ach.tier]}
                  </span>
                </div>

                <div className="trophy-card-main-col">
                  <div className="trophy-card-top-line">
                    <span className="trophy-card-category">{ach.categoryTitle}</span>
                    {ach.unlocked ? (
                      <span className="pill pill--ok">Kazanıldı</span>
                    ) : (
                      <span className="pill pill--idle">Kilitli</span>
                    )}
                  </div>

                  <h3 className="trophy-card-title">{ach.title}</h3>
                  <p className="trophy-card-desc">{ach.description}</p>

                  {/* İlerleme Çubuğu */}
                  <div className="trophy-card-progress-area">
                    <div className="trophy-card-progress-labels">
                      <span className="trophy-card-progress-hint">
                        {ach.hint || 'Hedefe ulaşın'}
                      </span>
                      <span className="trophy-card-progress-pct">
                        %{ach.progressPercent}
                      </span>
                    </div>
                    <div className="trophy-card-progress-track">
                      <div
                        className="trophy-card-progress-fill"
                        style={{ width: `${ach.progressPercent}%` }}
                      />
                    </div>
                  </div>

                  {/* Kart alt bilgisi */}
                  <div className="trophy-card-footer">
                    <span className="trophy-card-metrics-val">
                      Şu an: <strong>{ach.currentValue.toLocaleString('tr-TR')}</strong> /{' '}
                      {ach.targetValue.toLocaleString('tr-TR')} {ach.unit}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {filteredAchievements.length === 0 && (
            <div className="ach-no-results">
              <p>Arama veya filtre kriterlerine uyan bir kupa bulunamadı.</p>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setTierFilter('all')
                  setCategoryFilter('all')
                  setSearchQuery('')
                }}
              >
                Filtreleri temizle
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
