import { useState, type CSSProperties } from 'react'
import { useAppData } from '../AppData'
import { ACCENTS, BACKGROUNDS, DENSITIES, FONTS, HOME_SECTIONS, RADII, TAB_IDS, THEMES, moveTab, toggleTab, type Appearance, type TabId } from '../appearance'
import { Icon } from '../components/Icon'
import { ConfirmDialog } from '../components/Dialog'
import { SubPage } from '../components/SubPage'
import { Button } from '../components/ui'
import { useI18n, type MessageKey } from '../i18n'
import { haptic } from '../telegram'

const ACCENT_COLOR: Record<string, string> = {
  blue: '#2563eb', violet: '#7c3aed', green: '#059669', rose: '#e11d48', orange: '#ea580c', teal: '#0d9488', red: '#dc2626', graphite: '#374151',
}
const BG_COLOR: Record<string, string> = {
  auto: 'linear-gradient(135deg, #dbeafe, #ede9fe, #fce7f3)', plain: '#f2f3f5', sunset: 'linear-gradient(135deg, #fed7aa, #fbcfe8)',
  ocean: 'linear-gradient(135deg, #bae6fd, #a5f3fc)', forest: 'linear-gradient(135deg, #bbf7d0, #d9f99d)', midnight: 'linear-gradient(135deg, #312e81, #4c1d95)',
  paper: '#f3dfb8', dots: 'radial-gradient(#9ca3af 1.2px, #f2f3f5 1.5px) 0 0 / 8px 8px',
}
const TAB_LABEL: Record<TabId, MessageKey> = {
  home: 'tab.home', post: 'tab.post', schedule: 'tab.schedule', market: 'tab.market', me: 'tab.me',
}

function Section({ title, children, hint }: { title: string; children: React.ReactNode; hint?: string }) {
  return (
    <section className="card" aria-label={title}>
      <h2>{title}</h2>
      {hint && <p className="muted small">{hint}</p>}
      {children}
    </section>
  )
}

function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: ReadonlyArray<{ id: T; label: string }>; onChange: (v: T) => void
}) {
  return (
    <fieldset className="segmented" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => { haptic('select'); onChange(o.id) }}>{o.label}</button>
      ))}
    </fieldset>
  )
}

function Switch({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="ap-switch" onClick={() => { haptic('select'); onChange(!checked) }}>
      <span><strong>{label}</strong>{hint && <><br /><span className="muted small">{hint}</span></>}</span>
      <span className="ap-track" aria-hidden="true" />
    </button>
  )
}

/** Men -> Ko'rinish: rang, fon, mavzu, zichlik, burchaklar, shrift, harakat, pastki panel va bosh sahifa bo'limlari. */
export function AppearanceScreen({ onBack }: { onBack: () => void }) {
  const { appearance: a, setAppearance, resetAppearance, notify } = useAppData()
  const { t } = useI18n()
  const [confirmReset, setConfirmReset] = useState(false)
  const set = (patch: Partial<Appearance>) => setAppearance(patch)
  const opts = <T extends string>(prefix: string, ids: readonly T[]) => ids.map((id) => ({ id, label: t(`${prefix}.${id}` as MessageKey) }))
  const hidden = TAB_IDS.filter((id) => !a.tabs.includes(id))

  return (
    <SubPage title={t('ap.title')} onBack={onBack}>
      <p className="muted">{t('ap.lead')}</p>

      <section className="ap-preview" aria-label={t('ap.previewTitle')}>
        <strong>{t('ap.previewTitle')}</strong>
        <span>{t('ap.previewText')}</span>
        <span className="ap-mini"><span>{t('ap.chip1')}</span><span>{t('ap.chip2')}</span><span>{t(`ap.accent.${a.accent}` as MessageKey)}</span></span>
      </section>

      <Section title={t('ap.accent')}>
        <div className="ap-swatches" role="group" aria-label={t('ap.accent')}>
          {ACCENTS.map((id) => (
            <button key={id} type="button" className="ap-swatch" aria-pressed={a.accent === id} onClick={() => { haptic('select'); set({ accent: id }) }}>
              <span className={`ap-dot${id === 'auto' ? ' ap-dot-auto' : ''}`} style={id === 'auto' ? undefined : ({ '--c': ACCENT_COLOR[id] } as CSSProperties)} />
              {t(`ap.accent.${id}` as MessageKey)}
            </button>
          ))}
        </div>
      </Section>

      <Section title={t('ap.bg')}>
        <div className="ap-swatches" role="group" aria-label={t('ap.bg')}>
          {BACKGROUNDS.map((id) => (
            <button key={id} type="button" className="ap-swatch" aria-pressed={a.background === id} onClick={() => { haptic('select'); set({ background: id }) }}>
              <span className="ap-bg" style={{ background: BG_COLOR[id] }} />
              {t(`ap.bg.${id}` as MessageKey)}
            </button>
          ))}
        </div>
      </Section>

      <Section title={t('ap.theme')}>
        <Segmented label={t('ap.theme')} value={a.theme} options={opts('ap.theme', THEMES)} onChange={(theme) => set({ theme })} />
      </Section>

      <Section title={t('ap.density')}>
        <Segmented label={t('ap.density')} value={a.density} options={opts('ap.density', DENSITIES)} onChange={(density) => set({ density })} />
        <h2>{t('ap.radius')}</h2>
        <Segmented label={t('ap.radius')} value={a.radius} options={opts('ap.radius', RADII)} onChange={(radius) => set({ radius })} />
        <h2>{t('ap.font')}</h2>
        <Segmented label={t('ap.font')} value={a.font} options={opts('ap.font', FONTS)} onChange={(font) => set({ font })} />
      </Section>

      <Section title={t('ap.motion')}>
        <Switch label={t('ap.motion')} hint={t('ap.motionHint')} checked={a.motion} onChange={(motion) => set({ motion })} />
        <Switch label={t('ap.haptics')} hint={t('ap.hapticsHint')} checked={a.haptics} onChange={(haptics) => set({ haptics })} />
      </Section>

      <Section title={t('ap.tabs')} hint={t('ap.tabsHint')}>
        <div role="list">
          {a.tabs.map((id, i) => (
            <div key={id} role="listitem" className="ap-tabrow">
              <span className="ap-tabname"><Icon name={id === 'me' ? 'user' : id === 'home' ? 'home' : id === 'post' ? 'post' : id === 'schedule' ? 'calendar' : 'market'} size={20} />{t(TAB_LABEL[id])}</span>
              <span className="ap-mv">
                <button type="button" aria-label={`${t('ap.up')}: ${t(TAB_LABEL[id])}`} disabled={i === 0} onClick={() => set({ tabs: moveTab(a.tabs, id, -1) })}>↑</button>
                <button type="button" aria-label={`${t('ap.down')}: ${t(TAB_LABEL[id])}`} disabled={i === a.tabs.length - 1} onClick={() => set({ tabs: moveTab(a.tabs, id, 1) })}>↓</button>
                <button type="button" aria-label={`${t('ap.toggleTab')}: ${t(TAB_LABEL[id])}`} disabled={id === 'me' || a.tabs.length <= 2}
                  onClick={() => set({ tabs: toggleTab(a.tabs, id) })}>✕</button>
              </span>
            </div>
          ))}
          {hidden.map((id) => (
            <div key={id} role="listitem" className="ap-tabrow" data-off="true">
              <span className="ap-tabname">{t(TAB_LABEL[id])}</span>
              <span className="ap-mv">
                <button type="button" aria-label={`${t('ap.toggleTab')}: ${t(TAB_LABEL[id])}`} onClick={() => set({ tabs: toggleTab(a.tabs, id) })}>＋</button>
              </span>
            </div>
          ))}
        </div>
        <label className="field" htmlFor="ap-start">{t('ap.start')}</label>
        <select id="ap-start" className="input" value={a.start} onChange={(e) => set({ start: e.target.value as TabId })}>
          {a.tabs.map((id) => <option key={id} value={id}>{t(TAB_LABEL[id])}</option>)}
        </select>
      </Section>

      <Section title={t('ap.homeSections')}>
        {HOME_SECTIONS.map((k) => (
          <Switch key={k} label={t(`ap.home.${k}` as MessageKey)} checked={a.home[k]} onChange={(v) => set({ home: { ...a.home, [k]: v } })} />
        ))}
      </Section>

      <Button variant="ghost" block onClick={() => setConfirmReset(true)}>{t('ap.reset')}</Button>
      {confirmReset && (
        <ConfirmDialog title={t('ap.reset')} body={t('ap.resetAsk')} confirmLabel={t('ap.reset')}
          onConfirm={() => { resetAppearance(); setConfirmReset(false); notify(t('ap.resetDone')) }} onClose={() => setConfirmReset(false)} />
      )}
    </SubPage>
  )
}
