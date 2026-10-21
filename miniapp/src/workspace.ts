// Ish joyi (yordamchi rejimi): tanlov shu qurilmada eslab qolinadi (faqat qulaylik). Ruxsatni server HAR so'rovda tekshiradi.
const KEY = 'postassist.workspace'
const ID = /^[0-9]{1,15}$/

/** Botdagi «📱 Mini App'da ishlash» tugmasi `?ws=<egasi_id>` bilan ochadi (faqat butun son); aks holda eslab qolingan tanlov. */
export function getInitialWorkspace(): number | null {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('ws')
    if (fromUrl && ID.test(fromUrl) && Number(fromUrl) > 0) return Number(fromUrl)
  } catch { /* e'tiborsiz */ }
  try {
    const stored = localStorage.getItem(KEY)
    if (stored && ID.test(stored) && Number(stored) > 0) return Number(stored)
  } catch { /* e'tiborsiz */ }
  return null
}

export function saveWorkspace(owner: number | null): void {
  try {
    if (owner) localStorage.setItem(KEY, String(owner))
    else localStorage.removeItem(KEY)
  } catch { /* e'tiborsiz */ }
}
