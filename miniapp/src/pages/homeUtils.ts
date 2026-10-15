// Bosh sahifa yordamchilari: kun vaqtiga qarab salomlashuv, keyingi postgacha qolgan vaqt, kunlik maslahat.

export type GreetKey = 'home.greet.morning' | 'home.greet.day' | 'home.greet.evening' | 'home.greet.night'

export function greetingKey(hour: number): GreetKey {
  if (hour >= 5 && hour < 12) return 'home.greet.morning'
  if (hour >= 12 && hour < 18) return 'home.greet.day'
  if (hour >= 18 && hour < 23) return 'home.greet.evening'
  return 'home.greet.night'
}

export type Countdown =
  | { key: 'cd.now' }
  | { key: 'cd.min' | 'cd.hour' | 'cd.day'; n: number }
  | { key: 'cd.hourMin'; h: number; m: number }

/** `target` gacha qolgan vaqt: <1 daqiqa -> "hozir", <1 soat -> daqiqa, <24 soat -> soat(+daqiqa), aks holda kun. O'tgan vaqt -> "hozir". */
export function countdownTo(target: Date, now: Date): Countdown {
  const mins = Math.floor((target.getTime() - now.getTime()) / 60000)
  if (mins < 1) return { key: 'cd.now' }
  if (mins < 60) return { key: 'cd.min', n: mins }
  if (mins < 24 * 60) {
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return m === 0 ? { key: 'cd.hour', n: h } : { key: 'cd.hourMin', h, m }
  }
  return { key: 'cd.day', n: Math.floor(mins / (24 * 60)) }
}

export const TIP_COUNT = 4

/** Kunlik maslahat indeksi (yil kuniga bog'liq: har kuni boshqa, kun ichida barqaror). */
export function tipIndex(date: Date): number {
  const start = Date.UTC(date.getFullYear(), 0, 0)
  const day = Math.floor((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - start) / 86400000)
  return ((day % TIP_COUNT) + TIP_COUNT) % TIP_COUNT
}
