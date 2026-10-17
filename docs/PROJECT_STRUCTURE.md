# Papkalar va fayllar vazifasi

```
.
├── telegram_bot/            # bot + Mini App backend (Docker'da /app)
│   ├── main.py              # ENTRYPOINT: web server, DB, PTB Application, scheduler
│   ├── config.py            # barcha env sozlamalar, TARIFF_CATALOG, TIER_LIMITS
│   ├── database.py          # DB core runtime (pool, tranzaksiya, init_db) + repositories/ fasadi (`import database as db`)
│   ├── schema.sql           # yagona sxema + idempotent migratsiyalar
│   ├── scheduler.py         # post yuborish/o'chirish/hisobot ishlari
│   ├── menu_commands.py     # ☰ menyu buyruqlari (uz/ru/en)
│   ├── handlers/            # Telegram handlerlari (har bir funksiya bo'limi alohida fayl)
│   ├── keyboards/           # reply/inline klaviaturalar, callback_data ro'yxati
│   ├── middlewares/         # rate_limiter, rbac, fsm_cleaner
│   ├── services/            # biznes mantiq (ai/, autopilot/, channels/, delivery/, payments/, sources/, templates/, ads/)
│   ├── repositories/        # SQL qatlami (users, posts, channels, payments, teams, ...)
│   ├── miniapp_api/         # Mini App backend: /api/v1 + statik /app
│   ├── utils/               # sanitayzer, xavfsizlik, AI agent, web server, yordamchilar
│   ├── locales/             # asosiy matnlar (translations.py, en_overlay.py), calendars/
│   ├── translations/        # bo'limlar bo'yicha matnlar (settings_stats, autopilot, ...)
│   ├── staging/             # mock Telegram server (docker-compose.staging.yml uchun)
│   └── tests/run_tests.sh   # moslik shimi → ../tests/run_tests.sh
├── miniapp/                 # Vite + React + TS frontend (src/, scripts/, public/)
├── tests/                   # barcha Python testlar (*_test.py) + run_tests.sh
├── scripts/                 # deploy.sh, db_migrate.py, preflight_env.py, security_check.sh, start_production.sh,
│                            #   build_miniapp.sh, miniapp_*_smoke.py, brand/ (animatsiya manbalari)
├── docs/                    # hujjatlar (shu papka)
├── Dockerfile               # 3 bosqich: python builder → node (miniapp build) → runtime
├── docker-compose*.yml      # bot + postgres + redis (staging: mock telegram)
├── DEPLOYMENT.md            # serverga chiqarish
└── CLAUDE.md                # loyiha egasi qoidalari va oxirgi ishlar
```

## `telegram_bot/handlers/` (asosiylari)

| Fayl | Vazifa |
|---|---|
| `__init__.py` | `register_all_handlers` — barcha handler/ConversationHandler ro'yxati |
| `start.py` | `/start` (+ `ref_<id>`, Mini App `go_*`), Sozlamalar, yordam, `/app` |
| `new_post.py`, `new_post_confirm.py`, `manual_post.py` | post yaratish, albom yig'ish, tasdiq |
| `magic_post.py`, `ai_post.py`, `ai_assistant.py`, `image_post.py` | AI orqali kontent |
| `queue.py`, `pending.py` | rejalangan postlar |
| `channels.py`, `analytics.py`, `statistics.py` | kanallar, tahlil |
| `subscription.py`, `payment_receipt.py` | PRO/ULTRA, to'lov |
| `settings.py`, `onboarding.py`, `support.py`, `privacy.py` | sozlamalar, yordam |
| `admin.py`, `team.py`, `autopilot.py`, `content_calendar*.py`, `templates.py` | admin, jamoa, avtopilot, kontent-reja, shablonlar |

## `telegram_bot/services/` (asosiylari)

`delivery/` (yetkazish dvigateli) · `payments/` (Stars/karta/Payme) · `ai/` (provayderlar, rejalash) ·
`autopilot/` · `channels/` (tahlil, o'sish, maslahat) · `schedule_nlp.py` + `recurrence.py` (tabiiy til rejalash, takrorlanish) ·
`media_group_collector.py`, `album_gate.py` (albom) · `credits_service.py`, `ai_quota.py`, `voice_schedule_quota.py` (limitlar) ·
`subscription_service.py`, `plan_sql.py` (tarif qoidasi) · `post_cleaner.py` · `cache_backend.py` (Redis/xotira).

## `telegram_bot/miniapp_api/`

`app.py` (marshrutlar, middleware) · `auth.py` (initData HMAC) · `service.py` (o'qish) · `writes.py` (yozish, media yuklash, AI) ·
`repository.py` (SQL) · `drafts.py` (bot→Mini App qoralama) · `media_items.py` (albom amallari) · `prefs.py` (bildirishnoma kalitlari) ·
`menu.py` (botdagi «📱 Mini App» tugmalari) · `ratelimit.py`, `proxy.py`, `access.py`, `errors.py`, `settings.py`, `static.py`, `db.py`.
