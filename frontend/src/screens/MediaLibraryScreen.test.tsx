import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MediaLibraryScreen } from './MediaLibraryScreen'

const stages = [
  { key: 'download', label: 'İndirme', state: 'done' },
  { key: 'inspect', label: 'İnceleme', state: 'done' },
  { key: 'transcript', label: 'Altyazı', state: 'done' },
  { key: 'analysis', label: 'Analiz', state: 'done' },
  { key: 'candidates', label: 'Adaylar', state: 'done' },
  { key: 'selection', label: 'Klip seçimi', state: 'done' },
]

const libraryPayload = {
  sources: [
    {
      id: 1,
      title: 'Motorun seçtiği video',
      youtube_video_id: 'yt-1',
      youtube_url: 'https://www.youtube.com/watch?v=yt-1',
      source_channel_title: 'Kaynak Kanal',
      source_channel_youtube_id: 'UCsrc',
      reaction_source: false,
      filter_rules: { max_age_days: 7 },
      trim_start_seconds: 0,
      trim_end_seconds: 0,
      duration_seconds: 600,
      tag: '#done',
      asset_stage: 'candidates',
      asset_stage_label: null,
      asset_status: 'processed',
      file_bytes: 5000,
      origin: 'youtube',
      stages,
      selected_candidates: [
        {
          id: 11,
          start_seconds: 12,
          end_seconds: 48,
          duration_seconds: 36,
          score: 0.91,
          reason: 'yuksek enerji',
          hype_confidence: 0.87,
          hype_reason: 'reaksiyon tamamlanıyor',
          refined: true,
          render_id: 9,
          render_status: 'rendered',
        },
      ],
      selected_count: 1,
      full_cut_ready: false,
      is_current: true,
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      published_at: '2026-10-18T07:00:00Z',
      updated_at: '2026-10-18T07:00:00Z',
    },
  ],
  sources_total: 1,
  current_source_id: 1,
  clips: [
    {
      id: 9,
      title: 'Hazır klip',
      candidate_reason: 'yuksek enerji',
      orientation: 'vertical',
      status: 'rendered',
      file_bytes: 4096,
      duration_seconds: 36,
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      created_at: '2026-10-18T06:00:00Z',
      thumbnail_url: '/api/media/clips/9/thumbnail',
      stream_url: '/api/media/clips/9/stream',
      metadata_status: 'approved',
      published_status: 'verified',
      visibility: 'private',
      youtube_video_id: 'yt-pub-1',
      youtube_url: 'https://www.youtube.com/watch?v=yt-pub-1',
      source_video_id: 1,
      source_youtube_video_id: 'yt-1',
      source_channel_title: 'Kaynak Kanal',
      start_seconds: 12,
      end_seconds: 48,
      hype_confidence: 0.87,
    },
  ],
  clips_total: 1,
  summary: {
    sources_total: 1,
    entered: 1,
    queued_pool: 14,
    processed: 1,
    failed: 0,
    shorts_ready: 1,
    full_cuts_ready: 0,
  },
}

const detailPayload = {
  render: {
    id: 9,
    orientation: 'vertical',
    status: 'rendered',
    duration_seconds: 36,
    width: 1080,
    height: 1920,
    file_bytes: 4096,
    created_at: '2026-10-18T06:00:00Z',
    stream_url: '/api/media/clips/9/stream',
    thumbnail_url: '/api/media/clips/9/thumbnail',
    validation: { ok: true },
    webcam_confidence: 0.9,
    layout: {},
    last_error: null,
  },
  candidate: {
    id: 11,
    start_seconds: 12,
    end_seconds: 48,
    duration_seconds: 36,
    score: 0.91,
    reason: 'yuksek enerji',
    hype_confidence: 0.87,
    hype_reason: 'reaksiyon tamamlanıyor',
    refined: true,
  },
  source: {
    video_id: 1,
    title: 'Motorun seçtiği video',
    youtube_video_id: 'yt-1',
    youtube_url: 'https://www.youtube.com/watch?v=yt-1',
    channel_title: 'Kaynak Kanal',
    channel_youtube_id: 'UCsrc',
    published_at: '2026-10-18T07:00:00Z',
    duration_seconds: 600,
    reaction_source: false,
  },
  channel: { id: 4, name: 'Kanal A', ribbon_color: '#123456' },
  metadata: {
    revision: 1,
    versions: 1,
    status: 'approved',
    title: 'Hazır klip',
    description: 'Motorun seçtiği andan üretilen açıklama.',
    tags: ['shorts', 'reaksiyon'],
    hook: 'İlk üç saniyede ne oldu?',
    thumbnail_text: 'İZLE',
    content_warning: false,
    ai_disclosure: false,
    provider_name: 'test',
    created_at: '2026-10-18T06:10:00Z',
  },
  publishing: {
    upload_status: 'verified',
    visibility: 'private',
    youtube_video_id: 'yt-pub-1',
    youtube_url: 'https://www.youtube.com/watch?v=yt-pub-1',
    published_at: null,
    public_at: null,
    next_slot: '2026-10-19T15:00:00+00:00',
    timezone: 'Europe/Istanbul',
    publish_times: ['09:00', '14:00', '20:00'],
    automation_state: 'running',
    metadata_approved: true,
    auto_approve: false,
    daily_limit: 3,
    today_count: 1,
  },
  filters: { reaction_source: false, max_age_days: 7 },
  note: 'Gizli yüklendi; planlanan yayın diliminde herkese açılacak.',
}

function mockFetch() {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      const body = url.includes('/api/media/clips/9')
        ? detailPayload
        : libraryPayload
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    },
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('MediaLibraryScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows the current engine video, its stages and the source channel link', async () => {
    const fetchMock = mockFetch()
    render(<MediaLibraryScreen />)

    expect(
      await screen.findByRole('heading', { name: 'Şu an motorda' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Motorun seçtiği video')).toBeInTheDocument()
    const channelLink = screen.getByRole('link', { name: /Kaynak Kanal/ })
    expect(channelLink).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=yt-1',
    )
    for (const label of ['İndirme', 'İnceleme', 'Altyazı', 'Analiz', 'Adaylar', 'Klip seçimi']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    // Ürün görünümü yalnızca motorun seçtiği/hazır kayıtları ister.
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).includes('engine_selected_only=true'),
      ),
    ).toBe(true)
    expect(
      fetchMock.mock.calls.some((call) =>
        String(call[0]).includes('ready_only=true'),
      ),
    ).toBe(true)
    expect(
      screen.getByRole('button', { name: 'Hazır klip detayını aç' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Gizli · saat bekliyor')).toBeInTheDocument()
  })

  it('opens the clip detail with player, YouTube plan, metadata and filters', async () => {
    mockFetch()
    render(<MediaLibraryScreen />)

    fireEvent.click(
      await screen.findByRole('button', { name: 'Hazır klip detayını aç' }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()

    const player = dialog.querySelector('video')
    expect(player).toHaveAttribute('src', '/api/media/clips/9/stream')
    expect(screen.getByText('Motorun seçtiği andan üretilen açıklama.')).toBeInTheDocument()
    expect(screen.getByText('shorts')).toBeInTheDocument()
    expect(screen.getByText('reaksiyon')).toBeInTheDocument()
    expect(screen.getByText('Gizli yükleme')).toBeInTheDocument()
    expect(screen.getByText('Son 7 gün')).toBeInTheDocument()
    expect(
      within(dialog).getByRole('link', { name: /YouTube'da aç/ }),
    ).toHaveAttribute('href', 'https://www.youtube.com/watch?v=yt-pub-1')
  })

  it('shows a product empty state when the engine has not selected a clip', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              ...libraryPayload,
              sources: [],
              sources_total: 0,
              current_source_id: null,
              clips: [],
              clips_total: 0,
              summary: {
                ...libraryPayload.summary,
                sources_total: 0,
                entered: 0,
                processed: 0,
                shorts_ready: 0,
                full_cuts_ready: 0,
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )
    render(<MediaLibraryScreen />)

    expect(
      await screen.findByText('Motor henüz klip seçmedi'),
    ).toBeInTheDocument()
  })
})

  it('removes a source video through the card action', async () => {
    const fetchMock = mockFetch()
    render(<MediaLibraryScreen />)

    // İki adımlı onay: Kaldır -> Kalıcı olarak kaldır.
    fireEvent.click(await screen.findByRole('button', { name: 'Kaldır' }))
    fireEvent.click(
      screen.getByRole('button', { name: 'Kalıcı olarak kaldır' }),
    )

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        (c) =>
          String(c[0]).includes('/api/media/videos/1') &&
          c[1]?.method === 'DELETE',
      )
      expect(del).toBeDefined()
    })
    // Kaldırma sonrası liste yeniden çekilir.
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/media?'))
          .length,
      ).toBeGreaterThanOrEqual(2)
    })
  })
