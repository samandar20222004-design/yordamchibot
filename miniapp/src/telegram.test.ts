// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getInitData, isInTelegram, openBot } from './telegram'

type W = { Telegram?: unknown }
const setTg = (v: unknown) => { (window as unknown as W).Telegram = v }

afterEach(() => { delete (window as unknown as W).Telegram; vi.restoreAllMocks() })

describe('openBot (navigatsiya kontrakti)', () => {
  it('faqat https://t.me/<username> — start/payload parametrisiz', () => {
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
