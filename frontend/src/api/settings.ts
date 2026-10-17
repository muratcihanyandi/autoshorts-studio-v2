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
