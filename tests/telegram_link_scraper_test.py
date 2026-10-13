"""🔗 «HAVODAN POST» — t.me post havolasini o'qish: matn, media, zaxira va timeout.

DIQQAT: real t.me'ga ulanilmaydi — HTML namunalar Telegram veb-vidjeti
(``tgme_widget_message_*``) tuzilishiga qarab yozilgan fixture'lar.

Qamrov:
  * havola shakllari (/s/, ?query, www, telegram.me, yopiq /c/);
  * aynan kerakli postni tanlash, reply-iqtibosni o'tkazib yuborish;
  * rasm/video ajratish, faqat-media post;
  * preview → embed zaxirasi, 404/timeout, umumiy 15 s chegara;
  * handler: AI javob bermasa ham matn yo'qolmaydi (AI'siz qoralama),
    aniq xato xabarlari, umumiy deadline.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/telegram_link_scraper_test.py
"""
import asyncio
import os
import socket
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:SCRAPER_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from handlers import sources as src  # noqa: E402
from services.sources import url_extractor as ux  # noqa: E402

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ====================================================================== FIXTURE HTML
def wrap(channel, pid, inner):
    return (f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
            f'<div class="tgme_widget_message text_not_supported_wrap js-widget_message" '
            f'data-post="{channel}/{pid}" data-view="x">{inner}</div></div>')


TEXT_POST = wrap("jizzax_ch", 123, (
    '<div class="tgme_widget_message_text js-message_text" dir="auto">'
    '<b>Muhim yangilik</b><br/>Bugun shahar markazida yangi bog\' ochildi. '
    '<a href="https://t.me/x">Batafsil</a> &amp; rasmlar</div>'))

REPLY_POST = wrap("jizzax_ch", 124, (
    '<a class="tgme_widget_message_reply" href="https://t.me/jizzax_ch/123">'
    '<div class="tgme_widget_message_author_name">Jizzax</div>'
    '<div class="tgme_widget_message_text js-message_reply_text">IQTIBOS: eski post matni shu yerda</div></a>'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">'
    'Haqiqiy javob matni: ertaga ham ochiq bo\'ladi.</div>'))

PHOTO_POST = wrap("jizzax_ch", 125, (
    '<a class="tgme_widget_message_photo_wrap 5 1" href="https://t.me/jizzax_ch/125" '
    'style="width:453px;background-image:url(\'https://cdn4.telesco.pe/file/abc.jpg?x=1&amp;y=2\')">'
    '<div class="tgme_widget_message_photo"></div></a>'
    '<a class="tgme_widget_message_photo_wrap 5 2" href="https://t.me/jizzax_ch/125" '
    'style="background-image:url(\'https://cdn4.telesco.pe/file/def.jpg\')"></a>'
    '<div class="tgme_widget_message_text js-message_text before_footer" dir="auto">'
    'Rasmli post: bog\' ochilishidan lavhalar.</div>'))

MEDIA_ONLY = wrap("jizzax_ch", 126, (
    '<a class="tgme_widget_message_photo_wrap 5 1" '
    'style="background-image:url(\'https://cdn4.telesco.pe/file/only.jpg\')"></a>'))

VIDEO_POST = wrap("jizzax_ch", 127, (
    '<div class="tgme_widget_message_video_player"><video src="https://cdn4.telesco.pe/file/v.mp4" '
    'class="tgme_widget_message_video"></video></div>'
    '<div class="tgme_widget_message_text js-message_text">Video post uchun yetarli matn bor.</div>'))

OTHER_CHANNEL = wrap("boshqa_kanal", 123, (
    '<div class="tgme_widget_message_text js-message_text">BOSHQA KANAL POSTI — olinmasligi kerak.</div>'))


def page(*blocks, title="Jizzax Yangiliklari"):
    return (f'<html><head><meta property="og:title" content="{title}"></head><body>'
            + "".join(blocks) + "</body></html>")


PREVIEW = page(TEXT_POST, REPLY_POST, PHOTO_POST, MEDIA_ONLY, VIDEO_POST, OTHER_CHANNEL)

print("== havola shakllari ==")
for raw, want in (
    ("https://t.me/jizzax_ch/123", ("jizzax_ch", 123)),
    ("t.me/jizzax_ch/123", ("jizzax_ch", 123)),
    ("https://t.me/jizzax_ch/123/", ("jizzax_ch", 123)),
    ("https://t.me/jizzax_ch/123?single", ("jizzax_ch", 123)),
    ("https://t.me/jizzax_ch/123?comment=5", ("jizzax_ch", 123)),
    ("https://t.me/s/jizzax_ch/123", ("jizzax_ch", 123)),
    ("https://www.t.me/jizzax_ch/123", ("jizzax_ch", 123)),
    ("https://telegram.me/jizzax_ch/123", ("jizzax_ch", 123)),
    ("http://t.me/Jizzax_Ch/9", ("Jizzax_Ch", 9)),
):
    tg = ux.parse_telegram_url(ux.normalize_input_url(raw))
    check(f"post havolasi: {raw}", tg.get("is_post") and (tg["channel"], tg["post_id"]) == want, str(tg))
tg = ux.parse_telegram_url("https://t.me/jizzax_ch")
check("kanal havolasi (post yo'q) → channel_only", tg.get("is_channel_only") and not tg.get("is_post"))
tg = ux.parse_telegram_url("https://t.me/c/1234567890/55")
check("yopiq kanal posti (/c/...) aniqlanadi", tg.get("is_private") and not tg.get("is_post")
      and not tg.get("is_channel_only"), str(tg))
check("telegram bo'lmagan sayt", ux.parse_telegram_url("https://example.com/a/1") == {"is_telegram": False})

print("== postni ajratish ==")
r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 123)
check("kerakli post tanlandi", r["ok"] and "Muhim yangilik" in r["text"], str(r))
check("<br> → yangi qator, teg olib tashlandi, &amp; → &",
      "\n" in r["text"] and "<" not in r["text"] and "& rasmlar" in r["text"], r["text"])
check("sarlavha og:title dan", r["title"] == "Jizzax Yangiliklari", r["title"])
check("boshqa kanalning bir xil ID'li posti aralashmaydi", "BOSHQA KANAL" not in r["text"])

r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 124)
check("reply post: asosiy matn olinadi", r["ok"] and r["text"].startswith("Haqiqiy javob"), str(r))
check("reply post: iqtibos matni ASOSIY matn bo'lib ketmaydi", "IQTIBOS" not in r["text"], r["text"])

r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 125)
check("rasmli post: matn + 2 ta rasm", r["ok"] and len(r["media"]) == 2, str(r))
check("rasm havolasi &amp; dan tozalangan, https",
      r["media"][0] == {"type": "photo", "url": "https://cdn4.telesco.pe/file/abc.jpg?x=1&y=2"}, str(r["media"]))

r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 126)
check("faqat-media post: matn yo'q (ok=False), lekin media topildi",
      not r["ok"] and r["error_code"] == ux.ERR_EMPTY_CONTENT and len(r["media"]) == 1, str(r))

r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 127)
check("video post: video havolasi ajratildi",
      r["ok"] and r["media"] == [{"type": "video", "url": "https://cdn4.telesco.pe/file/v.mp4"}], str(r))

r = ux.extract_telegram_post_from_html(PREVIEW, "jizzax_ch", 999)
check("mavjud bo'lmagan post: empty_content", not r["ok"] and r["error_code"] == ux.ERR_EMPTY_CONTENT)
check("bo'sh HTML: istisnosiz", ux.extract_telegram_post_from_html("", "a_chan", 1)["ok"] is False)
check("buzilgan HTML: istisnosiz",
      ux.extract_telegram_post_from_html('<div data-post="jizzax_ch/123"><div class="tgme_widget_message_text', "jizzax_ch", 123)["ok"] is False)
check("xavfsizlik: <script> tegi matnda qolmaydi",
      "<script" not in (ux.extract_telegram_post_from_html(
          page(wrap("jizzax_ch", 5, '<div class="tgme_widget_message_text js-message_text">'
                    'Oddiy matn bor <script>x()</script> davomi</div>')), "jizzax_ch", 5).get("text") or ""))


# ====================================================================== FAKE TARMOQ
PUBLIC_IP = lambda host, port=80: ["149.154.167.99"]  # noqa: E731


class FakeResponse:
    def __init__(self, body, status=200, ctype="text/html; charset=utf-8"):
        self._b, self.status = body.encode("utf-8"), status
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(self._b))}
        self._pos = 0

    def read(self, n=-1):
        chunk = self._b[self._pos:self._pos + n] if n and n > 0 else self._b[self._pos:]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass


class FakeClient:
    """URL → javob (str body | Exception | callable). Chaqiruvlar yozib boriladi."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def open(self, request, timeout=None):
        url = request.full_url
        self.calls.append((url, timeout))
        for prefix, result in self.routes.items():
            if url.startswith(prefix):
                value = result() if callable(result) else result
                if isinstance(value, BaseException):
                    raise value
                return FakeResponse(value) if isinstance(value, str) else value
        raise OSError("marshrut yo'q: " + url)


def fetch(url, routes, **kw):
    client = FakeClient(routes)
    out = ux.fetch_and_extract(url, client=client, resolver=PUBLIC_IP, **kw)
    return out, client


print("== o'qish: preview → embed zaxirasi ==")
out, cl = fetch("t.me/jizzax_ch/123", {"https://t.me/s/jizzax_ch/123": PREVIEW})
art = out.get("article") or {}
check("preview'dan o'qildi", out["ok"] and art.get("via") == "preview" and "Muhim yangilik" in art["text"], str(out)[:300])
check("faqat 1 ta so'rov yuborildi", len(cl.calls) == 1, str(cl.calls))
check("manba havolasi to'liq (https://)", art.get("source_url") == "https://t.me/jizzax_ch/123", str(art.get("source_url")))
check("kanal manbasi", art.get("source") == "jizzax_ch")
check("media maydoni bor (ro'yxat)", isinstance(art.get("media"), list))

out, cl = fetch("https://t.me/jizzax_ch/125", {"https://t.me/s/jizzax_ch/125": PREVIEW})
check("rasmli post: media article'ga kiradi",
      out["ok"] and len(out["article"]["media"]) == 2, str(out)[:200])

EMBED = page(TEXT_POST)
no_post = page(OTHER_CHANNEL)   # preview boshqa post ko'rsatadi
out, cl = fetch("https://t.me/jizzax_ch/123", {
    "https://t.me/s/jizzax_ch/123": no_post,
    "https://t.me/jizzax_ch/123?embed=1": EMBED,
})
check("preview postni bermasa — embed zaxirasi ishlaydi",
      out["ok"] and out["article"]["via"] == "embed", str(out)[:300])
check("ikkala manzil ham so'raldi (preview → embed)",
      [c[0].split("?")[0] for c in cl.calls] == ["https://t.me/s/jizzax_ch/123", "https://t.me/jizzax_ch/123"], str(cl.calls))
check("embed manzili embed=1 bilan", "embed=1" in cl.calls[1][0])

out, cl = fetch("https://t.me/jizzax_ch/123", {
    "https://t.me/s/jizzax_ch/123": OSError("tarmoq uzildi"),
    "https://t.me/jizzax_ch/123?embed=1": EMBED,
})
check("preview tarmoq xatosi — embed bilan davom etadi", out["ok"] and out["article"]["via"] == "embed", str(out)[:200])

print("== o'qish: xatolar ==")
out, _ = fetch("https://t.me/jizzax_ch/126", {"https://t.me/s/jizzax_ch/126": PREVIEW,
                                              "https://t.me/jizzax_ch/126?embed=1": page(MEDIA_ONLY)})
check("faqat-media post: aniq 'matn yo'q' xatosi (crash yo'q)",
      not out["ok"] and out["error_code"] == ux.ERR_EMPTY_CONTENT, str(out)[:200])
check("faqat-media post: media qaytariladi", len(out.get("media") or []) == 1, str(out.get("media")))

out, _ = fetch("https://t.me/jizzax_ch/321", {"https://t.me/s/jizzax_ch/321": PREVIEW,
                                              "https://t.me/jizzax_ch/321?embed=1": PREVIEW})
check("post topilmasa: empty_content", not out["ok"] and out["error_code"] == ux.ERR_EMPTY_CONTENT)

out, _ = fetch("https://t.me/jizzax_ch/123", {"https://t.me/": socket.timeout("timed out")})
check("ikkala urinish timeout: error_code=timeout", not out["ok"] and out["error_code"] == ux.ERR_TIMEOUT, str(out)[:200])
check("timeout xabari foydalanuvchi tilida", "javob bermadi" in out["message"], out["message"])

out, _ = fetch("https://t.me/jizzax_ch/123", {"https://t.me/": OSError("ulanib bo'lmadi")})
check("tarmoq xatosi: network_error (istisnosiz)", not out["ok"] and out["error_code"] == ux.ERR_NETWORK, str(out)[:200])

out, _ = fetch("https://t.me/c/1234567890/5", {})
check("yopiq kanal posti: aniq xabar, tarmoqqa chiqilmaydi",
      not out["ok"] and out["error_code"] == ux.ERR_TELEGRAM_PRIVATE and "yopiq" in out["message"], str(out)[:200])
out, _ = fetch("https://t.me/jizzax_ch", {})
check("faqat kanal havolasi: channel_only", out["error_code"] == ux.ERR_TELEGRAM_CHANNEL_ONLY)
out, _ = fetch("https://t.me/jizzax_ch/123", {"https://t.me/s/jizzax_ch/123": PREVIEW}, lang="ru")
check("ru: muvaffaqiyat (til parametri xato bermaydi)", out["ok"])

print("== vaqt chegarasi: umumiy 15 s ==")
check("umumiy chegara 15 soniya", ux.TELEGRAM_TOTAL_TIMEOUT_SECONDS == 15.0)
out, cl = fetch("https://t.me/jizzax_ch/123", {"https://t.me/": socket.timeout("t")})
check("har bir so'rovga timeout uzatiladi va 15 s dan oshmaydi",
      cl.calls and all(0 < (c[1] or 0) <= 15.0 for c in cl.calls), str(cl.calls))

clock = {"t": 1000.0}
real_monotonic = ux.time.monotonic


def fake_monotonic():
    return clock["t"]


slow_calls = []


def slow_open():
    clock["t"] += 12.0     # birinchi urinish 12 s oladi → zaxira uchun 3 s qoladi
    return socket.timeout("slow")


ux.time.monotonic = fake_monotonic
try:
    client = FakeClient({"https://t.me/s/": slow_open, "https://t.me/jizzax_ch/123?embed=1": EMBED})
    out = ux.fetch_and_extract("https://t.me/jizzax_ch/123", client=client, resolver=PUBLIC_IP)
    check("zaxira so'rovi qolgan vaqt bilan cheklanadi (≤3 s) va muvaffaqiyatli",
          out["ok"] and client.calls[1][1] is not None and client.calls[1][1] <= 3.0 + 1e-6, str(client.calls))
    clock["t"] = 2000.0

    def very_slow():
        clock["t"] += 14.5
        return socket.timeout("slow")

    client = FakeClient({"https://t.me/": very_slow})
    out = ux.fetch_and_extract("https://t.me/jizzax_ch/123", client=client, resolver=PUBLIC_IP)
    check("15 s tugagach keyingi urinish BOSHLANMAYDI (jami 1 so'rov)", len(client.calls) == 1, str(client.calls))
    check("chegara tugadi: timeout kodi", out["error_code"] == ux.ERR_TIMEOUT, str(out)[:200])
finally:
    ux.time.monotonic = real_monotonic


# ====================================================================== HANDLER
print("== handler: AI javob bermasa ham matn yo'qolmaydi ==")


class Msg:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append({"text": text, "markup": reply_markup})
        return self


def make_ctx():
    return SimpleNamespace(user_data={src.UD_CHANNEL: "@jizzax_ch", src.UD_TITLE: "Jizzax", "lang": "uz"})


def make_update(msg):
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=777))


ARTICLE = {"title": "Muhim yangilik", "text": "Bugun shahar markazida yangi bog' ochildi va hamma kela oladi.",
           "source": "jizzax_ch", "source_url": "https://t.me/jizzax_ch/123", "media": []}


class FakeService:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def build_drafts(self, url, **kw):
        self.calls += 1
        return self.result


async def drive(loaded, service_result, text="https://t.me/jizzax_ch/123", fetch_delay=0.0, deadline=None):
    msg, ctx = Msg(text), make_ctx()
    orig = (src.validate_public_url, src.fetch_article_safe, src.new_url_service, src._dna_block,
            src.URL_FETCH_DEADLINE_SECONDS)

    def fake_fetch(url, lang="uz"):
        if fetch_delay:
            time.sleep(fetch_delay)
        return loaded

    async def no_dna(*a, **k):
        return ""

    service = FakeService(service_result)
    src.validate_public_url = lambda raw: {"ok": True, "url": raw}
    src.fetch_article_safe = fake_fetch
    src.new_url_service = lambda: service
    src._dna_block = no_dna
    if deadline is not None:
        src.URL_FETCH_DEADLINE_SECONDS = deadline
    try:
        state = await src.url_text_received(make_update(msg), ctx)
    finally:
        (src.validate_public_url, src.fetch_article_safe, src.new_url_service, src._dna_block,
         src.URL_FETCH_DEADLINE_SECONDS) = orig
    return state, msg, ctx, service


OK_LOADED = {"ok": True, "article": dict(ARTICLE), "injection_signals": []}
AI_OK = {"ok": True, "drafts": [{"format": "news", "label": "Yangilik", "text": "AI matn", "ai": True}]}

state, msg, ctx, svc = asyncio.run(drive(OK_LOADED, AI_OK))
check("AI ishlasa: formatlar tanlovi", state == src.SRC_URL_FORMATS and svc.calls == 1)

state, msg, ctx, svc = asyncio.run(drive(OK_LOADED, {"ok": False, "error_code": ux.ERR_AI_FAILED, "drafts": []}))
texts = [r["text"] for r in msg.replies]
check("AI javob bermasa: formatlar tanlovi baribir chiqadi", state == src.SRC_URL_FORMATS, str(state))
check("AI javob bermasa: «AI javob bera olmadi» xatosi bilan TO'XTAMAYDI",
      state != src.SRC_URL_INPUT)
check("AI javob bermasa: foydalanuvchiga sababi tushuntiriladi (kredit yechilmagan)",
      any("kredit yechilmadi" in t for t in texts), str(texts))
drafts = ctx.user_data.get(src.UD_DRAFTS) or []
check("mahalliy qoralamalar: 4 format, ai=False", len(drafts) == 4 and not any(d["ai"] for d in drafts), str(drafts)[:200])
check("mahalliy qoralama manba matni va havolasini saqlaydi",
      any("t.me/jizzax_ch/123" in d["text"] for d in drafts) and any("bog'" in d["text"] for d in drafts))
check("maqola user_data'da saqlangan", ctx.user_data.get(src.UD_ARTICLE, {}).get("source") == "jizzax_ch")
kb = next((r["markup"] for r in msg.replies if r["markup"] is not None and hasattr(r["markup"], "inline_keyboard")), None)
check("format tugmalari chiqdi", kb is not None and len([b for row in kb.inline_keyboard for b in row]) >= 4)

state, msg, ctx, svc = asyncio.run(drive(OK_LOADED, {"ok": False, "error_code": "quota_denied", "drafts": []}))
check("AI limiti tugagan: aniq limit xabari, qoralama berilmaydi",
      state == src.SRC_URL_INPUT and any("limit" in r["text"].lower() for r in msg.replies)
      and not ctx.user_data.get(src.UD_DRAFTS), str([r["text"] for r in msg.replies]))

for code, needle in ((ux.ERR_TIMEOUT, "javob bermadi"), (ux.ERR_TELEGRAM_PRIVATE, "yopiq"),
                     (ux.ERR_EMPTY_CONTENT, "matn topilmadi"), (ux.ERR_TELEGRAM_CHANNEL_ONLY, "post havolasini")):
    state, msg, ctx, svc = asyncio.run(drive({"ok": False, "error_code": code}, AI_OK))
    check(f"{code}: aniq xabar, AI chaqirilmaydi",
          state == src.SRC_URL_INPUT and svc.calls == 0 and any(needle in r["text"] for r in msg.replies),
          str([r["text"] for r in msg.replies]))

state, msg, ctx, svc = asyncio.run(drive({"ok": False, "error_code": "network_error"}, AI_OK))
check("boshqa xato: umumiy xabar (oldingi xulq saqlangan)",
      state == src.SRC_URL_INPUT and svc.calls == 0 and msg.replies)

t0 = time.monotonic()
state, msg, ctx, svc = asyncio.run(drive(OK_LOADED, AI_OK, fetch_delay=0.6, deadline=0.2))
elapsed = time.monotonic() - t0
check("umumiy deadline: osilib qolgan o'qish foydalanuvchini kutdirmaydi (timeout xabari)",
      state == src.SRC_URL_INPUT and any("javob bermadi" in r["text"] for r in msg.replies) and svc.calls == 0,
      str([r["text"] for r in msg.replies]))
check("deadline: handler 0.2 s chegarada qaytdi (thread tugashi kutilmaydi)", elapsed < 1.5, f"{elapsed:.2f}")
check("deadline konstantasi t.me chegarasidan katta",
      src.URL_FETCH_DEADLINE_SECONDS > ux.TELEGRAM_TOTAL_TIMEOUT_SECONDS)

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
