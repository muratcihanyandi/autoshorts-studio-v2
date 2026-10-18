import { getJson } from './client'

/** Medya kütüphanesi: kaynak videolar, klipler, stok özeti. */

export interface LibrarySource {
  id: number
  title: string
  youtube_video_id: string
  duration_seconds: number | null
  tag: string
  asset_stage: string | null
  asset_stage_label: string | null
  asset_status: string | null
  file_bytes: number
  origin: string | null
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  published_at: string | null
  updated_at: string | null
}

export interface LibraryClip {
  id: number
  title: string | null
  candidate_reason: string | null
  orientation: 'vertical' | 'horizontal'
  status: string
  file_bytes: number
  duration_seconds: number
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  created_at: string | null
}

export interface LibrarySummary {
  sources_total: number
  processed: number
  failed: number
  shorts_ready: number
  full_cuts_ready: number
}

export interface MediaLibrary {
  sources: LibrarySource[]
  sources_total: number
  clips: LibraryClip[]
  clips_total: number
  summary: LibrarySummary
}

export function fetchMedia(
  limit: number = 60,
  offset: number = 0,
): Promise<MediaLibrary> {
  return getJson<MediaLibrary>(`/api/media?limit=${limit}&offset=${offset}`)
}
