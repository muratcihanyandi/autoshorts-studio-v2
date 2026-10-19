import { useState, type FormEvent } from 'react'

import { loginStudio, setupStudio } from '../api/auth'
import logoDark from '../assets/brand/logo-dark-bg.svg'
import logoLight from '../assets/brand/logo-light-bg.svg'

type Mode = 'setup' | 'login'

export function AuthScreen({
  mode,
  onAuthenticated,
}: {
  mode: Mode
  onAuthenticated: (username: string) => void
}) {
  const [username, setUsername] = useState(mode === 'setup' ? 'admin' : '')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const isSetup = mode === 'setup'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (isSetup) {
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
      const result = isSetup
        ? await setupStudio(username.trim(), password)
        : await loginStudio(username.trim(), password)
      onAuthenticated(result.username ?? username.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Giriş yapılamadı.')
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
          <p>
            Kaynak videoları izler, en iyi anları seçer, dikey Shorts üretir;
            altyazıyı ve metaveriyi hazırlar, planına göre yayınlar.
          </p>
        </div>
        <ul className="auth-points">
          <li>Motorun seçtiği videolar ve işlem aşamaları</li>
          <li>Hazır klipleri stüdyoda izleme ve YouTube planı</li>
          <li>Kanal, takvim ve otomasyon tek ekranda</li>
        </ul>
        <span className="auth-foot">Raspberry Pi 5 · CasaOS</span>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <img src={logoLight} alt="" className="auth-card-logo" />
          <h2>{isSetup ? 'İlk kurulum' : 'Stüdyoya giriş'}</h2>
          <p className="auth-help">
            {isSetup
              ? 'Yönetici hesabını oluştur. Şifre yalnızca güçlü bir özet olarak saklanır; bir daha düz metin görünmez.'
              : 'Devam etmek için yönetici kullanıcı adı ve şifreni gir.'}
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
                  isSetup ? 'new-password' : 'current-password' // secret-scan-ok
                }
                required
                minLength={isSetup ? 8 : 1}
                disabled={busy}
              />
            </label>
            {isSetup && (
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
            <button type="submit" className="btn btn--primary auth-submit" disabled={busy}>
              {busy ? 'Bağlanıyor…' : isSetup ? 'Hesabı oluştur' : 'Giriş yap'}
            </button>
          </form>
          <p className="auth-note">
            Bu ekran stüdyo yöneticisi içindir. Oturum çerezi HttpOnly olarak
            tutulur; sayfa betikleri tarafından okunamaz.
          </p>
        </div>
      </section>
    </div>
  )
}
