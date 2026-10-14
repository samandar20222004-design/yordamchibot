// Telegram HTML to'plami (b/i/u/s/code/pre/a/tg-spoiler) uchun kichik yordamchilar: tahrirlagichda
// tanlangan matnni teg bilan o'rash va oldindan ko'rish uchun xavfsiz tahlil (dangerouslySetInnerHTML YO'Q).

export type FormatId = 'bold' | 'italic' | 'underline' | 'strike' | 'code' | 'spoiler'

export const FORMATS: ReadonlyArray<{ id: FormatId; open: string; close: string; label: string }> = [
  { id: 'bold', open: '<b>', close: '</b>', label: 'B' },
  { id: 'italic', open: '<i>', close: '</i>', label: 'I' },
  { id: 'underline', open: '<u>', close: '</u>', label: 'U' },
  { id: 'strike', open: '<s>', close: '</s>', label: 'S' },
  { id: 'code', open: '<code>', close: '</code>', label: '</>' },
  { id: 'spoiler', open: '<tg-spoiler>', close: '</tg-spoiler>', label: '◼' },
]

export interface Edit {
  value: string
  selStart: number
  selEnd: number
}

/** Tanlangan oraliqni `open`/`close` bilan o'raydi; tanlov bo'lmasa bo'sh juftlik qo'yadi va kursorni ichiga qo'yadi. */
export function wrapSelection(value: string, start: number, end: number, open: string, close: string): Edit {
  const a = Math.max(0, Math.min(start, end, value.length))
  const b = Math.max(0, Math.min(Math.max(start, end), value.length))
  const next = value.slice(0, a) + open + value.slice(a, b) + close + value.slice(b)
  return { value: next, selStart: a + open.length, selEnd: b + open.length }
}

/** Faqat http(s)/tg havolalar (xavfli protokollar rad etiladi). */
export function isSafeLink(url: string): boolean {
  return /^(https?:\/\/|tg:\/\/)[^\s<>"']+$/i.test(url.trim())
}

export function linkOpen(url: string): string {
  return `<a href="${url.trim().replace(/&/g, '&amp;').replace(/"/g, '&quot;')}">`
}

export type Node =
  | { kind: 'text'; text: string }
  | { kind: 'tag'; tag: 'b' | 'i' | 'u' | 's' | 'code' | 'pre' | 'a' | 'spoiler'; href?: string; children: Node[] }

const TAG_MAP: Record<string, Extract<Node, { kind: 'tag' }>['tag']> = {
  b: 'b', strong: 'b', i: 'i', em: 'i', u: 'u', ins: 'u', s: 's', strike: 's', del: 's',
  code: 'code', pre: 'pre', a: 'a', 'tg-spoiler': 'spoiler',
}

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" }
export const decodeEntities = (s: string) => s.replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENTITIES[m] ?? m)

const TOKEN = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^<>]*)?)>/g

/** Ruxsat etilgan teglarni daraxtga aylantiradi; boshqa teglar/yopilmaganlar oddiy matn bo'lib qoladi. */
export function parseTelegramHtml(input: string): Node[] {
  const root: Node[] = []
  const stack: { tag: string; node: Extract<Node, { kind: 'tag' }> }[] = []
  const current = () => (stack.length ? stack[stack.length - 1].node.children : root)
  const pushText = (text: string) => {
    if (!text) return
    const list = current()
    const last = list[list.length - 1]
    if (last && last.kind === 'text') last.text += text
    else list.push({ kind: 'text', text })
  }
  let pos = 0
  for (const m of input.matchAll(TOKEN)) {
    const idx = m.index ?? 0
    pushText(decodeEntities(input.slice(pos, idx)))
    pos = idx + m[0].length
    const closing = m[1] === '/'
    const name = m[2].toLowerCase()
    const mapped = TAG_MAP[name]
    if (!mapped) { pushText(m[0]); continue }
    if (!closing) {
      let href: string | undefined
      if (mapped === 'a') {
        const h = /href\s*=\s*"([^"]*)"/i.exec(m[3] ?? '')
        href = h ? decodeEntities(h[1]) : undefined
        if (!href || !isSafeLink(href)) { pushText(m[0]); continue }
      }
      const node: Extract<Node, { kind: 'tag' }> = { kind: 'tag', tag: mapped, href, children: [] }
      current().push(node)
      stack.push({ tag: name, node })
    } else {
      const at = [...stack].reverse().findIndex((e) => TAG_MAP[e.tag] === mapped)
      if (at === -1) { pushText(m[0]); continue }
      stack.length = stack.length - 1 - at // ichkaridagi yopilmaganlar ham yopiladi
    }
  }
  pushText(decodeEntities(input.slice(pos)))
  return root
}
