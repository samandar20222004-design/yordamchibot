import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { Lang, TierInfo } from '../api/types'
import { Icon } from '../components/Icon'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, ErrorState, InlineWarning, LoadingBlock, errorMessageKey, openBotAvailable } from '../components/ui'
import { toClientError } from '../hooks/useResource'
import { translate, useI18n } from '../i18n'
import { openBot } from '../telegram'
import { isUnlimited } from './format'
import { ChannelStatsView } from './StatsPage'

export function MePage() {
  const { me, channels, client, botUsername, notify, setLang } = useAppData()
  const [statsFor, setStatsFor] = useState<{ id: string; title: string } | null>(null)
  const { t, formatDate } = useI18n()
  const [langBusy, setLangBusy] = useState(false)
  const langInFlight = useRef(false)

  const changeLang = async (lang: Lang) => {
    if (langInFlight.current || lang === me.data?.user.language) return
    langInFlight.current = true
    setLangBusy(true)
    try {
      await client.setLanguage(lang)
      setLang(lang)
      notify(translate(lang, 'me.languageSaved'))
      me.reload()
    } catch (e) {
      notify(t(errorMessageKey(toClientError(e).code)), 'error')
    } finally {
      langInFlight.current = false
      setLangBusy(false)
    }
  }

  if (me.loading) return <Page><PageHeader title={t('me.title')} /><LoadingBlock rows={5} /></Page>
  if (!me.data) {
    return <Page><PageHeader title={t('me.title')} />
      {me.error && <ErrorState error={me.error} onRetry={me.reload} botUsername={botUsername} />}</Page>
  }
  const { user, plan, usage } = me.data
  const refresh = () => { me.reload(); channels.reload() }
  if (statsFor) return <ChannelStatsView channelId={statsFor.id} title={statsFor.title} onBack={() => setStatsFor(null)} />
  const displayName = user.name || user.username || t('common.none')
  const planName = plan.type === 'ultra' ? t('plan.ultra') : plan.type === 'enterprise' ? t('plan.enterprise') : plan.is_pro ? t('plan.pro') : t('plan.free')
  // Tarif kartalari faqat HOZIRGIDAN YUQORI tariflar uchun: Free -> PRO va ULTRA, PRO -> ULTRA.
  const upgrades = plan.type === 'ultra' || plan.type === 'enterprise' || !me.data.tiers ? []
    : plan.is_pro ? [['ultra', me.data.tiers.ultra] as const] : [['pro', me.data.tiers.pro] as const, ['ultra', me.data.tiers.ultra] as const]
  return (
    <Page>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title={t('me.title')} onRefresh={refresh} refreshing={me.refreshing || channels.refreshing} />

      <section className="card me-hero" aria-labelledby="profile">
        <Avatar text={displayName} />
        <div className="me-id">
          <h2 id="profile" className="me-name">{displayName}</h2>
          <p className="muted small">{user.username ? `@${user.username} · ` : ''}{t('me.id')} {user.id}</p>
        </div>
        <Badge pro={plan.is_pro}>{planName}</Badge>
      </section>

      <section className="card" aria-labelledby="plan">
        <div className="card-row">
          <h2 id="plan">{t('me.usage')}</h2>
          <span className="muted small">{plan.is_pro ? t('me.proActive') : t('me.plan')}</span>
        </div>
        {plan.is_pro && plan.expires_at && <p className="muted small">{t('me.expires', { date: formatDate(plan.expires_at) })}</p>}
        <div className="meters">
          <Meter label={t('me.limitChannels')} used={usage.channels} max={plan.limits.max_channels} />
          <Meter label={t('me.limitAi')} used={usage.ai_requests_today} max={plan.limits.daily_ai_requests} />
          <Meter label={t('me.limitQueue')} used={usage.pending_posts} max={plan.limits.queued_posts} />
        </div>
        {upgrades.length > 0 && (
          <div className="perks">
            <h3>{t('me.tiersTitle')}</h3>
            <div className="tiers">
              {upgrades.map(([key, info]) => <TierCard key={key} name={key === 'ultra' ? t('plan.ultra') : t('plan.pro')} info={info} />)}
            </div>
            <p className="muted small">{t('me.tierBuy')}</p>
            {openBotAvailable(botUsername) && (
              <Button variant="primary" block icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
            )}
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="settings">
        <h2 id="settings">{t('me.settings')}</h2>
        <div className="segmented" role="group" aria-label={t('me.languageChange')}>
          {(['uz', 'ru', 'en'] as const).map((l) => (
            <button key={l} type="button" aria-pressed={user.language === l} disabled={langBusy}
              onClick={() => void changeLang(l)}>{t(`lang.${l}`)}</button>
          ))}
        </div>
        <p className="muted small">{t('me.languageHint')}</p>
      </section>

      <section className="card" aria-labelledby="channels">
        <div className="card-row">
          <h2 id="channels">{t('me.channels')}</h2>
          {channels.data && <span className="muted small">{channels.data.items.length}</span>}
        </div>
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
    </Page>
  )
}

/** Ism/kanal nomining birinchi harfi (emoji va murakkab belgilar ham butun belgi sifatida olinadi). */
export function initialOf(text: string): string {
  const first = Array.from(text.trim())[0]
  return first ? first.toLocaleUpperCase() : '?'
}

function TierCard({ name, info }: { name: string; info: TierInfo }) {
  const { t } = useI18n()
  const price = String(info.price_from_uzs).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')
  const lines = [
    t('me.tierChannels', { n: info.limits.max_channels }),
    t('me.tierAi', { n: info.limits.daily_ai_requests }),
    t('me.tierQueue', { n: info.limits.queued_posts }),
    ...(info.limits.voice_daily ? [t('me.tierVoice', { n: info.limits.voice_daily })] : []),
  ]
  return (
    <div className="tier-card">
      <div className="card-row">
        <h4 className="tier-name">{name}</h4>
        <span className="muted small tier-price">{t('me.tierFrom', { price })}</span>
      </div>
      <ul className="perk-list">
        {lines.map((l) => <li key={l}><Icon name="check" size={18} /> <span>{l}</span></li>)}
      </ul>
    </div>
  )
}

function Avatar({ text, small = false }: { text: string; small?: boolean }) {
  return <span className={`avatar${small ? ' avatar-sm' : ''}`} aria-hidden="true">{initialOf(text)}</span>
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
