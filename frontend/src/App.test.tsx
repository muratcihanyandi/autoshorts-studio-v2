import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const healthyPayload = JSON.stringify({
  status: 'ok',
  service: 'autoshorts-backend',
  version: '0.1.0',
})

describe('App', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows backend status when the API responds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(healthyPayload, {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    render(<App />)
    expect(await screen.findByText(/çevrimiçi/i)).toBeInTheDocument()
    expect(await screen.findByText(/autoshorts-backend v0\.1\.0/)).toBeInTheDocument()
  })

  it('shows an error state with retry when the API is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('HTTP 503')
      }),
    )
    render(<App />)
    expect(await screen.findByText(/bağlantı kurulamadı/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /yeniden dene/i })).toBeInTheDocument()
  })
})
