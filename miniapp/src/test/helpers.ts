import type { Me, ScheduledPage } from '../api/types'

export const ME: Me = {
  user: { id: 4242, name: 'Alice', username: 'alice', language: 'uz' },
  plan: { type: 'free', is_pro: false, expires_at: null, limits: { max_channels: 3, daily_ai_requests: 5, queued_posts: 5 } },
  tiers: {
    pro: { limits: { max_channels: 10, daily_ai_requests: 40, queued_posts: 100, voice_daily: 20 }, price_from_uzs: 19000 },
    ultra: { limits: { max_channels: 30, daily_ai_requests: 100, queued_posts: 500, voice_daily: 100 }, price_from_uzs: 39000 },
  },
  usage: { channels: 2, pending_posts: 3, ai_requests_today: 1, ai_credits: 5 },
  posts: { pending: 3, sent: 7, failed: 1, cancelled: 2 },
  next_post_at: '2026-10-14T09:30:00Z',
  bot: { username: 'PostAssistrobot' },
}

export const PAGE: ScheduledPage = {
  items: [
    { id: 1, channel_id: '-1001', channel_title: 'Kanal A', post_type: 'text', preview: 'Birinchi post matni',
      has_media: false, scheduled_time: '2026-10-14T09:30:00Z', number: 1, recurrence: 'none', status: 'pending' },
    { id: 2, channel_id: '-1001', channel_title: null, post_type: 'photo', preview: '',
      has_media: true, scheduled_time: '2026-10-15T10:00:00Z', number: 2, recurrence: 'daily', status: 'pending' },
  ],
  total: 2, limit: 20, offset: 0, has_more: false,
}

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

export function errorBody(code: string, requestId = 'req123', retryAfter: number | null = null, field: string | null = null) {
  return { error: { code, message: 'server message', request_id: requestId, retry_after: retryAfter, field } }
}
