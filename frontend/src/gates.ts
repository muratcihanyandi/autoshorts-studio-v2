import { ApiError } from './api/client'

export interface GateInfo {
  feature: string
  requiredPlan: string
  detail: string
}

/** 403 kapı yanıtı mı? Plana takılan özellikler backend'den
 * {detail, feature, required_plan} şekliyle döner. */
export function gateFromError(error: unknown): GateInfo | null {
  if (!(error instanceof ApiError) || error.status !== 403) return null
  const payload = error.payload
  if (!payload) return null
  const feature = payload.feature
  const requiredPlan = payload.required_plan
  if (typeof feature !== 'string' || typeof requiredPlan !== 'string') {
    return null
  }
  return { feature, requiredPlan, detail: error.message }
}

const GATE_LABELS: Record<string, string> = {
  channels: 'Ek kanal ekleme',
  youtube_analytics: 'YouTube analitiği',
  bulk_actions: 'Toplu işlemler',
  manual_schedule: 'Manuel yayın planlama',
}

export function gateLabel(feature: string): string {
  return GATE_LABELS[feature] ?? feature
}
