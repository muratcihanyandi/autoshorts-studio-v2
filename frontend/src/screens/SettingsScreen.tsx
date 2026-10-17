import { useCallback } from 'react'
import { fetchOverview } from '../api/overview'
import { usePolling } from '../hooks/usePolling'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

const PHASE_LABEL: Record<string, string> = {
  setup: 'Kurulum — veritabanı bekleniyor',
  awaiting_channels: 'Kanal bekleniyor',
  running: 'Çalışıyor',
}

export function SettingsScreen() {
  const fetcher = useCallback(() => fetchOverview(), [])
  const { state, retry } = usePolling(fetcher, 30000)

  return (
    <>
      <div className="screen-head">
        <h1>AYARLAR</h1>
        <span className="screen-sub">Sistem bilgisi</span>
      </div>

      {state.status === 'loading' && <LoadingState label="Bilgiler okunuyor…" />}
      {state.status === 'error' && (
        <ErrorState
          title="Bilgiler alınamadı"
          message={`Arka uca ulaşılamadı: ${state.message}.`}
          onRetry={retry}
        />
      )}
      {state.status === 'ok' && (
        <>
          {state.stale && <StaleNote onRetry={retry} />}
          <section className="ink-panel" style={{ maxWidth: 720 }}>
            <h2>SİSTEM</h2>
            <table className="info-table">
              <tbody>
                <tr>
                  <th>Sürüm</th>
                  <td className="nums">v{state.data.version}</td>
                </tr>
                <tr>
                  <th>Ortam</th>
                  <td>{state.data.app_env}</td>
                </tr>
                <tr>
                  <th>Durum</th>
                  <td>{PHASE_LABEL[state.data.phase] ?? state.data.phase}</td>
                </tr>
                <tr>
                  <th>Veritabanı</th>
                  <td>
                    {state.data.database === 'reachable'
                      ? 'Bağlı (PostgreSQL)'
                      : state.data.database === 'unreachable'
                        ? 'Erişilemiyor'
                        : 'Yapılandırılmadı'}
                  </td>
                </tr>
                <tr>
                  <th>Güncelleme</th>
                  <td>
                    main dalına push edildiğinde GHCR imajları otomatik
                    derlenir; CasaOS’ta uygulamayı yeniden başlatmak yeterli.
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
        </>
      )}
    </>
  )
}
