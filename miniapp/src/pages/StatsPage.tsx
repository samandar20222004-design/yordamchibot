import { useState } from 'react'
import { useAppData } from '../AppData'
import type { ChannelAnalytics, Confidence } from '../api/types'
import { Page, PageHeader } from '../components/Shell'
import { Badge, ErrorState, InlineWarning, LoadingBlock } from '../components/ui'
import { Button } from '../components/ui'
import { useResource } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'

const CONF_KEYS: Record<Confidence, MessageKey> = {
  none: 'stats.conf.none', low: 'stats.conf.low', medium: 'stats.conf.medium', high: 'stats.conf.high',
}

/** O'sish: +50 / -120 / 0; ma'lumot yo'q (null) -> 0 EMAS, "ma'lumot yetarli emas". */
export function formatDelta(value: number | null, noData: string): string {
  if (value === null) return noData
  if (value === 0) return '0'
  return value > 0 ? `+${value.toLocaleString()}` : `-${Math.abs(value).toLocaleString()}`
}

function MembersCard({ data }: { data: ChannelAnalytics['members'] }) {
  const { t, formatDate } = useI18n()
  const noData = t('stats.noData')
  if (data.current === null) {
    return (
      <section className="card" aria-labelledby="st-members">
        <h2 id="st-members">{t('stats.members')}</h2>
        <p className="muted">{t('stats.collecting')}</p>
      </section>
    )
  }
  const sourceLabel = data.source === 'bot_api_getChatMemberCount' ? t('stats.source.telegram') : (data.source ?? '—')
  const history = data.history
  const counts = history.map((h) => h.member_count)
  const lo = Math.min(...counts)
  const hi = Math.max(...counts)
  const widthOf = (n: number) => (hi === lo ? 100 : 12 + Math.round(((n - lo) / (hi - lo)) * 88))
  return (
    <section className="card" aria-labelledby="st-members">
      <div className="card-row">
        <h2 id="st-members">{t('stats.members')}</h2>
        <Badge>{t('stats.confidence')}: {t(CONF_KEYS[data.confidence])}</Badge>
      </div>
      <div className="stat-big">
        <span className="stat-value" data-testid="members-current">{data.current.toLocaleString()}</span>
        {data.as_of && <span className="stat-label">{t('stats.asOf', { date: formatDate(data.as_of) })}</span>}
      </div>
      <div className="stats">
        <div className="stat"><span className="stat-label">{t('stats.delta7')}</span>
          <span className="stat-value" data-testid="delta-7">{formatDelta(data.delta_7d, noData)}</span></div>
        <div className="stat"><span className="stat-label">{t('stats.delta30')}</span>
          <span className="stat-value" data-testid="delta-30">{formatDelta(data.delta_30d, noData)}</span></div>
      </div>
      {data.stale && <div className="banner banner-warn" role="status">{t('stats.stale')}</div>}
      {history.length > 1 && (
        <div>
          <h3 className="group-title">{t('stats.history')}</h3>
          <ul className="hist">
            {history.map((h) => (
              <li key={h.date}>
                <span className="muted">{formatDate(h.date)}</span>
                <span className="bar" style={{ width: `${widthOf(h.member_count)}%` }} aria-hidden="true" />
                <span>{h.member_count.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted small">{t('stats.source', { source: sourceLabel })}</p>
    </section>
  )
}

function PostsCard({ data }: { data: ChannelAnalytics['posts'] }) {
  const { t } = useI18n()
  const cells: Array<[MessageKey, number]> = [
    ['stats.sent7', data.sent_7d], ['stats.sent30', data.sent_30d], ['stats.sentAll', data.sent_all],
    ['stats.pending', data.pending], ['stats.failed', data.failed], ['stats.unknown', data.unknown],
  ]
  return (
    <section className="card" aria-labelledby="st-posts">
      <h2 id="st-posts">{t('stats.posts')}</h2>
      <div className="stats">
        {cells.map(([key, value]) => (
          <div className="stat" key={key}><span className="stat-label">{t(key)}</span><span className="stat-value">{value}</span></div>
        ))}
      </div>
      <p className="muted small">{t('stats.postsNote')}</p>
    </section>
  )
}

function ViewsCard({ data }: { data: ChannelAnalytics['views'] }) {
  const { t } = useI18n()
  return (
    <section className="card" aria-labelledby="st-views">
      <h2 id="st-views">{t('stats.views')}</h2>
      {data.available && data.avg !== null && data.max !== null ? (
        <>
          <div className="stats">
            <div className="stat"><span className="stat-label">{t('stats.viewsAvg', { n: data.with_views })}</span>
              <span className="stat-value">{data.avg.toLocaleString()}</span></div>
            <div className="stat"><span className="stat-label">{t('stats.viewsMax')}</span>
              <span className="stat-value">{data.max.toLocaleString()}</span></div>
          </div>
          {data.sources.length > 0 && <p className="muted small">{t('stats.source', { source: data.sources.join(', ') })}</p>}
        </>
      ) : (
        <p className="muted" data-testid="views-unavailable">{t('stats.viewsUnavailable')}</p>
      )}
    </section>
  )
}

function ChannelStats({ channelId }: { channelId: string }) {
  const { client, botUsername } = useAppData()
  const res = useResource((signal) => client.channelAnalytics(channelId, signal), true)
  if (res.loading) return <LoadingBlock rows={4} />
  if (!res.data) return res.error ? <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} /> : null
  return (
    <>
      {res.error && <InlineWarning error={res.error} onRetry={res.reload} />}
      <MembersCard data={res.data.members} />
      <PostsCard data={res.data.posts} />
      <ViewsCard data={res.data.views} />
    </>
  )
}

/** Bitta kanal tahlili (Men -> Kanallarim -> «Tahlil»): sarlavhada «Orqaga», yangilash tugmasi. */
export function ChannelStatsView({ channelId, title, onBack }: { channelId: string; title: string; onBack: () => void }) {
  const { t } = useI18n()
  const [nonce, setNonce] = useState(0)
  return (
    <Page wide>
      <Button variant="ghost" onClick={onBack}>‹ {t('common.back')}</Button>
      <PageHeader title={title} onRefresh={() => setNonce((n) => n + 1)} />
      <ChannelStats key={`${channelId}:${nonce}`} channelId={channelId} />
    </Page>
  )
}
