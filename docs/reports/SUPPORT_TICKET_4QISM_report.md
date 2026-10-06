# 💬 POSTASSIST REFACTOR — 4-QISM (SO'NGGI QISM): QO'LLAB-QUVVATLASH TIZIMI

**Sana:** 2026-09-18
**Repo:** `samandar20222004-design/yordamchibot`
**Branch:** `arena/01a0b316-yordamchibot`
**Holat:** Bajarildi — `bash tests/run_tests.sh` **EXIT=0**, `[FAIL]` yo'q.

---

## 0. Muammo va yechim (qisqacha)

| Muammo | Yechim |
|---|---|
| Foydalanuvchi bot ichidan adminga yoza olmasdi (faqat tashqi `t.me/@username` havolasi) | [💬 Qo'llab-quvvatlash] endi **bot ichidagi** bir martalik murojaat (one-time ticket) oqimini ochadi |
| Foydalanuvchi nazoratsiz spam yozishi mumkin edi | FSM **birinchi xabardan keyin DARHOL** yopiladi; qo'shimcha ravishda 20 s cooldown va 24 soatlik soft-limit (5 murojaat) |
| Admin javobi qanday yetib borishi noaniq edi | Admin bot xabariga Telegram'ning oddiy **«Reply»** funksiyasi bilan yozadi — javob avtomatik murojaat egasiga boradi |

---

## 1. Amalga oshirilgan ishlar

### 1.1 YAGONA MUROJAAT OQIMI (ONE-TIME TICKET FSM)

Yangi modul: `telegram_bot/handlers/support.py`, FSM holati `SUPPORT_TICKET_INPUT = 540`
(529–539 — kontent manbalari bandi, 601+ — to'lovlar; **540 bo'sh va unikal**).

```
[💬 Qo'llab-quvvatlash]
      ↓  (help_support — main_conv ENTRY POINT)
✍️ Savol yoki muammoingizni bitta xabarda to'liq yozib qoldiring.
(Adminlarimiz tez orada xabaringizni ko'rib chiqadi).
      [◀️ Orqaga]
      ↓  (matn YOKI rasm + izoh)
✅ Murojaatingiz adminga yetkazildi. Javob shu yerda keladi.
      ↑ FSM holati DARHOL yopiladi (ConversationHandler.END)
```

* Holat router darajasida ham, handler darajasida ham tekshirilgan: 540 holatida
  **matn ham, rasm+izoh ham** `support_message_received` ga tushadi
  (`ImageEntryHandler` faol dialogda `None` qaytaradi — rasm boshqa oqimga
  «o'g'irlanmaydi»), menyu tugmalari esa odatdagidek ishlaydi.
* `[◀️ Orqaga]` (`sup_back`) oqimni yopadi va 👤 Profil hub'ini qayta chizadi;
  FSM sessiyasidan tashqarida bosilsa ham global handler eyebrow sifatida
  ishlaydi (o'lik tugma qolmaydi).
* Matnsiz/rasmsiz xabar (stiker va h.k.) murojaat hisoblanmaydi: muloyim
  yo'riqnoma beriladi va holat ochiq qoladi (foydalanuvchi qamalib qolmaydi).
* Anti-spam: `SUPPORT_TICKET_COOLDOWN_SEC = 20`, `SUPPORT_TICKET_DAILY_LIMIT = 5`
  (DB hisobi fail-soft — baza xatosi murojaatni to'smaydi).

### 1.2 ADMINGA XABAR YUBORISH

Murojaat `.env` dagi `ADMIN_IDS` ro'yxatidagi **HAR BIR** adminga yuboriladi:

```
📩 Yangi murojaat!
👤 Kimdan: @username (ID: <code>424242</code>)
📝 Xabar:
{matn}
```

* Rasm+izoh yuborilsa — foto **caption** sifatida ketadi (uzun izoh bo'lsa
  rasm alohida xabar bilan yuboriladi; ikkala xabar ham kuzatuvga ulanadi).
* Foydalanuvchi matni HTML-escape qilinadi (parse xatosi yo'q).
* `ADMIN_IDS` bo'sh bo'lsa foydalanuvchiga **rostgo'y** javob beriladi —
  soxta «yetkazildi» YO'Q; yetkazish muvaffaqiyatsiz bo'lsa ham xuddi shunday.

### 1.3 ADMINDAN TO'G'RIDAN-TO'G'RI JAVOB (ADMIN REPLY DISPATCHER)

* Har bir yuborilgan admin xabari `(admin_chat_id, admin_message_id)` →
  murojaat ko'rinishida saqlanadi:
  * **DB** — yangi `support_ticket_deliveries` jadvali (bot qayta ishga
    tushgandan keyin ham javob yo'qolmaydi);
  * **xotira keshi** — tez javob uchun (chegaralangan, 5000 yozuv).
* Admin «Reply» yozsa javob murojaat egasiga yetkaziladi:

```
💬 Qo'llab-quvvatlash xizmati javobi:

{admin_javobi}
```

* Adminga tasdiq: **«✅ Javob foydalanuvchiga yetkazildi»**.
* Yetkazib bo'lmasa (foydalanuvchi botni bloklagan): adminga halol xato xabari;
  matnsiz (media) javob yuborilsa — «javobni MATN ko'rinishida yozing».
* Murojaat DB'da `answered` holatiga o'tadi (`answered_at` — birinchi javob vaqti).
* Murojaatga bog'lanmagan reply **eski** `unknown_message_fallback` oqimiga
  o'tadi — boshqa oqimlar buzilmaydi.

### 1.4 XAVFSIZLIK (NOT-AN-ADMIN)

* Ro'yxatga olishdagi filtr: `filters.REPLY & filters.ChatType.PRIVATE &
  filters.User(ADMIN_IDS) & ~filters.COMMAND` — oddiy foydalanuvchi reply'si,
  reply bo'lmagan xabar va guruh reply'si **handler'ga umuman yetib bormaydi**.
* Handler ichida ikkinchi qatlam: `from_user.id` server-side qayta tekshiriladi
  (admin emas → hech qanday amal); chat turi ham `private` bo'lishi shart.
* Adminlar umuman sozlanmagan bo'lsa handler ro'yxatga **olinmaydi**
  (`SUPPORT_ADMIN_REPLY_ENABLED`), filtr esa hech qachon mos kelmaydi.

### 1.5 MA'LUMOTLAR BAZASI VA SXEMA

* `telegram_bot/schema.sql` — 2 yangi jadval (jami 28 → **30** jadval;
  indekslar soni **31** o'zgarmadi — qidiruv `UNIQUE` konstrenin implicit
  indeksi orqali ishlaydi):
  * `support_tickets` — murojaatning o'zi (matn, muallif, holat);
  * `support_ticket_deliveries` — admin xabari ↔ murojaat bog'lanishi
    (`UNIQUE (admin_chat_id, admin_message_id)`).
* `telegram_bot/database.py` — jadval yaratish (idempotent) +
  `EXPECTED_TABLES` startup tekshiruvi + fail-safe CRUD:
  `create_support_ticket`, `attach_support_ticket_delivery`,
  `get_support_ticket`, `get_support_ticket_by_admin_message`,
  `mark_support_ticket_answered`, `count_user_support_tickets`,
  `get_recent_support_tickets`.
* `telegram_bot/tests/schema_test.py` — 30 jadval kontraktiga moslashtirildi.

### 1.6 i18n (UZ / RU / EN — 100% paritet)

Yangi modul `telegram_bot/translations/support.py` (`support_t`,
`support_parity_report`, `SUPPORT_I18N`), `translations/__init__.py` orqali
eksport qilinadi: yo'riqnoma, tasdiq, admin xabari, javob sarlavhasi,
xato/ximoya matnlari — uchala tilda (paritet test bilan qo'riqlanadi).

### 1.7 UI/KLAVIATURA

* `keyboards/inline.py`: `get_support_ticket_keyboard(lang)` — AYNAN bitta
  tugma `[◀️ Orqaga]` (`sup_back`, 8 bayt).
* 👤 Profil hub'idagi 💬 tugmasi endi **bot ichidagi** oqimni ochadi
  (tashqi `t.me` havolasi emas); qo'llanma (`/help`) klaviaturasidagi legacy
  havola o'zgarmagan holda saqlanadi.

---

## 2. O'zgargan / qo'shilgan fayllar

| Fayl | Holat |
|---|---|
| `telegram_bot/handlers/support.py` | 🆕 yangi (FSM + admin reply dispatcher) |
| `telegram_bot/translations/support.py` | 🆕 yangi (i18n lug'ati) |
| `tests/support_ticket_flow_test.py` | 🆕 yangi (106 tekshiruv) |
| `telegram_bot/schema.sql` | ✏️ +2 jadval |
| `telegram_bot/database.py` | ✏️ +CRUD +EXPECTED_TABLES +fallback DDL |
| `telegram_bot/handlers/__init__.py` | ✏️ entry point, 540 holati, reply handler |
| `telegram_bot/keyboards/inline.py` | ✏️ `get_support_ticket_keyboard`, 💬 tugmasi |
| `telegram_bot/translations/__init__.py` | ✏️ eksport |
| `telegram_bot/tests/schema_test.py` | ✏️ 30 jadval kontraktiga moslashtirildi |
| `tests/run_tests.sh` | ✏️ yangi `3H)` bosqichi |
| `.env.example` (+ `telegram_bot/` nusxasi) | ✏️ `ADMIN_IDS` izohi |
| `DEPLOYMENT.md` | ✏️ qo'llab-quvvatlash bo'limi |

---

## 3. Testlar va tekshiruv

Yangi suite: `tests/support_ticket_flow_test.py` — **106 tekshiruv, 0 xato**:

1. **TEST 1** — yagona murojaat oqimi: yo'riqnoma matni spec bilan AYNAN mos,
   FSM 540 ga o'tadi, matn/rasm+izoh → `ConversationHandler.END`, tasdiq matni,
   spam himoyasi (ikkinchi xabar adminga bormaydi), `[◀️ Orqaga]` → Profil hub'i.
2. **TEST 2** — adminga xabar shakli (uchala til), HTML-escape, `ADMIN_IDS` dagi
   har bir admin, DB + kesh kuzatuvi, adminlar yo'q holatda rostgo'y javob;
   juda uzun izoh + rasm: matn **alohida**, foto **qisqa izoh** bilan yuboriladi
   (hech bir ma'lumot yo'qolmaydi, ikkala xabar ham Reply kuzatuvida).
3. **TEST 3** — admin «Reply» → foydalanuvchiga yetkazish, adminga tasdiq,
   `answered` holati, **restart** (kesh bo'sh, DB bor) ssenariysi, media-javob
   va bloklangan foydalanuvchi holatlari.
4. **TEST 4** — not-an-admin ta'sir qila olmasligi: filtr (4 xil update),
   router natijasi va handler ichidagi himoya.
5. **TEST 5** — regressiya: i18n paritet, FSM unikalligi, sxema paralleligi,
   handler tartibi (catch-all'dan oldin), 👤 Profil hub'i o'zgarmagan.

Buyruq va natija:

```bash
PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
echo "BASH EXIT CODE: $?"
# → BARCHA TESTLAR 100% YASHIL ✔
# → BASH EXIT CODE: 0
```

---

## 4. Kafolatlar

* **Mavjud oqimlar buzilmagan:** reply handler faqat adminlar + faqat shaxsiy
  chatdagi reply'ga mos keladi va catch-all'dan oldin turadi; boshqa reply'lar
  eski `unknown_message_fallback` yo'liga o'tadi.
* **Ikki qatlamli himoya:** filtr + handler ichidagi tekshiruv (fail-closed).
* **Restart'ga chidamli:** javob manzili DB'da (`support_ticket_deliveries`),
  xotira kesh yo'qolsa ham javob yetib boradi.
* **Rostgo'y UX:** yetkazilmagan murojaat uchun «yetkazildi» deyilmaydi.
