import { useCallback, useState } from 'react'
import { fetchChannels } from '../api/channels'
import {
  PERMISSION_LABEL,
  PLATFORM_LABEL,
  addSourceVideo,
  characterPhotoUrl,
  createCharacter,
  createSource,
  deleteCharacter,
  deleteSource,
  discoverChannel,
  fetchChannelSources,
  fetchCharacters,
  updateCharacter,
  updateSource,
  uploadCharacterPhoto,
  type CharacterOut,
  type CharacterCreateInput,
  type CharacterUpdateInput,
  type SourceCreateInput,
  type SourceOut,
  type SourceOrientation,
  type SourcePlatform,
  type SourcesResponse,
} from '../api/characters'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'

const EMPTY_SOURCES: SourcesResponse = { sources: [], total: 0, authorized: 0 }

const EMPTY_FORM = {
  name: '',
  system_prompt: '',
  notes: '',
}

const EMPTY_SOURCE_FORM = {
  platform: 'youtube' as SourcePlatform,
  platform_key: '',
  title: '',
  orientation: 'auto' as SourceOrientation,
  reaction: false,
  reaction_only: false,
}

const ORIENTATION_LABEL: Record<SourceOrientation, string> = {
  auto: 'Otomatik (yatay + dikey)',
  vertical: 'Yalnız dikey',
  horizontal: 'Yatay + dikey',
}

function hataMesaji(err: unknown): string {
  return err instanceof Error ? err.message : 'Bilinmeyen hata'
}

function platformKeyHints(platform: SourcePlatform): {
  label: string
  placeholder: string
} {
  if (platform === 'youtube') {
    return { label: 'UC… Kanal Kimliği', placeholder: 'UCxxxxxxxxxxxxxxxxxxxxxx' }
  }
  if (platform === 'twitch') {
    return { label: 'Kanal Adresi', placeholder: 'örn. https://twitch.tv/kullanici' }
  }
  return { label: 'Kanal Adresi', placeholder: 'örn. https://kick.com/kullanici' }
}

/** Kaynak kartı: platform kimliği, yetki durumu, net kurallar ve eylemler. */
function SourceRow({
  source,
  channelId,
  onChanged,
  onActionError,
}: {
  source: SourceOut
  channelId: number
  onChanged: () => void
  onActionError: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [vodOpen, setVodOpen] = useState(false)
  const [vodUrl, setVodUrl] = useState('')
  const [vodTitle, setVodTitle] = useState('')
  const [note, setNote] = useState<string | null>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      onChanged()
    } catch (err) {
      onActionError(hataMesaji(err))
    } finally {
      setBusy(false)
    }
  }

  const setPermission = (status: 'authorized' | 'pending') =>
    run(async () => {
      await updateSource(source.id, { permission_status: status })
      setNote(status === 'authorized' ? 'İzin verildi.' : 'İzin geri çekildi.')
    })

  const discover = () =>
    run(async () => {
      const result = await discoverChannel(channelId)
      setNote(
        result.quota_blocked
          ? `Keşif tamamlandı — ${result.new_videos} yeni video (kota sınırına yaklaşıldı).`
          : `Keşif tamamlandı — ${result.new_videos} yeni video.`,
      )
    })

  const submitVod = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    try {
      await addSourceVideo(source.id, {
        url: vodUrl.trim(),
        title: vodTitle.trim(),
      })
      setVodUrl('')
      setVodTitle('')
      setVodOpen(false)
      setNote('VOD eklendi.')
      onChanged()
    } catch (err) {
      onActionError(hataMesaji(err))
    } finally {
      setBusy(false)
    }
  }

  const pillTone =
    source.permission_status === 'authorized'
      ? 'pill--ok'
      : source.permission_status === 'rejected'
        ? 'pill--error'
        : 'pill--warn'

  const reactionOnly = source.filter_rules?.require_reaction_content === true

  const toggleReactionOnly = () =>
    run(async () => {
      await updateSource(source.id, {
        filter_rules: {
          ...source.filter_rules,
          require_reaction_content: !reactionOnly,
        },
      })
      setNote(
        reactionOnly
          ? 'Tepki kuralı kapatıldı.'
          : 'Tepki kuralı açıldı — işlenmemiş videolar yeniden değerlendirildi.',
      )
    })

  const changeOrientation = (orientation: SourceOrientation) =>
    run(async () => {
      await updateSource(source.id, { output_orientation: orientation })
      setNote(`Çıktı yönü: ${ORIENTATION_LABEL[orientation]}.`)
    })

  const recencyDays = source.filter_rules?.max_age_days ?? 0

  const changeRecency = (days: number) =>
    run(async () => {
      await updateSource(source.id, {
        filter_rules: {
          ...source.filter_rules,
          max_age_days: days > 0 ? days : undefined,
        },
      })
      setNote(
        days > 0
          ? `Güncellik penceresi son ${days} gün olarak ayarlandı.`
          : 'Güncellik penceresi kaldırıldı.',
      )
    })

  return (
    <div className="source-card">
      <div className="source-card-header">
        <div className="source-primary-info">
          <span className={`source-platform-chip platform--${source.platform}`}>
            {PLATFORM_LABEL[source.platform]}
          </span>
          <div className="source-title-group">
            <strong className="source-title-text">{source.title}</strong>
            <small className="source-char-link">{source.character_name ?? 'karakter yok'}</small>
          </div>
          <span className={`pill ${pillTone}`}>
            <span className="pill-dot" aria-hidden="true" />
            {PERMISSION_LABEL[source.permission_status]}
          </span>
          {source.reaction_source && (
            <span className="source-badge badge--reaction">reaksiyon</span>
          )}
          {source.output_orientation !== 'auto' && (
            <span className="source-badge badge--orientation">
              {ORIENTATION_LABEL[source.output_orientation]}
            </span>
          )}
          {reactionOnly && <span className="source-badge badge--reaction-only">yalnız tepki</span>}
          {recencyDays > 0 && (
            <span className="source-badge badge--recency">son {recencyDays} gün</span>
          )}
        </div>

        <div className="source-quick-actions">
          {source.platform === 'youtube' ? (
            <button
              type="button"
              className="btn btn--primary btn-sm"
              disabled={busy}
              onClick={() => void discover()}
              title="Kanalı tara ve yeni videoları kütüphaneye al"
            >
              Keşfet
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--primary btn-sm"
              disabled={busy}
              onClick={() => setVodOpen((open) => !open)}
            >
              VOD Ekle
            </button>
          )}

          {source.permission_status === 'authorized' ? (
            <button
              type="button"
              className="btn--ghost btn-sm"
              disabled={busy}
              onClick={() => void setPermission('pending')}
              title="İzni geçici olarak geri çek"
            >
              İzni Geri Çek
            </button>
          ) : (
            <button
              type="button"
              className="btn--ghost btn-sm"
              disabled={busy}
              onClick={() => void setPermission('authorized')}
              title="İçerik işleme izni ver"
            >
              İzni Ver
            </button>
          )}

          {confirmDelete ? (
            <div className="delete-confirm-group">
              <button
                type="button"
                className="btn--danger btn-sm"
                disabled={busy}
                onClick={() => void run(() => deleteSource(source.id))}
              >
                Emin misin?
              </button>
              <button
                type="button"
                className="btn--ghost btn-sm"
                onClick={() => setConfirmDelete(false)}
              >
                Vazgeç
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn--danger btn-sm"
              onClick={() => setConfirmDelete(true)}
              title="Kaynağı stüdyodan sil"
            >
              Sil
            </button>
          )}
        </div>
      </div>

      {/* Yapılandırma ve Otomasyon Kuralları Izgarası */}
      <div className="source-config-grid">
        <div className="config-block">
          <label htmlFor={`src-orient-${source.id}`} className="config-label">
            Çıktı Formatı
          </label>
          <select
            id={`src-orient-${source.id}`}
            aria-label={`${source.title} çıktı yönü`}
            value={source.output_orientation}
            disabled={busy}
            onChange={(e) =>
              void changeOrientation(e.target.value as SourceOrientation)
            }
            className="config-select"
          >
            <option value="auto">Yön: Otomatik (yatay + dikey)</option>
            <option value="vertical">Yön: Yalnız dikey</option>
            <option value="horizontal">Yön: Yatay + dikey</option>
          </select>
          <span className="config-desc">
            {source.output_orientation === 'vertical'
              ? 'Yalnızca Shorts üretilir; yatay dosya iş bitince silinir.'
              : 'Budanmış yatay video ve dikey Shorts birlikte üretilir.'}
          </span>
        </div>

        <div className="config-block">
          <label htmlFor={`src-recency-${source.id}`} className="config-label">
            Güncellik Penceresi
          </label>
          <select
            id={`src-recency-${source.id}`}
            aria-label={`${source.title} güncellik penceresi`}
            value={recencyDays}
            disabled={busy}
            onChange={(e) => void changeRecency(Number(e.target.value))}
            className="config-select"
          >
            <option value={0}>Güncellik: sınırsız</option>
            <option value={7}>Son 7 gün</option>
            <option value={15}>Son 15 gün</option>
            <option value={30}>Son 30 gün</option>
          </select>
          <span className="config-desc">
            {recencyDays > 0
              ? `Yalnız son ${recencyDays} gün içinde yüklenen videolar taranır.`
              : 'Tüm geçmiş ve yeni videolar işleme dahil edilir.'}
          </span>
        </div>

        <div className="config-block">
          <span className="config-label">Tepki Kuralı</span>
          <button
            type="button"
            className={`btn--ghost config-rule-btn${reactionOnly ? ' active' : ''}`}
            disabled={busy}
            onClick={() => void toggleReactionOnly()}
            title="Katı kural: yalnız tepki/reaksiyon başlıklı videolar işlenir."
          >
            {reactionOnly ? 'Tepki Kuralını Kapat' : 'Yalnız Tepki'}
          </button>
          <span className="config-desc">
            {reactionOnly
              ? 'Yalnız "Reacting" veya "Tepki" içeren videolar işlenir.'
              : 'Tüm video türleri içeriğe bakılmaksızın taranır.'}
          </span>
        </div>

        {source.output_orientation !== 'vertical' && (
          <div className="config-block">
            <span className="config-label">Giriş / Çıkış Budama</span>
            <div className="source-trim-box">
              <span
                className="source-trim"
                title="Intro/outro otomatik tespit edilir: konuşma boşluğu, sessizlik, siyah kare ve sahne kesmesi sinyalleri birleştirilir."
              >
                {source.trim_start_seconds || source.trim_end_seconds
                  ? `Budama: ${source.trim_start_seconds}s / ${source.trim_end_seconds}s (elle)`
                  : 'Budama: otomatik'}
              </span>
            </div>
            <span className="config-desc">
              Konuşma boşluğu ve sessizlik yapay zekâ ile otomatik kesilir.
            </span>
          </div>
        )}
      </div>

      {note && (
        <div className="save-ok" role="status">
          ✓ {note}
        </div>
      )}

      {vodOpen && (
        <form className="vod-form" onSubmit={submitVod}>
          <div className="field">
            <label htmlFor={`vod-url-${source.id}`}>VOD Adresi</label>
            <input
              id={`vod-url-${source.id}`}
              value={vodUrl}
              onChange={(e) => setVodUrl(e.target.value)}
              placeholder="örn. https://twitch.tv/videos/123456789"
              required
            />
          </div>
          <div className="field">
            <label htmlFor={`vod-title-${source.id}`}>Başlık</label>
            <input
              id={`vod-title-${source.id}`}
              value={vodTitle}
              onChange={(e) => setVodTitle(e.target.value)}
              placeholder="Video başlığı veya yayın konusu"
              required
            />
          </div>
          <div className="vod-actions">
            <button type="submit" className="btn btn--primary btn-sm" disabled={busy}>
              Ekle
            </button>
            <button
              type="button"
              className="btn--ghost btn-sm"
              onClick={() => setVodOpen(false)}
            >
              İptal
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

/** Karaktere kaynak ekleme formu: platform, anahtar, başlık, reaksiyon ve yön. */
function SourceAddForm({
  channelId,
  characterId,
  onCreated,
  onError,
  onCancel,
}: {
  channelId: number
  characterId: number
  onCreated: () => void
  onError: (message: string) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState({ ...EMPTY_SOURCE_FORM })
  const [busy, setBusy] = useState(false)
  const keyHints = platformKeyHints(form.platform)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    const input: SourceCreateInput = {
      youtube_channel_id: form.platform_key.trim(),
      platform: form.platform,
      title: form.title.trim(),
      character_id: characterId,
      output_orientation: form.orientation,
    }
    if (form.reaction) {
      input.reaction_source = true
    }
    if (form.reaction_only) {
      input.filter_rules = { require_reaction_content: true }
    }
    setBusy(true)
    try {
      await createSource(channelId, input)
      setForm({ ...EMPTY_SOURCE_FORM })
      onCreated()
    } catch (err) {
      onError(hataMesaji(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="source-add-form" onSubmit={submit}>
      <div className="form-subhead">
        <strong>Yeni Kaynak Kanalı Ekle</strong>
        <span className="screen-sub">Bu karaktere bağlı videoların taranacağı kanal</span>
      </div>
      <div className="settings-grid">
        <div className="field">
          <label htmlFor={`src-platform-${characterId}`}>Platform</label>
          <select
            id={`src-platform-${characterId}`}
            value={form.platform}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                platform: e.target.value as SourcePlatform,
              }))
            }
          >
            <option value="youtube">YouTube</option>
            <option value="twitch">Twitch</option>
            <option value="kick">Kick</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`src-key-${characterId}`}>{keyHints.label}</label>
          <input
            id={`src-key-${characterId}`}
            value={form.platform_key}
            onChange={(e) =>
              setForm((f) => ({ ...f, platform_key: e.target.value }))
            }
            placeholder={keyHints.placeholder}
            required
          />
          <span className="field-help">
            {form.platform === 'youtube'
              ? 'Kaynak kanalın UC ile başlayan kimliği.'
              : 'Kanalın tam adresi; videolar “VOD Ekle” ile elle girilir.'}
          </span>
        </div>
        <div className="field">
          <label htmlFor={`src-orientation-${characterId}`}>Çıktı Yönü</label>
          <select
            id={`src-orientation-${characterId}`}
            value={form.orientation}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                orientation: e.target.value as SourceOrientation,
              }))
            }
          >
            <option value="auto">Otomatik (yatay + dikey)</option>
            <option value="vertical">Yalnız dikey (Shorts)</option>
            <option value="horizontal">Yatay + dikey</option>
          </select>
          <span className="field-help">
            Otomatik: budanmış yatay tam kesit + dikey Shorts birlikte üretilir.
          </span>
        </div>
        <div className="field">
          <label htmlFor={`src-title-${characterId}`}>Başlık</label>
          <input
            id={`src-title-${characterId}`}
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Örn. Pelin Twitch veya Craftest Ana Kanalı"
            required
          />
        </div>
        <div className="field">
          <label className="check-row" htmlFor={`src-reaction-${characterId}`}>
            <input
              id={`src-reaction-${characterId}`}
              type="checkbox"
              checked={form.reaction}
              onChange={(e) =>
                setForm((f) => ({ ...f, reaction: e.target.checked }))
              }
            />
            <span>Reaksiyon kaynağı</span>
          </label>
          <span className="field-help">
            Yayıncının tepki verdiği kaynak içerik.
          </span>
        </div>
        <div className="field">
          <label className="check-row" htmlFor={`src-reaction-only-${characterId}`}>
            <input
              id={`src-reaction-only-${characterId}`}
              type="checkbox"
              checked={form.reaction_only}
              onChange={(e) =>
                setForm((f) => ({ ...f, reaction_only: e.target.checked }))
              }
            />
            <span>Yalnız tepki/reaksiyon videoları</span>
          </label>
          <span className="field-help">
            Katı kural: yayıncının kendi montajları işlenmez.
          </span>
        </div>
      </div>
      <div className="settings-actions">
        <button
          type="submit"
          className="btn btn--primary"
          disabled={busy || !form.platform_key.trim() || !form.title.trim()}
        >
          Kaynak Ekle
        </button>
        <button type="button" className="btn--ghost" onClick={onCancel}>
          Vazgeç
        </button>
      </div>
    </form>
  )
}

/** Karakter kartı: profil avatarı, rozetler, notlar ve bağlı kaynaklar. */
function CharacterCard({
  character,
  sources,
  channelId,
  onChanged,
  onActionError,
  onEdit,
  sourceFormOpen,
  onToggleSourceForm,
}: {
  character: CharacterOut
  sources: SourceOut[]
  channelId: number
  onChanged: () => void
  onActionError: (message: string) => void
  onEdit: () => void
  sourceFormOpen: boolean
  onToggleSourceForm: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      onChanged()
    } catch (err) {
      onActionError(hataMesaji(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="character-card">
      <div className="character-head">
        <div className="character-profile-info">
          {character.photo_configured ? (
            <img
              className="character-photo"
              src={characterPhotoUrl(character.id)}
              alt={`${character.name} fotoğrafı`}
            />
          ) : (
            <span
              className="character-photo character-photo--empty"
              aria-hidden="true"
            >
              {character.name.slice(0, 1).toLocaleUpperCase('tr-TR')}
            </span>
          )}
          <div className="character-title">
            <strong className="character-name-text">{character.name}</strong>
            <div className="character-badges">
              <span className="source-badge">
                {character.reference_face ? 'referans yüz var' : 'referans yüz yok'}
              </span>
              <span className="source-badge">
                {character.system_prompt_set ? 'prompt var' : 'prompt yok'}
              </span>
              <span className="source-badge badge--sources-count">
                {sources.length} kaynak bağlı
              </span>
            </div>
          </div>
        </div>

        <div className="channel-actions">
          <button type="button" className="btn--ghost btn-sm" onClick={onEdit}>
            Düzenle
          </button>
          {character.system_prompt_set && (
            <button
              type="button"
              className="btn--ghost btn-sm"
              disabled={busy}
              onClick={() =>
                void run(() => updateCharacter(character.id, { system_prompt: '' }))
              }
            >
              Promptu Temizle
            </button>
          )}
          <button
            type="button"
            className="btn btn--primary btn-sm"
            onClick={onToggleSourceForm}
          >
            {sourceFormOpen ? 'Formu Kapat' : 'Kaynak Ekle'}
          </button>
          {confirmDelete ? (
            <div className="delete-confirm-group">
              <button
                type="button"
                className="btn--danger btn-sm"
                disabled={busy}
                onClick={() => void run(() => deleteCharacter(character.id))}
              >
                Silmeyi Onayla
              </button>
              <button
                type="button"
                className="btn--ghost btn-sm"
                onClick={() => setConfirmDelete(false)}
              >
                Vazgeç
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn--danger btn-sm"
              onClick={() => setConfirmDelete(true)}
            >
              Sil
            </button>
          )}
        </div>
      </div>

      {character.notes && (
        <div className="character-notes-callout">
          <span className="quote-mark" aria-hidden="true">“</span>
          <p className="plate-note">{character.notes}</p>
        </div>
      )}

      <div className="character-sources">
        {sources.length === 0 ? (
          <div className="empty-sources-notice">
            <p className="plate-note">Bu karaktere bağlı kaynak yok.</p>
            <button
              type="button"
              className="btn--ghost btn-sm"
              onClick={onToggleSourceForm}
            >
              + Kaynak Ekle
            </button>
          </div>
        ) : (
          sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              channelId={channelId}
              onChanged={onChanged}
              onActionError={onActionError}
            />
          ))
        )}
      </div>

      {sourceFormOpen && (
        <SourceAddForm
          channelId={channelId}
          characterId={character.id}
          onCreated={() => {
            onToggleSourceForm()
            onChanged()
          }}
          onError={onActionError}
          onCancel={onToggleSourceForm}
        />
      )}
    </div>
  )
}

export function CharactersScreen() {
  const channelsFetcher = useCallback(() => fetchChannels(), [])
  const channels = usePolling(channelsFetcher, 30000)
  const charactersFetcher = useCallback(() => fetchCharacters(), [])
  const characters = usePolling(charactersFetcher, 15000)

  const [channelChoice, setChannelChoice] = useState<number | null>(null)
  const channelList =
    channels.state.status === 'ok' ? channels.state.data.channels : []
  const selectedChannelId =
    channelChoice ?? (channelList.length > 0 ? channelList[0].id : null)

  const sourcesFetcher = useCallback(
    () =>
      selectedChannelId === null
        ? Promise.resolve(EMPTY_SOURCES)
        : fetchChannelSources(selectedChannelId),
    [selectedChannelId],
  )
  const sources = usePolling(sourcesFetcher, 15000)

  const [actionError, setActionError] = useState<string | null>(null)
  const [editing, setEditing] = useState<CharacterOut | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [sourceFormFor, setSourceFormFor] = useState<number | null>(null)

  const set = (key: keyof typeof EMPTY_FORM, value: string) =>
    setForm((f) => ({ ...f, [key]: value }))

  const startEdit = (character: CharacterOut) => {
    setEditing(character)
    setForm({
      name: character.name,
      system_prompt: '',
      notes: character.notes ?? '',
    })
    setFormError(null)
    setPhotoFile(null)
    setSourceFormFor(null)
  }

  const cancelEdit = () => {
    setEditing(null)
    setForm({ ...EMPTY_FORM })
    setFormError(null)
    setPhotoFile(null)
  }

  const refresh = () => {
    characters.retry()
    sources.retry()
  }

  const submit = async () => {
    setSaving(true)
    setFormError(null)
    try {
      if (editing) {
        const patch: CharacterUpdateInput = {
          name: form.name.trim(),
          notes: form.notes.trim(),
        }
        if (form.system_prompt.trim() !== '') {
          patch.system_prompt = form.system_prompt.trim()
        }
        await updateCharacter(editing.id, patch)
        cancelEdit()
      } else {
        const input: CharacterCreateInput = { name: form.name.trim() }
        if (form.system_prompt.trim() !== '') {
          input.system_prompt = form.system_prompt.trim()
        }
        if (form.notes.trim() !== '') {
          input.notes = form.notes.trim()
        }
        await createCharacter(input)
        setForm({ ...EMPTY_FORM })
      }
      refresh()
    } catch (err) {
      setFormError(hataMesaji(err))
    } finally {
      setSaving(false)
    }
  }

  const uploadPhoto = async () => {
    if (!editing || !photoFile) return
    setSaving(true)
    setFormError(null)
    try {
      await uploadCharacterPhoto(editing.id, photoFile)
      setPhotoFile(null)
      refresh()
    } catch (err) {
      setFormError(hataMesaji(err))
    } finally {
      setSaving(false)
    }
  }

  const boundSources = (characterId: number): SourceOut[] =>
    sources.state.status === 'ok'
      ? sources.state.data.sources.filter(
          (s) => s.character_id === characterId,
        )
      : []

  const unboundSources: SourceOut[] =
    sources.state.status === 'ok'
      ? sources.state.data.sources.filter((s) => s.character_id === null)
      : []

  const selectedChannel = channelList.find((c) => c.id === selectedChannelId)

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>Karakterler</h1>
          <span className="screen-sub">
            Yayıncı karakterleri, kaynak kanalları ve içerik filtre kuralları
          </span>
        </div>
      </div>

      <div className="stack">
        {/* Aktif Stüdyo Kanalı Seçimi Bannerı */}
        <section className="plate channel-selection-banner" aria-label="Stüdyo kanalı seçimi">
          <div className="banner-channel-meta">
            <div className="banner-channel-title">
              <span
                className="banner-ribbon-badge"
                style={{ background: selectedChannel?.ribbon_color ?? '#3550c4' }}
                aria-hidden="true"
              />
              <span className="banner-heading">Aktif Stüdyo Kanalı</span>
            </div>
            <p className="plate-note">
              Kaynaklar seçili stüdyo kanalına eklenir; her karakter o kanalın
              kaynak listesine bağlanır.
            </p>
          </div>

          {channelList.length === 0 ? (
            <p className="plate-note">
              Stüdyo kanalı yok — önce Kanallar ekranından bir kanal ekleyin.
            </p>
          ) : (
            <div className="field channel-select-field">
              <label htmlFor="char-channel">Stüdyo kanalı</label>
              <select
                id="char-channel"
                value={selectedChannelId ?? ''}
                onChange={(e) => setChannelChoice(Number(e.target.value))}
                className="channel-select-input"
              >
                {channelList.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </section>

        {characters.state.status === 'loading' && (
          <LoadingState label="Karakterler okunuyor…" />
        )}
        {characters.state.status === 'error' && (
          <ErrorState
            title="Karakterler alınamadı"
            message={`Arka uca ulaşılamadı: ${characters.state.message}.`}
            onRetry={characters.retry}
          />
        )}

        {characters.state.status === 'ok' && (
          <>
            {characters.state.stale && <StaleNote onRetry={characters.retry} />}

            {actionError && (
              <div className="action-error" role="alert">
                {actionError}
              </div>
            )}

            {characters.state.data.total === 0 ? (
              <EmptyState title="Henüz karakter yok">
                Yayıncıları karakter olarak tanımlayın: fotoğraf, isteğe bağlı
                sistem promptu ve kaynak kanalları. Aşağıdaki formda ilk
                karakterinizi ekleyin.
              </EmptyState>
            ) : (
              <section className="ink-panel characters-list-panel" aria-label="Kayıtlı karakterler">
                <div className="panel-header-with-badge">
                  <h2 className="panel-title">Kayıtlı Karakterler</h2>
                  <span className="badge-subtle">
                    {characters.state.data.total} karakter ·{' '}
                    {sources.state.status === 'ok' ? sources.state.data.total : 0} kaynak ·{' '}
                    {sources.state.status === 'ok' ? sources.state.data.authorized : 0} yetkili
                  </span>
                </div>

                <div className="character-cards-grid">
                  {characters.state.data.characters.map((character) => (
                    <CharacterCard
                      key={character.id}
                      character={character}
                      sources={boundSources(character.id)}
                      channelId={selectedChannelId ?? 0}
                      onChanged={refresh}
                      onActionError={setActionError}
                      onEdit={() => startEdit(character)}
                      sourceFormOpen={sourceFormFor === character.id}
                      onToggleSourceForm={() =>
                        setSourceFormFor((prev) =>
                          prev === character.id ? null : character.id,
                        )
                      }
                    />
                  ))}
                </div>

                {unboundSources.length > 0 && (
                  <div className="character-card unbound-sources-card">
                    <div className="character-head">
                      <div className="character-profile-info">
                        <span
                          className="character-photo character-photo--empty"
                          aria-hidden="true"
                        >
                          ?
                        </span>
                        <div className="character-title">
                          <strong className="character-name-text">
                            Karaktere bağlı olmayan kaynaklar
                          </strong>
                          <span className="character-badges">
                            <span className="source-badge">karakter atanmamış</span>
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="character-sources">
                      {unboundSources.map((source) => (
                        <SourceRow
                          key={source.id}
                          source={source}
                          channelId={selectedChannelId ?? 0}
                          onChanged={refresh}
                          onActionError={setActionError}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </section>
            )}

            <section className="plate character-form">
              <h2 className="panel-title">
                {editing
                  ? `Karakter Düzenle — ${editing.name}`
                  : 'Yeni Karakter Ekle'}
              </h2>
              {formError && (
                <div className="action-error" role="alert">
                  {formError}
                </div>
              )}
              {editing && (
                <p className="plate-note">
                  Değiştirmek istemediğiniz alanları aynı bırakın. Sistem
                  promptu boş bırakılırsa mevcut prompt korunur; değiştirmek
                  için yeni metni yazın.
                </p>
              )}
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void submit()
                }}
              >
                <div className="settings-grid">
                  <div className="field">
                    <label htmlFor="char-name">Ad</label>
                    <input
                      id="char-name"
                      value={form.name}
                      onChange={(e) => set('name', e.target.value)}
                      placeholder="Örn. Pelin Yayıncı veya Craftest"
                      maxLength={120}
                      required
                    />
                  </div>
                  <div className="field field--wide">
                    <label htmlFor="char-prompt">Sistem Promptu</label>
                    <textarea
                      id="char-prompt"
                      rows={3}
                      value={form.system_prompt}
                      onChange={(e) => set('system_prompt', e.target.value)}
                      placeholder={
                        editing
                          ? 'Değiştirmek istemiyorsanız boş bırakın'
                          : 'Karakterin ses tonu, klip seçim tercihleri veya odak noktası'
                      }
                    />
                    <span className="field-help">
                      Boş bırakılırsa genel stüdyo promptu kullanılır.
                    </span>
                  </div>
                  <div className="field">
                    <label htmlFor="char-notes">Notlar</label>
                    <textarea
                      id="char-notes"
                      rows={3}
                      value={form.notes}
                      onChange={(e) => set('notes', e.target.value)}
                      placeholder="Yayın saatleri, içerik türü veya hatırlatıcılar"
                    />
                  </div>
                  {editing && (
                    <div className="field">
                      <label htmlFor="char-photo">Fotoğraf</label>
                      <input
                        id="char-photo"
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={(e) =>
                          setPhotoFile(e.target.files?.[0] ?? null)
                        }
                      />
                      <span className="field-help">
                        Yüzün net göründüğü bir kare (jpg/png/webp, en fazla
                        8MB). Referans yüz çıkarılır; webcam bölgesi bununla
                        doğrulanır.
                      </span>
                      {photoFile && (
                        <button
                          type="button"
                          className="btn--ghost btn-sm"
                          disabled={saving}
                          onClick={() => void uploadPhoto()}
                        >
                          Fotoğrafı Yükle
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="settings-actions">
                  <button type="submit" className="btn btn--primary" disabled={saving}>
                    {saving
                      ? 'Kaydediliyor…'
                      : editing
                        ? 'Değişiklikleri Kaydet'
                        : 'Karakter Ekle'}
                  </button>
                  {editing && (
                    <button
                      type="button"
                      className="btn--ghost"
                      onClick={cancelEdit}
                    >
                      Vazgeç
                    </button>
                  )}
                </div>
              </form>
            </section>
          </>
        )}
      </div>
    </>
  )
}
