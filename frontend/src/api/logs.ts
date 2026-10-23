import { getJson, sendJson } from './client'

/** Günlükler: audit_events akışı, filtreli ve imleç sayfalamalı. */

export interface LogEntry {
  id: number
  ts: string | null
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  event_type: string
  category: string
  detail: Record<string, unknown> | null
}

export interface LogChannel {
  id: number
  name: string
  ribbon_color: string
}

export interface LogsPage {
  entries: LogEntry[]
  has_more: boolean
  categories: string[]
  channels: LogChannel[]
}

export interface LogsFilter {
  limit?: number
  before_id?: number
  channel_id?: number
  category?: string
}

export function fetchLogs(filter: LogsFilter = {}): Promise<LogsPage> {
  const params = new URLSearchParams()
  if (filter.limit !== undefined) params.set('limit', String(filter.limit))
  if (filter.before_id !== undefined)
    params.set('before_id', String(filter.before_id))
  if (filter.channel_id !== undefined)
    params.set('channel_id', String(filter.channel_id))
  if (filter.category !== undefined) params.set('category', filter.category)
  const query = params.toString()
  return getJson<LogsPage>(`/api/logs${query ? `?${query}` : ''}`)
}

/** Birleşik hata akışı: başarısız işler, medya varlıkları ve yükleme
 * satırları — tam hata metni ve düzeltme eylemiyle. */
export interface ErrorEntry {
  kind: 'job' | 'asset' | 'upload'
  id: number
  ts: string | null
  what: string
  error: string
  attempts: number | null
  max_attempts: number | null
  /** İş hatasıysa: /jobs/{id}/retry ile yeniden kuyruğa alınır. */
  retry_job_id: number | null
  /** Medya hatasıysa: video kaldığı aşamadan sürdürülür. */
  resume_video_id: number | null
  stage: string | null
  title: string | null
  source_video_id: number | null
  channel_name: string | null
  ribbon_color: string | null
}

export interface ErrorsPage {
  errors: ErrorEntry[]
  total: number
}

export function fetchLogErrors(limit: number = 60): Promise<ErrorsPage> {
  return getJson<ErrorsPage>(`/api/logs/errors?limit=${limit}`)
}

/** Başarısız işi taze deneme bütçeyle yeniden kuyruğa al. */
export function retryJob(jobId: number): Promise<unknown> {
  return sendJson<unknown>(`/api/jobs/${jobId}/retry`, 'POST')
}
