import { getJson } from './client'

/** Stüdyonun nabzı: iş sonuçları ve yayın/otomasyon olaylarının akışı. */

export type PulseTone = 'ok' | 'error' | 'run' | 'warn'

export interface PulseEvent {
  id: string
  kind: 'job_finished' | 'audit'
  event_type: string
  tone: PulseTone
  title: string | null
  channel_id: number | null
  channel_name: string | null
  detail: Record<string, unknown> | null
  created_at: string | null
}

export interface PulseFeed {
  events: PulseEvent[]
  now: string | null
}

export function fetchPulse(since?: string): Promise<PulseFeed> {
  const params = since ? `?since=${encodeURIComponent(since)}` : ''
  return getJson<PulseFeed>(`/api/pulse${params}`)
}
