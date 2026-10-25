import { getJson, sendJson, ApiError } from './client'

/** YouTube kanal yönetimi (madde 5): kanalın videolarını listele,
 * analiz et ve siteden silinmiş olsa bile YouTube'ta kalanları temizle. */

export interface YoutubeChannelInfo {
  id: number
  name: string
  ribbon_color: string
  connected: boolean
}

export interface YoutubeStats {
  channel_title: string | null
  subscriber_count: number
  view_count: number
  video_count: number
}

export interface YoutubeVideo {
  youtube_video_id: string
  title: string
  published_at: string | null
  privacy_status: string
  view_count: number
  like_count: number
  comment_count: number
  thumbnail_url: string | null
  /** Stüdyo kayıtlarında var mı? false = siteden silinmiş ya da
   * elle yüklenmiş ("kayıt dışı") video. */
  managed: boolean
  render_id: number | null
  orientation: string | null
  public_at: string | null
  scheduled_at: string | null
}

export interface YoutubeQuota {
  used_today: number
  daily_limit: number
}

export interface YoutubeVideosResponse {
  channel: YoutubeChannelInfo
  youtube: YoutubeStats | null
  videos: YoutubeVideo[]
  quota: YoutubeQuota | null
}

export interface YoutubeAnalyticsResponse {
  channel: YoutubeChannelInfo
  youtube: YoutubeStats | null
  managed_totals: {
    video_count: number
    total_view_count: number
    total_like_count: number
    total_comment_count: number
  }
  top_videos: YoutubeVideo[]
  quota: YoutubeQuota | null
}

export interface YoutubeDeleteResponse {
  youtube_video_id: string
  deleted: boolean
  managed: boolean
  files_removed: number
}

export function fetchChannelVideos(
  channelId: number,
): Promise<YoutubeVideosResponse> {
  return getJson<YoutubeVideosResponse>(
    `/api/youtube/channels/${channelId}/videos`,
  )
}

export function fetchChannelAnalytics(
  channelId: number,
): Promise<YoutubeAnalyticsResponse> {
  return getJson<YoutubeAnalyticsResponse>(
    `/api/youtube/channels/${channelId}/analytics`,
  )
}

export function deleteYoutubeVideo(
  channelId: number,
  youtubeVideoId: string,
): Promise<YoutubeDeleteResponse> {
  return sendJson<YoutubeDeleteResponse>(
    `/api/youtube/channels/${channelId}/videos/${youtubeVideoId}`,
    'DELETE',
  ).then((body) => {
    if (body === null) {
      throw new ApiError(204, 'Silme yanıtı boş döndü')
    }
    return body
  })
}
