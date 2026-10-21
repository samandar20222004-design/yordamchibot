import { useAppData } from '../AppData'
import { useI18n, type MessageKey } from '../i18n'
import { Icon } from './Icon'

/** Yordamchi boshqa egasining ish joyida ishlayotganda har sahifada ko'rinadigan yo'l-yo'riq qatori. */
export function WorkspaceBanner() {
  const { workspace, setWorkspace } = useAppData()
  const { t } = useI18n()
  if (!workspace) return null
  const perms = Array.from(new Set(workspace.channels.flatMap((c) => c.perms)))
  return (
    <div className="ws-banner" role="status">
      <Icon name="user" size={16} />
      <span className="ws-banner-text">
        <strong>{t('team.banner', { name: workspace.owner_name || String(workspace.owner_id) })}</strong>
        <span className="muted small">{perms.length === 0 ? t('team.preset_view') : perms.map((p) => t(`team.perm_${p}` as MessageKey)).join(' · ')}</span>
      </span>
      <button type="button" className="ws-banner-exit" onClick={() => setWorkspace(null)}>{t('team.exit')}</button>
    </div>
  )
}
