import { useState } from 'react'
import { useAppData } from '../AppData'
import { ApiClientError } from '../api/client'
import { MARKET_CATEGORIES, type MarketCategory, type MarketListing, type MarketSummary } from '../api/types'
import { Avatar } from '../components/Avatar'
import { ConfirmDialog } from '../components/Dialog'
import { SubPage } from '../components/SubPage'
import { Button, ErrorState, FormError, LoadingBlock, openBotAvailable } from '../components/ui'
import { toClientError, type Resource } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { haptic, openBot } from '../telegram'
import type { MarketMine } from '../api/types'
import { ListingFacts } from './MarketListing'
import { parsePriceInput } from './marketUtils'

const STATUS_KEY: Record<string, MessageKey> = {
  active: 'mk.statusActive', paused: 'mk.statusPaused', blocked: 'mk.statusBlocked',
}

/** «Kanalim» bo'limi: o'z kanallari va ularning birjadagi holati. */
export function MineList({ mine, onOpen }: {
  mine: Resource<MarketMine>
  onOpen: (item: { channelId: string; title: string; listing: MarketListing | null }) => void
}) {
  const { t } = useI18n()
  const { botUsername } = useAppData()
  if (mine.loading) return <LoadingBlock rows={3} />
  if (!mine.data && mine.error) return <ErrorState error={mine.error} onRetry={mine.reload} botUsername={botUsername} />
  const items = mine.data?.items ?? []
  if (items.length === 0) {
    return (
      <section className="card">
        <p className="muted">{t('mk.mineEmpty')}</p>
        {openBotAvailable(botUsername) && (
          <Button variant="primary" icon="plus" onClick={() => openBot(botUsername, 'channels')}>{t('mk.mineAddChannel')}</Button>
        )}
      </section>
    )
  }
  return (
    <ul className="list">
      {items.map((c) => (
        <li key={c.channel_id}>
          <button type="button" className="item mk-row" onClick={() => onOpen({ channelId: c.channel_id, title: c.title, listing: c.listing })}>
            <Avatar text={c.title} small />
            <span className="mk-row-main">
              <strong className="mk-row-title">{c.title}</strong>
              <span className="muted small">
                {c.listing ? t(STATUS_KEY[c.listing.status ?? 'active']) : t('mk.statusNone')}
                {c.listing && ` · ${t('mk.views', { n: c.listing.view_count ?? 0 })} · ${t('mk.requests', { n: c.listing.inquiry_count ?? 0 })}`}
              </span>
            </span>
            <span className={`mk-dot mk-dot-${c.listing?.status ?? 'none'}`} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Kanalni birjaga chiqarish / tahrirlash / to'xtatish / olib tashlash. */
export function MineEditor({ channelId, title, listing: initial, summary, onBack, onChanged }: {
  channelId: string; title: string; listing: MarketListing | null; summary: MarketSummary | null
  onBack: () => void; onChanged: () => void
}) {
  const { client, notify, botUsername } = useAppData()
  const { t } = useI18n()
  const [listing, setListing] = useState<MarketListing | null>(initial)
  const [category, setCategory] = useState<MarketCategory>(initial?.category ?? 'other')
  const [price, setPrice] = useState(initial?.price == null ? '' : String(initial.price))
  const [desc, setDesc] = useState(initial?.description ?? '')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [priceBad, setPriceBad] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  // Valyuta: mavjud e'lonniki; yangi e'lon — egasining mamlakatiga qarab (O'zbekiston raqami -> so'm, boshqa -> dollar).
  const currency = initial?.currency ?? summary?.viewer.currency ?? 'UZS'
  const needPhone = !initial && summary !== null && summary.viewer.country === ''
  const min = currency === 'USD' ? (summary?.price_min_usd ?? 1) : (summary?.price_min ?? 1000)
  const max = currency === 'USD' ? (summary?.price_max_usd ?? 100000) : (summary?.price_max ?? 1_000_000_000)
  const descMax = summary?.description_max ?? 400
  const blocked = listing?.status === 'blocked'

  const run = async (name: string, work: () => Promise<void>) => {
    setBusy(name)
    setError(null)
    try {
      await work()
    } catch (e) {
      haptic('error')
      setError(toClientError(e))
    } finally {
      setBusy(null)
    }
  }

  const save = () => run('save', async () => {
    const parsed = parsePriceInput(price, min, max)
    if (parsed === undefined) { setPriceBad(true); return }
    setPriceBad(false)
    const desc2 = desc.trim() === '' ? null : desc.trim()
    if (listing) {
      setListing(await client.marketUpdate(listing.id, { category, price: parsed, description: desc2 }))
      notify(t('mk.saved'))
    } else {
      setListing(await client.marketPublish({ channel_id: channelId, category, price: parsed, description: desc2 }))
      notify(t('mk.published'))
    }
    haptic('success')
    onChanged()
  })

  const toggle = () => listing && run('toggle', async () => {
    setListing(await client.marketUpdate(listing.id, { status: listing.status === 'paused' ? 'active' : 'paused' }))
    onChanged()
  })

  const refresh = () => listing && run('refresh', async () => {
    setListing(await client.marketRefresh(listing.id))
    notify(t('mk.refreshed'))
    onChanged()
  })

  const remove = () => listing && run('remove', async () => {
    await client.marketDelete(listing.id)
    notify(t('mk.removed'))
    onChanged()
    onBack()
  })

  return (
    <SubPage title={title} onBack={onBack}>
      {listing && (
        <section className="card mk-hero-card">
          <div className="mk-head">
            <Avatar text={listing.title} large />
            <div className="mk-head-main">
              <h2>{listing.title}</h2>
              <span className="muted">@{listing.username} · {t(STATUS_KEY[listing.status ?? 'active'])}</span>
              <span className="muted small">{t('mk.views', { n: listing.view_count ?? 0 })} · {t('mk.requests', { n: listing.inquiry_count ?? 0 })}</span>
            </div>
          </div>
          {blocked && <div className="banner banner-error" role="alert">{t('err.market_blocked')}</div>}
          <ListingFacts listing={listing} />
        </section>
      )}

      <section className="card mk-form">
        <label className="field" htmlFor="mk-cat">{t('mk.fCategory')}</label>
        <select id="mk-cat" className="input" value={category} disabled={busy !== null}
          onChange={(e) => setCategory(e.target.value as MarketCategory)}>
          {MARKET_CATEGORIES.map((c) => <option key={c} value={c}>{t(`mk.cat.${c}` as MessageKey)}</option>)}
        </select>
        <label className="field" htmlFor="mk-price">{t('mk.fPriceInput')}</label>
        <input id="mk-price" className="input" inputMode="numeric" value={price} placeholder={currency === 'USD' ? '$20' : '50000'} aria-invalid={priceBad || undefined}
          disabled={busy !== null} onChange={(e) => { setPrice(e.target.value); setPriceBad(false) }} />
        <p className={priceBad ? 'field-error' : 'muted small'}>{t(currency === 'USD' ? 'mk.priceHintUsd' : 'mk.priceHint')}</p>
        <label className="field" htmlFor="mk-desc">{t('mk.fDesc')}</label>
        <textarea id="mk-desc" className="input" rows={3} value={desc} maxLength={descMax} disabled={busy !== null}
          onChange={(e) => setDesc(e.target.value)} />
        <p className="muted small">{t('mk.descHint', { max: descMax })}</p>
        {needPhone && (
          <div className="banner banner-warn" role="status">
            {t('mk.phoneNeeded')}{' '}
            {openBotAvailable(botUsername) && <button type="button" className="btn btn-ghost" onClick={() => openBot(botUsername)}>{t('common.openBot')}</button>}
          </div>
        )}
        {error && <FormError error={error} />}
        <Button variant="primary" block icon={listing ? 'check' : 'sparkle'} busy={busy === 'save'} disabled={busy !== null && busy !== 'save'} onClick={save}>
          {listing ? t('mk.save') : t('mk.publish')}
        </Button>
      </section>

      {listing && (
        <div className="mk-actions">
          {!blocked && (
            <Button block icon={listing.status === 'paused' ? 'send' : 'clock'} busy={busy === 'toggle'} onClick={toggle}>
              {listing.status === 'paused' ? t('mk.resume') : t('mk.pause')}
            </Button>
          )}
          <Button block icon="refresh" busy={busy === 'refresh'} onClick={refresh}>{t('mk.refresh')}</Button>
          <Button variant="ghost" block icon="trash" onClick={() => setConfirmRemove(true)}>{t('mk.remove')}</Button>
        </div>
      )}
      {confirmRemove && (
        <ConfirmDialog title={t('mk.remove')} body={t('mk.removeAsk')} confirmLabel={t('mk.remove')} danger busy={busy === 'remove'}
          onConfirm={remove} onClose={() => setConfirmRemove(false)} />
      )}
    </SubPage>
  )
}
