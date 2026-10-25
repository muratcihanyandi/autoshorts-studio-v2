import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchOverview, type Overview, type StudioPhase } from '../api/overview'
import { fetchPulse, type PulseEvent } from '../api/pulse'
import { fetchSystemResources } from '../api/system'
import {
  ACTIVITY_LABEL,
  AUTOMATION_STATE_LABEL,
  startAutomation,
  stopAutomation,
  type ChannelRow,
} from '../api/automation'
import { usePolling } from '../hooks/usePolling'
import { formatDateTime } from '../format'
import { pulseStory, relativeTime } from '../pulse/narrative'
import { Gauge } from '../components/Studio'
import { ChannelSettingsModal } from '../components/ChannelSettingsModal'
import { PipelineDetailModal } from '../components/PipelineDetailModal'
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

/** Sıradaki yayın kartı: elle plan varsa saati büyütür, yoksa
 * otomatik slot bekleyen klip sayısını dürüstçe söyler. */
function NextPublishCard({ data }: { data: Overview }) {
  const next = data.next_publish ?? null
  if (next?.scheduled_at) {
    let clock = '—'
    try {
      clock = new Date(next.scheduled_at).toLocaleTimeString('tr-TR', {
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      clock = '—'
    }
    return (
      <div className="stat-card stat-card--publish">
        <span>Sıradaki yayın</span>
        <b className="nums">{clock}</b>
        <small>
          {formatDateTime(next.scheduled_at)}
          {next.channel_name ? ` · ${next.channel_name}` : ''}
          {next.title ? ` · “${next.title}”` : ''}
        </small>
      </div>
    )
  }
  if (next && next.waiting_count > 0) {
    return (
      <div className="stat-card stat-card--publish">
        <span>Yayın bekliyor</span>
        <b className="nums">{next.waiting_count}</b>
        <small>gizli yüklü klip otomatik saati bekliyor</small>
      </div>
    )
  }
  return (
    <div className="stat-card stat-card--publish">
      <span>Sıradaki yayın</span>
      <b className="nums">—</b>
      <small>planlanmış yayın yok</small>
    </div>
  )
}

/** Bugünün akışı: stüdyonun sesi genel bakışın ilk ekranında da
 * yaşar — panel ayrı yoklamayla tazelenir (madde 3 + madde 2). */
function TodayFlowPanel() {
  const fetchCb = useCallback(() => fetchPulse(), [])
  const feed = usePolling(fetchCb, 15000)
  if (feed.state.status === 'error') {
    return <p className="plate-note">Akış şu an okunamıyor.</p>
  }
  const events: PulseEvent[] =
    feed.state.status === 'ok' ? feed.state.data.events.slice(0, 8) : []
  if (events.length === 0) {
    return (
      <p className="plate-note">
        Bugün henüz kayda değer bir şey olmadı. Motor işleri tamamladıkça
        burada doğal cümlelerle göreceksin.
      </p>
    )
  }
  return (
    <ul className="activity-list overview-flow">
      {events.map((event) => {
        const story = pulseStory(event)
        return (
          <li key={event.id} className={`activity-item tone--${story.tone}`}>
            <span className="activity-dot" aria-hidden="true" />
            <div>
              <p>{story.sentence}</p>
              <small>
                {event.channel_name ? `${event.channel_name} · ` : ''}
                {relativeTime(event.created_at)}
              </small>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** Bir kanalın kontrol satırı: Başlat/Durdur, kalıcı otomasyon durumu,
 * gerçek motor aktivitesi, stok/kuyruk/shorts sayıları, son hata.
 * Stok hedefine ilerleme ince meter'la gösterilir (madde 3 dolgunluk). */
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
  const stockPercent =
    row.ready_stock_target > 0
      ? Math.min(100, Math.round((row.ready_stock / row.ready_stock_target) * 100))
      : 0
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
          hazır stok{' '}
          <span className="nums">
            {row.ready_stock}/{row.ready_stock_target}
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
      <div
        className="oc-stock-meter"
        role="meter"
        aria-valuenow={stockPercent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${row.name} stok doluluğu`}
        title={`Stok hedefi doluluğu: %${stockPercent}`}
      >
        <i style={{ width: `${stockPercent}%` }} />
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
  const [pipelineDetail, setPipelineDetail] = useState(false)

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
  // Kalıcı çözüm (2026-10-21): motor çalışıyor ama elde iş yoksa
  // (aktif+kuyruk 0, üretim sırası boş, stok boş) bunu ekranda söyle —
  // aksi halde "çalışıyor ama işlem yok" gizli kalıyordu.
  const data = overview.state.status === 'ok' ? overview.state.data : null
  const productionEmpty =
    data !== null &&
    (data.worker?.running ?? false) &&
    data.jobs.active === 0 &&
    data.jobs.queued === 0 &&
    (data.production?.planned_videos ?? 0) === 0 &&
    data.stock.clips === 0

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

          {productionEmpty && (
            <div className="action-error" role="alert">
              Motor çalışıyor ama işlenecek video yok: üretim sırası ve hazır
              stok boş. Kaynak kanallarda yeni videoları bekliyor — ya da
              videolar 'Hariç' durumuna düştü. Medya Kütüphanesi → Hariç
              tutulanlar bölümünden geri alabilirsin.
            </div>
          )}

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
            <div className="stat-card">
              <span>Hazır stok</span>
              <b className="nums">{overview.state.data.stock.clips}</b>
              <small>yayın bekleyen klip</small>
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
          </div>

          {/* Gün nabzı: işler, sıradaki yayın (madde 3 dolgun satır) */}
          <div className="stat-grid stat-grid--pulse" aria-label="Günün nabzı">
            <div className="stat-card">
              <span>İş kuyruğu</span>
              <b className="nums">{overview.state.data.jobs.active}</b>
              <small>
                sürüyor · {overview.state.data.jobs.queued} sırada
              </small>
            </div>
            <div className="stat-card">
              <span>Bugün tamamlanan</span>
              <b className="nums">
                {overview.state.data.today_jobs?.succeeded ?? 0}
              </b>
              <small>iş başarıyla bitti</small>
            </div>
            <div
              className={`stat-card${
                (overview.state.data.today_jobs?.failed ?? 0) > 0 ? ' warn' : ''
              }`}
            >
              <span>Bugün hatalı</span>
              <b className="nums">
                {overview.state.data.today_jobs?.failed ?? 0}
              </b>
              <small>
                {(overview.state.data.today_jobs?.failed ?? 0) > 0
                  ? 'Günlükler → Hatalar sekmesinden incele'
                  : 'aksilik yok'}
              </small>
            </div>
            <NextPublishCard data={overview.state.data} />
          </div>

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
                <div className="table-scroll">
                  <table className="info-table">
                    <tbody>
                      <tr
                        className="interactive-row"
                        onClick={() => setPipelineDetail(true)}
                        title="Kaynak detaylarını görmek için tıklayın"
                      >
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
                      <tr
                        className="interactive-row"
                        onClick={() => setPipelineDetail(true)}
                        title="Kuyruk ve çalışan iş detaylarını görmek için tıklayın"
                      >
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
                      <tr
                        className="interactive-row"
                        onClick={() => setPipelineDetail(true)}
                        title="Üretim sırası ve planlama kararlarını görmek için tıklayın"
                      >
                        <th>Üretim sırası</th>
                        <td className="nums">
                          {overview.state.data.production?.planned_videos ?? 0}{' '}
                          video işlenmeyi bekliyor
                        </td>
                        <td>
                          <span className="pill pill--idle">
                            {(overview.state.data.production?.planned_videos ?? 0) > 0
                              ? 'Dolu'
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
                </div>
                <div style={{ padding: '10px 18px', borderTop: '1px solid var(--plate-line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <small style={{ color: 'var(--plate-muted)' }}>İşlenen videolar ve izlenen kanalların ayrıntıları</small>
                  <button type="button" className="btn btn--ghost" onClick={() => setPipelineDetail(true)}>
                    Detayları İncele →
                  </button>
                </div>
              </section>
            </div>

            <div className="stack">
              <section className="ink-panel" aria-label="Bugünün akışı">
                <h2>Bugünün akışı</h2>
                <TodayFlowPanel />
              </section>

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

      {pipelineDetail && (
        <PipelineDetailModal onClose={() => setPipelineDetail(false)} />
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
