import { getJson } from './client'
import type { ChannelRow, WorkerHealth } from './automation'

export type StudioPhase = 'setup' | 'awaiting_channels' | 'running'

/** Bugün herkese açık yapılan videolar + günlük limitler (kanalların
 * limitleri toplamı; 0 = limitsiz). */
export interface TodayPublished {
  vertical: number
  horizontal: number
  vertical_limit: number
  horizontal_limit: number
}

export interface Overview {
  version: string
  app_env: string
  uptime_seconds: number | null
  phase: StudioPhase
  database: 'reachable' | 'not_configured' | 'unreachable'
  channels: { connected: number; total?: number }
  sources: { monitored: number }
  llm_providers: { configured: number }
  jobs: { active: number; queued: number }
  stock: { clips: number }
  today_published: TodayPublished
  channel_rows?: ChannelRow[]
  worker?: WorkerHealth
}

export function fetchOverview(): Promise<Overview> {
  return getJson<Overview>('/api/overview')
}
