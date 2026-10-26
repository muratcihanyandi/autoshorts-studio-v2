import { useCallback, useEffect, useRef, useState } from 'react'

export type PollState<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T; stale: boolean }
  | { status: 'error'; message: string }

interface UsePolling {
  <T>(fetcher: () => Promise<T>, intervalMs?: number): {
    state: PollState<T>
    retry: () => void
    refresh: () => Promise<void>
  }
}

/**
 * Periyodik veri çekme: yükleme / tamam / hata durumları ve yeniden deneme.
 * Veri zaten yüklendiyse yeniden denemede (retry) veya yenilemede (refresh)
 * ekran yükleme durumuna düşürülmez (flicker/sayfa yenilenmesi engellenir);
 * eldeki son veri stale olarak korunur.
 */
export const usePolling: UsePolling = <T,>(
  fetcher: () => Promise<T>,
  intervalMs = 10000,
) => {
  const [state, setState] = useState<PollState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

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
    setState((prev) =>
      prev.status === 'ok' ? { ...prev, stale: true } : { status: 'loading' },
    )
    setAttempt((a) => a + 1)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const data = await fetcherRef.current()
      setState({ status: 'ok', data, stale: false })
    } catch {
      // Arkaplan yenileme hatası mevcut veriyi silmez
    }
  }, [])

  return { state, retry, refresh }
}
