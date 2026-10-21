import { afterEach, describe, expect, it } from 'vitest'
import { getAppTimezone, setAppTimezone, tashkentParts, TASHKENT_TZ } from './pages/recurrence'

describe('foydalanuvchi vaqt zonasi', () => {
  afterEach(() => setAppTimezone(undefined))

  it('standart Toshkent', () => {
    expect(getAppTimezone()).toBe(TASHKENT_TZ)
    expect(tashkentParts(new Date('2026-10-15T13:00:00Z'))).toEqual({ weekday: 3, time: '18:00', day: 15 })
  })

  it('Berlin zonasida soat va hafta kuni mahalliy', () => {
    setAppTimezone('Europe/Berlin')
    expect(getAppTimezone()).toBe('Europe/Berlin')
    expect(tashkentParts(new Date('2026-10-15T16:00:00Z'))).toEqual({ weekday: 3, time: '18:00', day: 15 })
  })

  it('kun chegarasi: UTC 23:30 Tokioda ertasi kun 08:30', () => {
    setAppTimezone('Asia/Tokyo')
    expect(tashkentParts(new Date('2026-10-15T23:30:00Z'))).toEqual({ weekday: 4, time: '08:30', day: 16 })
  })

  it('yaroqsiz zona Toshkentga qaytadi', () => {
    setAppTimezone('Mars/Olympus')
    expect(getAppTimezone()).toBe(TASHKENT_TZ)
  })
})
