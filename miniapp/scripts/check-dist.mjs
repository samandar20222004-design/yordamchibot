// Build tekshiruvi: dist/index.html dagi barcha `/app/...` havolalari dist ichida mavjud bo'lishi shart.
// Backend statik serving `/app/` prefiksi ostida (telegram_bot/miniapp_api/static.py) — vite `base` shunga mos.
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, normalize, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
const indexPath = join(dist, 'index.html')
const problems = []
if (!existsSync(indexPath)) {
  problems.push('dist/index.html yo\'q')
} else {
  const html = readFileSync(indexPath, 'utf8')
  const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1])
  const local = refs.filter((r) => !/^(https?:)?\/\//.test(r) && !r.startsWith('data:'))
  if (local.length === 0) problems.push('index.html da lokal resurs topilmadi')
  for (const ref of local) {
    if (!ref.startsWith('/app/')) { problems.push(`prefiks '/app/' emas: ${ref}`); continue }
    const rel = normalize(ref.slice('/app/'.length).split('?')[0])
    const file = join(dist, rel)
    if (rel.startsWith('..') || !file.startsWith(dist + sep) || !existsSync(file)) problems.push(`yo'q: ${ref}`)
  }
  if (!/telegram\.org\/js\/telegram-web-app\.js/.test(html)) problems.push('Telegram WebApp SDK <script> yo\'q')
}
if (problems.length) {
  console.error('check-dist XATO:\n - ' + problems.join('\n - '))
  process.exit(1)
}
console.log('check-dist OK')
