import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsScreen } from './SettingsScreen'

const settingsPayload = {
  google_client_id: { value: 'test.apps.googleusercontent.com', source: 'database' },
  google_client_secret: { configured: true, source: 'environment', hint: 'abcd' },
  token_encryption_key: { configured: false, source: 'unset', hint: '' },
  oauth_redirect_base: { value: '', source: 'unset' },
  frontend_base_url: { value: 'http://ui-test:1478', source: 'environment' },
  youtube_api_key: { configured: true, source: 'database', hint: '9876' },
  daily_quota_units: { value: 10000, source: 'environment' },
  metadata_system_prompt: { value: '', source: 'unset' },
  cpu_target_percent: { value: 0, source: 'environment' },
  ram_target_percent: { value: 0, source: 'environment' },
  ffmpeg_threads: { value: 0, source: 'environment' },
  max_heavy_jobs: { value: 1, source: 'environment' },
  max_concurrent_jobs: { value: 2, source: 'environment' },
  retry_max_attempts: { value: 3, source: 'environment' },
  retry_backoff_seconds: { value: 60, source: 'environment' },
  horizontal_stock_target_default: { value: 3, source: 'environment' },
  shorts_per_video: { value: 3, source: 'environment' },
  min_free_disk_gb: { value: '2.0', source: 'environment' },
  download_rate_limit_kbps: { value: 0, source: 'environment' },
  planned_poll_interval_minutes: { value: 5, source: 'environment' },
  transcription_method: { value: 'sidecar', source: 'environment' },
  whisper_model: { value: 'tiny', source: 'environment' },
  whisper_language: { value: 'tr', source: 'environment' },
  media_root: { value: '/data/media', source: 'environment' },
}

const overviewPayload = {
  version: '0.1.0',
  app_env: 'production',
  uptime_seconds: 120,
  phase: 'running',
  database: 'reachable',
  channels: { connected: 1, total: 1 },
  sources: { monitored: 0 },
  llm_providers: { configured: 0 },
  jobs: { active: 0, queued: 0 },
  stock: { clips: 0 },
  today_published: 0,
}

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/settings') && init?.method === 'PUT') {
      // Yanıt asla gizli değerin kendisini taşımaz.
      return new Response(
        JSON.stringify({
          ...settingsPayload,
          youtube_api_key: { configured: true, source: 'database', hint: 'abcd' },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    }
    const body = url.includes('/api/settings')
      ? settingsPayload
      : overviewPayload
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

describe('SettingsScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })
  afterEach(() => cleanup())

  it('renders the settings form with masked secrets and source badges', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<SettingsScreen />)

    expect(
      await screen.findByText('YouTube & Google Bağlantısı'),
    ).toBeInTheDocument()
    // Düz alan effective değerle dolu gelir.
    expect(
      await screen.findByDisplayValue('test.apps.googleusercontent.com'),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('http://ui-test:1478')).toBeInTheDocument()
    // Gizli değer maskeli gösterilir.
    expect(screen.getByText(/ayarlı · ••••9876/)).toBeInTheDocument()
    // Kaynak rozetleri.
    expect(screen.getAllByText('siteden ayarlı').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ortamdan').length).toBeGreaterThan(0)
    expect(
      screen.getByRole('button', { name: 'Ayarları Kaydet' }),
    ).toBeInTheDocument()
    // Sistem paneli kalır.
    expect(await screen.findByText('Sistem')).toBeInTheDocument()
  })

  it('sends only changed plain fields and filled secrets on save', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await screen.findByDisplayValue('http://ui-test:1478')
    fireEvent.change(screen.getByLabelText(/Arayüz Adresi/i), {
      target: { value: 'http://yeni-ui:1478' },
    })
    fireEvent.change(screen.getByLabelText(/YouTube API Anahtarı/i), {
      target: { value: 'yeni-gizli-anahtar' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ayarları Kaydet' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/settings') && c[1]?.method === 'PUT',
      )
      expect(put).toBeDefined()
      const body = JSON.parse(String(put![1]!.body))
      expect(body).toEqual({
        frontend_base_url: 'http://yeni-ui:1478',
        youtube_api_key: 'yeni-gizli-anahtar',
      })
    })
    expect(await screen.findAllByText('Kaydedildi.')).not.toHaveLength(0)
  })

  it('keeps untouched secrets out of the payload', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await screen.findByDisplayValue('test.apps.googleusercontent.com')
    // Yalnızca kota değişir; secret alanları boş kalır.
    fireEvent.change(screen.getByLabelText(/Günlük Kota Birimi/i), {
      target: { value: '5000' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ayarları Kaydet' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/settings') && c[1]?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put![1]!.body))).toEqual({ daily_quota_units: 5000 })
    })
  })
})
