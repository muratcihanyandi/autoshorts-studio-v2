import { EmptyState } from '../components/States'

export function ChannelsScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>KANALLAR</h1>
        <span className="screen-sub">YouTube kanalları ve OAuth bağlantıları</span>
      </div>
      <EmptyState
        title="Henüz bağlı kanal yok"
        action={undefined}
      >
        Kanal bağlama (OAuth 2.0) bir sonraki aşamada geliyor. Bağlanınca her
        kanal kendi kurdele rengiyle burada listelenecek; token yenileme,
        yeniden bağlanma ve kanal bazlı yayın ayarları bu ekrandan yönetilecek.
      </EmptyState>
    </>
  )
}
