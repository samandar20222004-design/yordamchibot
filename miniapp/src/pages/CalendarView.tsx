import { useMemo, useState, type ReactNode } from 'react'
import { useAppData } from '../AppData'
import type { ScheduledPost } from '../api/types'
import { Button, ErrorState, InlineWarning, LoadingBlock } from '../components/ui'
import { useResource } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'
import { localDayKey, monthGrid, shiftMonth } from './format'

const MONTH_KEYS = Array.from({ length: 12 }, (_, i) => `cal.m${i + 1}` as MessageKey)
const WEEKDAY_KEYS = Array.from({ length: 7 }, (_, i) => `cal.w${i + 1}` as MessageKey)

/** Postlarni mahalliy kun bo'yicha sanaydi (kalendar katagidagi son). Yaroqsiz sana e'tiborsiz. */
export function countByDay(items: ScheduledPost[]): Map<string, ScheduledPost[]> {
  const byDay = new Map<string, ScheduledPost[]>()
  for (const p of items) {
    const d = p.scheduled_time ? new Date(p.scheduled_time) : null
    if (!d || Number.isNaN(d.getTime())) continue
    const key = localDayKey(d)
    const list = byDay.get(key)
    if (list) list.push(p)
    else byDay.set(key, [p])
  }
  return byDay
}

function Month({ year, month, renderPost, selectedKey, onSelect }: {
  year: number; month: number; renderPost: (p: ScheduledPost) => ReactNode
  selectedKey: string; onSelect: (key: string) => void
}) {
  const { client, botUsername } = useAppData()
  const { t, formatDate } = useI18n()
  const grid = useMemo(() => monthGrid(year, month), [year, month])
  const res = useResource(
    (signal) => client.calendar(grid.start.toISOString(), grid.end.toISOString(), signal), true)
  const byDay = useMemo(() => countByDay(res.data?.items ?? []), [res.data])
  const todayKey = localDayKey(new Date())

  if (res.loading) return <LoadingBlock rows={4} />
  if (!res.data) return res.error ? <ErrorState error={res.error} onRetry={res.reload} botUsername={botUsername} /> : null
  const picked = byDay.get(selectedKey) ?? []
  const pickedDate = grid.days.find((d) => localDayKey(d) === selectedKey)

  return (
    <>
      {res.error && <InlineWarning error={res.error} onRetry={res.reload} />}
      {res.data.truncated && <div className="banner banner-warn" role="status">{t('cal.truncated')}</div>}
      <div className="cal" role="grid" aria-label={t(MONTH_KEYS[month]!) + ' ' + year}>
        <div className="cal-row cal-head" role="row">
          {WEEKDAY_KEYS.map((k) => <span key={k} role="columnheader">{t(k)}</span>)}
        </div>
        {Array.from({ length: 6 }, (_, w) => (
          <div className="cal-row" role="row" key={w}>
            {grid.days.slice(w * 7, w * 7 + 7).map((d) => {
              const key = localDayKey(d)
              const n = byDay.get(key)?.length ?? 0
              const inMonth = d.getMonth() === month
              return (
                <button key={key} type="button" role="gridcell" className="cal-day"
                  data-testid={`cal-${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`}
                  data-out={inMonth ? undefined : 'true'} data-today={key === todayKey ? 'true' : undefined}
                  aria-selected={key === selectedKey} aria-current={key === todayKey ? 'date' : undefined}
                  aria-label={`${formatDate(d.toISOString())}${n ? ', ' + t('cal.dayCount', { n }) : ''}`}
                  onClick={() => onSelect(key)}>
                  <span>{d.getDate()}</span>
                  {n > 0 && <span className="cal-count" aria-hidden="true">{n}</span>}
                </button>
              )
            })}
          </div>
        ))}
      </div>
      {pickedDate ? (
        <section aria-live="polite">
          <h2 className="group-title">{t('cal.pickTitle', { date: formatDate(pickedDate.toISOString()), n: picked.length })}</h2>
          {picked.length === 0 ? <p className="muted">{t('cal.empty')}</p> : <ul className="list">{picked.map(renderPost)}</ul>}
        </section>
      ) : <p className="muted">{t('cal.hint')}</p>}
    </>
  )
}

/** Oylik kalendar: kunlar bo'yicha kutilayotgan postlar soni; kun tanlanganda o'sha kun postlari. */
export function CalendarView({ renderPost, reloadKey }: { renderPost: (p: ScheduledPost) => ReactNode; reloadKey: number }) {
  const { t } = useI18n()
  const now = new Date()
  const [cursor, setCursor] = useState({ year: now.getFullYear(), month: now.getMonth() })
  const [selected, setSelected] = useState(() => localDayKey(now))
  const go = (delta: number) => setCursor((c) => shiftMonth(c.year, c.month, delta))
  const goToday = () => { const d = new Date(); setCursor({ year: d.getFullYear(), month: d.getMonth() }); setSelected(localDayKey(d)) }

  return (
    <>
      <div className="cal-nav">
        <Button variant="ghost" aria-label={t('cal.prev')} onClick={() => go(-1)}>‹</Button>
        <strong aria-live="polite">{t(MONTH_KEYS[cursor.month]!)} {cursor.year}</strong>
        <Button variant="ghost" aria-label={t('cal.next')} onClick={() => go(1)}>›</Button>
        <Button variant="ghost" onClick={goToday}>{t('cal.today')}</Button>
      </div>
      <Month key={`${cursor.year}-${cursor.month}-${reloadKey}`} year={cursor.year} month={cursor.month}
        renderPost={renderPost} selectedKey={selected} onSelect={setSelected} />
    </>
  )
}
