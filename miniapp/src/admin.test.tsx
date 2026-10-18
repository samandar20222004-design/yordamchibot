// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { parseAdminAds, parseAdminMarket, ShapeError } from './api/validate'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

const ADS = {
  settings: { reply: { enabled: false, interval: 4 }, channel: { enabled: true, interval: 3 } },
  items: { channel: [{ id: 1, scope: 'channel', text: '<b>Kanal reklamasi</b>', button_text: 'Ochish', button_url: 'https://example.com', is_active: true }], reply: [] },
}
const MARKET = {
  totals: { active: 2, paused: 0, blocked: 1, banned_users: 1, open_inquiries: 4 },
  items: [{ id: 5, title: 'Texno', username: 'texno', owner_id: 99, category: 'tech', status: 'active', members: 1200, view_count: 10, inquiry_count: 2, reports: 2, owner_banned: false }],
}
type Call = { url: string; method: string; body: unknown }

function setup(opts: { admin: boolean; search?: string; deny?: boolean }) {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } }, ready: vi.fn(), expand: vi.fn(), close: vi.fn(),
      openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (url.includes('/admin/') && opts.deny) return jsonResponse(errorBody('admin_only'), 403)
    if (url.includes('/admin/overview')) return jsonResponse({ stats: { users: 120, pro_subscribers: 9, channels: 40, posts_today: 7, pending_posts: 3, stars_revenue: 500, sent: 80, failed: 2, cancelled: 1, sponsors: 2 }, market: MARKET.totals })
    if (url.includes('/admin/ads/settings')) return jsonResponse({ ...ADS, settings: { ...ADS.settings, reply: { enabled: true, interval: 4 } } })
    if (url.includes('/admin/ads')) return jsonResponse(ADS)
    if (url.includes('/admin/sponsors')) return jsonResponse({ items: [{ id: 1, channel_id: '-1001', title: 'Homiy', username: 'homiy', invite_link: '' }] })
    if (url.includes('/admin/market/listings/5/status')) return jsonResponse({ id: 5, status: 'blocked' })
    if (url.includes('/admin/market')) return jsonResponse(MARKET)
    if (url.includes('/market/unread')) return jsonResponse({ unread: 0 })
    if (url.includes('/me')) return jsonResponse(opts.admin ? { ...ME, is_admin: true } : ME)
    if (url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
    if (url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  }))
  window.history.replaceState({}, '', `/app/${opts.search ?? ''}`)
  return calls
}

beforeEach(() => { vi.useRealTimers(); try { localStorage.clear() } catch { /* */ } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram; window.history.replaceState({}, '', '/app/') })

describe('Super admin rejimi (Mini App)', () => {
  it('oddiy foydalanuvchi: Men sahifasida admin qatori yo\'q, ?tab=admin e\'tiborsiz, /admin so\'rovi ketmaydi', async () => {
    const calls = setup({ admin: false, search: '?tab=admin' })
    render(<App />)
    expect(await screen.findByRole('navigation')).toBeTruthy()
    expect(screen.queryByText('Super admin rejimi')).toBeNull()
    expect(calls.some((c) => c.url.includes('/admin/'))).toBe(false)
  })

  it('admin: Men sahifasidagi tugma admin rejimiga o\'tkazadi, «Oddiy» qaytaradi', async () => {
    setup({ admin: true, search: '?tab=me' })
    render(<App />)
    fireEvent.click(await screen.findByText('Super admin rejimi'))
    expect(await screen.findByText('Umumiy ko\'rinish')).toBeTruthy()
    expect(await screen.findByText('120')).toBeTruthy()
    expect(screen.getByRole('navigation', { name: 'Super admin bo\'limlari' }).querySelectorAll('button')).toHaveLength(5)
    fireEvent.click(screen.getByText('Oddiy'))
    expect(await screen.findByText('Super admin rejimi')).toBeTruthy()
  })

  it('?tab=admin: admin to\'g\'ridan-to\'g\'ri admin rejimida ochiladi; reklama sozlamasi PATCH bilan saqlanadi', async () => {
    const calls = setup({ admin: true, search: '?tab=admin' })
    render(<App />)
    expect(await screen.findByText('Umumiy ko\'rinish')).toBeTruthy()
    fireEvent.click(screen.getByText('Reklama', { selector: 'nav span' }))
    expect(await screen.findByText('Kanal reklamasi')).toBeTruthy()
    const switches = await screen.findAllByRole('switch')
    fireEvent.click(switches[2]) // «Bot javoblari orasida» -> yoqilgan
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.url.endsWith('/admin/ads/settings') && JSON.stringify(c.body) === '{"reply_enabled":true}')).toBe(true))
  })

  it('birja nazorati: bloklash tasdiq so\'raydi va POST ketadi', async () => {
    const calls = setup({ admin: true, search: '?tab=admin' })
    render(<App />)
    fireEvent.click(await screen.findByText('Birja', { selector: 'nav span' }))
    expect(await screen.findByText('Texno')).toBeTruthy()
    fireEvent.click(screen.getByText('Bloklash'))
    expect(await screen.findByText(/e'loni katalogdan yashiriladi/)).toBeTruthy()
    expect(calls.some((c) => c.url.includes('/status'))).toBe(false)
    fireEvent.click(screen.getByText('Tasdiqlash'))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/admin/market/listings/5/status') && JSON.stringify(c.body) === '{"status":"blocked"}')).toBe(true))
  })

  it('server admin_only desa — xabar ko\'rsatiladi (UI ruxsat bermaydi, server hal qiladi)', async () => {
    setup({ admin: true, search: '?tab=admin', deny: true })
    render(<App />)
    expect(await screen.findByText('Bu bo\'lim faqat adminlar uchun.')).toBeTruthy()
  })

  it('validatorlar: noto\'g\'ri shakl rad etiladi', () => {
    expect(() => parseAdminAds({ settings: {}, items: {} })).toThrow(ShapeError)
    expect(parseAdminMarket(MARKET).items[0].reports).toBe(2)
    expect(() => parseAdminMarket({ totals: {}, items: [{ id: 'x' }] })).toThrow(ShapeError)
  })
})
