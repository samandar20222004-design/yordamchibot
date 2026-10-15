import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import type { ScheduleProposal } from '../api/types'
import { toClientError } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { describeRecurrence } from '../pages/recurrence'
import { Icon } from './Icon'
import { Badge, Button, FormError } from './ui'

const EXAMPLES: MessageKey[] = ['smart.ex1', 'smart.ex2', 'smart.ex3']
const FAIL_KEYS: Record<string, MessageKey> = {
  no_time: 'smart.fail.no_time', unrecognized: 'smart.fail.unrecognized', past: 'smart.fail.past',
  empty: 'smart.fail.empty', too_long: 'smart.fail.too_long',
}
const MAX_CHARS = 300

/**
 * «Aqlli rejalash»: vaqtni erkin tilda yozish -> server tuzilma TAKLIFI qaytaradi (qoidalar, kerak bo'lsa AI) -> foydalanuvchi
 * ko'rib TASDIQLAYDI. Hech narsa o'zi yozilmaydi: «Qo'llash» faqat shakl maydonlarini to'ldiradi; qo'lda kiritish saqlanadi.
 */
export function SmartSchedule({ onApply, defaultTime }: { onApply: (proposal: ScheduleProposal) => void; defaultTime?: string }) {
  const { client } = useAppData()
  const { t, formatDateTime } = useI18n()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [proposal, setProposal] = useState<{ value: ScheduleProposal; source: 'rules' | 'ai' } | null>(null)
  const [failKey, setFailKey] = useState<MessageKey | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const inFlight = useRef(false)

  const run = async () => {
    if (inFlight.current) return
    const value = text.trim()
    setProposal(null)
    setError(null)
    if (!value) { setFailKey('smart.fail.empty'); return }
    setFailKey(null)
    inFlight.current = true
    setBusy(true)
    try {
      const res = await client.parseSchedule(value, defaultTime)
      if (res.ok) setProposal({ value: res.proposal, source: res.source })
      else setFailKey(FAIL_KEYS[res.reason] ?? 'smart.fail.unrecognized')
    } catch (e) {
      setError(toClientError(e))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const rec = proposal?.value.recurrence ?? null
  const recText = rec ? describeRecurrence(rec, t) : null

  return (
    <section className="smart" aria-labelledby="smart-title">
      <h3 id="smart-title"><Icon name="sparkle" size={18} /> {t('smart.title')}</h3>
      <p className="muted small">{t('smart.hint')}</p>
      <div className="chips" role="group" aria-label={t('smart.title')}>
        {EXAMPLES.map((k) => (
          <button key={k} type="button" className="chip" onClick={() => { setText(t(k)); setFailKey(null); setProposal(null) }}>{t(k)}</button>
        ))}
      </div>
      <div className="smart-row">
        <input className="input" type="text" value={text} maxLength={MAX_CHARS} placeholder={t('smart.placeholder')}
          aria-label={t('smart.title')} aria-invalid={failKey !== null || undefined}
          onChange={(e) => { setText(e.target.value); setFailKey(null) }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void run() } }} />
        <Button type="button" variant="secondary" busy={busy} onClick={() => void run()}>
          {busy ? t('smart.parsing') : t('smart.parse')}
        </Button>
      </div>
      <div aria-live="polite">
        {failKey && <p className="field-error" role="alert">{t(failKey)}</p>}
        {error && <FormError error={error} />}
        {proposal && (
          <div className="proposal" data-testid="smart-proposal">
            <div className="proposal-top">
              <strong>{t('smart.proposal')}</strong>
              <Badge>{t(proposal.source === 'ai' ? 'smart.source.ai' : 'smart.source.rules')}</Badge>
            </div>
            <p className="proposal-main">{recText ?? t('rep.none')}</p>
            <p className="muted">{t('smart.first', { when: formatDateTime(proposal.value.scheduled_at) })}</p>
            <div className="proposal-actions">
              <Button type="button" variant="primary" onClick={() => { onApply(proposal.value); setProposal(null); setText('') }}>{t('smart.apply')}</Button>
              <Button type="button" variant="ghost" onClick={() => setProposal(null)}>{t('common.cancel')}</Button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
