import { useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import type { PostFilter, ScheduledPost } from '../api/types'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { PostThumb } from '../components/PostThumb'
import { RichTextField } from '../components/RichTextField'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, EmptyState, ErrorState, FormError, InlineWarning, LoadingBlock, errorMessageKey, openBotAvailable } from '../components/ui'
import { config } from '../config'
import { useScheduleFeed } from '../hooks/useScheduleFeed'
import { toClientError } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { openBot } from '../telegram'
import { CalendarView } from './CalendarView'
import { groupByDay, isFutureEnough, isoToLocalInput, localInputToIso } from './format'
import { compressImage } from './imageCompress'
import { describeRecurrence, suggestSecondTime } from './recurrence'
import { isSafeLink } from './richtext'

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
      <div className="item-main">
        <PostThumb postId={post.id} hasMedia={post.has_media} type={post.post_type} label={t('schedule.media')} />
        <p className="item-text">{post.preview || t('schedule.noText')}</p>
      </div>
      <div className="item-meta">
        <span>{post.channel_title || t('schedule.unknownChannel')}</span>
        {!actions && <Badge>{t(statusKey(post.status))}</Badge>}
        {post.has_media && <Badge>{t('schedule.media')}</Badge>}
        {repeats && <Badge>{describeRecurrence({ type: post.recurrence ?? '', day: post.recurrence_day, time: post.recurrence_time, time2: post.recurrence_time2 }, t) ?? t('schedule.repeats')}</Badge>}
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
  post: ScheduledPost; onClose: () => void; onSaved: (close?: boolean) => void
}) {
  const { client, notify } = useAppData()
  const { t } = useI18n()
  const [full, setFull] = useState<ScheduledPost | null>(null)
  const [text, setText] = useState('')
  const [btnText, setBtnText] = useState('')
  const [btnUrl, setBtnUrl] = useState('')
  const [when, setWhen] = useState(() => isoToLocalInput(post.scheduled_time))
  const [time1, setTime1] = useState(post.recurrence_time ?? '')
  const [time2, setTime2] = useState<string | null>(post.recurrence_time2 ?? null)
  const [loadError, setLoadError] = useState<ApiClientError | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [invalid, setInvalid] = useState<'text' | 'when' | 'button' | 'time' | null>(null)
  const [busy, setBusy] = useState(false)
  const [mediaBusy, setMediaBusy] = useState(false)
  const [mediaVersion, setMediaVersion] = useState(0)
  const [hasMedia, setHasMedia] = useState(post.has_media)
  const [postType, setPostType] = useState(post.post_type)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const inFlight = useRef(false)
  const recurrence = post.recurrence ?? ''
  const recurring = !!recurrence && recurrence !== 'none'
  // Kun vaqtini (va kuniga ikkinchi vaqtni) faqat kunlik/ikki vaqtli postlarda o'zgartirish mumkin; boshqa turlarda — faqat birinchi vaqt.
  const dailyKind = recurrence === 'daily' || recurrence === 'twice'
  // Media postda matn = sarlavha (caption): Telegram 1024 dan kesadi, shuning uchun tahrirda ham shu chegara.
  const textMax = hasMedia ? config.maxCaptionChars : config.maxPostChars
  const originals = useRef({ text: '', btnText: '', btnUrl: '', when: isoToLocalInput(post.scheduled_time), time1: post.recurrence_time ?? '', time2: post.recurrence_time2 ?? null as string | null })

  useEffect(() => {
    const ctl = new AbortController()
    client.post(post.id, ctl.signal).then(
      (p) => {
        if (ctl.signal.aborted) return
        const body = p.text ?? p.preview
        setFull(p)
        setText(body)
        setBtnText(p.button_text ?? '')
        setBtnUrl(p.button_url ?? '')
        originals.current = { ...originals.current, text: body, btnText: p.button_text ?? '', btnUrl: p.button_url ?? '' }
      },
      (e: unknown) => { if (!ctl.signal.aborted) setLoadError(toClientError(e)) },
    )
    return () => ctl.abort()
  }, [client, post.id])

  const mediaAction = async (run: () => Promise<ScheduledPost>, doneKey: MessageKey) => {
    setMediaBusy(true)
    setError(null)
    try {
      const updated = await run()
      setHasMedia(updated.has_media)
      setPostType(updated.post_type)
      setMediaVersion((v) => v + 1)
      notify(t(doneKey))
      onSaved(false) // ro'yxat fonda yangilanadi, oyna ochiq qoladi
    } catch (e) {
      const err = toClientError(e)
      const key = err.code === 'unsupported_media_type' ? 'media.errType' : err.code === 'payload_too_large' ? 'media.errSize'
        : err.code === 'caption_too_long' ? 'media.errCaption' : errorMessageKey(err.code)
      notify(t(key as MessageKey), 'error')
      if (err.code === 'not_editable') onSaved()
    } finally {
      setMediaBusy(false)
    }
  }
  const pickFile = async (picked: File | undefined) => {
    if (fileRef.current) fileRef.current.value = ''
    if (!picked || mediaBusy) return
    const isVideo = picked.type === 'video/mp4' || picked.type === 'video/quicktime'
    const isImage = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(picked.type)
    if (!isVideo && !isImage) { notify(t('media.errType'), 'error'); return }
    if (picked.size > (isVideo ? config.maxUploadVideoBytes : config.maxUploadPhotoBytes)) { notify(t('media.errSize'), 'error'); return }
    if (text.length > config.maxCaptionChars) { notify(t('media.errCaption'), 'error'); return }
    const file = isImage ? await compressImage(picked) : picked
    await mediaAction(() => client.replacePostMedia(post.id, file), 'edit.mediaSaved')
  }

  const save = async () => {
    if (inFlight.current || full === null) return
    const o = originals.current
    const trimmed = text.trim()
    const textChanged = trimmed !== o.text.trim()
    // Uzunlik FAQAT matn o'zgargan bo'lsa tekshiriladi: eski uzun matnli postning vaqtini o'zgartirish bloklanmasin.
    if (!trimmed || (textChanged && trimmed.length > textMax)) { setInvalid('text'); return }
    const timeChanged = !recurring && when !== o.when
    if (timeChanged && !isFutureEnough(when)) { setInvalid('when'); return }
    const recChanged = recurring && (time1 !== o.time1 || (dailyKind && (time2 ?? null) !== o.time2))
    if (recChanged && !/^([01]\d|2[0-3]):[0-5]\d$/.test(time1)) { setInvalid('time'); return }
    if (recChanged && time2 !== null && (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time2) || time2 === time1)) { setInvalid('time'); return }
    const btnChanged = btnText.trim() !== o.btnText || btnUrl.trim() !== o.btnUrl
    if (btnChanged && (btnText.trim() !== '' || btnUrl.trim() !== '')
      && (!btnText.trim() || btnText.trim().length > config.maxButtonTextChars || !isSafeLink(btnUrl))) { setInvalid('button'); return }
    if (!textChanged && !timeChanged && !recChanged && !btnChanged) { onClose(); return }
    inFlight.current = true
    setBusy(true)
    setError(null)
    setInvalid(null)
    try {
      await client.updatePost(post.id, {
        ...(textChanged ? { text: trimmed } : {}),
        ...(timeChanged ? { scheduled_at: localInputToIso(when) ?? '' } : {}),
        ...(recChanged ? { recurrence_time: time1, ...(dailyKind && time2 ? { recurrence_time2: time2 } : {}) } : {}),
        ...(btnChanged ? { button_text: btnText.trim(), button_url: btnUrl.trim() } : {}),
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
    <Dialog title={t('schedule.editTitle')} onClose={onClose} busy={busy || mediaBusy}>
      {loadError ? <FormError error={loadError} /> : full === null ? <p className="muted">{t('schedule.loadingText')}</p> : (
        <>
          <h3 className="edit-sec">{t('media.title')}</h3>
          <div className="edit-media">
            {hasMedia
              ? <PostThumb postId={post.id} hasMedia type={postType} label={t('schedule.media')} version={String(mediaVersion)} size="lg" />
              : <p className="muted small">{t('edit.noMedia')}</p>}
            <input ref={fileRef} type="file" className="sr-only" tabIndex={-1} aria-label={t('media.title')}
              accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime" onChange={(e) => void pickFile(e.target.files?.[0])} />
            <div className="edit-media-actions">
              <Button variant="secondary" icon="image" busy={mediaBusy} onClick={() => fileRef.current?.click()}>
                {hasMedia ? t('media.replace') : t('media.add')}
              </Button>
              {hasMedia && (
                <Button variant="ghost" icon="trash" disabled={mediaBusy} onClick={() => void mediaAction(() => client.deletePostMedia(post.id), 'edit.mediaRemoved')}>
                  {t('edit.removeMedia')}
                </Button>
              )}
            </div>
          </div>

          <h3 className="edit-sec"><label htmlFor="edit-text">{t('post.text')}</label></h3>
          <RichTextField id="edit-text" value={text} onChange={(v) => { setText(v); setInvalid(null) }} maxLength={textMax} rows={8} invalid={invalid === 'text'} />
          <p className="muted">{t('post.counter', { n: text.length, max: textMax })}</p>
          {invalid === 'text' && <p className="field-error" role="alert">{t(hasMedia ? 'post.errCaption' : 'post.errText', { max: textMax })}</p>}

          <h3 className="edit-sec">{t('post.button.title')}</h3>
          <input className="input" value={btnText} maxLength={config.maxButtonTextChars} placeholder={t('post.button.text')} aria-label={t('post.button.text')}
            onChange={(e) => { setBtnText(e.target.value); setInvalid(null) }} />
          <input className="input" type="url" inputMode="url" value={btnUrl} placeholder={t('post.button.url')} aria-label={t('post.button.url')}
            onChange={(e) => { setBtnUrl(e.target.value); setInvalid(null) }} />
          {invalid === 'button' && <p className="field-error" role="alert">{t('post.errButton')}</p>}

          <h3 className="edit-sec">{t('edit.timeTitle')}</h3>
          {recurring ? (
            <>
              <label className="field" htmlFor="edit-time1">{t('edit.time1')}</label>
              <input id="edit-time1" className="input" type="time" step={60} value={time1} aria-invalid={invalid === 'time' || undefined}
                onChange={(e) => { setTime1(e.target.value); setInvalid(null) }} />
              {dailyKind && (
                <>
                  <label className="check">
                    <input type="checkbox" checked={time2 !== null}
                      onChange={(e) => { setTime2(e.target.checked ? suggestSecondTime(time1 || '09:00') : null); setInvalid(null) }} />
                    <span>{t('rep.secondHint')}</span>
                  </label>
                  {time2 !== null && (
                    <input className="input" type="time" step={60} value={time2} aria-label={t('rep.second')}
                      aria-invalid={invalid === 'time' || undefined} onChange={(e) => { if (e.target.value) { setTime2(e.target.value); setInvalid(null) } }} />
                  )}
                </>
              )}
              {invalid === 'time' && <p className="field-error" role="alert">{t('edit.errTime')}</p>}
              <p className="muted small">{t('edit.recurringNote')}</p>
            </>
          ) : (
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
        <Button onClick={onClose} disabled={busy || mediaBusy}>{t('common.cancel')}</Button>
        <Button variant="primary" busy={busy} disabled={full === null || mediaBusy} onClick={() => void save()}>{t('schedule.save')}</Button>
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
        onSaved={(close = true) => { if (close) setEditing(null); refreshAll() }} />}
      {cancelling && (
        <ConfirmDialog title={t('schedule.cancelTitle')} body={t('schedule.cancelBody')} confirmLabel={t('schedule.cancelYes')}
          danger busy={cancelBusy} onConfirm={() => void confirmCancel()} onClose={() => setCancelling(null)} />
      )}
    </Page>
  )
}
