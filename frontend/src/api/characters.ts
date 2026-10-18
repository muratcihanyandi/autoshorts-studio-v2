import { ApiError, getJson, sendJson } from './client'

export type SourcePlatform = 'youtube' | 'twitch' | 'kick'
export type SourcePermission = 'authorized' | 'pending' | 'rejected'

export interface CharacterOut {
  id: number
  name: string
  photo_configured: boolean
  reference_face: boolean
  system_prompt_set: boolean
  notes: string | null
  created_at: string
}

export interface CharactersResponse {
  characters: CharacterOut[]
  total: number
}

export interface CharacterCreateInput {
  name: string
  system_prompt?: string
  notes?: string
}

/** PATCH'te system_prompt: '' karakter promptunu temizler (genel prompta döner). */
export interface CharacterUpdateInput {
  name?: string
  system_prompt?: string
  notes?: string
}

export interface SourceOut {
  id: number
  channel_id: number
  /** Platform anahtarı: YouTube'da UC kimliği, Twitch/Kick'te kanal adresi. */
  youtube_channel_id: string
  platform: SourcePlatform
  title: string
  permission_status: SourcePermission
  authorized_at: string | null
  character_id: number | null
  character_name: string | null
  reaction_source: boolean
  trim_start_seconds: number
  trim_end_seconds: number
  filter_rules: SourceFilterRules
  created_at: string
  updated_at: string
}

export interface SourcesResponse {
  sources: SourceOut[]
  total: number
  authorized: number
}

export interface SourceCreateInput {
  youtube_channel_id: string
  platform: SourcePlatform
  title: string
  character_id?: number
  reaction_source?: boolean
  trim_start_seconds?: number
  trim_end_seconds?: number
  filter_rules?: SourceFilterRules
}

/** Kanal bazlı kaynak kuralları (JSONB). */
export interface SourceFilterRules {
  require_reaction_content?: boolean
  exclude_title_patterns?: string[]
  max_age_days?: number
}

export interface SourceUpdateInput {
  permission_status?: SourcePermission
  reaction_source?: boolean
  trim_start_seconds?: number
  trim_end_seconds?: number
  filter_rules?: SourceFilterRules
}

export interface DiscoverResult {
  sources_checked: number
  new_videos: number
  new_excluded: number
  quota_blocked: boolean
}

/** Twitch/Kick kaynaklarına elle eklenen VOD gövdesi. */
export interface SourceVideoInput {
  url: string
  title: string
}

export interface SourceVideoOut {
  id: number
  youtube_video_id: string
  title: string
  status: string
}

export const PLATFORM_LABEL: Record<SourcePlatform, string> = {
  youtube: 'YouTube',
  twitch: 'Twitch',
  kick: 'Kick',
}

export const PERMISSION_LABEL: Record<SourcePermission, string> = {
  authorized: 'yetkili',
  pending: 'bekliyor',
  rejected: 'reddedildi',
}

/** Karakter fotoğrafının tarayıcıda doğrudan kullanılabilir adresi. */
export function characterPhotoUrl(id: number): string {
  return `/api/characters/${id}/photo`
}

export function fetchCharacters(): Promise<CharactersResponse> {
  return getJson<CharactersResponse>('/api/characters')
}

export function createCharacter(
  input: CharacterCreateInput,
): Promise<CharacterOut> {
  return sendJson<CharacterOut>('/api/characters', 'POST', input).then((c) => {
    if (c === null) throw new Error('Boş yanıt')
    return c
  })
}

export function updateCharacter(
  id: number,
  patch: CharacterUpdateInput,
): Promise<CharacterOut> {
  return sendJson<CharacterOut>(`/api/characters/${id}`, 'PATCH', patch).then(
    (c) => {
      if (c === null) throw new Error('Boş yanıt')
      return c
    },
  )
}

export function deleteCharacter(id: number): Promise<null> {
  return sendJson<null>(`/api/characters/${id}`, 'DELETE')
}

/** Fotoğraf yükleme: multipart "file" alanı (sendJson JSON gövde gönderir). */
export async function uploadCharacterPhoto(
  id: number,
  file: File,
): Promise<CharacterOut> {
  const data = new FormData()
  data.append('file', file)
  const response = await fetch(`/api/characters/${id}/photo`, {
    method: 'POST',
    body: data,
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload && typeof payload.detail === 'string') {
        detail = payload.detail
      }
    } catch {
      // gövde JSON değilse HTTP kodu yeter
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as CharacterOut
}

export function fetchChannelSources(channelId: number): Promise<SourcesResponse> {
  return getJson<SourcesResponse>(`/api/channels/${channelId}/sources`)
}

export function createSource(
  channelId: number,
  input: SourceCreateInput,
): Promise<SourceOut> {
  return sendJson<SourceOut>(`/api/channels/${channelId}/sources`, 'POST', input).then(
    (s) => {
      if (s === null) throw new Error('Boş yanıt')
      return s
    },
  )
}

export function updateSource(
  sourceId: number,
  patch: SourceUpdateInput,
): Promise<SourceOut> {
  return sendJson<SourceOut>(`/api/sources/${sourceId}`, 'PATCH', patch).then(
    (s) => {
      if (s === null) throw new Error('Boş yanıt')
      return s
    },
  )
}

export function deleteSource(sourceId: number): Promise<null> {
  return sendJson<null>(`/api/sources/${sourceId}`, 'DELETE')
}

export function discoverChannel(channelId: number): Promise<DiscoverResult> {
  return sendJson<DiscoverResult>(`/api/channels/${channelId}/discover`, 'POST').then(
    (r) => {
      if (r === null) throw new Error('Boş yanıt')
      return r
    },
  )
}

export function addSourceVideo(
  sourceId: number,
  input: SourceVideoInput,
): Promise<SourceVideoOut> {
  return sendJson<SourceVideoOut>(`/api/sources/${sourceId}/videos`, 'POST', input).then(
    (v) => {
      if (v === null) throw new Error('Boş yanıt')
      return v
    },
  )
}

/** Manuel sınıflandırma düzeltmesi: 'planned' işleme geri alır,
 * 'excluded' işlenmemiş videoyu hariç tutar. */
export function setSourceVideoStatus(
  videoId: number,
  status: 'planned' | 'excluded',
): Promise<SourceVideoOut> {
  return sendJson<SourceVideoOut>(
    `/api/sources/videos/${videoId}/status`,
    'POST',
    { status },
  ).then((v) => {
    if (v === null) throw new Error('Boş yanıt')
    return v
  })
}
