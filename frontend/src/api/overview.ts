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

/** Bugün biten işlerin gün nabzı (madde 3). */
export interface TodayJobs {
  succeeded: number
  failed: number
}

/** Sıradaki yayın: elle planlanmış en yakın saat; plan yoksa
 * waiting_count ile otomatik slot bekleyen klip sayısı verilir. */
export interface NextPublish {
  scheduled_at: string | null
  title: string | null
  orientation: string | null
  channel_name: string | null
  waiting_count: number
}

export interface Overview {
  version: string
  app_env: string
  uptime_seconds: number | null
  phase: StudioPhase
  database: 'reachable' | 'not_configured' | 'unreachable'
  channel_id?: number | null
  channels: { connected: number; total?: number }
  sources: { monitored: number }
  llm_providers: { configured: number }
  jobs: { active: number; queued: number }
  stock: { clips: number }
  /** Üretim havuzu: işlenmeyi bekleyen (planned) video sayısı —
   * motor çalışıyor ama sıra boşsa "işlenecek video yok" uyarısı
   * bunu okur (2026-10-21 kalıcı çözüm). */
  production?: { planned_videos: number }
  today_published: TodayPublished
  today_jobs?: TodayJobs
  next_publish?: NextPublish | null
  channel_rows?: ChannelRow[]
  worker?: WorkerHealth
}

export function fetchOverview(channelId?: number): Promise<Overview> {
  const url = channelId != null ? `/api/overview?channel_id=${channelId}` : '/api/overview'
  return getJson<Overview>(url)
}
