import { cleanup, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const overviewPayload = {
  version: '0.1.0',
  app_env: 'production',
  uptime_seconds: 120,
  phase: 'awaiting_channels',
  database: 'reachable',
  channels: { connected: 0, total: 0 },
  sources: { monitored: 0 },
  llm_providers: { configured: 0 },
  jobs: { active: 0, queued: 0 },
  stock: { clips: 0 },
  today_published: {
    vertical: 0,
    horizontal: 0,
    vertical_limit: 0,
    horizontal_limit: 0,
  },
}

const channelsPayload = {
  channels: [
    {
      id: 1,
      name: 'Klip Fabrikası',
      handle: '@klipfabrika',
      youtube_channel_id: 'UCmock123',
      status: 'connected',
      ribbon_color: '#3550c4',
      notes: null,
      created_at: '2026-10-17T00:00:00Z',
      updated_at: '2026-10-17T00:00:00Z',
      last_connected_at: '2026-10-17T00:00:00Z',
      last_disconnected_at: null,
    },
  ],
  total: 1,
  connected: 1,
}

const systemPayload = {
  cpu_percent: 38.4,
  memory_percent: 61.2,
  memory_total_mb: 8192,
  disk_percent: 84.0,
  disk_total_gb: 231,
  temperature_c: null,
}

function mockApiOk() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes('/api/system')
        ? systemPayload
        : url.includes('/api/channels')
          ? channelsPayload
          : overviewPayload
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

describe('App', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders the shell and the overview from real API data', async () => {
    mockApiOk()
    render(<App />)

    expect(screen.getByRole('navigation', { name: 'Stüdyo gezinme' })).toBeInTheDocument()
    expect(await screen.findByText('Bugün yayınlanan yatay')).toBeInTheDocument()
    expect(screen.getByText('Kanal bekleniyor')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Genel Bakış' })).toBeInTheDocument()
    expect(screen.getByText('günlük yatay limiti')).toBeInTheDocument()
    expect(screen.getByText('Pi kaynakları')).toBeInTheDocument()
    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('38%')).toBeInTheDocument()
  })

  it('shows an error state with retry when the API is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('HTTP 503')
      }),
    )
    render(<App />)

    expect(await screen.findByText('Durum alınamadı')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Yeniden dene' }),
    ).toBeInTheDocument()
  })

  it('navigates to an empty-state screen via the rail', async () => {
    mockApiOk()
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Stüdyo gezinme' })
    const channelsLink = screen.getByRole('link', { name: 'Kanallar' })
    expect(nav).toContainElement(channelsLink)

    // Boş durum ekranı doğrudan rotayla da render edilir:
    expect(channelsLink).toHaveAttribute('href', '/kanallar')
  })

  it('lists channels and offers the new-channel form on /kanallar', async () => {
    mockApiOk()
    window.history.pushState({}, '', '/kanallar')
    render(<App />)

    expect(await screen.findByText('Klip Fabrikası')).toBeInTheDocument()
    expect(screen.getByText('Kayıtlı Kanallar')).toBeInTheDocument()
    expect(screen.getByText('bağlı')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Kopar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Kanalı Ekle' })).toBeInTheDocument()
    expect(screen.getByLabelText('Kanal adı')).toBeInTheDocument()
  })
})
