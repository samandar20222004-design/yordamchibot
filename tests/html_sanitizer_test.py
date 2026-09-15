#!/usr/bin/env python3
"""PHASE 2 / step 2: strict offline entity parser + real PTB transport tests.

No live Telegram/DB/AI credentials are used. The simulator is intentionally
independent of the sanitizer: XML enforces balanced markup/entities, then a
Telegram-specific whitelist checks attributes and prohibited nesting.
"""
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import random
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
os.environ.setdefault("BOT_TOKEN", "123456:HTML_TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ.setdefault("ADMIN_ID", "123456789")

from utils.telegram_sanitizer import (
    sanitize_html, html_length, html_to_text, escape_html, escape_html_limited,
    telegram_html_payload, truncate_text,
)
from utils.telegram_delivery import SafeHTMLBot, sanitize_api_payload, create_safe_bot
from telegram import InputMediaPhoto, InputMediaVideo, InputTextMessageContent, InlineQueryResultArticle
from telegram.error import BadRequest, TimedOut
from telegram.ext import Defaults
from telegram.request import BaseRequest

TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
        "a", "span", "tg-spoiler", "pre", "code", "blockquote"}


def simulate_entities(text, limit=4096):
    if re.search(r"&(?!amp;|lt;|gt;|quot;|#\d+;|#x[0-9a-fA-F]+;)", text):
        raise ValueError("unsupported or unfinished entity")
    # XML needs a value for Telegram's boolean expandable attribute.
    xml = text.replace("<blockquote expandable>", '<blockquote expandable="">')
    try:
        root = ET.fromstring("<root>" + xml + "</root>")
    except ET.ParseError as exc:
        raise ValueError("unbalanced or raw HTML") from exc

    def visit(node, ancestors):
        if node.tag not in TAGS:
            raise ValueError("unknown tag")
        attrs = node.attrib
        allowed = {"a": {"href"}, "span": {"class"}, "code": {"class"},
                   "blockquote": {"expandable"}}.get(node.tag, set())
        if not set(attrs) <= allowed:
            raise ValueError("unsafe attributes")
        if node.tag == "a" and not re.match(r"^(https?|tg)://[^\s]+$", attrs.get("href", "")):
            raise ValueError("bad href")
        if node.tag == "span" and attrs.get("class") != "tg-spoiler":
            raise ValueError("not a spoiler span")
        if node.tag == "code" and "class" in attrs:
            if not ancestors or ancestors[-1] != "pre" or not attrs["class"].startswith("language-"):
                raise ValueError("code language outside pre")
        if "code" in ancestors or ("pre" in ancestors and node.tag != "code"):
            raise ValueError("formatting inside code/pre")
        if node.tag in ("code", "pre") and ancestors and not (ancestors == ["pre"] and node.tag == "code"):
            raise ValueError("code/pre inside formatting")
        if node.tag in ("a", "blockquote") and node.tag in ancestors:
            raise ValueError("nested links/quotes")
        for child in node:
            visit(child, ancestors + [node.tag])
    for child in root:
        visit(child, [])
    plain = "".join(root.itertext())
    if len(plain.encode("utf-16-le")) // 2 > limit:
        raise ValueError("Telegram text limit exceeded")
    return plain


class SanitizerTests(unittest.TestCase):
    def valid(self, raw, limit=4096):
        output = sanitize_html(raw, limit)
        simulate_entities(output, limit)
        self.assertEqual(output, sanitize_html(output, limit), "must be idempotent")
        return output

    def test_unclosed(self):
        self.assertEqual(self.valid("<b>Salom"), "<b>Salom</b>")
        self.assertEqual(self.valid("<b><i>Salom"), "<b><i>Salom</i></b>")

    def test_crossed_and_stray_closers(self):
        self.valid("</i><b>A<i>B</b>C</i>")

    def test_unknown_tags(self):
        for tag in ("div", "p", "script", "img", "style", "iframe", "span", "tg-emoji"):
            with self.subTest(tag=tag):
                output = self.valid(f"<{tag}>salom</{tag}>")
                self.assertNotIn(f"<{tag}>", output)
                self.assertIn("salom", output)

    def test_whitelist(self):
        for tag in TAGS - {"a", "span"}:
            with self.subTest(tag=tag):
                self.assertIn(">salom</", self.valid(f"<{tag}>salom</{tag}>"))
        self.valid('<span class="tg-spoiler">sir</span><tg-spoiler>sir</tg-spoiler>')

    def test_raw_symbols(self):
        self.assertEqual(self.valid("5 < 10 & price > 100"), "5 &lt; 10 &amp; price &gt; 100")

    def test_entities(self):
        self.assertEqual(self.valid("&amp; &lt; &gt; &quot; &#39; &#x1F600; &copy; &bogus;"),
                         '&amp; &lt; &gt; " \' 😀 © &amp;bogus;')
        self.valid("&amp;lt;b&amp;gt; &amp;amp;")

    def test_broken_tokens(self):
        for raw in ('x <b', '<a href="https://x.com', 'x &amp', 'x <!--',
                    '<![broken]>', '<?bad?>', '<b/>x', '<b title=">">x',
                    '<b><span>x</b>', '<span class="tg-spoiler"><span>x</span>y</span>'):
            with self.subTest(raw=raw):
                self.valid(raw)

    def test_attributes(self):
        self.assertEqual(self.valid('<b onclick="x" style="bad">x</b>'), '<b>x</b>')
        self.assertEqual(self.valid('<span class="tg-spoiler" onclick="x">x</span>'),
                         '<span class="tg-spoiler">x</span>')
        self.valid('<blockquote expandable cite="x">quote</blockquote>')

    def test_urls(self):
        for url in ('javascript:alert(1)', 'data:text/plain,x', 'file:///etc/passwd',
                    'https://', 'https://user:pass@x.com', 'https://x.com/ bad',
                    'java&#115;cript:alert(1)', 'https://x.com:bad'):
            with self.subTest(url=url):
                self.assertNotIn('<a href=', self.valid(f'<a href="{url}">link</a>'))
        self.assertIn('href="https://x.com/?a=1&amp;b=2"',
                      self.valid('<a href="https://x.com/?a=1&b=2">link</a>'))
        self.valid('<a href="tg://user?id=123">user</a>')

    def test_nesting_restrictions(self):
        for raw in ('<code><b>x</b></code>', '<b><pre>x</pre></b>',
                    '<pre><code class="language-python">x & y</code></pre>',
                    '<a href="https://x.com"><a href="https://y.com">x</a>y</a>',
                    '<blockquote>x<blockquote>y</blockquote>z</blockquote>',
                    '<b><b>x</b>y</b>'):
            self.valid(raw)

    def test_limits(self):
        for limit in (0, 1, 2, 5, 1024, 4096):
            for raw in ("x" * 5000, '<b><i>' + "&amp;" * 5000,
                        '<a href="https://x.com">' + "😀" * 5000,
                        '<pre><code class="language-python">' + "<&>" * 2000):
                with self.subTest(limit=limit):
                    self.valid(raw, limit)

    def test_exact_limit_ignores_markup(self):
        self.assertEqual(self.valid('<b>' + 'x' * 4096 + '</b>'), '<b>' + 'x' * 4096 + '</b>')
        self.assertEqual(html_length(self.valid('<i>' + '&amp;' * 1025, 1024)), 1024)

    def test_utf16_boundary(self):
        self.assertEqual(html_to_text(self.valid('<b>😀😀x', 3)), '😀')
        self.assertEqual(truncate_text('😀x', 2), '😀')

    def test_controls_and_surrogates(self):
        self.valid('a\x00\x01\ud800b & # \n\t')
        self.valid('&#0; &#xD800; &#99999999;')

    def test_empty_and_arbitrary_values(self):
        self.assertEqual(sanitize_html(None), '')
        self.assertEqual(sanitize_html(123), '123')
        self.assertEqual(sanitize_html(''), '')
        self.assertEqual(sanitize_html('<b>x', None), '<b>x</b>')

    def test_literal_contract(self):
        from utils.security import safe_html, safe_text, safe_limit_html
        from utils.helpers import safe_html as formatted, html_escape
        self.assertEqual(safe_html('<b>x</b>'), '&lt;b&gt;x&lt;/b&gt;')
        self.assertEqual(html_escape('<b>x</b>'), safe_html('<b>x</b>'))
        self.assertEqual(formatted('<b>x'), '<b>x</b>')
        for limit in range(20):
            value = safe_text('<&"' * 50, limit)
            self.assertLessEqual(len(value), limit)
            simulate_entities(value)
        self.assertEqual(len(safe_text('<' * 50, 10)), 10)
        simulate_entities(safe_limit_html('&' * 500))

    def test_payload_contract(self):
        self.assertEqual(telegram_html_payload('5 < 10 & >'), ('5 < 10 & >', None))
        self.assertEqual(telegram_html_payload('<u>x'), ('<u>x</u>', 'HTML'))
        self.assertEqual(telegram_html_payload('x' * 5000, 1024), ('x' * 1024, None))

    def test_simulator_rejects_bad_payloads(self):
        for raw in ('<b>x', '<i>x</b>', '<div>x</div>', 'a & b', '<span>x</span>',
                    '<a href="javascript:x">x</a>', '<code><b>x</b></code>', 'x' * 4097):
            with self.assertRaises(ValueError):
                simulate_entities(raw)

    def test_deterministic_fuzz(self):
        rng = random.Random(20260915)
        tokens = ['<b>', '</b>', '<i>', '</i>', '<pre>', '<code>', '</code>',
                  '<script>', '</script>', '<span>', '</span>', '&', '<', '>',
                  '&amp;', '&copy;', '😀', 'Salom', ' ', '<a href="https://x.com">',
                  '</a>', '<!--x-->', '<blockquote expandable>', '</blockquote>']
        for _ in range(600):
            raw = ''.join(rng.choices(tokens, k=40))
            self.valid(raw, rng.choice([0, 1, 10, 100, 1024, 4096]))

    def test_deep_input(self):
        self.valid('<b>' * 10000 + 'x' + '</b>' * 10000)


class RecordingRequest(BaseRequest):
    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 15

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        data = {key: json.loads(value) if key in ('media', 'results') else value
                for key, value in request_data.json_parameters.items()}
        self.calls.append((endpoint, data, request_data.multipart_data))
        if endpoint == 'getMe':
            result = {'id': 123456, 'is_bot': True, 'first_name': 'Test', 'username': 'test_bot'}
        elif endpoint == 'sendMediaGroup':
            result = [{'message_id': n, 'date': 1, 'chat': {'id': 1, 'type': 'private'}} for n in (1, 2)]
        elif endpoint == 'copyMessage':
            result = {'message_id': 1}
        elif endpoint in ('answerInlineQuery', 'editMessageMedia'):
            result = True
        else:
            result = {'message_id': 1, 'date': 1, 'chat': {'id': 1, 'type': 'private'}}
        return 200, json.dumps({'ok': True, 'result': result}).encode()


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = RecordingRequest()
        self.bot = SafeHTMLBot('123456:TEST', request=self.request,
                               get_updates_request=RecordingRequest(), defaults=Defaults(parse_mode='HTML'))
        await self.bot.initialize()

    async def asyncTearDown(self):
        await self.bot.shutdown()

    async def test_real_ptb_message_defaults_and_edit(self):
        await self.bot.send_message(1, '<b>' + '&' * 5000)
        self.assertEqual(len(simulate_entities(self.request.calls[-1][1]['text'])), 4096)
        await self.bot.edit_message_text('<i>broken', chat_id=1, message_id=1)
        self.assertEqual(self.request.calls[-1][1]['text'], '<i>broken</i>')

    async def test_api_kwargs_applied_before_sanitizer(self):
        await self.bot.send_message(1, 'placeholder', parse_mode=None,
                                    api_kwargs={'text': '<b>unsafe &', 'parse_mode': 'HTML'})
        self.assertEqual(self.request.calls[-1][1]['text'], '<b>unsafe &amp;</b>')

    async def test_all_media_and_caption_edit(self):
        for method, field in [('send_photo', 'photo'), ('send_video', 'video'),
                              ('send_animation', 'animation'), ('send_document', 'document'),
                              ('send_audio', 'audio'), ('send_voice', 'voice')]:
            with self.subTest(method=method):
                await getattr(self.bot, method)(chat_id=1, **{field: 'file_id'}, caption='<b>' + '😀&' * 2000)
                simulate_entities(self.request.calls[-1][1]['caption'], 1024)
        await self.bot.edit_message_caption(chat_id=1, message_id=1, caption='<i>x&')
        self.assertEqual(self.request.calls[-1][1]['caption'], '<i>x&amp;</i>')
        await self.bot.copy_message(1, 2, 3, caption='<b>x&', parse_mode='HTML')
        simulate_entities(self.request.calls[-1][1]['caption'], 1024)

    async def test_albums_and_uploaded_files(self):
        media = [InputMediaPhoto(BytesIO(b'fake-photo'), caption='<b>' + '&' * 2000, parse_mode='HTML'),
                 InputMediaVideo('file_id', caption='<i>broken', parse_mode='HTML')]
        await self.bot.send_media_group(1, media)
        data = self.request.calls[-1][1]
        for item in data['media']:
            simulate_entities(item['caption'], 1024)
        self.assertTrue(self.request.calls[-1][2], 'file attachment must survive copying')
        await self.bot.edit_message_media(media[0], chat_id=1, message_id=1)
        simulate_entities(self.request.calls[-1][1]['media']['caption'], 1024)

    async def test_plain_and_markdown_not_rewritten(self):
        for mode in (None, 'MarkdownV2'):
            await self.bot.send_message(1, '<b>literal &', parse_mode=mode)
            self.assertEqual(self.request.calls[-1][1]['text'], '<b>literal &')

    async def test_inline_content(self):
        result = InlineQueryResultArticle('1', 'Title', InputTextMessageContent('<b>' + '&' * 5000, parse_mode='HTML'))
        await self.bot.answer_inline_query('id', [result])
        body = self.request.calls[-1][1]['results'][0]['input_message_content']['message_text']
        simulate_entities(body)

    async def test_media_is_not_mutated(self):
        original = InputMediaPhoto('file_id', caption='<b>x&', parse_mode='HTML')
        cleaned = sanitize_api_payload(original)
        self.assertEqual(original.caption, '<b>x&')
        self.assertEqual(cleaned.caption, '<b>x&amp;</b>')
        self.assertEqual(cleaned.media, original.media)
        data = {'text': '<b>x', 'parse_mode': 'HTML', 'entities': ['stale']}
        self.assertIsNone(sanitize_api_payload(data)['entities'])
        self.assertEqual(data['entities'], ['stale'])

    async def test_magic_and_photo_direct_helpers(self):
        from handlers.magic_post import _magic_deliver_one
        from handlers.image_post import _send_photo_to_chat, _send_photo_preview
        bot = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock())
        raw = '<b>' + '&' * 5000
        self.assertTrue(await _magic_deliver_one(bot, 1, raw))
        simulate_entities(bot.send_message.call_args.kwargs['text'])
        await _send_photo_to_chat(bot, 1, 'file_id', raw)
        simulate_entities(bot.send_photo.call_args.kwargs['caption'], 1024)
        target = SimpleNamespace(reply_photo=AsyncMock())
        await _send_photo_preview(target, 'file_id', raw)
        simulate_entities(target.reply_photo.call_args.kwargs['caption'], 1024)

    async def test_magic_no_duplicate_on_timeout(self):
        from handlers.magic_post import _magic_deliver_one
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimedOut()))
        self.assertFalse(await _magic_deliver_one(bot, 1, '<b>text'))
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_magic_parse_fallback_is_plain_not_escaped(self):
        from handlers.magic_post import _magic_deliver_one
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[BadRequest("can't parse entities"), None]))
        self.assertTrue(await _magic_deliver_one(bot, 1, '<b>A & B'))
        self.assertEqual(bot.send_message.call_args.kwargs['text'], 'A & B')
        self.assertIsNone(bot.send_message.call_args.kwargs['parse_mode'])

    async def test_ai_studio_preview(self):
        from handlers.ai_assistant import _send_preview
        target = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        await _send_preview(target, '<b>' + '&' * 5000, 'file_id', 'photo', None)
        simulate_entities(target.reply_photo.call_args.kwargs['caption'], 1024)
        for call in target.reply_text.call_args_list:
            simulate_entities(call.args[0])

    async def test_scheduler_brand_and_album(self):
        from scheduler import compose_post_text, _build_album_media
        for limit in (1024, 4096):
            output = compose_post_text('<b>' + '&amp;' * 6000, False, '<i>ad', '<u>@brand</u>', limit)
            self.assertTrue(output.endswith('<u>@brand</u>'))
            simulate_entities(output, limit)
        oversized_brand = compose_post_text('<b>content', True, '', '<i>' + 'b' * 2000, 1024)
        self.assertEqual(simulate_entities(oversized_brand, 1024), 'b' * 1024)
        for item in _build_album_media([{'type': 'photo', 'file_id': '1'}, {'type': 'video', 'file_id': '2'}], '<b>' + '&' * 5000):
            if item.caption:
                simulate_entities(item.caption, 1024)

    async def test_ai_proxy(self):
        from utils.ai_agent import sanitize_magic_post_html
        self.assertEqual(sanitize_magic_post_html('<b>x&'), '<b>x&amp;</b>')

    async def test_production_wiring(self):
        source = (ROOT / 'telegram_bot/main.py').read_text()
        self.assertIn('.bot(create_safe_bot(BOT_TOKEN))', source)
        bot = create_safe_bot('123456:TEST')
        self.assertIsInstance(bot, SafeHTMLBot)
        self.assertEqual(bot.request.read_timeout, 15)
        await bot.request.shutdown()
        await bot._request[0].shutdown()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    errors = len(result.failures) + len(result.errors)
    print(f"HTML SANITIZER: {result.testsRun} tests, {errors} errors, {len(result.skipped)} skipped")
    if errors:
        print('[FAIL] HTML sanitizer suite')
    else:
        print('[OK] HTML sanitizer suite')
    sys.exit(0 if result.wasSuccessful() else 1)
