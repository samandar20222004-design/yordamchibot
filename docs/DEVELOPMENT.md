# Yangi funksiya qayerga yoziladi

| Nima qo'shmoqchisiz | Qayerga |
|---|---|
| Yangi Telegram buyrug'i / tugma / bosqich | `handlers/<bo'lim>.py` + `handlers/__init__.py` (`register_all_handlers`) ga ulash; tugma — `keyboards/`; callback nomi — `keyboards/callback_data.py` |
| Biznes qoidasi (limit, hisob, tarif) | `services/` (handler ichiga yozmang); Mini App ham shuni ishlatadi |
| SQL | `repositories/<jadval>_repository.py`; `database.py` fasadi orqali eksport qilinadi; sxema o'zgarsa — `schema.sql` (faqat idempotent: `IF NOT EXISTS`) |
| Fon ishi / jadval | funksiya `scheduler.py` yoki `services/`; ro'yxatga olish — `main.py` (`scheduler.add_job`) |
| AI prompt / provayder | `services/ai/` (`prompts.py`, `providers.py`, `router.py`); katta eski qism — `utils/ai_agent.py` |
| Yangi matn | uchala til (uz/ru/en) majburiy: `locales/translations.py` (+ `locales/en_overlay.py`) yoki bo'lim moduli `translations/`; tugma yorlig'i ≤ 18 belgi |
| Mini App endpoint | `miniapp_api/app.py` (marshrut), `service.py` (o'qish) yoki `writes.py` (yozish); yozuv marshruti `@_write`/`@_upload`/`@_ai` bilan belgilanadi |
| Mini App ekran | `miniapp/src/pages/`, komponent — `components/`, matn — `i18n/messages.ts` (uz/ru/en) |
| Env sozlama | `config.py` (yoki `miniapp_api/settings.py`) + `.env.example` (haqiqiy `KEY=value` qatori; `tests/env_docs_parity_test.py` tekshiradi) |

## Qoidalar

- Avval mavjudini tuzating, keyin yangisini qo'shing; keraksiz refaktoring yo'q.
- Xatti-harakat o'zgarsa testni moslang — tekshiruvni o'chirmang.
- Foydalanuvchi matni, token, initData loglarga tushmasin (`utils/sentry_scrubber.py`, `utils/silent_errors.py`).
- Ma'lumotni frontenddan olmang: `user_id`, tarif, kanal egaligi — faqat backend tekshiruvi (`miniapp_api/auth.py`, `service.py`).
- `MINIAPP_ENABLED` sukut 0; production'da yoqish — egasi qaroriga.
- `main` ga merge va deploy — loyiha egasi.

## Xatolarni kuzatish

- Jurnal: JSON qatorlar (`logger` nomi, `event`, `latency_ms`, `error_code`); 2 s dan sekin update — «Sekin javob» (`SLOW_UPDATE_SECONDS`).
- Yutilgan xatolar: `utils/silent_errors.log_silent_failure` (`[silent-error] modul:funksiya → xato`).
- Sog'liq: `GET /health/live`, `/health/ready`; Sentry (agar `SENTRY_DSN`) — `utils/sentry_scrubber.py` maxfiylarni tozalaydi.
