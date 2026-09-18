#!/usr/bin/env python3
"""💬 POSTASSIST V2 · 4-QISM (so'nggi qism) — QO'LLAB-QUVVATLASH KONTRAKT TESTLARI.

Deterministik, tarmoqsiz (DB va Telegram mock qilinadi).

Qamrov (topshiriq bandlari bo'yicha):

  TEST 1 — YAGONA MUROJAAT OQIMI (ONE-TIME TICKET FSM):
           * [💬 Qo'llab-quvvatlash] bosilganda AYNAN shu yo'riqnoma chiqadi:
             «✍️ Savol yoki muammoingizni bitta xabarda to'liq yozib qoldiring.
              (Adminlarimiz tez orada xabaringizni ko'rib chiqadi).»
             va klaviaturada faqat [◀️ Orqaga] bo'ladi (uchala tilda);
           * foydalanuvchi matn (yoki rasm+izoh) yuborganda FSM DARHOL
             yopiladi (``ConversationHandler.END``) — ketma-ket yozish
             adminga SPAM bo'lib bormaydi (cooldown isboti bilan);
           * foydalanuvchiga AYNAN «✅ Murojaatingiz adminga yetkazildi.
             Javob shu yerda keladi.» tasdig'i beriladi;
           * [◀️ Orqaga] oqimni yopadi va 👤 Profil hub'ini qaytaradi.

  TEST 2 — ADMINGA XABAR YUBORISH:
           * murojaat ``.env`` dagi ADMIN_IDS ro'yxatidagi HAR BIR adminga
             yetib boradi va shakl AYNAN:
                 📩 Yangi murojaat!
                 👤 Kimdan: @username (ID: <code>{user_id}</code>)
                 📝 Xabar:
                 {matn}
           * Reply kuzatuvi uchun (admin_chat_id, admin_message_id) juftligi
             DB'ga (``support_ticket_deliveries``) va xotiradagi keshga
             yoziladi; rasm+izoh yuborilsa foto caption sifatida ketadi;
           * adminlar sozlanmagan bo'lsa foydalanuvchiga ROSTGO'Y javob
             («hali sozlanmagan»), soxta «yetkazildi» YO'Q.

  TEST 3 — ADMINDAN TO'G'RIDAN-TO'G'RI JAVOB (ADMIN REPLY DISPATCHER):
           * admin bot yuborgan xabarga Telegram «Reply» orqali yozsa —
             murojaat egasiga AYNAN:
                 💬 Qo'llab-quvvatlash xizmati javobi:
                 {admin_javobi}
             yetib boradi va adminga «✅ Javob foydalanuvchiga yetkazildi»
             tasdig'i qaytadi; murojaat DB'da 'answered' bo'ladi;
           * bot QAYTA ISHGA TUSHGAN holat (xotira keshi bo'sh, DB'da bor)
             ham ishlaydi — javob yo'qolmaydi;
           * murojaatga bog'lanmagan reply eski fallback oqimiga o'tadi.

  TEST 4 — XAVFSIZLIK (NOT-AN-ADMIN):
           * ``SUPPORT_ADMIN_REPLY_FILTER`` oddiy foydalanuvchi reply'siga
             MOS KELMAYDI (handler umuman ishga tushmaydi);
           * handler ichida ham ``from_user.id`` qayta tekshiriladi:
             admin bo'lmagan foydalanuvchi murojaat ID'sini bilsa ham
             HECH NARSA yuborilmaydi (fail-closed);
           * reply bo'lmagan xabar va guruh reply'si ham mos kelmaydi.

  TEST 5 — REGRESSIYA VA PARITET:
           * i18n UZ↔RU↔EN 100% paritet, spec matnlari aynan;
           * callback'lar ≤64 bayt, FSM holati 540 boshqa oqimlar bilan
             to'qnashmaydi (530–539 manbalar, 601+ to'lovlar);
           * schema.sql ↔ database.EXPECTED_TABLES paralleligi;
           * ⚙️ Sozlamalar klaviaturasi o'zgarmagan (7 tugma, help_support);
           * admin Reply handler ro'yxatda va catch-all
             ``expired_session_callback`` dan OLDIN turadi.

Ishga tushirish::

    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/support_ticket_flow_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:SUPPORT_FLOW_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "900900")
os.environ.setdefault("ADMIN_IDS", "900901")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("SUPPORT_USERNAME", "")
os.environ.setdefault("PORT", "10015")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = ROOT / "telegram_bot"
sys.path.insert(0, str(BOT_DIR))

import database as db_mod  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

import handlers  # noqa: E402,F401 — barcha handlerlarni reyestrga qo'yadi
import handlers.support as sup  # noqa: E402

LANGS = ("uz", "ru", "en")
USER_ID = 424242
ADMIN_A = 900900          # config.ADMIN_ID
ADMIN_B = 900901          # config.ADMIN_IDS
ADMINS = sorted(db_mod.__dict__.get("ADMIN_IDS_SET", None) or {}) or [ADMIN_A, ADMIN_B]

PASSED = 0
FAILURES = 0

# --- SPEK MATNLARI (topshiriqda AYNAN berilgan) --------------------------
SPEC_PROMPT = (
    "✍️ Savol yoki muammoingizni bitta xabarda to'liq yozib qoldiring.\n"
    "(Adminlarimiz tez orada xabaringizni ko'rib chiqadi)."
)
SPEC_CONFIRM = "✅ Murojaatingiz adminga yetkazildi. Javob shu yerda keladi."
SPEC_DELIVERED = "✅ Javob foydalanuvchiga yetkazildi"
SPEC_REPLY_HEADER = "💬 Qo'llab-quvvatlash xizmati javobi:"


def check(label, condition, extra=""):
    """Bitta tekshiruv natijasini hisobga oladi va chop etadi."""
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label} {extra}")
    return bool(condition)


def header(tag, title):
    print(f"\n===== {tag}) {title} =====")


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# YENGIL FAKE'LAR (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """``reply_text`` ni yozib boruvchi soxta xabar."""

    def __init__(self, text=None, caption=None, photo=None, message_id=10,
                 chat_id=None, user_id=None):
        self.text = text
        self.caption = caption
        self.photo = photo
        self.message_id = message_id
        self.chat_id = chat_id if chat_id is not None else (user_id or USER_ID)
        self.chat = SimpleNamespace(id=self.chat_id, type="private")
        self.reply_to_message = None
        self.sent = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, markup=reply_markup, parse_mode=parse_mode))
        return _Msg(message_id=self.message_id + 1, chat_id=self.chat_id)


class _Photo:
    def __init__(self, file_id):
        self.file_id = file_id


class _Query:
    """CallbackQuery fake — ``answer``/``edit_message_text`` yozib boradi."""

    def __init__(self, data="help_support", message=None, user_id=USER_ID,
                 username="ali"):
        self.data = data
        self.message = message if message is not None else _Msg(message_id=5)
        self.from_user = SimpleNamespace(id=user_id, username=username,
                                         first_name="Ali")
        self.edits = []
        self.answered = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered.append((text, show_alert))
        return True

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append(dict(text=text, markup=reply_markup, parse_mode=parse_mode))
        return True

    @property
    def screen(self):
        return self.edits[-1] if self.edits else {}


class _Bot:
    """``send_message``/``send_photo`` ni yozib boruvchi soxta bot."""

    username = "postassist_support_test_bot"

    def __init__(self, fail_for=()):
        self.out = []
        self._mid = 1000
        self.fail_for = set(fail_for)

    async def get_me(self):
        return SimpleNamespace(username=self.username)

    async def send_message(self, chat_id=None, text=None, **kw):
        if chat_id in self.fail_for:
            raise RuntimeError("blocked by user")
        self._mid += 1
        self.out.append(dict(kind="message", chat_id=chat_id, text=text,
                             message_id=self._mid, **kw))
        return SimpleNamespace(message_id=self._mid, chat_id=chat_id)

    async def send_photo(self, chat_id=None, photo=None, caption=None, **kw):
        if chat_id in self.fail_for:
            raise RuntimeError("blocked by user")
        self._mid += 1
        self.out.append(dict(kind="photo", chat_id=chat_id, text=caption,
                             photo=photo, message_id=self._mid, **kw))
        return SimpleNamespace(message_id=self._mid, chat_id=chat_id)


def _ctx(lang="uz", bot=None, user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={}, bot=bot or _Bot(),
                           application=None)


def _msg_update(msg, user_id=USER_ID, username="ali", first_name="Ali"):
    return SimpleNamespace(
        message=msg, effective_message=msg, callback_query=None,
        effective_user=SimpleNamespace(id=user_id, username=username,
                                       first_name=first_name),
    )


def _cb_update(query, user_id=USER_ID):
    return SimpleNamespace(message=None, effective_message=query.message,
                           callback_query=query, effective_user=query.from_user)


class _FakeDB:
    """``database.run_db`` mock — qo'llab-quvvatlash oqimi uchun deterministik."""

    def __init__(self, daily_count=0, fail_create=False):
        self.tickets = {}
        self.deliveries = {}       # (admin_chat_id, admin_message_id) -> ticket_id
        self.answered = []
        self.calls = []
        self.daily_count = daily_count
        self.fail_create = fail_create

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append(name)
        if name == "get_user_language":
            return "uz"
        if name == "count_user_support_tickets":
            return self.daily_count
        if name == "create_support_ticket":
            if self.fail_create:
                return 0
            ticket_id = len(self.tickets) + 1
            self.tickets[ticket_id] = dict(
                id=ticket_id, user_id=int(args[0]), username=args[1] or "",
                message_text=args[2] or "", has_media=bool(args[3]),
                display_name=("@" + args[1]) if args[1] else "",
            )
            return ticket_id
        if name == "attach_support_ticket_delivery":
            self.deliveries[(int(args[1]), int(args[2]))] = int(args[0])
            return True
        if name == "get_support_ticket_by_admin_message":
            ticket_id = self.deliveries.get((int(args[0]), int(args[1])))
            return self.tickets.get(ticket_id) if ticket_id else None
        if name == "mark_support_ticket_answered":
            self.answered.append((int(args[0]), int(args[1])))
            return True
        if name == "get_support_ticket":
            return self.tickets.get(int(args[0]))
        # 👤 Profil hub'i (sup_back) uchun minimal ma'lumotlar.
        if name == "get_referral_stats":
            return {"ai_credits": 5, "streak": 1, "referrals_count": 0}
        if name == "get_user_channels":
            return []
        if name == "get_user_code":
            return "TST001"
        return None


class _DBPatch:
    """``db_mod.run_db`` ni vaqtincha almashtiradi."""

    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.orig = db_mod.run_db
        db_mod.run_db = self.fake.run_db
        return self.fake

    def __exit__(self, *exc):
        db_mod.run_db = self.orig
        return False


# ---------------------------------------------------------------------------
# APP/ROUTING YORDAMCHILARI (haqiqiy PTB Update obyektlari, tarmoqsiz)
# ---------------------------------------------------------------------------
_RAW_BOT = None


def _ptb_bot():
    global _RAW_BOT
    if _RAW_BOT is None:
        from telegram import Bot

        _RAW_BOT = Bot("123456:SUPPORT_FLOW_TEST_TOKEN")
    return _RAW_BOT


def _build_app():
    from telegram.ext import ApplicationBuilder

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:SUPPORT_FLOW_TEST_TOKEN").build()
    handlers.register_all_handlers(app)
    return app


def _conversation(app):
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            if isinstance(handler, ConversationHandler):
                return handler
    return None


def _cb_update_real(data, user_id=USER_ID):
    from telegram import Update

    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "1", "chat_instance": "x", "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "message": {
                "message_id": 9, "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 999, "is_bot": True, "first_name": "Bot"},
                "text": "👤 Profil",
            },
        },
    }, _ptb_bot())


def _msg_update_real(text="Salom", user_id=USER_ID, reply_to_message_id=None,
                     chat_type="private", photo=False):
    from telegram import Update

    message = {
        "message_id": 11, "date": 0,
        "chat": {"id": user_id, "type": chat_type},
        "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
    }
    if photo:
        message["photo"] = [{
            "file_id": "router-photo", "file_unique_id": "uq1",
            "width": 90, "height": 90, "file_size": 100,
        }]
        message["caption"] = text
    else:
        message["text"] = text
    if reply_to_message_id is not None:
        message["reply_to_message"] = {
            "message_id": reply_to_message_id, "date": 0, "text": "📩 Yangi murojaat!",
            "chat": {"id": user_id, "type": chat_type},
            "from": {"id": 999, "is_bot": True, "first_name": "Bot"},
        }
    return Update.de_json({"update_id": 2, "message": message}, _ptb_bot())


def _routed_names(app, update, groups_limit=1):
    """Update uchun mos keladigan handler callback nomlari (birinchi guruh)."""
    names = []
    for group in sorted(app.handlers)[:groups_limit]:
        for handler in app.handlers[group]:
            try:
                if handler.check_update(update):
                    names.append(getattr(getattr(handler, "callback", None),
                                         "__name__", type(handler).__name__))
            except Exception:
                continue
    return names


def _conv_routed_names(app, update, state):
    """Faol ``state`` bilan ``main_conv.check_update`` qaysi handlerni tanlaydi.

    Bu — HAQIQIY router tekshiruvi (entry point'lar + state handlerlar
    tartibi), shu sababli rasm/qo'shni oqimlar to'qnashuvi ham aniqlanadi.
    """
    conv = _conversation(app)
    if conv is None:
        return []
    conv._conversations[conv._get_key(update)] = state
    try:
        resolved = conv.check_update(update)
    finally:
        conv._conversations.pop(conv._get_key(update), None)
    if resolved is None:
        return []
    handler = resolved[2]
    return [getattr(getattr(handler, "callback", None), "__name__",
                    type(handler).__name__)]


def _entry_fn_names(app, update):
    conv = _conversation(app)
    names = set()
    if conv is None:
        return names
    for entry in conv.entry_points:
        try:
            if entry.check_update(update):
                callback = getattr(entry, "callback", None)
                names.add(getattr(callback, "__name__", ""))
        except Exception:
            continue
    return names


def _state_fn_names(app, update, state):
    conv = _conversation(app)
    names = set()
    if conv is None:
        return names
    for handler in conv.states.get(state, []):
        try:
            if handler.check_update(update):
                callback = getattr(handler, "callback", None)
                names.add(getattr(callback, "__name__", ""))
        except Exception:
            continue
    return names


def _flow_deliveries(fake_db):
    """Xotiradagi Reply kuzatuvi yozuvlari (admin_chat_id, message_id)."""
    return sorted(sup._ADMIN_DELIVERIES)


def _inline_rows(markup):
    if markup is None:
        return []
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def _flat_cbs(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ===========================================================================
# TEST 1 — YAGONA MUROJAAT OQIMI (ONE-TIME TICKET FSM)
# ===========================================================================
def test_one_time_ticket_flow():
    header("1", "💬 Yagona murojaat oqimi — FSM bir xabardan keyin DARHOL yopiladi")

    sup.reset_support_runtime_state()
    app = _build_app()
    conv = _conversation(app)
    check("main_conv mavjud", conv is not None)

    # 1a) [💬 Qo'llab-quvvatlash] → main_conv ENTRY POINT (support_ticket_entry).
    names = _entry_fn_names(app, _cb_update_real("help_support"))
    check("routing: help_support → support_ticket_entry (FSM entry)",
          "support_ticket_entry" in names, str(names))

    # 1b) Yo'riqnoma ekrani: spec matni + faqat [◀️ Orqaga].
    for lang in LANGS:
        bot = _Bot()
        ctx = _ctx(lang=lang, bot=bot)
        query = _Query("help_support")
        state = _run(sup.support_ticket_entry(_cb_update(query), ctx))
        check(f"[{lang}] help_support → SUPPORT_TICKET_INPUT (540)",
              state == sup.SUPPORT_TICKET_INPUT == 540, str(state))
        screen = query.screen
        check(f"[{lang}] yo'riqnoma ekrani chizildi (edit)",
              bool(query.edits), str(query.edits)[:80])
        rows = _inline_rows(screen.get("markup"))
        check(f"[{lang}] klaviatura AYNAN [◀️ Orqaga] (sup_back)",
              len(rows) == 1 and len(rows[0]) == 1
              and rows[0][0][1] == sup.CB_SUPPORT_BACK,
              str(rows))

    from translations import support_t as _support_t

    check("UZ yo'riqnoma matni topshiriqdagi matnga AYNAN mos",
          _support_t("sp_prompt", "uz") == SPEC_PROMPT,
          repr(_support_t("sp_prompt", "uz")))

    # 1c) Matn yuboriladi → FSM DARHOL yopiladi + tasdiq + adminga yetkazish.
    fake = _FakeDB()
    bot = _Bot()
    ctx = _ctx(bot=bot)
    msg = _Msg(text="Postim kanalga chiqmayapti, yordam bering")
    with _DBPatch(fake):
        state = _run(sup.support_message_received(_msg_update(msg), ctx))

    check("FSM DARHOL yopildi (ConversationHandler.END)",
          state == ConversationHandler.END, str(state))
    check("foydalanuvchiga tasdiq AYNAN spec matni",
          [s["text"] for s in msg.sent] == [SPEC_CONFIRM],
          str([s["text"] for s in msg.sent]))
    check("murojaat DB'ga yozildi (support_tickets)",
          len(fake.tickets) == 1
          and fake.tickets[1]["message_text"].startswith("Postim kanalga"),
          str(fake.tickets))
    check("adminlarga yetkazildi (ADMIN_IDS dagi har biriga)",
          sorted({o["chat_id"] for o in bot.out}) == sorted(ADMINS),
          str([(o["kind"], o["chat_id"]) for o in bot.out]))

    # 1d) SPAM: ikkinchi xabar adminga BORMASLIGI (cooldown + FSM yopiqligi).
    #     DIQQAT: 1c murojaatidan keyin cooldown AYNAN faol — bu yerda
    #     kesh TOZALANMAYDI, chunki himoya shu holatda tekshiriladi.
    bot2 = _Bot()
    ctx2 = _ctx(bot=bot2)
    msg2 = _Msg(text="yana bir xabar", message_id=20)
    with _DBPatch(_FakeDB()):
        state2 = _run(sup.support_message_received(_msg_update(msg2), ctx2))
    check("ketma-ket ikkinchi xabar adminga yuborilmadi (spam to'xtadi)",
          not bot2.out, str(bot2.out))
    check("ikkinchi xabar ham FSM'ni yopadi (END)",
          state2 == ConversationHandler.END, str(state2))

    # 1e) Rasm+izoh ham qabul qilinadi va foto adminga ketadi.
    #     (Cooldown oldingi murojaatdan qolmasligi uchun kesh tozalanadi —
    #      cooldown O'ZI alohida 1d bandida tekshirilgan.)
    sup.reset_support_runtime_state()
    fake3 = _FakeDB()
    bot3 = _Bot()
    ctx3 = _ctx(bot=bot3)
    photo_msg = _Msg(caption="Rasm bilan murojaat", photo=[_Photo("small"),
                                                           _Photo("big-file-id")])
    with _DBPatch(fake3):
        state3 = _run(sup.support_message_received(_msg_update(photo_msg), ctx3))
    check("rasm+izoh: FSM yopildi", state3 == ConversationHandler.END, str(state3))
    check("rasm+izoh: foto adminga caption bilan yuborildi",
          all(o["kind"] == "photo" and o["photo"] == "big-file-id" for o in bot3.out)
          and len(bot3.out) == len(ADMINS),
          str([(o["kind"], o["photo"]) for o in bot3.out]))
    check("rasm+izoh: has_media=True DB'da",
          all(t["has_media"] for t in fake3.tickets.values()), str(fake3.tickets))

    # 1e-2) Juda uzun izoh + rasm: matn alohida, rasm QISQA caption bilan
    #       ketadi — hech bir ma'lumot yo'qolmaydi (ikkala xabar Reply
    #       kuzatuviga ulanadi).
    sup.reset_support_runtime_state()
    fake_long = _FakeDB()
    long_bot = _Bot()
    with _DBPatch(fake_long):
        long_state = _run(sup.support_message_received(
            _msg_update(_Msg(caption="x" * 1500,
                             photo=[_Photo("long-photo")])),
            _ctx(bot=long_bot),
        ))
    kinds = [o["kind"] for o in long_bot.out]
    check("uzun izoh: FSM yopildi",
          long_state == ConversationHandler.END, str(long_state))
    check("uzun izoh: matn va rasm ALOHIDA yuborildi (ma'lumot yo'qolmaydi)",
          kinds == ["message", "photo"] * len(ADMINS), str(kinds))
    check("uzun izoh: matn to'liq (1500 belgi) yetib bordi",
          all(len(o["text"]) >= 1500 for o in long_bot.out if o["kind"] == "message"),
          str([len(o["text"] or "") for o in long_bot.out]))
    check("uzun izoh: ikkala xabar ham kuzatuvda (Reply ishlaydi)",
          len(_flow_deliveries(fake_long)) == len(ADMINS) * 2,
          str(fake_long.deliveries))

    # 1f) Matnsiz/rasmsiz xabar (stiker) — murojaat bo'lmaydi, oqim ochiq qoladi.
    sup.reset_support_runtime_state()
    bot4 = _Bot()
    ctx4 = _ctx(bot=bot4)
    stub = _Msg(text=None, photo=None)
    with _DBPatch(_FakeDB()):
        state4 = _run(sup.support_message_received(_msg_update(stub), ctx4))
    check("matnsiz xabar murojaat sifatida qabul qilinmadi",
          not bot4.out and len(stub.sent) == 1, str(stub.sent))
    check("matnsiz xabarda holat ochiq qoladi (540)",
          state4 == sup.SUPPORT_TICKET_INPUT == 540, str(state4))

    # 1g) [◀️ Orqaga] — oqim yopiladi va ⚙️ Sozlamalar hub'i qaytadi.
    bot5 = _Bot()
    ctx5 = _ctx(bot=bot5)
    query = _Query(sup.CB_SUPPORT_BACK)
    with _DBPatch(_FakeDB()):
        state5 = _run(sup.support_back_callback(_cb_update(query), ctx5))
    check("[◀️ Orqaga] → ConversationHandler.END",
          state5 == ConversationHandler.END, str(state5))
    check("[◀️ Orqaga] → ⚙️ Sozlamalar hub'i qayta chizildi",
          bool(query.edits) and "help_support" in _flat_cbs(query.screen.get("markup")),
          str(_flat_cbs(query.screen.get("markup"))))

    # 1g-2) Router darajasidagi isbot: 540 holatida HAM matn, HAM rasm+izoh
    #       ``support_message_received`` ga tushadi (rasm boshqa oqimga
    #       "o'g'irlanmaydi" — ImageEntryHandler faol dialogda None qaytaradi),
    #       menyu tugmalari esa odatdagidek ishlaydi.
    conv_state_names_text = _conv_routed_names(
        app, _msg_update_real("Yordam kerak"), sup.SUPPORT_TICKET_INPUT)
    check("540 holatida matn → support_message_received",
          "support_message_received" in conv_state_names_text,
          str(conv_state_names_text))
    photo_update = _msg_update_real("Rasm bilan izoh", photo=True)
    check("540 holatida rasm+izoh → support_message_received (rasm oqimi buzmaydi)",
          "support_message_received" in
          _conv_routed_names(app, photo_update, sup.SUPPORT_TICKET_INPUT),
          str(_conv_routed_names(app, photo_update, sup.SUPPORT_TICKET_INPUT)))

    # 1h) Holat faqat murojaat ekranida: FSM'dan tashqarida matn bu oqimga
    #     TUSHMASLIGI (spam himoyasining router darajasidagi isboti).
    plain_text = _msg_update_real("Salom, oddiy xabar")
    check("FSM'dan tashqarida matn support handleriga yo'naltirilmaydi",
          "support_message_received" not in _routed_names(app, plain_text),
          str(_routed_names(app, plain_text)))
    check("supl_back state handler ro'yxatda (faol holat uchun)",
          "support_back_callback" in _state_fn_names(
              app, _cb_update_real(sup.CB_SUPPORT_BACK), sup.SUPPORT_TICKET_INPUT),
          str(_state_fn_names(app, _cb_update_real(sup.CB_SUPPORT_BACK),
                              sup.SUPPORT_TICKET_INPUT)))


# ===========================================================================
# TEST 2 — ADMINGA XABAR SHAKLLANISHI
# ===========================================================================
def test_admin_delivery_format():
    header("2", "📩 Adminga xabar shakli (ADMIN_IDS) + Reply kuzatuvi yozuvi")

    sup.reset_support_runtime_state()
    ticket = {
        "id": 7, "user_id": USER_ID, "username": "ali",
        "display_name": "@ali", "message_text": "Kanalga ulanmayapti",
        "has_media": False,
    }
    for lang in LANGS:
        text = sup.build_admin_ticket_text(ticket, lang)
        check(f"[{lang}] sarlavha «Yangi murojaat» bilan boshlanadi",
              text.startswith("📩 "), text[:40])
        check(f"[{lang}] muallif: @ali (ID: <code>{USER_ID}</code>)",
              "@ali" in text and f"<code>{USER_ID}</code>" in text, text[:120])
        check(f"[{lang}] murojaat matni to'liq kiritilgan",
              "Kanalga ulanmayapti" in text, text[-80:])
        check(f"[{lang}] Reply bo'yicha ko'rsatma bor (adminsiz javob yo'qolmaydi)",
              "Reply" in text, text[-80:])

    # XSS/HTML himoyasi — foydalanuvchi teglari escape qilinadi.
    evil = dict(ticket, display_name="@evil", message_text="<b>bold</b> & <script>")
    escaped = sup.build_admin_ticket_text(evil, "uz")
    check("HTML-escape: foydalanuvchi teglari neytrallandi",
          "<script>" not in escaped and "&lt;script&gt;" in escaped,
          escaped[escaped.find("📝"):][:120])

    # Har bir admin + DB/xotira kuzatuvi.
    fake = _FakeDB()
    bot = _Bot()
    ctx = _ctx(bot=bot)
    with _DBPatch(fake):
        delivered = _run(sup._deliver_ticket_to_admins(ctx, ticket, ""))
    check("ADMIN_IDS dagi HAR BIR adminga yuborildi",
          delivered == len(ADMINS) and len(bot.out) == len(ADMINS), str(delivered))
    check("DB'ga (admin_chat_id, admin_message_id) kuzatuvi yozildi",
          len(fake.deliveries) == len(ADMINS), str(fake.deliveries))
    check("xotiradagi kesh ham to'ldirildi (tez reply uchun)",
          all(sup.cached_delivery(chat, mid) is not None
              for chat, mid in fake.deliveries),
          str(list(fake.deliveries)))
    check("kuzatuv murojaat ID'siga bog'landi",
          set(fake.deliveries.values()) == {ticket["id"]}, str(fake.deliveries))

    # Adminlar sozlanmagan bo'lsa — ROSTGO'Y javob, soxta tasdiq yo'q.
    sup.reset_support_runtime_state()
    msg = _Msg(text="Yordam kerak")
    ctx2 = _ctx(bot=_Bot())
    import config as cfg

    orig_ids = cfg.ADMIN_IDS_SET
    try:
        cfg.ADMIN_IDS_SET = frozenset()
        sup.ADMIN_IDS_SET = frozenset()
        with _DBPatch(_FakeDB()):
            state = _run(sup.support_message_received(_msg_update(msg), ctx2))
        replies = [s["text"] for s in msg.sent]
        check("adminlar yo'q: soxta «yetkazildi» YO'Q",
              replies and replies[0] != SPEC_CONFIRM
              and "sozlanmagan" in replies[0].lower(), str(replies))
        check("adminlar yo'q: FSM baribir yopiladi",
              state == ConversationHandler.END, str(state))
    finally:
        cfg.ADMIN_IDS_SET = orig_ids
        sup.ADMIN_IDS_SET = orig_ids


# ===========================================================================
# TEST 3 — ADMIN «REPLY» → FOYDALANUVCHIGA YETKAZISH
# ===========================================================================
def test_admin_reply_dispatch():
    header("3", "💬 Admin «Reply» javobi foydalanuvchiga yetib boradi")

    sup.reset_support_runtime_state()
    fake = _FakeDB()
    # 1) foydalanuvchi murojaati
    sender_bot = _Bot()
    sender_ctx = _ctx(bot=sender_bot)
    msg = _Msg(text="Post rejalashtirilmayapti")
    with _DBPatch(fake):
        _run(sup.support_message_received(_msg_update(msg), sender_ctx))

    admin_chat, admin_message_id = sorted(fake.deliveries)[0]
    check("admin xabari ID'si kuzatuvda (reply uchun)",
          admin_chat in ADMINS and admin_message_id > 0,
          f"{admin_chat}:{admin_message_id}")

    # 2) admin o'sha xabarga oddiy «Reply» yozadi
    admin_bot = _Bot()
    admin_ctx = _ctx(bot=admin_bot)
    admin_msg = _Msg(text="Muammo tuzatildi, qayta urinib ko'ring",
                     message_id=55, chat_id=admin_chat)
    admin_msg.reply_to_message = SimpleNamespace(message_id=admin_message_id)
    with _DBPatch(fake):
        _run(sup.support_admin_reply(
            _msg_update(admin_msg, user_id=admin_chat, username="admin"),
            admin_ctx,
        ))

    user_deliveries = [o for o in admin_bot.out if o["chat_id"] == USER_ID]
    check("javob foydalanuvchiga yuborildi (send_message)",
          len(user_deliveries) == 1, str(admin_bot.out))
    body = user_deliveries[0]["text"] if user_deliveries else ""
    check("javob sarlavhasi AYNAN spec matni",
          body.startswith(SPEC_REPLY_HEADER), body[:80])
    check("adminning javob matni to'liq yetib bordi",
          "Muammo tuzatildi" in body, body)
    admin_replies = [s["text"] for s in admin_msg.sent]
    check("adminga «✅ Javob foydalanuvchiga yetkazildi» tasdig'i",
          admin_replies == [SPEC_DELIVERED], str(admin_replies))
    check("murojaat DB'da 'answered' deb belgilandi",
          fake.answered == [(1, admin_chat)], str(fake.answered))

    # 3) Bot QAYTA ISHGA TUSHGAN holat: xotira keshi bo'sh, DB'da kuzatuv bor.
    sup._ADMIN_DELIVERIES.clear()
    admin_bot2 = _Bot()
    admin_msg2 = _Msg(text="Ikkinchi javob (restart'dan keyin)",
                      message_id=56, chat_id=admin_chat)
    admin_msg2.reply_to_message = SimpleNamespace(message_id=admin_message_id)
    with _DBPatch(fake):
        _run(sup.support_admin_reply(
            _msg_update(admin_msg2, user_id=admin_chat, username="admin"),
            _ctx(bot=admin_bot2),
        ))
    check("DB kuzatuvi orqali restart'dan keyin ham yetkazildi",
          any(o["chat_id"] == USER_ID and "Ikkinchi javob" in (o["text"] or "")
              for o in admin_bot2.out),
          str(admin_bot2.out))
    check("restart holatida ham admin tasdiq oldi",
          [s["text"] for s in admin_msg2.sent] == [SPEC_DELIVERED],
          str([s["text"] for s in admin_msg2.sent]))

    # 4) Murojaatga bog'lanmagan reply — eski fallback oqimi (buzilmaydi).
    sup.reset_support_runtime_state()
    other_bot = _Bot()
    other_msg = _Msg(text="Boshqa xabarga javob", message_id=57, chat_id=ADMIN_A)
    other_msg.reply_to_message = SimpleNamespace(message_id=999999)
    with _DBPatch(_FakeDB()):
        _run(sup.support_admin_reply(
            _msg_update(other_msg, user_id=ADMIN_A, username="admin"),
            _ctx(bot=other_bot),
        ))
    check("noma'lum reply foydalanuvchiga yuborilmadi",
          not [o for o in other_bot.out if o["chat_id"] != ADMIN_A],
          str(other_bot.out))

    # 5) Faqat matn: media (rasm) bilan javob — adminga ogohlantirish.
    sup.reset_support_runtime_state()
    fake2 = _FakeDB()
    with _DBPatch(fake2):
        _run(sup.support_message_received(
            _msg_update(_Msg(text="Media javob testi")), _ctx(bot=_Bot())))
    chat2, mid2 = sorted(fake2.deliveries)[0]
    media_bot = _Bot()
    media_msg = _Msg(text=None, caption=None, message_id=58, chat_id=chat2)
    media_msg.reply_to_message = SimpleNamespace(message_id=mid2)
    with _DBPatch(fake2):
        _run(sup.support_admin_reply(
            _msg_update(media_msg, user_id=chat2, username="admin"),
            _ctx(bot=media_bot),
        ))
    check("matnsiz (media) javob foydalanuvchiga yuborilmadi",
          not [o for o in media_bot.out], str(media_bot.out))
    check("adminga «matn yozing» ko'rsatmasi berildi",
          media_msg.sent and "MATN" in media_msg.sent[0]["text"].upper(),
          str(media_msg.sent))

    # 6) Foydalanuvchi botni bloklagan bo'lsa — adminga ROSTGO'Y xato.
    sup.reset_support_runtime_state()
    fake3 = _FakeDB()
    with _DBPatch(fake3):
        _run(sup.support_message_received(
            _msg_update(_Msg(text="Blok testi")), _ctx(bot=_Bot())))
    chat3, mid3 = sorted(fake3.deliveries)[0]
    blocked_bot = _Bot(fail_for={USER_ID})
    blocked_msg = _Msg(text="Javob (bloklangan)", message_id=59, chat_id=chat3)
    blocked_msg.reply_to_message = SimpleNamespace(message_id=mid3)
    with _DBPatch(fake3):
        _run(sup.support_admin_reply(
            _msg_update(blocked_msg, user_id=chat3, username="admin"),
            _ctx(bot=blocked_bot),
        ))
    replies = [s["text"] for s in blocked_msg.sent]
    check("yetkazilmaganda adminga xato xabari (soxta tasdiq YO'Q)",
          replies and replies[0] != SPEC_DELIVERED and "yetkazilmadi" in replies[0],
          str(replies))


# ===========================================================================
# TEST 4 — XAVFSIZLIK: NOT-AN-ADMIN TA'SIR QILA OLMAYDI
# ===========================================================================
def test_non_admin_cannot_trigger():
    header("4", "🛡 Not-an-admin reply handleriga ta'sir qila olmaydi")

    app = _build_app()
    admin_reply = _msg_update_real("javob", user_id=ADMIN_A, reply_to_message_id=777)
    plain_user_reply = _msg_update_real("javob", user_id=USER_ID,
                                        reply_to_message_id=777)
    user_no_reply = _msg_update_real("javob", user_id=USER_ID)
    group_reply = _msg_update_real("javob", user_id=ADMIN_A,
                                   reply_to_message_id=777, chat_type="group")

    check("filtr: admin reply → MOS",
          bool(sup.SUPPORT_ADMIN_REPLY_FILTER.check_update(admin_reply)))
    check("filtr: oddiy foydalanuvchi reply → MOS EMAS",
          not sup.SUPPORT_ADMIN_REPLY_FILTER.check_update(plain_user_reply))
    check("filtr: reply bo'lmagan xabar → MOS EMAS",
          not sup.SUPPORT_ADMIN_REPLY_FILTER.check_update(user_no_reply))
    check("filtr: guruh reply'si → MOS EMAS (faqat shaxsiy chat)",
          not sup.SUPPORT_ADMIN_REPLY_FILTER.check_update(group_reply))

    routed_user = _routed_names(app, plain_user_reply)
    check("router: oddiy foydalanuvchi reply'si support handleriga tushmaydi",
          "support_admin_reply" not in routed_user, str(routed_user))
    routed_admin = _routed_names(app, admin_reply)
    check("router: admin reply'si support_admin_reply handleriga tushadi",
          "support_admin_reply" in routed_admin, str(routed_admin))

    # Handler ichidagi ikkinchi qatlam himoya (filter chetlab o'tilsa ham).
    sup.reset_support_runtime_state()
    fake = _FakeDB()
    with _DBPatch(fake):
        _run(sup.support_message_received(
            _msg_update(_Msg(text="Himoya testi")), _ctx(bot=_Bot())))
    chat, mid = sorted(fake.deliveries)[0]

    attacker_bot = _Bot()
    attacker_msg = _Msg(text="Men adminga javob berdim", message_id=70, chat_id=USER_ID)
    attacker_msg.reply_to_message = SimpleNamespace(message_id=mid)
    with _DBPatch(fake):
        _run(sup.support_admin_reply(
            _msg_update(attacker_msg, user_id=USER_ID, username="attacker"),
            _ctx(bot=attacker_bot),
        ))
    check("not-an-admin: foydalanuvchiga hech narsa yuborilmadi",
          not attacker_bot.out, str(attacker_bot.out))
    check("not-an-admin: hech qanday tasdiq/xabar qaytmadi",
          not attacker_msg.sent, str(attacker_msg.sent))
    check("not-an-admin: murojaat 'answered' bo'lib belgilanmadi",
          not fake.answered, str(fake.answered))

    # Guruh/kanal reply'i handler ichida ham rad etiladi.
    sup.reset_support_runtime_state()
    with _DBPatch(_FakeDB()):
        _run(sup.support_message_received(
            _msg_update(_Msg(text="Guruh testi")), _ctx(bot=_Bot())))
    chat2, mid2 = sorted(fake.deliveries)[0]
    grp_bot = _Bot()
    grp_msg = _Msg(text="guruhdagi javob", message_id=71, chat_id=ADMIN_A)
    grp_msg.chat = SimpleNamespace(id=ADMIN_A, type="group")
    grp_msg.reply_to_message = SimpleNamespace(message_id=mid2)
    with _DBPatch(fake):
        _run(sup.support_admin_reply(
            _msg_update(grp_msg, user_id=ADMIN_A, username="admin"),
            _ctx(bot=grp_bot),
        ))
    check("guruh reply'i foydalanuvchiga yetkazilmaydi",
          not [o for o in grp_bot.out if o["chat_id"] == USER_ID], str(grp_bot.out))


# ===========================================================================
# TEST 5 — REGRESSIYA: i18n, FSM, sxema, mavjud oqimlar
# ===========================================================================
def test_regression_and_parity():
    header("5", "🧱 Regressiya: i18n paritet, FSM unikalligi, sxema, hub")

    from translations import support_parity_report, support_t

    report = support_parity_report()
    check("i18n UZ↔RU↔EN 100% paritet (in_sync)",
          report["in_sync"] is True, str(report))
    check("UZ yo'riqnoma matni spec bilan AYNAN mos",
          support_t("sp_prompt", "uz") == SPEC_PROMPT,
          repr(support_t("sp_prompt", "uz")))
    check("UZ tasdiq matni spec bilan AYNAN mos",
          support_t("sp_confirm", "uz") == SPEC_CONFIRM,
          repr(support_t("sp_confirm", "uz")))
    check("UZ admin tasdig'i spec bilan AYNAN mos",
          support_t("sp_admin_delivered", "uz") == SPEC_DELIVERED,
          repr(support_t("sp_admin_delivered", "uz")))
    check("UZ javob sarlavhasi spec bilan AYNAN mos",
          support_t("sp_reply_header", "uz") == SPEC_REPLY_HEADER,
          repr(support_t("sp_reply_header", "uz")))
    for lang in LANGS:
        check(f"[{lang}] «{support_t('sp_btn_back', lang)}» tugmasi bor",
              "◀️" in support_t("sp_btn_back", lang))

    # Callback'lar 64 bayt chegarasida.
    from keyboards.callback_data import CALLBACK_DATA_MAX_BYTES, is_callback_safe

    for value in (sup.CB_SUPPORT_BACK, "help_support"):
        check(f"callback xavfsiz: {value}",
              is_callback_safe(value)
              and len(value.encode("utf-8")) <= CALLBACK_DATA_MAX_BYTES)

    # FSM holati 540 unikal va boshqa oqimlar bilan to'qnashmaydi.
    check("FSM: SUPPORT_TICKET_INPUT = 540",
          sup.SUPPORT_TICKET_INPUT == 540, str(sup.SUPPORT_TICKET_INPUT))
    occupied = set()
    for module_name in ("handlers.sources", "handlers.image_post", "handlers.manual_post",
                        "handlers.voice_post", "handlers.magic_post",
                        "handlers.post_score", "handlers.autopilot",
                        "handlers.templates", "handlers.ai_post"):
        try:
            module = __import__(module_name, fromlist=["*"])
        except Exception:
            continue
        for value in vars(module).values():
            if isinstance(value, int) and 100 <= value <= 900:
                occupied.add(value)
    check("FSM: 540 hech bir mavjud holat bilan to'qnashmaydi",
          sup.SUPPORT_TICKET_INPUT not in occupied, str(sorted(occupied))[:120])

    # Ro'yxatga olish tartibi: Reply handler catch-all'dan OLDIN turadi.
    app = _build_app()
    order = []
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            callback = getattr(handler, "callback", None)
            order.append((getattr(callback, "__name__", type(handler).__name__),
                          type(handler).__name__))
    names = [name for name, _ in order]
    check("admin Reply handler ro'yxatda (MessageHandler)",
          any(name == "support_admin_reply" and kind == "MessageHandler"
              for name, kind in order), str(order[-6:]))
    check("admin Reply handler catch-all'dan OLDIN",
          names.index("support_admin_reply") < len(names) - 1
          and "unknown_message_fallback" in names
          and names.index("support_admin_reply") < names.index("unknown_message_fallback"),
          str(names[-4:]))
    check("sup_back global handler ro'yxatda (eskirgan tugma o'lik emas)",
          "support_back_callback" in names, str(names[-8:]))

    # Sxema ↔ database.py paralleligi.
    schema = (BOT_DIR / "schema.sql").read_text(encoding="utf-8")
    check("schema.sql: support_tickets jadvali",
          "CREATE TABLE IF NOT EXISTS support_tickets (" in schema)
    check("schema.sql: support_ticket_deliveries jadvali",
          "CREATE TABLE IF NOT EXISTS support_ticket_deliveries (" in schema)
    check("schema.sql: admin xabar ID'si UNIQUE (reply kuzatuvi)",
          "UNIQUE (admin_chat_id, admin_message_id)" in schema)
    check("database.EXPECTED_TABLES: support jadvallari",
          "support_tickets" in db_mod.EXPECTED_TABLES
          and "support_ticket_deliveries" in db_mod.EXPECTED_TABLES)
    check("database.py: ichki fallback DDL ham jadvallarni yaratadi",
          "CREATE TABLE IF NOT EXISTS support_tickets" in
          (BOT_DIR / "database.py").read_text(encoding="utf-8"))
    for fn_name in ("create_support_ticket", "attach_support_ticket_delivery",
                    "get_support_ticket_by_admin_message",
                    "mark_support_ticket_answered", "count_user_support_tickets"):
        check(f"database.{fn_name}() mavjud",
              callable(getattr(db_mod, fn_name, None)))

    # ⚙️ Sozlamalar hub'i o'zgarmagan (7 tugma, help_support o'z joyida).
    from keyboards.inline import (get_cabinet_inline_keyboard,
                                  get_settings_hub_keyboard,
                                  get_support_ticket_keyboard)

    hub_cbs = _flat_cbs(get_settings_hub_keyboard("uz"))
    check("hub: 7 tugma saqlangan",
          hub_cbs == ["stgs_lang", "stgs_post", "stgs_notif", "stgs_referral",
                      "stgs_pay", "help_support", "stgs_back"], str(hub_cbs))
    profile_buttons = [b for row in get_cabinet_inline_keyboard("uz").inline_keyboard
                       for b in row if b.text.endswith("Qo'llab-quvvatlash")]
    check("profil: 💬 tugmasi bot ICHIDAGI oqimni ochadi (URL emas)",
          profile_buttons and profile_buttons[0].callback_data == "help_support"
          and not profile_buttons[0].url, str(profile_buttons))
    for lang in LANGS:
        kb = get_support_ticket_keyboard(lang)
        check(f"[{lang}] murojaat ekranida AYNAN bitta tugma",
              len(kb.inline_keyboard) == 1 and len(kb.inline_keyboard[0]) == 1,
              str(_inline_rows(kb)))

    # Mavjud oqim regressiyasi: qo'llanma/`/help` klaviaturasi va qo'llanma
    # matni o'zgarmagan (support linchi hamon ishlaydi).
    from keyboards.inline import get_help_keyboard

    guide_kb = get_help_keyboard("support_user", "uz")
    check("qo'llanma klaviaturasi: FAQ tugmasi saqlangan",
          "help:faq" in _flat_cbs(guide_kb), str(_flat_cbs(guide_kb)))
    check("qo'llanma klaviaturasi: tashqi aloqa havolasi saqlangan (legacy)",
          any(b.url == "https://t.me/support_user"
              for row in guide_kb.inline_keyboard for b in row),
          str(_flat_cbs(guide_kb)))


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    test_one_time_ticket_flow()
    test_admin_delivery_format()
    test_admin_reply_dispatch()
    test_non_admin_cannot_trigger()
    test_regression_and_parity()

    print(f"\nJAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        sys.exit(1)
    print("Barcha qo'llab-quvvatlash (4-QISM) testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
