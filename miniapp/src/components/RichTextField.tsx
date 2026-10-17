import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useI18n, type MessageKey } from '../i18n'
import { covered, insertLink, modelToHtml, parseModel, toggle, unlink, wordAt, type Fmt, type Model } from '../pages/richModel'
import { domToModel, offsetOf, renderModel, setSelectionOffsets } from '../pages/richDom'
import { isValidLinkInput, normalizeLink } from '../pages/richtext'
import { Button } from './ui'

const TOOLS: ReadonlyArray<{ id: string; fmt: Fmt; label: string; key: MessageKey; native?: string }> = [
  { id: 'bold', fmt: 'bold', label: 'B', key: 'post.fmt.bold', native: 'bold' },
  { id: 'italic', fmt: 'italic', label: 'I', key: 'post.fmt.italic', native: 'italic' },
  { id: 'underline', fmt: 'underline', label: 'U', key: 'post.fmt.underline', native: 'underline' },
  { id: 'strike', fmt: 'strike', label: 'S', key: 'post.fmt.strike', native: 'strikeThrough' },
  { id: 'code', fmt: 'code', label: '</>', key: 'post.fmt.code' },
  { id: 'spoiler', fmt: 'spoiler', label: '◼', key: 'post.fmt.spoiler' },
]

/** Test/yordamchi: muharrir elementidagi joriy Telegram HTML. */
export function readEditor(el: Element): string {
  return modelToHtml(domToModel(el))
}

/**
 * Ko'rinadigan (WYSIWYG) matn muharriri + Telegram format paneli. Foydalanuvchi teg ko'rmaydi: B/I/U/S/kod/yashirin/havola
 * tanlangan matnga ta'sir qiladi (qayta bosilsa olib tashlanadi), qiymat esa Telegram HTML sifatida saqlanadi.
 * Format modeli (`richModel`) teg qoldig'i/ikki marta o'rashni imkonsiz qiladi.
 */
export function RichTextField({ id, value, onChange, maxLength, rows = 6, invalid = false, placeholder }: {
  id: string; value: string; onChange: (next: string) => void; maxLength: number; rows?: number; invalid?: boolean; placeholder?: string
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement | null>(null)
  const lastHtml = useRef<string | null>(null)
  const saved = useRef<{ a: number; b: number }>({ a: 0, b: 0 })
  const [active, setActive] = useState<ReadonlySet<Fmt>>(new Set())
  const [empty, setEmpty] = useState(value === '')
  const [linkRow, setLinkRow] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')

  const current = (): Model => domToModel(ref.current as HTMLElement)

  const selection = useCallback((): { a: number; b: number } | null => {
    const root = ref.current
    const sel = root?.ownerDocument.defaultView?.getSelection()
    if (!root || !sel || sel.rangeCount === 0) return null
    const r = sel.getRangeAt(0)
    if (!root.contains(r.startContainer) || !root.contains(r.endContainer)) return null
    const a = offsetOf(root, r.startContainer, r.startOffset)
    const b = offsetOf(root, r.endContainer, r.endOffset)
    return { a: Math.min(a, b), b: Math.max(a, b) }
  }, [])

  const refreshActive = useCallback(() => {
    const root = ref.current
    if (!root) return
    const sel = selection()
    if (!sel) return
    saved.current = sel
    const model = domToModel(root)
    const next = new Set<Fmt>()
    const [a, b] = sel.a === sel.b ? [Math.max(0, sel.a - 1), sel.a] : [sel.a, sel.b]
    for (const tool of TOOLS) if (covered(model, a, b, tool.fmt)) next.add(tool.fmt)
    if (covered(model, a, b, 'link')) next.add('link')
    setActive((prev) => (prev.size === next.size && [...next].every((x) => prev.has(x)) ? prev : next))
  }, [selection])

  useEffect(() => {
    const doc = ref.current?.ownerDocument
    doc?.addEventListener('selectionchange', refreshActive)
    return () => doc?.removeEventListener('selectionchange', refreshActive)
  }, [refreshActive])

  // Tashqaridan kelgan qiymat (qoralama, tahrirlash oynasi) — faqat bizdan chiqmagan bo'lsa qayta chiziladi.
  useLayoutEffect(() => {
    const root = ref.current
    if (!root || value === lastHtml.current) return
    lastHtml.current = value
    renderModel(root, parseModel(value))
    setEmpty(value === '')
  }, [value])

  const emit = (model: Model) => {
    const html = modelToHtml(model)
    lastHtml.current = html
    setEmpty(html === '')
    onChange(html)
  }

  const onInput = () => {
    const root = ref.current
    if (!root) return
    const model = current()
    if (model.text === '' && root.childNodes.length > 0) renderModel(root, model) // :empty/placeholder tiklanadi
    emit(model)
  }

  const apply = (edit: (m: Model, a: number, b: number) => Model, sel?: { a: number; b: number } | null) => {
    const root = ref.current
    if (!root) return false
    const range = sel ?? selection() ?? saved.current
    const model = current()
    let { a, b } = range
    if (a === b) {
      const w = wordAt(model.text, a)
      if (!w) return false
      ;[a, b] = w
    }
    const next = edit(model, a, b)
    if (next === model) return false
    renderModel(root, next)
    setSelectionOffsets(root, a, b)
    emit(next)
    saved.current = { a, b }
    refreshActive()
    return true
  }

  const onTool = (tool: (typeof TOOLS)[number]) => {
    const root = ref.current
    if (!root) return
    const sel = selection() ?? saved.current // focus() tanlovni o'zgartirishi mumkin — avval o'qiladi
    root.focus({ preventScroll: true })
    const handled = apply((m, a, b) => toggle(m, a, b, tool.fmt), sel)
    if (!handled && tool.native) {
      try { root.ownerDocument.execCommand?.(tool.native) } catch { /* qo'llab-quvvatlanmasa e'tiborsiz */ }
      onInput()
    }
  }

  const onLink = () => {
    const root = ref.current
    if (root && active.has('link')) { // havola ichida bosilsa — olib tashlash
      apply((m, a, b) => unlink(m, a, b))
      return
    }
    setLinkRow((v) => !v)
  }

  const applyLink = () => {
    if (!isValidLinkInput(linkUrl)) return
    const href = normalizeLink(linkUrl)
    const sel = selection() ?? saved.current
    const root = ref.current
    if (!root) return
    const model = current()
    const next = insertLink(model, sel.a, sel.b, href)
    renderModel(root, next)
    emit(next)
    setLinkRow(false)
    setLinkUrl('')
  }

  const onPaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault() // tashqi HTML/uslub kirmasin — faqat oddiy matn
    const text = e.clipboardData.getData('text/plain')
    if (!text) return
    const root = ref.current
    const sel = root?.ownerDocument.defaultView?.getSelection()
    if (!root || !sel || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    range.deleteContents()
    const node = root.ownerDocument.createTextNode(text)
    range.insertNode(node)
    range.setStartAfter(node)
    range.collapse(true)
    sel.removeAllRanges()
    sel.addRange(range)
    onInput()
  }

  return (
    <>
      <div className="toolbar" role="toolbar" aria-label={t('post.fmt.label')}>
        {TOOLS.map((tool) => (
          <button key={tool.id} type="button" className={`tool tool-${tool.id}${active.has(tool.fmt) ? ' is-on' : ''}`}
            aria-label={t(tool.key)} title={t(tool.key)} aria-pressed={active.has(tool.fmt)}
            onMouseDown={(e) => e.preventDefault()} onClick={() => onTool(tool)}>
            {tool.label}
          </button>
        ))}
        <button type="button" className={`tool${active.has('link') ? ' is-on' : ''}`} aria-label={t('post.fmt.link')} title={t('post.fmt.link')}
          aria-expanded={linkRow} onMouseDown={(e) => e.preventDefault()} onClick={onLink}>🔗</button>
      </div>
      {linkRow && (
        <div className="link-row">
          <input className="input" type="text" inputMode="url" autoCapitalize="none" autoCorrect="off" value={linkUrl} placeholder={t('post.fmt.linkUrl')} aria-label={t('post.fmt.linkUrl')}
            aria-invalid={(linkUrl !== '' && !isValidLinkInput(linkUrl)) || undefined} onChange={(e) => setLinkUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); applyLink() } }} />
          <Button variant="secondary" disabled={!isValidLinkInput(linkUrl)} onClick={applyLink}>{t('post.fmt.linkApply')}</Button>
        </div>
      )}
      <div id={id} ref={ref} className={`input editor rich${empty ? ' is-empty' : ''}`} contentEditable suppressContentEditableWarning
        role="textbox" aria-multiline="true" aria-label={t('post.text')} aria-invalid={invalid || undefined}
        data-placeholder={placeholder ?? t('post.textPlaceholder')} data-maxlength={maxLength}
        style={{ minHeight: `${Math.max(3, rows) * 1.5 + 1.2}em` }}
        spellCheck onInput={onInput} onPaste={onPaste} onBlur={refreshActive} />
    </>
  )
}
