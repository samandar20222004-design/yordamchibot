// Server javoblarini ish vaqtida tekshirish (kichik qo'lda validatorlar: yangi kutubxona yo'q).
import { AI_STYLES, MARKET_CATEGORIES, NOTIFICATION_KEYS } from './types'
import type { AdminAd, AdminAds, AdminMarket, AdminMarketTotals, AdminOverview, AdminSponsor, MarketBadge, MarketMessageFlag, MarketCatalog, MarketCategory, MarketListing, MarketMine, MarketSummary, MarketThread, MarketThreadItem, PlanLimits, TierInfo, AiResult, Template, TemplateList, CalendarData, Channel, ChannelAnalytics, ChannelList, Confidence, Lang, Me, Plan, PostCounts, PostResult, RecurrenceInput, ScheduleParseResult, ScheduledPage, ScheduledPost, Draft, NotificationSettings } from './types'

export class ShapeError extends Error {}

type Rec = Record<string, unknown>

function rec(v: unknown, what: string): Rec {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new ShapeError(what)
  return v as Rec
}
function str(v: unknown, what: string): string {
  if (typeof v !== 'string') throw new ShapeError(what)
  return v
}
function strOrNull(v: unknown, what: string): string | null {
  if (v === null || v === undefined) return null
  return str(v, what)
}
function int(v: unknown, what: string): number {
  if (typeof v !== 'number' || !Number.isFinite(v) || !Number.isInteger(v)) throw new ShapeError(what)
  return v
}
function bool(v: unknown, what: string): boolean {
  if (typeof v !== 'boolean') throw new ShapeError(what)
  return v
}
function arr(v: unknown, what: string): unknown[] {
  if (!Array.isArray(v)) throw new ShapeError(what)
  return v
}
function lang(v: unknown): Lang {
  return v === 'ru' || v === 'en' ? v : 'uz'
}

function parsePlan(v: unknown): Plan {
  const p = rec(v, 'plan')
  const l = rec(p.limits, 'plan.limits')
  return {
    type: str(p.type, 'plan.type'),
    is_pro: bool(p.is_pro, 'plan.is_pro'),
    expires_at: strOrNull(p.expires_at, 'plan.expires_at'),
    limits: parseLimits(l),
  }
}

function parseLimits(l: Rec): PlanLimits {
  return {
    max_channels: int(l.max_channels, 'limits.max_channels'),
    daily_ai_requests: int(l.daily_ai_requests, 'limits.daily_ai_requests'),
    queued_posts: int(l.queued_posts, 'limits.queued_posts'),
    ...(l.voice_daily === undefined ? {} : { voice_daily: int(l.voice_daily, 'limits.voice_daily') }),
  }
}

function parseTier(v: unknown, what: string): TierInfo {
  const t = rec(v, what)
  const periods = t.periods === undefined ? [] : arr(t.periods, `${what}.periods`).map((x, i) => {
    const p = rec(x, `${what}.periods.${i}`)
    return {
      months: int(p.months, `${what}.months`), days: int(p.days, `${what}.days`), uzs: int(p.uzs, `${what}.uzs`),
      stars: int(p.stars, `${what}.stars`), usd: typeof p.usd === 'number' && Number.isFinite(p.usd) ? p.usd : 0, save_pct: int(p.save_pct, `${what}.save_pct`),
    }
  })
  return { limits: parseLimits(rec(t.limits, `${what}.limits`)), price_from_uzs: int(t.price_from_uzs, `${what}.price`), periods }
}

function parseCounts(v: unknown): PostCounts {
  const c = rec(v, 'posts')
  return {
    pending: int(c.pending, 'posts.pending'),
    sent: int(c.sent, 'posts.sent'),
    failed: int(c.failed, 'posts.failed'),
    cancelled: int(c.cancelled, 'posts.cancelled'),
  }
}

function parseNotifications(v: unknown, path: string): NotificationSettings {
  const o = rec(v, path)
  const out = {} as NotificationSettings
  for (const k of NOTIFICATION_KEYS) out[k] = bool(o[k], `${path}.${k}`)
  return out
}

/** `PATCH /me/settings` javobi: faqat yangilangan qism(lar). */
export function parseSettingsSaved(v: unknown): { language?: Lang; notifications?: Partial<NotificationSettings> } {
  const o = rec(v, 'settings')
  const out: { language?: Lang; notifications?: Partial<NotificationSettings> } = {}
  if (o.language !== undefined) out.language = lang(o.language)
  if (o.notifications !== undefined) {
    const n = rec(o.notifications, 'settings.notifications')
    out.notifications = {}
    for (const k of NOTIFICATION_KEYS) if (n[k] !== undefined) out.notifications[k] = bool(n[k], `settings.notifications.${k}`)
  }
  return out
}

export function parseMe(v: unknown): Me {
  const o = rec(v, 'me')
  const u = rec(o.user, 'user')
  const usage = rec(o.usage, 'usage')
  const bot = rec(o.bot, 'bot')
  return {
    user: {
      id: int(u.id, 'user.id'),
      name: strOrNull(u.name, 'user.name'),
      username: strOrNull(u.username, 'user.username'),
      language: lang(u.language),
      ...(typeof u.timezone === 'string' && u.timezone ? { timezone: u.timezone } : {}),
    },
    plan: parsePlan(o.plan),
    ...(o.pay_region === 'uz' || o.pay_region === 'intl' ? { pay_region: o.pay_region } : {}),
    ...(o.tiers === undefined ? {} : { tiers: {
      ...(rec(o.tiers, 'tiers').free === undefined ? {} : { free: parseTier(rec(o.tiers, 'tiers').free, 'tiers.free') }),
      pro: parseTier(rec(o.tiers, 'tiers').pro, 'tiers.pro'), ultra: parseTier(rec(o.tiers, 'tiers').ultra, 'tiers.ultra') } }),
    usage: {
      channels: int(usage.channels, 'usage.channels'),
      pending_posts: int(usage.pending_posts, 'usage.pending_posts'),
      ai_requests_today: int(usage.ai_requests_today, 'usage.ai_requests_today'),
      ai_credits: int(usage.ai_credits, 'usage.ai_credits'),
    },
    posts: parseCounts(o.posts),
    ...(o.settings === undefined ? {} : { settings: { notifications: parseNotifications(rec(o.settings, 'settings').notifications, 'settings.notifications') } }),
    next_post_at: strOrNull(o.next_post_at, 'next_post_at'),
    bot: { username: strOrNull(bot.username, 'bot.username') },
    ...(o.is_admin === true ? { is_admin: true } : {}),
  }
}

function parseChannel(v: unknown): Channel {
  const c = rec(v, 'channel')
  return {
    id: str(c.id, 'channel.id'),
    title: strOrNull(c.title, 'channel.title'),
    ...(c.pending_posts === undefined ? {} : { pending_posts: int(c.pending_posts, 'channel.pending_posts') }),
    ...(c.members === undefined ? {} : { members: intOrNull(c.members, 'channel.members') }),
    ...(c.members_as_of === undefined ? {} : { members_as_of: strOrNull(c.members_as_of, 'channel.members_as_of') }),
  }
}

function intOrNull(v: unknown, what: string): number | null {
  if (v === null || v === undefined) return null
  return int(v, what)
}
function numOrNull(v: unknown, what: string): number | null {
  if (v === null || v === undefined) return null
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new ShapeError(what)
  return v
}
function confidence(v: unknown): Confidence {
  return v === 'low' || v === 'medium' || v === 'high' ? v : 'none'
}

export function parseChannelAnalytics(v: unknown): ChannelAnalytics {
  const o = rec(v, 'analytics')
  const ch = rec(o.channel, 'analytics.channel')
  const m = rec(o.members, 'analytics.members')
  const p = rec(o.posts, 'analytics.posts')
  const w = rec(o.views, 'analytics.views')
  return {
    channel: { id: str(ch.id, 'channel.id'), title: strOrNull(ch.title, 'channel.title') ?? '' },
    members: {
      current: intOrNull(m.current, 'members.current'),
      as_of: strOrNull(m.as_of, 'members.as_of'),
      delta_7d: intOrNull(m.delta_7d, 'members.delta_7d'),
      delta_30d: intOrNull(m.delta_30d, 'members.delta_30d'),
      points: int(m.points, 'members.points'),
      span_days: int(m.span_days, 'members.span_days'),
      confidence: confidence(m.confidence),
      stale: bool(m.stale, 'members.stale'),
      source: strOrNull(m.source, 'members.source'),
      collected_at: strOrNull(m.collected_at, 'members.collected_at'),
      history: arr(m.history, 'members.history').map((h) => {
        const r = rec(h, 'members.history[]')
        return { date: str(r.date, 'history.date'), member_count: int(r.member_count, 'history.member_count') }
      }),
    },
    posts: {
      sent_7d: int(p.sent_7d, 'posts.sent_7d'), sent_30d: int(p.sent_30d, 'posts.sent_30d'),
      sent_all: int(p.sent_all, 'posts.sent_all'), pending: int(p.pending, 'posts.pending'),
      failed: int(p.failed, 'posts.failed'), unknown: int(p.unknown, 'posts.unknown'),
    },
    views: {
      available: bool(w.available, 'views.available'),
      with_views: int(w.with_views, 'views.with_views'),
      avg: numOrNull(w.avg, 'views.avg'),
      max: intOrNull(w.max, 'views.max'),
      collected_at: strOrNull(w.collected_at, 'views.collected_at'),
      sources: arr(w.sources, 'views.sources').map((x) => str(x, 'views.sources[]')),
    },
  }
}

export function parseChannels(v: unknown): ChannelList {
  const o = rec(v, 'channels')
  return { items: arr(o.items, 'items').map(parseChannel), total: int(o.total, 'total') }
}

function mediaItems(v: unknown, path: string): { type: string; previewable: boolean }[] {
  if (!Array.isArray(v) || v.length > 10) throw new ShapeError(path)
  return v.map((x, i) => {
    const o = rec(x, `${path}[${i}]`)
    return { type: str(o.type, `${path}.type`), previewable: bool(o.previewable, `${path}.previewable`) }
  })
}

export function parsePost(v: unknown): ScheduledPost {
  const p = rec(v, 'post')
  return {
    ...(p.text === undefined ? {} : { text: str(p.text, 'post.text') }),
    ...(p.button_text == null ? {} : { button_text: str(p.button_text, 'post.button_text') }),
    ...(p.button_url == null ? {} : { button_url: str(p.button_url, 'post.button_url') }),
    id: int(p.id, 'post.id'),
    channel_id: str(p.channel_id, 'post.channel_id'),
    channel_title: strOrNull(p.channel_title, 'post.channel_title'),
    post_type: str(p.post_type, 'post.post_type'),
    preview: str(p.preview, 'post.preview'),
    has_media: bool(p.has_media, 'post.has_media'),
    ...(p.media_items === undefined ? {} : { media_items: mediaItems(p.media_items, 'post.media_items') }),
    scheduled_time: strOrNull(p.scheduled_time, 'post.scheduled_time'),
    number: p.number === null || p.number === undefined ? null : int(p.number, 'post.number'),
    recurrence: strOrNull(p.recurrence, 'post.recurrence'),
    status: str(p.status, 'post.status'),
    ...(p.recurrence_day === undefined ? {} : { recurrence_day: intOrNull(p.recurrence_day, 'post.recurrence_day') }),
    ...(p.recurrence_time === undefined ? {} : { recurrence_time: strOrNull(p.recurrence_time, 'post.recurrence_time') }),
    ...(p.recurrence_time2 == null ? {} : { recurrence_time2: strOrNull(p.recurrence_time2, 'post.recurrence_time2') }),
  }
}

export function parseScheduled(v: unknown): ScheduledPage {
  const o = rec(v, 'scheduled')
  return {
    items: arr(o.items, 'items').map(parsePost),
    total: int(o.total, 'total'),
    limit: int(o.limit, 'limit'),
    offset: int(o.offset, 'offset'),
    has_more: bool(o.has_more, 'has_more'),
  }
}

const REC_TYPES = ['daily', 'weekly', 'interval', 'weekdays', 'twice'] as const

function parseRecurrence(v: unknown): RecurrenceInput | null {
  if (v === null || v === undefined) return null
  const r = rec(v, 'recurrence')
  const type = r.type
  if (typeof type !== 'string' || !(REC_TYPES as readonly string[]).includes(type)) throw new ShapeError('recurrence.type')
  const time = str(r.time, 'recurrence.time')
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new ShapeError('recurrence.time')
  const base = { type: type as RecurrenceInput['type'], day: intOrNull(r.day, 'recurrence.day'), time }
  if (type === 'twice') {
    const time2 = str(r.time2, 'recurrence.time2')
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time2) || time2 === time) throw new ShapeError('recurrence.time2')
    return { ...base, time2 }
  }
  return base
}

export function parseScheduleParse(v: unknown): ScheduleParseResult {
  const o = rec(v, 'schedule')
  if (o.ok === false) return { ok: false, reason: str(o.reason, 'reason') }
  if (o.ok !== true) throw new ShapeError('ok')
  const source = o.source
  if (source !== 'rules' && source !== 'ai') throw new ShapeError('source')
  const p = rec(o.proposal, 'proposal')
  const at = str(p.scheduled_at, 'proposal.scheduled_at')
  if (Number.isNaN(new Date(at).getTime())) throw new ShapeError('proposal.scheduled_at')
  return { ok: true, source, proposal: { scheduled_at: at, recurrence: parseRecurrence(p.recurrence) } }
}

export function parseCalendar(v: unknown): CalendarData {
  const o = rec(v, 'calendar')
  return { items: arr(o.items, 'items').map(parsePost), truncated: bool(o.truncated, 'truncated') }
}

export function parsePostEnvelope(v: unknown): ScheduledPost {
  return parsePost(rec(v, 'envelope').post)
}

export function parsePostResult(v: unknown): PostResult {
  const o = rec(v, 'result')
  const delivery = o.delivery
  if (delivery !== 'scheduled' && delivery !== 'immediate') throw new ShapeError('delivery')
  return { post: parsePost(o.post), created: bool(o.created, 'created'), delivery }
}

export function parseCancelled(v: unknown): { id: number } {
  const o = rec(v, 'cancel')
  if (o.status !== 'cancelled') throw new ShapeError('status')
  return { id: int(o.id, 'id') }
}

export function parseLanguage(v: unknown): { language: Lang } {
  const o = rec(v, 'language')
  if (o.language !== 'uz' && o.language !== 'ru' && o.language !== 'en') throw new ShapeError('language')
  return { language: o.language }
}

export function parseAi(v: unknown): AiResult {
  const o = rec(v, 'ai')
  const style = str(o.style, 'ai.style')
  if (!(AI_STYLES as readonly string[]).includes(style)) throw new ShapeError('ai.style')
  const text = str(o.text, 'ai.text')
  if (!text.trim()) throw new ShapeError('ai.text')
  return { text, style: style as AiResult['style'] }
}

export interface ApiErrorBody {
  code: string
  message: string
  requestId: string | null
  retryAfter: number | null
  field: string | null
}

export function parseErrorBody(v: unknown): ApiErrorBody | null {
  try {
    const e = rec(rec(v, 'body').error, 'error')
    return {
      code: str(e.code, 'code'),
      message: str(e.message, 'message'),
      requestId: strOrNull(e.request_id, 'request_id'),
      retryAfter: typeof e.retry_after === 'number' ? e.retry_after : null,
      field: typeof e.field === 'string' ? e.field : null,
    }
  } catch {
    return null
  }
}

export function parseDraft(v: unknown): Draft | null {
  const o = rec(v, 'draft')
  if (o.draft === null) return null
  const d = rec(o.draft, 'draft.item')
  let media: Draft['media'] = null
  if (d.media !== null && d.media !== undefined) {
    const m = rec(d.media, 'draft.media')
    media = {
      type: str(m.type, 'draft.media.type'),
      previewable: bool(m.previewable, 'draft.media.previewable'),
      count: m.count === null || m.count === undefined ? null : int(m.count, 'draft.media.count'),
      ...(m.items === undefined ? {} : { items: mediaItems(m.items, 'draft.media.items') }),
    }
  }
  return {
    post_type: str(d.post_type, 'draft.post_type'),
    text: str(d.text, 'draft.text'),
    button_text: strOrNull(d.button_text, 'draft.button_text'),
    button_url: strOrNull(d.button_url, 'draft.button_url'),
    channel_id: strOrNull(d.channel_id, 'draft.channel_id'),
    reactions: bool(d.reactions, 'draft.reactions'),
    delete_after_hours: int(d.delete_after_hours, 'draft.delete_after_hours'),
    media,
    updated_at: strOrNull(d.updated_at, 'draft.updated_at'),
  }
}

export function parseDeleted(v: unknown): { deleted: boolean } {
  return { deleted: bool(rec(v, 'deleted').deleted, 'deleted') }
}

export function parseTemplates(v: unknown): TemplateList {
  const o = rec(v, 'templates')
  const items: Template[] = arr(o.items, 'templates.items').map((raw) => {
    const t = rec(raw, 'template')
    return { id: int(t.id, 'template.id'), name: str(t.name, 'template.name'), text: str(t.text, 'template.text'),
      created_at: str(t.created_at, 'template.created_at') }
  })
  return { items, limit: int(o.limit, 'templates.limit') }
}

export function parseTemplateSaved(v: unknown): { id: number; created: boolean } {
  const o = rec(v, 'template')
  return { id: int(o.id, 'template.id'), created: bool(o.created, 'template.created') }
}

export function parseTemplateDeleted(v: unknown): { id: number } {
  return { id: int(rec(v, 'template').id, 'template.id') }
}

// --- 💰 Reklama birjasi ---
function category(v: unknown): MarketCategory {
  return (MARKET_CATEGORIES as readonly string[]).includes(v as string) ? (v as MarketCategory) : 'other'
}

export function parseMarketListing(v: unknown): MarketListing {
  const o = rec(v, 'listing')
  const badges = (o.badges === undefined ? [] : arr(o.badges, 'listing.badges'))
    .filter((b): b is MarketBadge => b === 'growing' || b === 'engaged' || b === 'active')
  const status = o.status === 'active' || o.status === 'paused' || o.status === 'blocked' ? o.status : undefined
  return {
    id: int(o.id, 'listing.id'), title: str(o.title, 'listing.title'), username: str(o.username, 'listing.username'),
    category: category(o.category), price: intOrNull(o.price, 'listing.price'),
    currency: o.currency === 'USD' ? 'USD' : 'UZS', country: typeof o.country === 'string' && o.country ? o.country : null,
    description: strOrNull(o.description, 'listing.description'),
    members: intOrNull(o.members, 'listing.members'), avg_views: intOrNull(o.avg_views, 'listing.avg_views'),
    er_percent: numOrNull(o.er_percent, 'listing.er_percent'), growth_30d: intOrNull(o.growth_30d, 'listing.growth_30d'),
    posts_30d: intOrNull(o.posts_30d, 'listing.posts_30d'), stats_updated_at: strOrNull(o.stats_updated_at, 'listing.stats_updated_at'),
    badges,
    ...(status ? { status } : {}),
    ...(typeof o.channel_id === 'string' ? { channel_id: o.channel_id } : {}),
    ...(typeof o.view_count === 'number' ? { view_count: int(o.view_count, 'listing.view_count') } : {}),
    ...(typeof o.inquiry_count === 'number' ? { inquiry_count: int(o.inquiry_count, 'listing.inquiry_count') } : {}),
  }
}

export function parseMarketSummary(v: unknown): MarketSummary {
  const o = rec(v, 'market')
  return {
    listings: int(o.listings, 'market.listings'), inquiries: int(o.inquiries, 'market.inquiries'),
    categories: arr(o.categories, 'market.categories').map(category), max_listings: int(o.max_listings, 'market.max_listings'),
    price_min: int(o.price_min, 'market.price_min'), price_max: int(o.price_max, 'market.price_max'),
    price_min_usd: typeof o.price_min_usd === 'number' ? o.price_min_usd : 1, price_max_usd: typeof o.price_max_usd === 'number' ? o.price_max_usd : 100000,
    viewer: { country: typeof rec(o.viewer ?? {}, 'market.viewer').country === 'string' ? String(rec(o.viewer ?? {}, 'market.viewer').country) : '',
      currency: rec(o.viewer ?? {}, 'market.viewer').currency === 'USD' ? 'USD' : 'UZS' },
    description_max: int(o.description_max, 'market.description_max'),
    message_min: int(o.message_min, 'market.message_min'), message_max: int(o.message_max, 'market.message_max'),
  }
}

export function parseMarketCatalog(v: unknown): MarketCatalog {
  const o = rec(v, 'catalog')
  return {
    items: arr(o.items, 'catalog.items').map(parseMarketListing), total: int(o.total, 'catalog.total'),
    page: int(o.page, 'catalog.page'), pages: int(o.pages, 'catalog.pages'), page_size: int(o.page_size, 'catalog.page_size'),
    viewer_country: typeof o.viewer_country === 'string' ? o.viewer_country : '', filter: o.filter === 'mine' ? 'mine' : 'all',
  }
}

export function parseMarketCard(v: unknown): { listing: MarketListing; is_owner: boolean } {
  const o = rec(v, 'card')
  return { listing: parseMarketListing(o.listing), is_owner: bool(o.is_owner, 'card.is_owner') }
}

export function parseMarketListingEnvelope(v: unknown): MarketListing {
  return parseMarketListing(rec(v, 'envelope').listing)
}

export function parseMarketMine(v: unknown): MarketMine {
  const o = rec(v, 'mine')
  return {
    items: arr(o.items, 'mine.items').map((raw) => {
      const i = rec(raw, 'mine.item')
      return { channel_id: str(i.channel_id, 'mine.channel_id'), title: str(i.title, 'mine.title'),
        listing: i.listing === null || i.listing === undefined ? null : parseMarketListing(i.listing) }
    }),
    max_listings: int(o.max_listings, 'mine.max_listings'),
  }
}

function role(v: unknown, what: string): 'owner' | 'advertiser' {
  if (v !== 'owner' && v !== 'advertiser') throw new ShapeError(what)
  return v
}

export function parseMarketThreads(v: unknown): { items: MarketThreadItem[] } {
  const o = rec(v, 'threads')
  return {
    items: arr(o.items, 'threads.items').map((raw) => {
      const t = rec(raw, 'thread')
      return { id: int(t.id, 'thread.id'), title: str(t.title, 'thread.title'), role: role(t.role, 'thread.role'),
        unread: t.unread === undefined ? 0 : int(t.unread, 'thread.unread'), updated_at: str(t.updated_at, 'thread.updated_at') }
    }),
  }
}

export function parseMarketThread(v: unknown): MarketThread {
  const o = rec(v, 'thread')
  const t = rec(o.thread, 'thread.thread')
  if (t.status !== 'open' && t.status !== 'closed') throw new ShapeError('thread.status')
  return {
    thread: { id: int(t.id, 'thread.id'), title: str(t.title, 'thread.title'), username: str(t.username, 'thread.username'),
      role: role(t.role, 'thread.role'), status: t.status, listing_id: int(t.listing_id, 'thread.listing_id') },
    peer: (() => {
      const p = o.peer === undefined ? {} : rec(o.peer, 'thread.peer')
      return { new_account: p.new_account === true, reports: typeof p.reports === 'number' ? int(p.reports, 'peer.reports') : 0 }
    })(),
    messages: arr(o.messages, 'thread.messages').map((raw) => {
      const m = rec(raw, 'message')
      const flags = (m.flags === undefined ? [] : arr(m.flags, 'message.flags'))
        .filter((f): f is MarketMessageFlag => f === 'prepay' || f === 'scam' || f === 'pressure' || f === 'link')
      return { mine: bool(m.mine, 'message.mine'), text: str(m.text, 'message.text'), at: str(m.at, 'message.at'), flags }
    }),
  }
}

export function parseMarketAck(v: unknown): Record<string, unknown> {
  return rec(v, 'ack')
}

// --- 👑 Super admin ---
function count(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}
function parseAdminTotals(v: unknown): AdminMarketTotals {
  const o = rec(v, 'admin.market')
  return { active: count(o.active), paused: count(o.paused), blocked: count(o.blocked), banned_users: count(o.banned_users), open_inquiries: count(o.open_inquiries) }
}
export function parseAdminOverview(v: unknown): AdminOverview {
  const o = rec(v, 'admin.overview')
  const s = rec(o.stats, 'admin.stats')
  return {
    stats: { users: count(s.users), pro_subscribers: count(s.pro_subscribers), channels: count(s.channels), posts_today: count(s.posts_today),
      pending_posts: count(s.pending_posts), stars_revenue: count(s.stars_revenue), sent: count(s.sent), failed: count(s.failed),
      cancelled: count(s.cancelled), sponsors: count(s.sponsors) },
    market: parseAdminTotals(o.market),
    countries: (() => {
      const c = rec(o.countries ?? {}, 'admin.countries')
      return {
        items: (Array.isArray(c.items) ? c.items : []).map((x) => {
          const r = rec(x, 'country')
          return { country: typeof r.country === 'string' ? r.country : '', users: count(r.users) }
        }),
        verified: count(c.verified), unverified: count(c.unverified), total: count(c.total),
      }
    })(),
  }
}
function parseAdminAd(v: unknown): AdminAd {
  const o = rec(v, 'admin.ad')
  const scope = o.scope === 'reply' ? 'reply' : 'channel'
  return { id: int(o.id, 'ad.id'), scope, text: str(o.text, 'ad.text'), button_text: str(o.button_text ?? '', 'ad.button_text'),
    button_url: str(o.button_url ?? '', 'ad.button_url'), is_active: bool(o.is_active, 'ad.is_active') }
}
export function parseAdminAdEnvelope(v: unknown): AdminAd {
  return parseAdminAd(rec(v, 'admin.ad.env').ad)
}
export function parseAdminAds(v: unknown): AdminAds {
  const o = rec(v, 'admin.ads')
  const s = rec(o.settings, 'ads.settings')
  const side = (x: unknown, what: string) => {
    const r = rec(x, what)
    return { enabled: bool(r.enabled, `${what}.enabled`), interval: int(r.interval, `${what}.interval`) }
  }
  const items = rec(o.items, 'ads.items')
  return {
    settings: { reply: side(s.reply, 'ads.reply'), channel: side(s.channel, 'ads.channel') },
    items: { channel: arr(items.channel, 'ads.items.channel').map(parseAdminAd), reply: arr(items.reply, 'ads.items.reply').map(parseAdminAd) },
  }
}
export function parseAdminSponsors(v: unknown): { items: AdminSponsor[] } {
  return { items: arr(rec(v, 'admin.sponsors').items, 'sponsors.items').map((x) => {
    const o = rec(x, 'sponsor')
    return { id: int(o.id, 'sponsor.id'), channel_id: str(o.channel_id, 'sponsor.channel_id'), title: str(o.title ?? '', 'sponsor.title'),
      username: str(o.username ?? '', 'sponsor.username'), invite_link: str(o.invite_link ?? '', 'sponsor.invite_link') }
  }) }
}
export function parseAdminMarket(v: unknown): AdminMarket {
  const o = rec(v, 'admin.market')
  return { totals: parseAdminTotals(o.totals), items: arr(o.items, 'market.items').map((x) => {
    const r = rec(x, 'listing')
    const status = r.status === 'blocked' ? 'blocked' : r.status === 'paused' ? 'paused' : 'active'
    return { id: int(r.id, 'listing.id'), title: str(r.title ?? '', 'listing.title'), username: str(r.username ?? '', 'listing.username'),
      owner_id: int(r.owner_id, 'listing.owner_id'), category: str(r.category ?? 'other', 'listing.category'), status,
      members: intOrNull(r.members, 'listing.members'), view_count: count(r.view_count), inquiry_count: count(r.inquiry_count),
      reports: count(r.reports), owner_banned: r.owner_banned === true }
  }) }
}
