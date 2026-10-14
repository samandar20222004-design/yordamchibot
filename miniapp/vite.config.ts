import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Build `miniapp/dist` ga chiqadi; backend uni `/app/*` ostida beradi
// (telegram_bot/miniapp_api/static.py), shuning uchun base = '/app/'.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: { outDir: 'dist', sourcemap: false, target: 'es2020' },
  // Faqat `npm run dev`: API so'rovlari lokal botga (PORT, sukut 10000) yo'naltiriladi.
  server: { proxy: { '/api': 'http://localhost:10000' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
})
