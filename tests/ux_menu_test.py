"""UX part 1: unified help, reaction save-to-preview and album warnings.

Run with: python tests/ux_menu_test.py (from telegram_bot).
All Telegram calls are mocked; no network or database is needed.
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:UX_MENU_TEST_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from handlers import manual_post as mp, settings  # noqa: E402
from keyboards import inline as kb  # noqa: E402
from translations import manual_post_t, settings_stats_t  # noqa: E402
from translations.settings_stats import (  # noqa: E402
    CB_SETTINGS_HUB, CB_SETTINGS_HELP_HUB, SETTINGS_MENU_BUTTON_KEYS,
    SETTINGS_HELP_HUB_BUTTON_KEYS, settings_stats_parity_report,
)

start = importlib.import_module("handlers.start")
LANGS = ("uz", "ru", "en")
HELP_LABELS = {
    "uz": "ℹ️ Yordam va Qo'llanma",
    "ru": "ℹ️ Помощь и руководство",
    "en": "ℹ️ Help and Guide",
}
SAVE_LABELS = {
    "uz": "✅ Saqlash va davom etish",
    "ru": "✅ Сохранить и продолжить",
    "en": "✅ Save and continue",
}
ALBUM_WARNING_UZ = (
    "⚠️ Telegram cheklovi sababli, tugmali postlar faqat 1 ta media bilan chiqadi. "
    "Tugma qo'shilsa, faqat birinchi media yuboriladi."
)


def buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def callback_update(data):
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=7777), message=message,
        answer=AsyncMock(), edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query)


class UXMenuTests(unittest.IsolatedAsyncioTestCase):
    def test_settings_layout_and_localization_contract(self):
        self.assertTrue(settings_stats_parity_report()["in_sync"])
        for lang in LANGS:
            with self.subTest(lang=lang):
                panel = kb.get_settings_profile_keyboard(lang)
                flat = buttons(panel)
                self.assertEqual([len(row) for row in panel.inline_keyboard], [2] * 4)
                self.assertEqual([b.callback_data for b in flat], list(CB_SETTINGS_HUB))
                self.assertEqual([b.text for b in flat], [
                    settings_stats_t(key, lang) for key in SETTINGS_MENU_BUTTON_KEYS
                ])
                self.assertEqual(flat[-2].text, HELP_LABELS[lang])
                self.assertNotIn("stgs_about", [b.callback_data for b in flat])
                self.assertNotIn("help_support", [b.callback_data for b in flat])
                help_buttons = buttons(kb.get_settings_help_hub_keyboard(lang))
                self.assertEqual([b.callback_data for b in help_buttons], list(CB_SETTINGS_HELP_HUB))
                self.assertEqual([b.text for b in help_buttons], [
                    settings_stats_t(key, lang) for key in SETTINGS_HELP_HUB_BUTTON_KEYS
                ])

    async def test_help_click_shows_about_guide_and_contact_in_one_message(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                update = callback_update("stgs_help_hub")
                query = update.callback_query
                with patch.object(start, "ensure_user_lang", AsyncMock(return_value=lang)), \
                     patch.object(settings, "SUPPORT_USERNAME", "@support_user"):
                    await settings.settings_menu_callback(update, SimpleNamespace(user_data={}))
                query.answer.assert_awaited_once()
                query.edit_message_text.assert_awaited_once()
                query.message.reply_text.assert_not_awaited()
                text = query.edit_message_text.call_args.args[0]
                self.assertIn("<b>PostAssist</b>", text)
                self.assertIn("/help", text)
                self.assertIn('<a href="https://t.me/support_user">@support_user</a>', text)
                self.assertLessEqual(len(text), 4096)
                markup = query.edit_message_text.call_args.kwargs["reply_markup"]
                self.assertEqual([b.callback_data for b in buttons(markup)], ["help_support", "stgs_hub"])

    async def test_help_without_username_keeps_ticket_access(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                query = callback_update("stgs_help_hub").callback_query
                with patch.object(settings, "SUPPORT_USERNAME", ""), \
                     patch.object(start, "SUPPORT_USERNAME", ""):
                    await settings._render_help_hub(query, lang)
                    support_line = start._help_support_line(lang)
                text = query.edit_message_text.call_args.args[0]
                self.assertIn(support_line, text)
                self.assertNotIn('href="https://t.me/', text)
                markup = query.edit_message_text.call_args.kwargs["reply_markup"]
                self.assertEqual(buttons(markup)[0].callback_data, "help_support")

    async def test_legacy_help_callbacks_still_route(self):
        for data, renderer in (("stgs_about", "_render_about"), ("help_hub", "_render_help"),
                               ("stgs_help", "_render_help"), ("help_support", "_render_support")):
            with self.subTest(callback=data):
                with patch.object(start, "ensure_user_lang", AsyncMock(return_value="uz")), \
                     patch.object(settings, renderer, AsyncMock()) as render:
                    await settings.settings_menu_callback(callback_update(data), SimpleNamespace(user_data={}))
                render.assert_awaited_once()

    async def test_save_returns_to_preview_with_selected_reactions(self):
        for lang in LANGS:
            for selected in ([], ["👍", "🔥"]):
                with self.subTest(lang=lang, selected=selected):
                    context = SimpleNamespace(user_data={
                        "lang": lang, mp.UD_CONTENT: "Test post", mp.UD_REACTIONS: list(selected),
                    })
                    save = kb.get_manual_reaction_keyboard(selected, lang).inline_keyboard[-1][0]
                    self.assertEqual(save.text, SAVE_LABELS[lang])
                    update = callback_update(save.callback_data)
                    state = await mp.manual_panel_callback(update, context)
                    self.assertEqual(state, mp.MANUAL_PREVIEW)
                    self.assertEqual(context.user_data[mp.UD_REACTIONS], selected)
                    update.callback_query.answer.assert_awaited_once()
                    reply = update.callback_query.message.reply_text
                    reply.assert_awaited_once()
                    self.assertIn("Test post", reply.call_args.args[0])
                    self.assertIn(kb.CB_MANUAL_NOW, [
                        b.callback_data for b in buttons(reply.call_args.kwargs["reply_markup"])
                    ])
                    for emoji in selected:
                        self.assertIn(emoji, [b.text for b in buttons(reply.call_args.kwargs["reply_markup"])])

    async def test_url_and_reaction_album_warnings(self):
        for lang in LANGS:
            expected = ALBUM_WARNING_UZ if lang == "uz" else manual_post_t("mp_album_warning", lang)
            for album in (False, True):
                for data, state in ((kb.CB_MANUAL_REACT, mp.MANUAL_PREVIEW),
                                    (kb.CB_MANUAL_URL_BTN, mp.MANUAL_URL_INPUT)):
                    with self.subTest(lang=lang, album=album, callback=data):
                        context = SimpleNamespace(user_data={
                            "lang": lang, mp.UD_CONTENT: "Test post", mp.UD_MEDIA_GROUP: album,
                        })
                        update = callback_update(data)
                        self.assertEqual(await mp.manual_panel_callback(update, context), state)
                        text = update.callback_query.message.reply_text.call_args.args[0]
                        self.assertEqual(expected in text, album)
                        self.assertEqual(context.user_data[mp.UD_MEDIA_GROUP], album)


if __name__ == "__main__":
    unittest.main(verbosity=2)
