import { useState } from 'react'
import { useAppData } from '../AppData'
import type { Me, TierInfo, TierPeriod } from '../api/types'
import { Icon } from '../components/Icon'
import { SubPage } from '../components/SubPage'
import { Button, openBotAvailable } from '../components/ui'
import { useI18n, type MessageKey } from '../i18n'
import { openBot } from '../telegram'

const PERIOD_KEYS: Record<number, MessageKey> = { 1: 'plans.p1', 3: 'plans.p3', 6: 'plans.p6', 12: 'plans.p12' }
const money = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

type TierId = 'free' | 'pro' | 'ultra'
type Region = 'uz' | 'intl'
const usd = (n: number) => `$${n.toFixed(2)}`

/** Tariflar: davr tanlanadi (1 oy / 3 oy / 6 oy / 1 yil), kartalarda narx, Stars, tejam va haqiqiy limitlar. To'lov faqat botda. */
export function PlansScreen({ me, onBack }: { me: Me; onBack: () => void }) {
  const { botUsername } = useAppData()
  const { t, formatDate } = useI18n()
  const tiers = me.tiers
  const periodsAvail = tiers?.pro.periods ?? []
  const [months, setMonths] = useState<number>(periodsAvail.find((p) => p.months === 1)?.months ?? periodsAvail[0]?.months ?? 1)
  // Narx mintaqasi: serverdan (saqlangan tanlov yoki til); bu yerda faqat ko'rinish almashtiriladi (to'lov botda).
  const [region, setRegion] = useState<Region>(me.pay_region ?? 'intl')
  const currentType = me.plan.type === 'ultra' ? 'ultra' : me.plan.type === 'enterprise' ? 'enterprise' : me.plan.is_pro ? 'pro' : 'free'

  const order: TierId[] = ['free', 'pro', 'ultra']
  const nameOf = (id: TierId) => t(id === 'ultra' ? 'plan.ultra' : id === 'pro' ? 'plan.pro' : 'plan.free')

  const card = (id: TierId) => {
    const info: TierInfo | undefined = tiers?.[id]
    const limits = id === 'free' ? (info?.limits ?? me.plan.limits) : info?.limits
    if (!limits) return null
    const period: TierPeriod | undefined = info?.periods.find((p) => p.months === months)
    const isCurrent = currentType === id
    const lines = [
      t('me.tierChannels', { n: limits.max_channels }),
      t('me.tierAi', { n: limits.daily_ai_requests }),
      t('me.tierQueue', { n: limits.queued_posts }),
      ...(limits.voice_daily ? [t('me.tierVoice', { n: limits.voice_daily })] : []),
      ...(id === 'ultra' && (limits.team_seats ?? 0) > 0 ? [t('me.tierTeam', { n: limits.team_seats ?? 0, total: (limits.team_seats ?? 0) + 1 })] : []),
      ...(id === 'pro' ? [t('me.tierSolo')] : []),
    ]
    return (
      <article key={id} className={`plan-card plan-${id}${isCurrent ? ' is-current' : ''}`} aria-label={nameOf(id)}>
        <div className="plan-top">
          <h2 className="plan-name">{nameOf(id)}</h2>
          {isCurrent && <span className="chip plan-current">{t('plans.current')}</span>}
          {!isCurrent && id === 'ultra' && period && period.save_pct > 0 && <span className="chip plan-best">{t('plans.best')}</span>}
        </div>
        {id === 'free' ? (
          <p className="plan-price"><strong>{t('plans.price', { price: '0' })}</strong> <span className="muted">{t('plans.freeLine')}</span></p>
        ) : period ? (
          <div className="plan-price">
            <strong>{region === 'intl' ? usd(period.usd) : t('plans.price', { price: money(period.uzs) })}</strong>
            {period.months > 1 && (
              <span className="muted"> {region === 'intl'
                ? t('plans.perMonthUsd', { price: usd(period.usd / period.months) })
                : t('plans.perMonth', { price: money(Math.round(period.uzs / period.months)) })}</span>
            )}
            {id === 'ultra' && (limits.team_seats ?? 0) > 0 && (
              <div className="muted small">{t('plans.perAccount', { price: region === 'intl' ? usd(period.usd / period.months / ((limits.team_seats ?? 0) + 1)) : t('plans.price', { price: money(Math.round(period.uzs / period.months / ((limits.team_seats ?? 0) + 1))) }) })}</div>
            )}
            <div className="plan-sub">
              {region === 'intl' && <span className="chip">{t('plans.stars', { n: period.stars })}</span>}
              {period.save_pct > 0 && <span className="chip chip-save">{t('plans.save', { n: period.save_pct })}</span>}
            </div>
          </div>
        ) : null}
        <ul className="perk-list">
          {lines.map((l) => <li key={l}><Icon name="check" size={18} /> <span>{l}</span></li>)}
        </ul>
        {id !== 'free' && !isCurrent && openBotAvailable(botUsername) && (
          <Button variant="primary" block icon="bot" onClick={() => openBot(botUsername, 'plans')}>{t('plans.buy')}</Button>
        )}
        {isCurrent && id !== 'free' && me.plan.expires_at && <p className="muted small">{t('me.expires', { date: formatDate(me.plan.expires_at) })}</p>}
      </article>
    )
  }

  return (
    <SubPage title={t('plans.title')} onBack={onBack}>
      <p className="muted">{t('plans.lead')}</p>
      {me.pay_region === 'uz' && (
        <div className="period-tabs" role="group" aria-label={t('plans.regionLabel')}>
          {(['uz', 'intl'] as const).map((r) => (
            <button key={r} type="button" aria-pressed={region === r} onClick={() => setRegion(r)}>
              <span>{t(r === 'uz' ? 'plans.regionUz' : 'plans.regionIntl')}</span>
            </button>
          ))}
        </div>
      )}
      <p className="muted small">{t(region === 'uz' ? 'plans.regionNoteUz' : 'plans.regionNoteIntl')}</p>
      {periodsAvail.length > 0 && (
        <div className="period-tabs" role="group" aria-label={t('plans.periodLabel')}>
          {periodsAvail.map((p) => (
            <button key={p.months} type="button" aria-pressed={months === p.months} onClick={() => setMonths(p.months)}>
              <span>{t(PERIOD_KEYS[p.months] ?? 'plans.p1')}</span>
              {p.save_pct > 0 && <small>{t('plans.save', { n: p.save_pct })}</small>}
            </button>
          ))}
        </div>
      )}
      <div className="plan-list">{order.map(card)}</div>
      <p className="muted small">{t('me.tierBuy')}</p>
    </SubPage>
  )
}
