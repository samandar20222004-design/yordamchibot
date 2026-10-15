import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import type { Lang } from '../api/types'
import { Icon } from '../components/Icon'
import { SubPage } from '../components/SubPage'
import { errorMessageKey } from '../components/ui'
import { toClientError } from '../hooks/useResource'
import { translate, useI18n } from '../i18n'

const FLAGS: Record<Lang, string> = { uz: '🇺🇿', ru: '🇷🇺', en: '🇬🇧' }
const LANGS: readonly Lang[] = ['uz', 'ru', 'en']

/** Til tanlash: har bir til alohida katta qator (bayroq + o'z nomi + tanlangan belgisi); tanlansa darhol saqlanadi. */
export function LanguageScreen({ current, onBack }: { current: Lang; onBack: () => void }) {
  const { client, me, notify, setLang } = useAppData()
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)

  const choose = async (lang: Lang) => {
    if (inFlight.current || lang === current) return
    inFlight.current = true
    setBusy(true)
    try {
      await client.setLanguage(lang)
      setLang(lang)
      notify(translate(lang, 'me.languageSaved'))
      me.reload()
    } catch (e) {
      notify(t(errorMessageKey(toClientError(e).code)), 'error')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  return (
    <SubPage title={t('lang.title')} onBack={onBack}>
      <p className="muted">{t('me.languageHint')}</p>
      <div className="lang-cards" role="group" aria-label={t('me.languageChange')}>
        {LANGS.map((l) => (
          <button key={l} type="button" className="lang-card" aria-pressed={current === l} disabled={busy} onClick={() => void choose(l)}>
            <span className="lang-flag" aria-hidden="true">{FLAGS[l]}</span>
            <span className="lang-name">{t(`lang.${l}`)}</span>
            {current === l && <span className="lang-check"><Icon name="check" size={20} /></span>}
          </button>
        ))}
      </div>
    </SubPage>
  )
}
