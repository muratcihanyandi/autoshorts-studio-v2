import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MediaLibraryScreen } from './MediaLibraryScreen'

const libraryPayload = {
  sources: [
    {
      id: 1,
      title: 'Islenmis video',
      youtube_video_id: 'yt-1',
      duration_seconds: 600,
      tag: '#done',
      asset_stage: 'candidates',
      asset_stage_label: null,
      asset_status: 'processed',
      file_bytes: 5000,
      origin: 'youtube',
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      published_at: null,
      updated_at: '2026-10-18T07:00:00Z',
    },
    {
      id: 2,
      title: 'Indirilen video',
      youtube_video_id: 'yt-2',
      duration_seconds: 900,
      tag: '#downloading',
      asset_stage: 'download',
      asset_stage_label: 'indiriliyor',
      asset_status: 'downloading',
      file_bytes: 0,
      origin: 'youtube',
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      published_at: null,
      updated_at: '2026-10-18T07:05:00Z',
    },
  ],
  sources_total: 2,
  clips: [
    {
      id: 9,
      title: 'Islenmis video',
      candidate_reason: 'yuksek enerji',
      orientation: 'vertical',
      status: 'rendered',
      file_bytes: 4096,
      duration_seconds: 45.5,
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      created_at: '2026-10-18T06:00:00Z',
    },
  ],
  clips_total: 1,
  summary: {
    sources_total: 2,
    processed: 1,
    failed: 0,
    shorts_ready: 1,
    full_cuts_ready: 0,
  },
}

describe('MediaLibraryScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists sources with status pills and the clip table', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(libraryPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<MediaLibraryScreen />)

    expect(await screen.findByText('Kaynak videolar')).toBeInTheDocument()
    // Ayni baslik kaynak ve klip tablolarinda da gecer: iki satir beklenir.
    expect(screen.getAllByText('Islenmis video').length).toBe(2)
    expect(screen.getAllByText('Indirilen video').length).toBe(1)
    // Filtre etiketleri durum etiketleriyle ayni sozcukte: ikişer kez.
    expect(screen.getAllByText('İndiriliyor').length).toBe(2)
    expect(screen.getAllByText('Stokta').length).toBe(2)
    // Islenmemis satirda 'Hariç tut' eylemi var.
    expect(screen.getByRole('button', { name: 'Hariç tut' })).toBeInTheDocument()
    expect(screen.getByText('Klipler')).toBeInTheDocument()
    expect(screen.getByText('Dikey')).toBeInTheDocument()
    expect(screen.getByText('Hazır')).toBeInTheDocument()
    // Ozet stat kartlari.
    expect(screen.getByText('Shorts stoğu')).toBeInTheDocument()
  })

  it('filters sources by tag', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(libraryPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<MediaLibraryScreen />)

    await screen.findByText('Indirilen video')
    fireEvent.click(screen.getByRole('button', { name: 'Hata' }))
    expect(screen.getByText(/Bu durumda video yok/)).toBeInTheDocument()
    // Kaynak satiri kalkar; klip tablosundaki ayni baslik kalir.
    expect(screen.getAllByText('Islenmis video').length).toBe(1)
  })

  it('shows excluded records only under the Hariç filter', async () => {
    const excludedPayload = {
      ...libraryPayload,
      sources: [
        {
          ...libraryPayload.sources[0],
          id: 3,
          title: 'Hariç tutulmuş video',
          tag: '#excluded',
          asset_stage: null,
          asset_stage_label: null,
          asset_status: null,
        },
      ],
      sources_total: 1,
      summary: { ...libraryPayload.summary, sources_total: 1 },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      new Response(
        JSON.stringify(
          String(input).includes('include_excluded=true')
            ? excludedPayload
            : libraryPayload,
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<MediaLibraryScreen />)

    // Varsayılan liste hariç kayıtları taşımaz.
    await screen.findByText('Indirilen video')
    expect(
      screen.queryByText('Hariç tutulmuş video'),
    ).not.toBeInTheDocument()

    // 'Hariç' filtresi istekleri include_excluded=true ile yeniler.
    fireEvent.click(screen.getByRole('button', { name: 'Hariç' }))
    expect(
      await screen.findByText('Hariç tutulmuş video'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'İşleme al' })).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some((c) =>
        String(c[0]).includes('include_excluded=true'),
      ),
    ).toBe(true)
  })

  it('shows the empty library state when no sources exist', async () => {
    const empty = {
      ...libraryPayload,
      sources: [],
      sources_total: 0,
      clips: [],
      clips_total: 0,
      summary: {
        sources_total: 0,
        processed: 0,
        failed: 0,
        shorts_ready: 0,
        full_cuts_ready: 0,
      },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(empty), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<MediaLibraryScreen />)

    expect(await screen.findByText('Kütüphane boş')).toBeInTheDocument()
  })
})
