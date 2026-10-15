import { useEffect, useState } from 'react'
import { useI18n, type MessageKey } from '../i18n'
import { ALL_MASK, WEEKEND_MASK, WORKDAYS_MASK, suggestSecondTime, type RepeatChoice } from '../pages/recurrence'

const DAY_KEYS = [1, 2, 3, 4, 5, 6, 7].map((n) => `cal.w${n}` as MessageKey)

/** Qo'lda takrorlash tanlovi: takrorlanmaydi / har kuni / har N kunda / tanlangan hafta kunlari (dam olish, ish kunlari...). */
export function RepeatPicker({ value, onChange, showTz, firstTime = '09:00' }: {
  value: RepeatChoice; onChange: (next: RepeatChoice) => void; showTz: boolean; firstTime?: string
}) {
  const { t } = useI18n()
  // Yozish paytida maydon BO'SH bo'la oladi (o'chirib yangi raqam yozish uchun); chegara (2..30) fokus ketganda qo'llanadi.
  const [draft, setDraft] = useState(String(value.interval))
  useEffect(() => setDraft(String(value.interval)), [value.interval])
  const commit = () => {
    const raw = Number(draft)
    const n = draft.trim() === '' || !Number.isFinite(raw) ? value.interval : Math.min(30, Math.max(2, Math.round(raw)))  // bo'sh qoldirilsa avvalgi qiymat
    setDraft(String(n))
    if (n !== value.interval) onChange({ ...value, interval: n })
  }
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

      {value.kind === 'daily' && (
        <div className="repeat-twice">
          <label className="check">
            <input type="checkbox" checked={value.time2 != null}
              onChange={(e) => onChange({ ...value, time2: e.target.checked ? suggestSecondTime(firstTime) : null })} />
            <span>{t('rep.secondHint')}</span>
          </label>
          {value.time2 != null && (
            <label className="repeat-second">
              <span className="muted small">{t('rep.second')}</span>
              <input className="input" type="time" step={60} value={value.time2} aria-label={t('rep.second')}
                onChange={(e) => e.target.value && onChange({ ...value, time2: e.target.value })} />
            </label>
          )}
        </div>
      )}

      {value.kind === 'interval' && (
        <div className="repeat-interval">
          <span>{t('rep.every')}</span>
          <input className="input" type="number" inputMode="numeric" min={2} max={30} aria-label={t('rep.interval')}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              const n = Number(e.target.value)
              if (e.target.value !== '' && Number.isInteger(n) && n >= 2 && n <= 30) onChange({ ...value, interval: n })
            }}
            onBlur={commit} />
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
