import { useRef, useState } from 'react'
import { useAppData } from '../AppData'
import { NOTIFICATION_KEYS, type NotificationKey, type NotificationSettings } from '../api/types'
import { SubPage } from '../components/SubPage'
import { errorMessageKey } from '../components/ui'
import { toClientError } from '../hooks/useResource'
import { useI18n, type MessageKey } from '../i18n'

/** Botdagi standart qiymatlar (eski serverda `settings` bo'lmasa). */
export const NOTIFICATION_DEFAULTS: NotificationSettings = {
  notify_scheduled: true, notify_news: false, notify_morning_digest: true, notify_uzbek_calendar: true,
}

const LABELS: Record<NotificationKey, { title: MessageKey; hint: MessageKey; icon: string }> = {
  notify_scheduled: { title: 'notif.scheduled', hint: 'notif.scheduledHint', icon: '📅' },
  notify_morning_digest: { title: 'notif.digest', hint: 'notif.digestHint', icon: '🌅' },
  notify_uzbek_calendar: { title: 'notif.calendar', hint: 'notif.calendarHint', icon: '🗓' },
  notify_news: { title: 'notif.news', hint: 'notif.newsHint', icon: '📣' },
}
const ORDER: readonly NotificationKey[] = ['notify_scheduled', 'notify_morning_digest', 'notify_uzbek_calendar', 'notify_news']

export function enabledCount(values: NotificationSettings): number {
  return NOTIFICATION_KEYS.filter((k) => values[k]).length
}

/** Bildirishnomalar: har biri alohida almashtirgich (switch); o'zgarish darhol saqlanadi, xatoda avvalgi holatga qaytadi. */
export function NotificationsScreen({ current, onBack }: { current: NotificationSettings; onBack: () => void }) {
  const { client, me, notify } = useAppData()
  const { t } = useI18n()
  const [values, setValues] = useState<NotificationSettings>(current)
  const [busyKey, setBusyKey] = useState<NotificationKey | null>(null)
  const inFlight = useRef(false)

  const toggle = async (key: NotificationKey) => {
    if (inFlight.current) return
    inFlight.current = true
    const next = !values[key]
    setValues((v) => ({ ...v, [key]: next }))
    setBusyKey(key)
    try {
      await client.setNotifications({ [key]: next })
      notify(t('notif.saved'))
      me.reload()
    } catch (e) {
      setValues((v) => ({ ...v, [key]: !next })) // saqlanmadi: avvalgi holat
      notify(t(errorMessageKey(toClientError(e).code)), 'error')
    } finally {
      inFlight.current = false
      setBusyKey(null)
    }
  }

  return (
    <SubPage title={t('notif.title')} onBack={onBack}>
      <p className="muted">{t('notif.hint')}</p>
      <div className="set-group" role="group" aria-label={t('notif.title')}>
        {ORDER.map((key) => {
          const l = LABELS[key]
          return (
            <div key={key} className="switch-row">
              <span className="switch-icon" aria-hidden="true">{l.icon}</span>
              <span className="switch-text">
                <strong id={`n-${key}`}>{t(l.title)}</strong>
                <span className="muted small">{t(l.hint)}</span>
              </span>
              <button type="button" role="switch" className="switch" aria-checked={values[key]} aria-labelledby={`n-${key}`}
                disabled={busyKey !== null} onClick={() => void toggle(key)}>
                <span className="switch-knob" />
              </button>
            </div>
          )
        })}
      </div>
    </SubPage>
  )
}
