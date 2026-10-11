# 🌍 Dinamik ko'p davlatli kalendar arxitekturasi

> Holat: **kuchda** (2026-10). Bu hujjat bayram/mavsum ma'lumotlari qayerda
> saqlanishini, davlat bo'yicha qanday yechilishini va AI promptiga qanday
> tushishini tushuntiradi.

## 1. Nima o'zgardi

Bayram va mavsum sanalari ilgari `telegram_bot/services/uzbekistan_calendar.py`
ichida **qattiq kodlangan** Python lug'atlari edi (`_TEXT` / `_FIXED_EVENTS`).
Endi **ma'lumot** va **mantiq** ajratilgan:

| Qatlam | Joy | Vazifa |
| --- | --- | --- |
| Ma'lumot | `telegram_bot/locales/calendars/global.json` | Xalqaro sanalar: Yangi yil, 8-mart, maktabga qaytish mavsumi, Qora juma |
| Ma'lumot | `telegram_bot/locales/calendars/uz.json` | O'zbekiston milliy sanalari + hijri Hayitlar |
| Mantiq | `telegram_bot/services/calendar_service.py` | `CalendarService` — yuklash, davlat yechish, sana hisobi, AI konteksti |
| Shim | `telegram_bot/services/uzbekistan_calendar.py` | Eski chaqiruvchi sirti (100% orqaga mos), har doim `country="UZ"` |
| Kontekst | `telegram_bot/services/ai/calendar_context.py` | AI tizim promptiga davlatga mos sana bloki |
| Sozlama | `users.target_country` (ISO-3166-1 alpha-2) | Foydalanuvchining maqsad davlati, standart `UZ` |

**Yangi davlat qo'shish = bitta yangi JSON fayl.** Python kodi o'zgarmaydi.

## 2. Yechish (resolution) tartibi

```
resolve_country("uzb")        -> "UZ"     (alias / ISO-3)
resolve_country(None | "")    -> "UZ"     (STANDART)
resolve_country("jp")         -> "JP"     (profili yo'q)
resolve_country("klingon")    -> "UZ"     (tushunarsiz -> fail-safe)
resolve_country("global")     -> ""       (faqat xalqaro qatlam)

scopes_for("UZ")   -> ("global", "uz")    # global baza + milliy qatlam
scopes_for("JP")   -> ("global",)         # FALLBACK: faqat xalqaro
scopes_for("global") -> ("global",)
```

Keyinroq kelgan qatlam bir xil `key` ni **override** qiladi: `uz.json` ichida
`new_year` e'lon qilinsa, u xalqaro `new_year` ni almashtiradi (lekin faqat
shu davlat uchun). `"inherits": []` — xalqaro blokdan butunlay voz kechish.

## 3. Sana qoidalari (`when`)

```jsonc
{ "type": "fixed",       "month": 3, "day": 21 }
{ "type": "nth_weekday", "month": 11, "weekday": 4, "nth": -1 }  // 0=Du … 6=Ya
{ "type": "hijri",       "month": 10, "day": 1 }                 // tabulyar Hijri
```

* `nth_weekday` — `nth > 0` oy ichidagi N-chi, `nth < 0` oy oxiridan.
  **Qora juma = noyabrning oxirgi jumasi** (`nth: -1`), chunki "4-chi juma"
  1-noyabr jumaga to'g'ri kelgan yillarda noto'g'ri bo'ladi (2024 → 29-noyabr).
* `hijri` — tabulyar islom fuqarolik taqvimi. Rasmiy oy-ko'rish e'loni bir
  kun farq qilsa `date_overrides={"eid_al_fitr": date(2026, 4, 1)}` bilan
  tuzatiladi.
* Yangi qoida turi: `register_rule("easter", resolver)` — JSON'da darhol
  `{"type": "easter"}` ishlay boshlaydi.

Noto'g'ri yildagi yoki buzilgan `date_overrides` qiymati **e'tiborga
olinmaydi** va hisoblangan sana saqlanadi (xato sozlama bayramni yo'q
qila olmaydi).

## 4. Fail-soft kafolati

Taqvim xatosi botni, scheduler job'ini yoki AI generatsiyasini **hech qachon**
yiqa olmaydi:

* buzilgan/yaroqsiz JSON fayl → o'tkazib yuboriladi va loglanadi;
* katalog umuman yo'q → kod ichidagi minimal `_BUILTIN_GLOBAL` zaxira ishlaydi;
* yaroqsiz sana yozuvi (kalit/`when`/nom yo'q) → shu yozuv o'tkazib yuboriladi;
* noma'lum `when.type` → sana hisoblanmaydi, qolganlar ishlaydi;
* `available_countries()` faqat **kamida bitta yaroqli sanasi** bor profillarni
  ko'rsatadi ("o'lik" davlat tanlovda chiqmaydi).

## 5. AI promptiga tushishi

```python
from services.ai import facade as ai

system = ai.with_calendar_context(base_prompt, country=user_country, lang=lang)
```

Shartnoma (`utils.ai_agent.with_language` bilan bir xil): **idempotent**,
davlat almashganda eski blok yangilanadi, sana bo'lmasa hech narsa
qo'shilmaydi, hech qachon istisno bermaydi. Blok oxirida gallyutsinatsiya
qo'riqchisi bor: *"Bu sanalarni faqat MAVZU TAKLIFI sifatida ishlat; sana yoki
bayram nomini O'YLAB TOPMA va rasmiy deb taqdim etma."*

## 6. Foydalanuvchining maqsad davlati

`users.target_country VARCHAR(8) DEFAULT 'UZ'` (idempotent ALTER migratsiya
`database.py::_ddl_user_settings_and_migrations` va `schema.sql` da).

```python
db.set_user_target_country(user_id, "JP")   # yozishdan oldin normalizatsiya
db.get_user_target_country(user_id)         # saqlanmagan/xato -> "UZ"
```

Uni iste'mol qiluvchilar:

* `scheduler.uzbekistan_calendar_reminders_job` — har bir qabul qiluvchining
  davlati bo'yicha yechadi; sanalar davlat kesimida **bir marta** hisoblanadi
  (N+1 yo'q). Hech bir mavjud davlatda 3 kundan keyingi sana bo'lmasa DB
  so'rovi umuman bajarilmaydi.
* `handlers.daily_retention.resolve_calendar_event` — callback'da
  `country → UZ → global` fallback zanjiri bilan izlaydi (eslatma tugmasi
  davlat o'zgargandan keyin ham ishlaydi).

`repositories.channels_repository.get_channels_for_content_nudges` qatori
7 ustunga kengaytirildi (oxirgisi `target_country`). Eski 6 ustunli qatorlar
ham qabul qilinadi — yetishmayotgan qiymat standartga yechiladi.

## 7. Orqaga moslik

`services.uzbekistan_calendar` sirti (`get_calendar_events`,
`get_events_for_date`, `get_events_for_reminder`, `get_calendar_event`,
`calendar_reminder_text`, `calendar_post_topic`, `MOVABLE_EVENT_KEYS`,
`SEASONAL_MOVABLE_KEYS`, `UzbekistanCalendarEvent`) o'zgarmagan va
1900–2200 yillar uchun tarixiy natija bilan bire-bir teng
(`tests/calendar_multi_country_test.py` golden qo'riqchisi).

Yagona ko'rinadigan farq: UZ taqvimiga xalqaro **Qora juma** qo'shildi
(`global.json` meroslanadi) — 2026-uz uchun 13 o'rniga 14 sana.

## 8. Testlar

```bash
bash tests/run_tests.sh                      # butun suite
python tests/calendar_multi_country_test.py  # faqat shu qamrov
```
