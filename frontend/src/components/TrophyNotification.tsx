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
  bronze: 'Bronz kupa',
  silver: 'Gümüş kupa',
  gold: 'Altın kupa',
  platinum: 'Platin kupa',
}

/** Kupa bildirimi: stüdyo toast dili (beyaz kart, yumuşak zeminli
    ikon çipi, 240ms giriş) — dereceye göre tonlanır. */
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
      <span className="trophy-toast-icon-wrap">
        <TrophyIcon tier={achievement.tier} size={16} unlocked={true} />
      </span>

      <div className="trophy-toast-content">
        <div className="trophy-toast-title">
          {tierLabel} kazanıldı — {achievement.title}
        </div>
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
