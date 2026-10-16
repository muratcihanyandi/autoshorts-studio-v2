import type { ReactNode } from 'react'

export type BillTone = 'plain' | 'amber' | 'green' | 'red'

/** Jenerik blok satırı: afiş jeneriği gibi sıkı büyük-harf satırı + değer. */
export function BillRow({
  label,
  value,
  tone = 'plain',
}: {
  label: string
  value: ReactNode
  tone?: BillTone
}) {
  return (
    <div className={`bill-row${tone === 'plain' ? '' : ` tone-${tone}`}`}>
      <span>{label}</span>
      <span className="nums">{value}</span>
    </div>
  )
}

/** Damga: otomasyonun imzası. varyant canlı / bekleme / kurulum. */
export function Stamp({
  text,
  variant,
}: {
  text: string
  variant: 'live' | 'wait' | 'setup'
}) {
  return (
    <span className={`stamp stamp--${variant} stamp-press`}>{text}</span>
  )
}

/** Mürekkep göstergesi: değer + tonlu dolgu. */
export function Gauge({
  label,
  value,
  tone = 'plain',
}: {
  label: string
  value: string
  tone?: 'plain' | 'warn' | 'ok'
}) {
  const percent = Number.parseInt(value.replace('%', ''), 10)
  return (
    <div className="gauge">
      <label className={tone === 'warn' ? 'warn' : undefined}>
        <span>{label}</span>
        <span className="nums">{value}</span>
      </label>
      <div
        className="gauge-track"
        role="meter"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <i
          className={`gauge-fill${tone === 'plain' ? '' : ` ${tone}`}`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
    </div>
  )
}
