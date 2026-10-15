// Telegram WebApp SDK uchun xavfsiz o'ram: SDK yo'q yoki xato bersa ilova qulamaydi.
// MUHIM: autentifikatsiya FAQAT `initData` (xom satr) orqali serverda tekshiriladi.
// `initDataUnsafe` imzosiz — undan faqat interfeys tili uchun ishora sifatida foydalanamiz.

interface TgWebApp {
  initData?: string
  initDataUnsafe?: { user?: { language_code?: string; photo_url?: string } }
  colorScheme?: 'light' | 'dark'
  ready?: () => void
  expand?: () => void
  close?: () => void
  openTelegramLink?: (url: string) => void
  onEvent?: (event: string, cb: () => void) => void
  offEvent?: (event: string, cb: () => void) => void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TgWebApp }
  }
}

function webApp(): TgWebApp | undefined {
  try {
    return window.Telegram?.WebApp
  } catch {
    return undefined
  }
}

/** Server tekshiradigan xom `initData`. Bo'sh = Telegram ichida emas. */
export function getInitData(): string {
  const v = webApp()?.initData
  return typeof v === 'string' ? v : ''
}

export function isInTelegram(): boolean {
  return getInitData() !== ''
}

/** Faqat interfeys tili uchun ishora (autentifikatsiya EMAS). */
export function getLanguageHint(): string {
  return webApp()?.initDataUnsafe?.user?.language_code ?? navigator.language ?? 'uz'
}

/** Telegram profil rasmi URL (faqat https; imzosiz ishora — faqat ko'rsatish uchun, autentifikatsiya EMAS). */
export function getUserPhotoUrl(): string | null {
  const url = webApp()?.initDataUnsafe?.user?.photo_url
  return typeof url === 'string' && /^https:\/\/[^\s"'<>]+$/.test(url) && url.length <= 512 ? url : null
}

export function getColorScheme(): 'light' | 'dark' {
  const scheme = webApp()?.colorScheme
  if (scheme === 'light' || scheme === 'dark') return scheme
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function closeApp(): void {
  try {
    webApp()?.close?.()
  } catch {
    /* e'tiborsiz */
  }
}

// Telegram username: 5..32 belgi, harf bilan boshlanadi, harf/raqam/pastki chiziq.
const USERNAME_RE = /^[A-Za-z][A-Za-z0-9_]{4,31}$/

export function isValidBotUsername(username: string | null | undefined): username is string {
  return typeof username === 'string' && USERNAME_RE.test(username)
}

/**
 * Botni Telegram ichida ochadi: FAQAT `https://t.me/<username>` (chatni ochadi, xolos).
 * `?start=<payload>` ATAYLAB ishlatilmaydi: bot `/start` handleri faqat `ref_<id>` ni tanlaydi va qolgan
 * boshqa payloadlarni e'tiborsiz qoldiradi; /newpost va PRO oqimlari havoladan ochilmaydi.
 * Shuning uchun /newpost va PRO oqimlari havola orqali EMAS, foydalanuvchi buyruq yuborishi bilan ochiladi.
 */
export function openBot(username: string | null | undefined): boolean {
  if (!isValidBotUsername(username)) return false
  const url = `https://t.me/${username}`
  const app = webApp()
  try {
    if (app?.openTelegramLink) {
      app.openTelegramLink(url)
      return true
    }
  } catch {
    /* quyida zaxira */
  }
  window.open(url, '_blank', 'noopener,noreferrer')
  return true
}

/** SDK'ni ishga tushiradi va tema/viewport o'zgarishlariga obuna bo'ladi. Qaytgan funksiya obunani bekor qiladi. */
export function initTelegram(onTheme: (scheme: 'light' | 'dark') => void): () => void {
  const app = webApp()
  try {
    app?.ready?.()
    app?.expand?.()
  } catch {
    /* SDK xatosi ilovani to'xtatmaydi */
  }
  const apply = () => onTheme(getColorScheme())
  apply()
  try {
    app?.onEvent?.('themeChanged', apply)
  } catch {
    /* e'tiborsiz */
  }
  return () => {
    try {
      app?.offEvent?.('themeChanged', apply)
    } catch {
      /* e'tiborsiz */
    }
  }
}
