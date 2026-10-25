import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { fetchAuthStatus, logoutStudio } from './api/auth'
import { AppShell } from './components/AppShell'
import { AuthScreen } from './components/AuthScreen'
import { PulseProvider } from './pulse/PulseProvider'
import { OverviewScreen } from './screens/OverviewScreen'
import { ChannelsScreen } from './screens/ChannelsScreen'
import { CharactersScreen } from './screens/CharactersScreen'
import { MediaLibraryScreen } from './screens/MediaLibraryScreen'
import { CalendarScreen } from './screens/CalendarScreen'
import { AutomationScreen } from './screens/AutomationScreen'
import { AccountScreen } from './screens/AccountScreen'
import { YouTubeScreen } from './screens/YouTubeScreen'
import { LlmProvidersScreen } from './screens/LlmProvidersScreen'
import { LogsScreen } from './screens/LogsScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { GuideScreen } from './screens/GuideScreen'

type AuthState =
  | { status: 'loading' }
  | { status: 'auth'; mode: 'login' | 'signup'; signupOpen: boolean }
  | { status: 'ready'; username: string }

function App() {
  const [auth, setAuth] = useState<AuthState>({ status: 'loading' })

  const loadAuth = useCallback(async () => {
    try {
      const status = await fetchAuthStatus()
      if (!status.configured) {
        setAuth({
          status: 'auth',
          mode: 'signup',
          signupOpen: status.signup_open,
        })
      } else if (!status.authenticated) {
        setAuth({
          status: 'auth',
          mode: 'login',
          signupOpen: status.signup_open,
        })
      } else {
        setAuth({ status: 'ready', username: status.username ?? 'yönetici' })
      }
    } catch {
      // Sunucu henüz yanıt vermiyorsa giriş formu gösterilir; deneme
      // sırasında gerçek hata mesajı görünür.
      setAuth({ status: 'auth', mode: 'login', signupOpen: false })
    }
  }, [])

  useEffect(() => {
    void loadAuth()
  }, [loadAuth])

  useEffect(() => {
    const onUnauthorized = () =>
      setAuth({ status: 'auth', mode: 'login', signupOpen: false })
    window.addEventListener('studio:unauthorized', onUnauthorized)
    return () =>
      window.removeEventListener('studio:unauthorized', onUnauthorized)
  }, [])

  if (auth.status === 'loading') {
    return (
      <div className="auth-splash" role="status" aria-live="polite">
        Stüdyo açılıyor…
      </div>
    )
  }

  if (auth.status === 'auth') {
    return (
      <AuthScreen
        initialMode={auth.mode}
        signupOpen={auth.signupOpen}
        onAuthenticated={(username) => {
          setAuth({ status: 'ready', username })
        }}
      />
    )
  }

  async function handleLogout() {
    try {
      await logoutStudio()
    } finally {
      setAuth({ status: 'auth', mode: 'login', signupOpen: false })
    }
  }

  return (
    <BrowserRouter>
      <PulseProvider>
        <Routes>
          <Route
            element={
              <AppShell username={auth.username} onLogout={handleLogout} />
            }
          >
            <Route index element={<OverviewScreen />} />
            <Route path="kanallar" element={<ChannelsScreen />} />
            <Route path="karakterler" element={<CharactersScreen />} />
            <Route path="medya" element={<MediaLibraryScreen />} />
            <Route path="youtube" element={<YouTubeScreen />} />
            <Route path="takvim" element={<CalendarScreen />} />
            <Route path="otomasyon" element={<AutomationScreen />} />
            <Route path="hesap" element={<AccountScreen />} />
            <Route path="llm-saglayicilari" element={<LlmProvidersScreen />} />
            <Route path="gunlukler" element={<LogsScreen />} />
            <Route path="ayarlar" element={<SettingsScreen />} />
            <Route path="rehber" element={<GuideScreen />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </PulseProvider>
    </BrowserRouter>
  )
}

export default App
