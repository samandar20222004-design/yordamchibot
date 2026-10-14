# PostAssist Mini App

Telegram Mini App (Vite + React + TypeScript). Bo'limlar: **Bosh** (haqiqiy hisoblar), **Post** (matn
yozish, AI bilan yozish, kanal tanlash, rejalashtirish yoki hozir yuborish), **Reja** (kutilayotgan postlarni
tahrirlash/bekor qilish + tarix), **Men** (profil, tarif, kanallar, til).

Nima BAJARILMAYDI (interfeys ularni ishlayotgandek ko'rsatmaydi): to'lov/tarif o'zgartirish (PRO botda: `/settings → 💎 PRO va Tariflar`),
kanal qo'shish/o'chirish (botda), media-post yaratish, takrorlanuvchi post yaratish, qoralama (bot postlarida shaxsiy qoralama
holati yo'q — `draft` faqat jamoa tasdiqlash oqimida), kanal holatini tekshirish (web server bot obyektiga ega emas).

**Yuborish Mini App tomonidan BAJARILMAYDI.** Post `scheduled_posts` jadvaliga yoziladi (botning `add_post` funksiyasi bilan),
yuborishni botning mavjud scheduler'i `get_due_posts` (`FOR UPDATE SKIP LOCKED`) orqali bir marta bajaradi. «Hozir yuborish» =
vaqti hozirgi vaqt bo'lgan post: scheduler uni keyingi tick'da (<= ~1 daqiqa) yuboradi.

## Tuzilma

```
miniapp/                       frontend (bu katalog)
  src/api/      client (fetch, timeout, GET qayta urinish), validate (ish vaqti tekshiruvi), types
  src/hooks/    useResource, useScheduleFeed (loading/error/refresh/pagination)
  src/i18n/     uz/ru/en matnlari (kalitlar va o'zgaruvchilar testlanadi)
  src/pages/    Home, Post, Schedule, Me
  src/components/, src/styles/ (tokens.css — dizayn tokenlari, Telegram theme + safe area)
telegram_bot/miniapp_api/      backend qatlami (aiohttp, bot handlerlariga bog'liq emas)
  settings.py   MINIAPP_* sozlamalari (xavfsiz standartlar, config xatolari)
  auth.py       Telegram initData HMAC (sof funksiyalar)
  proxy.py      X-Forwarded-* faqat ishonchli proksidan
  ratelimit.py  qat'iy auth limiteri (Redis xatosi -> 503; xotira fallback umumiy hisoblanmaydi)
  db.py         read-only tranzaksiya + SET LOCAL statement_timeout + in-flight semafor
  access.py     foydalanuvchi/beta ruxsati (yon ta'sirsiz)
  repository.py faqat o'qish SQL (egalik SQL ichida)
  service.py    ruxsat + ma'lumot + javob shakli
  writes.py     yozuv amallari: post yaratish/tahrirlash/bekor, til, AI (mavjud servislar qayta ishlatiladi)
  menu.py       MINIAPP_URL -> Telegram «Menu» tugmasi (faqat yoqilgan + to'g'ri HTTPS bo'lsa)
  app.py        middleware, marshrutlar, register_miniapp_routes()
  static.py     /app/* statik serving, SPA fallback, path traversal himoyasi
```

## API (`/api/v1`, `Authorization: tma <initData>`)

Yozuvchi marshrutlar (POST/PATCH/DELETE) faqat `Content-Type: application/json`, tana <= `MINIAPP_MAX_BODY_BYTES`, noma'lum
maydon rad (mass-assignment yo'q), `user_id` hech qachon tanadan olinmaydi. Cookie ishlatilmaydi va CORS sarlavhalari yo'q
(faqat bir-origin; `Authorization` sarlavhali cross-origin so'rov preflight'da to'xtaydi) — shu sababli CSRF yuzasi yo'q.

| Metod va yo'l | Vazifa / javob |
|---|---|
| `GET /health` | auth'siz: `{"status":"ok","api_version":1}` |
| `GET /me` | `user`, `plan`, `usage`, `posts{pending,sent,failed,cancelled}` (DB hisobi), `next_post_at`, `bot.username` |
| `GET /channels` | faqat foydalanuvchining faol kanallari: `items[{id,title}]`, `total` |
| `GET /scheduled-posts?status=pending\|history&limit=&offset=` | faqat o'zining postlari; `history` = yuborilgan/xato/bekor; har elementda `status` |
| `GET /posts/{id}` | bitta post (egasi bo'yicha, boshqaniki -> 404) + tahrirlash uchun to'liq `text` |
| `POST /posts` | `{channel_id, text, scheduled_at (ISO, zonali) \| send_now:true}` -> `201 {post, created, delivery}`; takroriy (30 s ichida bir xil kanal+matn) -> `200 created:false` |
| `PATCH /posts/{id}` | `{text?, scheduled_at?}` faqat `pending` (takrorlanuvchida vaqt o'zgarmaydi) -> `200 {post}`, aks holda `409 not_editable` |
| `DELETE /posts/{id}` | `pending` postni bekor qiladi (`status=cancelled`; qator saqlanadi) -> `200 {id,status}` |
| `PATCH /me/settings` | `{language: uz\|ru\|en}` -> `users.language_code` (botdagi til ham o'zgaradi) |
| `POST /ai/generate` | `{text<=3500, style: sales\|premium\|casual\|ads\|informative}` -> `{text, style}`; botdagi Magic Post bilan AYNAN bir xil kvota/kredit bron-qaytarish (`services.ai_quota`), provayder yo'q/xato -> `503 ai_unavailable` (soxta javob yo'q, bron qaytariladi) |
| `GET /draft` | botdan kelgan joriy qoralama: `{draft: null \| {post_type, text, button_text, button_url, channel_id, reactions, delete_after_hours, media: {type, previewable, count}}}`; `file_id` mijozga CHIQMAYDI; 48 soatdan eskisi ko'rinmaydi |
| `GET /draft/media` | qoralamadagi RASM baytlari (Bot API `getFile`, token serverda; faqat jpeg/png/webp, <=8 MB) |
| `DELETE /draft` | qoralamani o'chiradi |
| `POST /posts` (qo'shimcha) | `use_draft: true` — media (`post_type`, `file_id`), reaksiya va avto-o'chirish qoralamadan olinadi, post yaratilgach qoralama o'chadi; `button_text`+`button_url` — inline tugma (faqat http/https/tg havola) |

Validatsiya: matn 1..4096 belgi (Telegram utf-16 limiti ham), boshqaruv belgilari rad; vaqt kamida 60 s keyin, ko'pi bilan 366 kun;
`channel_id` faqat raqam yoki `@username` shaklida va **faqat egasiga tegishli faol kanal**; bepul tarifda navbat limiti
(`check_queue_limit`, admin istisno). Egalik HAR DOIM SQL ichida (`user_id = %s`); begona post/kanal -> 404 (mavjudligi sezdirilmaydi).
Limitlar: yozuv `MINIAPP_RATE_WRITE_LIMIT` (30/min), AI `MINIAPP_RATE_AI_LIMIT` (4/min) — Redis limiter orqali, xatoda 503 (fail-closed).

Xato formati: `{"error":{"code","message","request_id","retry_after","field"}}` (message uz/ru/en; `field` — faqat maydon NOMI).
Kodlar: `bad_request`, `https_required`, `unauthorized`, `auth_expired`, `not_registered`, `beta_access_required`, `not_found`,
`method_not_allowed`, `rate_limited`, `internal_error`, `service_unavailable`, `auth_unavailable`, `invalid_input`, `schedule_in_past`,
`unsupported_media_type`, `payload_too_large`, `channel_not_found`, `not_editable`, `queue_limit_reached`, `ai_limit_reached`,
`ai_unavailable`, `save_failed`.

## Telegram «Menu» tugmasini Mini App'ga ulash (ixtiyoriy)

1. HTTPS domen orqali Mini App ochiladigan bo'lsin (`https://<domen>/app/`), `MINIAPP_ENABLED=1`, proksi sozlamalari (pastda) to'g'ri.
2. `MINIAPP_URL=https://<domen>/app/` ni belgilang. Faqat `MINIAPP_ENABLED=1` VA URL to'g'ri HTTPS bo'lsa, bot start paytida
   `setChatMenuButton` bilan «Menu» tugmasi Mini App'ni ochadi; aks holda (sukut) tugma avvalgidek buyruqlar ro'yxatini ko'rsatadi
   va bot o'zgarmaydi.
3. BotFather'da qo'shimcha: `/mybots → Bot Settings → Menu Button` (yoki `/newapp`) orqali ham o'sha URL ni berish mumkin;
   kod bilan o'rnatilgan tugma BotFather sozlamasini bot ishga tushganda qayta yozadi.

## Xavfsizlik qarorlari

- **Autentifikatsiya:** har so'rovda `initData` qayta tekshiriladi (rasmiy bot-token HMAC-SHA-256,
  `hmac.compare_digest`). `hash` chiqariladi, qolgan BARCHA maydonlar (`signature` ham) saralanib
  data-check-string bo'ladi. Takroriy/bo'sh kalit rad; `auth_date` butun son, yoshi ≤ 3600 s, kelajak ≤ 60 s;
  `user.id` musbat int (bool emas). `user_id` faqat tasdiqlangan `initData` dan — query/body/sarlavhadagi
  `user_id` e'tiborsiz. `BOT_TOKEN` yo'q/yaroqsiz bo'lsa `503 auth_unavailable` (fail-closed).
  > **F5 holati:** Telegram rasmiy hujjati sandbox tarmog'idan o'qib bo'lmadi (siyosat 403), shuning uchun `signature` qoidasi
  > rasmiy manbadan **tasdiqlanmagan**. Uchinchi tomon (rasmiy EMAS) implementatsiyalari bilan o'qib solishtirildi va mos:
  > aiogram 3.31.0 va `@telegram-apps/init-data-node` 2.0.10 — bot-token usulida faqat `hash` chiqariladi (`signature` data-check-string
  > ichida qoladi); Ed25519 (uchinchi tomon) usulida `hash` va `signature` chiqariladi, prefiks `<bot_id>:WebAppData\n`. Ularning literal
  > HMAC vektorlari bu kod bilan bir xil hash beradi (`tests/miniapp_auth_test.py` 10-bo'lim). Haqiqiy klientdan olingan `initData` bilan
  > sinov **o'tkazilmagan**; Mini App'ni yoqishdan oldin shu birinchi smoke-test majburiy.
- **Maxfiylik:** `BOT_TOKEN`, `initData`, `Authorization` log/javob/xato matniga tushmaydi (testlangan).
- **Ruxsat:** `users` da qator bo'lishi va `deleted_at IS NULL`; API foydalanuvchi YARATMAYDI.
  `BETA_INVITE_ONLY` yoqiq bo'lsa botdagi qoida bilan BIR XIL: admin yoki `approved` kiradi, `pending` kirmaydi,
  ro'yxatda yo'q (qator bor) = eski foydalanuvchi (`REASON_EXISTING`) — kiradi. Beta holati o'qilmasa/JSON buzuq bo'lsa
  `503`. `BetaGate.check()` chaqirilmaydi (u `pending` ga yozadi).
- **Ownership:** har bir SQL `user_id = %s`; xato bo'sh ro'yxatga aylantirilmaydi (mavjud `get_user_channels`/
  `get_queue_posts` xatoni yutadi, shu sababli ishlatilmaydi).
- **PRO holati:** faqat `users.plan_type`/`subscription_expires_at` dan, DB vaqti bo'yicha. To'lov yo'q.
- **Rate limit:** IP bo'yicha HMAC'dan OLDIN, so'ng foydalanuvchi bo'yicha. Limiter xatosi `503`. Redis pool'i (sukut 10, botning limiteri bilan
  umumiy) to'lib ketmasligi uchun limiter Redis chaqiruvlarini `MINIAPP_RATE_REDIS_CONCURRENCY` bilan cheklaydi (real Redis bilan o'lchangan: gate'siz 60
  parallel so'rovda 50 tasi 503 bergan).
  `MINIAPP_RATE_REQUIRE_SHARED=1` (production sukut) — faqat sog'lom **Redis**; xotira fallback umumiy deb
  hisoblanmaydi. Production'da `0` bo'lsa marshrutlar ULANMAYDI.
- **Proksi/HTTPS:** forwarded sarlavhalarga ishonilmaydi, faqat `MINIAPP_TRUSTED_PROXY_CIDRS` peer yoki
  `MINIAPP_PROXY_ASSERT_EDGE_ONLY=1` (operator kafolati; kod tekshira olmaydi). `X-Forwarded-For` o'ngdan
  `MINIAPP_PROXY_HOPS`-chi. HTTPS majburiy (`MINIAPP_REQUIRE_HTTPS=1`); proksi sozlanmagan bo'lsa ULANMAYDI.
- **DB timeout:** HTTP timeout (`MINIAPP_REQUEST_TIMEOUT_SECONDS`) faqat mijozga javobni qisqartiradi —
  `asyncio.to_thread` thread'i va SQL **to'xtamaydi**. Haqiqiy to'xtatish: Mini App so'rovlari alohida read-only
  tranzaksiyada `SET LOCAL statement_timeout` (autocommit EMAS, pool ulanishiga o'tmaydi; bot so'rovlariga
  ta'sir yo'q). In-flight semafori thread tugaganda bo'shaydi; burst'da so'rovlar cheklangan navbatda kutadi (real PostgreSQL'da o'lchangan: navbatsiz 20 parallel
  so'rovdan 16 tasi 503), navbat to'lsa yoki kutish tugasa tez `503`.
- **CSP:** `frame-ancestors` Telegram web; `X-Frame-Options` qo'yilmaydi. Haqiqiy Telegram klientlarida
  (iOS/Android/Desktop/Web) tekshirilmagan.

## Botga navigatsiya (Post / PRO) — haqiqiy holat

Mini App botni faqat **`https://t.me/<BOT_USERNAME>`** orqali ochadi (`openTelegramLink`): bu chatni ochadi,
**`/newpost` yoki PRO oqimini ochmaydi**. Shu sababli matnlar foydalanuvchiga buyruqni o'zi yuborishni aytadi:

| Tugma/matn | Haqiqiy yo'l (kodda tekshirilgan) |
|---|---|
| Post | botga `/newpost` yuborish (`CommandHandler("newpost")`) |
| PRO | `/settings` → «💎 PRO va Tariflar» (`sub_open` → `subscription_callback`); yorliq botdagi `ss_btn_pro_plans` bilan bir xil |
| Botni ochish | `https://t.me/<BOT_USERNAME>`; `BOT_USERNAME` berilmasa tugma ko'rsatilmaydi |

**`?start=<payload>` deep-link ATAYLAB ishlatilmaydi.** `/start` handleri faqat `ref_<id>` ni taniydi; qolgan har
qanday payload `handlers/beta_access.py:extract_invite_code` orqali beta **taklif kodi** deb olinadi — noma'lum payload
yangi/kutilayotgan foydalanuvchini "noto'g'ri kod" sifatida qayd etishi mumkin. To'g'ridan-to'g'ri ochish kerak bo'lsa,
botga alohida payload yo'naltirgich (kod parsingdan OLDIN, `ref_`/kod bilan to'qnashmasdan) qo'shilishi kerak — bu
bot o'zgarishi, shuning uchun hozir qilinmagan (`tests/miniapp_navigation_test.py` shu holatni qo'riqlaydi).

## Sozlamalar (`MINIAPP_*`, hammasi ixtiyoriy; sukut = xavfsiz)

| O'zgaruvchi | Sukut | Izoh |
|---|---|---|
| `MINIAPP_ENABLED` | `0` | `1` bo'lmasa hech narsa ulanmaydi |
| `MINIAPP_TRUSTED_PROXY_CIDRS` | — | ishonchli proksi peer tarmoqlari (vergul bilan) |
| `MINIAPP_PROXY_ASSERT_EDGE_ONLY` | `0` | `1` = konteynerga faqat proksi orqali kiriladi (operator javobgar) |
| `MINIAPP_PROXY_HOPS` | `1` | `X-Forwarded-For` da o'ngdan nechanchi element |
| `MINIAPP_REQUIRE_HTTPS` | `1` | `0` faqat lokal/test |
| `MINIAPP_RATE_REQUIRE_SHARED` | production `1`, dev/test `0` | production'da `0` = ulanmaydi |
| `MINIAPP_RATE_AUTH_LIMIT` / `MINIAPP_RATE_AUTH_WINDOW` | `120` / `60` s | IP bo'yicha |
| `MINIAPP_RATE_USER_LIMIT` / `MINIAPP_RATE_USER_WINDOW` | `60` / `60` s | foydalanuvchi bo'yicha |
| `MINIAPP_RATE_REDIS_CONCURRENCY` | `4` | limiterning bir vaqtdagi Redis chaqiruvlari (pool'dan kichik; burst'da 503 o'rniga navbat) |
| `MINIAPP_AUTH_MAX_AGE_SECONDS` | `3600` | `initData` maks. yoshi |
| `MINIAPP_INIT_DATA_MAX_BYTES` | `4096` | `initData` uzunlik chegarasi |
| `MINIAPP_REQUEST_TIMEOUT_SECONDS` | `8` | HTTP javob chegarasi (DB'ni to'xtatmaydi) |
| `MINIAPP_DB_STATEMENT_TIMEOUT_MS` | `5000` | `SET LOCAL statement_timeout` |
| `MINIAPP_MAX_INFLIGHT_DB` | `4` | parallel DB so'rovlari |
| `MINIAPP_DB_QUEUE_WAIT_SECONDS` / `MINIAPP_DB_MAX_QUEUE` | `2` / `64` | burst paytida slot kutish navbati (to'lsa yoki kutish tugasa tez `503`; `0` = navbatsiz) |
| `MINIAPP_MAX_PAGE_SIZE` | `50` | `limit` yuqori chegarasi |
| `MINIAPP_DIST_DIR` | `<repo>/miniapp/dist` | build katalogi |
| `BOT_USERNAME` | — | `/me.bot.username` va "Botni ochish" tugmasi uchun (berilmasa tugma yo'q) |

## Ishga tushirish (lokal)

```bash
cd miniapp && npm ci && npm test && npm run build      # dist/ — backend /app/ ostida beradi
# backend (lokal, test bazasi):
cd ../telegram_bot && MINIAPP_ENABLED=1 ENVIRONMENT=development MINIAPP_PROXY_ASSERT_EDGE_ONLY=1 \
  MINIAPP_REQUIRE_HTTPS=0 python main.py
```

Frontend dev: `npm run dev` (`/api` lokal botga proksilanadi, `PORT` sukut 10000). Telegram tashqarisida
ilova faqat "Telegram ichida oching" ekranini ko'rsatadi (soxta ma'lumot yo'q).

## Build va deploy

**Node versiyasi:** build (`vite` 8) uchun Node ≥ 22.12; testlar (`vitest`/`jsdom`) uchun ≥ 22.22.2 (eski 22.x da `npm` `EBADENGINE`
ogohlantirishi chiqadi, lekin ishlaydi). Dockerfile `node:22-slim` (suzuvchi 22.x), CI `setup-node` `22`.

- **Docker:** `Dockerfile` da `miniapp-build` stage (node:22-slim: `npm ci` + `npm run build`); runtime image'ga faqat statik
  `dist/` → `/app/miniapp/dist` ko'chadi (Node runtime'da YO'Q, CMD/HEALTHCHECK o'zgarmagan). `MINIAPP_ENABLED=0` bo'lsa
  Python serveri dist'ga tegmaydi. `.dockerignore` lokal `node_modules`/`dist` ni kontekstdan chiqaradi.
- **Render Native Python / VPS:** `bash scripts/build_miniapp.sh` (Build Command'ga `&& bash ../scripts/build_miniapp.sh`) yoki
  `MINIAPP_DIST_DIR` ni tayyor build papkasiga qarating. Backend `dist` ni `<repo>/miniapp/dist` yoki `/app/miniapp/dist` dan topadi.
- **CI:** `.github/workflows/ci.yml` da `miniapp` job (Node 22: `npm ci` → `npm test` → `npm run build` (tsc + vite + `check-dist`) →
  `npm audit --omit=dev` advisory). Python job'i o'zgarmagan; unda `tests/miniapp_*_test.py` ishlaydi.
- `npm run build` oxirida `scripts/check-dist.mjs`: `index.html` dagi barcha `/app/...` havolalari `dist` ichida bor-yo'qligini
  va Telegram SDK `<script>` borligini tekshiradi (vite `base: '/app/'` backend prefiksiga mos).

## Production'ga chiqarishdan oldin (egasi qiladi)

1. `miniapp/dist` server muhitida mavjudligini tekshirish (yuqoridagi "Build va deploy"; Docker image build'i birinchi marta haqiqiy muhitda sinab ko'rilishi kerak).
2. Redis (`REDIS_URL`) — `MINIAPP_RATE_REQUIRE_SHARED=1` uchun majburiy.
3. Proksi: `MINIAPP_TRUSTED_PROXY_CIDRS` yoki `MINIAPP_PROXY_ASSERT_EDGE_ONLY=1` + `MINIAPP_PROXY_HOPS`.
4. `BOT_USERNAME`, beta qoidasi (yuqoriga qarang), `MINIAPP_ENABLED=1`.
5. BotFather'da Mini App/menyu tugmasini sozlash (botda hozir `web_app` tugmasi yo'q).
6. Haqiqiy Telegram klientlarida (iOS/Android/Desktop/Web) tekshirish: tema, safe area, CSP, `initData`.

## Production talablari (qisqa tekshiruv ro'yxati)

| Talab | Holat/qoida |
|---|---|
| `MINIAPP_ENABLED` | sukut `0`; faqat yuqoridagi barcha shartlar bajarilgach `1` |
| Redis (`REDIS_URL`) | MAJBURIY (`MINIAPP_RATE_REQUIRE_SHARED=1`); Redis yo'q/uzilgan -> API 503 (fail-closed) |
| Beta qoidasi | `BETA_INVITE_ONLY` sukut `true`: faqat `approved` (yoki admin) kiradi; `pending`/ro'yxatda yo'qlar rad |
| Ishonchli proksi | `MINIAPP_TRUSTED_PROXY_CIDRS` yoki `MINIAPP_PROXY_ASSERT_EDGE_ONLY=1` (+`MINIAPP_PROXY_HOPS`); HTTPS majburiy; sozlanmasa marshrutlar ulanmaydi |
| `BOT_TOKEN` | initData HMAC kaliti; token log/Sentry'ga tushmaydi |

## initData imzosi — tasdiqlash holati va real smoke-test

- Holat: rasmiy sahifa (core.telegram.org/bots/webapps) sandboxdan to'g'ridan-to'g'ri o'qilmadi. Qidiruv xizmati orqali olingan QISQARTMA (so'zma-so'z emas) bot-token usulini (saralangan `key=value`, LF, kalit `HMAC("WebAppData", token)`, `auth_date` tekshiruvi) tasdiqladi va alohida Ed25519 usulida `hash` VA `signature` chiqarilishini ko'rsatdi — bu birinchi usulda `signature` chiqarilmasligini **bilvosita** tasdiqlaydi. Birinchi usul uchun "signature data-check-string ichida qoladi" jumlasi so'zma-so'z ko'rilmadi (qidiruv xulosalari zid chiqdi). **Empirik dalil:** uchinchi tomon fixture'idagi haqiqiy klientdan olingan `signature`'li payload bu kod bilan tasdiqlanadi, `signature` chiqarib hisoblansa hash MOS KELMAYDI — ya'ni Telegram hash'ni signature bilan birga yaratadi. To'liq tasdiq uchun o'z test botingiz bilan real klient smoke-testi hamon kerak. Uchinchi tomon implementatsiyalari (aiogram, `@telegram-apps/init-data-node`, `init-data-py` real vektorlari) bilan mosligi tekshirilgan — bu rasmiy tasdiq EMAS.
- Real klient smoke-testi (egasi qiladi, TEST bot bilan): 1) alohida test bot yarating va unga Mini App URL ulang; 2) Mini App ichida `Telegram.WebApp.initData` qiymatini nusxalang; 3) `read -rs MINIAPP_SMOKE_BOT_TOKEN && export MINIAPP_SMOKE_BOT_TOKEN`; 4) `umask 077; pbpaste > /tmp/initdata.txt`; 5) `python scripts/miniapp_initdata_smoke.py --file /tmp/initdata.txt` (qo'shimcha: `--api https://<domen>/api/v1` — ayni initData bilan ishlayotgan serverning `GET /me` ini chaqirib, end-to-end natijani (HTTP holat, xato kodi) ko'rsatadi); 6) `shred -u /tmp/initdata.txt`. Vosita faqat maydon nomlari, yosh va mos/mos emas natijasini chiqaradi (qiymatlar yo'q). `SERVER VALIDATORI: OK` va `signature BILAN ... True` chiqsa, qoida haqiqiy klientda tasdiqlangan hisoblanadi. initData va tokenni repo/logga qo'ymang.

## Testlar

- Frontend: `npm test` (vitest + jsdom; API klient, validatorlar, tarjimalar, sahifalar/holatlar), `npm run build` (`tsc` + vite).
- Backend: `tests/miniapp_*_test.py` (`tests/run_tests.sh` ichida). Yozuv oqimlari: `miniapp_writes_real_test.py` (REAL PostgreSQL + to'liq HTTP: yaratish, takroriy yuborish, IDOR, tahrirlash, bekor, navbat limiti, til),
  `miniapp_ai_writes_test.py` (AI bron/qaytarish, parallel, timeout, validatsiya, marshrut limitlari), `miniapp_menu_test.py`,
  `miniapp_bot_api_test.py` («Menu» tugmasi: HAQIQIY PTB `Bot` -> soxta Bot API serveri, `tests/fake_bot_api.py`), `miniapp_scheduler_e2e_test.py`
  (Mini App'da yaratilgan post -> HAQIQIY scheduler -> soxta Bot API: aynan 1 ta yuborish, parallel tick, bekor/kelajak/xato holatlari).
  Real PostgreSQL testlari URL bo'lmasa `pgserver` (CI) ishlatadi, u ham yo'q bo'lsa SKIP. Soxta server haqiqiy Telegram o'rnini BOSMAYDI.
  Haqiqiy Bot API'da «Menu» tugmasini tekshirish (TEST bot bilan, qo'lda): `python scripts/miniapp_menu_smoke.py` (docstring'ga qarang). Real Redis testi (`miniapp_redis_real_test.py`, ixtiyoriy `MINIAPP_TEST_REDIS_URL` — faqat lokal host): `redis-server` binary + Python
  `redis` paketi bo'lsa o'zi vaqtincha lokal server ishga tushiradi (127.0.0.1, persistence yo'q), aks holda SKIP/BLOCKED.
  Real PostgreSQL testi:
  `MINIAPP_TEST_DATABASE_URL=postgresql://... python tests/miniapp_db_real_test.py` (faqat SINOV bazasi).
