import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import type { Template } from '../api/types'
import { toClientError } from '../hooks/useResource'
import { useI18n } from '../i18n'
import { ConfirmDialog } from './Dialog'
import { Button, ErrorState, errorMessageKey } from './ui'

/**
 * Shablonlar (botdagi «📋 Shablonlar» bilan bir xil ro'yxat): saqlash, qo'llash, o'chirish. Yig'ilgan kartada
 * ro'yxat faqat ochilganda yuklanadi — muharrir sahifasini sekinlashtirmaydi.
 */
export function TemplatesCard({ text, onApply }: { text: string; onApply: (text: string) => void }) {
  const { client, notify, botUsername } = useAppData()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Template[] | null>(null)
  const [limit, setLimit] = useState(20)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [name, setName] = useState('')
  const [nameError, setNameError] = useState<'name' | 'text' | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingUse, setPendingUse] = useState<Template | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Template | null>(null)
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const out = await client.templates()
      setItems(out.items)
      setLimit(out.limit)
    } catch (e) {
      setError(toClientError(e))
    }
  }, [client])

  useEffect(() => {
    if (open && items === null && !error) void load()
  }, [open, items, error, load])

  const guarded = async (fn: () => Promise<void>) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      notify(t(errorMessageKey(toClientError(e).code)), 'error')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const save = () => guarded(async () => {
    const trimmed = name.trim()
    if (!trimmed) { setNameError('name'); return }
    if (!text.trim()) { setNameError('text'); return }
    setNameError(null)
    const out = await client.saveTemplate(trimmed.slice(0, 64), text.trim())
    notify(t(out.created ? 'tpl.saved' : 'tpl.duplicate'))
    setName('')
    await load()
  })

  const remove = (tpl: Template) => guarded(async () => {
    await client.deleteTemplate(tpl.id)
    setItems((cur) => (cur ?? []).filter((x) => x.id !== tpl.id))
    setPendingDelete(null)
    notify(t('tpl.deleted'))
  })

  const use = (tpl: Template) => {
    if (text.trim() && text.trim() !== tpl.text.trim()) { setPendingUse(tpl); return }
    onApply(tpl.text)
    notify(t('tpl.applied'))
  }

  return (
    <details className="card ai-card tpl-card" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <h2 id="tpl">{t('tpl.title')}{items && <span className="tpl-count">{t('tpl.count', { n: items.length, max: limit })}</span>}</h2>
      </summary>

      {error && !items && <ErrorState error={error} onRetry={() => void load()} botUsername={botUsername} />}
      {!error && items === null && <p className="muted" role="status">…</p>}
      {items && items.length === 0 && <p className="muted">{t('tpl.empty')}</p>}
      {items && items.length > 0 && (
        <ul className="tpl-list">
          {items.map((tpl) => (
            <li key={tpl.id} className="tpl-item">
              <div className="tpl-text">
                <strong className="tpl-name">{tpl.name}</strong>
                <span className="tpl-snippet muted">{tpl.text.replace(/<[^>]*>/g, '').slice(0, 90)}</span>
              </div>
              <div className="tpl-actions">
                <Button variant="secondary" onClick={() => use(tpl)} disabled={busy}>{t('tpl.use')}</Button>
                <Button variant="ghost" icon="trash" onClick={() => setPendingDelete(tpl)} disabled={busy}
                  aria-label={`${t('tpl.delete')}: ${tpl.name}`} title={t('tpl.delete')} />
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="tpl-save">
        <label className="field" htmlFor="tpl-name">{t('tpl.name')}</label>
        <div className="tpl-save-row">
          <input id="tpl-name" className="input" value={name} maxLength={64} aria-invalid={nameError === 'name' || undefined}
            onChange={(e) => { setName(e.target.value); setNameError(null) }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void save() } }} />
          <Button variant="secondary" icon="plus" busy={busy} onClick={() => void save()}
            disabled={Boolean(items && items.length >= limit)}>{t('tpl.save')}</Button>
        </div>
        {nameError === 'text' && <p className="field-error" role="alert">{t('tpl.needText')}</p>}
        {nameError === 'name' && <p className="field-error" role="alert">{t('tpl.needName')}</p>}
      </div>

      {pendingUse && (
        <ConfirmDialog title={t('tpl.replaceTitle')} body={t('tpl.replaceBody', { name: pendingUse.name })}
          confirmLabel={t('tpl.replaceConfirm')}
          onConfirm={() => { onApply(pendingUse.text); setPendingUse(null); notify(t('tpl.applied')) }}
          onClose={() => setPendingUse(null)} />
      )}
      {pendingDelete && (
        <ConfirmDialog title={t('tpl.deleteTitle')} body={t('tpl.deleteBody', { name: pendingDelete.name })} danger
          confirmLabel={t('tpl.delete')} busy={busy} onConfirm={() => void remove(pendingDelete)}
          onClose={() => setPendingDelete(null)} />
      )}
    </details>
  )
}
