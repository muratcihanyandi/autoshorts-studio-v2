export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new ApiError(response.status, `HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

/** JSON gövdeli istekler (POST/PATCH/DELETE); 204 boş döner. */
export async function sendJson<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T | null> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload && typeof payload.detail === 'string') {
        detail = payload.detail
      }
    } catch {
      // gövde JSON değilse HTTP kodu yeter
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) {
    return null
  }
  return (await response.json()) as T
}
