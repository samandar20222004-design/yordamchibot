import { useState } from 'react'
import { useAppData } from '../../AppData'
import type { AdminPromo } from '../../api/types'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Page, PageHeader } from '../../components/Shell'
import { Button, EmptyState, ErrorState, FormError, LoadingBlock } from '../../components/ui'
import { useResource } from '../../hooks/useResource'
import { useI18n, type MessageKey } from '../../i18n'
import { useAdminAction } from './AdminPages'

type Section = 'promo' | 'grant' | 'system' | 'roles'
const SECTIONS: ReadonlyArray<{ id: Section; label: MessageKey }> = [
  { id: 'promo', label: 'adm.tlPromo' }, { id: 'grant', label: 'adm.tlGrant' },
  { id: 'system', label: 'adm.tlSystem' }, { id: 'roles', label: 'adm.tlRoles' },
]

function shortDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

/** Super admin «Boshqaruv» bo'limi: promo-kodlar (ro'yxat, yaratish, o'chirish), tarif berish, tizim, rollar. */
export function AdminToolsPage() {
  const { t } = useI18n()
  const [section, setSection] = useState<Section>('promo')
  return (
    <Page>
      <PageHeader title={t('adm.tools')} />
      <div className="chips" role="group" aria-label={t('adm.tools')}>
        {SECTIONS.map((x) => (
          <button key={x.id} type="button" className="chip" aria-pressed={section === x.id} onClick={() => setSection(x.id)}>{t(x.label)}</button>
        ))}
      </div>
      {section === 'promo' && <PromoSection />}
      {section === 'grant' && <GrantSection />}
      {section === 'system' && <SystemSection />}
      {section === 'roles' && <RolesSection />}
    </Page>
  )
}

// ----------------------------------------------------------------- Promo-kodlar
function PromoCreate({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [code, setCode] = useState('')
  const [days, setDays] = useState('30')
  const [max, setMax] = useState('')
  const [plan, setPlan] = useState<'pro' | 'ultra'>('pro')
  const d = Number(days)
  const m = max.trim() === '' ? null : Number(max)
  const valid = /^[A-Za-z0-9_-]{3,32}$/.test(code.trim()) && Number.isInteger(d) && d >= 1 && (m === null || (Number.isInteger(m) && m >= 1))
  const save = async () => {
    const ok = await run(() => client.adminPromoCreate({ code: code.trim(), days: d, max_uses: m, plan }), 'adm.saved')
    if (ok) onSaved()
  }
  return (
    <Dialog title={t('adm.prNew')} onClose={onClose} busy={busy}>
      <label className="field">{t('adm.prCode')}
        <input className="input" autoCapitalize="characters" value={code} maxLength={32} onChange={(e) => setCode(e.target.value)} />
      </label>
      <label className="field">{t('adm.prDays')}
        <input className="input" type="number" inputMode="numeric" min={1} value={days} onChange={(e) => setDays(e.target.value)} />
      </label>
      <label className="field">{t('adm.prMax')}
        <input className="input" type="number" inputMode="numeric" min={1} value={max} onChange={(e) => setMax(e.target.value)} />
      </label>
      <div className="chips" role="group" aria-label={t('adm.prPlan')}>
        {(['pro', 'ultra'] as const).map((p) => (
          <button key={p} type="button" className="chip" aria-pressed={plan === p} onClick={() => setPlan(p)}>{p.toUpperCase()}</button>
        ))}
      </div>
      {error && <FormError error={error} />}
      <div className="dialog-actions">
        <Button onClick={onClose} disabled={busy}>{t('common.back')}</Button>
        <Button variant="primary" busy={busy} disabled={!valid} onClick={() => void save()}>{t('adm.prCreate')}</Button>
      </div>
    </Dialog>
  )
}

function PromoDetail({ promo, onClose, onChanged }: { promo: AdminPromo; onClose: () => void; onChanged: () => void }) {
  const { client } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminPromoDetail(promo.code, s), true)
  const { busy, error, run } = useAdminAction()
  const [asking, setAsking] = useState(false)
  const toggle = async () => {
    const ok = await run(() => client.adminPromoActive(promo.code, !promo.is_active), 'adm.saved')
    if (ok) onChanged()
  }
  const remove = async () => {
    const ok = await run(() => client.adminPromoDelete(promo.code), 'adm.deleted')
    if (ok) { setAsking(false); onChanged() }
  }
  return (
    <Dialog title={promo.code} onClose={onClose} busy={busy}>
      <p className="muted small">{t('adm.prRow', { plan: promo.plan.toUpperCase(), days: promo.days, used: promo.used, max: promo.max_uses ?? '∞', left: promo.left ?? '∞' })}</p>
      <p className="muted small">{t(`adm.st_${promo.status}` as MessageKey)}{promo.expires_at ? ` · ${t('adm.prExp', { date: shortDate(promo.expires_at) })}` : ''}</p>
      <h3 className="sec-label">{t('adm.prWho')}</h3>
      {res.loading && <LoadingBlock rows={2} />}
      {res.data && res.data.redeemers.length === 0 && <p className="muted small">{t('adm.prNobody')}</p>}
      {res.data && res.data.redeemers.length > 0 && (
        <ul className="list">
          {res.data.redeemers.map((r, i) => (
            <li key={`${r.user_id}-${i}`} className="item adm-row"><code>{r.user_id}</code><span className="muted small">{shortDate(r.at)}</span></li>
          ))}
        </ul>
      )}
      {error && <FormError error={error} />}
      <div className="dialog-actions">
        <Button onClick={onClose} disabled={busy}>{t('common.back')}</Button>
        <Button busy={busy} onClick={() => void toggle()}>{t(promo.is_active ? 'adm.prDisable' : 'adm.prEnable')}</Button>
        <Button icon="trash" disabled={busy} onClick={() => setAsking(true)} aria-label={t('adm.prDelete')}>{t('adm.prDelete')}</Button>
      </div>
      {asking && (
        <ConfirmDialog title={t('adm.prDeleteTitle')} body={t('adm.prDeleteAsk', { code: promo.code, used: promo.used })} confirmLabel={t('adm.delete')} danger busy={busy}
          onClose={() => setAsking(false)} onConfirm={() => void remove()} />
      )}
    </Dialog>
  )
}

function PromoSection() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminPromos(s), true)
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<AdminPromo | null>(null)
  const d = res.data
  return (
    <>
      {res.loading && <LoadingBlock rows={3} />}
      {!d && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {d && (
        <>
          <div className="adm-grid">
            <div className="adm-stat"><span className="stat-label">{t('adm.prRedeemed')}</span><strong className="stat-value">{d.totals.redemptions}</strong></div>
            <div className="adm-stat"><span className="stat-label">{t('adm.prRemaining')}</span><strong className="stat-value">{d.totals.remaining_uses}</strong></div>
          </div>
          <p className="muted small">{t('adm.prTotals', { total: d.totals.total, active: d.totals.active, used_up: d.totals.used_up, expired: d.totals.expired, disabled: d.totals.disabled })}
            {d.totals.unlimited > 0 ? ` · +${d.totals.unlimited} ${t('adm.prUnlimited')}` : ''}</p>
          <Button icon="plus" variant="primary" block onClick={() => setCreating(true)}>{t('adm.prNew')}</Button>
          {d.items.length === 0 && <EmptyState title={t('adm.prEmptyTitle')} body={t('adm.prEmpty')} />}
          <ul className="list">
            {d.items.map((p) => (
              <li key={p.code} className="item adm-listing">
                <button type="button" className="adm-row adm-row-btn" onClick={() => setOpen(p)}>
                  <span className="adm-row-main">
                    <strong className="adm-row-title">{p.code}</strong>
                    <span className="muted small">{t('adm.prRow', { plan: p.plan.toUpperCase(), days: p.days, used: p.used, max: p.max_uses ?? '∞', left: p.left ?? '∞' })}</span>
                  </span>
                  <span className="chip">{t(`adm.st_${p.status}` as MessageKey)}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {creating && <PromoCreate onClose={() => setCreating(false)} onSaved={() => { setCreating(false); res.reload() }} />}
      {open && <PromoDetail promo={open} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); res.reload() }} />}
    </>
  )
}

// ----------------------------------------------------------------- Tarif berish
function GrantSection() {
  const { client } = useAppData()
  const { t } = useI18n()
  const { busy, error, run } = useAdminAction()
  const [uid, setUid] = useState('')
  const [days, setDays] = useState('30')
  const [plan, setPlan] = useState<'pro' | 'ultra'>('pro')
  const [ask, setAsk] = useState(false)
  const u = Number(uid)
  const d = Number(days)
  const valid = /^[0-9]{1,15}$/.test(uid.trim()) && u > 0 && Number.isInteger(d) && d >= 1
  const go = async () => {
    const ok = await run(() => client.adminGrant({ user_id: u, days: d, plan }), 'adm.grDone')
    if (ok) setAsk(false)
  }
  return (
    <section className="card adm-card">
      <h2>{t('adm.tlGrant')}</h2>
      <label className="field">{t('adm.grUser')}
        <input className="input" type="number" inputMode="numeric" value={uid} onChange={(e) => setUid(e.target.value)} />
      </label>
      <label className="field">{t('adm.grDays')}
        <input className="input" type="number" inputMode="numeric" min={1} value={days} onChange={(e) => setDays(e.target.value)} />
      </label>
      <div className="chips" role="group" aria-label={t('adm.prPlan')}>
        {(['pro', 'ultra'] as const).map((p) => (
          <button key={p} type="button" className="chip" aria-pressed={plan === p} onClick={() => setPlan(p)}>{p.toUpperCase()}</button>
        ))}
      </div>
      {error && <FormError error={error} />}
      <Button variant="primary" block disabled={!valid} onClick={() => setAsk(true)}>{t('adm.grGo')}</Button>
      {ask && (
        <ConfirmDialog title={t('adm.grGo')} body={`${u} · ${plan.toUpperCase()} · ${d}`} confirmLabel={t('adm.confirm')} busy={busy}
          onClose={() => setAsk(false)} onConfirm={() => void go()} />
      )}
    </section>
  )
}

// ----------------------------------------------------------------- Tizim
function SystemSection() {
  const { client } = useAppData()
  const { t } = useI18n()
  const health = useResource((s) => client.adminHealth(s), true)
  const feats = useResource((s) => client.adminFeatures(s), true)
  const audit = useResource((s) => client.adminAudit(s), true)
  return (
    <>
      <h3 className="sec-label">{t('adm.sysHealth')}</h3>
      {health.loading && <LoadingBlock rows={1} />}
      {health.data && (
        <section className="card adm-card">
          <strong>{health.data.ready ? `✅ ${t('adm.sysReady')}` : `⚠️ ${t('adm.sysNotReady')}`}</strong>
          <div className="chips">{Object.entries(health.data.checks).map(([k, v]) => <span key={k} className="chip">{k}: {v}</span>)}</div>
          {health.data.uptime && <p className="muted small">{t('adm.sysUptime')}: {health.data.uptime}</p>}
        </section>
      )}
      {!health.data && health.error && <p className="muted small">{t('adm.sysEmpty')}</p>}
      <h3 className="sec-label">{t('adm.sysFeatures')}</h3>
      {feats.data && feats.data.most_used.length === 0 && <p className="muted small">{t('adm.sysEmpty')}</p>}
      <ul className="list">
        {feats.data?.most_used.slice(0, 10).map((f) => (
          <li key={f.name} className="item adm-row"><span className="adm-row-title">{f.name}</span><span className="muted small">{f.count} · {f.users} · {f.rate}%</span></li>
        ))}
      </ul>
      <h3 className="sec-label">{t('adm.sysAudit')}</h3>
      {audit.data && audit.data.items.length === 0 && <p className="muted small">{t('adm.sysEmpty')}</p>}
      {!audit.data && audit.error && <p className="muted small">{t('adm.sysEmpty')}</p>}
      <ul className="list">
        {audit.data?.items.slice(0, 15).map((a, i) => (
          <li key={i} className="item adm-row">
            <span className="adm-row-main"><strong className="adm-row-title">{a.action}</strong>
              <span className="muted small">{a.admin_id ?? '—'}{a.target_type ? ` → ${a.target_type}#${a.target_id}` : ''}</span></span>
            <span className="muted small">{shortDate(a.at)}</span>
          </li>
        ))}
      </ul>
    </>
  )
}

// ----------------------------------------------------------------- Rollar
function RolesSection() {
  const { client, botUsername } = useAppData()
  const { t } = useI18n()
  const res = useResource((s) => client.adminRoles(s), true)
  const { busy, error, run } = useAdminAction()
  const [uid, setUid] = useState('')
  const [role, setRole] = useState('admin')
  const apply = async (userId: number, r: string) => {
    if (await run(() => client.adminRoleSet({ user_id: userId, role: r }), 'adm.saved')) res.reload()
  }
  const valid = /^[0-9]{1,15}$/.test(uid.trim()) && Number(uid) > 0
  return (
    <>
      <p className="muted small">{t('adm.rolesHint')}</p>
      {res.loading && <LoadingBlock rows={2} />}
      {!res.data && res.error && <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} />}
      {res.data && (
        <>
          <ul className="list">
            {res.data.items.map((r) => (
              <li key={r.user_id} className="item adm-row">
                <span className="adm-row-main"><strong className="adm-row-title">{r.user_id}</strong><span className="muted small">{r.role}</span></span>
                <Button icon="trash" disabled={busy} onClick={() => void apply(r.user_id, 'user')} aria-label={t('adm.rlRemove')} />
              </li>
            ))}
          </ul>
          <section className="card adm-card">
            <label className="field">{t('adm.rlUser')}
              <input className="input" type="number" inputMode="numeric" value={uid} onChange={(e) => setUid(e.target.value)} />
            </label>
            <div className="chips" role="group" aria-label={t('adm.rlRole')}>
              {res.data.choices.map((c) => (
                <button key={c} type="button" className="chip" aria-pressed={role === c} onClick={() => setRole(c)}>{c}</button>
              ))}
            </div>
            {error && <FormError error={error} />}
            <Button variant="primary" block busy={busy} disabled={!valid} onClick={() => void apply(Number(uid), role)}>{t('adm.rlSet')}</Button>
          </section>
        </>
      )}
    </>
  )
}
