import { useCallback, useEffect, useState } from 'react'

import {
  fetchLogErrors,
  fetchLogs,
  retryJob,
  type ErrorEntry,
  type LogEntry,
} from '../api/logs'
import { resumeSourceVideo } from '../api/media'
import { usePolling } from '../hooks/usePolling'
import { ErrorState, LoadingState, StaleNote } from '../components/States'

/** Olay tiplerinin Türkçe etiketleri; bilinmeyen tipler ham görünür. */
const EVENT_LABEL: Record<string, string> = {
  'automation.characters': 'Otomasyon karakterleri güncellendi',
  'channel.created': 'Kanal eklendi',
  'channel.updated': 'Kanal güncellendi',
  'channel.disconnected': 'Kanal bağlantısı kesildi',
  'channel.deleted': 'Kanal silindi',
  'character.created': 'Karakter eklendi',
  'character.updated': 'Karakter güncellendi',
  'character.photo_updated': 'Karakter fotoğrafı güncellendi',
  'character.deleted': 'Karakter silindi',
  'discovery.run': 'Kaynak keşfi çalıştı',
  'hype.evaluated': 'Hype değerlendirmesi tamamlandı',
  'hype.fallback': 'Hype skoru yedek değerle verildi',
  'llm.provider_created': 'LLM sağlayıcı eklendi',
  'llm.provider_updated': 'LLM sağlayıcı güncellendi',
  'llm.provider_duplicated': 'LLM sağlayıcı çoğaltıldı',
  'llm.provider_deleted': 'LLM sağlayıcı silindi',
  'media.download': 'Video indirildi',
  'media.inspect': 'Medya incelendi',
  'media.transcript': 'Transkript alındı',
  'media.analysis': 'Sahne analizi tamamlandı',
  'media.candidates': 'Klip adayları üretildi',
  'metadata.generated': 'Metaveri üretildi',
  'oauth.started': 'OAuth akışı başladı',
  'oauth.connected': 'Kanal bağlandı',
  'oauth.failed': 'OAuth akışı başarısız',
  'oauth.token_refreshed': 'Erişim anahtarı yenilendi',
  'oauth.token_refresh_failed': 'Erişim anahtarı yenilenemedi',
  'planning.run': 'Planlama çalıştı',
  'render.done': 'Klip render edildi',
  'render.review': 'Render incelemeye düştü',
  'settings.update': 'Ayarlar güncellendi',
  'source.added': 'Kaynak eklendi',
  'source.removed': 'Kaynak kaldırıldı',
  'source.video_added': 'Yeni kaynak videosu bulundu',
  'source.confirmed': 'Kaynak üretimi tamamlandı',
  'subtitle.corrected': 'Altyazı düzeltildi',
}

const CATEGORY_LABEL: Record<string, string> = {
  media: 'Medya',
  automation: 'Otomasyon',
  channel: 'Kanal',
  character: 'Karakter',
  discovery: 'Keşif',
  hype: 'Hype',
  llm: 'LLM',
  metadata: 'Metaveri',
  oauth: 'OAuth',
  planning: 'Planlama',
  render: 'Render',
  settings: 'Ayarlar',
  source: 'Kaynak',
  subtitle: 'Altyazı',
}

function eventLabel(eventType: string): string {
  return EVENT_LABEL[eventType] ?? eventType
}

function formatLogTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('tr-TR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return '—'
  }
}

/** Detay sözlüğünü okunabilir tek satıra indirir. */
function detailText(detail: Record<string, unknown> | null): string {
  if (!detail) return ''
  const parts: string[] = []
  for (const [key, value] of Object.entries(detail)) {
    if (value === null || value === undefined) continue
    parts.push(`${key}: ${String(value)}`)
  }
  return parts.join(' · ')
}

function LogRow({ entry }: { entry: LogEntry }) {
  return (
    <tr>
      <td className="nums">{formatLogTime(entry.ts)}</td>
      <td>
        {entry.channel_name ? (
          <span className="lib-channel">
            {entry.ribbon_color && (
              <i style={{ background: entry.ribbon_color }} aria-hidden="true" />
            )}
            {entry.channel_name}
          </span>
        ) : (
          '—'
        )}
      </td>
      <td>
        <div className="lib-title">
          <b>{eventLabel(entry.event_type)}</b>
          <small className="nums">{entry.event_type}</small>
        </div>
      </td>
      <td className="log-detail">{detailText(entry.detail) || '—'}</td>
    </tr>
  )
}

const STAGE_LABEL: Record<string, string> = {
  download: 'İndirme',
  inspect: 'İnceleme',
  transcript: 'Altyazı',
  analysis: 'Analiz',
  candidates: 'Adaylar',
}

/** Hata akışı satırı: tam hata metni + operatörün düzeltme düğmesi. */
function ErrorRow({
  entry,
  busy,
  onRetry,
  onResume,
}: {
  entry: ErrorEntry
  busy: boolean
  onRetry: (entry: ErrorEntry) => void
  onResume: (entry: ErrorEntry) => void
}) {
  const action =
    entry.kind === 'job' ? (
      <button
        type="button"
        className="btn--ghost"
        disabled={busy}
        onClick={() => onRetry(entry)}
        title="İşi taze deneme bütçeyle yeniden kuyruğa alır."
      >
        {busy ? 'Alınıyor…' : 'Tekrar dene'}
      </button>
    ) : entry.kind === 'asset' ? (
      <button
        type="button"
        className="btn--ghost"
        disabled={busy}
        onClick={() => onResume(entry)}
        title="Videoyu kaldığı aşamadan sürdürür."
      >
        {busy ? 'Sürdürülüyor…' : 'Kaldığı yerden sürdür'}
      </button>
    ) : null
  return (
    <tr>
      <td className="nums">{formatLogTime(entry.ts)}</td>
      <td>
        <div className="lib-title">
          <b>{entry.what}</b>
          {entry.stage && (
            <small>· {STAGE_LABEL[entry.stage] ?? entry.stage}</small>
          )}
          {entry.attempts !== null && entry.max_attempts !== null && (
            <small className="nums">
              {' '}
              ({entry.attempts}/{entry.max_attempts} deneme)
            </small>
          )}
        </div>
      </td>
      <td>
        {entry.title ?? '—'}
        {entry.channel_name && (
          <small className="log-channel">
            {' '}
            · {entry.channel_name}
          </small>
        )}
      </td>
      <td className="log-detail log-error">{entry.error}</td>
      <td>{action}</td>
    </tr>
  )
}

export function LogsScreen() {
  const [tab, setTab] = useState<'events' | 'errors'>('events')
  const [category, setCategory] = useState<string | null>(null)
  const [channelId, setChannelId] = useState<number | null>(null)
  const [older, setOlder] = useState<LogEntry[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [actionNote, setActionNote] = useState<string | null>(null)

  const fetchCb = useCallback(
    () =>
      fetchLogs({
        limit: 80,
        category: category ?? undefined,
        channel_id: channelId ?? undefined,
      }),
    [category, channelId],
  )
  const view = usePolling(fetchCb, 5000)
  const errorsView = usePolling(() => fetchLogErrors(60), 15000)

  // Filtre değişince yüklenmiş geçmiş sayfalar anlamsızlaşır: sıfırla.
  useEffect(() => {
    setOlder([])
  }, [category, channelId])

  const data = view.state.status === 'ok' ? view.state.data : null
  const entries = data ? [...data.entries, ...older] : []
  const errors =
    errorsView.state.status === 'ok' ? errorsView.state.data.errors : []

  async function loadMore() {
    if (!data || loadingMore) return
    setLoadingMore(true)
    try {
      const oldest = entries.length
        ? Math.min(...entries.map((e) => e.id))
        : null
      const page = await fetchLogs({
        limit: 80,
        category: category ?? undefined,
        channel_id: channelId ?? undefined,
        before_id: oldest ?? undefined,
      })
      setOlder((prev) => [...prev, ...page.entries])
    } finally {
      setLoadingMore(false)
    }
  }

  async function retryErrorEntry(entry: ErrorEntry) {
    if (entry.retry_job_id === null) return
    setBusyKey(`${entry.kind}:${entry.id}`)
    setActionNote(null)
    try {
      await retryJob(entry.retry_job_id)
      setActionNote('İş yeniden kuyruğa alındı.')
      errorsView.retry()
    } catch (err) {
      setActionNote(
        err instanceof Error ? err.message : 'İş alınamadı.',
      )
    } finally {
      setBusyKey(null)
    }
  }

  async function resumeErrorEntry(entry: ErrorEntry) {
    if (entry.resume_video_id === null) return
    setBusyKey(`${entry.kind}:${entry.id}`)
    setActionNote(null)
    try {
      await resumeSourceVideo(entry.resume_video_id)
      setActionNote('Video kaldığı aşamadan sürdürülüyor.')
      errorsView.retry()
    } catch (err) {
      setActionNote(
        err instanceof Error ? err.message : 'Video sürdürülemedi.',
      )
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <>
      <div className="screen-head">
        <h1>Günlükler</h1>
        <span className="screen-sub">
          Sistemin olay akışı ve hatalar — her işlem kayda geçer
        </span>
      </div>

      {view.state.status === 'error' && tab === 'events' && (
        <ErrorState
          title="Günlükler alınamadı"
          message={`Arka uca ulaşılamadı: ${view.state.message}.`}
          onRetry={view.retry}
        />
      )}
      {errorsView.state.status === 'error' && tab === 'errors' && (
        <ErrorState
          title="Hata akışı alınamadı"
          message={`Arka uca ulaşılamadı: ${errorsView.state.message}.`}
          onRetry={errorsView.retry}
        />
      )}
      {actionNote && (
        <p className="bulk-result" role="status">
          {actionNote}
        </p>
      )}

      <section className="ink-panel" aria-label="Günlük görünümü">
        <div className="panel-head-row">
          <h2>
            {tab === 'events' ? 'Olay akışı' : 'Hatalar'}
            {tab === 'events' && (
              <span
                className={`log-live nums${view.state.status === 'ok' && view.state.stale ? ' off' : ''}`}
              >
                {view.state.status === 'ok' && view.state.stale
                  ? 'sinyal yok'
                  : 'canlı · 5 sn'}
              </span>
            )}
            {tab === 'errors' && errors.length > 0 && (
              <span className="panel-count nums">{errors.length} kayıt</span>
            )}
          </h2>
          <div className="filter-row" role="group" aria-label="Görünüm seçimi">
            <button
              className={`filter-pill${tab === 'events' ? ' active' : ''}`}
              onClick={() => setTab('events')}
            >
              Olay akışı
            </button>
            <button
              className={`filter-pill${tab === 'errors' ? ' active' : ''}`}
              onClick={() => setTab('errors')}
            >
              Hatalar
            </button>
          </div>
        </div>

        {tab === 'events' && (
          <>
            {view.state.status === 'loading' && (
              <LoadingState label="Günlükler sorgulanıyor…" />
            )}
            {data && (
              <>
                {view.state.status === 'ok' && view.state.stale && (
                  <StaleNote onRetry={view.retry} />
                )}
                <div className="filter-row" role="group" aria-label="Kategori filtresi">
                  <button
                    className={`filter-pill${category === null ? ' active' : ''}`}
                    onClick={() => setCategory(null)}
                  >
                    Tümü
                  </button>
                  {data.categories.map((cat) => (
                    <button
                      key={cat}
                      className={`filter-pill${category === cat ? ' active' : ''}`}
                      onClick={() => setCategory(cat)}
                    >
                      {CATEGORY_LABEL[cat] ?? cat}
                    </button>
                  ))}
                  {data.channels.length > 0 && (
                    <label className="filter-select">
                      <span>Kanal</span>
                      <select
                        value={channelId ?? ''}
                        onChange={(e) =>
                          setChannelId(e.target.value === '' ? null : Number(e.target.value))
                        }
                      >
                        <option value="">tümü</option>
                        {data.channels.map((ch) => (
                          <option key={ch.id} value={ch.id}>
                            {ch.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                {entries.length === 0 ? (
                  <p className="plate-note">
                    Bu filtrede olay yok — filtreleri gevşetip yeniden dene.
                    Sistem çalışırken her indirme, kurgu, altyazı ve yayın
                    işlemi buraya düşer.
                  </p>
                ) : (
                  <>
                    <div className="log-scroll">
                      <table className="info-table">
                        <thead>
                          <tr>
                            <th>Zaman</th>
                            <th>Kanal</th>
                            <th>Olay</th>
                            <th>Detay</th>
                          </tr>
                        </thead>
                        <tbody>
                          {entries.map((entry) => (
                            <LogRow key={entry.id} entry={entry} />
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {(data.has_more || older.length > 0) && (
                      <button
                        className="btn btn--ghost more-button"
                        disabled={loadingMore || !data.has_more}
                        onClick={() => void loadMore()}
                      >
                        {loadingMore
                          ? 'Yükleniyor…'
                          : data.has_more
                            ? 'Daha eski olayları yükle'
                            : 'Kayıt sonu'}
                      </button>
                    )}
                  </>
                )}
              </>
            )}
          </>
        )}

        {tab === 'errors' && (
          <>
            {errorsView.state.status === 'loading' && (
              <LoadingState label="Hata kayıtları sorgulanıyor…" />
            )}
            {errors.length === 0 &&
            errorsView.state.status !== 'loading' ? (
              <p className="plate-note">
                Bekleyen hata yok — başarısız iş, medya veya yükleme
                kaydı bulunamadı.
              </p>
            ) : errors.length > 0 ? (
              <div className="log-scroll">
                <table className="info-table">
                  <thead>
                    <tr>
                      <th>Zaman</th>
                      <th>İş</th>
                      <th>Video</th>
                      <th>Hata</th>
                      <th>Eylem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errors.map((entry) => (
                      <ErrorRow
                        key={`${entry.kind}:${entry.id}`}
                        entry={entry}
                        busy={busyKey === `${entry.kind}:${entry.id}`}
                        onRetry={(e) => void retryErrorEntry(e)}
                        onResume={(e) => void resumeErrorEntry(e)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </>
        )}
      </section>
    </>
  )
}
