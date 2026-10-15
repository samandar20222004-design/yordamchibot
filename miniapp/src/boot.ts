// index.html dagi yuklash ekrani (#boot): ilova tayyor bo'lganda bir marta silliq yashiriladi (ikkinchi animatsiya yo'q).

export function hideBoot(): void {
  const el = typeof document === 'undefined' ? null : document.getElementById('boot')
  if (!el || el.classList.contains('boot-hide')) return
  el.classList.add('boot-hide')
  setTimeout(() => el.remove(), 350)
}
