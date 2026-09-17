# PHASE D (2/2) — KONTENT MANBALARI: handler/klaviatura qatlami, scheduler va testlar

**Holat:** ✅ Bajarildi · `PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh` → **BARCHA TESTLAR 100% YASHIL (0 FAIL, 10 663 ta tekshiruv)**

**Branch:** `arena/01a0ae27-yordamchibot` · **Yangi test:** `tests/sources_rss_and_recycle_test.py` (157 ta tekshiruv, 7 ta test bloki)

---

## 1. Nima qilindi

PHASE D ning 1/2 qismi (`d0917b3`) faqat **servis qatlami** edi: SSRF himoyali havola
o'quvchi, RSS/ATOM oqimi, Content Recycle xizmati, DB jadvallari va i18n lug'ati.
Ular **foydalanuvchi uchun ko'rinmas** edi — bot orqali ishga tushirishning hech
qanday yo'li yo'q edi. Bu bosqich ularni interfeys va avtomatika bilan bog'ladi.

| # | Band | 1/2 (oldingi) | 2/2 (bu bosqich) |
|---|---|---|---|
| 11 | 🔗 URL → POST | `url_extractor.py` (SSRF, 5 MB/10 s, untrusted data, 4 format) | handler oqimi: havola → maqola kartochkasi → 4 format tugmasi → preview → navbat |
| 12 | 📡 RSS / ATOM | `rss_service.py` (parse, dublikat filtri, `poll_due_sources`) | manbalar menyusi (qo'shish/tekshirish/avtopublish/o'chirish), qoralamalar, **scheduler job** |
| 13 | ♻️ Content Recycle | `recycle.py` (14+ kun, ko'r-ko'rona repost taqiqi) | nomzodlar ro'yxati → AI yangilash → preview → navbat |

---

## 2. Yangi fayl — `telegram_bot/handlers/sources.py`

Kirish: **📢 Kanallarim → kanal → [📥 Kontent manbalari]** (`ch_src:<channel_id>`).

```
📥 KONTENT MANBALARI — Kanal: <nomi>
 [🔗 Havoladan post]
 [📡 RSS oqim]
 [♻️ Eski postni yangilash]
 [🗂 Qoralamalar (N)]
 [◀️ Orqaga]
```

### 2.1 🔗 Havoladan post (URL → POST)

1. Foydalanuvchi havola yuboradi → **`validate_public_url`** (SSRF guard) —
   ichki tarmoq, `localhost`, `169.254.0.0/16` (bulut metadata), nostandart port
   va `file://` kabi sxemalar **tarmoqqa chiqilmasdan** rad etiladi;
2. Sahifa **`asyncio.to_thread`** ichida o'qiladi (event loop bloklanmaydi) —
   5 MB / 10 s chegarasi servis qatlamida;
3. AI (Channel DNA ulangan holda) **4 ta format** tayyorlaydi:
   `📰 Yangilik | ⚡ Qisqa | 🧠 Ekspert | 📢 Reklama` (2×2 tugma);
4. Format tanlangach — **umumiy preview paneli**:

```
[📅 Rejalashtirish]  [🚀 Hozir chiqarish]
[🔄 Boshqa variant]  [❌ Bekor qilish]
```

Kvota rad etilsa — AI chaqirilmaydi, kredit **yechilmaydi**, foydalanuvchiga
muloyim xabar (`src_url_ai_failed`).

### 2.2 📡 RSS / ATOM

* `➕ Manba qo'shish` — havola (yana SSRF guard) → interval
  (`parse_interval_input` + `clamp_interval`: **15..1440 daqiqa**, 5 → 15, 5000 → 1440);
* har manba qatori: `🔄 Hoziroq tekshirish` + `▶️/⏸` + `🤖 Avtopublish` + `🗑`;
* tekshiruv natijasi: `✅ Tekshirildi: N ta yangi element, M dublikat o'tkazib yuborildi`
  — **ikkinchi tekshiruvda dublikat qayta ishlanmaydi** (`UNIQUE(source_id, external_id)`
  + `filter_new_items`);
* yangi qoralama darhol preview'ga tushadi (tasdiqlash yoki rejalashtirish).

### 2.3 ♻️ Content Recycle

* `channel_posts_history` dan **14+ kunlik**, yaxshi ko'rsatkichli postlar;
* ko'rsatkich ma'lumoti bo'lmasa **soxta raqam uydirilmaydi** (`metrics_available=False`
  + ogohlantirish);
* AI yangi hook + sarlavha + CTA yozadi; o'xshashlik `≥ 0.75` bo'lsa
  **ko'r-ko'rona repost rad etiladi** (`BLIND_REPOST`) — post ko'rsatilmaydi;
* muvaffaqiyatli yangilanish → preview → navbat.

### 2.4 🗂 Qoralamalar

Tasdiqlash kutayotgan (`pending`) qoralamalar ro'yxati; har biri uchun
`[📅 Rejalashtirish]` (preview → navbat, status `queued` + `scheduled_post_id`)
va `[🗑 O'chirish]` (status `dismissed`).

### 2.5 Xavfsizlik va sifat kafolotlari

* **IDOR** — har kirish `handlers.channels._owned_channel` orqali; manba/qoralama
  so'rovlari `user_id` bilan filtrlangan DB funksiyalaridan o'tadi (begona id →
  «topilmadi», begona foydalanuvchi manbani o'chira olmaydi);
* **Yagona yozish nuqtasi** — barcha postlar `database.add_post` orqali
  `scheduled_posts` navbatiga tushadi; «🚀 Hozir chiqarish» ham navbat orqali
  (scheduler 1 daqiqa ichida chiqaradi) — dublikat yuborish xavfi yo'q;
* **Fail-soft** — tarmoq/AI/DB xatosida foydalanuvchi javobsiz qolmaydi
  (barcha yuborishlar `_safe_edit` / `_safe_send` ichida, hech qanday istisno
  tashqariga chiqmaydi);
* **Toza sessiya** — `clear_sources_session` har kirishda eski `user_data`
  qoldiqlarini tozalaydi; oqimlar bir-biriga aralashmaydi.

---

## 3. Scheduler ulanmasi — `scheduler.poll_content_sources_job`

`main.py` da har **15 daqiqada** (Toshkent zonasi, `max_instances=1`, `coalesce=True`,
`misfire_grace_time=300`):

```python
scheduler.add_job(
    poll_content_sources_job, 'interval', minutes=15, args=[application.bot],
    id="poll_content_sources", timezone=tashkent_tz, ...
)
```

Job `poll_due_sources(db, notifier=..., schedule_post=...)` ni chaqiradi:

* vaqti kelgan (`enabled` + `interval_minutes`) manbalar `get_due_content_sources`
  orqali olinadi (til va kanal nomi bilan birga);
* har bir yangi element → `source_items` (**dublikat qayta ishlanmaydi**) →
  Channel DNA asosida qoralama (`source_drafts`, `pending`);
* `autopublish` yoqilgan manbada qoralama `autopublish_draft` orqali
  `scheduled_posts` navbatiga yoziladi (`queued` + post id);
* egasiga 3 tagacha qoralama uchun bildirishnoma yuboriladi;
* **hech qachon istisno tashlamaydi** — bitta manba xatosi qolganlarini
  to'xtatmaydi; `bot=None` bo'lsa tekshiruv baribir bajariladi.

---

## 4. O'zgartirilgan fayllar

| Fayl | O'zgarish |
|---|---|
| `telegram_bot/handlers/sources.py` | **YANGI** — handler/klaviatura qatlami (FSM 530–539) |
| `telegram_bot/scheduler.py` | `poll_content_sources_job` (+ `_notice_escape` yordamchisi) |
| `telegram_bot/main.py` | yangi job ro'yxatdan o'tkazildi |
| `telegram_bot/handlers/__init__.py` | import, entry point `^ch_src:`, 10 ta FSM holati, stale tarmog'i `^src_` |
| `telegram_bot/keyboards/callback_data.py` | `CB_CHANNEL_SOURCES` + 8 ta yangi `src_*` prefiksi (barchasi ≤16 bayt) |
| `telegram_bot/keyboards/inline.py` | kanal paneliga `[📥 Kontent manbalari]` |
| `telegram_bot/translations/channels_queue.py` | `cq_ch_btn_sources` (uz/ru/en) + `CHANNEL_PANEL_BUTTON_KEYS` |
| `telegram_bot/translations/sources.py` | +5 ta kalit: `src_bad_time`, `src_publish_queued`, `src_scheduled_ok`, `src_write_failed`, `src_rec_similarity` (75 ta kalit, `in_sync=True`) |
| `tests/sources_rss_and_recycle_test.py` | **YANGI** — 157 ta tekshiruv |
| `tests/channels_and_queue_v2_test.py` | panel layoutiga yangi tugma moslashtirildi |
| `tests/run_tests.sh` | `3z)` bosqichi sifatida yangi test qo'shildi |

---

## 5. Test qamrovi (`tests/sources_rss_and_recycle_test.py`)

| Test | Mavzu | Asosiy tekshiruvlar |
|---|---|---|
| 1 | 🛡 SSRF + URL→post | 6 ta bloklangan havola (tarmoqqa chiqilmaydi), 4 format tugmasi, preview (4 amal), `🔄` qayta generatsiya, `📅` noto'g'ri/to'g'ri vaqt, `🚀` navbat, kvota rad etilganda kredit yechilmasligi |
| 2 | 📡 RSS handler | manba qo'shish (SSRF + clamp 5→15), 2 yangi element → 2 qoralama, **2-tekshiruvda 0 yangi (dublikat)**, `▶️/⏸`, `🤖`, `🗑`, IDOR (begona o'chira olmaydi) |
| 3 | 🧩 RSS servis | `parse_feed` (RSS 2.0 + Atom), XXE/entity himoyasi, `canonical_url` (utm/fbclid tozalash), `filter_new_items`, `clamp_interval` |
| 4 | ♻️ Recycle | 14 kundan yangi post nomzod emas, past ko'rsatkich rad etiladi, ko'rsatkich yo'qda `quality='unknown'` (soxta raqam yo'q), **BLIND_REPOST rad etiladi**, muvaffaqiyat → navbat |
| 5 | 🗂 Qoralamalar | ro'yxat + badge, tasdiqlash → `queued` + post id, o'chirish → `dismissed`, IDOR |
| 6 | 🕒 Scheduler | 2 manba → 4 qoralama, autopublish → 2 post navbatda, qo'lda manba `pending`, bildirishnoma, **2-tick 0 yangi**, o'chirilgan manba tekshirilmaydi, botsiz ham ishlaydi |
| 7 | 🧱 UI/routing/i18n | panel tugmasi (uz/ru/en), ≤64 bayt (uzun channel_id), prefiks ≤16 bayt, 19 ta routing, stale tarmog'i, FSM 530–539 unikalligi, `sources` + `channels_queue` paritet |

Barcha tekshiruvlar **tarmoqqa chiqmaydi**: DB — SQL emulyatsiyasi bilan soxta
cursor (real `database.py` funksiyalari va ularning `WHERE user_id` filtrlari
sinanadi), AI — soxta orkestrator, tarmoq — soxta `fetch`/`load_feed`, DNS —
deterministik resolver stub (SSRF qoidalarining o'zi o'zgarmaydi).

---

## 6. Keyingi qadam (ixtiyoriy)

* 📊 **Manbalar statistikasi** — qaysi manba/qoralama ko'proq ko'rish yig'gani
  (kanal DNA singari `content_sources` bo'yicha eng yaxshi vaqt/manba tavsiyasi);
* 🧹 **Qoralamalar avto-tozalash** — 30 kundan eski `dismissed`/`queued`
  qoralamalarni paketli tozalash (`cleanup_service` ga qo'shish);
* 🔔 **Bildirishnoma sozlamasi** — RSS yangi qoralama bildirishnomasini
  yoqish/o'chirish (hozirda har doim yuboriladi, ≤3 ta).
