import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'

// Ro'yxatdagi rasmlar bir vaqtda ko'p yuklanib Mini App'ni va serverni og'irlashtirmasin: ko'pi bilan 3 ta parallel so'rov.
const MAX_PARALLEL = 3
let active = 0
const waiting: Array<() => void> = []

function acquire(): Promise<() => void> {
  const release = () => {
    active -= 1
    const next = waiting.shift()
    if (next) next()
  }
  if (active < MAX_PARALLEL) { active += 1; return Promise.resolve(release) }
  return new Promise((resolve) => waiting.push(() => { active += 1; resolve(release) }))
}

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
