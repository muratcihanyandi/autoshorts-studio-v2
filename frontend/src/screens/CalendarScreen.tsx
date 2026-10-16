import { EmptyState } from '../components/States'

export function CalendarScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>TAKVİM</h1>
        <span className="screen-sub">Yayın planı ve gerçekleşen yayınlar</span>
      </div>
      <EmptyState title="Takvim henüz boş">
        Kanallar bağlanıp yayın profilleri tanımlandığında takvim dolacak.
        Planlanan yayınlar ve gerçekleşen yayınlar ayrı katmanlarda
        gösterilecek: mavi plan, yeşil gerçekleşme — aradaki her fark tek
        bakışta görünecek.
      </EmptyState>
    </>
  )
}
