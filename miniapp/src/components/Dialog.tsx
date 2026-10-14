import { useEffect, useRef, type ReactNode } from 'react'
import { useI18n } from '../i18n'
import { Button } from './ui'

/** Modal oyna: Esc va "orqaga" bilan yopiladi, fokus ichkarida, fon aylanmaydi. */
export function Dialog({ title, onClose, children, busy = false }: {
  title: string; onClose: () => void; children: ReactNode; busy?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('[data-autofocus], textarea, select, input, button')?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [onClose, busy])
  return (
    <div className="dialog-backdrop" onClick={() => { if (!busy) onClose() }}>
      <div ref={ref} className="dialog" role="dialog" aria-modal="true" aria-label={title}
        onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}

export function ConfirmDialog({ title, body, confirmLabel, danger = false, busy = false, onConfirm, onClose }: {
  title: string; body: string; confirmLabel: string; danger?: boolean; busy?: boolean
  onConfirm: () => void; onClose: () => void
}) {
  const { t } = useI18n()
  return (
    <Dialog title={title} onClose={onClose} busy={busy}>
      <p>{body}</p>
      <div className="dialog-actions">
        <Button data-autofocus onClick={onClose} disabled={busy}>{t('common.back')}</Button>
        <Button variant="primary" className={danger ? 'btn-danger' : undefined} busy={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  )
}

export function Toast({ text, kind }: { text: string; kind: 'success' | 'error' }) {
  return (
    <div className={`toast toast-${kind}`} role={kind === 'error' ? 'alert' : 'status'} aria-live="polite">
      {text}
    </div>
  )
}
