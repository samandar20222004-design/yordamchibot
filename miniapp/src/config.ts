// Markaziy sozlamalar. Maxfiy qiymatlar (token, kalit) bu yerda BO'LMASLIGI shart:
// Mini App faqat Telegram `initData` ni yuboradi, server uni tekshiradi.
export const config = {
  /** Backend API manzili (bir domen). Dev/staging uchun VITE_API_BASE bilan almashtiriladi. */
  apiBase: (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1',
  /** Bitta so'rov uchun kutish (ms). Server tomonda ham 8 s chegara bor. */
  requestTimeoutMs: 10_000,
  /** AI generatsiya uchun (server chegarasi 30 s). */
  aiTimeoutMs: 35_000,
  /** Matn chegaralari (server bilan bir xil: backend writes.py). */
  maxPostChars: 4096,
  maxAiInputChars: 3500,
  /** Rejalashtirish: eng erta vaqt (server kamida 60 s talab qiladi). */
  minLeadMs: 120_000,
  /** Faqat GET uchun, faqat tarmoq/timeout/502/503/504 da. */
  maxGetRetries: 1,
  retryDelayMs: 600,
  /** Ma'lumot shu vaqtdan eski bo'lsa, ilova ko'ringanda jimgina yangilanadi. */
  staleAfterMs: 60_000,
  pageSize: 20,
  /** Backend "cheksiz" ni 999 bilan ifodalaydi (PRO limitlari). */
  unlimitedThreshold: 999,
} as const
