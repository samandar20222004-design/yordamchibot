// contenteditable <-> model ko'prigi. Brauzer o'zi yaratgan teglarni (b/strong/i/em/u/strike/span[style]/div/br) tushunadi,
// chizishda esa FAQAT o'zimizning toza tuzilmani yaratadi (innerHTML ISHLATILMAYDI).
import { ORDER, normalize, segments, sameFmt, type Fmt, type Model, type Span } from './richModel'
import { isSafeLink } from './richtext'

const BLOCK = new Set(['DIV', 'P', 'LI', 'BLOCKQUOTE', 'H1', 'H2', 'H3'])
export const SENTINEL_ATTR = 'data-sentinel'

function fmtsOf(el: Element): { f: Fmt; v?: string }[] {
  const tag = el.tagName.toLowerCase()
  const out: { f: Fmt; v?: string }[] = []
  if (tag === 'b' || tag === 'strong') out.push({ f: 'bold' })
  else if (tag === 'i' || tag === 'em') out.push({ f: 'italic' })
  else if (tag === 'u' || tag === 'ins') out.push({ f: 'underline' })
  else if (tag === 's' || tag === 'strike' || tag === 'del') out.push({ f: 'strike' })
  else if (tag === 'code') out.push({ f: 'code' })
  else if (tag === 'pre') out.push({ f: 'pre' })
  else if (tag === 'tg-spoiler') out.push({ f: 'spoiler' })
  else if (tag === 'a') {
    const href = el.getAttribute('href') ?? ''
    if (isSafeLink(href)) out.push({ f: 'link', v: href })
  } else if (tag === 'tg-emoji') {
    const id = el.getAttribute('emoji-id') ?? ''
    if (/^\d{1,32}$/.test(id)) out.push({ f: 'emoji', v: id })
  }
  const style = (el as HTMLElement).style
  if (style) {
    if (/^(bold|[6-9]00)$/.test(style.fontWeight)) out.push({ f: 'bold' })
    if (style.fontStyle === 'italic') out.push({ f: 'italic' })
    const deco = `${style.textDecoration} ${style.textDecorationLine}`
    if (deco.includes('underline')) out.push({ f: 'underline' })
    if (deco.includes('line-through')) out.push({ f: 'strike' })
  }
  return out
}

/** DOM (yoki parcha) -> model. */
export function domToModel(root: ParentNode): Model {
  let text = ''
  const spans: Span[] = []
  const walk = (parent: ParentNode) => {
    for (const child of Array.from(parent.childNodes)) {
      if (child.nodeType === 3) {
        text += (child.nodeValue ?? '').replace(/​/g, '').replace(/ /g, ' ')
        continue
      }
      if (child.nodeType !== 1) continue
      const el = child as Element
      if (el.hasAttribute(SENTINEL_ATTR)) continue
      const tag = el.tagName
      if (tag === 'BR') { text += '\n'; continue }
      const block = BLOCK.has(tag)
      if (block && text.length > 0 && !text.endsWith('\n')) text += '\n'
      const start = text.length
      const onlyBr = block && el.childNodes.length === 1 && (el.firstChild as Element).tagName === 'BR'
      if (!onlyBr) walk(el)
      if (text.length > start) for (const x of fmtsOf(el)) spans.push({ s: start, e: text.length, f: x.f, v: x.v })
    }
  }
  walk(root)
  return { text, spans: normalize(spans, text.length) }
}

const TAGS: Record<Fmt, string> = {
  link: 'a', bold: 'b', italic: 'i', underline: 'u', strike: 's', spoiler: 'tg-spoiler', code: 'code', pre: 'pre', emoji: 'tg-emoji',
}

/** Modelni toza DOM sifatida chizadi. Matn oxiri "\n" bilan tugasa, bo'sh qator ko'rinishi uchun sentinel <br> qo'shiladi. */
export function renderModel(root: HTMLElement, model: Model): void {
  while (root.firstChild) root.removeChild(root.firstChild)
  const doc = root.ownerDocument
  const stack: { f: Fmt; v?: string; el: HTMLElement }[] = []
  for (const seg of segments(model)) {
    let keep = 0
    while (keep < stack.length && keep < seg.want.length && sameFmt(stack[keep], seg.want[keep])) keep++
    stack.length = keep
    for (let k = keep; k < seg.want.length; k++) {
      const w = seg.want[k]
      const el = doc.createElement(TAGS[w.f])
      if (w.f === 'link') el.setAttribute('href', w.v ?? '')
      if (w.f === 'emoji') el.setAttribute('emoji-id', w.v ?? '')
      const host = k === 0 ? root : stack[k - 1].el
      host.appendChild(el)
      stack.push({ ...w, el })
    }
    const host = stack.length ? stack[stack.length - 1].el : root
    host.appendChild(doc.createTextNode(model.text.slice(seg.a, seg.b)))
  }
  if (model.text.endsWith('\n')) {
    const br = doc.createElement('br')
    br.setAttribute(SENTINEL_ATTR, '1')
    root.appendChild(br)
  }
}

/** Tugun+offset -> matn offseti (model bilan bir xil qoidalar: parcha modeli uzunligi). */
export function offsetOf(root: HTMLElement, node: Node, offset: number): number {
  const range = root.ownerDocument.createRange()
  range.setStart(root, 0)
  range.setEnd(node, offset)
  const holder = root.ownerDocument.createElement('div')
  holder.appendChild(range.cloneContents())
  return domToModel(holder).text.length
}

/** Matn offsetlari bo'yicha tanlov o'rnatadi (DOM `renderModel` bilan chizilgan bo'lishi kerak). */
export function setSelectionOffsets(root: HTMLElement, a: number, b: number): void {
  const sel = root.ownerDocument.defaultView?.getSelection()
  if (!sel) return
  const walker = root.ownerDocument.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */)
  const locate = (target: number): [Node, number] => {
    let seen = 0
    let last: Text | null = null
    for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
      const len = n.data.length
      if (target <= seen + len) return [n, target - seen]
      seen += len
      last = n
    }
    return last ? [last, last.data.length] : [root, root.childNodes.length]
  }
  walker.currentNode = root
  const [sn, so] = locate(a)
  walker.currentNode = root
  const [en, eo] = locate(b)
  const range = root.ownerDocument.createRange()
  range.setStart(sn, so)
  range.setEnd(en, eo)
  sel.removeAllRanges()
  sel.addRange(range)
}

export { ORDER }
