// Bot yuklash animatsiyasi (telegram_bot/assets/loading.mp4) — Mini App dagi BrandMark bilan bir xil SVG/CSS dan.
// Ishlatish: NODE_PATH=<playwright o'rnatilgan papka>/node_modules node scripts/make_loading_video.mjs  (ffmpeg kerak)
// Natija repoga commit qilinadi; qayta yaratish faqat belgi dizayni o'zgarganda kerak.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(process.env.PLAYWRIGHT_DIR ? join(process.env.PLAYWRIGHT_DIR, '/') : import.meta.url)
const { chromium } = require('playwright')

const SIZE = 512, FPS = 25, LOOP_MS = 2800
const frames = Math.round((LOOP_MS / 1000) * FPS)
const css = readFileSync(join(here, 'brand/mark.css'), 'utf8')
const svg = readFileSync(join(here, 'brand/mark.svg.html'), 'utf8')
const html = `<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;background:#0b1b4d}
.stage{position:relative;width:${SIZE}px;height:${SIZE}px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:radial-gradient(circle at 50% 45%,#16337f 0,#0b1b4d 70%)}
.mk{position:relative;width:300px;height:300px;margin-top:-20px}
.mk::before,.mk::after{content:'';position:absolute;inset:0;border-radius:50%;border:4px solid #5aaaff;opacity:0;animation:ring 2.8s ease-out infinite}
.mk::after{animation-delay:1.4s}
.mk .bm{border-radius:50%;box-shadow:0 18px 50px rgba(36,129,204,.45)}
.dots{position:absolute;bottom:58px;display:flex;gap:16px}
.dots i{width:16px;height:16px;border-radius:50%;background:#5aaaff;opacity:.3;animation:dot 1.4s ease-in-out infinite}
.dots i:nth-child(2){animation-delay:.23s}.dots i:nth-child(3){animation-delay:.46s}
@keyframes ring{0%{transform:scale(1);opacity:.6}100%{transform:scale(1.55);opacity:0}}
@keyframes dot{0%,80%,100%{opacity:.3;transform:scale(.8)}40%{opacity:1;transform:scale(1.2)}}
${css}
</style><div class="stage"><div class="mk">${svg}</div><div class="dots"><i></i><i></i><i></i></div></div>`

const tmp = mkdtempSync(join(tmpdir(), 'loading-'))
const out = resolve(here, '../telegram_bot/assets/loading.mp4')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined })
try {
  const page = await browser.newPage({ viewport: { width: SIZE, height: SIZE } })
  await page.setContent(html)
  for (let i = 0; i < frames; i++) {
    const t = (i * LOOP_MS) / frames
    await page.evaluate((t) => document.getAnimations().forEach((a) => { a.pause(); a.currentTime = t }), t)
    await page.screenshot({ path: join(tmp, `f${String(i).padStart(3, '0')}.png`) })
  }
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', join(tmp, 'f%03d.png'),
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '24', '-preset', 'veryslow', '-movflags', '+faststart', '-an', out])
  console.log(out)
} finally {
  await browser.close()
  rmSync(tmp, { recursive: true, force: true })
}
