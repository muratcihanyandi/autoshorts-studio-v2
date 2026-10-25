import { useState } from 'react'

import {
  changePassword,
  createUser,
  fetchMe,
  fetchPlans,
  fetchUsers,
  patchUser,
  type AccountPlan,
  type AccountRole,
  type AccountUser,
} from '../api/account'
import { usePolling } from '../hooks/usePolling'
import { formatDateTime } from '../format'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Yönetici',
  operator: 'Operatör',
}

const PLAN_LABEL: Record<string, string> = {
  free: 'Ücretsiz',
  pro: 'Pro',
}

/** Profil kartı: kimlik + rol/plan hapları. */
function ProfileCard({
  username,
  role,
  plan,
  planExpiresAt,
}: {
  username: string
  role: string
  plan: string
  planExpiresAt: string | null
}) {
  const initial = (username.trim()[0] || 'U').toUpperCase()
  return (
    <section className="plate account-profile" aria-label="Hesap bilgileri">
      <h2 className="panel-title">Profil</h2>
      <div className="account-profile-main">
        <div className="account-avatar" aria-hidden="true">
          {initial}
        </div>
        <div className="account-profile-details">
          <div className="account-profile-row">
            <b>{username}</b>
            <span className={`pill pill--${role === 'admin' ? 'ok' : 'idle'}`}>
              {ROLE_LABEL[role] ?? role}
            </span>
            <span className={`pill pill--${plan === 'pro' ? 'run' : 'idle'}`}>
              {PLAN_LABEL[plan] ?? plan} planı
            </span>
          </div>
          <small className="account-desc">
            {role === 'admin'
              ? 'Tüm yetkilere sahip stüdyo yöneticisi. Kullanıcıları ve planları yönetebilir.'
              : 'Stüdyo operatörü. Yetkili kanalları ve medya üretimini takip edebilir.'}
          </small>
          {planExpiresAt && (
            <small className="account-expiry">
              Plan süresi: {formatDateTime(planExpiresAt)}
            </small>
          )}
        </div>
      </div>
    </section>
  )
}

/** Şifre değiştirme formu; başarılı değişimde oturum düşmez. */
function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setNote(null)
    if (next.length < 8) {
      setError('Yeni şifre en az 8 karakter olmalı.')
      return
    }
    if (next !== confirm) {
      setError('Yeni şifreler birbiriyle uyuşmuyor.')
      return
    }
    setBusy(true)
    try {
      await changePassword(current, next)
      setNote('Şifre güncellendi; oturumun açık kaldı.')
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Şifre değiştirilemedi.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="plate" aria-label="Şifre değiştir">
      <h2 className="panel-title">Şifre Değiştir</h2>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="password-current">Mevcut şifre</label>
          <input
            id="password-current"
            type="password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            autoComplete="current-password"
            required
          />
        </div>
        <div className="field">
          <label htmlFor="password-new">Yeni şifre</label>
          <input
            id="password-new"
            type="password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="password-confirm">Yeni şifre (tekrar)</label>
          <input
            id="password-confirm"
            type="password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            autoComplete="new-password"
            required
          />
        </div>
        <button type="submit" className="btn" disabled={busy}>
          Şifreyi Güncelle
        </button>
        {note && (
          <p className="action-note" role="status">
            {note}
          </p>
        )}
        {error && (
          <p className="action-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  )
}

/** Abonelik karşılaştırması: mevcut plan vurgulu iki kart. */
function PlansCard({
  currentPlan,
  plans,
}: {
  currentPlan: string | null
  plans: {
    id: string
    name: string
    price_note: string
    max_channels: number | null
    features: { key: string; label: string; included: boolean }[]
  }[]
}) {
  return (
    <section className="plate" aria-label="Abonelik planları">
      <h2 className="panel-title">Abonelik</h2>
      <p className="account-plan-note">
        Örnek abonelik sistemidir: ödeme akışı yoktur, plan atamasını
        yönetici bu ekrandaki kullanıcı yönetiminden yapar.
      </p>
      <div className="plan-grid">
        {plans.map((plan) => {
          const isCurrent = plan.id === currentPlan
          return (
            <div
              key={plan.id}
              className={`plan-card${isCurrent ? ' plan-card--current' : ''}`}
            >
              <div className="plan-card-head">
                <b>{plan.name}</b>
                {isCurrent && (
                  <span className="pill pill--ok">Mevcut planın</span>
                )}
              </div>
              <div className="plan-price nums">
                {plan.price_note === '0' ? 'Ücretsiz' : `₺${plan.price_note}/ay`}
              </div>
              <ul className="plan-features">
                <li>
                  YouTube kanalı:{' '}
                  {plan.max_channels === null ? 'Sınırsız' : plan.max_channels}
                </li>
                {plan.features.map((feature) => (
                  <li
                    key={feature.key}
                    className={feature.included ? '' : 'plan-feature--off'}
                  >
                    {feature.included ? '✓' : '—'} {feature.label}
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/** Kullanıcı satırı: rol/plan seçimi ve etkinleştirme düğmesi. */
function UserRow({
  user,
  onPatch,
}: {
  user: AccountUser
  onPatch: (
    id: number,
    body: { role?: AccountRole; plan?: AccountPlan; is_active?: boolean },
  ) => void
}) {
  return (
    <tr>
      <td>{user.username}</td>
      <td>
        <select
          aria-label={`${user.username} rolü`}
          value={user.role}
          onChange={(event) =>
            onPatch(user.id, { role: event.target.value as AccountRole })
          }
        >
          <option value="admin">Yönetici</option>
          <option value="operator">Operatör</option>
        </select>
      </td>
      <td>
        <select
          aria-label={`${user.username} planı`}
          value={user.plan}
          onChange={(event) =>
            onPatch(user.id, { plan: event.target.value as AccountPlan })
          }
        >
          <option value="free">Ücretsiz</option>
          <option value="pro">Pro</option>
        </select>
      </td>
      <td>
        <button
          type="button"
          className="btn--ghost"
          onClick={() => onPatch(user.id, { is_active: !user.is_active })}
        >
          {user.is_active ? 'Devre dışı bırak' : 'Etkinleştir'}
        </button>
      </td>
    </tr>
  )
}

/** Admin kullanıcı yönetimi: liste + yeni kullanıcı formu. */
function UsersPanel() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<AccountRole>('operator')
  const [plan, setPlan] = useState<AccountPlan>('free')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const users = usePolling(fetchUsers, 30000)

  const patch = (
    id: number,
    body: { role?: AccountRole; plan?: AccountPlan; is_active?: boolean },
  ) => {
    patchUser(id, body)
      .then(() => users.retry())
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Güncelleme başarısız.'),
      )
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await createUser({ username, password, role, plan })
      setUsername('')
      setPassword('')
      users.retry()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Kullanıcı açılamadı.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="plate" aria-label="Kullanıcı yönetimi">
      <h2 className="panel-title">Kullanıcılar</h2>
      {users.state.status === 'loading' && (
        <LoadingState label="Kullanıcılar okunuyor…" />
      )}
      {users.state.status === 'error' && (
        <ErrorState
          title="Kullanıcılar alınamadı"
          message={users.state.message}
          onRetry={users.retry}
        />
      )}
      {users.state.status === 'ok' && (
        <>
          {users.state.stale && <StaleNote onRetry={users.retry} />}
          <div className="table-scroll">
            <table className="info-table" aria-label="Stüdyo kullanıcıları">
              <thead>
                <tr>
                  <th>Kullanıcı</th>
                  <th>Rol</th>
                  <th>Plan</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {users.state.data.users.map((user) => (
                  <UserRow key={user.id} user={user} onPatch={patch} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h3 className="account-subhead">Yeni Kullanıcı</h3>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="user-name">Kullanıcı adı</label>
          <input
            id="user-name"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            minLength={3}
            maxLength={64}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="user-password">Şifre</label>
          <input
            id="user-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            autoComplete="new-password"
            required
          />
        </div>
        <div className="field">
          <label htmlFor="user-role">Rol</label>
          <select
            id="user-role"
            value={role}
            onChange={(event) => setRole(event.target.value as AccountRole)}
          >
            <option value="operator">Operatör</option>
            <option value="admin">Yönetici</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="user-plan">Plan</label>
          <select
            id="user-plan"
            value={plan}
            onChange={(event) => setPlan(event.target.value as AccountPlan)}
          >
            <option value="free">Ücretsiz</option>
            <option value="pro">Pro</option>
          </select>
        </div>
        <button type="submit" className="btn" disabled={busy}>
          Kullanıcı Aç
        </button>
        {error && (
          <p className="action-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  )
}

export function AccountScreen() {
  const me = usePolling(fetchMe, 60000)
  const plans = usePolling(fetchPlans, 60000)
  const isAdmin = me.state.status === 'ok' && me.state.data.role === 'admin'

  return (
    <>
      <div className="screen-head">
        <h1>Hesap</h1>
        <span className="screen-sub">Profil, şifre ve abonelik yönetimi</span>
      </div>

      {me.state.status === 'loading' && <LoadingState label="Hesap okunuyor…" />}
      {me.state.status === 'error' && (
        <ErrorState
          title="Hesap bilgisi alınamadı"
          message={me.state.message}
          onRetry={me.retry}
        />
      )}
      {me.state.status === 'ok' && (
        <>
          {me.state.stale && <StaleNote onRetry={me.retry} />}
          <ProfileCard
            username={me.state.data.username}
            role={me.state.data.role}
            plan={me.state.data.plan}
            planExpiresAt={me.state.data.plan_expires_at}
          />
          <PasswordCard />
          {plans.state.status === 'ok' && (
            <PlansCard
              currentPlan={plans.state.data.current.plan}
              plans={plans.state.data.plans}
            />
          )}
          {isAdmin && <UsersPanel />}
        </>
      )}
    </>
  )
}
