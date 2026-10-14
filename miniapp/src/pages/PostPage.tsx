import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import { ApiClientError } from '../api/client'
import { AI_STYLES, type AiStyle } from '../api/types'
import { ConfirmDialog } from '../components/Dialog'
import { Page, PageHeader } from '../components/Shell'
import { Button, EmptyState, ErrorState, FormError, LoadingBlock, openBotAvailable } from '../components/ui'
import { config } from '../config'
import { useI18n, type MessageKey } from '../i18n'
import { openBot } from '../telegram'
import { toClientError } from '../hooks/useResource'
import { defaultScheduleValue, isFutureEnough, isUnlimited, localInputToIso } from './format'

type Mode = 'schedule' | 'now'
type FieldKey = 'channel' | 'text' | 'when'

/**
 * Post yaratish: matn (qo'lda yoki AI), kanal (faqat o'zingizniki — server ham tekshiradi) va vaqt.
 * Yuborishni Mini App BAJARMAYDI: post navbatga yoziladi, botning rejalashtiruvchisi yuboradi.
 * Takroriy bosishdan himoya: `inFlight` ref + tugma `busy`; server ham 30 s ichida bir xil postni qaytaradi.
 */
export function PostPage() {
  const { me, channels, client, feed, go, notify, botUsername } = useAppData()
  const { t } = useI18n()
  const [channelId, setChannelId] = useState('')
  const [text, setText] = useState('')
  const [mode, setMode] = useState<Mode>('schedule')
  const [when, setWhen] = useState(() => defaultScheduleValue())
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [fieldError, setFieldError] = useState<{ field: FieldKey; key: MessageKey } | null>(null)
  const [idea, setIdea] = useState('')
  const [style, setStyle] = useState<AiStyle>('casual')
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState<ApiClientError | null>(null)
  const [aiIdeaError, setAiIdeaError] = useState(false)
  const inFlight = useRef(false)
  const aiInFlight = useRef(false)

  if (me.loading || channels.loading) return <Page><PageHeader title={t('post.title')} /><LoadingBlock rows={4} /></Page>
  if (!me.data) {
    return <Page><PageHeader title={t('post.title')} />
      {me.error && <ErrorState error={me.error} onRetry={me.reload} botUsername={botUsername} />}</Page>
  }
  if (!channels.data) {
    return <Page><PageHeader title={t('post.title')} />
      {channels.error && <ErrorState error={channels.error} onRetry={channels.reload} botUsername={botUsername} />}</Page>
  }

  const items = channels.data.items
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

  const validate = (): boolean => {
    const trimmed = text.trim()
    if (!selected) { setFieldError({ field: 'channel', key: 'post.errChannel' }); return false }
    if (!trimmed || trimmed.length > config.maxPostChars) { setFieldError({ field: 'text', key: 'post.errText' }); return false }
    if (mode === 'schedule' && !isFutureEnough(when)) { setFieldError({ field: 'when', key: 'post.errWhen' }); return false }
    setFieldError(null)
    return true
  }

  const submit = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const payload = mode === 'now'
        ? { channel_id: selected, text: text.trim(), send_now: true }
        : { channel_id: selected, text: text.trim(), scheduled_at: localInputToIso(when) ?? '' }
      const result = await client.createPost(payload)
      notify(result.created ? t(mode === 'now' ? 'post.createdNow' : 'post.created') : t('post.duplicate'))
      setText('')
      setIdea('')
      setConfirm(false)
      feed.reload()
      me.reload()
      go('schedule')
    } catch (e) {
      const err = toClientError(e)
      setError(err)
      setConfirm(false)
      if (err.field === 'text' || err.field === 'channel_id' || err.field === 'scheduled_at') {
        setFieldError({
          field: err.field === 'text' ? 'text' : err.field === 'channel_id' ? 'channel' : 'when',
          key: err.field === 'text' ? 'post.errText' : err.field === 'channel_id' ? 'post.errChannel' : 'post.errWhen',
        })
      }
      // Tarmoq/timeout: natija NOMA'LUM — ro'yxatni yangilab, yaratilgan bo'lsa ko'rinadi.
      if (err.code === 'network' || err.code === 'timeout') { feed.reload(); me.reload() }
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

  return (
    <Page>
      <PageHeader title={t('post.title')} />
      <p className="muted">{t('post.leadNew')}</p>

      <section className="card" aria-labelledby="ai">
        <h2 id="ai">{t('post.ai.title')}</h2>
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
      </section>

      <form className="card" onSubmit={onSubmit} noValidate aria-labelledby="compose">
        <h2 id="compose">{t('post.text')}</h2>
        <label className="field" htmlFor="channel">{t('post.channel')}</label>
        <select id="channel" className="input" value={selected} aria-invalid={fieldError?.field === 'channel' || undefined}
          onChange={(e) => { setChannelId(e.target.value); setFieldError(null) }}>
          {items.length > 1 && <option value="">{t('post.channelPick')}</option>}
          {items.map((c) => <option key={c.id} value={c.id}>{c.title || c.id}</option>)}
        </select>
        {fieldError?.field === 'channel' && <p className="field-error" role="alert">{t(fieldError.key)}</p>}

        <label className="field" htmlFor="text">{t('post.text')}</label>
        <textarea id="text" className="input" rows={7} value={text} maxLength={config.maxPostChars}
          placeholder={t('post.textPlaceholder')} aria-invalid={fieldError?.field === 'text' || undefined}
          onChange={(e) => { setText(e.target.value); setFieldError(null) }} />
        <p className="muted" aria-live="off">{t('post.counter', { n: text.length, max: config.maxPostChars })}</p>
        {fieldError?.field === 'text' && <p className="field-error" role="alert">{t(fieldError.key, { max: config.maxPostChars })}</p>}

        <fieldset className="segmented" aria-label={t('post.when')}>
          <legend className="field">{t('post.when')}</legend>
          <button type="button" aria-pressed={mode === 'schedule'} onClick={() => setMode('schedule')}>{t('post.whenSchedule')}</button>
          <button type="button" aria-pressed={mode === 'now'} onClick={() => setMode('now')}>{t('post.whenNow')}</button>
        </fieldset>

        {mode === 'schedule' ? (
          <>
            <label className="field" htmlFor="when">{t('post.date')}</label>
            <input id="when" className="input" type="datetime-local" value={when}
              aria-invalid={fieldError?.field === 'when' || undefined}
              onChange={(e) => { setWhen(e.target.value); setFieldError(null) }} />
            {fieldError?.field === 'when' && <p className="field-error" role="alert">{t(fieldError.key)}</p>}
          </>
        ) : <p className="muted">{t('post.nowHint')}</p>}

        {error && <FormError error={error} />}
        <Button type="submit" variant="primary" block busy={busy}>
          {busy ? t('post.saving') : mode === 'now' ? t('post.submitNow') : t('post.submitSchedule')}
        </Button>
        <p className="muted">{t('post.queue', { used: usage.pending_posts, limit: limit(plan.limits.queued_posts) })}</p>
      </form>

      {confirm && (
        <ConfirmDialog title={t('post.confirmNowTitle')} body={t('post.confirmNowBody', { channel: selectedTitle })}
          confirmLabel={t('post.confirmSend')} busy={busy} onConfirm={() => void submit()} onClose={() => setConfirm(false)} />
      )}
    </Page>
  )
}
