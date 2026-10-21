#!/usr/bin/env python3
"""Reklama birjasi: kanal hududi (davlat/global) va kanal tilini aniqlash — DB'siz."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:REGION_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


from services import channel_region as R  # noqa: E402
from translations.ad_market import ad_market_parity_report  # noqa: E402

print("== Til aniqlash ==")
CASES = [
    ("Toshkent yangiliklari va eng so'nggi xabarlar kanalimiz", "uz"),
    ("Ўзбекистон янгиликлари ва ҳаёт ҳақида", "uz"),
    ("Новости Москвы и России каждый день", "ru"),
    ("Останні новини України щодня їх читають", "uk"),
    ("The best daily news and free tips for you", "en"),
    ("Türkiye haberleri ve son dakika gelişmeleri bir arada", "tr"),
    ("أخبار العالم العربي اليوم وكل يوم", "ar"),
    ("Texno", None),                                         # juda qisqa
    ("Bonjour tout le monde ceci est un canal", None),       # noma'lum lotin tili: ogohlantirish YO'Q
    ("https://t.me/abc @kanal #news 12345 67890", None),     # faqat havola/belgi
    ("Yangiliklar va the news today", None),                  # aralash (teng): ishonchsiz
]
for text, want in CASES:
    check(f"til: «{text[:34]}» -> {want}", R.detect_language(text) == want, str(R.detect_language(text)))

print("== Moslik (assess) ==")
a = R.assess("UZ", "Новости Москвы и России каждый день")
check("UZ + rus tili: mos (O'zbekistonda rus tili tabiiy)", a["fits"] is True and a["suggested"] is None)
a = R.assess("UZ", "The best daily news and free tips for you")
check("UZ + ingliz tili: mos emas, tavsiya Global", a["fits"] is False and a["suggested"] == "ZZ" and a["recommended"] == "ZZ")
a = R.assess("RU", "Toshkent yangiliklari va eng so'nggi xabarlar kanalimiz")
check("RU + o'zbek tili: mos emas, tavsiya UZ", a["fits"] is False and a["suggested"] == "UZ")
a = R.assess("TR", "Новости Москвы и России каждый день")
check("TR + rus tili: mos emas, tavsiya RU", a["fits"] is False and a["suggested"] == "RU")
a = R.assess("ZZ", "Новости Москвы и России каждый день")
check("Global: hech qachon ogohlantirmaydi", a["fits"] is True and a["suggested"] is None and a["recommended"] == "ZZ")
a = R.assess("DE", "Novosti Moskvy i Rossii kazhdyy den")
check("ro'yxatda yo'q davlat (DE) + noaniq matn: ogohlantirish yo'q", a["fits"] is None and a["suggested"] is None and a["recommended"] == "DE")
a = R.assess("DE", "Новости Москвы и России каждый день")
check("til xaritasi yo'q davlat (DE): ogohlantirmaydi (chet ellik bexuda to'silmaydi)", a["fits"] is None)
a = R.assess("US", "Toshkent yangiliklari va eng so'nggi xabarlar kanalimiz")
check("US + o'zbek tili: mos emas, tavsiya UZ", a["fits"] is False and a["suggested"] == "UZ")
a = R.assess(None, "Новости Москвы и России каждый день")
check("hudud berilmagan: til bo'yicha tavsiya (RU)", a["recommended"] == "RU")

print("== Hududlar ro'yxati ==")
regs = R.all_regions()
check("ro'yxat: mashhurlar boshida, takrorsiz, global YO'Q", regs[:3] == ["UZ", "RU", "KZ"] and len(regs) == len(set(regs)) and R.GLOBAL not in regs and len(regs) > 100)
check("valid_region: ISO-2/ZZ/kichik harf; yaroqsiz rad", R.valid_region("kz") and R.valid_region("ZZ") and not R.valid_region("XX") and not R.valid_region("") and not R.valid_region(None) and not R.valid_region(5))
from services import ad_market as svc  # noqa: E402
check("valyuta: UZ — so'm; boshqa davlat va Global — dollar", svc.owner_currency("UZ") == "UZS" and svc.owner_currency("ZZ") == "USD" and svc.owner_currency("DE") == "USD")
check("birja matnlari uz/ru/en pariteti", ad_market_parity_report()["in_sync"])
for lang in ("uz", "ru", "en"):
    from translations import market_t
    long = [k for k in ("mk_btn_use", "mk_btn_keep") if len(market_t(k, lang, name="🇺🇿 UZ")) > 22]
    check(f"[{lang}] hudud tugmalari qisqa", not long, str(long))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
