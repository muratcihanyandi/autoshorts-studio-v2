export interface BackendHealth {
  status: string
  service: string
  version: string
}

export async function fetchBackendHealth(): Promise<BackendHealth> {
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return (await response.json()) as BackendHealth
}
