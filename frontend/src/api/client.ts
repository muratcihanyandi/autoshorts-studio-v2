export class ApiError extends Error {
  status: number
  /** Hata gövdesi JSON'duysa ham payload (kapı tespiti için). */
  payload: Record<string, unknown> | null

  constructor(
    status: number,
    message: string,
    payload: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.status = status
    this.payload = payload
  }
}

/** 401 alınca kabuğu login ekranına döndür (auth uçları hariç). */
function notifyUnauthorized(path: string): void {
  if (path.startsWith('/api/auth/')) return
  window.dispatchEvent(new Event('studio:unauthorized'))
}

/** Hata gövdesini okuyarak ApiError üret; detail string'i mesaj olur,
 * tüm gövde payload olarak taşınır (plana takılan 403'ler {feature,
 * required_plan} taşır). */
async function apiError(response: Response): Promise<ApiError> {
  let payload: Record<string, unknown> | null = null
  let detail = `HTTP ${response.status}`
  try {
    const body = (await response.json()) as Record<string, unknown>
    if (body && typeof body === 'object') {
      payload = body
      if (typeof body.detail === 'string') {
        detail = body.detail
      }
    }
  } catch {
    // gövde JSON değilse HTTP kodu yeter
  }
  return new ApiError(response.status, detail, payload)
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized(path)
    throw await apiError(response)
  }
  return (await response.json()) as T
}

/** JSON gövdeli istekler (POST/PATCH/PUT/DELETE); 204 boş döner. */
export async function sendJson<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<T | null> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized(path)
    throw await apiError(response)
  }
  if (response.status === 204) {
    return null
  }
  return (await response.json()) as T
}
