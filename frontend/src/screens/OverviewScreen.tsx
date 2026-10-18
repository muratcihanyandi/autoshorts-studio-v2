import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchOverview, type Overview, type StudioPhase } from '../api/overview'
import { fetchSystemResources } from '../api/system'
import {
  ACTIVITY_LABEL,
  AUTOMATION_STATE_LABEL,
  startAutomation,
  stopAutomation,
  type ChannelRow,
} from '../api/automation'
import { usePolling } from '../hooks/usePolling'
import { Gauge } from '../components/Studio'
import { ChannelSettingsModal } from '../components/ChannelSettingsModal'
import { LivePipelinePanel } from '../components/LivePipeline'
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

function stateTone(state: string): 'ok' | 'warn' | 'error' | 'idle' {
  if (state === 'running') return 'ok'
  if (state === 'paused') return 'warn'
  if (state === 'error') return 'error'
  return 'idle'
}

function activityTone(activity: string): 'ok' | 'run' | 'idle' {
  if (activity === 'stock_ready') return 'ok'
  if (activity === 'stopped' || activity === 'idle') return 'idle'
  return 'run'
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('tr-TR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

/** Bir kanalın kontrol satırı: Başlat/Durdur, kalıcı otomasyon durumu,
 * gerçek motor aktivitesi, stok/kuyruk/shorts sayıları, son hata. */
function OverviewChannelRow({
  row,
  onToggle,
  onOpenSettings,
  busy,
}: {
  row: ChannelRow
  onToggle: (row: ChannelRow) => void
  onOpenSettings: (row: ChannelRow) => void
  busy: boolean
}) {
  const running = row.automation_state === 'running'
  return (
    <div className="overview-channel">
      <div className="oc-identity">
        <i style={{ background: row.ribbon_color }} aria-hidden="true" />
        <b>{row.name}</b>
      </div>
      <span className={`pill pill--${stateTone(row.automation_state)}`}>
        {AUTOMATION_STATE_LABEL[row.automation_state]}
      </span>
      <div className="oc-metrics">
        <span>
          stok{' '}
          <span className="nums">
            {row.horizontal_stock}/{row.horizontal_stock_target}
          </span>
        </span>
        <span>
          sırada <span className="nums">{row.queued_horizontal}</span>
        </span>
        <span>
          Shorts <span className="nums">{row.shorts_ready}</span>
        </span>
        {row.full_cuts_ready > 0 && (
          <span>
            tam kesit <span className="nums">{row.full_cuts_ready}</span>
          </span>
        )}
      </div>
      <div className="oc-actions">
        <button
          className={`btn${running ? ' btn--danger' : ''}`}
          disabled={busy}
          onClick={() => onToggle(row)}
        >
          {running ? 'Durdur' : 'Başlat'}
        </button>
        <button className="btn btn--ghost" onClick={() => onOpenSettings(row)}>
          Ayarlar
        </button>
      </div>
      <div className="oc-activity">
        <span className={`pill pill--${activityTone(row.engine_activity)}`}>
          {ACTIVITY_LABEL[row.engine_activity]}
        </span>
        <span>son işlem: {formatTime(row.last_success_at)}</span>
        {row.last_error && (
          <span className="error" title={row.last_error}>
            son hata: {row.last_error.slice(0, 80)}
          </span>
        )}
      </div>
    </div>
  )
}

export function OverviewScreen() {
  const fetchOverviewCb = useCallback(() => fetchOverview(), [])
  const fetchSystemCb = useCallback(() => fetchSystemResources(), [])
  const overview = usePolling(fetchOverviewCb, 10000)
  const system = usePolling(fetchSystemCb, 10000)
  const [busyChannel, setBusyChannel] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [modalChannel, setModalChannel] = useState<ChannelRow | null>(null)

  async function toggleChannel(row: ChannelRow) {
    setBusyChannel(row.channel_id)
    setActionError(null)
    try {
      if (row.automation_state === 'running') {
        await stopAutomation(row.channel_id)
      } else {
        await startAutomation(row.channel_id)
      }
      await overview.retry()
    } catch (exc) {
      setActionError(
        exc instanceof Error ? exc.message : 'İşlem başarısız oldu.',
      )
    } finally {
      setBusyChannel(null)
    }
  }

  const rows = overview.state.status === 'ok' ? overview.state.data.channel_rows ?? [] : []
  const worker = overview.state.status === 'ok' ? overview.state.data.worker : undefined

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

          {worker && (
            <div className={`worker-banner${worker.running ? '' : ' off'}`}>
              <span
                className={`pill ${worker.running ? 'pill--ok' : 'pill--error'}`}
              >
                {worker.running ? 'Worker çalışıyor' : 'Worker kapalı'}
              </span>
              {worker.running ? (
                <span className="nums">
                  {worker.jobs_processed} iş · son sinyal{' '}
                  {formatTime(worker.last_tick_at)}
                </span>
              ) : worker.enabled ? (
                <span>
                  Worker açıktı ama sinyal gelmiyor — konteyneri yeniden
                  başlatın.
                </span>
              ) : (
                <span>
                  Otomasyon motoru bu dağıtımda kapalı (WORKER_ENABLED). Compose
                  dosyasında açın; Başlat/Durdur ancak motor çalışırken iş
                  üretir.
                </span>
              )}
            </div>
          )}

          {(() => {
            const pill = PHASE_PILL[overview.state.data.phase]
            return <span className={`pill pill--${pill.tone}`}>{pill.text}</span>
          })()}

          <div className="stat-grid" aria-label="Günün özeti">
            <div className="stat-card">
              <span>Bugün yayınlanan yatay</span>
              <b className="nums">
                {overview.state.data.today_published.horizontal}
                <small>
                  /{' '}
                  {overview.state.data.today_published.horizontal_limit ||
                    '∞'}
                </small>
              </b>
              <small>günlük yatay limiti</small>
            </div>
            <div className="stat-card">
              <span>Bugün yayınlanan dikey</span>
              <b className="nums">
                {overview.state.data.today_published.vertical}
                <small>
                  / {overview.state.data.today_published.vertical_limit || '∞'}
                </small>
              </b>
              <small>günlük dikey limiti</small>
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
                  / {overview.state.data.channels.total ?? 0} kayıtlı
                </small>
              </b>
              <small>otomasyon kanal bazında yönetilir</small>
            </div>
            <div className="stat-card">
              <span>İş kuyruğu</span>
              <b className="nums">{overview.state.data.jobs.active}</b>
              <small>
                sürüyor · {overview.state.data.jobs.queued} sırada
              </small>
            </div>
          </div>

          <LivePipelinePanel />

          <div className="two-col">
            <div className="stack">
              <section className="ink-panel" aria-label="Kanallar">
                <h2>Kanallar</h2>
                {actionError && (
                  <p className="plate-note error">{actionError}</p>
                )}
                {rows.length > 0 ? (
                  rows.map((row) => (
                    <OverviewChannelRow
                      key={row.channel_id}
                      row={row}
                      onToggle={(r) => void toggleChannel(r)}
                      onOpenSettings={setModalChannel}
                      busy={busyChannel === row.channel_id}
                    />
                  ))
                ) : (
                  <p className="plate-note">
                    Henüz kanal yok.{' '}
                    <Link to="/kanallar">Kanallar ekranına git</Link> — ilk
                    kanalı ekleyince burada kontrol satırı açılır.
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

      {modalChannel && (
        <ChannelSettingsModal
          channelId={modalChannel.channel_id}
          channelName={modalChannel.name}
          onClose={() => setModalChannel(null)}
          onSaved={() => void overview.retry()}
        />
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
