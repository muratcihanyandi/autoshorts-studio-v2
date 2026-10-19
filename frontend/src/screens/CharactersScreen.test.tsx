import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CharactersScreen } from './CharactersScreen'

const channelsPayload = {
  channels: [
    {
      id: 3,
      name: 'Klip Fabrikası',
      handle: '@klipfabrika',
      youtube_channel_id: 'UCstudio123',
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

const charactersPayload = {
  characters: [
    {
      id: 1,
      name: 'Pelin Yayıncı',
      photo_configured: true,
      reference_face: true,
      system_prompt_set: false,
      notes: 'Hafta sonu yayıncısı',
      created_at: '2026-10-17T00:00:00Z',
    },
  ],
  total: 1,
}

const sourcesPayload = {
  sources: [
    {
      id: 7,
      channel_id: 3,
      youtube_channel_id: 'UCmock123',
      platform: 'youtube',
      title: 'Pelin Ana Kanalı',
      permission_status: 'pending',
      authorized_at: null,
      character_id: 1,
      character_name: 'Pelin Yayıncı',
      reaction_source: false,
      output_orientation: 'auto',
      trim_start_seconds: 0,
      trim_end_seconds: 0,
      filter_rules: {},
      created_at: '2026-10-17T00:00:00Z',
      updated_at: '2026-10-17T00:00:00Z',
    },
  ],
  total: 1,
  authorized: 0,
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/api/characters') && method === 'POST') {
      return json(
        {
          id: 2,
          name: 'Yeni Karakter',
          photo_configured: false,
          reference_face: false,
          system_prompt_set: true,
          notes: null,
          created_at: '2026-10-17T00:00:00Z',
        },
        201,
      )
    }
    if (url.includes('/api/sources/') && method === 'PATCH') {
      return json({ ...sourcesPayload.sources[0], permission_status: 'authorized' })
    }
    if (url.includes('/api/channels/') && url.includes('/sources') && method === 'POST') {
      return json({ ...sourcesPayload.sources[0], id: 8, platform: 'twitch' }, 201)
    }
    if (url.includes('/sources')) {
      return json(sourcesPayload)
    }
    if (url.includes('/api/characters')) {
      return json(charactersPayload)
    }
    if (url.includes('/api/channels')) {
      return json(channelsPayload)
    }
    return json({})
  })
}

describe('CharactersScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })
  afterEach(() => cleanup())

  it('renders character cards with badges and bound sources', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<CharactersScreen />)

    expect(await screen.findByText('Pelin Yayıncı')).toBeInTheDocument()
    expect(screen.getByText('referans yüz var')).toBeInTheDocument()
    expect(screen.getByText('prompt yok')).toBeInTheDocument()
    expect(screen.getByText('Hafta sonu yayıncısı')).toBeInTheDocument()
    // Fotoğraf küçük resmi karakter fotoğraf uç noktasından gelir.
    expect(screen.getByRole('img', { name: /Pelin Yayıncı/ })).toHaveAttribute(
      'src',
      '/api/characters/1/photo',
    )
    // Bağlı kaynak satırı: platform rozeti, yetki hapı, karakter adı.
    expect(await screen.findByText('Pelin Ana Kanalı')).toBeInTheDocument()
    expect(screen.getByText('YouTube')).toBeInTheDocument()
    expect(screen.getByText('bekliyor')).toBeInTheDocument()
    expect(screen.getAllByText('Pelin Yayıncı').length).toBe(2)
    // Kaynak eylemleri ve kanal seçici.
    expect(screen.getByRole('button', { name: 'İzni Ver' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keşfet' })).toBeInTheDocument()
    expect(screen.getByLabelText('Stüdyo kanalı')).toBeInTheDocument()
  })

  it('posts the new character payload from the add form', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    await screen.findByText('Pelin Yayıncı')
    fireEvent.change(screen.getByLabelText('Ad'), {
      target: { value: 'Yeni Karakter' },
    })
    fireEvent.change(screen.getByLabelText('Sistem Promptu'), {
      target: { value: 'Sen bir oyun yayıncısısın.' },
    })
    fireEvent.change(screen.getByLabelText('Notlar'), {
      target: { value: 'Akşam yayınları' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Karakter Ekle' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/characters') && c[1]?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post![1]!.body))).toEqual({
        name: 'Yeni Karakter',
        system_prompt: 'Sen bir oyun yayıncısısın.',
        notes: 'Akşam yayınları',
      })
    })
  })

  it('authorizes a source via permission PATCH', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    await screen.findByText('Pelin Ana Kanalı')
    fireEvent.click(screen.getByRole('button', { name: 'İzni Ver' }))

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/sources/7') && c[1]?.method === 'PATCH',
      )
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]!.body))).toEqual({
        permission_status: 'authorized',
      })
    })
  })

  it('adds a twitch reaction source with trims from the per-character form', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    await screen.findByText('Pelin Yayıncı')
    fireEvent.click(screen.getByRole('button', { name: 'Kaynak Ekle' }))

    // YouTube varsayılanı: UC kimliği etiketi.
    expect(await screen.findByLabelText('UC… Kanal Kimliği')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Platform'), {
      target: { value: 'twitch' },
    })
    // Platform değişince etiket kanal adresine döner.
    expect(screen.getByLabelText('Kanal Adresi')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Kanal Adresi'), {
      target: { value: 'https://twitch.tv/pelin' },
    })
    fireEvent.change(screen.getByLabelText('Başlık'), {
      target: { value: 'Pelin Twitch' },
    })
    // Budama alanları reaksiyon işaretlenmeden görünmez.
    expect(screen.queryByLabelText('Baştan Budama (sn)')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Reaksiyon kaynağı'))
    fireEvent.change(screen.getByLabelText('Baştan Budama (sn)'), {
      target: { value: '10' },
    })
    fireEvent.change(screen.getByLabelText('Sondan Budama (sn)'), {
      target: { value: '20' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Kaynak Ekle' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) =>
          String(c[0]).includes('/api/channels/3/sources') &&
          c[1]?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post![1]!.body))).toEqual({
        youtube_channel_id: 'https://twitch.tv/pelin',
        platform: 'twitch',
        title: 'Pelin Twitch',
        character_id: 1,
        output_orientation: 'auto',
        reaction_source: true,
        trim_start_seconds: 10,
        trim_end_seconds: 20,
      })
    })
  })

  it('sends the chosen output orientation when adding a source', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    await screen.findByText('Pelin Yayıncı')
    fireEvent.click(screen.getByRole('button', { name: 'Kaynak Ekle' }))
    fireEvent.change(await screen.findByLabelText('UC… Kanal Kimliği'), {
      target: { value: 'UCdikey' },
    })
    fireEvent.change(screen.getByLabelText('Başlık'), {
      target: { value: 'Dikey Kaynak' },
    })
    // Görev 2: dikey seçilirse yalnız Shorts üretilir, yatay dosya silinir.
    fireEvent.change(screen.getByLabelText('Çıktı Yönü'), {
      target: { value: 'vertical' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Kaynak Ekle' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) =>
          String(c[0]).includes('/api/channels/3/sources') &&
          c[1]?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post![1]!.body))).toMatchObject({
        youtube_channel_id: 'UCdikey',
        title: 'Dikey Kaynak',
        character_id: 1,
        output_orientation: 'vertical',
      })
    })
  })

  it('changes the output orientation of an existing source', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    const select = await screen.findByLabelText('Pelin Ana Kanalı çıktı yönü')
    fireEvent.change(select, { target: { value: 'vertical' } })

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/sources/7') && c[1]?.method === 'PATCH',
      )
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]!.body))).toEqual({
        output_orientation: 'vertical',
      })
    })
  })

  it('sets the recency window via the source row select', async () => {
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<CharactersScreen />)

    const select = await screen.findByLabelText(
      'Pelin Ana Kanalı güncellik penceresi',
    )
    fireEvent.change(select, { target: { value: '15' } })

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) =>
          String(c[0]).includes('/api/sources/') && c[1]?.method === 'PATCH',
      )
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]!.body))).toEqual({
        filter_rules: { max_age_days: 15 },
      })
    })
  })
})
