import type { ReactNode } from 'react'
import { useI18n } from '../i18n'
import { Icon } from './Icon'
import { Page } from './Shell'

/** Ichki ekran (Tarif, Til, Kanallar): tepada «Orqaga» va sarlavha. */
export function SubPage({ title, onBack, children }: { title: string; onBack: () => void; children: ReactNode }) {
  const { t } = useI18n()
  return (
    <Page>
      <div className="subpage-head">
        <button type="button" className="back-btn" onClick={onBack} aria-label={t('common.back')}>
          <Icon name="back" size={22} />
        </button>
        <h1>{title}</h1>
      </div>
      {children}
    </Page>
  )
}
