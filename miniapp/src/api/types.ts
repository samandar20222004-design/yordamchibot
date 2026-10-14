export type Lang = 'uz' | 'ru' | 'en'

export interface PlanLimits {
  max_channels: number
  daily_ai_requests: number
  queued_posts: number
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
  usage: { channels: number; pending_posts: number; ai_requests_today: number; ai_credits: number }
  posts: PostCounts
  next_post_at: string | null
  bot: { username: string | null }
}

export interface Channel {
  id: string
  title: string | null
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

/** Server xato kodlari (telegram_bot/miniapp_api/errors.py) + mijoz tomoni kodlari. */
export type ErrorCode =
  | 'bad_request' | 'https_required' | 'unauthorized' | 'auth_expired' | 'not_registered'
  | 'beta_access_required' | 'not_found' | 'method_not_allowed' | 'rate_limited'
  | 'internal_error' | 'service_unavailable' | 'auth_unavailable'
  | 'invalid_input' | 'schedule_in_past' | 'unsupported_media_type' | 'payload_too_large'
  | 'channel_not_found' | 'not_editable' | 'queue_limit_reached' | 'ai_limit_reached'
  | 'ai_unavailable' | 'save_failed'
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
