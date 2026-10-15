import { describe, expect, it } from 'vitest'
import { isSafeLink, linkOpen, parseTelegramHtml, toggleFormat, wrapSelection } from './richtext'

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

describe('toggleFormat (format tugmalari)', () => {
  const B = ['<b>', '</b>'] as const
  it('tanlov bo\'lmasa bo\'sh teg QOLDIRMAYDI: andoza matn teg ichida tanlanadi', () => {
    const r = toggleFormat('ab', 1, 1, ...B, 'matn')
    expect(r.value).toBe('a<b>matn</b>b')
    expect(r.value.slice(r.selStart, r.selEnd)).toBe('matn')
    expect(r.value).not.toContain('<b></b>')
  })
  it('tanlangan matnni o\'raydi; qayta bosilsa olib tashlaydi (tanlangan holda ham, tashqaridan ham)', () => {
    const w = toggleFormat('Salom dunyo', 6, 11, ...B, 'x')
    expect(w.value).toBe('Salom <b>dunyo</b>')
    const off = toggleFormat(w.value, w.selStart, w.selEnd, ...B, 'x')
    expect(off.value).toBe('Salom dunyo')
    expect(off.value.slice(off.selStart, off.selEnd)).toBe('dunyo')
    const all = toggleFormat('<b>dunyo</b>', 0, 12, ...B, 'x')
    expect(all.value).toBe('dunyo')
  })
  it('kursor bo\'sh juftlik ichida: juftlik olib tashlanadi (yetim teg yo\'q)', () => {
    expect(toggleFormat('a<b></b>c', 4, 4, ...B, 'matn').value).toBe('ac')
  })
  it('har xil teglar ketma-ket: ichma-ich to\'g\'ri (S, U, spoyler bo\'sh qolmaydi)', () => {
    let v = 'x'
    let sel = { s: 1, e: 1 }
    for (const [o, c] of [['<s>', '</s>'], ['<u>', '</u>'], ['<tg-spoiler>', '</tg-spoiler>']] as const) {
      const r = toggleFormat(v, sel.s, sel.e, o, c, 'matn')
      v = r.value
      sel = { s: r.selStart, e: r.selEnd }
    }
    expect(v).toBe('x<s><u><tg-spoiler>matn</tg-spoiler></u></s>')
  })
})
