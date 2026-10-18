import { useEffect, useState } from 'react'
import { useAppData } from '../AppData'
import { ApiClientError } from '../api/client'
import type { MarketListing, MarketSummary } from '../api/types'
import { Avatar } from '../components/Avatar'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { SubPage } from '../components/SubPage'
import { Button, ErrorState, FormError, LoadingBlock } from '../components/ui'
import { toClientError } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { haptic, openChannel } from '../telegram'
import { formatCount, formatMoney } from './marketUtils'

/** Narx: «60 000 so'm» yoki «kelishiladi». */
export function usePriceText(): (price: number | null, currency?: 'UZS' | 'USD') => string {
  const { t } = useI18n()
  return (price, currency = 'UZS') => (price === null ? t('mk.priceNeg') : currency === 'USD' ? `$${formatMoney(price)}` : `${formatMoney(price)} ${t('mk.currency')}`)
}

/** E'lon ko'rsatkichlari: obunachi (+o'sish), ko'rish, ER, postlar — noma'lum bo'lsa halol «ma'lumot yetarli emas». */
export function ListingMetrics({ listing }: { listing: MarketListing }) {
  const { t } = useI18n()
  const growth = listing.growth_30d
  const items: Array<{ label: MessageKey; value: string; sub?: string; tone: string }> = [
    { label: 'mk.fMembers', value: formatCount(listing.members), tone: 'blue',
      sub: growth === null ? undefined : `${growth >= 0 ? '+' : ''}${formatCount(growth)} · ${t('mk.fGrowth')}` },
    { label: 'mk.fViews', value: listing.avg_views === null ? '—' : formatCount(listing.avg_views), tone: 'violet',
      sub: listing.avg_views === null ? t('mk.viewsUnknown') : undefined },
    { label: 'mk.fEr', value: listing.er_percent === null ? '—' : `${listing.er_percent}%`, tone: 'green' },
    { label: 'mk.fPosts', value: listing.posts_30d === null ? '—' : String(listing.posts_30d), tone: 'gold' },
  ]
  return (
    <div className="mk-metrics">
      {items.map((m) => (
        <div key={m.label} className={`mk-metric tone-stat-${m.tone}`}>
          <span className="stat-label">{t(m.label)}</span>
          <strong className="mk-metric-value">{m.value}</strong>
          {m.sub && <span className="muted small">{m.sub}</span>}
        </div>
      ))}
    </div>
  )
}

export function ListingBadges({ listing }: { listing: MarketListing }) {
  const { t } = useI18n()
  if (listing.badges.length === 0) return null
  return (
    <div className="mk-badges">
      {listing.badges.map((b) => <span key={b} className="mk-pill mk-pill-accent">{t(`mk.badge.${b}` as MessageKey)}</span>)}
    </div>
  )
}

export function ListingFacts({ listing }: { listing: MarketListing }) {
  const { t, formatDateTime } = useI18n()
  const price = usePriceText()
  return (
    <>
      <ListingMetrics listing={listing} />
      <div className="mk-price"><span className="muted">{t('mk.fPrice')}</span><strong>{price(listing.price, listing.currency)}</strong></div>
      <ListingBadges listing={listing} />
      {listing.description && <p className="mk-desc">{listing.description}</p>}
      <p className="muted small mk-foot">
        ✅ {t('mk.verified')}
        {listing.stats_updated_at && <><br />{t('mk.updated', { when: formatDateTime(listing.stats_updated_at) })}</>}
        <br />{t('mk.statsNote')}
      </p>
    </>
  )
}

function InquiryDialog({ listing, summary, onClose, onSent }: {
  listing: MarketListing; summary: MarketSummary | null; onClose: () => void; onSent: (delivered: boolean) => void
}) {
  const { client } = useAppData()
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiClientError | null>(null)
  const min = summary?.message_min ?? 10
  const max = summary?.message_max ?? 1000
  const ready = text.trim().length >= min
  const submit = async () => {
    if (!ready || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await client.marketInquire(listing.id, text.trim())
      haptic('success')
      onSent(res.delivered)
    } catch (e) {
      haptic('error')
      setError(toClientError(e))
      setBusy(false)
    }
  }
  return (
    <Dialog title={t('mk.inqTitle', { title: listing.title })} onClose={onClose} busy={busy}>
      <p className="muted">{t('mk.inqHint')}</p>
      <textarea className="input" rows={5} value={text} maxLength={max} placeholder={t('mk.inqPlaceholder')}
        onChange={(e) => setText(e.target.value)} aria-label={t('mk.inqTitle', { title: listing.title })} />
      <p className="muted small mk-count">{t('mk.charCount', { n: text.trim().length, max })}</p>
      <p className="mk-tip">{t('mk.safetyTip')}</p>
      {error && <FormError error={error} />}
      <div className="dialog-actions">
        <Button onClick={onClose} disabled={busy}>{t('mk.cancel')}</Button>
        <Button variant="primary" icon="send" busy={busy} disabled={!ready} onClick={submit}>{t('mk.send')}</Button>
      </div>
    </Dialog>
  )
}

/** Reklama beruvchi uchun kanal kartasi: ko'rsatkichlar, so'rov yozish, shikoyat. */
export function ListingView({ id, summary, onBack, onOpenChats }: {
  id: number; summary: MarketSummary | null; onBack: () => void; onOpenChats: () => void
}) {
  const { client, notify } = useAppData()
  const { t } = useI18n()
  const [card, setCard] = useState<{ listing: MarketListing; is_owner: boolean } | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [dialog, setDialog] = useState<'inquiry' | 'report' | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    setCard(null)
    setError(null)
    client.marketListing(id, ctl.signal).then(setCard, (e) => { if (!ctl.signal.aborted) setError(toClientError(e)) })
    return () => ctl.abort()
  }, [client, id])

  const report = async () => {
    setBusy(true)
    try {
      const res = await client.marketReport(id)
      notify(t(res.again ? 'mk.reportedAgain' : 'mk.reported'))
      setDialog(null)
      if (res.blocked) onBack()
    } catch (e) {
      notify(t(`err.${toClientError(e).code}` as MessageKey), 'error')
    } finally {
      setBusy(false)
    }
  }

  const listing = card?.listing
  return (
    <SubPage title={listing?.title ?? t('mk.title')} onBack={onBack}>
      {!card && !error && <LoadingBlock rows={4} />}
      {error && <ErrorState error={error} onRetry={() => { setError(null); client.marketListing(id).then(setCard, (e) => setError(toClientError(e))) }} />}
      {listing && (
        <>
          <section className="card mk-hero-card">
            <div className="mk-head">
              <Avatar text={listing.title} large />
              <div className="mk-head-main">
                <h2>{listing.title}</h2>
                <span className="muted">@{listing.username} · {t(`mk.cat.${listing.category}` as MessageKey)}</span>
              </div>
            </div>
            <ListingFacts listing={listing} />
          </section>
          <div className="mk-actions">
            {!card.is_owner && (
              <Button variant="primary" block icon="send" onClick={() => { haptic('tap'); setDialog('inquiry') }}>{t('mk.contact')}</Button>
            )}
            <Button block icon="megaphone" onClick={() => openChannel(listing.username)}>{t('mk.openChannel')}</Button>
            {!card.is_owner && <Button variant="ghost" block onClick={() => setDialog('report')}>{t('mk.report')}</Button>}
          </div>
          {dialog === 'inquiry' && (
            <InquiryDialog listing={listing} summary={summary} onClose={() => setDialog(null)}
              onSent={(delivered) => { setDialog(null); notify(t(delivered ? 'mk.inqSent' : 'mk.inqNotDelivered')); onOpenChats() }} />
          )}
          {dialog === 'report' && (
            <ConfirmDialog title={t('mk.report')} body={t('mk.report')} confirmLabel={t('mk.report')} danger busy={busy}
              onConfirm={report} onClose={() => setDialog(null)} />
          )}
        </>
      )}
    </SubPage>
  )
}
