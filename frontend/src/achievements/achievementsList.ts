import type {
  AchievementDefinition,
  ChannelMetrics,
  ComputedAchievement,
  TrophySummary,
} from '../types/achievements'

export const ACHIEVEMENTS: AchievementDefinition[] = [
  // ==========================================
  // BRONZ KUPALAR (İlk Kıvılcımlar)
  // ==========================================
  {
    id: 'first_stage',
    title: 'İlk Sahne',
    description:
      'Büyük bir imparatorluk tek bir video ile başlar. YouTube sahnesine ilk adımını attın!',
    tier: 'bronze',
    category: 'first_steps',
    categoryTitle: 'İlk Adımlar',
    targetValue: 1,
    unit: 'video',
    evaluate: (m) => {
      const current = m.totalVideos
      const unlocked = current >= 1
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 1) * 100),
        hint: unlocked ? 'İlk video yayında!' : 'YouTube kanalına ilk videonu yükle.',
      }
    },
  },
  {
    id: 'audience_gathering',
    title: 'Seyirci Toplanıyor',
    description:
      'Artık boş bir salona konuşmuyorsun. İlk 1.000 izleyicin seni keşfetti.',
    tier: 'bronze',
    category: 'views',
    categoryTitle: 'İzlenmeler',
    targetValue: 1000,
    unit: 'izlenme',
    evaluate: (m) => {
      const current = m.totalViews
      const unlocked = current >= 1000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 1000) * 100),
        hint: unlocked ? '1.000 izleyiciye ulaşıldı!' : '1.000 toplam izlenmeye ulaş.',
      }
    },
  },
  {
    id: 'loyal_followers',
    title: 'Sadık Takipçiler',
    description:
      'Seni sürekli takip etmek isteyen ilk 50 kişi bildirim zilini açtı.',
    tier: 'bronze',
    category: 'community',
    categoryTitle: 'Topluluk',
    targetValue: 50,
    unit: 'abone',
    evaluate: (m) => {
      const current = m.subscriberCount
      const unlocked = current >= 50
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 50) * 100),
        hint: unlocked ? '50 sadık takipçi seninle!' : '50 aboneye ulaş.',
      }
    },
  },
  {
    id: 'keyboard_warriors',
    title: 'Klavye Başındakiler',
    description:
      'Sohbet başladı! İzleyicilerin ilk yorumlarını ve fikirlerini bıraktı.',
    tier: 'bronze',
    category: 'engagement',
    categoryTitle: 'Etkileşim',
    targetValue: 25,
    unit: 'yorum',
    evaluate: (m) => {
      const current = m.totalComments
      const unlocked = current >= 25
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 25) * 100),
        hint: unlocked ? 'Yorumlar akmaya başladı!' : 'Videolarında 25 yoruma ulaş.',
      }
    },
  },
  {
    id: 'first_like_wave',
    title: 'İlk Beğeni Dalgası',
    description:
      'İçeriklerin beğenilmeye başladı. İlk 100 beğeni kasada.',
    tier: 'bronze',
    category: 'engagement',
    categoryTitle: 'Etkileşim',
    targetValue: 100,
    unit: 'beğeni',
    evaluate: (m) => {
      const current = m.totalLikes
      const unlocked = current >= 100
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 100) * 100),
        hint: unlocked ? '100 beğeni barajı aşıldı!' : 'Videolarında 100 beğeni topla.',
      }
    },
  },
  {
    id: 'vertical_strip',
    title: 'Dikey Şerit',
    description:
      'Algoritmanın hızlı şeridine girdin. Shorts akışı seni sevmeye başladı.',
    tier: 'bronze',
    category: 'shorts',
    categoryTitle: 'Shorts',
    targetValue: 10000,
    unit: 'Shorts izlenmesi',
    evaluate: (m) => {
      const current = m.shortsViews
      const unlocked = m.shortsCount >= 10 && current >= 10000
      const progress = Math.min(100, (current / 10000) * 100)
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : progress,
        hint: unlocked
          ? 'Shorts akışında sağlam bir yer edindin!'
          : `10 Shorts videosu ve 10.000 izlenme (Şu an: ${m.shortsCount}/10 video, ${current}/10.000 izlenme).`,
      }
    },
  },

  // ==========================================
  // GÜMÜŞ KUPALAR (İvme ve Etkileşim Derinliği)
  // ==========================================
  {
    id: 'viral_spark',
    title: 'Viral Kıvılcım',
    description:
      'Algoritma seni önerilenlere fırlattı! 24 saat içinde 5.000 kişi videolarına akın etti.',
    tier: 'silver',
    category: 'views',
    categoryTitle: '1 Günde İzlenme',
    targetValue: 5000,
    unit: 'günlük izlenme',
    evaluate: (m) => {
      const current = m.maxDailyViews
      const unlocked = current >= 5000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 5000) * 100),
        hint: unlocked ? '1 günde 5.000 izlenme barajı yıkıldı!' : 'Tek bir günde 5.000 izlenmeye ulaş.',
      }
    },
  },
  {
    id: 'silver_threshold',
    title: 'Gümüş Eşik',
    description:
      'Kanal yarı binliğe ulaştı! YouTube Süper Teşekkür ve Katıl (Fan Funding) kapısı aralandı.',
    tier: 'silver',
    category: 'community',
    categoryTitle: 'Erken Para Kazanma',
    targetValue: 500,
    unit: 'abone',
    evaluate: (m) => {
      const current = m.subscriberCount
      const unlocked = current >= 500
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 500) * 100),
        hint: unlocked ? '500 aboneyle erken para kazanma eşiğindesin!' : '500 aboneye ulaş.',
      }
    },
  },
  {
    id: 'engagement_beast',
    title: 'Etkileşim Canavarı',
    description:
      'Sadece izleyip geçmiyorlar; izleyicilerin kanalınla güçlü bir bağ kuruyor!',
    tier: 'silver',
    category: 'engagement',
    categoryTitle: 'Etkileşim Oranı',
    targetValue: 8.0,
    unit: '%',
    evaluate: (m) => {
      const current = m.engagementRate
      const unlocked = current >= 8.0 && m.totalViews >= 500
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 8.0) * 100),
        hint: unlocked
          ? '%8+ etkileşim oranıyla kitle sadakati tavan yaptı!'
          : '%8 ve üzeri etkileşim oranına (Beğeni+Yorum / İzlenme) ulaş.',
      }
    },
  },
  {
    id: 'discussion_club',
    title: 'Tartışma Kulübü',
    description:
      'Yorumlar bölümü bir foruma dönüştü. Topluluğun nabzı burada atıyor.',
    tier: 'silver',
    category: 'engagement',
    categoryTitle: 'Yorum Sayısı',
    targetValue: 250,
    unit: 'yorum',
    evaluate: (m) => {
      const current = m.totalComments
      const unlocked = current >= 250
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 250) * 100),
        hint: unlocked ? '250 yorumla topluluk harareti zirvede!' : 'Videolarında 250 yoruma ulaş.',
      }
    },
  },
  {
    id: 'screen_locked',
    title: 'Gözleri Ekrana Kilitledin',
    description:
      'Kanalın dev bir kitleye ulaşıyor. 50.000 izlenme barajı aşıldı.',
    tier: 'silver',
    category: 'views',
    categoryTitle: 'İzlenme Hacmi',
    targetValue: 50000,
    unit: 'izlenme',
    evaluate: (m) => {
      const current = m.totalViews
      const unlocked = current >= 50000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 50000) * 100),
        hint: unlocked ? '50.000 izlenme tamamlandı!' : 'Toplam 50.000 izlenmeye ulaş.',
      }
    },
  },

  // ==========================================
  // ALTIN KUPALAR (Büyük Kilometre Taşları)
  // ==========================================
  {
    id: 'agenda_setter',
    title: 'Gündem Sensin!',
    description:
      'Trendler sarsılıyor! Tek bir günde koca bir stadyumu dolduracak kadar izlendin.',
    tier: 'gold',
    category: 'views',
    categoryTitle: '1 Günde Patlama',
    targetValue: 25000,
    unit: 'günlük izlenme',
    evaluate: (m) => {
      const current = m.maxDailyViews
      const unlocked = current >= 25000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 25000) * 100),
        hint: unlocked ? '24 saatte 25.000 izlenme ile trend patlaması!' : 'Tek bir günde 25.000 izlenmeye ulaş.',
      }
    },
  },
  {
    id: 'thousands_club',
    title: 'Binler Kulübü',
    description:
      'Dört haneli kulübe hoş geldin! Partner programının en kritik kalesi fethedildi.',
    tier: 'gold',
    category: 'community',
    categoryTitle: 'Partner Eşiği',
    targetValue: 1000,
    unit: 'abone',
    evaluate: (m) => {
      const current = m.subscriberCount
      const unlocked = current >= 1000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 1000) * 100),
        hint: unlocked ? '1.000 abone barajı aşıldı, partner kapısı açık!' : '1.000 aboneye ulaş.',
      }
    },
  },
  {
    id: 'shorts_phenom',
    title: 'Shorts Fenomeni',
    description:
      'Milyonlar seni kaydırıp duruyor. Shorts kütüphanen devasa bir izleyici havuzuna ulaştı.',
    tier: 'gold',
    category: 'shorts',
    categoryTitle: 'Shorts Hedefi',
    targetValue: 3000000,
    unit: 'Shorts izlenmesi',
    evaluate: (m) => {
      const current = m.shortsViews
      const unlocked = current >= 3000000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 3000000) * 100),
        hint: unlocked ? '3 Milyon Shorts görüntülemesi tamam!' : 'Shorts videolarında 3 Milyon izlenmeye ulaş.',
      }
    },
  },
  {
    id: 'marathon_runner',
    title: 'Maraton Koşucusu',
    description:
      'İzleyicilerin seninle binlerce saat geçirdi. Partnerlik için son dönemeçtesin.',
    tier: 'gold',
    category: 'views',
    categoryTitle: 'İzlenme Süresi',
    targetValue: 3000,
    unit: 'saat',
    evaluate: (m) => {
      const current = m.watchHours
      const unlocked = current >= 3000
      return {
        unlocked,
        currentValue: current,
        progressPercent: unlocked ? 100 : Math.min(100, (current / 3000) * 100),
        hint: unlocked ? '3.000 saat izlenme süresi geride kaldı!' : '3.000 geçerli izlenme saatine ulaş.',
      }
    },
  },

  // ==========================================
  // PLATİN KUPA (Nihai Hedef - Büyük Usta)
  // ==========================================
  {
    id: 'youtube_partner',
    title: 'YouTube Partneri',
    description:
      'Tebrikler Usta! YouTube stüdyondan artık gerçek gelir elde ediyorsun. Para kazanma resmen açıldı ve Platin Kupayı kaldırdın!',
    tier: 'platinum',
    category: 'monetization',
    categoryTitle: 'Para Kazanma Açıldı!',
    targetValue: 1,
    unit: 'YPP Onayı',
    evaluate: (m) => {
      // 1.000 Abone + (4.000 İzlenme Saati VEYA 10 Milyon Shorts İzlenmesi)
      const subGoal = m.subscriberCount >= 1000
      const watchGoal = m.watchHours >= 4000
      const shortsGoal = m.shortsViews >= 10000000
      const conditionMet = subGoal && (watchGoal || shortsGoal)

      // İlerleme hesaplama: Abone (%50) + (Saat veya Shorts'tan yüksek olanı %50)
      const subProg = Math.min(1, m.subscriberCount / 1000) * 50
      const watchProg = Math.min(1, m.watchHours / 4000) * 50
      const shortsProg = Math.min(1, m.shortsViews / 10000000) * 50
      const secondHalfProg = Math.max(watchProg, shortsProg)
      const totalProg = Math.min(100, Math.round(subProg + secondHalfProg))

      return {
        unlocked: conditionMet,
        currentValue: conditionMet ? 1 : 0,
        progressPercent: conditionMet ? 100 : totalProg,
        hint: conditionMet
          ? 'Para kazanma şartları tamamlandı! Platin Kupa senin!'
          : `Gereken: 1.000 Abone (${m.subscriberCount}/1000) VE (4.000 Saat (${m.watchHours}/4000) veya 10M Shorts (${m.shortsViews.toLocaleString('tr-TR')}/10M)).`,
      }
    },
  },
]

/**
 * Kanal metriklerine göre tüm başarımları hesaplar ve PlayStation Trophy özeti çıkarır.
 */
export function computeAchievements(
  metrics: ChannelMetrics,
  unlockedDates: Record<string, string> = {},
): {
  achievements: ComputedAchievement[]
  summary: TrophySummary
} {
  const achievements: ComputedAchievement[] = ACHIEVEMENTS.map((def) => {
    const res = def.evaluate(metrics)
    return {
      id: def.id,
      title: def.title,
      description: def.description,
      tier: def.tier,
      category: def.category,
      categoryTitle: def.categoryTitle,
      targetValue: def.targetValue,
      currentValue: res.currentValue,
      progressPercent: res.progressPercent,
      unit: def.unit,
      unlocked: res.unlocked,
      unlockedAt: res.unlocked ? unlockedDates[def.id] ?? new Date().toISOString() : null,
      isSecret: def.isSecret,
      hint: res.hint,
    }
  })

  const bronzeTotal = achievements.filter((a) => a.tier === 'bronze')
  const silverTotal = achievements.filter((a) => a.tier === 'silver')
  const goldTotal = achievements.filter((a) => a.tier === 'gold')
  const platinumTotal = achievements.filter((a) => a.tier === 'platinum')

  const bronzeUnlocked = bronzeTotal.filter((a) => a.unlocked).length
  const silverUnlocked = silverTotal.filter((a) => a.unlocked).length
  const goldUnlocked = goldTotal.filter((a) => a.unlocked).length
  const platinumUnlocked = platinumTotal.filter((a) => a.unlocked).length

  const totalUnlocked =
    bronzeUnlocked + silverUnlocked + goldUnlocked + platinumUnlocked
  const totalCount = achievements.length
  const completionPercentage =
    totalCount > 0 ? Math.round((totalUnlocked / totalCount) * 100) : 0

  // PlayStation Trophy Seviyesi puan hesabı:
  // Bronze = 15 puan, Silver = 30 puan, Gold = 90 puan, Platinum = 300 puan
  const trophyPoints =
    bronzeUnlocked * 15 +
    silverUnlocked * 30 +
    goldUnlocked * 90 +
    platinumUnlocked * 300
  // Her 100 puan ~ 1 seviye (başlangıç seviye 1)
  const level = Math.max(1, Math.floor(trophyPoints / 60) + 1)

  const isMonetized = platinumUnlocked > 0

  return {
    achievements,
    summary: {
      total: totalCount,
      unlockedCount: totalUnlocked,
      completionPercentage,
      level,
      bronze: { total: bronzeTotal.length, unlocked: bronzeUnlocked },
      silver: { total: silverTotal.length, unlocked: silverUnlocked },
      gold: { total: goldTotal.length, unlocked: goldUnlocked },
      platinum: { total: platinumTotal.length, unlocked: platinumUnlocked },
      isMonetized,
    },
  }
}
