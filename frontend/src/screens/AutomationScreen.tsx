import { useCallback, useState } from 'react'
import {
  cancelJob,
  fetchJobs,
  JOB_STATUS_LABEL,
  retryJob,
  type Job,
} from '../api/jobs'
import type { StageStep } from '../api/media'
import { usePolling } from '../hooks/usePolling'
import { formatDuration, formatTimeShort } from '../format'
import { jobAction, jobStageDetail } from '../jobNarrative'
import { notifyPulse } from '../pulse/bus'
import { ErrorState, LoadingState, StaleNote } from '../components/States'
import { StageTrack } from '../components/StageTrack'

/** media_process işinin beş aşaması — çalışan işin kartında canlı
 * ilerleme çubuğu olarak gösterilir (madde 4 otomasyon canlandırması). */
const MEDIA_STAGES: { key: string; label: string }[] = [
  { key: 'download', label: 'İndirme' },
  { key: 'inspect', label: 'İnceleme' },
  { key: 'transcript', label: 'Altyazı' },
  { key: 'analysis', label: 'Analiz' },
  { key: 'candidates', label: 'Adaylar' },
]

function mediaStageSteps(stage: string | null): StageStep[] {
  const currentIndex = MEDIA_STAGES.findIndex((item) => item.key === stage)
  return MEDIA_STAGES.map((item, index) => ({
    key: item.key,
    label: item.label,
    state:
      stage === null || currentIndex === -1
        ? ('pending' as const)
        : index < currentIndex
          ? ('done' as const)
          : index === currentIndex
            ? ('active' as const)
            : ('pending' as const),
    detail: null,
  }))
}

function statusTone(status: Job['status']): string {
  if (status === 'running') return 'run'
  if (status === 'failed') return 'error'
  if (status === 'succeeded') return 'ok'
  if (status === 'cancelling') return 'warn'
  return 'idle'
}

function secondsBetween(a: string | null, b: number): number | null {
  if (!a) return null
  const from = new Date(a).getTime()
  if (Number.isNaN(from)) return null
  return Math.max(0, Math.round((b - from) / 1000))
}

/** Süren iş için geçen süre, bitmiş iş için toplam süre. */
function jobDuration(job: Job, now: number): number | null {
  if (job.status === 'running' || job.status === 'cancelling') {
    return secondsBetween(job.started_at, now)
  }
  if (!job.started_at || !job.finished_at) return null
  const started = new Date(job.started_at).getTime()
  const finished = new Date(job.finished_at).getTime()
  if (Number.isNaN(started) || Number.isNaN(finished)) return null
  return Math.max(0, Math.round((finished - started) / 1000))
}

function isToday(iso: string | null): boolean {
  if (!iso) return false
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return false
  const now = new Date()
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  )
}

/** Tek işin anlatım satırı: durum, video, olup biten, kanal ve süre —
 * sade bir cümle okuyuşu; çalışan media_process işi aşama çubuğunu da
 * taşır. Teknik ayrıntılar yalnız hata varsa girer. */
function JobRow({
  job,
  now,
  position,
  busy,
  onCancel,
  onRetry,
}: {
  job: Job
  now: number
  position: number | null
  busy: boolean
  onCancel: (job: Job) => void
  onRetry: (job: Job) => void
}) {
  const canCancel = job.status === 'queued' || job.status === 'running'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const duration = jobDuration(job, now)
  const action = jobAction(job)
  const running = job.status === 'running' || job.status === 'cancelling'
  const showTrack =
    running && job.job_type === 'media_process' && job.stage !== null
  return (
    <div className={`flow-row${running ? ' flow-row--live' : ''}`}>
      {position !== null && <span className="flow-pos nums">{position}.</span>}
      <span className={`pill pill--${statusTone(job.status)}`}>
        {running && <i className="live-dot live-dot--inline" aria-hidden="true" />}
        {JOB_STATUS_LABEL[job.status]}
      </span>
      {job.title ? <b>{job.title}</b> : <b>{action}</b>}
      {job.title && <span className="flow-soft">{action}</span>}
      {job.channel_name && (
        <span className="flow-soft">
          {job.ribbon_color && (
            <i style={{ background: job.ribbon_color }} aria-hidden="true" />
          )}
          {job.channel_name}
        </span>
      )}
      {job.youtube_video_id && (
        <a
          href={`https://www.youtube.com/watch?v=${job.youtube_video_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="lib-yt-link nums"
          title="YouTube'da izle"
        >
          YouTube ↗
        </a>
      )}
      {duration !== null && (
        <span className="flow-soft nums">
          {formatDuration(duration)}
          {job.attempts > 1 ? ` · deneme ${job.attempts}/${job.max_attempts}` : ''}
        </span>
      )}
      {job.finished_at && (
        <span className="flow-soft nums">{formatTimeShort(job.finished_at)}</span>
      )}
      {job.last_error && (
        <span className="flow-error" title={job.last_error}>
          {job.last_error.slice(0, 90)}
          {job.last_error.length > 90 ? '…' : ''}
        </span>
      )}
      {(canCancel || canRetry) && (
        <span className="flow-actions">
          {canCancel && (
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => onCancel(job)}
            >
              İptal
            </button>
          )}
          {canRetry && (
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={() => onRetry(job)}
            >
              Yeniden dene
            </button>
          )}
        </span>
      )}
      {showTrack && (
        <div className="flow-track">
          <StageTrack steps={mediaStageSteps(job.stage)} />
          <p className="flow-detail">{jobStageDetail(job)}</p>
        </div>
      )}
    </div>
  )
}

export function AutomationScreen() {
  const fetcher = useCallback(() => fetchJobs(), [])
  const { state, retry } = usePolling(fetcher, 10000)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [filter, setFilter] = useState<'all' | 'running' | 'queued' | 'failed'>('all')

  const act = async (
    id: number,
    fn: (id: number) => Promise<Job>,
    successPulse?: Parameters<typeof notifyPulse>[0],
  ) => {
    setBusy(id)
    setActionError(null)
    try {
      await fn(id)
      if (successPulse) notifyPulse(successPulse)
      retry()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'bilinmeyen hata')
    } finally {
      setBusy(null)
    }
  }

  const cancelWithNote = (job: Job) =>
    act(job.id, cancelJob, {
      tone: 'warn',
      sentence: `“${job.title ?? 'İş'}” iptal edildi`,
    })

  const retryWithNote = (job: Job) =>
    act(job.id, retryJob, {
      tone: 'run',
      sentence: `“${job.title ?? 'İş'}” yeniden kuyruğa alındı`,
      link: '/otomasyon',
    })

  const jobs = state.status === 'ok' ? state.data.jobs : []
  const now = Date.now()
  const running = jobs.filter(
    (j) => j.status === 'running' || j.status === 'cancelling',
  )
  const queued = jobs.filter((j) => j.status === 'queued')
  const finished = jobs.filter(
    (j) =>
      j.status === 'succeeded' ||
      j.status === 'failed' ||
      j.status === 'cancelled',
  )
  const succeededToday = finished.filter(
    (j) => j.status === 'succeeded' && isToday(j.finished_at),
  ).length
  const failedToday = finished.filter(
    (j) => j.status === 'failed' && isToday(j.finished_at),
  ).length

  return (
    <>
      <div className="screen-head">
        <h1>Otomasyon</h1>
        <span className="screen-sub">
          Hangi video ne durumda — sistem kendi devam eder
        </span>
      </div>

      {actionError && (
        <div className="action-error" role="alert">
          {actionError}
        </div>
      )}

      {state.status === 'loading' && <LoadingState label="İşler okunuyor…" />}
      {state.status === 'error' && (
        <ErrorState
          title="İşler alınamadı"
          message={`Arka uca ulaşılamadı: ${state.message}.`}
          onRetry={retry}
        />
      )}
      {state.status === 'ok' && (
        <>
          {state.stale && <StaleNote onRetry={retry} />}

          {/* Canlı sahne: sistemin ruh hali */}
          <div className="auto-hero">
            <div className="auto-hero-text">
              <h2>
                {running.length > 0
                  ? 'Sistem şimdi çalışıyor'
                  : queued.length > 0
                    ? 'Sıradaki video bekleniyor'
                    : 'Sistem boşta ve hazır'}
              </h2>
              <p>
                {running.length > 0
                  ? `Şu anda ${running.length} video üzerinde çalışılıyor, ${queued.length} video sırada bekliyor. İşlemler tamamlandıkça klipler kütüphaneye eklenecek.`
                  : queued.length > 0
                    ? `Kuyrukta ${queued.length} video sırasını bekliyor. Otomasyon motoru sıradaki videoyu işlemeye başlayacak.`
                    : 'Şu an yürütülen veya bekleyen bir işlem yok. Yetkili kaynaklara yeni video yüklendiğinde sistem otomatik olarak indirme ve işleme sürecini başlatır.'}
              </p>
            </div>
            <div className="auto-hero-pills">
              {running.length > 0 && (
                <span className="pill pill--run">
                  {running.length} sürüyor
                </span>
              )}
              {queued.length > 0 && (
                <span className="pill pill--idle">
                  {queued.length} sırada
                </span>
              )}
              {running.length === 0 && queued.length === 0 && (
                <span className="pill pill--ok">Hazır</span>
              )}
              {failedToday > 0 && (
                <span className="pill pill--error">
                  bugün {failedToday} başarısız
                </span>
              )}
            </div>
          </div>

          {/* Günün nabız kartları */}
          <div className="stat-grid" aria-label="Günün iş özeti">
            <div className="stat-card">
              <span>Bugün tamamlanan</span>
              <b className="nums">{succeededToday}</b>
              <small>iş başarıyla bitti</small>
            </div>
            <div className={`stat-card${failedToday > 0 ? ' warn' : ''}`}>
              <span>Bugün hatalı</span>
              <b className="nums">{failedToday}</b>
              <small>
                {failedToday > 0 ? 'yeniden denenebilir' : 'aksilik yok'}
              </small>
            </div>
            <div className="stat-card">
              <span>Şu an süren</span>
              <b className="nums">{running.length}</b>
              <small>motor elinde</small>
            </div>
            <div className="stat-card">
              <span>Kuyrukta bekleyen</span>
              <b className="nums">{queued.length}</b>
              <small>sıra numarasıyla</small>
            </div>
          </div>

          <section className="ink-panel" aria-label="Otomasyon işleri">
            <div className="panel-head-row">
              <h2>İş Akışı ve Süreç Durumu</h2>
              <div className="chip-row" role="group" aria-label="İş filtresi">
                <button
                  type="button"
                  className={`chip${filter === 'all' ? ' chip--on' : ''}`}
                  onClick={() => setFilter('all')}
                >
                  Tümü ({jobs.length})
                </button>
                <button
                  type="button"
                  className={`chip${filter === 'running' ? ' chip--on' : ''}`}
                  onClick={() => setFilter('running')}
                >
                  Sürüyor ({running.length})
                </button>
                <button
                  type="button"
                  className={`chip${filter === 'queued' ? ' chip--on' : ''}`}
                  onClick={() => setFilter('queued')}
                >
                  Sırada ({queued.length})
                </button>
                <button
                  type="button"
                  className={`chip${filter === 'failed' ? ' chip--on' : ''}`}
                  onClick={() => setFilter('failed')}
                >
                  Hatalar ({failedToday})
                </button>
              </div>
            </div>

            {jobs.length === 0 ? (
              <div className="flow-section" style={{ padding: '24px 18px' }}>
                <p className="plate-note">
                  Kuyruk boş — süren ya da bekleyen iş yok. Yetkili kaynak
                  eklendiğinde sistem taramayı kendisi başlatır; her video
                  burada ne olduğundan anlatılır.
                </p>
              </div>
            ) : (
              <>
                {(filter === 'all' || filter === 'running') && (
                  <div className="flow-section">
                    <h3>Şu an sürüyor</h3>
                    {running.length === 0 ? (
                      <p className="plate-note">Şu an süren iş yok.</p>
                    ) : (
                      running.map((job) => (
                        <JobRow
                          key={job.id}
                          job={job}
                          now={now}
                          position={null}
                          busy={busy === job.id}
                          onCancel={cancelWithNote}
                          onRetry={retryWithNote}
                        />
                      ))
                    )}
                  </div>
                )}

                {(filter === 'all' || filter === 'queued') && (
                  <div className="flow-section">
                    <h3>Sırada bekleyen</h3>
                    {queued.length === 0 ? (
                      <p className="plate-note">Bekleyen iş yok.</p>
                    ) : (
                      queued.map((job, index) => (
                        <JobRow
                          key={job.id}
                          job={job}
                          now={now}
                          position={index + 1}
                          busy={busy === job.id}
                          onCancel={cancelWithNote}
                          onRetry={retryWithNote}
                        />
                      ))
                    )}
                  </div>
                )}

                {(filter === 'all' || filter === 'failed') && (
                  <div className="flow-section">
                    <h3>Son bitenler</h3>
                    {finished.length === 0 ? (
                      <p className="plate-note">Henüz bitmiş iş yok.</p>
                    ) : (
                      (filter === 'failed' ? finished.filter((j) => j.status === 'failed') : finished).map((job) => (
                        <JobRow
                          key={job.id}
                          job={job}
                          now={now}
                          position={null}
                          busy={busy === job.id}
                          onCancel={cancelWithNote}
                          onRetry={retryWithNote}
                        />
                      ))
                    )}
                  </div>
                )}
              </>
            )}
            <p className="plate-note">
              İşler veritabanında kalıcıdır; uygulama yeniden başlasa da
              kaybolmaz. Çöken işler kalp atışı izlenip otomatik geri alınır.
            </p>
          </section>
        </>
      )}
    </>
  )
}
