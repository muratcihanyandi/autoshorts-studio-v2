import { getJson } from './client'

/** Canlı boru hattı görünümü: aktif işler, kuyruk ve son sonuçlar. */

export interface DownloadInfo {
  bytes: number
  expected_bytes: number | null
}

export interface ActiveJobCard {
  job_id: number
  job_type: string
  source_video_id: number | null
  title: string | null
  youtube_video_id?: string | null
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  stage: string | null
  stage_index: number | null
  stage_count: number
  elapsed_seconds: number | null
  attempts: number
  max_attempts: number
  eta_seconds: number | null
  average_seconds: number | null
  download: DownloadInfo | null
  last_error: string | null
}

export interface QueuedJobCard {
  job_id: number
  job_type: string
  title: string | null
  youtube_video_id?: string | null
  channel_name: string | null
  position: number
  attempts: number
  max_attempts: number
}

export interface RecentJobCard {
  job_id: number
  job_type: string
  title: string | null
  youtube_video_id?: string | null
  channel_name: string | null
  status: 'succeeded' | 'failed'
  duration_seconds: number | null
  error: string | null
  finished_at: string | null
}

/** Detay penceresinin kaynak satırı: yetkili kaynak kanal. */
export interface PipelineSource {
  id: number
  title: string
  platform: string
  channel_name: string | null
  ribbon_color: string | null
  videos: number
}

export interface PipelineView {
  active: ActiveJobCard[]
  queued: QueuedJobCard[]
  recent: RecentJobCard[]
  sources: PipelineSource[]
  now: string
}

export function fetchPipeline(): Promise<PipelineView> {
  return getJson<PipelineView>('/api/pipeline')
}
