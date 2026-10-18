/** Reklama birjasi: son/narx ko'rinishi (sof funksiyalar, testlanadi). */

/** 950 -> «950», 12 400 -> «12.4k», 1 250 000 -> «1.25M»; noma'lum -> «—». */
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  const v = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (v >= 1_000_000) return `${sign}${trim((v / 1_000_000).toFixed(2))}M`
  if (v >= 10_000) return `${sign}${trim((v / 1_000).toFixed(1))}k`
  return `${sign}${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')}`
}

function trim(s: string): string {
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s
}

/** 60000 -> «60 000». */
export function formatMoney(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

/** Kiritilgan narx matni -> butun son; bo'sh -> `null` (kelishiladi); yaroqsiz -> `undefined`. */
export function parsePriceInput(text: string, min: number, max: number): number | null | undefined {
  const raw = text.trim().toLowerCase().replace(/[\s_]/g, '')
  if (raw === '') return null
  const m = /^(\d+(?:[.,]\d+)?)(k|ming|тыс|m|mln|млн)?$/.exec(raw)
  if (!m) return undefined
  const mult = !m[2] ? 1 : m[2] === 'k' || m[2] === 'ming' || m[2] === 'тыс' ? 1_000 : 1_000_000
  const value = Math.round(Number(m[1].replace(',', '.')) * mult)
  return value >= min && value <= max ? value : undefined
}
