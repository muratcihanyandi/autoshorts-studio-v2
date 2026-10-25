import { getJson, sendJson } from './client'

/** Hesap sistemi (madde 6): profil, şifre değiştirme, abonelik
 * kataloğu ve admin kullanıcı yönetimi. */

export type AccountRole = 'admin' | 'operator'
export type AccountPlan = 'free' | 'pro'

export interface AccountMe {
  username: string
  role: AccountRole
  plan: AccountPlan
  plan_expires_at: string | null
  is_active: boolean
}

export interface PlanFeature {
  key: string
  label: string
  included: boolean
}

export interface PlanInfo {
  id: AccountPlan
  name: string
  price_note: string
  max_channels: number | null
  features: PlanFeature[]
}

export interface PlansResponse {
  current: { plan: AccountPlan | null; plan_expires_at: string | null }
  plans: PlanInfo[]
}

export interface AccountUser {
  id: number
  username: string
  role: AccountRole
  plan: AccountPlan
  plan_expires_at: string | null
  is_active: boolean
}

export function fetchMe(): Promise<AccountMe> {
  return getJson<AccountMe>('/api/auth/me')
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ ok: boolean } | null> {
  return sendJson<{ ok: boolean }>('/api/auth/password', 'POST', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

export function fetchPlans(): Promise<PlansResponse> {
  return getJson<PlansResponse>('/api/plans')
}

export function fetchUsers(): Promise<{ users: AccountUser[] }> {
  return getJson<{ users: AccountUser[] }>('/api/auth/users')
}

export function createUser(body: {
  username: string
  password: string
  role: AccountRole
  plan: AccountPlan
}): Promise<{ user: AccountUser } | null> {
  return sendJson<{ user: AccountUser }>('/api/auth/users', 'POST', body)
}

export function patchUser(
  id: number,
  body: { role?: AccountRole; plan?: AccountPlan; is_active?: boolean },
): Promise<{ user: AccountUser } | null> {
  return sendJson<{ user: AccountUser }>(`/api/auth/users/${id}`, 'PATCH', body)
}
