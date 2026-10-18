import { getJson, sendJson } from './client'

/** Kanal otomasyon durumu (kalıcı Start/Stop durum makinesi). */
export type AutomationState = 'stopped' | 'running' | 'paused' | 'error'

/** Motorun şu an gerçekten ne yaptığı (işlerden hesaplanır). */
export type EngineActivity =
  | 'idle'
  | 'discovering'
  | 'downloading'
  | 'transcribing'
  | 'analyzing'
  | 'rendering'
  | 'stock_ready'
  | 'stopped'

/** auto / on / off üç durumlu kanal ayarları. */
export type SettingMode = 'auto' | 'on' | 'off'

export const AUTOMATION_STATE_LABEL: Record<AutomationState, string> = {
  stopped: 'durdu',
  running: 'çalışıyor',
  paused: 'duraklatıldı',
  error: 'hata',
}

export const ACTIVITY_LABEL: Record<EngineActivity, string> = {
  idle: 'bekliyor',
  discovering: 'kaynak aranıyor',
  downloading: 'indiriliyor',
  transcribing: 'transkript çıkarılıyor',
  analyzing: 'hype noktaları analiz ediliyor',
  rendering: 'Shorts render ediliyor',
  stock_ready: 'stokta hazır',
  stopped: 'motor durdu',
}

export const MODE_LABEL: Record<SettingMode, string> = {
  auto: 'otomatik',
  on: 'açık',
  off: 'kapalı',
}

export interface ChannelRow {
  channel_id: number
  name: string
  handle: string | null
  status: string
  ribbon_color: string
  automation_state: AutomationState
  engine_activity: EngineActivity
  horizontal_stock: number
  horizontal_stock_target: number
  queued_horizontal: number
  shorts_ready: number
  full_cuts_ready: number
  last_error: string | null
  last_error_at: string | null
  last_success_at: string | null
}

export interface WorkerHealth {
  enabled: boolean
  running: boolean
  worker_id: string | null
  started_at: string | null
  last_tick_at: string | null
  jobs_processed: number
}

export interface FollowedCharacter {
  character_id: number
  name: string
  source_count: number
  followed_at: string | null
}

export interface ChannelSettings {
  channel_id: number
  automation_state: AutomationState
  horizontal_stock_target: number
  daily_vertical_limit: number
  daily_horizontal_limit: number
  title_mode: SettingMode
  description_mode: SettingMode
  tags_mode: SettingMode
  content_warning_mode: SettingMode
  ai_disclosure_mode: SettingMode
  channel_system_prompt: string | null
  characters: FollowedCharacter[]
}

export interface ChannelSettingsInput {
  horizontal_stock_target?: number
  daily_vertical_limit?: number
  daily_horizontal_limit?: number
  title_mode?: SettingMode
  description_mode?: SettingMode
  tags_mode?: SettingMode
  content_warning_mode?: SettingMode
  ai_disclosure_mode?: SettingMode
  channel_system_prompt?: string
  character_ids?: number[]
}

export interface AutomationActionResult {
  channel_id: number
  automation_state: AutomationState
  cancelled_jobs?: number | null
  refill?: { enqueued?: boolean; reason?: string } | null
}

export interface ChannelVideo {
  source_video_id: number
  title: string
  tag: string
  status: string
  platform: string | null
  duration_seconds: number | null
  file_bytes: number | null
  file_path: string | null
  error: string | null
}

export interface ChannelShort {
  rendered_clip_id: number
  tag: string
  status: string
  orientation: string
  clip_candidate_id: number | null
  source_video_id: number | null
  duration_seconds: number
  file_bytes: number
  width: number
  height: number
  error: string | null
}

/** Durum etiketinin pill tonu. */
export function tagTone(tag: string): 'ok' | 'run' | 'warn' | 'idle' | 'error' {
  if (tag === '#done' || tag === '#confirmed' || tag === '#shorts') return 'ok'
  if (tag === '#downloading' || tag === '#processing') return 'run'
  if (tag === '#queued') return 'idle'
  return 'error'
}

export function startAutomation(channelId: number): Promise<AutomationActionResult> {
  return sendJson<AutomationActionResult>(
    `/api/channels/${channelId}/automation/start`,
    'POST',
  ).then((r) => {
    if (r === null) throw new Error('Boş yanıt')
    return r
  })
}

export function stopAutomation(channelId: number): Promise<AutomationActionResult> {
  return sendJson<AutomationActionResult>(
    `/api/channels/${channelId}/automation/stop`,
    'POST',
  ).then((r) => {
    if (r === null) throw new Error('Boş yanıt')
    return r
  })
}

export function pauseAutomation(channelId: number): Promise<AutomationActionResult> {
  return sendJson<AutomationActionResult>(
    `/api/channels/${channelId}/automation/pause`,
    'POST',
  ).then((r) => {
    if (r === null) throw new Error('Boş yanıt')
    return r
  })
}

export function fetchChannelSettings(channelId: number): Promise<ChannelSettings> {
  return getJson<ChannelSettings>(`/api/channels/${channelId}/automation`)
}

export function updateChannelSettings(
  channelId: number,
  input: ChannelSettingsInput,
): Promise<ChannelSettings> {
  return sendJson<ChannelSettings>(`/api/channels/${channelId}/automation`, 'PUT', input).then(
    (s) => {
      if (s === null) throw new Error('Boş yanıt')
      return s
    },
  )
}

export function fetchChannelVideos(
  channelId: number,
): Promise<{ videos: ChannelVideo[]; total: number }> {
  return getJson<{ videos: ChannelVideo[]; total: number }>(
    `/api/channels/${channelId}/horizontal`,
  )
}

export function fetchChannelShorts(
  channelId: number,
): Promise<{ shorts: ChannelShort[]; total: number }> {
  return getJson<{ shorts: ChannelShort[]; total: number }>(
    `/api/channels/${channelId}/shorts`,
  )
}
