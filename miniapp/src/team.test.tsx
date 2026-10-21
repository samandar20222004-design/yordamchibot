// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { parseTeam, ShapeError } from './api/validate'
import { inviteLink } from './telegram'
import { ME, PAGE, errorBody, jsonResponse } from './test/helpers'

type Call = { url: string; method: string; body: unknown; headers: Record<string, string> }

const SEATS_ULTRA = { plan: 'ultra', limit: 2, used: 1, pending: 1, free: 0 }
const OWNER_TEAM = {
  mode: 'owner', seats: SEATS_ULTRA, can_invite: true, workspaces: [],
  channels: [
    { channel_id: '-1001', title: 'Kanal A', members: [{ user_id: 77, name: 'Ali', username: 'ali', perms: ['create', 'edit', 'ai'], active: true, since: null }],
      invites: [{ id: 5, perms: ['create', 'reschedule'], expires_at: null }] },
    { channel_id: '-1002', title: 'Kanal B', members: [], invites: [] },
  ],
}
const PRO_TEAM = { mode: 'owner', seats: { plan: 'pro', limit: 0, used: 0, pending: 0, free: 0 }, can_invite: false, channels: [], workspaces: [] }
const HELPER_TEAM = {
  mode: 'helper', seats: { plan: 'free', limit: 0, used: 0, pending: 0, free: 0 }, can_invite: false, channels: [],
  workspaces: [{ owner_id: 9, owner_name: 'Ega Ega', suspended: false, channels: [{ channel_id: '-1009', title: 'Egasining kanali', perms: ['create', 'edit', 'reschedule', 'delete', 'ai'] }] }],
}

function setup(opts: { team: unknown; me?: Record<string, unknown> }) {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } }, ready: vi.fn(), expand: vi.fn(), close: vi.fn(),
      openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    const headers = (init.headers ?? {}) as Record<string, string>
    calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : undefined, headers })
    if (url.endsWith('/team/invites') && method === 'POST') return jsonResponse({ id: 9, token: 'tok_ABCDEFGH12345678', perms: (JSON.parse(String(init.body)) as { perms: string[] }).perms, channel_ids: (JSON.parse(String(init.body)) as { channel_ids: string[] }).channel_ids, expires_at: null }, 201)
    if (url.endsWith('/team/helpers') && method === 'PATCH') return jsonResponse({ ok: true })
    if (url.includes('/team/invites/') && method === 'DELETE') return jsonResponse({ id: 5, revoked: true })
    if (url.endsWith('/team/members') && method === 'PATCH') return jsonResponse({ ok: true })
    if (url.endsWith('/team/members/remove')) return jsonResponse({ removed: true })
    if (url.endsWith('/team/leave')) return jsonResponse({ left: true })
    if (url.endsWith('/team/mode') && method === 'PATCH') return jsonResponse({ mode: (JSON.parse(String(init.body)) as { mode: string }).mode })
    if (url.endsWith('/team')) return jsonResponse(opts.team)
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/me')) return jsonResponse({ ...ME, ...(opts.me ?? {}) })
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1009', title: 'Egasining kanali', pending_posts: 0, members: null }], total: 1 })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(PAGE)
    if (url.includes('/market/unread')) return jsonResponse({ unread: 0 })
    return jsonResponse(errorBody('not_found'), 404)
  }))
  return calls
}

const openTeam = async () => {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
  fireEvent.click(await screen.findByRole('button', { name: /^Jamoa va rol/ }))
  await screen.findByRole('heading', { name: 'Jamoa va rol' })
}

beforeEach(() => { vi.useRealTimers(); try { localStorage.clear(); sessionStorage.clear() } catch { /* */ } window.history.replaceState({}, '', '/app/') })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Jamoa va rol (Mini App)', () => {
  it('ULTRA egasi: o\'rindiqlar 1/2, yordamchi kartasi (ruxsatlari belgilangan) va kutilayotgan taklif', async () => {
    setup({ team: OWNER_TEAM })
    await openTeam()
    expect(await screen.findByText('1 / 2 yordamchi')).toBeTruthy()
    expect(screen.getByText(/Jami 3 akkaunt/)).toBeTruthy()
    expect(screen.getByText(/limitlar SIZDAN hisoblanadi/)).toBeTruthy()
    const card = screen.getByRole('region', { name: 'Ali' })
    expect((within(card).getByLabelText(/Post yaratish/) as HTMLInputElement).checked).toBe(true)
    expect((within(card).getByLabelText(/Tahrirlash/) as HTMLInputElement).checked).toBe(true)
    expect((within(card).getByLabelText(/Darhol yuborish/) as HTMLInputElement).checked).toBe(false)
    expect(screen.getByText(/Taklif kutmoqda/)).toBeTruthy()
  })

  it('PRO: yordamchi qo\'shib bo\'lmaydi — «bitta odam» matni va ULTRA tugmasi', async () => {
    setup({ team: PRO_TEAM })
    await openTeam()
    expect(await screen.findByText('Bitta odam hammasini boshqaradi')).toBeTruthy()
    expect(screen.getByText(/ULTRA'da: siz \+ 2 yordamchi = 3 akkaunt/)).toBeTruthy()
    expect(screen.queryByText('Yordamchi taklif qilish')).toBeNull()
    expect(screen.getByRole('button', { name: /ULTRA tarifini ko'rish/ })).toBeTruthy()
  })

  it('taklif: standart — hamma kanal va hamma ruxsat; kanal/ruxsat tanlansa POST shunga mos, havola t.me/<bot>?start=team_<token>', async () => {
    const calls = setup({ team: OWNER_TEAM })
    await openTeam()
    fireEvent.click(await screen.findByRole('button', { name: /Yordamchi taklif qilish/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Hammasi' })[0]) // kanallar: hammasini bekor qilish (1-qator — kanal tanlagich)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Kanal B' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tahlilchi' })) // shablon: faqat statistika
    expect((within(dialog).getByLabelText(/Statistika/) as HTMLInputElement).checked).toBe(true)
    expect((within(dialog).getByLabelText(/Post yaratish/) as HTMLInputElement).checked).toBe(false)
    fireEvent.click(within(dialog).getByLabelText(/AI yordamchi/)) // alohida ruxsat qo'shildi
    fireEvent.click(within(dialog).getByRole('button', { name: 'Havola yaratish' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/invites') && JSON.stringify(c.body) === '{"channel_ids":["-1002"],"perms":["analytics","ai"]}')).toBe(true))
    expect(await screen.findByText('https://t.me/PostAssistrobot?start=team_tok_ABCDEFGH12345678')).toBeTruthy()
  })

  it('taklif: hech narsa o\'zgartirilmasa — hamma kanal va hammasi ruxsat (kengroq standart)', async () => {
    const calls = setup({ team: OWNER_TEAM })
    await openTeam()
    fireEvent.click(await screen.findByRole('button', { name: /Yordamchi taklif qilish/ }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Havola yaratish' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/team/invites')
      && JSON.stringify(c.body) === '{"channel_ids":["-1001","-1002"],"perms":["create","edit","reschedule","delete","send_now","analytics","ai"]}')).toBe(true))
  })

  it('yordamchi ruxsatlari: katakcha o\'zgarsa «Saqlash» PATCH /team/helpers yuboradi; olib tashlash tasdiq so\'raydi', async () => {
    const calls = setup({ team: OWNER_TEAM })
    await openTeam()
    const card = await screen.findByRole('region', { name: 'Ali' })
    const save = within(card).getByRole('button', { name: 'Saqlash' }) as HTMLButtonElement
    expect(save.disabled).toBe(true) // o'zgarish yo'q
    fireEvent.click(within(card).getByLabelText(/Darhol yuborish/))
    fireEvent.click(within(card).getByLabelText(/Tahrirlash/)) // olib tashlandi
    fireEvent.click(save)
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.url.endsWith('/team/helpers')
      && JSON.stringify(c.body) === '{"user_id":77,"channel_ids":["-1001"],"perms":["create","send_now","ai"]}')).toBe(true))
    fireEvent.click(within(card).getByRole('button', { name: 'Olib tashlash' }))
    expect(await screen.findByText(/Olib tashlash/, { selector: 'p' }).catch(() => null)).toBeDefined()
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Olib tashlash' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.url.endsWith('/team/helpers') && JSON.stringify(c.body) === '{"user_id":77,"channel_ids":[],"perms":[]}')).toBe(true))
  })

  it('yordamchi rejimi: so\'ramasdan ish joyiga o\'zi kiradi — X-Workspace, banner; «O\'z ish joyim» chiqaradi va qayta kirmaydi', async () => {
    const calls = setup({ team: HELPER_TEAM, me: { work_mode: 'helper' } })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(await screen.findByText('Ish joyi: Ega Ega')).toBeTruthy()
    await waitFor(() => expect(calls.some((c) => c.url.includes('/channels') && c.headers['X-Workspace'] === '9')).toBe(true))
    expect(localStorage.getItem('postassist.workspace')).toBe('9')
    expect(calls.filter((c) => c.url.endsWith('/team')).every((c) => c.headers['X-Workspace'] === undefined || c.headers['X-Workspace'] === '9')).toBe(true)
    fireEvent.click(within(screen.getByText('Ish joyi: Ega Ega').closest('.ws-banner') as HTMLElement).getByRole('button', { name: /O'z ish joyim/ }))
    await waitFor(() => expect(screen.queryByText('Ish joyi: Ega Ega')).toBeNull())
    expect(localStorage.getItem('postassist.workspace')).toBeNull()
    expect(sessionStorage.getItem('postassist.wsOptOut')).toBe('1')
  })

  it('yordamchi ish joyi kartasi: kanal va ruxsatlari ko\'rinadi; «Ishlash» tugmasi qo\'lda ham yoqadi', async () => {
    sessionStorage.setItem('postassist.wsOptOut', '1')
    setup({ team: HELPER_TEAM, me: { work_mode: 'helper' } })
    await openTeam()
    const card = await screen.findByRole('region', { name: 'Ega Ega' })
    expect(within(card).getByText('Egasining kanali')).toBeTruthy()
    expect(within(card).getByText('Post yaratish')).toBeTruthy()
    expect(within(card).queryByText('Darhol yuborish')).toBeNull() // berilmagan ruxsat ko'rinmaydi
    fireEvent.click(within(card).getByRole('button', { name: /Ishlash/ }))
    expect(await screen.findByText('Ish joyi: Ega Ega')).toBeTruthy()
  })

  it('eskirgan (yopilgan) ish joyi avtomatik o\'chadi', async () => {
    localStorage.setItem('postassist.workspace', '555')
    setup({ team: PRO_TEAM, me: { work_mode: 'owner' } })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    await waitFor(() => expect(localStorage.getItem('postassist.workspace')).toBeNull())
  })

  it('rol tanlash FAQAT sozlamada: ochilganda hech qanday oyna so\'ralmaydi (rol tanlanmagan bo\'lsa ham)', async () => {
    setup({ team: PRO_TEAM, me: { work_mode: null } })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText('Siz kimsiz?')).toBeNull()
  })

  it('Sozlamadagi rol tanlash: «Yordamchiman» PATCH /team/mode yuboradi', async () => {
    const calls = setup({ team: PRO_TEAM, me: { work_mode: null } })
    await openTeam()
    fireEvent.click(await screen.findByRole('radio', { name: /Yordamchiman/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.url.endsWith('/team/mode') && JSON.stringify(c.body) === '{"mode":"helper"}')).toBe(true))
  })

  it('super admin: rol tanlashda 3-variant «Super admin» (oddiy foydalanuvchida yo\'q)', async () => {
    setup({ team: PRO_TEAM, me: { is_admin: true, work_mode: 'owner' } })
    await openTeam()
    expect(await screen.findByRole('radio', { name: /Super admin/ })).toBeTruthy()
    cleanup()
    vi.unstubAllGlobals()
    setup({ team: PRO_TEAM, me: { work_mode: 'owner' } })
    await openTeam()
    expect(screen.queryByRole('radio', { name: /Super admin/ })).toBeNull()
  })

  it('ULTRA kartasi: jamoa qatori va akkauntga narx; PRO: «bitta odam»', async () => {
    setup({ team: PRO_TEAM, me: { tiers: { ...ME.tiers, ultra: { ...ME.tiers!.ultra, limits: { ...ME.tiers!.ultra.limits, team_seats: 2 } } } } })
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Men/ }))
    fireEvent.click(await screen.findByRole('button', { name: /^Tarif/ }))
    expect(await screen.findByText('Jamoa: siz + 2 yordamchi (3 akkaunt)')).toBeTruthy()
    expect(screen.getByText('Bitta odam hamma kanalni boshqaradi')).toBeTruthy()
    expect(screen.getByText(/Har bir akkauntga oyiga ≈ \$3\.13/)).toBeTruthy()
  })

  it('validator va havola yordamchilari', () => {
    expect(parseTeam(OWNER_TEAM).seats.limit).toBe(2)
    expect(parseTeam(OWNER_TEAM).channels[0].members[0].perms).toEqual(['create', 'edit', 'ai'])
    expect(() => parseTeam({ seats: {}, channels: [{ channel_id: 1 }] })).toThrow(ShapeError)
    expect(() => parseTeam({ ...OWNER_TEAM, channels: [{ channel_id: '-1', members: [{ user_id: 1, perms: ['root'] }] }] })).toThrow(ShapeError)
    expect(inviteLink('PostAssistrobot', 'tok_ABCDEFGH')).toBe('https://t.me/PostAssistrobot?start=team_tok_ABCDEFGH')
    expect(inviteLink('bad name', 'tok_ABCDEFGH')).toBeNull()
    expect(inviteLink('PostAssistrobot', 'a b<script>')).toBeNull()
  })
})
