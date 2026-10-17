import { useCallback, useEffect, useState } from 'react'
import { fetchOverview } from '../api/overview'
import {
  fetchSettings,
  SOURCE_LABEL,
  updateSettings,
  type SettingsPatch,
  type SettingsView,
} from '../api/settings'
import { usePolling } from '../hooks/usePolling'
import { ErrorState, LoadingState, StaleNote } from '../components/States'
import { ApiError } from '../api/client'

const PHASE_LABEL: Record<string, string> = {
  setup: 'Kurulum — veritabanı bekleniyor',
  awaiting_channels: 'Kanal bekleniyor',
  running: 'Çalışıyor',
}

type PlainKey = 'google_client_id' | 'oauth_redirect_base' | 'frontend_base_url'
type SecretKey =
  | 'google_client_secret'
  | 'token_encryption_key'
  | 'youtube_api_key'

const PLAIN_FIELDS: { key: PlainKey; label: string; help?: string }[] = [
  {
    key: 'google_client_id',
    label: 'Google Client ID',
    help: 'Google Cloud Console → OAuth istemci kimliği.',
  },
  {
    key: 'oauth_redirect_base',
    label: 'OAuth Yönlendirme Adresi',
    help: 'Stüdyonun dışarıdan erişilen adresi (örn. http://192.168.x.x:8000).',
  },
  {
    key: 'frontend_base_url',
    label: 'Arayüz Adresi',
    help: 'Bu arayüzün dışarıdan erişilen adresi; OAuth dönüşü buraya yönelenir.',
  },
]

const SECRET_FIELDS: {
  key: SecretKey
  label: string
  help?: string
  warning?: string
}[] = [
  {
    key: 'google_client_secret',
    label: 'Google Client Secret',
    help: 'Değeri yalnızca kaydederken gönderilir; asla geri okunmaz.',
  },
  {
    key: 'token_encryption_key',
    label: 'Token Şifreleme Anahtarı',
    warning:
      'Değiştirirseniz bağlı kanalların izinleri çözülemez hale gelir; ' +
      'kanalları yeniden bağlamanız gerekir.',
  },
  {
    key: 'youtube_api_key',
    label: 'YouTube API Anahtarı',
    help: 'Kaynak izleme (Data API v3) için kullanılır.',
  },
]

interface FormState {
  plain: Record<PlainKey, string>
  secrets: Record<SecretKey, string>
  quota: string
}

function initForm(view: SettingsView): FormState {
  return {
    plain: {
      google_client_id: view.google_client_id.value,
      oauth_redirect_base: view.oauth_redirect_base.value,
      frontend_base_url: view.frontend_base_url.value,
    },
    secrets: {
      google_client_secret: '',
      token_encryption_key: '',
      youtube_api_key: '',
    },
    quota: String(view.daily_quota_units.value),
  }
}

export function SettingsScreen() {
  const fetcher = useCallback(() => fetchOverview(), [])
  const { state, retry } = usePolling(fetcher, 30000)

  const [view, setView] = useState<SettingsView | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<
    { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string }
  >({ kind: 'idle' })

  const loadSettings = useCallback(async () => {
    try {
      const next = await fetchSettings()
      setView(next)
      setForm(initForm(next))
      setLoadError(null)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'bilinmeyen hata'
      setLoadError(message)
    }
  }, [])

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  const setPlain = (key: PlainKey, value: string) => {
    setForm((f) => (f ? { ...f, plain: { ...f.plain, [key]: value } } : f))
  }
  const setSecret = (key: SecretKey, value: string) => {
    setForm((f) => (f ? { ...f, secrets: { ...f.secrets, [key]: value } } : f))
  }
  const setQuota = (value: string) => {
    setForm((f) => (f ? { ...f, quota: value } : f))
  }

  const save = async () => {
    if (!view || !form) return
    const patch: SettingsPatch = {}
    for (const { key } of PLAIN_FIELDS) {
      if (form.plain[key] !== view[key].value) {
        patch[key] = form.plain[key].trim()
      }
    }
    for (const { key } of SECRET_FIELDS) {
      if (form.secrets[key].trim() !== '') {
        patch[key] = form.secrets[key].trim()
      }
    }
    const quota = Number(form.quota)
    if (Number.isInteger(quota) && quota !== view.daily_quota_units.value) {
      patch.daily_quota_units = quota
    }

    if (Object.keys(patch).length === 0) {
      setSaveState({ kind: 'saved' })
      return
    }

    setSaveState({ kind: 'saving' })
    try {
      const next = await updateSettings(patch)
      setView(next)
      setForm(initForm(next))
      setSaveState({ kind: 'saved' })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'bilinmeyen hata'
      setSaveState({ kind: 'error', message })
    }
  }

  const clearSecret = async (key: SecretKey) => {
    setSaveState({ kind: 'saving' })
    try {
      const next = await updateSettings({ [key]: '' })
      setView(next)
      setForm(initForm(next))
      setSaveState({ kind: 'saved' })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'bilinmeyen hata'
      setSaveState({ kind: 'error', message })
    }
  }

  return (
    <>
      <div className="screen-head">
        <h1>Ayarlar</h1>
        <span className="screen-sub">Stüdyo yapılandırması ve sistem bilgisi</span>
      </div>

      {state.status === 'ok' && state.stale && <StaleNote onRetry={retry} />}

      <div className="stack">
        <section className="plate settings-form">
          <h2 className="panel-title">YouTube &amp; Google Bağlantısı</h2>
          {loadError && (
            <div className="action-error" role="alert">
              Ayarlar okunamadı: {loadError}. Veritabanı hazır olduğunda bu
              ekran yapılandırma formuna döner.
            </div>
          )}
          {!view && !loadError && (
            <p className="plate-note">Ayarlar okunuyor…</p>
          )}
          {view && form && (
            <>
              <p className="plate-note">
                Bu ekrandan kaydedilen değerler veritabanında saklanır ve
                ortam değişkenlerinin önüne geçer. Gizli değerler bir kez
                kaydedildikten sonra geri okunmaz — yalnızca son dört
                karakteri gösterilir.
              </p>
              <div className="settings-grid">
                {PLAIN_FIELDS.map(({ key, label, help }) => (
                  <div className="field" key={key}>
                    <label htmlFor={`set-${key}`}>
                      {label}
                      <span className="source-badge">
                        {SOURCE_LABEL[view[key].source]}
                      </span>
                    </label>
                    <input
                      id={`set-${key}`}
                      value={form.plain[key]}
                      onChange={(e) => setPlain(key, e.target.value)}
                      autoComplete="off"
                    />
                    {help && <span className="field-help">{help}</span>}
                  </div>
                ))}
                <div className="field">
                  <label htmlFor="set-quota">
                    Günlük Kota Birimi
                    <span className="source-badge">
                      {SOURCE_LABEL[view.daily_quota_units.source]}
                    </span>
                  </label>
                  <input
                    id="set-quota"
                    className="nums"
                    type="number"
                    min={1}
                    value={form.quota}
                    onChange={(e) => setQuota(e.target.value)}
                  />
                  <span className="field-help">
                    YouTube Data API için günlük birim bütçesi (varsayılan
                    10000).
                  </span>
                </div>
                {SECRET_FIELDS.map(({ key, label, help, warning }) => (
                  <div className="field" key={key}>
                    <label htmlFor={`set-${key}`}>
                      {label}
                      <span className="source-badge">
                        {view[key].configured
                          ? `ayarlı · ••••${view[key].hint}`
                          : SOURCE_LABEL[view[key].source]}
                      </span>
                    </label>
                    <div className="secret-row">
                      <input
                        id={`set-${key}`}
                        type="password"
                        placeholder={
                          view[key].configured
                            ? 'Değiştirmek için yeni değeri yazın'
                            : 'Henüz ayarlanmadı'
                        }
                        value={form.secrets[key]}
                        onChange={(e) => setSecret(key, e.target.value)}
                        autoComplete="new-password"
                      />
                      {view[key].source === 'database' && (
                        <button
                          type="button"
                          className="btn--ghost"
                          onClick={() => void clearSecret(key)}
                        >
                          Sıfırla
                        </button>
                      )}
                    </div>
                    {help && <span className="field-help">{help}</span>}
                    {warning && <span className="field-warn">{warning}</span>}
                  </div>
                ))}
              </div>
              <div className="settings-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={saveState.kind === 'saving'}
                  onClick={() => void save()}
                >
                  {saveState.kind === 'saving' ? 'Kaydediliyor…' : 'Ayarları Kaydet'}
                </button>
                {saveState.kind === 'saved' && (
                  <span className="save-ok" role="status">
                    Kaydedildi.
                  </span>
                )}
                {saveState.kind === 'error' && (
                  <span className="save-error" role="alert">
                    {saveState.message}
                  </span>
                )}
              </div>
            </>
          )}
        </section>

        {state.status === 'loading' && <LoadingState label="Bilgiler okunuyor…" />}
        {state.status === 'error' && (
          <ErrorState
            title="Bilgiler alınamadı"
            message={`Arka uca ulaşılamadı: ${state.message}.`}
            onRetry={retry}
          />
        )}
        {state.status === 'ok' && (
          <section className="ink-panel" style={{ maxWidth: 720 }}>
            <h2>Sistem</h2>
            <table className="info-table">
              <tbody>
                <tr>
                  <th>Sürüm</th>
                  <td className="nums">v{state.data.version}</td>
                </tr>
                <tr>
                  <th>Ortam</th>
                  <td>{state.data.app_env}</td>
                </tr>
                <tr>
                  <th>Durum</th>
                  <td>{PHASE_LABEL[state.data.phase] ?? state.data.phase}</td>
                </tr>
                <tr>
                  <th>Veritabanı</th>
                  <td>
                    {state.data.database === 'reachable'
                      ? 'Bağlı (PostgreSQL)'
                      : state.data.database === 'unreachable'
                        ? 'Erişilemiyor'
                        : 'Yapılandırılmadı'}
                  </td>
                </tr>
                <tr>
                  <th>Güncelleme</th>
                  <td>
                    main dalına push edildiğinde GHCR imajları otomatik
                    derlenir; CasaOS’ta uygulamayı yeniden başlatmak yeterli.
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
        )}
      </div>
    </>
  )
}
