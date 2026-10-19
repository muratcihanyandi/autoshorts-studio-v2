import { getJson, sendJson } from './client'

export type JobStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface Job {
  id: number
  job_type: string
  payload: Record<string, unknown> | null
  status: JobStatus
  priority: number
  attempts: number
  max_attempts: number
  last_error: string | null
  worker_id: string | null
  heartbeat_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  /** Video/kanal bağlamı: otomasyon ekranının doğal cümleleri için
   * arka uçtan doldurulur; eşleşme yoksa null kalır. */
  title: string | null
  channel_name: string | null
  ribbon_color: string | null
  stage: string | null
}

export interface Jobs {
  jobs: Job[]
  total: number
}

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'sırada',
  running: 'sürüyor',
  cancelling: 'iptal ediliyor',
  succeeded: 'tamamlandı',
  failed: 'başarısız',
  cancelled: 'iptal edildi',
}

export const JOB_TYPE_LABEL: Record<string, string> = {
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

export function fetchJobs(): Promise<Jobs> {
  return getJson<Jobs>('/api/jobs?limit=30')
}

export function cancelJob(id: number): Promise<Job> {
  return sendJson<Job>(`/api/jobs/${id}/cancel`, 'POST').then((j) => {
    if (j === null) throw new Error('Boş yanıt')
    return j
  })
}

export function retryJob(id: number): Promise<Job> {
  return sendJson<Job>(`/api/jobs/${id}/retry`, 'POST').then((j) => {
    if (j === null) throw new Error('Boş yanıt')
    return j
  })
}
