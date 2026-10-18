import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { OverviewScreen } from './screens/OverviewScreen'
import { ChannelsScreen } from './screens/ChannelsScreen'
import { CharactersScreen } from './screens/CharactersScreen'
import { MediaLibraryScreen } from './screens/MediaLibraryScreen'
import { CalendarScreen } from './screens/CalendarScreen'
import { AutomationScreen } from './screens/AutomationScreen'
import { LlmProvidersScreen } from './screens/LlmProvidersScreen'
import { LogsScreen } from './screens/LogsScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { GuideScreen } from './screens/GuideScreen'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewScreen />} />
          <Route path="kanallar" element={<ChannelsScreen />} />
          <Route path="karakterler" element={<CharactersScreen />} />
          <Route path="medya" element={<MediaLibraryScreen />} />
          <Route path="takvim" element={<CalendarScreen />} />
          <Route path="otomasyon" element={<AutomationScreen />} />
          <Route path="llm-saglayicilari" element={<LlmProvidersScreen />} />
          <Route path="gunlukler" element={<LogsScreen />} />
          <Route path="ayarlar" element={<SettingsScreen />} />
          <Route path="rehber" element={<GuideScreen />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
