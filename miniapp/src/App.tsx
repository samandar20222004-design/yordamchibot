import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppDataContext, type AppData } from './AppData'
import { DEFAULT_APPEARANCE, applyAppearance, loadCloudIfNewer, loadLocal, sanitize, save, type Appearance } from './appearance'
import { hideBoot } from './boot'
import { createApiClient } from './api/client'
import { OfflineBanner, TabBar, type Tab } from './components/Shell'
import { Toast } from './components/Dialog'
import { EmptyState } from './components/ui'
import { I18nProvider, normalizeLang, useI18n } from './i18n'
import { useResource } from './hooks/useResource'
import { useScheduleFeed } from './hooks/useScheduleFeed'
import { HomePage } from './pages/HomePage'
import { MarketPage } from './pages/MarketPage'
import { MePage } from './pages/MePage'
import { PostPage } from './pages/PostPage'
import { SchedulePage } from './pages/SchedulePage'
import { getColorScheme, getInitData, getInitialTab, getLanguageHint, initTelegram, isInTelegram } from './telegram'

function NotInTelegram() {
  const { t } = useI18n()
  return (
    <main className="page">
      <EmptyState title={t('tg.title')} body={t('tg.body')} />
    </main>
  )
}

function Shell({ onLang, appearance, setAppearance, resetAppearance }: {
  onLang: (lang: ReturnType<typeof normalizeLang>) => void
  appearance: Appearance
  setAppearance: (patch: Partial<Appearance>) => void
  resetAppearance: () => void
}) {
  const [tab, setTab] = useState<Tab>(() => getInitialTab() ?? appearance.start)
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
  const draft = useResource(async (s) => ({ draft: await client.draft(s) }), true)
  const feed = useScheduleFeed(client, tab === 'schedule')
  const botUsername = me.data?.bot.username ?? null
  // 💰 Birja: o'qilmagan xabarlar (tab nishoni). Har daqiqada va ilova qayta ko'ringanda yangilanadi.
  const unreadRes = useResource((s) => client.marketUnread(s).then((n) => ({ n })), true)
  const reloadUnread = unreadRes.reload
  useEffect(() => {
    const id = setInterval(() => { if (document.visibilityState === 'visible') reloadUnread() }, 60_000)
    return () => clearInterval(id)
  }, [reloadUnread])
  const unread = unreadRes.data?.n ?? 0

  const profileLang = me.data?.user.language
  useEffect(() => {
    if (profileLang) onLang(profileLang)
  }, [profileLang, onLang])

  // Botdan qoralama bilan kelgan foydalanuvchi to'g'ridan-to'g'ri tahrirlagichga tushadi (bir marta).
  const autoOpened = useRef(getInitialTab() !== null) // aniq ?tab= bo'lsa, qoralama o'rniga shu bo'lim ochiladi
  const hasDraft = Boolean(draft.data?.draft)
  useEffect(() => {
    if (hasDraft && !autoOpened.current) {
      autoOpened.current = true
      setTab('post')
    }
  }, [hasDraft])

  const value = useMemo<AppData>(
    () => ({ client, me, channels, draft, feed, go: setTab, unread, refreshUnread: reloadUnread, appearance, setAppearance, resetAppearance, botUsername, notify, setLang: onLang }),
    [client, me, channels, draft, feed, unread, reloadUnread, appearance, setAppearance, resetAppearance, botUsername, notify, onLang],
  )

  // Yuklash ekrani (#boot, index.html) /me kelguncha turadi; keyin (yoki xatoda) bir marta yashiriladi.
  const ready = me.data !== null || me.error !== null
  useEffect(() => { if (ready) hideBoot() }, [ready])
  if (!ready) return null

  return (
    <AppDataContext.Provider value={value}>
      <div className="shell">
        <OfflineBanner />
        {tab === 'home' && <HomePage />}
        {tab === 'post' && <PostPage />}
        {tab === 'schedule' && <SchedulePage />}
        {tab === 'market' && <MarketPage />}
        {tab === 'me' && <MePage />}
        <TabBar active={tab} onChange={setTab} badges={{ market: unread }} tabs={appearance.tabs} />
        {toast && <Toast key={toast.id} text={toast.text} kind={toast.kind} />}
      </div>
    </AppDataContext.Provider>
  )
}

export default function App() {
  // Pre-/me til: faqat interfeys ishorasi (autentifikatsiya emas); /me kelgach profil tili ishlatiladi.
  const [lang, setLang] = useState(() => normalizeLang(getLanguageHint()))
  const inTelegram = isInTelegram()
  const [scheme, setScheme] = useState<'light' | 'dark'>(() => getColorScheme())
  const [appearance, setAppearanceState] = useState<Appearance>(() => loadLocal())

  useEffect(() => initTelegram(setScheme), [])
  // Rang/fon/mavzu/zichlik... `<html data-*>` orqali; Telegram mavzusi o'zgarsa ('auto') qayta qo'llanadi.
  useEffect(() => { applyAppearance(appearance, scheme) }, [appearance, scheme])
  // Boshqa qurilmada o'zgartirilgan bo'lsa (Telegram bulutli xotirasi) — yangisi olinadi.
  useEffect(() => {
    let alive = true
    void loadCloudIfNewer().then((remote) => { if (alive && remote) { setAppearanceState(remote); save(remote) } })
    return () => { alive = false }
  }, [])
  const setAppearance = useCallback((patch: Partial<Appearance>) => {
    setAppearanceState((prev) => {
      const next = sanitize({ ...prev, ...patch })
      save(next)
      return next
    })
  }, [])
  const resetAppearance = useCallback(() => {
    const next = sanitize(DEFAULT_APPEARANCE)
    save(next)
    setAppearanceState(next)
  }, [])
  useEffect(() => { document.documentElement.lang = lang }, [lang])

  useEffect(() => { if (!inTelegram) hideBoot() }, [inTelegram])

  return (
    <I18nProvider lang={lang}>
      {inTelegram
        ? <Shell onLang={setLang} appearance={appearance} setAppearance={setAppearance} resetAppearance={resetAppearance} />
        : <NotInTelegram />}
    </I18nProvider>
  )
}
