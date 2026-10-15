// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { compressImage } from './imageCompress'

const file = (name: string, type: string, size: number) => new File([new Uint8Array(size)], name, { type })
afterEach(() => vi.unstubAllGlobals())

describe('compressImage', () => {
  it('GIF, video va noma\'lum turlarga tegilmaydi', async () => {
    const gif = file('a.gif', 'image/gif', 5_000_000)
    expect(await compressImage(gif)).toBe(gif)
    const mp4 = file('a.mp4', 'video/mp4', 5_000_000)
    expect(await compressImage(mp4)).toBe(mp4)
  })
  it('createImageBitmap yo\'q yoki xato bersa asl fayl qaytadi', async () => {
    const big = file('x.jpg', 'image/jpeg', 3_000_000)
    expect(await compressImage(big)).toBe(big)
    vi.stubGlobal('createImageBitmap', vi.fn(async () => { throw new Error('bad') }))
    expect(await compressImage(big)).toBe(big)
  })
  it('kichik va yengil rasm qayta kodlanmaydi', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 800, height: 600, close: vi.fn() })))
    const small = file('s.jpg', 'image/jpeg', 100_000)
    expect(await compressImage(small)).toBe(small)
  })
  it('katta rasm 1600 px ga kichraytiriladi va JPEG bo\'ladi (natija yengilroq bo\'lsa)', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 4000, height: 3000, close: vi.fn() })))
    const dims: number[] = []
    const ctx = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: '' }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) { dims.push(this.width, this.height); return ctx as never })
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((cb) => cb(new Blob([new Uint8Array(300_000)], { type: 'image/jpeg' })))
    const big = file('IMG_001.png', 'image/png', 6_000_000)
    const out = await compressImage(big)
    expect(out).not.toBe(big)
    expect(out.type).toBe('image/jpeg')
    expect(out.name).toBe('IMG_001.jpg')
    expect(out.size).toBe(300_000)
    expect(dims).toEqual([1600, 1200])
  })
  it('siqish asldan og\'ir bo\'lsa asl qaytadi', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 3000, height: 2000, close: vi.fn() })))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillRect: vi.fn(), drawImage: vi.fn() } as never)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((cb) => cb(new Blob([new Uint8Array(900_000)])))
    const f = file('p.jpg', 'image/jpeg', 800_000)
    expect(await compressImage(f)).toBe(f)
  })
})
