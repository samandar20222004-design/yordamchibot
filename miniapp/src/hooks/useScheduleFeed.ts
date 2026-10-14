import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiClient } from '../api/client'
import { ApiClientError } from '../api/client'
import type { PostFilter, ScheduledPost } from '../api/types'
import { config } from '../config'
import { toClientError } from './useResource'

export interface ScheduleFeed {
  items: ScheduledPost[]
  total: number
  hasMore: boolean
  loading: boolean
  refreshing: boolean
  loadingMore: boolean
  error: ApiClientError | null
  moreError: ApiClientError | null
  reload: () => void
  loadMore: () => void
}

/** Rejalashtirilgan postlar: sahifalab yuklash (offset), takroriy elementlar id bo'yicha olib tashlanadi. */
export function useScheduleFeed(client: ApiClient, enabled: boolean, status: PostFilter = 'pending'): ScheduleFeed {
  const [items, setItems] = useState<ScheduledPost[]>([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [pending, setPending] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<ApiClientError | null>(null)
  const [moreError, setMoreError] = useState<ApiClientError | null>(null)
  const loadedAt = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const itemsRef = useRef<ScheduledPost[]>([])
  itemsRef.current = items

  const reload = useCallback(() => {
    controller.current?.abort()
    const ctl = new AbortController()
    controller.current = ctl
    setPending(true)
    setLoadingMore(false)
    setMoreError(null)
    client.scheduledPosts(config.pageSize, 0, ctl.signal, status).then(
      (page) => {
        if (ctl.signal.aborted) return
        loadedAt.current = Date.now()
        setItems(page.items)
        setTotal(page.total)
        setHasMore(page.has_more)
        setLoaded(true)
        setError(null)
        setPending(false)
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        setError(toClientError(e))
        setPending(false)
      },
    )
  }, [client, status])

  const loadMore = useCallback(() => {
    if (controller.current && loadingMore) return
    const ctl = new AbortController()
    controller.current?.abort()
    controller.current = ctl
    setLoadingMore(true)
    setMoreError(null)
    client.scheduledPosts(config.pageSize, itemsRef.current.length, ctl.signal, status).then(
      (page) => {
        if (ctl.signal.aborted) return
        setItems((prev) => {
          const seen = new Set(prev.map((p) => p.id))
          return [...prev, ...page.items.filter((p) => !seen.has(p.id))]
        })
        setTotal(page.total)
        setHasMore(page.has_more)
        setLoadingMore(false)
      },
      (e: unknown) => {
        if (ctl.signal.aborted) return
        setMoreError(toClientError(e))
        setLoadingMore(false)
      },
    )
  }, [client, loadingMore, status])

  useEffect(() => {
    if (enabled && !loaded && controller.current === null) reload()
  }, [enabled, loaded, reload])

  useEffect(() => () => {
    controller.current?.abort()
    controller.current = null // StrictMode: qayta ulanishda yuklash yana boshlanadi
  }, [])

  useEffect(() => {
    if (!enabled) return
    const onVisible = () => {
      if (document.visibilityState !== 'visible' || !loaded) return
      if (Date.now() - loadedAt.current > config.staleAfterMs) reload()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [enabled, loaded, reload])

  return {
    items, total, hasMore, error, moreError, reload, loadMore, loadingMore,
    loading: pending && !loaded,
    refreshing: pending && loaded,
  }
}
