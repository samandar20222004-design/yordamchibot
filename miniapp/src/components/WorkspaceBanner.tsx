import { useAppData } from '../AppData'
import { useI18n, type MessageKey } from '../i18n'
import { Icon } from './Icon'

/** Yordamchi boshqa egasining ish joyida ishlayotganda har sahifada ko'rinadigan yo'l-yo'riq qatori. */
export function WorkspaceBanner() {
  const { workspace, setWorkspace } = useAppData()
  const { t } = useI18n()
  if (!workspace) return null
  const roles = Array.from(new Set(workspace.channels.map((c) => c.role)))
  return (
    <div className="ws-banner" role="status">
      <Icon name="user" size={16} />
      <span className="ws-banner-text">
        <strong>{t('team.banner', { name: workspace.owner_name || String(workspace.owner_id) })}</strong>
        <span className="muted small">{roles.map((r) => t(`team.role_${r}` as MessageKey)).join(' · ')}</span>
      </span>
      <button type="button" className="ws-banner-exit" onClick={() => setWorkspace(null)}>{t('team.exit')}</button>
    </div>
  )
}
