export type TrophyTier = 'bronze' | 'silver' | 'gold' | 'platinum'

export type AchievementCategory =
  | 'first_steps'
  | 'views'
  | 'community'
  | 'engagement'
  | 'shorts'
  | 'monetization'

export interface ChannelMetrics {
  totalVideos: number
  totalViews: number
  subscriberCount: number
  totalLikes: number
  totalComments: number
  shortsCount: number
  shortsViews: number
  horizontalCount: number
  horizontalViews: number
  watchHours: number
  maxDailyViews: number
  engagementRate: number // Yüzde (örn: 8.5)
}

export interface AchievementDefinition {
  id: string
  title: string
  description: string
  tier: TrophyTier
  category: AchievementCategory
  categoryTitle: string
  targetValue: number
  unit: string
  isSecret?: boolean
  evaluate: (metrics: ChannelMetrics) => {
    unlocked: boolean
    currentValue: number
    progressPercent: number
    hint?: string
  }
}

export interface ComputedAchievement {
  id: string
  title: string
  description: string
  tier: TrophyTier
  category: AchievementCategory
  categoryTitle: string
  targetValue: number
  currentValue: number
  progressPercent: number
  unit: string
  unlocked: boolean
  unlockedAt: string | null
  isSecret?: boolean
  hint?: string
}

export interface TrophySummary {
  total: number
  unlockedCount: number
  completionPercentage: number
  level: number
  bronze: { total: number; unlocked: number }
  silver: { total: number; unlocked: number }
  gold: { total: number; unlocked: number }
  platinum: { total: number; unlocked: number }
  isMonetized: boolean
}
