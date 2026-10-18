import { ApiError, getJson, sendJson } from './client'

export type SettingSource = 'database' | 'environment' | 'unset'

export interface PlainSetting {
  value: string
  source: SettingSource
}

export interface SecretSetting {
  configured: boolean
  source: SettingSource
  hint: string
}

export interface IntSetting {
  value: number
  source: SettingSource
}

export interface SettingsView {
  google_client_id: PlainSetting
  google_client_secret: SecretSetting
  token_encryption_key: SecretSetting
  oauth_redirect_base: PlainSetting
  frontend_base_url: PlainSetting
  youtube_api_key: SecretSetting
  daily_quota_units: IntSetting
  metadata_system_prompt: PlainSetting
  cpu_target_percent: IntSetting
  ram_target_percent: IntSetting
  ffmpeg_threads: IntSetting
  max_heavy_jobs: IntSetting
  max_concurrent_jobs: IntSetting
  retry_max_attempts: IntSetting
  retry_backoff_seconds: IntSetting
  horizontal_stock_target_default: IntSetting
  shorts_per_video: IntSetting
  min_free_disk_gb: PlainSetting
  download_rate_limit_kbps: IntSetting
  planned_poll_interval_minutes: IntSetting
  transcription_method: PlainSetting
  whisper_model: PlainSetting
  whisper_language: PlainSetting
  media_root: PlainSetting
}

/** PUT gövdesi: verilen alanlar gönderilir; secret'lar boşsa dokunulmaz. */
export type SettingsPatch = Partial<{
  google_client_id: string
  google_client_secret: string
  token_encryption_key: string
  oauth_redirect_base: string
  frontend_base_url: string
  youtube_api_key: string
  daily_quota_units: number
  metadata_system_prompt: string
  cpu_target_percent: number
  ram_target_percent: number
  ffmpeg_threads: number
  max_heavy_jobs: number
  max_concurrent_jobs: number
  retry_max_attempts: number
  retry_backoff_seconds: number
  horizontal_stock_target_default: number
  shorts_per_video: number
  min_free_disk_gb: number
  download_rate_limit_kbps: number
  planned_poll_interval_minutes: number
  transcription_method: string
  whisper_model: string
  whisper_language: string
}>

export function fetchSettings(): Promise<SettingsView> {
  return getJson<SettingsView>('/api/settings')
}

export function updateSettings(patch: SettingsPatch): Promise<SettingsView> {
  // PUT her zaman güncel görünümle yanıt verir; boş gövde beklenmedik durum.
  return sendJson<SettingsView>('/api/settings', 'PUT', patch).then((view) => {
    if (view === null) {
      throw new ApiError(204, 'Ayar yanıtı boş döndü')
    }
    return view
  })
}

export const SOURCE_LABEL: Record<SettingSource, string> = {
  database: 'siteden ayarlı',
  environment: 'ortamdan',
  unset: 'ayarlanmadı',
}
