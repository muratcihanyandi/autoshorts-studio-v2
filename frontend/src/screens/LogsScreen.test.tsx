import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LogsScreen } from './LogsScreen'

const logsPayload = {
  entries: [
    {
      id: 12,
      ts: '2026-10-18T07:04:00Z',
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      event_type: 'media.download',
      category: 'media',
      detail: { source_video_id: 21, file_bytes: 5000 },
    },
    {
      id: 11,
      ts: '2026-10-18T07:03:00Z',
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      event_type: 'llm.provider_created',
      category: 'llm',
      detail: { name: 'p1' },
    },
  ],
  has_more: false,
  categories: ['media', 'llm'],
  channels: [{ id: 4, name: 'Kanal A', ribbon_color: '#123456' }],
}

const errorsPayload = {
  errors: [
    {
      kind: 'asset',
      id: 51,
      ts: '2026-10-23T07:49:14Z',
      what: 'Video işleme',
      error: 'Altyazı (transkript) aşaması hata verdi — TimeoutError: (ayrıntı yok)',
      attempts: null,
      max_attempts: null,
      retry_job_id: null,
      resume_video_id: 957,
      stage: 'transcript',
      title: 'RRaenee videosu',
      source_video_id: 957,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
    },
  ],
  total: 1,
}

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/api/logs/errors')
      ? errorsPayload
      : logsPayload
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('LogsScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists events with Turkish labels and details', async () => {
    stubFetch()
    render(<LogsScreen />)

    expect(
      await screen.findByRole('heading', { name: /Olay akışı/ }),
    ).toBeInTheDocument()
    expect(screen.getByText('Video indirildi')).toBeInTheDocument()
    expect(screen.getByText('LLM sağlayıcı eklendi')).toBeInTheDocument()
    // Detay tek satira iner.
    expect(screen.getByText(/source_video_id: 21/)).toBeInTheDocument()
    // Kategori filtre haplari.
    expect(screen.getByRole('button', { name: 'Medya' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'LLM' })).toBeInTheDocument()
    // Kanal secici acilir kutu.
    expect(screen.getByRole('combobox')).toBeInTheDocument()
    // has_more false: daha fazla butonu yok.
    expect(
      screen.queryByRole('button', { name: /Daha eski/ }),
    ).toBeNull()
  })

  it('shows the errors tab with the full error text and resume action', async () => {
    stubFetch()
    render(<LogsScreen />)

    await screen.findByRole('heading', { name: /Olay akışı/ })
    fireEvent.click(screen.getByRole('button', { name: 'Hatalar' }))

    expect(
      await screen.findByText(/TimeoutError: \(ayrıntı yok\)/),
    ).toBeInTheDocument()
    expect(screen.getByText('RRaenee videosu')).toBeInTheDocument()
    // Asama etiketi ve surdurme dugmesi.
    expect(screen.getByText('· Altyazı')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Kaldığı yerden sürdür' }),
    ).toBeInTheDocument()
  })
})
