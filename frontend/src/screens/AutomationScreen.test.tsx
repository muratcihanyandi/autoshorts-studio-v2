import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AutomationScreen } from './AutomationScreen'

const jobsPayload = {
  jobs: [
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
    },
    {
      id: 6,
      job_type: 'source_discover',
      payload: { channel_id: 2 },
      status: 'failed',
      priority: 9,
      attempts: 3,
      max_attempts: 3,
      last_error: 'RuntimeError: patladi',
      worker_id: 'worker-ab',
      heartbeat_at: null,
      started_at: '2026-10-17T00:00:00Z',
      finished_at: '2026-10-17T00:01:00Z',
      created_at: '2026-10-17T00:00:00Z',
    },
  ],
  total: 2,
}

describe('AutomationScreen', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists queued and failed jobs with actions', async () => {
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

    expect(await screen.findByText('İş Kuyruğu')).toBeInTheDocument()
    expect(screen.getAllByText('Kaynak yoklaması').length).toBe(2)
    expect(screen.getByText('kuyrukta')).toBeInTheDocument()
    expect(screen.getByText('başarısız')).toBeInTheDocument()
    expect(screen.getByText(/patladi/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'İptal' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Yeniden Dene' }),
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

    await screen.findByText('kuyrukta')
    fireEvent.click(screen.getByRole('button', { name: 'İptal' }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/api/jobs/7/cancel') && c[1]?.method === 'POST',
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
