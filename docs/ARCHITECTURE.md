# PostAssist — arxitektura

PostAssist — Telegram kanallar uchun bot (python-telegram-bot 21+, PostgreSQL/psycopg2, APScheduler)
va unga ulangan Telegram Mini App (Vite + React + TypeScript). Bot va Mini App **bitta jarayon**,
**bitta PostgreSQL bazasi** va **bitta qoidalar to'plami** (tarif, limit, kredit) ustida ishlaydi.

## Ishga tushish

`telegram_bot/main.py` (Docker CMD: `python main.py`):

1. `utils.web_server.start_web_server()` — aiohttp: `/`, `/health`, `/health/live`, `/health/ready`;
   `MINIAPP_ENABLED=1` bo'lsa shu serverga `/api/v1/*` va `/app/*` ham ulanadi (`miniapp_api.app.register_miniapp_routes`).
2. `db.init_db()` — `schema.sql` ni qo'llaydi (idempotent migratsiyalar).
3. `GuardedApplication` (PTB `Application` kengaytmasi): update qabul navbati, har foydalanuvchiga alohida lock,
   eskirgan update'larni tashlash, handler timeout.
4. `handlers.register_all_handlers(...)` — barcha handlerlar.
5. APScheduler (`Asia/Tashkent`): `check_and_send_posts` (har 1 daq), `check_and_delete_expired_posts`, `notify_post_problems`,
   `subscription_sweep` (15 daq), `poll_content_sources` (15 daq), `snapshot_channel_member_counts` (6 soat),
   `cleanup_old_data` / `cleanup_old_records`, `daily_morning_digest` (09:00), `uzbekistan_calendar_reminders`,
   `weekly_channel_reports` (dushanba 09:00), `referral_reward_notices`, `flush_user_activity` (to'liq ro'yxat — `main.py`, `scheduler.add_job`).
6. `graceful_shutdown` — scheduler, web server, DB pool tartibli yopiladi.

## Qatlamlar (yuqoridan pastga)

| Qatlam | Papka | Mas'uliyat |
|---|---|---|
| Telegram interfeysi | `handlers/`, `keyboards/`, `middlewares/` | xabar/callback handlerlari, tugmalar, RBAC, rate limit, FSM tozalash |
| Mini App API | `miniapp_api/` | `/api/v1` (aiohttp), initData autentifikatsiya, yozuv/o'qish, statik `/app` |
| Biznes mantiq | `services/` | AI, to'lov/obuna, kredit, scheduler yordamchilari, media albom, rejalash NLP, autopilot |
| Ma'lumot | `repositories/`, `database.py`, `schema.sql` | SQL; `repositories/runtime.py` — `db_cursor` |
| Yordamchilar | `utils/` | sanitayzer (Telegram HTML), xavfsizlik, yetkazish, AI agent, web server |
| Matnlar | `locales/`, `translations/` | uz/ru/en matnlari (qarang: `docs/PROJECT_STRUCTURE.md`) |
| Fon ishlari | `scheduler.py` | post yuborish, o'chirish, hisobotlar; `services/delivery` — yagona yetkazish dvigateli |

Qoida: handler → service → repository. Mini App ham shu service/repository qatlamidan foydalanadi
(`miniapp_api/service.py`, `writes.py`), shuning uchun tarif/limit/kredit qoidalari botdagi bilan bir xil
(`config.TARIFF_CATALOG`, `config.TIER_LIMITS`, `services/plan_sql.py`).

## Muhim oqimlar

- **Post yaratish** (`handlers/new_post*.py`, `manual_post.py`, `magic_post.py`): kontent yig'iladi → tasdiq → `scheduled_posts` qatoriga yoziladi.
- **Yuborish**: `scheduler.check_and_send_posts` → `services/delivery` (kanal bo'yicha 1 post/s, umumiy 30 msg/s, RetryAfter tasnifi,
  dead-letter) → Telegram. Takroriy yuborishdan himoya: delivery kalitlari + atomik holat o'tkazish.
- **Albom**: `post_type='album'`, `file_id` = JSON ro'yxat (`[{type,file_id,caption}]`), 10 tagacha; `scheduler._build_album_media`.
- **Tarif/obuna**: `services/subscription_service.py`, `payment_service.py`, `services/payments/`; Stars, karta (chek), Payme.
- **AI**: `utils/ai_agent.py`, `services/ai/` (provayderlar, byudjet/kvota: `services/ai_quota.py`, `repositories/ai_budget_repository.py`).
- **Mini App ⇄ bot**: qarang `docs/MINIAPP.md`.

## Ma'lum murakkab joylar (tegilmagan, ataylab)

- `utils/ai_agent.py` (~4,9k qator), `handlers/__init__.py` (~2,6k), `scheduler.py` (~2,6k), `database.py` (~3,5k) — katta, lekin
  ishlaydi va regressiya testlari bilan qoplangan; bo'lish alohida, kichik bosqichlarda va testlar bilan qilinadi.
- `locales/translations.py` (asosiy matnlar, `get_text`) va `translations/` paketi (bo'limlar bo'yicha matnlar, masalan `settings_stats_t`)
  — nomi o'xshash, lekin turli vazifa; birlashtirish import yo'llarini keng o'zgartiradi, shuning uchun qoldirilgan.
