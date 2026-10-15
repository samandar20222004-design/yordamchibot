// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { Meter, initialOf } from './pages/MePage'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

function mockApi(me = ME) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/me')) return jsonResponse(me)
    if (method === 'GET' && url.includes('/channels')) {
      return jsonResponse({ items: [{ id: '-1001', title: 'Juda uzun nomli kanal: Mahsulotlar va xizmatlar yangiliklari', pending_posts: 3, members: 12345, members_as_of: '2026-10-14' }], total: 1 })
    }
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  }))
}

const openMe = async () => {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('initialOf', () => {
  it('birinchi harf, katta; emoji va bo\'sh matn xavfsiz', () => {
    expect(initialOf('alice')).toBe('A')
    expect(initialOf('  Мария')).toBe('М')
    expect(initialOf('😀 Kanal')).toBe('😀')
    expect(initialOf('')).toBe('?')
    expect(initialOf('   ')).toBe('?')
  })
})

describe('Meter', () => {
  it('chiziq foizi va daraja: 2/5 -> 40% ok, 4/5 -> high, 5/5 va oshgan -> 100% full', () => {
    const { container, rerender } = render(<Meter label="AI" used={2} max={5} />)
    const bar = () => container.querySelector('.meter-bar > span') as HTMLElement
    expect(bar().style.width).toBe('40%')
    expect(bar().dataset.level).toBe('ok')
    rerender(<Meter label="AI" used={4} max={5} />)
    expect(bar().dataset.level).toBe('high')
    rerender(<Meter label="AI" used={9} max={5} />)
    expect(bar().style.width).toBe('100%')
    expect(bar().dataset.level).toBe('full')
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('5') // limitdan oshmaydi
  })
  it('cheksiz: "son / ∞", chiziq yo\'q', () => {
    render(<Meter label="Kanallar" used={7} max={999} />)
    expect(screen.getByText('7 / ∞')).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })
})

describe('Profil sahifasi', () => {
  it('bepul: ism va @username, tarif belgisi, 3 ta foydalanish ko\'rsatkichi, PRO afzalliklari va botni ochish', async () => {
    mockApi()
    await openMe()
    expect(await screen.findByText(/@alice/)).toBeTruthy()
    expect(screen.getAllByText('Bepul').length).toBeGreaterThan(0)
    const bars = screen.getAllByRole('progressbar')
    expect(bars).toHaveLength(3)
    expect(screen.getByText('2 / 3')).toBeTruthy()     // kanallar
    expect(screen.getByText('1 / 5')).toBeTruthy()     // AI (bugun)
    expect(screen.getByText('3 / 5')).toBeTruthy()     // navbat
    for (const perk of ['Cheksiz kanallar', 'Cheksiz AI so\'rovlar', 'Cheksiz navbat', 'Postlarda bot belgisi yo\'q']) expect(screen.getByText(perk)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Botni ochish' })).toBeTruthy()
  })

  it('PRO: afzalliklar ro\'yxati va "bepul" belgisi yo\'q, muddat ko\'rsatiladi', async () => {
    mockApi({ ...ME, plan: { type: 'pro', is_pro: true, expires_at: '2026-11-01T00:00:00Z', limits: { max_channels: 999, daily_ai_requests: 999, queued_posts: 999 } } })
    await openMe()
    expect(await screen.findByText('PRO obunangiz faol.')).toBeTruthy()
    expect(screen.queryByText('Cheksiz kanallar')).toBeNull()
    expect(screen.queryByText('Bepul')).toBeNull()
    expect(screen.getByText(/Amal qilish muddati/)).toBeTruthy()
  })

  it('kanal qatori: uzun nom saqlanadi (title atributi/matn), "Tahlil" tugmasi ishlaydi', async () => {
    mockApi()
    await openMe()
    const title = await screen.findByText(/Juda uzun nomli kanal/)
    expect(title.className).toContain('chan-title')
    expect(screen.getByText(/Rejada: 3/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tahlil' }).className).toContain('chan-act') // Button className'ni o'tkazadi
  })

  it('til tugmalari saqlangan (3 ta, joriy tanlangan)', async () => {
    mockApi()
    await openMe()
    const group = await screen.findByRole('group', { name: 'Interfeys tili' })
    const btns = within(group).getAllByRole('button')
    expect(btns).toHaveLength(3)
    expect(btns.filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
  })
})
