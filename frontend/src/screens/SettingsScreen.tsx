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
import {
  SubtitlePreview,
} from '../components/SubtitlePreview'
import { WhisperInstallControl } from '../components/WhisperInstallControl'

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
  | 'clip_min_seconds'
  | 'clip_max_seconds'
  | 'download_rate_limit_kbps'
  | 'planned_poll_interval_minutes'

type TabKey = 'connection' | 'production' | 'shorts' | 'horizontal' | 'system'

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: 'connection', label: 'Bağlantılar', hint: 'Google ve YouTube erişimi' },
  { key: 'production', label: 'Üretim', hint: 'Motor, limitler ve transkripsiyon' },
  { key: 'shorts', label: 'Shorts', hint: 'Dikey klipler: görünüm, altyazı ve oran' },
  { key: 'horizontal', label: 'Yatay video', hint: 'Yatay tam kesit ayarları' },
  { key: 'system', label: 'Sistem', hint: 'Sürüm ve çalışma ortamı' },
]

const NUMBER_FIELDS: {
  key: NumberKey
  label: string
  help: string
  min?: number
  group: 'engine' | 'shorts' | 'horizontal'
}[] = [
  {
    key: 'cpu_target_percent',
    label: 'CPU Hedefi (%)',
    help: 'Üzerine çıkılırsa worker yeni iş almaz, bekler. 0 = kapalı.',
    min: 0,
    group: 'engine',
  },
  {
    key: 'ram_target_percent',
    label: 'RAM Hedefi (%)',
    help: 'Üzerine çıkılırsa yeni işler bekler. 0 = kapalı.',
    min: 0,
    group: 'engine',
  },
  {
    key: 'ffmpeg_threads',
    label: 'FFmpeg İş Parçacığı',
    help: 'Render komutlarına -threads N olarak geçer. 0 = otomatik.',
    min: 0,
    group: 'engine',
  },
  {
    key: 'max_heavy_jobs',
    label: 'Eşzamanlı Ağır İş',
    help: 'Aynı anda en fazla kaç indirme/render koşar (varsayılan 1).',
    min: 1,
    group: 'engine',
  },
  {
    key: 'max_concurrent_jobs',
    label: 'Eşzamanlı İş (Toplam)',
    help: "Worker'ın aynı anda aldığı toplam iş sayısı.",
    min: 1,
    group: 'engine',
  },
  {
    key: 'retry_max_attempts',
    label: 'Yeniden Deneme Sayısı',
    help: 'Bir işin toplam deneme hakkı.',
    min: 1,
    group: 'engine',
  },
  {
    key: 'retry_backoff_seconds',
    label: 'Yeniden Deneme Beklemesi (sn)',
    help: 'Başarısız iş bu süre sonunda tekrar kuyruğa girer.',
    min: 0,
    group: 'engine',
  },
  {
    key: 'planned_poll_interval_minutes',
    label: 'Üretim Döngüsü (dk)',
    help: 'Stok kontrolü ve render beslemesinin çalışma aralığı.',
    min: 1,
    group: 'engine',
  },
  {
    key: 'download_rate_limit_kbps',
    label: 'İndirme Hız Limiti (KB/s)',
    help: 'yt-dlp --limit-rate olarak uygulanır. 0 = limitsiz.',
    min: 0,
    group: 'engine',
  },
  {
    key: 'shorts_per_video',
    label: 'Video Başına Shorts',
    help: 'Bir yatay videodan çıkarılacak en fazla Shorts sayısı.',
    min: 1,
    group: 'shorts',
  },
  {
    key: 'clip_min_seconds',
    label: 'Klip Süresi Alt Sınır (sn)',
    help: 'Motorun seçebileceği en kısa klip süresi.',
    min: 5,
    group: 'shorts',
  },
  {
    key: 'clip_max_seconds',
    label: 'Klip Süresi Üst Sınır (sn)',
    help: 'En uzun klip süresi (Shorts sınırı 180 sn). Süre esnek: an 1-2 dakika sürüyorsa klip de o kadar uzun seçilir.',
    min: 20,
    group: 'shorts',
  },
  {
    key: 'horizontal_stock_target_default',
    label: 'Yatay Stok Hedefi (Varsayılan)',
    help: 'Yeni kanal profillerine başlangıç değeri (genellikle 3).',
    min: 1,
    group: 'horizontal',
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

const DEFAULT_POS_X = 50
const DEFAULT_POS_Y = 78
const DEFAULT_WEBCAM_PERCENT = 35

/** Görev 1: beş seçilebilir stil — anahtarlar backend
 * subtitle_style.SUBTITLE_STYLES ile aynı sözleşme. */
const SUBTITLE_STYLE_OPTIONS = [
  { key: 'klasik', label: 'Klasik Beyaz' },
  { key: 'shorts_sari', label: 'Shorts Sarı' },
  { key: 'anton', label: 'Anton' },
  { key: 'kutu', label: 'Kutulu' },
  { key: 'noto', label: 'Noto Sans' },
]

interface FormState {
  plain: Record<PlainKey, string>
  secrets: Record<SecretKey, string>
  quota: string
  numbers: Record<NumberKey, string>
  method: string
  retention: string
  whisperModel: string
  whisperLanguage: string
  subtitleBurn: boolean
  subtitleFontSize: string
  subtitleStyleKey: string
  subtitlePosX: string
  subtitlePosY: string
  webcamPercent: string
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
    retention: String(view.media_retention_days.value),
    whisperModel: view.whisper_model.value,
    whisperLanguage: view.whisper_language.value,
    subtitleBurn: view.burn_subtitles.value,
    subtitleFontSize: String(view.subtitle_font_size.value),
    subtitleStyleKey: view.subtitle_style_preset.value || 'klasik',
    subtitlePosX: String(view.subtitle_pos_x_percent.value ?? DEFAULT_POS_X),
    subtitlePosY: String(view.subtitle_pos_y_percent.value ?? DEFAULT_POS_Y),
    webcamPercent: String(
      view.shorts_webcam_percent.value ?? DEFAULT_WEBCAM_PERCENT,
    ),
  }
}

export function SettingsScreen() {
  const fetcher = useCallback(() => fetchOverview(), [])
  const { state, retry } = usePolling(fetcher, 30000)

  const [view, setView] = useState<SettingsView | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [tab, setTab] = useState<TabKey>('connection')
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
    const retention = Number(form.retention)
    if (
      Number.isInteger(retention) &&
      retention !== view.media_retention_days.value
    ) {
      patch.media_retention_days = retention
    }
    if (form.whisperModel.trim() !== view.whisper_model.value) {
      patch.whisper_model = form.whisperModel.trim()
    }
    if (form.whisperLanguage.trim() !== view.whisper_language.value) {
      patch.whisper_language = form.whisperLanguage.trim()
    }
    if (form.subtitleBurn !== view.burn_subtitles.value) {
      patch.burn_subtitles = form.subtitleBurn
    }
    const subtitleSize = Number(form.subtitleFontSize)
    if (
      Number.isFinite(subtitleSize) &&
      subtitleSize !== view.subtitle_font_size.value
    ) {
      patch.subtitle_font_size = subtitleSize
    }
    if (form.subtitleStyleKey !== view.subtitle_style_preset.value) {
      patch.subtitle_style_preset = form.subtitleStyleKey
    }
    const posX = Number(form.subtitlePosX)
    if (
      Number.isFinite(posX) &&
      posX !== view.subtitle_pos_x_percent.value
    ) {
      patch.subtitle_pos_x_percent = posX
    }
    const posY = Number(form.subtitlePosY)
    if (
      Number.isFinite(posY) &&
      posY !== view.subtitle_pos_y_percent.value
    ) {
      patch.subtitle_pos_y_percent = posY
    }
    const webcamPercent = Number(form.webcamPercent)
    if (
      Number.isInteger(webcamPercent) &&
      webcamPercent !== view.shorts_webcam_percent.value
    ) {
      patch.shorts_webcam_percent = webcamPercent
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

  const activeTab = TABS.find((t) => t.key === tab) ?? TABS[0]

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>Ayarlar</h1>
          <span className="screen-sub">{activeTab.hint}</span>
        </div>
      </div>

      {state.status === 'ok' && state.stale && <StaleNote onRetry={retry} />}

      <div className="stack">
        <div className="settings-tabs" role="tablist" aria-label="Ayar kategorileri">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`settings-tab${tab === key ? ' settings-tab--active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {loadError && (
          <div className="action-error" role="alert" style={{ margin: '16px 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>Ayarlar okunamadı: {loadError}.</span>
            <button
              type="button"
              className="btn btn--ghost btn-sm"
              onClick={() => void loadSettings()}
            >
              Yeniden Dene
            </button>
          </div>
        )}

        {tab === 'connection' && (
          <section className="plate settings-form" aria-label="Bağlantı ayarları">
            <h2 className="panel-title">YouTube &amp; Google Bağlantısı</h2>
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
                  {PLAIN_FIELDS.filter((f) => f.key !== 'metadata_system_prompt').map(({ key, label, help }) => (
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
                  {PLAIN_FIELDS.filter((f) => f.key === 'metadata_system_prompt').map(({ key, label, help, multiline }) => (
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
                      <textarea
                        id={`set-${key}`}
                        rows={4}
                        value={form.plain[key]}
                        onChange={(e) => setPlain(key, e.target.value)}
                        autoComplete="off"
                      />
                      {help && <span className="field-help">{help}</span>}
                    </div>
                  ))}
                </div>
                <SaveBar saveState={saveState} onSave={() => void save()} />
              </>
            )}
          </section>
        )}

        {tab === 'production' && (
          <section className="plate settings-form" aria-label="Üretim ayarları">
            <h2 className="panel-title">Üretim ve Limitler</h2>
            {!view && !loadError && <p className="plate-note">Ayarlar okunuyor…</p>}
            {view && form && (
              <>
                <p className="plate-note">
                  Bu değerler otomasyon motorunu doğrudan yönetir: worker her
                  döngüde yeniden okur, yeniden başlatma gerekmez. Pi'nin
                  8 GB RAM sınırı için varsayılanlar muhafazakârdır.
                </p>
                <h3 className="settings-group-title">Motor ve İş Limitleri</h3>
                <div className="settings-grid">
                  {NUMBER_FIELDS.filter((f) => f.group === 'engine').map(({ key, label, help, min }) => (
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
                </div>
                <h3 className="settings-group-title">Medya Temizliği</h3>
                <div className="settings-grid">
                  <div className="field">
                    <label htmlFor="set-retention">
                      Yayınlanan videoların temizliği
                      <span className="source-badge">
                        {SOURCE_LABEL[view.media_retention_days.source]}
                      </span>
                    </label>
                    <select
                      id="set-retention"
                      value={form.retention}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, retention: e.target.value } : f))
                      }
                    >
                      <option value="0">Yayınladıktan hemen sonra</option>
                      <option value="1">1 gün sonra</option>
                      <option value="3">3 gün sonra</option>
                      <option value="7">7 gün sonra</option>
                      <option value="14">14 gün sonra</option>
                      <option value="30">30 gün sonra</option>
                      <option value="-1">Hiçbir zaman</option>
                    </select>
                    <span className="field-help">
                      Video YouTube'da herkese açık yapıldıktan sonra yerel
                      dosyası diskten silinir; kayıt ve denetim izi kalır.
                      Varsayılan: yayınladıktan hemen sonra.
                    </span>
                  </div>
                </div>
                <h3 className="settings-group-title">Transkripsiyon</h3>
                <div className="settings-grid">
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
                        Yalnızca YouTube altyazısı (hızlı)
                      </option>
                      <option value="whisper">
                        Her zaman Whisper (temiz metin, yavaş)
                      </option>
                    </select>
                    <span className="field-help">
                      Whisper seçiliyken YouTube altyazısı kullanılmaz;
                      metin her zaman yerel Whisper ile yazılır (yalnızca
                      Whisper hata verirse YouTube altyazısına düşer).
                      Kurulumu aşağıdaki düğmeyle yapabilirsiniz.
                    </span>
                    <WhisperInstallControl />
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
                          Küçük sunucularda tiny önerilir; büyük modeller
                          RAM'i zorlar.
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
                          id={`set-whisper-lang`}
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
                <SaveBar saveState={saveState} onSave={() => void save()} />
              </>
            )}
          </section>
        )}

        {tab === 'shorts' && (
          <section className="plate settings-form" aria-label="Shorts ayarları">
            <h2 className="panel-title">Shorts (Dikey Klipler)</h2>
            {!view && !loadError && <p className="plate-note">Ayarlar okunuyor…</p>}
            {view && form && (
              <>
                <p className="plate-note">
                  Dikey kliplerin nasıl üretileceğini ve nasıl
                  görüneceğini yönetir: klip sayısı ve süresi, webcam
                  oranı, altyazı stili ve konumu. Kaydettiğinde bir
                  sonraki render'dan itibaren uygulanır.
                </p>
                <h3 className="settings-group-title">Klip Üretimi</h3>
                <div className="settings-grid">
                  {NUMBER_FIELDS.filter((f) => f.group === 'shorts').map(({ key, label, help, min }) => (
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
                </div>
                <h3 className="settings-group-title">Görünüm ve Altyazı</h3>
                <div className="subtitle-settings">
                  <div className="settings-grid">
                    <div className="field">
                      <label htmlFor="set-webcam-percent">
                        Webcam / Video Oranı
                        <span className="source-badge">
                          {SOURCE_LABEL[view.shorts_webcam_percent.source]}
                        </span>
                      </label>
                      <div className="range-row">
                        <input
                          id="set-webcam-percent"
                          type="range"
                          min={20}
                          max={50}
                          step={5}
                          value={form.webcamPercent}
                          onChange={(e) =>
                            setForm((f) =>
                              f ? { ...f, webcamPercent: e.target.value } : f,
                            )
                          }
                        />
                        <span className="nums">
                          W %{form.webcamPercent} · V %
                          {100 - (Number(form.webcamPercent) || DEFAULT_WEBCAM_PERCENT)}
                        </span>
                      </div>
                      <span className="field-help">
                        Webcam üst bölümünün kadran yüksekliğinden alacağı pay
                        (varsayılan %35). Dikdörtgen zoom'suz, en-boy oranı
                        korunarak bölüme tam oturur; kalan alan videoya kalır.
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="set-subtitle-burn">
                        Altyazı Gömme
                        <span className="source-badge">
                          {SOURCE_LABEL[view.burn_subtitles.source]}
                        </span>
                      </label>
                      <label className="check-row">
                        <input
                          id="set-subtitle-burn"
                          type="checkbox"
                          checked={form.subtitleBurn}
                          onChange={(e) =>
                            setForm((f) =>
                              f ? { ...f, subtitleBurn: e.target.checked } : f,
                            )
                          }
                        />
                        <span>Dikey kliplere altyazı göm</span>
                      </label>
                      <span className="field-help">
                        Transkripti olmayan videolar (mevcut altyazı da
                        Whisper da yoksa) altyazısız çıkar; akış durmaz.
                      </span>
                    </div>
                    <div className="field field--wide">
                      <span className="field-label">Yazı Stili</span>
                      <div className="style-options" role="radiogroup" aria-label="Altyazı yazı stili">
                        {SUBTITLE_STYLE_OPTIONS.map(({ key, label }) => (
                          <button
                            key={key}
                            type="button"
                            role="radio"
                            aria-checked={form.subtitleStyleKey === key}
                            className={`style-option${form.subtitleStyleKey === key ? ' style-option--active' : ''}`}
                            onClick={() =>
                              setForm((f) =>
                                f ? { ...f, subtitleStyleKey: key } : f,
                              )
                            }
                          >
                            <StyleSample styleKey={key} />
                            <span className="style-option-label">{label}</span>
                          </button>
                        ))}
                      </div>
                      <span className="field-help">
                        Stil, altyazının klipte nasıl görüneceğini belirler;
                        yanındaki önizleme seçimi anında yansıtır.
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="set-subtitle-size">
                        Yazı Boyutu
                        <span className="source-badge">
                          {SOURCE_LABEL[view.subtitle_font_size.source]}
                        </span>
                      </label>
                      <div className="range-row">
                        <input
                          id="set-subtitle-size"
                          type="range"
                          min={24}
                          max={140}
                          step={2}
                          value={form.subtitleFontSize}
                          onChange={(e) =>
                            setForm((f) =>
                              f ? { ...f, subtitleFontSize: e.target.value } : f,
                            )
                          }
                        />
                        <span className="nums">{form.subtitleFontSize}</span>
                      </div>
                      <span className="field-help">
                        1080x1920 çıktıda piksel cinsinden yazı yüksekliği
                        (varsayılan 64).
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="set-subtitle-x">
                        Yatay Konum
                        <span className="source-badge">
                          {SOURCE_LABEL[view.subtitle_pos_x_percent.source]}
                        </span>
                      </label>
                      <div className="range-row">
                        <input
                          id="set-subtitle-x"
                          type="range"
                          min={0}
                          max={100}
                          step={1}
                          value={form.subtitlePosX}
                          onChange={(e) =>
                            setForm((f) =>
                              f ? { ...f, subtitlePosX: e.target.value } : f,
                            )
                          }
                        />
                        <span className="nums">%{form.subtitlePosX}</span>
                      </div>
                      <span className="field-help">
                        50 = tam ortada; altyazı çapası bu orana taşınır.
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="set-subtitle-y">
                        Dikey Konum
                        <span className="source-badge">
                          {SOURCE_LABEL[view.subtitle_pos_y_percent.source]}
                        </span>
                      </label>
                      <div className="range-row">
                        <input
                          id="set-subtitle-y"
                          type="range"
                          min={0}
                          max={100}
                          step={1}
                          value={form.subtitlePosY}
                          onChange={(e) =>
                            setForm((f) =>
                              f ? { ...f, subtitlePosY: e.target.value } : f,
                            )
                          }
                        />
                        <span className="nums">%{form.subtitlePosY}</span>
                      </div>
                      <span className="field-help">
                        Varsayılan %78, Shorts'un altyazı standardı (alt-orta,
                        kamera bölümünün altında).<br />
                        <button
                          type="button"
                          className="btn--ghost"
                          onClick={() =>
                            setForm((f) =>
                              f
                                ? {
                                    ...f,
                                    subtitlePosX: String(DEFAULT_POS_X),
                                    subtitlePosY: String(DEFAULT_POS_Y),
                                  }
                                : f,
                            )
                          }
                        >
                          Shorts varsayılanına dön
                        </button>
                      </span>
                    </div>
                  </div>
                  <SubtitlePreview
                    burn={form.subtitleBurn}
                    fontSizePx={Number(form.subtitleFontSize) || 64}
                    styleKey={form.subtitleStyleKey}
                    posX={Number(form.subtitlePosX) || DEFAULT_POS_X}
                    posY={Number(form.subtitlePosY) || DEFAULT_POS_Y}
                    webcamPercent={
                      Number(form.webcamPercent) || DEFAULT_WEBCAM_PERCENT
                    }
                  />
                </div>
                <SaveBar saveState={saveState} onSave={() => void save()} />
              </>
            )}
          </section>
        )}

        {tab === 'horizontal' && (
          <section className="plate settings-form" aria-label="Yatay video ayarları">
            <h2 className="panel-title">Yatay Video (Tam Kesit)</h2>
            {!view && !loadError && <p className="plate-note">Ayarlar okunuyor…</p>}
            {view && form && (
              <>
                <p className="plate-note">
                  Tepki videolarının yatay tam kesitleri 1920x1080
                  ölçek+padsiyle üretilir; altyazı yatay kesitlerde asla
                  gömülmez ve ses korunur. Motor stok hedefine göre
                  yatay kesit hazırlar, yayın planı kanal ayarlarından
                  yönetilir.
                </p>
                <div className="settings-grid">
                  {NUMBER_FIELDS.filter((f) => f.group === 'horizontal').map(({ key, label, help, min }) => (
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
                </div>
                <div className="plate-note">
                  Günlük yatay yayın limiti ve hazırlık durumu kanal
                  profilinine aittir; kanalın Yönetim sayfasından
                  değiştirilir.
                </div>
                <SaveBar saveState={saveState} onSave={() => void save()} />
              </>
            )}
          </section>
        )}

        {tab === 'system' && (
          <>
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
                        main dalına push edildiğinde imajlar otomatik
                        derlenir; uygulamayı yeniden başlatmak yeterli.
                      </td>
                    </tr>
                  </tbody>
                </table>
              </section>
            )}
          </>
        )}
      </div>
    </>
  )
}

function SaveBar({
  saveState,
  onSave,
}: {
  saveState: { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string }
  onSave: () => void
}) {
  return (
    <div className="settings-actions">
      <button
        type="button"
        className="btn"
        disabled={saveState.kind === 'saving'}
        onClick={onSave}
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
  )
}

/** Stil kartındaki mini örnek — SubtitlePreview ile aynı CSS karşılıkları. */
function StyleSample({ styleKey }: { styleKey: string }) {
  const configs: Record<string, React.CSSProperties> = {
    klasik: {
      color: '#fff',
      fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
      textShadow: '0 1px 0 #000, 1px 0 0 #000, -1px 0 0 #000, 0 -1px 0 #000',
    },
    shorts_sari: {
      color: '#ffee00',
      fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
      fontWeight: 700,
      textShadow: '0 1px 0 #000, 1px 0 0 #000, -1px 0 0 #000, 0 -1px 0 #000',
    },
    anton: {
      color: '#fff',
      fontFamily: "'Anton', sans-serif",
      textShadow: '0 1px 0 #000, 1px 0 0 #000, -1px 0 0 #000, 0 -1px 0 #000',
      letterSpacing: '0.02em',
    },
    kutu: {
      color: '#fff',
      fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
      fontWeight: 700,
      background: 'rgba(0, 0, 0, 0.6)',
      padding: '1px 7px',
      borderRadius: 4,
    },
    noto: {
      color: '#fff',
      fontFamily: "'Noto Sans', sans-serif",
      textShadow: '0 1px 0 #000',
    },
  }
  return (
    <span className="style-sample" aria-hidden="true" style={configs[styleKey]}>
      Aa
    </span>
  )
}
