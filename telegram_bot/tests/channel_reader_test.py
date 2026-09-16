#!/usr/bin/env python3
"""OCHIQ TELEGRAM KANALLARINI O'QISH (web-preview scraper) testlari.

Muammo: foydalanuvchi ochiq kanal linkini yuborganda (masalan
@kunuzofficial yoki https://t.me/kunuzofficial) bot "Kanal postlari
o'qilmadi" deb xato bermoqda edi — parser real t.me/s/ HTML strukturasiga
(tgme_widget_message_wrap) mos kelmasdi va to'liq havolalar tozalanmasdi.

Tuzatish:
  1. extract_channel_username — @nik / nik / https://t.me/nik /
     https://t.me/s/nik / https://t.me/nik/123 formatlarini qabul qiladi;
  2. _parse_channel_page — real tgme_widget_message_wrap strukturasini
     o'qiydi (data-post, views, media, background-image);
  3. read_channel_posts — DB (bot-admin kanallar) → t.me/s/ scraping
     fallback, holat (status) bilan: ok/private/not_found/empty/invalid/error;
  4. Yopiq kanal → "Bu yopiq kanal..." xabari;
  5. Sayt havolasi (https://kun.uz/) → read_webpage_for_ai: title +
     meta description + asosiy matn (1000 belgigacha) → AI tahliliga;
  6. Kanal ovozi tahlili — DB tarixi bo'sh bo'lsa web-preview fallback.

Ishga tushirish:
    cd telegram_bot && python tests/channel_reader_test.py
"""
import asyncio
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

warnings.filterwarnings("ignore", category=UserWarning)

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telegram import Update, Message, Chat, User  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

CHECKS = []


def check(msg, cond, detail=""):
    CHECKS.append((bool(cond), msg, str(detail)))
    if not cond:
        print(f"  [FAIL] {msg}: {detail}")
    else:
        print(f"  [OK] {msg}")


# ======================================================================
# Real t.me/s/ sahifasi strukturasi (2024-2026 format)
# ======================================================================
REAL_TME_HTML = """<!DOCTYPE html><html><head><title>Kun.uz — Telegram</title></head><body>
<div class="tgme_background_wrap"></div>
<div class="tgme_main_wrap">
<section class="tgme_channel_history js-widget_chat_history">
<div class="tgme_widget_message_wrap js-widget_message " data-post="kunuzofficial/173901" data-view="channels">
  <div class="tgme_widget_message_user"><a class="tgme_widget_message_owner_photo" href="https://t.me/kunuzofficial"></a></div>
  <div class="tgme_widget_message_middle"><div class="tgme_widget_message_bubble" data-view="channels">
    <div class="tgme_widget_message_author title" dir="auto"><a class="tgme_widget_message_owner_name" href="https://t.me/kunuzofficial">Kun.uz</a></div>
    <div class="tgme_widget_message_text js-message_text" dir="auto"><b>Гофуржон Мирзаев</b> назначен<br/><br/>Он работал советником с 2022 года. <a href="https://kun.uz/kr/56852084">https://kun.uz/kr/56852084</a></div>
    <div class="tgme_widget_message_footer compact js-message_footer"><div class="tgme_widget_message_info short js-message_info">
      <span class="tgme_widget_message_views">238K</span>
      <a class="tgme_widget_message_date" href="https://t.me/kunuzofficial/173901"><time datetime="2026-09-07T04:14:00+00:00">04:14</time></a>
    </div></div>
  </div></div>
</div>
<div class="tgme_widget_message_wrap js-widget_message " data-post="kunuzofficial/173902" data-view="channels">
  <div class="tgme_widget_message_middle"><div class="tgme_widget_message_bubble" data-view="channels">
    <div class="tgme_widget_message_text js-message_text" dir="auto">Погода на неделю: сухо и жарко 🌡</div>
    <a class="tgme_widget_message_photo_wrap" href="https://t.me/kunuzofficial/173902" style="width:480px;background-image:url('https://cdn4.telesco.pe/file/photo2.jpg')"><img class="tgme_widget_message_photo js-tgme_photo" src="https://cdn4.telesco.pe/file/photo2.jpg" style="width:480px"></a>
    <div class="tgme_widget_message_footer"><div class="tgme_widget_message_info short js-message_info">
      <span class="tgme_widget_message_views">219K</span>
      <a class="tgme_widget_message_date" href="https://t.me/kunuzofficial/173902"><time datetime="2026-09-07T02:26:00+00:00">02:26</time></a>
    </div></div>
  </div></div>
</div>
<div class="tgme_widget_message_wrap js-widget_message " data-post="kunuzofficial/173903" data-view="channels">
  <div class="tgme_widget_message_middle"><div class="tgme_widget_message_bubble" data-view="channels">
    <div class="tgme_widget_message_video_thumb" style="background-image:url('https://cdn4.telesco.pe/file/video3.jpg')"><i class="link_bg"></i></div>
    <div class="tgme_widget_message_footer"><div class="tgme_widget_message_info short js-message_info">
      <span class="tgme_widget_message_views">1.1M</span>
      <a class="tgme_widget_message_date" href="https://t.me/kunuzofficial/173903"><time datetime="2026-09-07T03:10:00+00:00">03:10</time></a>
    </div></div>
  </div></div>
</div>
</section></div></body></html>"""

PRIVATE_TME_HTML = """<html><head><title>Telegram Messenger</title></head><body>
<div class="tgme_page_wrap"><div class="tgme_page">
<div class="tgme_page_title">Shaxsiy kanal</div>
<div class="tgme_page_extra">If you have Telegram, you can view and join ...</div>
</div></div></body></html>"""

KUNUZ_HTML = """<!DOCTYPE html><html><head>
<title>Kun.uz — O'zbekistondagi eng yangi yangiliklar</title>
<meta name="description" content="Kun.uz — O'zbekiston va jahon yangiliklari">
<script>var tracker = "script-matni-tozalanishi-kerak";</script>
<style>body { color: red; }</style>
</head><body>
<nav>Menyu Bosh sahifa Yangiliklar</nav>
<h1>Asosiy sarlavha</h1>
<p>Prezident Toshkentda yig'ilish o'tkazdi. Tafsilotlar kun.uzda.</p>
<p>Ob-havo: bugun +35 gradus issiq bo'lishi kutilmoqda.</p>
</body></html>"""


# ======================================================================
# Mock infratuzilma
# ======================================================================
class _RecBot:
    """Handler chaqiruvlarini yozib boruvchi bot."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self, chat_username=None, get_chat_error=None):
        self.sent = []
        self.actions = []
        self.chat_username = chat_username
        self.get_chat_error = get_chat_error

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"kind": "message", "chat_id": chat_id, "text": text,
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_chat_action(self, chat_id=None, action=None, **kw):
        self.actions.append((chat_id, action))
        return True

    async def get_chat(self, chat_id=None, **kw):
        if self.get_chat_error:
            raise self.get_chat_error
        return SimpleNamespace(id=chat_id, username=self.chat_username,
                               type="channel", title="Test Channel")


def _text_update(uid, text, bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


class _RecordingMsg:
    """query.message — reply_text/delete chaqiruvlarini bot.sent ga yozadi."""

    def __init__(self, real, bot, chat_id):
        self._real = real
        self._bot = bot
        self.chat_id = chat_id

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self._bot.sent.append({"kind": "message", "chat_id": self.chat_id,
                               "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self._bot.sent))

    async def delete(self, **kw):
        return True

    def __getattr__(self, item):
        return getattr(self._real, item)


def _callback_update(uid, data, bot):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="x")
    if bot is not None:
        msg.set_bot(bot)

    class _Query:
        def __init__(self):
            self.data = data
            self.from_user = user
            self.message = _RecordingMsg(msg, bot, uid)

        async def answer(self, *a, **kw):
            return True

    return Update(update_id=1, callback_query=_Query())


class _NullTyping:
    """keep_typing o'rniga — hech narsa qilmaydigan async context manager."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _null_keep_typing(bot, chat_id, **kw):
    return _NullTyping()


class _FakeFetch:
    """utils.channel_reader._fetch_html mock — URL → (status, html, ctype)."""

    def __init__(self, mapping, default=None):
        self.mapping = dict(mapping)
        self.default = default or (200, "<html></html>", "text/html")
        self.calls = []

    async def __call__(self, url):
        self.calls.append(url)
        if url in self.mapping:
            value = self.mapping[url]
            if isinstance(value, Exception):
                raise value
            return value
        return self.default


class _FakeRunDB:
    """database.run_db mock — funksiya nomi bo'yicha natija qaytaradi."""

    def __init__(self, mapping, strict=True):
        self.mapping = dict(mapping)
        self.calls = []
        self.strict = strict

    async def __call__(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name in self.mapping:
            value = self.mapping[name]
            if isinstance(value, Exception):
                raise value
            return value() if callable(value) and not isinstance(value, (list, dict, bool)) else value
        if self.strict:
            raise AssertionError(f"kutilmagan db chaqiruvi: {name}({args})")
        return []


# ======================================================================
# 1. extract_channel_username — barcha formatlar
# ======================================================================
def test_extract_channel_username():
    print("== 1. extract_channel_username — har qanday format ==")
    from utils.channel_reader import extract_channel_username as ex

    cases = [
        ("@kunuzofficial", "kunuzofficial"),
        ("kunuzofficial", "kunuzofficial"),
        ("https://t.me/kunuzofficial", "kunuzofficial"),
        ("http://t.me/kunuzofficial", "kunuzofficial"),
        ("https://t.me/s/kunuzofficial", "kunuzofficial"),
        ("http://t.me/s/kunuzofficial", "kunuzofficial"),
        ("https://t.me/kunuzofficial/173897", "kunuzofficial"),
        ("https://t.me/kunuzofficial/", "kunuzofficial"),
        ("t.me/kunuzofficial", "kunuzofficial"),
        ("https://telegram.me/kunuzofficial", "kunuzofficial"),
        ("https://telegram.dog/kunuzofficial", "kunuzofficial"),
        ("www.t.me/kunuzofficial", "kunuzofficial"),
        ("@KunUz_Official", "KunUz_Official"),
        ("@daryo", "daryo"),
    ]
    for raw, expected in cases:
        check(f"username: {raw} → {expected}", ex(raw) == expected, ex(raw))

    bad = [
        "", None, "ab", "https://kun.uz/", "https://vk.com/kanal",
        "https://t.me/joinchat/AbCdEf123", "https://t.me/+AbCdEf123",
        "https://t.me/c/1234567/89", "salom dunyo", "https://t.me/",
    ]
    for raw in bad:
        check(f"noto'g'ri manba: {raw!r} → None", ex(raw) is None, ex(raw))


# ======================================================================
# 2. Yopiq taklif havolalari
# ======================================================================
def test_is_private_invite():
    print("== 2. is_private_invite — yopiq taklif havolalari ==")
    from utils.channel_reader import is_private_invite as pv

    for raw in ["https://t.me/joinchat/AbCdEf123", "t.me/joinchat/xyz",
                "https://t.me/+AbCdEf123", "t.me/+hash", "https://t.me/c/1234567/89"]:
        check(f"yopiq havola: {raw}", pv(raw) is True, pv(raw))

    for raw in ["@kunuzofficial", "https://t.me/kunuzofficial", "kunuzofficial",
                "https://kun.uz/", None, ""]:
        check(f"ochiq manba: {raw!r}", pv(raw) is False, pv(raw))


# ======================================================================
# 3. Sayt havolasi aniqlash
# ======================================================================
def test_is_website_link():
    print("== 3. is_website_link — sayt aniqlash ==")
    from utils.channel_reader import is_website_link as ws

    for raw in ["https://kun.uz/", "http://kun.uz/", "https://kun.uz/kr/94983135",
                "kun.uz", "www.kun.uz", "https://example.com/sahifa?param=1"]:
        check(f"sayt: {raw}", ws(raw) is True, ws(raw))

    for raw in ["https://t.me/kunuzofficial", "http://t.me/s/kunuzofficial",
                "t.me/kunuzofficial", "@kunuzofficial", "kunuzofficial",
                "https://t.me/joinchat/xyz", "https://t.me/+xyz", None, "",
                "salom dunyo", "12345"]:
        check(f"sayt emas: {raw!r}", ws(raw) is False, ws(raw))


# ======================================================================
# 4. _parse_channel_page — REAL t.me/s/ strukturasi
# ======================================================================
def test_parse_real_tme_html():
    print("== 4. _parse_channel_page — real t.me/s/ HTML ==")
    from utils.channel_reader import _parse_channel_page

    posts = _parse_channel_page(REAL_TME_HTML, "kunuzofficial")
    check("real format: 3 ta post topildi", len(posts) == 3, len(posts))

    if posts:
        first = posts[0]
        check("real: birinchi post matni", "Гофуржон Мирзаев" in first["text"], first["text"][:60])
        check("real: <b> tegi tozalandi", "<b>" not in first["text"])
        check("real: <br> → yangi qator", "\n" in first["text"])
        check("real: sana", first["date"].startswith("2026-09-07T04:14"), first["date"])
        check("real: post_link (data-post)", first["post_link"] == "https://t.me/kunuzofficial/173901",
              first["post_link"])
        check("real: views 238K → 238000", first["views"] == 238000, first["views"])

        second = posts[1]
        check("real: img src → media_url", "photo2.jpg" in second["media_url"], second["media_url"])
        check("real: 2-post views", second["views"] == 219000, second["views"])

        third = posts[2]
        check("real: video fon rasmi (background-image)", "video3.jpg" in third["media_url"],
              third["media_url"])
        check("real: views 1.1M → 1100000", third["views"] == 1100000, third["views"])
        check("real: matnsiz media-post saqlanadi", third["text"] == "" and third["media_url"] != "")

    # Eski (mock) format ham ishlashi kerak — orqaga moslik
    old_mock_html = '''
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message">
            <div class="tgme_widget_message_text">Eski format post matni</div>
            <time datetime="2026-08-30T10:00:00+00:00"></time>
            <a class="tgme_widget_message_date" href="https://t.me/test/123"></a>
        </div>
    </div>
    '''
    old_posts = _parse_channel_page(old_mock_html, "test")
    check("eski format: 1 ta post", len(old_posts) == 1, len(old_posts))
    if old_posts:
        check("eski format: matn", "Eski format" in old_posts[0]["text"])
        check("eski format: link", "test/123" in old_posts[0]["post_link"],
              old_posts[0]["post_link"])

    # Service xabarlari (tgme_widget_message_service) post emas
    service_html = ('<div class="tgme_widget_message_service">'
                    '<div class="service_msg">Kanal yaratildi</div></div>')
    check("service xabar → post emas", _parse_channel_page(service_html, "ch") == [])

    # Bo'sh/noto'g'ri HTML
    check("bo'sh HTML → []", _parse_channel_page("", "ch") == [])
    check("widget yo'q → []",
          _parse_channel_page("<html><body>Channel not found</body></html>", "ch") == [])


# ======================================================================
# 5. read_channel_posts — statuslar bilan
# ======================================================================
def test_read_channel_posts_statuses():
    print("== 5. read_channel_posts — DB → scraping fallback, statuslar ==")
    import utils.channel_reader as cr
    import database as db_mod

    orig_fetch = cr._fetch_html
    orig_run_db = db_mod.run_db

    try:
        # --- 5a) ochiq kanal: to'liq havola orqali scraping ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result = asyncio.run(cr.read_channel_posts("https://t.me/kunuzofficial", limit=5))
        check("ochiq kanal: status ok", result["status"] == "ok", result["status"])
        check("ochiq kanal: 3 ta post", len(result["posts"]) == 3, len(result["posts"]))
        check("ochiq kanal: toza username", result["channel"] == "kunuzofficial", result["channel"])
        # Eng yangisi birinchi (sahifada 173903 oxirida edi)
        if result["posts"]:
            check("ochiq kanal: eng yangisi birinchi",
                  result["posts"][0]["post_link"].endswith("/173903"),
                  result["posts"][0]["post_link"])

        # --- 5b) @nik bilan ham bir xil ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result_b = asyncio.run(cr.read_channel_posts("@kunuzofficial", limit=2))
        check("@nik: status ok", result_b["status"] == "ok", result_b["status"])
        check("@nik: limit=2 ishlaydi", len(result_b["posts"]) == 2, len(result_b["posts"]))

        # --- 5c) DB birinchi: tarix bor bo'lsa scraping ishlamaydi ---
        async def fetch_never(url):
            raise AssertionError("DB bor bo'lsa scraping bo'lmasligi kerak")
        cr._fetch_html = fetch_never
        db_mod.run_db = _FakeRunDB({
            "get_channel_posts_history": [{"text": "DB dan post", "message_id": 7,
                                           "post_date": "2026-09-01", "views": 12}],
        })
        result_c = asyncio.run(cr.read_channel_posts("-1001234567890", limit=5))
        check("DB-first: status ok", result_c["status"] == "ok", result_c["status"])
        check("DB-first: post matni DB dan", result_c["posts"][0]["text"] == "DB dan post",
              result_c["posts"])
        check("DB-first: post_link tuziladi",
              result_c["posts"][0]["post_link"] == "https://t.me/-1001234567890",
              result_c["posts"][0]["post_link"])

        # --- 5d) DB xatosi → scraping fallback ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": RuntimeError("db tushdi")})
        result_d = asyncio.run(cr.read_channel_posts("kunuzofficial", limit=5))
        check("DB xatosi: fallback scraping ishlaydi",
              result_d["status"] == "ok" and len(result_d["posts"]) == 3,
              (result_d["status"], len(result_d["posts"])))

        # --- 5e) yopiq kanal: 200 + tgme_page, widget yo'q ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/privatechannel": (200, PRIVATE_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result_e = asyncio.run(cr.read_channel_posts("privatechannel", limit=5))
        check("yopiq kanal (widget yo'q): status private", result_e["status"] == "private",
              result_e["status"])

        # --- 5e2) mavjud bo'lmagan username: t.me 200 + "you can contact" ---
        notfound_html = """<html><head><title>Telegram: Contact @nochannel</title></head><body>
        <div class="tgme_page_wrap"><div class="tgme_page">
        <div class="tgme_page_extra">If you have Telegram, you can contact <b>@nochannel</b> right away.</div>
        </div></div></body></html>"""
        cr._fetch_html = _FakeFetch({"https://t.me/s/nochannel": (200, notfound_html, "text/html")})
        result_e2 = asyncio.run(cr.read_channel_posts("nochannel", limit=5))
        check("mavjud emas (contact sahifa): status not_found",
              result_e2["status"] == "not_found", result_e2["status"])

        # --- 5f) kanal topilmadi: 404 ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/nosuchchannel12345": (404, "Not Found", "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result_f = asyncio.run(cr.read_channel_posts("nosuchchannel12345", limit=5))
        check("404: status not_found", result_f["status"] == "not_found", result_f["status"])

        # --- 5g) joinchat havolasi → private, tarmoqqa umuman chiqilmaydi ---
        async def fetch_fail(url):
            raise AssertionError("joinchat uchun fetch bo'lmasligi kerak")
        cr._fetch_html = fetch_fail
        result_g = asyncio.run(cr.read_channel_posts("https://t.me/joinchat/AbCdEf123", limit=5))
        check("joinchat: status private", result_g["status"] == "private", result_g["status"])
        result_g2 = asyncio.run(cr.read_channel_posts("https://t.me/+AbCdEf", limit=5))
        check("t.me/+ havolasi: status private", result_g2["status"] == "private", result_g2["status"])

        # --- 5h) raqamli ID, DB bo'sh → private (web-preview mumkin emas) ---
        result_h = asyncio.run(cr.read_channel_posts("-1001234567890", limit=5))
        check("raqamli ID: private (fetch yo'q)", result_h["status"] == "private", result_h["status"])

        # --- 5i) noto'g'ri manba → invalid ---
        result_i = asyncio.run(cr.read_channel_posts("salom dunyo", limit=5))
        check("noto'g'ri manba: invalid", result_i["status"] == "invalid", result_i["status"])
        result_i2 = asyncio.run(cr.read_channel_posts("", limit=5))
        check("bo'sh manba: invalid", result_i2["status"] == "invalid", result_i2["status"])
        result_i3 = asyncio.run(cr.read_channel_posts(None, limit=5))
        check("None manba: invalid", result_i3["status"] == "invalid", result_i3["status"])

        # --- 5j) tarmoq xatosi → error ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": RuntimeError("timeout")})
        result_j = asyncio.run(cr.read_channel_posts("kunuzofficial", limit=5))
        check("tarmoq xatosi: status error", result_j["status"] == "error", result_j["status"])

        # --- 5k) bo'sh kanal: widget bor, post yo'q → empty ---
        empty_html = '<html><div class="tgme_widget_message_wrap js-widget_message"></div></html>'
        cr._fetch_html = _FakeFetch({"https://t.me/s/emptychannel": (200, empty_html, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result_k = asyncio.run(cr.read_channel_posts("emptychannel", limit=5))
        check("bo'sh kanal: status empty", result_k["status"] == "empty", result_k["status"])

        # --- 5l) limit chegarasi (max 10) ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        result_l = asyncio.run(cr.read_channel_posts("kunuzofficial", limit=50))
        check("limit max 10 ga cheklanadi", len(result_l["posts"]) <= 10, len(result_l["posts"]))

        # --- 5m) fetch_latest_channel_posts — orqaga moslik (list qaytaradi) ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        posts_m = asyncio.run(cr.fetch_latest_channel_posts("https://t.me/kunuzofficial", limit=5))
        check("wrapper: ro'yxat qaytaradi", isinstance(posts_m, list) and len(posts_m) == 3,
              type(posts_m))
        check("wrapper: bo'sh niki → []", asyncio.run(cr.fetch_latest_channel_posts("")) == [])
        check("wrapper: None → []", asyncio.run(cr.fetch_latest_channel_posts(None)) == [])
        check("wrapper: joinchat → []",
              asyncio.run(cr.fetch_latest_channel_posts("https://t.me/joinchat/xyz")) == [])
    finally:
        cr._fetch_html = orig_fetch
        db_mod.run_db = orig_run_db


# ======================================================================
# 6. read_webpage_for_ai — sayt o'qish
# ======================================================================
def test_read_webpage_for_ai():
    print("== 6. read_webpage_for_ai — sayt o'qish (AI uchun) ==")
    import utils.channel_reader as cr

    orig_fetch = cr._fetch_html
    try:
        fetcher = _FakeFetch({"https://kun.uz/": (200, KUNUZ_HTML, "text/html; charset=utf-8")})
        cr._fetch_html = fetcher
        page = asyncio.run(cr.read_webpage_for_ai("https://kun.uz/"))
        check("sayt: title o'qildi", "Kun.uz" in page.get("title", ""), page.get("title"))
        check("sayt: meta description o'qildi",
              "yangiliklari" in page.get("description", ""), page.get("description"))
        check("sayt: asosiy matn bor", "yig'ilish" in page.get("text", ""), page.get("text")[:80])
        check("sayt: script matni tozalandi", "tracker" not in page.get("text", ""))
        check("sayt: style matni tozalandi", "color: red" not in page.get("text", ""))
        check("sayt: content (AI uchun) tuzildi", len(page.get("content", "")) > 50)
        check("sayt: title content ichida", "Kun.uz" in page.get("content", ""))
        check("sayt: url saqlandi", page.get("url") == "https://kun.uz/")

        # Protokolsiz domain → https:// qo'shiladi
        fetcher2 = _FakeFetch({"https://kun.uz": (200, KUNUZ_HTML, "text/html")})
        cr._fetch_html = fetcher2
        page2 = asyncio.run(cr.read_webpage_for_ai("kun.uz"))
        check("protokolsiz: https:// qo'shildi", page2.get("url") == "https://kun.uz", page2.get("url"))

        # Matn 1000 belgi bilan cheklanadi
        long_html = "<html><head><title>T</title></head><body>" + ("<p>matn-chunki </p>" * 300) + "</body></html>"
        fetcher3 = _FakeFetch({"https://long.uz/": (200, long_html, "text/html")})
        cr._fetch_html = fetcher3
        page3 = asyncio.run(cr.read_webpage_for_ai("https://long.uz/"))
        check("matn 1000 belgida chegaralanadi", len(page3.get("text", "")) == 1000,
              len(page3.get("text", "")))

        # 404 → error
        cr._fetch_html = _FakeFetch({"https://x.uz/": (404, "Not Found", "text/html")})
        err = asyncio.run(cr.read_webpage_for_ai("https://x.uz/"))
        check("404 → error", "error" in err, err)

        # Tarmoq xatosi → error
        cr._fetch_html = _FakeFetch({"https://down.uz/": RuntimeError("conn refused")})
        err2 = asyncio.run(cr.read_webpage_for_ai("https://down.uz/"))
        check("tarmoq xatosi → error", "error" in err2, err2)

        # Rasm fayli → error (matnli sahifa emas)
        cr._fetch_html = _FakeFetch({"https://img.uz/foto.jpg": (200, "binary", "image/jpeg")})
        err3 = asyncio.run(cr.read_webpage_for_ai("https://img.uz/foto.jpg"))
        check("rasm fayli → error", "error" in err3, err3)

        # Telegram havolasi → sayt emas
        err4 = asyncio.run(cr.read_webpage_for_ai("https://t.me/kunuzofficial"))
        check("telegram havolasi → error", "error" in err4, err4)

        # Noto'g'ri manba → error
        err5 = asyncio.run(cr.read_webpage_for_ai("bu manba emas"))
        check("noto'g'ri manba → error", "error" in err5, err5)
    finally:
        cr._fetch_html = orig_fetch


# ======================================================================
# 7. Handler: kanal o'qish oqimi (link/private/not_found/sayt)
# ======================================================================
def test_extract_username_received_flow():
    print("== 7. extract_username_received — to'liq havola + xabarlar ==")
    import utils.channel_reader as cr
    import database as db_mod
    from handlers import channel_extract as ce
    from handlers.channel_extract import EXTRACT_USERNAME, EXTRACT_CHOOSE_POST

    orig_fetch = cr._fetch_html
    orig_run_db = db_mod.run_db
    orig_typing = ce.keep_typing
    orig_ad = ce.get_auto_ad_injection_async
    import utils.ai_agent as ai_mod
    orig_rewrite = ai_mod.rewrite_channel_post

    try:
        ce.keep_typing = _null_keep_typing

        async def fake_ad(user_id):
            return ""
        ce.get_auto_ad_injection_async = fake_ad

        async def fake_rewrite(original, channel, link, tone="friendly"):
            return {"post_text": f"AI qayta yozdi: {original[:40]}"}
        ai_mod.rewrite_channel_post = fake_rewrite

        # --- 7a) to'liq havola → postlar ro'yxati chiqadi ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        bot = _RecBot()
        upd = _text_update(42, "https://t.me/kunuzofficial", bot=bot)
        state = asyncio.run(ce.extract_username_received(
            upd, SimpleNamespace(bot=bot, user_data={})))
        texts = [s["text"] or "" for s in bot.sent]
        check("7a: EXTRACT_CHOOSE_POST ga o'tdi", state == EXTRACT_CHOOSE_POST, state)
        check("7a: 'o'qilmoqda' indikatori", any("o'qilmoqda" in t for t in texts))
        check("7a: postlar ro'yxati chiqdi",
              any("so'nggi postlar" in t for t in texts), texts)
        check("7a: post matni ko'rinadi",
              any("Гофуржон Мирзаев" in t for t in texts))

        # --- 7b) yopiq taklif havolasi → "Bu yopiq kanal" ---
        async def fetch_fail(url):
            raise AssertionError("private uchun fetch bo'lmasligi kerak")
        cr._fetch_html = fetch_fail
        bot_b = _RecBot()
        upd_b = _text_update(42, "https://t.me/joinchat/AbCdEf123", bot=bot_b)
        state_b = asyncio.run(ce.extract_username_received(
            upd_b, SimpleNamespace(bot=bot_b, user_data={})))
        texts_b = [s["text"] or "" for s in bot_b.sent]
        check("7b: holat EXTRACT_USERNAME da qoldi", state_b == EXTRACT_USERNAME, state_b)
        check("7b: 'Bu yopiq kanal' xabari",
              any("yopiq kanal" in t for t in texts_b), texts_b)
        check("7b: ochiq kanal taklifi",
              any("Ochiq kanallarni" in t for t in texts_b))

        # --- 7c) yopiq kanal (widget yo'q) → "Bu yopiq kanal" ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/privatechannel": (200, PRIVATE_TME_HTML, "text/html")})
        bot_c = _RecBot()
        upd_c = _text_update(42, "@privatechannel", bot=bot_c)
        asyncio.run(ce.extract_username_received(
            upd_c, SimpleNamespace(bot=bot_c, user_data={})))
        texts_c = [s["text"] or "" for s in bot_c.sent]
        check("7c: 'Bu yopiq kanal' xabari",
              any("yopiq kanal" in t for t in texts_c), texts_c)

        # --- 7d) mavjud bo'lmagan kanal → "topilmadi" ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/nosuchchannel12345": (404, "Not Found", "text/html")})
        bot_d = _RecBot()
        upd_d = _text_update(42, "nosuchchannel12345", bot=bot_d)
        asyncio.run(ce.extract_username_received(
            upd_d, SimpleNamespace(bot=bot_d, user_data={})))
        texts_d = [s["text"] or "" for s in bot_d.sent]
        check("7d: 'topilmadi' xabari", any("topilmadi" in t for t in texts_d), texts_d)

        # --- 7e) noto'g'ri manba → haqoratlanmaydi, yo'riqnoma chiqadi ---
        bot_e = _RecBot()
        upd_e = _text_update(42, "salom dunyo", bot=bot_e)
        asyncio.run(ce.extract_username_received(
            upd_e, SimpleNamespace(bot=bot_e, user_data={})))
        texts_e = [s["text"] or "" for s in bot_e.sent]
        check("7e: 'noto'g'ri' yo'riqnomasi", any("Noto'g'ri" in t for t in texts_e), texts_e)

        # --- 7f) SAYT havolasi → sahifa o'qilib AI'ga yetkaziladi ---
        cr._fetch_html = _FakeFetch({"https://kun.uz/": (200, KUNUZ_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({
            "get_user_channels": [],
            "get_channel_tone": "friendly",
            "get_channel_posts_history": [],
        })
        bot_f = _RecBot()
        ctx_f = SimpleNamespace(bot=bot_f, user_data={})
        upd_f = _text_update(42, "https://kun.uz/", bot=bot_f)
        state_f = asyncio.run(ce.extract_username_received(upd_f, ctx_f))
        texts_f = [s["text"] or "" for s in bot_f.sent]
        check("7f: EXTRACT_CHOOSE_POST (AI natijasi bilan)", state_f == EXTRACT_CHOOSE_POST, state_f)
        check("7f: 'Sayt o'qilmoqda' xabari", any("Sayt o'qilmoqda" in t for t in texts_f))
        check("7f: AI tahlili chiqdi", any("AI taklifi" in t for t in texts_f), texts_f)
        check("7f: AI matni ko'rinadi", any("AI qayta yozdi" in t for t in texts_f))
        rewritten_f = ctx_f.user_data.get("extract_rewritten") or ""
        check("7f: user_data ga saqlandi", "AI qayta yozdi" in rewritten_f, rewritten_f[:60])
        check("7f: sayt matni AI ga yetkazildi",
              rewritten_f.startswith("AI qayta yozdi: Kun.uz"), rewritten_f[:60])
        # Sayt natijasi keyboardida 'Boshqa post' tugmasi yo'q
        kb_f = [s.get("reply_markup") for s in bot_f.sent if s.get("reply_markup") is not None]
        has_back = False
        for kb in kb_f:
            for row in getattr(kb, "inline_keyboard", []):
                for b in row:
                    if b.callback_data == "ext_back":
                        has_back = True
        check("7f: sayt natijasida 'Boshqa post' tugmasi yo'q", has_back is False)

        # --- 7g) sayt xatosi → tushunarli xabar, holat saqlanadi ---
        cr._fetch_html = _FakeFetch({"https://down.uz/": RuntimeError("conn refused")})
        bot_g = _RecBot()
        upd_g = _text_update(42, "https://down.uz/", bot=bot_g)
        state_g = asyncio.run(ce.extract_username_received(
            upd_g, SimpleNamespace(bot=bot_g, user_data={})))
        texts_g = [s["text"] or "" for s in bot_g.sent]
        check("7g: sayt xatosi xabari", any("ulanib bo'lmadi" in t for t in texts_g), texts_g)
        check("7g: holat EXTRACT_USERNAME da", state_g == EXTRACT_USERNAME, state_g)
    finally:
        cr._fetch_html = orig_fetch
        db_mod.run_db = orig_run_db
        ce.keep_typing = orig_typing
        ce.get_auto_ad_injection_async = orig_ad
        ai_mod.rewrite_channel_post = orig_rewrite


# ======================================================================
# 8. Kanal ovozi tahlili — web-preview fallback
# ======================================================================
def test_channel_voice_fallback():
    print("== 8. Kanal ovozi tahlili — DB bo'sh → t.me/s/ fallback ==")
    import utils.channel_reader as cr
    import database as db_mod
    import handlers.channels as ch_mod
    from handlers.channels import _fetch_public_posts_fallback, channel_voice_analysis_callback

    orig_fetch = cr._fetch_html
    orig_run_db = db_mod.run_db
    orig_analyze = ch_mod.analyze_channel_voice

    try:
        # --- 8a) fallback: bot.get_chat → username → scraping ---
        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({"get_channel_posts_history": []})
        bot = _RecBot(chat_username="kunuzofficial")
        posts = asyncio.run(_fetch_public_posts_fallback(
            SimpleNamespace(bot=bot), "-1001234567890"))
        check("8a: fallback postlar qaytardi", len(posts) == 3, len(posts))

        # --- 8b) get_chat xatosi → bo'sh (jim) ---
        from telegram.error import TelegramError
        bot_b = _RecBot(get_chat_error=TelegramError("chat topilmadi"))
        posts_b = asyncio.run(_fetch_public_posts_fallback(
            SimpleNamespace(bot=bot_b), "-1001234567890"))
        check("8b: get_chat xatosi → []", posts_b == [], posts_b)

        # --- 8c) public username yo'q (yopiq kanal) → [] ---
        bot_c = _RecBot(chat_username=None)
        posts_c = asyncio.run(_fetch_public_posts_fallback(
            SimpleNamespace(bot=bot_c), "-1001234567890"))
        check("8c: username yo'q → []", posts_c == [], posts_c)

        # --- 8d) context.bot yo'q → [] ---
        posts_d = asyncio.run(_fetch_public_posts_fallback(SimpleNamespace(), "-100123"))
        check("8d: bot yo'q → []", posts_d == [], posts_d)

        # --- 8e) to'liq ovoz tahlili: DB tarixi BO'SH, fallback ishlaydi ---
        analyze_seen = []

        async def fake_analyze(posts, lang="uz"):
            analyze_seen.append(len(posts))
            return {"tone": "concise", "reason": "Yangiliklar uslubi."}
        ch_mod.analyze_channel_voice = fake_analyze

        cr._fetch_html = _FakeFetch({"https://t.me/s/kunuzofficial": (200, REAL_TME_HTML, "text/html")})
        db_mod.run_db = _FakeRunDB({
            "get_user_channels_with_tone": [("-1001234567890", "Mening Kanalim", "friendly")],
            "get_channel_posts_history": [],  # DB tarixi BO'SH
            "set_channel_tone": True,
        })
        bot_e = _RecBot(chat_username="kunuzofficial")
        upd_e = _callback_update(42, "ch_voice:-1001234567890", bot=bot_e)
        state_e = asyncio.run(channel_voice_analysis_callback(
            upd_e, SimpleNamespace(application=None, bot=bot_e, user_data={"lang": "uz"})))
        check("8e: AI postlar oldi (fallback dan, 3 ta)",
              analyze_seen == [3], analyze_seen)
        set_calls = [a for name, a in db_mod.run_db.calls if name == "set_channel_tone"]
        check("8e: tone saqlandi (concise)", set_calls == [("-1001234567890", "concise")],
              set_calls)
        check("8e: handler END", state_e == ConversationHandler.END, state_e)
        replies_e = [s["text"] or "" for s in bot_e.sent]
        check("8e: natija xabari chiqdi",
              any("Kanal ovozi tahlili natijasi" in t for t in replies_e), replies_e[:3])

        # --- 8f) DB tarixi BOR bo'lsa fallback ishlamaydi ---
        async def fetch_fail(url):
            raise AssertionError("DB bor bo'lsa scraping bo'lmasligi kerak")
        cr._fetch_html = fetch_fail
        db_mod.run_db = _FakeRunDB({
            "get_user_channels_with_tone": [("-1001234567890", "Mening Kanalim", "friendly")],
            "get_channel_posts_history": [{"text": "DB dan post matni"}],
            "set_channel_tone": True,
        })
        bot_f = _RecBot()
        upd_f = _callback_update(42, "ch_voice:-1001234567890", bot=bot_f)
        asyncio.run(channel_voice_analysis_callback(
            upd_f, SimpleNamespace(application=None, bot=bot_f, user_data={"lang": "uz"})))
        check("8f: DB tarixi bor — fallback ishlamadi (fetch chaqirilmadi)", True)
    finally:
        cr._fetch_html = orig_fetch
        db_mod.run_db = orig_run_db
        ch_mod.analyze_channel_voice = orig_analyze


# ======================================================================
# 9. Kod-integratsiya (regression) tekshiruvlari
# ======================================================================
def test_source_integration():
    print("== 9. Kod-integratsiya regression tekshiruvlari ==")
    root = Path(__file__).resolve().parent.parent
    cr_src = (root / "utils" / "channel_reader.py").read_text(encoding="utf-8")
    ce_src = (root / "handlers" / "channel_extract.py").read_text(encoding="utf-8")
    ch_src = (root / "handlers" / "channels.py").read_text(encoding="utf-8")

    check("channel_reader: DB-first saqlanadi (get_channel_posts_history)",
          "get_channel_posts_history" in cr_src)
    check("channel_reader: t.me/s/ scraping bor", "https://t.me/s/" in cr_src)
    check("channel_reader: real wrap strukturasini o'qiydi",
          "tgme_widget_message_wrap" in cr_src)
    check("channel_reader: read_webpage_for_ai bor", "read_webpage_for_ai" in cr_src)
    check("channel_reader: meta description o'qiladi", "description" in cr_src)

    check("channel_extract: read_channel_posts ishlatiladi", "read_channel_posts" in ce_src)
    # i18n: matnlar locales/translations.py dagi kalitlardan olinadi —
    # handler kalitni ishlatishi VA uz qiymatda matn saqlanishi shart.
    from locales.translations import TRANSLATIONS as _TR
    check("channel_extract: 'Bu yopiq kanal' xabari bor",
          "ext_private_channel_full" in ce_src
          and "Bu yopiq kanal" in _TR["uz"]["ext_private_channel_full"])
    check("channel_extract: sayt havolasi qo'llab-quvvatlanadi",
          "is_website_link" in ce_src and "read_webpage_for_ai" in ce_src)
    check("channel_extract: to'liq havola promptda ko'rsatiladi",
          "ext_intro" in ce_src
          and "https://t.me/kunuzofficial" in _TR["uz"]["ext_intro"])

    check("channels: ovoz tahlilida web-preview fallback bor",
          "_fetch_public_posts_fallback" in ch_src and "read_channel_posts" in ch_src)


# ======================================================================
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    failed = [c for c in CHECKS if not c[0]]
    print(f"\nChannel-reader (web-preview) testlari: {len(CHECKS) - len(failed)} passed, "
          f"{len(failed)} failed")
    if failed:
        for _, msg, detail in failed:
            print(f"  [FAIL] {msg} {detail}")
        sys.exit(1)
    print("BARCHASI OK ✔")
