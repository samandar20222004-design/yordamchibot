// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse, setEditor } from './test/helpers'

type Handler = (url: string, init: RequestInit) => Response | Promise<Response> | undefined

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const DRAFT = { draft: { post_type: 'photo', text: 'Sarlavha', button_text: null, button_url: null, channel_id: null, reactions: false,
  delete_after_hours: 0, media: { type: 'photo', previewable: false, count: null, items: [{ type: 'photo', previewable: false }] }, updated_at: '2026-10-15T08:00:00Z' } }

function mockApi(handler: Handler = () => undefined, draft: unknown = { draft: null }) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = handler(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse(draft)
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
const uploads = (f: ReturnType<typeof mockApi>) => f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === 'POST' && String(c[0]).includes('/draft/media'))

async function openPost() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Post/))
  const text = (await screen.findByLabelText('Post matni')) as HTMLElement
  return { text, input: screen.getByLabelText('Rasm va videolar', { selector: 'input' }) as HTMLInputElement }
}
const pick = (input: HTMLInputElement, file: File) => fireEvent.change(input, { target: { files: [file] } })
const png = (size = 100) => new File([new Uint8Array(size)], 'a.png', { type: 'image/png' })

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Media yuklash', () => {
  it('rasm multipart bilan yuboriladi (matn birga), Authorization bor, Content-Type qo\'lda berilmaydi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.includes('/draft/media') ? jsonResponse(DRAFT) : undefined)
    const { text, input } = await openPost()
    setEditor(text, '  Sarlavha  ')
    pick(input, png())
    expect(await screen.findByText('Fayl qo\'shildi.')).toBeTruthy()
    const [call] = uploads(f)
    const init = call[1] as RequestInit
    expect(init.body).toBeInstanceOf(FormData)
    const form = init.body as FormData
    expect(form.get('text')).toBe('Sarlavha')
    expect((form.get('file') as File).name).toBe('a.png')
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('tma auth_date=1&hash=a')
    expect(headers['Content-Type']).toBeUndefined() // brauzer boundary bilan o'zi qo'yadi
  })

  it('qo\'llab-quvvatlanmaydigan tur va katta fayl: so\'rov yuborilmaydi', async () => {
    const f = mockApi()
    const { input } = await openPost()
    pick(input, new File(['x'], 'a.exe', { type: 'application/x-msdownload' }))
    expect(await screen.findByText(/fayl turi qo'llab-quvvatlanmaydi/)).toBeTruthy()
    pick(input, new File([new Uint8Array(51 * 1024 * 1024)], 'v.mp4', { type: 'video/mp4' }))
    expect(await screen.findByText(/Fayl juda katta/)).toBeTruthy()
    expect(uploads(f)).toHaveLength(0)
  })

  it('sarlavha 1024 dan uzun bo\'lsa yuklanmaydi', async () => {
    const f = mockApi()
    const { text, input } = await openPost()
    setEditor(text, 'x'.repeat(1100))
    pick(input, png())
    expect(await screen.findByText(/1024 belgidan oshmasligi kerak/)).toBeTruthy()
    expect(uploads(f)).toHaveLength(0)
  })

  it('server xatosi (upload_failed): tushunarli xabar, tugma qayta ishlaydi', async () => {
    mockApi((url, init) => init.method === 'POST' && url.includes('/draft/media') ? jsonResponse(errorBody('upload_failed'), 503) : undefined)
    const { input } = await openPost()
    pick(input, png())
    expect(await screen.findByText(/Telegram'ga yuklab bo'lmadi/)).toBeTruthy()
    await waitFor(() => expect((screen.getByRole('button', { name: 'Rasm/video qo\'shish' }) as HTMLButtonElement).disabled).toBe(false))
  })

  it('qoralamada media bo\'lsa albom katakchalari: hisoblagich, «+» va ✕ tugmalari', async () => {
    mockApi(undefined, DRAFT)
    await openPost()
    expect(await screen.findByText('1 / 10 ta')).toBeTruthy()
    expect(screen.getByRole('button', { name: '1-mediani olib tashlash' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Rasm/video qo\'shish' })).toBeTruthy()
  })
})

describe('Albom (10 tagacha media)', () => {
  const album = (n: number) => ({ draft: { ...DRAFT.draft, post_type: n > 1 ? 'album' : 'photo',
    media: { type: n > 1 ? 'album' : 'photo', previewable: false, count: n, items: Array.from({ length: n }, () => ({ type: 'photo', previewable: false })) } } })

  it('bir necha fayl tanlansa ketma-ket albomga qo\'shiladi (?add=1), har biri alohida so\'rov', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.includes('/draft/media') ? jsonResponse(album(1)) : undefined)
    const { input } = await openPost()
    fireEvent.change(input, { target: { files: [png(), png(), png()] } })
    await waitFor(() => expect(uploads(f)).toHaveLength(3))
    expect(uploads(f).every((c) => String(c[0]).endsWith('/draft/media?add=1'))).toBe(true)
    expect(await screen.findByText('Fayl qo\'shildi.')).toBeTruthy()
  })

  it('10 ta to\'lgan albomga yana fayl: ogohlantirish, yuklash so\'rovi yuborilmaydi, «+» yo\'q', async () => {
    const f = mockApi(undefined, album(10))
    const { input } = await openPost()
    expect(await screen.findByText('10 / 10 ta')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Rasm/video qo\'shish' })).toBeNull()
    fireEvent.change(input, { target: { files: [png(), png()] } })
    expect(await screen.findByText(/Albomga ko'pi bilan 10 ta media: 2 ta fayl qo'shilmadi/)).toBeTruthy()
    expect(uploads(f)).toHaveLength(0)
  })

  it('sig\'imdan ortig\'i qisqartiriladi: 9 ta bor, 3 ta tanlansa faqat 1 tasi yuklanadi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.includes('/draft/media') ? jsonResponse(album(10)) : undefined, album(9))
    const { input } = await openPost()
    expect(await screen.findByText('9 / 10 ta')).toBeTruthy()
    fireEvent.change(input, { target: { files: [png(), png(), png()] } })
    expect(await screen.findByText(/2 ta fayl qo'shilmadi/)).toBeTruthy()
    await waitFor(() => expect(uploads(f)).toHaveLength(1))
  })

  it('GIF albomga qo\'shilmaydi (Telegram qoidasi): aniq xabar, so\'rov yo\'q', async () => {
    const f = mockApi(undefined, album(2))
    const { input } = await openPost()
    await screen.findByText('2 / 10 ta')
    fireEvent.change(input, { target: { files: [new File(['GIF89a'], 'a.gif', { type: 'image/gif' })] } })
    expect(await screen.findByText(/GIF albomga qo'shilmaydi/)).toBeTruthy()
    expect(uploads(f)).toHaveLength(0)
  })

  it('bittasini olib tashlash: DELETE /draft/media?i=<index>, ro\'yxat qayta yuklanadi', async () => {
    const f = mockApi((url, init) => init.method === 'DELETE' && url.includes('/draft/media') ? jsonResponse(album(2)) : undefined, album(3))
    await openPost()
    expect(await screen.findByText('3 / 10 ta')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '2-mediani olib tashlash' }))
    await waitFor(() => expect(f.mock.calls.some((c) => c[1]?.method === 'DELETE' && String(c[0]).endsWith('/draft/media?i=1'))).toBe(true))
  })

  it('albom va tugma birga: tugma albom ostida alohida xabar bo\'lishi haqida eslatma', async () => {
    mockApi(undefined, { draft: { ...album(2).draft, button_text: 'Ochish', button_url: 'https://example.org' } })
    await openPost()
    expect(await screen.findByText(/alohida «🔗» xabarida chiqadi/)).toBeTruthy()
  })
})
