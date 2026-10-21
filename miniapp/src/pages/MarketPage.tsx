import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { ApiClientError } from '../api/client'
import { MARKET_CATEGORIES, type MarketCategory, type MarketListing, type MarketSort } from '../api/types'
import { Avatar } from '../components/Avatar'
import { Icon } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Button, ErrorState, LoadingBlock, openBotAvailable } from '../components/ui'
import { toClientError, useResource } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { getInitialThread, haptic, openBot } from '../telegram'
import { ThreadList, ThreadView } from './MarketChats'
import { ListingView, usePriceText } from './MarketListing'
import { MineEditor, MineList } from './MarketMine'
import { countryFlag, formatCount } from './marketUtils'

type Sub = 'catalog' | 'mine' | 'chats'
type Screen =
  | { kind: 'main' }
  | { kind: 'card'; id: number }
  | { kind: 'editor'; channelId: string; title: string; listing: MarketListing | null }
  | { kind: 'thread'; id: number }

/** Katalog sahifalari: mavzu/saralash o'zgarsa boshidan, «Yana» bosilsa keyingi sahifa qo'shiladi. */
function useCatalog(category: MarketCategory | 'all', sort: MarketSort, scope: 'all' | 'mine' | 'auto') {
  const { client } = useAppData()
  const [items, setItems] = useState<MarketListing[]>([])
  const [page, setPage] = useState(0)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [viewerCountry, setViewerCountry] = useState('')
  const [applied, setApplied] = useState<'all' | 'mine'>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiClientError | null>(null)
  const ctl = useRef<AbortController | null>(null)

  const load = useCallback((target: number) => {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setLoading(true)
    setError(null)
    client.marketCatalog(category, sort, target, c.signal, scope).then(
      (res) => {
        if (c.signal.aborted) return
        setItems((prev) => (target === 0 ? res.items : [...prev, ...res.items]))
        setPage(res.page)
        setPages(res.pages)
        setTotal(res.total)
        setViewerCountry(res.viewer_country)
        setApplied(res.filter)
        setLoading(false)
      },
      (e) => { if (!c.signal.aborted) { setError(toClientError(e)); setLoading(false) } },
    )
  }, [client, category, sort, scope])

  useEffect(() => { load(0); return () => ctl.current?.abort() }, [load])
  return { items, total, viewerCountry, applied, loading, error, hasMore: page + 1 < pages, more: () => load(page + 1), reload: () => load(0) }
}

/** Kanal mahalliymi yoki xalqaroligi: e'lon egasining TASDIQLANGAN telefon mamlakati ko'ruvchiniki bilan solishtiriladi. */
function originOf(listing: MarketListing, viewerCountry: string): 'local' | 'intl' | 'unknown' {
  const c = (listing.country ?? '').toUpperCase()
  if (!c || c === 'ZZ') return 'unknown'
  return viewerCountry && c === viewerCountry.toUpperCase() ? 'local' : 'intl'
}

function ListingRow({ listing, viewerCountry, onOpen }: { listing: MarketListing; viewerCountry: string; onOpen: () => void }) {
  const { t } = useI18n()
  const price = usePriceText()
  const origin = originOf(listing, viewerCountry)
  return (
    <button type="button" className="item mk-card mk-card-compact" onClick={() => { haptic('select'); onOpen() }}>
      <Avatar text={listing.title} small />
      <span className="mk-card-main">
        <span className="mk-card-top">
          <strong className="mk-card-title">{listing.title}</strong>
          <span className={`mk-origin mk-origin-${origin}`} title={t(origin === 'local' ? 'mk.local' : 'mk.intl')}>
            {countryFlag(listing.country)}{origin === 'unknown' ? '' : ` ${t(origin === 'local' ? 'mk.local' : 'mk.intl')}`}
          </span>
        </span>
        <span className="muted small mk-card-meta">
          👥 {formatCount(listing.members)}{listing.er_percent !== null ? ` · 📈 ${listing.er_percent}%` : ''} · 💲 {price(listing.price, listing.currency)} · {t(`mk.cat.${listing.category}` as MessageKey)}
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
  const [scope, setScope] = useState<'all' | 'mine' | 'auto'>('auto')
  const cat = useCatalog(category, sort, scope)
  const { botUsername } = useAppData()
  const sorts: Array<[MarketSort, MessageKey]> = [['m', 'mk.sortM'], ['p', 'mk.sortP'], ['e', 'mk.sortE']]
  return (
    <>
      <div className="mk-toolbar">
        {cat.viewerCountry ? (
          <div className="mk-seg" role="group" aria-label={t('mk.countryLabel')}>
            <button type="button" aria-pressed={cat.applied === 'mine'} onClick={() => setScope('mine')}>{countryFlag(cat.viewerCountry)} {cat.viewerCountry}</button>
            <button type="button" aria-pressed={cat.applied === 'all'} onClick={() => setScope('all')}>{t('mk.countryAll')}</button>
          </div>
        ) : (
          openBotAvailable(botUsername)
            ? <button type="button" className="mk-verify" onClick={() => openBot(botUsername)}>📞 {t('mk.countryVerify')}</button>
            : <span />
        )}
        <select className="mk-select" aria-label={t('mk.sortBy')} value={sort} onChange={(e) => setSort(e.target.value as MarketSort)}>
          {sorts.map(([k, label]) => <option key={k} value={k}>{t(label)}</option>)}
        </select>
      </div>
      <div className="mk-chips" role="group" aria-label={t('mk.tabCatalog')}>
        {(['all', ...MARKET_CATEGORIES] as const).map((c) => (
          <button key={c} type="button" className="chip" aria-pressed={category === c} onClick={() => setCategory(c)}>
            {c === 'all' ? t('mk.catAll') : t(`mk.cat.${c}` as MessageKey)}
          </button>
        ))}
      </div>
      {cat.loading && cat.items.length === 0 && <LoadingBlock rows={3} />}
      {cat.error && cat.items.length === 0 && <ErrorState error={cat.error} onRetry={cat.reload} />}
      {!cat.loading && !cat.error && cat.items.length === 0 && (
        <section className="card mk-empty"><p>{t('mk.empty')}</p></section>
      )}
      {cat.items.length > 0 && (
        <ul className="list mk-list">
          {cat.items.map((l) => <li key={l.id}><ListingRow listing={l} viewerCountry={cat.viewerCountry} onOpen={() => onOpen(l.id)} /></li>)}
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
      {summary.data && <p className="muted small mk-stat">{t('mk.stats', { listings: summary.data.listings, inquiries: summary.data.inquiries })}</p>}
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
        <p className="muted small">{t('mk.lead')}</p>
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
