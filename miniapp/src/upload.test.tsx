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
  delete_after_hours: 0, media: { type: 'photo', previewable: false, count: null }, updated_at: '2026-10-15T08:00:00Z' } }

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
const uploads = (f: ReturnType<typeof mockApi>) => f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === 'POST' && String(c[0]).endsWith('/draft/media'))

async function openPost() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Post/))
  const text = (await screen.findByLabelText('Post matni')) as HTMLElement
  return { text, input: screen.getByLabelText('Rasm yoki video') as HTMLInputElement }
}
const pick = (input: HTMLInputElement, file: File) => fireEvent.change(input, { target: { files: [file] } })
const png = (size = 100) => new File([new Uint8Array(size)], 'a.png', { type: 'image/png' })

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Media yuklash', () => {
  it('rasm multipart bilan yuboriladi (matn birga), Authorization bor, Content-Type qo\'lda berilmaydi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/draft/media') ? jsonResponse(DRAFT) : undefined)
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
    pick(input, png(10 * 1024 * 1024 + 1))
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
    mockApi((url, init) => init.method === 'POST' && url.endsWith('/draft/media') ? jsonResponse(errorBody('upload_failed'), 503) : undefined)
    const { input } = await openPost()
    pick(input, png())
    expect(await screen.findByText(/Telegram'ga yuklab bo'lmadi/)).toBeTruthy()
    await waitFor(() => expect((screen.getByRole('button', { name: 'Rasm/video qo\'shish' }) as HTMLButtonElement).disabled).toBe(false))
  })

  it('qoralamada media bo\'lsa tugma «Almashtirish» deb chiqadi', async () => {
    mockApi(undefined, DRAFT)
    await openPost()
    expect(await screen.findByRole('button', { name: 'Almashtirish' })).toBeTruthy()
  })
})
