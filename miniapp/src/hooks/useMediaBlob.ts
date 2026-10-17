import { useEffect, useState } from 'react'
import { acquire } from './mediaQueue'

export interface MediaBlobState { url: string | null; video: boolean; loading: boolean; failed: boolean }

/** `load` bergan blob'dan vaqtincha `blob:` manzil (3 parallel navbat). `key` o'zgarsa qayta yuklanadi. */
export function useMediaBlob(load: (signal: AbortSignal) => Promise<Blob | null>, enabled: boolean, key: string): MediaBlobState {
  const [state, setState] = useState<MediaBlobState>({ url: null, video: false, loading: false, failed: false })
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
        const blob = await load(ctl.signal)
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
    // `load` har renderda yangi funksiya bo'lishi mumkin: faqat `key`/`enabled` o'zgarganda qayta yuklanadi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key])
  return state
}
