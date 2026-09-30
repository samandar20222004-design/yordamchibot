# 🗂 PHASE 4 — DATABASE MODULLASHUVI VA REPOSITORY PATTERN

> Sana: 2026-09-30 · Tur: refactoring + arxitektura mustahkamlash
> Natija: **14 155 `[OK]` / 0 `[FAIL]`** (bazaviy qiymat 14 056 + 99 yangi arxitektura sinovi)

---

## 1. 🎯 Nima qilindi

` tеlegram_bot/database.py` — **8 928 qatorlik "God module"** — ikkita qatlamga
ajratildi:

| Qatlam | Natija |
|---|---|
| **CORE RUNTIME** | ulanish pool'i, atomik tranzaksiyalar, keshlar, sxema, offload, leak o'lchovi — `database.py` da qoldi (2 967 qator) |
| **FACADE** | domain funksiyalari endi 8 ta repository modulida; `database.py` ularni **o'z nomi bilan qayta eksport** qiladi |

Muhim: `database.py` **o'chirilmadi va qayta yozilmadi** — mavjud kod blok
bo'laklari ko'chirildi, har bir belgi o'z joyida saqlandi.

### 📉 Natijada

| | Oldin | Keyin |
|---|---|---|
| `telegram_bot/database.py` | **8 928** qator | **2 967** qator (−67 %) |
| Domain SQL joylashuvi | bitta faylda | 8 ta repository modulida |
| `import database as db` | ishlaydi | **ishlashda davom etadi** (obyekt darajasida bir xil) |

---

## 2. 🧩 Yangi arxitektura

```
┌──────────────────────────────────────────────────────────────────────┐
│  handlers / services / scheduler / tests                             │
│  (242 Python fayli — hech biri O'ZGARMADI, faqat 9 ta test          │
│   scanneri inspect.getsource() ga ko'chirildi)                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  import database as db
                                │  from database import X          ← ESKI YO'L, saqlanган
                                ▼
╔══════════════════════════════════════════════════════════════════════╗
║  telegram_bot/database.py                                           ║
║                                                                      ║
║  ┌────────────────────────────────────────────────────────────┐    ║
║  │ [CORE] — infratuzilma                                     │    ║
║  │  _WarmPool · ThreadedConnectionPool · sem                  │    ║
║  │  _Transaction (BEGIN/COMMIT/ROLLBACK + SAVEPOINT)          │    ║
║  │  transaction() · db_atomic · db_cursor                     │    ║
║  │  run_db (asyncio → thread) · TTL keshlar · profil keshi    │    ║
║  │  init_db / _init_db_once / sxema / integritet              │    ║
║  │  conn_balance() · conn_stats() · offload_stats()           │    ║
║  └────────────────────────────────────────────────────────────┘    ║
║  ┌────────────────────────────────────────────────────────────┐    ║
║  │ [FACADE] — so'ngi qismda, 8 ta oddiy re-export              │    ║
║  │  from repositories.<x>_repository import (name1, name2, …)  │    ║
║  └────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
                                │
                                │  KECH BOG'LANISH (import vaqti emas,
                                │  CHAQUV payti) — patch("database.db_cursor")
                                │  ishlashini saqlaydi
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  telegram_bot/repositories/                                          │
│                                                                      │
│   __init__.py  · yadroni avval yuklaydi → import sikli yo'q          │
│   runtime.py   · 15 ta kech bog'langan proksi                        │
│                                                                      │
│   settings_repository   119 q    │  scheduler_repository  525 q     │
│   users_repository    1 522 q    │  teams_repository      390 q     │
│   channels_repository 2 134 q    │  payments_repository   459 q     │
│   posts_repository      885 q    │  audit_repository      643 q     │
└──────────────────────────────────────────────────────────────────────┘
```

### 🔗 Nima uchun `repositories/runtime.py` bor

Repository modullari yadroni **qiymat bilan** emas (`from database import
db_cursor` — bu bo'lmaydi), balki **proksi orqali** bog'lanadi:

```python
# repositories/runtime.py
def __getattr__(name):
    return getattr(_database, name)   # chaqiruv PAYTI, joriy atributga qarab
```

Shu sabab 13 ta mavjud `patch("database.db_cursor")` nuqtasi repository
ichidagi SQL'gacha yetib boradi — mock seam buzilmaydi. Bu testda
o'tkazilgan **3-maktab** (`patch`, `monkeypatch`, `repositories.*` import
tartibi) — barchasi saqlanган.

---

## 3. 🔒 Tranzaksiya kafolati

`db_atomic` — yangi dekorator. Vazifani **bir butun tranzaksiya** ichida
bajarishga majburlaydi (funksiya signaturasi o'zgarmaydi):

```python
@db.db_atomic
def accept_payment(user_id: int, order_id: int) -> bool:
    with db.db_cursor() as cur:          # INSERT INTO payments …
        cur.execute("UPDATE orders SET status = 'paid' …")
    with db.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO payment_receipts …")
    return True
```

Uchta kritik oqim tekshirildi — bittaga **bitta atomik blok**:

| Oqim | Funksiya | Nazorat |
|---|---|---|
| Post rejalashtirish | `schedule_week_posts` | bitta `db_cursor(commit=True)`, `pg_advisory_xact_lock`, `COALESCE(MAX(user_post_number), 0)` |
| To'lov qabul qilish | `approve_payment_receipt` / `process_stars_payment` | `UPDATE … status` + `INSERT receipt` bitta tranzaksiyada |
| Kvota yechish | AI reserve / refund | `_AI_RESERVATION_*` holatlari va `_invalidate_user` bir blokda |

---

## 4. 💧 Leak va thread pool himoyasi

| O'lchov | Nima uchun |
|---|---|
| `conn_balance()` | olingan − berilgan ulanish. `0` emas → ulanish yo'qolgan (leak) |
| `conn_stats()` | `conn_inflight` / `conn_high_water` / `conn_overflow` |
| `offload_stats()` | `offload_inflight` / `offload_peak` — thread pool to'lishining oldindan signali |
| `get_db_pool_status()` | eski kalitlar (`ready`/`used`/`available`/`max`) saqlanib, **ikkala statistika ham qo'shildi** |

> **Doimiy `ThreadPoolExecutor` ataylab rad etildi.** `asyncio.to_thread`
> ichki executor'ini ishlatadi; doimiy modul darajasidagi executor bo'sh
> worker thread'larni `threading.active_count()` da ushlab turardi —
> `concurrency_load_test.py` ning `leaked_threads <= 0` tekshiruvini
> buzardi. Shuning uchun o'rniga **faqat o'lchov** qo'shildi.

---

## 5. 🧪 Yangi test: `tests/repository_layering_test.py`

**99 ta tekshiruv / 0 xato** — 9 bo'lim:

| # | Bo'lim | Nima tekshiradi |
|---|---|---|
| 1 | 🪞 Facade pariteti | 270 ta belgi `database.X` ≡ `repositories.<mod>.X` (obyekt birligi) + proksi/ta'rif to'qnashuvi (chekinmaslik) |
| 2 | 🎯 Kritik API | 85 funksiya + 24 o'zgarmas + 15 yadro API o'z joyida |
| 3 | 🎭 Mock nuqtasi | `patch("database.db_cursor")` repository SQL'iga yetadi |
| 4 | 🔀 Cross-repo | Bitta repo boshqasining kech bog'langan yordamchisini chaqiradi |
| 5 | 📥 Import tartibi | `import database` va `import repositories.*` — IKKALASI ham ishlaydi |
| 6 | 🧱 Qatlam intizomi | core'da domain SQL yo'q; repo'da pool mexanikasi yo'q |
| 7 | 🔒 Tranzaksiya | `db_atomic` COMMIT/ROLLBACK, ichki SAVEPOINT, async tranzaksiya |
| 8 | 💧 Leak/offload | Balans 0 ga qaytadi; offload peak > 0 |
| 9 | 📚 Yagona manzil | 216 ta repository funksiyasi, dublikat yo'q |

`tests/run_tests.sh` ga **3P) 🗂** bosqich sifatida ulandi.

---

## 6. ✅ Test natijalari

| | `[OK]` | `[FAIL]` | Exit |
|---|---|---|---|
| **Bazaviy** (PR #174, `e94dd32`) | 14 056 | 0 | 0 |
| **Faza 4 dan keyin** | **14 155** | **0** | **0** |

+99 — yangi arxitektura sinovlari. Barcha eski testlar o'z holicha o'tdi.

### Testlarda o'zgartirilgan narsa (9 fayl, faqat scanner usuli)

7 ta test faylda **statik source-scanner** `read_text()` / `split("def X")`
usulida ishlardi — modullarga bo'lingandan keyin bu usul yiqilib ketdi.
Ular `inspect.getsource(db_mod.<fn>)` ga ko'chirildi (natija bir xil, ammo
endi **haqiqiy** ta'rifni tekshiradi).

> Muhim: bu **test yozuvchiligi** tuzatishi — sinovning mazmuni o'zgarmagan,
> faqat manba olish usuli yangilangan.

---

## 7. 📁 Fayllar

| Fayl | Holat |
|---|---|
| `telegram_bot/database.py` | **M** — yadro + facade (2 967 qator) |
| `telegram_bot/repositories/` | **Y** — 8 modul + `runtime.py` + `__init__.py` |
| `tests/repository_layering_test.py` | **Y** — 99 tekshiruv |
| `tests/run_tests.sh` | **M** — 3P bosqichi qo'shildi |
| 8 ta test fayl | **M** — scanner `inspect.getsource()` ga ko'chirildi |
| `tools/tidy_repository_imports.py` | **Y** — takror importlarni tozalash (idempotent) |

---

## 8. 🔁 Qayta ishlab chiqarish / tekshirish

```bash
# 1) Toza muhit
python3 -m venv .venv
./.venv/bin/pip install -r telegram_bot/requirements.txt -r tests/requirements-test.txt

# 2) Tozalash (ixtiyoriy, idempotent)
./.venv/bin/python tools/tidy_repository_imports.py

# 3) To'liq regressiya
PYTHON=$PWD/.venv/bin/python bash tests/run_tests.sh

# 4) Faqat arxitektura sinovi
./.venv/bin/python tests/repository_layering_test.py
```

---

## 9. ✅ Qabul mezonlari

| # | Talab | Holat |
|---|---|---|
| 1 | `telegram_bot/repositories/` paketi | ✅ 8 domain repository |
| 2 | `database.py` ni birdan o'chirish/rewrite qilmaslik | ✅ blok ko'lak ko'chirildi |
| 3 | Facade orqali **to'liq** backward compatibility | ✅ 270 belgi obyekt darajasida bir xil |
| 4 | Atomik tranzaksiya chegaralari | ✅ `db_atomic` + 3 kritik oqim tekshirilgan |
| 5 | Connection leak / thread pool to'lishining oldini olish | ✅ o'lchov + `finally` |
| 6 | `bash tests/run_tests.sh` 100% yashil | ✅ **14 155 OK / 0 FAIL / EXIT=0** |
| 7 | Diff + arxitektura diagrammasi + test hisoboti | ✅ shu hujjat |
