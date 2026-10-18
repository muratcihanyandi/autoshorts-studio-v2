import { getJson } from './client'

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
