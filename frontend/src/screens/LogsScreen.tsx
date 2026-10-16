import { EmptyState } from '../components/States'

export function LogsScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>GÜNLÜKLER</h1>
        <span className="screen-sub">Yapılandırılmış olay günlüğü</span>
      </div>
      <EmptyState title="Canlı log akışı henüz yok">
        İş kuyruğu devreye girdiğinde her olay (indirme, kurgu, altyazı,
        yayın, hata) JSON satırları halinde burada akacak; kategoriye ve
        kanala göre filtrelenebilecek. Şimdilik konteyner günlükleri
        CasaOS’ta “autoshorts-backend” altında duruyor.
      </EmptyState>
    </>
  )
}
