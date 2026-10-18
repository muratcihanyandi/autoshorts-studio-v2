import { cleanup, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LivePipelinePanel } from './LivePipeline'

const pipelinePayload = {
  active: [
    {
      job_id: 41,
      job_type: 'media_process',
      source_video_id: 21,
      title: 'Test videosu',
      channel_id: 4,
      channel_name: 'Kanal A',
      ribbon_color: '#123456',
      stage: 'download',
      stage_index: 0,
      stage_count: 5,
      elapsed_seconds: 120,
      attempts: 1,
      max_attempts: 3,
      eta_seconds: 700,
      average_seconds: 900,
      download: { bytes: 4096, expected_bytes: 5000 },
      last_error: null,
    },
  ],
  queued: [
    {
      job_id: 42,
      job_type: 'media_process',
      title: 'Sıradaki video',
      channel_name: 'Kanal A',
      position: 1,
      attempts: 0,
      max_attempts: 3,
    },
  ],
  recent: [
    {
      job_id: 40,
      job_type: 'media_process',
      title: 'Biten video',
      channel_name: 'Kanal A',
      status: 'succeeded',
      duration_seconds: 60,
      error: null,
      finished_at: '2026-10-18T07:00:00Z',
    },
  ],
  now: '2026-10-18T07:10:00Z',
}

describe('LivePipelinePanel', () => {
  beforeEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows the active job with stage, percent, download and ETA', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(pipelinePayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    render(<LivePipelinePanel />)

    expect(await screen.findByText('Canlı boru hattı')).toBeInTheDocument()
    expect(screen.getByText('Yatay işleme')).toBeInTheDocument()
    expect(screen.getByText('Test videosu')).toBeInTheDocument()
    // Kanal adi aktif kartta ve kuyruk satirinda gorunur.
    expect(screen.getAllByText('Kanal A').length).toBe(2)
    // Asama etiketi + kaba oran: (0 + 4096/5000) / 5 asama -> %16.
    expect(screen.getByText('aşama İndirme')).toBeInTheDocument()
    expect(screen.getByText('16%')).toBeInTheDocument()
    expect(screen.getByText(/kaldı/)).toBeInTheDocument()
    // Kuyruk ve sonuc bolumleri.
    expect(screen.getByText('Sırada bekleyen')).toBeInTheDocument()
    expect(screen.getByText('Sıradaki video')).toBeInTheDocument()
    expect(screen.getByText('Son sonuçlar')).toBeInTheDocument()
    expect(screen.getByText('Biten video')).toBeInTheDocument()
  })

  it('shows the idle engine note when nothing runs or waits', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({ active: [], queued: [], recent: [], now: 'x' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    render(<LivePipelinePanel />)

    expect(await screen.findByText(/Motor boşta/)).toBeInTheDocument()
  })
})
