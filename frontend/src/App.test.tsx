import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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

const authPayload = {
  configured: true,
  authenticated: true,
  username: 'admin',
  signup_open: false,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApiOk() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes('/api/auth/status')
        ? authPayload
        : url.includes('/api/system')
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

    expect(
      await screen.findByRole('navigation', { name: 'Stüdyo gezinme' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Bugün yayınlanan yatay')).toBeInTheDocument()
    expect(screen.getByText('Kanal bekleniyor')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Genel Bakış' })).toBeInTheDocument()
    expect(screen.getByText('günlük yatay limiti')).toBeInTheDocument()
    expect(screen.getByText('Pi kaynakları')).toBeInTheDocument()
    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('38%')).toBeInTheDocument()
  })

  it('falls back to the login screen when the API is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('HTTP 503')
      }),
    )
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Giriş yap' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Kullanıcı adı')).toBeInTheDocument()
  })

  it('shows the signup screen when no account is configured', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          configured: false,
          authenticated: false,
          username: null,
          signup_open: true,
        }),
      ),
    )
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Hesap oluştur' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Kayıt ol' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByLabelText('Şifre (tekrar)')).toBeInTheDocument()
  })

  it('creates the first account and then shows the studio shell', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/auth/status')) {
          return jsonResponse({
            configured: false,
            authenticated: false,
            username: null,
            signup_open: true,
          })
        }
        if (url.includes('/api/auth/signup')) {
          return jsonResponse(authPayload, 201)
        }
        const body = url.includes('/api/system')
          ? systemPayload
          : url.includes('/api/channels')
            ? channelsPayload
            : overviewPayload
        return jsonResponse(body)
      }),
    )
    render(<App />)

    fireEvent.change(await screen.findByLabelText('Kullanıcı adı'), {
      target: { value: 'admin' },
    })
    fireEvent.change(screen.getByLabelText('Şifre'), {
      target: { value: 'gizli-sifre' },
    })
    fireEvent.change(screen.getByLabelText('Şifre (tekrar)'), {
      target: { value: 'gizli-sifre' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Hesap oluştur' }))

    expect(
      await screen.findByRole('navigation', { name: 'Stüdyo gezinme' }),
    ).toBeInTheDocument()
  })

  it('logs in and then shows the studio shell', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/auth/status')) {
        return new Response(
          JSON.stringify({
            configured: true,
            authenticated: false,
            username: null,
            signup_open: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/api/auth/login')) {
        return new Response(JSON.stringify(authPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      const body = url.includes('/api/system')
        ? systemPayload
        : url.includes('/api/channels')
          ? channelsPayload
          : overviewPayload
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    fireEvent.change(await screen.findByLabelText('Kullanıcı adı'), {
      target: { value: 'admin' },
    })
    fireEvent.change(screen.getByLabelText('Şifre'), {
      target: { value: 'gizli-sifre' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Giriş yap' }))

    expect(
      await screen.findByRole('navigation', { name: 'Stüdyo gezinme' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Çıkış' })).toBeInTheDocument()
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

  it('shows the mobile shell (drawer + bottom tabs) on narrow screens', async () => {
    mockApiOk()
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: query.includes('max-width'),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    )
    const { container } = render(<App />)

    // Mobil kabuk: üst çubuk + alt sekmeler; masaüstü rayı render edilmez.
    expect(
      await screen.findByRole('button', { name: 'Menüyü aç' }),
    ).toBeInTheDocument()
    const tabs = screen.getByRole('navigation', {
      name: 'Stüdyo kısayolları',
    })
    expect(tabs).toHaveTextContent('Genel')
    expect(tabs).toHaveTextContent('Kanallar')
    expect(tabs).toHaveTextContent('Medya')
    expect(tabs).toHaveTextContent('Takvim')
    expect(tabs).toHaveTextContent('Otomasyon')
    expect(container.querySelector('.rail')).toBeNull()
    expect(container.querySelector('.mobile-drawer')).not.toBeNull()

    // Çekmece: hamburger açar, tüm hedefler + yönetim bölümü listelenir,
    // bir hedefe tıklayınca kapanır.
    fireEvent.click(screen.getByRole('button', { name: 'Menüyü aç' }))
    const drawer = screen.getByRole('complementary', {
      name: 'Stüdyo menüsü',
    })
    expect(drawer).toHaveClass('open')
    expect(drawer).toHaveTextContent('Yönetim')
    expect(drawer).toHaveTextContent('Ayarlar')
    const settingsLink = screen.getByRole('link', { name: 'Ayarlar' })
    expect(settingsLink).toHaveAttribute('href', '/ayarlar')
    fireEvent.click(settingsLink)
    expect(drawer).not.toHaveClass('open')
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
