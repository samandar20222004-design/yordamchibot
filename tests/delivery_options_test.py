#!/usr/bin/env python3
"""⚙️ QO'SHIMCHA SOZLAMALAR (DELIVERY OPTIONS) — kanalga post yuborish
professional sozlamalari.

Post tayyorlash (preview) interfeysidagi "⚙️ Qo'shimcha sozlamalar" tugmasi
orqali 3 parametr boshqariladi (Toggle On/Off)::

    1. disable_notification — 🔇 Ovozsiz yuborish (Ha/Yo'q)
    2. protect_content      — 🔒 Forward/Nusxa olishni taqiqlash (Ha/Yo'q)
    3. auto_pin             — 📌 Kanalga chiqqach avtomatik qadash (Ha/Yo'q)

Qamrov:

  TEST 1:  i18n — uz/ru/en uchun yangi kalitlar + 100% paritet.
  TEST 2:  UI — preview'da ⚙️ tugma; 4 qatorli panel SPEKSI BUZILMAYDI;
           delivery klaviaturasi (✅/❌ toggle, 64-bayt callback kafolati).
  TEST 3:  OQIM — menyuni ochish, har bir parametrni toggle qilish
           (user_data/post state'ga yoziladi), orqaga qaytish; preview
           matnida xulosa qatori.
  TEST 4:  PUBLISH — 3 parametr db.add_post'ga to'g'ri uzatiladi; bekor
           qilishda holat tozalanadi.
  TEST 5:  DB — scheduled_posts ustunlari (CREATE + ALTER migratsiyalar),
           add_post imzosi, get_due_posts RETURNING tartibi (eski
           indekslar post[0]/post[2]/post[9] o'zgarmaydi).
  TEST 6:  SCHEDULER — disable_notification/protect_content Telegram
           send metodiga to'g'ridan-to'g'ri uzatiladi; auto_pin bo'lsa
           pin_chat_message(disable_notification=True) chaqiriladi;
           eski 16 maydonli tuple — eski xatti-harakat (pin yo'q);
           pin xatosi fail-soft (delivery buzilmaydi).

Ishga tushirish:
    python3 tests/delivery_options_test.py
"""
import asyncio
import inspect
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:DELIVERY_OPTIONS_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10006")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from telegram.ext import ConversationHandler  # noqa: E402

import handlers.manual_post as MP  # noqa: E402
import database as db_mod  # noqa: E402
import scheduler as sch  # noqa: E402
from keyboards import inline as KI  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, callback_byte_len,
)
from translations import (  # noqa: E402
    MANUAL_POST_I18N, manual_post_parity_report, manual_post_t,
)

USER_ID = 8888
CHANNEL_ID = "-1001234567890"


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context/DB fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, text=None, chat_id=USER_ID):
        self.text = text
        self.caption = None
        self.photo = None
        self.video = None
        self.document = None
        self.animation = None
        self.chat_id = chat_id
        self.message_id = 1
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(kind="text", text=text, **kwargs))
        return SimpleNamespace(message_id=10)

    async def reply_photo(self, photo=None, **kwargs):
        self.sent.append(dict(kind="photo", photo=photo, **kwargs))
        return SimpleNamespace(message_id=11)


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append(dict(reply_markup=reply_markup))
        return True


def _update_msg(msg):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=msg.from_user, callback_query=None)


def _update_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user,
                           callback_query=query)


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(
        user_data=ud, chat_data={},
        bot=SimpleNamespace(username="postassist_test_bot"),
        application=None,
    )


def _flat_cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _flat_buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def _run(coro):
    return asyncio.run(coro)


class _FakeDB:
    """database.run_db'ni soxtalashtiradi va chaqiruvlarni yozib boradi."""

    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []
        self._orig = db_mod.run_db
        db_mod.run_db = self._fake

    async def _fake(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        try:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            record = dict(bound.arguments)
        except Exception:
            record = dict(kwargs)
        self.calls.append((name, record))
        return self.values.get(name)

    def calls_of(self, name):
        return [kw for n, kw in self.calls if n == name]

    def restore(self):
        db_mod.run_db = self._orig


def _start_manual_flow(ctx, text="Yangi mahsulot: endi -30% chegirma!"):
    """✍️ entry → kontent → PREVIEW. Qaytaradi: (msg, state, fake)."""
    fake = _FakeDB({"get_user_channels": [((CHANNEL_ID, "Kanal A"))],
                    "add_post": 555})
    fake.values["get_user_channels"] = [(CHANNEL_ID, "Kanal A")]
    entry_msg = _Msg(text="ok")
    state = _run(MP.manual_post_entry(_update_msg(entry_msg), ctx))
    if state != MP.MANUAL_AWAIT_CONTENT:
        fake.restore()
        return None, state, fake
    msg = _Msg(text=text)
    state2 = _run(MP.manual_content_received(_update_msg(msg), ctx))
    return msg, state2, fake


# ============================================================================
# TEST 1 — i18n (uz/ru/en) + paritet
# ============================================================================
def test_i18n_delivery_options():
    print("\n== TEST 1: i18n — delivery options kalitlari (uz/ru/en) ==")
    keys = (
        "mp_btn_delivery", "mp_dlv_title", "mp_dlv_notification",
        "mp_dlv_protect", "mp_dlv_pin", "mp_dlv_on", "mp_dlv_off",
        "mp_extras_delivery", "mp_dlv_opt_silent", "mp_dlv_opt_protected",
        "mp_dlv_opt_autopin",
    )
    for lang in LANGS:
        table = MANUAL_POST_I18N[lang]
        for key in keys:
            check(f"[{lang}] {key} mavjud va bo'sh emas",
                  bool(str(table.get(key, "")).strip()), str(table.get(key)))
    rep = manual_post_parity_report()
    check("manual_post i18n pariteti SAQLANGAN (in_sync)",
          rep.get("in_sync") is True, str(rep))
    # Tugma matnlari spesdagi belgilar bilan boshlanadi.
    check("[uz] ⚙️ tugma spes nomi bilan",
          manual_post_t("mp_btn_delivery", "uz") == "⚙️ Qo'shimcha sozlamalar",
          manual_post_t("mp_btn_delivery", "uz"))
    check("[ru] ⚙️ tugma mavjud",
          "⚙️" in manual_post_t("mp_btn_delivery", "ru"),
          manual_post_t("mp_btn_delivery", "ru"))
    check("[en] ⚙️ tugma mavjud",
          "⚙️" in manual_post_t("mp_btn_delivery", "en"),
          manual_post_t("mp_btn_delivery", "en"))


# ============================================================================
# TEST 2 — UI: preview'da ⚙️ tugma; 4 qatorli panel SPEKSI buzilmaydi
# ============================================================================
def test_ui_preview_and_delivery_keyboard():
    print("\n== TEST 2: UI — preview ⚙️ tugma + delivery klaviatura ==")
    # 2a) 4 qatorli universal panel SPEKSI o'zgarmagan (qo'riqxonа).
    for lang in LANGS:
        kb = KI.get_manual_post_panel(lang)
        rows = kb.inline_keyboard
        check(f"[{lang}] panel AYNAN 4 qator (qo'riqxonа)",
              len(rows) == 4 and all(len(r) == 2 for r in rows), str(rows))
        cbs = _flat_cbs(kb)
        check(f"[{lang}] panel kanonik 8 amal",
              cbs == ["mnp_now", "mnp_time", "mnp_react", "mnp_url",
                      "mnp_24h", "mnp_repeat", "mnp_edit", "mnp_cancel"],
              str(cbs))

    # 2b) Preview markup'da ⚙️ Qo'shimcha sozlamalar to'liq qator bo'ladi.
    for lang in LANGS:
        ctx = _ctx(lang)
        msg, state, fake = _start_manual_flow(ctx)
        check(f"[{lang}] preview tayyor", state == MP.MANUAL_PREVIEW,
              str(state))
        markup = msg.sent[-1]["reply_markup"]
        cbs = _flat_cbs(markup)
        check(f"[{lang}] preview'da CB_MANUAL_DELIVERY bor",
              KI.CB_MANUAL_DELIVERY in cbs, str(cbs))
        check(f"[{lang}] ⚙️ tugma O'Z QATORIDA (paneli buzmaydi)",
              any(len(row) == 1 and row[0].callback_data == KI.CB_MANUAL_DELIVERY
                  for row in markup.inline_keyboard), str(cbs))
        check(f"[{lang}] panel 8 amali tartibi saqlangan",
              cbs[:8] == ["mnp_now", "mnp_time", "mnp_react", "mnp_url",
                          "mnp_24h", "mnp_repeat", "mnp_edit", "mnp_cancel"],
              str(cbs))
        fake.restore()

    # 2c) Delivery klaviaturasi: 3 toggle + orqaga; ✅/❌ holatlari.
    kb_off = KI.get_manual_delivery_keyboard({}, "uz")
    check("delivery kb: 4 qator (3 toggle + orqaga)",
          len(kb_off.inline_keyboard) == 4,
          str(kb_off.inline_keyboard))
    labels_off = [b.text for row in kb_off.inline_keyboard for b in row]
    check("delivery kb: barchasi ❌ (o'chirilgan)",
          all(manual_post_t("mp_dlv_off", "uz") in t for t in labels_off[:3]),
          str(labels_off))
    kb_on = KI.get_manual_delivery_keyboard({"dn": True, "pc": False,
                                             "ap": True}, "uz")
    labels_on = [b.text for row in kb_on.inline_keyboard for b in row]
    check("toggle dn → ✅ Yoqilgan",
          manual_post_t("mp_dlv_on", "uz") in labels_on[0]
          and manual_post_t("mp_dlv_off", "uz") in labels_on[1],
          str(labels_on))
    check("toggle ap → ✅ Yoqilgan (3-qator)",
          manual_post_t("mp_dlv_on", "uz") in labels_on[2], str(labels_on))
    cbs_dlv = _flat_cbs(kb_off)
    check("delivery kb callback'lari: dn/pc/ap + orqaga",
          cbs_dlv == ["mnp_dlt:dn", "mnp_dlt:pc", "mnp_dlt:ap",
                      KI.CB_MANUAL_DLV_BACK], str(cbs_dlv))
    for data in cbs_dlv:
        check(f"callback {data!r} 1..64 bayt",
              1 <= callback_byte_len(data) <= CALLBACK_DATA_MAX_BYTES, data)
    # Toggle kaliti parseri: faqat ma'lum kalitlar.
    check("parser: mnp_dlt:dn → 'dn'",
          KI.delivery_toggle_key_from_callback("mnp_dlt:dn") == "dn", "")
    check("parser: mnp_dlt:hack → None",
          KI.delivery_toggle_key_from_callback("mnp_dlt:hack") is None, "")
    check("parser: boshqa callback → None",
          KI.delivery_toggle_key_from_callback(KI.CB_MANUAL_URL_BTN) is None,
          "")
    # Har uch tilda ham toggle callback'lari TILGA bog'liq emas.
    for lang in LANGS:
        kb = KI.get_manual_delivery_keyboard({"dn": True}, lang)
        check(f"[{lang}] toggle callback'lari kanonik",
              _flat_cbs(kb) == ["mnp_dlt:dn", "mnp_dlt:pc", "mnp_dlt:ap",
                                KI.CB_MANUAL_DLV_BACK], str(_flat_cbs(kb)))


# ============================================================================
# TEST 3 — OQIM: menyu, toggle On/Off, orqaga, preview xulosasi
# ============================================================================
def test_delivery_options_flow():
    print("\n== TEST 3: oqim — menyu ochish, toggle, orqaga ==")
    for lang in LANGS:
        ctx = _ctx(lang)
        msg, state, fake = _start_manual_flow(ctx)
        # 1) ⚙️ bosiladi → sozlamalar oynasi.
        q = _Query(KI.CB_MANUAL_DELIVERY, msg)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check(f"[{lang}] ⚙️ → MANUAL_PREVIEW", st == MP.MANUAL_PREVIEW,
              str(st))
        menu = q.message.sent[-1]
        check(f"[{lang}] sozlamalar oynasi matni (mp_dlv_title)",
              menu["text"] == manual_post_t("mp_dlv_title", lang),
              menu["text"][:60])
        check(f"[{lang}] oynada delivery klaviaturasi bor",
              _flat_cbs(menu["reply_markup"]) == [
                  "mnp_dlt:dn", "mnp_dlt:pc", "mnp_dlt:ap",
                  KI.CB_MANUAL_DLV_BACK], str(_flat_cbs(menu["reply_markup"])))

        # 2) 🔇 ovozsiz toggle → user_data + klaviatura qayta chiziladi.
        q_dn = _Query("mnp_dlt:dn", menu and _Msg())
        st_dn = _run(MP.manual_panel_callback(_update_query(q_dn), ctx))
        check(f"[{lang}] toggle dn → MANUAL_PREVIEW",
              st_dn == MP.MANUAL_PREVIEW, str(st_dn))
        check(f"[{lang}] toggle dn → user_data True",
              ctx.user_data.get(MP.UD_DISABLE_NOTIFICATION) is True,
              str(ctx.user_data))
        check(f"[{lang}] toggle dn → klaviatura edit qilindi",
              len(q_dn.edits) == 1
              and q_dn.edits[0].get("reply_markup") is not None,
              str(q_dn.edits))
        edited = q_dn.edits[0]["reply_markup"]
        check(f"[{lang}] edited kb: dn ✅, qolganlari ❌",
              manual_post_t("mp_dlv_on", lang)
              in edited.inline_keyboard[0][0].text
              and manual_post_t("mp_dlv_off", lang)
              in edited.inline_keyboard[1][0].text,
              str(edited.inline_keyboard[0][0].text))

        # 3) Yana bosiladi → OFF (toggle qaytadi).
        q_dn2 = _Query("mnp_dlt:dn", _Msg())
        _run(MP.manual_panel_callback(_update_query(q_dn2), ctx))
        check(f"[{lang}] toggle dn yana → False (On/Off)",
              ctx.user_data.get(MP.UD_DISABLE_NOTIFICATION) is False,
              str(ctx.user_data))

        # 4) 🔒 va 📌 yoqiladi.
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:pc", _Msg())), ctx))
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:ap", _Msg())), ctx))
        check(f"[{lang}] pc+ap yoqildi",
              ctx.user_data.get(MP.UD_PROTECT_CONTENT) is True
              and ctx.user_data.get(MP.UD_AUTO_PIN) is True, str(ctx.user_data))

        # 5) Noma'lum toggle kaliti — holat O'ZGARMAYDI.
        before = dict(ctx.user_data)
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:hack", _Msg())), ctx))
        check(f"[{lang}] noma'lum toggle kaliti holatni buzmaydi",
              ctx.user_data == before, "")

        # 6) ◀️ Orqaga → preview + xulosa qatori (faqat yoqilganlar).
        q_back = _Query(KI.CB_MANUAL_DLV_BACK, _Msg())
        st_back = _run(MP.manual_panel_callback(_update_query(q_back), ctx))
        check(f"[{lang}] orqaga → MANUAL_PREVIEW",
              st_back == MP.MANUAL_PREVIEW, str(st_back))
        preview = q_back.message.sent[-1]
        raw_tmpl = str(MANUAL_POST_I18N[lang]["mp_extras_delivery"])
        head = raw_tmpl.split("{options}")[0]
        check(f"[{lang}] preview matnida ⚙️ xulosa qatori bor",
              head in preview["text"], preview["text"][:200])
        check(f"[{lang}] xulosada YOQILGAN parametrlar (pc+ap, dn o'chirilgan)",
              manual_post_t("mp_dlv_opt_protected", lang) in preview["text"]
              and manual_post_t("mp_dlv_opt_autopin", lang) in preview["text"]
              and manual_post_t("mp_dlv_opt_silent", lang)
              not in preview["text"],
              preview["text"][:220])
        fake.restore()

    # 7) Sessiya tugagach (kontent yo'q) — stale himoya ishlaydi.
    ctx = _ctx("uz")
    fake = _FakeDB({})
    try:
        q = _Query(KI.CB_MANUAL_DELIVERY, _Msg())
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("stale: kontentsiz ⚙️ → sessiya eskirgani xabari + END",
              st == ConversationHandler.END and not fake.calls_of("add_post"),
              str(st))
    finally:
        fake.restore()


# ============================================================================
# TEST 4 — PUBLISH: 3 parametr db.add_post'ga uzatiladi, tozalash ishlaydi
# ============================================================================
def test_publish_passes_delivery_options():
    print("\n== TEST 4: publish — add_post'ga uzatish + tozalash ==")
    ctx = _ctx("uz")
    msg, state, fake = _start_manual_flow(ctx)
    try:
        # 🔒 + 📌 yoqiladi (🔇 yo'q — False uzatilishi ham tekshiriladi).
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:pc", _Msg())), ctx))
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:ap", _Msg())), ctx))
        q = _Query(KI.CB_MANUAL_NOW, msg)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("🚀 → END (yuborildi)", st == ConversationHandler.END, str(st))
        saves = fake.calls_of("add_post")
        check("add_post AYNAN 1 marta", len(saves) == 1, str(len(saves)))
        kw = saves[0]
        check("add_post: disable_notification=False (o'chirilgan)",
              kw.get("disable_notification") is False, str(kw))
        check("add_post: protect_content=True",
              kw.get("protect_content") is True, str(kw))
        check("add_post: auto_pin=True",
              kw.get("auto_pin") is True, str(kw))
        # Eski maydonlar buzilmagan.
        check("add_post: channel_id/content joyida",
              str(kw.get("channel_id")) == CHANNEL_ID
              and "chegirma" in str(kw.get("content")), str(kw)[:200])
        # Yakunda holat TOZALANADI.
        check("yuborilgach delivery holati tozalandi",
              all(ctx.user_data.get(k) is None for k in (
                  MP.UD_DISABLE_NOTIFICATION, MP.UD_PROTECT_CONTENT,
                  MP.UD_AUTO_PIN)), str(ctx.user_data))
    finally:
        fake.restore()

    # ❌ Bekor qilish ham holatni tozalaydi.
    ctx2 = _ctx("uz")
    msg2, state2, fake2 = _start_manual_flow(ctx2)
    try:
        _run(MP.manual_panel_callback(
            _update_query(_Query("mnp_dlt:dn", _Msg())), ctx2))
        check("bekorlashdan oldin dn=True",
              ctx2.user_data.get(MP.UD_DISABLE_NOTIFICATION) is True, "")
        q = _Query(KI.CB_MANUAL_CANCEL, msg2)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx2))
        check("❌ → END", st == ConversationHandler.END, str(st))
        check("bekor qilish delivery holatini tozalaydi",
              all(ctx2.user_data.get(k) is None for k in (
                  MP.UD_DISABLE_NOTIFICATION, MP.UD_PROTECT_CONTENT,
                  MP.UD_AUTO_PIN)), str(ctx2.user_data))
        check("bekor qilishda add_post CHAQIRILMADI",
              not fake2.calls_of("add_post"), str(fake2.calls))
    finally:
        fake2.restore()


# ============================================================================
# TEST 5 — DB: ustunlar, migratsiyalar, add_post imzosi, RETURNING tartibi
# ============================================================================
def test_database_layer():
    print("\n== TEST 5: DB — ustunlar/migratsiyalar/RETURNING tartibi ==")
    sig = inspect.signature(db_mod.add_post)
    for name in ("disable_notification", "protect_content", "auto_pin"):
        param = sig.parameters.get(name)
        check(f"add_post({name}=...) mavjud, default False",
              param is not None and param.default is False,
              str(param))
    src = Path(ROOT / "database.py").read_text(encoding="utf-8")
    check("CREATE TABLE scheduled_posts: 3 ustun",
          all(col in src for col in (
              "disable_notification BOOLEAN DEFAULT FALSE",
              "protect_content BOOLEAN DEFAULT FALSE",
              "auto_pin BOOLEAN DEFAULT FALSE")), "")
    check("migratsiyalar: 3 ta ADD COLUMN IF NOT EXISTS",
          src.count("ADD COLUMN IF NOT EXISTS disable_notification") == 1
          and src.count("ADD COLUMN IF NOT EXISTS protect_content") == 1
          and src.count("ADD COLUMN IF NOT EXISTS auto_pin") == 1, "")
    check("get_due_posts RETURNING: 3 ustun OXIRIDA (eski indekslar saqlanadi)",
          "sp.delete_after_hours, sp.reaction_emojis,\n"
          "                          sp.disable_notification, sp.protect_content, sp.auto_pin"
          in src, "")


# ============================================================================
# TEST 6 — SCHEDULER: Telegram API'ga to'g'ridan-to'g'ri uzatish + auto_pin
# ============================================================================
class _FakeBot:
    """send_* va pin_chat_message chaqiruvlarini yozib boradi."""

    def __init__(self, pin_error=None):
        self.calls = []
        self.pins = []
        self._mid = 100
        self._pin_error = pin_error

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self._mid += 1
        self.calls.append(("send_message",
                           dict(chat_id=chat_id, text=text,
                                reply_markup=reply_markup, **kw)))
        return SimpleNamespace(message_id=self._mid)

    async def pin_chat_message(self, chat_id=None, message_id=None, **kw):
        if self._pin_error is not None:
            raise self._pin_error
        self.pins.append(dict(chat_id=chat_id, message_id=message_id, **kw))
        return True


def _make_post(flags=(False, False, False)):
    """get_due_posts shaklidagi post tuple'i (oxirida 3 ta flag)."""
    dn, pc, ap = flags
    return (
        9101, 42, CHANNEL_ID, "text", "Salom delivery options", None,
        None, None, False, datetime.now(timezone.utc),
        "none", None, None, None, 0, None, dn, pc, ap,
    )


def _scheduler_db_fake(calls):
    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing",
                    "attempt_count": 0, "idempotency_key": "k-dlv"}
        if name == "is_premium":
            return True          # PRO — watermark yo'q
        if name == "get_setting":
            return ""            # brand_text bo'sh
        if name == "get_ad_settings":
            return {"channel_ad_status": False}  # reklama o'chirilgan
        if name in ("mark_post_processing", "mark_post_as_sent",
                    "mark_post_status", "mark_sent_by_key"):
            return True
        return None

    return fake_run_db


def test_scheduler_delivery_options():
    print("\n== TEST 6: scheduler — API'ga uzatish + auto_pin ==")
    orig_run_db = sch.db.run_db
    orig_path = sch.SENT_JOURNAL_PATH
    try:
        # 6a) Barcha flaglar TRUE → send kwargs + pin.
        calls = []
        sch.db.run_db = _scheduler_db_fake(calls)
        bot = _FakeBot()
        _run(sch._execute_send(bot, _make_post(flags=(True, True, True))))
        sends = [c for c in bot.calls if c[0] == "send_message"]
        check("text post aynan 1 marta yuborildi", len(sends) == 1,
              str(bot.calls))
        kwargs = sends[0][1]
        check("send_message: disable_notification=True uzatildi",
              kwargs.get("disable_notification") is True, str(kwargs))
        check("send_message: protect_content=True uzatildi",
              kwargs.get("protect_content") is True, str(kwargs))
        check("auto_pin: pin_chat_message AYNAN 1 marta",
              len(bot.pins) == 1, str(bot.pins))
        check("pin: kanal + sent message_id",
              bot.pins and str(bot.pins[0].get("chat_id")) == CHANNEL_ID
              and bot.pins[0].get("message_id") == 101, str(bot.pins))
        check("pin: disable_notification=True (spes bo'yicha)",
              bot.pins and bot.pins[0].get("disable_notification") is True,
              str(bot.pins))
        names = [n for n, _a in calls]
        check("delivery 'sent' markazi yozildi",
              "mark_post_as_sent" in names or "mark_sent_by_key" in names,
              str(names))

        # 6b) ESKI 16 maydonli tuple → pin YO'Q, send kwargs YO'Q.
        calls.clear()
        bot2 = _FakeBot()
        legacy = _make_post()[:16]
        _run(sch._execute_send(bot2, legacy))
        sends2 = [c for c in bot2.calls if c[0] == "send_message"]
        check("legacy tuple: post yuborildi", len(sends2) == 1, str(bot2.calls))
        check("legacy tuple: delivery kwargs YO'Q (eski xatti-harakat)",
              "disable_notification" not in sends2[0][1]
              and "protect_content" not in sends2[0][1], str(sends2[0][1]))
        check("legacy tuple: pin CHAQIRILMADI", len(bot2.pins) == 0,
              str(bot2.pins))

        # 6c) Faqat auto_pin → send kwargs YO'Q, pin bor.
        calls.clear()
        bot3 = _FakeBot()
        _run(sch._execute_send(bot3, _make_post(flags=(False, False, True))))
        sends3 = [c for c in bot3.calls if c[0] == "send_message"]
        check("faqat auto_pin: send kwargs YO'Q",
              "disable_notification" not in sends3[0][1], str(sends3[0][1]))
        check("faqat auto_pin: pin chaqirildi", len(bot3.pins) == 1,
              str(bot3.pins))

        # 6d) Pin xatosi FAIL-SOFT: yuborish/markeri buzilmaydi.
        calls.clear()
        bot4 = _FakeBot(pin_error=RuntimeError("not enough rights"))
        try:
            _run(sch._execute_send(bot4, _make_post(flags=(True, True, True))))
            ok = True
        except Exception as e:
            ok = False
            print(f"    xato: {e}")
        check("pin xatosi _execute_send'ni YIQILTIRMAYDI", ok, "")
        check("pin xatosida ham post yuborilgan", len(bot4.calls) == 1, "")
        names4 = [n for n, _a in calls]
        check("pin xatosida ham 'sent' markeri yozildi",
              "mark_post_as_sent" in names4 or "mark_sent_by_key" in names4,
              str(names4))
    finally:
        sch.db.run_db = orig_run_db
        sch.SENT_JOURNAL_PATH = orig_path
        sch._UNPERSISTED_SENT.clear()


# ============================================================================
def main():
    print("=" * 72)
    print("⚙️ QO'SHIMCHA SOZLAMALAR (DELIVERY OPTIONS) — TEST SUITE")
    print("=" * 72)
    test_i18n_delivery_options()
    test_ui_preview_and_delivery_keyboard()
    test_delivery_options_flow()
    test_publish_passes_delivery_options()
    test_database_layer()
    test_scheduler_delivery_options()
    print("\n" + "=" * 72)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" DELIVERY OPTIONS TESTLARI 100% YASHIL ✔")
    else:
        print(f" !! {failures} ta tekshiruv YIQILDI")
    print("=" * 72)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
