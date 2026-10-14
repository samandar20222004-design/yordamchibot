import { describe, expect, it, vi } from 'vitest'
import { ApiClientError, createApiClient } from './client'
import { ME, PAGE, errorBody, jsonResponse } from '../test/helpers'

const noSleep = () => Promise.resolve()

function make(fetchImpl: typeof fetch, extra: Record<string, unknown> = {}) {
  return createApiClient({
    getInitData: () => 'auth_date=1&hash=abc',
    language: () => 'ru',
    fetchImpl,
    baseUrl: '/api/v1',
    sleep: noSleep,
    timeoutMs: 50,
    ...extra,
  })
}

async function codeOf(p: Promise<unknown>): Promise<string> {
  try {
    await p
    return 'OK'
  } catch (e) {
    return e instanceof ApiClientError ? e.code : 'other'
  }
}

describe('api client', () => {
  it('Authorization: tma <initData> yuboradi, user_id yubormaydi', async () => {
    const f = vi.fn(async () => jsonResponse(ME))
    const me = await make(f as unknown as typeof fetch).me()
    expect(me.user.id).toBe(4242)
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/me')
    expect((init.headers as Record<string, string>).Authorization).toBe('tma auth_date=1&hash=abc')
    expect((init.headers as Record<string, string>)['Accept-Language']).toBe('ru')
    expect(init.method).toBe('GET')
    expect(url).not.toMatch(/user_id/)
  })

  it('initData yo\'q bo\'lsa so\'rov yuborilmaydi (no_telegram)', async () => {
    const f = vi.fn()
    const c = createApiClient({ getInitData: () => '', fetchImpl: f as unknown as typeof fetch, sleep: noSleep })
    expect(await codeOf(c.me())).toBe('no_telegram')
    expect(f).not.toHaveBeenCalled()
  })

  it('pagination parametrlari', async () => {
    const f = vi.fn(async () => jsonResponse(PAGE))
    await make(f as unknown as typeof fetch).scheduledPosts(20, 40)
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/scheduled-posts?limit=20&offset=40')
  })

  it('server xato kodini xaritalaydi (auth_expired) va qayta urinmaydi', async () => {
    const f = vi.fn(async () => jsonResponse(errorBody('auth_expired'), 401))
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('auth_expired')
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('noma\'lum xato kodi -> internal_error', async () => {
    const f = vi.fn(async () => jsonResponse(errorBody('weird_code'), 400))
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('internal_error')
  })

  it('xato tanasi JSON bo\'lmasa ham tushunarli xato', async () => {
    const f = vi.fn(async () => new Response('<html>oops</html>', { status: 502 }))
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('internal_error')
  })

  it('503 da bir marta qayta uriladi va muvaffaqiyatli bo\'lsa qaytadi', async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(jsonResponse(errorBody('service_unavailable'), 503))
      .mockResolvedValueOnce(jsonResponse(ME))
    const me = await make(f as unknown as typeof fetch).me()
    expect(me.user.name).toBe('Alice')
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('503 ketma-ket: faqat 1 ta qayta urinish (jami 2)', async () => {
    const f = vi.fn(async () => jsonResponse(errorBody('service_unavailable', 'r', 5), 503, { 'Retry-After': '5' }))
    const c = make(f as unknown as typeof fetch)
    let err: ApiClientError | null = null
    try { await c.me() } catch (e) { err = e as ApiClientError }
    expect(f).toHaveBeenCalledTimes(2)
    expect(err?.code).toBe('service_unavailable')
    expect(err?.requestId).toBe('r')
    expect(err?.retryAfter).toBe(5)
  })

  it.each([[401, 'unauthorized'], [403, 'not_registered'], [429, 'rate_limited'], [400, 'bad_request']])(
    '%i qayta urinilmaydi', async (status, code) => {
      const f = vi.fn(async () => jsonResponse(errorBody(code), status))
      expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe(code)
      expect(f).toHaveBeenCalledTimes(1)
    })

  it('tarmoq xatosi: 1 marta qayta uriladi, keyin network', async () => {
    const f = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('network')
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('timeout: so\'rov bekor qilinadi va timeout kodi', async () => {
    const f = vi.fn((_u: string, init: RequestInit) => new Promise<Response>((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    }))
    expect(await codeOf(make(f as unknown as typeof fetch, { timeoutMs: 20 }).me())).toBe('timeout')
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('chaqiruvchi bekor qilsa qayta urinilmaydi', async () => {
    const ctl = new AbortController()
    const f = vi.fn((_u: string, init: RequestInit) => new Promise<Response>((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    }))
    const p = make(f as unknown as typeof fetch, { timeoutMs: 5000 }).me(ctl.signal)
    ctl.abort()
    expect(await codeOf(p)).toBe('other')
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('noto\'g\'ri shakl -> bad_response (qayta urinilmaydi)', async () => {
    const f = vi.fn(async () => jsonResponse({ user: 'x' }))
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('bad_response')
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('200 lekin JSON emas -> bad_response', async () => {
    const f = vi.fn(async () => new Response('nope', { status: 200 }))
    expect(await codeOf(make(f as unknown as typeof fetch).me())).toBe('bad_response')
  })

  describe('yozuv so\'rovlari', () => {
    const POSTED = { post: { ...PAGE.items[0], id: 5 }, created: true, delivery: 'scheduled' }

    it('POST: JSON tana + Content-Type, user_id yuborilmaydi', async () => {
      const f = vi.fn(async () => jsonResponse(POSTED, 201))
      const out = await make(f as unknown as typeof fetch).createPost({ channel_id: '-1001', text: 'Salom', send_now: true })
      expect(out.created).toBe(true)
      const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
      expect(url).toBe('/api/v1/posts')
      expect(init.method).toBe('POST')
      expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
      expect(JSON.parse(String(init.body))).toEqual({ channel_id: '-1001', text: 'Salom', send_now: true })
      expect(String(init.body)).not.toMatch(/user_id/)
    })

    it('GET so\'rovlarda Content-Type va tana yo\'q', async () => {
      const f = vi.fn(async () => jsonResponse(ME))
      await make(f as unknown as typeof fetch).me()
      const init = (f.mock.calls[0] as unknown as [string, RequestInit])[1]
      expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
      expect(init.body).toBeUndefined()
    })

    it.each([503, 502, 504])('yozuv %i da QAYTA URINILMAYDI (GET uchun urinish bor)', async (status) => {
      const f = vi.fn(async () => jsonResponse(errorBody('service_unavailable'), status))
      expect(await codeOf(make(f as unknown as typeof fetch).createPost({ channel_id: '-1', text: 'x', send_now: true }))).toBe('service_unavailable')
      expect(f).toHaveBeenCalledTimes(1)
    })

    it('tarmoq xatosi va timeout yozuvda qayta urinilmaydi', async () => {
      const net = vi.fn(async () => { throw new TypeError('x') })
      expect(await codeOf(make(net as unknown as typeof fetch).cancelPost(1))).toBe('network')
      expect(net).toHaveBeenCalledTimes(1)
      const slow = vi.fn((_u: string, init: RequestInit) => new Promise<Response>((_r, rej) => {
        init.signal?.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))
      }))
      expect(await codeOf(make(slow as unknown as typeof fetch).setLanguage('ru'))).toBe('timeout')
      expect(slow).toHaveBeenCalledTimes(1)
    })

    it('forma xatosi: server ko\'rsatgan maydon nomi ApiClientError.field da', async () => {
      const f = vi.fn(async () => jsonResponse(errorBody('invalid_input', 'r1', null, 'scheduled_at'), 422))
      try {
        await make(f as unknown as typeof fetch).createPost({ channel_id: '-1', text: 'x', scheduled_at: 'bad' })
        expect.unreachable()
      } catch (e) {
        expect(e).toBeInstanceOf(ApiClientError)
        expect((e as ApiClientError).field).toBe('scheduled_at')
        expect((e as ApiClientError).code).toBe('invalid_input')
      }
    })

    it('noma\'lum xato kodi internal_error ga tushadi; yaroqsiz javob shakli bad_response', async () => {
      const unknown = vi.fn(async () => jsonResponse(errorBody('totally_new'), 418))
      expect(await codeOf(make(unknown as unknown as typeof fetch).cancelPost(1))).toBe('internal_error')
      const junk = vi.fn(async () => jsonResponse({ nothing: true }, 200))
      expect(await codeOf(make(junk as unknown as typeof fetch).createPost({ channel_id: '-1', text: 'x', send_now: true }))).toBe('bad_response')
      const lang = vi.fn(async () => jsonResponse({ language: 'xx' }))
      expect(await codeOf(make(lang as unknown as typeof fetch).setLanguage('ru'))).toBe('bad_response')
    })

    it('AI: bo\'sh/yaroqsiz uslub javobi rad etiladi', async () => {
      const ok = vi.fn(async () => jsonResponse({ text: 'Matn', style: 'sales' }))
      expect((await make(ok as unknown as typeof fetch).generate('g', 'sales')).text).toBe('Matn')
      const empty = vi.fn(async () => jsonResponse({ text: '  ', style: 'sales' }))
      expect(await codeOf(make(empty as unknown as typeof fetch).generate('g', 'sales'))).toBe('bad_response')
      const bad = vi.fn(async () => jsonResponse({ text: 'x', style: 'hack' }))
      expect(await codeOf(make(bad as unknown as typeof fetch).generate('g', 'sales'))).toBe('bad_response')
    })

    it('id URL ichida kodlanadi; history filtri so\'rovga qo\'shiladi', async () => {
      const f = vi.fn(async () => jsonResponse({ ...PAGE }))
      await make(f as unknown as typeof fetch).scheduledPosts(20, 0, undefined, 'history')
      expect(String((f.mock.calls[0] as unknown[])[0])).toContain('status=history')
    })
  })
})
