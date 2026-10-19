import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AutomationScreen } from './AutomationScreen'

const jobsPayload = {
  jobs: [
    {
      id: 8,
      job_type: 'media_process',
      payload: { source_video_id: 3 },
      status: 'running',
      priority: 5,
      attempts: 1,
      max_attempts: 3,
      last_error: null,
      worker_id: 'worker-ab',
      heartbeat_at: '2026-10-17T00:00:30Z',
      started_at: '2026-10-17T00:00:00Z',
      finished_at: null,
      created_at: '2026-10-17T00:00:00Z',
      title: 'Tepki videosu 3',
      channel_name: 'Craftest',
      ribbon_color: '#123456',
      stage: 'download',
    },
    {
      id: 7,
      job_type: 'source_discover',
      payload: { channel_id: 1 },
      status: 'queued',
      priority: 9,
      attempts: 0,
      max_attempts: 3,
      last_error: null,
      worker_id: null,
      heartbeat_at: null,
      started_at: null,
      finished_at: null,
      created_at: '2026-10-17T00:00:00Z',
      title: null,
      channel_name: null,
      ribbon_color: null,
      stage: null,
    },
    {
      id: 6,
      job_type: 'media_process',
      payload: { source_video_id: 2 },
      status: 'failed',
      priority: 5,
      attempts: 3,
      max_attempts: 3,
      last_error: 'RuntimeError: patladi',
      worker_id: 'worker-ab',
      heartbeat_at: null,
      started_at: '2026-10-17T00:00:00Z',
      finished_at: '2026-10-17T00:01:00Z',
      created_at: '2026-10-17T00:00:00Z',
      title: 'Tepki videosu 2',
      channel_name: 'Craftest',
      ribbon_color: '#123456',
      stage: 'transcript',
    },
  ],
  total: 3,
}

describe('AutomationScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('tells each job as a natural sentence grouped by state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(jobsPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<AutomationScreen />)

    expect(await screen.findByText('Şu an sürüyor')).toBeInTheDocument()
    expect(screen.getByText('Sırada bekleyen')).toBeInTheDocument()
    expect(screen.getByText('Son bitenler')).toBeInTheDocument()
    // Videolu is: baslik + dogal eylem cumlesi.
    expect(screen.getAllByText('Tepki videosu 3').length).toBe(1)
    expect(screen.getByText('indiriliyor')).toBeInTheDocument()
    // Videosuz is: kendi ozneli cumle.
    expect(
      screen.getByText('yetkili kaynaklarda yeni videolar aranıyor'),
    ).toBeInTheDocument()
    // Durum pill'leri.
    expect(screen.getByText('sürüyor')).toBeInTheDocument()
    expect(screen.getByText('sırada')).toBeInTheDocument()
    expect(screen.getByText('başarısız')).toBeInTheDocument()
    expect(screen.getByText(/patladi/)).toBeInTheDocument()
    // Eylemler: kosan ve siradaki is iptal edilir, hatali is yeniden
    // denenir.
    expect(screen.getAllByRole('button', { name: 'İptal' }).length).toBe(2)
    expect(
      screen.getByRole('button', { name: 'Yeniden dene' }),
    ).toBeInTheDocument()
  })

  it('sends cancel for an active job', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(
        JSON.stringify(
          init?.method === 'POST'
            ? jobsPayload.jobs[0]
            : jobsPayload,
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<AutomationScreen />)

    await screen.findByText('sürüyor')
    // Ilk 'Iptal' sirasi 'Su an suruyor' bolumundeki kosi isin (id 8).
    fireEvent.click(screen.getAllByRole('button', { name: 'İptal' })[0])

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/jobs/8/cancel') && c[1]?.method === 'POST',
      )
      expect(post).toBeDefined()
    })
  })

  it('shows an empty-queue note without jobs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ jobs: [], total: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<AutomationScreen />)
    expect(await screen.findByText(/Kuyruk boş/)).toBeInTheDocument()
  })
})
