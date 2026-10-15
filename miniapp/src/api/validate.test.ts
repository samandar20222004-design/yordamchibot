import { describe, expect, it } from 'vitest'
import { ME, PAGE } from '../test/helpers'
import { parseChannels, parseErrorBody, parseMe, parseScheduled } from './validate'

describe('validatorlar', () => {
  it('to\'g\'ri /me', () => expect(parseMe(ME).plan.limits.max_channels).toBe(3))
  it('noma\'lum til uz ga tushadi', () => {
    expect(parseMe({ ...ME, user: { ...ME.user, language: 'de' } }).user.language).toBe('uz')
  })
  it('/me: kerakli maydon yo\'q -> xato', () => {
    expect(() => parseMe({ ...ME, usage: { channels: 1 } })).toThrow()
    expect(() => parseMe(null)).toThrow()
    expect(() => parseMe([])).toThrow()
  })
  it('/me: raqam o\'rniga satr -> xato', () => {
    expect(() => parseMe({ ...ME, usage: { ...ME.usage, channels: '2' } })).toThrow()
  })
  it('kanallar', () => {
    expect(parseChannels({ items: [{ id: '-1', title: null }], total: 1 }).items[0].id).toBe('-1')
    expect(() => parseChannels({ items: [{ id: 5, title: 'x' }], total: 1 })).toThrow()
    const rich = parseChannels({ items: [{ id: '-1', title: 'x', pending_posts: 2, members: null, members_as_of: null }], total: 1 }).items[0]!
    expect(rich).toMatchObject({ pending_posts: 2, members: null })
    expect(() => parseChannels({ items: [{ id: '-1', title: 'x', pending_posts: '2' }], total: 1 })).toThrow()
    expect(() => parseChannels({ items: [{ id: '-1', title: 'x', members: 1.5 }], total: 1 })).toThrow()
  })
  it('rejalashtirilgan postlar', () => {
    expect(parseScheduled(PAGE).items).toHaveLength(2)
    expect(() => parseScheduled({ ...PAGE, has_more: 'no' })).toThrow()
    expect(() => parseScheduled({ ...PAGE, items: [{ id: 'x' }] })).toThrow()
  })
  it('xato tanasi', () => {
    expect(parseErrorBody({ error: { code: 'x', message: 'm', request_id: 'r', retry_after: 3 } })?.retryAfter).toBe(3)
    expect(parseErrorBody({ nope: 1 })).toBeNull()
    expect(parseErrorBody(null)).toBeNull()
  })
})
