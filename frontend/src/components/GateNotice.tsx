import { Link } from 'react-router-dom'

import { gateLabel, type GateInfo } from '../gates'

/** Plana takılan özellik için nazik bilgi notu — hata değil, yol
 * göstergesi: neyin kilitli olduğu, hangi planla açıldığı ve planın
 * nerede görüleceği. */
export function GateNotice({ gate }: { gate: GateInfo }) {
  const planName = gate.requiredPlan === 'pro' ? 'Pro' : gate.requiredPlan
  return (
    <div className="gate-notice" role="note">
      <p>
        <strong>{gateLabel(gate.feature)}</strong> özelliği{' '}
        <strong>{planName}</strong> planıyla açılır.
      </p>
      {gate.detail && <small>{gate.detail}</small>}
      <Link to="/hesap" className="gate-link">
        Planları gör
      </Link>
    </div>
  )
}
