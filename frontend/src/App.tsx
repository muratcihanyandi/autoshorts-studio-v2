import { useEffect, useState } from 'react'
import './App.css'
import { fetchBackendHealth, type BackendHealth } from './api/health'

type HealthState =
  | { status: 'loading' }
  | { status: 'ok'; data: BackendHealth }
  | { status: 'error'; message: string }

function toErrorState(err: unknown): HealthState {
  return {
    status: 'error',
    message: err instanceof Error ? err.message : 'Bilinmeyen hata',
  }
}

function App() {
  const [health, setHealth] = useState<HealthState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    fetchBackendHealth().then(
      (data) => {
        if (!cancelled) setHealth({ status: 'ok', data })
      },
      (err: unknown) => {
        if (!cancelled) setHealth(toErrorState(err))
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

  const retry = () => {
    setHealth({ status: 'loading' })
    void fetchBackendHealth()
      .then((data) => setHealth({ status: 'ok', data }))
      .catch((err: unknown) => setHealth(toErrorState(err)))
  }

  return (
    <main className="shell">
      <header className="shell-header">
        <h1>Autonomous Creator Studio</h1>
        <p className="shell-subtitle">Otomatik YouTube klip stüdyosu — kurulum aşamasında</p>
      </header>

      <section className="status-card" aria-live="polite">
        <h2>Arka uç durumu</h2>
        {health.status === 'loading' && (
          <p className="status status-loading">Denetleniyor…</p>
        )}
        {health.status === 'ok' && (
          <p className="status status-ok">
            Çevrimiçi — {health.data.service} v{health.data.version}
          </p>
        )}
        {health.status === 'error' && (
          <div className="status status-error">
            <p>Bağlantı kurulamadı: {health.message}</p>
            <button type="button" onClick={retry}>
              Yeniden dene
            </button>
          </div>
        )}
      </section>
    </main>
  )
}

export default App
