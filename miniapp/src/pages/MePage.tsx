import { useState } from 'react'
import { useAppData } from '../AppData'
import { Avatar, initialOf } from '../components/Avatar'
import { Icon, type IconName } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Badge, ErrorState, InlineWarning, LoadingBlock, openBotAvailable } from '../components/ui'
import { useI18n } from '../i18n'
import { closeApp, getUserPhotoUrl, openBot } from '../telegram'
import { ChannelsScreen } from './ChannelsScreen'
import { isUnlimited } from './format'
import { AppearanceScreen } from './AppearanceScreen'
import { LanguageScreen } from './LanguageScreen'
import { NOTIFICATION_DEFAULTS, NotificationsScreen, enabledCount } from './NotificationsScreen'
import { PlansScreen } from './PlansScreen'
import { TeamScreen } from './TeamScreen'

export { initialOf }

type Screen = null | 'plans' | 'lang' | 'channels' | 'notif' | 'look' | 'team'
const FLAGS = { uz: '🇺🇿', ru: '🇷🇺', en: '🇬🇧' } as const

function Row({ icon, tone, label, value, onClick }: { icon: IconName; tone: string; label: string; value?: string; onClick: () => void }) {
  return (
    <button type="button" className="set-row" onClick={onClick}>
      <span className={`set-icon tone-${tone}`} aria-hidden="true"><Icon name={icon} size={20} /></span>
      <span className="set-label">{label}</span>
      {value && <span className="set-value">{value}</span>}
      <span className="set-chev" aria-hidden="true"><Icon name="chevron" size={18} /></span>
    </button>
  )
}

export function MePage() {
  const { me, channels, botUsername, setAdminMode } = useAppData()
  const [screen, setScreen] = useState<Screen>(null)
  const { t, formatDate } = useI18n()
  const photo = getUserPhotoUrl()

  if (me.loading) return <Page><PageHeader title={t('me.title')} /><LoadingBlock rows={5} /></Page>
  if (!me.data) {
    return <Page><PageHeader title={t('me.title')} />
      {me.error && <ErrorState error={me.error} onRetry={me.reload} botUsername={botUsername} />}</Page>
  }
  const { user, plan, usage, posts } = me.data
  if (screen === 'plans') return <PlansScreen me={me.data} onBack={() => setScreen(null)} />
  if (screen === 'lang') return <LanguageScreen current={user.language} onBack={() => setScreen(null)} />
  if (screen === 'channels') return <ChannelsScreen onBack={() => setScreen(null)} />
  if (screen === 'look') return <AppearanceScreen onBack={() => setScreen(null)} />
  if (screen === 'team') return <TeamScreen onBack={() => setScreen(null)} />
  const notifications = me.data.settings?.notifications ?? NOTIFICATION_DEFAULTS
  if (screen === 'notif') return <NotificationsScreen current={notifications} onBack={() => setScreen(null)} />

  const refresh = () => { me.reload(); channels.reload() }
  const displayName = user.name || user.username || t('common.none')
  const planName = plan.type === 'ultra' ? t('plan.ultra') : plan.type === 'enterprise' ? t('plan.enterprise') : plan.is_pro ? t('plan.pro') : t('plan.free')
  const daysLeft = plan.is_pro && plan.expires_at ? Math.max(0, Math.ceil((new Date(plan.expires_at).getTime() - Date.now()) / 86400000)) : null
  const planValue = plan.is_pro
    ? `${planName} · ${plan.expires_at ? t('me.planLeft', { n: daysLeft ?? 0 }) : t('me.planNoExpiry')}`
    : t('me.planFree')
  return (
    <Page>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title={t('me.title')} onRefresh={refresh} refreshing={me.refreshing || channels.refreshing} />

      <section className={`me-cover tier-${plan.type}`} aria-labelledby="profile">
        <div className="me-cover-bg" aria-hidden="true" />
        <Avatar text={displayName} photo={photo} large />
        <h2 id="profile" className="me-name">{displayName}</h2>
        <p className="muted small me-sub">{user.username ? `@${user.username} · ` : ''}{t('me.id')} {user.id}</p>
        <div className="me-chips">
          <Badge pro={plan.is_pro}>{planName}</Badge>
          {plan.is_pro && plan.expires_at && <span className="chip">{t('me.expires', { date: formatDate(plan.expires_at) })}</span>}
        </div>
        <div className="me-stats">
          <div><strong>{usage.channels}</strong><span>{t('home.channels')}</span></div>
          <div><strong>{usage.pending_posts}</strong><span>{t('home.scheduled')}</span></div>
          <div><strong>{posts.sent}</strong><span>{t('home.sent')}</span></div>
        </div>
      </section>

      {me.data.is_admin && (
        <section className="set-group adm-switch" aria-label={t('adm.title')}>
          <Row icon="shield" tone="violet" label={t('adm.enter')} value={t('adm.enterHint')} onClick={() => setAdminMode(true)} />
        </section>
      )}

      <h3 className="sec-label">{t('me.secSettings')}</h3>
      <section className="set-group" aria-label={t('me.secSettings')}>
        <Row icon="diamond" tone="gold" label={t('me.rowPlan')} value={planValue} onClick={() => setScreen('plans')} />
        <Row icon="globe" tone="blue" label={t('me.rowLang')} value={`${FLAGS[user.language]} ${t(`lang.${user.language}`)}`} onClick={() => setScreen('lang')} />
        <Row icon="sparkle" tone="violet" label={t('me.rowLook')} onClick={() => setScreen('look')} />
        <Row icon="bell" tone="rose" label={t('me.rowNotif')} value={t('me.notifValue', { n: enabledCount(notifications), total: 4 })} onClick={() => setScreen('notif')} />
        <Row icon="user" tone="blue" label={t('me.rowTeam')} value={(plan.limits.team_seats ?? 0) > 0 ? t('team.seatsMax', { n: plan.limits.team_seats ?? 0 }) : undefined} onClick={() => setScreen('team')} />
        <Row icon="megaphone" tone="green" label={t('me.rowChannels')} value={String(usage.channels)} onClick={() => setScreen('channels')} />
      </section>

      <h3 className="sec-label">{t('me.limits')}</h3>
      <section className="card" aria-labelledby="plan">
        <div className="card-row">
          <h2 id="plan">{t('me.usage')}</h2>
          <span className="muted small">{plan.is_pro ? t('me.proActive') : t('me.plan')}</span>
        </div>
        <div className="meters">
          <Meter label={t('me.limitChannels')} used={usage.channels} max={plan.limits.max_channels} />
          <Meter label={t('me.limitAi')} used={usage.ai_requests_today} max={plan.limits.daily_ai_requests} />
          <Meter label={t('me.limitQueue')} used={usage.pending_posts} max={plan.limits.queued_posts} />
        </div>
      </section>

      <h3 className="sec-label">{t('me.secApp')}</h3>
      <section className="set-group" aria-label={t('me.secApp')}>
        {openBotAvailable(botUsername) && <Row icon="bot" tone="violet" label={t('me.rowBot')} onClick={() => openBot(botUsername, 'settings')} />}
        {openBotAvailable(botUsername) && <Row icon="gift" tone="gold" label={t('me.rowInvite')} onClick={() => openBot(botUsername, 'invite')} />}
        {openBotAvailable(botUsername) && <Row icon="help" tone="blue" label={t('me.rowHelp')} onClick={() => openBot(botUsername, 'help')} />}
        <Row icon="close" tone="gray" label={t('me.appClose')} onClick={closeApp} />
      </section>
      <p className="muted small">{t('me.appBotHint')}</p>
    </Page>
  )
}

/** Foydalanish ko'rsatkichi: ishlatilgan / limit + chiziq (cheksiz limitda chiziq yo'q, "∞"). */
export function Meter({ label, used, max }: { label: string; used: number; max: number }) {
  const unlimited = isUnlimited(max)
  const pct = unlimited || max <= 0 ? 0 : Math.min(100, Math.round((used / max) * 100))
  const level = pct >= 100 ? 'full' : pct >= 80 ? 'high' : 'ok'
  return (
    <div className="meter">
      <div className="meter-top"><span>{label}</span><strong>{used} / {unlimited ? '∞' : max}</strong></div>
      {!unlimited && (
        <div className="meter-bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.min(used, max)}>
          <span style={{ width: `${pct}%` }} data-level={level} />
        </div>
      )}
    </div>
  )
}
