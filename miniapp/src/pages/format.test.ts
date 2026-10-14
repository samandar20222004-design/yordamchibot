import { describe, expect, it } from 'vitest'
import { groupByDay, isUnlimited } from './format'

describe('format', () => {
  it('isUnlimited: backend 999 konvensiyasi', () => {
    expect(isUnlimited(999)).toBe(true)
    expect(isUnlimited(5)).toBe(false)
  })
  it('groupByDay: bugun/ertaga/sana va tartib', () => {
    const now = new Date(2026, 9, 14, 12, 0)
    const iso = (d: Date) => d.toISOString()
    const items = [
      { t: iso(new Date(2026, 9, 14, 15, 0)) },
      { t: iso(new Date(2026, 9, 14, 18, 0)) },
      { t: iso(new Date(2026, 9, 15, 9, 0)) },
      { t: iso(new Date(2026, 9, 20, 9, 0)) },
      { t: null },
    ]
    const groups = groupByDay(items, (i) => i.t, now)
    expect(groups.map((g) => g.label)).toEqual(['today', 'tomorrow', 'date', 'date'])
    expect(groups[0].items).toHaveLength(2)
    expect(groups[3].key).toBe('unknown')
  })
  it('yaroqsiz sana qulamaydi', () => {
    expect(groupByDay([{ t: 'not-a-date' }], (i) => i.t)[0].key).toBe('unknown')
  })
})
