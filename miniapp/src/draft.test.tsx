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

const DRAFT = {
  post_type: 'photo', text: '<b>Bot matni</b> kanal uchun', button_text: 'Ochish', button_url: 'https://example.org/go',
  channel_id: '-1002', reactions: true, delete_after_hours: 24,
  media: { type: 'photo', previewable: true, count: null }, updated_at: '2026-10-14T09:00:00Z',
}

function mockApi(draft: unknown | null = DRAFT, handler: Handler = () => undefined) {
  let current = draft
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = handler(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: current })
    if (method === 'GET' && url.endsWith('/draft/media')) return new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { 'Content-Type': 'image/jpeg' } })
    if (method === 'DELETE' && url.endsWith('/draft')) { current = null; return jsonResponse({ deleted: true }) }
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }, { id: '-1002', title: 'Kanal B' }], total: 2 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const calls = (f: ReturnType<typeof mockApi>, method: string, part: string) =>
  f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === method && String(c[0]).endsWith(part))
const body = (c: unknown[]) => JSON.parse(String((c[1] as RequestInit).body))
const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
const created = () => jsonResponse({ post: { ...PAGE.items[0], id: 77 }, created: true, delivery: 'scheduled' }, 201)

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Botdan kelgan qoralama', () => {
  it('ilova qoralama bilan ochilganda to\'g\'ridan-to\'g\'ri tahrirlagichga tushadi va maydonlar to\'ladi', async () => {
    mockApi()
    render(<App />)
    const text = await screen.findByLabelText('Post matni', { selector: 'textarea' }) as HTMLTextAreaElement
    expect(text.value).toBe('<b>Bot matni</b> kanal uchun')
    expect(screen.getByText('Botdan kelgan post')).toBeTruthy()
    await waitFor(() => expect((screen.getByLabelText('Kanal') as HTMLSelectElement).value).toBe('-1002'))
    expect((screen.getByLabelText('Tugma matni') as HTMLInputElement).value).toBe('Ochish')
    // Ko'rinish: HTML xavfsiz ko'rsatiladi (<strong>), xom teg matni emas
    const preview = screen.getByRole('region', { name: 'Ko\'rinish' })
    expect(preview.querySelector('strong')?.textContent).toBe('Bot matni')
    expect(preview.textContent).toContain('Ochish')
  })

  it('rasm qoralamasi Authorization bilan so\'raladi', async () => {
    const f = mockApi()
    render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).endsWith('/draft/media'))).toBe(true))
    const call = f.mock.calls.find((c) => String(c[0]).endsWith('/draft/media')) as unknown[]
    expect(((call[1] as RequestInit).headers as Record<string, string>).Authorization).toBe('tma auth_date=1&hash=a')
  })

  it('rejalashtirish: use_draft va tugma yuboriladi, keyin qoralama qayta so\'raladi', async () => {
    const f = mockApi(DRAFT, (url, init) => init.method === 'POST' && url.endsWith('/posts') ? created() : undefined)
    render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect((screen.getByLabelText('Kanal') as HTMLSelectElement).value).toBe('-1002'))
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText('Post rejalashtirildi. U «Reja» bo\'limida.')).toBeTruthy()
    const [call] = calls(f, 'POST', '/posts')
    const sent = body(call)
    expect(sent.use_draft).toBe(true)
    expect(sent.channel_id).toBe('-1002')
    expect(sent.button_text).toBe('Ochish')
    expect(sent.button_url).toBe('https://example.org/go')
    expect(sent.text).toBe('<b>Bot matni</b> kanal uchun')
    expect('file_id' in sent).toBe(false) // mijoz file_id yubormaydi
    expect(calls(f, 'GET', '/draft').length).toBeGreaterThanOrEqual(2)
  })

  it('sarlavhasiz rasm: bo\'sh matn ruxsat, matnli (media yo\'q) postda esa rad', async () => {
    const f = mockApi({ ...DRAFT, text: '', button_text: null, button_url: null },
      (url, init) => init.method === 'POST' && url.endsWith('/posts') ? created() : undefined)
    render(<App />)
    const text = await screen.findByLabelText('Post matni', { selector: 'textarea' }) as HTMLTextAreaElement
    expect(text.value).toBe('')
    await waitFor(() => expect((screen.getByLabelText('Kanal') as HTMLSelectElement).value).toBe('-1002'))
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    await screen.findByText('Post rejalashtirildi. U «Reja» bo\'limida.')
    const sent = body(calls(f, 'POST', '/posts')[0])
    expect(sent.text).toBe('')
    expect(sent.use_draft).toBe(true)
    expect('button_text' in sent).toBe(false)
  })

  it('media sarlavhasi 1024 belgidan oshsa so\'rov yuborilmaydi', async () => {
    const f = mockApi()
    render(<App />)
    const text = await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect((screen.getByLabelText('Kanal') as HTMLSelectElement).value).toBe('-1002'))
    fireEvent.change(text, { target: { value: 'a'.repeat(1025) } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Media sarlavhasi 1024/)).toBeTruthy()
    expect(calls(f, 'POST', '/posts')).toHaveLength(0)
  })

  it('qoralamani o\'chirish: tasdiq so\'raladi, DELETE /draft yuboriladi', async () => {
    const f = mockApi()
    render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    fireEvent.click(screen.getByRole('button', { name: 'Qoralamani o\'chirish' }))
    expect(calls(f, 'DELETE', '/draft')).toHaveLength(0) // tasdiqsiz o'chmaydi
    fireEvent.click(await screen.findByRole('button', { name: 'Ha, o\'chirish' }))
    expect(await screen.findByText('Qoralama o\'chirildi.')).toBeTruthy()
    expect(calls(f, 'DELETE', '/draft')).toHaveLength(1)
    await waitFor(() => expect(screen.queryByText('Botdan kelgan post')).toBeNull())
  })

  it('qoralama muddati tugagan (draft_not_found): xato ko\'rsatiladi', async () => {
    mockApi(DRAFT, (url, init) => init.method === 'POST' && url.endsWith('/posts') ? jsonResponse(errorBody('draft_not_found'), 404) : undefined)
    render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect((screen.getByLabelText('Kanal') as HTMLSelectElement).value).toBe('-1002'))
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Qoralama topilmadi yoki muddati tugagan/)).toBeTruthy()
  })

  it('qoralama yo\'q: Bosh sahifada chaqiriq yo\'q, qoralama bor bo\'lsa Boshda "Davom ettirish" bor', async () => {
    mockApi(null)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(screen.queryByText('Botdan kelgan post tayyor')).toBeNull()
    cleanup()
    mockApi()
    render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    fireEvent.click(nav(/^Bosh/))
    expect(await screen.findByText('Botdan kelgan post tayyor')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Davom ettirish' }))
    expect(await screen.findByLabelText('Post matni', { selector: 'textarea' })).toBeTruthy()
  })

  it('/draft xatosi (eski server): ilova ishlayveradi, qoralama ko\'rsatilmaydi', async () => {
    mockApi(null, (url, init) => (init.method ?? 'GET') === 'GET' && url.endsWith('/draft') ? jsonResponse(errorBody('not_found'), 404) : undefined)
    render(<App />)
    expect(await screen.findByText('Salom, Alice!')).toBeTruthy()
  })
})

describe('Tahrirlagich: format, tugma, tez vaqt', () => {
  async function open() {
    mockApi(null)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Post/))
    return await screen.findByLabelText('Post matni', { selector: 'textarea' }) as HTMLTextAreaElement
  }

  it('Qalin tugmasi tanlangan matnni <b> bilan o\'raydi', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: 'Salom dunyo' } })
    text.setSelectionRange(6, 11)
    fireEvent.select(text)
    fireEvent.click(screen.getByRole('button', { name: 'Qalin' }))
    await waitFor(() => expect(text.value).toBe('Salom <b>dunyo</b>'))
  })

  it('havola: xavfli manzil qabul qilinmaydi, to\'g\'ri manzil <a href> qo\'shadi', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: 'link' } })
    text.setSelectionRange(0, 4)
    fireEvent.select(text)
    fireEvent.click(screen.getByRole('button', { name: 'Havola' }))
    const url = screen.getByLabelText('Havola manzili (https://…)')
    fireEvent.change(url, { target: { value: 'javascript:alert(1)' } })
    expect((screen.getByRole('button', { name: 'Qo\'yish' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(url, { target: { value: 'https://example.org/a?x=1&y=2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Qo\'yish' }))
    await waitFor(() => expect(text.value).toBe('<a href="https://example.org/a?x=1&amp;y=2">link</a>'))
  })

  it('tugma: noto\'g\'ri havola bilan so\'rov yuborilmaydi', async () => {
    const f = mockApi(null)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(nav(/^Post/))
    const text = await screen.findByLabelText('Post matni', { selector: 'textarea' })
    fireEvent.change(screen.getByLabelText('Kanal'), { target: { value: '-1001' } })
    fireEvent.change(text, { target: { value: 'Matn' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tugma qo\'shish' }))
    fireEvent.change(screen.getByLabelText('Tugma matni'), { target: { value: 'Ochish' } })
    fireEvent.change(screen.getByLabelText('Tugma havolasi (https://…)'), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: 'Postni rejalashtirish' }))
    expect(await screen.findByText(/Tugma matni \(1–64 belgi\)/)).toBeTruthy()
    expect(calls(f, 'POST', '/posts')).toHaveLength(0)
  })

  it('tez vaqt tugmasi sanani o\'rnatadi', async () => {
    await open()
    const when = screen.getByLabelText('Sana va vaqt') as HTMLInputElement
    fireEvent.change(when, { target: { value: '2030-01-01T10:00' } })
    fireEvent.click(screen.getByRole('button', { name: /^1 soat/ }))
    expect(when.value).not.toBe('2030-01-01T10:00')
    expect(when.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  })
})

describe('Qoralamadagi video/GIF oldindan ko\'rish', () => {
  it('video qoralama: <video> ko\'rinadi (blob:), rasm bo\'lsa <img>', async () => {
    const created: string[] = []
    vi.stubGlobal('URL', Object.assign(URL, {
      createObjectURL: vi.fn((b: Blob) => { created.push(b.type); return 'blob:test-media' }), revokeObjectURL: vi.fn() }))
    mockApi({ ...DRAFT, post_type: 'video', media: { type: 'video', previewable: true, count: null } }, (url) =>
      url.endsWith('/draft/media') ? new Response(new Uint8Array([0, 0, 0, 24]), { status: 200, headers: { 'Content-Type': 'video/mp4' } }) : undefined)
    const { container } = render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect(container.querySelector('video.bubble-media')).not.toBeNull())
    const video = container.querySelector('video.bubble-media') as HTMLVideoElement
    expect(video.getAttribute('src')).toBe('blob:test-media')
    expect(video.muted).toBe(true)
    expect(container.querySelector('img.bubble-media')).toBeNull()
    expect(created).toContain('video/mp4')
  })

  it('HTML (rasm emas, video emas) javobi ko\'rsatilmaydi: belgi bilan o\'rin egasi', async () => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }))
    mockApi(DRAFT, (url) =>
      url.endsWith('/draft/media') ? new Response('<html>', { status: 200, headers: { 'Content-Type': 'text/html' } }) : undefined)
    const { container } = render(<App />)
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
    await waitFor(() => expect(container.querySelector('.bubble-media-ph')).not.toBeNull())
    expect(container.querySelector('video.bubble-media, img.bubble-media')).toBeNull()
  })
})
