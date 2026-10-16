import { useCallback, useEffect, useState } from 'react'

export type PollState<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T; stale: boolean }
  | { status: 'error'; message: string }

interface UsePolling {
  <T>(fetcher: () => Promise<T>, intervalMs?: number): {
    state: PollState<T>
    retry: () => void
  }
}

/**
 * Periyodik veri çekme: yükleme / tamam / hata durumları ve yeniden deneme.
 * Bağlantı koparken eldeki son veri korunur (stale) — izleme panosu
 * geçici bir hatada boş ekrana düşmez.
 */
export const usePolling: UsePolling = <T,>(
  fetcher: () => Promise<T>,
  intervalMs = 10000,
) => {
  const [state, setState] = useState<PollState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false

    const run = () => {
      fetcher().then(
        (data) => {
          if (!cancelled) setState({ status: 'ok', data, stale: false })
        },
        (err: unknown) => {
          if (cancelled) return
          const message =
            err instanceof Error ? err.message : 'Bilinmeyen hata'
          setState((prev) =>
            prev.status === 'ok'
              ? { status: 'ok', data: prev.data, stale: true }
              : { status: 'error', message },
          )
        },
      )
    }

    run()
    const id = window.setInterval(run, intervalMs)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [fetcher, intervalMs, attempt])

  const retry = useCallback(() => {
    setState({ status: 'loading' })
    setAttempt((a) => a + 1)
  }, [])

  return { state, retry }
}
