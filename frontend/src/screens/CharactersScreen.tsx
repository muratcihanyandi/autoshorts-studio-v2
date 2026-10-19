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
  trim_start: '',
  trim_end: '',
}

/** Görev 2: kaynağın çıktı yönü etiketleri. */
const ORIENTATION_LABEL: Record<SourceOrientation, string> = {
  auto: 'Otomatik',
  vertical: 'Dikey video',
  horizontal: 'Yatay video',
}

function hataMesaji(err: unknown): string {
  return err instanceof Error ? err.message : 'Bilinmeyen hata'
}

/** Platform anahtarı etiketi: YouTube'da UC kimliği, diğerlerinde kanal adresi. */
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

/** Kaynak satırı: izin kaydı, keşif/VOD eylemleri ve silme. */
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
          // 0 = sınırsız: anahtar gövdeden düşer, kural kapanır.
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
    <div className="source-row">
      <span className="source-badge">{PLATFORM_LABEL[source.platform]}</span>
      <strong>{source.title}</strong>
      <small>{source.character_name ?? 'karakter yok'}</small>
      <span className={`pill ${pillTone}`}>
        {PERMISSION_LABEL[source.permission_status]}
      </span>
      {source.reaction_source && <span className="source-badge">reaksiyon</span>}
      {source.output_orientation !== 'auto' && (
        <span className="source-badge">
          {ORIENTATION_LABEL[source.output_orientation]}
        </span>
      )}
      {reactionOnly && <span className="source-badge">yalnız tepki</span>}
      {recencyDays > 0 && (
        <span className="source-badge">son {recencyDays} gün</span>
      )}
      <span className="channel-actions">
        <button
          type="button"
          className="btn--ghost"
          disabled={busy}
          onClick={() => void toggleReactionOnly()}
          title="Katı kural: yalnız tepki/reaksiyon başlıklı videolar işlenir; değişince mevcut videolar yeniden değerlendirilir."
        >
          {reactionOnly ? 'Tepki Kuralını Kapat' : 'Yalnız Tepki'}
        </button>
        <select
          aria-label={`${source.title} çıktı yönü`}
          value={source.output_orientation}
          disabled={busy}
          onChange={(e) =>
            void changeOrientation(e.target.value as SourceOrientation)
          }
          title="Bu kaynaktan ne üretilecek: Otomatik (reaksiyon bayrağına göre), Dikey (yalnız Shorts; yatay dosya işin sonunda silinir) veya Yatay (budanmış tam kesit)."
        >
          <option value="auto">Yön: Otomatik</option>
          <option value="vertical">Yön: Dikey video</option>
          <option value="horizontal">Yön: Yatay video</option>
        </select>
        <select
          aria-label={`${source.title} güncellik penceresi`}
          value={recencyDays}
          disabled={busy}
          onChange={(e) => void changeRecency(Number(e.target.value))}
          title="Bu kaynaktan yalnızca son N gün içinde yayınlanan videolar işlenir; pencere genişletilince eski hariçler geri değerlendirilir."
        >
          <option value={0}>Güncellik: sınırsız</option>
          <option value={7}>Son 7 gün</option>
          <option value={15}>Son 15 gün</option>
          <option value={30}>Son 30 gün</option>
        </select>
        {source.permission_status === 'authorized' ? (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() => void setPermission('pending')}
          >
            İzni Geri Çek
          </button>
        ) : (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() => void setPermission('authorized')}
          >
            İzni Ver
          </button>
        )}
        {source.platform === 'youtube' ? (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() => void discover()}
          >
            Keşfet
          </button>
        ) : (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() => setVodOpen((open) => !open)}
          >
            VOD Ekle
          </button>
        )}
        {confirmDelete ? (
          <>
            <button
              type="button"
              className="btn--danger"
              disabled={busy}
              onClick={() => void run(() => deleteSource(source.id))}
            >
              Emin misin?
            </button>
            <button
              type="button"
              className="btn--ghost"
              onClick={() => setConfirmDelete(false)}
            >
              Vazgeç
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn--danger"
            onClick={() => setConfirmDelete(true)}
          >
            Sil
          </button>
        )}
      </span>
      {note && (
        <span className="save-ok" role="status">
          {note}
        </span>
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
              required
            />
          </div>
          <button type="submit" className="btn--ghost" disabled={busy}>
            Ekle
          </button>
        </form>
      )}
    </div>
  )
}

/** Karaktere kaynak ekleme formu: platform, anahtar, başlık, reaksiyon ve budama. */
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
      input.trim_start_seconds = Number(form.trim_start) || 0
      input.trim_end_seconds = Number(form.trim_end) || 0
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
            <option value="auto">Otomatik</option>
            <option value="vertical">Dikey video</option>
            <option value="horizontal">Yatay video</option>
          </select>
          <span className="field-help">
            Otomatik: reaksiyon bayrağına göre. Dikey: yatay video indirilip
            işlenir, dikeyler çıkar, yatay dosya silinir. Yatay: budanmış
            yatay tam kesit üretilir.
          </span>
        </div>
        <div className="field">
          <label htmlFor={`src-title-${characterId}`}>Başlık</label>
          <input
            id={`src-title-${characterId}`}
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
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
            Reaksiyon videoları: budanmış yatay + dikey short üretilir.
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
            Katı kural: yayıncının kendi montajları (ör. funny moments)
            işlenmez. “Reacting to…” gibi tepki başlıkları — izlenen içerik
            funny moments olsa bile — serbest kalır.
          </span>
        </div>
        {form.reaction && (
          <>
            <div className="field">
              <label htmlFor={`src-trim-start-${characterId}`}>
                Baştan Budama (sn)
              </label>
              <input
                id={`src-trim-start-${characterId}`}
                className="nums"
                type="number"
                min={0}
                step={1}
                value={form.trim_start}
                onChange={(e) =>
                  setForm((f) => ({ ...f, trim_start: e.target.value }))
                }
              />
            </div>
            <div className="field">
              <label htmlFor={`src-trim-end-${characterId}`}>
                Sondan Budama (sn)
              </label>
              <input
                id={`src-trim-end-${characterId}`}
                className="nums"
                type="number"
                min={0}
                step={1}
                value={form.trim_end}
                onChange={(e) =>
                  setForm((f) => ({ ...f, trim_end: e.target.value }))
                }
              />
            </div>
          </>
        )}
      </div>
      <div className="settings-actions">
        <button
          type="submit"
          className="btn"
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

/** Karakter kartı: fotoğraf, rozetler, notlar ve bağlı kaynaklar. */
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
          <strong>{character.name}</strong>
          <span className="character-badges">
            <span className="source-badge">
              {character.reference_face ? 'referans yüz var' : 'referans yüz yok'}
            </span>
            <span className="source-badge">
              {character.system_prompt_set ? 'prompt var' : 'prompt yok'}
            </span>
          </span>
        </div>
        <span className="channel-actions">
          <button type="button" className="btn--ghost" onClick={onEdit}>
            Düzenle
          </button>
          {character.system_prompt_set && (
            <button
              type="button"
              className="btn--ghost"
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
            className="btn--ghost"
            onClick={onToggleSourceForm}
          >
            {sourceFormOpen ? 'Formu Kapat' : 'Kaynak Ekle'}
          </button>
          {confirmDelete ? (
            <>
              <button
                type="button"
                className="btn--danger"
                disabled={busy}
                onClick={() => void run(() => deleteCharacter(character.id))}
              >
                Silmeyi Onayla
              </button>
              <button
                type="button"
                className="btn--ghost"
                onClick={() => setConfirmDelete(false)}
              >
                Vazgeç
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn--danger"
              onClick={() => setConfirmDelete(true)}
            >
              Sil
            </button>
          )}
        </span>
      </div>
      {character.notes && <p className="plate-note">{character.notes}</p>}
      <div className="character-sources">
        {sources.length === 0 ? (
          <p className="plate-note">Bu karaktere bağlı kaynak yok.</p>
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

  return (
    <>
      <div className="screen-head">
        <h1>Karakterler</h1>
        <span className="screen-sub">
          Yayıncı karakterleri, kaynak kanalları ve izin kayıtları
        </span>
      </div>

      <div className="stack">
        <section className="plate" aria-label="Stüdyo kanalı seçimi">
          <h2 className="panel-title">Stüdyo Kanalı</h2>
          <p className="plate-note">
            Kaynaklar seçili stüdyo kanalına eklenir; her karakter o kanalın
            kaynak listesine bağlanır.
          </p>
          {channelList.length === 0 ? (
            <p className="plate-note">
              Stüdyo kanalı yok — önce Kanallar ekranından bir kanal ekleyin.
            </p>
          ) : (
            <div className="field">
              <label htmlFor="char-channel">Stüdyo kanalı</label>
              <select
                id="char-channel"
                value={selectedChannelId ?? ''}
                onChange={(e) => setChannelChoice(Number(e.target.value))}
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
              <section className="ink-panel" aria-label="Kayıtlı karakterler">
                <h2 className="panel-title">Kayıtlı Karakterler</h2>
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
                {unboundSources.length > 0 && (
                  <div className="character-card">
                    <div className="character-head">
                      <span
                        className="character-photo character-photo--empty"
                        aria-hidden="true"
                      >
                        ?
                      </span>
                      <div className="character-title">
                        <strong>Karaktere bağlı olmayan kaynaklar</strong>
                        <span className="character-badges">
                          <span className="source-badge">karakter atanmamış</span>
                        </span>
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
                <p className="plate-note">
                  {characters.state.data.total} karakter ·{' '}
                  {sources.state.status === 'ok' ? sources.state.data.total : 0}{' '}
                  kaynak ·{' '}
                  {sources.state.status === 'ok'
                    ? sources.state.data.authorized
                    : 0}{' '}
                  yetkili
                </p>
              </section>
            )}

            <section className="plate character-form">
              <h2 className="panel-title">
                {editing
                  ? `Karakter Düzenle — ${editing.name}`
                  : 'Yeni Karakter'}
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
                      maxLength={120}
                      required
                    />
                  </div>
                  <div className="field field--wide">
                    <label htmlFor="char-prompt">Sistem Promptu</label>
                    <textarea
                      id="char-prompt"
                      rows={4}
                      value={form.system_prompt}
                      onChange={(e) => set('system_prompt', e.target.value)}
                      placeholder={
                        editing
                          ? 'Değiştirmek istemiyorsanız boş bırakın'
                          : undefined
                      }
                    />
                    <span className="field-help">
                      Boş bırakılırsa genel prompt kullanılır.
                    </span>
                  </div>
                  <div className="field">
                    <label htmlFor="char-notes">Notlar</label>
                    <textarea
                      id="char-notes"
                      rows={3}
                      value={form.notes}
                      onChange={(e) => set('notes', e.target.value)}
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
                          className="btn--ghost"
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
                  <button type="submit" className="btn" disabled={saving}>
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
