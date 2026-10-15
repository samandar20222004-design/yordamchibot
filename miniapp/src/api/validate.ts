// Server javoblarini ish vaqtida tekshirish (kichik qo'lda validatorlar: yangi kutubxona yo'q).
import { AI_STYLES } from './types'
import type { PlanLimits, TierInfo, AiResult, Template, TemplateList, CalendarData, Channel, ChannelAnalytics, ChannelList, Confidence, Lang, Me, Plan, PostCounts, PostResult, RecurrenceInput, ScheduleParseResult, ScheduledPage, ScheduledPost, Draft } from './types'

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
  return { limits: parseLimits(rec(t.limits, `${what}.limits`)), price_from_uzs: int(t.price_from_uzs, `${what}.price`) }
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
    },
    plan: parsePlan(o.plan),
    ...(o.tiers === undefined ? {} : { tiers: { pro: parseTier(rec(o.tiers, 'tiers').pro, 'tiers.pro'), ultra: parseTier(rec(o.tiers, 'tiers').ultra, 'tiers.ultra') } }),
    usage: {
      channels: int(usage.channels, 'usage.channels'),
      pending_posts: int(usage.pending_posts, 'usage.pending_posts'),
      ai_requests_today: int(usage.ai_requests_today, 'usage.ai_requests_today'),
      ai_credits: int(usage.ai_credits, 'usage.ai_credits'),
    },
    posts: parseCounts(o.posts),
    next_post_at: strOrNull(o.next_post_at, 'next_post_at'),
    bot: { username: strOrNull(bot.username, 'bot.username') },
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
