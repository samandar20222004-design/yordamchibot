import { useRef } from 'react'
import { useI18n } from '../i18n'
import { useMediaBlob } from '../hooks/useMediaBlob'
import type { MediaItem } from '../api/types'
import { Icon } from './Icon'

export interface LocalUpload { id: string; url: string; video: boolean }

function Tile({ item, index, version, load, onRemove, busy, removeLabel }: {
  item: MediaItem; index: number; version: string; load: (index: number, signal: AbortSignal) => Promise<Blob | null>
  onRemove: (index: number) => void; busy: boolean; removeLabel: string
}) {
  const media = useMediaBlob((signal) => load(index, signal), item.previewable, `${version}:${index}`)
  const icon = item.type === 'video' || item.type === 'animation' ? 'video' : item.type === 'document' || item.type === 'audio' ? 'file' : 'image'
  return (
    <li className={`mg-tile${media.loading ? ' skeleton' : ''}`}>
      {media.url
        ? (media.video
          ? <video src={media.url} muted playsInline preload="metadata" />
          : <img src={media.url} alt="" decoding="async" />)
        : <span className="mg-ph"><Icon name={icon} size={26} /></span>}
      <span className="mg-num" aria-hidden="true">{index + 1}</span>
      <button type="button" className="mg-x" disabled={busy} aria-label={removeLabel} title={removeLabel} onClick={() => onRemove(index)}>
        <Icon name="close" size={14} />
      </button>
    </li>
  )
}

/**
 * Albom tahrirlagichi: 10 tagacha rasm/video katakchalari, har birida o'chirish (✕), oxirida «+» (yana qo'shish).
 * Yuklanayotgan fayllar darhol mahalliy ko'rinishda (spinner bilan) chiqadi.
 */
export function MediaGrid({ items, version, load, busy, uploading, locals, max, onAdd, onRemove, accept, progress }: {
  items: MediaItem[]; version: string; load: (index: number, signal: AbortSignal) => Promise<Blob | null>
  busy: boolean; uploading: boolean; locals: LocalUpload[]; max: number
  onAdd: (files: File[]) => void; onRemove: (index: number) => void; accept: string; progress: string | null
}) {
  const { t } = useI18n()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const total = items.length
  const full = total + locals.length >= max
  const pick = () => fileRef.current?.click()
  return (
    <div className="media-grid-box">
      <input ref={fileRef} type="file" multiple className="sr-only" tabIndex={-1} aria-label={t('media.title')} accept={accept}
        onChange={(e) => { const files = Array.from(e.target.files ?? []); if (fileRef.current) fileRef.current.value = ''; if (files.length) onAdd(files) }} />
      {total === 0 && locals.length === 0 ? (
        <button type="button" className="media-tile" disabled={busy || uploading} onClick={pick} aria-label={t('media.add')}>
          <span className="media-tile-label">
            <Icon name="image" size={28} />
            <strong>{uploading ? (progress ?? t('media.uploading')) : t('media.pickMany')}</strong>
            <span className="muted small">{t('media.lite')}</span>
          </span>
        </button>
      ) : (
        <>
          <div className="mg-head">
            <strong>{t('media.title')}</strong>
            <span className="badge" aria-live="polite">{t('media.count', { n: total + locals.length, max })}</span>
          </div>
          <ul className="mg-grid" aria-label={t('media.title')}>
            {items.map((item, i) => (
              <Tile key={`${version}:${i}`} item={item} index={i} version={version} load={load} onRemove={onRemove}
                busy={busy || uploading} removeLabel={t('media.remove', { n: i + 1 })} />
            ))}
            {locals.map((l) => (
              <li key={l.id} className="mg-tile mg-uploading" aria-busy="true">
                {l.video ? <video src={l.url} muted playsInline preload="metadata" /> : <img src={l.url} alt="" />}
                <span className="mg-spin" aria-hidden="true" />
              </li>
            ))}
            {!full && (
              <li>
                <button type="button" className="mg-add" disabled={busy || uploading} onClick={pick} aria-label={t('media.add')}>
                  <Icon name="plus" size={22} />
                  <span>{t('media.addMore')}</span>
                </button>
              </li>
            )}
          </ul>
          {uploading && progress && <p className="muted small" role="status">{progress}</p>}
        </>
      )}
      <p className="muted small">{t('media.hint')}</p>
    </div>
  )
}
