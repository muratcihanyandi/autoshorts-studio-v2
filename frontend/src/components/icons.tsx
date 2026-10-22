import type { ReactNode } from 'react'

/* El çizimi marka ikonları: 24px ızgara, 1.8px vuruş, tek renk
   (currentColor). Harici ikon paketi yok — Pi çevrimdışı çalışır.
   İkonlar süslüdür (aria-hidden); erişilebilir ad metinden gelir. */
function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export function MenuIcon() {
  return (
    <Svg>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
  )
}

export function CloseIcon() {
  return (
    <Svg>
      <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
    </Svg>
  )
}

export function GridIcon() {
  return (
    <Svg>
      <rect x="4" y="4" width="7" height="7" rx="1.6" />
      <rect x="13" y="4" width="7" height="7" rx="1.6" />
      <rect x="4" y="13" width="7" height="7" rx="1.6" />
      <rect x="13" y="13" width="7" height="7" rx="1.6" />
    </Svg>
  )
}

export function PlayIcon() {
  return (
    <Svg>
      <rect x="3" y="5" width="18" height="14" rx="2.4" />
      <path d="M10.5 9.6v4.8l4-2.4z" fill="currentColor" stroke="none" />
    </Svg>
  )
}

export function FilmIcon() {
  return (
    <Svg>
      <rect x="3" y="4.5" width="18" height="15" rx="2.2" />
      <path d="M7.5 4.5v15M16.5 4.5v15M7.5 12h9" />
    </Svg>
  )
}

export function CalendarIcon() {
  return (
    <Svg>
      <rect x="4" y="5.5" width="16" height="14.5" rx="2.2" />
      <path d="M8 3.5v3.4M16 3.5v3.4M4.5 10.5h15" />
    </Svg>
  )
}

export function BoltIcon() {
  return (
    <Svg>
      <path d="M13 3 5.5 13.5h4.5L10.5 21 18 10.5h-4.5z" />
    </Svg>
  )
}
