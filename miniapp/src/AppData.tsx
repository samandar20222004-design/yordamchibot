import { createContext, useContext } from 'react'
import type { ApiClient } from './api/client'
import type { ChannelList, Lang, Me } from './api/types'
import type { Tab } from './components/Shell'
import type { Resource } from './hooks/useResource'
import type { ScheduleFeed } from './hooks/useScheduleFeed'

export interface AppData {
  client: ApiClient
  me: Resource<Me>
  channels: Resource<ChannelList>
  feed: ScheduleFeed
  go: (tab: Tab) => void
  botUsername: string | null
  /** Qisqa xabar (toast): muvaffaqiyat yoki xato. */
  notify: (text: string, kind?: 'success' | 'error') => void
  /** Interfeys tilini darhol almashtirish (server saqlagandan keyin). */
  setLang: (lang: Lang) => void
}

export const AppDataContext = createContext<AppData | null>(null)

export function useAppData(): AppData {
  const v = useContext(AppDataContext)
  if (!v) throw new Error('AppDataContext yo\'q')
  return v
}
