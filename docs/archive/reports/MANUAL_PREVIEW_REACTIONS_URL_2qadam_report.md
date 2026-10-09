# DIQQAT: POSTASSIST UI/UX POLISH — 2-QADAM: MANUAL POST PREVIEW BOYITISH (REAKSIYALAR VA URL TUGMALAR)

**Sana:** 2026-09-17 · **Branch:** `arena/01a0af88-yordamchibot`
**Holat:** ✅ BAJARILDI — `PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh` → **BASH EXIT CODE: 0** (butun suite 100% yashil)

## MUAMMO

Oddiy (AI'siz) post tayyorlanganda admin kanalga chiqarishdan oldin
reaksiyalar (👍/❤️/🔥) va havolali inline tugma (URL button) qo'sha
olmasdi — preview paneli sayoz edi.

## YECHIM

### 1) Preview paneli — 4 qatorli boyitilgan tartib
`keyboards/inline.py::get_manual_post_panel` (callback'lar o'zgarmagan,
eski xabarlardagi tugmalar ham ishlayveradi):

```
[🚀 Hozir yuborish]        [📅 Vaqtni belgilash]     (mnp_now | mnp_time)
[❤️ Reaksiyalar]           [🔗 Havolali tugma]       (mnp_react | mnp_url)
[🗑 24 soatlik e'lon]      [🔄 Takroriy e'lon]       (mnp_24h | mnp_repeat)
[✏️ Tahrirlash]            [❌ Bekor qilish]         (mnp_edit | mnp_cancel)
```

Yangi callback'lar (hammasi `mnp_` prefiksida — global stale handler
`^mnp_` ularni ham qamrab oladi): `mnp_react`, `mnp_url`, `mnp_rt:<emoji>`,
`mnp_radd`, `mnp_rback`. Barchasi 64-bayt Telegram limitida.

### 2) ❤️ Reaksiyalar oqimi
- [❤️ Reaksiyalar] → inline presetlar (`get_manual_reaction_keyboard`):
  `[👍][👎]` / `[🔥][❤️][👏]` / `[➕ O'zim kiritaman][◀️ Orqaga]`.
- Har bosish toggle: tanlanganlar ✅ bilan belgilanadi (joyida,
  `edit_message_reply_markup` orqali yangilanadi).
- [➕ O'zim kiritaman] → FSM 455 (`MANUAL_REACTION_CUSTOM`): emoji'siz
  matn rad etiladi, emojilar `normalize_custom_reaction_emojis` bilan
  tozalanadi (10 tagacha).
- [◀️ Orqaga] → preview YANGILANADI: matnda `❤️ Reaksiyalar: …` xulosasi,
  markup'da post tagida reaksiya preview tugmalari.

### 3) 🔗 Havolali (URL) tugma oqimi
- [🔗 Havolali tugma] → FSM 456 (`MANUAL_URL_INPUT`) + yo'riqnoma:
  «Tugma matni va havolani quyidagi formatda yuboring:
  Masalan: `Batafsil - https://t.me/kanal`».
- Kiritma `parse_button_input` + `validate_button_text` +
  `validate_button_url` (`utils.security.url_rejection_reason`) orqali
  tekshiriladi: **faqat `http://`, `https://`, `tg://`** ruxsat;
  `javascript:`, `file:`, `data:`, `ftp:`, credentials'li havolalar rad
  etiladi (holat saqlanadi, muloyim xabar).
- Tugma qo'shilgach preview ostida **haqiqiy inline URL tugma** paydo
  bo'ladi (panel ustida, birinchi qatorda).

### 4) Scheduler / delivery birlashmasi
`handlers/manual_post.py::_publish` endi `db.add_post` ga to'liq uzatadi:
`btn_text`, `btn_url`, `enable_reactions`, `reaction_emojis`. Mavjud
scheduler zanjiri (`_execute_send`) bu ustunlardan to'liq `reply_markup`
quradi — kanalga post reaksiya tugmalari va URL tugma bilan chiqadi
(yangi scheduler kodi kerak bo'lmadi, chunki delivery infratuzilmasi
allaqachon shu ustunlarni o'qiydi).

### 5) Mavjud oqimlar kafolati
- Eski 6 amal (🚀/📅/🗑/🔄/✏️/❌) va ularning FSM oqimlari tegilmagan;
  dublikat detektori, kanal tanlash, vaqt/takroriy rejalar avvalgidek.
- FSM: yangi holatlar 455/456 — 460+ (post_score), 470+ (kalendar),
  480+ (avtopilot/shablon), 500+ (boshqalar) bilan to'qnashmaydi.
- i18n: `translations/manual_post.py` ga 10 ta yangi kalit uchala tilda
  (uz/ru/en), `manual_post_parity_report()` → `in_sync=True` (40 kalit).
- Shablonlar oqimi (`templates.py`) paneldan foydalanishda davom etadi —
  yangi 4 qatorli layout avtomatik qo'llanadi.

## TESTLAR

Yangi: `tests/manual_post_reactions_and_url_buttons_test.py` (184 tekshiruv):
1. 4 qatorli panel speksi (uz/ru/en), 64-bayt, mavjud oqimlar saqlangani;
2. Reaksiyalar: presetlar, toggle ✅, qo'lda kiritish, preview yangilanishi,
   `add_post` ga `enable_reactions`/`reaction_emojis` uzatilishi;
3. URL tugma: format, `tg://` ruxsati, xavfli URL'lar rad etilishi,
   preview'da haqiqiy URL tugma, `add_post` ga `btn_text`/`btn_url`;
4. Scheduler/delivery: DB ustunlari + `_execute_send` reply_markup zanjiri;
5. FSM/routing/i18n qo'riqonlari (455/456 noyobligi, `^mnp_` stale himoya,
   paritet).

Runner: `tests/run_tests.sh` ga **3e3** bosqichi qo'shildi.

## TEKSHIRUV NATIJASI

```
PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
echo "BASH EXIT CODE: $?"
# ...
# BARCHA TESTLAR 100% YASHIL ✔
# BASH EXIT CODE: 0
```

- Yangi suite: `o'tdi=184, xato=0`
- Regressiyalar: `manual_posting_and_unified_menu_test` (156 ✔),
  `autopilot_templates_and_duplicates_test` (212 ✔),
  `content_creation_menu_test` (256 ✔), `fsm_navigation_safety_test` ✔,
  qolgan 30+ suite + `telegram_bot/tests` ichki regressiyasi — hammasi yashil.
