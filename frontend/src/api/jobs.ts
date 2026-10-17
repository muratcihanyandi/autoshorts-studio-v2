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
}

export interface Jobs {
  jobs: Job[]
  total: number
}

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'kuyrukta',
  running: 'çalışıyor',
  cancelling: 'iptal ediliyor',
  succeeded: 'başarılı',
  failed: 'başarısız',
  cancelled: 'iptal',
}

export const JOB_TYPE_LABEL: Record<string, string> = {
  source_discover: 'Kaynak yoklaması',
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
