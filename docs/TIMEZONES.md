# Vaqt mintaqalari (har davlat o'z vaqtida)

Foydalanuvchi postni, rejani va takrorlanishni **o'z vaqtida** kiritadi va ko'radi. Saqlangan vaqt har doim UTC lahzasi
(`timestamptz`) — zona faqat kiritish va ko'rsatish uchun.

## Zona qaerdan olinadi (tartib)
1. `users.timezone` — foydalanuvchi `/timezone` orqali qo'lda tanlagan (o'z davlati zonalari yoki UTC siljishi).
2. Telefon mamlakatining asosiy zonasi (`users.phone_country` -> `services/user_timezone.py: country_zones`; ko'p zonali davlatlarda
   AQSh -> New York, Rossiya -> Moskva, Qozog'iston -> Almati va h.k., qolganlarini `/timezone` da tanlaydi).
3. `Asia/Tashkent` (telefon tasdiqlanmagan — eski xulq o'zgarmaydi).

Telefon `/start`da so'ralmaydi; tasdiqlangach zona avtomatik o'zgaradi (qo'lda tanlangan zona saqlanadi). Telefon tasdiqlanmagan
chet ellik `/timezone` -> «🌍 UTC bo'yicha» orqali zonani o'zi qo'yadi. Vaqt so'raladigan ekranlar oxirida joriy zona va `/timezone` ko'rsatiladi.

## Qanday ishlaydi
- `handlers/timezone_flow.py:TimezoneUpdateProcessor` (`main.py`da ulangan; handler emas, guruhlar ro'yxatiga tegmaydi) har yangilanishda foydalanuvchi zonasini `ContextVar`ga qo'yadi
  (10 daqiqalik xotira keshi); Mini App so'rovlari uchun shuni `miniapp_api/app.py` middleware qiladi.
- Kod `utz()` orqali joriy zonani oladi (`tashkent_tz` o'rniga). Fon vazifalar (`scheduler._build_sent_marker`) takrorlanuvchi postning
  keyingi vaqtini **egasining** zonasida (`use_tz`) hisoblaydi.
- Kun/soat siljishi devor-soat bo'yicha (`shift_local`): yozgi/qishki vaqt o'tishida ham «har kuni 18:30» mahalliy 18:30 bo'lib qoladi.
- Mini App: `/me.user.timezone`; takrorlanish soati/hafta kuni shu zonada (`recurrence.ts: setAppTimezone`).
- AI vaqt ko'rsatmalari ham foydalanuvchi zonasida (`[[TZ]]` belgisi `get_text`/`ai_agent._fill_tz` da to'ldiriladi).
- Bayram/mavsum eslatmalari: standart `UZ` bo'lib qolgan chet ellik telefon tasdiqlagach o'z mamlakatiga o'tadi (qo'lda tanlangan saqlanadi).

## Hali Toshkent vaqtida qolganlar (ataylab)
- Umumiy cron vazifalar: ertalabki digest, haftalik hisobot (09:00), tozalash (03:00), kunlik bonus sanasi (`credits_service`).
- Kanal tahlili (`post_hour`, eng yaxshi soatlar) Toshkent soatida hisoblanadi.
- Foydalanuvchining shaxsiy "kun" chegarasi (AI kunlik limit) — server sanasi bo'yicha.

Testlar: `tests/user_timezone_test.py` (real PG qismi bilan), `miniapp/src/timezone.test.ts`.
