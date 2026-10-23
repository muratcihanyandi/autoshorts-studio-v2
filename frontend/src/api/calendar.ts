import { ApiError, getJson, sendJson } from './client'

/** Takvim (Görev 1): planlanan ve gerçekleşen yayınlar. */

export type CalendarEntryStatus = 'scheduled' | 'planned' | 'published' | 'empty'

export interface CalendarMetadata {
  title: string
  description: string
  tags: string[]
  hook: string
  thumbnail_text: string
  status: string
  content_warning: boolean
  ai_disclosure: boolean
}

export interface CalendarEntry {
  id: number
  channel_id: number
  channel_name: string
  ribbon_color: string
  orientation: 'vertical' | 'horizontal' | null
  status: CalendarEntryStatus
  scheduled_at: string
  local_date: string
  title: string | null
  clip_render_id: number | null
  published_video_id: number | null
  thumbnail_url: string | null
  youtube_video_id: string | null
  youtube_url: string | null
  metadata: CalendarMetadata | null
  note: string
  /** Kullanıcının takvimden sürükleyip yerleştirdiği yayın. */
  manual: boolean
}

export interface CalendarChannel {
  id: number
  name: string
  ribbon_color: string
  timezone: string
  publish_times: string[]
  publish_times_vertical: string[]
  automation_state: string
  daily_vertical_limit: number
  daily_horizontal_limit: number
}

export interface CalendarData {
  year: number
  month: number
  month_label: string
  entries: CalendarEntry[]
  channels: CalendarChannel[]
  generated_at: string
}

export function fetchCalendar(year: number, month: number): Promise<CalendarData> {
  return getJson<CalendarData>(`/api/calendar?year=${year}&month=${month}`)
}

/** Elle planlama sonucu: hangi kayıt, hangi saate düştü. */
export interface RescheduleResult {
  published_video_id?: number
  clip_render_id?: number
  upload_job_id?: number
  scheduled_at: string | null
}

/** Takvimden sürüklenen videonun yayın saatini elle yerleştir.
 * Gizli yüklenmiş video (publishedVideoId) saati doğrudan alır; stoktaki
 * klip (clipRenderId) önce gizli yüklenir, saat yüklenince uygulanır. */
export function rescheduleCalendar(
  target: { publishedVideoId?: number; clipRenderId?: number },
  scheduledAt: string | null,
): Promise<RescheduleResult> {
  const body: Record<string, unknown> = {}
  if (target.publishedVideoId !== undefined) {
    body.published_video_id = target.publishedVideoId
  }
  if (target.clipRenderId !== undefined) {
    body.clip_render_id = target.clipRenderId
  }
  if (scheduledAt === null) {
    body.clear = true
  } else {
    body.scheduled_at = scheduledAt
  }
  return sendJson<RescheduleResult>(
    '/api/calendar/reschedule',
    'POST',
    body,
  ).then((result) => {
    if (result === null) {
      throw new ApiError(204, 'Planlama yanıtı boş döndü')
    }
    return result
  })
}
