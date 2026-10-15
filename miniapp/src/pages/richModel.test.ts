import { describe, expect, it } from 'vitest'
import { covered, insertLink, modelToHtml, parseModel, toggle, unlink, wordAt } from './richModel'
import { isValidLinkInput, normalizeLink } from './richtext'

describe('richModel: format modeli', () => {
  it('HTML <-> model aylanishi o\'zgarmaydi (ichma-ich, havola, spoyler, premium emoji)', () => {
    for (const html of [
      'oddiy matn', '<b>qalin</b> va <i>kursiv</i>', '<b><i>ikkalasi</i></b>', '<a href="https://example.org/a?x=1&amp;y=2">havola</a>',
      '<tg-spoiler>sir</tg-spoiler>', 'A <tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> B', '1 &lt; 2 &amp; 3 &gt; 2',
    ]) expect(modelToHtml(parseModel(html))).toBe(html)
  })

  it('toggle: bir xil format ikki marta bosilsa olib tashlanadi; teg qoldig\'i yo\'q', () => {
    const m0 = parseModel('Salom dunyo')
    const m1 = toggle(m0, 6, 11, 'bold')
    expect(modelToHtml(m1)).toBe('Salom <b>dunyo</b>')
    expect(covered(m1, 6, 11, 'bold')).toBe(true)
    expect(modelToHtml(toggle(m1, 6, 11, 'bold'))).toBe('Salom dunyo')
    expect(modelToHtml(toggle(m1, 8, 9, 'bold'))).toBe('Salom <b>du</b>n<b>yo</b>')
  })

  it('toggle: bo\'sh tanlov hech narsa qilmaydi; chegaradan chiqish kesiladi', () => {
    const m = parseModel('abc')
    expect(toggle(m, 2, 2, 'bold')).toBe(m)
    expect(modelToHtml(toggle(m, -5, 99, 'italic'))).toBe('<i>abc</i>')
  })

  it('kod ichida boshqa formatlar olib tashlanadi (Telegram qoidasi)', () => {
    const m = toggle(toggle(parseModel('abc'), 0, 3, 'bold'), 0, 3, 'code')
    expect(modelToHtml(m)).toBe('<code>abc</code>')
  })

  it('qisman ustma-ust: kesishgan formatlar to\'g\'ri ichma-ich yoziladi', () => {
    let m = parseModel('abcdef')
    m = toggle(m, 0, 4, 'bold')
    m = toggle(m, 2, 6, 'italic')
    const html = modelToHtml(m)
    expect(html).toBe('<b>ab<i>cd</i></b><i>ef</i>')
    expect(parseModel(html).text).toBe('abcdef')
  })

  it('havola: tanlovga qo\'yiladi / tanlov bo\'lmasa URL matn sifatida; xavfli manzil rad', () => {
    const m = parseModel('sayt')
    expect(modelToHtml(insertLink(m, 0, 4, 'https://example.org'))).toBe('<a href="https://example.org">sayt</a>')
    expect(modelToHtml(insertLink(parseModel('a '), 2, 2, 'https://x.uz'))).toBe('a <a href="https://x.uz">https://x.uz</a>')
    expect(insertLink(m, 0, 4, 'javascript:alert(1)')).toBe(m)
    expect(modelToHtml(unlink(insertLink(m, 0, 4, 'https://example.org'), 0, 4))).toBe('sayt')
  })

  it('wordAt: kursor so\'z ichida bo\'lsa shu so\'z', () => {
    expect(wordAt('salom dunyo', 8)).toEqual([6, 11])
    expect(wordAt('a  b', 2)).toBeNull()
  })
})

describe('normalizeLink: @username, t.me, domen', () => {
  it('to\'liq https havolaga keltiradi', () => {
    expect(normalizeLink('@mirzachollgagarin')).toBe('https://t.me/mirzachollgagarin')
    expect(normalizeLink('t.me/kanal')).toBe('https://t.me/kanal')
    expect(normalizeLink('sayt.uz/yo\'l?x=1')).toBe('https://sayt.uz/yo\'l?x=1')
    expect(normalizeLink('www.example.org')).toBe('https://www.example.org')
    expect(normalizeLink('https://a.uz')).toBe('https://a.uz')
    expect(normalizeLink('tg://resolve?domain=x')).toBe('tg://resolve?domain=x')
  })
  it('yaroqsiz yoki xavfli kirish o\'zgarmaydi va rad etiladi', () => {
    for (const bad of ['javascript:alert(1)', 'a b.uz', '@ab', 'mailto:a@b.uz', 'localhost', '']) expect(isValidLinkInput(bad)).toBe(false)
    expect(isValidLinkInput('@mirzachollgagarin')).toBe(true)
    expect(isValidLinkInput('sayt.uz')).toBe(true)
  })
})
