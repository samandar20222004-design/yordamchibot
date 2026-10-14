import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import type { Lang } from '../api/types'
import { messages, type MessageKey } from './messages'

export type { MessageKey } from './messages'

export function normalizeLang(raw: string | null | undefined): Lang {
  const tag = (raw ?? '').slice(0, 2).toLowerCase()
  return tag === 'ru' || tag === 'en' ? tag : 'uz'
}

const LOCALES: Record<Lang, string> = { uz: 'uz-UZ', ru: 'ru-RU', en: 'en-GB' }

// Brauzerlarda 'uz' Intl oy nomlari to'liq emas (masalan "M10"), shuning uchun o'zbekcha nomlar qo'lda.
const UZ_MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr']
const UZ_MONTHS_SHORT = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek']
const two = (n: number) => String(n).padStart(2, '0')

export function formatUz(date: Date, kind: 'dateTime' | 'date' | 'time'): string {
  const time = `${two(date.getHours())}:${two(date.getMinutes())}`
  if (kind === 'time') return time
  if (kind === 'date') return `${date.getDate()}-${UZ_MONTHS[date.getMonth()]}, ${date.getFullYear()}`
  return `${date.getDate()}-${UZ_MONTHS_SHORT[date.getMonth()]}, ${time}`
}

export function translate(lang: Lang, key: MessageKey, vars?: Record<string, string | number>): string {
  let text = messages[lang][key] ?? messages.uz[key] ?? key
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.split(`{${k}}`).join(String(v))
  return text
}

export interface I18n {
  lang: Lang
  t: (key: MessageKey, vars?: Record<string, string | number>) => string
  formatDateTime: (iso: string) => string
  formatDate: (iso: string) => string
  formatTime: (iso: string) => string
}

const Ctx = createContext<I18n | null>(null)

export function I18nProvider({ lang, children }: { lang: Lang; children: ReactNode }) {
  const t = useCallback<I18n['t']>((key, vars) => translate(lang, key, vars), [lang])
  const value = useMemo<I18n>(() => {
    const locale = LOCALES[lang]
    const dt = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    const d = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', year: 'numeric' })
    const tm = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' })
    const safe = (f: Intl.DateTimeFormat, kind: 'dateTime' | 'date' | 'time', iso: string) => {
      const date = new Date(iso)
      if (Number.isNaN(date.getTime())) return '—'
      return lang === 'uz' ? formatUz(date, kind) : f.format(date)
    }
    return {
      lang,
      t,
      formatDateTime: (iso) => safe(dt, 'dateTime', iso),
      formatDate: (iso) => safe(d, 'date', iso),
      formatTime: (iso) => safe(tm, 'time', iso),
    }
  }, [lang, t])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18n {
  const v = useContext(Ctx)
  if (!v) throw new Error('I18nProvider yo\'q')
  return v
}
