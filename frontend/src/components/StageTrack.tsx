import type { StageStep, StageState } from '../api/media'

const STATE_LABEL: Record<StageState, string> = {
  done: 'tamamlandı',
  active: 'sürüyor',
  pending: 'bekliyor',
  failed: 'hata',
  skipped: 'uygun an bulunamadı',
}

/** Motorun bir kaynak videodaki ilerlemesini adım adım gösterir. */
export function StageTrack({ steps }: { steps: StageStep[] }) {
  return (
    <ol className="stage-track" aria-label="İşlem aşamaları">
      {steps.map((step, index) => (
        <li
          key={step.key}
          className={`stage-step stage-step--${step.state}`}
          aria-current={step.state === 'active' ? 'step' : undefined}
          title={`${step.label}: ${STATE_LABEL[step.state]}`}
        >
          <span className="stage-dot" aria-hidden="true">
            {step.state === 'done' ? '✓' : step.state === 'failed' ? '!' : index + 1}
          </span>
          <span className="stage-label">{step.label}</span>
          {step.detail && (
            <span className="stage-detail nums">{step.detail}</span>
          )}
        </li>
      ))}
    </ol>
  )
}
