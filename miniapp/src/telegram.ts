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
  HapticFeedback?: {
    impactOccurred?: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void
    notificationOccurred?: (type: 'success' | 'error' | 'warning') => void
    selectionChanged?: () => void
  }
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

/** Botdagi «📱 Mini App» tugmalari `?tab=` bilan ochadi: faqat ma'lum bo'limlar (boshqa qiymat e'tiborsiz). */
export function getInitialTab(): 'home' | 'post' | 'schedule' | 'market' | 'me' | null {
  try {
    const tab = new URLSearchParams(window.location.search).get('tab')
    return tab === 'home' || tab === 'post' || tab === 'schedule' || tab === 'market' || tab === 'me' ? tab : null
  } catch {
    return null
  }
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

/** Botdagi bo'lim (deep-link). Bot `/start go_<bo'lim>` ni FAQAT shu ro'yxat bo'yicha tanlaydi (qat'iy ruxsat ro'yxati). */
export type BotSection = 'plans' | 'settings' | 'help' | 'channels' | 'invite'
const BOT_SECTIONS: readonly BotSection[] = ['plans', 'settings', 'help', 'channels', 'invite']

/**
 * Botni Telegram ichida ochadi: `https://t.me/<username>`; `section` berilsa `?start=go_<bo'lim>` qo'shiladi va bot
 * kerakli bo'limni (masalan tariflar kartasini) o'zi ochadi. Faqat ruxsat ro'yxatidagi bo'limlar; xom payload YO'Q.
 * Chat ochilgach Mini App yopiladi (aks holda sahifa botga o'tmay, ilova ustida qolardi).
 */
export function openBot(username: string | null | undefined, section?: BotSection): boolean {
  if (!isValidBotUsername(username)) return false
  const url = section && BOT_SECTIONS.includes(section) ? `https://t.me/${username}?start=go_${section}` : `https://t.me/${username}`
  const app = webApp()
  haptic('tap')
  try {
    if (app?.openTelegramLink) {
      app.openTelegramLink(url)
      // Telegram bot chatini ochadi, lekin Mini App ustida qolib ketishi mumkin (iOS): qisqa pauzadan so'ng yopamiz — foydalanuvchi to'g'ridan-to'g'ri botda qoladi.
      setTimeout(() => { try { app.close?.() } catch { /* e'tiborsiz */ } }, 300)
      return true
    }
  } catch {
    /* quyida zaxira */
  }
  window.open(url, '_blank', 'noopener,noreferrer')
  return true
}

/** Telegram tebranish (haptic) javobi: tugma bosilganini his qilish uchun. SDK yo'q yoki xato bersa jim. */
export function haptic(kind: 'tap' | 'select' | 'success' | 'error' = 'tap'): void {
  const h = webApp()?.HapticFeedback
  try {
    if (kind === 'select') h?.selectionChanged?.()
    else if (kind === 'success' || kind === 'error') h?.notificationOccurred?.(kind)
    else h?.impactOccurred?.('light')
  } catch {
    /* e'tiborsiz */
  }
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

const CHANNEL_USERNAME = /^[A-Za-z][A-Za-z0-9_]{3,31}$/

/** Ochiq kanalni Telegram'da ochadi (Mini App yopilmaydi). Noto'g'ri nom -> `false`. */
export function openChannel(username: string): boolean {
  if (!CHANNEL_USERNAME.test(username)) return false
  const url = `https://t.me/${username}`
  const app = webApp()
  if (app?.openTelegramLink) {
    app.openTelegramLink(url)
    return true
  }
  try {
    window.open(url, '_blank', 'noopener,noreferrer')
    return true
  } catch {
    return false
  }
}
