import { getJson } from './client'

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
  thumbnail_url: string | null
  youtube_video_id: string | null
  youtube_url: string | null
  metadata: CalendarMetadata | null
  note: string
}

export interface CalendarChannel {
  id: number
  name: string
  ribbon_color: string
  timezone: string
  publish_times: string[]
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
