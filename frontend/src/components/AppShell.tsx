import { NavLink, Outlet } from 'react-router-dom'
import logoUrl from '../assets/brand/logo-dark-bg.svg'

const PRIMARY_NAV = [
  { to: '/', label: 'Genel Bakış', end: true },
  { to: '/kanallar', label: 'Kanallar' },
  { to: '/karakterler', label: 'Karakterler' },
  { to: '/medya', label: 'Medya Kütüphanesi' },
  { to: '/takvim', label: 'Takvim' },
  { to: '/otomasyon', label: 'Otomasyon' },
  { to: '/rehber', label: 'Rehber' },
]

const ADMIN_NAV = [
  { to: '/llm-saglayicilari', label: 'LLM Sağlayıcıları' },
  { to: '/gunlukler', label: 'Günlükler' },
  { to: '/ayarlar', label: 'Ayarlar' },
]

export function AppShell({
  username,
  onLogout,
}: {
  username?: string
  onLogout?: () => void
}) {
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
          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end ?? false}>
              {item.label}
            </NavLink>
          ))}
          <span className="rail-section">Yönetim</span>
          {ADMIN_NAV.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          {username && (
            <div className="rail-user">
              <span title="Oturum açan yönetici">{username}</span>
              {onLogout && (
                <button type="button" onClick={onLogout}>
                  Çıkış
                </button>
              )}
            </div>
          )}
          <div>Raspberry Pi 5 · CasaOS</div>
        </div>
      </aside>
      <main className="content" id="main-content">
        <Outlet />
      </main>
    </div>
  )
}
