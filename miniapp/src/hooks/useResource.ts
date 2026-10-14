import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiClientError } from '../api/client'
import { config } from '../config'

export interface Resource<T> {
  data: T | null
  error: ApiClientError | null
  /** Birinchi yuklash (ma'lumot yo'q). */
  loading: boolean
  /** Ma'lumot bor, fonda yangilanmoqda. */
  refreshing: boolean
  reload: () => void
}

export function toClientError(e: unknown): ApiClientError {
  return e instanceof ApiClientError ? e : new ApiClientError('bad_response')
}

/**
 * Bitta GET resursi: yuklash/xato/yangilash holatlari. Bekor qilingan so'rov natijasi e'tiborga
 * olinmaydi; yangilash xatosi mavjud ma'lumotni O'CHIRMAYDI (foydalanuvchi ko'rib turgani saqlanadi).
 * Ilova yana ko'ringanda ma'lumot `staleAfterMs` dan eski bo'lsa jimgina yangilanadi.
 */
export function useResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, enabled: boolean): Resource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [pending, setPending] = useState(false)
  const loadedAt = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(() => {
    controller.current?.abort()
    const ctl = new AbortController()
    controller.current = ctl
    setPending(true)
    fetcherRef.current(ctl.signal).then(
      (value) => {
        if (ctl.signal.aborted) return
        loadedAt.current = Date.now()
        setData(value)
        setError(null)
        setPending(false)
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        setError(toClientError(e))
        setPending(false)
      },
    )
  }, [])

  useEffect(() => {
    if (enabled && loadedAt.current === 0 && controller.current === null) load()
  }, [enabled, load])

  useEffect(() => () => {
    controller.current?.abort()
    controller.current = null // StrictMode: qayta ulanishda yuklash yana boshlanadi
  }, [])

  useEffect(() => {
    if (!enabled) return
    const onVisible = () => {
      if (document.visibilityState !== 'visible' || loadedAt.current === 0) return
      if (Date.now() - loadedAt.current > config.staleAfterMs) load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [enabled, load])

  return { data, error, loading: pending && data === null, refreshing: pending && data !== null, reload: load }
}
