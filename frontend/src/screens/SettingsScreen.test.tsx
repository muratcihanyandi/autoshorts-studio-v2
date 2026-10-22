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
  clip_min_seconds: { value: 20, source: 'environment' },
  clip_max_seconds: { value: 180, source: 'environment' },
  min_free_disk_gb: { value: '2.0', source: 'environment' },
  download_rate_limit_kbps: { value: 0, source: 'environment' },
  planned_poll_interval_minutes: { value: 5, source: 'environment' },
  media_retention_days: { value: 0, source: 'environment' },
  transcription_method: { value: 'sidecar', source: 'environment' },
  whisper_model: { value: 'tiny', source: 'environment' },
  whisper_language: { value: 'tr', source: 'environment' },
  burn_subtitles: { value: true, source: 'environment' },
  subtitle_font_size: { value: 64, source: 'environment' },
  subtitle_style_preset: { value: 'klasik', source: 'environment' },
  subtitle_pos_x_percent: { value: 50, source: 'environment' },
  subtitle_pos_y_percent: { value: 78, source: 'environment' },
  shorts_webcam_percent: { value: 35, source: 'environment' },
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
  today_published: {
    vertical: 0,
    horizontal: 0,
    vertical_limit: 0,
    horizontal_limit: 0,
  },
}

const whisperState = { installed: false }

const whisperPayload = () => ({
  installed: whisperState.installed,
  platform: 'Windows',
  machine: 'AMD64',
  status: whisperState.installed
    ? { state: 'succeeded', mode: 'direct' }
    : null,
})

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/whisper/install') && init?.method === 'POST') {
      whisperState.installed = true
      return new Response(
        JSON.stringify({
          state: 'running',
          mode: 'direct',
          platform: 'Windows',
          machine: 'AMD64',
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      )
    }
    if (url.includes('/api/whisper')) {
      return new Response(JSON.stringify(whisperPayload()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
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

async function openTab(label: string) {
  fireEvent.click(await screen.findByRole('tab', { name: label }))
}

describe('SettingsScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    whisperState.installed = false
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
    // Kategori sekmeleri beşi de durur (Shorts + Yatay video başlıkları).
    expect(screen.getByRole('tab', { name: 'Bağlantılar' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Üretim' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Shorts' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Yatay video' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Sistem' })).toBeInTheDocument()
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

  it('saves the flexible clip duration bounds', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await openTab('Shorts')

    // Görev 3: klip süresi alt/üst sınırı siteden ayarlanabilir
    // (Shorts sekmesinde, kısa klip üretimi grubunda).
    expect(
      await screen.findByLabelText(/Klip Süresi Alt Sınır \(sn\)/i),
    ).toHaveValue(20)
    expect(screen.getByLabelText(/Klip Süresi Üst Sınır \(sn\)/i)).toHaveValue(180)
    fireEvent.change(screen.getByLabelText(/Klip Süresi Üst Sınır \(sn\)/i), {
      target: { value: '120' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ayarları Kaydet' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/settings') && c[1]?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put![1]!.body))).toEqual({ clip_max_seconds: 120 })
    })
  })

  it('shows the whisper install button and installs on click', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await openTab('Üretim')

    // Whisper kurulu değil: düğme görünür.
    const button = await screen.findByRole('button', {
      name: "Whisper'ı İndir ve Kur",
    })
    expect(button).toBeInTheDocument()

    fireEvent.click(button)

    // Kurulum isteği gönderilir; durum yenilenince kurulu görünür.
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) =>
          String(c[0]).includes('/api/whisper/install') &&
          c[1]?.method === 'POST',
      )
      expect(post).toBeDefined()
    })
    expect(await screen.findByText(/Whisper kurulu/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: "Whisper'ı İndir ve Kur" }),
    ).not.toBeInTheDocument()
  })

  it('renders the shorts section with a live preview', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<SettingsScreen />)

    await openTab('Shorts')

    expect(await screen.findByText('Shorts (Dikey Klipler)')).toBeInTheDocument()
    // Önizleme temsilî kadranı ve örnek altyazı metnini taşır.
    expect(
      screen.getByRole('img', { name: /önizlemesi/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('İşte günün en heyecanlı anı!')).toBeInTheDocument()

    // Kapalı yapınca örnek metin kalkar, kapalı notu gelir.
    fireEvent.click(screen.getByLabelText('Dikey kliplere altyazı göm'))
    expect(
      screen.queryByText('İşte günün en heyecanlı anı!'),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Altyazı kapalı')).toBeInTheDocument()
  })

  it('offers five subtitle styles including the yellow Shorts look', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<SettingsScreen />)

    await openTab('Shorts')

    expect(await screen.findByText('Shorts (Dikey Klipler)')).toBeInTheDocument()
    // Görev 1: beş stil seçeneği kartta sunulur.
    for (const label of [
      'Klasik Beyaz',
      'Shorts Sarı',
      'Anton',
      'Kutulu',
      'Noto Sans',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(
      screen.getByRole('radio', { name: /Shorts Sarı/i }),
    ).toBeInTheDocument()
  })

  it('saves only the changed subtitle settings', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await openTab('Shorts')
    await screen.findByText('Shorts (Dikey Klipler)')

    // Görev 2: dikey konum slider'ı; Görev 1: stil seçimi.
    fireEvent.change(screen.getByLabelText(/Dikey Konum/i), {
      target: { value: '40' },
    })
    fireEvent.change(screen.getByLabelText(/Yazı Boyutu/i), {
      target: { value: '88' },
    })
    fireEvent.click(screen.getByRole('radio', { name: /Shorts Sarı/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Ayarları Kaydet' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/settings') && c[1]?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put![1]!.body))).toEqual({
        subtitle_pos_y_percent: 40,
        subtitle_font_size: 88,
        subtitle_style_preset: 'shorts_sari',
      })
    })
  })

  it('saves the webcam/video ratio from the Shorts tab', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsScreen />)

    await openTab('Shorts')
    await screen.findByText('Shorts (Dikey Klipler)')

    // Varsayılan %35; slider %30'a çekilince yalnızca o alan gönderilir.
    const slider = screen.getByLabelText(/Webcam \/ Video Oranı/i)
    expect(slider).toHaveValue('35')
    fireEvent.change(slider, { target: { value: '30' } })
    // Önizleme bölüm etiketleri yeni oranı gösterir.
    expect(screen.getByText('Kamera %30')).toBeInTheDocument()
    expect(screen.getByText('Video %70')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ayarları Kaydet' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/settings') && c[1]?.method === 'PUT',
      )
      expect(put).toBeDefined()
      expect(JSON.parse(String(put![1]!.body))).toEqual({
        shorts_webcam_percent: 30,
      })
    })
  })

  it('shows the horizontal full-cut settings on their own tab', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<SettingsScreen />)

    await openTab('Yatay video')

    expect(
      await screen.findByText('Yatay Video (Tam Kesit)'),
    ).toBeInTheDocument()
    expect(
      screen.getByLabelText(/Yatay Stok Hedefi \(Varsayılan\)/i),
    ).toHaveValue(3)
    // Yatay kesit sözleşmesi: altyazı asla gömülmez, ses korunur.
    expect(
      screen.getByText(/altyazı yatay kesitlerde asla gömülmez/i),
    ).toBeInTheDocument()
  })

  it('shows the system info on its own tab', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<SettingsScreen />)

    await openTab('Sistem')

    expect(await screen.findByRole('heading', { name: 'Sistem' })).toBeInTheDocument()
    expect(screen.getByText('Bağlı (PostgreSQL)')).toBeInTheDocument()
  })
})
