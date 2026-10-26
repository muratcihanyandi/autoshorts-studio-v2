import type { TrophyTier } from '../types/achievements'

interface TrophyIconProps {
  tier: TrophyTier
  size?: number
  unlocked?: boolean
  className?: string
}

/** Kupa ikonu: tek renk çizgi dili (currentColor). Derece rengini
    CSS sınıfı (trophy-icon--bronze…) taşır; kilitli form kasa gösterir. */
export function TrophyIcon({
  tier,
  size = 32,
  unlocked = true,
  className = '',
}: TrophyIconProps) {
  if (!unlocked) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={`trophy-icon trophy-icon--locked ${className}`}
        aria-hidden="true"
      >
        <path
          d="M16 18V14C16 9.58 19.58 6 24 6C28.42 6 32 9.58 32 14V18M12 18H36C38.2 18 40 19.8 40 22V38C40 40.2 38.2 42 36 42H12C9.8 42 8 40.2 8 38V22C8 19.8 9.8 18 12 18Z"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="24" cy="29" r="3" fill="currentColor" />
        <path d="M24 32V36" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
    )
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`trophy-icon trophy-icon--${tier} ${className}`}
      aria-hidden="true"
    >
      {/* Kupa gövdesi */}
      <path
        d="M14 6H34V20C34 26 29.5 30 24 30C18.5 30 14 26 14 20V6Z"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      {/* Kulplar */}
      <path
        d="M14 10H8C6.34 10 5 11.34 5 13V16C5 19.87 8.13 23 12 23H14.2"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M34 10H40C41.66 10 43 11.34 43 13V16C43 19.87 39.87 23 36 23H33.8"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Kupa sapı ve tabanı */}
      <path
        d="M21 30H27V36C27 37 28 38 29 38H19C20 38 21 37 21 36V30Z"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M13 42H35"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      {/* Yıldız amblemi */}
      <path
        d="M24 12L25.3 15.5L29 16L26.2 18.5L27 22L24 20.2L21 22L21.8 18.5L19 16L22.7 15.5L24 12Z"
        fill="currentColor"
        opacity="0.9"
      />
    </svg>
  )
}
