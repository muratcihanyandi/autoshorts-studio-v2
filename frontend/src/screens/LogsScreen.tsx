import { useCallback, useEffect, useState } from 'react'

import { fetchLogs, type LogEntry } from '../api/logs'
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

export function LogsScreen() {
  const [category, setCategory] = useState<string | null>(null)
  const [channelId, setChannelId] = useState<number | null>(null)
  const [older, setOlder] = useState<LogEntry[]>([])
  const [loadingMore, setLoadingMore] = useState(false)

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

  // Filtre değişince yüklenmiş geçmiş sayfalar anlamsızlaşır: sıfırla.
  useEffect(() => {
    setOlder([])
  }, [category, channelId])

  const data = view.state.status === 'ok' ? view.state.data : null
  const entries = data ? [...data.entries, ...older] : []

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

  return (
    <>
      <div className="screen-head">
        <h1>Günlükler</h1>
        <span className="screen-sub">
          Yapılandırılmış olay günlüğü · her işlem kayda geçer
        </span>
      </div>

      {view.state.status === 'loading' && (
        <LoadingState label="Günlükler sorgulanıyor…" />
      )}
      {view.state.status === 'error' && (
        <ErrorState
          title="Günlükler alınamadı"
          message={`Arka uca ulaşılamadı: ${view.state.message}.`}
          onRetry={view.retry}
        />
      )}

      {data && (
        <>
          {view.state.status === 'ok' && view.state.stale && (
            <StaleNote onRetry={view.retry} />
          )}

          <section className="ink-panel" aria-label="Olay günlüğü">
            <h2>
              Olay akışı
              <span
                className={`log-live nums${view.state.status === 'ok' && view.state.stale ? ' off' : ''}`}
              >
                {view.state.status === 'ok' && view.state.stale
                  ? 'sinyal yok'
                  : 'canlı · 5 sn'}
              </span>
            </h2>
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
          </section>
        </>
      )}
    </>
  )
}
