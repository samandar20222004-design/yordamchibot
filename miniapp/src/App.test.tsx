// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

type Route = (url: string) => Response | Promise<Response>

function setTelegram(initData: string | null, extra: Record<string, unknown> = {}) {
  if (initData === null) {
    delete (window as unknown as { Telegram?: unknown }).Telegram
    return
  }
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData, colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } }, ready: vi.fn(), expand: vi.fn(), close: vi.fn(),
      openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn(), ...extra },
  }
}

function mockApi(route: Route) {
  const f = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => route(String(input)))
  vi.stubGlobal('fetch', f)
  return f
}

const okRoutes: Route = (url) => {
  if (url.includes('/me')) return jsonResponse(ME)
  if (url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
  if (url.includes('/scheduled-posts')) return jsonResponse(PAGE)
  return jsonResponse(errorBody('not_found'), 404)
}

beforeEach(() => { vi.useRealTimers() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setTelegram(null) })

describe('App', () => {
  it('Botdagi tugma ?tab= bilan ochsa shu bo\'lim ochiladi; noma\'lum qiymat e\'tiborsiz', async () => {
    setTelegram('query_id=1')
    mockApi(okRoutes)
    window.history.replaceState({}, '', '/app/?tab=me')
    render(<App />)
    await screen.findByRole('heading', { name: 'Men' })
    cleanup()
    window.history.replaceState({}, '', '/app/?tab=evil')
    render(<App />)
    await screen.findByText('Salom, Alice!')
    window.history.replaceState({}, '', '/app/')
  })

  it('/me kelguncha logo animatsiyali yuklash ekrani, keyin ilova', async () => {
    setTelegram('query_id=1')
    let release: (r: Response) => void = () => {}
    mockApi((url) => {
      if (url.includes('/me')) return new Promise<Response>((res) => { release = res })
      if (url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
      if (url.includes('/scheduled-posts')) return jsonResponse(PAGE)
      return jsonResponse(errorBody('not_found'), 404)
    })
    const { container } = render(<App />)
    const splash = container.querySelector('.splash')
    expect(splash).not.toBeNull()
    expect(splash?.querySelector('svg.bm .bm-robot')).not.toBeNull()
    expect(splash?.querySelector('svg.bm .bm-badge')).not.toBeNull()
    expect(container.querySelector('.shell')).toBeNull()
    release(jsonResponse(ME))
    await waitFor(() => expect(container.querySelector('.shell')).not.toBeNull())
    expect(container.querySelector('.splash')).toBeNull()
  })

  it('Telegram tashqarisida: tushunarli ekran, so\'rov yuborilmaydi', () => {
    setTelegram(null)
    const f = mockApi(okRoutes)
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Open inside Telegram' })).toBeTruthy()
    expect(f).not.toHaveBeenCalled()
  })

  it('Bosh: ma\'lumotlar, tarif nishoni va to\'rtta bo\'lim', async () => {
    setTelegram('auth_date=1&hash=a')
    mockApi(okRoutes)
    render(<App />)
    expect(await screen.findByText('Salom, Alice!')).toBeTruthy()
    expect(screen.getByText('Bepul')).toBeTruthy()
    const nav = screen.getByRole('navigation')
    expect(nav.querySelectorAll('button')).toHaveLength(4)
    expect(screen.getByText('1 / 5')).toBeTruthy() // AI
  })

  it('Authorization sarlavhasi bilan so\'raydi', async () => {
    setTelegram('auth_date=1&hash=a')
    const f = mockApi(okRoutes)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    const init = f.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('tma auth_date=1&hash=a')
  })

  it('Reja: ro\'yxat, media/takror nishonlari, kanal nomi zaxirasi', async () => {
    setTelegram('auth_date=1&hash=a')
    mockApi(okRoutes)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /Reja/ }))
    expect(await screen.findByText('Birinchi post matni')).toBeTruthy()
    expect(screen.getByText('Kanal A')).toBeTruthy()
    expect(screen.getByText('Media bor')).toBeTruthy()
    expect(screen.getByText('Takrorlanadi')).toBeTruthy()
    expect(screen.getByText('(matnsiz)')).toBeTruthy()
  })

  it('Reja: bo\'sh holat', async () => {
    setTelegram('auth_date=1&hash=a')
    mockApi((url) => url.includes('/scheduled-posts')
      ? jsonResponse({ items: [], total: 0, limit: 20, offset: 0, has_more: false }) : okRoutes(url))
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /Reja/ }))
    expect(await screen.findByText("Rejalashtirilgan post yo'q")).toBeTruthy()
  })

  it('Reja: "Yana yuklash" keyingi sahifani qo\'shadi', async () => {
    setTelegram('auth_date=1&hash=a')
    const f = mockApi((url) => {
      if (url.includes('offset=0')) return jsonResponse({ ...PAGE, total: 3, has_more: true })
      if (url.includes('offset=2')) return jsonResponse({
        items: [{ ...PAGE.items[0], id: 3, preview: 'Uchinchi post', number: 3 }],
        total: 3, limit: 20, offset: 2, has_more: false })
      return okRoutes(url)
    })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /Reja/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Yana yuklash' }))
    expect(await screen.findByText('Uchinchi post')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Yana yuklash' })).toBeNull()
    expect(f.mock.calls.some((c) => String(c[0]).includes('offset=2'))).toBe(true)
  })

  it('Xato: tushunarli matn, qayta urinish ishlaydi', async () => {
    setTelegram('auth_date=1&hash=a')
    let fail = true
    mockApi((url) => {
      if (url.includes('/me') && fail) return jsonResponse(errorBody('rate_limited', 'rq9'), 429)
      return okRoutes(url)
    })
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain("So'rovlar juda ko'p")
    expect(alert.textContent).toContain('rq9')
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Qayta urinish' }))
    expect(await screen.findByText('Salom, Alice!')).toBeTruthy()
  })

  it('Sessiya tugagan: qayta urinish emas, "Yopish" tugmasi', async () => {
    const close = vi.fn()
    setTelegram('auth_date=1&hash=a', { close })
    mockApi(() => jsonResponse(errorBody('auth_expired'), 401))
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Sessiya muddati tugadi')
    expect(screen.queryByRole('button', { name: 'Qayta urinish' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Yopish' }))
    expect(close).toHaveBeenCalled()
  })

  it('Men: profil, tarif limitlari va PRO yo\'naltirmasi (to\'lov tugmasi yo\'q)', async () => {
    const openTelegramLink = vi.fn()
    setTelegram('auth_date=1&hash=a', { openTelegramLink })
    mockApi(okRoutes)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /Men/ }))
    expect(await screen.findByText(/@alice/)).toBeTruthy()
    expect(await screen.findByText('Kanal A')).toBeTruthy()
    expect(screen.getByText(/PRO va Tariflar/)).toBeTruthy()
    expect(screen.queryByText(/To'lash|Sotib/i)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Botni ochish' }))
    expect(openTelegramLink).toHaveBeenCalledWith('https://t.me/PostAssistrobot')
  })

  it('PRO foydalanuvchi: cheksiz limitlar va muddat', async () => {
    setTelegram('auth_date=1&hash=a')
    const pro = { ...ME, plan: { type: 'pro', is_pro: true, expires_at: '2026-11-01T00:00:00Z',
      limits: { max_channels: 999, daily_ai_requests: 999, queued_posts: 999 } } }
    mockApi((url) => url.includes('/me') ? jsonResponse(pro) : okRoutes(url))
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(screen.getByText('PRO')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /Men/ }))
    expect(await screen.findByText('Obunangiz faol.')).toBeTruthy()
    expect(screen.getAllByText(/\/ ∞/).length).toBe(3) // 3 ta cheksiz limit: son / ∞
    expect(screen.queryAllByRole('progressbar')).toHaveLength(0) // cheksizda chiziq yo'q
  })

  it('Til profil bo\'yicha almashadi (ru)', async () => {
    setTelegram('auth_date=1&hash=a')
    mockApi((url) => url.includes('/me') ? jsonResponse({ ...ME, user: { ...ME.user, language: 'ru' } }) : okRoutes(url))
    render(<App />)
    expect(await screen.findByText('Здравствуйте, Alice!')).toBeTruthy()
    await waitFor(() => expect(document.documentElement.lang).toBe('ru')) // lang atributi useEffect orqali yangilanadi
  })
})

describe('Bosh sahifa', () => {
  it('salomlashuv, keyingi postgacha sanoq, maslahat va tezkor harakatlar ko\'rinadi', async () => {
    setTelegram('query_id=1')
    mockApi((url) => {
      if (url.includes('/me')) return jsonResponse({ ...ME, next_post_at: new Date(Date.now() + 135 * 60000).toISOString() })
      return okRoutes(url)
    })
    const { container } = render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(container.querySelector('.hero-kicker')?.textContent).toMatch(/Xayrli/)
    expect(container.querySelector('.hero-mark svg.bm')).not.toBeNull()
    expect(container.querySelector('.next-when')?.textContent).toMatch(/soat .* daqiqadan keyin/)
    expect(container.querySelector('.tip-card p')?.textContent?.length).toBeGreaterThan(20)
    expect(screen.getByRole('button', { name: 'Yangi post yozish' })).toBeTruthy()
    expect(container.querySelectorAll('.stat-bar').length).toBe(2)
    expect(container.querySelector('.achievement')?.textContent).toMatch(/7 ta post/)
    fireEvent.click(screen.getByRole('button', { name: 'Yangi post yozish' }))
    await screen.findByLabelText('Post matni', { selector: 'textarea' })
  })

  it('post rejalanmagan bo\'lsa: bo\'sh holat va «Post rejalash» tugmasi', async () => {
    setTelegram('query_id=1')
    mockApi((url) => (url.includes('/me') ? jsonResponse({ ...ME, next_post_at: null }) : okRoutes(url)))
    const { container } = render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(container.querySelector('.next-when')).toBeNull()
    expect(screen.getByRole('button', { name: 'Post rejalash' })).toBeTruthy()
  })
})
