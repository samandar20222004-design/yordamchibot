// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const POST_ROW = { ...PAGE.items[0], text: 'To\'liq matn: birinchi post' }

function mockApi(handler: Handler = () => undefined) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = handler(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }, { id: '-1002', title: 'Kanal B' }], total: 2 })
    if (method === 'GET' && url.includes('/posts/')) return jsonResponse({ post: POST_ROW })
    if (method === 'GET' && url.includes('/scheduled-posts')) {
      return jsonResponse(url.includes('status=history')
        ? { ...PAGE, items: [{ ...PAGE.items[0], id: 9, status: 'cancelled', preview: 'Eski post' }], total: 1 } : PAGE)
    }
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const calls = (f: ReturnType<typeof mockApi>, method: string, part: string) =>
  f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === method && String(c[0]).includes(part))

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
const body = (c: unknown[]) => JSON.parse(String((c[1] as RequestInit).body))

async function openPost() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Post/))
  return screen.findByLabelText('Post matni', { selector: 'textarea' })
}

const created = (over: Record<string, unknown> = {}) => jsonResponse({
  post: { ...PAGE.items[0], id: 77 }, created: true, delivery: 'scheduled', ...over }, 201)

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Post yaratish', () => {
  it('forma kanallar bilan chiqadi, kanal tanlanmaguncha yuborilmaydi', async () => {
    const f = mockApi()
    const text = await openPost()
    fireEvent.change(text, { target: { value: 'Salom' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect((await screen.findAllByText('Kanalni tanlang.')).length).toBeGreaterThan(0)
    expect(calls(f, 'POST', '/posts')).toHaveLength(0)
  })

  it('kanal yo\'q: forma o\'rniga tushunarli holat va botga yo\'naltirish', async () => {
    mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.includes('/channels')
      ? jsonResponse({ items: [], total: 0 }) : undefined)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Post/))
    expect(await screen.findByText('Avval kanal ulang')).toBeTruthy()
    expect(document.querySelector('textarea')).toBeNull()
  })

  it('rejalashtirish: to\'g\'ri JSON, sarlavhalar, muvaffaqiyat xabari va Reja bo\'limiga o\'tish', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts') ? created() : undefined)
    const text = await openPost()
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1002' } })
    fireEvent.change(text, { target: { value: '  Yangi post <b>x</b>  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText('Post rejalashtirildi. U «Reja» bo\'limida.')).toBeTruthy()
    const [call] = calls(f, 'POST', '/posts')
    const sent = body(call)
    expect(sent.channel_id).toBe('-1002')
    expect(sent.text).toBe('Yangi post <b>x</b>')
    expect(sent.scheduled_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    expect(Object.keys(sent).sort()).toEqual(['channel_id', 'scheduled_at', 'text']) // user_id YO'Q
    const headers = (call[1] as RequestInit).headers as Record<string, string>
    expect(headers.Authorization).toBe('tma auth_date=1&hash=a')
    expect(headers['Content-Type']).toBe('application/json')
    expect(await screen.findByRole('heading', { name: 'Reja' })).toBeTruthy()
  })

  it('takroriy bosish: faqat BITTA so\'rov yuboriladi', async () => {
    let resolve: (r: Response) => void = () => {}
    const pending = new Promise<Response>((r) => { resolve = r })
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts') ? pending : undefined)
    const text = await openPost()
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.change(text, { target: { value: 'Bir marta' } })
    const form = text.closest('form') as HTMLFormElement
    fireEvent.submit(form)
    fireEvent.submit(form)
    fireEvent.submit(form)
    await waitFor(() => expect(calls(f, 'POST', '/posts')).toHaveLength(1))
    expect((screen.getByRole('button', { name: 'Saqlanmoqda…' }) as HTMLButtonElement).disabled).toBe(true)
    resolve(created())
    await screen.findByText('Post rejalashtirildi. U «Reja» bo\'limida.')
    expect(calls(f, 'POST', '/posts')).toHaveLength(1)
  })

  it('bo\'sh matn va o\'tmish vaqt: so\'rov yuborilmaydi', async () => {
    const f = mockApi()
    const text = await openPost()
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Matnni kiriting/)).toBeTruthy()
    fireEvent.change(text, { target: { value: 'Matn' } })
    fireEvent.change(screen.getByLabelText('Sana va vaqt'), { target: { value: '2020-01-01T10:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Kelajakdagi vaqtni tanlang/)).toBeTruthy()
    expect(calls(f, 'POST', '/posts')).toHaveLength(0)
  })

  it('server xatosi (navbat limiti): xabar ko\'rsatiladi, matn saqlanadi, avtomatik qayta urinish yo\'q', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts')
      ? jsonResponse(errorBody('queue_limit_reached', 'rq1'), 403) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.change(text, { target: { value: 'Saqlanib qolsin' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    const alert = await screen.findByText(/Navbat limiti to'ldi/)
    expect(alert.textContent).toContain('rq1')
    expect(text.value).toBe('Saqlanib qolsin')
    expect(calls(f, 'POST', '/posts')).toHaveLength(1)
  })

  it('tarmoq xatosi: qayta URINILMAYDI (bitta POST), ro\'yxat tekshirish uchun yangilanadi', async () => {
    let n = 0
    const f = mockApi((url, init) => {
      if (init.method === 'POST' && url.endsWith('/posts')) { n += 1; throw new TypeError('network') }
      return undefined
    })
    const text = await openPost()
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.change(text, { target: { value: 'Matn' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Internetga ulanib bo'lmadi/)).toBeTruthy()
    await waitFor(() => expect(calls(f, 'GET', '/scheduled-posts').length).toBeGreaterThan(0))
    expect(n).toBe(1)
  })

  it('«Hozir yuborish»: tasdiqlash oynasi; bekor qilinsa so\'rov yo\'q, tasdiqlansa send_now', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/posts') ? created({ delivery: 'immediate' }) : undefined)
    const text = await openPost()
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.change(text, { target: { value: 'Hozir' } })
    fireEvent.click(screen.getByRole('button', { name: 'Hozir yuborish' }))
    fireEvent.click(screen.getByRole('button', { name: 'Postni yuborish' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Kanal A/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Orqaga' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls(f, 'POST', '/posts')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Postni yuborish' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Ha, yuborish' }))
    await screen.findByText('Post yuborish navbatiga qo\'yildi.')
    const sent = body(calls(f, 'POST', '/posts')[0])
    expect(sent).toEqual({ channel_id: '-1001', text: 'Hozir', send_now: true })
  })
})

describe('AI yordamchi', () => {
  it('g\'oyadan matn yaratadi va matn maydoniga qo\'yadi (tahrirlash mumkin)', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/ai/generate')
      ? jsonResponse({ text: 'AI yozgan post', style: 'sales' }) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.change(screen.getByLabelText('G\'oya yoki qisqa matn'), { target: { value: 'yangi mahsulot' } })
    fireEvent.change(screen.getByLabelText('Uslub'), { target: { value: 'sales' } })
    fireEvent.click(screen.getByRole('button', { name: 'AI bilan yozish' }))
    await waitFor(() => expect(text.value).toBe('AI yozgan post'))
    expect(body(calls(f, 'POST', '/ai/generate')[0])).toEqual({ text: 'yangi mahsulot', style: 'sales' })
    fireEvent.change(text, { target: { value: 'AI yozgan post (tahrirlandi)' } })
    expect(text.value).toContain('tahrirlandi')
  })

  it('limit tugagan: tushunarli xabar, matn o\'zgarmaydi; g\'oya bo\'sh bo\'lsa so\'rov yo\'q', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/ai/generate')
      ? jsonResponse(errorBody('ai_limit_reached'), 403) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.change(text, { target: { value: 'Mening matnim' } })
    fireEvent.click(screen.getByRole('button', { name: 'AI bilan yozish' }))
    expect(await screen.findByText(/G'oyani kiriting/)).toBeTruthy()
    expect(calls(f, 'POST', '/ai/generate')).toHaveLength(0)
    fireEvent.change(screen.getByLabelText('G\'oya yoki qisqa matn'), { target: { value: 'g\'oya' } })
    fireEvent.click(screen.getByRole('button', { name: 'AI bilan yozish' }))
    expect(await screen.findByText(/kunlik limit yoki kredit tugadi/)).toBeTruthy()
    expect(text.value).toBe('Mening matnim')
  })
})

describe('Reja: tahrirlash, bekor qilish, tarix', () => {
  async function openSchedule() {
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Reja/))
    await screen.findByText('Birinchi post matni')
  }

  it('bekor qilish: tasdiqlash so\'raladi, tasdiqlansa DELETE va ro\'yxat yangilanadi', async () => {
    const f = mockApi((_url, init) => init.method === 'DELETE' ? jsonResponse({ id: 1, status: 'cancelled' }) : undefined)
    await openSchedule()
    fireEvent.click(screen.getAllByRole('button', { name: 'Bekor qilish' })[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Orqaga' }))
    expect(calls(f, 'DELETE', '/posts/1')).toHaveLength(0)
    const before = calls(f, 'GET', '/scheduled-posts').length
    fireEvent.click(screen.getAllByRole('button', { name: 'Bekor qilish' })[0])
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Ha, bekor qilish' }))
    expect(await screen.findByText('Post bekor qilindi.')).toBeTruthy()
    expect(calls(f, 'DELETE', '/posts/1')).toHaveLength(1)
    await waitFor(() => expect(calls(f, 'GET', '/scheduled-posts').length).toBeGreaterThan(before))
  })

  it('bekor qilish xatosi (allaqachon yuborilgan): xabar + haqiqiy holat qayta yuklanadi', async () => {
    const f = mockApi((_url, init) => init.method === 'DELETE' ? jsonResponse(errorBody('not_editable'), 409) : undefined)
    await openSchedule()
    const before = calls(f, 'GET', '/scheduled-posts').length
    fireEvent.click(screen.getAllByRole('button', { name: 'Bekor qilish' })[0])
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Ha, bekor qilish' }))
    expect(await screen.findByText(/o'zgartirib bo'lmaydi/)).toBeTruthy()
    await waitFor(() => expect(calls(f, 'GET', '/scheduled-posts').length).toBeGreaterThan(before))
  })

  it('tahrirlash: to\'liq matn serverdan olinadi, faqat o\'zgargan maydon PATCH qilinadi', async () => {
    const f = mockApi((url, init) => init.method === 'PATCH' && url.includes('/posts/1')
      ? jsonResponse({ post: { ...POST_ROW, text: 'Yangi matn' } }) : undefined)
    await openSchedule()
    fireEvent.click(screen.getAllByRole('button', { name: 'Tahrirlash' })[0])
    const area = (await screen.findByLabelText('Post matni')) as HTMLTextAreaElement
    expect(area.value).toBe('To\'liq matn: birinchi post')
    expect(calls(f, 'GET', '/posts/1')).toHaveLength(1)
    fireEvent.change(area, { target: { value: 'Yangi matn' } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText('O\'zgarishlar saqlandi.')).toBeTruthy()
    expect(body(calls(f, 'PATCH', '/posts/1')[0])).toEqual({ text: 'Yangi matn' })
  })

  it('tahrirlash: o\'zgarish yo\'q bo\'lsa so\'rov yuborilmaydi; takrorlanuvchi postda vaqt maydoni yo\'q', async () => {
    const f = mockApi()
    await openSchedule()
    fireEvent.click(screen.getAllByRole('button', { name: 'Tahrirlash' })[0])
    await screen.findByLabelText('Post matni')
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls(f, 'PATCH', '/posts/')).toHaveLength(0)
    fireEvent.click(screen.getAllByRole('button', { name: 'Tahrirlash' })[1])
    await screen.findByLabelText('Post matni')
    expect(screen.queryByLabelText('Sana va vaqt')).toBeNull()
    expect(screen.getByLabelText(/Chiqish vaqti/)).toBeTruthy()
    expect(screen.getByText(/Takrorlanish turini/)).toBeTruthy()
  })

  it('tarix: status=history so\'raladi, holat nishoni ko\'rinadi, amallar tugmasi yo\'q', async () => {
    const f = mockApi()
    await openSchedule()
    fireEvent.click(screen.getByRole('button', { name: 'Tarix' }))
    expect(await screen.findByText('Eski post')).toBeTruthy()
    expect(screen.getByText('Bekor qilingan')).toBeTruthy()
    expect(calls(f, 'GET', 'status=history').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Tahrirlash' })).toBeNull()
  })

  it('XSS: post matnidagi HTML matn sifatida ko\'rsatiladi (DOM elementi yaratilmaydi)', async () => {
    mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.includes('/scheduled-posts') && !url.includes('history')
      ? jsonResponse({ ...PAGE, items: [{ ...PAGE.items[0], preview: '<img src=x onerror=alert(1)><script>alert(2)</script>' }] }) : undefined)
    await (async () => { render(<App />); await screen.findByText('Salom, Alice!'); fireEvent.click(nav(/^Reja/)) })()
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
  })
})

describe('Bosh va Men', () => {
  it('Bosh: yuborilgan/xatoli postlar soni serverdagi haqiqiy hisobdan', async () => {
    mockApi()
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(screen.getByText('Yuborilgan').nextSibling?.textContent).toBe('7')
    expect(screen.getByText('Xato bilan').nextSibling?.textContent).toBe('1')
  })

  it('til almashtirish: PATCH /me/settings, interfeys darhol yangi tilda', async () => {
    const f = mockApi((url, init) => init.method === 'PATCH' && url.endsWith('/me/settings')
      ? jsonResponse({ language: 'ru' }) : undefined)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Men/))
    fireEvent.click(await screen.findByRole('button', { name: 'Русский' }))
    expect(await screen.findByText('Язык сохранён.')).toBeTruthy()
    expect(body(calls(f, 'PATCH', '/me/settings')[0])).toEqual({ language: 'ru' })
    await waitFor(() => expect(document.documentElement.lang).toBe('ru')) // lang atributi useEffect orqali yangilanadi
  })

  it('til almashtirish xatosi: xabar, til o\'zgarmaydi', async () => {
    mockApi((_url, init) => init.method === 'PATCH' ? jsonResponse(errorBody('save_failed'), 503) : undefined)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Men/))
    fireEvent.click(await screen.findByRole('button', { name: 'English' }))
    expect(await screen.findByText(/Saqlab bo'lmadi/)).toBeTruthy()
    expect(document.documentElement.lang).toBe('uz')
  })
})
