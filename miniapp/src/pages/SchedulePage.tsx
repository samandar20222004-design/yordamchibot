import { useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import type { PostFilter, ScheduledPost } from '../api/types'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, EmptyState, ErrorState, FormError, InlineWarning, LoadingBlock, errorMessageKey, openBotAvailable } from '../components/ui'
import { config } from '../config'
import { useScheduleFeed } from '../hooks/useScheduleFeed'
import { toClientError } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { openBot } from '../telegram'
import { CalendarView } from './CalendarView'
import { groupByDay, isFutureEnough, isoToLocalInput, localInputToIso } from './format'
import { describeRecurrence } from './recurrence'

const SENT = new Set(['posted', 'published', 'completed'])
export function statusKey(status: string): MessageKey {
  if (status === 'pending') return 'status.pending'
  if (status === 'processing') return 'status.processing'
  if (SENT.has(status)) return 'status.sent'
  if (status === 'failed') return 'status.failed'
  if (status === 'cancelled') return 'status.cancelled'
  return 'status.other'
}

function PostItem({ post, actions, onEdit, onCancel }: {
  post: ScheduledPost; actions: boolean; onEdit: (p: ScheduledPost) => void; onCancel: (p: ScheduledPost) => void
}) {
  const { t, formatTime, formatDateTime } = useI18n()
  const repeats = !!post.recurrence && post.recurrence !== 'none'
  return (
    <li className="item">
      <div className="item-top">
        <span className="item-time">
          {post.scheduled_time ? (actions ? formatTime(post.scheduled_time) : formatDateTime(post.scheduled_time)) : t('common.none')}
        </span>
        {post.number !== null && <span className="muted">#{post.number}</span>}
      </div>
      <p className="item-text">{post.preview || t('schedule.noText')}</p>
      <div className="item-meta">
        <span>{post.channel_title || t('schedule.unknownChannel')}</span>
        {!actions && <Badge>{t(statusKey(post.status))}</Badge>}
        {post.has_media && <Badge>{t('schedule.media')}</Badge>}
        {repeats && <Badge>{describeRecurrence({ type: post.recurrence ?? '', day: post.recurrence_day, time: post.recurrence_time }, t) ?? t('schedule.repeats')}</Badge>}
      </div>
      {actions && (
        <div className="item-actions">
          <Button onClick={() => onEdit(post)}>{t('schedule.edit')}</Button>
          <Button variant="ghost" className="btn-danger-text" onClick={() => onCancel(post)}>{t('schedule.cancel')}</Button>
        </div>
      )}
    </li>
  )
}

function EditDialog({ post, onClose, onSaved }: {
  post: ScheduledPost; onClose: () => void; onSaved: () => void
}) {
  const { client, notify } = useAppData()
  const { t } = useI18n()
  const [text, setText] = useState<string | null>(null)
  const [original, setOriginal] = useState('')
  const [when, setWhen] = useState(() => isoToLocalInput(post.scheduled_time))
  const [loadError, setLoadError] = useState<ApiClientError | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [invalid, setInvalid] = useState<'text' | 'when' | null>(null)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const recurring = !!post.recurrence && post.recurrence !== 'none'
  // Media postda matn = sarlavha (caption): Telegram 1024 dan kesadi, shuning uchun tahrirda ham shu chegara.
  const textMax = post.has_media ? config.maxCaptionChars : config.maxPostChars
  const originalWhen = useRef(isoToLocalInput(post.scheduled_time))

  useEffect(() => {
    const ctl = new AbortController()
    client.post(post.id, ctl.signal).then(
      (full) => { if (!ctl.signal.aborted) { setText(full.text ?? full.preview); setOriginal(full.text ?? full.preview) } },
      (e: unknown) => { if (!ctl.signal.aborted) setLoadError(toClientError(e)) },
    )
    return () => ctl.abort()
  }, [client, post.id])

  const save = async () => {
    if (inFlight.current || text === null) return
    const trimmed = text.trim()
    const textChanged = trimmed !== original.trim()
    // Uzunlik FAQAT matn o'zgargan bo'lsa tekshiriladi: eski uzun matnli postning vaqtini o'zgartirish bloklanmasin.
    if (!trimmed || (textChanged && trimmed.length > textMax)) { setInvalid('text'); return }
    const timeChanged = !recurring && when !== originalWhen.current
    if (timeChanged && !isFutureEnough(when)) { setInvalid('when'); return }
    if (!textChanged && !timeChanged) { onClose(); return }
    inFlight.current = true
    setBusy(true)
    setError(null)
    setInvalid(null)
    try {
      await client.updatePost(post.id, {
        ...(textChanged ? { text: trimmed } : {}),
        ...(timeChanged ? { scheduled_at: localInputToIso(when) ?? '' } : {}),
      })
      notify(t('schedule.saved'))
      onSaved()
    } catch (e) {
      const err = toClientError(e)
      setError(err)
      if (err.code === 'not_editable') onSaved() // holat o'zgargan: ro'yxatni yangilash
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  return (
    <Dialog title={t('schedule.editTitle')} onClose={onClose} busy={busy}>
      {loadError ? <FormError error={loadError} /> : text === null ? <p className="muted">{t('schedule.loadingText')}</p> : (
        <>
          <label className="field" htmlFor="edit-text">{t('post.text')}</label>
          <textarea id="edit-text" className="input" rows={8} value={text} maxLength={textMax}
            aria-invalid={invalid === 'text' || undefined} onChange={(e) => { setText(e.target.value); setInvalid(null) }} />
          <p className="muted">{t('post.counter', { n: text.length, max: textMax })}</p>
          {invalid === 'text' && <p className="field-error" role="alert">{t(post.has_media ? 'post.errCaption' : 'post.errText', { max: textMax })}</p>}
          {recurring ? <p className="muted">{t('schedule.recurringNote')}</p> : (
            <>
              <label className="field" htmlFor="edit-when">{t('post.date')}</label>
              <input id="edit-when" className="input" type="datetime-local" value={when}
                aria-invalid={invalid === 'when' || undefined} onChange={(e) => { setWhen(e.target.value); setInvalid(null) }} />
              {invalid === 'when' && <p className="field-error" role="alert">{t('post.errWhen')}</p>}
            </>
          )}
          {error && <FormError error={error} />}
        </>
      )}
      <div className="dialog-actions">
        <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
        <Button variant="primary" busy={busy} disabled={text === null} onClick={() => void save()}>{t('schedule.save')}</Button>
      </div>
    </Dialog>
  )
}

export function SchedulePage() {
  const { client, feed: upcoming, me, notify, botUsername } = useAppData()
  const { t, formatDate } = useI18n()
  const [view, setView] = useState<PostFilter | 'calendar'>('pending')
  const [calendarKey, setCalendarKey] = useState(0)
  const history = useScheduleFeed(client, view === 'history', 'history')
  const feed = view === 'history' ? history : upcoming
  const [editing, setEditing] = useState<ScheduledPost | null>(null)
  const [cancelling, setCancelling] = useState<ScheduledPost | null>(null)
  const [cancelBusy, setCancelBusy] = useState(false)
  const cancelInFlight = useRef(false)

  const refreshAll = () => { upcoming.reload(); if (view === 'history') history.reload(); setCalendarKey((k) => k + 1); me.reload() }

  const confirmCancel = async () => {
    if (!cancelling || cancelInFlight.current) return
    cancelInFlight.current = true
    setCancelBusy(true)
    try {
      await client.cancelPost(cancelling.id)
      notify(t('schedule.cancelled'))
    } catch (e) {
      const err: ApiClientError = toClientError(e)
      notify(t(errorMessageKey(err.code)), 'error')
    } finally {
      cancelInFlight.current = false
      setCancelBusy(false)
      setCancelling(null)
      refreshAll() // muvaffaqiyatda ham, xatoda (holat o'zgargan bo'lishi mumkin) ham haqiqiy holat olinadi
    }
  }

  const tabs = (
    <div className="segmented" role="group" aria-label={t('schedule.view')}>
      <button type="button" aria-pressed={view === 'pending'} onClick={() => setView('pending')}>{t('schedule.tabUpcoming')}</button>
      <button type="button" aria-pressed={view === 'calendar'} onClick={() => setView('calendar')}>{t('cal.tab')}</button>
      <button type="button" aria-pressed={view === 'history'} onClick={() => setView('history')}>{t('schedule.tabHistory')}</button>
    </div>
  )

  const itemFor = (p: ScheduledPost) => (
    <PostItem key={p.id} post={p} actions={p.status === 'pending'} onEdit={setEditing} onCancel={setCancelling} />
  )

  let body
  if (view === 'calendar') body = <CalendarView renderPost={itemFor} reloadKey={calendarKey} />
  else if (feed.loading) body = <LoadingBlock rows={4} />
  else if (feed.error && feed.items.length === 0) body = <ErrorState error={feed.error} onRetry={feed.reload} botUsername={botUsername} />
  else {
    const groups = groupByDay(feed.items, (p) => p.scheduled_time)
    body = (
      <>
        {feed.error && <InlineWarning error={feed.error} onRetry={feed.reload} />}
        {feed.items.length === 0 ? (
          view === 'pending' ? (
            <EmptyState title={t('schedule.emptyTitle')} body={t('schedule.emptyBody')}
              action={openBotAvailable(botUsername)
                ? <Button variant="primary" icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
                : undefined} />
          ) : <EmptyState title={t('schedule.historyEmptyTitle')} body={t('schedule.historyEmptyBody')} />
        ) : (
          <>
            <p className="muted" aria-live="polite">{t('schedule.total', { n: feed.total })}</p>
            {groups.map((g) => (
              <section key={g.key} aria-label={g.label === 'date' ? formatDate(g.sampleIso) : t(`schedule.${g.label}`)}>
                <h2 className="group-title">
                  {g.label === 'date' ? (g.sampleIso ? formatDate(g.sampleIso) : t('common.none')) : t(`schedule.${g.label}`)}
                </h2>
                <ul className="list">
                  {g.items.map((p) => (
                    <PostItem key={p.id} post={p} actions={view === 'pending' && p.status === 'pending'}
                      onEdit={setEditing} onCancel={setCancelling} />
                  ))}
                </ul>
              </section>
            ))}
            {feed.moreError && <div className="banner banner-warn" role="alert">{t('schedule.moreError')}</div>}
            {feed.hasMore && (
              <Button block busy={feed.loadingMore} onClick={feed.loadMore}>
                {feed.loadingMore ? t('common.loading') : t('schedule.more')}
              </Button>
            )}
          </>
        )}
      </>
    )
  }

  return (
    <Page>
      <PageHeader title={t('schedule.title')} onRefresh={refreshAll} refreshing={feed.refreshing} />
      {tabs}
      {body}
      {editing && <EditDialog post={editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); refreshAll() }} />}
      {cancelling && (
        <ConfirmDialog title={t('schedule.cancelTitle')} body={t('schedule.cancelBody')} confirmLabel={t('schedule.cancelYes')}
          danger busy={cancelBusy} onConfirm={() => void confirmCancel()} onClose={() => setCancelling(null)} />
      )}
    </Page>
  )
}
