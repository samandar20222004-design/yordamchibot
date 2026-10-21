import { useRef, useState } from 'react'
import { useAppData } from '../../AppData'
import type { AdSupport, AdminAd, AdminListing, AdminSponsor } from '../../api/types'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Page, PageHeader } from '../../components/Shell'
import { Button, CountUp, EmptyState, ErrorState, FormError, LoadingBlock } from '../../components/ui'
import { ApiClientError } from '../../api/client'
import { toClientError, useResource } from '../../hooks/useResource'
import { useI18n, type MessageKey } from '../../i18n'
import { haptic } from '../../telegram'
import { countryFlag } from '../marketUtils'

/** Bitta almashtirgich (switch) qatori — reklama yoqish/o'chirish. */
export function SwitchRow({ id, title, hint, on, disabled, onChange }: {
  id: string; title: string; hint?: string; on: boolean; disabled?: boolean; onChange: (next: boolean) => void
}) {
  return (
    <div className="switch-row">
      <span className="switch-text">
        <strong id={id}>{title}</strong>
        {hint && <span className="muted small">{hint}</span>}
      </span>
      <button type="button" role="switch" className="switch" aria-checked={on} aria-labelledby={id} disabled={disabled}
        onClick={() => onChange(!on)}><span className="switch-knob" /></button>
    </div>
  )
}

export function useAdminAction() {
  const { notify } = useAppData()
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiClientError | null>(null)
  const inFlight = useRef(false)
  /** Bir vaqtda bitta amal; muvaffaqiyatda `ok` xabari, xatoda forma xatosi. */
  const run = async (fn: () => Promise<unknown>, ok?: MessageKey): Promise<boolean> => {
    if (inFlight.current) return false
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await fn()
      if (ok) notify(t(ok))
      haptic('success')
      return true
    } catch (e) {
      setError(toClientError(e))
      haptic('error')
      return false
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  return { busy, error, run, clear: () => setError(null) }
}

// ----------------------------------------------------------------- Umumiy
export function AdminOverviewPage() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminOverview(s), true)
  const d = res.data
  const cards: Array<{ key: MessageKey; value: number; tone: string }> = d ? [
    { key: 'adm.stUsers', value: d.stats.users, tone: 'blue' },
    { key: 'adm.stPro', value: d.stats.pro_subscribers, tone: 'gold' },
    { key: 'adm.stChannels', value: d.stats.channels, tone: 'green' },
    { key: 'adm.stToday', value: d.stats.posts_today, tone: 'violet' },
    { key: 'adm.stPending', value: d.stats.pending_posts, tone: 'blue' },
    { key: 'adm.stSent', value: d.stats.sent, tone: 'green' },
    { key: 'adm.stFailed', value: d.stats.failed, tone: 'rose' },
    { key: 'adm.stStars', value: d.stats.stars_revenue, tone: 'gold' },
  ] : []
  return (
    <Page>
      <PageHeader title={t('adm.overview')} onRefresh={res.reload} refreshing={res.refreshing} />
      {res.loading && <LoadingBlock rows={4} />}
      {!d && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {d && (
        <>
          <div className="adm-grid">
            {cards.map((c) => (
              <div key={c.key} className={`adm-stat tone-stat-${c.tone}`}>
                <span className="stat-label">{t(c.key)}</span>
                <strong className="stat-value"><CountUp value={c.value} /></strong>
              </div>
            ))}
          </div>
          <h3 className="sec-label">{t('adm.secMarket')}</h3>
          <div className="adm-grid">
            <div className="adm-stat"><span className="stat-label">{t('adm.mkActive')}</span><strong className="stat-value">{d.market.active}</strong></div>
            <div className="adm-stat"><span className="stat-label">{t('adm.mkBlocked')}</span><strong className="stat-value">{d.market.blocked}</strong></div>
            <div className="adm-stat"><span className="stat-label">{t('adm.mkBanned')}</span><strong className="stat-value">{d.market.banned_users}</strong></div>
            <div className="adm-stat"><span className="stat-label">{t('adm.mkOpen')}</span><strong className="stat-value">{d.market.open_inquiries}</strong></div>
          </div>
          <h3 className="sec-label">{t('adm.secCountries', { v: d.countries.verified, total: d.countries.total })}</h3>
          <div className="adm-grid">
            {d.countries.items.slice(0, 12).map((c) => (
              <div key={c.country} className="adm-stat">
                <span className="stat-label">{countryFlag(c.country)} {c.country === 'ZZ' ? '—' : c.country}</span>
                <strong className="stat-value">{c.users}</strong>
              </div>
            ))}
            <div className="adm-stat"><span className="stat-label">{t('adm.unverified')}</span><strong className="stat-value">{d.countries.unverified}</strong></div>
          </div>
          <p className="muted small">{t('adm.sponsorsCount', { n: d.stats.sponsors })}</p>
        </>
      )}
    </Page>
  )
}

// ----------------------------------------------------------------- Reklama
function AdEditor({ scope, ad, onClose, onSaved }: { scope: AdSupport; ad: AdminAd | null; onClose: () => void; onSaved: () => void }) {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [text, setText] = useState(ad?.text ?? '')
  const [btnText, setBtnText] = useState(ad?.button_text ?? '')
  const [btnUrl, setBtnUrl] = useState(ad?.button_url ?? '')
  const save = async () => {
    const button = { button_text: btnText.trim(), button_url: btnUrl.trim() }
    const ok = await run(() => ad
      ? client.adminAdUpdate(ad.id, { text, ...button })
      : client.adminAdCreate({ scope, text, ...button }), 'adm.saved')
    if (ok) onSaved()
  }
  return (
    <Dialog title={ad ? t('adm.adEdit') : t('adm.adNew')} onClose={onClose} busy={busy}>
      <label className="field">{t('adm.adText')}
        <textarea className="input" rows={6} value={text} maxLength={1000} onChange={(e) => setText(e.target.value)} />
      </label>
      <p className="muted small">{t('adm.adHtmlHint')}</p>
      <label className="field">{t('adm.adBtnText')}
        <input className="input" value={btnText} maxLength={64} onChange={(e) => setBtnText(e.target.value)} />
      </label>
      <label className="field">{t('adm.adBtnUrl')}
        <input className="input" inputMode="url" autoCapitalize="none" value={btnUrl} maxLength={500} placeholder="https://" onChange={(e) => setBtnUrl(e.target.value)} />
      </label>
      {error && <FormError error={error} />}
      <div className="dialog-actions">
        <Button onClick={onClose} disabled={busy}>{t('common.back')}</Button>
        <Button variant="primary" busy={busy} disabled={text.trim().length === 0} onClick={() => void save()}>{t('adm.save')}</Button>
      </div>
    </Dialog>
  )
}

function AdSideCard({ scope, enabled, interval, ads, reload }: {
  scope: AdSupport; enabled: boolean; interval: number; ads: AdminAd[]; reload: () => void
}) {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [value, setValue] = useState(String(interval))
  const [editor, setEditor] = useState<{ ad: AdminAd | null } | null>(null)
  const [removing, setRemoving] = useState<AdminAd | null>(null)
  const keyEnabled = scope === 'reply' ? 'reply_enabled' : 'channel_enabled'
  const keyInterval = scope === 'reply' ? 'reply_interval' : 'channel_interval'
  const n = Number(value)
  const valid = Number.isInteger(n) && n >= 1 && n <= 100
  return (
    <section className="card adm-card">
      <h2>{t(scope === 'reply' ? 'adm.adReply' : 'adm.adChannel')}</h2>
      <p className="muted small">{t(scope === 'reply' ? 'adm.adReplyHint' : 'adm.adChannelHint')}</p>
      <SwitchRow id={`adm-sw-${scope}`} title={t('adm.adEnabled')} on={enabled} disabled={busy}
        onChange={(next) => { void run(() => client.adminAdSettings({ [keyEnabled]: next }), 'adm.saved').then(reload) }} />
      <div className="adm-inline">
        <label className="field">{t('adm.adInterval')}
          <input className="input" type="number" inputMode="numeric" min={1} max={100} value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <Button busy={busy} disabled={!valid || n === interval} onClick={() => { void run(() => client.adminAdSettings({ [keyInterval]: n }), 'adm.saved').then(reload) }}>
          {t('adm.save')}
        </Button>
      </div>
      {error && <FormError error={error} />}
      <h3 className="sec-label">{t('adm.adList', { n: ads.length })}</h3>
      {ads.length === 0 && <p className="muted small">{t('adm.adEmpty')}</p>}
      <ul className="list">
        {ads.map((ad) => (
          <li key={ad.id} className="item adm-ad">
            <div className="adm-ad-text" dir="auto">{ad.text.replace(/<[^>]+>/g, '').slice(0, 160)}</div>
            {ad.button_text && <span className="chip">🔗 {ad.button_text}</span>}
            <div className="adm-actions">
              <SwitchRow id={`adm-ad-${ad.id}`} title={t(ad.is_active ? 'adm.adOn' : 'adm.adOff')} on={ad.is_active} disabled={busy}
                onChange={(next) => { void run(() => client.adminAdUpdate(ad.id, { is_active: next }), 'adm.saved').then(reload) }} />
              <Button icon="post" onClick={() => setEditor({ ad })} aria-label={t('adm.adEdit')} />
              <Button icon="trash" onClick={() => setRemoving(ad)} aria-label={t('adm.delete')} />
            </div>
          </li>
        ))}
      </ul>
      <Button icon="plus" variant="primary" block onClick={() => setEditor({ ad: null })}>{t('adm.adNew')}</Button>
      {editor && <AdEditor scope={scope} ad={editor.ad} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); reload() }} />}
      {removing && (
        <ConfirmDialog title={t('adm.delete')} body={t('adm.adDeleteAsk')} confirmLabel={t('adm.delete')} danger busy={busy}
          onClose={() => setRemoving(null)}
          onConfirm={() => { void run(() => client.adminAdDelete(removing.id), 'adm.deleted').then((ok) => { if (ok) { setRemoving(null); reload() } }) }} />
      )}
    </section>
  )
}

export function AdminAdsPage() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminAds(s), true)
  const d = res.data
  return (
    <Page>
      <PageHeader title={t('adm.ads')} onRefresh={res.reload} refreshing={res.refreshing} />
      {res.loading && <LoadingBlock rows={4} />}
      {!d && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {d && (
        <>
          <AdSideCard key={`c-${d.settings.channel.enabled}-${d.settings.channel.interval}`} scope="channel" enabled={d.settings.channel.enabled}
            interval={d.settings.channel.interval} ads={d.items.channel} reload={res.reload} />
          <AdSideCard key={`r-${d.settings.reply.enabled}-${d.settings.reply.interval}`} scope="reply" enabled={d.settings.reply.enabled}
            interval={d.settings.reply.interval} ads={d.items.reply} reload={res.reload} />
        </>
      )}
    </Page>
  )
}

// ----------------------------------------------------------------- Majburiy obuna
export function AdminSponsorsPage() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminSponsors(s), true)
  const { busy, error, run, clear } = useAdminAction()
  const [value, setValue] = useState('')
  const [removing, setRemoving] = useState<AdminSponsor | null>(null)
  const add = async () => {
    const ok = await run(() => client.adminSponsorAdd(value.trim()), 'adm.sponsorAdded')
    if (ok) { setValue(''); res.reload() }
  }
  return (
    <Page>
      <PageHeader title={t('adm.subs')} onRefresh={res.reload} refreshing={res.refreshing} />
      <p className="muted">{t('adm.subsHint')}</p>
      <section className="card adm-card">
        <label className="field">{t('adm.subsAdd')}
          <input className="input" value={value} maxLength={80} autoCapitalize="none" autoCorrect="off" placeholder="@kanal"
            onChange={(e) => { setValue(e.target.value); clear() }} />
        </label>
        <p className="muted small">{t('adm.subsAddHint')}</p>
        {error && <FormError error={error} />}
        <Button variant="primary" icon="plus" block busy={busy} disabled={value.trim().length < 4} onClick={() => void add()}>{t('adm.subsAddBtn')}</Button>
      </section>
      {res.loading && <LoadingBlock rows={3} />}
      {!res.data && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {res.data && res.data.items.length === 0 && <EmptyState title={t('adm.subsEmptyTitle')} body={t('adm.subsEmpty')} />}
      {res.data && res.data.items.length > 0 && (
        <ul className="list">
          {res.data.items.map((s) => (
            <li key={s.id} className="item adm-row">
              <span className="adm-row-main">
                <strong className="adm-row-title">{s.title || s.username || s.channel_id}</strong>
                <span className="muted small">{s.username ? `@${s.username}` : s.channel_id}</span>
              </span>
              <Button icon="trash" onClick={() => setRemoving(s)} aria-label={t('adm.delete')} />
            </li>
          ))}
        </ul>
      )}
      {removing && (
        <ConfirmDialog title={t('adm.delete')} body={t('adm.subsDeleteAsk', { name: removing.title || removing.username || removing.channel_id })}
          confirmLabel={t('adm.delete')} danger busy={busy} onClose={() => setRemoving(null)}
          onConfirm={() => { void run(() => client.adminSponsorDelete(removing.id), 'adm.deleted').then((ok) => { if (ok) { setRemoving(null); res.reload() } }) }} />
      )}
    </Page>
  )
}

// ----------------------------------------------------------------- Birja nazorati
type MarketFilter = 'all' | 'active' | 'paused' | 'blocked'
const FILTERS: ReadonlyArray<{ id: MarketFilter; label: MessageKey }> = [
  { id: 'all', label: 'adm.fAll' }, { id: 'active', label: 'adm.fActive' }, { id: 'paused', label: 'adm.fPaused' }, { id: 'blocked', label: 'adm.fBlocked' },
]

export function AdminMarketPage() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const [filter, setFilter] = useState<MarketFilter>('all')
  const res = useResource((s) => client.adminMarket(filter, s), true)
  const { busy, error, run } = useAdminAction()
  const [ask, setAsk] = useState<{ kind: 'block' | 'unblock' | 'ban' | 'unban'; item: AdminListing } | null>(null)
  const apply = async () => {
    if (!ask) return
    const { kind, item } = ask
    const ok = await run(() => kind === 'block' || kind === 'unblock'
      ? client.adminListingStatus(item.id, kind === 'block' ? 'blocked' : 'active')
      : client.adminUserBan(item.owner_id, kind === 'ban'), 'adm.saved')
    if (ok) { setAsk(null); res.reload() }
  }
  const changeFilter = (f: MarketFilter) => { setFilter(f); setTimeout(res.reload, 0) }
  return (
    <Page>
      <PageHeader title={t('adm.market')} onRefresh={res.reload} refreshing={res.refreshing} />
      <div className="chips" role="group" aria-label={t('adm.market')}>
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className={`chip`} aria-pressed={filter === f.id}
            onClick={() => changeFilter(f.id)}>{t(f.label)}</button>
        ))}
      </div>
      {error && <FormError error={error} />}
      {res.loading && <LoadingBlock rows={4} />}
      {!res.data && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {res.data && res.data.items.length === 0 && <EmptyState title={t('adm.mkEmptyTitle')} body={t('adm.mkEmpty')} />}
      {res.data && (
        <ul className="list">
          {res.data.items.map((it) => (
            <li key={it.id} className="item adm-listing">
              <div className="adm-row">
                <span className="adm-row-main">
                  <strong className="adm-row-title">{it.title || it.username}</strong>
                  <span className="muted small">
                    @{it.username} · {t('adm.mkMeta', { members: it.members ?? 0, views: it.view_count, reqs: it.inquiry_count })}
                  </span>
                </span>
                <span className={`mk-dot mk-dot-${it.status}`} aria-hidden="true" />
              </div>
              <div className="chips">
                <span className="chip">{t(`adm.st_${it.status}` as MessageKey)}</span>
                {it.reports > 0 && <span className="chip chip-warn">🚩 {it.reports}</span>}
                {it.owner_banned && <span className="chip chip-warn">⛔ {t('adm.ownerBanned')}</span>}
              </div>
              <div className="adm-actions">
                <Button onClick={() => setAsk({ kind: it.status === 'blocked' ? 'unblock' : 'block', item: it })}>
                  {t(it.status === 'blocked' ? 'adm.unblock' : 'adm.block')}
                </Button>
                <Button onClick={() => setAsk({ kind: it.owner_banned ? 'unban' : 'ban', item: it })}>
                  {t(it.owner_banned ? 'adm.unban' : 'adm.ban')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {ask && (
        <ConfirmDialog title={t(`adm.ask_${ask.kind}` as MessageKey)} body={t(`adm.askBody_${ask.kind}` as MessageKey, { name: ask.item.title || ask.item.username })}
          confirmLabel={t('adm.confirm')} danger={ask.kind === 'block' || ask.kind === 'ban'} busy={busy}
          onClose={() => setAsk(null)} onConfirm={() => void apply()} />
      )}
    </Page>
  )
}
