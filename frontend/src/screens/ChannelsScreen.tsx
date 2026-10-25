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
import { GateNotice } from '../components/GateNotice'
import { gateFromError, type GateInfo } from '../gates'
import { ChannelSettingsModal } from '../components/ChannelSettingsModal'

function hataMesaji(err: unknown): string {
  return err instanceof Error ? err.message : 'Bilinmeyen hata'
}

function formatDate(iso: string | null): string {
  if (!iso) return 'Henüz bağlanmadı'
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('tr-TR', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/** Kanal kartı: estetik kurdele, YouTube durum rozeti, hızlı ayarlar ve eylemler. */
function ChannelCard({
  channel,
  onChanged,
  onActionError,
  onOpenSettings,
}: {
  channel: Channel
  onChanged: () => void
  onActionError: (message: string) => void
  onOpenSettings: () => void
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

  const isConnected = channel.status === 'connected'

  return (
    <div
      className="studio-channel-card"
      style={{ '--ribbon-accent': channel.ribbon_color } as React.CSSProperties}
    >
      <div
        className="channel-card-ribbon"
        style={{ background: channel.ribbon_color }}
        aria-hidden="true"
      />
      <div className="channel-card-body">
        <div className="channel-card-head">
          <div className="channel-identity">
            <div
              className="channel-avatar"
              style={{ background: `${channel.ribbon_color}22`, color: channel.ribbon_color, borderColor: `${channel.ribbon_color}44` }}
            >
              <span>{channel.name.charAt(0).toUpperCase()}</span>
            </div>
            <div className="channel-titles">
              <strong className="channel-name">{channel.name}</strong>
              <div className="channel-meta-line">
                {channel.handle ? (
                  <span className="channel-handle">{channel.handle}</span>
                ) : (
                  <span className="channel-handle-empty">Özel handle yok</span>
                )}
                {channel.youtube_channel_id && (
                  <span className="channel-yt-id" title="YouTube Kanal ID">
                    {channel.youtube_channel_id}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="channel-status-pill-wrap">
            <span
              className={`pill ${
                isConnected
                  ? 'pill--ok'
                  : channel.status === 'disconnected'
                    ? 'pill--error'
                    : 'pill--warn'
              }`}
            >
              <span className="pill-dot" aria-hidden="true" />
              {STATUS_LABEL[channel.status]}
            </span>
          </div>
        </div>

        <div className="channel-card-meta">
          <div className="meta-stat">
            <span className="meta-label">Son Bağlantı</span>
            <span className="meta-value">{formatDate(channel.last_connected_at)}</span>
          </div>
          <div className="meta-stat">
            <span className="meta-label">Kayıt Tarihi</span>
            <span className="meta-value">{formatDate(channel.created_at)}</span>
          </div>
        </div>

        <div className="channel-card-footer">
          <button
            type="button"
            className="btn--ghost btn-settings-trigger"
            onClick={onOpenSettings}
            title="Otomasyon kuralları, yayın saatleri ve stok hedeflerini yapılandır"
          >
            ⚙️ Ayarlar & Otomasyon
          </button>

          <div className="channel-actions">
            {isConnected ? (
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
                className="btn btn--youtube"
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
              <div className="delete-confirm-group">
                <button
                  type="button"
                  className="btn--danger"
                  disabled={busy}
                  onClick={() => run(() => deleteChannel(channel.id))}
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
              </div>
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
          </div>
        </div>
      </div>
    </div>
  )
}

/** Yeni kanal ekleme formu: canlı kart önizlemesi + kurdele paleti + sınır kapısı bildirimi. */
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
  const [gate, setGate] = useState<GateInfo | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || busy) {
      return
    }
    setBusy(true)
    setGate(null)
    try {
      await createChannel({ name: trimmed, ribbon_color: ribbon })
      setName('')
      onCreated()
    } catch (err) {
      // Free plan tek kanal sınırına takıldıysa hata değil, plan notu.
      const gateInfo = gateFromError(err)
      if (gateInfo) {
        setGate(gateInfo)
      } else {
        onError(hataMesaji(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="plate new-channel-panel" aria-label="Yeni kanal ekle">
      <div className="panel-header-with-badge">
        <h2 className="panel-title">Yeni Kanal Ekle</h2>
        <span className="badge-subtle">Otomasyon Hazırlığı</span>
      </div>
      <p className="plate-note">
        Yeni bir YouTube kanalı tanımlayın ve arayüzde ayırt edilmesini sağlayacak kurdele rengini belirleyin.
        Ekledikten sonra YouTube yetkisini Bağla butonu ile verebilirsiniz.
      </p>

      <form onSubmit={submit} className="new-channel-form-grid">
        <div className="new-channel-inputs">
          <div className="field">
            <label htmlFor="channel-name">Kanal adı</label>
            <input
              id="channel-name"
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Örn. Klip Fabrikası veya Oyun Shorts"
              maxLength={120}
              required
            />
            <span className="field-help">Stüdyo içinde kanalı ayırt etmek için kullanılacak ad.</span>
          </div>

          <div className="field">
            <span id="ribbon-label">Kurdele Rengi</span>
            <div
              className="ribbon-picker"
              role="group"
              aria-labelledby="ribbon-label"
            >
              {RIBBON_COLORS.map((color) => (
                <button
                  key={color.value}
                  type="button"
                  className={`ribbon-option${ribbon === color.value ? ' selected' : ''}`}
                  title={color.label}
                  aria-label={`Kurdele rengi: ${color.label}`}
                  aria-pressed={ribbon === color.value}
                  style={{ background: color.value }}
                  onClick={() => setRibbon(color.value)}
                />
              ))}
            </div>
            <span className="field-help">Videolarda, takvimde ve panolarda bu renkle gösterilir.</span>
          </div>

          <div className="form-submit-row">
            <button type="submit" className="btn btn--primary" disabled={busy || !name.trim()}>
              Kanalı Ekle
            </button>
          </div>
          {gate && <GateNotice gate={gate} />}
        </div>

        <div className="new-channel-preview" aria-hidden="true">
          <span className="preview-label">Canlı Kart Önizlemesi</span>
          <div className="preview-card" style={{ borderLeftColor: ribbon }}>
            <div className="preview-avatar" style={{ background: `${ribbon}22`, color: ribbon }}>
              {name.trim() ? name.trim().charAt(0).toUpperCase() : 'K'}
            </div>
            <div className="preview-text">
              <strong className="preview-name">{name.trim() || 'Kanal Adı'}</strong>
              <small className="preview-status">Yetki bekleniyor</small>
            </div>
          </div>
        </div>
      </form>
    </section>
  )
}

export function ChannelsScreen() {
  const fetcher = useCallback(() => fetchChannels(), [])
  const { state, retry } = usePolling(fetcher, 15000)
  const [actionError, setActionError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const [settingsChannel, setSettingsChannel] = useState<{ id: number; name: string } | null>(null)
  const oauthResult = searchParams.get('oauth')

  const clearOauthNote = () => setSearchParams({}, { replace: true })

  const channelsList = state.status === 'ok' ? state.data.channels : []
  const connectedCount = state.status === 'ok' ? state.data.connected : 0
  const totalCount = state.status === 'ok' ? state.data.total : 0

  return (
    <>
      <div className="screen-head">
        <div>
          <h1>Kanallar</h1>
          <span className="screen-sub">Bağlı YouTube kanalları, kurdele renkleri ve otomasyon ayarları</span>
        </div>
      </div>

      {oauthResult === 'basarili' && (
        <div className="stale-note alert-success" role="status">
          <span>✓ Kanal başarıyla bağlandı — kurdelesi ve otomasyonu panoda aktif.</span>
          <button type="button" className="btn--ghost" onClick={clearOauthNote}>
            Tamam
          </button>
        </div>
      )}
      {oauthResult === 'hata' && (
        <div className="stale-note alert-danger" role="alert">
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
        <div className="channels-container">
          {state.stale && <StaleNote onRetry={retry} />}

          {actionError && (
            <div className="action-error" role="alert">
              {actionError}
            </div>
          )}

          {/* Üst Metrik Özet Şeridi */}
          <div className="channels-stats-grid">
            <div className="channel-stat-card">
              <span className="stat-card-label">Toplam Kanal</span>
              <span className="stat-card-value">{totalCount}</span>
              <span className="stat-card-sub">Stüdyoda yönetilen kanal sayısı</span>
            </div>
            <div className="channel-stat-card">
              <span className="stat-card-label">Bağlı YouTube Hesapları</span>
              <div className="stat-card-value-group">
                <span className="stat-card-value">{connectedCount}</span>
                {connectedCount > 0 && <span className="stat-indicator-dot online" />}
              </div>
              <span className="stat-card-sub">{connectedCount === totalCount && totalCount > 0 ? 'Tüm kanallar yayına hazır' : `${totalCount - connectedCount} kanal bağlantı bekliyor`}</span>
            </div>
            <div className="channel-stat-card">
              <span className="stat-card-label">Otomasyon Motoru</span>
              <span className="stat-card-value text-accent">Aktif</span>
              <span className="stat-card-sub">Otomatik klip üretimi ve takvim planlama</span>
            </div>
          </div>

          {state.data.total === 0 ? (
            <EmptyState title="Henüz kanal yok">
              Stüdyo yayın yapacak kanalları buradan yönetir. Aşağıdaki levhaya
              ilk kanalını ekle; ardından Bağla ile YouTube yetkisini ver.
            </EmptyState>
          ) : (
            <section className="ink-panel channel-list-panel" aria-label="Kayıtlı kanallar">
              <div className="panel-header-with-badge">
                <h2 className="panel-title">Kayıtlı Kanallar</h2>
                <span className="badge-subtle">{connectedCount} bağlı · {totalCount} kayıtlı</span>
              </div>
              <div className="channels-card-grid">
                {channelsList.map((channel) => (
                  <ChannelCard
                    key={channel.id}
                    channel={channel}
                    onChanged={retry}
                    onActionError={setActionError}
                    onOpenSettings={() => setSettingsChannel({ id: channel.id, name: channel.name })}
                  />
                ))}
              </div>
            </section>
          )}

          <NewChannelForm onCreated={retry} onError={setActionError} />
        </div>
      )}

      {settingsChannel && (
        <ChannelSettingsModal
          channelId={settingsChannel.id}
          channelName={settingsChannel.name}
          onClose={() => setSettingsChannel(null)}
          onSaved={() => {
            setSettingsChannel(null)
            retry()
          }}
        />
      )}
    </>
  )
}
