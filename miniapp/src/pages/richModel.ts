// Muharrirning formatlash modeli: tekst + oraliqlar (Telegram entity'lariga o'xshash). Tugmalar shu modelda ishlaydi
// (teg qoldig'i/ikki marta o'rash MUMKIN EMAS), keyin deterministik ravishda Telegram HTML'ga aylanadi.
import { decodeEntities, isSafeLink, parseTelegramHtml, type Node as TgNode } from './richtext'

export type Fmt = 'link' | 'bold' | 'italic' | 'underline' | 'strike' | 'spoiler' | 'code' | 'pre' | 'emoji'
/** Ichma-ich joylashish tartibi (tashqaridan ichkariga). */
export const ORDER: readonly Fmt[] = ['link', 'bold', 'italic', 'underline', 'strike', 'spoiler', 'code', 'pre', 'emoji']
export interface Span { s: number; e: number; f: Fmt; v?: string }
export interface Model { text: string; spans: Span[] }

export const TAG: Record<Fmt, [string, string]> = {
  link: ['a', 'a'], bold: ['b', 'b'], italic: ['i', 'i'], underline: ['u', 'u'], strike: ['s', 's'],
  spoiler: ['tg-spoiler', 'tg-spoiler'], code: ['code', 'code'], pre: ['pre', 'pre'], emoji: ['tg-emoji', 'tg-emoji'],
}
const NODE_FMT: Record<string, Fmt> = { b: 'bold', i: 'italic', u: 'underline', s: 's' as never, code: 'code', pre: 'pre', a: 'link', spoiler: 'spoiler', emoji: 'emoji' }
NODE_FMT.s = 'strike'

const esc = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escAttr = (t: string) => esc(t).replace(/"/g, '&quot;')

function openTag(f: Fmt, v?: string): string {
  if (f === 'link') return `<a href="${escAttr(v ?? '')}">`
  if (f === 'emoji') return `<tg-emoji emoji-id="${escAttr(v ?? '')}">`
  return `<${TAG[f][0]}>`
}
const closeTag = (f: Fmt) => `</${TAG[f][1]}>`

export function normalize(spans: Span[], length: number): Span[] {
  const out: Span[] = []
  for (const f of ORDER) {
    const same = spans.filter((x) => x.f === f).map((x) => ({ ...x, s: Math.max(0, x.s), e: Math.min(length, x.e) }))
      .filter((x) => x.e > x.s).sort((a, b) => a.s - b.s || a.e - b.e)
    let cur: Span | null = null
    for (const x of same) {
      if (cur && x.s <= cur.e && (x.v ?? '') === (cur.v ?? '') && f !== 'emoji') cur.e = Math.max(cur.e, x.e)
      else { if (cur) out.push(cur); cur = { ...x } }
    }
    if (cur) out.push(cur)
  }
  return out
}

/** Telegram HTML -> model. */
export function parseModel(html: string): Model {
  let text = ''
  const spans: Span[] = []
  const walk = (nodes: TgNode[]) => {
    for (const n of nodes) {
      if (n.kind === 'text') { text += n.text; continue }
      const start = text.length
      walk(n.children)
      const f = NODE_FMT[n.tag]
      if (f && text.length > start) spans.push({ s: start, e: text.length, f, v: n.href ?? n.emojiId })
    }
  }
  walk(parseTelegramHtml(html))
  return { text, spans: normalize(spans, text.length) }
}

export interface Segment { a: number; b: number; want: { f: Fmt; v?: string }[] }

/** Matnni bir xil format to'plamli bo'laklarga ajratadi (HTML va DOM chizish uchun umumiy). */
export function segments(model: Model): Segment[] {
  const { text } = model
  if (!text) return []
  const spans = normalize(model.spans, text.length)
  const cuts = new Set<number>([0, text.length])
  for (const sp of spans) { cuts.add(sp.s); cuts.add(sp.e) }
  const points = [...cuts].sort((x, y) => x - y)
  const out: Segment[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    const active = ORDER.flatMap((f) => spans.filter((x) => x.f === f && x.s <= a && x.e >= b).map((x) => ({ f, v: x.v })))
    // code/pre ichida boshqa format bo'lmaydi (Telegram qoidasi)
    const inCode = active.some((x) => x.f === 'code' || x.f === 'pre')
    out.push({ a, b, want: inCode ? active.filter((x) => x.f === 'code' || x.f === 'pre' || x.f === 'link') : active })
  }
  return out
}

export const sameFmt = (x: { f: Fmt; v?: string }, y: { f: Fmt; v?: string }) => x.f === y.f && (x.v ?? '') === (y.v ?? '')

/** Model -> Telegram HTML (deterministik, to'g'ri ichma-ich). */
export function modelToHtml(model: Model): string {
  let html = ''
  let stack: { f: Fmt; v?: string }[] = []
  for (const seg of segments(model)) {
    let keep = 0
    while (keep < stack.length && keep < seg.want.length && sameFmt(stack[keep], seg.want[keep])) keep++
    for (let k = stack.length - 1; k >= keep; k--) html += closeTag(stack[k].f)
    for (let k = keep; k < seg.want.length; k++) html += openTag(seg.want[k].f, seg.want[k].v)
    stack = seg.want
    html += esc(model.text.slice(seg.a, seg.b))
  }
  for (let k = stack.length - 1; k >= 0; k--) html += closeTag(stack[k].f)
  return html
}

/** [a, b) butunlay `f` bilan qoplanganmi. */
export function covered(model: Model, a: number, b: number, f: Fmt): boolean {
  if (b <= a) return false
  let pos = a
  const list = model.spans.filter((x) => x.f === f).sort((x, y) => x.s - y.s)
  for (const x of list) {
    if (x.e <= pos) continue
    if (x.s > pos) return false
    pos = x.e
    if (pos >= b) return true
  }
  return pos >= b
}

function cut(spans: Span[], f: Fmt, a: number, b: number): Span[] {
  const out: Span[] = []
  for (const x of spans) {
    if (x.f !== f || x.e <= a || x.s >= b) { out.push(x); continue }
    if (x.s < a) out.push({ ...x, e: a })
    if (x.e > b) out.push({ ...x, s: b })
  }
  return out
}

/** Format tugmasi: butunlay qoplangan bo'lsa OLIB TASHLAYDI, aks holda [a, b) ga qo'shadi. Teg qoldig'i qolmaydi. */
export function toggle(model: Model, a: number, b: number, f: Fmt, v?: string): Model {
  const lo = Math.max(0, Math.min(a, b))
  const hi = Math.min(model.text.length, Math.max(a, b))
  if (hi <= lo) return model
  if (f !== 'link' && covered(model, lo, hi, f)) {
    return { text: model.text, spans: normalize(cut(model.spans, f, lo, hi), model.text.length) }
  }
  let spans = cut(model.spans, f, lo, hi)
  if (f === 'code' || f === 'pre') {
    for (const other of ORDER) if (other !== 'link' && other !== f && other !== 'code' && other !== 'pre') spans = cut(spans, other, lo, hi)
  }
  spans.push({ s: lo, e: hi, f, v })
  return { text: model.text, spans: normalize(spans, model.text.length) }
}

/** Havolani olib tashlash (tanlov ichida). */
export function unlink(model: Model, a: number, b: number): Model {
  return { text: model.text, spans: normalize(cut(model.spans, 'link', Math.min(a, b), Math.max(a, b)), model.text.length) }
}

/** Kursor so'z ichida bo'lsa shu so'zni qaytaradi (tugma bosilganda tanlov bo'sh bo'lsa). */
export function wordAt(text: string, pos: number): [number, number] | null {
  const isWord = (ch: string | undefined) => !!ch && /[\p{L}\p{N}_'’ʻʼ-]/u.test(ch)
  let a = pos
  let b = pos
  while (a > 0 && isWord(text[a - 1])) a--
  while (b < text.length && isWord(text[b])) b++
  return b > a ? [a, b] : null
}

/** Matn oxirida/ichida havola qo'yish: tanlov bo'sh bo'lsa havola matni sifatida URL'ning o'zi qo'shiladi. */
export function insertLink(model: Model, a: number, b: number, url: string): Model {
  const href = url
  if (!isSafeLink(href)) return model
  if (b > a) return toggle(model, a, b, 'link', href)
  const label = decodeEntities(href)
  const text = model.text.slice(0, a) + label + model.text.slice(a)
  const shifted = model.spans.map((x) => ({ ...x, s: x.s >= a ? x.s + label.length : x.s, e: x.e >= a ? x.e + label.length : x.e }))
  shifted.push({ s: a, e: a + label.length, f: 'link', v: href })
  return { text, spans: normalize(shifted, text.length) }
}
