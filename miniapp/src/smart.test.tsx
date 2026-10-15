// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined

function mockApi(handler: Handler = () => undefined) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = handler(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
const posts = (f: ReturnType<typeof mockApi>, part: string) =>
  f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === 'POST' && String(c[0]).includes(part))
const body = (c: unknown[]) => JSON.parse(String((c[1] as RequestInit).body))

async function openPost() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Post/))
  const text = await screen.findByLabelText('Post matni', { selector: 'textarea' })
  fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
  fireEvent.change(text, { target: { value: 'Salom dunyo' } })
}

// 2026-10-17 (shanba) 12:00 Toshkent = 07:00 UTC — kelajakda bo'lishi uchun soat 2030 ga qo'yilgan emas: haqiqiy kelajak sanasi olinadi
const FUTURE = new Date(Date.now() + 10 * 24 * 3600 * 1000)
const FUTURE_ISO = new Date(Date.UTC(FUTURE.getUTCFullYear(), FUTURE.getUTCMonth(), FUTURE.getUTCDate(), 7, 0, 0)).toISOString().replace('.000Z', 'Z')

const proposal = (over: Record<string, unknown> = {}) => jsonResponse({
  ok: true, source: 'rules',
  proposal: { scheduled_at: FUTURE_ISO, recurrence: { type: 'interval', day: 2, time: '12:00' } }, ...over })

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Aqlli rejalash', () => {
  it('matn -> «Aniqlash» -> taklif kartasi (manba, takrorlanish, birinchi chiqish) -> «Qo\'llash» maydonlarni to\'ldiradi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/schedule/parse') ? proposal() : undefined)
    await openPost()
    fireEvent.change(screen.getByLabelText('Aqlli rejalash', { selector: 'input' }), { target: { value: 'kunora 12:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    const card = await screen.findByTestId('smart-proposal')
    expect(within(card).getByText('Har 2 kunda 12:00')).toBeTruthy()
    expect(within(card).getByText('Qoida bo\'yicha')).toBeTruthy()
    expect(within(card).getByText(/Birinchi chiqish:/)).toBeTruthy()
    expect(body(posts(f, '/schedule/parse')[0]!)).toMatchObject({ text: 'kunora 12:00' })
    // hech narsa yozilmadi (faqat taklif)
    expect(posts(f, '/posts')).toHaveLength(0)
    fireEvent.click(within(card).getByRole('button', { name: 'Qo\'llash' }))
    await waitFor(() => expect(screen.queryByTestId('smart-proposal')).toBeNull())
    expect((screen.getByLabelText('Takrorlash') as HTMLSelectElement).value).toBe('interval')
    expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('2')
  })

  it('qo\'llangan taklif bilan yuborish: createPost recurrence va scheduled_at bilan boradi', async () => {
    const f = mockApi((url, init) => {
      if (init.method === 'POST' && url.endsWith('/schedule/parse')) return proposal()
      if (init.method === 'POST' && url.endsWith('/posts')) {
        return jsonResponse({ post: { ...PAGE.items[0], id: 77 }, created: true, delivery: 'scheduled' }, 201)
      }
      return undefined
    })
    await openPost()
    fireEvent.change(screen.getByLabelText('Aqlli rejalash', { selector: 'input' }), { target: { value: 'kunora 12:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    fireEvent.click(await within(await screen.findByTestId('smart-proposal')).findByRole('button', { name: 'Qo\'llash' }))
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    await waitFor(() => expect(posts(f, '/posts').filter((c) => String(c[0]).endsWith('/posts'))).toHaveLength(1))
    const sent = body(posts(f, '/posts').find((c) => String(c[0]).endsWith('/posts'))!)
    expect(sent.recurrence).toEqual({ type: 'interval', day: 2, time: '12:00' })
    expect(typeof sent.scheduled_at).toBe('string')
    expect(await screen.findByText(/Takrorlanuvchi post rejalashtirildi/)).toBeTruthy()
  })

  it('aniqlanmadi: tushunarli xabar, taklif yo\'q; bo\'sh matn so\'rov yubormaydi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/schedule/parse') ? jsonResponse({ ok: false, reason: 'no_time' }) : undefined)
    await openPost()
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    expect(await screen.findByText('Avval vaqtni yozing.')).toBeTruthy()
    expect(posts(f, '/schedule/parse')).toHaveLength(0)
    fireEvent.change(screen.getByLabelText('Aqlli rejalash', { selector: 'input' }), { target: { value: 'har kuni' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    expect(await screen.findByText(/Vaqt aniqlanmadi/)).toBeTruthy()
    expect(screen.queryByTestId('smart-proposal')).toBeNull()
  })

  it('AI manbasi belgilanadi; AI kvotasi tugagan bo\'lsa xato ko\'rsatiladi', async () => {
    mockApi((url, init) => init.method === 'POST' && url.endsWith('/schedule/parse') ? proposal({ source: 'ai' }) : undefined)
    await openPost()
    fireEvent.change(screen.getByLabelText('Aqlli rejalash', { selector: 'input' }), { target: { value: 'nonushta payti' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    expect(await screen.findByText('AI aniqladi')).toBeTruthy()
    cleanup()
    vi.unstubAllGlobals()
    mockApi((url, init) => init.method === 'POST' && url.endsWith('/schedule/parse') ? jsonResponse(errorBody('ai_limit_reached', 'r1'), 429) : undefined)
    await openPost()
    fireEvent.change(screen.getByLabelText('Aqlli rejalash', { selector: 'input' }), { target: { value: 'nonushta payti' } })
    fireEvent.click(screen.getByRole('button', { name: 'Aniqlash' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByTestId('smart-proposal')).toBeNull()
  })

  it('misol chiplari matnni to\'ldiradi', async () => {
    mockApi()
    await openPost()
    fireEvent.click(screen.getByRole('button', { name: 'Kunora 18:30' }))
    expect((screen.getByLabelText('Aqlli rejalash', { selector: 'input' }) as HTMLInputElement).value).toBe('Kunora 18:30')
  })
})

describe('Qo\'lda takrorlash', () => {
  it('«Har N kunda»: createPost recurrence bilan; «Takrorlanmaydi» da recurrence yuborilmaydi', async () => {
    const created = () => jsonResponse({ post: { ...PAGE.items[0], id: 78 }, created: true, delivery: 'scheduled' }, 201)
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts') ? created() : undefined)
    await openPost()
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    await waitFor(() => expect(f.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(1))
    expect(body(f.mock.calls.find((c) => c[1]?.method === 'POST')!)).not.toHaveProperty('recurrence')
  })

  it('hafta kunlari: dam olish tanlansa birinchi chiqish shanbaga suriladi va xabar chiqadi; bo\'sh tanlov xato beradi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts')
      ? jsonResponse({ post: { ...PAGE.items[0], id: 79 }, created: true, delivery: 'scheduled' }, 201) : undefined)
    await openPost()
    // payshanba (2030-10-17) vaqti tanlanadi: dam olish kuniga mos emas
    fireEvent.change(screen.getByLabelText('Sana va vaqt'), { target: { value: '2030-10-17T12:00' } })
    fireEvent.change(screen.getByLabelText('Takrorlash'), { target: { value: 'weekdays' } })
    fireEvent.click(screen.getByRole('button', { name: 'Dam olish' }))
    expect(await screen.findByText(/ko'chirildi/)).toBeTruthy()
    const shown = (screen.getByLabelText('Sana va vaqt') as HTMLInputElement).value
    expect(shown.startsWith('2030-10-19')).toBe(true) // shanba
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    await waitFor(() => expect(f.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(1))
    const sent = body(f.mock.calls.find((c) => c[1]?.method === 'POST')!)
    expect(sent.recurrence).toMatchObject({ type: 'weekdays', day: 96 })
  })

  it('hech bir kun tanlanmasa: so\'rov yuborilmaydi', async () => {
    const f = mockApi()
    await openPost()
    fireEvent.change(screen.getByLabelText('Takrorlash'), { target: { value: 'weekdays' } })
    for (const d of ['Sh', 'Ya']) fireEvent.click(screen.getAllByRole('button', { name: d }).find((b) => b.closest('.weekdays'))!)
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText('Kamida bitta kun tanlang.')).toBeTruthy()
    expect(f.mock.calls.filter((c) => c[1]?.method === 'POST')).toHaveLength(0)
  })
})
