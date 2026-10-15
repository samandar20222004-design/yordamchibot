// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ME, PAGE, errorBody, jsonResponse, setEditor, editorValue, selectText } from './test/helpers'

function setTelegram() {
  ;(window as unknown as { Telegram: unknown }).Telegram = {
    WebApp: { initData: 'auth_date=1&hash=a', colorScheme: 'light', initDataUnsafe: { user: { language_code: 'uz' } },
      ready: vi.fn(), expand: vi.fn(), close: vi.fn(), openTelegramLink: vi.fn(), onEvent: vi.fn(), offEvent: vi.fn() },
  }
}

const ONCE = { ...PAGE.items[0], id: 1, has_media: true, post_type: 'photo', text: 'Matn <b>qalin</b>', button_text: 'Ochish', button_url: 'https://example.org/go' }
const DAILY2 = { ...PAGE.items[1], id: 2, has_media: false, post_type: 'text', recurrence: 'twice', recurrence_time: '09:00', recurrence_time2: '18:00', recurrence_day: 1080, text: 'Kunlik' }
const LIST = { ...PAGE, items: [{ ...PAGE.items[0], has_media: true, post_type: 'photo' }, { ...DAILY2, preview: 'Kunlik', text: undefined }], total: 2 }

function mockApi(onRequest: (url: string, init: RequestInit) => Response | undefined = () => undefined) {
  let current: Record<string, unknown> = { ...ONCE }
  const f = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const custom = onRequest(url, init)
    if (custom) return custom
    const method = init.method ?? 'GET'
    if (method === 'GET' && /\/posts\/\d+\/media$/.test(url)) return new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { 'Content-Type': 'image/jpeg' } })
    if (method === 'GET' && /\/posts\/2$/.test(url)) return jsonResponse({ post: DAILY2 })
    if (method === 'GET' && /\/posts\/1$/.test(url)) return jsonResponse({ post: current })
    if (method === 'PATCH') return jsonResponse({ post: { ...current, ...JSON.parse(String(init.body)) } })
    if (method === 'POST' && /\/posts\/1\/media$/.test(url)) { current = { ...current, post_type: 'video' }; return jsonResponse({ post: current }) }
    if (method === 'DELETE' && /\/posts\/1\/media$/.test(url)) { current = { ...current, has_media: false, post_type: 'text' }; return jsonResponse({ post: current }) }
    if (method === 'GET' && url.includes('/me')) return jsonResponse(ME)
    if (method === 'GET' && url.includes('/channels')) return jsonResponse({ items: [{ id: '-1001', title: 'Kanal A' }], total: 1 })
    if (method === 'GET' && url.endsWith('/draft')) return jsonResponse({ draft: null })
    if (method === 'GET' && url.includes('/scheduled-posts')) return jsonResponse(LIST)
    return jsonResponse(errorBody('not_found'), 404)
  })
  vi.stubGlobal('fetch', f)
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:thumb'), revokeObjectURL: vi.fn() }))
  return f
}

const calls = (f: ReturnType<typeof mockApi>, method: string, re: RegExp) =>
  f.mock.calls.filter((c) => (c[1]?.method ?? 'GET') === method && re.test(String(c[0])))
const body = (c: unknown[]) => JSON.parse(String((c[1] as RequestInit).body))

async function openEdit(index: number) {
  render(<App />)
  await screen.findByText('Salom, Alice!')
  fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Reja/ }))
  const buttons = await screen.findAllByRole('button', { name: 'Tahrirlash' })
  fireEvent.click(buttons[index]!)
  return screen.findByRole('dialog')
}

beforeEach(() => { vi.useRealTimers(); setTelegram() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as unknown as { Telegram?: unknown }).Telegram })

describe('Reja ro\'yxati: post rasmi', () => {
  it('rasmli postda kichik rasm (blob) ko\'rinadi, rasmsiz postda yo\'q', async () => {
    const f = mockApi()
    render(<App />)
    await screen.findByText('Salom, Alice!')
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^Reja/ }))
    await screen.findAllByRole('button', { name: 'Tahrirlash' })
    await waitFor(() => expect(document.querySelector('.thumb img')).not.toBeNull())
    expect(document.querySelectorAll('.thumb').length).toBe(1)
    expect(calls(f, 'GET', /\/posts\/1\/media$/).length).toBe(1)
  })
})

describe('To\'liq tahrirlash oynasi', () => {
  it('matn, format paneli, tugma, rasm va vaqt bir joyda; o\'zgarish bo\'lmasa so\'rov yo\'q', async () => {
    const f = mockApi()
    const dialog = await openEdit(0)
    expect(editorValue(await within(dialog).findByLabelText('Post matni'))).toBe('Matn <b>qalin</b>')
    expect(within(dialog).getByRole('toolbar')).toBeTruthy()
    expect((within(dialog).getByLabelText('Tugma matni') as HTMLInputElement).value).toBe('Ochish')
    expect((within(dialog).getByLabelText('Tugma havolasi (https://…)') as HTMLInputElement).value).toBe('https://example.org/go')
    expect(within(dialog).getByRole('button', { name: 'Almashtirish' })).toBeTruthy()
    expect(within(dialog).getByLabelText('Sana va vaqt')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls(f, 'PATCH', /\/posts\//)).toHaveLength(0)
  })

  it('faqat o\'zgargan maydonlar yuboriladi (matn + tugmani olib tashlash)', async () => {
    const f = mockApi()
    const dialog = await openEdit(0)
    const text = await within(dialog).findByLabelText('Post matni') as HTMLElement
    setEditor(text, 'Yangi matn')
    fireEvent.change(within(dialog).getByLabelText('Tugma matni'), { target: { value: '' } })
    fireEvent.change(within(dialog).getByLabelText('Tugma havolasi (https://…)'), { target: { value: '' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    await waitFor(() => expect(calls(f, 'PATCH', /\/posts\/1$/)).toHaveLength(1))
    expect(body(calls(f, 'PATCH', /\/posts\/1$/)[0]!)).toEqual({ text: 'Yangi matn', button_text: '', button_url: '' })
  })

  it('format tugmasi bo\'sh teg qoldirmaydi: bo\'sh matnda hech narsa o\'zgarmaydi', async () => {
    mockApi()
    const dialog = await openEdit(0)
    const text = await within(dialog).findByLabelText('Post matni') as HTMLElement
    setEditor(text, '')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tagi chizilgan' }))
    expect(editorValue(text)).toBe('')
    setEditor(text, 'abc def')
    selectText(text, 4, 7)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Tagi chizilgan' }))
    await waitFor(() => expect(editorValue(text)).toBe('abc <u>def</u>'))
    expect(editorValue(text)).not.toContain('<u></u>')
  })

  it('yaroqsiz tugma (havolasiz matn) yuborilmaydi', async () => {
    const f = mockApi()
    const dialog = await openEdit(0)
    await within(dialog).findByLabelText('Post matni')
    fireEvent.change(within(dialog).getByLabelText('Tugma havolasi (https://…)'), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    expect(await within(dialog).findByText(/Tugma matni \(1–64 belgi\)/)).toBeTruthy()
    expect(calls(f, 'PATCH', /\/posts\//)).toHaveLength(0)
  })

  it('rasmni olib tashlash va fayl bilan almashtirish (ro\'yxat fonda yangilanadi, oyna ochiq)', async () => {
    const f = mockApi()
    const dialog = await openEdit(0)
    await within(dialog).findByLabelText('Post matni')
    const input = dialog.querySelector('input[type=file]') as HTMLInputElement
    const file = new File([new Uint8Array(50)], 'a.mp4', { type: 'video/mp4' })
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() => expect(calls(f, 'POST', /\/posts\/1\/media$/)).toHaveLength(1))
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Rasmni olib tashlash' }))
    await waitFor(() => expect(calls(f, 'DELETE', /\/posts\/1\/media$/)).toHaveLength(1))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Rasmni olib tashlash' })).toBeNull())
    expect(screen.getByText(/Postda rasm yoki video yo'q/)).toBeTruthy()
  })

  it('noma\'lum fayl turi serverga yuborilmaydi', async () => {
    const f = mockApi()
    const dialog = await openEdit(0)
    await within(dialog).findByLabelText('Post matni')
    fireEvent.change(dialog.querySelector('input[type=file]') as HTMLInputElement, { target: { files: [new File(['x'], 'a.pdf', { type: 'application/pdf' })] } })
    expect(await screen.findByText(/qo'llab-quvvatlanmaydi/)).toBeTruthy()
    expect(calls(f, 'POST', /\/media$/)).toHaveLength(0)
  })

  it('takrorlanuvchi (ikki vaqtli) post: ikkala vaqt tahrirlanadi, sana maydoni yo\'q', async () => {
    const f = mockApi()
    const dialog = await openEdit(1)
    await within(dialog).findByLabelText('Post matni')
    expect(within(dialog).queryByLabelText('Sana va vaqt')).toBeNull()
    expect((within(dialog).getByLabelText(/Chiqish vaqti/) as HTMLInputElement).value).toBe('09:00')
    const second = within(dialog).getByLabelText('Ikkinchi vaqt (kuniga 2 marta)', { selector: 'input[type=time]' }) as HTMLInputElement
    expect(second.value).toBe('18:00')
    fireEvent.change(within(dialog).getByLabelText(/Chiqish vaqti/), { target: { value: '08:30' } })
    fireEvent.change(second, { target: { value: '20:00' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    await waitFor(() => expect(calls(f, 'PATCH', /\/posts\/2$/)).toHaveLength(1))
    expect(body(calls(f, 'PATCH', /\/posts\/2$/)[0]!)).toEqual({ recurrence_time: '08:30', recurrence_time2: '20:00' })
  })

  it('ikki vaqt bir xil bo\'lsa rad etiladi; ikkinchi vaqtni olib tashlash = bitta vaqt', async () => {
    const f = mockApi()
    const dialog = await openEdit(1)
    await within(dialog).findByLabelText('Post matni')
    const second = within(dialog).getByLabelText('Ikkinchi vaqt (kuniga 2 marta)', { selector: 'input[type=time]' })
    fireEvent.change(second, { target: { value: '09:00' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    expect(await within(dialog).findByText(/Vaqtni to'g'ri kiriting/)).toBeTruthy()
    expect(calls(f, 'PATCH', /\/posts\//)).toHaveLength(0)
    fireEvent.click(within(dialog).getByRole('checkbox'))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Saqlash' }))
    await waitFor(() => expect(calls(f, 'PATCH', /\/posts\/2$/)).toHaveLength(1))
    expect(body(calls(f, 'PATCH', /\/posts\/2$/)[0]!)).toEqual({ recurrence_time: '09:00' })
  })
})
