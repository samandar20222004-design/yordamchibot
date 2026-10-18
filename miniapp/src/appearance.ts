// Foydalanuvchi o'zi sozlaydigan ko'rinish: rang, fon, mavzu, zichlik, shrift, harakat, pastki panel va bosh sahifa bo'limlari.
// Saqlash: mahalliy (localStorage — darhol, miltillashsiz) + Telegram CloudStorage (qurilmalar o'rtasida). Har qanday yuklangan
// qiymat `sanitize` dan o'tadi (oq ro'yxat): buzilgan/soxta saqlangan ma'lumot ilovani buzmaydi.
import { cloudGet, cloudSet, setHapticsEnabled } from './telegram'

export const TAB_IDS = ['home', 'post', 'schedule', 'market', 'me'] as const
export type TabId = (typeof TAB_IDS)[number]
export const ACCENTS = ['auto', 'blue', 'violet', 'green', 'rose', 'orange', 'teal', 'red', 'graphite'] as const
export const BACKGROUNDS = ['auto', 'plain', 'sunset', 'ocean', 'forest', 'midnight', 'paper', 'dots'] as const
export const THEMES = ['auto', 'light', 'dark'] as const
export const DENSITIES = ['comfortable', 'compact'] as const
export const RADII = ['soft', 'round', 'square'] as const
export const FONTS = ['small', 'medium', 'large'] as const
export const HOME_SECTIONS = ['next', 'stats', 'market', 'tips'] as const

export type Accent = (typeof ACCENTS)[number]
export type Background = (typeof BACKGROUNDS)[number]
export type ThemePref = (typeof THEMES)[number]
export type Density = (typeof DENSITIES)[number]
export type Radius = (typeof RADII)[number]
export type FontSize = (typeof FONTS)[number]
export type HomeSection = (typeof HOME_SECTIONS)[number]

export interface Appearance {
  accent: Accent
  background: Background
  theme: ThemePref
  density: Density
  radius: Radius
  font: FontSize
  motion: boolean
  haptics: boolean
  /** Pastki paneldagi tablar (tartib va ko'rinish); `me` har doim bor. */
  tabs: TabId[]
  start: TabId
  home: Record<HomeSection, boolean>
}

export const DEFAULT_APPEARANCE: Appearance = {
  accent: 'auto', background: 'auto', theme: 'auto', density: 'comfortable', radius: 'soft', font: 'medium',
  motion: true, haptics: true, tabs: ['home', 'post', 'schedule', 'market', 'me'], start: 'home',
  home: { next: true, stats: true, market: true, tips: true },
}

const STORAGE_KEY = 'pa.appearance.v1'

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

/** Pastki panel: faqat ma'lum tablar, takrorsiz, `me` majburiy, kamida 2 ta. */
export function sanitizeTabs(raw: unknown): TabId[] {
  const seen = new Set<TabId>()
  if (Array.isArray(raw)) {
    for (const v of raw) if (typeof v === 'string' && (TAB_IDS as readonly string[]).includes(v)) seen.add(v as TabId)
  }
  if (seen.size === 0) return [...DEFAULT_APPEARANCE.tabs]
  seen.add('me')
  if (seen.size < 2) seen.add('home')
  return [...seen]
}

/** Har qanday kirishni (JSON, eski versiya, buzilgan qiymat) to'g'ri `Appearance` ga aylantiradi. */
export function sanitize(raw: unknown): Appearance {
  const o = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  const d = DEFAULT_APPEARANCE
  const tabs = sanitizeTabs(o.tabs)
  const home = (typeof o.home === 'object' && o.home !== null ? o.home : {}) as Record<string, unknown>
  const start = pick(o.start, TAB_IDS, d.start)
  return {
    accent: pick(o.accent, ACCENTS, d.accent), background: pick(o.background, BACKGROUNDS, d.background),
    theme: pick(o.theme, THEMES, d.theme), density: pick(o.density, DENSITIES, d.density),
    radius: pick(o.radius, RADII, d.radius), font: pick(o.font, FONTS, d.font),
    motion: typeof o.motion === 'boolean' ? o.motion : d.motion, haptics: typeof o.haptics === 'boolean' ? o.haptics : d.haptics,
    tabs, start: tabs.includes(start) ? start : tabs[0],
    home: Object.fromEntries(HOME_SECTIONS.map((k) => [k, typeof home[k] === 'boolean' ? home[k] : d.home[k]])) as Record<HomeSection, boolean>,
  }
}

interface Stored { t: number; v: Appearance }

export function loadLocal(): Appearance {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return sanitize(null)
    const parsed = JSON.parse(raw) as Partial<Stored>
    return sanitize(parsed?.v ?? parsed)
  } catch {
    return sanitize(null)
  }
}

function localTimestamp(): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? Number((JSON.parse(raw) as Partial<Stored>).t) || 0 : 0
  } catch {
    return 0
  }
}

export function save(value: Appearance): void {
  const payload = JSON.stringify({ t: Date.now(), v: value } satisfies Stored)
  try {
    window.localStorage.setItem(STORAGE_KEY, payload)
  } catch {
    /* maxfiy rejim: saqlanmaydi, sessiya ichida ishlaydi */
  }
  cloudSet(STORAGE_KEY, payload)
}

/** Bulutdagi nusxa mahalliydan yangiroq bo'lsa qaytaradi (boshqa qurilmada o'zgartirilgan). */
export async function loadCloudIfNewer(): Promise<Appearance | null> {
  const raw = await cloudGet(STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<Stored>
    if (typeof parsed.t !== 'number' || parsed.t <= localTimestamp()) return null
    return sanitize(parsed.v)
  } catch {
    return null
  }
}

/** Ko'rinishni `<html>` ga qo'llaydi (CSS data-atributlar orqali). */
export function applyAppearance(a: Appearance, scheme: 'light' | 'dark', root: HTMLElement = document.documentElement): void {
  root.dataset.accent = a.accent
  root.dataset.bg = a.background
  root.dataset.density = a.density
  root.dataset.radius = a.radius
  root.dataset.font = a.font
  root.dataset.motion = a.motion ? 'on' : 'off'
  root.dataset.theme = a.theme === 'auto' ? scheme : a.theme
  setHapticsEnabled(a.haptics)
}

/** Tab tartibini bir pog'onaga siljitadi (`me` ham siljiy oladi). */
export function moveTab(tabs: TabId[], id: TabId, dir: -1 | 1): TabId[] {
  const i = tabs.indexOf(id)
  const j = i + dir
  if (i < 0 || j < 0 || j >= tabs.length) return tabs
  const next = [...tabs]
  ;[next[i], next[j]] = [next[j], next[i]]
  return next
}

/** Tabni ko'rsatish/yashirish (`me` yashirilmaydi, kamida 2 tab qoladi). Yangi tab oxiriga qo'shiladi. */
export function toggleTab(tabs: TabId[], id: TabId): TabId[] {
  if (tabs.includes(id)) {
    if (id === 'me' || tabs.length <= 2) return tabs
    return tabs.filter((t) => t !== id)
  }
  return [...tabs, id]
}
