# Mini App va bot integratsiyasi

## Tarkib

- **Frontend:** `miniapp/` (Vite + React 19 + TS). Sahifalar: Bosh, Post, Reja, Men (+ ichki ekranlar: Tarif, Til, Bildirishnomalar, Kanallarim).
  API mijozi — `src/api/client.ts` (yagona; yozuv so'rovlari qayta urinilmaydi), turlar/validatorlar — `types.ts`, `validate.ts`.
- **Backend:** `telegram_bot/miniapp_api/` — botning web serveriga ulanadi (`utils/web_server.py` → `register_miniapp_routes`): `/api/v1/*`, `/app/*`.
- **Build:** `npm run build` → `miniapp/dist` (+ `.br`/`.gz`); Docker 2-bosqichda yig'adi; `aiohttp` siqilgan fayllarni o'zi beradi.
- **Holat:** `MINIAPP_ENABLED=0` (sukut). Yoqish: `MINIAPP_ENABLED=1`, `MINIAPP_URL` (HTTPS), proksi sozlamasi. Production'da yoqish — egasi qarori.

## Yagona tizim

| Narsa | Qanday bir xil |
|---|---|
| Foydalanuvchi, kanal, post | bir xil jadvallar (`users`, `channels`, `scheduled_posts`); Mini App postni navbatga yozadi, yuborishni bot scheduler'i bajaradi |
| Tarif, limit, kredit | `config.TARIFF_CATALOG/TIER_LIMITS`, `services/plan_sql.py`; AI kvota — botdagi `BudgetGuard`/`ai_quota` |
| Sozlamalar | til (`users.language_code`), bildirishnomalar (`user_settings`, kalitlar `miniapp_api/prefs.py` ↔ `handlers/settings.py`) |
| Huquq | faqat backend: initData → `user_id`; kanal/post egaligi har so'rovda SQL'da tekshiriladi |

## Bot → Mini App

`miniapp_api/menu.py`: `miniapp_tab_url`, `miniapp_button`, `with_miniapp_row` — Sozlamalar (`tab=me`), Rejalashtirilgan (`tab=schedule`), Tahlil (`tab=me`),
post tasdiqlash kartasida «📱 Mini App'da» (qoralama), `/app` va `/miniapp`. Mini App `?tab=home|post|schedule|me` ni o'qiydi (boshqasi e'tiborsiz).
Qoralama: bot postni `miniapp_drafts` ga yozadi (bitta joriy, 48 soat) — `miniapp_api/drafts.py`, `handlers/new_post.py:_save_miniapp_draft`.
Mini App o'chiq bo'lsa bot ekranlari o'zgarmaydi.

## Mini App → bot

`telegram.ts:openBot(username, section?)` → `https://t.me/<bot>` yoki `?start=go_<bo'lim>`; bot `handlers/start.py` da FAQAT ruxsat ro'yxati
(`MINIAPP_GO_TARGETS`): `go_plans` (tariflar kartasi), `go_settings`, `go_help`. Boshqa payload e'tiborsiz. To'lov, referal, autopilot, kontent-reja,
jamoa — faqat botda (ataylab).

## Media

Fayl: qurilma → `POST .../media` → server foydalanuvchining o'z chatiga jimgina yuboradi (file_id olish uchun) va xabarni o'chiradi → `file_id` saqlanadi.
Ko'rinish: server Telegram'dan oladi (`MediaFetcher`), LRU kesh, tur baytlardan aniqlanadi, CSP `img-src/media-src blob:`. Albom — `media_items.py`.

## Dizayn tizimi

Bot va Mini App bir xil nomlash va tarif ko'rinishini ishlatadi (FREE/PRO/ULTRA, davrlar 1/3/6/12 oy). Mini App rang/tipografiya tokenlari —
`miniapp/src/styles/base.css` (`:root`, qorong'i rejim `prefers-color-scheme`/Telegram `colorScheme`). Holatlar: yuklash (`#boot`), bo'sh, xato (`ErrorState`), muvaffaqiyat (toast).

## Tekshirish

Backend: `tests/miniapp_*_test.py`; frontend: `cd miniapp && npm test`. Haqiqiy initData bilan qo'lda smoke: `scripts/miniapp_initdata_smoke.py` (TEST bot tokeni bilan).
Eslatma: rasmiy Telegram sahifasi sandboxdan to'g'ridan-to'g'ri o'qilmagan; algoritm bilvosita va uchinchi tomon vektorlari bilan tasdiqlangan
(`miniapp_api/auth.py` docstring'ida batafsil) — to'liq tasdiq uchun smoke-test.
