export type Lang = 'uz' | 'ru' | 'en'

export interface PlanLimits {
  max_channels: number
  daily_ai_requests: number
  queued_posts: number
  /** Ovozli rejalash (kuniga); eski serverda bo'lmasligi mumkin. */
  voice_daily?: number
  /** Jamoa: egasidan tashqari nechta yordamchi akkaunt (PRO/FREE: 0, ULTRA: 2). Eski serverda bo'lmasligi mumkin. */
  team_seats?: number
}

/** Mijozga ko'rsatiladigan tarif: limitlar va 1 oylik narx (so'm) — server (config) bilan bir manba. */
export interface TierPeriod {
  months: number
  days: number
  uzs: number
  stars: number
  /** Xalqaro (dollar) narx; Telegram Stars shu narxga hisoblanadi. */
  usd: number
  /** 1 oylikka nisbatan HAQIQIY tejam (butun foiz). */
  save_pct: number
}

export interface TierInfo {
  limits: PlanLimits
  price_from_uzs: number
  /** Davrlar (1/3/6/12 oy); FREE uchun bo'sh. */
  periods: TierPeriod[]
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
  /** «Men kimman?» tanlovi: 'owner' (o'zim yuritaman), 'helper' (yordamchiman) yoki tanlanmagan. */
  work_mode?: 'owner' | 'helper' | null
  user: { id: number; name: string | null; username: string | null; language: Lang; timezone?: string }
  plan: Plan
  /** Narx mintaqasi: 'uz' (so'm) yoki 'intl' (dollar). Eski serverda yo'q = 'uz'. */
  pay_region?: 'uz' | 'intl'
  tiers?: { free?: TierInfo; pro: TierInfo; ultra: TierInfo }
  usage: { channels: number; pending_posts: number; ai_requests_today: number; ai_credits: number }
  posts: PostCounts
  /** Bildirishnoma tanlovlari (eski serverda yo'q bo'lishi mumkin). */
  settings?: { notifications: NotificationSettings }
  next_post_at: string | null
  bot: { username: string | null }
  /** Super admin rejimiga ruxsat (server hal qiladi; eski serverda yo'q = false). */
  is_admin?: boolean
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
  /** Faqat bitta postni olishda: media elementlari (albom bo'lsa ko'p). */
  media_items?: MediaItem[]
  scheduled_time: string | null
  number: number | null
  recurrence: string | null
  status: string
  /** Takrorlanish tafsiloti (Toshkent vaqti): interval -> kunlar soni, weekdays -> hafta kunlari bitmaski, weekly -> 0..6. */
  recurrence_day?: number | null
  recurrence_time?: string | null
  /** `twice` uchun ikkinchi vaqt (HH:MM). */
  recurrence_time2?: string | null
  /** Faqat bitta postni olishda (tahrirlash uchun to'liq matn); ro'yxatda yo'q. */
  text?: string
  /** Faqat bitta postni olishda: inline tugma. */
  button_text?: string | null
  button_url?: string | null
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
  | 'not_found' | 'method_not_allowed' | 'rate_limited'
  | 'internal_error' | 'service_unavailable' | 'auth_unavailable'
  | 'invalid_input' | 'schedule_in_past' | 'unsupported_media_type' | 'payload_too_large'
  | 'channel_not_found' | 'not_editable' | 'queue_limit_reached' | 'ai_limit_reached'
  | 'ai_unavailable' | 'upload_failed' | 'templates_limit_reached' | 'save_failed' | 'draft_not_found' | 'media_unavailable' | 'caption_too_long' | 'album_full' | 'album_mixed'
  | 'market_private' | 'market_not_admin' | 'market_limit' | 'market_blocked' | 'inquiry_limit' | 'inquiry_blocked' | 'inquiry_own' | 'inquiry_exists' | 'thread_closed' | 'thread_full' | 'message_card' | 'message_wallet' | 'message_link' | 'message_spam' | 'user_banned' | 'owner_busy' | 'phone_required' | 'admin_only' | 'sponsor_not_found' | 'sponsor_not_admin' | 'promo_exists' | 'user_unknown' | 'workspace_denied' | 'team_no_seats' | 'team_seats_full' | 'invite_invalid'
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
export interface MediaItem {
  type: string
  previewable: boolean
}

/** Bildirishnoma sozlamalari (botdagi `user_settings` kalitlari bilan bir xil). */
export const NOTIFICATION_KEYS = ['notify_scheduled', 'notify_news', 'notify_morning_digest', 'notify_uzbek_calendar'] as const
export type NotificationKey = (typeof NOTIFICATION_KEYS)[number]
export type NotificationSettings = Record<NotificationKey, boolean>

export interface DraftMedia {
  type: string
  previewable: boolean
  count: number | null
  /** Albomdagi (yoki yakka) media elementlari — `file_id`siz. */
  items?: MediaItem[]
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

export interface UpdatePostInput {
  text?: string
  scheduled_at?: string
  /** Ikkalasi ham bo'sh satr = tugmani olib tashlash. */
  button_text?: string
  button_url?: string
  /** Takrorlanuvchi postning kun vaqti (HH:MM) va kuniga ikkinchi vaqt (HH:MM; bo'lmasa bitta vaqt). */
  recurrence_time?: string
  recurrence_time2?: string
}

export type RecurrenceType = 'daily' | 'weekly' | 'interval' | 'weekdays' | 'twice' | 'monthly'

/** `time` — Toshkent vaqti (HH:MM); `day`: daily -> null, weekly -> 0..6, interval -> 2..30, weekdays -> bitmask 1..127 (Du=1), monthly -> oyning kuni 1..31. */
export interface RecurrenceInput {
  type: RecurrenceType
  day: number | null
  time: string
  /** Faqat `twice` (kuniga ikki vaqt: ertalab va kechqurun): ikkinchi vaqt (HH:MM). */
  time2?: string
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

// --- 💰 Reklama birjasi (telegram_bot/miniapp_api/market.py) ---
export const MARKET_CATEGORIES = ['news', 'tech', 'business', 'education', 'entertainment', 'lifestyle', 'sport', 'shop', 'auto', 'other'] as const
export type MarketCategory = (typeof MARKET_CATEGORIES)[number]
export type MarketSort = 'm' | 'p' | 'e'
export type MarketBadge = 'growing' | 'engaged' | 'active'

export interface MarketListing {
  id: number
  title: string
  username: string
  category: MarketCategory
  /** `currency` birligida (so'm yoki dollar); `null` — kelishiladi */
  price: number | null
  /** Narx valyutasi: egasi O'zbekiston raqami bilan tasdiqlangan bo'lsa 'UZS', aks holda 'USD'. */
  currency: 'UZS' | 'USD'
  /** E'lon mamlakati (ISO-2); eski e'londa `null` (faqat global ro'yxatda). */
  country: string | null
  description: string | null
  members: number | null
  avg_views: number | null
  er_percent: number | null
  growth_30d: number | null
  posts_30d: number | null
  stats_updated_at: string | null
  badges: MarketBadge[]
  /** Faqat egasiga: */
  status?: 'active' | 'paused' | 'blocked'
  channel_id?: string
  view_count?: number
  inquiry_count?: number
}

export interface MarketSummary {
  listings: number
  inquiries: number
  categories: MarketCategory[]
  max_listings: number
  price_min: number
  price_max: number
  price_min_usd: number
  price_max_usd: number
  /** Ko'rayotgan foydalanuvchi: tasdiqlangan mamlakat ('' = tasdiqlanmagan) va u e'lon qo'yganda ishlatiladigan valyuta. */
  viewer: { country: string; currency: 'UZS' | 'USD' }
  description_max: number
  message_min: number
  message_max: number
}

export interface MarketCatalog {
  items: MarketListing[]
  total: number
  page: number
  pages: number
  page_size: number
  viewer_country: string
  filter: 'all' | 'mine'
}

export interface MarketMineItem {
  channel_id: string
  title: string
  listing: MarketListing | null
}

export interface MarketMine {
  items: MarketMineItem[]
  max_listings: number
}

export interface MarketThreadItem {
  id: number
  title: string
  role: 'owner' | 'advertiser'
  unread: number
  updated_at: string
}

export interface MarketThread {
  thread: { id: number; title: string; username: string; role: 'owner' | 'advertiser'; status: 'open' | 'closed'; listing_id: number }
  /** Ikkinchi tomon haqida ishonch belgilari: yangi hisob, shikoyatlar soni. */
  peer: { new_account: boolean; reports: number }
  messages: Array<{ mine: boolean; text: string; at: string; flags: MarketMessageFlag[] }>
}

export type MarketMessageFlag = 'prepay' | 'scam' | 'pressure' | 'link'

export interface MarketListingInput {
  channel_id: string
  category: MarketCategory
  price: number | null
  description: string | null
}

// --- 👑 Super admin ---
export interface AdminOverview {
  stats: { users: number; pro_subscribers: number; channels: number; posts_today: number; pending_posts: number
    stars_revenue: number; sent: number; failed: number; cancelled: number; sponsors: number }
  market: AdminMarketTotals
  /** Foydalanuvchilar mamlakatlar bo'yicha (telefoni o'z kontakti orqali tasdiqlanganlar) va tasdiqlanmaganlar soni. */
  countries: { items: Array<{ country: string; users: number }>; verified: number; unverified: number; total: number }
}
export interface AdminMarketTotals { active: number; paused: number; blocked: number; banned_users: number; open_inquiries: number }
export type AdSupport = 'channel' | 'reply'
export interface AdminAd { id: number; scope: AdSupport; text: string; button_text: string; button_url: string; is_active: boolean }
export interface AdminAdSettings { reply: { enabled: boolean; interval: number }; channel: { enabled: boolean; interval: number } }
export interface AdminAds { settings: AdminAdSettings; items: Record<AdSupport, AdminAd[]> }
export interface AdminSponsor { id: number; channel_id: string; title: string; username: string; invite_link: string }
export interface AdminListing {
  id: number; title: string; username: string; owner_id: number; category: string; status: 'active' | 'paused' | 'blocked'
  members: number | null; view_count: number; inquiry_count: number; reports: number; owner_banned: boolean
}
export interface AdminMarket { totals: AdminMarketTotals; items: AdminListing[] }
export interface AdminAdInput { scope: AdSupport; text: string; button_text?: string; button_url?: string }

// --- 👑 Super admin: promo-kodlar va boshqaruv ---
export type AdminPromoStatus = 'active' | 'used_up' | 'expired' | 'disabled'
export interface AdminPromo {
  code: string; plan: string; days: number; max_uses: number | null; used: number; left: number | null
  status: AdminPromoStatus; is_active: boolean; expires_at: string | null; created_at: string | null
}
export interface AdminPromoTotals {
  total: number; active: number; used_up: number; expired: number; disabled: number; redemptions: number; remaining_uses: number; unlimited: number
}
export interface AdminPromos { totals: AdminPromoTotals; items: AdminPromo[] }
export interface AdminPromoDetail { promo: AdminPromo; redeemers: Array<{ user_id: number; at: string | null }> }
export interface AdminPromoInput { code: string; days: number; max_uses: number | null; plan: 'pro' | 'ultra' }
export interface AdminAuditItem { admin_id: number | null; action: string; target_type: string; target_id: string; at: string | null }
export interface AdminFeatureRow { name: string; count: number; users: number; rate: number }
export interface AdminFeatures { total_users: number | null; most_used: AdminFeatureRow[]; least_used: AdminFeatureRow[] }
export interface AdminHealth { ready: boolean; checks: Record<string, string>; uptime: string }
export interface AdminRoles { items: Array<{ user_id: number; role: string }>; choices: string[] }

// --- 👥 Jamoa va ish joyi ---
export type TeamRole = 'editor' | 'scheduler' | 'analyst'
export const TEAM_ROLES: readonly TeamRole[] = ['editor', 'scheduler', 'analyst']
export interface TeamMember { user_id: number; name: string; username: string; role: TeamRole; active: boolean; since: string | null }
export interface TeamInvite { id: number; role: TeamRole; expires_at: string | null }
export interface TeamChannel { channel_id: string; title: string; members: TeamMember[]; invites: TeamInvite[] }
export interface TeamSeats { plan: string; limit: number; used: number; pending: number; free: number }
export interface Workspace {
  owner_id: number; owner_name: string
  /** Egasining tarifi jamoani bermaydi (ULTRA tugagan) — ish joyi vaqtincha yopiq. */
  suspended: boolean
  channels: Array<{ channel_id: string; title: string; role: TeamRole }>
}
export interface TeamOverview {
  mode: 'owner' | 'helper' | null
  seats: TeamSeats
  can_invite: boolean
  channels: TeamChannel[]
  workspaces: Workspace[]
}
export interface TeamInviteCreated { id: number; token: string; role: TeamRole; channel_id: string; expires_at: string | null }
