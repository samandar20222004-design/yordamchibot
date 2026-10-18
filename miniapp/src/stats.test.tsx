// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { ChannelAnalytics } from './api/types'
import { formatDelta } from './pages/StatsPage'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const FULL: ChannelAnalytics = {
  channel: { id: '-1001', title: 'Kanal A' },
  members: {
    current: 1150, as_of: '2026-10-14', delta_7d: 50, delta_30d: null, points: 9, span_days: 12,
    confidence: 'medium', stale: false, source: 'bot_api_getChatMemberCount', collected_at: '2026-10-14T03:00:00Z',
    history: [{ date: '2026-10-14', member_count: 1150 }, { date: '2026-10-07', member_count: 1100 }],
  },
  posts: { sent_7d: 3, sent_30d: 8, sent_all: 20, pending: 2, failed: 1, unknown: 0 },
  views: { available: false, with_views: 0, avg: null, max: null, collected_at: null, sources: [] },
}
const EMPTY: ChannelAnalytics = {
  ...FULL,
  members: { ...FULL.members, current: null, as_of: null, delta_7d: null, points: 0, span_days: 0, confidence: 'none', source: null, history: [] },
}

function mockApi(analytics: () => Response, channels = [{ id: '-1001', title: 'Kanal A' }]) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/analytics')) return analytics()
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: channels, total: channels.length })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
/** Profil -> «Kanallarim» qatori (kanallar alohida ekranda). */
const openChannels = () => fireEvent.click(screen.getAllByRole('button', { name: /^Kanallarim/ }).find((b) => b.classList.contains('set-row'))!)

/** Men -> Kanallarim -> kanal yonidagi «Tahlil» tugmasi (index = ro'yxatdagi tartib). */
async function openStats(index = 0) {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Men/))
  openChannels()
  const buttons = await screen.findAllByRole('button', { name: 'Tahlil' })
  fireEvent.click(buttons[index]!)
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Kanal tahlili sahifasi', () => {
  it('formatDelta: null -> "ma\'lumot yo\'q" matni (0 emas), 0 -> "0", ishora bilan', () => {
    expect(formatDelta(null, 'yo\'q')).toBe('yo\'q')
    expect(formatDelta(0, 'yo\'q')).toBe('0')
    expect(formatDelta(50, 'yo\'q')).toBe('+50')
    expect(formatDelta(-120, 'yo\'q')).toBe('-120')
  })

  it('haqiqiy ma\'lumot: obunachilar, 7 kunlik o\'sish, 30 kunlik "yetarli emas", ishonch va manba', async () => {
    const f = mockApi(() => jsonResponse(FULL))
    await openStats()
    expect((await screen.findByTestId('members-current')).textContent).toMatch(/1[,.\s ]?150/)
    expect(screen.getByTestId('delta-7').textContent).toBe('+50')
    expect(screen.getByTestId('delta-30').textContent).toBe('ma\'lumot yetarli emas')
    expect(screen.getByText(/Ishonch: o'rtacha/)).toBeTruthy()
    expect(screen.getByText(/Manba: Telegram/)).toBeTruthy()
    expect(f.mock.calls.some((c) => String(c[0]).includes('/channels/-1001/analytics'))).toBe(true)
  })

  it('ko\'rishlar mavjud emas: halol izoh, raqam to\'qilmaydi', async () => {
    mockApi(() => jsonResponse(FULL))
    await openStats()
    expect((await screen.findByTestId('views-unavailable')).textContent).toMatch(/Telegram bot uchun post ko'rishlarini bermaydi/)
    expect(screen.queryByText(/O'rtacha \(/)).toBeNull()
  })

  it('snapshot yo\'q: "yig\'ilmoqda" xabari, soxta 0 ko\'rsatilmaydi', async () => {
    mockApi(() => jsonResponse(EMPTY))
    await openStats()
    expect(await screen.findByText(/Kunlik hisob yig'ilmoqda/)).toBeTruthy()
    expect(screen.queryByTestId('members-current')).toBeNull()
  })

  it('server xatosi (404) tushunarli xabar bilan ko\'rsatiladi, ilova qulamaydi', async () => {
    mockApi(() => jsonResponse(errorBody('not_found'), 404))
    await openStats()
    expect(await screen.findByRole('alert')).toBeTruthy()
  })

  it('«Tahlil» pastki tabda YO\'Q (tablar bir qatorda qoladi) va kanal yo\'q bo\'lsa tugma ham yo\'q', async () => {
    mockApi(() => jsonResponse(FULL), [])
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(within(screen.getByRole('navigation')).queryByRole('button', { name: /Tahlil/ })).toBeNull()
    expect(within(screen.getByRole('navigation')).getAllByRole('button')).toHaveLength(5)
    fireEvent.click(nav(/^Men/))
    openChannels()
    expect(await screen.findByText('Ulangan kanal yo\'q.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Tahlil' })).toBeNull()
  })

  it('bir nechta kanal: har kanal yonida tugma; tanlangan kanal so\'raladi; «Orqaga» profilga qaytaradi', async () => {
    const f = mockApi(() => jsonResponse(FULL), [{ id: '-1001', title: 'Kanal A' }, { id: '-1002', title: 'Kanal B' }])
    await openStats(1)
    await screen.findByTestId('members-current')
    expect(f.mock.calls.some((c) => String(c[0]).includes('/channels/-1002/analytics'))).toBe(true)
    expect(f.mock.calls.some((c) => String(c[0]).includes('/channels/-1001/analytics'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: /Orqaga/ }))
    expect(await screen.findAllByRole('button', { name: 'Tahlil' })).toHaveLength(2)
  })

  it('Kanallarim: har kanalda rejadagi soni va obunachilar; snapshot yo\'q kanalda obunachi qatori YO\'Q (0 emas)', async () => {
    mockApi(() => jsonResponse(FULL), [
      { id: '-1001', title: 'Kanal A', pending_posts: 3, members: 12345, members_as_of: '2026-10-14' },
      { id: '-1002', title: 'Kanal B', pending_posts: 0, members: null, members_as_of: null },
    ] as never)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Men/))
    openChannels()
    expect(await screen.findByText(/Rejada: 3/)).toBeTruthy()
    expect(screen.getByText(/Obunachi: 12[,.\s\u00a0\u202f]?345/)).toBeTruthy()
    expect(screen.getByText(/Rejada: 0/)).toBeTruthy()
    expect(screen.getAllByText(/Obunachi:/)).toHaveLength(1)
  })
})
