// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CalendarData, ScheduledPost } from './api/types'
import { countByDay } from './pages/CalendarView'
import { monthGrid, shiftMonth } from './pages/format'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const post = (id: number, iso: string, preview: string, over: Partial<ScheduledPost> = {}): ScheduledPost => ({
  id, channel_id: '-1001', channel_title: 'Kanal A', post_type: 'text', preview, has_media: false,
  scheduled_time: iso, number: id, recurrence: 'none', status: 'pending', ...over,
})

function mockApi(calendar: (url: string) => Response) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/scheduled-posts/calendar')) return calendar(url)
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
async function openCalendar() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Reja/))
  fireEvent.click(await screen.findByRole('button', { name: 'Kalendar' }))
}
const calls = (f: ReturnType<typeof mockApi>) => f.mock.calls.map((c) => String(c[0])).filter((u) => u.includes('/calendar'))

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('monthGrid / shiftMonth', () => {
  it('42 katak, dushanbadan boshlanadi, oy 1-sanasi qamrab olinadi', () => {
    for (const [y, m] of [[2026, 9], [2026, 1], [2027, 0], [2026, 2]] as const) {
      const g = monthGrid(y, m)
      expect(g.days).toHaveLength(42)
      expect(g.start.getDay()).toBe(1)
      expect(g.days.some((d) => d.getFullYear() === y && d.getMonth() === m && d.getDate() === 1)).toBe(true)
      expect(g.days.every((d) => d.getHours() === 0 && d.getMinutes() === 0)).toBe(true) // yozgi vaqt o'tishida ham yarim tun
      expect(g.end.getTime()).toBeGreaterThan(g.days[41]!.getTime())
    }
  })
  it('2026 oktyabr: 1-oktyabr payshanba -> tarmoq 28-sentabr (dushanba) dan boshlanadi', () => {
    const g = monthGrid(2026, 9)
    expect([g.start.getFullYear(), g.start.getMonth(), g.start.getDate()]).toEqual([2026, 8, 28])
  })
  it('shiftMonth: yil o\'tishi', () => {
    expect(shiftMonth(2026, 11, 1)).toEqual({ year: 2027, month: 0 })
    expect(shiftMonth(2026, 0, -1)).toEqual({ year: 2025, month: 11 })
  })
})

describe('countByDay', () => {
  it('mahalliy kun bo\'yicha guruhlaydi, yaroqsiz/bo\'sh sanani e\'tiborsiz qoldiradi', () => {
    const items = [post(1, '2026-10-14T09:00:00Z', 'a'), post(2, '2026-10-14T10:00:00Z', 'b'),
      post(3, 'not-a-date', 'c'), post(4, null as unknown as string, 'd')]
    const m = countByDay(items)
    expect([...m.values()].map((v) => v.length)).toEqual([2])
  })
})

describe('Kalendar ko\'rinishi', () => {
  it('so\'rov zonali ISO oralig\'i bilan boradi; kunda soni ko\'rinadi; kunni tanlasa postlar chiqadi', async () => {
    const now = new Date()
    const when = new Date(now.getFullYear(), now.getMonth(), 15, 12, 0)
    const data: CalendarData = { items: [post(7, when.toISOString(), 'Kalendar posti'), post(8, when.toISOString(), 'Ikkinchi')], truncated: false }
    const f = mockApi(() => jsonResponse(data))
    await openCalendar()
    const cell = await screen.findByTestId(`cal-${when.getFullYear()}-${when.getMonth() + 1}-15`)
    expect(within(cell).getByText('2')).toBeTruthy()
    const url = new URL(calls(f)[0]!, 'http://x')
    const from = new Date(url.searchParams.get('from')!)
    const to = new Date(url.searchParams.get('to')!)
    expect(from.getDay()).toBe(1)
    expect(to.getTime() - from.getTime()).toBeGreaterThanOrEqual(42 * 23 * 3600 * 1000)
    fireEvent.click(cell)
    expect(await screen.findByText('Kalendar posti')).toBeTruthy()
    expect(screen.getByText('Ikkinchi')).toBeTruthy()
    // tahrirlash/bekor qilish tugmalari shu yerda ham bor (kutilayotgan post)
    expect(screen.getAllByRole('button', { name: 'Bekor qilish' }).length).toBeGreaterThan(0)
  })

  it('post yo\'q kun: halol bo\'sh matn; son belgisi yo\'q', async () => {
    mockApi(() => jsonResponse({ items: [], truncated: false }))
    await openCalendar()
    const d = new Date()
    const cell = await screen.findByTestId(`cal-${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`)
    expect(cell.querySelector('.cal-count')).toBeNull()
    expect(await screen.findByText('Bu kunga post rejalanmagan.')).toBeTruthy()
  })

  it('server kesgan bo\'lsa (truncated) ogohlantirish ko\'rsatiladi', async () => {
    mockApi(() => jsonResponse({ items: [], truncated: true }))
    await openCalendar()
    expect(await screen.findByText(/faqat dastlabki 500/)).toBeTruthy()
  })

  it('keyingi oy: yangi oraliq so\'raladi', async () => {
    const f = mockApi(() => jsonResponse({ items: [], truncated: false }))
    await openCalendar()
    await screen.findByText('Bu kunga post rejalanmagan.')
    fireEvent.click(screen.getByRole('button', { name: 'Keyingi oy' }))
    await waitFor(() => expect(calls(f).length).toBe(2))
    expect(calls(f)[0]).not.toBe(calls(f)[1])
  })

  it('xato: ErrorState va qayta urinish; soxta bo\'sh kalendar ko\'rsatilmaydi', async () => {
    let n = 0
    mockApi(() => (n++ === 0 ? jsonResponse(errorBody('internal_error'), 500) : jsonResponse({ items: [], truncated: false })))
    await openCalendar()
    const retry = await screen.findByRole('button', { name: /Qayta urinish/i })
    expect(screen.queryByRole('grid')).toBeNull()
    fireEvent.click(retry)
    expect(await screen.findByRole('grid')).toBeTruthy()
  })

  it('noto\'g\'ri javob shakli (items yo\'q) xato sifatida ko\'rsatiladi, qulamaydi', async () => {
    mockApi(() => jsonResponse({ truncated: false }))
    await openCalendar()
    await waitFor(() => expect(screen.queryByRole('grid')).toBeNull())
    expect(await screen.findByRole('button', { name: /Qayta urinish/i })).toBeTruthy()
  })
})
