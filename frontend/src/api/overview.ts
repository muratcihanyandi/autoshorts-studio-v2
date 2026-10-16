import { getJson } from './client'

export type StudioPhase = 'setup' | 'awaiting_channels' | 'running'

export interface Overview {
  version: string
  app_env: string
  uptime_seconds: number | null
  phase: StudioPhase
  database: 'reachable' | 'not_configured' | 'unreachable'
  channels: { connected: number }
  sources: { monitored: number }
  llm_providers: { configured: number }
  jobs: { active: number; queued: number }
  stock: { clips: number }
  today_published: number
}

export function fetchOverview(): Promise<Overview> {
  return getJson<Overview>('/api/overview')
}
