import { useCallback, useState } from 'react'
import {
  cancelJob,
  fetchJobs,
  JOB_STATUS_LABEL,
  retryJob,
  type Job,
} from '../api/jobs'
import { usePolling } from '../hooks/usePolling'
import { formatDuration, formatTimeShort } from '../format'
import { jobAction } from '../jobNarrative'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

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

/** Tek işin anlatım satırı: durum, video, olup biten, kanal ve süre —
 * sade bir cümle okuyuşu; teknik ayrıntılar yalnız hata varsa girer. */
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
  return (
    <div className="flow-row">
      {position !== null && <span className="flow-pos nums">{position}.</span>}
      <span className={`pill pill--${statusTone(job.status)}`}>
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
    </div>
  )
}

export function AutomationScreen() {
  const fetcher = useCallback(() => fetchJobs(), [])
  const { state, retry } = usePolling(fetcher, 10000)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  const act = async (id: number, fn: (id: number) => Promise<Job>) => {
    setBusy(id)
    setActionError(null)
    try {
      await fn(id)
      retry()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'bilinmeyen hata')
    } finally {
      setBusy(null)
    }
  }

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
  const failedCount = finished.filter((j) => j.status === 'failed').length

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

          {/* Doğal Sistem Durumu Paneli */}
          <div className="auto-hero">
            <div className="auto-hero-text">
              <h2>
                {running.length > 0 ? (
                  <>🚀 Sistem Aktif Çalışıyor</>
                ) : queued.length > 0 ? (
                  <>⏳ İşlem Sırası Bekleniyor</>
                ) : (
                  <>☕ Sistem Boşta ve Hazır</>
                )}
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
              {failedCount > 0 && (
                <span className="pill pill--error">
                  {failedCount} başarısız
                </span>
              )}
            </div>
          </div>

          <section className="ink-panel" aria-label="Otomasyon işleri">
            <div className="panel-head-row">
              <h2>İş Akışı ve Süreç Durumu</h2>
              <span className="nums flow-soft">
                Toplam {jobs.length} kayıt
              </span>
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
                        onCancel={(j) => void act(j.id, cancelJob)}
                        onRetry={(j) => void act(j.id, retryJob)}
                      />
                    ))
                  )}
                </div>

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
                        onCancel={(j) => void act(j.id, cancelJob)}
                        onRetry={(j) => void act(j.id, retryJob)}
                      />
                    ))
                  )}
                </div>

                <div className="flow-section">
                  <h3>Son bitenler</h3>
                  {finished.length === 0 ? (
                    <p className="plate-note">Henüz bitmiş iş yok.</p>
                  ) : (
                    finished.map((job) => (
                      <JobRow
                        key={job.id}
                        job={job}
                        now={now}
                        position={null}
                        busy={busy === job.id}
                        onCancel={(j) => void act(j.id, cancelJob)}
                        onRetry={(j) => void act(j.id, retryJob)}
                      />
                    ))
                  )}
                </div>
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
