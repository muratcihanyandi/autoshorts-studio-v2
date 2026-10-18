import { cleanup, render, screen } from '@testing-library/react'
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

describe('LogsScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists events with Turkish labels and details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(logsPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<LogsScreen />)

    expect(await screen.findByText('Olay akışı')).toBeInTheDocument()
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
})
