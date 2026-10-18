import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import { ApiClientError } from '../api/client'
import type { MarketThread, MarketThreadItem } from '../api/types'
import { ConfirmDialog } from '../components/Dialog'
import { SubPage } from '../components/SubPage'
import { Button, ErrorState, FormError, LoadingBlock, openBotAvailable } from '../components/ui'
import { toClientError, type Resource } from '../hooks/useResource'
import { useI18n } from '../i18n'
import { haptic, openBot } from '../telegram'

/** «Suhbatlar»: ochiq yozishmalar ro'yxati. */
export function ThreadList({ threads, onOpen }: { threads: Resource<{ items: MarketThreadItem[] }>; onOpen: (id: number) => void }) {
  const { t, formatDateTime } = useI18n()
  const { botUsername } = useAppData()
  if (threads.loading) return <LoadingBlock rows={3} />
  if (!threads.data && threads.error) return <ErrorState error={threads.error} onRetry={threads.reload} botUsername={botUsername} />
  const items = threads.data?.items ?? []
  if (items.length === 0) return <section className="card"><p className="muted">{t('mk.threadsEmpty')}</p></section>
  return (
    <ul className="list">
      {items.map((x) => (
        <li key={x.id}>
          <button type="button" className="item mk-row" onClick={() => onOpen(x.id)}>
            <span className="mk-row-main">
              <strong className="mk-row-title">{x.title}</strong>
              <span className="muted small">{t(x.role === 'owner' ? 'mk.roleAdv' : 'mk.roleOwner')} · {formatDateTime(x.updated_at)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Bitta suhbat: xabarlar, javob, yopish va (egasi uchun) bloklash. */
export function ThreadView({ id, onBack, onChanged }: { id: number; onBack: () => void; onChanged: () => void }) {
  const { client, notify, botUsername } = useAppData()
  const { t, formatDateTime } = useI18n()
  const [data, setData] = useState<MarketThread | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<ApiClientError | null>(null)
  const [ask, setAsk] = useState<'close' | 'block' | null>(null)
  const end = useRef<HTMLDivElement>(null)

  const load = useCallback((signal?: AbortSignal) => {
    client.marketThread(id, signal).then(
      (d) => { setData(d); setError(null) },
      (e) => { if (!signal?.aborted) setError(toClientError(e)) },
    )
  }, [client, id])

  useEffect(() => {
    const ctl = new AbortController()
    load(ctl.signal)
    return () => ctl.abort()
  }, [load])
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [data?.messages.length])

  const send = async () => {
    const body = text.trim()
    if (!body || busy) return
    setBusy(true)
    setFormError(null)
    try {
      const res = await client.marketReply(id, body)
      setText('')
      haptic('success')
      if (!res.delivered) notify(t('mk.notDelivered'), 'error')
      load()
      onChanged()
    } catch (e) {
      haptic('error')
      setFormError(toClientError(e))
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!ask) return
    setBusy(true)
    try {
      if (ask === 'close') await client.marketCloseThread(id)
      else await client.marketBlock(id)
      notify(t(ask === 'close' ? 'mk.threadClosed' : 'mk.blocked'))
      onChanged()
      onBack()
    } catch (e) {
      notify(t(`err.${toClientError(e).code}` as never), 'error')
      setBusy(false)
      setAsk(null)
    }
  }

  const open = data?.thread.status === 'open'
  const roleLabel = data ? t(data.thread.role === 'owner' ? 'mk.roleAdv' : 'mk.roleOwner') : ''
  return (
    <SubPage title={data?.thread.title ?? t('mk.tabChats')} onBack={onBack}>
      {!data && !error && <LoadingBlock rows={4} />}
      {error && <ErrorState error={error} onRetry={() => load()} botUsername={botUsername} />}
      {data && (
        <>
          <p className="muted small mk-peer">{roleLabel}</p>
          <div className="mk-thread" role="log" aria-live="polite">
            {data.messages.map((m, i) => (
              <div key={i} className={`mk-bubble${m.mine ? ' mk-bubble-mine' : ''}`}>
                <span className="mk-bubble-who">{m.mine ? t('mk.you') : roleLabel} · {formatDateTime(m.at)}</span>
                <p>{m.text}</p>
              </div>
            ))}
            <div ref={end} />
          </div>
          {open ? (
            <section className="card mk-reply">
              <textarea className="input" rows={3} value={text} maxLength={1000} placeholder={t('mk.reply')} aria-label={t('mk.reply')}
                onChange={(e) => setText(e.target.value)} />
              {formError && <FormError error={formError} />}
              <Button variant="primary" block icon="send" busy={busy} disabled={text.trim() === ''} onClick={send}>{t('mk.send')}</Button>
              <p className="muted small">{t('mk.contactHint')}</p>
              {openBotAvailable(botUsername) && <Button variant="ghost" block icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>}
              <div className="mk-actions">
                <Button block onClick={() => setAsk('close')}>{t('mk.closeThread')}</Button>
                {data.thread.role === 'owner' && <Button variant="ghost" block onClick={() => setAsk('block')}>{t('mk.blockUser')}</Button>}
              </div>
            </section>
          ) : <p className="muted card">{t('mk.threadClosed')}</p>}
          {ask && (
            <ConfirmDialog title={t(ask === 'close' ? 'mk.closeThread' : 'mk.blockUser')} body={ask === 'block' ? t('mk.blockAsk') : t('mk.closeThread')}
              confirmLabel={t(ask === 'close' ? 'mk.closeThread' : 'mk.blockUser')} danger={ask === 'block'} busy={busy}
              onConfirm={confirm} onClose={() => setAsk(null)} />
          )}
        </>
      )}
    </SubPage>
  )
}
