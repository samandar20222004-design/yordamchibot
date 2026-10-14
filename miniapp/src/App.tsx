import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppDataContext, type AppData } from './AppData'
import { createApiClient } from './api/client'
import { OfflineBanner, TabBar, type Tab } from './components/Shell'
import { Toast } from './components/Dialog'
import { EmptyState } from './components/ui'
import { I18nProvider, normalizeLang, useI18n } from './i18n'
import { useResource } from './hooks/useResource'
import { useScheduleFeed } from './hooks/useScheduleFeed'
import { HomePage } from './pages/HomePage'
import { MePage } from './pages/MePage'
import { PostPage } from './pages/PostPage'
import { SchedulePage } from './pages/SchedulePage'
import { getInitData, getLanguageHint, initTelegram, isInTelegram } from './telegram'

function NotInTelegram() {
  const { t } = useI18n()
  return (
    <main className="page">
      <EmptyState title={t('tg.title')} body={t('tg.body')} />
    </main>
  )
}

function Shell({ onLang }: { onLang: (lang: ReturnType<typeof normalizeLang>) => void }) {
  const [tab, setTab] = useState<Tab>('home')
  const [toast, setToast] = useState<{ text: string; kind: 'success' | 'error'; id: number } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const notify = useCallback((text: string, kind: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ text, kind, id: Date.now() })
    toastTimer.current = setTimeout(() => setToast(null), 4500)
  }, [])
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current) }, [])
  const client = useMemo(() => createApiClient({ getInitData, language: getLanguageHint }), [])
  const me = useResource((s) => client.me(s), true)
  const channels = useResource((s) => client.channels(s), tab === 'me' || tab === 'post')
  const feed = useScheduleFeed(client, tab === 'schedule')
  const botUsername = me.data?.bot.username ?? null

  const profileLang = me.data?.user.language
  useEffect(() => {
    if (profileLang) onLang(profileLang)
  }, [profileLang, onLang])

  const value = useMemo<AppData>(
    () => ({ client, me, channels, feed, go: setTab, botUsername, notify, setLang: onLang }),
    [client, me, channels, feed, botUsername, notify, onLang],
  )

  return (
    <AppDataContext.Provider value={value}>
      <div className="shell">
        <OfflineBanner />
        {tab === 'home' && <HomePage />}
        {tab === 'post' && <PostPage />}
        {tab === 'schedule' && <SchedulePage />}
        {tab === 'me' && <MePage />}
        <TabBar active={tab} onChange={setTab} />
        {toast && <Toast key={toast.id} text={toast.text} kind={toast.kind} />}
      </div>
    </AppDataContext.Provider>
  )
}

export default function App() {
  // Pre-/me til: faqat interfeys ishorasi (autentifikatsiya emas); /me kelgach profil tili ishlatiladi.
  const [lang, setLang] = useState(() => normalizeLang(getLanguageHint()))
  const inTelegram = isInTelegram()

  useEffect(() => initTelegram((scheme) => {
    document.documentElement.dataset.theme = scheme
  }), [])
  useEffect(() => { document.documentElement.lang = lang }, [lang])

  return (
    <I18nProvider lang={lang}>
      {inTelegram ? <Shell onLang={setLang} /> : <NotInTelegram />}
    </I18nProvider>
  )
}
