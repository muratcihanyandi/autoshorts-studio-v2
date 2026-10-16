import { getJson } from './client'

export interface SystemResources {
  cpu_percent: number
  memory_percent: number
  memory_total_mb: number
  disk_percent: number
  disk_total_gb: number
  temperature_c: number | null
}

export function fetchSystemResources(): Promise<SystemResources> {
  return getJson<SystemResources>('/api/system')
}
