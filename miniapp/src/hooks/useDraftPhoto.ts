import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'

/** Qoralamadagi rasm uchun vaqtinchalik `blob:` manzil (Authorization kerak, shuning uchun fetch). `null` = yo'q/xato. */
export function useDraftPhoto(client: ApiClient, enabled: boolean, version: string | null): { url: string | null; loading: boolean } {
  const [state, setState] = useState<{ url: string | null; loading: boolean }>({ url: null, loading: enabled })
  useEffect(() => {
    if (!enabled || typeof URL.createObjectURL !== 'function') {
      setState({ url: null, loading: false })
      return
    }
    const ctl = new AbortController()
    let objectUrl: string | null = null
    setState({ url: null, loading: true })
    void client.draftMedia(ctl.signal).then((blob) => {
      if (ctl.signal.aborted) return
      objectUrl = blob ? URL.createObjectURL(blob) : null
      setState({ url: objectUrl, loading: false })
    })
    return () => {
      ctl.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [client, enabled, version])
  return state
}
