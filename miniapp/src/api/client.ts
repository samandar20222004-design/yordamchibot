import { config } from '../config'
import type { AiResult, AiStyle, CalendarData, ChannelAnalytics, CleanResult, TemplateList, ChannelList, CreatePostInput, Draft, ErrorCode, Lang, Me, PostFilter, PostResult, ScheduleParseResult, ScheduledPage, ScheduledPost } from './types'
import {
  parseAi, parseCancelled, parseChannelAnalytics, parseChannels, parseErrorBody, parseLanguage, parseMe, parsePostEnvelope,
  parseCalendar, parseClean, parseDeleted, parseTemplateDeleted, parseTemplateSaved, parseTemplates, parseScheduleParse, parseDraft, parsePostResult, parseScheduled,
} from './validate'

const KNOWN_CODES: readonly string[] = [
  'bad_request', 'https_required', 'unauthorized', 'auth_expired', 'not_registered',
  'beta_access_required', 'not_found', 'method_not_allowed', 'rate_limited', 'internal_error',
  'service_unavailable', 'auth_unavailable',
  'invalid_input', 'schedule_in_past', 'unsupported_media_type', 'payload_too_large',
  'channel_not_found', 'not_editable', 'queue_limit_reached', 'ai_limit_reached',
  'ai_unavailable', 'templates_limit_reached', 'save_failed', 'draft_not_found', 'media_unavailable', 'caption_too_long',
]

export class ApiClientError extends Error {
  readonly code: ErrorCode
  readonly status: number
  readonly requestId: string | null
  readonly retryAfter: number | null
  /** Server ko'rsatgan MAYDON NOMI (forma xatosi uchun); qiymat hech qachon emas. */
  readonly field: string | null

  constructor(code: ErrorCode, status = 0, requestId: string | null = null, retryAfter: number | null = null,
    field: string | null = null) {
    super(code)
    this.code = code
    this.status = status
    this.requestId = requestId
    this.retryAfter = retryAfter
    this.field = field
  }
}

export interface ClientOptions {
  getInitData: () => string
  language?: () => string
  fetchImpl?: typeof fetch
  baseUrl?: string
  timeoutMs?: number
  maxGetRetries?: number
  retryDelayMs?: number
  sleep?: (ms: number) => Promise<void>
}

const RETRYABLE_STATUS = new Set([502, 503, 504])
const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/**
 * Faqat GET so'rovlari (1-versiya: yozuvchi endpoint yo'q). Qayta urinish faqat shu yerda:
 * tarmoq xatosi, timeout va 502/503/504 da bir marta. 401/403/429 va boshqa mijoz xatolari
 * qayta urinilmaydi. To'lov/nashr kabi yozuvchi amallar qo'shilganda ular qayta URINILMASLIGI
 * (yoki Idempotency-Key talab qilinishi) shart.
 */
export function createApiClient(opts: ClientOptions) {
  const fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a))
  const base = (opts.baseUrl ?? config.apiBase).replace(/\/$/, '')
  const timeoutMs = opts.timeoutMs ?? config.requestTimeoutMs
  const maxRetries = opts.maxGetRetries ?? config.maxGetRetries
  const retryDelay = opts.retryDelayMs ?? config.retryDelayMs
  const sleep = opts.sleep ?? defaultSleep

  async function attempt(path: string, signal?: AbortSignal, method = 'GET', payload?: unknown,
    timeout = timeoutMs): Promise<unknown> {
    const initData = opts.getInitData()
    if (!initData) throw new ApiClientError('no_telegram')
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeout)
    const onAbort = () => controller.abort()
    signal?.addEventListener('abort', onAbort, { once: true })
    try {
      const headers: Record<string, string> = { Authorization: `tma ${initData}`, Accept: 'application/json' }
      const lang = opts.language?.()
      if (lang) headers['Accept-Language'] = lang
      if (payload !== undefined) headers['Content-Type'] = 'application/json'
      let res: Response
      try {
        res = await fetchImpl(`${base}${path}`, {
          method, headers, signal: controller.signal, cache: 'no-store',
          ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
        })
      } catch (e) {
        if (signal?.aborted) throw e // chaqiruvchi o'zi bekor qildi
        throw new ApiClientError(timedOut ? 'timeout' : 'network')
      }
      let body: unknown = null
      try {
        body = await res.json()
      } catch {
        body = null
      }
      if (!res.ok) {
        const err = parseErrorBody(body)
        const code = (err && KNOWN_CODES.includes(err.code) ? err.code : 'internal_error') as ErrorCode
        const header = Number(res.headers.get('Retry-After'))
        throw new ApiClientError(code, res.status, err?.requestId ?? null,
          err?.retryAfter ?? (Number.isFinite(header) && header > 0 ? header : null), err?.field ?? null)
      }
      if (body === null) throw new ApiClientError('bad_response', res.status)
      return body
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    }
  }

  async function get<T>(path: string, parse: (v: unknown) => T, signal?: AbortSignal): Promise<T> {
    let tries = 0
    for (;;) {
      try {
        return parse(await attempt(path, signal))
      } catch (e) {
        if (signal?.aborted) throw e
        const err =
          e instanceof ApiClientError ? e : new ApiClientError('bad_response') // ShapeError va h.k.
        const retryable = err.code === 'network' || err.code === 'timeout' || RETRYABLE_STATUS.has(err.status)
        if (!retryable || tries >= maxRetries) throw err
        tries += 1
        await sleep(retryDelay)
      }
    }
  }

  /**
   * Yozuvchi so'rovlar (POST/PATCH/DELETE): HECH QACHON avtomatik qayta URINILMAYDI (takroriy post
   * yaratilmasligi uchun). Tarmoq/timeout xatosida natija NOMA'LUM bo'lishi mumkin — chaqiruvchi
   * ro'yxatni qayta yuklab tekshiradi (server ham 30 s ichida bir xil postni takrorlamaydi).
   */
  async function send<T>(method: 'POST' | 'PATCH' | 'DELETE', path: string, body: unknown,
    parse: (v: unknown) => T, timeout = timeoutMs): Promise<T> {
    try {
      return parse(await attempt(path, undefined, method, body, timeout))
    } catch (e) {
      throw e instanceof ApiClientError ? e : new ApiClientError('bad_response')
    }
  }

  return {
    me: (signal?: AbortSignal): Promise<Me> => get('/me', parseMe, signal),
    channels: (signal?: AbortSignal): Promise<ChannelList> => get('/channels', parseChannels, signal),
    channelAnalytics: (channelId: string, signal?: AbortSignal): Promise<ChannelAnalytics> =>
      get(`/channels/${encodeURIComponent(channelId)}/analytics`, parseChannelAnalytics, signal),
    scheduledPosts: (limit: number, offset: number, signal?: AbortSignal, status: PostFilter = 'pending'): Promise<ScheduledPage> =>
      get(`/scheduled-posts?limit=${limit}&offset=${offset}${status === 'history' ? '&status=history' : ''}`, parseScheduled, signal),
    /** Kutilayotgan postlar [from, to) oralig'ida (ISO, zonali). */
    calendar: (from: string, to: string, signal?: AbortSignal): Promise<CalendarData> =>
      get(`/scheduled-posts/calendar?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, parseCalendar, signal),
    post: (id: number, signal?: AbortSignal): Promise<ScheduledPost> =>
      get(`/posts/${encodeURIComponent(String(id))}`, parsePostEnvelope, signal),
    draft: (signal?: AbortSignal): Promise<Draft | null> => get('/draft', parseDraft, signal),
    deleteDraft: (): Promise<{ deleted: boolean }> => send('DELETE', '/draft', undefined, parseDeleted),
    /** Qoralamadagi rasm (blob). Auth sarlavhasi kerak, shuning uchun <img src> emas, fetch. Xatoda `null`. */
    draftMedia: async (signal?: AbortSignal): Promise<Blob | null> => {
      const initData = opts.getInitData()
      if (!initData) return null
      try {
        const res = await fetchImpl(`${base}/draft/media`, {
          headers: { Authorization: `tma ${initData}` }, signal, cache: 'no-store' })
        if (!res.ok) return null
        const blob = await res.blob()
        return blob.type.startsWith('image/') ? blob : null
      } catch {
        return null
      }
    },
    createPost: (input: CreatePostInput): Promise<PostResult> =>
      send('POST', '/posts', input, parsePostResult),
    /** Erkin tildagi rejalash iborasini tuzilma taklifiga o'giradi (hech narsa yozilmaydi). */
    parseSchedule: (text: string, defaultTime?: string): Promise<ScheduleParseResult> =>
      send('POST', '/schedule/parse', { text, ...(defaultTime ? { default_time: defaultTime } : {}) }, parseScheduleParse),
    updatePost: (id: number, input: { text?: string; scheduled_at?: string }): Promise<ScheduledPost> =>
      send('PATCH', `/posts/${encodeURIComponent(String(id))}`, input, parsePostEnvelope),
    cancelPost: (id: number): Promise<{ id: number }> =>
      send('DELETE', `/posts/${encodeURIComponent(String(id))}`, undefined, parseCancelled),
    setLanguage: (language: Lang): Promise<{ language: Lang }> =>
      send('PATCH', '/me/settings', { language }, parseLanguage),
    templates: (signal?: AbortSignal): Promise<TemplateList> => get('/templates', parseTemplates, signal),
    saveTemplate: (name: string, text: string): Promise<{ id: number; created: boolean }> =>
      send('POST', '/templates', { name, text }, parseTemplateSaved),
    deleteTemplate: (id: number): Promise<{ id: number }> =>
      send('DELETE', `/templates/${encodeURIComponent(String(id))}`, undefined, parseTemplateDeleted),
    /** Matn oxiridagi begona havola/reklama qatorlarini olib, saqlangan imzoni qo'shadi (hech narsa yozilmaydi). */
    cleanText: (text: string): Promise<CleanResult> => send('POST', '/tools/clean', { text }, parseClean),
    generate: (text: string, style: AiStyle): Promise<AiResult> =>
      send('POST', '/ai/generate', { text, style }, parseAi, config.aiTimeoutMs),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
