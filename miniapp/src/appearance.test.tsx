// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { DEFAULT_APPEARANCE, applyAppearance, loadLocal, moveTab, sanitize, sanitizeTabs, save, toggleTab } from './appearance'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

function setup(cloud?: { get?: (key: string) => string | undefined }) {
  const setItem = vi.fn()
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } }, ready: vi.fn(), expand: vi.fn(), close: vi.fn(),
      openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn(), HapticFeedback: { impactOccurred: vi.fn(), selectionChanged: vi.fn(), notificationOccurred: vi.fn() },
      CloudStorage: { setItem, getItem: (key: string, cb: (e: unknown, v?: string) => void) => cb(null, cloud?.get?.(key)) } },
  }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/me')) return jsonResponse(ME)
    if (url.includes('/channels')) return jsonResponse({ items: [], total: 0 })
    if (url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    if (url.endsWith('/market/unread')) return jsonResponse({ unread: 0 })
    return jsonResponse(errorBody('not_found'), 404)
  }))
  return { setItem }
}

beforeEach(() => { window.localStorage.clear(); window.history.replaceState({}, '', '/app/') })
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram
  window.localStorage.clear()
  for (const k of ['accent', 'bg', 'density', 'radius', 'font', 'motion', 'theme']) delete document.documentElement.dataset[k]
})

describe('appearance: sof mantiq', () => {
  it('sanitize: noma\'lum/buzilgan qiymat standartga tushadi, to\'g\'ri qiymat saqlanadi', () => {
    expect(sanitize(null)).toEqual(DEFAULT_APPEARANCE)
    expect(sanitize('<script>')).toEqual(DEFAULT_APPEARANCE)
    const a = sanitize({ accent: 'violet', background: 'hack', theme: 'dark', density: 'compact', radius: 'x', font: 'large', motion: false, haptics: 'yes' })
    expect([a.accent, a.background, a.theme, a.density, a.radius, a.font, a.motion, a.haptics]).toEqual(['violet', 'auto', 'dark', 'compact', 'soft', 'large', false, true])
  })
  it('tablar: faqat ma\'lum, takrorsiz, «me» majburiy, kamida 2 ta; boshlang\'ich bo\'lim tabda bo\'lishi shart', () => {
    expect(sanitizeTabs(['market', 'evil', 'market', 'home'])).toEqual(['market', 'home', 'me'])
    expect(sanitizeTabs([])).toEqual(DEFAULT_APPEARANCE.tabs)
    expect(sanitizeTabs(['me'])).toEqual(['me', 'home'])
    expect(sanitize({ tabs: ['post', 'me'], start: 'market' }).start).toBe('post')
  })
  it('moveTab / toggleTab chegaralari', () => {
    const t = ['home', 'post', 'me'] as const
    expect(moveTab([...t], 'post', -1)).toEqual(['post', 'home', 'me'])
    expect(moveTab([...t], 'home', -1)).toEqual([...t])
    expect(toggleTab([...t], 'me')).toEqual([...t])
    expect(toggleTab(['home', 'me'], 'home')).toEqual(['home', 'me'])
    expect(toggleTab([...t], 'post')).toEqual(['home', 'me'])
    expect(toggleTab([...t], 'market')).toEqual(['home', 'post', 'me', 'market'])
  })
  it('applyAppearance <html data-*> ni qo\'yadi; mavzu avto = Telegram, aks holda tanlangan', () => {
    applyAppearance({ ...DEFAULT_APPEARANCE, accent: 'rose', background: 'ocean', density: 'compact', motion: false }, 'dark')
    const d = document.documentElement.dataset
    expect([d.accent, d.bg, d.density, d.motion, d.theme]).toEqual(['rose', 'ocean', 'compact', 'off', 'dark'])
    applyAppearance({ ...DEFAULT_APPEARANCE, theme: 'light' }, 'dark')
    expect(document.documentElement.dataset.theme).toBe('light')
  })
  it('save/loadLocal aylanishi; buzilgan JSON standartga', () => {
    save({ ...DEFAULT_APPEARANCE, accent: 'teal' })
    expect(loadLocal().accent).toBe('teal')
    window.localStorage.setItem('pa.appearance.v1', '{not json')
    expect(loadLocal()).toEqual(DEFAULT_APPEARANCE)
  })
})

describe('appearance: Men -> Ko\'rinish', () => {
  async function openLook() {
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(screen.getByRole('button', { name: 'Men' }))
    fireEvent.click(await screen.findByText("Ko'rinish"))
    return screen.findByRole('heading', { name: "Ko'rinish" })
  }

  it('rang tanlansa darhol qo\'llanadi va saqlanadi (mahalliy + Telegram bulut)', async () => {
    const { setItem } = setup()
    await openLook()
    fireEvent.click(screen.getByRole('button', { name: 'Binafsha' }))
    expect(document.documentElement.dataset.accent).toBe('violet')
    expect(loadLocal().accent).toBe('violet')
    expect(setItem).toHaveBeenCalled()
    expect(String(setItem.mock.calls.at(-1)?.[1])).toContain('violet')
  })

  it('fon, mavzu, zichlik, shrift va animatsiya sozlamalari <html> ga qo\'llanadi', async () => {
    setup()
    await openLook()
    fireEvent.click(screen.getByRole('button', { name: 'Okean' }))
    fireEvent.click(screen.getByRole('button', { name: "Qorong'u" }))
    fireEvent.click(screen.getByRole('button', { name: 'Ixcham' }))
    fireEvent.click(screen.getByRole('button', { name: 'Katta' }))
    fireEvent.click(screen.getByRole('switch', { name: /Animatsiyalar/ }))
    const d = document.documentElement.dataset
    expect([d.bg, d.theme, d.density, d.font, d.motion]).toEqual(['ocean', 'dark', 'compact', 'large', 'off'])
  })

  it('pastki panel: tabni yashirish va tartibini o\'zgartirish darhol ko\'rinadi; «Men» yashirilmaydi', async () => {
    setup()
    await openLook()
    fireEvent.click(screen.getByRole('button', { name: /Tabni ko'rsatish yoki yashirish: Reja/ }))
    const nav = screen.getByRole('navigation')
    expect(within(nav).queryByRole('button', { name: 'Reja' })).toBeNull()
    expect((screen.getByRole('button', { name: /Tabni ko'rsatish yoki yashirish: Men/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: /Pastga: Bosh/ }))
    const labels = within(nav).getAllByRole('button').map((b) => b.textContent)
    expect(labels.indexOf('Bosh')).toBeGreaterThan(labels.indexOf('Post'))
    fireEvent.click(screen.getByRole('button', { name: /Tabni ko'rsatish yoki yashirish: Reja/ })) // qayta qo'shish
    expect(within(nav).getByRole('button', { name: 'Reja' })).toBeTruthy()
  })

  it('bosh sahifa bo\'limlarini o\'chirish (Reklama birjasi banneri) va standartga qaytarish', async () => {
    setup()
    await openLook()
    fireEvent.click(screen.getByRole('switch', { name: /Reklama birjasi banneri/ }))
    expect(loadLocal().home.market).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Standartga qaytarish' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Standartga qaytarish' }))
    await waitFor(() => expect(loadLocal()).toEqual(DEFAULT_APPEARANCE))
  })

  it('saqlangan ko\'rinish qayta ochilganda qo\'llanadi: boshlang\'ich bo\'lim va yashirin banner', async () => {
    save({ ...DEFAULT_APPEARANCE, start: 'schedule', home: { ...DEFAULT_APPEARANCE.home, market: false } })
    setup()
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Reja' })).toBeTruthy()
  })

  it('boshqa qurilmada o\'zgartirilgan (yangiroq) bulutdagi sozlama olinadi; eskisi e\'tiborsiz', async () => {
    save({ ...DEFAULT_APPEARANCE, accent: 'blue' })
    const newer = JSON.stringify({ t: Date.now() + 60_000, v: { ...DEFAULT_APPEARANCE, accent: 'green' } })
    setup({ get: () => newer })
    render(<App />)
    await waitFor(() => expect(document.documentElement.dataset.accent).toBe('green'))
    cleanup()
    save({ ...DEFAULT_APPEARANCE, accent: 'rose' })
    const older = JSON.stringify({ t: 1, v: { ...DEFAULT_APPEARANCE, accent: 'red' } })
    setup({ get: () => older })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(document.documentElement.dataset.accent).toBe('rose')
  })
})
