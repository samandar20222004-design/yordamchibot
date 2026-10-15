import { config } from '../config'

/** Backend "cheksiz" ni 999 bilan beradi (PRO limitlari). */
export function isUnlimited(limit: number): boolean {
  return limit >= config.unlimitedThreshold
}

export function localDayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

export type DayLabel = 'today' | 'tomorrow' | 'date'

export interface DayGroup<T> {
  key: string
  label: DayLabel
  /** `label === 'date'` bo'lganda ko'rsatiladigan namuna ISO. */
  sampleIso: string
  items: T[]
}

/** Elementlarni mahalliy kun bo'yicha guruhlaydi (tartib saqlanadi). Yaroqsiz sana alohida "date" guruhida. */
export function groupByDay<T>(items: T[], getIso: (item: T) => string | null, now: Date = new Date()): DayGroup<T>[] {
  const today = localDayKey(now)
  const tomorrowDate = new Date(now)
  tomorrowDate.setDate(now.getDate() + 1)
  const tomorrow = localDayKey(tomorrowDate)
  const groups: DayGroup<T>[] = []
  for (const item of items) {
    const iso = getIso(item)
    const date = iso ? new Date(iso) : null
    const valid = date !== null && !Number.isNaN(date.getTime())
    const key = valid ? localDayKey(date) : 'unknown'
    let group = groups.find((g) => g.key === key)
    if (!group) {
      group = {
        key,
        label: key === today ? 'today' : key === tomorrow ? 'tomorrow' : 'date',
        sampleIso: iso ?? '',
        items: [],
      }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
}

const pad = (n: number) => String(n).padStart(2, '0')

/** `<input type="datetime-local">` qiymati (mahalliy vaqt, zonasiz): "YYYY-MM-DDTHH:mm". */
export function toLocalInputValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function isoToLocalInput(iso: string | null): string {
  const d = iso ? new Date(iso) : null
  return d && !Number.isNaN(d.getTime()) ? toLocalInputValue(d) : ''
}

/** Mahalliy kiritma -> UTC ISO (server zonali vaqt talab qiladi). Yaroqsiz -> null. */
export function localInputToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** Kiritma kamida `minLeadMs` kelajakdami (server 60 s talab qiladi; mijoz zaxira bilan 120 s). */
export function isFutureEnough(value: string, now: number = Date.now()): boolean {
  const iso = localInputToIso(value)
  return iso !== null && new Date(iso).getTime() >= now + config.minLeadMs
}

export function defaultScheduleValue(now: Date = new Date()): string {
  const d = new Date(now.getTime() + 60 * 60 * 1000)
  d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0)
  return toLocalInputValue(d)
}

export interface MonthGrid {
  /** Birinchi katak (dushanba) — mahalliy yarim tun. */
  start: Date
  /** Oxirgi katakdan KEYINGI mahalliy yarim tun (kalendar so'rovining `to` qiymati, kiritilmaydi). */
  end: Date
  /** 6 hafta x 7 kun = 42 katak (mahalliy yarim tun). */
  days: Date[]
}

/** Oy tarmog'i: dushanbadan boshlanadi, doim 42 katak (oy almashganda balandlik sakramaydi). `month` 0-11. */
export function monthGrid(year: number, month: number): MonthGrid {
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7 // dushanba = 0
  // Konstruktor bilan quriladi (24 soat qo'shilmaydi): yozgi/qishki vaqt o'tishida ham har katak mahalliy yarim tun.
  const days = Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - offset + i))
  return { start: days[0]!, end: new Date(year, month, 1 - offset + 42), days }
}

export function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
  const d = new Date(year, month + delta, 1)
  return { year: d.getFullYear(), month: d.getMonth() }
}
