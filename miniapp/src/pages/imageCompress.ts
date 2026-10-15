// Rasmni yuklashdan OLDIN telefonda yengillashtirish (Mini App va server yuklanmaydi): eng uzun tomon 1600 px, JPEG ~82%.
// GIF/video tegilmaydi; xato yoki kichik/yengil rasm bo'lsa asl fayl qaytadi (hech qachon yuklashni to'xtatmaydi).

export const MAX_SIDE = 1600
export const LIGHT_BYTES = 600 * 1024
const COMPRESSIBLE = ['image/jpeg', 'image/png', 'image/webp']

export async function compressImage(file: File, maxSide: number = MAX_SIDE, quality = 0.82): Promise<File> {
  if (!COMPRESSIBLE.includes(file.type) || typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file
  try {
    const bmp = await createImageBitmap(file)
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height))
    if (scale === 1 && file.size <= LIGHT_BYTES) { bmp.close?.(); return file }
    const w = Math.max(1, Math.round(bmp.width * scale))
    const h = Math.max(1, Math.round(bmp.height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) { bmp.close?.(); return file }
    ctx.fillStyle = '#fff' // shaffof PNG JPEG'da qora bo'lib qolmasin
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(bmp, 0, 0, w, h)
    bmp.close?.()
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
    if (!blob || blob.size >= file.size) return file
    return new File([blob], `${file.name.replace(/\.[^.]+$/, '') || 'photo'}.jpg`, { type: 'image/jpeg' })
  } catch {
    return file
  }
}
