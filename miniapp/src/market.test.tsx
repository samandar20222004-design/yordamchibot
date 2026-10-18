// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { parseMarketListing, ShapeError } from './api/validate'
import { formatCount, formatMoney, parsePriceInput } from './pages/marketUtils'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

const LISTING = {
  id: 7, title: 'Texno Yangiliklar', username: 'texnoyangi', category: 'tech', price: 60000, description: 'Har kuni texnologiya yangiliklari',
  members: 12400, avg_views: 3100, er_percent: 25, growth_30d: 320, posts_30d: 22, stats_updated_at: '2026-10-17T08:00:00Z',
  badges: ['growing', 'engaged'],
}
const UNKNOWN = { ...LISTING, id: 8, title: 'Yangi kanal', username: 'yangikanal', avg_views: null, er_percent: null, growth_30d: null, price: null, badges: [] }
const MINE_LISTED = { ...LISTING, status: 'active', channel_id: '-1001', view_count: 12, inquiry_count: 2 }

type Call = { url: string; method: string; body: unknown }

function setup(extra: (url: string, method: string, body: unknown) => Response | undefined = () => undefined) {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } }, ready: vi.fn(), expand: vi.fn(), close: vi.fn(),
      openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, method, body })
    const custom = extra(url, method, body)
    if (custom) return custom
    if (url.includes('/market/summary')) {
      return jsonResponse({ listings: 3, inquiries: 5, categories: ['tech', 'news'], max_listings: 5, price_min: 1000, price_max: 1000000000, description_max: 400, message_min: 10, message_max: 1000 })
    }
    if (url.includes('/market/listings?')) return jsonResponse({ items: [LISTING, UNKNOWN], total: 2, page: 0, pages: 1, page_size: 5 })
    if (url.match(/\/market\/listings\/7$/)) return jsonResponse({ listing: LISTING, is_owner: false })
    if (url.match(/\/market\/listings\/8$/)) return jsonResponse({ listing: UNKNOWN, is_owner: false })
    if (url.includes('/market/mine')) return jsonResponse({ items: [
      { channel_id: '-1001', title: 'Kanal A', listing: MINE_LISTED }, { channel_id: '-1002', title: 'Kanal B', listing: null }], max_listings: 5 })
    if (url.endsWith('/market/unread')) return jsonResponse({ unread: 3 })
    if (url.includes('/market/threads/3')) return jsonResponse({ thread: { id: 3, title: 'Texno Yangiliklar', username: 'texnoyangi', role: 'advertiser', status: 'open', listing_id: 7 },
      peer: { new_account: true, reports: 2 },
      messages: [{ mine: true, text: 'Salom, reklama kerak', at: '2026-10-17T09:00:00Z', flags: [] },
        { mine: false, text: 'Oldindan to\'lov qiling, shoshiling', at: '2026-10-17T09:05:00Z', flags: ['prepay', 'pressure'] }] })
    if (url.includes('/market/threads')) return jsonResponse({ items: [{ id: 3, title: 'Texno Yangiliklar', role: 'advertiser', unread: 2, updated_at: '2026-10-17T09:05:00Z' }] })
    if (url.includes('/me')) return jsonResponse(ME)
    if (url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
    if (url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  }))
  window.history.replaceState({}, '', '/app/?tab=market')
  return calls
}

beforeEach(() => { vi.useRealTimers() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram; window.history.replaceState({}, '', '/app/') })

describe('Reklama birjasi (Mini App)', () => {
  it('?tab=market: Birja ochiladi, katalog va umumiy hisob ko\'rinadi', async () => {
    setup()
    render(<App />)
    expect(await screen.findByText('Texno Yangiliklar')).toBeTruthy()
    expect(screen.getByText(/3 ta kanal · 5 ta so'rov/)).toBeTruthy()
    expect(screen.getByRole('navigation').querySelectorAll('button')).toHaveLength(5)
    expect(screen.getAllByText('👥 12.4k')).toHaveLength(2)
    expect(screen.getByText('💲 60 000 so\'m')).toBeTruthy()
    expect(screen.getByText('💲 kelishiladi')).toBeTruthy()
  })

  it('kartada noma\'lum ko\'rsatkich halol: «ma\'lumot yetarli emas», soxta 0 yo\'q', async () => {
    setup()
    render(<App />)
    fireEvent.click((await screen.findByText('Yangi kanal')).closest('button')!)
    expect(await screen.findByText("ma'lumot yetarli emas")).toBeTruthy()
    expect(screen.getByText('✅ Kanal egaligi bot orqali tekshirilgan', { exact: false })).toBeTruthy()
    expect(screen.queryByText('0%')).toBeNull()
  })

  it('so\'rov yuborish: qisqa matn bloklanadi, yetarli matn POST qilinadi', async () => {
    const calls = setup((url, method) => (method === 'POST' && url.includes('/inquiries') ? jsonResponse({ inquiry_id: 9, delivered: true }, 201) : undefined))
    render(<App />)
    fireEvent.click((await screen.findByText('Texno Yangiliklar')).closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: "Reklama so'rovi" }))
    const dialog = await screen.findByRole('dialog')
    const send = within(dialog).getByRole('button', { name: 'Yuborish' }) as HTMLButtonElement
    const box = within(dialog).getByRole('textbox')
    fireEvent.change(box, { target: { value: 'qisqa' } })
    expect(send.disabled).toBe(true)
    fireEvent.change(box, { target: { value: 'Salom! 1 ta post reklama kerak, byudjet 100 000' } })
    expect(send.disabled).toBe(false)
    fireEvent.click(send)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/market/listings/7/inquiries'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/inquiries'))!.body).toEqual({ text: 'Salom! 1 ta post reklama kerak, byudjet 100 000' })
    expect(await screen.findByText("So'rov yuborildi. Egasi javob bersa, botga xabar keladi.")).toBeTruthy()
  })

  it('so\'rov xatosi (kunlik limit) forma ichida tarjima qilingan xabar bilan ko\'rinadi', async () => {
    setup((url, method) => (method === 'POST' && url.includes('/inquiries') ? jsonResponse(errorBody('inquiry_limit'), 429) : undefined))
    render(<App />)
    fireEvent.click((await screen.findByText('Texno Yangiliklar')).closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: "Reklama so'rovi" }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Salom! 1 ta post reklama kerak' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Yuborish' }))
    expect(await within(dialog).findByText(/Kuniga 5 tadan ko'p yangi so'rov/)).toBeTruthy()
  })

  it('«Kanalim»: o\'z kanallari va holati; yangi e\'lon narxi «50k» -> 50000 bilan yuboriladi', async () => {
    const calls = setup((url, method) => (method === 'POST' && url.endsWith('/market/mine') ? jsonResponse({ listing: { ...MINE_LISTED, id: 11, channel_id: '-1002', price: 50000 } }, 201) : undefined))
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    fireEvent.click(screen.getByRole('button', { name: 'Kanalim' }))
    expect(await screen.findByText(/Katalogda · 12 ko'rish · 2 so'rov/)).toBeTruthy()
    fireEvent.click(screen.getByText("E'lon qilinmagan").closest('button')!)
    const price = await screen.findByLabelText("1 post narxi (so'm)")
    fireEvent.change(price, { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: "Birjaga chiqarish" }))
    expect(await screen.findByText(/Bo'sh qoldirsangiz/)).toBeTruthy()
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/market/mine'))).toBe(false)
    fireEvent.change(price, { target: { value: '50k' } })
    fireEvent.change(screen.getByLabelText('Tavsif'), { target: { value: 'Savdo kanali' } })
    fireEvent.change(screen.getByLabelText('Mavzu'), { target: { value: 'shop' } })
    fireEvent.click(screen.getByRole('button', { name: "Birjaga chiqarish" }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/market/mine'))).toBe(true))
    expect(calls.find((c) => c.method === 'POST' && c.url.endsWith('/market/mine'))!.body)
      .toEqual({ channel_id: '-1002', category: 'shop', price: 50000, description: 'Savdo kanali' })
  })

  it('e\'lonni to\'xtatish PATCH {status: paused} yuboradi', async () => {
    const calls = setup((_url, method) => (method === 'PATCH' ? jsonResponse({ listing: { ...MINE_LISTED, status: 'paused' } }) : undefined))
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    fireEvent.click(screen.getByRole('button', { name: 'Kanalim' }))
    fireEvent.click((await screen.findByText(/Katalogda/)).closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: "To'xtatish" }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.url).toMatch(/\/market\/mine\/7$/)
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ status: 'paused' })
    expect(await screen.findByRole('button', { name: 'Faollashtirish' })).toBeTruthy()
  })

  it('suhbat: xabarlar ko\'rinadi va javob POST qilinadi', async () => {
    const calls = setup((url, method) => (method === 'POST' && url.endsWith('/messages') ? jsonResponse({ sent: true, delivered: true }, 201) : undefined))
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    fireEvent.click(screen.getByRole('button', { name: 'Suhbatlar' }))
    fireEvent.click((await screen.findByText(/Kanal egasi · /)).closest('button')!)
    expect(await screen.findByText('Salom, reklama kerak')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Javob yozing…'), { target: { value: 'Kelishdik, ertaga' } })
    fireEvent.click(screen.getByRole('button', { name: 'Yuborish' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/market/threads/3/messages'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/messages'))!.body).toEqual({ text: 'Kelishdik, ertaga' })
  })
})

describe('Birja xavfsizligi va o\'qilmagan xabarlar (Mini App)', () => {
  it('pastki panelda Birja tabida o\'qilmaganlar nishoni, suhbatlar ro\'yxatida suhbat soni', async () => {
    setup()
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    expect(await screen.findByLabelText('3 ta o\'qilmagan xabar')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Suhbatlar' }))
    expect(await screen.findByLabelText('2 ta o\'qilmagan xabar')).toBeTruthy()
  })

  it('shubhali xabarda ⚠️ ogohlantirish, yangi hisob va shikoyatlar belgisi, xavfsizlik maslahati', async () => {
    setup()
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    fireEvent.click(screen.getByRole('button', { name: 'Suhbatlar' }))
    fireEvent.click((await screen.findByText(/Kanal egasi · /)).closest('button')!)
    expect(await screen.findByText(/Ehtiyot bo'ling/)).toBeTruthy()
    expect(screen.getByText(/oldindan to'lov so'ralmoqda, sizni shoshiltirishmoqda/)).toBeTruthy()
    expect(screen.getByText(/Yangi foydalanuvchi — ehtiyot bo'ling/)).toBeTruthy()
    expect(screen.getByText(/Bu foydalanuvchi haqida 2 ta shikoyat bor/)).toBeTruthy()
    expect(screen.getByText(/oldindan to'lov bermang, kartaga pul tashlamang/)).toBeTruthy()
    // o'z xabarida ogohlantirish yo'q
    expect(screen.getAllByText(/Ehtiyot bo'ling/)).toHaveLength(1)
  })

  it('🚩 Firibgar: tasdiqdan keyin POST /report yuboradi', async () => {
    const calls = setup((url, method) => (method === 'POST' && url.endsWith('/market/threads/3/report') ? jsonResponse({ reported: true, again: false, banned: false }) : undefined))
    render(<App />)
    await screen.findByText('Texno Yangiliklar')
    fireEvent.click(screen.getByRole('button', { name: 'Suhbatlar' }))
    fireEvent.click((await screen.findByText(/Kanal egasi · /)).closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: /Firibgar/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/3 ta turli shikoyatdan keyin/)).toBeTruthy()
    fireEvent.click(within(dialog).getAllByRole('button').find((b) => /Firibgar/.test(b.textContent ?? ''))!)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/market/threads/3/report'))).toBe(true))
  })

  it('?tab=market&thread=3 (botdagi «Mini App\'da» tugmasi) suhbatni to\'g\'ridan-to\'g\'ri ochadi; noto\'g\'ri qiymat e\'tiborsiz', async () => {
    setup()
    window.history.replaceState({}, '', '/app/?tab=market&thread=3')
    render(<App />)
    expect(await screen.findByText('Salom, reklama kerak')).toBeTruthy()
    cleanup()
    window.history.replaceState({}, '', '/app/?tab=market&thread=abc')
    render(<App />)
    expect(await screen.findByText('Reklama birjasi')).toBeTruthy()
    expect(screen.queryByText('Salom, reklama kerak')).toBeNull()
  })

  it('karta raqami xatosi so\'rov oynasida tarjima qilingan xabar bilan ko\'rinadi', async () => {
    setup((url, method) => (method === 'POST' && url.includes('/inquiries') ? jsonResponse(errorBody('message_card'), 422) : undefined))
    render(<App />)
    fireEvent.click((await screen.findByText('Texno Yangiliklar')).closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: "Reklama so'rovi" }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Kartamga 8600 1234 5678 9012 tashlang' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Yuborish' }))
    expect(await within(dialog).findByText(/Xabarda karta raqami bor/)).toBeTruthy()
  })
})

describe('marketUtils va validator', () => {
  it('formatCount / formatMoney', () => {
    expect([formatCount(null), formatCount(950), formatCount(2000), formatCount(12400), formatCount(1250000), formatCount(-45)])
      .toEqual(['—', '950', '2 000', '12.4k', '1.25M', '-45'])
    expect(formatMoney(1500000)).toBe('1 500 000')
  })
  it('parsePriceInput: son, k, ming, mln, bo\'sh=kelishiladi, yaroqsiz', () => {
    const p = (s: string) => parsePriceInput(s, 1000, 1_000_000_000)
    expect([p('50000'), p('50 000'), p('50k'), p('50 ming'), p('1.5 mln'), p('1,5 млн'), p(''), p('abc'), p('500'), p('99999999999')])
      .toEqual([50000, 50000, 50000, 50000, 1_500_000, 1_500_000, null, undefined, undefined, undefined])
  })
  it('parseMarketListing: noto\'g\'ri shakl ShapeError, noma\'lum kategoriya "other"', () => {
    expect(() => parseMarketListing({ id: 'x' })).toThrow(ShapeError)
    expect(parseMarketListing({ ...LISTING, category: 'zzz' }).category).toBe('other')
    expect(parseMarketListing({ ...LISTING, badges: ['growing', 'hack'] }).badges).toEqual(['growing'])
  })
})
