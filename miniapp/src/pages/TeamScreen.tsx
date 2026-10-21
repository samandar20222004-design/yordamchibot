import { useMemo, useState } from 'react'
import { useAppData } from '../AppData'
import type { TeamChannel, TeamPerm, TeamPreset, Workspace } from '../api/types'
import { TEAM_PERMS, TEAM_PRESETS } from '../api/types'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Icon } from '../components/Icon'
import { SubPage } from '../components/SubPage'
import { Button, ErrorState, FormError, LoadingBlock, openBotAvailable } from '../components/ui'
import { useAdminAction } from './admin/AdminPages'
import { useI18n, type MessageKey } from '../i18n'
import { haptic, inviteLink, openBot, shareLink } from '../telegram'

const permLabel = (p: TeamPerm): MessageKey => `team.perm_${p}` as MessageKey
const permHint = (p: TeamPerm): MessageKey => `team.permHint_${p}` as MessageKey
const PRESET_ORDER: readonly TeamPreset[] = ['full', 'editor', 'scheduler', 'analyst', 'view']
const sameSet = (a: readonly TeamPerm[], b: readonly TeamPerm[]) => a.length === b.length && a.every((x) => b.includes(x))

/** Ruxsatlar: tayyor shablonlar (bir bosishda) + har bir ruxsat alohida katakcha. «Ko'rish» har doim bor. */
export function PermPicker({ value, onChange, disabled }: { value: TeamPerm[]; onChange: (next: TeamPerm[]) => void; disabled?: boolean }) {
  const { t } = useI18n()
  const toggle = (p: TeamPerm) => onChange(TEAM_PERMS.filter((x) => (x === p ? !value.includes(x) : value.includes(x))))
  return (
    <div className="perm-picker">
      <div className="chips" role="group" aria-label={t('team.presets')}>
        {PRESET_ORDER.map((id) => (
          <button key={id} type="button" className="chip" disabled={disabled} aria-pressed={sameSet(value, TEAM_PRESETS[id])}
            onClick={() => onChange([...TEAM_PRESETS[id]])}>{t(`team.preset_${id}` as MessageKey)}</button>
        ))}
      </div>
      <ul className="perm-list">
        <li className="perm-row perm-fixed"><Icon name="check" size={18} /><span><strong>{t('team.perm_view')}</strong><small>{t('team.permHint_view')}</small></span></li>
        {TEAM_PERMS.map((p) => (
          <li key={p}>
            <label className="perm-row">
              <input type="checkbox" checked={value.includes(p)} disabled={disabled} onChange={() => toggle(p)} />
              <span><strong>{t(permLabel(p))}</strong><small>{t(permHint(p))}</small></span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChannelPicker({ channels, value, onChange, disabled }: { channels: TeamChannel[]; value: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const { t } = useI18n()
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])
  return (
    <div className="chips" role="group" aria-label={t('team.inviteChannel')}>
      <button type="button" className="chip" disabled={disabled} aria-pressed={value.length === channels.length && channels.length > 0}
        onClick={() => onChange(value.length === channels.length ? [] : channels.map((c) => c.channel_id))}>{t('team.allChannels')}</button>
      {channels.map((c) => (
        <button key={c.channel_id} type="button" className="chip" disabled={disabled} aria-pressed={value.includes(c.channel_id)} onClick={() => toggle(c.channel_id)}>{c.title || c.channel_id}</button>
      ))}
    </div>
  )
}

// ----------------------------------------------------------------- «Men kimman?» (faqat shu ekranda, so'ralmaydi)
function ModePicker({ mode, isAdmin, onPick, busy }: {
  mode: 'owner' | 'helper' | null; isAdmin: boolean; onPick: (m: 'owner' | 'helper' | 'admin') => void; busy: boolean
}) {
  const { t } = useI18n()
  const options: Array<{ id: 'owner' | 'helper' | 'admin'; label: MessageKey; hint: MessageKey }> = [
    { id: 'owner', label: 'team.modeOwner', hint: 'team.modeOwnerHint' },
    { id: 'helper', label: 'team.modeHelper', hint: 'team.modeHelperHint' },
    ...(isAdmin ? [{ id: 'admin' as const, label: 'team.modeAdmin' as MessageKey, hint: 'team.modeAdminHint' as MessageKey }] : []),
  ]
  return (
    <div className="mode-list" role="radiogroup" aria-label={t('team.modeLabel')}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={mode === o.id} className="mode-card" disabled={busy} onClick={() => onPick(o.id)}>
          <strong>{t(o.label)}</strong>
          <span className="muted small">{t(o.hint)}</span>
        </button>
      ))}
    </div>
  )
}

// ----------------------------------------------------------------- Taklif yaratish
function InviteDialog({ channels, onClose, onCreated }: { channels: TeamChannel[]; onClose: () => void; onCreated: () => void }) {
  const { client, botUsername, notify } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [picked, setPicked] = useState<string[]>(() => channels.map((c) => c.channel_id))
  const [perms, setPerms] = useState<TeamPerm[]>([...TEAM_PRESETS.full])
  const [token, setToken] = useState<string | null>(null)
  const link = token ? inviteLink(botUsername, token) : null
  const create = async () => {
    let created: string | null = null
    const ok = await run(async () => { created = (await client.teamInviteCreate(picked, perms)).token })
    if (ok && created) { setToken(created); onCreated() }
  }
  const copy = async () => {
    if (!link) return
    try { await navigator.clipboard.writeText(link); notify(t('team.copied')); haptic('success') } catch { notify(link) }
  }
  return (
    <Dialog title={t('team.invite')} onClose={onClose} busy={busy}>
      {channels.length === 0 && <p className="muted">{t('team.noChannels')}</p>}
      {!token && channels.length > 0 && (
        <>
          <span className="field-label">{t('team.inviteChannel')}</span>
          <ChannelPicker channels={channels} value={picked} onChange={setPicked} disabled={busy} />
          <span className="field-label">{t('team.permsTitle')}</span>
          <PermPicker value={perms} onChange={setPerms} disabled={busy} />
          <p className="muted small">{t('team.limitsNote')}</p>
          {error && <FormError error={error} />}
          <div className="dialog-actions">
            <Button onClick={onClose} disabled={busy}>{t('common.back')}</Button>
            <Button variant="primary" busy={busy} disabled={picked.length === 0} onClick={() => void create()}>{t('team.inviteCreate')}</Button>
          </div>
        </>
      )}
      {token && (
        <>
          <p><strong>{t('team.inviteReady')}</strong></p>
          <code className="invite-link" dir="ltr">{link ?? '—'}</code>
          <p className="muted small">{t('team.inviteHint', { n: 7 })}</p>
          <div className="dialog-actions">
            <Button onClick={() => void copy()} disabled={!link}>{t('team.copy')}</Button>
            <Button variant="primary" disabled={!link} onClick={() => { if (link) shareLink(link, t('team.inviteHint', { n: 7 })) }}>{t('team.share')}</Button>
          </div>
        </>
      )}
    </Dialog>
  )
}

// ----------------------------------------------------------------- Egasi: yordamchi kartasi
interface Helper { user_id: number; name: string; username: string; active: boolean; channelIds: string[]; perms: TeamPerm[]; mixed: boolean }

function groupHelpers(channels: TeamChannel[]): Helper[] {
  const map = new Map<number, Helper>()
  for (const c of channels) {
    for (const m of c.members) {
      const h = map.get(m.user_id)
      if (!h) map.set(m.user_id, { user_id: m.user_id, name: m.name, username: m.username, active: m.active, channelIds: [c.channel_id], perms: m.perms, mixed: false })
      else { h.channelIds.push(c.channel_id); if (!sameSet(h.perms, m.perms)) h.mixed = true }
    }
  }
  return Array.from(map.values())
}

function HelperCard({ helper, channels, reload }: { helper: Helper; channels: TeamChannel[]; reload: () => void }) {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [picked, setPicked] = useState<string[]>(helper.channelIds)
  const [perms, setPerms] = useState<TeamPerm[]>(helper.perms)
  const [ask, setAsk] = useState(false)
  const name = helper.name || (helper.username ? `@${helper.username}` : String(helper.user_id))
  const dirty = !sameSet(perms, helper.perms) || picked.length !== helper.channelIds.length || picked.some((c) => !helper.channelIds.includes(c))
  return (
    <section className="card adm-card" aria-label={name}>
      <div className="adm-row">
        <span className="adm-row-main"><h2>{name}</h2><span className="muted small">{helper.user_id}</span></span>
        <Button icon="trash" disabled={busy} onClick={() => setAsk(true)} aria-label={t('team.remove')} />
      </div>
      {!helper.active && <p className="muted small">⏸ {t('team.inactive')}</p>}
      <span className="field-label">{t('team.inviteChannel')}</span>
      <ChannelPicker channels={channels} value={picked} onChange={setPicked} disabled={busy} />
      <span className="field-label">{t('team.permsTitle')}</span>
      {helper.mixed && <p className="muted small">{t('team.permsMixed')}</p>}
      <PermPicker value={perms} onChange={setPerms} disabled={busy} />
      {error && <FormError error={error} />}
      <Button variant="primary" block busy={busy} disabled={!dirty || picked.length === 0}
        onClick={() => { void run(() => client.teamHelperUpdate(helper.user_id, picked, perms), 'adm.saved').then((ok) => { if (ok) reload() }) }}>{t('adm.save')}</Button>
      {ask && (
        <ConfirmDialog title={t('team.remove')} body={t('team.removeAsk', { name })} confirmLabel={t('team.remove')} danger busy={busy} onClose={() => setAsk(false)}
          onConfirm={() => { void run(() => client.teamHelperUpdate(helper.user_id, [], []), 'adm.deleted').then((ok) => { if (ok) { setAsk(false); reload() } }) }} />
      )}
    </section>
  )
}

function OwnerTeam() {
  const { team, me, botUsername, client } = useAppData()
  const { t } = useI18n()
  const { busy, run } = useAdminAction()
  const [inviting, setInviting] = useState(false)
  const d = team.data
  const helpers = useMemo(() => groupHelpers(d?.channels ?? []), [d])
  if (!d) return null
  const seats = d.seats
  const ultraSeats = me.data?.tiers?.ultra.limits.team_seats ?? 2
  if (!d.can_invite) {
    return (
      <section className="card adm-card">
        <h2>{t('team.soloTitle')}</h2>
        <p className="muted">{t('team.soloBody', { h: ultraSeats, n: ultraSeats + 1 })}</p>
        {openBotAvailable(botUsername) && <Button variant="primary" block icon="diamond" onClick={() => openBot(botUsername, 'plans')}>{t('team.upgrade')}</Button>}
      </section>
    )
  }
  const pct = seats.limit > 0 ? Math.min(100, Math.round(((seats.used + seats.pending) / seats.limit) * 100)) : 0
  const pending = d.channels.flatMap((c) => c.invites.map((i) => ({ ...i, channel: c })))
  const seenInvite = new Set<number>()
  return (
    <>
      <section className="card adm-card">
        <div className="meter-top"><span>{t('team.seatsTitle')}</span><strong>{t('team.seatsOf', { used: seats.used, limit: seats.limit })}</strong></div>
        <div className="meter-bar" role="progressbar" aria-label={t('team.seatsTitle')} aria-valuemin={0} aria-valuemax={seats.limit} aria-valuenow={seats.used + seats.pending}>
          <span style={{ width: `${pct}%` }} data-level={pct >= 100 ? 'full' : 'ok'} />
        </div>
        <p className="muted small">{t('team.accounts', { n: seats.limit + 1, h: seats.limit })}{seats.pending > 0 ? ` · ${t('team.seatsPending', { n: seats.pending })}` : ''}</p>
        <p className="muted small">{t('team.limitsNote')}</p>
        <Button variant="primary" block icon="plus" onClick={() => setInviting(true)}>{t('team.invite')}</Button>
      </section>
      <h3 className="sec-label">{t('team.members')}</h3>
      {helpers.length === 0 && pending.length === 0 && <p className="muted small">{t('team.membersEmpty')}</p>}
      {helpers.map((h) => <HelperCard key={`${h.user_id}:${h.channelIds.join(',')}:${h.perms.join(',')}`} helper={h} channels={d.channels} reload={team.reload} />)}
      {pending.filter((i) => (seenInvite.has(i.id) ? false : (seenInvite.add(i.id), true))).map((i) => (
        <section key={`inv-${i.id}`} className="card adm-card">
          <div className="adm-row">
            <span className="adm-row-main"><strong className="adm-row-title">⏳ {t('team.pendingInvite')}</strong>
              <span className="muted small">{i.perms.length === 0 ? t('team.preset_view') : i.perms.map((p) => t(permLabel(p))).join(' · ')}</span></span>
            <Button disabled={busy} onClick={() => { void run(() => client.teamInviteRevoke(i.id), 'adm.deleted').then((ok) => { if (ok) team.reload() }) }}>{t('team.revoke')}</Button>
          </div>
        </section>
      ))}
      {inviting && <InviteDialog channels={d.channels} onClose={() => setInviting(false)} onCreated={team.reload} />}
    </>
  )
}

// ----------------------------------------------------------------- Yordamchi: ish joylari
function WorkspaceCard({ ws }: { ws: Workspace }) {
  const { client, team, workspace, setWorkspace } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [ask, setAsk] = useState(false)
  const active = workspace?.owner_id === ws.owner_id
  const name = ws.owner_name || String(ws.owner_id)
  return (
    <section className={`card adm-card${active ? ' ws-active' : ''}`} aria-label={name}>
      <h2>{name}</h2>
      {ws.suspended && <p className="muted small">⏸ {t('team.suspended')}</p>}
      <ul className="list">
        {ws.channels.map((c) => (
          <li key={c.channel_id} className="item team-member">
            <strong className="adm-row-title">{c.title || c.channel_id}</strong>
            <div className="chips">
              <span className="chip">{t('team.perm_view')}</span>
              {c.perms.map((p) => <span key={p} className="chip">{t(permLabel(p))}</span>)}
            </div>
          </li>
        ))}
      </ul>
      {error && <FormError error={error} />}
      <div className="dialog-actions">
        <Button disabled={busy} onClick={() => setAsk(true)}>{t('team.leave')}</Button>
        {!ws.suspended && (active
          ? <Button onClick={() => setWorkspace(null)}>{t('team.exit')}</Button>
          : <Button variant="primary" icon="send" onClick={() => { haptic('select'); setWorkspace(ws.owner_id) }}>{t('team.work')}</Button>)}
      </div>
      {active && <p className="muted small">{t('team.working')}. {t('team.limitedHint')}</p>}
      {ask && (
        <ConfirmDialog title={t('team.leave')} body={t('team.leaveAsk', { name })} confirmLabel={t('team.leave')} danger busy={busy}
          onClose={() => setAsk(false)}
          onConfirm={() => { void run(() => client.teamLeave(ws.owner_id)).then((ok) => { if (ok) { if (active) setWorkspace(null); setAsk(false); team.reload() } }) }} />
      )}
    </section>
  )
}

// ----------------------------------------------------------------- Ekran
export function TeamScreen({ onBack }: { onBack: () => void }) {
  const { client, me, team, botUsername, setAdminMode } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const d = team.data
  const mode = d?.mode ?? me.data?.work_mode ?? null
  const pick = async (m: 'owner' | 'helper' | 'admin') => {
    if (m === 'admin') { setAdminMode(true); return }
    if (m === mode) return
    const ok = await run(() => client.teamMode(m), 'adm.saved')
    if (ok) { team.reload(); me.reload() }
  }
  return (
    <SubPage title={t('team.title')} onBack={onBack}>
      {team.loading && <LoadingBlock rows={3} />}
      {!d && team.error && <ErrorState error={team.error} onRetry={team.reload} botUsername={botUsername} />}
      {d && (
        <>
          <h3 className="sec-label">{t('team.modeLabel')}</h3>
          <ModePicker mode={mode} isAdmin={me.data?.is_admin === true} onPick={(m) => void pick(m)} busy={busy} />
          {error && <FormError error={error} />}
          {(d.workspaces.length > 0 || mode === 'helper') && (
            <>
              <h3 className="sec-label"><Icon name="user" size={16} /> {t('team.workspaces')}</h3>
              {d.workspaces.length === 0 && <p className="muted small">{t('team.workspacesEmpty')}</p>}
              {d.workspaces.map((w) => <WorkspaceCard key={w.owner_id} ws={w} />)}
            </>
          )}
          {mode !== 'helper' && <OwnerTeam />}
          {mode === 'helper' && d.channels.length > 0 && <OwnerTeam />}
        </>
      )}
    </SubPage>
  )
}
