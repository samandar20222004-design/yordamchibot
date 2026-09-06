#!/usr/bin/env python3
"""Regression tests for media-safe editing, referral rewards and bilingual copy."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
# 💳 Karta rekvizitlari FAQAT .env/Render orqali keladi (kodda hardcode yo'q) —
# testlarda ham ular muhit o'zgaruvchisi sifatida beriladi.
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Sayitqulov S.")
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

    # Karta rekvizitlari FAQAT muhit o'zgaruvchilaridan (CARD_NUMBER/CARD_HOLDER)
    expected_number = _os.environ["CARD_NUMBER"]
    expected_holder = _os.environ["CARD_HOLDER"]
    assert cfg.CARD_NUMBER == expected_number
    assert cfg.CARD_HOLDER == expected_holder
    assert cfg.PAYMENT_CARD_NUMBER == expected_number  # eski nom = alias
    assert cfg.PAYMENT_CARD_HOLDER == expected_holder

    sub = importlib.import_module("handlers.subscription")
    pr = importlib.import_module("handlers.payment_receipt")

    # --- 1) Karta raqami/summa formatlash ---
    assert sub._fmt_card_number(cfg.CARD_NUMBER) == "8600 0609 5082 5589"
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
    """Karta ma'lumotlari QAT'IY .env (CARD_NUMBER/CARD_HOLDER) orqali keladi."""
    import config as cfg
    assert cfg.CARD_NUMBER == os.environ["CARD_NUMBER"]
    assert cfg.CARD_HOLDER == os.environ["CARD_HOLDER"]
    assert cfg.PAYMENT_CARD_NUMBER == cfg.CARD_NUMBER
    assert cfg.PAYMENT_CARD_HOLDER == cfg.CARD_HOLDER
    assert cfg._str_env("NON_EXISTING_ENV_VAR_12345", "fallback") == "fallback"


def test_main_menu_hint_translations():
    """translations.py dagi main_menu_hint kaliti UZ va RU lug'atlarida to'liq bo'lishi kerak."""
    from locales.translations import get_text
    assert get_text("main_menu_hint", "uz") == "Quyidagi menyudan kerakli bo‘limni tanlang 👇"
    assert get_text("main_menu_hint", "ru") == "Выберите нужный раздел из меню ниже 👇"


# ======================================================================
# 6 TA YANGI TALAB: fallback, main_menu_hint, concurrency, idempotency,
# karta config, stiker filtri
# ======================================================================
import asyncio as _asyncio
import datetime as _dt
import warnings as _warnings


def _build_app():
    """Haqiqiy PTB Application + register_all_handlers (tarmoqsiz)."""
    from telegram.ext import ApplicationBuilder
    from handlers import register_all_handlers
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    return app


class _RecBot:
    """PTB shortcut'lari (reply_text → send_message) uchun yozib boruvchi bot."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))


def _private_update(uid=777, text=None, voice=False, contact=False, sticker=False,
                    sticker_emoji=None, document=False, command=False, edited=False,
                    chat_type="private", bot=None):
    from telegram import (Update, Message, Chat, User, Voice, Contact, Sticker,
                          Document, MessageEntity)
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid if chat_type == "private" else -100500, type=chat_type)
    kw = dict(message_id=1, date=_dt.datetime.now(), chat=chat, from_user=user)
    if text is not None:
        kw["text"] = text
    if command and text:
        kw["entities"] = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    if voice:
        kw["voice"] = Voice(file_id="v", file_unique_id="vu", duration=3)
    if contact:
        kw["contact"] = Contact(phone_number="+998901234567", first_name="A")
    if sticker:
        kw["sticker"] = Sticker(file_id="s", file_unique_id="su", width=1, height=1,
                                is_animated=False, is_video=False, type="regular",
                                emoji=sticker_emoji)
    if document:
        kw["document"] = Document(file_id="d", file_unique_id="du", file_name="a.pdf")
    msg = Message(**kw)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, edited_message=msg) if edited else Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _first_matching_handler(app, upd):
    """PTB Application.process_update kabi: guruh bo'yicha birinchi mos handler."""
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            check = handler.check_update(upd)
            if check is None or check is False:
                continue
            return group, handler, check
    return None


async def _dispatch(app, upd, lang="uz"):
    """Birinchi mos handlerni haqiqiy CallbackContext bilan ishga tushiradi."""
    from telegram.ext import CallbackContext
    found = _first_matching_handler(app, upd)
    if not found:
        return None
    group, handler, check = found
    ctx = CallbackContext(app, chat_id=upd.effective_chat.id, user_id=upd.effective_user.id)
    ctx.user_data["lang"] = lang
    await handler.handle_update(upd, app, check, ctx)
    return handler


def _patch_db(responses=None):
    import database as db_mod
    responses = responses or {}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name in responses:
            val = responses[name]
            return val(*args, **kwargs) if callable(val) else val
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    return lambda: setattr(db_mod, "run_db", orig)


# ---------------------------------------------------------------- 1. FALLBACK
def test_unknown_fallback_texts_exact_uz_ru():
    """Talab 1: fallback matni UZ/RU lug'atlarda aynan ko'rsatilgan shaklda."""
    assert get_text("unknown_message_fallback", "uz") == (
        "Kechirasiz, men bu xabarni tushunmadim. "
        "Iltimos, quyidagi menyudan kerakli bo‘limni tanlang 👇"
    )
    assert get_text("unknown_message_fallback", "ru") == (
        "Извините, я не понял это сообщение. "
        "Пожалуйста, выберите нужный раздел из меню ниже 👇"
    )


def test_unknown_fallback_registered_last_in_register_all_handlers():
    """Talab 1: fallback register_all_handlers ning ENG OXIRIDA (eng past prioritet)."""
    from telegram.ext import MessageHandler
    from handlers import unknown_message_fallback
    src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    body = src.split("def register_all_handlers(app):", 1)[1]
    i_fallback = body.rfind("unknown_message_fallback")
    i_last_add = body.rfind("app.add_handler(")
    assert i_fallback != -1 and i_last_add != -1
    # Fallback ro'yxatga qo'shish — oxirgi add_handler chaqiruvi
    assert i_last_add < i_fallback, "unknown_message_fallback oxirgi add_handler bo'lishi shart"
    # catch-all expired_session_callback dan ham keyin
    assert body.rfind("CallbackQueryHandler(expired_session_callback)") < i_fallback

    app = _build_app()
    groups = sorted(app.handlers)
    last = app.handlers[groups[-1]][-1]
    assert isinstance(last, MessageHandler)
    assert last.callback is unknown_message_fallback


def test_unknown_fallback_filter_scope():
    """Fallback faqat shaxsiy chat, tahrirlanmagan, oddiy xabarlar uchun mos keladi."""
    from telegram.ext import MessageHandler
    from handlers import UNKNOWN_MESSAGE_FILTER, unknown_message_fallback
    h = MessageHandler(UNKNOWN_MESSAGE_FILTER, unknown_message_fallback)
    assert h.check_update(_private_update(text="salom"))
    assert h.check_update(_private_update(voice=True))
    assert h.check_update(_private_update(contact=True))
    assert h.check_update(_private_update(sticker=True))
    assert h.check_update(_private_update(document=True))
    assert not h.check_update(_private_update(text="salom", chat_type="supergroup"))
    assert not h.check_update(_private_update(text="salom", edited=True))


def test_unknown_fallback_does_not_shadow_commands_and_menu_buttons():
    """/start, /help va menyu tugmalari fallback'ga EMAS — o'z handlerlariga tushadi."""
    from telegram.ext import CommandHandler, ConversationHandler
    from handlers import unknown_message_fallback
    from keyboards.default import BTN_NEW_POST, BTN_NEW_POST_RU, BTN_HELP, BTN_BACK, BTN_BACK_RU
    app = _build_app()
    bot = _RecBot()

    g, h, _ = _first_matching_handler(app, _private_update(text="/start", command=True, bot=bot))
    assert isinstance(h, CommandHandler) and h.callback.__name__ == "start"
    g, h, _ = _first_matching_handler(app, _private_update(text="/help", command=True, bot=bot))
    assert isinstance(h, CommandHandler)
    for btn in (BTN_NEW_POST, BTN_NEW_POST_RU, BTN_HELP, BTN_BACK, BTN_BACK_RU):
        g, h, _ = _first_matching_handler(app, _private_update(text=btn, bot=bot))
        assert isinstance(h, ConversationHandler), btn
    # noma'lum buyruq va tasodifiy matn → fallback
    for txt, cmd in (("/nomalum", True), ("tasodifiy matn", False)):
        g, h, _ = _first_matching_handler(app, _private_update(text=txt, command=cmd, bot=bot))
        assert getattr(h, "callback", None) is unknown_message_fallback, txt


def test_unknown_fallback_replies_in_user_language_with_main_menu():
    """Dialogdan tashqarida: matn/voice/kontakt → foydalanuvchi tilida javob + asosiy menyu."""
    import handlers as h_mod
    from telegram import ReplyKeyboardMarkup
    from keyboards.default import BTN_NEW_POST, BTN_NEW_POST_RU
    app = _build_app()
    restore = _patch_db({"get_user_language": "ru", "is_premium": True})
    try:
        async def run():
            results = []
            for lang, kind in (("uz", "text"), ("ru", "voice"), ("uz", "contact"), ("ru", "sticker")):
                h_mod._UNKNOWN_FALLBACK_LAST.clear()
                bot = _RecBot()
                upd = _private_update(
                    text="???" if kind == "text" else None,
                    voice=(kind == "voice"), contact=(kind == "contact"),
                    sticker=(kind == "sticker"), bot=bot,
                )
                handler = await _dispatch(app, upd, lang=lang)
                assert handler is not None and handler.callback is h_mod.unknown_message_fallback
                results.append((lang, bot.sent))
            return results
        for lang, sent in _asyncio.run(run()):
            assert len(sent) == 1, sent
            assert sent[0]["text"] == get_text("unknown_message_fallback", lang)
            kb = sent[0]["reply_markup"]
            assert isinstance(kb, ReplyKeyboardMarkup)
            labels = [b.text for row in kb.keyboard for b in row]
            assert (BTN_NEW_POST_RU if lang == "ru" else BTN_NEW_POST) in labels
    finally:
        restore()


def test_unknown_fallback_uses_db_language_when_cache_empty():
    """Bot restartdan keyin (user_data bo'sh) RU foydalanuvchi ruscha javob oladi."""
    import handlers as h_mod
    from telegram.ext import CallbackContext
    app = _build_app()
    restore = _patch_db({"get_user_language": "ru", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        bot = _RecBot()
        upd = _private_update(text="что-то", bot=bot)
        ctx = CallbackContext(app, chat_id=777, user_id=777)  # lang keshi YO'Q
        _asyncio.run(h_mod.unknown_message_fallback(upd, ctx))
        assert bot.sent and bot.sent[0]["text"] == get_text("unknown_message_fallback", "ru")
        assert ctx.user_data.get("lang") == "ru"
    finally:
        restore()


def test_unknown_fallback_cooldown_prevents_spam():
    """Bir foydalanuvchiga ketma-ket xabarlar uchun bitta javob (cooldown)."""
    import handlers as h_mod
    h_mod._UNKNOWN_FALLBACK_LAST.clear()
    assert h_mod._unknown_fallback_allowed(4242, now=1000.0) is True
    assert h_mod._unknown_fallback_allowed(4242, now=1000.5) is False
    assert h_mod._unknown_fallback_allowed(4242, now=1000.0 + h_mod.UNKNOWN_FALLBACK_COOLDOWN_SEC) is True
    # boshqa foydalanuvchiga ta'sir qilmaydi
    assert h_mod._unknown_fallback_allowed(4343, now=1000.0) is True
    h_mod._UNKNOWN_FALLBACK_LAST.clear()


def test_unknown_fallback_inside_dialog_does_not_break_state():
    """Dialog ICHIDA (masalan, ball o'tkazish — faqat matn) voice kelsa: holat saqlanadi,
    asosiy menyu YUBORILMAYDI, qisqa eslatma chiqadi."""
    import handlers as h_mod
    from telegram.ext import ConversationHandler
    from handlers.start import TRANSFER_TARGET
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = TRANSFER_TARGET
        bot = _RecBot()
        handler = _asyncio.run(_dispatch(app, _private_update(voice=True, bot=bot)))
        assert handler is not None and handler.callback is h_mod.unknown_message_fallback
        assert conv._conversations.get((777, 777)) == TRANSFER_TARGET, "dialog holati buzilmasligi kerak"
        assert bot.sent and bot.sent[0]["text"] == get_text("unknown_in_dialog", "uz")
        assert bot.sent[0]["reply_markup"] is None
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


# ---------------------------------------------------------- 2. main_menu_hint
def test_main_menu_hint_used_in_start_and_back_to_menu_flows():
    """Talab 2: main_menu_hint start / orqaga-menyu oqimlarida ishlatiladi (uz/ru)."""
    st_src = (ROOT / "handlers/start.py").read_text(encoding="utf-8")
    sub_src = (ROOT / "handlers/subscription.py").read_text(encoding="utf-8")
    assert 'get_text("main_menu_hint"' in st_src
    assert 'get_text("main_menu_hint"' in sub_src
    assert "def send_main_menu(" in st_src
    # start.py da qattiq yozilgan o'zbekcha obuna matnlari qolmagan
    assert "Obuna tasdiqlandi!" not in st_src
    assert "Hali barcha kanallarga a'zo bo'lmadingiz" not in st_src
    for lang in ("uz", "ru"):
        hint = get_text("main_menu_hint", lang)
        confirmed = get_text("sub_confirmed", lang, name="Ali", hint=hint)
        assert hint in confirmed and "Ali" in confirmed
        assert "{" not in confirmed


def test_send_main_menu_helper_renders_hint_and_keyboard():
    """send_main_menu: matn berilmasa main_menu_hint + foydalanuvchi tilidagi klaviatura."""
    import importlib
    from telegram import ReplyKeyboardMarkup
    from keyboards.default import BTN_NEW_POST_RU, BTN_NEW_POST
    st_mod = importlib.import_module("handlers.start")

    async def run():
        out = {}
        for lang in ("uz", "ru"):
            bot = _RecBot()
            ctx = SimpleNamespace(bot=bot, user_data={"lang": lang})
            await st_mod.send_main_menu(ctx, 555, lang, False)
            out[lang] = bot.sent
        return out

    res = _asyncio.run(run())
    for lang, sent in res.items():
        assert len(sent) == 1
        assert sent[0]["text"] == get_text("main_menu_hint", lang)
        kb = sent[0]["reply_markup"]
        assert isinstance(kb, ReplyKeyboardMarkup)
        labels = [b.text for row in kb.keyboard for b in row]
        assert (BTN_NEW_POST_RU if lang == "ru" else BTN_NEW_POST) in labels


def test_subscription_check_callback_localized_ru():
    """Obuna tasdiqlangach RU foydalanuvchi ruscha tabrik + main_menu_hint + menyu oladi."""
    import importlib
    from telegram import ReplyKeyboardMarkup
    st_mod = importlib.import_module("handlers.start")

    async def fake_check(bot, uid):
        return True, []

    orig_check = st_mod.check_user_subscribed
    st_mod.check_user_subscribed = fake_check
    restore = _patch_db({"get_user_language": "ru"})
    try:
        bot = _RecBot()

        class _Q:
            from_user = SimpleNamespace(id=901, first_name="Ivan")
            async def answer(self, *a, **k): return True
            class message:
                @staticmethod
                async def delete(): return True

        upd = SimpleNamespace(callback_query=_Q(), effective_user=_Q.from_user)
        ctx = SimpleNamespace(bot=bot, user_data={})
        _asyncio.run(st_mod.subscription_check_callback(upd, ctx))
        assert len(bot.sent) == 1
        text = bot.sent[0]["text"]
        assert "Подписка подтверждена" in text and "Ivan" in text
        assert get_text("main_menu_hint", "ru") in text
        assert isinstance(bot.sent[0]["reply_markup"], ReplyKeyboardMarkup)
    finally:
        st_mod.check_user_subscribed = orig_check
        restore()


def test_i18n_new_keys_parity_and_no_hardcoded_sub_text():
    """Yangi kalitlar ikkala tilda; parity buzilmagan; _deny_if_unsubscribed lokalizatsiya qilingan."""
    from locales.translations import translation_parity_report, has_key
    for key in ("unknown_message_fallback", "unknown_in_dialog", "np_sticker_not_allowed",
                "sub_required", "sub_confirmed", "sub_not_yet_alert", "sub_not_yet_msg",
                "main_menu_hint"):
        assert has_key(key, "uz") and has_key(key, "ru"), key
        assert get_text(key, "uz") != get_text(key, "ru"), key
    assert translation_parity_report()["in_sync"] is True
    h_src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    assert 'get_text("sub_required"' in h_src
    assert "Botdan to'liq foydalanish uchun quyidagi rasmiy kanallarga" not in h_src


# ------------------------------------------------------------ 3. CONCURRENCY
def test_double_click_same_user_is_serialized_no_state_corruption():
    """Talab 3: bitta foydalanuvchining 2 ta parallel update'i (double click)
    GuardedApplication.process_update orqali KETMA-KET ishlanadi, boshqa
    foydalanuvchi esa parallel; user_data'dagi read-modify-write yo'qolmaydi."""
    import main as main_mod

    events = []

    class _Parent:
        """Application o'rnini bosuvchi: haqiqiy process_update ish yukini taqlid qiladi."""
        user_data = {}

        async def process_update(self, update):
            uid = update.effective_user.id
            ud = self.user_data.setdefault(uid, {"step": 0})
            step = ud["step"]
            events.append(("start", uid, update.update_id))
            await _asyncio.sleep(0.02)  # DB/Telegram I/O taqlidi
            ud["step"] = step + 1        # qulfsiz bo'lsa ikkinchi bosish yo'qolardi
            events.append(("end", uid, update.update_id))

    class _Guarded(main_mod.GuardedApplication):
        """Application.__init__ siz (tarmoqsiz) — faqat process_update mantiqi."""
        def __init__(self):
            self._lock_manager = main_mod.UpdateLockManager()
            self._parent = _Parent()

        async def _answer_rate_limited(self, update):
            events.append(("rate_limited", update.effective_user.id, update.update_id))

    # super().process_update → _Parent.process_update
    async def _super_process(self, update):
        return await self._parent.process_update(update)

    orig_process = main_mod.Application.process_update
    main_mod.Application.process_update = _super_process
    # flood/dublikat himoyasi testga aralashmasin
    orig_flood, orig_rate, orig_dup = main_mod.check_global_flood, main_mod.check_rate_limit, main_mod.is_duplicate_message
    main_mod.check_global_flood = lambda: False
    main_mod.check_rate_limit = lambda *a, **k: (False, False)
    main_mod.is_duplicate_message = lambda *a, **k: False
    try:
        app = _Guarded()

        def upd(uid, n):
            return SimpleNamespace(update_id=n, effective_user=SimpleNamespace(id=uid),
                                   effective_chat=SimpleNamespace(id=uid),
                                   effective_message=SimpleNamespace(text=f"t{n}"), callback_query=None)

        async def run():
            await _asyncio.gather(app.process_update(upd(1, 1)), app.process_update(upd(1, 2)),
                                  app.process_update(upd(2, 3)))
        _asyncio.run(run())
    finally:
        main_mod.Application.process_update = orig_process
        main_mod.check_global_flood, main_mod.check_rate_limit, main_mod.is_duplicate_message = orig_flood, orig_rate, orig_dup

    assert app._parent.user_data[1]["step"] == 2, app._parent.user_data  # ikkala bosish ham hisobga olindi
    assert app._parent.user_data[2]["step"] == 1
    idx = {(e[0], e[2]): i for i, e in enumerate(events)}
    assert idx[("end", 1)] < idx[("start", 2)], events   # user 1: seriyali
    assert idx[("start", 3)] < idx[("end", 1)], events   # user 2: user 1 ni kutmadi
    assert not [e for e in events if e[0] == "rate_limited"]
    assert len(app._lock_manager._locks) == 0           # leak yo'q


def test_main_uses_guarded_application_with_concurrent_updates():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "class GuardedApplication" in src
    assert "concurrent_updates(True)" in src
    assert "asyncio.Lock" in src
    assert "def get_update_lock_key" in src


# ------------------------------------------------------------ 4. IDEMPOTENCY
def _sch_isolated():
    """Scheduler idempotency testlari uchun toza xotira/journal holati."""
    import scheduler as sch_mod
    sch_mod._UNPERSISTED_SENT.clear()
    sch_mod._journal_loaded = True  # diskdagi journalni o'qimaymiz
    return sch_mod


def test_scheduler_restart_does_not_resend_after_transient_db_error():
    """Talab 4: send → DB xatosi → restart: post QAYTA YUBORILMAYDI.

    Oqim: mark_post_processing → Telegram send OK → mark_post_as_sent XATO →
    backoff bilan qayta urinish → yozildi. Keyingi tick get_due_posts faqat
    'pending' ni oladi; recover_stale_processing_posts esa sent_message_id /
    sent_post_messages bo'yicha 'posted' ga o'tkazadi — 'pending' ga qaytarmaydi."""
    sch_mod = _sch_isolated()
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    sch_src = (ROOT / "scheduler.py").read_text(encoding="utf-8")

    # get_due_posts faqat pending'ni oladi (processing qayta olinmaydi)
    body = db_src.split("def get_due_posts", 1)[1].split("\ndef ", 1)[0]
    assert "status = 'pending'" in body and "FOR UPDATE SKIP LOCKED" in body
    assert "SET status = 'processing'" in body
    # recover: yuborilganlar posted, faqat yuborilmaganlar pending
    rec = db_src.split("def recover_stale_processing_posts", 1)[1].split("\ndef ", 1)[0]
    assert "SET status = 'posted'" in rec and "sent_post_messages" in rec
    assert "sent_message_id IS NULL" in rec
    # scheduler: processing send'dan oldin; send'dan keyin marker backoff bilan
    assert "db.mark_post_processing" in sch_src
    assert "await _persist_sent_marker(sent_marker)" in sch_src
    assert "await flush_unpersisted_sent_markers()" in sch_src
    # DB yozuv funksiyalari natija qaytaradi (False = xato) — scheduler shunga tayanadi
    for fn in ("mark_post_processing", "mark_post_status", "mark_post_as_sent"):
        fn_body = db_src.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
        assert "return True" in fn_body and "return False" in fn_body, fn

    calls = []
    fail_left = {"n": 2}   # mark_post_as_sent ikki marta "uzilib", uchinchisida yoziladi

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "mark_post_as_sent":
            if fail_left["n"] > 0:
                fail_left["n"] -= 1
                raise RuntimeError("transient DB error")
            return True
        if name == "mark_post_status":
            return False  # zaxira yo'li ham vaqtincha ishlamaydi
        return None

    sleeps = []

    async def fake_sleep(sec):
        sleeps.append(float(sec))

    class _Bot:
        def __init__(self): self.n = 0
        async def send_message(self, chat_id, text, **kw):
            self.n += 1
            return SimpleNamespace(message_id=4242)

    bot = _Bot()
    orig, orig_sleep = sch_mod.db.run_db, sch_mod.asyncio.sleep
    sch_mod.db.run_db, sch_mod.asyncio.sleep = fake_run_db, fake_sleep
    try:
        post = (777, 123456789, "-100123", "text", "Idempotent", None, None, None, False, None,
                "none", None, None, None, 0, None)
        _asyncio.run(sch_mod._execute_send(bot, post))
        names = [c[0] for c in calls]
        assert bot.n == 1
        assert names.index("mark_post_processing") < names.index("mark_post_as_sent")
        assert names.count("mark_post_as_sent") == 3          # 2 xato + 1 muvaffaqiyat
        assert sleeps[:2] == list(sch_mod.SENT_MARKER_RETRY_DELAYS[:2])  # backoff
        assert "retry_post" not in names
        assert 777 not in sch_mod._UNPERSISTED_SENT               # marker yozildi → guard tozalandi

        # "restart" — scheduler ticki: get_due_posts faqat pending ni beradi → 777 qayta chiqmaydi
        async def fake_due(fn, *a, **k):
            name = getattr(fn, "__name__", "")
            calls.append((name, a))
            return [] if name == "get_due_posts" else None
        sch_mod.db.run_db = fake_due
        _asyncio.run(sch_mod.check_and_send_posts(bot))
        assert bot.n == 1, "post faqat BIR marta yuborilishi shart"
    finally:
        sch_mod.db.run_db, sch_mod.asyncio.sleep = orig, orig_sleep
        sch_mod._UNPERSISTED_SENT.clear()


def test_scheduler_persistent_db_outage_guard_and_flush():
    """DB uzoq vaqt yotsa: post yuborilgach marker xotira/journal guard'ida qoladi;
    stale-recovery uni 'pending' qilib qayta bersa ham QAYTA YUBORILMAYDI; DB
    tiklangach keyingi tick boshida marker yoziladi (flush)."""
    sch_mod = _sch_isolated()
    db_down = {"v": True}
    calls = []
    # Soxta DB holati: marker yozilmaguncha stale-recovery postni 'pending' ga
    # qaytargan deb faraz qilamiz (eng yomon holat) — u har tick'da yana keladi.
    db_status = {900: "pending"}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name in ("mark_post_as_sent", "mark_post_status", "reschedule_recurring_post"):
            if db_down["v"]:
                raise RuntimeError("DB down")
            if name == "mark_post_as_sent":
                db_status[args[0]] = "posted"
            elif name == "mark_post_status":
                db_status[args[0]] = args[1]
            return True
        if name == "get_due_posts":
            if db_status.get(900) != "pending":
                return []  # haqiqiy DB: 'posted' post hech qachon olinmaydi
            return [(900, 1, "-100", "text", "Bir marta", None, None, None, False, None,
                     "none", None, None, None, 0, None)]
        return None

    async def fake_sleep(sec):
        return None

    class _Bot:
        def __init__(self): self.n = 0
        async def send_message(self, chat_id, text, **kw):
            self.n += 1
            return SimpleNamespace(message_id=1)

    bot = _Bot()
    orig, orig_sleep = sch_mod.db.run_db, sch_mod.asyncio.sleep
    sch_mod.db.run_db, sch_mod.asyncio.sleep = fake_run_db, fake_sleep
    try:
        # Tick 1: yuboriladi, marker yozilmaydi (DB down) → guard'da qoladi
        _asyncio.run(sch_mod.check_and_send_posts(bot))
        assert bot.n == 1
        assert sch_mod.is_sent_but_unpersisted(900)
        assert "retry_post" not in [c[0] for c in calls]
        # Tick 2 (DB hali down, post yana 'pending' deb keladi): QAYTA YUBORILMAYDI
        _asyncio.run(sch_mod.check_and_send_posts(bot))
        assert bot.n == 1, "DB yotganda ham post ikki marta chiqmasligi shart"
        # DB tiklandi → tick 3 boshida flush marker yozadi, post qayta yuborilmaydi
        db_down["v"] = False
        calls.clear()
        _asyncio.run(sch_mod.check_and_send_posts(bot))
        assert bot.n == 1
        names = [c[0] for c in calls]
        assert names and names[0] == "mark_post_as_sent" and names.index("mark_post_as_sent") < names.index("get_due_posts")
        assert not sch_mod.is_sent_but_unpersisted(900)
    finally:
        sch_mod.db.run_db, sch_mod.asyncio.sleep = orig, orig_sleep
        sch_mod._UNPERSISTED_SENT.clear()


def test_scheduler_sent_journal_survives_restart(tmp_path=None):
    """Journal fayli: marker restartdan keyin ham o'qiladi (best-effort) va guard ishlaydi."""
    import importlib
    import tempfile
    sch_mod = _sch_isolated()
    path = os.path.join(tempfile.mkdtemp(prefix="sent_journal_"), "journal.json")
    orig_path = sch_mod.SENT_JOURNAL_PATH
    sch_mod.SENT_JOURNAL_PATH = path
    try:
        marker = sch_mod._build_sent_marker(555, 77, "-100", 0, [78], "daily", None,
                                            _dt.time(10, 0), None)
        assert marker["next_time"]  # takrorlanuvchi post uchun keyingi vaqt saqlanadi
        sch_mod._UNPERSISTED_SENT[555] = marker
        sch_mod._journal_save()
        assert os.path.isfile(path)
        # "restart": xotira bo'sh, journal qayta o'qiladi
        sch_mod._UNPERSISTED_SENT.clear()
        sch_mod._journal_loaded = False
        assert sch_mod.is_sent_but_unpersisted(555)
        assert sch_mod._UNPERSISTED_SENT[555]["message_id"] == 77
        # DB tiklangach flush: posted + reschedule + pending; journal tozalanadi
        calls = []

        async def ok_db(fn, *a, **k):
            calls.append((getattr(fn, "__name__", ""), a))
            return True
        orig = sch_mod.db.run_db
        sch_mod.db.run_db = ok_db
        try:
            assert _asyncio.run(sch_mod.flush_unpersisted_sent_markers()) == 1
        finally:
            sch_mod.db.run_db = orig
        names = [c[0] for c in calls]
        assert names == ["mark_post_as_sent", "reschedule_recurring_post", "mark_post_status"], names
        assert ("mark_post_status", (555, "pending")) in calls
        assert not os.path.isfile(path) and not sch_mod._UNPERSISTED_SENT
    finally:
        sch_mod.SENT_JOURNAL_PATH = orig_path
        sch_mod._UNPERSISTED_SENT.clear()
        sch_mod._journal_loaded = True


def test_scheduler_processing_write_failure_aborts_before_send():
    """DB 'processing' markerini yozolmasa post YUBORILMAYDI (avval to'xtaymiz, keyin qayta navbat)."""
    sch_mod = _sch_isolated()
    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "mark_post_processing":
            return False
        if name == "get_due_posts":
            return [(901, 1, "-100", "text", "x", None, None, None, False, None,
                     "none", None, None, None, 0, None)]
        return None

    class _Bot:
        def __init__(self): self.n = 0
        async def send_message(self, *a, **k):
            self.n += 1
            return SimpleNamespace(message_id=1)

    bot = _Bot()
    orig = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        _asyncio.run(sch_mod.check_and_send_posts(bot))
    finally:
        sch_mod.db.run_db = orig
    assert bot.n == 0
    names = [c[0] for c in calls]
    assert "retry_post" in names  # keyinroq qayta uriniladi, post yo'qolmaydi


# --------------------------------------------------------- 5. KARTA CONFIG
def test_card_config_defaults_env_override_and_no_hardcoded_card():
    """Talab: CARD_NUMBER/CARD_HOLDER FAQAT .env dan; kodda hardcode yo'q."""
    import importlib
    import config as cfg
    # Kodda default karta qolmagan
    assert not hasattr(cfg, "DEFAULT_CARD_NUMBER")
    assert not hasattr(cfg, "DEFAULT_CARD_HOLDER")
    cfg_src = (ROOT / "config.py").read_text(encoding="utf-8")
    assert 'CARD_NUMBER = os.getenv("CARD_NUMBER", "")' in cfg_src
    assert 'CARD_HOLDER = os.getenv("CARD_HOLDER", "")' in cfg_src
    # Eski nomlar alias bo'lib qoladi
    assert cfg.PAYMENT_CARD_NUMBER == cfg.CARD_NUMBER
    assert cfg.PAYMENT_CARD_HOLDER == cfg.CARD_HOLDER

    saved = {k: os.environ.get(k) for k in ("CARD_NUMBER", "CARD_HOLDER",
                                            "PAYMENT_CARD_NUMBER", "PAYMENT_CARD_HOLDER")}
    try:
        # env yo'q → bo'sh (hech qanday yashirin default yo'q)
        for k in saved:
            os.environ.pop(k, None)
        importlib.reload(cfg)
        assert cfg.CARD_NUMBER == "" and cfg.CARD_HOLDER == ""
        assert cfg.PAYMENT_CARD_NUMBER == "" and cfg.PAYMENT_CARD_HOLDER == ""
        # env berilsa — aynan o'sha qiymatlar
        os.environ["CARD_NUMBER"] = "5614680000000001"
        os.environ["CARD_HOLDER"] = "Test T."
        importlib.reload(cfg)
        assert cfg.CARD_NUMBER == "5614680000000001" and cfg.CARD_HOLDER == "Test T."
        assert cfg.PAYMENT_CARD_NUMBER == "5614680000000001"
        assert cfg.PAYMENT_CARD_HOLDER == "Test T."
        # eski PAYMENT_CARD_* endi karta qiymatini BELGILAMAYDI
        os.environ.pop("CARD_NUMBER", None)
        os.environ.pop("CARD_HOLDER", None)
        os.environ["PAYMENT_CARD_NUMBER"] = "9860111122223333"
        os.environ["PAYMENT_CARD_HOLDER"] = "Legacy H."
        importlib.reload(cfg)
        assert cfg.CARD_NUMBER == "" and cfg.CARD_HOLDER == ""
        # Render'dagi qiymat to'lov oynasida aynan ko'rinadi
        os.environ["CARD_NUMBER"] = "8600123412341234"
        os.environ["CARD_HOLDER"] = "Render R."
        importlib.reload(cfg)
        import handlers.subscription as sub
        importlib.reload(sub)
        for lang in ("uz", "ru"):
            text = sub._build_card_payment_text(7, lang, "1m")
            assert "8600 1234 1234 1234" in text and "Render R." in text, lang
        # env bo'sh → "rekvizit yo'q" xabari
        os.environ["CARD_NUMBER"] = ""
        os.environ["CARD_HOLDER"] = ""
        importlib.reload(cfg)
        importlib.reload(sub)
        assert get_text("card_payment_no_card", "uz") in sub._build_card_payment_text(7, "uz", "1m")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(cfg)
        import handlers.subscription as sub
        importlib.reload(sub)

    # Handlerlarda karta raqami/egasi qattiq yozilmagan
    for rel in ("handlers/payment_receipt.py", "handlers/subscription.py", "config.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        if rel != "config.py":
            assert "8600060950825589" not in src, rel
            assert "8600 0609 5082 5589" not in src, rel
            assert "Sayitqulov" not in src, rel
    sub_src = (ROOT / "handlers/subscription.py").read_text(encoding="utf-8")
    assert "CARD_NUMBER" in sub_src and "CARD_HOLDER" in sub_src
    assert "PAYMENT_CARD_NUMBER" not in sub_src

    # .env.example (ikkala fayl) hujjatlashtirilgan
    for rel in (".env.example", "telegram_bot/.env.example"):
        env_src = (ROOT.parent / rel).read_text(encoding="utf-8")
        assert "CARD_NUMBER=" in env_src and "CARD_HOLDER=" in env_src, rel


def test_card_text_renders_config_values():
    import config as cfg
    import handlers.subscription as sub
    for lang in ("uz", "ru"):
        text = sub._build_card_payment_text(123, lang, "1m")
        assert sub._fmt_card_number(cfg.CARD_NUMBER) in text, lang
        assert cfg.CARD_HOLDER in text, lang


# ------------------------------------------------------- 6. STIKER FILTRI
def test_sticker_warning_texts_exact():
    """Talab 6: stiker ogohlantirishi UZ aynan talabdagidek, RU ekvivalenti mavjud."""
    assert get_text("np_sticker_not_allowed", "uz") == (
        "Kechirasiz, stikerlar post sifatida qabul qilinmaydi. "
        "Iltimos, rasm, video yoki matn yuboring"
    )
    ru = get_text("np_sticker_not_allowed", "ru")
    assert ru and ru != get_text("np_sticker_not_allowed", "uz") and "стикер" in ru.lower()


def test_content_received_rejects_sticker_in_user_language():
    """GET_CONTENT bosqichida stiker → o'z tilida ogohlantirish, holat GET_CONTENT da qoladi."""
    import handlers.new_post as np_mod
    from handlers.new_post import GET_CONTENT, content_received, classify_post_content, is_sticker_message

    class _Msg:
        def __init__(self, **kw):
            self.sticker = kw.get("sticker")
            self.voice = kw.get("voice")
            self.video_note = kw.get("video_note")
            self.contact = kw.get("contact")
            self.photo = kw.get("photo")
            self.video = kw.get("video")
            self.document = kw.get("document")
            self.audio = kw.get("audio")
            self.animation = kw.get("animation")
            self.text = kw.get("text")
            self.caption = kw.get("caption", "")
            self.media_group_id = None
            self.replies = []

        async def reply_text(self, text, **kw):
            self.replies.append(text)

    _f = SimpleNamespace(file_id="f1")
    assert is_sticker_message(_Msg(sticker=_f))
    assert not is_sticker_message(_Msg(text="salom"))
    assert classify_post_content(_Msg(sticker=_f)) == "sticker"
    assert classify_post_content(_Msg(voice=_f)) == "unsupported"
    assert classify_post_content(_Msg(video_note=_f)) == "unsupported"
    assert classify_post_content(_Msg(contact=_f)) == "unsupported"
    assert classify_post_content(_Msg(text="matn")) == "ok"
    assert classify_post_content(_Msg(photo=[SimpleNamespace(file_id="p")])) == "ok"

    async def run(lang):
        msg = _Msg(sticker=SimpleNamespace(file_id="st1"))
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": lang, "post_channel": "-100"}, bot=None)
        state = await content_received(upd, ctx)
        return state, msg.replies, ctx.user_data

    for lang in ("uz", "ru"):
        state, replies, ud = _asyncio.run(run(lang))
        assert state == GET_CONTENT, (lang, state)
        assert replies == [get_text("np_sticker_not_allowed", lang)], (lang, replies)
        assert "file_id" not in ud and "post_type" not in ud  # stiker post bo'lib qolmadi

    # voice → umumiy "media qabul qilinmaydi" xabari (stiker matni emas)
    async def run_voice():
        msg = _Msg(voice=SimpleNamespace(file_id="v1"))
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42), effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        return await content_received(upd, ctx), msg.replies
    state, replies = _asyncio.run(run_voice())
    assert state == GET_CONTENT and replies == [get_text("np_media_not_allowed", "uz")]


def test_edit_confirm_rejects_sticker_keeps_card():
    """Tasdiqlash/tahrirlash bosqichida stiker → ogohlantirish, CONFIRM_POST holati, karta saqlanadi."""
    from handlers.new_post import CONFIRM_POST, edit_confirm_message_received

    class _Msg:
        sticker = SimpleNamespace(file_id="st")
        text = None
        caption = None

        def __init__(self): self.replies = []
        async def reply_text(self, text, **kw): self.replies.append(text)

    async def run(lang):
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42), effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": lang, "content": "asl matn", "post_type": "photo",
                                         "file_id": "ph"}, bot=None)
        return await edit_confirm_message_received(upd, ctx), msg.replies, ctx.user_data

    for lang in ("uz", "ru"):
        state, replies, ud = _asyncio.run(run(lang))
        assert state == CONFIRM_POST
        assert replies == [get_text("np_sticker_not_allowed", lang)]
        assert ud["content"] == "asl matn" and ud["file_id"] == "ph" and ud["post_type"] == "photo"


def test_sticker_in_get_content_state_goes_to_conversation_not_fallback():
    """To'liq handler zanjiri: GET_CONTENT holatida stiker ConversationHandler ga tushadi
    (content_received) — fallback emas — va aynan stiker ogohlantirishi yuboriladi."""
    import handlers as h_mod
    from telegram.ext import ConversationHandler
    from handlers.new_post import GET_CONTENT
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "ru", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = GET_CONTENT
        bot = _RecBot()
        handler = _asyncio.run(_dispatch(app, _private_update(sticker=True, bot=bot), lang="ru"))
        assert isinstance(handler, ConversationHandler)
        assert conv._conversations.get((777, 777)) == GET_CONTENT
        assert bot.sent and bot.sent[0]["text"] == get_text("np_sticker_not_allowed", "ru")
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


# -------------------------------------------------- 7. REAKSIYA: STIKER + ERKIN EMOJI
def test_reactions_received_accepts_free_space_separated_emojis():
    """GET_REACTIONS: erkin emoji matni ("👍 ❤️ 🔥") tanlovga qo'shiladi."""
    from handlers.new_post import GET_REACTIONS, reactions_received

    class _Msg:
        def __init__(self, text):
            self.text = text
            self.sticker = None
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))

    async def run():
        msg = _Msg("👍 ❤️ 🔥")
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        state = await reactions_received(upd, ctx)
        return state, ctx.user_data, msg.replies

    state, ud, replies = _asyncio.run(run())
    assert state == GET_REACTIONS, state
    assert ud.get("selected_reactions") == ["👍", "❤️", "🔥"], ud
    assert replies, "javob yuborilmadi"
    for emoji in ("👍", "❤️", "🔥"):
        assert emoji in replies[0][0], replies[0]


def test_reactions_received_accepts_sticker_emoji():
    """GET_REACTIONS: stiker yuborilganda message.sticker.emoji reaksiyaga qo'shiladi."""
    from handlers.new_post import GET_REACTIONS, reactions_received

    class _Sticker:
        file_id = "st1"
        emoji = "🔥"

    class _Msg:
        def __init__(self):
            self.text = None
            self.sticker = _Sticker()
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))

    async def run():
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "ru"}, bot=None)
        state = await reactions_received(upd, ctx)
        return state, ctx.user_data, msg.replies

    state, ud, replies = _asyncio.run(run())
    assert state == GET_REACTIONS, state
    assert ud.get("selected_reactions") == ["🔥"], ud
    assert replies and "🔥" in replies[0][0], replies


def test_reactions_received_sticker_custom_emoji_added():
    """GET_REACTIONS: kanonik bo'lmagan stiker emojisi (😍) ham tanlovga qo'shiladi."""
    from handlers.new_post import GET_REACTIONS, reactions_received

    class _Sticker:
        file_id = "st2"
        emoji = "😍"

    class _Msg:
        def __init__(self):
            self.text = None
            self.sticker = _Sticker()
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))

    async def run():
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        state = await reactions_received(upd, ctx)
        return state, ctx.user_data, msg.replies

    state, ud, replies = _asyncio.run(run())
    assert state == GET_REACTIONS
    assert ud.get("selected_reactions") == ["😍"], ud


def test_reactions_received_sticker_without_emoji_falls_back_to_hint():
    """GET_REACTIONS: emojisi yo'q stiker — crash'siz inline eslatma, holat saqlanadi."""
    from handlers.new_post import GET_REACTIONS, reactions_received

    class _Sticker:
        file_id = "st3"
        emoji = None

    class _Msg:
        def __init__(self):
            self.text = None
            self.sticker = _Sticker()
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))

    async def run():
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=None)
        state = await reactions_received(upd, ctx)
        return state, ctx.user_data, msg.replies

    state, ud, replies = _asyncio.run(run())
    assert state == GET_REACTIONS
    assert replies and replies[0][0] == get_text("np_reactions_use_inline", "uz"), replies


def test_get_reactions_state_registers_sticker_handler():
    """GET_REACTIONS holatida filters.Sticker.ALL → reactions_received ro'yxatdan o'tgan."""
    src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    assert "MessageHandler(filters.Sticker.ALL, reactions_received)" in src


def test_sticker_in_get_reactions_state_goes_to_conversation_not_fallback():
    """To'liq zanjir: GET_REACTIONS holatida stiker ConversationHandler'ga tushadi
    (fallback emas) va stiker emojisi reaksiyaga qo'shiladi."""
    import handlers as h_mod
    from telegram.ext import ConversationHandler
    from handlers.new_post import GET_REACTIONS
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "ru", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = GET_REACTIONS
        bot = _RecBot()
        upd = _private_update(sticker=True, sticker_emoji="👍", bot=bot)
        handler = _asyncio.run(_dispatch(app, upd, lang="ru"))
        assert isinstance(handler, ConversationHandler), handler
        assert conv._conversations.get((777, 777)) == GET_REACTIONS
        assert bot.sent, "javob yuborilmadi"
        assert bot.sent[0]["text"] == get_text("np_reactions_selected", "ru", emojis="👍"), bot.sent[0]["text"]
        # Fallback emas — aynan reaksiya tanlovi javobi
        assert bot.sent[0]["text"] != get_text("unknown_message_fallback", "ru")
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


def test_free_emoji_in_get_reactions_state_goes_to_conversation_not_fallback():
    """To'liq zanjir: GET_REACTIONS holatida "👍 ❤️ 🔥" matni ham ConversationHandler'da
    qabul qilinadi va fallback'ga tushmaydi."""
    import handlers as h_mod
    from telegram.ext import ConversationHandler
    from handlers.new_post import GET_REACTIONS
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = GET_REACTIONS
        bot = _RecBot()
        upd = _private_update(text="👍 ❤️ 🔥", bot=bot)
        handler = _asyncio.run(_dispatch(app, upd, lang="uz"))
        assert isinstance(handler, ConversationHandler), handler
        assert conv._conversations.get((777, 777)) == GET_REACTIONS
        assert bot.sent and "👍" in bot.sent[0]["text"] and "❤️" in bot.sent[0]["text"]
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


# ============================================================== ONBOARDING
def test_start_onboarding_texts_exact_uz_ru():
    """Birinchi marta kirgan foydalanuvchi matni aynan talabdagidek (uz/ru)."""
    assert get_text("start_onboarding", "uz") == (
        "👋 Xush kelibsiz! Telegram kanalingiz uchun 1 daqiqada professional post tayyorlaymizmi?\n"
        "\n"
        "✍️ AI post yozish\n"
        "📅 Istalgan vaqtga rejalashtirish\n"
        "📢 Avtomatik kanalga chiqarish\n"
        "\n"
        "Birinchi postingizni hoziroq tayyorlash uchun quyidagi bo'limni tanlang 👇"
    )
    assert get_text("start_onboarding", "ru") == (
        "👋 Добро пожаловать! Готовы создать профессиональный пост для вашего канала всего за 1 минуту?\n"
        "\n"
        "✍️ Генерация постов через AI\n"
        "📅 Планирование на любое время\n"
        "📢 Автопостинг в каналы\n"
        "\n"
        "Чтобы создать свой первый пост прямо сейчас, выберите раздел ниже 👇"
    )


def _run_start(is_new: bool, lang: str):
    """/start ni ishga tushirib, (matn, reply_markup) juftligini qaytaradi."""
    import importlib
    from telegram import ReplyKeyboardMarkup  # noqa: F401
    import database as db_mod
    st_mod = importlib.import_module("handlers.start")

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "save_user":
            return is_new
        if name == "get_user_language":
            return lang
        if name == "get_setting":
            return ""
        if name == "is_premium":
            return False
        return None

    async def fake_check(bot, uid):
        return True, []

    class _Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup))
            return None

    user = SimpleNamespace(id=880001, username="newbie", full_name="Yangi User",
                           first_name="Yangi", language_code=lang)
    msg = _Msg()
    upd = SimpleNamespace(message=msg, effective_user=user, effective_message=msg)
    ctx = SimpleNamespace(bot=_RecBot(), user_data={}, chat_data={}, args=[])

    orig_run_db, orig_check = db_mod.run_db, st_mod.check_user_subscribed
    db_mod.run_db = fake_run_db
    st_mod.check_user_subscribed = fake_check
    try:
        _asyncio.run(st_mod.start(upd, ctx))
    finally:
        db_mod.run_db = orig_run_db
        st_mod.check_user_subscribed = orig_check
    assert msg.replies, "start() javob bermadi"
    return msg.replies[0]


def test_start_first_time_user_gets_onboarding_and_main_menu():
    """Birinchi marta kirgan (is_new=True) → onboarding matni + bosh menyu."""
    from telegram import ReplyKeyboardMarkup
    from keyboards.default import BTN_NEW_POST, BTN_NEW_POST_RU
    for lang, btn in (("uz", BTN_NEW_POST), ("ru", BTN_NEW_POST_RU)):
        text, markup = _run_start(True, lang)
        assert text.startswith(get_text("start_onboarding", lang)), (lang, text[:80])
        assert get_text("start_hello", lang, name="Yangi") not in text
        assert isinstance(markup, ReplyKeyboardMarkup)
        labels = [b.text for row in markup.keyboard for b in row]
        assert btn in labels, (lang, labels)


def test_start_returning_user_gets_standard_greeting():
    """Qayta kirgan (is_new=False) → standart salomlashish + bosh menyu."""
    from telegram import ReplyKeyboardMarkup
    for lang in ("uz", "ru"):
        text, markup = _run_start(False, lang)
        assert text.startswith(get_text("start_hello", lang, name="Yangi")), (lang, text[:80])
        assert get_text("start_onboarding", lang) not in text
        assert isinstance(markup, ReplyKeyboardMarkup)


def test_start_source_uses_is_new_branch():
    """handlers/start.py da is_new bo'yicha onboarding tarmog'i mavjud."""
    src = (ROOT / "handlers/start.py").read_text(encoding="utf-8")
    assert 'get_text("start_onboarding"' in src
    assert 'get_text("start_hello"' in src
    assert "if is_new:" in src


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"New requirements: {len(tests)} tests passed")
