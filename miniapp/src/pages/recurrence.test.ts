import { describe, expect, it } from 'vitest'
import { translate } from '../i18n'
import {
  ALL_MASK, WEEKEND_MASK, WORKDAYS_MASK, alignToWeekdays, buildRecurrence, choiceFromRecurrence, daysOf, describeRecurrence,
  DEFAULT_REPEAT, maskOf, suggestSecondTime, tashkentParts,
} from './recurrence'

// 2026-10-15 12:00 Toshkent = 07:00 UTC (payshanba)
const THU = new Date('2026-10-15T07:00:00Z')

describe('Toshkent vaqti qismlari', () => {
  it('hafta kuni (Du=0) va HH:MM', () => {
    expect(tashkentParts(THU)).toEqual({ weekday: 3, time: '12:00' })
    expect(tashkentParts(new Date('2026-10-17T07:30:00Z'))).toEqual({ weekday: 5, time: '12:30' })
  })
  it('qurilma zonasidan mustaqil: 19:00 UTC = ertasi 00:00 Toshkent (kun almashadi)', () => {
    expect(tashkentParts(new Date('2026-10-15T19:00:00Z'))).toEqual({ weekday: 4, time: '00:00' })
  })
})

describe('maska yordamchilari', () => {
  it('maskOf/daysOf qaytma; dam olish=96, ish kunlari=31', () => {
    expect(WEEKEND_MASK).toBe(96)
    expect(WORKDAYS_MASK).toBe(31)
    expect(maskOf([5, 6])).toBe(WEEKEND_MASK)
    expect(daysOf(WORKDAYS_MASK)).toEqual([0, 1, 2, 3, 4])
  })
  it('alignToWeekdays: payshanba -> shanba; mos bo\'lsa o\'zgarmaydi; vaqt saqlanadi', () => {
    const sat = alignToWeekdays(THU, WEEKEND_MASK)
    expect(sat.toISOString()).toBe('2026-10-17T07:00:00.000Z')
    expect(alignToWeekdays(sat, WEEKEND_MASK).getTime()).toBe(sat.getTime())
    expect(alignToWeekdays(THU, 1 << 3).getTime()).toBe(THU.getTime())
  })
})

describe('buildRecurrence (server shartnomasi bilan bir xil kanonik shakl)', () => {
  const base = { interval: 2, mask: WEEKEND_MASK }
  it('none -> null', () => expect(buildRecurrence({ kind: 'none', ...base }, THU)).toBeNull())
  it('daily', () => expect(buildRecurrence({ kind: 'daily', ...base }, THU)).toEqual({ type: 'daily', day: null, time: '12:00' }))
  it('interval 2..30; 1 -> daily; yaroqsiz -> null', () => {
    expect(buildRecurrence({ kind: 'interval', ...base, interval: 3 }, THU)).toEqual({ type: 'interval', day: 3, time: '12:00' })
    expect(buildRecurrence({ kind: 'interval', ...base, interval: 1 }, THU)?.type).toBe('daily')
    expect(buildRecurrence({ kind: 'interval', ...base, interval: 31 }, THU)).toBeNull()
    expect(buildRecurrence({ kind: 'interval', ...base, interval: 0 }, THU)).toBeNull()
  })
  it('weekdays: dam olish -> weekdays(96); bitta kun -> weekly; 7 kun -> daily; bo\'sh -> null', () => {
    expect(buildRecurrence({ kind: 'weekdays', ...base, mask: WEEKEND_MASK }, THU)).toEqual({ type: 'weekdays', day: 96, time: '12:00' })
    expect(buildRecurrence({ kind: 'weekdays', ...base, mask: 1 << 3 }, THU)).toEqual({ type: 'weekly', day: 3, time: '12:00' })
    expect(buildRecurrence({ kind: 'weekdays', ...base, mask: ALL_MASK }, THU)?.type).toBe('daily')
    expect(buildRecurrence({ kind: 'weekdays', ...base, mask: 0 }, THU)).toBeNull()
  })
  it('vaqt qurilma zonasiga emas, Toshkentga ko\'ra olinadi', () => {
    expect(buildRecurrence({ kind: 'daily', ...base }, new Date('2026-10-15T19:00:00Z'))?.time).toBe('00:00')
  })
})

describe('choiceFromRecurrence <-> buildRecurrence', () => {
  it('taklif qaytma aylanishi saqlanadi', () => {
    for (const r of [
      { type: 'daily' as const, day: null, time: '12:00' }, { type: 'interval' as const, day: 4, time: '12:00' },
      { type: 'weekly' as const, day: 3, time: '12:00' }, { type: 'weekdays' as const, day: 96, time: '12:00' },
    ]) expect(buildRecurrence(choiceFromRecurrence(r), THU)).toEqual(r)
    expect(choiceFromRecurrence(null).kind).toBe('none')
  })
})

describe('describeRecurrence (3 til)', () => {
  const tr = (lang: 'uz' | 'ru' | 'en') => (k: Parameters<typeof translate>[1], v?: Record<string, string | number>) => translate(lang, k, v)
  it('uz', () => {
    const t = tr('uz')
    expect(describeRecurrence({ type: 'daily', time: '12:00' }, t)).toBe('Har kuni 12:00')
    expect(describeRecurrence({ type: 'interval', day: 2, time: '18:30' }, t)).toBe('Har 2 kunda 18:30')
    expect(describeRecurrence({ type: 'weekdays', day: 96, time: '12:00' }, t)).toBe('Dam olish kunlari 12:00')
    expect(describeRecurrence({ type: 'weekdays', day: 31, time: '09:00' }, t)).toBe('Ish kunlari 09:00')
    expect(describeRecurrence({ type: 'weekdays', day: 5, time: '10:00' }, t)).toBe('Du, Ch · 10:00')
    expect(describeRecurrence({ type: 'weekly', day: 4, time: '17:00' }, t)).toBe('Ju · 17:00')
  })
  it('ru va en', () => {
    expect(describeRecurrence({ type: 'weekdays', day: 96, time: '12:00' }, tr('ru'))).toBe('По выходным, 12:00')
    expect(describeRecurrence({ type: 'interval', day: 3, time: '12:00' }, tr('en'))).toBe('Every 3 days, 12:00')
  })
  it('tafsilot yo\'q/noma\'lum -> null (chaqiruvchi umumiy belgini ko\'rsatadi)', () => {
    const t = tr('uz')
    expect(describeRecurrence({ type: 'daily', time: null }, t)).toBeNull()
    expect(describeRecurrence({ type: 'interval', day: null, time: '12:00' }, t)).toBeNull()
    expect(describeRecurrence({ type: 'monthly', day: 1, time: '12:00' }, t)).toBeNull()
    expect(describeRecurrence({ type: 'weekly', day: 9, time: '12:00' }, t)).toBeNull()
  })
})

describe('kuniga ikki vaqt (ertalab va kechqurun)', () => {
  const at = new Date('2026-10-15T04:00:00Z') // 09:00 Toshkent
  it('daily + time2 -> twice; time2 scheduledAt bilan bir xil bo\'lsa oddiy daily', () => {
    expect(buildRecurrence({ ...DEFAULT_REPEAT, kind: 'daily', time2: '18:00' }, at)).toEqual({ type: 'twice', day: null, time: '09:00', time2: '18:00' })
    expect(buildRecurrence({ ...DEFAULT_REPEAT, kind: 'daily', time2: '09:00' }, at)).toEqual({ type: 'daily', day: null, time: '09:00' })
    expect(buildRecurrence({ ...DEFAULT_REPEAT, kind: 'daily', time2: null }, at)).toEqual({ type: 'daily', day: null, time: '09:00' })
  })
  it('serverdagi twice -> UI tanlovi va tavsif', () => {
    expect(choiceFromRecurrence({ type: 'twice', day: null, time: '09:00', time2: '18:00' })).toMatchObject({ kind: 'daily', time2: '18:00' })
    const t = (k: string, v?: Record<string, string | number>) => `${k}|${v?.time}|${v?.time2}`
    expect(describeRecurrence({ type: 'twice', time: '09:00', time2: '18:00' }, t as never)).toBe('rec.twice|09:00|18:00')
  })
  it('suggestSecondTime: ertalab -> 18:00, kech -> 09:00', () => {
    expect(suggestSecondTime('09:00')).toBe('18:00')
    expect(suggestSecondTime('19:30')).toBe('09:00')
  })
})
