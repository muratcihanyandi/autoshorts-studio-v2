import { useCallback, useState } from 'react'
import {
  cancelJob,
  fetchJobs,
  JOB_STATUS_LABEL,
  JOB_TYPE_LABEL,
  retryJob,
  type Job,
} from '../api/jobs'
import { usePolling } from '../hooks/usePolling'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

function statusClass(status: Job['status']): string {
  if (status === 'succeeded') return 'tone-green'
  if (status === 'failed') return 'tone-red'
  if (status === 'running' || status === 'queued') return 'tone-amber'
  return ''
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

  return (
    <>
      <div className="screen-head">
        <h1>Otomasyon</h1>
        <span className="screen-sub">İş kuyruğu: kaynak izleme ve üretim hattı</span>
      </div>

      {actionError && (
        <div className="action-error" role="alert">
          {actionError}
        </div>
      )}

      {state.status === 'loading' && <LoadingState label="İş kuyruğu okunuyor…" />}
      {state.status === 'error' && (
        <ErrorState
          title="İş kuyruğu alınamadı"
          message={`Arka uca ulaşılamadı: ${state.message}.`}
          onRetry={retry}
        />
      )}
      {state.status === 'ok' && (
        <>
          {state.stale && <StaleNote onRetry={retry} />}
          <section className="plate">
            <h2 className="panel-title">İş Kuyruğu</h2>
            {state.data.jobs.length === 0 ? (
              <p className="plate-note">
                Kuyruk boş. Yetkili kaynak eklendiğinde sistem kaynak
                yoklaması işlerini otomatik oluşturur; her iş burada
                izlenebilir.
              </p>
            ) : (
              <table className="info-table">
                <tbody>
                  {state.data.jobs.map((job) => (
                    <tr key={job.id}>
                      <th>
                        {JOB_TYPE_LABEL[job.job_type] ?? job.job_type}
                        <span className="source-badge">
                          #{job.id}
                        </span>
                      </th>
                      <td>
                        <div className="llm-provider-info">
                          <span
                            className={`job-line ${statusClass(job.status)}`}
                            style={{ borderBottom: 'none', display: 'block' }}
                          >
                            <span>{JOB_STATUS_LABEL[job.status]}</span>
                            <span>
                              deneme {job.attempts}/{job.max_attempts}
                            </span>
                          </span>
                          {job.last_error && (
                            <span className="llm-meta save-error">
                              {job.last_error}
                            </span>
                          )}
                        </div>
                        <div className="channel-actions">
                          {(job.status === 'queued' || job.status === 'running') && (
                            <button
                              type="button"
                              className="btn--ghost"
                              disabled={busy === job.id}
                              onClick={() => void act(job.id, cancelJob)}
                            >
                              İptal
                            </button>
                          )}
                          {(job.status === 'failed' ||
                            job.status === 'cancelled') && (
                            <button
                              type="button"
                              className="btn--ghost"
                              disabled={busy === job.id}
                              onClick={() => void act(job.id, retryJob)}
                            >
                              Yeniden Dene
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
