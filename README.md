# PostAssist (yordamchibot)

Telegram kanallar uchun bot: postlarni qo'lda yoki AI yordamida yozish,
rejalashtirish, kanalga vaqtida joylash, statistika va PRO obuna.

* **Bot imkoniyatlari (foydalanuvchi uchun):** [telegram_bot/README.md](telegram_bot/README.md)
* **Serverga chiqarish:** [DEPLOYMENT.md](DEPLOYMENT.md)
* **Barcha muhit o'zgaruvchilari:** [.env.example](.env.example)
* **Dasturchi hujjatlari:** [arxitektura](docs/ARCHITECTURE.md) · [papkalar](docs/PROJECT_STRUCTURE.md) · [yangi funksiya qayerga](docs/DEVELOPMENT.md) · [Mini App API](docs/API.md) · [Mini App ⇄ bot](docs/MINIAPP.md) · [testlar](docs/TESTING.md) · [tozalash auditi](docs/CLEANUP_AUDIT.md)
* **Payme integratsiyasi:** [docs/PAYME.md](docs/PAYME.md) · **Bayram kalendari:** [docs/CALENDAR.md](docs/CALENDAR.md)

Texnologiyalar: Python 3.11, [python-telegram-bot](https://python-telegram-bot.org/) 21+,
PostgreSQL (psycopg2), APScheduler, aiohttp. Redis ixtiyoriy.
AI: Gemini → Groq → OpenRouter → boshqa provayderlar (birinchisi ishlamasa keyingisi).

---

## Lokal ishga tushirish

```bash
cd telegram_bot
python3 -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env        # BOT_TOKEN, DATABASE_URL, ADMIN_IDS ni to'ldiring
set -a; . ../.env; set +a         # ilova .env ni o'zi o'qimaydi — shell'ga eksport qilinadi
python main.py
```

Minimal sozlamalar: `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_IDS` va kamida bitta AI
kaliti (`GEMINI_API_KEY`, `GROQ_API_KEY` yoki `OPENROUTER_API_KEY`).
Jadvallar birinchi ishga tushishda `schema.sql` dan avtomatik yaratiladi.

---

## Papkalar

```
telegram_bot/
├── main.py              Kirish nuqtasi: Application, himoya qatlami, rejalashtiruvchi ishlari
├── config.py            Barcha muhit o'zgaruvchilari shu yerda o'qiladi
├── database.py          Ulanish puli, tranzaksiyalar, sxema; repositories/ funksiyalarini qayta eksport qiladi
├── schema.sql           Ma'lumotlar bazasi sxemasi (idempotent)
├── scheduler.py         Vaqti kelgan postlarni kanalga yuborish (har daqiqa)
├── menu_commands.py     ☰ «Menu» tugmasidagi buyruqlar ro'yxati
├── handlers/            Telegram oqimlari: har bir fayl — bitta bo'lim (menyu, post, kanal, admin…)
│   └── __init__.py      Barcha handlerlarni ro'yxatdan o'tkazish (register_all_handlers)
├── keyboards/           Tugmalar: default.py (pastki menyu), inline.py (xabar ostidagi tugmalar),
│                        callback_data.py (callback prefikslari va 64-bayt cheklovi)
├── repositories/        SQL so'rovlar — jadval/domen bo'yicha (users, channels, posts, payments…)
├── services/            Biznes mantiq: to'lov, obuna, kvota, RBAC, kesh, URL xavfsizligi…
│   ├── ai/              AI: provayderlar, promptlar, validator, kvota, progress
│   │   └── engine/      Yagona AI shlyuz (gateway.py): marshrut, kesh, retry, telemetriya
│   ├── channels/        Kanal tahlili: DNA, eng yaxshi vaqt, monitoring, jamoa
│   ├── payments/        Payme provayderi va webhook
│   └── sources/         RSS va havolalardan kontent olish
├── middlewares/         Rate limit, RBAC (resursga ruxsat), FSM tozalash
├── locales/             Asosiy matnlar: translations.py (uz/ru), en_overlay.py (en)
├── translations/        Bo'limlar bo'yicha matnlar (har birida uz/ru/en)
├── utils/               Umumiy yordamchilar: HTML xavfsizligi, sana formati, AI agent, web server…
└── staging/             Yuklama testlari uchun soxta Telegram API serveri
tests/                   Testlar (har biri mustaqil skript) va run_tests.sh
scripts/                 Deploy, migratsiya, preflight va xavfsizlik tekshiruvi skriptlari
```

---

## So'rov qanday ishlaydi

```
Telegram update
  → main.GuardedApplication.process_update
       eski xabarni tashlash · tugmaga darhol javob · foydalanuvchi qulfi ·
       rate limit · vaqt chegarasi · sekin javobni logga yozish
  → middlewares/rbac.py      (o'zgartiruvchi tugmalar uchun resursga ruxsat)
  → handlers/<bo'lim>.py      (oqim mantiqi, ekran matni va tugmalar)
  → services/…               (biznes qoidalar: kvota, to'lov, AI…)
  → database.run_db(...)      (sinxron SQL alohida thread'da)
  → repositories/…           (SQL)
```

Rejalashtirilgan postlar alohida yo'l bilan yuboriladi: `main.py` dagi
APScheduler har daqiqada `scheduler.check_and_send_posts` ni chaqiradi.

---

## Qoidalar (yangi kod yozganda)

**Bazaga murojaat.** Async handler ichida SQL funksiyani to'g'ridan-to'g'ri
chaqirmang — event loop to'xtab qoladi:

```python
rows = await db.run_db(db.get_user_channels, user_id)
```

Yangi SQL — `repositories/<domen>_repository.py` ga, `database.py` orqali eksport.
O'qish uchun `with db_cursor() as cur:` (bazaga bitta so'rov),
yozish uchun `with db_cursor(commit=True) as cur:`. Bir nechta yozuv bitta
atomik blokda bo'lishi kerak bo'lsa — `with db_transaction() as cur:`.
Qiymatlar doim parametr sifatida: `cur.execute("... WHERE id = %s", (post_id,))`.

**Egalik tekshiruvi.** Tugmadagi ID'ga ishonmang. Post/kanal ustida amal
qilishdan oldin uni `user_id` bo'yicha qayta o'qing (masalan
`get_queue_post_detail(post_id, user_id)`), topilmasa — rad eting.

**Matnlar.** Foydalanuvchiga ko'rinadigan har bir matn uch tilda bo'lishi shart:

* umumiy kalitlar — `locales/translations.py` (uz, ru) + `locales/en_overlay.py` (en),
  o'qish: `get_text("kalit", lang, nom=qiymat)`;
* bo'lim matnlari — `translations/<bo'lim>.py`, o'qish: `channels_queue_t("kalit", lang)` va h.k.

`tests/i18n_full_parity_test.py` uch tildagi kalitlar bir xilligini tekshiradi.

**HTML.** Xabarlar `parse_mode="HTML"` bilan yuboriladi. Foydalanuvchidan
kelgan har qanday matn (ism, kanal nomi, post matni) `html_escape(...)` dan
o'tishi kerak, aks holda `&` yoki `<` belgisi xabarni buzadi.

**Tugmalar.** `callback_data` 64 baytdan oshmasligi kerak — `cb(PREFIX, id)`
yordamchisidan foydalaning. Yangi prefiks `keyboards/callback_data.py` dagi
ro'yxatga qo'shiladi. Qaytarib bo'lmaydigan amallar (o'chirish) tasdiq so'rashi
kerak: `prefix:<id>` → tasdiq ekrani, `prefix:<id>:ok` → bajarish.

**Yangi bo'lim qo'shish:**
1. Matnlar — `translations/<bo'lim>.py` (uz/ru/en).
2. Tugmalar — `keyboards/inline.py`.
3. Oqim — `handlers/<bo'lim>.py`.
4. Ro'yxatdan o'tkazish — `handlers/__init__.py` (`register_all_handlers` ichida).
5. SQL bo'lsa — `repositories/` + `schema.sql`.
6. Test — `tests/<bo'lim>_test.py` va uni `tests/run_tests.sh` ga qo'shing.

---

## Testlar

```bash
pip install -r telegram_bot/requirements.txt -r tests/requirements-test.txt
cd telegram_bot
ruff check ..                                         # lint (ruff.toml)
BOT_TOKEN=1:x PYTHONPATH=. bash tests/run_tests.sh    # to'liq to'plam
BOT_TOKEN=1:x PYTHONPATH=. python ../tests/schema_test.py   # bitta test
```

Oxirida yiqilgan testlar ro'yxati chiqadi. Testlarning ko'pi soxta (mock)
ma'lumotlar bilan ishlaydi. Haqiqiy PostgreSQL bilan ishlaydigan qismlar
`P0_TEST_DATABASE_URL`, `STEP5_TEST_DATABASE_URL` va shunga o'xshash `*_TEST_DATABASE_URL`
o'zgaruvchilari berilganda ishga tushadi (aks holda o'tkazib yuboriladi).

---

## Tezlik bo'yicha eslatma

Javob vaqtining asosiy qismi — bazaga va Telegram'ga borib-kelish. Bot va
ma'lumotlar bazasi bir mintaqada bo'lsin (masalan, Render Frankfurt + Neon
Frankfurt). Agar bitta xabarni qayta ishlash `SLOW_UPDATE_SECONDS` (standart
2 s) dan uzoq davom etsa, logda `Sekin javob: …` yozuvi paydo bo'ladi.
