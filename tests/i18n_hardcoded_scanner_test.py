"""Regression tests for the i18n menu merge and the hard-coded UI scanner."""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(REPO_ROOT / "telegram_bot"))

from i18n_hardcoded_scanner import (  # noqa: E402
    find_hardcoded_strings,
    scan,
    scan_file,
    scan_handlers_and_keyboards,
)
from translations import (  # noqa: E402
    CONTENT_MENU_I18N,
    content_menu_parity_report,
    content_menu_t,
)


EXPECTED_AI_LABELS = {
    "uz": {
        "ai_chat": "💬 AI Chat",
        "ai_audit": "🔍 Post auditi",
        "ai_improve": "✏️ Postni yaxshilash",
        "ai_ideas": "💡 Kontent g'oyalari",
        "ai_plan": "🧠 Kontent reja",
        "ai_analysis": "📊 Kanal tahlili",
    },
    "ru": {
        "ai_chat": "💬 AI Чат",
        "ai_audit": "🔍 Аудит поста",
        "ai_improve": "✏️ Улучшить пост",
        "ai_ideas": "💡 Идеи контента",
        "ai_plan": "🧠 Контент-план",
        "ai_analysis": "📊 Анализ канала",
    },
    "en": {
        "ai_chat": "💬 AI Chat",
        "ai_audit": "🔍 Post audit",
        "ai_improve": "✏️ Improve post",
        "ai_ideas": "💡 Content ideas",
        "ai_plan": "🧠 Content plan",
        "ai_analysis": "📊 Channel analysis",
    },
}


def test_conflict_resolution_keeps_both_translation_sets() -> None:
    """The AI labels and the newer unified menu labels coexist in all locales."""
    for lang, expected in EXPECTED_AI_LABELS.items():
        table = CONTENT_MENU_I18N[lang]
        for key, label in expected.items():
            assert table[key] == label
            assert content_menu_t(key, lang) == label

    # The newer menu choice wins for the shared key; legacy routing labels stay.
    assert content_menu_t("cm_btn_magic", "uz") == "✨ AI bilan yaratish (Magic Post)"
    assert content_menu_t("cm_btn_magic", "ru") == "✨ Создать с AI (Magic Post)"
    assert content_menu_t("cm_btn_magic", "en") == "✨ Create with AI (Magic Post)"
    legacy_and_menu_keys = (
        "cm_btn_manual",
        "cm_btn_studio",
        "cm_btn_back",
        "cm_btn_text",
        "cm_btn_image",
        "cm_btn_voice",
        "cm_btn_ai",
    )
    for lang in EXPECTED_AI_LABELS:
        for key in legacy_and_menu_keys:
            assert content_menu_t(key, lang)

    assert content_menu_parity_report()["in_sync"] is True


def test_scanner_finds_direct_and_keyword_ui_text() -> None:
    source = textwrap.dedent(
        '''\
        async def handler(update, context, translated_text, user):
            await update.message.reply_text("Reply text")
            await context.bot.send_message(123, "send positional")
            await context.bot.send_message(chat_id=123, text="send keyword")
            InlineKeyboardButton("Inline button", callback_data="callback")
            KeyboardButton(text="Reply button")
            await update.callback_query.answer(f"Hello {user}!")
            await update.message.reply_text(translated_text)
            logger.info("not UI")
            await update.message.reply_text("   ")
        '''
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "handler.py"
        path.write_text(source, encoding="utf-8")
        findings = scan_file(path)

    assert [(name, text) for _, name, text in findings] == [
        ("reply_text", "Reply text"),
        ("send_message", "send positional"),
        ("send_message", "send keyword"),
        ("InlineKeyboardButton", "Inline button"),
        ("KeyboardButton", "Reply button"),
        ("answer", "Hello !"),
    ]
    assert find_hardcoded_strings is scan_file
    assert scan_handlers_and_keyboards is scan


def test_scan_is_limited_to_handlers_and_keyboards() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        handler = root / "telegram_bot" / "handlers" / "handler.py"
        keyboard = root / "telegram_bot" / "keyboards" / "keyboard.py"
        service = root / "telegram_bot" / "services" / "service.py"
        for path in (handler, keyboard, service):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('reply_text("Visible")\n', encoding="utf-8")

        results = scan(root)
        paths = {Path(path).relative_to(root).as_posix() for path in results}

    assert paths == {
        "telegram_bot/handlers/handler.py",
        "telegram_bot/keyboards/keyboard.py",
    }


def _run() -> None:
    tests = (
        test_conflict_resolution_keeps_both_translation_sets,
        test_scanner_finds_direct_and_keyword_ui_text,
        test_scan_is_limited_to_handlers_and_keyboards,
    )
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"PASS: {len(tests)}, FAIL: 0")


if __name__ == "__main__":
    _run()
