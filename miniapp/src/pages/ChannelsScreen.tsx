import { useState } from 'react'
import { useAppData } from '../AppData'
import { Avatar } from '../components/Avatar'
import { SubPage } from '../components/SubPage'
import { Button, ErrorState, LoadingBlock, openBotAvailable } from '../components/ui'
import { useI18n } from '../i18n'
import { openBot } from '../telegram'
import { ChannelStatsView } from './StatsPage'

/** Kanallarim: ro'yxat (rejadagi postlar, obunachilar) va har bir kanal uchun «Tahlil». */
export function ChannelsScreen({ onBack }: { onBack: () => void }) {
  const { channels, botUsername } = useAppData()
  const { t, formatDate } = useI18n()
  const [statsFor, setStatsFor] = useState<{ id: string; title: string } | null>(null)
  if (statsFor) return <ChannelStatsView channelId={statsFor.id} title={statsFor.title} onBack={() => setStatsFor(null)} />
  return (
    <SubPage title={t('me.channels')} onBack={onBack}>
      <section className="card" aria-labelledby="channels">
        <h2 id="channels" className="sr-only">{t('me.channels')}</h2>
        {channels.loading && <LoadingBlock rows={2} />}
        {!channels.data && channels.error && <ErrorState error={channels.error} onRetry={channels.reload} botUsername={botUsername} />}
        {channels.data && channels.data.items.length === 0 && <p className="muted">{t('me.channelsEmpty')}</p>}
        {channels.data && channels.data.items.length > 0 && (
          <ul className="list">
            {channels.data.items.map((c) => {
              const title = c.title || c.id
              return (
                <li key={c.id} className="item chan">
                  <Avatar text={title} small />
                  <span className="chan-main">
                    <strong className="chan-title">{title}</strong>
                    <span className="muted small">
                      {c.pending_posts !== undefined && t('me.chPending', { n: c.pending_posts })}
                      {c.pending_posts !== undefined && c.members != null && ' · '}
                      {c.members != null && t('me.chMembers', { n: c.members.toLocaleString() })}
                      {c.members != null && c.members_as_of ? ` (${formatDate(c.members_as_of)})` : ''}
                    </span>
                  </span>
                  <Button className="chan-act" icon="chart" onClick={() => setStatsFor({ id: c.id, title })}>{t('stats.open')}</Button>
                </li>
              )
            })}
          </ul>
        )}
      </section>
      {openBotAvailable(botUsername) && (
        <Button variant="primary" block icon="plus" onClick={() => openBot(botUsername, 'channels')}>{t('me.addChannel')}</Button>
      )}
    </SubPage>
  )
}
