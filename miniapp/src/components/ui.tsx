import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { ApiClientError } from '../api/client'
import { closeApp, isValidBotUsername, openBot } from '../telegram'
import { useI18n, type MessageKey } from '../i18n'
import { Icon, type IconName } from './Icon'

export function Button({
  variant = 'secondary', busy = false, block = false, icon, children, className, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
  busy?: boolean
  block?: boolean
  icon?: IconName
}) {
  return (
    <button type="button" {...rest} disabled={rest.disabled || busy} aria-busy={busy || undefined}
      className={`btn btn-${variant}${block ? ' btn-block' : ''}${children ? '' : ' icon-btn'}${className ? ` ${className}` : ''}`}>
      {icon && <Icon name={icon} size={20} />}
      {children}
    </button>
  )
}

function animationsAllowed(): boolean {
  try {
    return typeof window.matchMedia === 'function' && typeof window.requestAnimationFrame === 'function'
      && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** Son 0 dan qiymatgacha silliq o'sadi (birinchi ko'rinishda). Harakat kamaytirilgan bo'lsa darhol yakuniy qiymat. */
export function CountUp({ value, durationMs = 900 }: { value: number; durationMs?: number }) {
  const [shown, setShown] = useState(() => (animationsAllowed() && value > 0 ? 0 : value))
  useEffect(() => {
    if (!animationsAllowed() || value <= 0) { setShown(value); return }
    let raf = 0
    const start = performance.now()
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / durationMs)
      setShown(Math.round(value * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, durationMs])
  return <>{shown}</>
}

export function Badge({ pro = false, children }: { pro?: boolean; children: ReactNode }) {
  return <span className={`badge${pro ? ' badge-pro' : ''}`}>{children}</span>
}

export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />
}

export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  const { t } = useI18n()
  return (
    <div className="card" role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">{t('common.loading')}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={i === 0 ? 22 : 16} width={i === 0 ? '55%' : `${90 - i * 12}%`} />
      ))}
    </div>
  )
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="state">
      <h2>{title}</h2>
      <p>{body}</p>
      {action}
    </div>
  )
}

const ERROR_KEYS: Record<string, MessageKey> = {
  network: 'err.network',
  timeout: 'err.timeout',
  bad_response: 'err.bad_response',
  unauthorized: 'err.unauthorized',
  auth_expired: 'err.auth_expired',
  auth_unavailable: 'err.auth_unavailable',
  not_registered: 'err.not_registered',
  rate_limited: 'err.rate_limited',
  service_unavailable: 'err.service_unavailable',
  https_required: 'err.https_required',
  internal_error: 'err.internal_error',
  invalid_input: 'err.invalid_input',
  schedule_in_past: 'err.schedule_in_past',
  unsupported_media_type: 'err.unsupported_media_type',
  payload_too_large: 'err.payload_too_large',
  channel_not_found: 'err.channel_not_found',
  not_editable: 'err.not_editable',
  queue_limit_reached: 'err.queue_limit_reached',
  ai_limit_reached: 'err.ai_limit_reached',
  ai_unavailable: 'err.ai_unavailable',
  templates_limit_reached: 'err.templates_limit_reached',
  upload_failed: 'err.upload_failed',
  save_failed: 'err.save_failed',
  draft_not_found: 'err.draft_not_found',
  media_unavailable: 'err.media_unavailable',
  caption_too_long: 'err.caption_too_long',
  album_full: 'err.album_full',
  album_mixed: 'err.album_mixed',
  market_private: 'err.market_private',
  market_not_admin: 'err.market_not_admin',
  market_limit: 'err.market_limit',
  market_blocked: 'err.market_blocked',
  inquiry_limit: 'err.inquiry_limit',
  inquiry_blocked: 'err.inquiry_blocked',
  inquiry_own: 'err.inquiry_own',
  inquiry_exists: 'err.inquiry_exists',
  thread_closed: 'err.thread_closed',
  thread_full: 'err.thread_full',
  message_card: 'err.message_card',
  message_wallet: 'err.message_wallet',
  message_link: 'err.message_link',
  message_spam: 'err.message_spam',
  user_banned: 'err.user_banned',
  owner_busy: 'err.owner_busy',
  phone_required: 'err.phone_required',
  admin_only: 'err.admin_only',
  sponsor_not_found: 'err.sponsor_not_found',
  sponsor_not_admin: 'err.sponsor_not_admin',
  promo_exists: 'err.promo_exists',
  user_unknown: 'err.user_unknown',
  bad_request: 'err.bad_request',
  not_found: 'err.not_found',
  method_not_allowed: 'err.method_not_allowed',
}
/** Qayta urinish foyda bermaydigan kodlar: ilovani qayta ochish yoki botda amal kerak. */
const FATAL = new Set(['unauthorized', 'auth_expired', 'https_required', 'not_registered'])

export function errorMessageKey(code: string): MessageKey {
  return ERROR_KEYS[code] ?? 'err.generic'
}

export function ErrorState({ error, onRetry, botUsername }: {
  error: ApiClientError; onRetry?: () => void; botUsername?: string | null
}) {
  const { t } = useI18n()
  const fatal = FATAL.has(error.code)
  const needsBot = error.code === 'not_registered'
  return (
    <div className="state state-error" role="alert">
      <h2>{t(errorMessageKey(error.code))}</h2>
      {error.requestId && <p className="muted">{t('err.reference', { id: error.requestId })}</p>}
      {needsBot && openBotAvailable(botUsername) && (
        <Button variant="primary" icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
      )}
      {fatal && !(needsBot && openBotAvailable(botUsername)) && (
        <Button variant="primary" onClick={closeApp}>{t('common.close')}</Button>
      )}
      {!fatal && onRetry && <Button variant="primary" icon="refresh" onClick={onRetry}>{t('common.retry')}</Button>}
    </div>
  )
}

export function openBotAvailable(username: string | null | undefined): boolean {
  return isValidBotUsername(username)
}

export function InlineWarning({ error, onRetry }: { error: ApiClientError; onRetry: () => void }) {
  const { t } = useI18n()
  return (
    <div className="banner banner-warn" role="alert">
      {t(errorMessageKey(error.code))}{' '}
      <button type="button" className="btn btn-ghost" onClick={onRetry}>{t('common.retry')}</button>
    </div>
  )
}

/** Forma ostidagi xato (qayta urinish tugmasisiz): xabar kod bo'yicha tarjima qilinadi. */
export function FormError({ error }: { error: ApiClientError }) {
  const { t } = useI18n()
  return (
    <div className="banner banner-error" role="alert">
      {t(errorMessageKey(error.code))}
      {error.requestId && <span className="muted"> · {t('err.reference', { id: error.requestId })}</span>}
    </div>
  )
}
