// Ro'yxatdagi/albomdagi rasmlar bir vaqtda ko'p yuklanib Mini App'ni va serverni og'irlashtirmasin: ko'pi bilan 3 ta parallel so'rov.
const MAX_PARALLEL = 3
let active = 0
const waiting: Array<() => void> = []

export function acquire(): Promise<() => void> {
  const release = () => {
    active -= 1
    const next = waiting.shift()
    if (next) next()
  }
  if (active < MAX_PARALLEL) { active += 1; return Promise.resolve(release) }
  return new Promise((resolve) => waiting.push(() => { active += 1; resolve(release) }))
}
