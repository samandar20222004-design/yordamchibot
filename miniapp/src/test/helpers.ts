import { fireEvent } from '@testing-library/react'
import { readEditor } from '../components/RichTextField'
import { renderModel, setSelectionOffsets } from '../pages/richDom'
import { parseModel } from '../pages/richModel'
import type { Me, ScheduledPage } from '../api/types'

export const ME: Me = {
  user: { id: 4242, name: 'Alice', username: 'alice', language: 'uz' },
  plan: { type: 'free', is_pro: false, expires_at: null, limits: { max_channels: 3, daily_ai_requests: 5, queued_posts: 5 } },
  tiers: {
    free: { limits: { max_channels: 3, daily_ai_requests: 5, queued_posts: 40, voice_daily: 0 }, price_from_uzs: 0, periods: [] },
    pro: {
      limits: { max_channels: 10, daily_ai_requests: 40, queued_posts: 300, voice_daily: 20 }, price_from_uzs: 29000,
      periods: [
        { months: 1, days: 30, uzs: 29000, stars: 115, save_pct: 0 }, { months: 3, days: 90, uzs: 75000, stars: 300, save_pct: 13 },
        { months: 6, days: 180, uzs: 135000, stars: 535, save_pct: 22 }, { months: 12, days: 365, uzs: 245000, stars: 970, save_pct: 30 },
      ],
    },
    ultra: {
      limits: { max_channels: 30, daily_ai_requests: 100, queued_posts: 900, voice_daily: 100 }, price_from_uzs: 69000,
      periods: [
        { months: 1, days: 30, uzs: 69000, stars: 275, save_pct: 0 }, { months: 3, days: 90, uzs: 175000, stars: 695, save_pct: 16 },
        { months: 6, days: 180, uzs: 335000, stars: 1330, save_pct: 19 }, { months: 12, days: 365, uzs: 620000, stars: 2460, save_pct: 25 },
      ],
    },
  },
  usage: { channels: 2, pending_posts: 3, ai_requests_today: 1, ai_credits: 5 },
  settings: { notifications: { notify_scheduled: true, notify_news: false, notify_morning_digest: true, notify_uzbek_calendar: true } },
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

/** Muharrir (contenteditable) testlari: Telegram HTML yozish/o'qish. */
export function setEditor(el: HTMLElement, html: string): void {
  renderModel(el, parseModel(html))
  fireEvent.input(el)
}
export const editorValue = (el: HTMLElement): string => readEditor(el)

/** Muharrirdagi [a, b) matn oralig'ini tanlaydi. */
export function selectText(el: HTMLElement, a: number, b: number): void {
  setSelectionOffsets(el, a, b)
  fireEvent(document, new Event('selectionchange'))
}
