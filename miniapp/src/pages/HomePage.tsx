import { useAppData } from '../AppData'
import { Icon } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, EmptyState, ErrorState, InlineWarning, LoadingBlock, openBotAvailable } from '../components/ui'
import { useI18n } from '../i18n'
import { openBot } from '../telegram'
import { isUnlimited } from './format'

export function HomePage() {
  const { me, draft, go, botUsername } = useAppData()
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
    <Page wide>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title="PostAssist" onRefresh={me.reload} refreshing={me.refreshing} />
      <section aria-labelledby="hello" className="card hero">
        <div className="card-row">
          <h2 id="hello">{user.name ? t('home.hello', { name: user.name }) : t('home.helloAnon')}</h2>
          <Badge pro={plan.is_pro}>{plan.is_pro ? t('plan.pro') : t('plan.free')}</Badge>
        </div>
        <p className="lead">{t('home.subtitle')}</p>
      </section>

      {draft.data?.draft && (
        <section className="card cta-card" aria-labelledby="draft-cta">
          <h2 id="draft-cta">{t('home.draftTitle')}</h2>
          <p className="muted">{t('home.draftBody')}</p>
          <Button variant="primary" icon="send" block onClick={() => go('post')}>{t('home.draftOpen')}</Button>
        </section>
      )}

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

      <section aria-labelledby="actions">
        <h2 id="actions" className="group-title">{t('home.actions')}</h2>
        <div className="tiles">
          <button type="button" className="tile tile-primary" onClick={() => go('post')}>
            <Icon name="post" size={26} />{t('home.goPost')}
          </button>
          <button type="button" className="tile" onClick={() => go('schedule')}>
            <Icon name="calendar" size={26} />{t('home.goSchedule')}
          </button>
          <button type="button" className="tile" onClick={() => go('me')}>
            <Icon name="user" size={26} />{t('home.goMe')}
          </button>
        </div>
      </section>
    </Page>
  )
}
