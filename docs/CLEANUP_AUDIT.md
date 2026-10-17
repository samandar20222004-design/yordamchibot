# Tozalash auditi (dalillar bilan)

Usul: (1) `ast` orqali barcha `import`lar grafi (nisbiy importlar ham), (2) satr-ma'lumotlar (`"modul.nomi"`, Docker/CI/skript/hujjat matnlari),
(3) `vulture` (60%+) va har bir nomzod nomi butun repo bo'yicha `grep` (kod + testlar + hujjat), (4) frontend: har bir `src` fayli import qilinishi.

| Tekshiruv | Natija |
|---|---|
| Prod modullar (228) ichida hech qaysi prod kod import qilmaydigan | 4 ta: `services/channels/weekly_report.py` (faqat 1 test), `services/payments/memory_store.py` (3 test), `staging/` + `staging/mock_telegram_server.py` (`docker-compose.staging.yml`, hujjat, testlar) |
| `vulture` 114 "ishlatilmaydigan funksiya" nomzodi | repo bo'yicha FAQAT ta'rifda uchraydigan: 1 ta — `handlers/image_post.py:_is_album_session` (o'chirildi; qolganlari boshqa joydan chaqiriladi/dinamik) |
| `vulture` 80%+ (o'zgaruvchi/import) | imzo-mosligi parametrlari (`include_legacy`, `requested_by`, ...) va 2 ta ishlatilmaydigan import — chaqiruvchilar bilan mosligi uchun tegilmadi |
| Mini App `src` fayllari | ishlatilmaydigan fayl yo'q (`main.tsx` — entrypoint) |
| Git'da kuzatilmaydigan fayl | yo'q (`__pycache__`, `.ruff_cache`, `dist` `.gitignore`da) |

## Qaror

- **O'chirildi:** `_is_album_session` (bitta ta'rif, hech qayerda chaqirilmaydi; `image_to_post_flow` 180/180 va `image_post_fallback` o'tdi).
- **Saqlandi (sabab):** `weekly_report.py` — orqaga moslik shimi, testda ishlatiladi; `memory_store.py` — test/dev omborxonasi;
  `staging/` — staging compose uchun; `docs/ci-hardening.yml` — hech qayerdan havola yo'q, lekin CI mustahkamlash namunasi (hujjat) — egasi qaroriga;
  `telegram_bot/tests/run_tests.sh` — CI `working-directory: telegram_bot` va eski yo'llar uchun moslik shimi.
- **Avvalgi bosqichlarda allaqachon tozalangan:** eskirgan AI shimlari, o'lik modullar, `docs/archive`, `tools/`, `/start` animatsiyasi.

## Katta fayllar (keyingi, alohida bosqichlar uchun)

`locales/translations.py` 5,4k · `utils/ai_agent.py` 4,9k · `database.py` 3,5k · `scheduler.py` 2,6k · `handlers/__init__.py` 2,6k · `handlers/new_post.py` 2,5k ·
`handlers/admin.py` 2,5k. Bo'lish kam xavfli tartibda: `handlers/__init__.py` (faqat ro'yxatga olish; bo'limlar bo'yicha `register_*`),
so'ng `utils/ai_agent.py` (promptlar/provayderlar). Har bosqichdan keyin to'liq `tests/run_tests.sh`.
