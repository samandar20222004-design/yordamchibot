#!/usr/bin/env python3
"""Regression tests for media-safe editing, referral rewards and bilingual copy."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handlers.new_post import _apply_single_media
from locales.translations import get_text
from scheduler import build_reaction_buttons


def test_media_context_is_stable():
    ctx = SimpleNamespace(user_data={"content": "old"})
    _apply_single_media(ctx, {"type": "video", "file_id": "vid-123", "caption": "caption"})
    # A caption edit updates only content (the handler intentionally has no
    # assignment that converts the post to text or clears file_id).
    ctx.user_data["content"] = "edited"
    assert ctx.user_data["post_type"] == "video"
    assert ctx.user_data["file_id"] == "vid-123"


def test_reactions_are_inline_buttons():
    row = build_reaction_buttons(42, True, ["👍", "❤️", "🔥"])
    assert [b.text for b in row] == ["👍", "❤️", "🔥"]
    assert all(b.callback_data.startswith("react:42:") for b in row)


def test_i18n_requirement_copy():
    for lang in ("uz", "ru"):
        assert "+3" in get_text("referral_menu", lang, credits=1, count=2, link="x")
        assert "+1" in get_text("referral_menu", lang, credits=1, count=2, link="x")
        assert "🎁" in get_text("daily_bonus_guide", lang)


def test_no_referral_pro_hook_or_manual_license_ui():
    assert "check_and_grant_referral_pro" not in (ROOT / "handlers/channels.py").read_text()
    keyboard = (ROOT / "keyboards/default.py").read_text()
    assert "[BTN_DAILY_BONUS, BTN_BUY_AD_FREE]" not in keyboard
    assert "BTN_BUY_AD_FREE" not in keyboard
    start_src = (ROOT / "handlers/start.py").read_text()
    for token in ("adfree_toggle", "adfree_confirm", "adfree_refund", "buy_ad_free_handler", "ad_free_callback"):
        assert token not in start_src, token
    import database as db_mod
    for name in ("buy_ad_free_posts", "refund_ad_free_posts", "toggle_ad_free_status",
                 "consume_ad_free_post", "peek_ad_free_post",
                 "check_and_grant_referral_pro", "get_referral_pro_progress"):
        assert not hasattr(db_mod, name), name


def test_referral_reward_tiers():
    import database as db_mod
    assert [db_mod.referral_reward_for(i) for i in range(1, 7)] == [3, 3, 3, 1, 1, 1]
    assert db_mod.total_referral_reward(4) == 10


def test_auto_ad_free_mode():
    """PRO/admin → reklama 0; oddiy → ad_pool oralig'i."""
    import asyncio
    import database as db_mod
    from utils import helpers

    orig_prem, orig_run = db_mod.is_premium, db_mod.run_db
    try:
        db_mod.is_premium = lambda uid: uid == 5001
        assert helpers.is_user_ad_free(5001) is True
        assert helpers.is_user_ad_free(5002) is False
        assert helpers.is_user_ad_free(123456789) is True  # admin

        async def fake_run_db(func, *args, **kwargs):
            name = func.__name__
            if name in ("is_premium", "<lambda>"):
                return args[0] == 5001
            if name == "get_ads_full":
                return [{"id": 1, "text": "POOL-AD", "button_text": "", "button_url": "", "is_active": True}]
            return ""
        db_mod.run_db = fake_run_db

        # PRO: 10 ta ketma-ket chaqiruvda ham reklama YO'Q
        for _ in range(10):
            assert asyncio.run(helpers.get_smart_reply_ad_async(5001)) == ""
        assert asyncio.run(helpers.is_user_ad_free_async(5001)) is True
        # Oddiy: har 3-xabarda reklama chiqadi
        helpers._USER_MSG_COUNT.pop(5002, None)
        outs = [asyncio.run(helpers.get_smart_reply_ad_async(5002)) for _ in range(3)]
        assert outs[0] == "" and outs[1] == "" and "POOL-AD" in outs[2]
    finally:
        db_mod.is_premium, db_mod.run_db = orig_prem, orig_run
        helpers._AD_ROTATION_INDEX.clear()


def test_card_payment_button_and_text():
    from handlers.subscription import (
        _get_subscription_keyboard, _build_card_payment_text, _get_card_payment_keyboard,
    )
    for lang in ("uz", "ru"):
        kb = _get_subscription_keyboard("free", lang)
        flat = [b for row in kb.inline_keyboard for b in row]
        card = [b for b in flat if b.callback_data == "sub_card_pay"]
        assert len(card) == 1 and "Uzcard" in card[0].text and "Humo" in card[0].text
        assert "sub_pay:stars_1m" in [b.callback_data for b in flat]  # Stars saqlanadi
        text = _build_card_payment_text(42, lang)
        assert "Uzcard" in text and "42" in text and "19 000" in text
        back = [b.callback_data for row in _get_card_payment_keyboard(lang).inline_keyboard for b in row]
        assert "sub_back" in back
    pro_kb = _get_subscription_keyboard("pro", "uz")
    assert "sub_card_pay" not in [b.callback_data for row in pro_kb.inline_keyboard for b in row]


def test_i18n_new_keys():
    for lang in ("uz", "ru"):
        for key in ("no_credits", "balance_card", "ad_mode_pro", "ad_mode_free",
                    "btn_card_payment", "card_payment_title", "card_payment_steps"):
            assert get_text(key, lang) != key, (key, lang)
        guide = get_text("daily_bonus_guide", lang)
        assert "🎁" in guide and "🎁" in get_text("no_credits", lang, guide=guide, link="x")
    assert "Kabinet & Sozlamalar" in get_text("daily_bonus_guide", "uz")
    assert "Kunlik bonus" in get_text("daily_bonus_guide", "uz")


def test_ru_cabinet_after_switch_no_crash():
    """Regression: RU foydalanuvchi '👤 Кабинет & Настройки' bossa — kabinet RU.

    Bot qayta ishga tushgach ``context.user_data`` bo'sh bo'ladi; til DB'dan
    yuklanadi ('ru') va kabinet rus tilida chiqadi. Kabinet ichidagi har bir
    tugma (shu jumladan '📅 Ожидающие посты' → ``cab_pending``) xatosiz
    ishlaydi — oldin ``UnboundLocalError: lang`` bilan '⚠️ Произошла
    непредвиденная ошибка' chiqardi.
    """
    import asyncio
    import importlib
    import database as db_mod

    st_mod = importlib.import_module("handlers.start")

    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        calls.append((name, args, kwargs))
        if name == "get_user_language":
            return "ru"  # Neon DB: foydalanuvchi rus tilini tanlagan
        if name == "get_referral_stats":
            return {"referrals_count": 1, "ai_credits": 7, "streak": 2}
        if name == "get_user_channels":
            return []
        if name == "get_user_code":
            return "RUTEST"
        if name == "get_queue_post_count":
            return 0
        if name == "get_user_plan":
            return {"plan_type": "free", "expires_at": None, "ai_used": 0}
        return None

    class _Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text=None, reply_markup=None, **kw):
            self.sent.append(("send_message", text, reply_markup))
            return None

    class _Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))
            return None

    class _User:
        id = 777001
        username = "ru_user"
        first_name = "Ruslan"

    class _Query:
        def __init__(self, data):
            self.data = data
            self.answers = []
            self.message = _Msg()
            self.from_user = _User()

        async def answer(self, *a, **kw):
            self.answers.append((a, kw))

        async def edit_message_text(self, *a, **kw):
            pass

    class _Ctx:
        def __init__(self, bot):
            self.bot = bot
            self.user_data = {}  # bot restart — kesh bo'sh!

    class _Upd:
        def __init__(self, msg, user):
            self.message = msg
            self.effective_user = user

    class _UpdQ:
        def __init__(self, query):
            self.callback_query = query

    async def run():
        async def _no_ad():
            return ""

        orig_ad = st_mod.get_smart_reply_ad_async
        orig_run_db = db_mod.run_db
        db_mod.run_db = fake_run_db
        st_mod.get_smart_reply_ad_async = lambda uid: _no_ad()
        try:
            # 1) Reply-tugma '👤 Кабинет & Настройки' → user_cabinet_menu
            bot = _Bot()
            ctx = _Ctx(bot)
            msg = _Msg()
            await st_mod.user_cabinet_menu(_Upd(msg, _User()), ctx)
            assert msg.replies, "kabinet javob bermadi"
            text, markup = msg.replies[0]
            assert "Личный кабинет" in text, text[:120]
            assert ctx.user_data.get("lang") == "ru", ctx.user_data  # DB'dan hydrate
            labels = [b.text for row in markup.inline_keyboard for b in row]
            assert get_text("cab_my_channels", "ru") in labels, labels

            # 2) Kabinet ichidagi tugma 'cab_pending' — oldin UnboundLocalError
            q = _Query("cab_pending")
            await st_mod.cabinet_callback(_UpdQ(q), ctx)
            got = q.message.replies
            assert got, "cab_pending javob bermadi"
            assert "нет ожидающих" in got[-1][0], got[-1][0][:120]
            return True
        finally:
            db_mod.run_db = orig_run_db
            st_mod.get_smart_reply_ad_async = orig_ad

    assert asyncio.run(run())


def test_ru_cabinet_keys_format_without_missing_key():
    """RU kabinet matnlari: barcha kalitlar mavjud va format xatolari yo'q."""
    from locales.translations import TRANSLATIONS, get_text
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]
    # Kabinet + karta to'lov + chek kalitlari ikkala tilda to'liq bo'lishi kerak.
    keys = [
        "btn_settings", "btn_main_menu", "btn_cancel", "msg_closed",
        "cab_my_channels", "cab_analytics", "cab_pending", "cab_queue",
        "cab_balance", "cab_btn_daily_bonus", "cab_referral", "cab_close",
        "cabinet_title", "cabinet_streak", "cabinet_credits_admin",
        "credits_value", "lang_prompt", "lang_changed",
        "card_tariff_title", "card_plan_1m", "card_plan_3m", "card_plan_1y",
        "card_tariff_1m", "card_tariff_3m", "card_tariff_1y",
        "card_payment_selected", "card_payment_card", "card_payment_steps",
        "btn_send_receipt", "receipt_prompt", "receipt_saved",
        "receipt_admin_title", "receipt_admin_user_line",
        "receipt_admin_user_nick_line", "receipt_admin_user_id_line",
        "receipt_admin_tarif_line", "receipt_admin_time_line",
        "receipt_btn_approve", "receipt_btn_reject",
    ]
    # lang_prompt atayin ikki tilda bitta matn (tilni tanlash ekrani);
    # 'ID:' qatori ham talab bo'yicha ikkala tilda bir xil yoziladi.
    lang_neutral = {"lang_prompt", "receipt_admin_user_id_line"}
    for key in keys:
        assert key in uz and key in ru, key
        if key not in lang_neutral:
            assert uz[key] != ru[key], (key, uz[key], ru[key])
    # Formatlash hech qachon MissingKey/TypeError bermaydi va qavs qoldirmaydi
    samples = {
        "cabinet_streak": {"streak": 3},
        "credits_value": {"n": 12},
        "card_tariff_1m": {"price": "19 000"},
        "card_tariff_3m": {"price": "45 000"},
        "card_tariff_1y": {"price": "140 000"},
        "card_payment_selected": {"tarif": "1 oy", "summa": "19 000"},
        "card_payment_card": {"card": "8600 0609 5082 5589", "holder": "Sayitqulov S."},
        "card_payment_steps": {"user_id": 42, "admin": "@admin"},
        "receipt_prompt": {"user_id": 42, "tarif": "1 oy", "summa": "19 000"},
        "receipt_admin_user_line": {"name": "Ali", "username": "ali"},
        "receipt_admin_user_nick_line": {"name": "Ali"},
        "receipt_admin_user_id_line": {"user_id": 42},
        "receipt_admin_tarif_line": {"tarif": "3 oy", "summa": "45 000"},
        "receipt_admin_time_line": {"sana": "01.01.2026 12:00"},
    }
    for lang in ("uz", "ru"):
        for key, kw in samples.items():
            out = get_text(key, lang, **kw)
            assert "{" not in out and "}" not in out, (lang, key, out)
    # Kabinet RU sarlavhasi rus tilida
    assert "Личный кабинет" in get_text("cabinet_title", "ru")


def test_card_payment_tariff_and_receipt_flow():
    """💳 Karta orqali to'lov: tarif tanlash → karta rekvizitlari → chek yuborish
    → admin tasdiqlash (PRO tanlangan muddatga) / rad etish."""
    import asyncio
    import importlib
    import os as _os
    import config as cfg
    import database as db_mod

    # Fixed karta rekvizitlari (env bo'sh bo'lsa ham default ishlaydi)
    expected_number = _os.getenv("PAYMENT_CARD_NUMBER", "8600060950825589")
    expected_holder = _os.getenv("PAYMENT_CARD_HOLDER", "Sayitqulov S.")
    assert cfg.PAYMENT_CARD_NUMBER == expected_number
    assert cfg.PAYMENT_CARD_HOLDER == expected_holder

    sub = importlib.import_module("handlers.subscription")
    pr = importlib.import_module("handlers.payment_receipt")

    # --- 1) Karta raqami/summa formatlash ---
    assert sub._fmt_card_number(cfg.PAYMENT_CARD_NUMBER) == "8600 0609 5082 5589"
    assert sub._fmt_uzs(sub.CARD_TARIFFS["1m"]["amount"]) == "19 000"
    assert sub._fmt_uzs(sub.CARD_TARIFFS["3m"]["amount"]) == "45 000"
    assert sub._fmt_uzs(sub.CARD_TARIFFS["1y"]["amount"]) == "140 000"
    assert [sub._plan_key_for_days(d) for d in (30, 90, 365)] == ["1m", "3m", "1y"]

    # --- 2) Tarif tanlash klaviaturasi: 1m/3m/1y + orqaga (uz va ru) ---
    for lang in ("uz", "ru"):
        kb = sub._get_card_tariffs_keyboard(lang)
        flat = [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]
        assert [cb for _, cb in flat] == ["sub_tarif:1m", "sub_tarif:3m", "sub_tarif:1y", "sub_back"], flat
        assert flat[0][0] == get_text("card_tariff_1m", lang, price="19 000"), flat[0]
        assert flat[1][0] == get_text("card_tariff_3m", lang, price="45 000"), flat[1]
        assert flat[2][0] == get_text("card_tariff_1y", lang, price="140 000"), flat[2]

    # --- 3) Tanlangan tarif bo'yicha karta ekrani (summa, karta, egasi, ID) ---
    for lang, plan_word in (("uz", "3 oy"), ("ru", "3 месяца")):
        text = sub._build_card_payment_text(42, lang, "3m")
        assert plan_word in text and "45 000" in text, text[:200]
        assert "8600 0609 5082 5589" in text and "Sayitqulov S." in text, text[:200]
        assert "42" in text  # foydalanuvchi ID yo'riqnomada ko'rsatiladi

    # --- 4) Chek qabul qilish: user_data'dagi tarif → 90 kun DB'ga, admin caption ---
    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        calls.append((name, args, kwargs))
        if name == "get_user_language":
            return "ru"
        if name == "save_payment_receipt":
            return 55
        if name == "approve_payment_receipt":
            return {"ok": True, "user_id": 777001, "days": 90, "language_code": "ru"}
        if name == "reject_payment_receipt":
            return {"ok": True, "user_id": 777001}
        if name == "get_user_plan":
            return {"plan_type": "free", "expires_at": None, "ai_used": 0}
        return None

    class _Bot:
        def __init__(self):
            self.messages = []
            self.photos = []
            self.documents = []
            self.answers = []

        async def send_message(self, chat_id, text=None, **kw):
            self.messages.append((chat_id, text, kw))
            return None

        async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
            self.photos.append((chat_id, caption, reply_markup))
            return None

        async def send_document(self, chat_id, document, caption=None, reply_markup=None, **kw):
            self.documents.append((chat_id, caption, reply_markup))
            return None

        async def answer_callback_query(self, *a, **kw):
            self.answers.append((a, kw))
            return None

        async def edit_message_reply_markup(self, *a, **kw):
            return None

    class _Photo:
        file_id = "PHOTO_RECEIPT_1"

    class _Msg:
        def __init__(self):
            self.replies = []
            self.photo = [_Photo()]
            self.caption = ""

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))
            return None

    class _User:
        id = 777001
        username = "purchaser"
        full_name = "Aziz Karimov"
        first_name = "Aziz"

    class _Ctx:
        def __init__(self, bot):
            self.bot = bot
            self.user_data = {"lang": "ru", "card_plan": "3m"}

    class _AdminUser(_User):
        id = 123456789
        username = "the_admin"

    class _AdminQuery:
        def __init__(self, data):
            self.data = data
            self.from_user = _AdminUser()
            self.answers = []
            self.message = _Msg()

        async def answer(self, *a, **kw):
            self.answers.append((a, kw))
            return None

        async def edit_message_reply_markup(self, *a, **kw):
            return None

    class _UpdMsg:
        def __init__(self, msg, user):
            self.message = msg
            self.effective_user = user

    class _UpdQ:
        def __init__(self, query):
            self.callback_query = query

    orig_run_db = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        async def run():
            # Foydalanuvchi chek yuboradi (photo)
            bot = _Bot()
            ctx = _Ctx(bot)
            msg = _Msg()
            await pr.receipt_received(_UpdMsg(msg, _User()), ctx)
            # DB'ga tarif bo'yicha 90 kun yozildi
            save_calls = [c for c in calls if c[0] == "save_payment_receipt"]
            assert save_calls and save_calls[0][1][-1] == 90, save_calls
            # Foydalanuvchi: 'Chekingiz qabul qilindi va adminga yuborildi...' (RU)
            assert msg.replies, "user javob olmadi"
            assert "получен и отправлен администратору" in msg.replies[-1][0], msg.replies[-1][0]
            assert "card_plan" not in ctx.user_data  # foydalanilgan tanlov tozalandi
            # Admin: rasm + caption (ism, @username, ID, tarif, summa, vaqt) + tugmalar
            assert bot.photos, "adminga rasm yuborilmadi"
            cap = bot.photos[0][1]
            assert "Aziz (@purchaser)" in cap, cap
            assert "ID: 777001" in cap, cap
            assert "3 месяца (45 000 сум)" in cap, cap
            assert "Время: " in cap, cap
            kb = bot.photos[0][2]
            flat = [b for row in kb.inline_keyboard for b in row]
            assert [b.callback_data for b in flat] == ["rc_ok:55", "rc_no:55"], flat

            # Admin ✅ Tasdiqlash → user'ga tabrik (90 kunlik PRO)
            bot2 = _Bot()
            q = _AdminQuery("rc_ok:55")
            await pr.receipt_admin_callback(_UpdQ(q), _Ctx(bot2))
            user_msgs = [m for m in bot2.messages if m[0] == 777001]
            assert user_msgs, "tasdiqlash xabari yo'q"
            assert "PRO на 90 дней" in user_msgs[-1][1], user_msgs[-1][1]

            # Admin ❌ Rad etish → user'ga bildirishnoma
            bot3 = _Bot()
            q3 = _AdminQuery("rc_no:55")
            await pr.receipt_admin_callback(_UpdQ(q3), _Ctx(bot3))
            rej = [m for m in bot3.messages if m[0] == 777001]
            assert rej and "не был подтверждён" in rej[-1][1], rej
            return True
        assert asyncio.run(run())
    finally:
        db_mod.run_db = orig_run_db


def test_receipt_admin_handler_registered_before_stale_fallback():
    """Chek ✅/❌ tugmalari 'expired session' catch-all'ga yutilib ketmasligi
    uchun global reyestrda OLDINDAN ro'yxatdan o'tgan bo'lishi shart."""
    src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    i_receipt = src.find("receipt_admin_callback,")
    i_stale = src.find("CallbackQueryHandler(expired_session_callback)")
    assert i_receipt != -1 and i_stale != -1
    assert i_receipt < i_stale, (
        "receipt_admin_callback expired_session_callback'dan keyin ro'yxatdan o'tgan — "
        "admin ✅/❌ tugmalari ishlamaydi")


def test_update_lock_manager_concurrency_and_cleanup():
    """UpdateLockManager: ayni bir user/chat so'rovlari navbat bilan (seriyali),
    turli userlar esa parallel ishlaydi; foydalanilmagan lock'lar tozalanadi."""
    import asyncio
    from main import UpdateLockManager

    mgr = UpdateLockManager()
    events = []

    async def worker(key, delay, val):
        async with mgr.lock(key):
            events.append(f"start:{val}")
            await asyncio.sleep(delay)
            events.append(f"end:{val}")

    async def run():
        # 1) Ayni bir user (user:1) — ketma-ketlik kafolati
        await asyncio.gather(
            worker("user:1", 0.04, 1),
            worker("user:1", 0.01, 2),
        )
        assert events == ["start:1", "end:1", "start:2", "end:2"], events
        assert len(mgr._locks) == 0 and len(mgr._counts) == 0

        # 2) Turli userlar (user:1 va user:2) — parallel bajarilish
        events.clear()
        t0 = asyncio.get_event_loop().time()
        await asyncio.gather(
            worker("user:1", 0.04, "u1"),
            worker("user:2", 0.04, "u2"),
        )
        elapsed = asyncio.get_event_loop().time() - t0
        assert events[:2] == ["start:u1", "start:u2"] or events[:2] == ["start:u2", "start:u1"]
        assert elapsed < 0.07, f"Parallel bajarilmadi: {elapsed}s"
        assert len(mgr._locks) == 0 and len(mgr._counts) == 0

    asyncio.run(run())


def test_guarded_application_per_user_locking():
    """GuardedApplication: har bir update uchun lock key to'g'ri aniqlanadi."""
    from main import GuardedApplication, get_update_lock_key
    from types import SimpleNamespace

    user_u1 = SimpleNamespace(effective_user=SimpleNamespace(id=1001), callback_query=None, effective_message=None)
    user_u2 = SimpleNamespace(effective_user=SimpleNamespace(id=1002), callback_query=None, effective_message=None)
    chat_upd = SimpleNamespace(effective_user=None, effective_chat=SimpleNamespace(id=2001), callback_query=None, effective_message=None)

    assert get_update_lock_key(user_u1) == "user:1001"
    assert get_update_lock_key(user_u2) == "user:1002"
    assert get_update_lock_key(chat_upd) == "chat:2001"
    assert get_update_lock_key(None) is None


def test_scheduler_mark_processing_before_send():
    """Post kanalga yuborilishidan oldin statusi qat'iy 'processing' qilinadi."""
    import asyncio
    import scheduler as sch_mod

    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        calls.append((name, args))
        if name == "mark_post_processing":
            return None
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name == "mark_post_as_sent":
            return None
        return None

    class _MockBot:
        async def send_message(self, chat_id, text, **kwargs):
            calls.append(("send_message", (chat_id, text)))
            return SimpleNamespace(message_id=999)

    orig_run_db = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        post = (
            501, 123456789, "-100123", "text", "Test content", None,
            None, None, False, None,
            "none", None, None, None,
            0, None
        )
        asyncio.run(sch_mod._execute_send(_MockBot(), post))
        call_names = [c[0] for c in calls]
        assert "mark_post_processing" in call_names
        assert "send_message" in call_names
        assert call_names.index("mark_post_processing") < call_names.index("send_message")
        assert ("mark_post_processing", (501,)) in calls
    finally:
        sch_mod.db.run_db = orig_run_db


def test_scheduler_idempotency_on_db_error_after_send():
    """Post Telegramga yuborilgach, agar DB da xatolik bo'lsa ham post qayta navbatga qo'yilmaydi (idempotent)."""
    import asyncio
    import scheduler as sch_mod

    calls = []
    requeued = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        calls.append((name, args))
        if name == "mark_post_processing":
            return None
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name == "mark_post_as_sent":
            raise RuntimeError("DB connection dropped after send")
        if name == "mark_post_status":
            return None
        if name == "retry_post":
            requeued.append(args[0])
            return None
        return None

    class _MockBot:
        async def send_message(self, chat_id, text, **kwargs):
            return SimpleNamespace(message_id=888)

    orig_run_db = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        post = (
            502, 123456789, "-100123", "text", "Test content", None,
            None, None, False, None,
            "none", None, None, None,
            0, None
        )
        asyncio.run(sch_mod._execute_send(_MockBot(), post))
        assert 502 not in requeued, "Post Telegramga ketganidan keyin qayta navbatga qo'yilmasligi shart!"
        status_calls = [c for c in calls if c[0] == "mark_post_status"]
        assert any(c[1] == (502, "posted") for c in status_calls), status_calls
    finally:
        sch_mod.db.run_db = orig_run_db


def test_recover_stale_processing_posts_idempotent():
    """Stale processing postlarni tiklash: yuborilganlar 'posted', yuborilmaganlar 'pending' bo'ladi."""
    src = (ROOT / "database.py").read_text(encoding="utf-8")
    assert "def recover_stale_processing_posts" in src
    assert "def mark_post_processing" in src
    assert "SET status = 'posted'" in src
    assert "SET status = 'pending', processing_started_at = NULL" in src


def test_env_card_config_and_fallback():
    """Karta ma'lumotlari config.py va .env orqali boshqariladi (fallback bilan)."""
    import config as cfg
    assert cfg.PAYMENT_CARD_NUMBER != ""
    assert cfg.PAYMENT_CARD_HOLDER != ""
    assert cfg._str_env("NON_EXISTING_ENV_VAR_12345", "8600060950825589") == "8600060950825589"
    assert cfg._str_env("NON_EXISTING_ENV_VAR_12345", "Sayitqulov S.") == "Sayitqulov S."


def test_main_menu_hint_translations():
    """translations.py dagi main_menu_hint kaliti UZ va RU lug'atlarida to'liq bo'lishi kerak."""
    from locales.translations import get_text
    assert get_text("main_menu_hint", "uz") == "Quyidagi menyudan kerakli bo‘limni tanlang 👇"
    assert get_text("main_menu_hint", "ru") == "Выберите нужный раздел из меню ниже 👇"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"New requirements: {len(tests)} tests passed")
