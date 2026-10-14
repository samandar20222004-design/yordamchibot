import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { Lang } from '../api/types'
import { Page, PageHeader } from '../components/Shell'
import { Badge, Button, ErrorState, InlineWarning, LoadingBlock, errorMessageKey, openBotAvailable } from '../components/ui'
import { toClientError } from '../hooks/useResource'
import { translate, useI18n } from '../i18n'
import { openBot } from '../telegram'
import { isUnlimited } from './format'

export function MePage() {
  const { me, channels, client, botUsername, notify, setLang } = useAppData()
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
  const { user, plan } = me.data
  const limit = (n: number) => (isUnlimited(n) ? t('common.unlimited') : String(n))
  const refresh = () => { me.reload(); channels.reload() }
  return (
    <Page>
      {me.error && <InlineWarning error={me.error} onRetry={me.reload} />}
      <PageHeader title={t('me.title')} onRefresh={refresh} refreshing={me.refreshing || channels.refreshing} />

      <section className="card" aria-labelledby="profile">
        <h2 id="profile">{t('me.profile')}</h2>
        <dl className="kv">
          <dt>{t('me.name')}</dt><dd>{user.name || t('common.none')}</dd>
          <dt>{t('me.username')}</dt><dd>{user.username ? `@${user.username}` : t('common.none')}</dd>
          <dt>{t('me.id')}</dt><dd>{user.id}</dd>
        </dl>
        <div className="segmented" role="group" aria-label={t('me.languageChange')}>
          {(['uz', 'ru', 'en'] as const).map((l) => (
            <button key={l} type="button" aria-pressed={user.language === l} disabled={langBusy}
              onClick={() => void changeLang(l)}>{t(`lang.${l}`)}</button>
          ))}
        </div>
        <p className="muted">{t('me.languageHint')}</p>
      </section>

      <section className="card" aria-labelledby="plan">
        <div className="card-row">
          <h2 id="plan">{t('me.plan')}</h2>
          <Badge pro={plan.is_pro}>{plan.is_pro ? t('plan.pro') : t('plan.free')}</Badge>
        </div>
        {plan.is_pro && <p>{t('me.proActive')}</p>}
        {plan.is_pro && plan.expires_at && <p className="muted">{t('me.expires', { date: formatDate(plan.expires_at) })}</p>}
        <h3 className="muted">{t('me.limits')}</h3>
        <dl className="kv">
          <dt>{t('me.limitChannels')}</dt><dd>{limit(plan.limits.max_channels)}</dd>
          <dt>{t('me.limitAi')}</dt><dd>{limit(plan.limits.daily_ai_requests)}</dd>
          <dt>{t('me.limitQueue')}</dt><dd>{limit(plan.limits.queued_posts)}</dd>
        </dl>
        {!plan.is_pro && (
          <>
            <h3>{t('me.proTitle')}</h3>
            <p className="lead">{t('me.proBody')}</p>
            {openBotAvailable(botUsername) && (
              <Button variant="primary" block icon="bot" onClick={() => openBot(botUsername)}>{t('common.openBot')}</Button>
            )}
          </>
        )}
      </section>

      <section className="card" aria-labelledby="channels">
        <h2 id="channels">{t('me.channels')}</h2>
        {channels.loading && <LoadingBlock rows={2} />}
        {!channels.data && channels.error && <ErrorState error={channels.error} onRetry={channels.reload} botUsername={botUsername} />}
        {channels.data && channels.data.items.length === 0 && <p className="muted">{t('me.channelsEmpty')}</p>}
        {channels.data && channels.data.items.length > 0 && (
          <ul className="list">
            {channels.data.items.map((c) => (
              <li key={c.id} className="item"><span>{c.title || c.id}</span></li>
            ))}
          </ul>
        )}
      </section>
    </Page>
  )
}
