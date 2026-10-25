import type { ReactNode } from 'react'

/** Krem afiş levhası üzerinde yönlendirici boş durum. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="state-box">
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  )
}

/** Hata durumu: sorunu ve çıkışı söyler, yeniden dene sunar. */
export function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string
  onRetry: () => void
}) {
  return (
    <div className="state-box error" role="alert">
      <h3>{title}</h3>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        Yeniden dene
      </button>
    </div>
  )
}

/** Mürekkep sıyırma & modern iskelet: yükleme durumu. */
export function LoadingState({
  label,
  skeleton = false,
}: {
  label: string
  skeleton?: boolean
}) {
  return (
    <div className="ink-loading" role="status" aria-live="polite">
      <div className="ink-loading-head">
        <span className="ink-spinner" aria-hidden="true" />
        <span className="ink-loading-text">{label}</span>
      </div>
      {skeleton && (
        <div className="skeleton-rows" aria-hidden="true">
          <div className="skeleton-bar" style={{ width: '85%' }} />
          <div className="skeleton-bar" style={{ width: '65%' }} />
          <div className="skeleton-bar" style={{ width: '45%' }} />
        </div>
      )}
    </div>
  )
}

/** Bağlantı kopunca son verilerle kalındığını bildiren not. */
export function StaleNote({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="stale-note" role="status">
      <span>
        Bağlantı koptu — son ölçülen değerler gösteriliyor.
      </span>
      <button type="button" onClick={onRetry}>
        Yeniden dene
      </button>
    </div>
  )
}
