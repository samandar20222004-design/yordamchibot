// Server javoblarini ish vaqtida tekshirish (kichik qo'lda validatorlar: yangi kutubxona yo'q).
import { AI_STYLES } from './types'
import type { AiResult, Channel, ChannelList, Lang, Me, Plan, PostCounts, PostResult, ScheduledPage, ScheduledPost } from './types'

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
    limits: {
      max_channels: int(l.max_channels, 'limits.max_channels'),
      daily_ai_requests: int(l.daily_ai_requests, 'limits.daily_ai_requests'),
      queued_posts: int(l.queued_posts, 'limits.queued_posts'),
    },
  }
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
  return { id: str(c.id, 'channel.id'), title: strOrNull(c.title, 'channel.title') }
}

export function parseChannels(v: unknown): ChannelList {
  const o = rec(v, 'channels')
  return { items: arr(o.items, 'items').map(parseChannel), total: int(o.total, 'total') }
}

export function parsePost(v: unknown): ScheduledPost {
  const p = rec(v, 'post')
  return {
    ...(p.text === undefined ? {} : { text: str(p.text, 'post.text') }),
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
