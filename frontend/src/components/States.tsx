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

/** Mürekkep sıyırma: yükleme durumu. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div className="ink-loading" aria-live="polite">
      {label}
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
