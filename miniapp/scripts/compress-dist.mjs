// Build'dan keyin statik fayllarni OLDINDAN siqadi (brotli + gzip): server (aiohttp FileResponse) `Accept-Encoding` ga qarab
// `.br` / `.gz` ni o'zi beradi. JS ~350 KB -> ~90 KB: Mini App telefon tarmog'ida ancha tez ochiladi.
import { brotliCompressSync, constants, gzipSync } from 'node:zlib'
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
const COMPRESSIBLE = /\.(js|css|html|svg|json|txt)$/i
const MIN_BYTES = 1024
let files = 0
let before = 0
let after = 0

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) { walk(full); continue }
    if (!COMPRESSIBLE.test(name)) continue
    const data = readFileSync(full)
    if (data.length < MIN_BYTES) continue
    const br = brotliCompressSync(data, { params: { [constants.BROTLI_PARAM_QUALITY]: 11, [constants.BROTLI_PARAM_SIZE_HINT]: data.length } })
    const gz = gzipSync(data, { level: 9 })
    if (br.length < data.length) writeFileSync(full + '.br', br)
    if (gz.length < data.length) writeFileSync(full + '.gz', gz)
    files += 1
    before += data.length
    after += Math.min(br.length, gz.length, data.length)
  }
}

walk(dist)
console.log(`compress-dist OK: ${files} fayl, ${(before / 1024).toFixed(0)} KB -> ${(after / 1024).toFixed(0)} KB`)
