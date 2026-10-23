import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CalendarScreen } from './CalendarScreen'

/** Izgara UTC tarih dizgisiyle eşleşir; bugünün UTC tarihi kullanılır. */
const today = new Date().toISOString().slice(0, 10)

function entry(overrides: Record<string, unknown>) {
  return {
    id: 1,
    channel_id: 4,
    channel_name: 'Kanal A',
    ribbon_color: '#123456',
    orientation: 'vertical',
    status: 'planned',
    scheduled_at: `${today}T06:00:00Z`,
    local_date: today,
    title: 'Klip',
    clip_render_id: null,
    published_video_id: null,
    thumbnail_url: null,
    youtube_video_id: null,
    youtube_url: null,
    metadata: null,
    note: 'Stokta hazır; onay/yükleme sonrası bu dilime düşer.',
    manual: false,
    ...overrides,
  }
}

const calendarPayload = {
  year: new Date().getUTCFullYear(),
  month: new Date().getUTCMonth() + 1,
  month_label: 'Bu Ay',
  entries: [
    entry({
      id: 1,
      status: 'scheduled',
      title: 'Saat Bekleyen Klip',
      clip_render_id: 9,
      published_video_id: 101,
      youtube_video_id: 'yt-sch',
      youtube_url: 'https://www.youtube.com/watch?v=yt-sch',
      metadata: {
        title: 'Saat Bekleyen Klip',
        description: 'Gizli yüklendi.',
        tags: ['plan'],
        hook: '',
        thumbnail_text: '',
        status: 'approved',
        content_warning: false,
        ai_disclosure: false,
      },
      note: 'Gizli yüklendi; plan saatinde herkese açılacak.',
    }),
    entry({
      id: 2,
      status: 'planned',
      title: 'Stok Klipi',
      metadata: {
        title: 'Stok Klipi',
        description: 'Stoktaki hazır klip açıklaması.',
        tags: ['shorts', 'stok'],
        hook: 'İlk üç saniyede ne oldu?',
        thumbnail_text: 'İZLE',
        status: 'draft',
        content_warning: false,
        ai_disclosure: false,
      },
    }),
    entry({
      id: 3,
      orientation: 'horizontal',
      status: 'published',
      title: 'Yayınlanan Klip',
      youtube_video_id: 'yt-pub',
      youtube_url: 'https://www.youtube.com/watch?v=yt-pub',
      metadata: {
        title: 'Yayınlanan Klip',
        description: 'Yayına verildi.',
        tags: ['yayin'],
        hook: '',
        thumbnail_text: '',
        status: 'approved',
        content_warning: false,
        ai_disclosure: false,
      },
      note: 'Yayına verildi.',
    }),
    entry({
      id: 4,
      orientation: null,
      status: 'empty',
      title: null,
      note: 'Bu dilim için hazır video yok',
    }),
  ],
  channels: [
    {
      id: 4,
      name: 'Kanal A',
      ribbon_color: '#123456',
      timezone: 'Europe/Istanbul',
      publish_times: ['09:00', '14:00', '20:00'],
      publish_times_vertical: ['12:00', '17:00', '21:00'],
      automation_state: 'running',
      daily_vertical_limit: 3,
      daily_horizontal_limit: 1,
    },
  ],
  generated_at: '2026-10-19T08:00:00Z',
}

function stubFetch() {
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return new Response(JSON.stringify(calendarPayload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    },
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('CalendarScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })
  afterEach(() => cleanup())

  it('renders the month grid with status chips, legend and channel hours', async () => {
    stubFetch()
    render(<CalendarScreen />)

    expect(await screen.findByText('Stok Klipi')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Takvim' })).toBeInTheDocument()
    // Durum rozetleri: saat bekleyen, stoktaki, yayındaki ve boş dilim.
    expect(screen.getByText('Saat Bekleyen Klip')).toBeInTheDocument()
    expect(screen.getByText('Yayınlanan Klip')).toBeInTheDocument()
    expect(screen.getByText('Bu dilim için hazır video yok')).toBeInTheDocument()
    expect(screen.getByText('Saat bekliyor')).toBeInTheDocument()
    expect(screen.getByText('Stokta')).toBeInTheDocument()
    expect(screen.getByText('Yayında')).toBeInTheDocument()
    // Gösterge sayıları ve kanal yayın saatleri tablosu.
    expect(screen.getByText('1 saat bekliyor')).toBeInTheDocument()
    expect(screen.getByText('1 stokta')).toBeInTheDocument()
    expect(screen.getByText('1 yayında')).toBeInTheDocument()
    expect(screen.getByText('1 boş dilim')).toBeInTheDocument()
    expect(screen.getByText('Kanal A')).toBeInTheDocument()
    expect(screen.getByText(/09:00 · 14:00 · 20:00/)).toBeInTheDocument()
    expect(screen.getByText('(Europe/Istanbul)')).toBeInTheDocument()
    expect(screen.getByText('Bu Ay')).toBeInTheDocument()
  })

  it('opens the planned entry detail with metadata on click', async () => {
    stubFetch()
    render(<CalendarScreen />)

    fireEvent.click(
      await screen.findByRole('button', { name: /Stok Klipi/ }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', { name: 'Stok Klipi' }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText(/Kanal A · Dikey/)).toBeInTheDocument()
    expect(
      within(dialog).getByText('Stoktaki hazır klip açıklaması.'),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('İlk üç saniyede ne oldu?')).toBeInTheDocument()
    expect(within(dialog).getByText('shorts')).toBeInTheDocument()
    expect(within(dialog).getByText('stok')).toBeInTheDocument()
    // Yüklenmemiş kayıtta YouTube bağlantısı yoktur.
    expect(
      within(dialog).queryByRole('link', { name: /YouTube'da aç/ }),
    ).not.toBeInTheDocument()
  })

  it('opens the published entry with its YouTube link', async () => {
    stubFetch()
    render(<CalendarScreen />)

    fireEvent.click(
      await screen.findByRole('button', { name: /Yayınlanan Klip/ }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('link', { name: /YouTube'da aç/ }),
    ).toHaveAttribute('href', 'https://www.youtube.com/watch?v=yt-pub')
  })

  it('navigates months and refetches the calendar', async () => {
    const fetchMock = stubFetch()
    render(<CalendarScreen />)

    await screen.findByText('Stok Klipi')
    fireEvent.click(screen.getByRole('button', { name: 'Sonraki ›' }))

    const now = new Date()
    const next = new Date(now.getFullYear(), now.getMonth() + 1, 1)
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some((call) =>
          String(call[0]).includes(
            `year=${next.getFullYear()}&month=${next.getMonth() + 1}`,
          ),
        ),
      ).toBe(true)
    })
  })

  it('schedules a video by dragging it onto a day cell', async () => {
    const fetchMock = stubFetch()
    render(<CalendarScreen />)

    // Suruklenebilir kayit: saat bekleyen (gizli yuklu) klip.
    const chip = await screen.findByRole('button', {
      name: /Saat Bekleyen Klip/,
    })
    fireEvent.dragStart(chip, {
      dataTransfer: { setData: vi.fn(), effectAllowed: 'move' },
    })
    const cell = screen.getByRole('gridcell', { name: today })
    fireEvent.dragOver(cell, { dataTransfer: {} })
    fireEvent.drop(cell, { dataTransfer: {} })

    // Saat secici acilir; kaydin mevcut saati varsayilan.
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', { name: 'Saat Bekleyen Klip' }),
    ).toBeInTheDocument()
    const timeInput = within(dialog).getByLabelText('Saat') as HTMLInputElement
    fireEvent.change(timeInput, { target: { value: '21:30' } })
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Bu saate planla' }),
    )

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes('/api/calendar/reschedule'),
      )
      expect(call).toBeDefined()
      const init = call?.[1] as RequestInit
      expect(init.method).toBe('POST')
      const body = JSON.parse(String(init.body)) as {
        published_video_id?: number
        scheduled_at?: string
      }
      expect(body.published_video_id).toBe(101)
      // Secilen yerel saat ISO'ya cevrilmis olarak gider.
      expect(body.scheduled_at).toBe(
        new Date(`${today}T21:30:00`).toISOString(),
      )
    })
  })
})
