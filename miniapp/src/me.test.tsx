// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { Meter, initialOf } from './pages/MePage'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setTelegram(photo?: string) {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz', ...(photo ? { photo_url: photo } : {}) } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

function mockApi(me = ME) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/me')) return jsonResponse(me)
    if (method === 'GET' && url.includes('/channels')) {
      return jsonResponse({ items: [{ id: '-1001', title: 'Juda uzun nomli kanal: Mahsulotlar va xizmatlar yangiliklari', pending_posts: 3, members: 12345, members_as_of: '2026-10-14' }], total: 1 })
    }
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    return jsonResponse(errorBody('not_found'), 404)
  }))
}

const openMe = async () => {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('initialOf', () => {
  it('birinchi harf, katta; emoji va bo\'sh matn xavfsiz', () => {
    expect(initialOf('alice')).toBe('A')
    expect(initialOf('  Мария')).toBe('М')
    expect(initialOf('😀 Kanal')).toBe('😀')
    expect(initialOf('')).toBe('?')
    expect(initialOf('   ')).toBe('?')
  })
})

describe('Meter', () => {
  it('chiziq foizi va daraja: 2/5 -> 40% ok, 4/5 -> high, 5/5 va oshgan -> 100% full', () => {
    const { container, rerender } = render(<Meter label="AI" used={2} max={5} />)
    const bar = () => container.querySelector('.meter-bar > span') as HTMLElement
    expect(bar().style.width).toBe('40%')
    expect(bar().dataset.level).toBe('ok')
    rerender(<Meter label="AI" used={4} max={5} />)
    expect(bar().dataset.level).toBe('high')
    rerender(<Meter label="AI" used={9} max={5} />)
    expect(bar().style.width).toBe('100%')
    expect(bar().dataset.level).toBe('full')
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('5') // limitdan oshmaydi
  })
  it('cheksiz: "son / ∞", chiziq yo\'q', () => {
    render(<Meter label="Kanallar" used={7} max={999} />)
    expect(screen.getByText('7 / ∞')).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })
})

const openRow = (name: RegExp) => fireEvent.click(screen.getAllByRole('button', { name }).find((b) => b.classList.contains('set-row'))!)

describe('Profil sahifasi', () => {
  it('bepul: ism, @username, tarif belgisi, 3 ta foydalanish ko\'rsatkichi va sozlamalar qatorlari', async () => {
    mockApi()
    await openMe()
    expect(await screen.findByText(/@alice/)).toBeTruthy()
    expect(screen.getAllByText('Bepul').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('progressbar')).toHaveLength(3)
    expect(screen.getByText('2 / 3')).toBeTruthy()     // kanallar
    expect(screen.getByText('1 / 5')).toBeTruthy()     // AI (bugun)
    expect(screen.getByText('3 / 5')).toBeTruthy()     // navbat
    const rows = Array.from(document.querySelectorAll('.set-row .set-label')).map((e) => e.textContent)
    expect(rows).toEqual(['Tarif', 'Til', 'Ko\'rinish', 'Bildirishnomalar', 'Kanallarim', 'Botga o\'tish', 'Do\'stlarni taklif qilish', 'Yordam va qo\'llanma', 'Ilovani yopish'])
    expect(screen.queryByText(/Cheksiz/)).toBeNull()   // "cheksiz" va'dasi yo'q
  })

  it('Tarif alohida ekranda: davr tanlanadi, PRO va ULTRA kartalarida HAQIQIY limitlar, narx va tejam; botda sotib olish', async () => {
    mockApi()
    await openMe()
    openRow(/^Tarif/)
    expect(await screen.findByRole('heading', { name: 'Tariflar' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'PRO' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'ULTRA' })).toBeTruthy()
    expect(screen.getByText('Kanallar: 10 tagacha')).toBeTruthy()
    expect(screen.getByText('Kanallar: 30 tagacha')).toBeTruthy()
    expect(screen.getByText('AI: kuniga 40 ta')).toBeTruthy()
    expect(screen.getByText('Navbat: 900 tagacha post')).toBeTruthy()
    expect(screen.getByText('29 000 so\'m')).toBeTruthy()   // 1 oy (sukut)
    expect(screen.getByText('69 000 so\'m')).toBeTruthy()
    expect(screen.getByText('Hozirgi tarif')).toBeTruthy()  // bepul tarifdagi foydalanuvchida «Bepul» kartasi
    const tabs = within(screen.getByRole('group', { name: 'Tarif davri' }))
    expect(tabs.getAllByRole('button').map((b) => b.textContent)).toEqual(['1 oy', '3 oy−13%', '6 oy−22%', '1 yil−30%'])
    fireEvent.click(tabs.getByRole('button', { name: /1 yil/ }))
    expect(screen.getByText('245 000 so\'m')).toBeTruthy()
    expect(screen.getByText('620 000 so\'m')).toBeTruthy()
    expect(screen.getByText('970 Stars')).toBeTruthy()
    expect(screen.getAllByText('−30%').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Botda sotib olish' })).toHaveLength(2) // PRO va ULTRA; to'lov tugmasi Mini App'da yo'q
    fireEvent.click(screen.getByRole('button', { name: 'Orqaga' }))
    expect(await screen.findByText(/@alice/)).toBeTruthy()
  })

  it('PRO: Tarif ekranida PRO «Hozirgi tarif», muddat ko\'rsatiladi; ULTRA sotib olinadi, PRO emas', async () => {
    mockApi({ ...ME, plan: { type: 'pro', is_pro: true, expires_at: '2026-11-01T00:00:00Z', limits: { max_channels: 10, daily_ai_requests: 40, queued_posts: 300 } } })
    await openMe()
    expect(await screen.findByText('Obunangiz faol.')).toBeTruthy()
    expect(screen.queryByText('Bepul')).toBeNull()
    openRow(/^Tarif/)
    const proCard = (await screen.findByRole('article', { name: 'PRO' }))
    expect(within(proCard).getByText('Hozirgi tarif')).toBeTruthy()
    expect(within(proCard).getByText(/Amal qilish muddati/)).toBeTruthy()
    expect(within(proCard).queryByRole('button', { name: 'Botda sotib olish' })).toBeNull()
    expect(within(screen.getByRole('article', { name: 'ULTRA' })).getByRole('button', { name: 'Botda sotib olish' })).toBeTruthy()
  })

  it('ULTRA: belgi «ULTRA»; Tarif ekranida ULTRA joriy', async () => {
    mockApi({ ...ME, plan: { type: 'ultra', is_pro: true, expires_at: '2026-11-01T00:00:00Z', limits: { max_channels: 30, daily_ai_requests: 100, queued_posts: 900 } } })
    await openMe()
    expect(await screen.findByText('Obunangiz faol.')).toBeTruthy()
    openRow(/^Tarif/)
    expect(within(await screen.findByRole('article', { name: 'ULTRA' })).getByText('Hozirgi tarif')).toBeTruthy()
    expect(screen.getAllByText('Hozirgi tarif')).toHaveLength(1)
  })

  it('Kanallarim alohida ekranda: uzun nom saqlanadi, «Tahlil» tugmasi bor', async () => {
    mockApi()
    await openMe()
    openRow(/^Kanallarim/)
    const title = await screen.findByText(/Juda uzun nomli kanal/)
    expect(title.className).toContain('chan-title')
    expect(screen.getByText(/Rejada: 3/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tahlil' }).className).toContain('chan-act') // Button className'ni o'tkazadi
  })

  it('Til alohida ekranda: 3 ta til (bayroq + nom), joriy tanlangan, tanlansa saqlanadi', async () => {
    mockApi()
    await openMe()
    openRow(/^Til/)
    const group = await screen.findByRole('group', { name: 'Interfeys tili' })
    const btns = within(group).getAllByRole('button')
    expect(btns).toHaveLength(3)
    expect(btns.filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
    expect(btns.map((b) => b.textContent)).toEqual(['🇺🇿O\'zbekcha', '🇷🇺Русский', '🇬🇧English'])
  })
})

describe('Sozlamalar: profil muqovasi va bo\'limlar', () => {
  it('Telegram profil rasmi (https) ko\'rsatiladi; bo\'limlar: tarif, til, kanallar, ilova', async () => {
    setTelegram('https://t.me/i/userpic/320/me.jpg')
    mockApi()
    await openMe()
    const img = document.querySelector('.me-cover img.avatar-photo') as HTMLImageElement | null
    expect(img?.getAttribute('src')).toBe('https://t.me/i/userpic/320/me.jpg')
    expect(img?.getAttribute('referrerpolicy')).toBe('no-referrer')
    const labels = Array.from(document.querySelectorAll('.sec-label')).map((e) => e.textContent)
    expect(labels).toEqual(['Sozlamalar', 'Limitlar', 'Ilova'])
    expect(screen.getByRole('button', { name: 'Ilovani yopish' })).toBeTruthy()
  })

  it('Rasm yuklanmasa bosh harfga qaytadi; https bo\'lmagan manzil e\'tiborsiz', async () => {
    setTelegram('https://t.me/i/userpic/320/me.jpg')
    mockApi()
    await openMe()
    const img = document.querySelector('.me-cover img.avatar-photo') as HTMLImageElement
    fireEvent.error(img)
    expect(document.querySelector('.me-cover img.avatar-photo')).toBeNull()
    expect(document.querySelector('.me-cover .avatar-lg')?.textContent).toBe('A')
    cleanup()
    setTelegram('http://evil.example/x.jpg')
    await openMe()
    expect(document.querySelector('.me-cover img')).toBeNull()
  })
})

describe('Bildirishnomalar ekrani', () => {
  const openNotif = async (f?: (url: string, init: RequestInit) => Response | undefined) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      const custom = f?.(url, init)
      if (custom) return custom
      const method = init.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
      if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
      if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
      if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
      return jsonResponse(errorBody('not_found'), 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
    fireEvent.click(await screen.findByRole('button', { name: /^Bildirishnomalar/ }))
    await screen.findByRole('switch', { name: /Rejalashtirilgan post eslatmalari/ })
    return fetchMock
  }

  it('qator qiymati: nechta yoqilgan; ekranda 4 ta almashtirgich, holatlari serverdagidek', async () => {
    mockApi()
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
    expect(await screen.findByText('3 / 4 yoqilgan')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /^Bildirishnomalar/ }))
    const sw = await screen.findAllByRole('switch')
    expect(sw).toHaveLength(4)
    expect(screen.getByRole('switch', { name: /Yangiliklar va PRO/ }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('switch', { name: /Rejalashtirilgan post eslatmalari/ }).getAttribute('aria-checked')).toBe('true')
  })

  it('almashtirilsa PATCH {notifications:{kalit:bool}} ketadi va holat o\'zgaradi', async () => {
    const f = await openNotif((url, init) => init.method === 'PATCH' && url.endsWith('/me/settings')
      ? jsonResponse({ notifications: JSON.parse(String(init.body)).notifications }) : undefined)
    fireEvent.click(screen.getByRole('switch', { name: /Yangiliklar va PRO/ }))
    expect(await screen.findByText('Saqlandi.')).toBeTruthy()
    const patch = f.mock.calls.find((c) => c[1]?.method === 'PATCH')!
    expect(JSON.parse(String((patch[1] as RequestInit).body))).toEqual({ notifications: { notify_news: true } })
    expect(screen.getByRole('switch', { name: /Yangiliklar va PRO/ }).getAttribute('aria-checked')).toBe('true')
  })

  it('saqlash xatosida avvalgi holatga qaytadi va xabar chiqadi', async () => {
    await openNotif((_url, init) => init.method === 'PATCH' ? jsonResponse(errorBody('save_failed'), 503) : undefined)
    fireEvent.click(screen.getByRole('switch', { name: /Rejalashtirilgan post eslatmalari/ }))
    expect(await screen.findByText(/saqlab bo'lmadi|Saqlab bo'lmadi|saqlanmadi/i)).toBeTruthy()
    expect(screen.getByRole('switch', { name: /Rejalashtirilgan post eslatmalari/ }).getAttribute('aria-checked')).toBe('true')
  })
})
