import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { fetchOverview, type Overview, type StudioPhase } from '../api/overview'
import { fetchSystemResources } from '../api/system'
import { fetchChannels, STATUS_LABEL } from '../api/channels'
import { usePolling } from '../hooks/usePolling'
import { Gauge } from '../components/Studio'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

const PHASE_PILL: Record<
  StudioPhase,
  { text: string; tone: 'ok' | 'warn' }
> = {
  setup: { text: 'Kurulum', tone: 'warn' },
  awaiting_channels: { text: 'Kanal bekleniyor', tone: 'warn' },
  running: { text: 'Sistem sağlıklı', tone: 'ok' },
}

function databaseLabel(db: Overview['database']): string {
  if (db === 'reachable') return 'bağlı'
  if (db === 'unreachable') return 'erişilemiyor'
  return 'yapılandırılmadı'
}

function gaugeTone(percent: number): 'plain' | 'warn' {
  return percent >= 80 ? 'warn' : 'plain'
}

export function OverviewScreen() {
  const fetchOverviewCb = useCallback(() => fetchOverview(), [])
  const fetchSystemCb = useCallback(() => fetchSystemResources(), [])
  const fetchChannelsCb = useCallback(() => fetchChannels(), [])
  const overview = usePolling(fetchOverviewCb, 15000)
  const system = usePolling(fetchSystemCb, 10000)
  const channels = usePolling(fetchChannelsCb, 20000)

  return (
    <>
      <div className="screen-head">
        <h1>Genel Bakış</h1>
        <span className="screen-sub nums">
          {overview.state.status === 'ok'
            ? `v${overview.state.data.version} · çalışma süresi ${formatUptime(overview.state.data.uptime_seconds)}`
            : 'AutoShorts Studio'}
        </span>
      </div>

      {overview.state.status === 'loading' && (
        <LoadingState label="Stüdyo durumu sorgulanıyor…" />
      )}
      {overview.state.status === 'error' && (
        <ErrorState
          title="Durum alınamadı"
          message={`Arka uca ulaşılamadı: ${overview.state.message}. Pi üzerindeki konteynerleri ve ağı kontrol et.`}
          onRetry={overview.retry}
        />
      )}

      {overview.state.status === 'ok' && (
        <>
          {overview.state.stale && <StaleNote onRetry={overview.retry} />}
          {(() => {
            const pill = PHASE_PILL[overview.state.data.phase]
            return <span className={`pill pill--${pill.tone}`}>{pill.text}</span>
          })()}

          <div className="stat-grid" aria-label="Günün özeti">
            <div className="stat-card">
              <span>Bugün yayınlanan</span>
              <b className="nums">{overview.state.data.today_published}</b>
              <small>klip</small>
            </div>
            <div className="stat-card">
              <span>Özel stok</span>
              <b className="nums">{overview.state.data.stock.clips}</b>
              <small>klip</small>
            </div>
            <div
              className={`stat-card${
                overview.state.data.channels.connected === 0 ? ' warn' : ''
              }`}
            >
              <span>Bağlı kanal</span>
              <b className="nums">
                {overview.state.data.channels.connected}
                <small>
                  / {overview.state.data.channels.total} kayıtlı
                </small>
              </b>
              <small>
                {overview.state.data.channels.connected > 0
                  ? 'otomasyon aktif'
                  : 'ilk kanalı bağlayınca hattı döner'}
              </small>
            </div>
            <div className="stat-card">
              <span>İş kuyruğu</span>
              <b className="nums">{overview.state.data.jobs.active}</b>
              <small>
                sürüyor · {overview.state.data.jobs.queued} sırada
              </small>
            </div>
          </div>

          <div className="two-col">
            <div className="stack">
              <section className="ink-panel" aria-label="Kanallar">
                <h2>Kanallar</h2>
                {channels.state.status === 'ok' &&
                channels.state.data.channels.length > 0 ? (
                  <table className="info-table">
                    <tbody>
                      {channels.state.data.channels.slice(0, 5).map((channel) => (
                        <tr key={channel.id}>
                          <th>
                            <i
                              style={{
                                display: 'inline-block',
                                width: 10,
                                height: 10,
                                borderRadius: 3,
                                background: channel.ribbon_color,
                                marginRight: 8,
                              }}
                            />
                            {channel.name}
                          </th>
                          <td className="nums">{channel.handle ?? '—'}</td>
                          <td>
                            <span
                              className={`pill ${
                                channel.status === 'connected'
                                  ? 'pill--ok'
                                  : 'pill--idle'
                              }`}
                            >
                              {STATUS_LABEL[channel.status]}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="plate-note">
                    Henüz bağlı kanal yok.{' '}
                    <Link to="/kanallar">Kanallar ekranına git</Link> — ilk
                    kanalı bağlayınca burada listelenir.
                  </p>
                )}
                {channels.state.status === 'ok' &&
                  channels.state.data.channels.length > 5 && (
                    <p className="plate-note">
                      <Link to="/kanallar">
                        +{channels.state.data.channels.length - 5} kanal daha
                      </Link>
                    </p>
                  )}
              </section>

              <section className="ink-panel" aria-label="Boru hattı">
                <h2>Boru hattı</h2>
                <table className="info-table">
                  <tbody>
                    <tr>
                      <th>Kaynak izleme</th>
                      <td className="nums">
                        {overview.state.data.sources.monitored} yetkili kaynak
                      </td>
                      <td>
                        <span className="pill pill--idle">
                          {overview.state.data.sources.monitored > 0
                            ? 'İzleniyor'
                            : 'Kaynak yok'}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <th>İş kuyruğu</th>
                      <td className="nums">
                        {overview.state.data.jobs.active} sürüyor ·{' '}
                        {overview.state.data.jobs.queued} sırada
                      </td>
                      <td>
                        <span
                          className={`pill ${
                            overview.state.data.jobs.active > 0
                              ? 'pill--run'
                              : 'pill--ok'
                          }`}
                        >
                          {overview.state.data.jobs.active > 0
                            ? 'Sürüyor'
                            : 'Boş'}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <th>LLM sağlayıcıları</th>
                      <td className="nums">
                        {overview.state.data.llm_providers.configured}{' '}
                        yapılandırılmış
                      </td>
                      <td>
                        <span
                          className={`pill ${
                            overview.state.data.llm_providers.configured > 0
                              ? 'pill--ok'
                              : 'pill--idle'
                          }`}
                        >
                          {overview.state.data.llm_providers.configured > 0
                            ? 'Hazır'
                            : 'Yapılandırılmadı'}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <th>Veritabanı</th>
                      <td>PostgreSQL</td>
                      <td>
                        <span
                          className={`pill ${
                            overview.state.data.database === 'reachable'
                              ? 'pill--ok'
                              : 'pill--error'
                          }`}
                        >
                          {databaseLabel(overview.state.data.database)}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </section>
            </div>

            <section className="ink-panel" aria-label="Pi kaynakları">
              <h2>Pi kaynakları</h2>
              {system.state.status === 'loading' && (
                <p className="plate-note">Ölçüm bekleniyor…</p>
              )}
              {system.state.status === 'error' && (
                <p className="plate-note">
                  Kaynak ölçümü alınamıyor ({system.state.message}).
                </p>
              )}
              {system.state.status === 'ok' && (
                <>
                  {system.state.stale && <StaleNote onRetry={system.retry} />}
                  <Gauge
                    label="CPU"
                    value={`${Math.round(system.state.data.cpu_percent)}%`}
                    tone={gaugeTone(system.state.data.cpu_percent)}
                  />
                  <Gauge
                    label={`RAM (${Math.round(system.state.data.memory_total_mb / 1024)} GB)`}
                    value={`${Math.round(system.state.data.memory_percent)}%`}
                    tone={gaugeTone(system.state.data.memory_percent)}
                  />
                  <Gauge
                    label={`Disk (${Math.round(system.state.data.disk_total_gb)} GB)`}
                    value={`${Math.round(system.state.data.disk_percent)}%`}
                    tone={gaugeTone(system.state.data.disk_percent)}
                  />
                  {system.state.data.temperature_c !== null && (
                    <Gauge
                      label="Sıcaklık"
                      value={`${system.state.data.temperature_c}°C`}
                      tone={system.state.data.temperature_c >= 75 ? 'warn' : 'ok'}
                    />
                  )}
                </>
              )}
            </section>
          </div>
        </>
      )}
    </>
  )
}

function formatUptime(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${Math.round(seconds)} sn`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} dk`
  const hours = Math.floor(seconds / 3600)
  if (hours < 24) return `${hours} sa ${Math.floor((seconds % 3600) / 60)} dk`
  return `${Math.floor(hours / 24)} gün ${hours % 24} sa`
}
