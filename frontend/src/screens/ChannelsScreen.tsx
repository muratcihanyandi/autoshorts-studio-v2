import { useCallback, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  RIBBON_COLORS,
  STATUS_LABEL,
  createChannel,
  deleteChannel,
  disconnectChannel,
  fetchChannels,
  startOAuth,
  type Channel,
} from '../api/channels'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, ErrorState, LoadingState, StaleNote } from '../components/States'

function hataMesaji(err: unknown): string {
  return err instanceof Error ? err.message : 'Bilinmeyen hata'
}

/** Kanal satırı: kurdele rengi + kimlik + durum + eylemler. */
function ChannelRow({
  channel,
  onChanged,
  onActionError,
}: {
  channel: Channel
  onChanged: () => void
  onActionError: (message: string) => void
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
    <div className="channel-row">
      <i style={{ background: channel.ribbon_color }} aria-hidden="true" />
      <strong>{channel.name}</strong>
      {channel.handle && <small>{channel.handle}</small>}
      <small>{STATUS_LABEL[channel.status]}</small>
      <span className="channel-actions">
        {channel.status === 'connected' ? (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() => run(() => disconnectChannel(channel.id))}
          >
            Kopar
          </button>
        ) : (
          <button
            type="button"
            className="btn--ghost"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const { authorization_url } = await startOAuth(channel.id)
                window.open(authorization_url, '_blank', 'noopener')
              })
            }
          >
            Bağla
          </button>
        )}
        {confirmDelete ? (
          <button
            type="button"
            className="btn--danger"
            disabled={busy}
            onClick={() => run(() => deleteChannel(channel.id))}
          >
            Emin misin?
          </button>
        ) : (
          <button
            type="button"
            className="btn--danger"
            disabled={busy}
            onClick={() => setConfirmDelete(true)}
          >
            Sil
          </button>
        )}
      </span>
    </div>
  )
}

/** Yeni kanal formu: isim + kurdele rengi. */
function NewChannelForm({
  onCreated,
  onError,
}: {
  onCreated: () => void
  onError: (message: string) => void
}) {
  const [name, setName] = useState('')
  const [ribbon, setRibbon] = useState<string>(RIBBON_COLORS[0].value)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || busy) {
      return
    }
    setBusy(true)
    try {
      await createChannel({ name: trimmed, ribbon_color: ribbon })
      setName('')
      onCreated()
    } catch (err) {
      onError(hataMesaji(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="plate new-channel" aria-label="Yeni kanal ekle">
      <h2 className="panel-title">Yeni Kanal</h2>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="channel-name">Kanal adı</label>
          <input
            id="channel-name"
            name="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Örn. Klip Fabrikası"
            maxLength={120}
            required
          />
        </div>
        <div className="field">
          <span id="ribbon-label">Kurdele rengi</span>
          <div
            className="ribbon-picker"
            role="group"
            aria-labelledby="ribbon-label"
          >
            {RIBBON_COLORS.map((color) => (
              <button
                key={color.value}
                type="button"
                className="ribbon-option"
                title={color.label}
                aria-label={`Kurdele rengi: ${color.label}`}
                aria-pressed={ribbon === color.value}
                style={{ background: color.value }}
                onClick={() => setRibbon(color.value)}
              />
            ))}
          </div>
        </div>
        <button type="submit" className="btn" disabled={busy || !name.trim()}>
          Kanalı Ekle
        </button>
      </form>
    </section>
  )
}

export function ChannelsScreen() {
  const fetcher = useCallback(() => fetchChannels(), [])
  const { state, retry } = usePolling(fetcher, 15000)
  const [actionError, setActionError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const oauthResult = searchParams.get('oauth')

  const clearOauthNote = () => setSearchParams({}, { replace: true })

  return (
    <>
      <div className="screen-head">
        <h1>Kanallar</h1>
        <span className="screen-sub">Bağlı YouTube kanalları ve kurdele renkleri</span>
      </div>

      {oauthResult === 'basarili' && (
        <div className="stale-note" role="status">
          <span>Kanal bağlandı — kurdelesi panoda.</span>
          <button type="button" className="btn--ghost" onClick={clearOauthNote}>
            Tamam
          </button>
        </div>
      )}
      {oauthResult === 'hata' && (
        <div className="stale-note" role="alert">
          <span>
            Kanal bağlantısı tamamlanamadı. Google’daki yönlendirme adresi
            kayıtlı olmayabilir —{' '}
            <Link to="/rehber">Rehber’deki bağlantı adımlarına</Link> bakın.
          </span>
          <button type="button" className="btn--ghost" onClick={clearOauthNote}>
            Kapat
          </button>
        </div>
      )}

      {state.status === 'loading' && <LoadingState label="Kanallar okunuyor…" />}
      {state.status === 'error' && (
        <ErrorState
          title="Kanallar alınamadı"
          message={`Arka uca ulaşılamadı: ${state.message}.`}
          onRetry={retry}
        />
      )}

      {state.status === 'ok' && (
        <>
          {state.stale && <StaleNote onRetry={retry} />}

          {actionError && (
            <div className="action-error" role="alert">
              {actionError}
            </div>
          )}

          {state.data.total === 0 ? (
            <EmptyState title="Henüz kanal yok">
              Stüdyo yayın yapacak kanalları buradan yönetir. Aşağıdaki levhaya
              ilk kanalını ekle; ardından Bağla ile YouTube yetkisini ver.
            </EmptyState>
          ) : (
            <section className="ink-panel" aria-label="Kayıtlı kanallar">
              <h2 className="panel-title">Kayıtlı Kanallar</h2>
              {state.data.channels.map((channel) => (
                <ChannelRow
                  key={channel.id}
                  channel={channel}
                  onChanged={retry}
                  onActionError={setActionError}
                />
              ))}
              <p className="screen-sub" style={{ marginTop: 'var(--space-3)' }}>
                {state.data.connected} bağlı · {state.data.total} kayıtlı kanal.
              </p>
            </section>
          )}

          <NewChannelForm onCreated={retry} onError={setActionError} />
        </>
      )}
    </>
  )
}
