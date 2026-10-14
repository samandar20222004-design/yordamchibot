import { describe, expect, it } from 'vitest'
import { isSafeLink, linkOpen, parseTelegramHtml, wrapSelection } from './richtext'

describe('wrapSelection', () => {
  it('tanlangan matnni o\'raydi va tanlovni saqlaydi', () => {
    const r = wrapSelection('Salom dunyo', 6, 11, '<b>', '</b>')
    expect(r.value).toBe('Salom <b>dunyo</b>')
    expect(r.value.slice(r.selStart, r.selEnd)).toBe('dunyo')
  })
  it('tanlov bo\'lmasa bo\'sh juftlik, kursor ichida', () => {
    const r = wrapSelection('ab', 1, 1, '<i>', '</i>')
    expect(r.value).toBe('a<i></i>b')
    expect(r.selStart).toBe(4)
    expect(r.selEnd).toBe(4)
  })
  it('chegaradan tashqari indekslar xavfsiz', () => {
    expect(wrapSelection('abc', -5, 99, '<u>', '</u>').value).toBe('<u>abc</u>')
    expect(wrapSelection('abc', 3, 1, '<b>', '</b>').value).toBe('a<b>bc</b>')
  })
})

describe('isSafeLink / linkOpen', () => {
  it('faqat http(s) va tg', () => {
    expect(isSafeLink('https://example.org/x?a=1&b=2')).toBe(true)
    expect(isSafeLink('tg://resolve?domain=a')).toBe(true)
    expect(isSafeLink('javascript:alert(1)')).toBe(false)
    expect(isSafeLink('data:text/html,x')).toBe(false)
    expect(isSafeLink('https://a b')).toBe(false)
    expect(isSafeLink('')).toBe(false)
  })
  it('linkOpen qo\'shtirnoq va & ni qochiradi', () => {
    expect(linkOpen(' https://a.b/?x=1&y="2" ')).toBe('<a href="https://a.b/?x=1&amp;y=&quot;2&quot;">')
  })
})

describe('parseTelegramHtml', () => {
  it('ichma-ich teglar va matn', () => {
    const t = parseTelegramHtml('A <b>qalin <i>kursiv</i></b> B')
    expect(t).toEqual([
      { kind: 'text', text: 'A ' },
      { kind: 'tag', tag: 'b', href: undefined, children: [
        { kind: 'text', text: 'qalin ' },
        { kind: 'tag', tag: 'i', href: undefined, children: [{ kind: 'text', text: 'kursiv' }] },
      ] },
      { kind: 'text', text: ' B' },
    ])
  })
  it('noma\'lum teg (<script>) matn bo\'lib qoladi, element yaratilmaydi', () => {
    const t = parseTelegramHtml('x <script>alert(1)</script> y')
    expect(t.every((n) => n.kind === 'text')).toBe(true)
    expect(t.map((n) => (n.kind === 'text' ? n.text : '')).join('')).toBe('x <script>alert(1)</script> y')
  })
  it('xavfli havola tegi rad etiladi (javascript:)', () => {
    const t = parseTelegramHtml('<a href="javascript:alert(1)">bos</a>')
    expect(t.some((n) => n.kind === 'tag')).toBe(false)
  })
  it('xavfsiz havola href bilan', () => {
    const t = parseTelegramHtml('<a href="https://example.org/?a=1&amp;b=2">x</a>')
    expect(t[0]).toMatchObject({ kind: 'tag', tag: 'a', href: 'https://example.org/?a=1&b=2' })
  })
  it('yopilmagan teg va ortiqcha yopuvchi teg xato bermaydi', () => {
    expect(() => parseTelegramHtml('<b>ochiq')).not.toThrow()
    const t = parseTelegramHtml('a</b>b')
    expect(t.map((n) => (n.kind === 'text' ? n.text : '')).join('')).toBe('a</b>b')
  })
  it('entity\'lar dekodlanadi', () => {
    const t = parseTelegramHtml('a &lt; b &amp;&amp; c')
    expect(t).toEqual([{ kind: 'text', text: 'a < b && c' }])
  })
  it('tg-spoiler va s/u/code', () => {
    const t = parseTelegramHtml('<tg-spoiler>x</tg-spoiler><s>y</s><u>z</u><code>c</code>')
    expect(t.map((n) => (n.kind === 'tag' ? n.tag : 'text'))).toEqual(['spoiler', 's', 'u', 'code'])
  })
})
