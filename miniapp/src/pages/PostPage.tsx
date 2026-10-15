import { useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import { ApiClientError } from '../api/client'
import { AI_STYLES, type AiStyle, type CreatePostInput } from '../api/types'
import { ConfirmDialog } from '../components/Dialog'
import { Icon } from '../components/Icon'
import { PostPreview } from '../components/PostPreview'
import { RepeatPicker } from '../components/RepeatPicker'
import { Page, PageHeader } from '../components/Shell'
import { SmartSchedule } from '../components/SmartSchedule'
import { TemplatesCard } from '../components/TemplatesCard'
import { Button, EmptyState, ErrorState, FormError, LoadingBlock, errorMessageKey, openBotAvailable } from '../components/ui'
import { config } from '../config'
import { useDraftPhoto } from '../hooks/useDraftPhoto'
import { useI18n, type MessageKey } from '../i18n'
import { openBot } from '../telegram'
import { toClientError } from '../hooks/useResource'
import { defaultScheduleValue, isFutureEnough, isoToLocalInput, isUnlimited, localInputToIso, toLocalInputValue } from './format'
import { DEFAULT_REPEAT, alignToWeekdays, buildRecurrence, choiceFromRecurrence, tashkentParts, type RepeatChoice } from './recurrence'
import { FORMATS, isSafeLink, linkOpen, wrapSelection } from './richtext'

type Mode = 'schedule' | 'now'
type FieldKey = 'channel' | 'text' | 'when' | 'button'

/** Telegram: rasm/video ostidagi matn (caption) chegarasi (config bilan backend'ga mos). */
const CAPTION_MAX = config.maxCaptionChars

const FORMAT_KEYS: Record<string, MessageKey> = {
  bold: 'post.fmt.bold', italic: 'post.fmt.italic', underline: 'post.fmt.underline',
  strike: 'post.fmt.strike', code: 'post.fmt.code', spoiler: 'post.fmt.spoiler',
}

/** Tez vaqt tanlovlari: har biri "hozir"dan hisoblanadi (kelajakda bo'lmasa o'chiriladi). */
export function quickTimes(now: Date): { id: '30m' | '1h' | 'today' | 'tomorrow'; value: string }[] {
  const at = (add: number) => toLocalInputValue(new Date(now.getTime() + add * 60_000))
  const today = new Date(now); today.setHours(18, 0, 0, 0)
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1); tomorrow.setHours(9, 0, 0, 0)
  return [
    { id: '30m', value: at(30) },
    { id: '1h', value: at(60) },
    { id: 'today', value: toLocalInputValue(today) },
    { id: 'tomorrow', value: toLocalInputValue(tomorrow) },
  ]
}

/**
 * Post yaratish (PostBot uslubida): botdan kelgan qoralama (matn + media) shu yerda tahrirlanadi, kanal va vaqt
 * tanlanadi, "Ko'rinish" kartasida Telegram xabari ko'rinishida ko'rsatiladi. Yuborishni Mini App BAJARMAYDI:
 * post navbatga yoziladi, botning rejalashtiruvchisi yuboradi. Takroriy bosishdan himoya: `inFlight` ref + `busy`;
 * server ham 30 s ichida bir xil postni qaytaradi.
 */
export function PostPage() {
  const { me, channels, client, draft, feed, go, notify, botUsername } = useAppData()
  const { t } = useI18n()
  const [channelId, setChannelId] = useState('')
  const [text, setText] = useState('')
  const [mode, setMode] = useState<Mode>('schedule')
  const [when, setWhen] = useState(() => defaultScheduleValue())
  const [repeat, setRepeat] = useState<RepeatChoice>(DEFAULT_REPEAT)
  const [aligned, setAligned] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [fieldError, setFieldError] = useState<{ field: FieldKey; key: MessageKey } | null>(null)
  const [idea, setIdea] = useState('')
  const [style, setStyle] = useState<AiStyle>('casual')
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState<ApiClientError | null>(null)
  const [aiIdeaError, setAiIdeaError] = useState(false)
  const [btnOpen, setBtnOpen] = useState(false)
  const [btnText, setBtnText] = useState('')
  const [btnUrl, setBtnUrl] = useState('')
  const [linkOpenRow, setLinkOpenRow] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')
  const [discard, setDiscard] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [aiOpen, setAiOpen] = useState<boolean | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const inFlight = useRef(false)
  const aiInFlight = useRef(false)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const selection = useRef<{ start: number; end: number }>({ start: 0, end: 0 })

  const current = draft.data?.draft ?? null
  const draftKey = current ? `${current.updated_at ?? ''}|${current.text.length}|${current.channel_id ?? ''}` : null
  const appliedKey = useRef<string | null>(null)
  const items = channels.data?.items ?? []

  // Botdan yangi/yangilangan qoralama kelganda matn va tugma BIR MARTA to'ldiriladi (foydalanuvchi tahririni bosmaydi).
  useEffect(() => {
    if (!current || draftKey === appliedKey.current) return
    appliedKey.current = draftKey
    setText(current.text)
    setBtnText(current.button_text ?? '')
    setBtnUrl(current.button_url ?? '')
    setBtnOpen(Boolean(current.button_text && current.button_url))
    setFieldError(null)
    setError(null)
  }, [current, draftKey])

  // Kanal ro'yxati kech kelishi mumkin: qoralamadagi kanal ro'yxat kelgach, qoralama boshiga BIR MARTA tanlanadi.
  const channelKey = useRef<string | null>(null)
  const draftChannel = current?.channel_id ?? null
  const hasDraftChannel = draftChannel !== null && items.some((c) => c.id === draftChannel)
  useEffect(() => {
    if (!draftKey || channelKey.current === draftKey || !hasDraftChannel || !draftChannel) return
    channelKey.current = draftKey
    setChannelId(draftChannel)
  }, [draftKey, draftChannel, hasDraftChannel])

  const media = current?.media ?? null
  const photo = useDraftPhoto(client, Boolean(media?.previewable), current?.updated_at ?? null)
  const textMax = media ? CAPTION_MAX : config.maxPostChars

  if (me.loading || channels.loading) return <Page><PageHeader title={t('post.title')} /><LoadingBlock rows={4} /></Page>
  if (!me.data) {
    return <Page><PageHeader title={t('post.title')} />
      {me.error && <ErrorState error={me.error} onRetry={me.reload} botUsername={botUsername} />}</Page>
  }
  if (!channels.data) {
    return <Page><PageHeader title={t('post.title')} />
      {channels.error && <ErrorState error={channels.error} onRetry={channels.reload} botUsername={botUsername} />}</Page>
  }

  if (items.length === 0) {
    return (
      <Page>
        <PageHeader title={t('post.title')} />
        <EmptyState title={t('post.noChannelsTitle')} body={t('post.noChannelsBody')}
          action={openBotAvailable(botUsername)
            ? <Button variant="primary" icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
            : undefined} />
      </Page>
    )
  }

  const { plan, usage } = me.data
  const limit = (n: number) => (isUnlimited(n) ? t('common.unlimited') : String(n))
  const selected = channelId || (items.length === 1 ? items[0].id : '')
  const selectedTitle = items.find((c) => c.id === selected)?.title || selected
  const useDraft = Boolean(current)
  const hasButton = btnOpen && (btnText.trim() !== '' || btnUrl.trim() !== '')
  const aiIsOpen = aiOpen ?? !useDraft
  const nowDate = new Date()

  const apply = (edit: { value: string; selStart: number; selEnd: number }) => {
    setText(edit.value)
    setFieldError(null)
    requestAnimationFrame(() => {
      const el = textRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(edit.selStart, edit.selEnd)
      selection.current = { start: edit.selStart, end: edit.selEnd }
    })
  }
  const format = (open: string, close: string) => {
    const { start, end } = selection.current
    apply(wrapSelection(text, start, end, open, close))
  }
  const applyLink = () => {
    if (!isSafeLink(linkUrl)) return
    const { start, end } = selection.current
    apply(wrapSelection(text, start, end, linkOpen(linkUrl), '</a>'))
    setLinkOpenRow(false)
    setLinkUrl('')
  }

  const validate = (): boolean => {
    const trimmed = text.trim()
    if (!selected) { setFieldError({ field: 'channel', key: 'post.errChannel' }); return false }
    if ((!trimmed && !media) || text.length > textMax) {
      setFieldError({ field: 'text', key: media && text.length > textMax ? 'post.errCaption' : 'post.errText' })
      return false
    }
    if (hasButton) {
      if (!btnText.trim() || btnText.trim().length > config.maxButtonTextChars || !isSafeLink(btnUrl)) {
        setFieldError({ field: 'button', key: 'post.errButton' })
        return false
      }
    }
    if (mode === 'schedule' && !isFutureEnough(when)) { setFieldError({ field: 'when', key: 'post.errWhen' }); return false }
    if (mode === 'schedule' && repeat.kind === 'weekdays' && repeat.mask === 0) { setFieldError({ field: 'when', key: 'rep.pickDay' }); return false }
    setFieldError(null)
    return true
  }

  const submit = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const scheduledIso = localInputToIso(when) ?? ''
      const recurrence = mode === 'schedule' && scheduledIso ? buildRecurrence(repeat, new Date(scheduledIso)) : null
      const payload: CreatePostInput = mode === 'now'
        ? { channel_id: selected, text: text.trim(), send_now: true }
        : { channel_id: selected, text: text.trim(), scheduled_at: scheduledIso, ...(recurrence ? { recurrence } : {}) }
      if (hasButton) { payload.button_text = btnText.trim(); payload.button_url = btnUrl.trim() }
      if (useDraft) payload.use_draft = true
      const result = await client.createPost(payload)
      notify(result.created ? t(mode === 'now' ? 'post.createdNow' : recurrence ? 'post.createdRepeat' : 'post.created') : t('post.duplicate'))
      setRepeat(DEFAULT_REPEAT)
      setAligned(false)
      setText('')
      setIdea('')
      setBtnText('')
      setBtnUrl('')
      setBtnOpen(false)
      setConfirm(false)
      appliedKey.current = null
      channelKey.current = null
      draft.reload()
      feed.reload()
      me.reload()
      go('schedule')
    } catch (e) {
      const err = toClientError(e)
      setError(err)
      setConfirm(false)
      if (err.field === 'text' || err.field === 'channel_id' || err.field === 'scheduled_at'
        || err.field === 'button_text' || err.field === 'button_url') {
        const map = {
          text: ['text', 'post.errText'], channel_id: ['channel', 'post.errChannel'], scheduled_at: ['when', 'post.errWhen'],
          button_text: ['button', 'post.errButton'], button_url: ['button', 'post.errButton'],
        } as const
        const [field, key] = map[err.field]
        setFieldError({ field, key })
      }
      if (err.code === 'caption_too_long') setFieldError({ field: 'text', key: 'post.errCaption' })
      if (err.code === 'draft_not_found') draft.reload()
      // Tarmoq/timeout: natija NOMA'LUM — ro'yxatni yangilab, yaratilgan bo'lsa ko'rinadi.
      if (err.code === 'network' || err.code === 'timeout') { feed.reload(); me.reload(); draft.reload() }
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !validate()) return
    if (mode === 'now') setConfirm(true)
    else void submit()
  }

  const generate = async () => {
    if (aiInFlight.current) return
    const trimmed = idea.trim()
    if (!trimmed || trimmed.length > config.maxAiInputChars) { setAiIdeaError(true); return }
    setAiIdeaError(false)
    aiInFlight.current = true
    setAiBusy(true)
    setAiError(null)
    try {
      const out = await client.generate(trimmed, style)
      setText(out.text)
      setFieldError(null)
      notify(t('post.ai.done'))
    } catch (e) {
      setAiError(toClientError(e))
    } finally {
      me.reload() // kvota/kredit hisobi yangilanadi (xatoda ham bron qaytarilgan bo'lishi mumkin)
      aiInFlight.current = false
      setAiBusy(false)
    }
  }

  /** Qurilmadan rasm/video: mijozda tur va hajm tekshiriladi (server baribir baytlardan tekshiradi), matn/tugma birga saqlanadi. */
  const pickMedia = async (file: File | undefined) => {
    if (fileRef.current) fileRef.current.value = ''
    if (!file || uploading) return
    const isVideo = file.type === 'video/mp4' || file.type === 'video/quicktime'
    const isImage = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(file.type)
    if (!isVideo && !isImage) { notify(t('media.errType'), 'error'); return }
    if (file.size > (isVideo ? config.maxUploadVideoBytes : config.maxUploadPhotoBytes)) { notify(t('media.errSize'), 'error'); return }
    if (text.length > CAPTION_MAX) { setFieldError({ field: 'text', key: 'post.errCaption' }); notify(t('media.errCaption'), 'error'); return }
    if (btnOpen && (btnText.trim() !== '' || btnUrl.trim() !== '')
      && (!btnText.trim() || btnText.trim().length > config.maxButtonTextChars || !isSafeLink(btnUrl))) {
      setFieldError({ field: 'button', key: 'post.errButton' }); return
    }
    setUploading(true)
    try {
      await client.uploadMedia(file, {
        text: text.trim(),
        button_text: hasButton ? btnText.trim() : '',
        button_url: hasButton ? btnUrl.trim() : '',
      })
      draft.reload()
      notify(t('media.added'))
    } catch (e) {
      const err = toClientError(e)
      const key = err.code === 'unsupported_media_type' ? 'media.errType' : err.code === 'payload_too_large' ? 'media.errSize'
        : err.code === 'caption_too_long' ? 'media.errCaption' : errorMessageKey(err.code)
      notify(t(key), 'error')
    } finally {
      setUploading(false)
    }
  }

  const discardDraft = async () => {
    setDiscarding(true)
    try {
      await client.deleteDraft()
      appliedKey.current = null
      setText('')
      setBtnText('')
      setBtnUrl('')
      setBtnOpen(false)
      draft.reload()
      notify(t('post.draft.discarded'))
      setDiscard(false)
    } catch (e) {
      notify(t(errorMessageKey(toClientError(e).code)), 'error')
      setDiscard(false)
    } finally {
      setDiscarding(false)
    }
  }

  const quick = quickTimes(nowDate)
  const deviceTz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone } catch { return '' } })()
  const showTz = deviceTz !== '' && deviceTz !== 'Asia/Tashkent'

  /** Takrorlash tanlovi o'zgarganda: hafta kunlari bo'yicha birinchi chiqish mos kunga suriladi (server shuni talab qiladi). */
  const changeRepeat = (next: RepeatChoice) => {
    setRepeat(next)
    setFieldError(null)
    const iso = localInputToIso(when)
    if (iso && next.kind === 'weekdays' && next.mask) {
      const moved = alignToWeekdays(new Date(iso), next.mask)
      if (moved.getTime() !== new Date(iso).getTime()) {
        setAligned(true)
        setWhen(toLocalInputValue(moved))
      }
    } else {
      setAligned(false)
    }
  }
  const changeWhen = (value: string) => {
    setFieldError(null)
    const iso = localInputToIso(value)
    if (iso && repeat.kind === 'weekdays' && repeat.mask) {
      const moved = alignToWeekdays(new Date(iso), repeat.mask)
      setAligned(moved.getTime() !== new Date(iso).getTime())
      setWhen(toLocalInputValue(moved))
    } else {
      setAligned(false)
      setWhen(value)
    }
  }
  const applyProposal = (p: { scheduled_at: string; recurrence: Parameters<typeof choiceFromRecurrence>[0] }) => {
    setMode('schedule')
    setWhen(isoToLocalInput(p.scheduled_at))
    setRepeat(choiceFromRecurrence(p.recurrence))
    setAligned(false)
    setFieldError(null)
  }
  const currentTashkentTime = (() => { const iso = localInputToIso(when); return iso ? tashkentParts(new Date(iso)).time : undefined })()
  const mediaType = media?.type ?? ''
  return (
    <Page wide>
      <PageHeader title={t('post.title')} />
      <p className="muted">{t('post.leadNew')}</p>

      {current && (
        <section className="card draft-banner" aria-labelledby="draft-title">
          <div className="card-row">
            <h2 id="draft-title"><Icon name="bot" size={20} /> {t('post.draft.title')}</h2>
            <Button variant="ghost" icon="trash" onClick={() => setDiscard(true)} aria-label={t('post.draft.discard')}
              title={t('post.draft.discard')} />
          </div>
          <p className="muted">{t('post.draft.body')}</p>
          <div className="chips">
            {media && <span className="badge">{t(`post.media.${mediaType}` as MessageKey, { n: media.count ?? 0 })}</span>}
            {current.reactions && <span className="badge">{t('post.draft.reactions')}</span>}
            {current.delete_after_hours > 0 && <span className="badge">{t('post.draft.autoDelete', { h: current.delete_after_hours })}</span>}
          </div>
        </section>
      )}

      <form className="compose" onSubmit={onSubmit} noValidate aria-label={t('post.edit.title')}>
        <section className="card compose-edit" aria-labelledby="compose">
          <h2 id="compose">{t('post.edit.title')}</h2>
          <label className="field" htmlFor="channel">{t('post.channel')}</label>
          <select id="channel" className="input" value={selected} aria-invalid={fieldError?.field === 'channel' || undefined}
            onChange={(e) => { setChannelId(e.target.value); setFieldError(null) }}>
            {items.length > 1 && <option value="">{t('post.channelPick')}</option>}
            {items.map((c) => <option key={c.id} value={c.id}>{c.title || c.id}</option>)}
          </select>
          {fieldError?.field === 'channel' && <p className="field-error" role="alert">{t(fieldError.key)}</p>}

          <label className="field" htmlFor="text">{t('post.text')}</label>
          <div className="toolbar" role="toolbar" aria-label={t('post.fmt.label')}>
            {FORMATS.map((f) => (
              <button key={f.id} type="button" className={`tool tool-${f.id}`} aria-label={t(FORMAT_KEYS[f.id])}
                title={t(FORMAT_KEYS[f.id])} onMouseDown={(e) => e.preventDefault()} onClick={() => format(f.open, f.close)}>
                {f.label}
              </button>
            ))}
            <button type="button" className="tool" aria-label={t('post.fmt.link')} title={t('post.fmt.link')}
              aria-expanded={linkOpenRow} onMouseDown={(e) => e.preventDefault()} onClick={() => setLinkOpenRow((v) => !v)}>
              🔗
            </button>
          </div>
          {linkOpenRow && (
            <div className="link-row">
              <input className="input" type="url" inputMode="url" value={linkUrl} placeholder={t('post.fmt.linkUrl')}
                aria-label={t('post.fmt.linkUrl')} aria-invalid={(linkUrl !== '' && !isSafeLink(linkUrl)) || undefined}
                onChange={(e) => setLinkUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); applyLink() } }} />
              <Button variant="secondary" disabled={!isSafeLink(linkUrl)} onClick={applyLink}>{t('post.fmt.linkApply')}</Button>
            </div>
          )}
          <textarea id="text" ref={textRef} className="input editor" rows={media ? 5 : 8} value={text} maxLength={textMax}
            placeholder={t('post.textPlaceholder')} aria-invalid={fieldError?.field === 'text' || undefined}
            onChange={(e) => { setText(e.target.value); setFieldError(null) }}
            onSelect={(e) => { const el = e.currentTarget; selection.current = { start: el.selectionStart, end: el.selectionEnd } }}
            onBlur={(e) => { const el = e.currentTarget; selection.current = { start: el.selectionStart, end: el.selectionEnd } }} />
          <div className="media-row">
            <input ref={fileRef} type="file" className="sr-only" tabIndex={-1} aria-label={t('media.title')}
              accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime"
              onChange={(e) => void pickMedia(e.target.files?.[0])} />
            <Button variant="secondary" icon="image" busy={uploading} onClick={() => fileRef.current?.click()}>
              {uploading ? t('media.uploading') : media ? t('media.replace') : t('media.add')}
            </Button>
            <p className="muted small">{t('media.hint')}</p>
          </div>
          <p className="muted" aria-live="off">
            {t('post.counter', { n: text.length, max: textMax })}
            {media && <> · {t('post.captionLimit', { max: CAPTION_MAX })}</>}
          </p>
          {fieldError?.field === 'text' && <p className="field-error" role="alert">{t(fieldError.key, { max: textMax })}</p>}
        </section>

        <section className="card compose-button" aria-labelledby="btn-title">
          <div className="card-row">
            <h2 id="btn-title">{t('post.button.title')}</h2>
            {btnOpen
              ? <Button variant="ghost" icon="trash" onClick={() => { setBtnOpen(false); setBtnText(''); setBtnUrl('') }}
                aria-label={t('post.button.remove')} title={t('post.button.remove')} />
              : <Button variant="secondary" icon="plus" onClick={() => setBtnOpen(true)}>{t('post.button.add')}</Button>}
          </div>
          {btnOpen && (
            <>
              <label className="field" htmlFor="btn-text">{t('post.button.text')}</label>
              <input id="btn-text" className="input" value={btnText} maxLength={config.maxButtonTextChars}
                aria-invalid={fieldError?.field === 'button' || undefined}
                onChange={(e) => { setBtnText(e.target.value); setFieldError(null) }} />
              <label className="field" htmlFor="btn-url">{t('post.button.url')}</label>
              <input id="btn-url" className="input" type="url" inputMode="url" value={btnUrl} maxLength={config.maxButtonUrlChars}
                aria-invalid={fieldError?.field === 'button' || undefined}
                onChange={(e) => { setBtnUrl(e.target.value); setFieldError(null) }} />
              {fieldError?.field === 'button' && <p className="field-error" role="alert">{t(fieldError.key)}</p>}
            </>
          )}
        </section>

        <PostPreview channelTitle={selectedTitle || t('post.channelPick')} html={text}
          media={media ? { type: media.type, count: media.count, url: photo.url, loading: photo.loading } : null}
          buttonText={hasButton ? btnText.trim() || null : null} />

        <section className="card compose-when" aria-labelledby="when-title">
          <h2 id="when-title">{t('post.when')}</h2>
          <fieldset className="segmented" aria-label={t('post.when')}>
            <legend className="sr-only">{t('post.when')}</legend>
            <button type="button" aria-pressed={mode === 'schedule'} onClick={() => setMode('schedule')}>{t('post.whenSchedule')}</button>
            <button type="button" aria-pressed={mode === 'now'} onClick={() => setMode('now')}>{t('post.whenNow')}</button>
          </fieldset>

          {mode === 'schedule' ? (
            <>
              <SmartSchedule onApply={applyProposal} defaultTime={currentTashkentTime} />
              <div className="chips" role="group" aria-label={t('post.quick.label')}>
                {quick.map((q) => (
                  <button key={q.id} type="button" className="chip" aria-pressed={when === q.value}
                    disabled={!isFutureEnough(q.value, nowDate.getTime())}
                    onClick={() => changeWhen(q.value)}>
                    <Icon name="clock" size={16} /> {t(`post.quick.${q.id}` as MessageKey)}
                  </button>
                ))}
              </div>
              <label className="field" htmlFor="when">{t('post.date')}</label>
              <input id="when" className="input" type="datetime-local" value={when}
                aria-invalid={fieldError?.field === 'when' || undefined}
                onChange={(e) => changeWhen(e.target.value)} />
              {fieldError?.field === 'when' && <p className="field-error" role="alert">{t(fieldError.key)}</p>}
              <RepeatPicker value={repeat} onChange={changeRepeat} showTz={showTz} />
              {aligned && <p className="muted small" role="status">{t('rep.aligned')}</p>}
            </>
          ) : <p className="muted">{t('post.nowHint')}</p>}
        </section>

        <div className="submit-bar">
          {error && <FormError error={error} />}
          <Button type="submit" variant="primary" block busy={busy} icon="send">
            {busy ? t('post.saving') : mode === 'now' ? t('post.submitNow') : t('post.submitSchedule')}
          </Button>
          <p className="muted">{t('post.queue', { used: usage.pending_posts, limit: limit(plan.limits.queued_posts) })}</p>
        </div>
      </form>

      <TemplatesCard text={text} onApply={(tpl) => { setText(tpl); setFieldError(null) }} />

      <details className="card ai-card" open={aiIsOpen} onToggle={(e) => setAiOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary><h2 id="ai">{t('post.ai.title')}</h2></summary>
        <label className="field" htmlFor="idea">{t('post.ai.idea')}</label>
        <textarea id="idea" className="input" rows={3} value={idea} maxLength={config.maxAiInputChars}
          aria-invalid={aiIdeaError || undefined} onChange={(e) => { setIdea(e.target.value); setAiIdeaError(false) }} />
        {aiIdeaError && <p className="field-error" role="alert">{t('post.ai.errIdea', { max: config.maxAiInputChars })}</p>}
        <label className="field" htmlFor="style">{t('post.ai.style')}</label>
        <select id="style" className="input" value={style} onChange={(e) => setStyle(e.target.value as AiStyle)}>
          {AI_STYLES.map((s) => <option key={s} value={s}>{t(`ai.style.${s}` as MessageKey)}</option>)}
        </select>
        <Button variant="secondary" block busy={aiBusy} onClick={generate}>
          {aiBusy ? t('post.ai.generating') : t('post.ai.generate')}
        </Button>
        <p className="muted">{t('post.ai.cost')} {t('post.ai', { used: usage.ai_requests_today, limit: limit(plan.limits.daily_ai_requests) })}</p>
        {aiError && <FormError error={aiError} />}
      </details>

      {confirm && (
        <ConfirmDialog title={t('post.confirmNowTitle')} body={t('post.confirmNowBody', { channel: selectedTitle })}
          confirmLabel={t('post.confirmSend')} busy={busy} onConfirm={() => void submit()} onClose={() => setConfirm(false)} />
      )}
      {discard && (
        <ConfirmDialog title={t('post.draft.discardTitle')} body={t('post.draft.discardBody')} danger
          confirmLabel={t('post.draft.discardConfirm')} busy={discarding}
          onConfirm={() => void discardDraft()} onClose={() => setDiscard(false)} />
      )}
    </Page>
  )
}
