import { EmptyState } from '../components/States'

export function MediaLibraryScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>Medya Kütüphanesi</h1>
        <span className="screen-sub">İndirilen kaynaklar, klipler ve özel stok</span>
      </div>
      <EmptyState title="Kütüphane boş">
        Kaynak izleme devreye girince yetkili kanallardan indirilen videolar,
        üretilen klipler ve yayın için bekleyen özel stok burada listelenecek.
        İlk indirme işlemi otomatik olacak — yapman gereken bir şey yok.
      </EmptyState>
    </>
  )
}
