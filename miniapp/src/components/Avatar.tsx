import { useEffect, useState } from 'react'

/** Ism/kanal nomining birinchi harfi (emoji va murakkab belgilar ham butun belgi sifatida olinadi). */
export function initialOf(text: string): string {
  const first = Array.from(text.trim())[0]
  return first ? first.toLocaleUpperCase() : '?'
}

/** Telegram profil rasmi (bo'lsa) yoki bosh harf; rasm yuklanmasa harfga qaytadi. */
export function Avatar({ text, small = false, large = false, medium = false, photo = null }: { text: string; small?: boolean; large?: boolean; medium?: boolean; photo?: string | null }) {
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [photo])
  const cls = `avatar${small ? ' avatar-sm' : ''}${large ? ' avatar-lg' : ''}${medium ? ' avatar-md' : ''}`
  if (photo && !broken) {
    return <img className={`${cls} avatar-photo`} src={photo} alt="" width={large ? 88 : medium ? 56 : 48} height={large ? 88 : medium ? 56 : 48}
      referrerPolicy="no-referrer" decoding="async" onError={() => setBroken(true)} />
  }
  return <span className={cls} aria-hidden="true">{initialOf(text)}</span>
}
