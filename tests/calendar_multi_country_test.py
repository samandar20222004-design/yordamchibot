#!/usr/bin/env python3
"""🌍 DINAMIK KO'P DAVLATLI KALENDAR + 🌊 AI STREAMING — unit testlar.

Qamrov:
  1. JSON locale konfiguratsiyalari (global.json / uz.json) mavjud va to'g'ri;
  2. ``CalendarService`` — davlat normalizatsiyasi, qatlam (scope) zanjiri,
     inheritance/override, FALLBACK mantiqi (noma'lum davlat → faqat global,
     bo'sh → standart UZ, buzilgan JSON → fail-soft);
  3. Kengaytiruvchanlik: YANGI davlat = yangi JSON fayl (kod o'zgarmaydi),
     ``register_rule`` orqali yangi sana qoidasi;
  4. Orqaga moslik: eski ``services.uzbekistan_calendar`` sirti 1900–2200
     uchun tarixiy (golden) natija bilan bire-bir teng;
  5. AI prompt konteksti: davlatga mos blok, idempotentlik, davlat almashishi,
     gallyutsinatsiya qo'riqchisi;
  6. Token streaming + rich message drafts: tahrir chastotasi (≥ 1.05 s),
     429/RetryAfter, per-chat soatning ``AIProgressReporter`` bilan
     BO'LISHILISHI, HTML-escape va 4096 belgi chegarasi;
  7. Scheduler calendar job'i har bir foydalanuvchining maqsad davlatini
     hisobga oladi va "bo'sh kun"da DB'ga umuman tegmaydi.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

CALENDARS_DIR = ROOT / "locales" / "calendars"

PASS = FAIL = 0


def check(condition, message):
    global PASS, FAIL
    if not condition:
        FAIL += 1
        print(f"  [FAIL] {message}")
        raise AssertionError(message)
    PASS += 1
    print(f"  [OK] {message}")


# ---------------------------------------------------------------------------
# 1) JSON LOCALE KONFIGURATSIYALARI
# ---------------------------------------------------------------------------
def test_locale_calendar_files():
    print("\n-- 1) locales/calendars/*.json mavjud va to'g'ri tuzilgan --")
    for name in ("global.json", "uz.json"):
        path = CALENDARS_DIR / name
        check(path.is_file(), f"{name} fayli locales/calendars/ da mavjud")
        payload = json.loads(path.read_text(encoding="utf-8"))
        check(isinstance(payload, dict), f"{name} — JSON obyekti")
        check(payload.get("scope") == name[:-5], f"{name} scope kaliti to'g'ri")
        check(isinstance(payload.get("events"), list) and payload["events"],
              f"{name} — events ro'yxati bo'sh emas")
        for entry in payload["events"]:
            check(bool(str(entry.get("key") or "").strip()),
                  f"{name} — har bir sana kalitga ega")
            when = entry.get("when") or {}
            check(str(when.get("type")) in ("fixed", "nth_weekday", "hijri"),
                  f"{name}:{entry.get('key')} — when.type qo'llab-quvvatlanadi")
            names = entry.get("names") or {}
            check(all(str(names.get(code) or "").strip() for code in ("uz", "ru", "en")),
                  f"{name}:{entry.get('key')} — uchala tilda nomlangan")

    glob = json.loads((CALENDARS_DIR / "global.json").read_text(encoding="utf-8"))
    uz = json.loads((CALENDARS_DIR / "uz.json").read_text(encoding="utf-8"))
    global_keys = {e["key"] for e in glob["events"]}
    uz_keys = {e["key"] for e in uz["events"]}

    check({"new_year", "women_day", "black_friday", "back_to_school"} <= global_keys,
          "global.json — xalqaro sanalar: Yangi yil, 8-mart, Qora juma, maktab mavsumi")
    check({"navruz", "independence_day", "remembrance_day", "teachers_day",
           "constitution_day", "defenders_day", "eid_al_fitr", "eid_al_adha",
           "ramadan_prep", "admission_exam_season"} <= uz_keys,
          "uz.json — O'zbekiston milliy sanalari va Hayitlar")
    check(not (global_keys & uz_keys),
          "global va uz qatlamlarida dublikat kalit yo'q (aralashmagan)")
    check(uz.get("inherits") == ["global"], "uz.json — global qatlamini meros oladi")
    check(glob.get("inherits") == [], "global.json — hech narsani meros olmaydi (baza)")
    check(str(uz.get("country", {}).get("code")) == "UZ", "uz.json — davlat kodi UZ")
    check(str(glob.get("country", {}).get("code")) == "",
          "global.json — davlat kodi bo'sh (xalqaro qatlam)")
    check("title" in (glob.get("labels") or {}), "global.json — umumiy yorliqlar (labels) bor")


# ---------------------------------------------------------------------------
# 2) DAVLAT NORMALIZATSIYASI VA FALLBACK
# ---------------------------------------------------------------------------
def test_country_resolution_and_fallback():
    print("\n-- 2) CalendarService: davlat yechish + fallback mantiqi --")
    from services.calendar_service import DEFAULT_COUNTRY, CalendarService

    cal = CalendarService()
    check(DEFAULT_COUNTRY == "UZ", "standart davlat — UZ")

    # Standart (bo'sh / None) → UZ
    for value in (None, "", "   ", [], {}):
        check(cal.resolve_country(value) == "UZ",
              f"bo'sh qiymat {value!r} → standart UZ")

    # Alias / ISO-3 / lokalizatsiya qilingan nom → UZ
    for value in ("uz", "UZ", "Uz", "uzb", "UZB", "uzbekistan", "Uzbekistan",
                  "o'zbekiston", "O'ZBEKISTON", "узбекистан"):
        check(cal.resolve_country(value) == "UZ", f"alias {value!r} → UZ")

    # Noma'lum, lekin ISO-2 shaklidagi kod → o'z kodi (profil yo'q → global)
    check(cal.resolve_country("jp") == "JP", "ISO-2 shaklidagi noma'lum kod saqlanadi")
    check(cal.resolve_country("JP") == "JP", "kod katta harfda saqlanadi")

    # Tushunarsiz qiymat → fail-safe standart
    for value in ("klingon empire", "12345", "!@#", "x"):
        check(cal.resolve_country(value) == "UZ", f"tushunarsiz {value!r} → fail-safe UZ")

    # Xalqaro qatlam (fallback zanjirining oxirgi halqasi)
    check(cal.resolve_country("global") == "", "'global' → xalqaro qatlam (bo'sh kod)")

    # Qatlam zanjiri
    check(cal.scopes_for("UZ") == ("global", "uz"), "UZ → (global, uz)")
    check(cal.scopes_for("JP") == ("global",), "profili yo'q JP → FAQAT global (fallback)")
    check(cal.scopes_for(None) == ("global", "uz"), "None → standart UZ zanjiri")
    check(cal.scopes_for("global") == ("global",), "'global' → faqat xalqaro qatlam")
    check(cal.resolve_chain("JP") == ("global",), "JP uchun yechish zanjiri (global)")
    check(cal.resolve_chain("UZ") == ("global", "uz"), "UZ uchun yechish zanjiri")

    # Fallback natijasi: JP faqat xalqaro sanalarni oladi
    jp_keys = {e.key for e in cal.events(2026, "JP")}
    uz_keys = {e.key for e in cal.events(2026, "UZ")}
    global_keys = {e.key for e in cal.events(2026, "global")}
    check(jp_keys == global_keys, "JP sanalari aynan xalqaro to'plamga teng (fallback)")
    check(global_keys <= uz_keys, "UZ sanalari xalqaro to'plamni O'Z ICHIGA oladi (meroslama)")
    check("navruz" not in jp_keys and "navruz" in uz_keys,
          "milliy sana (Navro'z) JP uchun chiqmaydi")
    check("black_friday" in jp_keys and "black_friday" in uz_keys,
          "xalqaro sana (Qora juma) ikkala davlatda ham bor")
    check(cal.movable_keys("JP") == () and len(cal.movable_keys("UZ")) == 3,
          "hijri (o'zgaruvchi) sanalar faqat UZ qatlamida")
    check(cal.has_profile("UZ") and not cal.has_profile("JP") and not cal.has_profile("global"),
          "has_profile: UZ=bor, JP=yo'q, global=davlat emas")
    check("UZ" in cal.available_countries(), "available_countries — UZ ni o'z ichiga oladi")
    check(all(code for code in cal.available_countries()),
          "available_countries — bo'sh (xalqaro) kodni davlat deb ko'rsatmaydi")


# ---------------------------------------------------------------------------
# 3) SANA QOIDALARI (fixed / nth_weekday / hijri) + OVERRIDE
# ---------------------------------------------------------------------------
def test_date_rules_and_overrides():
    print("\n-- 3) Sana qoidalari: fixed / nth_weekday / hijri + rasmiy override --")
    from services.calendar_service import CalendarService, nth_weekday_of_month

    cal = CalendarService()
    events = {e.key: e for e in cal.events(2026, "UZ")}

    # fixed
    check(events["navruz"].date == date(2026, 3, 21), "fixed: Navro'z = 21-mart")
    check(events["independence_day"].date == date(2026, 9, 1), "fixed: Mustaqillik = 1-sentabr")
    check(events["constitution_day"].date == date(2026, 12, 8), "fixed: Konstitutsiya = 8-dekabr")
    check(events["new_year"].date == date(2026, 1, 1), "fixed: Yangi yil = 1-yanvar (global)")
    check(events["back_to_school"].kind == "season", "back_to_school — mavsum (bayram emas)")

    # nth_weekday — Qora juma: noyabrning OXIRGI jumasi
    real_black_friday = {2023: "2023-11-24", 2024: "2024-11-29", 2025: "2025-11-28",
                         2026: "2026-11-27", 2027: "2027-11-26", 2028: "2028-11-24"}
    for year, expected in real_black_friday.items():
        got = cal.event("black_friday", year, "UZ").date.isoformat()
        check(got == expected, f"Qora juma {year} = {expected} (haqiqiy sana)")
    check(all(cal.event("black_friday", y, "UZ").date.weekday() == 4
              for y in range(2020, 2031)), "Qora juma har doim JUMA kuniga tushadi")
    check(all(cal.event("black_friday", y, "UZ").date.month == 11
              for y in range(2020, 2031)), "Qora juma har doim noyabrda")
    check(nth_weekday_of_month(2026, 11, 4, -1) == date(2026, 11, 27),
          "nth_weekday(nth=-1) — oyning oxirgi kunini topadi")
    check(nth_weekday_of_month(2026, 11, 0, 5) == date(2026, 11, 30),
          "nth_weekday — 2026-noyabrda 5 ta dushanba bor (30-noyabr)")
    check(nth_weekday_of_month(2026, 2, 0, 5) is None,
          "nth_weekday — oyda mavjud bo'lmagan hafta raqami (2026-fevral, 5-dushanba) → None")
    check(nth_weekday_of_month(2026, 13, 0, 1) is None, "nth_weekday — noto'g'ri oy → None")

    # hijri (o'zgaruvchi) + rasmiy sana override
    check(events["eid_al_fitr"].kind == "movable", "Ro'za hayiti — o'zgaruvchi (movable)")
    check(events["ramadan_prep"].kind == "season", "Ramazon tayyorgarligi — mavsum")
    check(events["eid_al_fitr"].date != cal.event("eid_al_fitr", 2027, "UZ").date,
          "hijri sana yildan-yilga siljiydi")

    overridden = cal.events(2026, "UZ", date_overrides={"eid_al_fitr": date(2026, 4, 1)})
    check(next(e for e in overridden if e.key == "eid_al_fitr").date == date(2026, 4, 1),
          "rasmiy sana override (date) qo'llanadi")
    overridden = cal.events(2026, "UZ", date_overrides={"eid_al_fitr": "2026-04-01"})
    check(next(e for e in overridden if e.key == "eid_al_fitr").date == date(2026, 4, 1),
          "rasmiy sana override (ISO matn) qo'llanadi")
    ignored = cal.events(2026, "UZ", date_overrides={"eid_al_fitr": date(2027, 4, 1)})
    check(next(e for e in ignored if e.key == "eid_al_fitr").date == date(2026, 3, 20),
          "boshqa yilga tegishli override e'tiborga olinmaydi")
    ignored = cal.events(2026, "UZ", date_overrides={"eid_al_fitr": "buzilgan-sana"})
    check(next(e for e in ignored if e.key == "eid_al_fitr").date == date(2026, 3, 20),
          "buzilgan override qiymati hisoblangan sanani buzmaydi")

    # Yil chegarasi va saralash
    for bad_year in (1899, 2201, 0):
        try:
            cal.events(bad_year, "UZ")
            check(False, f"yil {bad_year} rad etilishi kerak")
        except ValueError:
            check(True, f"yil {bad_year} → ValueError (chegara qo'riqchisi)")
    dates = [e.date for e in cal.events(2026, "UZ")]
    check(dates == sorted(dates), "sanalar kronologik tartibda qaytariladi")
    check(cal.events_for_date("2026-03-21", "UZ")[0].key == "navruz",
          "events_for_date ISO matnni qabul qiladi")
    check(cal.events_for_date("buzilgan", "UZ") == (), "buzilgan sana → bo'sh natija")
    check([e.key for e in cal.events_for_reminder(date(2026, 3, 18), 3, "UZ")] == ["navruz"],
          "eslatma roppa-rosa 3 kun oldin")
    check(cal.events_for_reminder(None, 3, "UZ") == (), "None sana → bo'sh natija")
    check(cal.event("", 2026, "UZ") is None, "bo'sh kalit → None")
    check(cal.event("yoq_sana", 2026, "UZ") is None, "noma'lum kalit → None")


# ---------------------------------------------------------------------------
# 4) KENGAYTIRUVCHANLIK (yangi davlat = yangi JSON) VA FAIL-SOFT
# ---------------------------------------------------------------------------
def test_extensibility_and_failsoft(tmpdir):
    print("\n-- 4) Kengaytiruvchanlik: yangi davlat = yangi JSON; fail-soft --")
    from services.calendar_service import CalendarService, register_rule

    base = Path(tmpdir)
    # Haqiqiy qatlamlar nusxalanadi — shunda "buzilgan fayl qo'shilsa ham
    # mavjud davlatlar natijasi o'zgarmaydi" tekshiruvi mazmunli bo'ladi.
    for name in ("global.json", "uz.json"):
        (base / name).write_text(
            (CALENDARS_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    (base / "jp.json").write_text(json.dumps({
        "scope": "jp",
        "country": {"code": "JP", "alpha3": "JPN",
                    "aliases": ["japan", "yaponiya", "япония"],
                    "names": {"uz": "Yaponiya", "ru": "Япония", "en": "Japan"}},
        "inherits": ["global"],
        "labels": {"title": {"uz": "Yaponiya kalendari", "en": "Japan content calendar"}},
        "events": [
            {"key": "golden_week", "kind": "season",
             "names": {"uz": "Oltin hafta", "ru": "Золотая неделя", "en": "Golden Week"},
             "when": {"type": "fixed", "month": 5, "day": 3}},
            # global qatlamidagi sanani MAHALLIY nom bilan OVERRIDE qilish
            {"key": "new_year", "kind": "holiday",
             "names": {"uz": "Yangi yil (Yaponiya)", "ru": "Новый год (Япония)",
                       "en": "New Year (Japan)"},
             "when": {"type": "fixed", "month": 1, "day": 1}},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    cal = CalendarService(base_dir=base)
    check("JP" in cal.available_countries(), "yangi JSON fayl — yangi davlat (kodsiz)")
    check(cal.resolve_country("japan") == "JP", "yangi davlat aliasi ishlaydi")
    check(cal.resolve_country("JPN") == "JP", "yangi davlat ISO-3 kodi ishlaydi")
    check(cal.scopes_for("JP") == ("global", "jp"), "yangi davlat — global + o'z qatlami")
    keys = {e.key for e in cal.events(2026, "JP")}
    check("golden_week" in keys and "black_friday" in keys,
          "yangi davlat: o'z sanasi + meros qilingan xalqaro sanalar")
    check("navruz" not in keys, "yangi davlat UZ sanalarini olmaydi (izolyatsiya)")
    check(cal.event("new_year", 2026, "JP").name("en") == "New Year (Japan)",
          "key to'qnashuvida davlat qatlami globalni OVERRIDE qiladi")
    check(cal.event("new_year", 2026, "UZ").name("en") == "New Year",
          "override faqat o'sha davlatga ta'sir qiladi (UZ o'zgarmagan)")
    check(cal.country_name("JP", "en") == "Japan", "yangi davlat nomi lokalizatsiya qilingan")
    check(cal.label("title", "en", "JP") == "Japan content calendar",
          "davlatga xos yorliq (label) ishlaydi")
    check(cal.label("title", "en", "UZ").endswith("calendar")
          or cal.label("title", "en", "UZ"), "yorliq fallback — global yorlig'iga tushadi")

    # inherits: [] — xalqaro blokdan butunlay voz kechish
    (base / "iso.json").write_text(json.dumps({
        "scope": "iso",
        "country": {"code": "IS", "names": {"uz": "Ajratilgan", "ru": "Изолир.", "en": "Isolated"}},
        "inherits": [],
        "events": [{"key": "solo_day", "kind": "holiday",
                    "names": {"uz": "Yakkakun", "ru": "Соло-день", "en": "Solo day"},
                    "when": {"type": "fixed", "month": 7, "day": 7}}],
    }, ensure_ascii=False), encoding="utf-8")
    iso = CalendarService(base_dir=base)
    check({e.key for e in iso.events(2026, "IS")} == {"solo_day"},
          "inherits: [] — davlat xalqaro sanalarni olmaydi")

    # Fail-soft: buzilgan JSON → o'tkazib yuboriladi, servis yiqilmaydi
    (base / "broken.json").write_text("{ bu json emas", encoding="utf-8")
    (base / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    (base / "bad_events.json").write_text(json.dumps({
        "scope": "bad", "country": {"code": "BD"},
        "events": [{"key": "", "when": {}}, {"key": "no_when"}, {"key": "no_names",
                  "when": {"type": "fixed", "month": 1, "day": 1}}, "shunchaki-matn"],
    }), encoding="utf-8")
    broken = CalendarService(base_dir=base)
    check("BD" not in broken.available_countries(),
          "faqat yaroqsiz sanalari bo'lgan profil davlat sifatida ko'rsatilmaydi")
    check(len(broken.events(2026, "UZ")) == 14, "buzilgan fayllar UZ natijasini buzmaydi")
    check(broken.events(2026, "JP") and broken.events(2026, "global"),
          "buzilgan fayllar bo'lsa ham qolgan davlatlar ishlaydi")

    # Mavjud bo'lmagan katalog → faqat ichki zaxira (builtin global)
    missing = CalendarService(base_dir=Path(tmpdir) / "yoq")
    check(missing.events(2026, "UZ"), "katalog yo'q bo'lsa ham builtin global zaxira ishlaydi")
    check("new_year" in {e.key for e in missing.events(2026, "UZ")},
          "builtin zaxira — Yangi yil va 8-mart ni o'z ichiga oladi")

    # Yangi sana qoidasi (register_rule) — kod o'zgartirmasdan kengaytirish
    register_rule("fixed_plus_ten", lambda when, year: date(year, 2, 10))
    (base / "custom.json").write_text(json.dumps({
        "scope": "custom", "country": {"code": "CU"}, "inherits": [],
        "events": [{"key": "custom_day", "kind": "holiday",
                    "names": {"uz": "Maxsus kun", "ru": "Особый день", "en": "Custom day"},
                    "when": {"type": "fixed_plus_ten"}}],
    }, ensure_ascii=False), encoding="utf-8")
    custom = CalendarService(base_dir=base)
    check(custom.event("custom_day", 2026, "CU").date == date(2026, 2, 10),
          "register_rule — yangi when.type qoidasi ishlaydi")

    # Noma'lum when.type → sana hisoblanmaydi, lekin servis yiqilmaydi
    (base / "unknown_rule.json").write_text(json.dumps({
        "scope": "unk", "country": {"code": "UK"}, "inherits": [],
        "events": [{"key": "mystery", "kind": "holiday",
                    "names": {"uz": "Sir", "ru": "Тайна", "en": "Mystery"},
                    "when": {"type": "not_a_real_rule"}}],
    }, ensure_ascii=False), encoding="utf-8")
    unknown = CalendarService(base_dir=base)
    check(unknown.events(2026, "UK") == (), "noma'lum when.type → sana yo'q (yiqilish yo'q)")
    check(len(unknown.events(2026, "UZ")) == 14,
          "noma'lum qoidali profil boshqa davlatlarga ta'sir qilmaydi")


# ---------------------------------------------------------------------------
# 5) ORQAGA MOSLIK (GOLDEN REGRESSIYA)
# ---------------------------------------------------------------------------
#: 2026-yil uchun tarixiy (refaktorgacha bo'lgan) UZ natijasi — bire-bir qo'riq.
GOLDEN_UZ_2026 = [
    ("new_year", "2026-01-01", "holiday"),
    ("defenders_day", "2026-01-14", "holiday"),
    ("ramadan_prep", "2026-01-20", "season"),
    ("women_day", "2026-03-08", "holiday"),
    ("eid_al_fitr", "2026-03-20", "movable"),
    ("navruz", "2026-03-21", "holiday"),
    ("remembrance_day", "2026-05-09", "holiday"),
    ("eid_al_adha", "2026-05-27", "movable"),
    ("admission_exam_season", "2026-06-01", "season"),
    ("back_to_school", "2026-08-15", "season"),
    ("independence_day", "2026-09-01", "holiday"),
    ("teachers_day", "2026-10-01", "holiday"),
    ("constitution_day", "2026-12-08", "holiday"),
]


def test_backward_compatibility():
    print("\n-- 5) Orqaga moslik: eski uzbekistan_calendar sirti o'zgarmagan --")
    import services.uzbekistan_calendar as uz
    from services.calendar_service import CalendarEvent

    check(uz.UzbekistanCalendarEvent is CalendarEvent,
          "UzbekistanCalendarEvent — CalendarEvent bilan aynan bir klass")
    check(uz.MOVABLE_EVENT_KEYS == ("eid_al_fitr", "eid_al_adha", "ramadan_prep"),
          "MOVABLE_EVENT_KEYS tartibi va tarkibi saqlangan")
    check(uz.SEASONAL_MOVABLE_KEYS == frozenset({"ramadan_prep"}),
          "SEASONAL_MOVABLE_KEYS saqlangan")
    check(uz.SUPPORTED_LANGS == ("uz", "ru", "en"), "SUPPORTED_LANGS saqlangan")

    legacy = [(e.key, e.date.isoformat(), e.kind)
              for e in uz.get_calendar_events(2026) if e.key != "black_friday"]
    check(legacy == GOLDEN_UZ_2026, "2026 UZ natijasi golden qiymat bilan bire-bir teng")

    # Bir nechta yil uchun ham barqarorlik (hijri hisob deterministik)
    check(uz.get_calendar_event("ramadan_prep", 2025).date.isoformat() == "2025-01-31",
          "2025 Ramazon tayyorgarligi — tarixiy qiymat")
    check(uz.get_calendar_event("eid_al_adha", 2025).date.isoformat() == "2025-06-07",
          "2025 Qurbon hayiti — tarixiy qiymat")
    check(uz.get_calendar_event("ramadan_prep", 2027).date.isoformat() == "2027-01-10",
          "2027 Ramazon tayyorgarligi — tarixiy qiymat")
    for year in range(2020, 2031):
        movable = [e for e in uz.get_calendar_events(year)
                   if e.key in ("eid_al_fitr", "eid_al_adha", "ramadan_prep")]
        check(len(movable) == 3, f"{year} — uchala hijri sana ham hisoblandi")

    navruz = uz.get_calendar_event("navruz", 2026)
    check(uz.calendar_reminder_text(navruz, "uz").startswith("🗓 3 kundan keyin"),
          "o'zbekcha eslatma matni o'zgarmagan")
    check("Через 3 дня" in uz.calendar_reminder_text(navruz, "ru"),
          "ruscha eslatma matni o'zgarmagan")
    check("in 3 days" in uz.calendar_reminder_text(navruz, "en"),
          "inglizcha eslatma matni o'zgarmagan")
    check(uz.calendar_post_topic(navruz, "uz") ==
          "Navro'z munosabati bilan kanal uchun samimiy tabrik yoki mavzuviy post yoz.",
          "Magic Post mavzu matni o'zgarmagan")
    check(uz.get_calendar_events(2026, country="UZ") == uz.get_calendar_events(2026),
          "eski imzo (country'siz) standart UZ ni beradi")

    # Eski ichki yordamchilar ham import qilinadi (monkeypatch sirti)
    check(callable(uz._hijri_to_gregorian) and callable(uz._coerce_date),
          "ichki yordamchilar (_hijri_to_gregorian / _coerce_date) qayta eksport qilingan")
    check(uz._hijri_to_gregorian(1447, 10, 1) == date(2026, 3, 20),
          "hijri → grigorian konversiyasi tarixiy natijani beradi")


# ---------------------------------------------------------------------------
# 6) AI PROMPT KALENDAR KONTEKSTI
# ---------------------------------------------------------------------------
def test_ai_prompt_calendar_context():
    print("\n-- 6) AI promptlar davlatga mos kalendar kontekstini yutadi --")
    from services.ai import calendar_context as ai
    from services.ai.calendar_context import (
        AI_CALENDAR_MARKER, calendar_directive, strip_calendar_directive,
        supported_countries, with_calendar_context,
    )

    anchor = date(2026, 10, 10)
    uz_block = calendar_directive("UZ", "uz", today=anchor)
    check(uz_block, "UZ uchun kalendar bloki BO'SH EMAS (fail-soft xatoni yashirmaydi)")
    check(AI_CALENDAR_MARKER in uz_block and "END OF CALENDAR CONTEXT" in uz_block,
          "blok marker bilan o'ralgan (idempotentlik uchun)")
    check("Navro'z" not in uz_block and "Qora juma" in uz_block,
          "faqat yaqin (90 kun ichidagi) sanalar ko'rsatiladi")
    check("MAVZU TAKLIFI" in uz_block, "gallyutsinatsiya qo'riqchisi (o'ylab topma) bor")
    check("2026-11-27" in uz_block and "2026-12-08" in uz_block,
          "Qora juma va Konstitutsiya kunlari ISO sanada ko'rsatilgan")

    jp_block = calendar_directive("JP", "en", today=anchor)
    check("Black Friday" in jp_block and "Constitution Day" not in jp_block,
          "JP uchun blok — faqat xalqaro sanalar (fallback)")
    check(uz_block != jp_block, "davlatga qarab blok mazmuni farq qiladi")
    ru_block = calendar_directive("UZ", "ru", today=anchor)
    check("Чёрная пятница" in ru_block, "blok foydalanuvchi tilida lokalizatsiya qilinadi")

    # Idempotentlik + davlat almashishi
    base = "You are a social media writer."
    once = with_calendar_context(base, "UZ", "uz", today=anchor)
    twice = with_calendar_context(once, "UZ", "uz", today=anchor)
    check(once == twice, "bir xil davlat qayta qo'shilsa prompt O'ZGARMAYDI (idempotent)")
    check(once.count(AI_CALENDAR_MARKER) == 1, "blok faqat bitta (ko'paymaydi)")
    swapped = with_calendar_context(once, "JP", "en", today=anchor)
    check(swapped.count(AI_CALENDAR_MARKER) == 1, "davlat almashganda blok ko'paymaydi")
    check("Black Friday" in swapped and "Konstitutsiya" not in swapped,
          "davlat almashganda ESKI blok o'chirilib yangisi qo'yiladi")
    check(swapped.endswith(base), "asl prompt matni blok ostida saqlanadi")
    check(with_calendar_context("", "UZ", "uz", today=anchor).startswith("====="),
          "bo'sh promptga blok toza qo'shiladi")
    check(strip_calendar_directive(once) == base, "strip — blokni to'liq olib tashlaydi")
    check(with_calendar_context(None, "UZ", "uz", today=anchor),
          "None prompt → faqat blok (istisno yo'q)")

    # Fasad orqali ham bir xil ishlaydi
    check(ai.with_calendar_context(base, "UZ", "uz", today=anchor) == once,
          "calendar_context.with_calendar_context — bir xil natija")
    check(ai.supported_countries() == supported_countries() == ("UZ",),
          "supported_countries — JSON profillaridan olinadi")
    check(ai.resolve_prompt_country("uzb") == "UZ", "resolve_prompt_country — normalizatsiya")
    ctx = ai.calendar_prompt_context("UZ", "uz", today=anchor)
    check(ctx["country"] == "UZ" and ctx["events"] >= 1, "calendar_prompt_context telemetriyasi")

    # Haqiqiy integratsiya: kontent-reja prompti davlatga mos sanalarni yutadi
    from services.ai.planner import build_plan_prompt
    plain = build_plan_prompt("Kanal", 7, 1, "uz")
    check(build_plan_prompt("Kanal", 7, 1, "uz", None) == plain,
          "country=None bo'lsa reja prompti BITTABAYT o'zgarmaydi (orqaga moslik)")
    with_country = build_plan_prompt("Kanal", 7, 1, "uz", "UZ")
    check(with_country.startswith(plain), "davlat bloki prompt OXIRIGA qo'shiladi")
    check("Qora juma" in with_country, "UZ rejasi — mahalliy/xalqaro sanalarni ko'radi")
    jp_prompt = build_plan_prompt("Kanal", 7, 1, "en", "JP")
    check("Black Friday" in jp_prompt and "Constitution Day" not in jp_prompt,
          "JP rejasi — faqat xalqaro sanalar (fallback)")
    check(build_plan_prompt("Kanal", 7, 1, "en", "JP") != with_country,
          "davlatga qarab reja prompti farq qiladi")

    # Uzoq kelajakda sana bo'lmasa — bo'sh blok (prompt shishmaydi)
    check(calendar_directive("JP", "en", today=date(2026, 6, 1), days=5) == "",
          "yaqin sana bo'lmasa blok bo'sh qaytadi")
    check(with_calendar_context(base, "JP", "en", today=date(2026, 6, 1), days=5) == base,
          "bo'sh kontekst prompt'ga hech narsa qo'shmaydi")


# ---------------------------------------------------------------------------
# 7) TOKEN STREAMING + RICH MESSAGE DRAFTS
# ---------------------------------------------------------------------------
def test_token_streaming_rate_limits():
    print("\n-- 7) Token streaming: tahrir chastotasi va flood-control --")
    from services.ai.progress import MIN_EDIT_INTERVAL_FLOOR, AIProgressReporter
    from services.ai.streaming import (
        AIStreamRenderer, TokenStreamBuffer, close_open_tags, truncate_message,
    )

    # --- TokenStreamBuffer: sof mantiq, soxta soat bilan ---
    clock_now = {"t": 0.0}
    buffer = TokenStreamBuffer(min_edit_interval=1.0, min_delta_chars=10,
                               chat_id=1, time_fn=lambda: clock_now["t"])
    check(buffer.minimum_edit_interval >= MIN_EDIT_INTERVAL_FLOOR,
          "tahrir oralig'i Telegram chegarasidan (1.05 s) pastga tushirilmaydi")
    buffer.feed("salom")
    check(not buffer.is_due(now=0.0), "yetarli yangi matn bo'lmasa tahrir YO'Q")
    buffer.feed(" dunyo bu juda uzun matn")
    check(buffer.pending_chars >= 10 and buffer.is_due(now=0.0),
          "yetarli matn yig'ilgach tahrirga ruxsat")
    buffer.mark_edit(now=0.0)
    check(buffer.pending_chars == 0, "tahrirdan keyin hisoblagich tozalanadi")
    buffer.feed("yana bir oz matn qo'shamiz")
    check(not buffer.is_due(now=0.5), "1.05 s ichida ikkinchi tahrir TAQIQLANADI")
    check(buffer.is_due(now=1.05), "oralikdan keyin tahrirga ruxsat")

    # 429 / RetryAfter
    buffer.block_for(30.0, now=1.05)
    check(not buffer.is_due(now=5.0), "RetryAfter oynasida tahrir bloklanadi")
    check(buffer.is_due(now=40.0), "RetryAfter oynasi tugagach tahrirga ruxsat")
    check(buffer.is_due(now=0.0, force=True) is False,
          "force ham chastota qo'riqchisini chetlab o'tmaydi")

    # --- AIStreamRenderer: tahrirlar soni vaqt bilan chegaralangan ---
    async def run_stream(n_tokens=40, min_interval=0.05):
        sent = []

        async def editor(text):
            sent.append((time.monotonic(), text))

        async def tokens():
            for i in range(n_tokens):
                yield f"token-{i} "

        renderer = AIStreamRenderer(editor=editor, min_edit_interval=min_interval,
                                    min_delta_chars=8, cursor="", max_final_wait=0.0)
        renderer.buffer.time_fn = lambda: time.monotonic()
        result = await renderer.render(tokens())
        return result, sent

    result, sent = asyncio.run(run_stream(60, min_interval=0.05))
    check(result.completed and result.ok, "token oqimi muvaffaqiyatli yakunlandi")
    check(result.tokens == 60, "barcha tokenlar iste'mol qilindi")
    check("token-59" in result.text, "yakuniy matn oxirgi tokenni o'z ichiga oladi")
    check(result.edits <= 30, f"tahrirlar soni chastota bilan chegaralangan ({result.edits})")
    check(result.edits >= 1, "kamida bitta tahrir yuborildi")
    check(all("▌" not in text for _, text in sent), "cursor='' bo'lsa kursor chizilmaydi")
    check(sent[-1][1].rstrip().endswith("token-59"), "oxirgi tahrir — to'liq matn")

    # 429 paytida oqim DAVOM ETADI va generatsiya yiqilmaydi
    async def run_throttled():
        attempts = {"n": 0}

        class RetryAfter(Exception):
            retry_after = 2

        async def editor(text):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise RetryAfter("429 Too Many Requests")

        async def tokens():
            for i in range(30):
                yield "abcdefgh"

        renderer = AIStreamRenderer(editor=editor, min_edit_interval=1.05,
                                    min_delta_chars=8, cursor="", max_final_wait=0.0)
        return await renderer.render(tokens()), attempts

    throttled, attempts = asyncio.run(run_throttled())
    check(throttled.completed, "429 bo'lsa ham oqim yakuniga yetadi")
    check(throttled.throttled >= 1, "RetryAfter hodisalari hisobga olindi")
    check(throttled.tokens == 30, "429 tokenlarni yo'qotmaydi")

    # Xatoli editor — generatsiya yiqilmaydi
    async def run_broken_editor():
        async def editor(text):
            raise RuntimeError("network down")

        async def tokens():
            for i in range(5):
                yield "salom"

        renderer = AIStreamRenderer(editor=editor, min_edit_interval=1.05,
                                    min_delta_chars=1, cursor="", max_final_wait=0.0)
        return await renderer.render(tokens())

    broken = asyncio.run(run_broken_editor())
    check(broken.completed and broken.text, "buzilgan editor natijani yo'qotmaydi")
    check(broken.error == "RuntimeError", "xato turi qayd etiladi (yashirilmaydi)")

    # Editor yo'q (message.edit_text mavjud emas) → baribir matn qaytadi
    async def run_no_editor():
        async def tokens():
            yield "matn"
        return await AIStreamRenderer(editor=None, cursor="").render(tokens())

    no_editor = asyncio.run(run_no_editor())
    check(no_editor.completed and no_editor.edits == 0, "editor bo'lmasa tahrir qilinmaydi")

    # --- truncate / tag yopish ---
    check(len(truncate_message("a" * 5000, 4096)) <= 4096, "4096 belgi chegarasi saqlanadi")
    check(truncate_message("qisqa") == "qisqa", "qisqa matn o'zgarmaydi")
    check(close_open_tags("<b>ochiq").endswith("</b>"), "ochiq <b> tegi yopiladi")
    cut = truncate_message("<b>" + "x" * 5000, 200)
    check(cut.count("<b>") == cut.count("</b>"), "kesilgan matnda teglar muvozanatda")
    check(cut.endswith("…"), "qisqartirilgan matn ellipsis bilan tugaydi")

    # --- AIProgressReporter integratsiyasi: BITTA per-chat soat ---
    async def run_shared_clock():
        from services.ai.progress import ChatEditClock
        shared = ChatEditClock()
        reporter = AIProgressReporter(minimum_edit_interval=1.05, chat_id=777, clock=shared)
        reporter._record_edit("stage", at=1000.0)
        renderer = AIStreamRenderer(reporter=reporter, cursor="", max_final_wait=0.0)
        check(renderer._clock is shared, "stream — reporter'ning per-chat soatini BO'LISHADI")
        check(renderer.chat_id == 777, "stream — reporter chat'ini meros oladi")
        check(renderer.minimum_edit_interval >= reporter.minimum_edit_interval,
              "stream chastotasi reporter'nikidan qat'iy emas")
        slot = renderer.buffer.next_edit_slot()
        check(abs(slot - 1001.05) < 1e-6,
              "stream reporter'ning oxirgi tahrir vaqtini hisobga oladi")
        return reporter, renderer

    asyncio.run(run_shared_clock())

    async def run_reporter_stream():
        sent = []

        class FakeMessage:
            chat_id = 42

            async def edit_text(self, text):
                sent.append(text)

        reporter = AIProgressReporter(lang="en", minimum_edit_interval=1.05)
        reporter.attach_message(FakeMessage())

        async def tokens():
            for i in range(20):
                yield "word "

        result = await reporter.stream(tokens, min_delta_chars=5, cursor="", max_final_wait=0.0)
        return reporter, result, sent

    reporter, streamed, sent = asyncio.run(run_reporter_stream())
    check(streamed.completed, "AIProgressReporter.stream — oqimni yakunlaydi")
    check(reporter.edit_count >= 1, "reporter tahrirlar sonini o'z hisobiga qo'shadi")
    check(reporter.lang == "en", "reporter tili saqlanadi (yangi holat maydoni)")
    check(sent and sent[-1].rstrip().endswith("word"), "yakuniy matn xabarga yozildi")


def test_rich_message_drafts():
    print("\n-- 8) Rich message drafts: HTML-escape, tugmalar, 4096 chegarasi --")
    from services.ai.streaming import RichButton, RichMessageDraft, render_rich_draft

    draft = (RichMessageDraft(lang="uz")
             .add_title("📊 Hisobot")
             .add_text("<script>alert(1)</script>", "bold")
             .add_bullets(["Ko'rishlar: 1 240", "", "Obunachi: +38"])
             .add_divider()
             .add_footer("AI tomonidan tayyorlandi")
             .add_button("📅 Reja", callback_data="cal_days:7")
             .add_button("🔗 Kanal", url="https://t.me/example")
             .add_button("", callback_data="ignored")
             .add_button("Bog'lamsiz"))

    rendered = draft.render()
    check("<b>📊 Hisobot</b>" in rendered.text, "sarlavha qalin tegda")
    check("&lt;script&gt;" in rendered.text and "<script>" not in rendered.text,
          "foydalanuvchi matni HTML-escape qilinadi (injection yo'q)")
    bullets = [line for line in rendered.text.splitlines() if line.startswith("•")]
    check(len(bullets) == 2 and bullets[0] == "• Ko'rishlar: 1 240",
          "ro'yxat elementlari chiziladi va bo'sh elementlar o'tkazib yuboriladi")
    check("<i>AI tomonidan tayyorlandi</i>" in rendered.text, "footer kursivda")
    check(len(rendered.buttons) == 1 and len(rendered.buttons[0]) == 2,
          "tugmalar bitta qatorda (2 ta), yaroqsiz tugmalar olib tashlangan")
    check(rendered.parse_mode == "HTML", "parse_mode — HTML")

    kwargs = draft.telegram_kwargs(chat_id=123)
    check(kwargs["text"] == rendered.text and kwargs["chat_id"] == 123,
          "telegram_kwargs — matn va qo'shimcha parametrlar")
    check("reply_markup" in kwargs, "telegram o'rnatilganda reply_markup quriladi")
    markup = kwargs["reply_markup"]
    check(markup.inline_keyboard[0][0].callback_data == "cal_days:7",
          "callback tugma to'g'ri quriladi")
    check(markup.inline_keyboard[0][1].url == "https://t.me/example",
          "URL tugma to'g'ri quriladi")
    check(len(markup.inline_keyboard[0][0].callback_data) <= 64,
          "callback_data 64 belgi chegarasida")

    # Uzun matn → Telegram chegarasi + teglar yopilgan
    long_draft = RichMessageDraft().add_text("x" * 9000).add_text("<b>ochiq", "bold")
    check(len(long_draft.text) <= 4096, "uzun qoralama 4096 belgiga sig'adi")
    check(long_draft.text.count("<b>") == long_draft.text.count("</b>"),
          "uzun qoralamada teglar muvozanatda")
    check(RichMessageDraft().is_empty, "bo'sh qoralama — is_empty")
    check(not draft.is_empty, "to'ldirilgan qoralama — is_empty emas")
    check(RichButton("x").callback_data == "", "RichButton standart qiymatlari")

    # Bir tahrir bilan chiqarish (oqimsiz)
    async def run_render():
        sent = []

        async def editor(text):
            sent.append(text)

        result = await render_rich_draft(editor, draft)
        return result, sent

    result, sent = asyncio.run(run_render())
    check(result.completed and result.edits == 1, "rich draft — BITTA tahrir bilan chiqadi")
    check(sent and sent[0] == rendered.text, "yuborilgan matn qoralama bilan bir xil")


# ---------------------------------------------------------------------------
# 9) SCHEDULER: DAVLATGA MOS ESLATMA JOBI
# ---------------------------------------------------------------------------
def test_scheduler_country_aware_job():
    print("\n-- 9) Scheduler calendar job — har bir foydalanuvchining davlati --")
    import scheduler
    from services.calendar_service import get_calendar_service

    cal = get_calendar_service()
    fake_bot = type("FakeBot", (), {"send_message": AsyncMock()})()

    async def run_multi_country(today, rows):
        fake_bot.send_message.reset_mock()

        async def fake_run_db(fn, *args):
            return rows

        with patch.object(scheduler.db, "run_db", new=fake_run_db):
            return await scheduler.uzbekistan_calendar_reminders_job(fake_bot, today=today)

    # 2026-03-18 → 3 kundan keyin 21-mart: UZ'da Navro'z, JP'da hech narsa
    rows = [
        ("-10001", "UZ kanal", 501, "uz", [], "", "UZ"),
        ("-10002", "JP kanal", 502, "en", [], "", "JP"),
        ("-10003", "Eski 6-ustun qator", 503, "ru", [], ""),   # orqaga moslik
    ]
    result = asyncio.run(run_multi_country(date(2026, 3, 18), rows))
    calls = [c.kwargs for c in fake_bot.send_message.await_args_list]
    check(result == {"sent": 2, "skipped": 0}, "faqat mos davlatli foydalanuvchilarga yuborildi")
    check([c["chat_id"] for c in calls] == [501, 503],
          "UZ (va eski 6-ustunli standart) qatorlarga yuborildi, JP'ga yo'q")
    check("Navro'z" in calls[0]["text"], "o'zbek foydalanuvchi — o'zbekcha Navro'z")
    check("Навруз" in calls[1]["text"], "rus tilidagi foydalanuvchi — ruscha Navruz")

    # 2026-11-24 → 3 kundan keyin 27-noyabr (Qora juma): JP ham, UZ ham oladi
    result = asyncio.run(run_multi_country(date(2026, 11, 24), rows))
    calls = [c.kwargs for c in fake_bot.send_message.await_args_list]
    check(result == {"sent": 3, "skipped": 0},
          "xalqaro sanada (Qora juma) barcha davlatlar eslatma oladi")
    check([c["chat_id"] for c in calls] == [501, 502, 503], "uchala kanal ham qamrab olindi")
    check("Black Friday" in calls[1]["text"], "JP foydalanuvchi — xalqaro sana (fallback)")
    check("Qora juma" in calls[0]["text"], "UZ foydalanuvchi — o'zbekcha Qora juma")

    # "Bo'sh kun": hech bir davlatda sana yo'q → DB'ga UMUMAN tegilmaydi
    fake_bot.send_message.reset_mock()

    async def must_not_be_called(fn, *args):
        raise AssertionError("bo'sh kunda DB so'rovi bajarilmasligi kerak")

    with patch.object(scheduler.db, "run_db", new=must_not_be_called):
        result = asyncio.run(scheduler.uzbekistan_calendar_reminders_job(
            fake_bot, today=date(2026, 3, 1)))
    check(result == {"sent": 0, "skipped": 0},
          "bo'sh kunda DB so'rovisiz {sent:0, skipped:0} qaytadi")
    check(fake_bot.send_message.await_count == 0, "bo'sh kunda hech narsa yuborilmaydi")

    # Eski shartnoma (6-ustunli qator + (notify_uzbek_calendar, None)) saqlangan
    observed = {}

    async def spy_run_db(fn, *args):
        observed["fn"] = fn
        observed["args"] = args
        return [("-10003", "Navruz channel", 502, "en", [], "")]

    async def run_legacy_contract():
        fake_bot.send_message.reset_mock()
        with patch.object(scheduler.db, "run_db", new=spy_run_db):
            return await scheduler.uzbekistan_calendar_reminders_job(
                fake_bot, today=date(2026, 3, 18))

    result = asyncio.run(run_legacy_contract())
    check(observed["fn"] is scheduler.db.get_channels_for_content_nudges,
          "eski repository funksiyasi chaqiriladi")
    check(observed["args"] == ("notify_uzbek_calendar", None),
          "eski sozlama kaliti va argumentlar o'zgarmagan")
    check(result == {"sent": 1, "skipped": 0}, "eski 6-ustunli qator ham ishlaydi")
    check("in 3 days" in fake_bot.send_message.await_args.kwargs["text"],
          "eski inglizcha eslatma matni saqlangan")

    # bot=None → hech narsa qilinmaydi
    check(asyncio.run(scheduler.uzbekistan_calendar_reminders_job(None)) ==
          {"sent": 0, "skipped": 0}, "bot=None → {sent:0, skipped:0}")

    # _nudge_row_values: 6 va 7 ustun, dict va buzilgan qator
    check(scheduler._nudge_row_values(("a", "b", 1, "uz", [], ""))[6] is None,
          "6-ustunli qator → target_country None (standartga yechiladi)")
    check(scheduler._nudge_row_values(("a", "b", 1, "uz", [], "", "UZ"))[6] == "UZ",
          "7-ustunli qator → target_country o'qiladi")
    check(scheduler._nudge_row_values({"channel_id": "a", "user_id": 1,
                                       "target_country": "JP"})[6] == "JP",
          "dict qator → target_country o'qiladi")
    check(scheduler._nudge_row_values(None)[2] is None, "buzilgan qator → xavfsiz default")
    check(len(cal.events(2026, "UZ")) == 14, "2026 UZ sanalari soni (13 milliy + Qora juma)")


# ---------------------------------------------------------------------------
# 10) REPOSITORY: MAQSAD DAVLAT NORMALIZATSIYASI
# ---------------------------------------------------------------------------
def test_target_country_repository():
    print("\n-- 10) Repository: users.target_country normalizatsiyasi --")
    import database as db

    check(db.DEFAULT_TARGET_COUNTRY == "UZ", "standart maqsad davlat — UZ")
    check(db.TARGET_COUNTRY_MAX_LEN == 8, "ustun kengligi chegarasi (VARCHAR(8))")
    check(db.TARGET_COUNTRY_COLUMN == "target_country",
          "maqsad davlat ustuni nomi — users.target_country")
    # Profili YO'Q davlat nomi fail-safe holda standartga tushadi (JP nomi
    # faqat locales/calendars/jp.json qo'shilgandan keyin taniladi — 4-bo'lim).
    for value, expected in (("uz", "UZ"), ("UZB", "UZ"), (None, "UZ"),
                            ("", "UZ"), ("klingon", "UZ"), ("uzb", "UZ"),
                            ("japan", "UZ"), ("JP", "JP"), ("jp", "JP")):
        check(db.normalize_target_country(value) == expected,
              f"normalize_target_country({value!r}) → {expected}")
    check(len(db.normalize_target_country("uzbekistan")) <= db.TARGET_COUNTRY_MAX_LEN,
          "natija ustun kengligiga sig'adi")
    check(callable(db.get_user_target_country) and callable(db.set_user_target_country),
          "get/set_user_target_country database.py orqali eksport qilingan")

    # Bazaga ulanish bo'lmasa ham standart qaytadi (fail-soft)
    with patch.object(db, "db_cursor", side_effect=RuntimeError("DB down")):
        check(db.get_user_target_country(1) == "UZ", "DB xatosida → standart UZ")
        check(db.set_user_target_country(1, "UZ") is False, "DB xatosida → False (crash yo'q)")


def main():
    print("== 🌍 Dinamik ko'p davlatli kalendar + 🌊 AI streaming ==")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_locale_calendar_files()
        test_country_resolution_and_fallback()
        test_date_rules_and_overrides()
        test_extensibility_and_failsoft(tmpdir)
        test_backward_compatibility()
        test_ai_prompt_calendar_context()
        test_token_streaming_rate_limits()
        test_rich_message_drafts()
        test_scheduler_country_aware_job()
        test_target_country_repository()
    print(f"\nJAMI: o'tdi={PASS}, xato={FAIL}")
    if FAIL:
        sys.exit(1)
    print("🌍 DINAMIK KALENDAR + 🌊 STREAMING — TESTLAR 100% YASHIL ✔")


if __name__ == "__main__":
    main()
