import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import logoUrl from '../assets/brand/logo-dark-bg.svg'
import { ActivityBell } from './ActivityBell'
import {
  BoltIcon,
  CalendarIcon,
  CloseIcon,
  FilmIcon,
  GridIcon,
  MenuIcon,
  PlayIcon,
} from './icons'

const PRIMARY_NAV = [
  { to: '/', label: 'Genel Bakış', end: true },
  { to: '/kanallar', label: 'Kanallar' },
  { to: '/karakterler', label: 'Karakterler' },
  { to: '/medya', label: 'Medya Kütüphanesi' },
  { to: '/youtube', label: 'YouTube' },
  { to: '/takvim', label: 'Takvim' },
  { to: '/otomasyon', label: 'Otomasyon' },
  { to: '/rehber', label: 'Rehber' },
]

const ADMIN_NAV = [
  { to: '/llm-saglayicilari', label: 'LLM Sağlayıcıları' },
  { to: '/gunlukler', label: 'Günlükler' },
  { to: '/ayarlar', label: 'Ayarlar' },
]

/* Alt sekme çubuğu: en çok kullanılan beş hedef (kısa adlarıyla);
   kalan hedefler çekmecede tam adlarıyla yer alır. */
const TAB_NAV = [
  { to: '/', label: 'Genel', end: true, icon: GridIcon },
  { to: '/kanallar', label: 'Kanallar', icon: PlayIcon },
  { to: '/medya', label: 'Medya', icon: FilmIcon },
  { to: '/takvim', label: 'Takvim', icon: CalendarIcon },
  { to: '/otomasyon', label: 'Otomasyon', icon: BoltIcon },
]

/* Masaüstü rayı ile mobil kabuk aynı 900px sınırla ayrılır; JS ve CSS
   aynı medya sorgusunu okur, ilk boyamada yanıp sönme olmaz.
   matchMedia bulunmayan ortamlarda (jsdom) masaüstü kabul edilir. */
const MOBILE_QUERY = '(max-width: 900px)'

function subscribeToMobile(onChange: () => void) {
  if (typeof window.matchMedia !== 'function') return () => {}
  const query = window.matchMedia(MOBILE_QUERY)
  query.addEventListener('change', onChange)
  // Bazı gömülü görünümlerde viewport değişimi MQ change olayı
  // üretmez; resize tetiklemesi aynı anlık görüntüyü yeniden okutur.
  window.addEventListener('resize', onChange)
  return () => {
    query.removeEventListener('change', onChange)
    window.removeEventListener('resize', onChange)
  }
}

function getMobileSnapshot(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia(MOBILE_QUERY).matches
  )
}

function useIsMobile(): boolean {
  return useSyncExternalStore(
    subscribeToMobile,
    getMobileSnapshot,
    () => false,
  )
}

function StudioNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Stüdyo gezinme">
      {PRIMARY_NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end ?? false}
          onClick={onNavigate}
        >
          {item.label}
        </NavLink>
      ))}
      <span className="rail-section">Yönetim</span>
      {ADMIN_NAV.map((item) => (
        <NavLink key={item.to} to={item.to} onClick={onNavigate}>
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

export function AppShell({
  username,
  onLogout,
}: {
  username?: string
  onLogout?: () => void
}) {
  const isMobile = useIsMobile()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerRef = useRef<HTMLElement | null>(null)
  const menuButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!drawerOpen) return
    const menuButton = menuButtonRef.current
    drawerRef.current?.focus()
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKeyDown)
      menuButton?.focus()
    }
  }, [drawerOpen])

  const closeDrawer = () => setDrawerOpen(false)

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        İçeriğe geç
      </a>
      {isMobile ? (
        <>
          <header className="mobile-bar">
            <button
              ref={menuButtonRef}
              type="button"
              className="menu-button"
              aria-label="Menüyü aç"
              aria-expanded={drawerOpen}
              onClick={() => setDrawerOpen(true)}
            >
              <MenuIcon />
            </button>
            <img
              src={logoUrl}
              alt="AutoShorts Studio"
              className="mobile-logo"
            />
            <ActivityBell />
          </header>
          <div
            className={`drawer-backdrop${drawerOpen ? ' open' : ''}`}
            aria-hidden="true"
            onClick={closeDrawer}
          />
          <aside
            ref={drawerRef}
            className={`mobile-drawer${drawerOpen ? ' open' : ''}`}
            tabIndex={-1}
            aria-label="Stüdyo menüsü"
          >
            <div className="drawer-brand">
              <img src={logoUrl} alt="AutoShorts Studio" />
              <button
                type="button"
                className="drawer-close"
                aria-label="Menüyü kapat"
                onClick={closeDrawer}
              >
                <CloseIcon />
              </button>
            </div>
            <div className="drawer-scroll">
              <StudioNav onNavigate={closeDrawer} />
            </div>
            <div className="drawer-foot">
              {username && (
                <div className="rail-user">
                  <span title="Oturum açan yönetici">{username}</span>
                  <div className="rail-user-actions">
                    <Link to="/hesap">Hesap</Link>
                    {onLogout && (
                      <button type="button" onClick={onLogout}>
                        Çıkış
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </aside>
          <nav className="tabbar" aria-label="Stüdyo kısayolları">
            {TAB_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end ?? false}
                className="tab-item"
              >
                <span className="tab-pill">
                  <item.icon />
                  <span>{item.label}</span>
                </span>
              </NavLink>
            ))}
          </nav>
        </>
      ) : (
        <>
          <aside className="rail">
            <div className="rail-brand">
              <img src={logoUrl} alt="AutoShorts Studio" />
            </div>
            <StudioNav />
            <div className="rail-foot">
              {username && (
                <div className="rail-user">
                  <span title="Oturum açan yönetici">{username}</span>
                  <div className="rail-user-actions">
                    <Link to="/hesap">Hesap</Link>
                    {onLogout && (
                      <button type="button" onClick={onLogout}>
                        Çıkış
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </aside>
          <div className="shell-main">
            <header className="desktop-topbar">
              <div className="topbar-context">
                <span className="topbar-status-pulse" aria-hidden="true" />
                <span className="topbar-studio-title">AutoShorts Stüdyo</span>
              </div>
              <div className="topbar-right">
                <ActivityBell />
              </div>
            </header>
            <main className="content" id="main-content">
              {/* key, rota degistiginde giris animasyonunu yeniden baslatir. */}
              <div className="route-view" key={location.pathname}>
                <Outlet />
              </div>
            </main>
          </div>
        </>
      )}
      {isMobile && (
        <main className="content" id="main-content">
          {/* key, rota degistiginde giris animasyonunu yeniden baslatir. */}
          <div className="route-view" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      )}
    </div>
  )
}
