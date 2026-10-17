import { NavLink, Outlet } from 'react-router-dom'
import logoUrl from '../assets/brand/logo-dark-bg.svg'

const NAV_ITEMS = [
  { to: '/', label: 'Genel Bakış', end: true },
  { to: '/kanallar', label: 'Kanallar' },
  { to: '/medya', label: 'Medya Kütüphanesi' },
  { to: '/takvim', label: 'Takvim' },
  { to: '/otomasyon', label: 'Otomasyon' },
  { to: '/llm-saglayicilari', label: 'LLM Sağlayıcıları' },
  { to: '/gunlukler', label: 'Günlükler' },
  { to: '/ayarlar', label: 'Ayarlar' },
]

export function AppShell() {
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        İçeriğe geç
      </a>
      <aside className="rail">
        <div className="rail-brand">
          <img src={logoUrl} alt="AutoShorts Studio" />
        </div>
        <nav aria-label="Stüdyo gezinme">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end ?? false}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">Raspberry Pi 5 · CasaOS</div>
      </aside>
      <main className="content" id="main-content">
        <Outlet />
      </main>
    </div>
  )
}
