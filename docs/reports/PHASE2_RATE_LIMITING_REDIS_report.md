# PHASE 2 · RATE LIMITING va REDIS / DISTRIBUTED STATE ARXITEKTURASI

**Sana:** 2026-09-29
**Repo:** `samandar20222004-design/yordamchibot`
**Branch:** `arena/01a0ecf3-yordamchibot`
**Holat:** Bajarildi — yangi testlar 100% yashil, mavjud regressiya bazasi o'zgarmadi.

---

## 1. Muammo (nega kerak edi)

| # | Muammo | Oqibat |
|---|--------|--------|
| 1 | Barcha holat `utils/helpers.py` dagi **bitta `dict`** larda (`_USER_HISTORY`, `_CB_THROTTLE`) | Render/Docker'da 2+ instance ishlatilganda chegaralar yarim qoladi — foydalanuvchi chegaradan o'tib ketadi |
| 2 | `is_callback_throttled(user_id)` — `data` argumenti ishlatilmaganda | Kalit `(user_id, "")` bo'lardi: **bitta** tugma bosish foydalanuvchining **barcha** tugmalarini 1.5 s bloklaydi |
| 3 | Chegara to'lganda `_USER_HISTORY.clear()` | Bitta foydalanuvchining flood'i **boshqa** foydalanuvchilarning holatini ham tozalaydi (global tozalash) |
| 4 | Matn / AI / URL harakati bitta savatda | Qimmatli AI yoki tashqi fetch'lar ham xuddi shu oynada sanab qo'yilardi |

---

## 2. Yechim

### 2.1 `telegram_bot/services/cache_backend.py` — State & Cache Adapter

Yagona **interfeys** (ABC) — barcha qiymatlar `str`, `ttl` soniyada:

```python
get(key) / set(key, value, ttl=None) / delete(key) / incr(key, ttl=None, amount=1) / expire(key, ttl)
```

* **`MemoryCacheBackend`** — thread-xavfsiz (`RLock`), `time.monotonic()` asosida TTL,
  `OrderedDict` LRU, chegaralar: `max_entries` (20 000), `max_value_bytes` (64 KB),
  `max_total_bytes` (32 MB) — **Render 512 MB RAM** himoyasi. `incr` fixed-window:
  TTL faqat kalit **birinchi marta** yaratilganda qo'yiladi, keyingi oshirishlarda
  oyna cho'zilmaydi (Redis `INCR` + `EXPIRE` semantikasi).
* **`RedisCacheBackend`** — `redis.asyncio` mijozi (`get/set(ex)/delete/incrby/expire/persist`),
  `REDIS_KEY_PREFIX` bilan. Paket yo'q bo'lsa `CacheUnavailableError`.
* **`ResilientCacheBackend`** — circuit breaker: `failure_threshold` ta ketma-ket
  xatodan keyin breaker **ochiladi** (Redis'ga urinish to'xtaydi), `cooldown`
  dan keyin **half-open** proba, muvaffaqiyatli bo'lsa yopiladi. Xatolar
  **`CacheUnavailableError`** ga aylantiriladi — bot qulamaydi.
* **Factory** `create_cache_backend()` — `REDIS_ENABLED` + `REDIS_URL` bo'lmasa yoki
  `PING` muvaffaqiyatsiz bo'lsa **jim** In-Memory ga qaytadi.

### 2.2 `telegram_bot/middlewares/rate_limiter.py` — Granular rate limiting

| bucket | kalit | standart |
|---|---|---|
| `message` | `(user_id)` | 1 s da ≤ 2 ta matn xabari |
| `callback` | `(user_id, callback_action)` | 1.5 s da 1 ta bosish — **boshqa tugma erkin** |
| `ai` | `(user_id)` | 4 s da 1 ta qimmatli AI so'rovi |
| `fetch` | `(user_id)` | 60 s da 5 ta URL/RSS so'rovi (SSRF/DoS) |
| `fetch_global` | `(bot)` | 60 s da 120 ta (Redis bilan — barcha instance uchun) |

* **Mass tozalash yo'q** — har bir kalit `incr` + o'z TTL'i bilan «o'zi» yo'qoladi.
* **Klassifikatsiya**: `callback_query` → `callback` (+ `ai`/`fetch` agar action
  mos bo'lsa: `studio_ai_post`, `ai_post_retry`, `photo_rewrite`, `adp:*`,
  `src_chk:`, `src_url`, `src_add`); havola tutgan matnli xabar → `message` + `fetch`.
* **Middleware** `RateLimitMiddleware(BaseHandler)` — `group=-1` da ro'yxatga olinadi,
  `block=True`; rad bo'lsa `ApplicationHandlerStop` (butun zanjir to'xtaydi) va
  callback'ga tilga mos «⏳ Iltimos, kuting» toast yuboriladi (tugma qotmaydi).
* **Fail-open** — backend nosoz bo'lsa foydalanuvchi bloklanmaydi.

### 2.3 Konfiguratsiya

`config.py` + **ikkala** `.env.example` (paritet saqlangan):

```
REDIS_URL=            REDIS_ENABLED=          REDIS_KEY_PREFIX=postassist
REDIS_SOCKET_TIMEOUT=2.0  REDIS_MAX_CONNECTIONS=10
REDIS_CIRCUIT_FAILURES=3  REDIS_CIRCUIT_COOLDOWN=30.0
MEM_CACHE_MAX_ENTRIES=20000  MEM_CACHE_MAX_VALUE_BYTES=65536  MEM_CACHE_MAX_TOTAL_BYTES=33554432
RATE_LIMIT_ENABLED=1
RATE_LIMIT_MESSAGE_MAX=2      RATE_LIMIT_MESSAGE_WINDOW=1.0
RATE_LIMIT_CALLBACK_MAX=1     RATE_LIMIT_CALLBACK_WINDOW=1.5
RATE_LIMIT_AI_MAX=1           RATE_LIMIT_AI_WINDOW=4.0
RATE_LIMIT_FETCH_MAX=5        RATE_LIMIT_FETCH_WINDOW=60.0  RATE_LIMIT_FETCH_GLOBAL_MAX=120
RATE_LIMIT_AI_ACTIONS=        RATE_LIMIT_FETCH_ACTIONS=
```

`REDIS_ENABLED` bo'sh qoldirilsa **avtomatik**: URL bor bo'lsa `1`, yo'q bo'lsa `0`.
Redis **ixtiyoriy** — `pip install redis` qilinmasa ham tizim butunlay In-Memory
rejimda ishlaydi. `docker-compose.yml` ga `profiles: ["redis"]` bilan ixtiyoriy
`redis` xizmati qo'shildi.

### 2.4 `main.py` integratsiyasi

* `init_cache_backend()` — `recover_on_startup()` dan keyin (uzilish bo'lsa jim
  In-Memory ga qaytadi, start to'xtamaydi);
* `application.add_handler(RateLimitMiddleware(), group=-1)` — barcha
  handler'lardan **oldin**;
* `close_cache_backend()` — graceful shutdown oxirida;
* eski global callback-debounce (`is_callback_throttled(user.id)`) olib
  tashlandi — endi `(user_id, action)` bo'yicha **granular** throttling.

---

## 3. Testlar

| Test | Joyi | Natija |
|---|---|---|
| `tests/cache_backend_test.py` (76 tekshiruv) | ichki runner (CI) | 100% yashil |
| `tests/rate_limiter_redis_test.py` (153 tekshiruv) | root runner, 3N bosqichi | 100% yashil |

Qamrov:

* yagona interfeys + barcha backend'lar kontrakti;
* In-Memory: TTL, fixed-window `incr`, LRU, katta qiymat va umumiy hajm
  chegaralari, kalitlar izolyatsiyasi;
* Redis **mavjud** holat (sun'iy `redis.asyncio` mijozi + ixtiyoriy jonli
  `REDIS_URL` bilan SKIP/PASS) va Redis **yo'q** holat (faqat In-Memory);
* Redis **uzilgan** holat: avtomatik fallback + circuit breaker
  (threshold → open → cooldown → half-open → close);
* **multi-instance**: ikki limiter, bitta Redis — ikkinchisi xuddi shu tugmani
  bloklaydi;
* **callback throttling**: bir xil tugma bloklanadi, **boshqa tugma o'tadi**
  (bir necha usul bilan: to'g'ridan-to'g'ri, middleware orqali va haqiqiy
  PTB `Application` zanjirida `ApplicationHandlerStop` bilan);
* konfiguratsiya + `.env.example` pariteti + `main.py` integratsiyasi.

Tarmoq, DB va `redis` paketi **shart emas** — barcha testlar offline va
deterministik.
