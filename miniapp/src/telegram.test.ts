// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getInitData, haptic, isInTelegram, openBot } from './telegram'

type W = { Telegram?: unknown }
const setTg = (v: unknown) => { (window as unknown as W).Telegram = v }

afterEach(() => { delete (window as unknown as W).Telegram; vi.restoreAllMocks() })

describe('openBot (navigatsiya kontrakti)', () => {
  it('bo\'limsiz: faqat https://t.me/<username>; bo\'lim faqat ruxsat ro\'yxatidan (?start=go_<bo\'lim>)', () => {
    const open = vi.fn()
    setTg({ WebApp: { initData: 'x', openTelegramLink: open } })
    expect(openBot('PostAssistrobot')).toBe(true)
    expect(open).toHaveBeenCalledWith('https://t.me/PostAssistrobot')
    expect(String(open.mock.calls[0][0])).not.toMatch(/[?=&]/)
  })

  it.each(['', 'a', 'ab_c', 'bad name', 'x?start=newpost', '../evil', 'https://evil.example', '1bot', 'a'.repeat(33), null, undefined])(
    'yaroqsiz username %j rad etiladi', (name) => {
      const open = vi.fn()
      const winOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
      setTg({ WebApp: { initData: 'x', openTelegramLink: open } })
      expect(openBot(name as string | null | undefined)).toBe(false)
      expect(open).not.toHaveBeenCalled()
      expect(winOpen).not.toHaveBeenCalled()
    })

  it('openTelegramLink yo\'q bo\'lsa window.open (noopener) zaxirasi', () => {
    const winOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    setTg({ WebApp: { initData: 'x' } })
    expect(openBot('PostAssistrobot')).toBe(true)
    expect(winOpen).toHaveBeenCalledWith('https://t.me/PostAssistrobot', '_blank', 'noopener,noreferrer')
  })

  it('openTelegramLink xato bersa ham qulamaydi (zaxira)', () => {
    const winOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    setTg({ WebApp: { initData: 'x', openTelegramLink: () => { throw new Error('boom') } } })
    expect(openBot('PostAssistrobot')).toBe(true)
    expect(winOpen).toHaveBeenCalled()
  })
})

describe('Telegram SDK xavfsizligi', () => {
  it('SDK yo\'q: initData bo\'sh, Telegramda emas', () => {
    expect(getInitData()).toBe('')
    expect(isInTelegram()).toBe(false)
  })
  it('SDK getter xato bersa ham ilova qulamaydi', () => {
    Object.defineProperty(window, 'Telegram', { configurable: true, get() { throw new Error('sdk') } })
    expect(getInitData()).toBe('')
    delete (window as unknown as W).Telegram
  })
  it('initData satr bo\'lmasa e\'tiborsiz', () => {
    setTg({ WebApp: { initData: 123 } })
    expect(getInitData()).toBe('')
  })
})

describe('openBot bo\'limlari (deep-link ruxsat ro\'yxati)', () => {
  it('plans/settings/help -> ?start=go_<bo\'lim>; noma\'lum bo\'lim e\'tiborsiz (oddiy havola)', () => {
    const open = vi.fn()
    ;(window as unknown as { Telegram: unknown }).Telegram = { WebApp: { openTelegramLink: open } }
    expect(openBot('PostAssistrobot', 'plans')).toBe(true)
    expect(open).toHaveBeenLastCalledWith('https://t.me/PostAssistrobot?start=go_plans')
    expect(openBot('PostAssistrobot', 'settings')).toBe(true)
    expect(open).toHaveBeenLastCalledWith('https://t.me/PostAssistrobot?start=go_settings')
    expect(openBot('PostAssistrobot', 'admin' as never)).toBe(true)
    expect(open).toHaveBeenLastCalledWith('https://t.me/PostAssistrobot')
    expect(openBot('bad name', 'plans')).toBe(false)
  })
  it('channels/invite/cleaner -> botdagi aynan shu ekran (go_channels, go_invite, go_cleaner)', () => {
    const open = vi.fn()
    ;(window as unknown as { Telegram: unknown }).Telegram = { WebApp: { openTelegramLink: open } }
    for (const s of ['channels', 'invite', 'cleaner'] as const) {
      expect(openBot('PostAssistrobot', s)).toBe(true)
      expect(open).toHaveBeenLastCalledWith(`https://t.me/PostAssistrobot?start=go_${s}`)
    }
  })
})

describe('haptic', () => {
  it('SDK bo\'lsa tebranadi, bo\'lmasa yoki xato bersa jim', () => {
    const impact = vi.fn()
    const sel = vi.fn()
    const note = vi.fn()
    ;(window as unknown as { Telegram: unknown }).Telegram = { WebApp: { HapticFeedback: { impactOccurred: impact, selectionChanged: sel, notificationOccurred: note } } }
    haptic()
    haptic('select')
    haptic('success')
    expect(impact).toHaveBeenCalledWith('light')
    expect(sel).toHaveBeenCalled()
    expect(note).toHaveBeenCalledWith('success')
    ;(window as unknown as { Telegram: unknown }).Telegram = { WebApp: { HapticFeedback: { impactOccurred: () => { throw new Error('x') } } } }
    expect(() => haptic()).not.toThrow()
    ;(window as unknown as { Telegram: unknown }).Telegram = undefined
    expect(() => haptic('error')).not.toThrow()
  })
})
