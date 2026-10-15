"""Bot yuklash animatsiyasini (telegram_bot/assets/loading.gif) logodan yaratadi.

Ishlatish: python scripts/make_loading_gif.py  (Pillow kerak; natija repoga commit qilinadi).
Logo suzadi, atrofida nur halqalari urib turadi, pastda uch nuqta ketma-ket yonadi.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "miniapp" / "public" / "logo-192.png"
OUT = ROOT / "telegram_bot" / "assets" / "loading.gif"
SIZE, FRAMES, BG = 256, 24, (11, 27, 77)
RING = (90, 170, 255)


def frame(i: int, logo: Image.Image) -> Image.Image:
    t = i / FRAMES
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img, "RGBA")
    cx = cy = SIZE // 2 - 12
    for k in (0.0, 0.5):  # ikki halqa, yarim davr siljigan
        p = (t + k) % 1.0
        r = 54 + p * 54
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=RING + (int(150 * (1 - p)),), width=3)
    bob = math.sin(t * 2 * math.pi) * 5
    s = 104 + math.sin(t * 2 * math.pi) * 4
    lg = logo.resize((int(s), int(s)), Image.LANCZOS)
    img.paste(lg, (int(cx - s / 2), int(cy - s / 2 - bob)), lg)
    for n in range(3):  # nuqtalar
        phase = (t * 3 - n) % 3
        a = 255 if phase < 1 else 90
        r = 5 if phase < 1 else 4
        x = SIZE // 2 + (n - 1) * 20
        d.ellipse((x - r, SIZE - 38 - r, x + r, SIZE - 38 + r), fill=RING + (a,))
    return img


def main() -> None:
    logo = Image.open(LOGO).convert("RGBA")
    frames = [frame(i, logo) for i in range(FRAMES)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=80, loop=0, optimize=True, disposal=2)
    print(OUT, OUT.stat().st_size, "bayt")


if __name__ == "__main__":
    main()
