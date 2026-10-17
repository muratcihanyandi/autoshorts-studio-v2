import { useCallback, useState } from 'react'
import {
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmLogs,
  fetchLlmProviders,
  PROVIDER_TYPE_LABEL,
  STATUS_LABEL,
  testLlmProvider,
  updateLlmProvider,
  type LlmProvider,
  type LlmTestResult,
} from '../api/llm'
import { usePolling } from '../hooks/usePolling'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

const EMPTY_FORM = {
  name: '',
  provider_type: 'openai',
  api_base: '',
  model_id: '',
  api_key: '',
  priority: '1',
  timeout_seconds: '30',
  max_retries: '0',
}

export function LlmProvidersScreen() {
  const fetcher = useCallback(() => fetchLlmProviders(), [])
  const { state, retry } = usePolling(fetcher, 15000)
  const logsFetcher = useCallback(() => fetchLlmLogs(), [])
  const logs = usePolling(logsFetcher, 15000)

  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [testResults, setTestResults] = useState<Record<number, LlmTestResult>>(
    {},
  )

  const set = (key: keyof typeof EMPTY_FORM, value: string) =>
    setForm((f) => ({ ...f, [key]: value }))

  const submit = async () => {
    setSaving(true)
    setFormError(null)
    try {
      await createLlmProvider({
        name: form.name.trim(),
        provider_type: form.provider_type as LlmProvider['provider_type'],
        api_base: form.api_base.trim(),
        model_id: form.model_id.trim(),
        api_key: form.api_key.trim(),
        priority: Number(form.priority),
        timeout_seconds: Number(form.timeout_seconds),
        max_retries: Number(form.max_retries),
        enabled: true,
      })
      setForm({ ...EMPTY_FORM })
      retry()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'bilinmeyen hata')
    } finally {
      setSaving(false)
    }
  }

  const toggleEnabled = async (provider: LlmProvider) => {
    try {
      await updateLlmProvider(provider.id, { enabled: !provider.enabled })
      retry()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'bilinmeyen hata')
    }
  }

  const remove = async (id: number) => {
    try {
      await deleteLlmProvider(id)
      setConfirmDelete(null)
      retry()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'bilinmeyen hata')
    }
  }

  const runTest = async (id: number) => {
    try {
      const result = await testLlmProvider(id)
      setTestResults((prev) => ({ ...prev, [id]: result }))
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'bilinmeyen hata')
    }
  }

  return (
    <>
      <div className="screen-head">
        <h1>LLM SAĞLAYICILARI</h1>
        <span className="screen-sub">Ana sağlayıcı + iki yedek, sınırlı geçiş</span>
      </div>

      {state.status === 'loading' && <LoadingState label="Sağlayıcılar okunuyor…" />}
      {state.status === 'error' && (
        <ErrorState
          title="Sağlayıcılar alınamadı"
          message={`Arka uca ulaşılamadı: ${state.message}.`}
          onRetry={retry}
        />
      )}
      {state.status === 'ok' && (
        <>
          {state.stale && <StaleNote onRetry={retry} />}
          <div className="stack">
            <section className="plate">
              <h2 className="panel-title">KAYITLI SAĞLAYICILAR</h2>
              {state.data.providers.length === 0 ? (
                <p className="plate-note">
                  Henüz sağlayıcı yok. Altyazı düzeltme ve metaveri üretimi
                  için bir ana, en fazla iki yedek sağlayıcı ekleyin. Ana
                  sağlayıcı hata verirse sistem otomatik yedeğe geçer.
                </p>
              ) : (
                <table className="info-table llm-table">
                  <tbody>
                    {state.data.providers.map((p) => {
                      const test = testResults[p.id]
                      return (
                        <tr key={p.id}>
                          <th>
                            {p.name}
                            <span className="source-badge">
                              {p.enabled
                                ? `öncelik ${p.priority}`
                                : 'devre dışı'}
                            </span>
                          </th>
                          <td>
                            <div className="llm-provider-info">
                              <span className="llm-meta">
                                {PROVIDER_TYPE_LABEL[p.provider_type]} ·{' '}
                                {p.model_id}
                              </span>
                              <span className="llm-meta">
                                anahtar{' '}
                                {p.api_key.configured
                                  ? `••••${p.api_key.hint}`
                                  : 'yok'}
                                {' · '}zaman aşımı {p.timeout_seconds}sn
                                {' · '}tekrar {p.max_retries}
                              </span>
                              {test && (
                                <span
                                  className={
                                    test.status === 'success'
                                      ? 'save-ok'
                                      : 'save-error'
                                  }
                                  role="status"
                                >
                                  Deneme:{' '}
                                  {STATUS_LABEL[test.status] ?? test.status}
                                  {' · '}
                                  {test.latency_ms} ms
                                  {test.status !== 'success' &&
                                    ` · ${test.detail}`}
                                </span>
                              )}
                            </div>
                            <div className="channel-actions">
                              <button
                                type="button"
                                className="btn--ghost"
                                onClick={() => void runTest(p.id)}
                              >
                                Dene
                              </button>
                              <button
                                type="button"
                                className="btn--ghost"
                                onClick={() => void toggleEnabled(p)}
                              >
                                {p.enabled ? 'Devre Dışı' : 'Etkinleştir'}
                              </button>
                              {confirmDelete === p.id ? (
                                <>
                                  <button
                                    type="button"
                                    className="btn--danger"
                                    onClick={() => void remove(p.id)}
                                  >
                                    Silmeyi Onayla
                                  </button>
                                  <button
                                    type="button"
                                    className="btn--ghost"
                                    onClick={() => setConfirmDelete(null)}
                                  >
                                    Vazgeç
                                  </button>
                                </>
                              ) : (
                                <button
                                  type="button"
                                  className="btn--danger"
                                  onClick={() => setConfirmDelete(p.id)}
                                >
                                  Sil
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
              <p className="plate-note">
                {state.data.enabled} etkin / {state.data.total} kayıtlı · en
                fazla 3 sağlayıcı (ana + iki yedek)
              </p>
            </section>

            {state.data.providers.length < 3 && (
              <section className="plate new-channel">
                <h2 className="panel-title">YENİ SAĞLAYICI</h2>
                {formError && (
                  <div className="action-error" role="alert">
                    {formError}
                  </div>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    void submit()
                  }}
                >
                  <div className="settings-grid">
                    <div className="field">
                      <label htmlFor="llm-name">Ad</label>
                      <input
                        id="llm-name"
                        value={form.name}
                        onChange={(e) => set('name', e.target.value)}
                        required
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="llm-type">Tür</label>
                      <select
                        id="llm-type"
                        value={form.provider_type}
                        onChange={(e) => set('provider_type', e.target.value)}
                      >
                        <option value="openai">OpenAI uyumlu</option>
                        <option value="anthropic">Anthropic uyumlu</option>
                        <option value="google">Google uyumlu</option>
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor="llm-base">API Adresi</label>
                      <input
                        id="llm-base"
                        value={form.api_base}
                        onChange={(e) => set('api_base', e.target.value)}
                        placeholder="https://api.example.com/v1"
                        required
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="llm-model">Model Kimliği</label>
                      <input
                        id="llm-model"
                        value={form.model_id}
                        onChange={(e) => set('model_id', e.target.value)}
                        required
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="llm-key">API Anahtarı</label>
                      <input
                        id="llm-key"
                        type="password"
                        value={form.api_key}
                        onChange={(e) => set('api_key', e.target.value)}
                        autoComplete="new-password"
                        required
                      />
                      <span className="field-help">
                        Bir kez kaydedilir; şifrelenmiş saklanır ve asla geri
                        okunmaz.
                      </span>
                    </div>
                    <div className="field">
                      <label htmlFor="llm-priority">Öncelik (1 = ana)</label>
                      <input
                        id="llm-priority"
                        className="nums"
                        type="number"
                        min={1}
                        max={3}
                        value={form.priority}
                        onChange={(e) => set('priority', e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="llm-timeout">Zaman Aşımı (sn)</label>
                      <input
                        id="llm-timeout"
                        className="nums"
                        type="number"
                        min={1}
                        max={300}
                        value={form.timeout_seconds}
                        onChange={(e) => set('timeout_seconds', e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="llm-retries">Yeniden Deneme (0-3)</label>
                      <input
                        id="llm-retries"
                        className="nums"
                        type="number"
                        min={0}
                        max={3}
                        value={form.max_retries}
                        onChange={(e) => set('max_retries', e.target.value)}
                      />
                      <span className="field-help">
                        Yalnızca ağ/zaman aşımı hatalarında; bu sağlayıcının
                        toplam deneme sayısı.
                      </span>
                    </div>
                  </div>
                  <div className="settings-actions">
                    <button type="submit" className="btn" disabled={saving}>
                      {saving ? 'Ekleniyor…' : 'Sağlayıcı Ekle'}
                    </button>
                  </div>
                </form>
              </section>
            )}

            <section className="ink-panel">
              <h2>SON İSTEKLER</h2>
              {logs.state.status === 'ok' && logs.state.data.total === 0 && (
                <p className="plate-note">
                  Henüz istek yok. Sağlayıcı ekleyip “Dene” ile bağlantıyı
                  kontrol edin; her deneme buraya kaydedilir.
                </p>
              )}
              {logs.state.status === 'ok' && logs.state.data.total > 0 && (
                <table className="info-table">
                  <tbody>
                    {logs.state.data.logs.slice(0, 10).map((log) => (
                      <tr key={log.id}>
                        <th>{log.provider_name}</th>
                        <td className="nums">
                          {STATUS_LABEL[log.status] ?? log.status} ·{' '}
                          {log.latency_ms} ms
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>
        </>
      )}
    </>
  )
}
