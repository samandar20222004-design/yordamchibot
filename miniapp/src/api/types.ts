export type Lang = 'uz' | 'ru' | 'en'

export interface PlanLimits {
  max_channels: number
  daily_ai_requests: number
  queued_posts: number
  /** Ovozli rejalash (kuniga); eski serverda bo'lmasligi mumkin. */
  voice_daily?: number
}

/** Mijozga ko'rsatiladigan tarif: limitlar va 1 oylik narx (so'm) — server (config) bilan bir manba. */
export interface TierInfo {
  limits: PlanLimits
  price_from_uzs: number
}

export interface Plan {
  type: string
  is_pro: boolean
  expires_at: string | null
  limits: PlanLimits
}

export interface PostCounts {
  pending: number
  sent: number
  failed: number
  cancelled: number
}

export type AiStyle = 'sales' | 'premium' | 'casual' | 'ads' | 'informative'
export const AI_STYLES: readonly AiStyle[] = ['sales', 'premium', 'casual', 'ads', 'informative']

export interface Me {
  user: { id: number; name: string | null; username: string | null; language: Lang }
  plan: Plan
  tiers?: { pro: TierInfo; ultra: TierInfo }
  usage: { channels: number; pending_posts: number; ai_requests_today: number; ai_credits: number }
  posts: PostCounts
  next_post_at: string | null
  bot: { username: string | null }
}

export interface Channel {
  id: string
  title: string | null
  /** Rejadagi (kutilayotgan) postlar soni. */
  pending_posts?: number
  /** Oxirgi (eskirmagan) obunachi snapshot'i; yo'q bo'lsa `null` (0 emas). */
  members?: number | null
  members_as_of?: string | null
}

export type Confidence = 'none' | 'low' | 'medium' | 'high'

export interface MemberPoint {
  date: string
  member_count: number
}

/** Kanal analitikasi: faqat HAQIQIY ma'lumot; noma'lum qiymat `null` / `available: false` (0 emas). */
export interface ChannelAnalytics {
  channel: { id: string; title: string }
  members: {
    current: number | null
    as_of: string | null
    delta_7d: number | null
    delta_30d: number | null
    points: number
    span_days: number
    confidence: Confidence
    stale: boolean
    source: string | null
    collected_at: string | null
    history: MemberPoint[]
  }
  /** Botning O'Z postlari (kanalning haqiqiy natijasi emas). */
  posts: { sent_7d: number; sent_30d: number; sent_all: number; pending: number; failed: number; unknown: number }
  views: { available: boolean; with_views: number; avg: number | null; max: number | null; collected_at: string | null; sources: string[] }
}

export interface ChannelList {
  items: Channel[]
  total: number
}

export interface ScheduledPost {
  id: number
  channel_id: string
  channel_title: string | null
  post_type: string
  preview: string
  has_media: boolean
  scheduled_time: string | null
  number: number | null
  recurrence: string | null
  status: string
  /** Takrorlanish tafsiloti (Toshkent vaqti): interval -> kunlar soni, weekdays -> hafta kunlari bitmaski, weekly -> 0..6. */
  recurrence_day?: number | null
  recurrence_time?: string | null
  /** Faqat bitta postni olishda (tahrirlash uchun to'liq matn); ro'yxatda yo'q. */
  text?: string
}

export interface ScheduledPage {
  items: ScheduledPost[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

/** Kalendar oralig'idagi kutilayotgan postlar; `truncated` = server chegarasi (500) sabab ro'yxat to'liq emas. */
export interface CalendarData {
  items: ScheduledPost[]
  truncated: boolean
}

/** Server xato kodlari (telegram_bot/miniapp_api/errors.py) + mijoz tomoni kodlari. */
export type ErrorCode =
  | 'bad_request' | 'https_required' | 'unauthorized' | 'auth_expired' | 'not_registered'
  | 'beta_access_required' | 'not_found' | 'method_not_allowed' | 'rate_limited'
  | 'internal_error' | 'service_unavailable' | 'auth_unavailable'
  | 'invalid_input' | 'schedule_in_past' | 'unsupported_media_type' | 'payload_too_large'
  | 'channel_not_found' | 'not_editable' | 'queue_limit_reached' | 'ai_limit_reached'
  | 'ai_unavailable' | 'upload_failed' | 'templates_limit_reached' | 'save_failed' | 'draft_not_found' | 'media_unavailable' | 'caption_too_long'
  | 'network' | 'timeout' | 'bad_response' | 'no_telegram'

export interface PostResult {
  post: ScheduledPost
  created: boolean
  delivery: 'scheduled' | 'immediate'
}

export interface AiResult {
  text: string
  style: AiStyle
}

export type PostFilter = 'pending' | 'history'

/** Botdan kelgan qoralama (media `file_id` mijozga berilmaydi — faqat tur). */
export interface DraftMedia {
  type: string
  previewable: boolean
  count: number | null
}

export interface Draft {
  post_type: string
  text: string
  button_text: string | null
  button_url: string | null
  channel_id: string | null
  reactions: boolean
  delete_after_hours: number
  media: DraftMedia | null
  updated_at: string | null
}

export interface CreatePostInput {
  channel_id: string
  text: string
  scheduled_at?: string
  send_now?: boolean
  button_text?: string
  button_url?: string
  use_draft?: boolean
  recurrence?: RecurrenceInput
}

export type RecurrenceType = 'daily' | 'weekly' | 'interval' | 'weekdays'

/** `time` — Toshkent vaqti (HH:MM); `day`: daily -> null, weekly -> 0..6, interval -> 2..30, weekdays -> bitmask 1..127 (Du=1). */
export interface RecurrenceInput {
  type: RecurrenceType
  day: number | null
  time: string
}

export interface ScheduleProposal {
  scheduled_at: string
  recurrence: RecurrenceInput | null
}

export type ScheduleParseResult =
  | { ok: true; source: 'rules' | 'ai'; proposal: ScheduleProposal }
  | { ok: false; reason: string }

export interface Template {
  id: number
  name: string
  text: string
  created_at: string
}

export interface TemplateList {
  items: Template[]
  limit: number
}
