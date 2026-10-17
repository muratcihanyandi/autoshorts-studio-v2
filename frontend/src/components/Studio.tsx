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
