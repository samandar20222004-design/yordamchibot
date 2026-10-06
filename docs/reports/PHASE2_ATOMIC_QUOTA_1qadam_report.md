# 🔒 PHASE 2 · 1-QADAM — KVOTA VA KREDIT TRANZAKSIYASINI ATOMAR QILISH

**Sana:** 2026-09-15 · **Holat:** ✅ Bajarildi (testlar 100% yashil)
**Test buyrug'i:** `PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh`
**Natija:** `EXIT=0` · **`[FAIL]` = 0** · yangi suite: `PASS=161, FAIL=0`

---

## 1. MUAMMO (refaktorgacha)

Har bir AI oqimi ikkita **alohida** tranzaksiyani chaqirar edi:

```python
can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)   # TX 1
reserved             = await db.run_db(db.use_user_credit, user_id)   # TX 2
```

| Xavf | Qayerda | Oqibat |
|---|---|---|
| **Race condition** | ikki TX orasidagi oynada | parallel so'rovlarda kvota bron qilinib kredit yechilmaydi (yoki aksincha) |
| **Yarim bron** | TX 1 OK, TX 2 xato | kunlik kvota yonadi, foydalanuvchi javob olmaydi |
| **FAIL-OPEN** | `magic_post.py:389`, `voice_post.py:526`, `image_post.py:537` | `except Exception: can_use/reserved = True` — DB xatosida oqim **davom etardi** |

---

## 2. YECHIM

### 2.1 `database.reserve_ai_request(user_id, operation_type, cost=1) -> dict`

BITTA atomik blok (`db_cursor(commit=True)`):

1. `SELECT ... FOR UPDATE` — foydalanuvchi qatori **qulflanadi** (parallel bronlar navbatga turadi);
2. `_ensure_limit_reset` — kun o'tgan bo'lsa kunlik sanagich yangilanadi (shu tranzaksiyada);
3. `_effective_plan_strict` — muddati o'tgan PRO → FREE (**qat'iy**: xatoda istisno, yutilmaydi);
4. **Kvota → kredit zanjiri:**
   - bepul kunlik kvota bo'lsa → shartli atomik `UPDATE ... WHERE used + cost <= max_ai` (`source='daily_quota'`);
   - kvota tugagan bo'lsa → `CreditsService.spend_in_tx` (`source='credit'`), balans + `credits_ledger` auditi **shu** tranzaksiyada;
5. `ai_reservations` ga bron qatori yoziladi → `reservation_id` qaytadi.

**Qaytariladigan shakl (doim bir xil):**

```python
{"allowed": bool, "reason": str, "reservation_id": int|None,
 "source": "daily_quota"|"credit"|None, "cost": int,
 "used": int, "max_ai": int, "credits_left": int|None}
```

`reason`: `ok` · `insufficient_balance` · `db_error` · `user_not_found` · `invalid_request`

**FAIL-CLOSED kafolati:** har qanday DB/pool/SQL xatosida tranzaksiya ROLLBACK → `allowed=False, reason="db_error", used=-1`. Mablag' yetishmasa bron qatori ham **SAVEPOINT** orqali qaytadi — bazada yarim yozuv qolmaydi.

### 2.2 `database.refund_ai_request(user_id, reservation_id) -> dict`

```sql
UPDATE ai_reservations SET status='refunded', refunded_at=NOW()
 WHERE id=%s AND user_id=%s AND status='active' RETURNING source, cost
```

- **IDEMPOTENT:** qaytarilgan bron ikkinchi marta qaytmaydi (parallel refund/retry ham xavfsiz);
- **manbaga qarab:** `daily_quota` → `ai_requests_today` kamayadi (`GREATEST(...,0)`), `credit` → `ai_credits` qaytadi + `credits_ledger` ga `ai_refund` auditi;
- **FAIL-CLOSED:** DB xatosida `success=False, reason="db_error"` (yarim qaytaruv yo'q).

### 2.3 `services/ai_quota.py` (yangi modul) — barcha AI oqimlari uchun yagona qatlam

`reserve_for_flow()` · `release_ai_quota()` · `take_reservation_id()` · `reservation_source()` · `denial_message()` · `is_quota_exhausted()` · `ai_quota_temp_error_text()`

Har bir oqim o'z `ctx_prefix` ini ishlatadi (`magic` / `studio` / `voice` / `score` / `image`) — parallel oqimlar bir-birining bronini o'chirmaydi; stale bron har doim **oldin** tozalanadi.

---

## 3. O'ZGARGAN FAYLLAR (16 ta)

### Yangi fayllar (2)
| Fayl | Vazifa |
|---|---|
| `telegram_bot/services/ai_quota.py` | Barcha AI oqimlari uchun yagona bron/qaytarish qatlami + fail-closed matn |
| `tests/atomic_quota_test.py` | Atomik tranzaksiya + race condition + fail-closed acceptance suite (**161 check**) |

### Mahsulot kodi (8)
| Fayl | O'zgarish |
|---|---|
| `telegram_bot/database.py` | `reserve_ai_request()`, `refund_ai_request()`, `_effective_plan_strict()`, `_deny_ai_reserve()`, `_InsufficientBalanceSignal`; `ai_reservations` DDL (zaxira) + `EXPECTED_TABLES` + FK `fk_ai_reservations_user` |
| `telegram_bot/schema.sql` | `ai_reservations` jadvali + `idx_ai_reservations_user` + CHECK/FK constraintlar (idempotent) |
| `telegram_bot/services/credits_service.py` | `OP_AI_REFUND = "ai_refund"` (oq ro'yxatga qo'shildi) |
| `telegram_bot/handlers/magic_post.py` | Preflight → atomik bron; **fail-open o'chirildi**; refund `reservation_id` bilan |
| `telegram_bot/handlers/ai_assistant.py` | AI chat + `_studio_ai_preflight` → atomik bron; `_studio_ai_refund(context)`; **fail-open o'chirildi** |
| `telegram_bot/handlers/voice_post.py` | Preflight → atomik bron; **fail-open o'chirildi**; refund `reservation_id` bilan |
| `telegram_bot/handlers/image_post.py` | `_reserve_one_ai_credit(context)` → atomik bron; **fail-open o'chirildi**; refund atomik |
| `telegram_bot/handlers/post_score.py` | Improve preflight → atomik bron; refund `reservation_id` bilan |

### Testlar (6)
| Fayl | O'zgarish |
|---|---|
| `tests/run_tests.sh` | Yangi bosqich **3o)** qo'shildi |
| `tests/post_score_flow_test.py` | Bitta assertion yangi atomik zanjirga moslashtirildi (kafolat saqlandi) |
| `telegram_bot/tests/syntax_test.py` | `services.ai_quota` import ro'yxatiga qo'shildi |
| `telegram_bot/tests/schema_test.py` | `ai_reservations` + jadvallar 18→19, indekslar 18→19 |
| `telegram_bot/tests/db_integrity_test.py` | `INTEGRITY_CONSTRAINTS` 9→10 |
| `telegram_bot/tests/payment_region_selection_test.py` | Indekslar parallelligi 18→19 |

---

## 4. QO'SHILGAN TESTLAR (`tests/atomic_quota_test.py` — 161 check)

Test **haqiqiy mahsulot kodini** ishga tushiradi: `database.db_transaction` PostgreSQL qator-qulfi + SAVEPOINT + ROLLBACK semantikasini takrorlovchi in-memory dvijok bilan almashtiriladi (SQL ketma-ketligi, `FOR UPDATE`, shartli `UPDATE ... RETURNING`, `credits_ledger` — hammasi real).

| # | Test | Asosiy assertion'lar |
|---|---|---|
| 1 | **5 PARALLEL, balansda 1 kredit** | AYNAN 1 ruxsat / 4 rad · balans 1→0 (manfiy emas) · 1 bron qatori · ledger'da aynan 1 ta `-1` · ledger bron ID'siga bog'langan |
| 2 | **5 PARALLEL, kunlik kvota 3** | AYNAN 3 ruxsat · sanagich limitdan oshmaydi · hammasi `daily_quota` · kredit tegilmaydi |
| 3 | **DB xatosi → FAIL-CLOSED** | `allowed=False` + `db_error` + `used=-1` · tranzaksiya ichidagi xatoda ham · ROLLBACK: balans/sanagich/bron/ledger o'zgarmaydi |
| 4 | **Mablag' yetishmasa iz qolmaydi** | `insufficient_balance` · bron qatori YO'Q (SAVEPOINT) · ledger bo'sh · noma'lum user → `user_not_found` |
| 5 | **Kvota kreditdan avval** | 1-bron `daily_quota`, kredit tegilmaydi · kvota tugach `credit` · tugagach rad |
| 6 | **Refund atomik + idempotent** | kredit qaytadi + `ai_refund` auditi · 2-refund `already_refunded` · **5 parallel refund → aynan 1** · kvota manbasida kredit tegilmaydi · sanagich manfiyga tushmaydi · refund DB xatosida fail-closed |
| 7 | **Argument validatsiyasi** | `cost=0/-5/10⁶/'abc'`, `operation_type='drop_table'/None`, `user_id='abc'/None` → hammasi rad (DB'ga tegmasdan) · oq ro'yxatdagi 9 oqim qabul · `magic_post:sales` belgilash normallashadi |
| 8 | **Adapter qatlami** | haqiqiy DB → atomik yo'l · xatoda fail-closed · eski test adapteri → legacy zanjir (1×1 chaqiruv) · legacy'da kredit yetishmasa kvota qaytadi · legacy DB xatosida fail-closed · adapter jim bo'lsa rad · **haqiqiy kod + kontekst wiring** (ID yoziladi/pop qilinadi/stale tozalanadi/oqimlar aralashmaydi) |
| 9 | **Barcha oqimlar shu funksiyada** | 5 handler'da `services.ai_quota` import + `reserve_for_flow`/`reserve_ai_quota` · **fail-open naqshlari yo'q** · bevosita `check_ai_limit`/`use_user_credit` yo'q · eski DB funksiyalari saqlangan · schema/FK/`ai_refund` mavjud · `FOR UPDATE` + bitta TX + fail-closed dalillari |

---

## 5. BACKWARD COMPATIBILITY

* **Eski DB funksiyalari O'CHIRILMADI:** `check_ai_limit`, `use_user_credit`, `refund_ai_usage`, `increment_ai_usage`, `add_user_credit`, `get_user_credits` — barchasi ishlaydi (TEST 9 assert qiladi).
* **Legacy zanjir saqlangan:** `services/ai_quota.py` ichida `check_ai_limit` + `use_user_credit` alias zanjiri bor — eski test adapterlari va eski deploy'lar uchun. Lekin endi u ham **fail-closed** (`reserved = True` fail-open o'chirildi).
* **Legacy refund** (`add_user_credit` + `refund_ai_usage`) `reservation_id` bo'lmaganda ishlaydi — mavjud test kontraktlari buzilmadi.
* **`_ai_quota_temp_error_text`** nomi saqlandi (endi yagona manbaga delegat qiladi).
* **Mavjud testlarning fake DB adapterlari o'zgartirilmadi** — ular legacy yo'lni tekshirishda davom etadi.

## 6. UX / i18n TOZALIGI

* Hech qanday hardcoded matn qo'shilmadi: rad holatlari mavjud `safe_t("ai_limit_msg")`, `post_score_t("ps_no_credit")`, `image_no_credit` kalitlari orqali; DB xatosi uchun matn yagona `ai_quota_temp_error_text()` (UZ/RU/EN) manbasidan.
* DB xatosida foydalanuvchi endi **ayblanmaydi**: "AI xizmati vaqtincha band, birozdan so'ng qayta urinib ko'ring" (fail-closed, lekin muloyim).
* Ortiqcha/dublikat tugma qo'shilmadi — klaviaturalar o'zgarmadi.

---

## 7. OCHIQ QOLGAN VA KEYINGI QADAMLARGA TAVSIYA

1. **Doiradan tashqari (qoldirildi, buzilmadi):** `ai_assistant.py` dagi audit / photo-edit / vision oqimlari (`increment_ai_usage` chaqiruvlari **1448, 1811, 2034**-qatorlar) hali ham eski kvota zanjirida. Ular alohida mikro-topshiriq bilan atomik bronga o'tkazilishi kerak.
2. **`_studio_ai_refund` ning 5 ta chaqiruv joyi** (**1417, 1439, 1789, 2004, 2025**-qatorlar — audit/photo/vision oqimlari) `context` siz chaqiriladi → ular legacy refund'da qoladi. Ularni `context` bilan yangilash keyingi qadamda xavfsiz (funksiya parametri ixtiyoriy). Atomik bronga ulangan AI Studio oqimining 2 ta chaqiruvi (**1203, 1225**) allaqachon `context` bilan yangilandi.
3. **Double-count himoyasi:** atomik bronda kunlik sanagich allaqachon oshirilgani uchun muvaffaqiyatli yuborishdan keyingi `increment_ai_usage` chaqirilmaydi (`reservation_source()` orqali). Legacy bronda eski xatti-harakat saqlangan.
4. **Deploy:** `init_db()` `schema.sql` ni qo'llaydi → `ai_reservations` mavjud bazalarda ham avtomatik yaratiladi (idempotent). Startup tekshiruvi (`EXPECTED_TABLES`) jadvalni talab qiladi: jadval bo'lmasa bot aniq xato bilan to'xtaydi (fail-closed).

---

## 8. MUHIT ESLATMASI (yashirilmagan)

* Sandbox'da faqat **Python 3.13** mavjud; `requirements.txt` dagi `psycopg2-binary==2.9.9` cp313 uchun wheel'ga ega emas (kompilyatsiya xatosi). Test muhiti uchun venv'ga **`psycopg2-binary 2.9.13`** o'rnatildi (qolgan barcha dependency'lar pin qilinganidek). **`requirements.txt` o'zgartirilmadi** — bu faqat lokal test muhitiga tegishli; production Docker image `python:3.11-slim` ishlatadi va u yerda 2.9.9 ishlaydi.
* Haqiqiy PostgreSQL sandbox'da yo'q — shu sababli testlar in-memory dvijok bilan deterministik (real DB talab qilinmaydi). Live DB bo'lgan muhitda `telegram_bot/tests/db_integrity_test.py` va `schema_test.py` qo'shimcha tekshiruvlarni ham bajaradi.
