import { describe, expect, it } from 'vitest'
import { messages } from './messages'
import { formatUz, normalizeLang, translate } from './index'

const keys = Object.keys(messages.uz)
const placeholders = (s: string) => (s.match(/\{[a-z]+\}/g) ?? []).sort().join(',')

describe('tarjimalar', () => {
  it('uch tilda bir xil kalitlar', () => {
    expect(Object.keys(messages.ru).sort()).toEqual([...keys].sort())
    expect(Object.keys(messages.en).sort()).toEqual([...keys].sort())
  })
  it('bo\'sh matn yo\'q', () => {
    for (const lang of ['uz', 'ru', 'en'] as const) {
      for (const k of keys) expect(messages[lang][k as keyof typeof messages.uz].trim().length).toBeGreaterThan(0)
    }
  })
  it('o\'zgaruvchilar (placeholder) uch tilda bir xil', () => {
    for (const k of keys) {
      const key = k as keyof typeof messages.uz
      expect(placeholders(messages.ru[key])).toBe(placeholders(messages.uz[key]))
      expect(placeholders(messages.en[key])).toBe(placeholders(messages.uz[key]))
    }
  })
  it('har bir server xato kodi uchun tarjima bor', () => {
    for (const code of ['unauthorized', 'auth_expired', 'not_registered',
      'rate_limited', 'service_unavailable', 'https_required', 'internal_error', 'auth_unavailable',
      'bad_request', 'not_found', 'method_not_allowed', 'caption_too_long', 'draft_not_found', 'media_unavailable',
      'market_private', 'market_not_admin', 'market_limit', 'market_blocked', 'inquiry_limit', 'inquiry_blocked', 'inquiry_own', 'inquiry_exists', 'thread_closed', 'thread_full']) {
      expect(keys).toContain(`err.${code}`)
    }
  })
  it('bot yorliqlari (PRO bo\'limi) botdagi matn bilan bir xil', () => {
    expect(messages.uz['me.tierBuy']).toContain('💎 PRO va Tariflar')
    expect(messages.ru['me.tierBuy']).toContain('💎 PRO и тарифы')
    expect(messages.en['me.tierBuy']).toContain('💎 PRO & Plans')
  })
  it('translate o\'zgaruvchini almashtiradi', () => {
    expect(translate('en', 'home.hello', { name: 'Bob' })).toBe('Hello, Bob!')
    expect(translate('ru', 'post.queue', { used: 1, limit: 5 })).toBe('Постов в очереди: 1 / 5')
  })
  it('normalizeLang', () => {
    expect(normalizeLang('ru-RU')).toBe('ru')
    expect(normalizeLang('EN')).toBe('en')
    expect(normalizeLang('de')).toBe('uz')
    expect(normalizeLang(undefined)).toBe('uz')
  })
  it('o\'zbekcha sana/vaqt (brauzer Intl\'iga bog\'liq emas)', () => {
    const d = new Date(2026, 9, 13, 8, 5)
    expect(formatUz(d, 'dateTime')).toBe('13-okt, 08:05')
    expect(formatUz(d, 'date')).toBe('13-oktabr, 2026')
    expect(formatUz(d, 'time')).toBe('08:05')
  })
})
