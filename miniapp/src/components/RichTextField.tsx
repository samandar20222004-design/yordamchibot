import { useRef, useState } from 'react'
import { useI18n, type MessageKey } from '../i18n'
import { FORMATS, isSafeLink, linkOpen, toggleFormat, wrapSelection } from '../pages/richtext'
import { Button } from './ui'

const FORMAT_KEYS: Record<string, MessageKey> = {
  bold: 'post.fmt.bold', italic: 'post.fmt.italic', underline: 'post.fmt.underline',
  strike: 'post.fmt.strike', code: 'post.fmt.code', spoiler: 'post.fmt.spoiler',
}

/** Matn maydoni + Telegram format paneli (B/I/U/S/kod/spoyler/havola). Teg qoldiqlari qolmaydi (`toggleFormat`). */
export function RichTextField({ id, value, onChange, maxLength, rows = 6, invalid = false }: {
  id: string; value: string; onChange: (next: string) => void; maxLength: number; rows?: number; invalid?: boolean
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLTextAreaElement | null>(null)
  const selection = useRef({ start: 0, end: 0 })
  const [linkRow, setLinkRow] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')

  const apply = (edit: { value: string; selStart: number; selEnd: number }) => {
    onChange(edit.value)
    requestAnimationFrame(() => {
      const el = ref.current
      if (!el) return
      el.focus()
      el.setSelectionRange(edit.selStart, edit.selEnd)
      selection.current = { start: edit.selStart, end: edit.selEnd }
    })
  }
  const remember = (el: HTMLTextAreaElement) => { selection.current = { start: el.selectionStart, end: el.selectionEnd } }

  return (
    <>
      <div className="toolbar" role="toolbar" aria-label={t('post.fmt.label')}>
        {FORMATS.map((f) => (
          <button key={f.id} type="button" className={`tool tool-${f.id}`} aria-label={t(FORMAT_KEYS[f.id]!)} title={t(FORMAT_KEYS[f.id]!)}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => apply(toggleFormat(value, selection.current.start, selection.current.end, f.open, f.close, t('post.fmt.placeholder')))}>
            {f.label}
          </button>
        ))}
        <button type="button" className="tool" aria-label={t('post.fmt.link')} title={t('post.fmt.link')} aria-expanded={linkRow}
          onMouseDown={(e) => e.preventDefault()} onClick={() => setLinkRow((v) => !v)}>🔗</button>
      </div>
      {linkRow && (
        <div className="link-row">
          <input className="input" type="url" inputMode="url" value={linkUrl} placeholder={t('post.fmt.linkUrl')} aria-label={t('post.fmt.linkUrl')}
            aria-invalid={(linkUrl !== '' && !isSafeLink(linkUrl)) || undefined} onChange={(e) => setLinkUrl(e.target.value)} />
          <Button variant="secondary" disabled={!isSafeLink(linkUrl)}
            onClick={() => { apply(wrapSelection(value, selection.current.start, selection.current.end, linkOpen(linkUrl), '</a>')); setLinkRow(false); setLinkUrl('') }}>
            {t('post.fmt.linkApply')}
          </Button>
        </div>
      )}
      <textarea id={id} ref={ref} className="input editor" rows={rows} value={value} maxLength={maxLength} aria-invalid={invalid || undefined}
        onChange={(e) => onChange(e.target.value)} onSelect={(e) => remember(e.currentTarget)} onBlur={(e) => remember(e.currentTarget)} />
    </>
  )
}
