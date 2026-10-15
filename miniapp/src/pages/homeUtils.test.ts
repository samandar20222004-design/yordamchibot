import { describe, expect, it } from 'vitest'
import { countdownTo, greetingKey, tipIndex, TIP_COUNT } from './homeUtils'

describe('greetingKey', () => {
  it('kun vaqtiga qarab', () => {
    expect([5, 11].map(greetingKey)).toEqual(['home.greet.morning', 'home.greet.morning'])
    expect([12, 17].map(greetingKey)).toEqual(['home.greet.day', 'home.greet.day'])
    expect([18, 22].map(greetingKey)).toEqual(['home.greet.evening', 'home.greet.evening'])
    expect([23, 0, 4].map(greetingKey)).toEqual(['home.greet.night', 'home.greet.night', 'home.greet.night'])
  })
})

describe('countdownTo', () => {
  const now = new Date('2026-10-15T10:00:00Z')
  const at = (mins: number) => new Date(now.getTime() + mins * 60000)
  it('hozir / daqiqa / soat / soat+daqiqa / kun', () => {
    expect(countdownTo(at(0), now)).toEqual({ key: 'cd.now' })
    expect(countdownTo(at(-30), now)).toEqual({ key: 'cd.now' })
    expect(countdownTo(at(45), now)).toEqual({ key: 'cd.min', n: 45 })
    expect(countdownTo(at(120), now)).toEqual({ key: 'cd.hour', n: 2 })
    expect(countdownTo(at(135), now)).toEqual({ key: 'cd.hourMin', h: 2, m: 15 })
    expect(countdownTo(at(3 * 24 * 60 + 5), now)).toEqual({ key: 'cd.day', n: 3 })
  })
})

describe('tipIndex', () => {
  it('0..TIP_COUNT-1, kun ichida barqaror, ketma-ket kunlarda o\'zgaradi', () => {
    const a = tipIndex(new Date(2026, 9, 15, 1))
    expect(a).toBeGreaterThanOrEqual(0)
    expect(a).toBeLessThan(TIP_COUNT)
    expect(tipIndex(new Date(2026, 9, 15, 23))).toBe(a)
    expect(tipIndex(new Date(2026, 9, 16))).toBe((a + 1) % TIP_COUNT)
  })
})
