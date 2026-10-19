import { config } from '../config'
import { setAppTimezone } from '../pages/recurrence'
import type { AdminAd, AdminAdInput, AdminAds, AdminMarket, AdminOverview, AdminSponsor, AiResult, AiStyle, CalendarData, ChannelAnalytics, TemplateList, ChannelList, CreatePostInput, MarketCatalog, MarketCategory, MarketListing, MarketListingInput, MarketMine, MarketSort, MarketSummary, MarketThread, MarketThreadItem, Draft, ErrorCode, Lang, Me, NotificationSettings, PostFilter, PostResult, ScheduleParseResult, ScheduledPage, ScheduledPost, UpdatePostInput } from './types'
import {
  parseAdminAdEnvelope, parseAdminAds, parseAdminMarket, parseAdminOverview, parseAdminSponsors,
  parseAi, parseCancelled, parseChannelAnalytics, parseChannels, parseErrorBody, parseLanguage, parseMe, parsePostEnvelope,
  parseMarketAck, parseMarketCard, parseMarketCatalog, parseMarketListingEnvelope, parseMarketMine, parseMarketSummary, parseMarketThread, parseMarketThreads,
  parseCalendar, parseDeleted, parseSettingsSaved, parseTemplateDeleted, parseTemplateSaved, parseTemplates, parseScheduleParse, parseDraft, parsePostResult, parseScheduled,
} from './validate'

const KNOWN_CODES: readonly string[] = [
  'bad_request', 'https_required', 'unauthorized', 'auth_expired', 'not_registered',
  'not_found', 'method_not_allowed', 'rate_limited', 'internal_error',
  'service_unavailable', 'auth_unavailable',
  'invalid_input', 'schedule_in_past', 'unsupported_media_type', 'payload_too_large',
  'channel_not_found', 'not_editable', 'queue_limit_reached', 'ai_limit_reached',
  'ai_unavailable', 'upload_failed', 'templates_limit_reached', 'save_failed', 'draft_not_found', 'media_unavailable', 'caption_too_long', 'album_full', 'album_mixed',
  'market_private', 'market_not_admin', 'market_limit', 'market_blocked', 'inquiry_limit', 'inquiry_blocked', 'inquiry_own', 'inquiry_exists', 'thread_closed', 'thread_full',
  'message_card', 'message_wallet', 'message_link', 'message_spam', 'user_banned', 'owner_busy', 'phone_required',
  'admin_only', 'sponsor_not_found', 'sponsor_not_admin',
]

/** Yuklash vaqti fayl hajmiga qarab (sekin mobil tarmoqda 50 MB video 60 s ga sig'maydi). */
export function uploadTimeout(file: { size: number }): number {
  return Math.min(config.uploadMaxTimeoutMs, config.uploadTimeoutMs + Math.round(file.size / (200 * 1024)) * 1000)
}

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
      const isForm = typeof FormData !== 'undefined' && payload instanceof FormData
      if (payload !== undefined && !isForm) headers['Content-Type'] = 'application/json'
      let res: Response
      try {
        res = await fetchImpl(`${base}${path}`, {
          method, headers, signal: controller.signal, cache: 'no-store',
          ...(payload === undefined ? {} : { body: isForm ? (payload as FormData) : JSON.stringify(payload) }),
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
    me: (signal?: AbortSignal): Promise<Me> => get('/me', parseMe, signal).then((m) => { setAppTimezone(m.user.timezone); return m }),
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
    draftMedia: async (signal?: AbortSignal, index?: number): Promise<Blob | null> => {
      const initData = opts.getInitData()
      if (!initData) return null
      try {
        const res = await fetchImpl(`${base}/draft/media${index === undefined ? '' : `?i=${index}`}`, {
          headers: { Authorization: `tma ${initData}` }, signal, cache: 'no-store' })
        if (!res.ok) return null
        const blob = await res.blob()
        return blob.type.startsWith('image/') || blob.type.startsWith('video/') ? blob : null
      } catch {
        return null
      }
    },
    /** Qurilmadan rasm/video/GIF yuklaydi (multipart); server Telegram file_id oladi va qoralamaga yozadi. */
    uploadMedia: (file: File, fields: { text?: string; button_text?: string; button_url?: string } = {}, add = false): Promise<Draft | null> => {
      const form = new FormData()
      for (const [k, v] of Object.entries(fields)) if (v !== undefined) form.append(k, v)
      form.append('file', file, file.name)
      return send('POST', `/draft/media${add ? '?add=1' : ''}`, form, parseDraft, uploadTimeout(file))
    },
    /** Qoralamadagi `index`-chi mediani olib tashlaydi (albom qisqaradi). */
    deleteDraftMedia: (index: number): Promise<Draft | null> =>
      send('DELETE', `/draft/media?i=${index}`, undefined, parseDraft),
    createPost: (input: CreatePostInput): Promise<PostResult> =>
      send('POST', '/posts', input, parsePostResult),
    /** Erkin tildagi rejalash iborasini tuzilma taklifiga o'giradi (hech narsa yozilmaydi). */
    parseSchedule: (text: string, defaultTime?: string): Promise<ScheduleParseResult> =>
      send('POST', '/schedule/parse', { text, ...(defaultTime ? { default_time: defaultTime } : {}) }, parseScheduleParse),
    updatePost: (id: number, input: UpdatePostInput): Promise<ScheduledPost> =>
      send('PATCH', `/posts/${encodeURIComponent(String(id))}`, input, parsePostEnvelope),
    /** Rejalangan postning rasmi/videosi (blob; faqat egasi). Xatoda `null`. */
    postMedia: async (id: number, signal?: AbortSignal, index?: number): Promise<Blob | null> => {
      const initData = opts.getInitData()
      if (!initData) return null
      try {
        const res = await fetchImpl(`${base}/posts/${encodeURIComponent(String(id))}/media${index === undefined ? '' : `?i=${index}`}`, {
          headers: { Authorization: `tma ${initData}` }, signal })
        if (!res.ok) return null
        const blob = await res.blob()
        return blob.type.startsWith('image/') || blob.type.startsWith('video/') ? blob : null
      } catch {
        return null
      }
    },
    /** Qurilmadagi fayl bilan rasm/videoni almashtiradi (yoki matnli postga qo'shadi). */
    replacePostMedia: (id: number, file: File): Promise<ScheduledPost> => {
      const form = new FormData()
      form.append('file', file, file.name)
      return send('POST', `/posts/${encodeURIComponent(String(id))}/media`, form, parsePostEnvelope, uploadTimeout(file))
    },
    /** Albomga yana bir fayl qo'shadi (10 tagacha). */
    addPostMedia: (id: number, file: File): Promise<ScheduledPost> => {
      const form = new FormData()
      form.append('file', file, file.name)
      return send('POST', `/posts/${encodeURIComponent(String(id))}/media?add=1`, form, parsePostEnvelope, uploadTimeout(file))
    },
    /** Rasm/videoni olib tashlaydi: `index` berilsa albomdan shu element, bo'lmasa hammasi (post matnli bo'lib qoladi). */
    deletePostMedia: (id: number, index?: number): Promise<ScheduledPost> =>
      send('DELETE', `/posts/${encodeURIComponent(String(id))}/media${index === undefined ? '' : `?i=${index}`}`, undefined, parsePostEnvelope),
    cancelPost: (id: number): Promise<{ id: number }> =>
      send('DELETE', `/posts/${encodeURIComponent(String(id))}`, undefined, parseCancelled),
    /** Bildirishnoma tanlovlarini saqlaydi (faqat o'zgargan kalitlar yuboriladi). */
    setNotifications: (notifications: Partial<NotificationSettings>): Promise<{ notifications?: Partial<NotificationSettings> }> =>
      send('PATCH', '/me/settings', { notifications }, parseSettingsSaved),
    setLanguage: (language: Lang): Promise<{ language: Lang }> =>
      send('PATCH', '/me/settings', { language }, parseLanguage),
    templates: (signal?: AbortSignal): Promise<TemplateList> => get('/templates', parseTemplates, signal),
    saveTemplate: (name: string, text: string): Promise<{ id: number; created: boolean }> =>
      send('POST', '/templates', { name, text }, parseTemplateSaved),
    deleteTemplate: (id: number): Promise<{ id: number }> =>
      send('DELETE', `/templates/${encodeURIComponent(String(id))}`, undefined, parseTemplateDeleted),
    // --- 💰 Reklama birjasi ---
    marketSummary: (signal?: AbortSignal): Promise<MarketSummary> => get('/market/summary', parseMarketSummary, signal),
    marketCatalog: (category: MarketCategory | 'all', sort: MarketSort, page: number, signal?: AbortSignal, country: 'all' | 'mine' | 'auto' = 'auto'): Promise<MarketCatalog> =>
      get(`/market/listings?category=${category}&sort=${sort}&page=${page}&country=${country}`, parseMarketCatalog, signal),
    marketListing: (id: number, signal?: AbortSignal): Promise<{ listing: MarketListing; is_owner: boolean }> =>
      get(`/market/listings/${id}`, parseMarketCard, signal),
    marketInquire: (id: number, text: string): Promise<{ inquiry_id: number; delivered: boolean }> =>
      send('POST', `/market/listings/${id}/inquiries`, { text }, (v) => {
        const o = parseMarketAck(v)
        return { inquiry_id: Number(o.inquiry_id), delivered: o.delivered === true }
      }),
    marketReport: (id: number): Promise<{ again: boolean; blocked: boolean }> =>
      send('POST', `/market/listings/${id}/report`, undefined, (v) => {
        const o = parseMarketAck(v)
        return { again: o.again === true, blocked: o.blocked === true }
      }),
    marketMine: (signal?: AbortSignal): Promise<MarketMine> => get('/market/mine', parseMarketMine, signal),
    marketPublish: (input: MarketListingInput): Promise<MarketListing> =>
      send('POST', '/market/mine', input, parseMarketListingEnvelope, config.aiTimeoutMs),
    marketUpdate: (id: number, patch: Partial<Pick<MarketListingInput, 'category' | 'price' | 'description'>> & { status?: 'active' | 'paused' }): Promise<MarketListing> =>
      send('PATCH', `/market/mine/${id}`, patch, parseMarketListingEnvelope),
    marketRefresh: (id: number): Promise<MarketListing> =>
      send('POST', `/market/mine/${id}/refresh`, undefined, parseMarketListingEnvelope),
    marketDelete: (id: number): Promise<void> =>
      send('DELETE', `/market/mine/${id}`, undefined, () => undefined),
    marketThreads: (signal?: AbortSignal): Promise<{ items: MarketThreadItem[] }> => get('/market/threads', parseMarketThreads, signal),
    marketThread: (id: number, signal?: AbortSignal): Promise<MarketThread> => get(`/market/threads/${id}`, parseMarketThread, signal),
    marketReply: (id: number, text: string): Promise<{ delivered: boolean }> =>
      send('POST', `/market/threads/${id}/messages`, { text }, (v) => ({ delivered: parseMarketAck(v).delivered === true })),
    marketCloseThread: (id: number): Promise<void> => send('POST', `/market/threads/${id}/close`, undefined, () => undefined),
    /** Tab nishoni uchun yengil so'rov: o'qilmagan xabarlar soni. */
    marketUnread: (signal?: AbortSignal): Promise<number> =>
      get('/market/unread', (v) => Number(parseMarketAck(v).unread) || 0, signal),
    /** 🚩 Firibgar: suhbat yopiladi, 3 ta turli shikoyatdan keyin global ban. */
    marketReportUser: (id: number): Promise<{ again: boolean }> =>
      send('POST', `/market/threads/${id}/report`, undefined, (v) => ({ again: parseMarketAck(v).again === true })),
    marketBlock: (id: number): Promise<void> => send('POST', `/market/threads/${id}/block`, undefined, () => undefined),
    // --- 👑 Super admin (server har bir so'rovda ruxsatni tekshiradi) ---
    adminOverview: (signal?: AbortSignal): Promise<AdminOverview> => get('/admin/overview', parseAdminOverview, signal),
    adminAds: (signal?: AbortSignal): Promise<AdminAds> => get('/admin/ads', parseAdminAds, signal),
    adminAdSettings: (patch: { reply_enabled?: boolean; reply_interval?: number; channel_enabled?: boolean; channel_interval?: number }): Promise<AdminAds> =>
      send('PATCH', '/admin/ads/settings', patch, parseAdminAds),
    adminAdCreate: (input: AdminAdInput): Promise<AdminAd> => send('POST', '/admin/ads', input, parseAdminAdEnvelope),
    adminAdUpdate: (id: number, patch: { text?: string; button_text?: string; button_url?: string; is_active?: boolean }): Promise<AdminAd> =>
      send('PATCH', `/admin/ads/${id}`, patch, parseAdminAdEnvelope),
    adminAdDelete: (id: number): Promise<void> => send('DELETE', `/admin/ads/${id}`, undefined, () => undefined),
    adminSponsors: (signal?: AbortSignal): Promise<{ items: AdminSponsor[] }> => get('/admin/sponsors', parseAdminSponsors, signal),
    adminSponsorAdd: (channel: string): Promise<{ items: AdminSponsor[] }> =>
      send('POST', '/admin/sponsors', { channel }, parseAdminSponsors, config.aiTimeoutMs),
    adminSponsorDelete: (id: number): Promise<void> => send('DELETE', `/admin/sponsors/${id}`, undefined, () => undefined),
    adminMarket: (status: 'all' | 'active' | 'paused' | 'blocked', signal?: AbortSignal): Promise<AdminMarket> =>
      get(`/admin/market${status === 'all' ? '' : `?status=${status}`}`, parseAdminMarket, signal),
    adminListingStatus: (id: number, status: 'active' | 'blocked'): Promise<void> =>
      send('POST', `/admin/market/listings/${id}/status`, { status }, () => undefined),
    adminUserBan: (userId: number, banned: boolean): Promise<void> =>
      send('POST', `/admin/market/users/${userId}/ban`, { banned }, () => undefined),
    generate: (text: string, style: AiStyle): Promise<AiResult> =>
      send('POST', '/ai/generate', { text, style }, parseAi, config.aiTimeoutMs),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
