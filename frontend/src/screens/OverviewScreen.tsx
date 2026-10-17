import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { fetchOverview, type Overview, type StudioPhase } from '../api/overview'
import { fetchSystemResources } from '../api/system'
import { fetchChannels, STATUS_LABEL } from '../api/channels'
import { usePolling } from '../hooks/usePolling'
import { BillRow, Gauge, Stamp } from '../components/Studio'
import {
  ErrorState,
  LoadingState,
  StaleNote,
} from '../components/States'

const STAMP_BY_PHASE: Record<
  StudioPhase,
  { text: string; variant: 'live' | 'wait' | 'setup' }
> = {
  setup: { text: 'KURULUM', variant: 'setup' },
  awaiting_channels: { text: 'KANAL BEKLENİYOR', variant: 'wait' },
  running: { text: 'ŞİMDİ YAYINDA', variant: 'live' },
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
        <h1>GENEL BAKIŞ</h1>
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
          <div className="two-col">
            <section className="plate" aria-label="Günün özeti">
              <div className="marquee">
                <div>
                  <span className="marquee-number nums">
                    {overview.state.data.today_published}
                  </span>
                  <span className="marquee-label">BUGÜN YAYINLANAN KLİP</span>
                </div>
                <Stamp
                  key={overview.state.data.phase}
                  {...STAMP_BY_PHASE[overview.state.data.phase]}
                />
              </div>

              <p className="plate-note">
                {overview.state.data.phase === 'running'
                  ? 'Otomasyon çalışıyor: kurallar sağlandıkça sistem kendisi yayınlıyor.'
                  : overview.state.data.phase === 'awaiting_channels'
                    ? 'Sıradaki adım: bir YouTube kanalı bağla — takvim ve üretim hattı kanallarla döner.'
                    : 'Veritabanı bağlantısı yapılandırılmadı: dağıtım kontrol listesindeki .env adımını tamamla.'}
              </p>

              <div className="bill">
                <BillRow
                  label="KANALLAR"
                  value={`${overview.state.data.channels.connected} bağlı`}
                />
                <BillRow
                  label="KAYNAK İZLEME"
                  value={`${overview.state.data.sources.monitored} kaynak`}
                />
                <BillRow
                  label="İŞ KUYRUĞU"
                  value={`${overview.state.data.jobs.active} sürüyor · ${overview.state.data.jobs.queued} sırada`}
                />
                <BillRow
                  label="LLM SAĞLAYICILARI"
                  value={`${overview.state.data.llm_providers.configured} yapılandırılmış`}
                />
                <BillRow
                  label="ÖZEL STOK"
                  value={`${overview.state.data.stock.clips} klip`}
                />
                <BillRow
                  label="BUGÜN YAYIN"
                  value={overview.state.data.today_published}
                  tone={overview.state.data.today_published > 0 ? 'green' : 'plain'}
                />
                <BillRow
                  label="VERİTABANI"
                  value={databaseLabel(overview.state.data.database)}
                  tone={overview.state.data.database === 'reachable' ? 'green' : 'amber'}
                />
              </div>
            </section>

            <div className="stack">
              <section className="ink-panel" aria-label="Pi kaynakları">
                <h2>Pİ KAYNAKLARI</h2>
                {system.state.status === 'loading' && (
                  <p className="screen-sub">Ölçüm bekleniyor…</p>
                )}
                {system.state.status === 'error' && (
                  <p className="screen-sub">
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

              <section className="ink-panel" aria-label="Kanallar">
                <h2>KANALLAR</h2>
                {channels.state.status === 'ok' &&
                channels.state.data.channels.length > 0 ? (
                  <>
                    {channels.state.data.channels.slice(0, 5).map((channel) => (
                      <div className="channel-row" key={channel.id}>
                        <i style={{ background: channel.ribbon_color }} />
                        {channel.name}
                        <small>{STATUS_LABEL[channel.status]}</small>
                      </div>
                    ))}
                    {channels.state.data.channels.length > 5 && (
                      <p className="screen-sub">
                        <Link to="/kanallar">
                          +{channels.state.data.channels.length - 5} kanal daha
                        </Link>
                      </p>
                    )}
                  </>
                ) : (
                  <p className="screen-sub">
                    Henüz bağlı kanal yok.{' '}
                    <Link to="/kanallar">Kanallar ekranına git</Link> — ilk
                    kanalı bağlayınca burada kurdele rengiyle listelenir.
                  </p>
                )}
              </section>
            </div>
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
