import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'

/** Qoralamadagi rasm uchun vaqtinchalik `blob:` manzil (Authorization kerak, shuning uchun fetch). `null` = yo'q/xato. */
export function useDraftPhoto(client: ApiClient, enabled: boolean, version: string | null): { url: string | null; loading: boolean; video: boolean } {
  const [state, setState] = useState<{ url: string | null; loading: boolean; video: boolean }>({ url: null, loading: enabled, video: false })
  useEffect(() => {
    if (!enabled || typeof URL.createObjectURL !== 'function') {
      setState({ url: null, loading: false, video: false })
      return
    }
    const ctl = new AbortController()
    let objectUrl: string | null = null
    setState({ url: null, loading: true, video: false })
    void client.draftMedia(ctl.signal).then((blob) => {
      if (ctl.signal.aborted) return
      objectUrl = blob ? URL.createObjectURL(blob) : null
      setState({ url: objectUrl, loading: false, video: Boolean(blob?.type.startsWith('video/')) })
    })
    return () => {
      ctl.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [client, enabled, version])
  return state
}
