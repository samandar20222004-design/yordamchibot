import { useI18n, type MessageKey } from '../i18n'
import { ALL_MASK, WEEKEND_MASK, WORKDAYS_MASK, type RepeatChoice } from '../pages/recurrence'

const DAY_KEYS = [1, 2, 3, 4, 5, 6, 7].map((n) => `cal.w${n}` as MessageKey)

/** Qo'lda takrorlash tanlovi: takrorlanmaydi / har kuni / har N kunda / tanlangan hafta kunlari (dam olish, ish kunlari...). */
export function RepeatPicker({ value, onChange, showTz }: {
  value: RepeatChoice; onChange: (next: RepeatChoice) => void; showTz: boolean
}) {
  const { t } = useI18n()
  const toggle = (day: number) => onChange({ ...value, mask: (value.mask ^ (1 << day)) & ALL_MASK })
  return (
    <div className="repeat">
      <label className="field" htmlFor="repeat-kind">{t('rep.label')}</label>
      <select id="repeat-kind" className="input" value={value.kind}
        onChange={(e) => onChange({ ...value, kind: e.target.value as RepeatChoice['kind'] })}>
        <option value="none">{t('rep.none')}</option>
        <option value="daily">{t('rep.daily')}</option>
        <option value="interval">{t('rep.interval')}</option>
        <option value="weekdays">{t('rep.weekdays')}</option>
      </select>

      {value.kind === 'interval' && (
        <div className="repeat-interval">
          <span>{t('rep.every')}</span>
          <input className="input" type="number" inputMode="numeric" min={2} max={30} aria-label={t('rep.interval')}
            value={value.interval}
            onChange={(e) => onChange({ ...value, interval: Math.min(30, Math.max(2, Number(e.target.value) || 2)) })} />
          <span>{t('rep.daysUnit')}</span>
        </div>
      )}

      {value.kind === 'weekdays' && (
        <>
          <div className="chips" role="group" aria-label={t('rep.weekdays')}>
            <button type="button" className="chip" aria-pressed={value.mask === WEEKEND_MASK}
              onClick={() => onChange({ ...value, mask: WEEKEND_MASK })}>{t('rep.weekendsBtn')}</button>
            <button type="button" className="chip" aria-pressed={value.mask === WORKDAYS_MASK}
              onClick={() => onChange({ ...value, mask: WORKDAYS_MASK })}>{t('rep.workdaysBtn')}</button>
          </div>
          <div className="weekdays" role="group" aria-label={t('rep.weekdays')}>
            {DAY_KEYS.map((key, day) => (
              <button key={key} type="button" aria-pressed={(value.mask & (1 << day)) !== 0} onClick={() => toggle(day)}>{t(key)}</button>
            ))}
          </div>
        </>
      )}
      {value.kind !== 'none' && showTz && <p className="muted small">{t('rep.tz')}</p>}
    </div>
  )
}
