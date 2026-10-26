import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { fetchChannels, type Channel } from '../api/channels'

const STORAGE_KEY = 'autoshorts_active_channel_id'

interface ChannelContextType {
  channels: Channel[]
  activeChannelId: number | null
  activeChannel: Channel | null
  loading: boolean
  error: string | null
  setActiveChannelId: (id: number | null) => void
  refreshChannels: () => Promise<void>
}

const ChannelContext = createContext<ChannelContextType | undefined>(undefined)

export function ChannelProvider({ children }: { children: ReactNode }) {
  const [channels, setChannels] = useState<Channel[]>([])
  const [activeChannelId, setActiveChannelIdState] = useState<number | null>(() => {
    if (typeof window === 'undefined') return null
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      return stored ? Number(stored) : null
    } catch {
      return null
    }
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refreshChannels = useCallback(async () => {
    try {
      setError(null)
      const res = await fetchChannels()
      const list = res.channels ?? []
      setChannels(list)

      // Aktif kanalı senkronize et
      setActiveChannelIdState((prev) => {
        if (list.length === 0) {
          try {
            localStorage.removeItem(STORAGE_KEY)
          } catch {
            // ignore
          }
          return null
        }
        // Eğer önceki aktif kanal hala listede varsa koru
        const stillExists = list.some((c) => c.id === prev)
        if (stillExists && prev !== null) {
          return prev
        }
        // Yoksa ilk kanalı seç
        const fallbackId = list[0].id
        try {
          localStorage.setItem(STORAGE_KEY, String(fallbackId))
        } catch {
          // ignore
        }
        return fallbackId
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Kanallar yüklenemedi.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshChannels()
  }, [refreshChannels])

  const setActiveChannelId = useCallback((id: number | null) => {
    setActiveChannelIdState(id)
    try {
      if (id !== null) {
        localStorage.setItem(STORAGE_KEY, String(id))
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch {
      // ignore
    }
  }, [])

  const activeChannel = useMemo(() => {
    if (activeChannelId === null) return null
    return channels.find((c) => c.id === activeChannelId) ?? null
  }, [channels, activeChannelId])

  const value = useMemo<ChannelContextType>(
    () => ({
      channels,
      activeChannelId,
      activeChannel,
      loading,
      error,
      setActiveChannelId,
      refreshChannels,
    }),
    [channels, activeChannelId, activeChannel, loading, error, setActiveChannelId, refreshChannels],
  )

  return <ChannelContext.Provider value={value}>{children}</ChannelContext.Provider>
}

export function useActiveChannel(): ChannelContextType {
  const ctx = useContext(ChannelContext)
  if (!ctx) {
    return {
      channels: [],
      activeChannelId: null,
      activeChannel: null,
      loading: false,
      error: null,
      setActiveChannelId: () => {},
      refreshChannels: async () => {},
    }
  }
  return ctx
}
