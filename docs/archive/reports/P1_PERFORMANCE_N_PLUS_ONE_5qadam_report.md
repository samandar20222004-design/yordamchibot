# ⚡️ P1 PERFORMANCE & DB OPTIMIZATION — 5-QADAM

**Analytics N+1 Query Optimization & Index Tuning**

| | |
|---|---|
| Bosqich | PostAssist V2 · 5-qadam (P1) |
| Oldingi qadam | 4-qadam — navigatsiya + yagona inline admin panel (PR #189, qabul qilindi) |
| Qamrov | `repositories/analytics_repository.py` (yangi), kanal tahlili xizmatlari, `scheduled_posts`/`post_reactions`/`channel_posts_history`/`channel_post_events`/`sent_post_messages`/`post_deliveries` indekslari |
| Test | `tests/refactor_step5_test.py` — **156/156 PASS** (jumladan real PostgreSQL qismi) |
| Regressiya | `bash tests/run_tests.sh` → **0 [FAIL], exit 0** |

---

## 1. Muammo (qisqacha)

Kanalning oxirgi **50–100 ta posti** o'rganilganda har bir post uchun alohida
`SELECT` (reaksiyalar, ko'rishlar, metrikalar) yuborilardi — klassik **N+1
query**. Foydalanuvchilar soni oshganda bu DB connection pool'ini to'ldirib,
botning umumiy javob qaytarish tezligini tushirib yuboradi.

Qo'shimcha aniq nuqson: `posts_repository.get_channel_post_stats()` **8 ta
ketma-ket SQL** yuborardi (har bir ko'rsatkich uchun alohida `SELECT`).

---

## 2. Yechim arxitekturasi

```
        ┌──────────────────────────────────────────────────────────┐
        │  services/channels/analytics.py        (SERVICE qatlami)  │
        │  analyze_channel_posts()  →  IDOR/RBAC, ≤ 2 DB chaqiruvi  │
        │  get_channel_analytics_snapshot() → 1 DB chaqiruvi        │
        └───────────────┬──────────────────────────────────────────┘
                        │ (run_db orqali, thread offload)
        ┌───────────────▼──────────────────────────────────────────┐
        │  repositories/analytics_repository.py  (REPOSITORY)       │
        │  • get_channel_posts_metrics_batch()  → 1 SQL (JOIN+GROUP)│
        │  • get_channel_analytics_summary()    → 1 SQL (agregat)   │
        │  • get_posts_metrics_batch()          → 2 SQL (= ANY(%s)) │
        │  • get_channels_analytics_summary()   → 1 SQL (N kanal!)  │
        └───────────────┬──────────────────────────────────────────┘
                        │ kech bog'langan `db_cursor` (repositories.runtime)
        ┌───────────────▼──────────────────────────────────────────┐
        │  PostgreSQL — JOIN / GROUP BY / FILTER / ARRAY_AGG        │
        └──────────────────────────────────────────────────────────┘
```

**Muhim kafolat:** har bir repository funksiyasi **aynan bitta**
`cur.execute()` qiladi (ko'p post/kanal — bitta statement ichida
`= ANY(%s)` / `JOIN` / `GROUP BY`). Shu sababli so'rovlar soni postlar
soniga **bog'liq emas**.

### 2.1 BATCH FETCHING — postlar metrikasi (1 SQL)

`get_channel_posts_metrics_batch(channel_id, limit)` uchta manbani bitta
statementda birlashtiradi:

* `channel_posts_history` — kontent, `views`, sana;
* `sent_post_messages` + `post_reactions` (ichki `GROUP BY message_id`) — reaksiyalar;
* `channel_post_events` (ichki `GROUP BY message_id`) — soat/kun/media/CTA.

### 2.2 AGREGATSIYA — DB darajasida (1 SQL)

`get_channel_analytics_summary(channel_id, days)` Python'ga katta ro'yxatni
tortmaydi; hammasi SQL'da hisoblanadi:

* `SUM/AVG/MAX(views)` — o'rtacha va umumiy ko'rishlar;
* `best_hour` / `best_weekday` — `GROUP BY … ORDER BY COUNT(*) DESC LIMIT 1`;
* **eng yaxshi formatlar** — format bo'yicha `AVG(views)` → `ARRAY_AGG(... ORDER BY avg_views DESC)`;
* `format_distribution` — `JSONB_OBJECT_AGG(fmt, cnt)`.

### 2.3 KO'P KANAL — N+1 emas (1 SQL)

`get_channels_analytics_summary([...10 kanal...])` — `UNNEST(%s::text[])` +
`= ANY(%s)`; har bir kanal uchun alohida so'rov **yuborilmaydi**.

### 2.4 Statistika: 8 → 3 so'rov

`get_channel_post_stats()` endi:

1. `COUNT(*) FILTER (WHERE …)` — `sent_7d` / `sent_30d` / `sent_all` / `pending` (1 SQL);
2. `GROUP BY GROUPING SETS ((hour), (post_type))` — peak hours + type distribution (1 SQL);
3. `channel_posts_history` agregati — views/count (1 SQL, o'zgarmagan).

Qaytadigan lug'at kalitlari va qiymatlari **aynan o'sha** — handler'lar
(`handlers/analytics.py`, `handlers/channels.py`, `handlers/start.py`)
o'zgartirilmagan.

---

## 3. INDEX TUNING (idempotent migratsiya)

Yagona manba — `database.ANALYTICS_PERFORMANCE_INDEXES`; startup'da
`_apply_analytics_performance_indexes(cur)` qo'llaydi, DDL `schema.sql`
bilan bir xil (barchasi `CREATE INDEX IF NOT EXISTS` — qayta bajarish bepul).

| Indeks | Jadval | Ustunlar | Nima tezlashadi |
|---|---|---|---|
| `idx_scheduled_posts_channel_created` | `scheduled_posts` | `(channel_id, created_at DESC)` | kanal postlari tarixi (analitika/queue) |
| `idx_scheduled_posts_channel_status` | `scheduled_posts` | `(channel_id, status)` | kanal + holat filtri (`get_channel_post_stats`) |
| `idx_post_reactions_post_type` | `post_reactions` | `(post_id, reaction_type)` | post metrikasi (batch `= ANY`) |
| `idx_channel_posts_history_channel_views` | `channel_posts_history` | `(channel_id, views DESC)` | Top-N ko'rishlar / views agregati |
| `idx_channel_post_events_channel_created` | `channel_post_events` | `(channel_id, created_at DESC)` | Channel DNA / Best Time oynasi |
| `idx_sent_post_messages_post_channel` | `sent_post_messages` | `(post_id, channel_id)` | batch metrika JOIN'i |
| `idx_post_deliveries_channel_status` | `post_deliveries` | `(channel_id, status)` | kanal bo'yicha yetkazish holati |

**Xavfsizlik choralari**

* barcha indekslar `IF NOT EXISTS` — migratsiya **idempotent** (testda 2–3 marta qo'llanadi);
* bitta indeks qurilmasa — `logger.warning`, qolganlari bajariladi (**fail-soft**, `_apply_integrity_indexes` kabi);
* `schema_test.py` hisoblagichlari (31 jadval / **33 indeks**) **o'zgarmagan** — DDL ataylab
  «INDEX» va «IF NOT EXISTS» alohida qatorlarda yozilgan (repo'dagi mavjud
  `post_deliveries` / `ai_usage_events` naqshi);
* `db_integrity_test.py` "barcha indekslar idempotent" tekshiruvi ham yashil
  (yassilangan matnda 44/44);
* `ANALYTICS_PERFORMANCE_INDEX_NAMES` startup `_verify_schema` va
  `scripts/db_migrate.py` tekshiruviga qo'shildi.

**REAL PostgreSQL (pgserver) tasdig'i** (`EXPLAIN`):

```
Index Scan using idx_channel_posts_history_channel_views on channel_posts_history
Index Scan using idx_scheduled_posts_channel_status      on scheduled_posts
Bitmap Index Scan on idx_post_reactions_post_type        (post_id = ANY(...))
```

---

## 4. Regressiya qo'riqonlari (o'zgarmagan interfeys)

* `ContentLoop.analyze()` — barcha eski kalitlar saqlanadi; qo'shimcha
  `analytics_summary`, `analytics_source`, `avg_views`, `best_formats`;
  DB agregatsiyasi bo'lmasa — `summarize_posts_locally()` (PURE) ishlaydi.
* `get_channel_dna_extended()` — qo'shimcha `analytics_summary` kaliti
  (profil saqlash formati va AI prompt kontrakti o'zgarmagan).
* `repositories.REPOSITORIES` — **8 ta** (frozen shartnoma saqlangan);
  yangi modul `OPTIONAL_REPOSITORIES` da e'lon qilingan.
* `database` facade barcha yangi funksiyalarni qayta chiqaradi;
  `patch("database.db_cursor")` mock nuqtasi kech bog'lanish orqali ishlaydi.
* IDOR — fail-closed (begona foydalanuvchi uchun **0 ta** analitika so'rovi);
  DB xatosida fail-soft (soxta raqam uydirilmaydi).

---

## 5. Test natijalari

```
$ PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
...
===== 3k2) ⚡️ 5-QADAM (P1): ANALYTICS N+1 + INDEX TUNING =====
  [OK]  50 ta post: so'rovlar soni N+1 EMAS (jami 2 ta)
  [OK]  100 ta post: so'rovlar soni N+1 EMAS (jami 2 ta)
  [OK]  500 ta post: so'rovlar soni N+1 EMAS (jami 2 ta)
  [OK]  N+1 detektori: so'rovlar soni postlar soniga BOG'LIQ EMAS (50=100=500)
  [OK]  Tejash: 50 post uchun 150 so'rov o'rniga 2 ta so'rov
  [OK]  REAL DB: 50 ta post metrikasi AYNAN 1 ta SQL
  [OK]  REAL DB: get_channel_post_stats AYNAN 3 ta SQL (ilgari 8 ta)
  ...
JAMI: PASS=156, FAIL=0 (jami 156)
5-QADAM PERFORMANCE TESTLARI 100% YASHIL ✔
...
BARCHA TESTLAR 100% YASHIL ✔
```

`tests/refactor_step5_test.py` — 10 test bloki, **156 tekshiruv**:
N+1 detektori (50/100/500), `= ANY(%s)` batch, DB darajasidagi agregatsiya,
ko'p kanal (1 SQL), index tuning (idempotentlik + fail-soft),
`get_channel_post_stats` (8→3), IDOR/fail-closed, regressiya interfeysi,
statik N+1 skaneri (AST) va **real PostgreSQL** bloki
(`pgserver` bo'lmasa — halol `[SKIP]`).

---

## 6. Natijalar (diff xulosasi)

| Fayl | O'zgarish |
|---|---|
| `telegram_bot/repositories/analytics_repository.py` | **+713** (yangi) — 5 o'qish funksiyasi, har biri 1 SQL |
| `telegram_bot/services/channels/analytics.py` | **+401** (yangi) — batch servis qatlami, IDOR, PURE fallback |
| `tests/refactor_step5_test.py` | **+1158** (yangi) — 156 tekshiruv, live PG bloki |
| `telegram_bot/database.py` | `ANALYTICS_PERFORMANCE_INDEXES` + applier + facade eksportlari |
| `telegram_bot/schema.sql` | 7 ta yangi idempotent indeks (`CREATE INDEX IF` + `NOT EXISTS`) |
| `telegram_bot/repositories/posts_repository.py` | `get_channel_post_stats`: 8 → 3 SQL (FILTER + GROUPING SETS) |
| `telegram_bot/services/channels/{content_loop,dna}.py` | DB agregatsiyasi (qo'shimcha kalitlar, orqaga moslik) |
| `telegram_bot/services/channels/__init__.py`, `repositories/__init__.py` | eksportlar / `OPTIONAL_REPOSITORIES` |
| `scripts/db_migrate.py` | migratsiya tekshiruviga analitika indekslari qo'shildi |
| `tests/run_tests.sh` | yangi `3k2)` bosqichi + sarlavha hujjati |

**Effekt:** 50 ta post tahlili uchun ~150 so'rov → **2 so'rov**;
kanal statistikasi uchun 8 → **3 so'rov**; 10 kanal uchun 10 → **1 so'rov**.
So'rovlar soni endi postlar/kanallar soniga bog'liq emas — pool
bandligi pasayadi, bot javob tezligi barqarorlashadi.
