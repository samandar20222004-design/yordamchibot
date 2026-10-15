import { useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import { usePostMedia } from '../hooks/usePostMedia'
import { Icon } from './Icon'

/** Ro'yxatdagi post rasmi/videosi: faqat ekranga kirganda (IntersectionObserver) va ko'pi bilan 3 ta parallel yuklanadi. */
export function PostThumb({ postId, hasMedia, type, label, version = '', size = 'sm' }: {
  postId: number; hasMedia: boolean; type: string; label: string; version?: string; size?: 'sm' | 'lg'
}) {
  const { client } = useAppData()
  const ref = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || !hasMedia) return
    if (typeof IntersectionObserver === 'undefined') { setVisible(true); return }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setVisible(true); io.disconnect() }
    }, { rootMargin: '120px' })
    io.observe(el)
    return () => io.disconnect()
  }, [hasMedia])
  const media = usePostMedia(client, postId, hasMedia && visible, version)
  if (!hasMedia) return null
  const icon = type === 'video' || type === 'animation' ? 'video' : type === 'document' || type === 'audio' ? 'file' : 'image'
  return (
    <div ref={ref} className={`thumb thumb-${size}${media.loading ? ' skeleton' : ''}`} role="img" aria-label={label}>
      {media.url
        ? (media.video
          ? <video src={media.url} muted playsInline preload="metadata" />
          : <img src={media.url} alt="" loading="lazy" decoding="async" />)
        : <Icon name={icon} size={size === 'lg' ? 30 : 22} />}
    </div>
  )
}
