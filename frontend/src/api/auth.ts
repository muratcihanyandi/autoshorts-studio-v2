import { getJson, sendJson } from './client'

export interface AuthStatus {
  configured: boolean
  authenticated: boolean
  username: string | null
  signup_open: boolean
}

export function fetchAuthStatus(): Promise<AuthStatus> {
  return getJson<AuthStatus>('/api/auth/status')
}

export async function signupStudio(
  username: string,
  password: string,
): Promise<AuthStatus> {
  const result = await sendJson<AuthStatus>('/api/auth/signup', 'POST', {
    username,
    password,
  })
  if (!result) throw new Error('Kayıt yanıtı alınamadı.')
  return result
}

export async function loginStudio(
  username: string,
  password: string,
): Promise<AuthStatus> {
  const result = await sendJson<AuthStatus>('/api/auth/login', 'POST', {
    username,
    password,
  })
  if (!result) throw new Error('Giriş yanıtı alınamadı.')
  return result
}

export async function logoutStudio(): Promise<void> {
  await sendJson<null>('/api/auth/logout', 'POST')
}
