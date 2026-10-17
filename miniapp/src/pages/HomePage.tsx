import { useEffect, useState } from 'react'
import { useAppData } from '../AppData'
import { BrandMark } from '../components/BrandMark'
import { Icon, type IconName } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, CountUp, EmptyState, ErrorState, InlineWarning, LoadingBlock, openBotAvailable } from '../components/ui'
import { useI18n, type MessageKey } from '../i18n'
import { haptic, openBot, type BotSection } from '../telegram'
import { isUnlimited } from './format'
import { countdownTo, greetingKey, tipIndex, type Countdown } from './homeUtils'

/** Har daqiqada yangilanadigan hozirgi vaqt (keyingi postgacha sanoq uchun). */
function useNow(intervalMs = 30000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function Bar({ used, max }: { used: number; max: number }) {
  if (isUnlimited(max) || max <= 0) return null
  const pct = Math.min(100, Math.round((used / max) * 100))
  return (
    <div className="stat-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} data-level={pct >= 100 ? 'full' : pct >= 80 ? 'high' : 'ok'} /></div>
  )
}

/** Botdagi bo'limlar: har biri `?start=go_<bo'lim>` bilan botning aynan shu ekranini ochadi (uzilish yo'q). */
const BOT_TOOLS: ReadonlyArray<{ section: BotSection; icon: IconName; tone: string; label: MessageKey; sub: MessageKey }> = [
  { section: 'channels', icon: 'megaphone', tone: 'green', label: 'home.toolChannels', sub: 'home.toolChannelsSub' },
  { section: 'invite', icon: 'gift', tone: 'rose', label: 'home.toolInvite', sub: 'home.toolInviteSub' },
  { section: 'plans', icon: 'diamond', tone: 'gold', label: 'home.toolPlans', sub: 'home.toolPlansSub' },
]

export function HomePage() {
  const { me, draft, go, botUsername } = useAppData()
  const { t, formatDateTime } = useI18n()
  const now = useNow()

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
  const planName = plan.type === 'ultra' ? t('plan.ultra') : plan.type === 'enterprise' ? t('plan.enterprise') : plan.is_pro ? t('plan.pro') : t('plan.free')
  const cdText = (c: Countdown): string => (c.key === 'cd.hourMin'
    ? t(c.key, { h: c.h, m: c.m }) : 'n' in c ? t(c.key, { n: c.n }) : t(c.key))
  const next = nextAt ? new Date(nextAt) : null
  const countdown = next ? cdText(countdownTo(next, now)) : null
  const tip = tipIndex(now) + 1
  const steps: Array<{ done: boolean; label: string; icon: IconName }> = [
    { done: usage.channels > 0, label: t('home.step1'), icon: 'bot' },
    { done: posts.sent + usage.pending_posts > 0, label: t('home.step2'), icon: 'post' },
    { done: usage.pending_posts > 0 || posts.sent > 0, label: t('home.step3'), icon: 'clock' },
  ]
  const tiles: Array<{ icon: IconName; label: MessageKey; to: 'post' | 'schedule' | 'me'; tone: string; primary?: boolean }> = [
    { icon: 'post', label: 'home.goPost', to: 'post', tone: 'violet', primary: true },
    { icon: 'calendar', label: 'home.goSchedule', to: 'schedule', tone: 'blue' },
    { icon: 'user', label: 'home.goMe', to: 'me', tone: 'gold' },
  ]
  const canOpenBot = openBotAvailable(botUsername)
  const goTab = (to: 'post' | 'schedule' | 'me') => { haptic('select'); go(to) }
  return (
    <Page wide>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title="PostAssist" onRefresh={me.reload} refreshing={me.refreshing} />

      <section aria-labelledby="hello" className="card hero hero-wow">
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-orbs" aria-hidden="true"><i /><i /><i /></div>
        <div className="hero-top">
          <div className="hero-text">
            <p className="hero-kicker">{t(greetingKey(now.getHours()))}</p>
            <h2 id="hello">{user.name ? t('home.hello', { name: user.name }) : t('home.helloAnon')}</h2>
            <p className="lead">{t('home.subtitle')}</p>
          </div>
          <div className="hero-mark" aria-hidden="true"><BrandMark /></div>
        </div>
        <div className="hero-chips">
          <Badge pro={plan.is_pro}>{planName}</Badge>
          <span className="chip chip-glass">{t('home.heroChannels', { n: usage.channels })}</span>
        </div>
        <Button variant="primary" block icon="sparkle" className="hero-cta" onClick={() => goTab('post')}>{t('home.ctaNew')}</Button>
      </section>

      {draft.data?.draft && (
        <section className="card cta-card" aria-labelledby="draft-cta">
          <h2 id="draft-cta">{t('home.draftTitle')}</h2>
          <p className="muted">{t('home.draftBody')}</p>
          <Button variant="primary" icon="send" block onClick={() => goTab('post')}>{t('home.draftOpen')}</Button>
        </section>
      )}

      <section className="card next-card" aria-labelledby="next-title">
        <span className="next-icon" aria-hidden="true"><Icon name="clock" size={26} /></span>
        <div className="next-body">
          <h2 id="next-title" className="next-title">{t('home.nextTitle')}</h2>
          {next && countdown ? (
            <>
              <p className="next-when">{countdown}</p>
              <p className="muted small">{formatDateTime(nextAt!)}</p>
            </>
          ) : (
            <>
              <p className="muted">{t('home.nextEmpty')}</p>
              <Button variant="secondary" icon="plus" onClick={() => goTab('post')}>{t('home.nextCta')}</Button>
            </>
          )}
        </div>
      </section>

      <div className="stats stats-wow">
        <div className="stat tone-stat-green"><span className="stat-ico" aria-hidden="true"><Icon name="megaphone" size={18} /></span>
          <span className="stat-label">{t('home.channels')}</span>
          <span className="stat-value"><CountUp value={usage.channels} /></span></div>
        <div className="stat tone-stat-blue"><span className="stat-ico" aria-hidden="true"><Icon name="calendar" size={18} /></span>
          <span className="stat-label">{t('home.scheduled')}</span>
          <span className="stat-value"><CountUp value={usage.pending_posts} /> / {limit(plan.limits.queued_posts)}</span>
          <Bar used={usage.pending_posts} max={plan.limits.queued_posts} /></div>
        <div className="stat tone-stat-violet"><span className="stat-ico" aria-hidden="true"><Icon name="send" size={18} /></span>
          <span className="stat-label">{t('home.sent')}</span>
          <span className="stat-value"><CountUp value={posts.sent} /></span></div>
        <div className="stat tone-stat-rose"><span className="stat-ico" aria-hidden="true"><Icon name="close" size={18} /></span>
          <span className="stat-label">{t('home.failed')}</span>
          <span className="stat-value"><CountUp value={posts.failed} /></span></div>
        <div className="stat stat-wide tone-stat-gold"><span className="stat-ico" aria-hidden="true"><Icon name="sparkle" size={18} /></span>
          <span className="stat-label">{t('home.ai')}</span>
          <span className="stat-value"><CountUp value={usage.ai_requests_today} /> / {limit(plan.limits.daily_ai_requests)}</span>
          <Bar used={usage.ai_requests_today} max={plan.limits.daily_ai_requests} /></div>
      </div>

      {posts.sent > 0 && <p className="achievement" role="status">{t('home.sentCount', { n: posts.sent })}</p>}

      {usage.channels === 0 && (
        <section className="card steps-card" aria-labelledby="steps-title">
          <h2 id="steps-title">{t('home.stepsTitle')}</h2>
          <ol className="steps">
            {steps.map((s, i) => (
              <li key={s.label} className={s.done ? 'done' : undefined}>
                <span className="step-dot" aria-hidden="true">{s.done ? <Icon name="check" size={16} /> : i + 1}</span>
                <span>{s.label}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
      {usage.channels === 0 && (
        <EmptyState title={t('home.noChannelsTitle')} body={t('home.noChannelsBody')}
          action={canOpenBot
            ? <Button variant="primary" icon="plus" onClick={() => openBot(botUsername, 'channels')}>{t('home.addChannel')}</Button>
            : undefined} />
      )}

      <section aria-labelledby="actions">
        <h2 id="actions" className="group-title">{t('home.actions')}</h2>
        <div className="tiles">
          {tiles.map((x) => (
            <button key={x.to} type="button" className={`tile${x.primary ? ' tile-primary' : ''}`} onClick={() => goTab(x.to)}>
              <span className={`tile-ico tone-${x.tone}`} aria-hidden="true"><Icon name={x.icon} size={22} /></span>{t(x.label)}
            </button>
          ))}
        </div>
      </section>

      {canOpenBot && (
        <section aria-labelledby="bot-tools">
          <h2 id="bot-tools" className="group-title">{t('home.botTools')}</h2>
          <p className="muted small tools-hint">{t('home.botToolsHint')}</p>
          <div className="bot-tools">
            {BOT_TOOLS.map((x) => (
              <button key={x.section} type="button" className="bot-tool" onClick={() => openBot(botUsername, x.section)}>
                <span className={`set-icon tone-${x.tone}`} aria-hidden="true"><Icon name={x.icon} size={20} /></span>
                <span className="bot-tool-text"><strong>{t(x.label)}</strong><span>{t(x.sub)}</span></span>
                <span className="bot-tool-go" aria-hidden="true"><Icon name="chevron" size={16} /></span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card tip-card" aria-labelledby="tip-title">
        <h2 id="tip-title"><Icon name="sparkle" size={18} /> {t('home.tipTitle')}</h2>
        <p>{t(`home.tip${tip}` as MessageKey)}</p>
      </section>
    </Page>
  )
}
