import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import { MARKET_CATEGORIES, type MarketCategory, type MarketListing, type MarketSort } from '../api/types'
import { Avatar } from '../components/Avatar'
import { Icon } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Button, ErrorState, LoadingBlock } from '../components/ui'
import { toClientError, useResource } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { getInitialThread, haptic } from '../telegram'
import { ThreadList, ThreadView } from './MarketChats'
import { ListingView, usePriceText } from './MarketListing'
import { MineEditor, MineList } from './MarketMine'
import { formatCount } from './marketUtils'

type Sub = 'catalog' | 'mine' | 'chats'
type Screen =
  | { kind: 'main' }
  | { kind: 'card'; id: number }
  | { kind: 'editor'; channelId: string; title: string; listing: MarketListing | null }
  | { kind: 'thread'; id: number }

/** Katalog sahifalari: mavzu/saralash o'zgarsa boshidan, «Yana» bosilsa keyingi sahifa qo'shiladi. */
function useCatalog(category: MarketCategory | 'all', sort: MarketSort) {
  const { client } = useAppData()
  const [items, setItems] = useState<MarketListing[]>([])
  const [page, setPage] = useState(0)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiClientError | null>(null)
  const ctl = useRef<AbortController | null>(null)

  const load = useCallback((target: number) => {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setLoading(true)
    setError(null)
    client.marketCatalog(category, sort, target, c.signal).then(
      (res) => {
        if (c.signal.aborted) return
        setItems((prev) => (target === 0 ? res.items : [...prev, ...res.items]))
        setPage(res.page)
        setPages(res.pages)
        setTotal(res.total)
        setLoading(false)
      },
      (e) => { if (!c.signal.aborted) { setError(toClientError(e)); setLoading(false) } },
    )
  }, [client, category, sort])

  useEffect(() => { load(0); return () => ctl.current?.abort() }, [load])
  return { items, total, loading, error, hasMore: page + 1 < pages, more: () => load(page + 1), reload: () => load(0) }
}

function ListingRow({ listing, onOpen }: { listing: MarketListing; onOpen: () => void }) {
  const { t } = useI18n()
  const price = usePriceText()
  return (
    <button type="button" className="item mk-card" onClick={() => { haptic('select'); onOpen() }}>
      <Avatar text={listing.title} />
      <span className="mk-card-main">
        <strong className="mk-card-title">{listing.title}</strong>
        <span className="muted small">@{listing.username} · {t(`mk.cat.${listing.category}` as MessageKey)}</span>
        <span className="mk-chips-row">
          <span className="mk-pill">👥 {formatCount(listing.members)}</span>
          {listing.er_percent !== null && <span className="mk-pill">📈 {listing.er_percent}%</span>}
          <span className="mk-pill">💲 {price(listing.price)}</span>
        </span>
      </span>
      <span className="mk-go" aria-hidden="true"><Icon name="chevron" size={16} /></span>
    </button>
  )
}

function Catalog({ onOpen }: { onOpen: (id: number) => void }) {
  const { t } = useI18n()
  const [category, setCategory] = useState<MarketCategory | 'all'>('all')
  const [sort, setSort] = useState<MarketSort>('m')
  const cat = useCatalog(category, sort)
  const sorts: Array<[MarketSort, MessageKey]> = [['m', 'mk.sortM'], ['p', 'mk.sortP'], ['e', 'mk.sortE']]
  return (
    <>
      <div className="mk-chips" role="group" aria-label={t('mk.tabCatalog')}>
        {(['all', ...MARKET_CATEGORIES] as const).map((c) => (
          <button key={c} type="button" className="chip" aria-pressed={category === c} onClick={() => setCategory(c)}>
            {c === 'all' ? t('mk.catAll') : t(`mk.cat.${c}` as MessageKey)}
          </button>
        ))}
      </div>
      <div className="mk-sort" role="group" aria-label={t('mk.sortBy')}>
        <span className="muted small">{t('mk.sortBy')}</span>
        {sorts.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)}>{t(label)}</button>
        ))}
      </div>
      {cat.loading && cat.items.length === 0 && <LoadingBlock rows={3} />}
      {cat.error && cat.items.length === 0 && <ErrorState error={cat.error} onRetry={cat.reload} />}
      {!cat.loading && !cat.error && cat.items.length === 0 && (
        <section className="card mk-empty"><p>{t('mk.empty')}</p></section>
      )}
      {cat.items.length > 0 && (
        <ul className="list">
          {cat.items.map((l) => <li key={l.id}><ListingRow listing={l} onOpen={() => onOpen(l.id)} /></li>)}
        </ul>
      )}
      {cat.hasMore && <Button block busy={cat.loading} onClick={cat.more}>{t('mk.tabCatalog')} +</Button>}
    </>
  )
}

/** 💰 Reklama birjasi: katalog, o'z kanalini qo'yish va suhbatlar (bot bilan bir xil qoidalar). */
export function MarketPage() {
  const { client, refreshUnread } = useAppData()
  const { t } = useI18n()
  // Botdagi «📱 Mini App'da» tugmasi (?tab=market&thread=<id>) suhbatni to'g'ridan-to'g'ri ochadi.
  const [sub, setSub] = useState<Sub>(() => (getInitialThread() ? 'chats' : 'catalog'))
  const [screen, setScreen] = useState<Screen>(() => {
    const id = getInitialThread()
    return id ? { kind: 'thread', id } : { kind: 'main' }
  })
  const summary = useResource((s) => client.marketSummary(s), true)
  const mine = useResource((s) => client.marketMine(s), sub === 'mine' || screen.kind === 'editor')
  const threads = useResource((s) => client.marketThreads(s), sub === 'chats' || screen.kind === 'thread')
  const back = () => setScreen({ kind: 'main' })

  if (screen.kind === 'card') {
    return <ListingView id={screen.id} summary={summary.data} onBack={back}
      onOpenChats={() => { setSub('chats'); threads.reload(); back() }} />
  }
  if (screen.kind === 'editor') {
    return <MineEditor channelId={screen.channelId} title={screen.title} listing={screen.listing} summary={summary.data}
      onBack={back} onChanged={() => { mine.reload(); summary.reload() }} />
  }
  if (screen.kind === 'thread') {
    return <ThreadView id={screen.id} onBack={back} onChanged={() => { threads.reload(); refreshUnread() }} />
  }

  const subs: Array<[Sub, MessageKey]> = [['catalog', 'mk.tabCatalog'], ['mine', 'mk.tabMine'], ['chats', 'mk.tabChats']]
  return (
    <Page wide>
      <PageHeader title={t('mk.title')} onRefresh={() => { summary.reload(); mine.reload(); threads.reload() }} refreshing={summary.refreshing} />
      <section className="card hero hero-wow mk-hero" aria-label={t('mk.title')}>
        <div className="hero-glow" aria-hidden="true" />
        <p className="lead">{t('mk.lead')}</p>
        {summary.data && (
          <div className="hero-chips">
            <span className="chip chip-glass">{t('mk.stats', { listings: summary.data.listings, inquiries: summary.data.inquiries })}</span>
          </div>
        )}
      </section>
      <fieldset className="segmented mk-subtabs" aria-label={t('mk.title')}>
        {subs.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={sub === k} onClick={() => setSub(k)}>{t(label)}</button>
        ))}
      </fieldset>
      {sub === 'catalog' && <Catalog onOpen={(id) => setScreen({ kind: 'card', id })} />}
      {sub === 'mine' && <MineList mine={mine} onOpen={(c) => setScreen({ kind: 'editor', ...c })} />}
      {sub === 'chats' && <ThreadList threads={threads} onOpen={(id) => setScreen({ kind: 'thread', id })} />}
      <details className="card mk-how">
        <summary>{t('mk.howTitle')}</summary>
        <ol>
          <li>{t('mk.how1')}</li>
          <li>{t('mk.how2')}</li>
          <li>{t('mk.how3')}</li>
        </ol>
        <p className="muted small">🛡 {t('mk.safety')}</p>
      </details>
    </Page>
  )
}
