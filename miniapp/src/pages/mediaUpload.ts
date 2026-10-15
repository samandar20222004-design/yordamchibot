// Albomga fayl tanlash: tur/hajm/son tekshiruvi (server baribir baytlardan tekshiradi — bu faqat tez va aniq xabar uchun).
import type { MediaItem } from '../api/types'
import { config } from '../config'

export const MEDIA_ACCEPT = 'image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime'
const IMAGES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const VIDEOS = ['video/mp4', 'video/quicktime']

export interface PreparedFiles {
  accepted: File[]
  /** Albom to'lgani uchun qo'shilmagan fayllar soni. */
  skippedFull: number
  errors: Array<'type' | 'size' | 'mixed'>
}

/**
 * `files` dan albomga sig'adiganlarini ajratadi: noma'lum tur / juda katta hajm / GIF (albomga kirmaydi) tashlanadi,
 * sig'imdan oshganlari `skippedFull` ga yoziladi. Mavjud elementlar ichida GIF bo'lsa yangi fayl qabul qilinmaydi.
 */
export function prepareFiles(files: File[], existing: readonly MediaItem[], max: number = config.maxAlbumItems): PreparedFiles {
  const errors: PreparedFiles['errors'] = []
  const note = (e: PreparedFiles['errors'][number]) => { if (!errors.includes(e)) errors.push(e) }
  const hasGif = existing.some((i) => i.type === 'animation')
  const accepted: File[] = []
  let skippedFull = 0
  for (const f of files) {
    const video = VIDEOS.includes(f.type)
    if (!video && !IMAGES.includes(f.type)) { note('type'); continue }
    if (f.size > (video ? config.maxUploadVideoBytes : config.maxUploadPhotoBytes) && !(f.type === 'image/jpeg' || f.type === 'image/png' || f.type === 'image/webp')) { note('size'); continue }
    if (video && f.size > config.maxUploadVideoBytes) { note('size'); continue }
    if (f.type === 'image/gif' && (existing.length > 0 || files.length > 1 || accepted.length > 0)) { note('mixed'); continue }
    if (hasGif) { note('mixed'); continue }
    if (existing.length + accepted.length >= max) { skippedFull += 1; continue }
    accepted.push(f)
  }
  return { accepted, skippedFull, errors }
}
