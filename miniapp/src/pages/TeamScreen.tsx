import { useState } from 'react'
import { useAppData } from '../AppData'
import type { TeamChannel, TeamMember, TeamRole, Workspace } from '../api/types'
import { TEAM_ROLES } from '../api/types'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Icon } from '../components/Icon'
import { SubPage } from '../components/SubPage'
import { Button, FormError, LoadingBlock, ErrorState, openBotAvailable } from '../components/ui'
import { useAdminAction } from './admin/AdminPages'
import { useI18n, type MessageKey } from '../i18n'
import { haptic, inviteLink, openBot, shareLink } from '../telegram'

const roleLabel = (r: TeamRole): MessageKey => `team.role_${r}` as MessageKey
const roleHelp = (r: TeamRole): MessageKey => `team.roleHelp_${r}` as MessageKey

function RoleChips({ value, onPick, disabled }: { value: TeamRole | null; onPick: (r: TeamRole) => void; disabled?: boolean }) {
  const { t } = useI18n()
  return (
    <div className="chips" role="group" aria-label={t('team.roleLabel')}>
      {TEAM_ROLES.map((r) => (
        <button key={r} type="button" className="chip" aria-pressed={value === r} disabled={disabled} onClick={() => onPick(r)}>{t(roleLabel(r))}</button>
      ))}
    </div>
  )
}

// ----------------------------------------------------------------- «Men kimman?»
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

/** Birinchi ochilishdagi qisqa «Men kimman?» oynasi (bir marta; keyin Men → Jamoa va rol). */
export function RoleWelcome({ onDone }: { onDone: (mode: 'owner' | 'helper' | null) => void }) {
  const { client, me } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const pick = async (m: 'owner' | 'helper') => {
    const ok = await run(() => client.teamMode(m))
    if (ok) { me.reload(); onDone(m) }
  }
  return (
    <Dialog title={t('team.welcomeTitle')} onClose={() => onDone(null)} busy={busy}>
      <p className="muted">{t('team.welcomeBody')}</p>
      <ModePicker mode={null} isAdmin={false} busy={busy} onPick={(m) => { if (m !== 'admin') void pick(m) }} />
      {error && <FormError error={error} />}
      <div className="dialog-actions"><Button onClick={() => onDone(null)} disabled={busy}>{t('team.welcomeLater')}</Button></div>
    </Dialog>
  )
}

// ----------------------------------------------------------------- Taklif yaratish
function InviteDialog({ channels, onClose, onCreated }: { channels: TeamChannel[]; onClose: () => void; onCreated: () => void }) {
  const { client, botUsername, notify } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [channel, setChannel] = useState(channels[0]?.channel_id ?? '')
  const [role, setRole] = useState<TeamRole>('editor')
  const [token, setToken] = useState<string | null>(null)
  const link = token ? inviteLink(botUsername, token) : null
  const create = async () => {
    let created: string | null = null
    const ok = await run(async () => { created = (await client.teamInviteCreate(channel, role)).token })
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
          <div className="chips" role="group" aria-label={t('team.inviteChannel')}>
            {channels.map((c) => (
              <button key={c.channel_id} type="button" className="chip" aria-pressed={channel === c.channel_id} onClick={() => setChannel(c.channel_id)}>{c.title || c.channel_id}</button>
            ))}
          </div>
          <span className="field-label">{t('team.inviteRole')}</span>
          <RoleChips value={role} onPick={setRole} />
          <p className="muted small">{t(roleHelp(role))}</p>
          {error && <FormError error={error} />}
          <div className="dialog-actions">
            <Button onClick={onClose} disabled={busy}>{t('common.back')}</Button>
            <Button variant="primary" busy={busy} disabled={!channel} onClick={() => void create()}>{t('team.inviteCreate')}</Button>
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

// ----------------------------------------------------------------- Egasi: o'rindiqlar va a'zolar
function MemberRow({ channel, m, reload }: { channel: TeamChannel; m: TeamMember; reload: () => void }) {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [ask, setAsk] = useState(false)
  const name = m.name || (m.username ? `@${m.username}` : String(m.user_id))
  return (
    <li className="item team-member">
      <div className="adm-row">
        <span className="adm-row-main"><strong className="adm-row-title">{name}</strong><span className="muted small">{m.user_id}</span></span>
        <Button icon="trash" disabled={busy} onClick={() => setAsk(true)} aria-label={t('team.remove')} />
      </div>
      <RoleChips value={m.role} disabled={busy} onPick={(r) => { if (r !== m.role) void run(() => client.teamMemberRole(channel.channel_id, m.user_id, r), 'adm.saved').then((ok) => { if (ok) reload() }) }} />
      {!m.active && <p className="muted small">⏸ {t('team.inactive')}</p>}
      {error && <FormError error={error} />}
      {ask && (
        <ConfirmDialog title={t('team.remove')} body={t('team.removeAsk', { name, title: channel.title || channel.channel_id })} confirmLabel={t('team.remove')} danger busy={busy}
          onClose={() => setAsk(false)} onConfirm={() => { void run(() => client.teamMemberRemove(channel.channel_id, m.user_id), 'adm.deleted').then((ok) => { if (ok) { setAsk(false); reload() } }) }} />
      )}
    </li>
  )
}

function OwnerTeam() {
  const { team, me, botUsername } = useAppData()
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, run } = useAdminAction()
  const [inviting, setInviting] = useState(false)
  const d = team.data
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
  const withPeople = d.channels.filter((c) => c.members.length > 0 || c.invites.length > 0)
  return (
    <>
      <section className="card adm-card">
        <div className="meter-top"><span>{t('team.seatsTitle')}</span><strong>{t('team.seatsOf', { used: seats.used, limit: seats.limit })}</strong></div>
        <div className="meter-bar" role="progressbar" aria-label={t('team.seatsTitle')} aria-valuemin={0} aria-valuemax={seats.limit} aria-valuenow={seats.used + seats.pending}>
          <span style={{ width: `${pct}%` }} data-level={pct >= 100 ? 'full' : 'ok'} />
        </div>
        <p className="muted small">{t('team.accounts', { n: seats.limit + 1, h: seats.limit })}{seats.pending > 0 ? ` · ${t('team.seatsPending', { n: seats.pending })}` : ''}</p>
        <Button variant="primary" block icon="plus" onClick={() => setInviting(true)}>{t('team.invite')}</Button>
      </section>
      <h3 className="sec-label">{t('team.members')}</h3>
      {withPeople.length === 0 && <p className="muted small">{t('team.membersEmpty')}</p>}
      {withPeople.map((c) => (
        <section key={c.channel_id} className="card adm-card" aria-label={c.title}>
          <h2>{c.title || c.channel_id}</h2>
          <ul className="list">
            {c.members.map((m) => <MemberRow key={m.user_id} channel={c} m={m} reload={team.reload} />)}
            {c.invites.map((i) => (
              <li key={`inv-${i.id}`} className="item adm-row">
                <span className="adm-row-main"><strong className="adm-row-title">⏳ {t('team.pendingInvite')}</strong><span className="muted small">{t(roleLabel(i.role))}</span></span>
                <Button disabled={busy} onClick={() => { void run(() => client.teamInviteRevoke(i.id), 'adm.deleted').then((ok) => { if (ok) team.reload() }) }}>{t('team.revoke')}</Button>
              </li>
            ))}
          </ul>
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
          <li key={c.channel_id} className="item adm-row">
            <span className="adm-row-main"><strong className="adm-row-title">{c.title || c.channel_id}</strong><span className="muted small">{t(roleHelp(c.role))}</span></span>
            <span className="chip">{t(roleLabel(c.role))}</span>
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
