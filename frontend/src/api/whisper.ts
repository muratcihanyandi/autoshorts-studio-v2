import { getJson, sendJson } from './client'

export type WhisperInstallState = 'running' | 'succeeded' | 'failed'

export interface WhisperInstallStatus {
  state: WhisperInstallState
  mode?: string | null
  target?: string | null
  platform?: string | null
  machine?: string | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
  log_tail?: string | null
}

export interface WhisperStatus {
  installed: boolean
  platform: string
  machine: string
  status: WhisperInstallStatus | null
}

export interface WhisperInstallStarted {
  state: 'running'
  mode: string
  platform: string
  machine: string
}

export function fetchWhisperStatus(): Promise<WhisperStatus> {
  return getJson<WhisperStatus>('/api/whisper')
}

export function installWhisper(): Promise<WhisperInstallStarted> {
  return sendJson<WhisperInstallStarted>('/api/whisper/install', 'POST').then(
    (r) => {
      if (r === null) throw new Error('Boş yanıt')
      return r
    },
  )
}
