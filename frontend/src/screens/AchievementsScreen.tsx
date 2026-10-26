import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import '../styles/achievements.css'
import { fetchChannels, type Channel } from '../api/channels'
import {
  fetchChannelVideos,
  type YoutubeVideosResponse,
} from '../api/youtube'
import { fetchMe, type UserProfile } from '../api/auth'
import { computeAchievements } from '../achievements/achievementsList'
import { TrophyIcon } from '../components/TrophyIcons'
import { TrophyNotification } from '../components/TrophyNotification'
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
  const [channels, setChannels] = useState<Channel[]>([])
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null)
  const [loadingChannels, setLoadingChannels] = useState(true)

  const [videoData, setVideoData] = useState<YoutubeVideosResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Filtreler
  const [tierFilter, setTierFilter] = useState<FilterTier>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Ses ayarları
  const [soundEnabled, setSoundEnabled] = useState(true)

  // Kupa pop-up bildirimi (otomatik tek seferlik duyulur)
  const [activeToast, setActiveToast] = useState<ComputedAchievement | null>(null)

  // Kullanıcı ve Kanalları yükle (Hesap İzolasyonu)
  useEffect(() => {
    let cancelled = false
    setLoadingChannels(true)

    void fetchMe()
      .then((user) => {
        if (!cancelled) setCurrentUser(user)
      })
      .catch(() => {})

    fetchChannels()
      .then((res) => {
        if (cancelled) return
        const list = res.channels ?? []
        setChannels(list)
        if (list.length > 0 && selectedChannelId === null) {
          setSelectedChannelId(list[0].id)
        }
      })
      .catch((err) => {
        if (!cancelled) setErrorMsg(err instanceof Error ? err.message : 'Kanallar alınamadı.')
      })
      .finally(() => {
        if (!cancelled) setLoadingChannels(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedChannelId])

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
    if (selectedChannelId !== null) {
      void loadChannelData(selectedChannelId)
    }
  }, [selectedChannelId, loadChannelData])

  // Seçili kanala ait metrikler ve başarımları bağımsız hesapla
  const metrics = useMemo(() => deriveMetrics(videoData), [videoData])

  // Hem HESABA hem KANALA özel LocalStorage anahtarı:
  // Bir kanalın açılan kupaları diğer kanalın kupa ağacına kesinlikle karışmaz!
  const storageKey = useMemo(() => {
    const uid = currentUser?.id ?? 'me'
    const chId = selectedChannelId ?? 'none'
    return `autoshorts_seen_trophies_u_${uid}_ch_${chId}`
  }, [currentUser?.id, selectedChannelId])

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

  const selectedChannel = channels.find((c) => c.id === selectedChannelId)

  return (
    <div className="achievements-page">
      {/* PlayStation Kupa Pop-up Bildirimi (Otomatik Tek Seferlik Duyulur) */}
      <TrophyNotification
        achievement={activeToast}
        onDismiss={() => setActiveToast(null)}
        soundEnabled={soundEnabled}
      />

      {/* Sayfa Üst Başlığı ve Hesap Bilgisi */}
      <header className="achievements-header">
        <div className="achievements-header-main">
          <div className="achievements-title-wrap">
            <h1 className="achievements-h1">
              <span className="achievements-h1-icon" aria-hidden="true">
                🏆
              </span>
              Başarımlar
            </h1>
          </div>

          <div className="achievements-controls">
            {/* Hesap Rozeti */}
            {currentUser && (
              <div className="ach-user-badge" title="Aktif Hesap">
                <span>👤 {currentUser.username}</span>
                <span className="ach-user-plan-pill">{currentUser.plan}</span>
              </div>
            )}

            {/* Ses Aç / Kapa Butonu */}
            <button
              type="button"
              className={`ach-sound-toggle ${soundEnabled ? 'ach-sound-toggle--on' : ''}`}
              onClick={() => setSoundEnabled((v) => !v)}
              title={soundEnabled ? 'Sesler açık' : 'Sesler kapalı'}
              aria-label="Sesleri aç veya kapat"
            >
              {soundEnabled ? '🔊 Ses Açık' : '🔇 Ses Kapalı'}
            </button>
          </div>
        </div>

        {/* HER KANALA ÖZEL BAŞARIM AĞACI SEKME ÇUBUĞU */}
        {channels.length > 0 && (
          <div className="ach-channel-tree-section">
            <span className="ach-channel-tree-tabs-label">Kanal:</span>
            <div className="ach-channel-tree-tabs" role="tablist" aria-label="Kanallar">
              {channels.map((c) => {
                const isSelected = c.id === selectedChannelId
                return (
                  <button
                    key={c.id}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    className={`ach-channel-tree-tab ${isSelected ? 'ach-channel-tree-tab--active' : ''}`}
                    onClick={() => setSelectedChannelId(c.id)}
                  >
                    <span
                      className="ach-channel-ribbon"
                      style={{ backgroundColor: c.ribbon_color || '#3b82f6' }}
                    />
                    <div className="ach-channel-tab-text">
                      <span className="ach-channel-tab-name">{c.name}</span>
                      {c.handle && (
                        <small className="ach-channel-tab-handle">{c.handle}</small>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </header>

      {/* Yükleniyor veya Boş Durum */}
      {loadingChannels ? (
        <LoadingState label="Kanallar yükleniyor…" />
      ) : channels.length === 0 ? (
        <EmptyState
          title="Bağlı kanal bulunamadı"
          action={<Link to="/kanallar" className="btn btn--primary">Kanallara Git</Link>}
        >
          Başarımları görüntülemek için bir kanal bağlayın.
        </EmptyState>
      ) : (
        <>
          {errorMsg && (
            <div className="ach-error-banner" role="alert">
              <span>⚠️ {errorMsg}</span>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => selectedChannelId && void loadChannelData(selectedChannelId)}
              >
                Tekrar Dene
              </button>
            </div>
          )}

          {/* AKTİF KANAL BİLGİ ŞERİDİ */}
          {selectedChannel && (
            <div className="ach-active-channel-banner">
              <div className="ach-active-channel-info">
                <span
                  className="ach-active-channel-ribbon-dot"
                  style={{ backgroundColor: selectedChannel.ribbon_color || '#3b82f6' }}
                />
                <h2 className="ach-active-channel-name">{selectedChannel.name}</h2>
                {selectedChannel.handle && (
                  <span className="ach-active-channel-handle">{selectedChannel.handle}</span>
                )}
              </div>
              <div className="ach-active-channel-badge">
                {summary.isMonetized ? '🏆 Para Kazanma Açık' : '⏳ Hedefe Doğru'}
              </div>
            </div>
          )}

          {/* KUPA ÖZETİ PANOSU */}
          <section
            className="ps-trophy-shelf"
            aria-label={`${selectedChannel?.name ?? 'Kanal'} Kupa İstatistiği`}
          >
            <div className="ps-level-badge">
              <div className="ps-level-icon" aria-hidden="true">
                ⭐
              </div>
              <div className="ps-level-content">
                <span className="ps-level-tag">SEVİYE</span>
                <span className="ps-level-num">{summary.level}</span>
              </div>
            </div>

            <div className="ps-progress-box">
              <div className="ps-progress-labels">
                <span className="ps-progress-title">Genel İlerleme</span>
                <span className="ps-progress-percent">
                  %{summary.completionPercentage} ({summary.unlockedCount}/{summary.total})
                </span>
              </div>
              <div className="ps-progress-bar-wrap">
                <div
                  className="ps-progress-bar-fill"
                  style={{ width: `${summary.completionPercentage}%` }}
                />
              </div>
            </div>

            <div className="ps-trophy-counters">
              <div className="ps-counter ps-counter--bronze" title="Bronz Kupalar">
                <TrophyIcon tier="bronze" size={24} unlocked={true} />
                <div className="ps-counter-info">
                  <span className="ps-counter-val">
                    {summary.bronze.unlocked}/{summary.bronze.total}
                  </span>
                  <span className="ps-counter-name">Bronz</span>
                </div>
              </div>

              <div className="ps-counter ps-counter--silver" title="Gümüş Kupalar">
                <TrophyIcon tier="silver" size={24} unlocked={true} />
                <div className="ps-counter-info">
                  <span className="ps-counter-val">
                    {summary.silver.unlocked}/{summary.silver.total}
                  </span>
                  <span className="ps-counter-name">Gümüş</span>
                </div>
              </div>

              <div className="ps-counter ps-counter--gold" title="Altın Kupalar">
                <TrophyIcon tier="gold" size={24} unlocked={true} />
                <div className="ps-counter-info">
                  <span className="ps-counter-val">
                    {summary.gold.unlocked}/{summary.gold.total}
                  </span>
                  <span className="ps-counter-name">Altın</span>
                </div>
              </div>

              <div
                className={`ps-counter ps-counter--platinum ${
                  summary.isMonetized ? 'ps-counter--plat-unlocked' : ''
                }`}
                title="Platin Kupa"
              >
                <TrophyIcon
                  tier="platinum"
                  size={26}
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
          </section>

          {/* PARA KAZANMA TAKİBİ */}
          <section className="monetization-showcase">
            <div className="monetization-showcase-header">
              <div className="monetization-showcase-title">
                <h2>Para Kazanma (YPP)</h2>
              </div>
              <div
                className={`monetization-status-pill ${
                  summary.isMonetized
                    ? 'monetization-status-pill--active'
                    : 'monetization-status-pill--progress'
                }`}
              >
                {summary.isMonetized ? '✓ Açık' : '⏳ Hedefe Doğru'}
              </div>
            </div>

            <div className="monetization-tracks">
              {/* Kriter 1: Abone Eşiği */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">1.000 Abone</span>
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
                <small className="monetization-track-note">
                  {metrics.subscriberCount >= 1000
                    ? '✓ Tamamlandı'
                    : `Kalan: ${Math.max(0, 1000 - metrics.subscriberCount).toLocaleString('tr-TR')}`}
                </small>
              </div>

              {/* Kriter 2A: 4000 Saat Yatay İzlenme */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">4.000 Saat (Yatay)</span>
                  <span className="monetization-track-val">
                    {metrics.watchHours.toLocaleString('tr-TR')} / 4.000 Saat
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
                <small className="monetization-track-note">
                  {metrics.watchHours >= 4000
                    ? '✓ Tamamlandı'
                    : `Kalan: ${Math.max(0, 4000 - metrics.watchHours).toLocaleString('tr-TR')} saat`}
                </small>
              </div>

              {/* Kriter 2B: 10 Milyon Shorts İzlenmesi */}
              <div className="monetization-track-card">
                <div className="monetization-track-top">
                  <span className="monetization-track-name">10 Milyon Shorts</span>
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
                <small className="monetization-track-note">
                  {metrics.shortsViews >= 10000000
                    ? '✓ Tamamlandı'
                    : `Kalan: ${Math.max(0, 10000000 - metrics.shortsViews).toLocaleString(
                        'tr-TR',
                      )}`}
                </small>
              </div>
            </div>
          </section>

          {/* FİLTRE & ARAMA ÇUBUĞU */}
          <div className="achievements-filter-bar">
            <div className="ach-filter-group">
              <button
                type="button"
                className={`ach-filter-chip ${tierFilter === 'all' ? 'ach-filter-chip--active' : ''}`}
                onClick={() => setTierFilter('all')}
              >
                Tümü ({achievements.length})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ${tierFilter === 'unlocked' ? 'ach-filter-chip--active' : ''}`}
                onClick={() => setTierFilter('unlocked')}
              >
                Açılanlar ({summary.unlockedCount})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ${tierFilter === 'locked' ? 'ach-filter-chip--active' : ''}`}
                onClick={() => setTierFilter('locked')}
              >
                Kilitliler ({summary.total - summary.unlockedCount})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ach-filter-chip--bronze ${
                  tierFilter === 'bronze' ? 'ach-filter-chip--active' : ''
                }`}
                onClick={() => setTierFilter('bronze')}
              >
                🥉 Bronz ({summary.bronze.total})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ach-filter-chip--silver ${
                  tierFilter === 'silver' ? 'ach-filter-chip--active' : ''
                }`}
                onClick={() => setTierFilter('silver')}
              >
                🥈 Gümüş ({summary.silver.total})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ach-filter-chip--gold ${
                  tierFilter === 'gold' ? 'ach-filter-chip--active' : ''
                }`}
                onClick={() => setTierFilter('gold')}
              >
                🥇 Altın ({summary.gold.total})
              </button>
              <button
                type="button"
                className={`ach-filter-chip ach-filter-chip--platinum ${
                  tierFilter === 'platinum' ? 'ach-filter-chip--active' : ''
                }`}
                onClick={() => setTierFilter('platinum')}
              >
                🏆 Platin ({summary.platinum.total})
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
              <div
                key={ach.id}
                className={`trophy-card trophy-card--${ach.tier} ${
                  ach.unlocked ? 'trophy-card--unlocked' : 'trophy-card--locked'
                }`}
              >
                <div className="trophy-card-icon-col">
                  <div className="trophy-card-icon-wrap">
                    <TrophyIcon
                      tier={ach.tier}
                      size={48}
                      unlocked={ach.unlocked}
                    />
                    {ach.tier === 'platinum' && ach.unlocked && (
                      <span className="trophy-plat-glow-ring" aria-hidden="true" />
                    )}
                  </div>
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
                      <span className="trophy-card-status-badge trophy-card-status-badge--unlocked">
                        ✓ KAZANILDI
                      </span>
                    ) : (
                      <span className="trophy-card-status-badge trophy-card-status-badge--locked">
                        🔒 KİLİTLİ
                      </span>
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
                        className={`trophy-card-progress-fill trophy-card-progress-fill--${ach.tier}`}
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
              </div>
            ))}
          </div>

          {filteredAchievements.length === 0 && (
            <div className="ach-no-results">
              <p>Arama veya filtre kriterlerine uyan bir kupa bulunamadı.</p>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => {
                  setTierFilter('all')
                  setCategoryFilter('all')
                  setSearchQuery('')
                }}
              >
                Filtreleri Temizle
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
