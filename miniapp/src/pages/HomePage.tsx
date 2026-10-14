import { useAppData } from '../AppData'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, EmptyState, ErrorState, InlineWarning, LoadingBlock, openBotAvailable } from '../components/ui'
import { useI18n } from '../i18n'
import { openBot } from '../telegram'
import { isUnlimited } from './format'

export function HomePage() {
  const { me, go, botUsername } = useAppData()
  const { t, formatDateTime } = useI18n()

  if (me.loading) return <Page><PageHeader title="PostAssist" /><LoadingBlock rows={4} /></Page>
  if (!me.data) {
    return (
      <Page>
        <PageHeader title="PostAssist" />
        {me.error && <ErrorState error={me.error} onRetry={me.reload} botUsername={botUsername} />}
      </Page>
    )
  }

  const { user, plan, usage, posts, next_post_at: nextAt } = me.data
  const limit = (n: number) => (isUnlimited(n) ? t('common.unlimited') : String(n))
  return (
    <Page>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title="PostAssist" onRefresh={me.reload} refreshing={me.refreshing} />
      <section aria-labelledby="hello" className="card">
        <div className="card-row">
          <h2 id="hello">{user.name ? t('home.hello', { name: user.name }) : t('home.helloAnon')}</h2>
          <Badge pro={plan.is_pro}>{plan.is_pro ? t('plan.pro') : t('plan.free')}</Badge>
        </div>
        <p className="lead">{t('home.subtitle')}</p>
      </section>

      <div className="stats">
        <div className="stat"><span className="stat-label">{t('home.channels')}</span>
          <span className="stat-value">{usage.channels}</span></div>
        <div className="stat"><span className="stat-label">{t('home.scheduled')}</span>
          <span className="stat-value">{usage.pending_posts} / {limit(plan.limits.queued_posts)}</span></div>
        <div className="stat"><span className="stat-label">{t('home.sent')}</span>
          <span className="stat-value">{posts.sent}</span></div>
        <div className="stat"><span className="stat-label">{t('home.failed')}</span>
          <span className="stat-value">{posts.failed}</span></div>
        <div className="stat stat-wide"><span className="stat-label">{t('home.ai')}</span>
          <span className="stat-value">{usage.ai_requests_today} / {limit(plan.limits.daily_ai_requests)}</span></div>
        <div className="stat stat-wide"><span className="stat-label">{t('home.next')}</span>
          <span className="stat-value">{nextAt ? formatDateTime(nextAt) : t('home.nextNone')}</span></div>
      </div>

      {usage.channels === 0 && (
        <EmptyState title={t('home.noChannelsTitle')} body={t('home.noChannelsBody')}
          action={openBotAvailable(botUsername)
            ? <Button variant="primary" icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
            : undefined} />
      )}

      <section className="card" aria-labelledby="actions">
        <h2 id="actions">{t('home.actions')}</h2>
        <Button variant="primary" block icon="post" onClick={() => go('post')}>{t('home.goPost')}</Button>
        <Button block icon="calendar" onClick={() => go('schedule')}>{t('home.goSchedule')}</Button>
        <Button block icon="user" onClick={() => go('me')}>{t('home.goMe')}</Button>
      </section>
    </Page>
  )
}
