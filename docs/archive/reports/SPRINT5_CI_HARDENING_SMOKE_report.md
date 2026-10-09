# 🏁 SPRINT 5 (YAKUNIY BOSQICH) — CI QAT'IYLIGI, WORKFLOW HARDENING VA ISHLAB CHIQARISH SMOKE TEST

**Sana:** 2026-10-09 · **Holat:** ✅ BAJARILDI (0 [FAIL], `bash tests/run_tests.sh` → exit 0)

---

## 1. CI WORKFLOW MUSTAHKAMLASH

### 1.1 Tekshiruv: `docs/ci-hardening.yml` taklifi

Taklif qilingan uchta qoida ko'rib chiqildi va **asosli deb topildi**:

| Qoida | Nima uchun kerak | Baho |
|---|---|---|
| `pip-audit -r telegram_bot/requirements.txt` | Bog'liqliklardagi ma'lum CVE'lar (masalan `aiohttp` 3.9.5) ko'rinib turishi shart | ✅ qabul qilindi |
| `bandit -r telegram_bot -ll` | Statik xavfsizlik topilmalari (SQL qurish, `assert`, zaif hash) | ✅ qabul qilindi |
| Qat'iy `ruff check` (`\|\| true` bypass'isiz) | Avvalgi `ruff check . \|\| true` natijani **butunlay yashirib** yuborardi — lint xatosi bor-yo'qligi umuman ko'rinmasdi | ✅ qabul qilindi |

### 1.2 Qo'llash: GitHub App ruxsati YETARLI EMAS

`.github/workflows/ci.yml` yangilandi, lekin **push rad etildi** — bu aniq
tasdiqlandi (taxmin emas):

```
! [remote rejected] arena/69830dd7-yordamchibot -> arena/69830dd7-yordamchibot
  (refusing to allow a GitHub App to create or update workflow
   `.github/workflows/ci.yml` without `workflows` permission)
```

Shuning uchun vazifadagi **zaxira yo'l** bajarildi:

* `.github/workflows/ci.yml` o'zgarishsiz qoldirildi (App ruxsati yo'q —
  faylni o'zgartirib bo'lmaydi);
* Yakuniy (ko'rib chiqilgan) workflow matni `docs/ci-hardening.yml` ga
  yozildi — repo egasi uni **1 daqiqada** qo'llashi mumkin:

  ```bash
  cp docs/ci-hardening.yml .github/workflows/ci.yml
  git add .github/workflows/ci.yml && git commit -m "ci: SPRINT 5 hardening"
  git push origin main
  ```

### 1.3 `scripts/security_check.sh` — serverda bitta komanda

```
bash scripts/security_check.sh                 # qat'iy: topilma bo'lsa exit 1
bash scripts/security_check.sh --advisory      # faqat hisobot (exit 0) — CI shu rejimda
bash scripts/security_check.sh --install       # yetishmayotgan vositani o'rnatish
bash scripts/security_check.sh --skip-network  # pip-audit o'tkazib yuborish (oflayn)
bash scripts/security_check.sh --json out.json # mashina o'qiydigan hisobot
```

4 ta darvoza (CI va server **bir xil** darvozalar — yagona manba):

| # | Darvoza | Bloklovchi? |
|---|---|---|
| 1 | `ruff` E9,F63,F7,F82 + `flake8` xuddi shu tanlov bilan | ✅ HA (ilova ishga tushmaydi) |
| 2 | `ruff check telegram_bot` (to'liq) | hisobot |
| 3 | `pip-audit -r telegram_bot/requirements.txt` | hisobot |
| 4 | `bandit -r telegram_bot -ll` | hisobot |

**Halollik qoidasi:** vosita o'rnatilmagan bo'lsa u `[SKIP]` sifatida qayd
etiladi va **yashil deb hisoblanmaydi** (soxta PASS yo'q), lekin muhit
yetishmovchiligi job'ni yiqitmaydi. Haqiqiy o'lchov (barcha vositalar
o'rnatilgan holda):

```
OK    : 2     (ruff lint gate, flake8 lint gate)
FAIL  : 3     (to'liq ruff, pip-audit, bandit — mavjud texnik qarz)
SKIP  : 0
```

Bloklovchi lint gate **yashil**; qolgan uchtasi `continue-on-error` bilan
hisobot sifatida yuradi — aynan `docs/ci-hardening.yml` taklif qilgan dizayn.

---

## 2. TO'LIQ SMOKE TEST VA PAYME INTEGRATSIYASI SINTOVI

`tests/smoke_test.py` ga **6-bo'lim** qo'shildi
(`💳 TO'LOV USULLARI — Payme JSON-RPC + ⭐️ Stars + 🧾 Karta cheki`).
Smoke test `tests/run_tests.sh` ichida `--offline` rejimda chaqiriladi, ya'ni
bu tekshiruvlar har bir CI yugurishida majburiy bajariladi.

### 2.1 Payme JSON-RPC (in-memory kassa, deterministik soat)

| Tekshiruv | Kutilgan natija |
|---|---|
| `CheckPerformTransaction` (to'g'ri summa) | `{"allow": true}` |
| `CheckPerformTransaction` (noto'g'ri summa) | `-31001` |
| `CheckPerformTransaction` (buyurtma topilmadi / `account` yo'q) | `-31050` / `-32600` |
| `CheckPerformTransaction` tranzaksiya yaratmaydi | read-only, store bo'sh |
| `CreateTransaction` | `state 1` + `transaction` + `create_time` |
| `CreateTransaction` takrori (ayni Payme id) | idempotent `state 1` |
| `CreateTransaction` (ikkinchi faol tranzaksiya) | `-31052` band |
| `CheckTransaction` | `state 1` (pending) |
| `PerformTransaction` | `state 2` + `perform_time`, PRO **aynan 1 marta** (30 kun) |
| `PerformTransaction` × 3 (takroriy callback) | PRO baribir 1 marta, bildirishnoma 0 |
| Ledger kaliti | `payme:<transaction id>` — noyob |
| `CancelTransaction` (`PAYME_ALLOW_REFUNDS=0`) | `-31007` |
| Basic Auth: noto'g'ri kalit / sarlavha yo'q / `Bearer` | `-32504`, store'ga tegilmaydi |
| Noma'lum metod | `-32601` |
| `build_checkout_url` | `m=` / `ac.order_id=` / `a=` base64 ichida |
| Konfiguratsiya | `PAYME_KEY` bo'sh → `checkout_enabled=False` (**fail-closed**) |

### 2.2 `POST /payments/payme` production web-app'da

`utils.web_server.build_web_app()` ustida `aiohttp` TestClient bilan:

* route mavjud: `/payments/payme`;
* `GET` → HTTP 200 + `-32300`; buzilgan JSON → `-32700`;
* auth yo'q / noto'g'ri kalit → HTTP 200 + `-32504` (DB'gacha yetib bormaydi);
* `Cache-Control: no-store`;
* to'liq oqim: `CheckPerformTransaction` → `CreateTransaction` →
  `PerformTransaction` ×3 → `state 2`, PRO **1 marta**, bildirishnoma **1 marta**;
* `/health/live` buzilmagan (route qo'shilishi health endpoint'iga ta'sir qilmaydi).

### 2.3 Barcha to'lov usullari BIR VAQTDA

| Usul | Tasdiqlangan xossasi |
|---|---|
| ⭐️ **Stars** | `send_invoice` → `currency=XTR`, `provider_token=""`, payload `sub_stars_1m_<user_id>`; `_validate_stars_payload` to'g'ri summa/valyutani qabul qiladi, soxta summani va **boshqa user payload'ini (IDOR)** rad etadi |
| 🧾 **Karta cheki** | `RECEIPT_WAIT = 603`, `receipt_received` handler mavjud, chek oqimi Payme yoqilganda ham saqlanadi (har 3 tilda: uz/ru/en) |
| ⚡️ **Payme** | JSON-RPC oqimi orqali PRO darhol faollashadi (adminsiz) |

**Yonma-yon ishlash (asosiy kafolat):**

* karta ekranida ⚡️ Payme tugmasi va 🧾 chek tugmasi **bir klaviaturada** turadi;
* `payme_url=None` (Payme sozlanmagan) → Payme tugmasi **ko'rinmaydi**
  (fail-closed), lekin chek oqimi ishlayveradi (fail-safe);
* **aralashmaslik:** Payme ledger'i faqat `payme:` namespace'ida; Stars
  payload'i Payme ledger'iga tushmaydi; Payme identifikatori Stars
  validatoridan o'tmaydi; chek oqimi Payme buyurtmasini o'zgartirmaydi.

---

## 3. DOKUMENTATSIYA VA `.env.example`

### 3.1 `.env.example`

Tekshirildi: `PAYME_MERCHANT_ID`, `PAYME_KEY`, `PAYME_CHECKOUT_URL`,
`PAYME_ALLOW_REFUNDS` (shuningdek `PAYME_LOGIN`, `PAYME_ACCOUNT_FIELD`)
**allaqachon mavjud** va izohli. Qo'shimcha:

* Payme blokiga `DEPLOYMENT.md → 3.2-bo'lim` havolasi qo'shildi;
* bu to'rtta kalit endi **smoke test kontrakti** (0-bo'lim) — ular
  `.env.example` dan olib tashlansa test yiqiladi.

### 3.2 `DEPLOYMENT.md`

Yangi **3.2-bo'lim — «⚡️ Payme webhook — ulash tartibi (avtomatik PRO)»**:
`.env` parametrlari → Payme kabineti jadvali (endpoint, usul, hisob maydoni,
Basic Auth) → restart → 3 ta tezkor `curl` tekshiruvi → muhim qoidalar
(fail-closed, idempotentlik, `-31007`, kalit log'ga yozilmasligi).

Shuningdek 5-bo'lim (yakuniy checklist) ga `bash scripts/security_check.sh`
bandi qo'shildi.

---

## 4. NATIJA

```
bash tests/run_tests.sh     →  BARCHA TESTLAR 100% YASHIL ✔   (exit 0)
python3 tests/smoke_test.py --offline
                            →  PASS: 151 · FAIL: 0 · NOT TESTED: 2
                               (LIVE getMe va LIVE webhook — --offline rejimi, halol qayd)
bash scripts/security_check.sh --advisory
                            →  OK: 2 · FAIL: 3 (hisobot) · SKIP: 0
```

Bloklovchi darvoza (sintaksis / aniqlanmagan nomlar) — **yashil**.

### O'zgartirilgan fayllar

| Fayl | O'zgarish |
|---|---|
| `scripts/security_check.sh` | 🆕 serverda bitta komandalik xavfsizlik darvozasi |
| `docs/ci-hardening.yml` | ♻️ yakuniy workflow matni + qo'llash yo'riqnomasi |
| `tests/smoke_test.py` | ➕ 6-bo'lim (Payme JSON-RPC + HTTP + 3 usul yonma-yon), 0-bo'lim kontraktlari |
| `tests/run_tests.sh` | 📝 smoke test tavsifi yangilandi |
| `DEPLOYMENT.md` | ➕ 3.2 Payme webhook bo'limi + checklist bandi |
| `.env.example` | 📝 Payme blokiga DEPLOYMENT.md havolasi |
| `docs/archive/reports/SPRINT5_…_report.md` | 🆕 ushbu hisobot |

### Ma'lum cheklovlar (halol qayd)

* `.github/workflows/ci.yml` **App ruxsati yo'qligi** sababli o'zgartirilmadi —
  matn `docs/ci-hardening.yml` da, `cp` bilan qo'llanadi.
* `pip-audit` (aiohttp 3.9.5) va `bandit` topilmalari, shuningdek to'liq `ruff`
  texnik qarzi — **hisobot** rejimida. Ularni yopish keyingi texnik qarz
  sprint'i ishi; bloklovchi lint gate hozir ham toza.
