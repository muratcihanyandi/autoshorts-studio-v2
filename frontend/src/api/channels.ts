import { getJson, sendJson } from './client'

export type ChannelStatus = 'pending' | 'connected' | 'disconnected' | 'error'

export interface Channel {
  id: number
  name: string
  handle: string | null
  youtube_channel_id: string | null
  status: ChannelStatus
  ribbon_color: string
  notes: string | null
  created_at: string
  updated_at: string
  last_connected_at: string | null
  last_disconnected_at: string | null
}

export interface ChannelsResponse {
  channels: Channel[]
  total: number
  connected: number
}

export interface ChannelCreateInput {
  name: string
  handle?: string | null
  ribbon_color?: string
}

export interface OAuthStartResponse {
  authorization_url: string
}

export const RIBBON_COLORS = [
  { value: '#3550c4', label: 'Kobalt' },
  { value: '#c93a2e', label: 'Kızıl' },
  { value: '#d9a036', label: 'Hardal' },
  { value: '#2e7f6f', label: 'Çam' },
] as const

export const STATUS_LABEL: Record<ChannelStatus, string> = {
  pending: 'bağlantı bekliyor',
  connected: 'bağlı',
  disconnected: 'bağlantı kopmuş',
  error: 'hata',
}

export function fetchChannels(): Promise<ChannelsResponse> {
  return getJson<ChannelsResponse>('/api/channels')
}

export function createChannel(input: ChannelCreateInput): Promise<Channel> {
  return sendJson<Channel>('/api/channels', 'POST', input) as Promise<Channel>
}

export function disconnectChannel(id: number): Promise<Channel> {
  return sendJson<Channel>(
    `/api/channels/${id}/disconnect`,
    'POST',
  ) as Promise<Channel>
}

export function deleteChannel(id: number): Promise<null> {
  return sendJson<null>(`/api/channels/${id}`, 'DELETE') as Promise<null>
}

export function startOAuth(id: number): Promise<OAuthStartResponse> {
  return sendJson<OAuthStartResponse>(
    `/api/channels/${id}/oauth/start`,
    'POST',
  ) as Promise<OAuthStartResponse>
}
