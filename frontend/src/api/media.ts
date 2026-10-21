import { ApiError, getJson, sendJson } from './client'

/** Medya kütüphanesi: kaynak videolar, klipler, stok özeti. */

export type StageState = 'done' | 'active' | 'pending' | 'failed' | 'skipped'

export interface StageStep {
  key: string
  label: string
  state: StageState
  /** Aktif adımın canlı detayı (örn. indirme yüzdesi "%63"). */
  detail: string | null
}

export interface SelectedCandidate {
  id: number
  start_seconds: number
  end_seconds: number
  duration_seconds: number
  score: number
  reason: string | null
  hype_confidence: number | null
  hype_reason: string | null
  refined: boolean
  render_id: number | null
  render_status: string | null
}

export interface LibrarySource {
  id: number
  title: string
  platform: string
  youtube_video_id: string
  youtube_url: string | null
  source_channel_title: string | null
  source_channel_youtube_id: string | null
  reaction_source: boolean
  filter_rules: Record<string, unknown>
  trim_start_seconds: number
  trim_end_seconds: number
  duration_seconds: number | null
  tag: string
  asset_stage: string | null
  asset_stage_label: string | null
  asset_status: string | null
  file_bytes: number
  origin: string | null
  stages: StageStep[]
  selected_candidates: SelectedCandidate[]
  selected_count: number
  full_cut_ready: boolean
  is_current: boolean
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  published_at: string | null
  updated_at: string | null
}

export interface LibraryClip {
  id: number
  title: string
  candidate_reason: string | null
  orientation: 'vertical' | 'horizontal'
  status: string
  file_bytes: number
  duration_seconds: number
  channel_id: number | null
  channel_name: string | null
  ribbon_color: string | null
  created_at: string | null
  thumbnail_url: string | null
  stream_url: string | null
  metadata_status: string | null
  published_status: string
  visibility: string | null
  youtube_video_id: string | null
  youtube_url: string | null
  source_video_id: number | null
  source_youtube_video_id: string | null
  source_platform: string | null
  source_channel_title: string | null
  start_seconds: number | null
  end_seconds: number | null
  hype_confidence: number | null
}

export interface LibrarySummary {
  sources_total: number
  /** Sisteme girmiş video sayısı: indirilmiş, işlenmiş, onaylanmış
   * veya şu an işlenen (kesif havuzundaki bekleyenler hariç). */
  entered: number
  /** Hiç işleme girmemiş, keşif havuzunda bekleyen video sayısı. */
  queued_pool: number
  processed: number
  failed: number
  shorts_ready: number
  full_cuts_ready: number
}

export interface MediaLibrary {
  sources: LibrarySource[]
  sources_total: number
  current_source_id: number | null
  clips: LibraryClip[]
  clips_total: number
  summary: LibrarySummary
}

export interface ClipDetail {
  render: {
    id: number
    orientation: string
    status: string
    duration_seconds: number
    width: number
    height: number
    file_bytes: number
    created_at: string | null
    stream_url: string | null
    thumbnail_url: string | null
    validation: Record<string, unknown>
    webcam_confidence: number
    layout: Record<string, unknown>
    last_error: string | null
  }
  candidate: {
    id: number
    start_seconds: number
    end_seconds: number
    duration_seconds: number
    score: number
    reason: string | null
    hype_confidence: number | null
    hype_reason: string | null
    refined: boolean
  } | null
  source: {
    video_id: number
    title: string
    platform: string | null
    youtube_video_id: string
    youtube_url: string | null
    channel_title: string | null
    channel_youtube_id: string | null
    published_at: string | null
    duration_seconds: number | null
    reaction_source: boolean
  } | null
  channel: {
    id: number
    name: string
    ribbon_color: string
  } | null
  metadata: {
    revision: number
    versions: number
    status: string
    title: string
    description: string
    tags: string[]
    hook: string
    thumbnail_text: string
    content_warning: boolean
    ai_disclosure: boolean
    provider_name: string
    created_at: string | null
  } | null
  publishing: {
    upload_status: string
    visibility: string | null
    youtube_video_id: string | null
    youtube_url: string | null
    published_at: string | null
    public_at: string | null
    next_slot: string | null
    timezone: string
    publish_times: string[]
    automation_state: string
    metadata_approved: boolean
    auto_approve: boolean
    daily_limit: number
    today_count: number
  }
  filters: Record<string, unknown>
  note: string
}

export function fetchMedia(
  limit: number = 60,
  offset: number = 0,
  includeExcluded: boolean = false,
  activeOnly: boolean = true,
  engineSelectedOnly: boolean = false,
  readyOnly: boolean = false,
): Promise<MediaLibrary> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    active_only: String(activeOnly),
    engine_selected_only: String(engineSelectedOnly),
    ready_only: String(readyOnly),
  })
  if (includeExcluded) params.set('include_excluded', 'true')
  return getJson<MediaLibrary>(`/api/media?${params.toString()}`)
}

export function fetchClipDetail(renderId: number): Promise<ClipDetail> {
  return getJson<ClipDetail>(`/api/media/clips/${renderId}`)
}

/** Kaynak videoyu sistemden kaldır: dosyalar, satırlar ve bekleyen
 * işler temizlenir; video kütüphaneden Hariç olarak kaybolur. */
export interface VideoRemovalResult {
  source_video_id: number
  status: string
  files_removed: number
  jobs_cancelled: number
}

export function removeSourceVideo(
  sourceVideoId: number,
): Promise<VideoRemovalResult> {
  return sendJson<VideoRemovalResult>(
    `/api/media/videos/${sourceVideoId}`,
    'DELETE',
  ).then((body) => {
    if (body === null) {
      throw new ApiError(204, 'Kaldırma yanıtı boş döndü')
    }
    return body
  })
}

/** Hazır klibi kaldır: gizli yüklenmişse önce YouTube'dan silinir,
 * sonra yerel dosya ve kayıtlar; klip yeniden üretilmez. */
export interface ClipRemovalResult {
  render_id: number
  status: string
  youtube_deleted: string[]
  files_removed: number
  jobs_cancelled: number
  skipped?: boolean
}

export function removeClip(renderId: number): Promise<ClipRemovalResult> {
  return sendJson<ClipRemovalResult>(
    `/api/media/clips/${renderId}`,
    'DELETE',
  ).then((body) => {
    if (body === null) {
      throw new ApiError(204, 'Klip kaldırma yanıtı boş döndü')
    }
    return body
  })
}
