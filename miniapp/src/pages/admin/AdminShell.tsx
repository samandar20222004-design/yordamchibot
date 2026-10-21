import { useState } from 'react'
import { useAppData } from '../../AppData'
import { Icon, type IconName } from '../../components/Icon'
import { OfflineBanner } from '../../components/Shell'
import { useI18n, type MessageKey } from '../../i18n'
import { haptic } from '../../telegram'
import { AdminToolsPage } from './AdminTools'
import { AdminAdsPage, AdminMarketPage, AdminOverviewPage, AdminSponsorsPage } from './AdminPages'

type AdminTab = 'overview' | 'ads' | 'subs' | 'market' | 'tools'

const ADMIN_TABS: ReadonlyArray<{ id: AdminTab; icon: IconName; label: MessageKey }> = [
  { id: 'overview', icon: 'shield', label: 'adm.tabOverview' },
  { id: 'ads', icon: 'megaphone', label: 'adm.tabAds' },
  { id: 'subs', icon: 'bell', label: 'adm.tabSubs' },
  { id: 'market', icon: 'market', label: 'adm.tabMarket' },
  { id: 'tools', icon: 'sparkle', label: 'adm.tabTools' },
]

/** Super admin rejimi: o'z pastki paneli (4 bo'lim + «Oddiy» — oddiy Mini App'ga qaytish). */
export function AdminShell() {
  const { setAdminMode } = useAppData()
  const { t } = useI18n()
  const [tab, setTab] = useState<AdminTab>('overview')
  const count = ADMIN_TABS.length + 1
  return (
    <div className="shell shell-admin">
      <OfflineBanner />
      <div className="adm-banner" role="status"><Icon name="shield" size={16} /> {t('adm.modeBanner')}</div>
      {tab === 'overview' && <AdminOverviewPage />}
      {tab === 'ads' && <AdminAdsPage />}
      {tab === 'subs' && <AdminSponsorsPage />}
      {tab === 'market' && <AdminMarketPage />}
      {tab === 'tools' && <AdminToolsPage />}
      <nav className="tabbar tabbar-admin" aria-label={t('adm.navLabel')}
        style={{ '--tab-i': ADMIN_TABS.findIndex((x) => x.id === tab), '--tab-n': count, gridTemplateColumns: `repeat(${count}, 1fr)` } as React.CSSProperties}>
        <span className="tab-pill" aria-hidden="true" />
        {ADMIN_TABS.map((item) => (
          <button key={item.id} type="button" className="tab" aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => { if (item.id !== tab) haptic('select'); setTab(item.id) }}>
            <span className="tab-ico"><Icon name={item.icon} /></span>
            <span>{t(item.label)}</span>
            <span className="tab-dot" aria-hidden="true" />
          </button>
        ))}
        <button type="button" className="tab tab-exit" onClick={() => { haptic('select'); setAdminMode(false) }}>
          <span className="tab-ico"><Icon name="swap" /></span>
          <span>{t('adm.tabExit')}</span>
        </button>
      </nav>
    </div>
  )
}
