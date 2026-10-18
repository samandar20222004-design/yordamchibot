import type { CSSProperties, ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { useI18n, type MessageKey } from '../i18n'
import { haptic } from '../telegram'
import { Icon, type IconName } from './Icon'
import { Button } from './ui'

export type Tab = 'home' | 'post' | 'schedule' | 'market' | 'me'

export const TABS: ReadonlyArray<{ id: Tab; icon: IconName; label: MessageKey }> = [
  { id: 'home', icon: 'home', label: 'tab.home' },
  { id: 'post', icon: 'post', label: 'tab.post' },
  { id: 'schedule', icon: 'calendar', label: 'tab.schedule' },
  { id: 'market', icon: 'market', label: 'tab.market' },
  { id: 'me', icon: 'user', label: 'tab.me' },
]

export function TabBar({ active, onChange }: { active: Tab; onChange: (tab: Tab) => void }) {
  const { t } = useI18n()
  const index = Math.max(0, TABS.findIndex((x) => x.id === active))
  return (
    <nav className="tabbar" aria-label={t('nav.label')} style={{ '--tab-i': index } as CSSProperties}>
      <span className="tab-pill" aria-hidden="true" />
      {TABS.map((tab) => (
        <button key={tab.id} type="button" className="tab"
          onClick={() => { if (tab.id !== active) haptic('select'); onChange(tab.id) }}
          aria-current={active === tab.id ? 'page' : undefined}>
          <Icon name={tab.icon} />
          <span>{t(tab.label)}</span>
          <span className="tab-dot" aria-hidden="true" />
        </button>
      ))}
    </nav>
  )
}

export function PageHeader({ title, onRefresh, refreshing }: { title: string; onRefresh?: () => void; refreshing?: boolean }) {
  const { t } = useI18n()
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {onRefresh && (
        <Button icon="refresh" busy={refreshing} onClick={onRefresh} aria-label={t('common.refresh')} title={t('common.refresh')} />
      )}
    </div>
  )
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine !== false)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])
  return online
}

export function OfflineBanner() {
  const { t } = useI18n()
  const online = useOnline()
  if (online) return null
  return <div className="banner banner-warn" role="status">{t('common.offline')}</div>
}

export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <main className={`page${wide ? ' page-wide' : ''}`}>{children}</main>
}
