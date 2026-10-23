import { useCallback, useEffect, useState } from 'react'
import {
  fetchChannelSettings,
  fetchChannelShorts,
  fetchChannelVideos,
  tagTone,
  updateChannelSettings,
  MODE_LABEL,
  type ChannelSettings,
  type ChannelShort,
  type ChannelVideo,
  type SettingMode,
} from '../api/automation'
import { fetchCharacters, type CharacterOut } from '../api/characters'

type ModalTab = 'settings' | 'horizontal' | 'shorts'

const MODE_OPTIONS: SettingMode[] = ['auto', 'on', 'off']

const MODE_FIELDS: { key: keyof ChannelSettings; label: string; help: string }[] = [
  {
    key: 'title_mode',
    label: 'Başlık üretimi',
    help: 'Otomatik: LLM üretir · Açık: üretim etkin · Kapalı: elle girilir',
  },
  {
    key: 'description_mode',
    label: 'Açıklama üretimi',
    help: 'Otomatik: LLM üretir · Açık: üretim etkin · Kapalı: elle girilir',
  },
  {
    key: 'tags_mode',
    label: 'Etiket üretimi',
    help: 'Otomatik: LLM üretir · Açık: üretim etkin · Kapalı: yalnız şablon etiketleri',
  },
  {
    key: 'content_warning_mode',
    label: '+18 içerik bildirimi',
    help: 'Otomatik: LLM içeriğe göre karar verir · Açık: bildirim var · Kapalı: bildirim yok',
  },
  {
    key: 'ai_disclosure_mode',
    label: 'Yapay zekâ kullanım bildirimi',
    help: 'Otomatik: LLM karar verir (altyazı düzeltmesi tek başına sayılmaz)',
  },
]

function formatBytes(bytes: number | null): string {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Kanal ayarları modalı: takip edilen karakterler, otomasyon ve stok
 * hedefi, içerik modları, sistem promptu + yatay/shorts listeleri. */
export function ChannelSettingsModal({
  channelId,
  channelName,
  onClose,
  onSaved,
}: {
  channelId: number
  channelName: string
  onClose: () => void
  onSaved: () => void
}) {
  const [tab, setTab] = useState<ModalTab>('settings')
  const [settings, setSettings] = useState<ChannelSettings | null>(null)
  const [allCharacters, setAllCharacters] = useState<CharacterOut[]>([])
  const [videos, setVideos] = useState<ChannelVideo[] | null>(null)
  const [shorts, setShorts] = useState<ChannelShort[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState(false)

  const [stockTarget, setStockTarget] = useState(3)
  const [dailyVertical, setDailyVertical] = useState(3)
  const [dailyHorizontal, setDailyHorizontal] = useState(3)
  const [shortsTimes, setShortsTimes] = useState('12:00, 17:00, 21:00')
  const [horizontalTimes, setHorizontalTimes] = useState('09:00, 14:00, 20:00')
  const [modes, setModes] = useState<Record<string, SettingMode>>({})
  const [prompt, setPrompt] = useState('')
  const [followed, setFollowed] = useState<number[]>([])

  const loadSettings = useCallback(async () => {
    setError(null)
    try {
      const [s, chars] = await Promise.all([
        fetchChannelSettings(channelId),
        fetchCharacters(),
      ])
      setSettings(s)
      setStockTarget(s.horizontal_stock_target)
      setDailyVertical(s.daily_vertical_limit)
      setDailyHorizontal(s.daily_horizontal_limit)
      setShortsTimes((s.publish_times_vertical ?? ['12:00', '17:00', '21:00']).join(', '))
      setHorizontalTimes((s.publish_times ?? ['09:00', '14:00', '20:00']).join(', '))
      setModes({
        title_mode: s.title_mode,
        description_mode: s.description_mode,
        tags_mode: s.tags_mode,
        content_warning_mode: s.content_warning_mode,
        ai_disclosure_mode: s.ai_disclosure_mode,
      })
      setPrompt(s.channel_system_prompt ?? '')
      setFollowed(s.characters.map((c) => c.character_id))
      setAllCharacters(chars.characters)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Ayarlar alınamadı.')
    }
  }, [channelId])

  const loadLists = useCallback(async () => {
    setError(null)
    try {
      const [v, s] = await Promise.all([
        fetchChannelVideos(channelId),
        fetchChannelShorts(channelId),
      ])
      setVideos(v.videos)
      setShorts(s.shorts)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Listeler alınamadı.')
    }
  }, [channelId])

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  useEffect(() => {
    if (tab !== 'settings' && videos === null) {
      void loadLists()
    }
  }, [tab, videos, loadLists])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function save() {
    setSaving(true)
    setError(null)
    setSavedNote(false)
    const shortsSlots = shortsTimes
      .split(/[,;\s]+/)
      .map((part) => part.trim())
      .filter(Boolean)
    const horizontalSlots = horizontalTimes
      .split(/[,;\s]+/)
      .map((part) => part.trim())
      .filter(Boolean)
    const slotPattern = /^([01]?\d|2[0-3]):[0-5]\d$/
    for (const slot of [...shortsSlots, ...horizontalSlots]) {
      if (!slotPattern.test(slot)) {
        setError(
          `"${slot}" geçerli bir saat değil. Saatleri "09:00, 14:00" biçiminde, virgülle ayırarak yazın.`,
        )
        setSaving(false)
        return
      }
    }
    if (shortsSlots.length === 0 || horizontalSlots.length === 0) {
      setError('Her yön için en az bir yayın saati gerekli.')
      setSaving(false)
      return
    }
    try {
      await updateChannelSettings(channelId, {
        horizontal_stock_target: stockTarget,
        daily_vertical_limit: dailyVertical,
        daily_horizontal_limit: dailyHorizontal,
        publish_times: horizontalSlots,
        publish_times_vertical: shortsSlots,
        title_mode: modes.title_mode,
        description_mode: modes.description_mode,
        tags_mode: modes.tags_mode,
        content_warning_mode: modes.content_warning_mode,
        ai_disclosure_mode: modes.ai_disclosure_mode,
        channel_system_prompt: prompt,
        character_ids: followed,
      })
      setSavedNote(true)
      onSaved()
      await loadSettings()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Kaydedilemedi.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`${channelName} kanal ayarları`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="modal">
        <div className="modal-head">
          <h2>{channelName} — kanal ayarları</h2>
          <button className="btn btn--ghost" onClick={onClose}>
            Kapat
          </button>
        </div>
        <div className="modal-tabs" role="tablist">
          {(
            [
              ['settings', 'Ayarlar'],
              ['horizontal', 'Yatay Videolar'],
              ['shorts', 'Shorts'],
            ] as [ModalTab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              className={`modal-tab${tab === key ? ' active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {error && <p className="plate-note error">{error}</p>}

        {tab === 'settings' && (
          <div className="modal-body">
            {!settings && <p className="plate-note">Ayarlar yükleniyor…</p>}
            {settings && (
              <>
                <section className="field">
                  <span>Hazır video stok hedefi</span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={stockTarget}
                    onChange={(e) => setStockTarget(Number(e.target.value) || 1)}
                  />
                  <small className="field-help">
                    Hazır video stoğu (dikey + yatay) bu sayıya ulaşınca yeni kaynak
                    indirilmez; videolar paylaşıldıkça stok azalır ve üretim
                    yeniden başlar. Varsayılan 3.
                  </small>
                </section>

                <div className="settings-grid">
                  <section className="field">
                    <span>Günlük dikey limiti</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      value={dailyVertical}
                      onChange={(e) =>
                        setDailyVertical(Number(e.target.value) || 0)
                      }
                    />
                    <small className="field-help">
                      Bir günde herkese açılacak dikey Short sayısı (0 =
                      sınırsız).
                    </small>
                  </section>
                  <section className="field">
                    <span>Günlük yatay limiti</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      value={dailyHorizontal}
                      onChange={(e) =>
                        setDailyHorizontal(Number(e.target.value) || 0)
                      }
                    />
                    <small className="field-help">
                      Bir günde herkese açılacak yatay tam kesit sayısı (0 =
                      sınırsız).
                    </small>
                  </section>
                </div>

                <div className="settings-grid">
                  <section className="field">
                    <span>Shorts yayın saatleri</span>
                    <input
                      value={shortsTimes}
                      placeholder="12:00, 17:00, 21:00"
                      onChange={(e) => setShortsTimes(e.target.value)}
                    />
                    <small className="field-help">
                      Dikey Shortlar bu saatlerde yayına çıkar (prime time).
                      Varsayılan: 12:00, 17:00, 21:00.
                    </small>
                  </section>
                  <section className="field">
                    <span>Yatay yayın saatleri</span>
                    <input
                      value={horizontalTimes}
                      placeholder="09:00, 14:00, 20:00"
                      onChange={(e) => setHorizontalTimes(e.target.value)}
                    />
                    <small className="field-help">
                      Yatay tam kesitler bu saatlerde yayına çıkar. Varsayılan:
                      09:00, 14:00, 20:00.
                    </small>
                  </section>
                </div>

                <section className="field">
                  <span>Takip edilen karakterler</span>
                  {allCharacters.length === 0 && (
                    <small className="field-help">
                      Karakter yok. Karakterler ekranından ekleyebilirsiniz.
                    </small>
                  )}
                  <div className="check-row" role="group" aria-label="Karakterler">
                    {allCharacters.map((character) => (
                      <label key={character.id} className="follow-check">
                        <input
                          type="checkbox"
                          checked={followed.includes(character.id)}
                          onChange={(e) => {
                            setFollowed((prev) =>
                              e.target.checked
                                ? [...prev, character.id]
                                : prev.filter((id) => id !== character.id),
                            )
                          }}
                        />
                        {character.name}
                      </label>
                    ))}
                  </div>
                  <small className="field-help">
                    Takip listesi doluysa yalnız bu karakterlerin kaynakları
                    işlenir; boşsa kanalın tüm yetkili kaynakları kullanılır.
                  </small>
                </section>

                {MODE_FIELDS.map(({ key, label, help }) => (
                  <section className="field" key={key}>
                    <span>{label}</span>
                    <select
                      value={modes[key] ?? 'auto'}
                      onChange={(e) =>
                        setModes((prev) => ({
                          ...prev,
                          [key]: e.target.value as SettingMode,
                        }))
                      }
                    >
                      {MODE_OPTIONS.map((m) => (
                        <option key={m} value={m}>
                          {MODE_LABEL[m]}
                        </option>
                      ))}
                    </select>
                    <small className="field-help">{help}</small>
                  </section>
                ))}

                <section className="field">
                  <span>Kanal sistem promptu</span>
                  <textarea
                    rows={4}
                    value={prompt}
                    placeholder="Bu kanalın LLM çağrılarına uygulanır (karakter promptu yoksa)."
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                  <small className="field-help">
                    Uygulama sırası: karakter promptu, sonra kanal promptu,
                    sonra genel prompt. Boş bırakılırsa genel prompt kullanılır.
                  </small>
                </section>

                <div className="modal-actions">
                  {savedNote && <small className="save-note">Kaydedildi.</small>}
                  <button className="btn" onClick={() => void save()} disabled={saving}>
                    {saving ? 'Kaydediliyor…' : 'Değişiklikleri Kaydet'}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {tab === 'horizontal' && (
          <div className="modal-body">
            {videos === null && <p className="plate-note">Liste yükleniyor…</p>}
            {videos !== null && videos.length === 0 && (
              <p className="plate-note">Bu kanalda henüz yatay video yok.</p>
            )}
            {videos !== null && videos.length > 0 && (
              <table className="info-table">
                <thead>
                  <tr>
                    <th>Durum</th>
                    <th>Başlık</th>
                    <th>Süre</th>
                    <th>Boyut</th>
                  </tr>
                </thead>
                <tbody>
                  {videos.map((video) => (
                    <tr key={video.source_video_id}>
                      <td>
                        <span className={`pill pill--${tagTone(video.tag)}`}>
                          {video.tag}
                        </span>
                      </td>
                      <td title={video.error ?? undefined}>{video.title}</td>
                      <td className="nums">{formatDuration(video.duration_seconds)}</td>
                      <td className="nums">{formatBytes(video.file_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === 'shorts' && (
          <div className="modal-body">
            {shorts === null && <p className="plate-note">Liste yükleniyor…</p>}
            {shorts !== null && shorts.length === 0 && (
              <p className="plate-note">Bu kanalda henüz üretilmiş Shorts yok.</p>
            )}
            {shorts !== null && shorts.length > 0 && (
              <table className="info-table">
                <thead>
                  <tr>
                    <th>Durum</th>
                    <th>Yön</th>
                    <th>Süre</th>
                    <th>Boyut</th>
                    <th>Çözünürlük</th>
                  </tr>
                </thead>
                <tbody>
                  {shorts.map((short) => (
                    <tr key={short.rendered_clip_id}>
                      <td>
                        <span className={`pill pill--${tagTone(short.tag)}`}>
                          {short.tag}
                        </span>
                      </td>
                      <td>{short.orientation === 'vertical' ? 'dikey' : 'yatay'}</td>
                      <td className="nums">{formatDuration(short.duration_seconds)}</td>
                      <td className="nums">{formatBytes(short.file_bytes)}</td>
                      <td className="nums">
                        {short.width}&times;{short.height}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
