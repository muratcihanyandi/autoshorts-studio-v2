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

type PlainKey =
  | 'google_client_id'
  | 'oauth_redirect_base'
  | 'frontend_base_url'
  | 'metadata_system_prompt'
type SecretKey =
  | 'google_client_secret'
  | 'token_encryption_key'
  | 'youtube_api_key'

/** Sayısal üretim ayarları (worker her döngüde yeniden okur). */
type NumberKey =
  | 'cpu_target_percent'
  | 'ram_target_percent'
  | 'ffmpeg_threads'
  | 'max_heavy_jobs'
  | 'max_concurrent_jobs'
  | 'retry_max_attempts'
  | 'retry_backoff_seconds'
  | 'horizontal_stock_target_default'
  | 'shorts_per_video'
  | 'download_rate_limit_kbps'
  | 'planned_poll_interval_minutes'



const NUMBER_FIELDS: {
  key: NumberKey
  label: string
  help: string
  min?: number
}[] = [
  {
    key: 'cpu_target_percent',
    label: 'CPU Hedefi (%)',
    help: 'Üzerine çıkılırsa worker yeni iş almaz, bekler. 0 = kapalı.',
    min: 0,
  },
  {
    key: 'ram_target_percent',
    label: 'RAM Hedefi (%)',
    help: 'Üzerine çıkılırsa yeni işler bekler. 0 = kapalı.',
    min: 0,
  },
  {
    key: 'ffmpeg_threads',
    label: 'FFmpeg İş Parçacığı',
    help: 'Render komutlarına -threads N olarak geçer. 0 = otomatik.',
    min: 0,
  },
  {
    key: 'max_heavy_jobs',
    label: 'Eşzamanlı Ağır İş',
    help: 'Aynı anda en fazla kaç indirme/render koşar (varsayılan 1).',
    min: 1,
  },
  {
    key: 'max_concurrent_jobs',
    label: 'Eşzamanlı İş (Toplam)',
    help: "Worker'ın aynı anda aldığı toplam iş sayısı.",
    min: 1,
  },
  {
    key: 'retry_max_attempts',
    label: 'Yeniden Deneme Sayısı',
    help: 'Bir işin toplam deneme hakkı.',
    min: 1,
  },
  {
    key: 'retry_backoff_seconds',
    label: 'Yeniden Deneme Beklemesi (sn)',
    help: 'Başarısız iş bu süre sonunda tekrar kuyruğa girer.',
    min: 0,
  },
  {
    key: 'horizontal_stock_target_default',
    label: 'Yatay Stok Hedefi (Varsayılan)',
    help: 'Yeni kanal profillerine başlangıç değeri (genellikle 3).',
    min: 1,
  },
  {
    key: 'shorts_per_video',
    label: 'Video Başına Shorts',
    help: 'Bir yatay videodan çıkarılacak en fazla Shorts sayısı.',
    min: 1,
  },
  {
    key: 'download_rate_limit_kbps',
    label: 'İndirme Hız Limiti (KB/s)',
    help: 'yt-dlp --limit-rate olarak uygulanır. 0 = limitsiz.',
    min: 0,
  },
  {
    key: 'planned_poll_interval_minutes',
    label: 'Üretim Döngüsü (dk)',
    help: 'Stok kontrolü ve render beslemesinin çalışma aralığı.',
    min: 1,
  },
]

const PLAIN_FIELDS: {
  key: PlainKey
  label: string
  help?: string
  multiline?: boolean
}[] = [
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
  {
    key: 'metadata_system_prompt',
    label: 'Metaveri Sistem Promptu (Genel)',
    help: 'Yapay zeka başlık/hook/açıklama/etiket üretiminde kullanılır; karakter promptu varsa onu geçer.',
    multiline: true,
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
  numbers: Record<NumberKey, string>
  method: string
  whisperModel: string
  whisperLanguage: string
}

function initForm(view: SettingsView): FormState {
  const numbers = {} as Record<NumberKey, string>
  for (const { key } of NUMBER_FIELDS) {
    numbers[key] = String(view[key].value)
  }
  return {
    plain: {
      google_client_id: view.google_client_id.value,
      oauth_redirect_base: view.oauth_redirect_base.value,
      frontend_base_url: view.frontend_base_url.value,
      metadata_system_prompt: view.metadata_system_prompt.value,
    },
    secrets: {
      google_client_secret: '',
      token_encryption_key: '',
      youtube_api_key: '',
    },
    quota: String(view.daily_quota_units.value),
    numbers,
    method: view.transcription_method.value || 'sidecar',
    whisperModel: view.whisper_model.value,
    whisperLanguage: view.whisper_language.value,
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
  const setNumber = (key: NumberKey, value: string) => {
    setForm((f) =>
      f ? { ...f, numbers: { ...f.numbers, [key]: value } } : f,
    )
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
    for (const { key } of NUMBER_FIELDS) {
      const value = Number(form.numbers[key])
      if (Number.isFinite(value) && value !== view[key].value) {
        patch[key] = value
      }
    }
    if (form.method !== view.transcription_method.value) {
      patch.transcription_method = form.method
    }
    if (form.whisperModel.trim() !== view.whisper_model.value) {
      patch.whisper_model = form.whisperModel.trim()
    }
    if (form.whisperLanguage.trim() !== view.whisper_language.value) {
      patch.whisper_language = form.whisperLanguage.trim()
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
                {PLAIN_FIELDS.map(({ key, label, help, multiline }) => (
                  <div
                    className={multiline ? 'field field--wide' : 'field'}
                    key={key}
                  >
                    <label htmlFor={`set-${key}`}>
                      {label}
                      <span className="source-badge">
                        {SOURCE_LABEL[view[key].source]}
                      </span>
                    </label>
                    {multiline ? (
                      <textarea
                        id={`set-${key}`}
                        rows={4}
                        value={form.plain[key]}
                        onChange={(e) => setPlain(key, e.target.value)}
                        autoComplete="off"
                      />
                    ) : (
                      <input
                        id={`set-${key}`}
                        value={form.plain[key]}
                        onChange={(e) => setPlain(key, e.target.value)}
                        autoComplete="off"
                      />
                    )}
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

        <section className="plate settings-form">
          <h2 className="panel-title">Kaynak Limitleri ve Üretim</h2>
          {!view && <p className="plate-note">Ayarlar okunuyor…</p>}
          {view && form && (
            <>
              <p className="plate-note">
                Bu değerler otomasyon motorunu doğrudan yönetir: worker her
                döngüde yeniden okur, yeniden başlatma gerekmez. Pi'nin
                8 GB RAM sınırı için varsayılanlar muhafazakârdır.
              </p>
              <div className="settings-grid">
                {NUMBER_FIELDS.map(({ key, label, help, min }) => (
                  <div className="field" key={key}>
                    <label htmlFor={`set-${key}`}>
                      {label}
                      <span className="source-badge">
                        {SOURCE_LABEL[view[key].source]}
                      </span>
                    </label>
                    <input
                      id={`set-${key}`}
                      className="nums"
                      type="number"
                      min={min ?? 0}
                      value={form.numbers[key]}
                      onChange={(e) => setNumber(key, e.target.value)}
                    />
                    <span className="field-help">{help}</span>
                  </div>
                ))}
                <div className="field">
                  <label htmlFor="set-method">
                    Transkripsiyon Yöntemi
                    <span className="source-badge">
                      {SOURCE_LABEL[view.transcription_method.source]}
                    </span>
                  </label>
                  <select
                    id="set-method"
                    value={form.method}
                    onChange={(e) =>
                      setForm((f) => (f ? { ...f, method: e.target.value } : f))
                    }
                  >
                    <option value="sidecar">
                      Yalnızca mevcut altyazı (hafif)
                    </option>
                    <option value="whisper">
                      Eksik altyazıda Whisper (yerel, ağır)
                    </option>
                  </select>
                  <span className="field-help">
                    Whisper, sunucuda whisper CLI kuruluysa çalışır; kurulum
                    gerektirir. Varsayılan hafif moddur.
                  </span>
                </div>
                {form.method === 'whisper' && (
                  <>
                    <div className="field">
                      <label htmlFor="set-whisper-model">
                        Whisper Modeli
                        <span className="source-badge">
                          {SOURCE_LABEL[view.whisper_model.source]}
                        </span>
                      </label>
                      <select
                        id="set-whisper-model"
                        value={form.whisperModel}
                        onChange={(e) =>
                          setForm((f) =>
                            f ? { ...f, whisperModel: e.target.value } : f,
                          )
                        }
                      >
                        <option value="tiny">tiny (en hızlı)</option>
                        <option value="base">base</option>
                        <option value="small">small</option>
                      </select>
                      <span className="field-help">
                        Pi 5 için tiny önerilir; büyük modeller RAM'i zorlar.
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="set-whisper-lang">
                        Whisper Dili
                        <span className="source-badge">
                          {SOURCE_LABEL[view.whisper_language.source]}
                        </span>
                      </label>
                      <input
                        id="set-whisper-lang"
                        value={form.whisperLanguage}
                        onChange={(e) =>
                          setForm((f) =>
                            f ? { ...f, whisperLanguage: e.target.value } : f,
                          )
                        }
                      />
                    </div>
                  </>
                )}
                <div className="field field--wide">
                  <label>Medya Dizinini (Konteyner İçi)</label>
                  <input value={view.media_root.value} readOnly disabled />
                  <span className="field-help">
                    Compose ortam değişkeniyle belirlenir; kalıcı disk
                    birimine bağlıdır. Değiştirmek için dağıtım dosyasını
                    güncelleyin.
                  </span>
                </div>
              </div>
              <div className="settings-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={saveState.kind === 'saving'}
                  onClick={() => void save()}
                >
                  {saveState.kind === 'saving' ? 'Kaydediliyor…' : 'Limitleri Kaydet'}
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
