import { EmptyState } from '../components/States'
import { Stamp } from '../components/Studio'

export function AutomationScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>OTOMASYON</h1>
        <span className="screen-sub">Kaynak izleme, üretim ve yayın kuralları</span>
      </div>
      <EmptyState
        title="Otomasyon kuralları henüz tanımlı değil"
        action={
          <div className="stamp-note">
            <Stamp text="DURAKLATILDI" variant="live" />
            <span className="stamp-caption">
              Yakında: hattı durdurunca müdahalenin damgası panoda kalır.
            </span>
          </div>
        }
      >
        Günlük klip hedefi, stok alt sınırı, yayın saatleri ve duraklatma
        kuralları buradan yönetilecek. Sistem tam otomatik çalışacak;
        durdurmak istersen tek tıkla tüm hattı duraklatabileceksin.
      </EmptyState>
    </>
  )
}
