"""Delivery options regression tests; no Telegram or PostgreSQL required."""
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'telegram_bot'))
os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN')
os.environ.setdefault('ADMIN_ID', '123456789')
os.environ.setdefault('DATABASE_URL', 'postgresql://user:pass@localhost/testdb')

import database as db
import scheduler as sched
from handlers import manual_post as manual
from utils.delivery_options import DELIVERY_KEYS, delivery_markup


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_and_reset(self):
        for lang in ('uz', 'ru', 'en'):
            context = SimpleNamespace(user_data={manual.UD_CONTENT: 'Hello'})
            query = SimpleNamespace(data='mnp_delivery', from_user=SimpleNamespace(id=1),
                                    answer=AsyncMock(), edit_message_reply_markup=AsyncMock())
            with patch.object(manual, 'get_lang', return_value=lang):
                for key in DELIVERY_KEYS:
                    query.data = 'mnp_delivery:' + key
                    for expected in (True, False):
                        await manual.manual_panel_callback(SimpleNamespace(callback_query=query), context)
                        self.assertIs(context.user_data[manual.UD_DELIVERY][key], expected)
                before = dict(context.user_data[manual.UD_DELIVERY])
                query.data = 'mnp_delivery:invalid'
                await manual.manual_panel_callback(SimpleNamespace(callback_query=query), context)
                self.assertEqual(before, context.user_data[manual.UD_DELIVERY])
            markup = delivery_markup({}, lang)
            self.assertEqual(len(markup.inline_keyboard), 4)
            for row in markup.inline_keyboard:
                self.assertLessEqual(len(row[0].callback_data.encode()), 64)
            manual.clear_fsm_data(context)
            self.assertNotIn(manual.UD_DELIVERY, context.user_data)

    async def test_scheduler_delivery_and_pin_failure(self):
        for kind in ('text', 'photo', 'video', 'animation', 'document', 'audio', 'voice', 'sticker', 'album'):
            for enabled in (False, True):
                with self.subTest(kind=kind, enabled=enabled):
                    options = dict.fromkeys(DELIVERY_KEYS, enabled)
                    async def run_db(fn, *args):
                        if fn is db.get_post_delivery_options:
                            return options if enabled else None
                        if fn is db.get_setting:
                            return ''
                        return True
                    bot = MagicMock()
                    for method in ('message', 'photo', 'video', 'animation', 'document', 'audio', 'voice', 'sticker'):
                        setattr(bot, 'send_' + method, AsyncMock(return_value=SimpleNamespace(message_id=9)))
                    bot.send_media_group = AsyncMock(return_value=[SimpleNamespace(message_id=9), SimpleNamespace(message_id=10)])
                    bot.pin_chat_message = AsyncMock(side_effect=RuntimeError('no pin rights'))
                    post = (1, 123456789, '-100123', kind, 'Hello', 'file', 'Link', 'https://example.com',
                            False, None, 'none', None, None, None, 0, None)
                    with patch.object(db, 'run_db', side_effect=run_db), \
                         patch.object(sched, 'is_sent_but_unpersisted', return_value=False), \
                         patch.object(sched, 'resolve_channel_ad', AsyncMock(return_value={})), \
                         patch.object(sched, 'apply_post_watermark', AsyncMock(return_value='Hello')), \
                         patch.object(sched, 'parse_album_items', return_value=[{'type': 'photo', 'file_id': 'a'}, {'type': 'photo', 'file_id': 'b'}]), \
                         patch.object(sched, '_persist_sent_marker', AsyncMock()) as persist:
                        await sched._execute_send(bot, post)
                        persist.assert_awaited_once()
                    method = 'media_group' if kind == 'album' else ('message' if kind == 'text' else kind)
                    kwargs = getattr(bot, 'send_' + method).await_args.kwargs
                    self.assertIs(kwargs['disable_notification'], enabled)
                    self.assertIs(kwargs['protect_content'], enabled)
                    if enabled:
                        bot.pin_chat_message.assert_awaited_once_with(chat_id=-100123, message_id=9, disable_notification=True)
                    else:
                        bot.pin_chat_message.assert_not_awaited()

    async def test_settings_read_failure_stops_delivery(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        post = (1, 123456789, '-100123', 'text', 'Hello', None, None, None,
                False, None, 'none', None, None, None, 0, None)
        with patch.object(db, 'run_db', AsyncMock(side_effect=RuntimeError('DB unavailable'))), \
             patch.object(sched, 'is_sent_but_unpersisted', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'DB unavailable'):
                await sched._execute_send(bot, post)
        bot.send_message.assert_not_awaited()

    async def test_single_album_item_options(self):
        bot = SimpleNamespace(send_photo=AsyncMock())
        await sched._send_single_media(bot, -100123, 'photo', 'file', 'Hello', None,
                                       disable_notification=True, protect_content=True)
        self.assertTrue(bot.send_photo.await_args.kwargs['protect_content'])

    def test_options_saved_atomically(self):
        import json
        cur = MagicMock()
        cur.fetchone.side_effect = [(1,), (42,)]
        @contextmanager
        def cursor(**kwargs):
            yield cur
        with patch.object(db, 'db_cursor', cursor), patch.object(db, '_invalidate_user'), patch.object(db, '_cache_clear'):
            self.assertEqual(db.add_post(1, '-100123', 'text', 'Hello', None, None,
                                        delivery_options=dict.fromkeys(DELIVERY_KEYS, True)), 42)
        sql, args = cur.execute.call_args.args
        self.assertEqual(sql.count('%s'), len(args))
        self.assertEqual(json.loads(args[-1]), dict.fromkeys(DELIVERY_KEYS, True))


if __name__ == '__main__':
    unittest.main()
