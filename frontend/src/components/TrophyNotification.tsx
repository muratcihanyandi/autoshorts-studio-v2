import { useEffect } from 'react'
import { TrophyIcon } from './TrophyIcons'
import { playTrophySound } from '../audio/trophySound'
import type { ComputedAchievement } from '../types/achievements'

interface TrophyNotificationProps {
  achievement: ComputedAchievement | null
  onDismiss: () => void
  soundEnabled?: boolean
}

const TIER_LABELS: Record<string, string> = {
  bronze: 'Bronz Kupa',
  silver: 'Gümüş Kupa',
  gold: 'Altın Kupa',
  platinum: 'Platin Kupa',
}

export function TrophyNotification({
  achievement,
  onDismiss,
  soundEnabled = true,
}: TrophyNotificationProps) {
  useEffect(() => {
    if (!achievement) return

    if (soundEnabled) {
      playTrophySound(achievement.tier)
    }

    const timer = setTimeout(() => {
      onDismiss()
    }, 5500)

    return () => clearTimeout(timer)
  }, [achievement, onDismiss, soundEnabled])

  if (!achievement) return null

  const tierLabel = TIER_LABELS[achievement.tier] ?? 'Kupa'

  return (
    <div
      className={`trophy-toast trophy-toast--${achievement.tier}`}
      role="status"
      aria-live="polite"
    >
      <div className="trophy-toast-icon-wrap">
        <TrophyIcon tier={achievement.tier} size={36} unlocked={true} />
        {achievement.tier === 'platinum' && (
          <span className="trophy-toast-plat-halo" aria-hidden="true" />
        )}
      </div>

      <div className="trophy-toast-content">
        <div className="trophy-toast-header">
          <span className="trophy-toast-tag">KUPA KAZANILDI!</span>
          <span className={`trophy-toast-tier-pill trophy-toast-tier-pill--${achievement.tier}`}>
            {tierLabel}
          </span>
        </div>
        <div className="trophy-toast-title">{achievement.title}</div>
        <div className="trophy-toast-desc">{achievement.description}</div>
      </div>

      <button
        type="button"
        className="trophy-toast-close"
        onClick={onDismiss}
        aria-label="Bildirimi kapat"
        title="Kapat"
      >
        ✕
      </button>
    </div>
  )
}
