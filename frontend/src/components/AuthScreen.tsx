import { useState, type FormEvent } from 'react'

import { loginStudio, signupStudio } from '../api/auth'
import logoDark from '../assets/brand/logo-dark-bg.svg'
import logoLight from '../assets/brand/logo-light-bg.svg'

type Mode = 'login' | 'signup'

export function AuthScreen({
  initialMode,
  signupOpen: _signupOpen,
  onAuthenticated,
}: {
  initialMode: Mode
  signupOpen?: boolean
  onAuthenticated: (username: string) => void
}) {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const isSignup = mode === 'signup'

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setPassword('')
    setConfirm('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (isSignup) {
      if (password.length < 8) {
        setError('Şifre en az 8 karakter olmalı.')
        return
      }
      if (password !== confirm) {
        setError('Şifreler birbirini tutmuyor.')
        return
      }
    }
    setBusy(true)
    try {
      const result = isSignup
        ? await signupStudio(username.trim(), password)
        : await loginStudio(username.trim(), password)
      onAuthenticated(result.username ?? username.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'İşlem tamamlanamadı.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-brand" aria-label="AutoShorts Studio">
        <img src={logoDark} alt="AutoShorts Studio" className="auth-logo" />
        <div className="auth-brand-copy">
          <span className="auth-kicker">YouTube Creator Studio</span>
          <h1>Kanalının arkasındaki motor.</h1>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <img src={logoLight} alt="" className="auth-card-logo" />

          <div className="auth-tabs" role="tablist" aria-label="Giriş veya kayıt">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'login'}
              className={mode === 'login' ? 'active' : ''}
              onClick={() => switchMode('login')}
            >
              Giriş yap
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signup'}
              className={mode === 'signup' ? 'active' : ''}
              onClick={() => switchMode('signup')}
            >
              Kayıt ol
            </button>
          </div>

          <h2>{isSignup ? 'Hesap oluştur' : 'Giriş yap'}</h2>
          <p className="auth-help">
            {isSignup
              ? 'Yeni stüdyo hesabı oluştur (Ücretsiz plan).'
              : 'Devam etmek için kullanıcı adı ve şifrenle giriş yap.'}
          </p>

          <form onSubmit={submit} className="auth-form">
              <label>
                Kullanıcı adı
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  required
                  minLength={3}
                  maxLength={64}
                  disabled={busy}
                />
              </label>
              <label>
                Şifre
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={
                    isSignup ? 'new-password' : 'current-password' // secret-scan-ok
                  }
                  required
                  minLength={isSignup ? 8 : 1}
                  disabled={busy}
                />
              </label>
              {isSignup && (
                <label>
                  Şifre (tekrar)
                  <input
                    type="password"
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    autoComplete="new-password"
                    required
                    minLength={8}
                    disabled={busy}
                  />
                </label>
              )}
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button
                type="submit"
                className="btn btn--primary auth-submit"
                disabled={busy}
              >
                {busy
                  ? 'Bağlanıyor…'
                  : isSignup
                    ? 'Hesap oluştur'
                    : 'Giriş yap'}
              </button>
            </form>
        </div>
      </section>
    </div>
  )
}
