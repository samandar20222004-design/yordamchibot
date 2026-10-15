import { useI18n, type MessageKey } from '../i18n'
import { Icon, type IconName } from './Icon'
import { TelegramText } from './TelegramText'

const MEDIA_ICON: Record<string, IconName> = {
  photo: 'image', video: 'video', animation: 'video', album: 'image',
  document: 'file', audio: 'file', voice: 'file', sticker: 'image',
}

export interface PreviewMedia {
  type: string
  count: number | null
  /** Rasm uchun `blob:` manzil (bo'lmasa — turi bilan belgi). */
  url: string | null
  loading: boolean
  /** `url` video/GIF-animatsiya (MP4) bo'lsa true. */
  video?: boolean
}

/** Telegram xabari ko'rinishidagi oldindan ko'rish (faqat o'qish uchun; hech narsa yuborilmaydi). */
export function PostPreview({ channelTitle, html, media, buttonText }: {
  channelTitle: string; html: string; media: PreviewMedia | null; buttonText: string | null
}) {
  const { t } = useI18n()
  const mediaLabel = media
    ? t(`post.media.${media.type}` as MessageKey, { n: media.count ?? 0 })
    : ''
  return (
    <section className="card preview" aria-labelledby="preview-title">
      <div className="card-row">
        <h2 id="preview-title">{t('post.preview.title')}</h2>
        <span className="badge badge-truncate" title={channelTitle}>{channelTitle}</span>
      </div>
      <div className="bubble">
        {media && (
          media.url ? (
            media.video
              ? <video className="bubble-media" src={media.url} aria-label={mediaLabel} muted loop playsInline controls preload="metadata" />
              : <img className="bubble-media" src={media.url} alt={mediaLabel} />
          ) : (
            <div className={`bubble-media bubble-media-ph${media.loading ? ' skeleton' : ''}`} role="img" aria-label={mediaLabel}>
              <Icon name={MEDIA_ICON[media.type] ?? 'file'} size={34} />
              <span>{mediaLabel}</span>
            </div>
          )
        )}
        {html.trim()
          ? <TelegramText html={html} />
          : !media && <p className="muted">{t('post.preview.empty')}</p>}
        {buttonText && <div className="bubble-btn" aria-hidden="true">{buttonText}</div>}
      </div>
    </section>
  )
}
