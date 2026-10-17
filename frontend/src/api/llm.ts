import { getJson, sendJson } from './client'

export type ProviderType = 'openai' | 'anthropic' | 'google'

export interface ApiKeyView {
  configured: boolean
  hint: string
}

export interface LlmProvider {
  id: number
  name: string
  provider_type: ProviderType
  api_base: string
  model_id: string
  api_key: ApiKeyView
  enabled: boolean
  priority: number
  timeout_seconds: number
  max_retries: number
}

export interface LlmProviders {
  providers: LlmProvider[]
  total: number
  enabled: number
}

export interface LlmTestResult {
  provider_id: number
  status: string
  latency_ms: number
  detail: string
}

export interface LlmRequestLog {
  id: number
  request_id: string
  provider_name: string
  status: string
  latency_ms: number
  created_at: string
}

export interface LlmRequestLogs {
  logs: LlmRequestLog[]
  total: number
}

export const PROVIDER_TYPE_LABEL: Record<ProviderType, string> = {
  openai: 'OpenAI uyumlu',
  anthropic: 'Anthropic uyumlu',
  google: 'Google uyumlu',
}

export const STATUS_LABEL: Record<string, string> = {
  success: 'başarılı',
  timeout: 'zaman aşımı',
  rate_limited: 'hız sınırı',
  http_error: 'HTTP hatası',
  network: 'ağ hatası',
  invalid_response: 'geçersiz yanıt',
  not_configured: 'yapılandırılmamış',
}

export function fetchLlmProviders(): Promise<LlmProviders> {
  return getJson<LlmProviders>('/api/llm/providers')
}

export function createLlmProvider(
  data: Omit<LlmProvider, 'id' | 'api_key'> & { api_key: string },
): Promise<LlmProvider> {
  return sendJson<LlmProvider>('/api/llm/providers', 'POST', data).then(
    (p) => {
      if (p === null) throw new Error('Boş yanıt')
      return p
    },
  )
}

export function updateLlmProvider(
  id: number,
  patch: Partial<Omit<LlmProvider, 'id' | 'api_key'>> & {
    api_key?: string
  },
): Promise<LlmProvider> {
  return sendJson<LlmProvider>(`/api/llm/providers/${id}`, 'PATCH', patch).then(
    (p) => {
      if (p === null) throw new Error('Boş yanıt')
      return p
    },
  )
}

export function deleteLlmProvider(id: number): Promise<null> {
  return sendJson<null>(`/api/llm/providers/${id}`, 'DELETE')
}

export function testLlmProvider(id: number): Promise<LlmTestResult> {
  return sendJson<LlmTestResult>(`/api/llm/providers/${id}/test`, 'POST').then(
    (r) => {
      if (r === null) throw new Error('Boş yanıt')
      return r
    },
  )
}

export function fetchLlmLogs(): Promise<LlmRequestLogs> {
  return getJson<LlmRequestLogs>('/api/llm/logs?limit=20')
}
