// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Avatar } from './components/Avatar'
import { TierBadge, TierMark } from './components/ui'
import { isPremium, tierOf } from './tier'

afterEach(cleanup)

describe('tarif ko\'rinishi (PRO ⭐ / ULTRA 👑)', () => {
  it('tierOf: pullik tarif davridan qat\'i nazar (1 soat ham) premium; bepul — yo\'q', () => {
    expect(tierOf({ type: 'free', is_pro: false })).toBe('free')
    expect(tierOf({ type: 'pro', is_pro: true })).toBe('pro')           // 1 soatlik/1 kunlik PRO ham
    expect(tierOf({ type: 'ultra', is_pro: true })).toBe('ultra')
    expect(tierOf({ type: 'enterprise', is_pro: true })).toBe('enterprise')
    expect(tierOf({ type: 'pro', is_pro: false })).toBe('free')         // muddati tugagan
    expect(tierOf(null)).toBe('free')
    expect(isPremium('pro') && !isPremium('free')).toBe(true)
  })

  it('TierBadge/TierMark: bepulda oddiy belgi, pullikda rangli belgi va ism yonida belgi', () => {
    const { container, rerender } = render(<><TierBadge tier="free">Bepul</TierBadge><TierMark tier="free" /></>)
    expect(container.querySelector('.tier-badge')).toBeNull()
    expect(container.querySelector('.tier-mark')).toBeNull()
    rerender(<><TierBadge tier="pro">PRO</TierBadge><TierMark tier="pro" /></>)
    expect(container.querySelector('.tier-badge.tier-pro')).not.toBeNull()
    expect(container.querySelector('.tier-mark.tier-pro')).not.toBeNull()
    expect(screen.getByText('PRO')).toBeTruthy()
    rerender(<TierBadge tier="ultra">ULTRA</TierBadge>)
    expect(container.querySelector('.tier-badge.tier-ultra')).not.toBeNull()
  })

  it('Avatar: pullik tarifda halqa va burchak belgisi, bepulda yo\'q', () => {
    const { container, rerender } = render(<Avatar text="Ali" medium />)
    expect(container.querySelector('.avatar-ring')).toBeNull()
    rerender(<Avatar text="Ali" medium tier="ultra" />)
    expect(container.querySelector('.avatar-ring.tier-ultra .avatar-tier')).not.toBeNull()
    expect(container.querySelector('.avatar')?.textContent).toBe('A')
  })
})
