import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'

import { acquire } from './mediaQueue'

export interface PostMediaState { url: string | null; video: boolean; loading: boolean; failed: boolean }

/** Rejalangan postning rasmi/videosi (blob URL). `enabled=false` bo'lsa (ko'rinmaydi / media yo'q) hech narsa yuklanmaydi. */
export function usePostMedia(client: ApiClient, postId: number, enabled: boolean, version = ''): PostMediaState {
  const [state, setState] = useState<PostMediaState>({ url: null, video: false, loading: false, failed: false })
  useEffect(() => {
    if (!enabled || typeof URL.createObjectURL !== 'function') {
      setState({ url: null, video: false, loading: false, failed: false })
      return
    }
    const ctl = new AbortController()
    let objectUrl: string | null = null
    setState({ url: null, video: false, loading: true, failed: false })
    void acquire().then(async (release) => {
      try {
        if (ctl.signal.aborted) return
        const blob = await client.postMedia(postId, ctl.signal)
        if (ctl.signal.aborted) return
        objectUrl = blob ? URL.createObjectURL(blob) : null
        setState({ url: objectUrl, video: Boolean(blob?.type.startsWith('video/')), loading: false, failed: !blob })
      } finally {
        release()
      }
    })
    return () => {
      ctl.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [client, postId, enabled, version])
  return state
}
