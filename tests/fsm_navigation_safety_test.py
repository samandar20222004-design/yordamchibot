#!/usr/bin/env python3
"""PHASE 2 · 3-QADAM — FSM TOZALASH VA MENYU XAVFSIZLIGI TESTLARI.

Qamrov (topshiriq talablari bilan birma-bir):
  1) Oraliq holatlarda (MAGIC_INPUT, PHOTO_WAITING) turganda foydalanuvchi
     asosiy menyu tugmalarini yoki /start bossa, context.user_data tozalanib,
     FSM state bekor qilinadi (ConversationHandler.END).
  2) "❌ Bekor qilish" barcha oqimlarda yagona standartda ishlaydi:
     context.user_data tozalanadi, ConversationHandler.END qaytariladi va
     foydalanuvchi xavfsiz menyuga qaytariladi.
  3) Admin callbacklarida RBAC (user_id admin ro'yxatida borligi) qat'iy
     tekshiriladi (server-side from_user.id asosida):
     - Admin bo'lmagan foydalanuvchi chaqirganda rad javobi (show_alert=True)
       beriladi va amallar bajarilmaydi;
     - Admin foydalanuvchi chaqirganda esa ruxsat beriladi.
  4) Middleware qatlami (FSMCleanerMiddleware, admin_rbac_required)
     hammasini yagona xavfsizlik filtri ostida ta'minlaydi.
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:FSM_SAFETY_TEST_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("ADMIN_IDS", "123456789,987654321")

from telegram.ext import ConversationHandler
from config import ADMIN_IDS_SET
from handlers import PHOTO_WAITING
from handlers.magic_post import magic_text_received
from handlers.image_post import (
    image_photo_received,
    image_topic_received,
    IMAGE_POST_INPUT,
)
from handlers.admin import admin_dashboard_callback
from handlers.start import cancel_handler
from middlewares.fsm_cleaner import is_cancel_trigger, is_start_or_menu_trigger, is_navigation_trigger, FSMCleanerMiddleware
from middlewares.rbac import is_admin_user, admin_rbac_required, RBAC_DENIED_MESSAGE


async def fake_run_db(func, *args, **kwargs):
    name = getattr(func, "__name__", str(func))
    if name == "get_setting":
        return ""
    if name == "save_user":
        return False
    if name == "get_user_language":
        return "uz"
    if name == "is_premium":
        return False
    if name == "get_user_channels":
        return []
    if name in ("get_system_stats", "get_admin_dashboard_stats"):
        return {"users": 100, "posts": 250, "channels": 10, "pro_users": 20}
    return ""


def create_mock_message_update(user_id: int, text: str = "", caption: str = ""):
    """Creates a mock Update with a Message."""
    user = SimpleNamespace(
        id=user_id,
        username="test_user",
        first_name="Test",
        last_name="",
        full_name="Test User",
        language_code="uz",
    )
    chat = SimpleNamespace(id=user_id, type="private")

    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.photo = []
    msg.document = None
    msg.from_user = user
    msg.chat = chat
    msg.reply_text = AsyncMock()
    msg.delete = AsyncMock()

    update = MagicMock()
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = msg
    update.message = msg
    update.callback_query = None
    return update


def create_mock_callback_update(user_id: int, data: str):
    """Creates a mock Update with a CallbackQuery."""
    user = SimpleNamespace(id=user_id, username="test_user", first_name="Test", language_code="uz")
    chat = SimpleNamespace(id=user_id, type="private")

    query = MagicMock()
    query.data = data
    query.from_user = user
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()

    update = MagicMock()
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = query.message
    update.message = None
    update.callback_query = query
    return update


def create_mock_context(user_data: dict | None = None):
    """Creates a mock ContextTypes.DEFAULT_TYPE."""
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    context.bot = MagicMock()
    context.args = []
    return context


# ============================================================
# TEST 1: MAGIC_INPUT holatida /start yoki menyu bosilganda
# ============================================================

async def test_magic_input_interrupted_by_start():
    """Foydalanuvchi MAGIC_INPUT da turganda /start yuborsa:
    context.user_data tozalanadi, ConversationHandler.END qaytariladi."""
    user_id = 555111
    context = create_mock_context({
        "magic_raw_text": "Qoralamadagi xom matn",
        "temp_quota": 1,
        "step": "MAGIC_INPUT",
    })
    update = create_mock_message_update(user_id=user_id, text="/start")

    with patch("handlers.start.db.run_db", new=fake_run_db), \
         patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
        result = await magic_text_received(update, context)

    assert result == ConversationHandler.END, f"Kutilgan END, lekin qaytdi: {result}"
    assert "magic_raw_text" not in context.user_data, "magic_raw_text tozalanmadi!"
    assert "temp_quota" not in context.user_data, "FSM user_data to'liq tozalanmadi!"
    print("  [OK] MAGIC_INPUT holatida /start: user_data tozalandi va state END bo'ldi")


async def test_magic_input_interrupted_by_main_menu():
    """Foydalanuvchi MAGIC_INPUT da turganda '🏠 Asosiy menyu' bossa:
    context.user_data tozalanadi, ConversationHandler.END qaytariladi."""
    user_id = 555111
    context = create_mock_context({
        "magic_raw_text": "Boshqa matn",
        "nav_section": "content",
    })
    update = create_mock_message_update(user_id=user_id, text="🏠 Asosiy menyu")

    with patch("handlers.start.db.run_db", new=fake_run_db), \
         patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
        result = await magic_text_received(update, context)

    assert result == ConversationHandler.END, f"Kutilgan END, lekin qaytdi: {result}"
    assert "magic_raw_text" not in context.user_data, "magic_raw_text tozalanmadi!"
    print("  [OK] MAGIC_INPUT holatida '🏠 Asosiy menyu': user_data tozalandi va state END bo'ldi")


async def test_magic_input_interrupted_by_menu_buttons():
    """Foydalanuvchi MAGIC_INPUT da boshqa asosiy menyu tugmalarini bossa
    (masalan '➕ Yangi post' yoki '📢 Kanallarim'): FSM bekor bo'ladi."""
    user_id = 555111
    for btn_text in ["➕ Yangi post", "📢 Kanallarim", "📊 Statistika", "🤖 AI Yordamchi"]:
        context = create_mock_context({"magic_raw_text": "Interrupted", "step": "MAGIC_INPUT"})
        update = create_mock_message_update(user_id=user_id, text=btn_text)

        with patch("handlers.start.db.run_db", new=fake_run_db), \
             patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
            result = await magic_text_received(update, context)

        assert result == ConversationHandler.END, f"Tugma '{btn_text}' da END bo'lmadi: {result}"
        assert "magic_raw_text" not in context.user_data, f"Tugma '{btn_text}' da user_data tozalanmadi!"
    print("  [OK] MAGIC_INPUT da barcha asosiy menyu tugmalari FSM ni xavfsiz tozalaydi")


# ============================================================
# TEST 2: PHOTO_WAITING / IMAGE_POST_INPUT holatida tozalanish
# ============================================================

async def test_photo_waiting_alias():
    """PHOTO_WAITING konstantasi IMAGE_POST_INPUT bilan mos kelishini tasdiqlash."""
    assert PHOTO_WAITING == IMAGE_POST_INPUT, "PHOTO_WAITING va IMAGE_POST_INPUT mos emas!"
    print(f"  [OK] PHOTO_WAITING == IMAGE_POST_INPUT ({PHOTO_WAITING})")


async def test_photo_waiting_interrupted_by_start():
    """Foydalanuvchi PHOTO_WAITING holatida rasm o'rniga /start yuborsa:
    'Faqat rasm yuboring' deb qotib qolmaydi, context tozalanib END bo'ladi."""
    user_id = 555222
    context = create_mock_context({
        "image_post_file_id": "file_12345",
        "image_post_caption": "Eski rasm tavsifi",
    })
    update = create_mock_message_update(user_id=user_id, text="/start")

    with patch("handlers.start.db.run_db", new=fake_run_db), \
         patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
        result = await image_photo_received(update, context)

    assert result == ConversationHandler.END, f"Kutilgan END, lekin qaytdi: {result}"
    assert "image_post_file_id" not in context.user_data, "image_post_file_id tozalanmadi!"
    assert "image_post_caption" not in context.user_data, "image_post_caption tozalanmadi!"
    print("  [OK] PHOTO_WAITING holatida /start: user_data tozalandi va state END bo'ldi")


async def test_photo_waiting_interrupted_by_main_menu():
    """Foydalanuvchi PHOTO_WAITING holatida '🏠 Asosiy menyu' bossa:
    context tozalanadi va state END bo'ladi."""
    user_id = 555222
    context = create_mock_context({
        "image_post_file_id": "file_999",
        "image_post_caption": "Old",
    })
    update = create_mock_message_update(user_id=user_id, text="🏠 Asosiy menyu")

    with patch("handlers.start.db.run_db", new=fake_run_db), \
         patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
        result = await image_photo_received(update, context)

    assert result == ConversationHandler.END, f"Kutilgan END, lekin qaytdi: {result}"
    assert len(context.user_data) == 0 or "image_post_file_id" not in context.user_data
    print("  [OK] PHOTO_WAITING holatida Asosiy menyu: user_data tozalandi va state END bo'ldi")


async def test_image_topic_interrupted_by_navigation():
    """IMAGE_TOPIC_INPUT holatida /start yoki menyu bossa: tozalanish va END."""
    user_id = 555222
    context = create_mock_context({
        "image_post_file_id": "file_abc",
        "image_post_caption": "Mavzu kutilyapti",
    })
    update = create_mock_message_update(user_id=user_id, text="/start")

    with patch("handlers.start.db.run_db", new=fake_run_db), \
         patch("handlers.start.check_user_subscribed", new=AsyncMock(return_value=(True, []))):
        result = await image_topic_received(update, context)

    assert result == ConversationHandler.END
    assert "image_post_file_id" not in context.user_data
    print("  [OK] IMAGE_TOPIC_INPUT holatida /start: user_data tozalandi va state END bo'ldi")


# ============================================================
# TEST 3: "❌ Bekor qilish" BARCHA OQIMLARDA YAGONA STANDARTDA
# ============================================================

async def test_cancel_in_magic_input():
    """MAGIC_INPUT da '❌ Bekor qilish' bosilganda context tozalanadi va END bo'ladi."""
    user_id = 555333
    context = create_mock_context({"magic_raw_text": "Bekor qilinadigan matn"})
    update = create_mock_message_update(user_id=user_id, text="❌ Bekor qilish")

    result = await magic_text_received(update, context)

    assert result == ConversationHandler.END
    assert "magic_raw_text" not in context.user_data
    update.message.reply_text.assert_called_once()
    print("  [OK] MAGIC_INPUT da '❌ Bekor qilish' standart bo'yicha tozalandi va bekor bo'ldi")


async def test_cancel_in_photo_waiting():
    """PHOTO_WAITING da '❌ Bekor qilish' bosilganda context tozalanadi va END bo'ladi."""
    user_id = 555333
    context = create_mock_context({"image_post_file_id": "file_cancel_me"})
    update = create_mock_message_update(user_id=user_id, text="❌ Bekor qilish")

    result = await image_photo_received(update, context)

    assert result == ConversationHandler.END
    assert "image_post_file_id" not in context.user_data
    update.message.reply_text.assert_called_once()
    print("  [OK] PHOTO_WAITING da '❌ Bekor qilish' standart bo'yicha tozalandi va bekor bo'ldi")


async def test_cancel_handler_direct():
    """cancel_handler to'g'ridan-to'g'ri chaqirilganda barcha oqimlar uchun standart ishlaydi."""
    user_id = 555333
    context = create_mock_context({"flow_state": "arbitrary_pending_work", "data": [1, 2, 3]})
    update = create_mock_message_update(user_id=user_id, text="/cancel")

    result = await cancel_handler(update, context)

    assert result == ConversationHandler.END
    assert "flow_state" not in context.user_data
    assert "data" not in context.user_data
    update.message.reply_text.assert_called_once()
    print("  [OK] Universal cancel_handler context.user_data ni tozalaydi va END qaytaradi")


# ============================================================
# TEST 4: ADMIN CALLBACKLARIDA QAT'IY RBAC TEKSHIRUVI
# ============================================================

async def test_admin_callback_denied_for_non_admin():
    """Admin ro'yxatida bo'lmagan foydalanuvchi admin callback yuborsa:
    show_alert=True bilan rad etiladi va amallar mutlaqo bajarilmaydi."""
    non_admin_id = 888111222
    assert non_admin_id not in ADMIN_IDS_SET
    assert not is_admin_user(non_admin_id)

    update = create_mock_callback_update(user_id=non_admin_id, data="adm_stats")
    context = create_mock_context()

    result = await admin_dashboard_callback(update, context)

    assert result == ConversationHandler.END
    # edit_message_text chaqirilmagan bo'lishi shart!
    update.callback_query.edit_message_text.assert_not_called()
    # answer(show_alert=True) chaqirilgan
    update.callback_query.answer.assert_called_once()
    args, kwargs = update.callback_query.answer.call_args
    assert kwargs.get("show_alert") is True
    print("  [OK] Non-admin admin callback (adm_stats) rad etildi (show_alert=True)")


async def test_admin_callback_allowed_for_admin():
    """Haqiqiy admin foydalanuvchi admin callback yuborsa: muvaffaqiyatli o'tadi."""
    admin_id = next(iter(ADMIN_IDS_SET))
    assert is_admin_user(admin_id)

    update = create_mock_callback_update(user_id=admin_id, data="adm_stats")
    context = create_mock_context()

    fake_stats = {
        "users": 100, "channels": 10, "sponsors": 2,
        "pending": 5, "sent": 250, "cancelled": 3, "failed": 1,
    }
    with patch("handlers.admin.db.run_db", new=AsyncMock(return_value=fake_stats)):
        result = await admin_dashboard_callback(update, context)

    assert result == ConversationHandler.END
    # edit_message_text chaqirilgan bo'lishi shart
    update.callback_query.edit_message_text.assert_called_once()
    print("  [OK] Admin foydalanuvchi uchun admin callback muvaffaqiyatli bajarildi")


async def test_admin_rbac_decorator_enforcement():
    """admin_rbac_required dekoratori noadmin so'rovlarini to'xtatishini tasdiqlash."""
    non_admin_id = 999333
    target_called = False

    @admin_rbac_required
    async def sample_admin_action(update, context):
        nonlocal target_called
        target_called = True
        return "success"

    # 1. Non-admin callback
    update_non_admin = create_mock_callback_update(user_id=non_admin_id, data="adm_test")
    context = create_mock_context()
    res = await sample_admin_action(update_non_admin, context)

    assert target_called is False
    assert res == ConversationHandler.END
    update_non_admin.callback_query.answer.assert_called_once_with(
        text=RBAC_DENIED_MESSAGE,
        show_alert=True,
    )

    # 2. Admin callback
    admin_id = next(iter(ADMIN_IDS_SET))
    update_admin = create_mock_callback_update(user_id=admin_id, data="adm_test")
    res_admin = await sample_admin_action(update_admin, context)

    assert target_called is True
    assert res_admin == "success"
    print("  [OK] @admin_rbac_required dekoratori noadminlarni alert bilan to'xtatadi")


# ============================================================
# TEST 5: MIDDLEWARE VA NAVIGATSIYA TRIGGERLARI
# ============================================================

async def test_fsm_cleaner_middleware():
    """FSMCleanerMiddleware navigatsiya signallarida user_data ni tozalaydi."""
    context = create_mock_context({"active_flow": "voice", "temp_file": "voice.ogg"})
    update = create_mock_message_update(user_id=123, text="🏠 Asosiy menyu")

    cleaned = await FSMCleanerMiddleware.process_update(update, context)

    assert cleaned is True
    assert "active_flow" not in context.user_data
    assert "temp_file" not in context.user_data

    # Oddiy matn kelsa tozalamaydi
    context.user_data["test_key"] = "keep_me"
    update_regular = create_mock_message_update(user_id=123, text="Oddiy post matni")
    cleaned_regular = await FSMCleanerMiddleware.process_update(update_regular, context)

    assert cleaned_regular is False
    assert context.user_data.get("test_key") == "keep_me"
    print("  [OK] FSMCleanerMiddleware navigatsiya signallarida xavfsiz tozalaydi")


def test_navigation_trigger_patterns():
    """is_cancel_trigger va is_start_or_menu_trigger regex va tillar bo'yicha to'g'ri ishlashi."""
    cancels = ["❌ Bekor qilish", "❌ Отмена", "❌ Cancel", "/cancel", "Bekor qilish", "cancel"]
    for c in cancels:
        assert is_cancel_trigger(c) is True, f"Cancel trigger tanilmadi: {c}"
        assert is_navigation_trigger(c) is True

    menus = ["/start", "/menu", "🏠 Asosiy menyu", "🏠 Главное меню", "🏠 Main menu", "➕ Yangi post", "📢 Kanallarim"]
    for m in menus:
        assert is_start_or_menu_trigger(m) is True, f"Menu trigger tanilmadi: {m}"
        assert is_navigation_trigger(m) is True

    regulars = ["Mening yangi postim", "Bugun qiziqarli yangilik", "https://t.me/kanal"]
    for r in regulars:
        assert is_navigation_trigger(r) is False, f"Oddiy matn trigger deb topildi: {r}"
    print("  [OK] Barcha tillardagi bekor qilish va navigatsiya triggerlari aniq tanildi")


# ============================================================
# MAIN TEST RUNNER
# ============================================================

async def main_async():
    print("==============================================================")
    print(" PHASE 2 · 3-QADAM: FSM TOZALASH VA MENYU XAVFSIZLIGI TESTLARI")
    print("==============================================================")

    print("\n== 1. MAGIC_INPUT Navigatsiya va Tozalanish ==")
    await test_magic_input_interrupted_by_start()
    await test_magic_input_interrupted_by_main_menu()
    await test_magic_input_interrupted_by_menu_buttons()

    print("\n== 2. PHOTO_WAITING Navigatsiya va Tozalanish ==")
    await test_photo_waiting_alias()
    await test_photo_waiting_interrupted_by_start()
    await test_photo_waiting_interrupted_by_main_menu()
    await test_image_topic_interrupted_by_navigation()

    print("\n== 3. '❌ Bekor qilish' Yagona Standarti ==")
    await test_cancel_in_magic_input()
    await test_cancel_in_photo_waiting()
    await test_cancel_handler_direct()

    print("\n== 4. Admin Callbacklarida Qat'iy RBAC ==")
    await test_admin_callback_denied_for_non_admin()
    await test_admin_callback_allowed_for_admin()
    await test_admin_rbac_decorator_enforcement()

    print("\n== 5. Middleware va Triggerlar ==")
    await test_fsm_cleaner_middleware()
    test_navigation_trigger_patterns()

    print("\n==============================================================")
    print(" BARCHA FSM XAVFSIZLIGI VA RBAC TESTLARI MUVOFFAQIYATLI O'TDI ✔")
    print("==============================================================")


def main():
    try:
        asyncio.run(main_async())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
