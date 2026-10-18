import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchPipeline,
  type ActiveJobCard,
  type PipelineView,
  type QueuedJobCard,
  type RecentJobCard,
} from '../api/pipeline'
import { usePolling } from '../hooks/usePolling'
import { formatBytes, formatDuration } from '../format'
import { StaleNote } from './States'

/** İş tiplerinin Türkçe etiketleri; bilinmeyen tipler ham adıyla kalır. */
const JOB_TYPE_LABEL: Record<string, string> = {
  media_process: 'Yatay işleme',
  hype_evaluate: 'Hype seçimi',
  clip_render: 'Klip render',
  clip_render_full_cut: 'Tam kesit render',
  source_discover: 'Kaynak keşfi',
  publish_due: 'Yayın kontrolü',
  subtitle_correct: 'Altyazı düzeltme',
  metadata_generate: 'Metaveri üretimi',
  ops_summary: 'Günlük özet',
}

const STAGE_LABEL: Record<string, string> = {
  download: 'İndirme',
  inspect: 'İnceleme',
  transcript: 'Transkript',
  analysis: 'Analiz',
  candidates: 'Aday seçimi',
}

function jobLabel(jobType: string): string {
  return JOB_TYPE_LABEL[jobType] ?? jobType
}

/** job_id -> anlık indirme hızı (bayt/sn). Birbirini izleyen poll'lar
 * arasındaki .part boyutu farkından ölçülür; ilk ölçümde bilinmez. */
function useDownloadRates(active: ActiveJobCard[]): Record<number, number | null> {
  const prevRef = useRef<{ at: number; bytes: Record<number, number> } | null>(null)
  const [rates, setRates] = useState<Record<number, number | null>>({})

  useEffect(() => {
    const now = Date.now()
    const current: Record<number, number> = {}
    for (const card of active) {
      if (card.download) current[card.job_id] = card.download.bytes
    }
    const prev = prevRef.current
    const next: Record<number, number | null> = {}
    if (prev) {
      const dt = (now - prev.at) / 1000
      for (const [key, bytes] of Object.entries(current)) {
        const id = Number(key)
        const before = prev.bytes[id]
        next[id] =
          before !== undefined && dt > 0.5
            ? Math.max(0, (bytes - before) / dt)
            : null
      }
    }
    prevRef.current = { at: now, bytes: current }
    setRates(next)
  }, [active])

  return rates
}

function JobCard({ card, rate }: { card: ActiveJobCard; rate: number | null }) {
  const label = jobLabel(card.job_type)
  const stageIndex = card.stage_index
  const stageLabel = card.stage ? STAGE_LABEL[card.stage] : null
  // Yuzde: asama tabanli kaba oran; indirmede dosya boyutu tahminiyle
  // inceltilir. Tahmin yoksa asama oraninda durur — sayi uydurulmaz.
  let fraction = stageIndex !== null ? stageIndex / card.stage_count : null
  if (stageIndex !== null && card.download && card.download.expected_bytes) {
    const sub = Math.min(
      1,
      card.download.bytes / card.download.expected_bytes,
    )
    fraction = (stageIndex + sub) / card.stage_count
  }
  const percent =
    fraction !== null ? Math.min(99, Math.round(fraction * 100)) : null

  return (
    <div className="pipeline-job">
      <div className="pj-head">
        <span className="pill pill--run">{label}</span>
        <b className="pj-title">{card.title ?? 'Kanal işi'}</b>
        {card.channel_name && (
          <span className="pj-channel">
            {card.ribbon_color && (
              <i style={{ background: card.ribbon_color }} aria-hidden="true" />
            )}
            {card.channel_name}
          </span>
        )}
        {card.attempts > 1 && (
          <span className="pj-attempt nums">
            deneme {card.attempts}/{card.max_attempts}
          </span>
        )}
      </div>
      {stageIndex !== null && (
        <div className="pj-progress">
          <div
            className="stage-track"
            role="img"
            aria-label={`Aşama ${stageIndex + 1}/${card.stage_count}${stageLabel ? `: ${stageLabel}` : ''}`}
          >
            {Array.from({ length: card.stage_count }, (_, i) => (
              <span
                key={i}
                className={`stage-seg${i < stageIndex ? ' done' : i === stageIndex ? ' current' : ''}`}
              />
            ))}
          </div>
          {percent !== null && <span className="pj-percent nums">{percent}%</span>}
        </div>
      )}
      <div className="pj-meta nums">
        {stageLabel && <span>aşama {stageLabel}</span>}
        <span>{formatDuration(card.elapsed_seconds)} sürüyor</span>
        {card.download && (
          <span>
            {formatBytes(card.download.bytes)}
            {card.download.expected_bytes
              ? ` / ≈${formatBytes(card.download.expected_bytes)}`
              : ''}
            {rate ? ` · ${formatBytes(rate)}/sn` : ''}
          </span>
        )}
        {card.eta_seconds !== null && (
          <span title="Son işlerin gerçek sürelerinden tahmin">
            ≈ {formatDuration(card.eta_seconds)} kaldı
          </span>
        )}
      </div>
    </div>
  )
}

function QueueRow({ card }: { card: QueuedJobCard }) {
  return (
    <div className="pipeline-queue-row">
      <span className="pj-pos nums">{card.position}.</span>
      <b>{card.title ?? jobLabel(card.job_type)}</b>
      {card.channel_name && <span>{card.channel_name}</span>}
      {card.attempts > 0 && (
        <span className="nums pj-attempt">
          deneme {card.attempts + 1}/{card.max_attempts}
        </span>
      )}
    </div>
  )
}

function RecentRow({ card }: { card: RecentJobCard }) {
  const ok = card.status === 'succeeded'
  return (
    <div className="pipeline-recent-row">
      <span className={`pill pill--${ok ? 'ok' : 'error'}`}>
        {ok ? 'Tamam' : 'Hata'}
      </span>
      <b>{card.title ?? jobLabel(card.job_type)}</b>
      <span className="nums">{formatDuration(card.duration_seconds)}</span>
      {!ok && card.error && (
        <span className="pj-error" title={card.error}>
          {card.error.slice(0, 64)}
          {card.error.length > 64 ? '…' : ''}
        </span>
      )}
    </div>
  )
}

/** Loading/error durumunda sabit referans: yeni dizi üretilirse
 * useDownloadRates'ın effect'i her render'da yeniden tetiklenir. */
const NO_JOBS: ActiveJobCard[] = []

/** Genel Bakış'ın canlı işler paneli: 5 saniyede bir tazelenir. */
export function LivePipelinePanel() {
  const fetchCb = useCallback(() => fetchPipeline(), [])
  const view = usePolling(fetchCb, 5000)
  const state = view.state

  const active =
    state.status === 'ok' ? state.data.active : NO_JOBS
  const rates = useDownloadRates(active)

  return (
    <section className="ink-panel" aria-label="Canlı boru hattı">
      <h2>Canlı boru hattı</h2>
      <div className="pipeline-body">
        {state.status === 'loading' && (
          <p className="plate-note">İşler sorgulanıyor…</p>
        )}
        {state.status === 'error' && (
          <p className="plate-note">
            Boru hattı durumu alınamıyor ({state.message}).
          </p>
        )}
        {state.status === 'ok' && (
          <>
            {state.stale && <StaleNote onRetry={view.retry} />}
            <PipelineContent data={state.data} rates={rates} />
          </>
        )}
      </div>
    </section>
  )
}

function PipelineContent({
  data,
  rates,
}: {
  data: PipelineView
  rates: Record<number, number | null>
}) {
  const { active, queued, recent } = data
  if (active.length === 0 && queued.length === 0) {
    return (
      <p className="plate-note">
        Motor boşta — çalışan ve bekleyen iş yok. Yeni video seçimi, stok
        hedefinin altına inildiğinde otomatik yapılır.
      </p>
    )
  }
  return (
    <>
      {active.map((card) => (
        <JobCard key={card.job_id} card={card} rate={rates[card.job_id] ?? null} />
      ))}
      {queued.length > 0 && (
        <div className="pipeline-section">
          <h3>Sırada bekleyen</h3>
          {queued.map((card) => (
            <QueueRow key={card.job_id} card={card} />
          ))}
        </div>
      )}
      {recent.length > 0 && (
        <div className="pipeline-section">
          <h3>Son sonuçlar</h3>
          {recent.map((card) => (
            <RecentRow key={card.job_id} card={card} />
          ))}
        </div>
      )}
    </>
  )
}
