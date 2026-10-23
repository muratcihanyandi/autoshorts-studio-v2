import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchWhisperStatus,
  installWhisper,
  type WhisperStatus,
} from '../api/whisper'

const POLL_MS = 3000

function platformLabel(status: WhisperStatus | null): string {
  if (!status) return ''
  if (status.platform === 'Linux') {
    return status.machine === 'aarch64' || status.machine === 'arm64'
      ? 'Bu sunucu (ARM64)'
      : 'Linux'
  }
  if (status.platform === 'Windows') return 'Windows'
  return status.platform
}

/** Whisper kurulum durumu + 'Indir ve Kur' dugmesi.
 * Kurulu degilse dugme gorunur; tiklandiginda platforma uygun pip
 * kurulumu arka planda baslar ve durum canli izlenir. */
export function WhisperInstallControl() {
  const [status, setStatus] = useState<WhisperStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const next = await fetchWhisperStatus()
      setStatus(next)
      setError(null)
      return next.status?.state === 'running' || next.installed
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Durum alınamadı.')
      return false
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const stopPolling = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  const startPolling = useCallback(() => {
    stopPolling()
    timer.current = setInterval(() => {
      void refresh().then((keepGoing) => {
        if (!keepGoing) stopPolling()
      })
    }, POLL_MS)
  }, [refresh, stopPolling])

  useEffect(() => stopPolling, [stopPolling])

  async function install() {
    setBusy(true)
    setError(null)
    try {
      await installWhisper()
      // Kurulum basladi: durumu hemen bir kez cek, sonra periyodik izle.
      await refresh()
      startPolling()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Kurulum başlatılamadı.')
    } finally {
      setBusy(false)
    }
  }

  if (status === null && error === null) {
    return <span className="field-help">Whisper durumu sorgulanıyor…</span>
  }

  const running = status?.status?.state === 'running'
  const installed = status?.installed === true
  const failed = status?.status?.state === 'failed'

  return (
    <div className="whisper-row">
      {installed ? (
        <span className="whisper-ok" role="status">
          Whisper kurulu
          {status?.platform ? ` · ${platformLabel(status)}` : ''}
        </span>
      ) : running ? (
        <>
          <span className="whisper-running" role="status">
            Whisper kuruluyor… (torch dahil, birkaç yüz MB; birkaç dakika
            sürebilir)
          </span>
          {status?.status?.mode === 'target' && (
            <span className="field-help">
              Kalıcı medya dizinine kuruluyor; konteyner yenilense de kalır.
            </span>
          )}
        </>
      ) : (
        <>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void install()}
          >
            {busy ? 'Başlatılıyor…' : "Whisper'ı İndir ve Kur"}
          </button>
          <span className="field-help">
            Whisper kurulu değil. Düğme platformunuza göre kurar
            {status ? ` (${platformLabel(status)})` : ''} ve eksik altyazıda
            konuşma tanıma devreye girer. İndirme yaklaşık birkaç yüz MB'tır.
          </span>
        </>
      )}
      {failed && (
        <span className="whisper-error" role="alert">
          Son kurulum başarısız:{' '}
          {status?.status?.error?.slice(0, 160) ?? 'bilinmeyen hata'}
        </span>
      )}
      {error && (
        <span className="whisper-error" role="alert">
          {error}
        </span>
      )}
    </div>
  )
}
