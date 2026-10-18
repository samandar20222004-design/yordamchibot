import { createContext, useContext } from 'react'
import type { ApiClient } from './api/client'
import type { ChannelList, Draft, Lang, Me } from './api/types'
import type { Appearance } from './appearance'
import type { Tab } from './components/Shell'
import type { Resource } from './hooks/useResource'
import type { ScheduleFeed } from './hooks/useScheduleFeed'

export interface AppData {
  client: ApiClient
  me: Resource<Me>
  channels: Resource<ChannelList>
  /** Botdan kelgan qoralama (`draft: null` = yo'q). Yuklash xatosi ilovani to'xtatmaydi. */
  draft: Resource<{ draft: Draft | null }>
  feed: ScheduleFeed
  go: (tab: Tab) => void
  /** Foydalanuvchi ko'rinish sozlamalari (rang, fon, tablar...). `patch` oq ro'yxatdan o'tkaziladi va saqlanadi. */
  appearance: Appearance
  setAppearance: (patch: Partial<Appearance>) => void
  resetAppearance: () => void
  /** 💰 Birja: o'qilmagan suhbat xabarlari soni (pastki paneldagi nishon) va uni qayta o'qish. */
  unread: number
  refreshUnread: () => void
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
