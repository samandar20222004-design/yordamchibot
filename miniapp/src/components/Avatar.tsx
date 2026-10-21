import { useEffect, useState } from 'react'
import type { Tier } from '../tier'
import { Icon } from './Icon'

/** Ism/kanal nomining birinchi harfi (emoji va murakkab belgilar ham butun belgi sifatida olinadi). */
export function initialOf(text: string): string {
  const first = Array.from(text.trim())[0]
  return first ? first.toLocaleUpperCase() : '?'
}

/** Telegram profil rasmi (bo'lsa) yoki bosh harf; rasm yuklanmasa harfga qaytadi. */
export function Avatar({ text, small = false, large = false, medium = false, photo = null, tier = 'free' }: { text: string; small?: boolean; large?: boolean; medium?: boolean; photo?: string | null; tier?: Tier }) {
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [photo])
  const cls = `avatar${small ? ' avatar-sm' : ''}${large ? ' avatar-lg' : ''}${medium ? ' avatar-md' : ''}`
  const face = photo && !broken
    ? <img className={`${cls} avatar-photo`} src={photo} alt="" width={large ? 88 : medium ? 56 : 48} height={large ? 88 : medium ? 56 : 48}
        referrerPolicy="no-referrer" decoding="async" onError={() => setBroken(true)} />
    : <span className={cls} aria-hidden="true">{initialOf(text)}</span>
  if (tier === 'free') return face
  // Pullik tarif: rangli halqa + burchakda ⭐/👑 belgisi
  return (
    <span className={`avatar-ring tier-${tier}`}>
      {face}
      <span className="avatar-tier" aria-hidden="true"><Icon name={tier === 'pro' ? 'star' : tier === 'ultra' ? 'crown' : 'diamond'} size={12} /></span>
    </span>
  )
}
