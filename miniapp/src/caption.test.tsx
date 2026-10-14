// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const MEDIA_POST = { ...PAGE.items[1], text: 'Rasm sarlavhasi' } // has_media: true

function mockApi(patch?: Response, post: typeof MEDIA_POST = MEDIA_POST) {
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    if (method === 'PATCH' && patch) return patch
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
    if (method === 'GET' && url.includes('/posts/2')) return jsonResponse({ post })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const nav = (name: RegExp) => within(screen.getByRole('navigation')).getByRole('button', { name })
const patches = (f: ReturnType<typeof mockApi>) => f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === 'PATCH')

async function openMediaEditor(expected = 'Rasm sarlavhasi') {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(nav(/^Reja/))
  await screen.findByText('Birinchi post matni')
  fireEvent.click(screen.getAllByRole('button', { name: 'Tahrirlash' })[1]) // 2-post: rasm
  const area = (await screen.findByLabelText('Post matni')) as HTMLTextAreaElement
  expect(area.value).toBe(expected)
  return area
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Media postni tahrirlash: sarlavha (caption) chegarasi 1024', () => {
  it('1025 belgi: aniq xato, so\'rov yuborilmaydi; maxLength=1024', async () => {
    const f = mockApi()
    const area = await openMediaEditor()
    expect(area.maxLength).toBe(1024)
    fireEvent.change(area, { target: { value: 'a'.repeat(1025) } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText(/Media sarlavhasi 1024/)).toBeTruthy()
    expect(patches(f)).toHaveLength(0)
  })

  it('eski uzun (>1024) matn o\'zgartirilmasa: uzunlik xatosi chiqmaydi (vaqt tahriri bloklanmaydi)', async () => {
    const longText = 'a'.repeat(1500)
    const f = mockApi(undefined, { ...MEDIA_POST, text: longText })
    await openMediaEditor(longText)
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(screen.queryByText(/Media sarlavhasi 1024/)).toBeNull()
    expect(patches(f)).toHaveLength(0)
  })

  it('server caption_too_long qaytarsa: tushunarli xabar ko\'rsatiladi', async () => {
    const f = mockApi(jsonResponse(errorBody('caption_too_long', 'req9', null, 'text'), 422))
    const area = await openMediaEditor()
    fireEvent.change(area, { target: { value: 'Yangi sarlavha' } })
    fireEvent.click(screen.getByRole('button', { name: 'Saqlash' }))
    expect(await screen.findByText(/Rasm\/video ostidagi matn 1024 belgidan oshmasligi kerak/)).toBeTruthy()
    expect(patches(f)).toHaveLength(1)
  })
})
