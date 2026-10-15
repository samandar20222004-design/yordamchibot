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

const TPL = { id: 5, name: 'Salomlashuv', text: '<b>Assalomu alaykum</b>, kanal a\'zolari!', created_at: '2026-01-01T00:00:00Z' }

function mockApi(handler: Handler = () => undefined) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = handler(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const calls = (f: ReturnType<typeof mockApi>, method: string, part: string) =>
  f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === method && String(c[0]).includes(part))
const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })

async function openPost() {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Post/))
  return screen.findByLabelText('Post matni', { selector: 'textarea' })
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Tozalagich', () => {
  it('matn tozalanadi, xabar chiqadi va «Qaytarish» asl matnni tiklaydi', async () => {
    const f = mockApi((url, init) => init.method === 'POST' && url.endsWith('/tools/clean')
      ? jsonResponse({ text: 'Asosiy\n\nImzo', removed_lines: 2, signature_added: true, has_signature: true, changed: true }) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.change(text, { target: { value: 'Asosiy\nReklama: t.me/x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tozalash' }))
    await waitFor(() => expect(text.value).toBe('Asosiy\n\nImzo'))
    expect(JSON.parse(String(calls(f, 'POST', '/tools/clean')[0][1]?.body))).toEqual({ text: 'Asosiy\nReklama: t.me/x' })
    expect(await screen.findByText(/Begona qatorlar olindi: 2/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Qaytarish' }))
    expect(text.value).toBe('Asosiy\nReklama: t.me/x')
    expect(screen.queryByRole('button', { name: 'Qaytarish' })).toBeNull()
  })

  it('o\'zgarish bo\'lmasa matn tegilmaydi; bo\'sh matnda tugma o\'chiq', async () => {
    mockApi((url, init) => init.method === 'POST' && url.endsWith('/tools/clean')
      ? jsonResponse({ text: 'Toza', removed_lines: 0, signature_added: false, has_signature: true, changed: false }) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    expect((screen.getByRole('button', { name: 'Tozalash' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(text, { target: { value: 'Toza' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tozalash' }))
    expect(await screen.findByText('Tozalashga hojat yo\'q.')).toBeTruthy()
    expect(text.value).toBe('Toza')
    expect(screen.queryByRole('button', { name: 'Qaytarish' })).toBeNull()
  })

  it('server xatosi: matn o\'zgarmaydi, xato xabari ko\'rinadi', async () => {
    mockApi((url, init) => init.method === 'POST' && url.endsWith('/tools/clean') ? jsonResponse(errorBody('save_failed'), 503) : undefined)
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.change(text, { target: { value: 'Matn' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tozalash' }))
    expect(await screen.findByText(/Saqlab bo'lmadi/)).toBeTruthy()
    expect(text.value).toBe('Matn')
  })
})

describe('Shablonlar', () => {
  const open = async () => {
    const text = (await openPost()) as HTMLTextAreaElement
    fireEvent.click(screen.getByRole('heading', { name: /Shablonlar/ }))
    return text
  }

  it('ochilganda yuklanadi; yig\'ilganda so\'rov yo\'q', async () => {
    const f = mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.endsWith('/templates') ? jsonResponse({ items: [TPL], limit: 20 }) : undefined)
    await openPost()
    expect(calls(f, 'GET', '/templates')).toHaveLength(0)
    fireEvent.click(screen.getByRole('heading', { name: /Shablonlar/ }))
    expect(await screen.findByText('Salomlashuv')).toBeTruthy()
    expect(calls(f, 'GET', '/templates')).toHaveLength(1)
    expect(screen.getByText('1 / 20')).toBeTruthy()
  })

  it('bo\'sh holat tushuntiriladi', async () => {
    mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.endsWith('/templates') ? jsonResponse({ items: [], limit: 20 }) : undefined)
    await open()
    expect(await screen.findByText(/Hali shablon yo'q/)).toBeTruthy()
  })

  it('bo\'sh tahrirlagichda «Qo\'llash» matnni darhol qo\'yadi', async () => {
    mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.endsWith('/templates') ? jsonResponse({ items: [TPL], limit: 20 }) : undefined)
    const text = await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Qo\'llash' }))
    expect(text.value).toBe(TPL.text)
  })

  it('matn bor bo\'lsa almashtirish tasdiqlanadi (bekor qilsa matn saqlanadi)', async () => {
    mockApi((url, init) => (init.method ?? 'GET') === 'GET' && url.endsWith('/templates') ? jsonResponse({ items: [TPL], limit: 20 }) : undefined)
    const text = await open()
    fireEvent.change(text, { target: { value: 'Mening matnim' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Qo\'llash' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Orqaga' }))
    expect(text.value).toBe('Mening matnim')
    fireEvent.click(screen.getByRole('button', { name: 'Qo\'llash' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Almashtirish' }))
    expect(text.value).toBe(TPL.text)
  })

  it('saqlash: matn va nom yuboriladi, ro\'yxat yangilanadi; nomsiz/matnsiz so\'rov yuborilmaydi', async () => {
    let items: typeof TPL[] = []
    const f = mockApi((url, init) => {
      const m = init.method ?? 'GET'
      if (m === 'GET' && url.endsWith('/templates')) return jsonResponse({ items, limit: 20 })
      if (m === 'POST' && url.endsWith('/templates')) { items = [TPL]; return jsonResponse({ id: 5, created: true }, 201) }
      return undefined
    })
    const text = await open()
    await screen.findByText(/Hali shablon yo'q/)
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText('Shablonga nom bering.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Shablon nomi'), { target: { value: 'Salomlashuv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText('Avval matn yozing — shu matn shablon bo\'ladi.')).toBeTruthy()
    expect(calls(f, 'POST', '/templates')).toHaveLength(0)
    fireEvent.change(text, { target: { value: '  Tayyor matn  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText('Salomlashuv', { selector: 'strong' })).toBeTruthy()
    expect(JSON.parse(String(calls(f, 'POST', '/templates')[0][1]?.body))).toEqual({ name: 'Salomlashuv', text: 'Tayyor matn' })
  })

  it('o\'chirish tasdiqlanadi va qatorni olib tashlaydi', async () => {
    const f = mockApi((url, init) => {
      const m = init.method ?? 'GET'
      if (m === 'GET' && url.endsWith('/templates')) return jsonResponse({ items: [TPL], limit: 20 })
      if (m === 'DELETE' && url.endsWith('/templates/5')) return jsonResponse({ id: 5, deleted: true })
      return undefined
    })
    await open()
    fireEvent.click(await screen.findByRole('button', { name: 'O\'chirish: Salomlashuv' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'O\'chirish' }))
    await waitFor(() => expect(calls(f, 'DELETE', '/templates/5')).toHaveLength(1))
    await waitFor(() => expect(screen.queryByText('Salomlashuv', { selector: 'strong' })).toBeNull())
  })

  it('limit to\'lganda xabar ko\'rsatiladi', async () => {
    mockApi((url, init) => {
      const m = init.method ?? 'GET'
      if (m === 'GET' && url.endsWith('/templates')) return jsonResponse({ items: [], limit: 20 })
      if (m === 'POST' && url.endsWith('/templates')) return jsonResponse(errorBody('templates_limit_reached'), 403)
      return undefined
    })
    const text = await open()
    await screen.findByText(/Hali shablon yo'q/)
    fireEvent.change(text, { target: { value: 'Matn' } })
    fireEvent.change(screen.getByLabelText('Shablon nomi'), { target: { value: 'N' } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText(/Shablonlar limiti to'ldi/)).toBeTruthy()
  })
})
