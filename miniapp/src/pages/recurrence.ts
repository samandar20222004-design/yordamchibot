import type { RecurrenceInput } from '../api/types'
import type { MessageKey } from '../i18n'

/** Bitmask: Du=1, Se=2, Ch=4, Pa=8, Ju=16, Sh=32, Ya=64 (server bilan bir xil). */
export const WEEKEND_MASK = 32 | 64
export const WORKDAYS_MASK = 1 | 2 | 4 | 8 | 16
export const ALL_MASK = 127
export const TASHKENT_TZ = 'Asia/Tashkent'

const DAY_FMT = new Intl.DateTimeFormat('en-US', { timeZone: TASHKENT_TZ, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const WEEKDAY_INDEX: Record<string, number> = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 }

/** Instantning Toshkent vaqtidagi hafta kuni (Du=0), soat va daqiqasi. Takrorlanish qoidalari server tomonida shu zonada hisoblanadi. */
export function tashkentParts(date: Date): { weekday: number; time: string } {
  const parts = DAY_FMT.formatToParts(date)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const hour = get('hour') === '24' ? '00' : get('hour')
  return { weekday: WEEKDAY_INDEX[get('weekday')] ?? 0, time: `${hour}:${get('minute')}` }
}

export function maskOf(days: number[]): number {
  return days.reduce((m, d) => m | (1 << d), 0)
}

export function daysOf(mask: number): number[] {
  return [0, 1, 2, 3, 4, 5, 6].filter((d) => mask & (1 << d))
}

/** `date` dan boshlab (o'zi ham) Toshkent hafta kuni `mask` ga mos eng yaqin payt (Toshkentda yozgi vaqt yo'q: +24 soat = ertasi kun). */
export function alignToWeekdays(date: Date, mask: number): Date {
  let d = date
  for (let i = 0; i < 8; i += 1) {
    if (mask & (1 << tashkentParts(d).weekday)) return d
    d = new Date(d.getTime() + 24 * 3600 * 1000)
  }
  return date
}

/** UI tanlovi -> serverga yuboriladigan takrorlanish (yoki null). Vaqt va kun `scheduledAt` ning Toshkent ko'rinishidan olinadi. */
export interface RepeatChoice {
  kind: 'none' | 'daily' | 'interval' | 'weekdays'
  interval: number
  mask: number
  /** Kuniga IKKI vaqt (faqat `daily`): ikkinchi vaqt HH:MM (ertalab va kechqurun); null = bitta vaqt. */
  time2?: string | null
}

export const DEFAULT_REPEAT: RepeatChoice = { kind: 'none', interval: 2, mask: WEEKEND_MASK, time2: null }

/** Ikkinchi vaqt uchun mantiqiy boshlang'ich: ertalab bo'lsa 18:00, aks holda 09:00. */
export function suggestSecondTime(first: string): string {
  const h = Number(first.slice(0, 2))
  return h < 12 ? '18:00' : '09:00'
}

export function buildRecurrence(choice: RepeatChoice, scheduledAt: Date): RecurrenceInput | null {
  const { time } = tashkentParts(scheduledAt)
  if (choice.kind === 'daily') {
    if (choice.time2 && choice.time2 !== time) return { type: 'twice', day: null, time, time2: choice.time2 }
    return { type: 'daily', day: null, time }
  }
  if (choice.kind === 'interval') {
    const n = Math.round(choice.interval)
    if (!(n >= 1 && n <= 30)) return null
    return n === 1 ? { type: 'daily', day: null, time } : { type: 'interval', day: n, time }
  }
  if (choice.kind === 'weekdays') {
    const mask = choice.mask & ALL_MASK
    if (mask === 0) return null
    if (mask === ALL_MASK) return { type: 'daily', day: null, time }
    const days = daysOf(mask)
    return days.length === 1 ? { type: 'weekly', day: days[0]!, time } : { type: 'weekdays', day: mask, time }
  }
  return null
}

/** Serverdagi (yoki taklifdagi) takrorlanish -> UI tanlovi (tahrirlash/qo'llash uchun). */
export function choiceFromRecurrence(r: RecurrenceInput | null): RepeatChoice {
  if (!r) return DEFAULT_REPEAT
  if (r.type === 'daily') return { ...DEFAULT_REPEAT, kind: 'daily' }
  if (r.type === 'twice') return { ...DEFAULT_REPEAT, kind: 'daily', time2: r.time2 ?? null }
  if (r.type === 'interval') return { ...DEFAULT_REPEAT, kind: 'interval', interval: r.day ?? 2 }
  if (r.type === 'weekly') return { ...DEFAULT_REPEAT, kind: 'weekdays', mask: 1 << (r.day ?? 0) }
  return { ...DEFAULT_REPEAT, kind: 'weekdays', mask: r.day ?? WEEKEND_MASK }
}

const WEEKDAY_KEYS = [1, 2, 3, 4, 5, 6, 7].map((n) => `cal.w${n}` as MessageKey)

/** Takrorlanishning o'qiladigan tavsifi: "Har 2 kunda 18:30", "Dam olish kunlari 12:00", "Du, Ch 10:00". */
export function describeRecurrence(
  r: { type: string; day?: number | null; time?: string | null; time2?: string | null },
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
): string | null {
  const time = r.time ?? ''
  if (!time) return null // tafsilot yo'q (eski yozuv): chaqiruvchi umumiy "Takrorlanadi" belgisini ko'rsatadi
  if (r.type === 'daily') return t('rec.daily', { time })
  if (r.type === 'twice' && r.time2) return t('rec.twice', { time, time2: r.time2 })
  if (r.type === 'interval' && r.day) return t('rec.interval', { n: r.day, time })
  if (r.type === 'weekly' && r.day != null && r.day >= 0 && r.day <= 6) return t('rec.days', { days: t(WEEKDAY_KEYS[r.day]!), time })
  if (r.type === 'weekdays' && r.day) {
    if (r.day === WEEKEND_MASK) return t('rec.weekends', { time })
    if (r.day === WORKDAYS_MASK) return t('rec.workdays', { time })
    return t('rec.days', { days: daysOf(r.day).map((d) => t(WEEKDAY_KEYS[d]!)).join(', '), time })
  }
  return null
}
