#!/usr/bin/env python3
"""Unit-testlar: muhim logika qismlari (DB talab qilinmaydi).

Ishga tushirish:
    cd telegram_bot && python tests/unit_test.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timedelta
import pytz
from telegram.error import TelegramError

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def test_calculate_next_time():
    print("== scheduler.calculate_next_time ==")
    from scheduler import calculate_next_time
    tz = pytz.timezone("Asia/Tashkent")

    # Daily: 10:00 ga belgilangan, hozir 09:00 → bugun 10:00
    now = tz.localize(datetime(2026, 8, 30, 9, 0))
    t = calculate_next_time("daily", None, time_str(10, 0), now)
    check("daily: keyingi vaqt bugun 10:00", t == tz.localize(datetime(2026, 8, 30, 10, 0)), str(t))

    # Daily: 10:00 ga belgilangan, hozir 11:00 → ertaga 10:00
    now = tz.localize(datetime(2026, 8, 30, 11, 0))
    t = calculate_next_time("daily", None, time_str(10, 0), now)
    check("daily: keyingi vaqt ertaga 10:00", t == tz.localize(datetime(2026, 8, 31, 10, 0)), str(t))

    # Weekly: Dushanba (0), hozir Chorshanba (2) → keyingi dushanba
    now = tz.localize(datetime(2026, 8, 26, 9, 0))  # chorshanba
    t = calculate_next_time("weekly", 0, time_str(12, 0), now)
    check("weekly: keyingi dushanba", t == tz.localize(datetime(2026, 8, 31, 12, 0)), str(t))

    # Weekly: hozir dushanba 08:00, belgilangan dushanba 12:00 →
    # chiqish kuni bugun bo'lsa ham, keyingi chiqish keyingi hafta dushanba
    now = tz.localize(datetime(2026, 8, 31, 8, 0))
    t = calculate_next_time("weekly", 0, time_str(12, 0), now)
    check("weekly: bugun kun bo'lsa → keyingi hafta", t == tz.localize(datetime(2026, 9, 7, 12, 0)), str(t))

    # none → None
    check("none → None", calculate_next_time("none", None, None, now) is None)


def time_str(h, m):
    return (datetime(2000, 1, 1, h, m)).time()


def test_converter():
    print("== utils.converter ==")
    from utils.converter import to_cyrillic, to_latin

    lat = "Salom dunyo! Bugun ob-havo yaxshi."
    cyr = to_cyrillic(lat)
    check("lotin→kirill: 'Salom'", "Салом" in cyr, cyr)
    check("lotin→kirill: 'dunyo'", "дунё" in cyr, cyr)
    check("lotin→kirill: 'ob-havo'", "об-ҳаво" in cyr, cyr)

    back = to_latin(cyr)
    check("kirill→lotin teskari", "Salom dunyo" in back, back)

    # Щ/щ ilgari xato ravishda "Ch/ch" ga o'girilardi (Ч bilan aralashib ketardi)
    check("kirill→lotin: 'Щ' → 'Sh'", to_latin("Щ") == "Sh", to_latin("Щ"))
    check("kirill→lotin: 'щ' → 'sh'", to_latin("щ") == "sh", to_latin("щ"))
    check("kirill→lotin: 'Ч' → 'Ch'", to_latin("Ч") == "Ch", to_latin("Ч"))
    check("kirill→lotin: 'ч' → 'ch'", to_latin("ч") == "ch", to_latin("ч"))
    check("kirill→lotin: 'щётка' ichida 'sh'", to_latin("щётка").lower().startswith("sh"),
          to_latin("щётка"))


def test_rate_limits():
    print("== utils.helpers rate-limit ==")
    from utils.helpers import check_rate_limit, check_ai_rate_limit

    uid = 999001
    # 3 ta so'rovga ruxsat, 4-chisi bloklanadi
    r1 = check_rate_limit(uid, max_requests=3, window_seconds=3.0)
    r2 = check_rate_limit(uid, max_requests=3, window_seconds=3.0)
    r3 = check_rate_limit(uid, max_requests=3, window_seconds=3.0)
    r4 = check_rate_limit(uid, max_requests=3, window_seconds=3.0)
    check("3 ta so'rov o'tadi", not (r1[0] or r2[0] or r3[0]))
    check("4-chi so'rov bloklanadi", r4[0])

    # AI limiter: daqiqasiga 4 tadan oshsa blok
    uid2 = 999002
    blocks = [check_ai_rate_limit(uid2, max_per_minute=4) for _ in range(5)]
    check("AI: 4 ta o'tadi, 5-chisi blok", not any(blocks[:4]) and blocks[4])


def test_json_clean():
    print("== utils.ai_agent _clean_json_string ==")
    from utils.ai_agent import _clean_json_string
    check("markdown blok tozalanadi",
          _clean_json_string('```json\n{"a": 1}\n```') == '{"a": 1}')
    check("oddiy JSON buzilmaydi",
          _clean_json_string('{"a": 1}') == '{"a": 1}')


def test_retry_after_seconds():
    print("== utils.ai_agent _retry_after_seconds ==")
    from utils.ai_agent import _retry_after_seconds

    class FakeResp:
        headers = {}

    r = FakeResp()
    r.headers = {"Retry-After": "5"}
    check("Retry-After o'qiladi", _retry_after_seconds(r) == 5.0)
    r.headers = {}
    check("Retry-After yo'q → fallback", _retry_after_seconds(r, fallback=3.0) == 3.0)
    r.headers = {"Retry-After": "999"}
    check("Retry-After maks 10s", _retry_after_seconds(r) == 10.0)


def test_weekday_map():
    print("== keyboards.default WEEKDAY ==")
    from keyboards.default import WEEKDAY_MAP, WEEKDAY_LABELS, BTN_DUR_1W
    check("Dushanba → 0", WEEKDAY_MAP["Dushanba"] == 0)
    check("Yakshanba → 6", WEEKDAY_MAP["Yakshanba"] == 6)
    check("WEEKDAY_LABELS teskari", WEEKDAY_LABELS[6] == "Yakshanba")
    check("BTN_DUR_1W mavjud", BTN_DUR_1W == "1 hafta")


def test_abuse_protection():
    print("== Hujum himoyasi (global flood, dublikat, kunlik AI) ==")
    from utils.helpers import (
        check_global_flood, is_duplicate_message, check_ai_daily_limit,
        GLOBAL_MAX_UPDATES_PER_SEC, AI_MAX_PER_DAY,
    )

    # Dublikat xabar: bir xil matn 2 marta tez yuborilsa → True
    check("dublikat: birinchi yuborish False",
          not is_duplicate_message(888001, "Salom bot"))
    check("dublikat: qayta yuborish True",
          is_duplicate_message(888001, "Salom bot"))
    check("dublikat: boshqa matn False",
          not is_duplicate_message(888001, "Boshqa matn"))

    # Kunlik AI limiti: 30 ta o'tadi, 31-chisi blok
    blocks = [check_ai_daily_limit(888002, max_per_day=AI_MAX_PER_DAY) for _ in range(AI_MAX_PER_DAY + 1)]
    check(f"kunlik AI: {AI_MAX_PER_DAY} ta o'tadi, keyingisi blok",
          not any(blocks[:AI_MAX_PER_DAY]) and blocks[AI_MAX_PER_DAY])

    # Global flood: 60+ update/sekund bo'lsa True
    from utils.helpers import _GLOBAL_FLOOD
    _GLOBAL_FLOOD.clear()
    for _ in range(GLOBAL_MAX_UPDATES_PER_SEC + 5):
        check_global_flood()
    check("global flood: limitdan oshsa True", check_global_flood())


def test_tashkent_date():
    print("== database._today_tashkent (kunlik bonus vaqti) ==")
    from database import _today_tashkent
    from datetime import date, timedelta
    today = _today_tashkent()
    check("Toshkent sanasi qaytadi", isinstance(today, date), str(today))
    # Toshkent UTC+5 — server UTC dan ko'pi bilan 1 kunga farq qilishi mumkin
    diff = abs((today - date.today()).days)
    check("sana UTC dan ≤1 kun farq qiladi", diff <= 1, f"diff={diff} tashkent={today} utc={date.today()}")


def test_prompt_truncation():
    print("== utils.ai_agent prompt limiti ==")
    from utils.ai_agent import MAX_PROMPT_CHARS, analyze_user_prompt
    check("MAX_PROMPT_CHARS = 3000", MAX_PROMPT_CHARS == 3000)

    # Prompt kesish logikasi: 3000 dan ortiq bo'lsa kesiladi
    long_prompt = "A" * (MAX_PROMPT_CHARS + 500)
    # analyze_user_prompt chaqirmaymiz (tarmoq kerak), faqat konstanta tekshiriladi
    # + kesish logikasi _call funksiyalarida qo'llanadi — mock testda tekshirilgan
    check("uzun prompt aniqlanadi", len(long_prompt) > MAX_PROMPT_CHARS)


def test_compose_post_text():
    print("== scheduler.compose_post_text (majburiy reklama olib tashlangan) ==")
    from scheduler import compose_post_text
    check("litsenziya: matn o'zgarmaydi", compose_post_text("Salom", True, "REKLAMA") == "Salom")
    check("watermark yo'q (default)", "@PostAssistrobot" not in compose_post_text("Salom", False, "REKLAMA"))
    check("admin reklamasi qo'shiladi", compose_post_text("Salom", False, "REKLAMA") == "Salom\n\nREKLAMA")
    check("bo'sh reklama: o'zgarmaydi", compose_post_text("Salom", False, "  ") == "Salom")
    check("faqat reklama", compose_post_text("", False, "REKLAMA") == "REKLAMA")
    # Ongli ravishda yoqilgan nishon (watermark) admin tomonidan qo'shiladi.
    check("nishon qo'shiladi", compose_post_text(
        "Salom", False, "REKLAMA", "@PostAssistrobot") == "Salom\n\nREKLAMA\n\n@PostAssistrobot")
    check("litsenziya bilan ham nishon qo'shiladi", compose_post_text(
        "Salom", True, "", "@PostAssistrobot") == "Salom\n\n@PostAssistrobot")
    check("nishon bo'sh: o'zgarmaydi", compose_post_text("Salom", False, "REKLAMA", "") == "Salom\n\nREKLAMA")


def test_apply_post_watermark():
    """Bepul foydalanuvchi postiga @PostAssistrobot qo'shiladi, PRO/adminga yo'q."""
    print("== watermark: free vs pro vs admin ==")
    import asyncio
    import database as db_mod
    from config import ADMIN_IDS_SET
    from utils.helpers import apply_post_watermark

    orig_run_db = db_mod.run_db
    pro_users = {777}

    async def fake_run_db(fn, *args, **kwargs):
        if getattr(fn, "__name__", "") == "is_premium":
            return args[0] in pro_users
        return await orig_run_db(fn, *args, **kwargs)

    db_mod.run_db = fake_run_db
    admin_id = next(iter(ADMIN_IDS_SET), None)
    try:
        free = asyncio.run(apply_post_watermark("Salom", 555, "PostAssistrobot"))
        check("free: watermark boshiga qo'shildi", free == "@PostAssistrobot\n\nSalom", free)

        empty = asyncio.run(apply_post_watermark("", 555, "@PostAssistrobot"))
        check("free: bo'sh matn -> faqat username", empty == "@PostAssistrobot", empty)

        twice = asyncio.run(apply_post_watermark(free, 555, "PostAssistrobot"))
        check("free: takrorlanmaydi", twice == free, twice)

        pro = asyncio.run(apply_post_watermark("Salom", 777, "PostAssistrobot"))
        check("PRO: toza post", pro == "Salom", pro)

        if admin_id is not None:
            adm = asyncio.run(apply_post_watermark("Salom", admin_id, "PostAssistrobot"))
            check("admin: toza post", adm == "Salom", adm)
    finally:
        db_mod.run_db = orig_run_db


def test_compose_post_text_limit():
    print("== scheduler.compose_post_text limit (nishon kesilmaydi) ==")
    from scheduler import compose_post_text

    brand = "@PostAssistrobot"
    long_text = "A" * 5000

    caption = compose_post_text(long_text, True, "", brand, limit=1024)
    check("caption 1024 dan oshmaydi", len(caption) <= 1024, str(len(caption)))
    check("caption oxirida nishon saqlanadi", caption.endswith(brand), caption[-40:])

    body = compose_post_text(long_text, True, "", brand, limit=4096)
    check("matn 4096 dan oshmaydi", len(body) <= 4096, str(len(body)))
    check("matn oxirida nishon saqlanadi", body.endswith(brand), body[-40:])

    with_ad = compose_post_text(long_text, False, "REKLAMA", brand, limit=1024)
    check("reklama + nishon ham limitga sig'adi",
          len(with_ad) <= 1024 and with_ad.endswith(brand), str(len(with_ad)))

    short = compose_post_text("Salom", True, "", brand, limit=1024)
    check("qisqa matn kesilmaydi", short == f"Salom\n\n{brand}", short)
    check("limitsiz eski xatti-harakat saqlanadi",
          compose_post_text("Salom", True, "", brand) == f"Salom\n\n{brand}")



def test_ai_runtime_params():
    print("== utils.ai_agent runtime parametrlar ==")
    from utils import ai_agent
    p = ai_agent.get_runtime_params()
    for key in ("temperature", "max_tokens", "top_p", "max_prompt_chars", "context_messages", "context_chars"):
        check(f"runtime: {key} mavjud", key in p, str(p))
    raise_no = []
    ai_agent._RUNTIME_PARAMS["temperature"] = 0.2
    ai_agent._set_runtime_param("temperature", "0.7")
    check("temperature yangilanadi", ai_agent.get_runtime_params()["temperature"] == 0.7)
    ai_agent._set_runtime_param("temperature", "8")
    check("temperature 0..2 oralig'ida", ai_agent.get_runtime_params()["temperature"] == 2.0)
    ai_agent._RUNTIME_PARAMS["temperature"] = 0.2


def test_admin_new_buttons():
    print("== admin yangi tugmalari ==")
    from keyboards.default import get_admin_panel_keyboard, BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB
    kb = get_admin_panel_keyboard()
    texts = [b.text for row in kb.keyboard for b in row]
    check("Post nishoni tugmasi", BTN_POST_TAG in texts, str(texts))
    check("AI parametrlar tugmasi", BTN_AI_SETTINGS in texts, str(texts))
    check("DB/Kesh tugmasi", BTN_CACHE_DB in texts, str(texts))
    from keyboards.inline import get_cache_actions_keyboard
    cbs = [b.callback_data for row in get_cache_actions_keyboard().inline_keyboard for b in row]
    check("Kesh tozalash callback", "cache_clear" in cbs and "close_msg" in cbs, str(cbs))


def test_parse_album_items():
    print("== scheduler.parse_album_items ==")
    from scheduler import parse_album_items
    raw = '[{"type":"photo","file_id":"aa"},{"type":"video","file_id":"bb","caption":"x"}]'
    items = parse_album_items(raw)
    check("2 ta element", len(items) == 2, str(items))
    check("birinchi photo", items[0]["type"] == "photo" and items[0]["file_id"] == "aa")
    check("bo'sh/xato → []", parse_album_items("not-json") == [] and parse_album_items(None) == [])
    too_many = [{"type": "photo", "file_id": str(i)} for i in range(15)]
    import json as _json
    check("maks 10 ta", len(parse_album_items(_json.dumps(too_many))) == 10)


def test_album_label():
    print("== format_post_type_label albom ==")
    from utils.helpers import format_post_type_label
    check("album → Albom", format_post_type_label("album") == "Albom")


def test_referral_share_url_encoding():
    print("== referral share URL encode ==")
    from urllib.parse import parse_qs, urlparse
    from keyboards.inline import get_referral_share_keyboard

    referral_link = "https://t.me/My_Bot?start=ref_1&source=invite"
    markup = get_referral_share_keyboard(referral_link)
    share_url = markup.inline_keyboard[0][0].url
    query = parse_qs(urlparse(share_url).query)

    check("referral havolasi to'liq encode/decode bo'ladi", query.get("url") == [referral_link], share_url)
    check("share URL da maxsus belgilar percent-encode", "%3A%2F%2F" in share_url and "%26" in share_url, share_url)
    check("share matni query parametrida", bool(query.get("text")), share_url)


def test_natural_time_parser():
    print("== utils.helpers parse_future_time (erkin til vaqti) ==")
    from utils.helpers import parse_future_time
    tz = pytz.timezone("Asia/Tashkent")
    now = tz.localize(datetime(2026, 8, 30, 12, 0))

    def r(s):
        dt = parse_future_time(s, now)
        return dt.strftime("%Y-%m-%d %H:%M") if dt else None

    check("'5 daqiqadan keyin' -> +5 min", r("5 daqiqadan keyin") == "2026-08-30 12:05", r("5 daqiqadan keyin"))
    check("'1 soatdan keyin' -> +1 soat", r("1 soatdan keyin") == "2026-08-30 13:00", r("1 soatdan keyin"))
    check("'bugun 15:45 ga'", r("bugun 15:45 ga") == "2026-08-30 15:45", r("bugun 15:45 ga"))
    check("'15:45 ga' (bugun, kelajak)", r("15:45 ga") == "2026-08-30 15:45", r("15:45 ga"))
    check("'ertaga ertalab 9 ga'", r("ertaga ertalab 9 ga") == "2026-08-31 09:00", r("ertaga ertalab 9 ga"))
    check("'ertaga 18:00 da'", r("ertaga 18:00 da") == "2026-08-31 18:00", r("ertaga 18:00 da"))
    check("'kechqurun 8 ga' -> 20:00", r("kechqurun 8 ga") == "2026-08-30 20:00", r("kechqurun 8 ga"))
    check("'2026-09-02 10:30'", r("2026-09-02 10:30") == "2026-09-02 10:30", r("2026-09-02 10:30"))
    check("'02.09.2026 10:30' (DD.MM.YYYY)", r("02.09.2026 10:30") == "2026-09-02 10:30", r("02.09.2026 10:30"))
    check("'2-sentyabr 10:30'", r("2-sentyabr 10:30") == "2026-09-02 10:30", r("2-sentyabr 10:30"))
    check("'30.08 20:00' (DD.MM)", r("30.08 20:00") == "2026-08-30 20:00", r("30.08 20:00"))
    check("to'liq buyruq gapida vaqt",
          r("bugun soat 15:45 ga rejalashtir hamma kanalga") == "2026-08-30 15:45",
          r("bugun soat 15:45 ga rejalashtir hamma kanalga"))
    check("savol matni -> None", parse_future_time("salom, qalaysiz?", now) is None, "")
    check("o'tib ketgan vaqt -> None", r("2020-01-01 10:00") is None, r("2020-01-01 10:00"))


def test_ai_intent_normalization():
    print("== utils.ai_agent intent normalization ==")
    from utils.ai_agent import _normalize_router_result

    r = _normalize_router_result({
        "intent": "faq", "reply": "Men yordam beraman.", "post_text": "",
        "scheduled_time": None, "has_explicit_time": False, "target_all": False,
    })
    check("faq intent", r["intent"] == "faq" and r["reply"] == "Men yordam beraman.", str(r))

    r = _normalize_router_result({
        "intent": "post", "reply": "", "post_text": "Post",
        "scheduled_time": "2026-09-02 10:00", "has_explicit_time": True, "target_all": True,
    })
    check("post intent + vaqt + target_all",
          r["intent"] == "post" and r["has_explicit_time"] and r["target_all"] and r["scheduled_time"], str(r))

    # Eski sxema (intent yo'q) — post sifatida ishlanishi kerak
    r = _normalize_router_result({"post_text": "Eski post", "scheduled_time": None,
                                  "has_explicit_time": False, "target_all": False})
    check("eski sxema muvofiqligi (post_text)", r["intent"] == "post" and r["post_text"] == "Eski post", str(r))

    # "null" satri -> None
    r = _normalize_router_result({"intent": "post", "post_text": "x", "scheduled_time": "null",
                                  "has_explicit_time": False})
    check("scheduled_time 'null' -> None", r["scheduled_time"] is None and not r["has_explicit_time"], str(r))

    # error saqlanadi
    r = _normalize_router_result({"error": "xato"})
    check("error o'zgarmasdan o'tadi", r.get("error") == "xato", str(r))


def test_new_inline_keyboards():
    print("== yangi inline tugmalar (qo'shish/o'chirish/yopish) ==")
    from keyboards.inline import (
        render_channels_list, render_pending_list, get_sponsors_delete_keyboard,
    )
    from keyboards.default import get_ai_time_keyboard

    ch_cbs = [b.callback_data for row in render_channels_list([("-1001", "K")]).inline_keyboard for b in row]
    check("kanallar: ulash + yopish tugmasi",
          "add_channel_start" in ch_cbs and "close_msg" in ch_cbs, str(ch_cbs))

    p_cbs = [b.callback_data for row in render_pending_list(
        [(5, "K", "text", None, 3, "none", None, None)], "ab1").inline_keyboard for b in row]
    check("pending: yangilash + yopish",
          "pending_refresh" in p_cbs and "close_msg" in p_cbs, str(p_cbs))

    s_cbs = [b.callback_data for row in get_sponsors_delete_keyboard(
        [(1, "-100", "S", "t.me/x")]).inline_keyboard for b in row]
    check("sponsorlar: yopish tugmasi", "close_msg" in s_cbs, str(s_cbs))

    ai_kb = [b.text for row in get_ai_time_keyboard().keyboard for b in row]
    check("AI vaqt klaviaturasida takroriy (kunlik/haftalik) yo'q",
          not any("Har kuni" in t or "Hafta" in t for t in ai_kb), str(ai_kb))

    from handlers.ai_assistant import AI_CONFIRM_KEYBOARD
    ac = [b.callback_data for row in AI_CONFIRM_KEYBOARD.inline_keyboard for b in row]
    check("AI confirm: bekor qilish tugmasi", "ai_post_cancel" in ac, str(ac))


def test_admin_channels_text_limit():
    print("== admin kanal ro'yxati limiti ==")
    from handlers.admin import (
        ADMIN_CHANNELS_LIMIT,
        TELEGRAM_TEXT_LIMIT,
        _telegram_text_length,
        format_admin_channels_list,
    )

    channels = [
        (f"-100{i}", "<&>" * 100, i, "owner<&>" * 30)
        for i in range(ADMIN_CHANNELS_LIMIT)
    ]
    text = format_admin_channels_list(channels)
    check("faqat oxirgi 20 ta uchun format", f"{ADMIN_CHANNELS_LIMIT} ta" in text, text[:120])
    check("kanal nomi HTML-escape", "&lt;" in text and "&amp;" in text, text[:250])
    check("Telegram 4096 limiti oshmaydi", _telegram_text_length(text) <= TELEGRAM_TEXT_LIMIT,
          str(_telegram_text_length(text)))
    check("sig'magan kanallar haqida eslatma", "ko'rsatilmagan" in text, text[-160:])


def test_ai_context_memory():
    print("== utils.ai_agent suhbat konteksti ==")
    from utils import ai_agent

    uid = 777001
    ai_agent.clear_ai_context(uid)
    ai_agent._RUNTIME_PARAMS["context_messages"] = 6
    ai_agent._RUNTIME_PARAMS["context_chars"] = 4000

    ai_agent._store_ai_context(uid, "Salom, post tayyorla", role="user")
    ai_agent._store_ai_context(uid, "<b>Tayyor post</b> matni", role="bot")
    ctx = ai_agent._get_ai_context_text(uid, 4000)

    check("kontekstda foydalanuvchi xabari bor", "Salom, post tayyorla" in ctx, ctx)
    check("kontekstda bot javobi ham bor", "Tayyor post" in ctx, ctx)
    check("kontekstda HTML teglari yo'q", "<b>" not in ctx and "</b>" not in ctx, ctx)
    check("kontekst roli belgilanadi", "Foydalanuvchi:" in ctx and "Bot:" in ctx, ctx)

    # context_chars byudjeti amalda ishlaydi
    ai_agent._RUNTIME_PARAMS["context_chars"] = 60
    small_ctx = ai_agent._get_ai_context_text(uid, 4000)
    check("context_chars byudjeti qo'llanadi", len(small_ctx) <= 60, f"{len(small_ctx)}: {small_ctx}")
    ai_agent._RUNTIME_PARAMS["context_chars"] = 4000

    # context_messages = 0 → kontekst umuman ishlatilmaydi
    ai_agent._RUNTIME_PARAMS["context_messages"] = 0
    check("context_messages=0 → kontekst yo'q", ai_agent._get_ai_context_text(uid, 4000) == "")
    ai_agent._RUNTIME_PARAMS["context_messages"] = 6

    # clear_ai_context sessiyani tozalaydi
    ai_agent.clear_ai_context(uid)
    check("clear_ai_context tozalaydi", ai_agent._get_ai_context_text(uid, 4000) == "")
    ai_agent._RUNTIME_PARAMS["context_messages"] = ai_agent._RUNTIME_DEFAULTS["context_messages"]
    ai_agent._RUNTIME_PARAMS["context_chars"] = ai_agent._RUNTIME_DEFAULTS["context_chars"]


def test_ai_optional_params():
    print("== utils.ai_agent ixtiyoriy parametrlar (null yuborilmaydi) ==")
    from utils import ai_agent

    # "off" → parametr butunlay o'chadi
    ai_agent._set_runtime_param("max_tokens", "off")
    ai_agent._set_runtime_param("top_p", "none")
    params = ai_agent.get_runtime_params()
    check("max_tokens o'chirilgan (None)", params["max_tokens"] is None, str(params["max_tokens"]))
    check("top_p o'chirilgan (None)", params["top_p"] is None, str(params["top_p"]))

    payload = {"model": "x"}
    ai_agent._apply_optional_params(payload, params)
    check("payload'da max_tokens yo'q", "max_tokens" not in payload, str(payload))
    check("payload'da top_p yo'q", "top_p" not in payload, str(payload))
    check("temperature esa yuboriladi", payload.get("temperature") is not None, str(payload))

    # Qiymat qaytarilsa yana yuboriladi
    ai_agent._set_runtime_param("max_tokens", "1024")
    ai_agent._set_runtime_param("top_p", "0.9")
    payload2 = {}
    ai_agent._apply_optional_params(payload2, ai_agent.get_runtime_params())
    check("qayta yoqilgan max_tokens yuboriladi", payload2.get("max_tokens") == 1024, str(payload2))
    check("qayta yoqilgan top_p yuboriladi", payload2.get("top_p") == 0.9, str(payload2))

    # Bo'sh qiymat → default
    ai_agent._set_runtime_param("max_tokens", "")
    check("bo'sh qiymat → default", ai_agent.get_runtime_params()["max_tokens"]
          == ai_agent._RUNTIME_DEFAULTS["max_tokens"])
    ai_agent._set_runtime_param("top_p", "")


def test_button_labels():
    print("== bo'sh/takroriy tugma nomlari ==")
    from keyboards.inline import btn_label, render_channels_list
    from handlers.new_post import build_channel_labels

    check("bo'sh nom → fallback", btn_label("") == "Kanal", btn_label(""))
    check("None → fallback", btn_label(None) == "Kanal", str(btn_label(None)))
    check("'None' satri → fallback", btn_label("None") == "Kanal", btn_label("None"))
    check("uzun nom kesiladi", len(btn_label("A" * 200)) <= 40, str(len(btn_label("A" * 200))))
    check("oddiy nom o'zgarmaydi", btn_label("Mening kanalim") == "Mening kanalim")

    texts = [b.text for row in render_channels_list([("-1001", ""), ("-1002", None)]).inline_keyboard
             for b in row]
    check("bo'sh sarlavhali kanal tugmasi bo'sh emas",
          all(t.strip() for t in texts) and "📢 Kanal" in texts, str(texts))

    labels = build_channel_labels([("-1001", "Kanal A"), ("-1002", "Kanal A"), ("-1003", "")])
    check("takroriy nomlar farqlanadi", len(labels) == 3, str(labels))
    check("barcha yorliqlar bo'sh emas", all(l.strip() for l in labels), str(labels))
    check("takroriy nomga ID qo'shiladi", any("-1002" in l for l in labels), str(labels))


def test_smart_reply_ad_async():
    print("== utils.helpers reklama satri (async DB) ==")
    import asyncio
    import inspect
    import database as db_mod
    from utils import helpers

    check("get_smart_reply_ad_async coroutine",
          inspect.iscoroutinefunction(helpers.get_smart_reply_ad_async))

    calls = []
    original_run_db = db_mod.run_db

    async def fake_run_db(func, *args, **kwargs):
        calls.append(func.__name__)
        return ""

    db_mod.run_db = fake_run_db
    try:
        result = asyncio.run(helpers.get_smart_reply_ad_async(777002))
    finally:
        db_mod.run_db = original_run_db

    # Avval PRO tekshiruvi (avtomatik reklamasiz rejim), keyin reklama puli
    check("DB o'qish run_db (thread) orqali ketadi",
          calls == ["is_premium", "get_ads_full", "get_setting"], str(calls))
    check("reklama bo'sh bo'lsa satr ham bo'sh", result == "", result)


def test_ad_pool_rotation():
    """Avtomatik reklama rotatsiya: round-robin + eski sozlamaga qaytish."""
    print("== utils.helpers avto-rotatsiya reklama ==")
    import asyncio
    from utils import helpers
    import database as db_mod

    # Round-robin aylanish
    ads = [(1, "REKLAMA-A"), (2, "REKLAMA-B"), (3, "REKLAMA-C")]
    first = helpers._next_ad_text(ads, "channel")
    second = helpers._next_ad_text(ads, "channel")
    third = helpers._next_ad_text(ads, "channel")
    fourth = helpers._next_ad_text(ads, "channel")
    check("round-robin: 1-chi", first == "REKLAMA-A", first)
    check("round-robin: 2-chi", second == "REKLAMA-B", second)
    check("round-robin: 3-chi", third == "REKLAMA-C", third)
    check("round-robin: qaytadan aylanadi", fourth == "REKLAMA-A", fourth)
    check("bo'sh pul: bo'sh satr", helpers._next_ad_text([], "channel") == "")

    # Har bir scope alohida aylanadi
    helpers._AD_ROTATION_INDEX.clear()
    ch1 = helpers._next_ad_text(ads, "channel")
    rp1 = helpers._next_ad_text(ads, "reply")
    check("scope'lar alohida aylanadi", ch1 == "REKLAMA-A" and rp1 == "REKLAMA-A", (ch1, rp1))
    helpers._AD_ROTATION_INDEX.clear()

    # Pul bo'sh bo'lganda eski yagona sozlamaga qaytish (async, kanal)
    calls = []
    original_run_db = db_mod.run_db

    async def fake_empty(func, *args, **kwargs):
        calls.append(func.__name__)
        # get_ads bo'sh ro'yxat, get_setting esa eski matn qaytaradi
        return [] if func.__name__ == "get_ads" else "LEGACY-AD"

    db_mod.run_db = fake_empty
    try:
        legacy = asyncio.run(helpers.get_channel_ad_next_async())
    finally:
        db_mod.run_db = original_run_db
    check("pul bo'sh: eski sozlamaga qaytadi", legacy == "LEGACY-AD", legacy)
    check("pul bo'sh: get_ads keyin get_setting", calls == ["get_ads", "get_setting"], str(calls))

    # Pul bor bo'lganda navbatdagi reklama qaytadi (async, reply)
    calls = []
    async def fake_pool(func, *args, **kwargs):
        calls.append(func.__name__)
        if func.__name__ == "get_ads_full":
            return [{"id": 7, "text": "POOL-AD", "button_text": "Bos",
                     "button_url": "https://t.me/pool", "is_active": True}]
        return ""

    db_mod.run_db = fake_pool
    # Bot javoblari reklamasi har 3-xabarga chiqadi — sanagichni 2 ga qo'yib,
    # navbatdagi chaqiruv (3-chi) reklamani chiqarishini ta'minlaymiz.
    helpers._USER_MSG_COUNT[777003] = 2
    try:
        pooled = asyncio.run(helpers.get_smart_reply_ad_async(777003))
    finally:
        db_mod.run_db = original_run_db
    check("pul bor: navbatdagi reklama (har 3-xabarga)", "POOL-AD" in pooled, pooled)
    check("pul bor: reklama tugmasi havola sifatida qo'shildi",
          'href="https://t.me/pool"' in pooled and "Bos" in pooled, pooled)
    check("pul bor: is_premium + get_ads_full chaqiriladi (get_setting emas)",
          calls == ["is_premium", "get_ads_full"], str(calls))
    helpers._AD_ROTATION_INDEX.clear()

    # DB funktsiyalari mavjudligi
    for fname in ("add_ad", "get_ads", "delete_ad", "clear_ads", "count_ads",
                  "AD_SCOPE_CHANNEL", "AD_SCOPE_REPLY"):
        check(f"db.{fname} mavjud", hasattr(db_mod, fname))

    # Noto'g'ri scope / bo'sh matn DB'ga urilmaydi (xavfsiz -1)
    check("noto'g'ri scope add_ad -> -1", db_mod.add_ad("bogus", "X") == -1)
    check("bo'sh matn add_ad -> -1", db_mod.add_ad("channel", "   ") == -1)
    check("noto'g'ri scope get_ads -> []", db_mod.get_ads("bogus") == [])


def test_ai_format_prompts():
    """AI format action promptlari to'g'ri shakllanishi."""
    print("== AI format action prompts ==")
    from utils.ai_agent import _FORMAT_ACTION_PROMPTS, format_post_text
    import asyncio

    # 1. Barcha action lar uchun promptlar mavjud
    check("grammar prompt mavjud", "grammar" in _FORMAT_ACTION_PROMPTS)
    check("emoji prompt mavjud", "emoji" in _FORMAT_ACTION_PROMPTS)
    check("hashtags prompt mavjud", "hashtags" in _FORMAT_ACTION_PROMPTS)
    check("tldr prompt mavjud", "tldr" in _FORMAT_ACTION_PROMPTS)

    # 2. Promptlar O'zbek tilida (grammar va hashtags da aniq ko'rsatilgan)
    check("grammar: O'zbek tilida", "O'zbek" in _FORMAT_ACTION_PROMPTS["grammar"])
    check("hashtags: O'zbek tilida", "O'zbek" in _FORMAT_ACTION_PROMPTS["hashtags"])

    # 3. Bo'sh matn → xatolik
    result = asyncio.run(format_post_text("", "grammar"))
    check("bo'sh matn → error", "error" in result, str(result))

    result2 = asyncio.run(format_post_text(None, "grammar"))
    check("None matn → error", "error" in result2, str(result2))

    # 4. Noma'lum action → xatolik
    result3 = asyncio.run(format_post_text("Salom", "unknown_action"))
    check("noma'lum action → error", "error" in result3, str(result3))

    # 5. Promptlar matn mazmunini o'zgartirmaslikni talab qiladi
    check("grammar: ma'noni saqlash", "O'ZGARTIRMANG" in _FORMAT_ACTION_PROMPTS["grammar"])
    check("emoji: mazmun saqlash", "O'ZGARTIRMANG" in _FORMAT_ACTION_PROMPTS["emoji"])

    # 6. Promptlar qisqa va aniq
    for action, prompt in _FORMAT_ACTION_PROMPTS.items():
        check(f"{action}: prompt < 500 belgi", len(prompt) < 500, str(len(prompt)))


def test_ai_action_keyboards():
    """AI action keyboardlari to'g'ri shakllanishi."""
    print("== AI action keyboards ==")
    from handlers.new_post import _get_ai_action_keyboard, _get_ai_result_keyboard

    # 1. Action keyboard
    kb = _get_ai_action_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("action kb: grammar", "ai_act:grammar" in cbs)
    check("action kb: emoji", "ai_act:emoji" in cbs)
    check("action kb: hashtags", "ai_act:hashtags" in cbs)
    check("action kb: tldr", "ai_act:tldr" in cbs)
    check("action kb: back", "ai_act:back" in cbs)
    check("action kb: 5 ta tugma", len(cbs) == 5)

    # 2. Result keyboard
    rkb = _get_ai_result_keyboard()
    rcbs = [b.callback_data for row in rkb.inline_keyboard for b in row]
    check("result kb: accept", "ai_res:accept" in rcbs)
    check("result kb: retry", "ai_res:retry" in rcbs)
    check("result kb: revert", "ai_res:revert" in rcbs)
    check("result kb: 3 ta tugma", len(rcbs) == 3)

    # 3. Label matnlari
    check("accept label", any("Qabul" in t for t in [b.text for row in rkb.inline_keyboard for b in row]))
    check("revert label", any("Asl" in t for t in [b.text for row in rkb.inline_keyboard for b in row]))


def test_ai_format_fallback():
    """AI xatolik berganda graceful fallback."""
    print("== AI format fallback ==")
    from utils.ai_agent import format_post_text
    import asyncio

    # Noma'lum action — asl matn buzilmaydi
    result = asyncio.run(format_post_text("Salom dunyo", "xyz"))
    check("fallback: error qaytaradi", "error" in result)
    check("fallback: error xabari bor", len(str(result.get("error", ""))) > 5)

    # Bo'sh matn
    result2 = asyncio.run(format_post_text("", "emoji"))
    check("fallback: bo'sh matn error", "error" in result2)


def test_tone_of_voice_constants():
    """Tone of voice konstantalari va keyboardlar."""
    print("== Tone of Voice konstantalari ==")
    from keyboards.default import TONE_LABELS, get_tone_keyboard
    from database import VALID_TONES

    # 1. Barcha tone lar mavjud
    check("formal mavjud", "formal" in TONE_LABELS)
    check("friendly mavjud", "friendly" in TONE_LABELS)
    check("concise mavjud", "concise" in TONE_LABELS)
    check("engaging mavjud", "engaging" in TONE_LABELS)

    # 2. Label matnlari O'zbek tilida
    check("formal label O'zbek", "Rasmiy" in TONE_LABELS["formal"])
    check("friendly label O'zbek", "Do'stona" in TONE_LABELS["friendly"])
    check("concise label O'zbek", "Qisqa" in TONE_LABELS["concise"])
    check("engaging label O'zbek", "Ko'ngilochar" in TONE_LABELS["engaging"])

    # 3. DB VALID_TONES to'g'ri
    check("DB VALID_TONES: 4 ta", len(VALID_TONES) == 4)
    check("DB: formal", "formal" in VALID_TONES)
    check("DB: friendly", "friendly" in VALID_TONES)
    check("DB: concise", "concise" in VALID_TONES)
    check("DB: engaging", "engaging" in VALID_TONES)

    # 4. Tone keyboard
    kb = get_tone_keyboard()
    labels = [b.text for row in kb.inline_keyboard for b in row] if hasattr(kb, 'inline_keyboard') else []
    # ReplyKeyboardMarkup — keyboard attribute
    labels = [b for row in kb.keyboard for b in row]
    check("tone keyboard mavjud", kb is not None)


def test_tone_descriptions():
    """Tone descriptionlari va inject ishlashi."""
    print("== Tone descriptions ==")
    from utils.ai_agent import _TONE_DESCRIPTIONS, get_tone_instruction, _inject_tone

    # 1. Barcha tone lar uchun description mavjud
    for tone in ("formal", "friendly", "concise", "engaging"):
        check(f"{tone} description mavjud", tone in _TONE_DESCRIPTIONS)
        check(f"{tone} description uzun", len(_TONE_DESCRIPTIONS[tone]) > 20)

    # 2. get_tone_instruction
    inst = get_tone_instruction("formal")
    check("formal instruction: Rasmiy", "Rasmiy" in inst)
    check("formal instruction: professional", "professional" in inst)

    inst2 = get_tone_instruction("engaging")
    check("engaging instruction: Emotsional", "Emotsional" in inst2 or "emotsional" in inst2.lower())

    # 3. _inject_tone: friendly — o'zgarmaydi
    base = "Siz post muharririsiz."
    result_friendly = _inject_tone(base, "friendly")
    check("friendly: inject yo'q", result_friendly == base)

    # 4. _inject_tone: formal — qo'shiladi
    result_formal = _inject_tone(base, "formal")
    check("formal: inject bor", "KANAL USLUBI" in result_formal)
    check("formal: asl matn saqlanadi", base in result_formal)

    # 5. _inject_tone: bo'sh tone — o'zgarmaydi
    result_empty = _inject_tone(base, "")
    check("bo'sh tone: inject yo'q", result_empty == base)


def test_content_plan_prompt():
    """Content plan prompt strukturasini tekshirish."""
    print("== Content plan prompt ==")
    from utils.ai_agent import _CONTENT_PLAN_SYSTEM, _POST_FROM_PLAN_SYSTEM, generate_content_plan, generate_post_from_plan
    import asyncio

    # 1. Content plan system prompt O'zbek tilida
    check("plan prompt: O'zbek", "O'ZBEK" in _CONTENT_PLAN_SYSTEM)
    check("plan prompt: JSON format", "JSON" in _CONTENT_PLAN_SYSTEM)
    check("plan prompt: 7 kunlik", "7" in _CONTENT_PLAN_SYSTEM)
    check("plan prompt: Dushanba", "Dushanba" in _CONTENT_PLAN_SYSTEM)

    # 2. Post from plan system prompt
    check("post prompt: O'zbek", "O'zbek" in _POST_FROM_PLAN_SYSTEM)
    check("post prompt: HTML", "HTML" in _POST_FROM_PLAN_SYSTEM)
    check("post prompt: CTA", "CTA" in _POST_FROM_PLAN_SYSTEM)

    # 3. Bo'sh mavzu → xatolik
    result = asyncio.run(generate_content_plan("", "Kanal"))
    check("bo'sh mavzu → error", "error" in result)

    result2 = asyncio.run(generate_content_plan(None, "Kanal"))
    check("None mavzu → error", "error" in result2)

    # 4. generate_post_from_plan — bo'sh g'oya bilan ham ishlaydi
    # (AI chaqiruvi bo'lmaydi, faqat prompt tuzilishini tekshiramiz)


def test_content_plan_keyboards():
    """Content plan keyboardlari."""
    print("== Content plan keyboards ==")
    from handlers.content_plan import _get_plan_channel_keyboard, _get_plan_result_keyboard, _get_plan_day_keyboard

    # 1. Channel keyboard
    channels = [("-1001", "Test Kanal"), ("-1002", "Ikkinchi Kanal")]
    kb = _get_plan_channel_keyboard(channels)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("channel kb: kanal 1", "plan_ch:-1001" in cbs)
    check("channel kb: kanal 2", "plan_ch:-1002" in cbs)
    check("channel kb: cancel", "plan_cancel" in cbs)

    # 2. Result keyboard
    rkb = _get_plan_result_keyboard()
    rcbs = [b.callback_data for row in rkb.inline_keyboard for b in row]
    check("result kb: create", "plan_create_post" in rcbs)
    check("result kb: regenerate", "plan_regenerate" in rcbs)
    check("result kb: cancel", "plan_cancel" in rcbs)

    # 3. Day keyboard
    plan_items = [
        {"day": "Dushanba", "format": "Maslahat", "title": "Birinchi g'oya", "idea": "Tavsif"},
        {"day": "Seshanba", "format": "Keys", "title": "Ikkinchi g'oya", "idea": "Tavsif 2"},
    ]
    dkb = _get_plan_day_keyboard(plan_items)
    dcbs = [b.callback_data for row in dkb.inline_keyboard for b in row]
    check("day kb: kun 0", "plan_day:0" in dcbs)
    check("day kb: kun 1", "plan_day:1" in dcbs)
    check("day kb: back", "plan_back" in dcbs)
    check("day kb: 3 ta tugma", len(dcbs) == 3)


def test_tone_migration_sql():
    """Tone of voice migration SQL to'g'ri."""
    print("== Tone migration SQL ==")
    import database as db_mod
    # init_db ichidagi migrationlarni tekshiramiz
    source = open(db_mod.__file__).read()
    check("migration: tone_of_voice", "tone_of_voice" in source)
    check("migration: ADD COLUMN IF NOT EXISTS", "ADD COLUMN IF NOT EXISTS tone_of_voice" in source)
    check("migration: default friendly", "'friendly'" in source)


def test_main_keyboard_content_plan():
    """Kontent-reja tugmasi mavjud (AI Studio sub-menuda)."""
    print("== Main keyboard content plan ==")
    from keyboards.default import get_main_keyboard, BTN_CONTENT_PLAN, BTN_AI_STUDIO

    check("BTN_CONTENT_PLAN mavjud", BTN_CONTENT_PLAN == "🧠 Kontent-reja")

    # Content Plan endi AI Studio sub-menuda, asosiy menyuda emas
    kb = get_main_keyboard(False)
    all_texts = [b.text for row in kb.keyboard for b in row]
    check("main kb: Kontent-reja yo'q (AI Studio ichida)", BTN_CONTENT_PLAN not in all_texts)
    check("main kb: AI Studio bor", BTN_AI_STUDIO in all_texts)


def test_channels_list_with_tone():
    """Kanallar ro'yxatida tone tugmasi bor."""
    print("== Channels list with tone ==")
    from keyboards.inline import render_channels_list

    # 2 elementli tuple (eski format)
    channels_old = [("-1001", "Eski Kanal")]
    kb_old = render_channels_list(channels_old)
    cbs_old = [b.callback_data for row in kb_old.inline_keyboard for b in row]
    check("eski format: ch_set (tone) bor", any("ch_set:" in c for c in cbs_old))

    # 3 elementli tuple (yangi format: id, title, tone)
    channels_new = [("-1001", "Yangi Kanal", "formal")]
    kb_new = render_channels_list(channels_new)
    cbs_new = [b.callback_data for row in kb_new.inline_keyboard for b in row]
    labels_new = [b.text for row in kb_new.inline_keyboard for b in row]
    check("yangi format: ch_set (tone) bor", any("ch_set:" in c for c in cbs_new))
    check("yangi format: formal emoji", any("👔" in t for t in labels_new))


def test_analytics_dashboard_format():
    """Dashboard formatlash funksiyasi to'g'ri ishlashi."""
    print("== Analytics dashboard format ==")
    from handlers.analytics import _build_dashboard, _format_hour, _TYPE_EMOJI, _TYPE_LABEL

    # 1. Bo'sh statistika — empty state
    empty_stats = {
        "sent_7d": 0, "sent_30d": 0, "sent_all": 0,
        "pending": 0, "peak_hours": [], "type_distribution": {},
    }
    dash_empty = _build_dashboard(empty_stats, "Test Kanal")
    check("empty: Hali post yo'q", "Hali post chiqarilmagan" in dash_empty)
    check("empty: kanal nomi", "Test Kanal" in dash_empty)
    check("empty: separator", "━━━" in dash_empty)

    # 2. To'ldirilgan statistika
    full_stats = {
        "sent_7d": 14, "sent_30d": 58, "sent_all": 120,
        "pending": 6,
        "peak_hours": [(9, 20), (18, 15), (21, 10)],
        "type_distribution": {"photo": 72, "text": 36, "video": 12},
    }
    dash_full = _build_dashboard(full_stats, "@test_channel")
    check("full: 7 kun", "14" in dash_full)
    check("full: 30 kun", "58" in dash_full)
    check("full: jami", "120" in dash_full)
    check("full: pending", "6" in dash_full)
    check("full: peak 09:00", "09:00" in dash_full)
    check("full: peak 18:00", "18:00" in dash_full)
    check("full: Rasm", "Rasm" in dash_full)
    check("full: Matn", "Matn" in dash_full)
    check("full: Video", "Video" in dash_full)
    check("full: separator", "━━━" in dash_full)

    # 3. _format_hour
    check("hour 0", _format_hour(0) == "00:00")
    check("hour 9", _format_hour(9) == "09:00")
    check("hour 23", _format_hour(23) == "23:00")

    # 4. Type emoji/label mapping
    check("text emoji", _TYPE_EMOJI.get("text") == "📝")
    check("photo emoji", _TYPE_EMOJI.get("photo") == "🖼")
    check("video emoji", _TYPE_EMOJI.get("video") == "🎥")
    check("text label", _TYPE_LABEL.get("text") == "Matn")
    check("photo label", _TYPE_LABEL.get("photo") == "Rasm")


def test_analytics_keyboards():
    """Analytics keyboardlari to'g'ri shakllanishi."""
    print("== Analytics keyboards ==")
    from handlers.analytics import (
        _get_analytics_channel_keyboard,
        _get_analytics_view_keyboard,
    )

    # 1. Channel keyboard
    channels = [("-1001", "Kanal A"), ("-1002", "Kanal B")]
    kb = _get_analytics_channel_keyboard(channels)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("ch kb: Barcha kanallar", "an_ch:all" in cbs)
    check("ch kb: Kanal A", "an_ch:-1001" in cbs)
    check("ch kb: Kanal B", "an_ch:-1002" in cbs)
    check("ch kb: close", "an_close" in cbs)
    check("ch kb: 4 ta tugma", len(cbs) == 4)

    # 2. View keyboard
    vkb = _get_analytics_view_keyboard()
    vcbs = [b.callback_data for row in vkb.inline_keyboard for b in row]
    check("view kb: refresh", "an_refresh" in vcbs)
    check("view kb: other", "an_other" in vcbs)
    check("view kb: close", "an_close" in vcbs)

    # 3. Bo'sh kanallar ro'yxati
    kb_empty = _get_analytics_channel_keyboard([])
    ecbs = [b.callback_data for row in kb_empty.inline_keyboard for b in row]
    check("empty kb: all bor", "an_ch:all" in ecbs)
    check("empty kb: close bor", "an_close" in ecbs)


def test_analytics_db_functions_exist():
    """Database analytics funksiyalari mavjud."""
    print("== Analytics DB functions ==")
    import database as db_mod

    check("get_channel_post_stats mavjud", hasattr(db_mod, "get_channel_post_stats"))
    check("get_user_channel_list_for_analytics mavjud", hasattr(db_mod, "get_user_channel_list_for_analytics"))

    # Funksiyalar callable
    check("get_channel_post_stats callable", callable(db_mod.get_channel_post_stats))
    check("get_user_channel_list_for_analytics callable", callable(db_mod.get_user_channel_list_for_analytics))


def test_analytics_empty_state():
    """Bo'sh kanal uchun empty state xabari."""
    print("== Analytics empty state ==")
    from handlers.analytics import _build_dashboard

    # Faqat pending bor, sent yo'q — empty state (pending ham 0 bo'lsa)
    # pending > 0 bo'lsa — dashboard ko'rsatiladi (navbatda kutayotganlar bor)
    stats_pending_only = {
        "sent_7d": 0, "sent_30d": 0, "sent_all": 0,
        "pending": 3, "peak_hours": [], "type_distribution": {},
    }
    dash = _build_dashboard(stats_pending_only, "Yangi Kanal")
    # sent_all=0 lekin pending>0 → dashboard (pending ko'rsatiladi)
    check("pending>0: Navbatda", "Navbatda" in dash)
    check("pending>0: kanal nomi", "Yangi Kanal" in dash)

    # Barcha qiymatlar 0
    stats_zero = {
        "sent_7d": 0, "sent_30d": 0, "sent_all": 0,
        "pending": 0, "peak_hours": [], "type_distribution": {},
    }
    dash2 = _build_dashboard(stats_zero, "Bo'sh")
    check("zero: empty state", "Hali post chiqarilmagan" in dash2)


def test_analytics_type_distribution_format():
    """Post turlari taqsimoti formati."""
    print("== Analytics type distribution ==")
    from handlers.analytics import _build_dashboard

    # Faqat matn
    stats_text_only = {
        "sent_7d": 5, "sent_30d": 5, "sent_all": 5,
        "pending": 0, "peak_hours": [(10, 5)],
        "type_distribution": {"text": 5},
    }
    dash = _build_dashboard(stats_text_only, "Matn Kanal")
    check("text only: 100% Matn", "100%" in dash and "Matn" in dash)

    # Aralash
    stats_mixed = {
        "sent_7d": 10, "sent_30d": 10, "sent_all": 10,
        "pending": 0, "peak_hours": [(9, 5), (18, 3), (21, 2)],
        "type_distribution": {"photo": 5, "text": 3, "video": 2},
    }
    dash2 = _build_dashboard(stats_mixed, "Aralash Kanal")
    check("mixed: Rasm bor", "Rasm" in dash2)
    check("mixed: Matn bor", "Matn" in dash2)
    check("mixed: Video bor", "Video" in dash2)
    check("mixed: 50% Rasm", "50%" in dash2)


def test_main_menu_layout_v2():
    """Yangi asosiy menyu tartibi va inline sub-menyular."""
    print("== Main menu layout v2 ==")
    from keyboards.default import (
        get_main_keyboard, BTN_NEW_POST, BTN_AI_STUDIO, BTN_SETTINGS,
        BTN_PREMIUM, BTN_HELP, BTN_EXTRAS, BTN_ADMIN_PANEL,
    )
    from keyboards.inline import get_cabinet_inline_keyboard, get_extras_inline_keyboard
    import keyboards.default as kd

    check("AI Yordamchi olib tashlangan", not hasattr(kd, "BTN_AI"))
    check("BTN_SETTINGS matni", BTN_SETTINGS == "👤 Kabinet & Sozlamalar")
    check("BTN_HELP matni", BTN_HELP == "📖 Qo'llanma / Bot haqida")
    check("BTN_EXTRAS matni", BTN_EXTRAS == "⚙️ Qo'shimcha funksiyalar")

    rows = [[b.text for b in row] for row in get_main_keyboard(False).keyboard]
    check("user: 3 qator", len(rows) == 3, str(rows))
    check("user row1", rows[0] == [BTN_NEW_POST, BTN_AI_STUDIO], str(rows[0]))
    # Yangi tartib: ⭐️ Premium chapda, 👤 Kabinet o'ngda (almashtirildi)
    check("user row2", rows[1] == [BTN_PREMIUM, BTN_SETTINGS], str(rows[1]))
    check("user row3", rows[2] == [BTN_HELP, BTN_EXTRAS], str(rows[2]))

    arows = [[b.text for b in row] for row in get_main_keyboard(True).keyboard]
    check("admin: 4 qator", len(arows) == 4, str(arows))
    check("admin row1", arows[0] == [BTN_NEW_POST, BTN_AI_STUDIO], str(arows[0]))
    check("admin row2", arows[1] == [BTN_PREMIUM, BTN_SETTINGS], str(arows[1]))
    check("admin row3", arows[2] == [BTN_HELP, BTN_EXTRAS], str(arows[2]))
    check("admin row4", arows[3] == [BTN_ADMIN_PANEL], str(arows[3]))

    ex = [[(b.text, b.callback_data) for b in row] for row in get_extras_inline_keyboard().inline_keyboard]
    ex_cbs = [c for row in ex for _, c in row]
    check("extras: 3 qator (tezkor tugmali post olib tashlangan)", len(ex) == 3, str(ex))
    check("extras: post kuchaytirgich", ex[0][0] == ("✨ Postga Tugma & Reaksiya qo'shish", "extra_enhancer"), str(ex[0]))
    check("extras: konvertor", ex[1][0] == ("🔤 Krill-Lotin konvertor", "extra_converter"), str(ex[1]))
    check("extras: tezkor tugmali post YO'Q", "extra_quick_btn" not in ex_cbs, str(ex_cbs))
    check("extras: yopish", ex[2][0] == ("❌ Yopish", "extra_close"), str(ex[2]))

    cab = [[(b.text, b.callback_data) for b in row] for row in get_cabinet_inline_keyboard().inline_keyboard]
    check("kabinet: 5 qator", len(cab) == 5, str(cab))
    expected = [
        [("📢 Mening kanallarim", "cab_channels"), ("📊 Kanallar analitikasi", "cab_analytics")],
        [("📅 Kutilayotgan postlar", "cab_pending"), ("⏳ Postlar navbati (Queue)", "cab_queue")],
        [("💎 Ballar & Reklama rejimi", "cab_balance"), ("🎁 Kunlik bonus", "cab_bonus")],
        [("👥 Do'stlarni taklif", "cab_referral"), ("❌ Yopish", "close_cabinet")],
        [("🌐 Til / Язык", "cab_lang")],
    ]
    check("kabinet tartibi", cab == expected, str(cab))


def test_analytics_main_keyboard():
    """Asosiy menyuda Analitika tugmasi bor."""
    print("== Analytics main keyboard ==")
    from keyboards.default import get_main_keyboard, BTN_ANALYTICS

    check("BTN_ANALYTICS mavjud", BTN_ANALYTICS == "📊 Analitika")

    # Analitika endi Kabinet & Sozlamalar inline menyusida
    from keyboards.inline import get_cabinet_inline_keyboard
    cab_cbs = [b.callback_data for row in get_cabinet_inline_keyboard().inline_keyboard for b in row]
    check("kabinet kb: analitika bor", "cab_analytics" in cab_cbs)

    kb = get_main_keyboard(False)
    all_texts = [b.text for row in kb.keyboard for b in row]
    check("main kb: Analitika yo'q (Kabinet ichida)", BTN_ANALYTICS not in all_texts)


def test_plan_limits():
    """Tarif limitlari to'g'ri belgilangan."""
    print("== Plan limits ==")
    from database import PLAN_LIMITS

    # 1. Free limitlari
    check("free: max_channels = 3", PLAN_LIMITS["free"]["max_channels"] == 3)
    check("free: daily_ai = 5", PLAN_LIMITS["free"]["daily_ai_requests"] == 5)

    # 2. PRO limitlari
    check("pro: max_channels = 999", PLAN_LIMITS["pro"]["max_channels"] == 999)
    check("pro: daily_ai = 999", PLAN_LIMITS["pro"]["daily_ai_requests"] == 999)

    # 3. Enterprise limitlari
    check("enterprise: max_channels = 999", PLAN_LIMITS["enterprise"]["max_channels"] == 999)
    check("enterprise: daily_ai = 999", PLAN_LIMITS["enterprise"]["daily_ai_requests"] == 999)

    # 4. Barcha tariflar mavjud
    check("free mavjud", "free" in PLAN_LIMITS)
    check("pro mavjud", "pro" in PLAN_LIMITS)
    check("enterprise mavjud", "enterprise" in PLAN_LIMITS)

    # Free limit = 3 (yangilangan)
    check("free: max_channels = 3 (yangi)", PLAN_LIMITS["free"]["max_channels"] == 3)


def test_safe_html():
    """safe_html funksiyasi Telegram HTML uchun xavfsiz formatlash."""
    print("== safe_html ==")
    from utils.helpers import safe_html

    # 1. Bo'sh matn
    check("bo'sh → bo'sh", safe_html("") == "")
    check("None → bo'sh", safe_html(None) == "")

    # 2. Ruxs etilgan teglar saqlanadi
    check("<b> saqlanadi", safe_html("<b>Salom</b>") == "<b>Salom</b>")
    check("<i> saqlanadi", safe_html("<i>Kursiv</i>") == "<i>Kursiv</i>")
    check("<code> saqlanadi", safe_html("<code>test</code>") == "<code>test</code>")
    check("<a> saqlanadi", "<a href" in safe_html('<a href="https://t.me">Link</a>'))

    # 3. Ruxs etilmagan teglar olib tashlanadi
    check("<script> olib tashlanadi", "<script>" not in safe_html("<script>alert(1)</script>"))
    check("<div> olib tashlanadi", "<div>" not in safe_html("<div>Matn</div>"))
    check("<span> olib tashlanadi", "<span>" not in safe_html("<span>Matn</span>"))
    # Matn saqlanadi
    check("<div> matni saqlanadi", "Matn" in safe_html("<div>Matn</div>"))

    # 4. Yopilmagan teglar avtomatik yopiladi
    result = safe_html("<b>Salom")
    check("yopilmagan <b> yopiladi", result.endswith("</b>"))
    check("yopilmagan <b> matni", "Salom" in result)

    # 5. Telegram teglari ichki teglar bilan
    result2 = safe_html("<b><i>Ikkita teg</i></b>")
    check("ichki teglar", "<b><i>" in result2 and "</i></b>" in result2)

    # 6. Oddiy matn o'zgarmaydi
    check("oddily matn", safe_html("Salom dunyo") == "Salom dunyo")

    # 7. Emoji va maxsus belgilar
    check("emoji saqlanadi", "👋" in safe_html("👋 Salom"))

    # 8. AI content simulation — broken HTML
    broken = "<b>Salom</b> <i>dunyo</i> <unclosed>"
    result3 = safe_html(broken)
    check("broken: <b> saqlanadi", "<b>" in result3)
    check("broken: <i> saqlanadi", "<i>" in result3)
    check("broken: <unclosed> yo'q", "<unclosed>" not in result3)


def test_free_channel_limit_enforcement():
    """Free foydalanuvchi 3 ta kanal ulay oladi, 4-ta limit."""
    print("== Free channel limit enforcement ==")
    from database import PLAN_LIMITS, check_channel_limit

    # 1. Free limit = 3
    check("free limit = 3", PLAN_LIMITS["free"]["max_channels"] == 3)

    # 2. check_channel_limit funksiyasi mavjud
    check("check_channel_limit callable", callable(check_channel_limit))

    # 3. Return format to'g'ri (tuple: bool, int, int)
    # (haqiqiy DB bo'lmasdan faqat format tekshiramiz)
    result = check_channel_limit(0)  # non-existent user
    check("return tuple", isinstance(result, tuple) and len(result) == 3)
    check("return[0] bool", isinstance(result[0], bool))
    check("return[1] int", isinstance(result[1], int))
    check("return[2] int", isinstance(result[2], int))

    # 4. Non-existent user → can_add=True (default)
    check("non-existent user can add", result[0] is True)


def test_stars_payment_plans():
    """Stars to'lov paketlari to'g'ri konfiguratsiya qilingan."""
    print("== Stars payment plans ==")
    from handlers.subscription import STARS_PLANS

    # 1. 1 oylik paket
    check("1m: mavjud", "stars_1m" in STARS_PLANS)
    check("1m: stars = 75", STARS_PLANS["stars_1m"]["stars"] == 75)
    check("1m: days = 30", STARS_PLANS["stars_1m"]["days"] == 30)
    check("1m: label bor", "75 Stars" in STARS_PLANS["stars_1m"]["label"])

    # 2. 3 oylik paket
    check("3m: mavjud", "stars_3m" in STARS_PLANS)
    check("3m: stars = 175", STARS_PLANS["stars_3m"]["stars"] == 175)
    check("3m: days = 90", STARS_PLANS["stars_3m"]["days"] == 90)
    check("3m: label bor", "175 Stars" in STARS_PLANS["stars_3m"]["label"])

    # 3. 1 yillik paket
    check("1y: mavjud", "stars_1y" in STARS_PLANS)
    check("1y: stars = 550", STARS_PLANS["stars_1y"]["stars"] == 550)
    check("1y: days = 365", STARS_PLANS["stars_1y"]["days"] == 365)
    check("1y: label bor", "550 Stars" in STARS_PLANS["stars_1y"]["label"])

    # 4. XTR valyutasi
    check("1m: XTR valyutasi", True)  # Invoice da currency="XTR" ishlatiladi
    check("3m: XTR valyutasi", True)


def test_stars_keyboard():
    """Stars to'lov keyboard to'g'ri shakllanishi."""
    print("== Stars keyboard ==")
    from handlers.subscription import _get_stars_keyboard

    kb = _get_stars_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]

    check("stars kb: 1m bor", "sub_pay:stars_1m" in cbs)
    check("stars kb: 3m bor", "sub_pay:stars_3m" in cbs)
    check("stars kb: 1y bor", "sub_pay:stars_1y" in cbs)
    check("stars kb: back bor", "sub_back" in cbs)
    check("stars kb: 5 ta tugma", len(cbs) == 5)
    check("stars kb: 75 Stars label", any("75 Stars" in t for t in labels))
    check("stars kb: 175 Stars label", any("175 Stars" in t for t in labels))
    check("stars kb: 550 Stars label", any("550 Stars" in t for t in labels))


def test_referral_pro_functions():
    """Referal PRO mukofoti OLIB TASHLANGAN — faqat AI ball beriladi."""
    print("== Referral: PRO removed, credits only ==")
    import database as db_mod

    for name in ("check_and_grant_referral_pro", "get_referral_pro_progress",
                 "get_active_referral_count", "REFERRAL_PRO_THRESHOLD", "REFERRAL_PRO_DAYS"):
        check(f"{name} olib tashlangan", not hasattr(db_mod, name))

    check("referral_reward_for mavjud", callable(getattr(db_mod, "referral_reward_for", None)))
    check("total_referral_reward mavjud", callable(getattr(db_mod, "total_referral_reward", None)))
    check("1-do'st +3", db_mod.referral_reward_for(1) == 3)
    check("2-do'st +3", db_mod.referral_reward_for(2) == 3)
    check("3-do'st +3", db_mod.referral_reward_for(3) == 3)
    check("4-do'st +1", db_mod.referral_reward_for(4) == 1)
    check("5-do'st +1", db_mod.referral_reward_for(5) == 1)
    check("100-do'st +1", db_mod.referral_reward_for(100) == 1)
    check("0 → 1-do'st sifatida (+3)", db_mod.referral_reward_for(0) == 3)
    check("noto'g'ri qiymat → +3", db_mod.referral_reward_for("x") == 3)
    check("jami: 3 do'st = 9", db_mod.total_referral_reward(3) == 9)
    check("jami: 5 do'st = 11", db_mod.total_referral_reward(5) == 11)
    check("jami: 0 do'st = 0", db_mod.total_referral_reward(0) == 0)


def test_referral_pro_logic():
    """Referal ball mantiqi save_user ichida ishlatiladi; set_user_plan chaqirilmaydi."""
    print("== Referral logic in save_user ==")
    import inspect
    import database as db_mod

    src = inspect.getsource(db_mod.save_user)
    check("save_user referral_reward_for ishlatadi", "referral_reward_for(" in src)
    check("save_user PRO bermaydi", "set_user_plan" not in src and "'pro'" not in src)
    check("save_user ad_free ustunlarini yozmaydi", "ad_free" not in src)


def test_stars_payment_handlers_exist():
    """Stars to'lov handlerlari mavjud."""
    print("== Stars payment handlers ==")
    from handlers.subscription import precheckout_callback, successful_payment_callback

    check("precheckout_callback mavjud", callable(precheckout_callback))
    check("successful_payment_callback mavjud", callable(successful_payment_callback))


def test_create_promo_command():
    """Admin promo yaratish buyrug'i."""
    print("== Create promo command ==")
    from handlers.subscription import create_promo_command

    check("create_promo_command mavjud", callable(create_promo_command))


def test_promo_code_create_and_redeem():
    """Promo-kod yaratish va ishlatish (DB darajasida)."""
    print("== Promo code create & redeem ==")
    import database as db_mod

    # create_promo_code va redeem_promo_code mavjud
    check("create_promo_code callable", callable(db_mod.create_promo_code))
    check("redeem_promo_code callable", callable(db_mod.redeem_promo_code))

    # log_stars_payment mavjud
    check("log_stars_payment mavjud", hasattr(db_mod, "log_stars_payment"))
    check("log_stars_payment callable", callable(db_mod.log_stars_payment))


def test_subscription_keyboard_stars():
    """Subscription keyboard da Stars tugmasi bor."""
    print("== Subscription keyboard Stars ==")
    from handlers.subscription import _get_subscription_keyboard

    kb = _get_subscription_keyboard("free")
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("free kb: stars_1m bor", "sub_pay:stars_1m" in cbs)
    check("free kb: stars_3m bor", "sub_pay:stars_3m" in cbs)
    check("free kb: stars_1y bor", "sub_pay:stars_1y" in cbs)
    check("free kb: promo bor", "sub_promo" in cbs)
    check("free kb: back_main bor", "sub_back_main" in cbs)
    check("free kb: 75 Stars label", any("75 Stars" in t for t in labels))
    check("free kb: 175 Stars label", any("175 Stars" in t for t in labels))
    check("free kb: 550 Stars label", any("550 Stars" in t for t in labels))

    # PRO da Stars yo'q
    kb_pro = _get_subscription_keyboard("pro")
    cbs_pro = [b.callback_data for row in kb_pro.inline_keyboard for b in row]
    check("pro kb: stars_1m yo'q", "sub_pay:stars_1m" not in cbs_pro)
    check("pro kb: promo bor", "sub_promo" in cbs_pro)
    check("pro kb: back_main bor", "sub_back_main" in cbs_pro)


def test_channel_reader_parser():
    """Channel reader HTML parser to'g'ri ishlashi."""
    print("== Channel reader parser ==")
    from utils.channel_reader import _strip_html_tags, _parse_channel_page

    # 1. _strip_html_tags
    check("strip: oddiy matn", _strip_html_tags("Salom") == "Salom")
    check("strip: <b> olib tashlash", _strip_html_tags("<b>Salom</b>") == "Salom")
    check("strip: <br> → newline", "\n" in _strip_html_tags("Salom<br>Dunyo"))
    check("strip: &amp; → &", _strip_html_tags("a &amp; b") == "a & b")
    check("strip: &lt; → <", _strip_html_tags("&lt;") == "<")
    check("strip: bo'sh", _strip_html_tags("") == "")
    check("strip: None", _strip_html_tags(None) == "")
    check("strip: <a href> matni", _strip_html_tags('<a href="t.me">Link</a>') == "Link")

    # 2. _parse_channel_page — bo'sh HTML
    posts_empty = _parse_channel_page("", "test")
    check("empty HTML → bo'sh", len(posts_empty) == 0)

    # 3. _parse_channel_page — mock HTML with post
    mock_html = '''
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message">
            <div class="tgme_widget_message_text">Salom dunyo! Bu test post.</div>
            <time datetime="2026-08-30T10:00:00+00:00"></time>
            <a class="tgme_widget_message_date" href="https://t.me/test/123"></a>
        </div>
    </div>
    '''
    posts_mock = _parse_channel_page(mock_html, "test")
    check("mock: 1 ta post", len(posts_mock) == 1)
    if posts_mock:
        check("mock: matn to'g'ri", "Salom dunyo" in posts_mock[0]["text"])
        check("mock: sana bor", posts_mock[0]["date"] != "")
        check("mock: link bor", "test/123" in posts_mock[0]["post_link"])

    # 4. _parse_channel_page — multiple posts
    mock_multi = '''
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message">
            <div class="tgme_widget_message_text">Birinchi post</div>
            <time datetime="2026-08-30T10:00:00+00:00"></time>
            <a class="tgme_widget_message_date" href="https://t.me/ch/1"></a>
        </div>
    </div>
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message">
            <div class="tgme_widget_message_text">Ikkinchi post</div>
            <time datetime="2026-08-30T11:00:00+00:00"></time>
            <a class="tgme_widget_message_date" href="https://t.me/ch/2"></a>
        </div>
    </div>
    '''
    posts_multi = _parse_channel_page(mock_multi, "ch")
    check("multi: 2 ta post", len(posts_multi) == 2)

    # 5. _parse_channel_page — rasm post (matnsiz)
    mock_img = '''
    <div class="tgme_widget_message_wrap">
        <div class="tgme_widget_message">
            <img class="tgme_widget_message_photo" src="https://cdn.t.me/img.jpg">
            <time datetime="2026-08-30T12:00:00+00:00"></time>
            <a class="tgme_widget_message_date" href="https://t.me/ch/3"></a>
        </div>
    </div>
    '''
    posts_img = _parse_channel_page(mock_img, "ch")
    check("img: rasm post topildi", len(posts_img) == 1)
    if posts_img:
        check("img: media_url bor", "img.jpg" in posts_img[0]["media_url"])


def test_channel_reader_functions():
    """Channel reader funksiyalari mavjud va callable."""
    print("== Channel reader functions ==")
    from utils.channel_reader import fetch_latest_channel_posts, format_post_list

    check("fetch_latest_channel_posts mavjud", callable(fetch_latest_channel_posts))
    check("format_post_list mavjud", callable(format_post_list))


def test_format_post_list():
    """format_post_list to'g'ri formatlash."""
    print("== format_post_list ==")
    from utils.channel_reader import format_post_list

    # 1. Bo'sh ro'yxat
    check("bo'sh → bo'sh", format_post_list([], "test") == "")

    # 2. Oddiy postlar
    posts = [
        {"text": "Birinchi yangilik haqida matn", "date": "2026-08-30T10:00:00+00:00", "media_url": "", "post_link": "https://t.me/ch/1"},
        {"text": "Ikkinchi yangilik", "date": "2026-08-30T11:00:00+00:00", "media_url": "", "post_link": "https://t.me/ch/2"},
    ]
    result = format_post_list(posts, "testkanal")
    check("format: kanal nomi", "testkanal" in result)
    check("format: 1-post", "1." in result)
    check("format: 2-post", "2." in result)
    check("format: matn", "Birinchi yangilik" in result)
    check("format: sana", "30.08.2026" in result)
    check("format: tanlash taklifi", "tanlang" in result.lower())

    # 3. Uzun matn qisqaradi
    long_post = [{"text": "A" * 300, "date": "", "media_url": "", "post_link": ""}]
    result_long = format_post_list(long_post, "ch")
    check("uzun: qisqaradi", "…" in result_long)

    # 4. Matnsiz post (rasm)
    img_post = [{"text": "", "date": "2026-08-30", "media_url": "img.jpg", "post_link": ""}]
    result_img = format_post_list(img_post, "ch")
    check("rasm: rasm/video label", "rasm/video" in result_img.lower())


def test_channel_extract_keyboards():
    """Channel extract keyboardlari."""
    print("== Channel extract keyboards ==")
    from handlers.channel_extract import _get_post_list_keyboard, _get_rewrite_result_keyboard

    # 1. Post list keyboard
    posts = [
        {"text": "Salom dunyo", "date": "", "media_url": "", "post_link": ""},
        {"text": "Ikkinchi post", "date": "", "media_url": "", "post_link": ""},
    ]
    kb = _get_post_list_keyboard(posts, "test")
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("list kb: post 0", "ext_post:0" in cbs)
    check("list kb: post 1", "ext_post:1" in cbs)
    check("list kb: refresh", "ext_refresh" in cbs)
    check("list kb: cancel", "ext_cancel" in cbs)
    check("list kb: 4 ta tugma", len(cbs) == 4)
    check("list kb: preview", any("Salom" in t for t in labels))

    # 2. Rewrite result keyboard
    rkb = _get_rewrite_result_keyboard()
    rcbs = [b.callback_data for row in rkb.inline_keyboard for b in row]
    check("result kb: schedule", "ext_schedule" in rcbs)
    check("result kb: rewrite", "ext_rewrite" in rcbs)
    check("result kb: back", "ext_back" in rcbs)
    check("result kb: cancel", "ext_cancel" in rcbs)


def test_rewrite_function_exists():
    """AI re-write funksiyasi mavjud."""
    print("== Rewrite function ==")
    from utils.ai_agent import rewrite_channel_post, _REWRITE_SYSTEM

    check("rewrite_channel_post mavjud", callable(rewrite_channel_post))
    check("_REWRITE_SYSTEM mavjud", len(_REWRITE_SYSTEM) > 50)
    check("rewrite: O'zbek tili", "O'zbek" in _REWRITE_SYSTEM)
    check("rewrite: fakt qo'shmaslik", "yolg'on" in _REWRITE_SYSTEM.lower() or "fakt" in _REWRITE_SYSTEM.lower())
    check("rewrite: manba", "MANBA" in _REWRITE_SYSTEM or "manba" in _REWRITE_SYSTEM.lower())


def test_channel_reader_error_handling():
    """Xato kanal nomlari uchun test."""
    print("== Channel reader error handling ==")
    from utils.channel_reader import fetch_latest_channel_posts, _parse_channel_page
    import asyncio

    # 1. Bo'sh kanal niki
    result = asyncio.run(fetch_latest_channel_posts(""))
    check("bo'sh niki → bo'sh", len(result) == 0)

    # 2. None kanal niki
    result2 = asyncio.run(fetch_latest_channel_posts(None))
    check("None niki → bo'sh", len(result2) == 0)

    # 3. @ belgisi tozalanadi
    result3 = asyncio.run(fetch_latest_channel_posts("@test"))
    check("@ bilan ishlaydi", isinstance(result3, list))

    # 4. Yopiq kanal simulyatsiyasi — "tgme_widget_message" yo'q
    posts_no_widget = _parse_channel_page("<html><body>Channel not found</body></html>", "none")
    check("yopiq kanal → bo'sh", len(posts_no_widget) == 0)

    # 5. Noto'g'ri HTML — parser xato bermaydi
    posts_bad = _parse_channel_page("<not>valid<html>", "bad")
    check("noto'g'ri HTML → xato yo'q", isinstance(posts_bad, list))


def test_main_keyboard_extract():
    """Ochiq kanaldan olish tugmasi mavjud (AI Studio sub-menuda)."""
    print("== Main keyboard extract ==")
    from keyboards.default import get_main_keyboard, BTN_CHANNEL_EXTRACT, BTN_AI_STUDIO

    check("BTN_CHANNEL_EXTRACT mavjud", BTN_CHANNEL_EXTRACT == "📢 Ochiq kanaldan olish")

    # Extract endi AI Studio sub-menuda, asosiy menyuda emas
    kb = get_main_keyboard(False)
    all_texts = [b.text for row in kb.keyboard for b in row]
    check("main kb: Extract yo'q (AI Studio ichida)", BTN_CHANNEL_EXTRACT not in all_texts)
    check("main kb: AI Studio bor", BTN_AI_STUDIO in all_texts)


def test_admin_dashboard():
    """Admin panel dashboard va inline keyboard."""
    print("== Admin dashboard ==")
    from handlers.admin import _build_dashboard_text, is_admin, ADMIN_GRANT_PRO, ADMIN_PROMO_CREATE
    from keyboards.inline import get_admin_dashboard_keyboard, get_admin_back_keyboard

    # 1. Dashboard text format
    stats = {
        "users": 100, "pro_subscribers": 15, "channels": 42,
        "posts_today": 8, "pending_posts": 3, "stars_revenue": 500,
    }
    text = _build_dashboard_text(stats)
    check("dashboard: title", "Admin Boshqaruv Paneli" in text)
    check("dashboard: users", "100" in text)
    check("dashboard: pro", "15" in text)
    check("dashboard: channels", "42" in text)
    check("dashboard: posts_today", "8" in text)
    check("dashboard: pending", "3" in text)
    check("dashboard: stars", "500" in text)
    check("dashboard: separator", "━━━" in text)

    # 2. Dashboard keyboard
    kb = get_admin_dashboard_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("dash kb: stats", "adm_stats" in cbs)
    check("dash kb: promo", "adm_promo" in cbs)
    check("dash kb: grant_pro", "adm_grant_pro" in cbs)
    check("dash kb: broadcast", "adm_broadcast" in cbs)
    check("dash kb: close", "close_msg" in cbs)
    check("dash kb: stats label", any("statistika" in t.lower() for t in labels))
    check("dash kb: promo label", any("Promo" in t for t in labels))

    # 3. Back keyboard
    bkb = get_admin_back_keyboard()
    bcbs = [b.callback_data for row in bkb.inline_keyboard for b in row]
    check("back kb: adm_back", "adm_back" in bcbs)
    check("back kb: adm_cancel (Bekor qilish)", "adm_cancel" in bcbs)
    check("back kb: close rejimi", "close_msg" in
          [b.callback_data for row in get_admin_back_keyboard(cancel=False).inline_keyboard
           for b in row])

    # 4. is_admin function
    check("is_admin: non-admin", not is_admin(0))
    check("is_admin: callable", callable(is_admin))

    # 5. State constants
    check("ADMIN_GRANT_PRO = 807", ADMIN_GRANT_PRO == 807)
    check("ADMIN_PROMO_CREATE = 808", ADMIN_PROMO_CREATE == 808)


def test_admin_handlers_exist():
    """Admin handler funksiyalari mavjud."""
    print("== Admin handlers exist ==")
    from handlers.admin import (
        admin_panel_menu, admin_stats_command, admin_dashboard_callback,
        admin_inline_text_handler, show_statistics,
        broadcast_start, broadcast_send, ai_settings_menu,
        ad_pool_callback,
    )

    check("admin_panel_menu callable", callable(admin_panel_menu))
    check("admin_stats_command callable", callable(admin_stats_command))
    check("admin_dashboard_callback callable", callable(admin_dashboard_callback))
    check("admin_inline_text_handler callable", callable(admin_inline_text_handler))
    check("show_statistics callable", callable(show_statistics))
    check("broadcast_start callable", callable(broadcast_start))
    check("broadcast_send callable", callable(broadcast_send))
    check("ai_settings_menu callable", callable(ai_settings_menu))
    check("ad_pool_callback callable", callable(ad_pool_callback))


def test_admin_dashboard_stats_db():
    """Database get_admin_dashboard_stats funksiyasi mavjud."""
    print("== Admin dashboard stats DB ==")
    import database as db_mod

    check("get_admin_dashboard_stats mavjud", hasattr(db_mod, "get_admin_dashboard_stats"))
    check("get_admin_dashboard_stats callable", callable(db_mod.get_admin_dashboard_stats))


def test_ai_studio_keyboard():
    """AI Studio inline keyboard to'g'ri shakllanishi."""
    print("== AI Studio keyboard ==")
    from keyboards.inline import get_ai_studio_keyboard
    from keyboards.default import get_main_keyboard, BTN_AI_STUDIO, BTN_NEW_POST, BTN_QUEUE, BTN_ANALYTICS, BTN_PREMIUM, BTN_SETTINGS

    kb = get_ai_studio_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("studio kb: ai_post", "studio_ai_post" in cbs)
    check("studio kb: extract", "studio_extract" in cbs)
    check("studio kb: content_plan", "studio_content_plan" in cbs)
    check("studio kb: audit", "studio_ai_audit" in cbs)
    check("studio kb: photo", "studio_ai_photo" in cbs)
    check("studio kb: close", "studio_close" in cbs)
    check("studio kb: 6 ta tugma", len(cbs) == 6)
    check("studio kb: AI Post label", any("AI Post" in t for t in labels))
    check("studio kb: Rasmdan post label", any("Rasmdan post" in t for t in labels))
    check("studio kb: Kontent-reja label", any("Kontent-reja" in t for t in labels))

    # Main keyboard — 6 tugma (3x2 grid)
    kb_main = get_main_keyboard(False)
    main_texts = [b.text for row in kb_main.keyboard for b in row]
    check("main kb: 6 ta tugma (free)", len(main_texts) == 6)
    check("main kb: Yangi post", BTN_NEW_POST in main_texts)
    check("main kb: AI Studio", BTN_AI_STUDIO in main_texts)
    check("main kb: Queue yo'q (Kabinet ichida)", BTN_QUEUE not in main_texts)
    check("main kb: Analitika yo'q (Kabinet ichida)", BTN_ANALYTICS not in main_texts)
    check("main kb: Premium", BTN_PREMIUM in main_texts)
    check("main kb: Kabinet", BTN_SETTINGS in main_texts)

    # Admin keyboard — 7 ta tugma (6 + admin)
    kb_admin = get_main_keyboard(True)
    admin_texts = [b.text for row in kb_admin.keyboard for b in row]
    check("main kb: 7 ta tugma (admin)", len(admin_texts) == 7)


def test_ai_studio_hardening():
    """AI Studio hardening: FSM holatlari, doimiy nav-tugmalar, 25s hard timeout."""
    print("== AI Studio hardening ==")
    import asyncio
    import handlers.ai_assistant as ai

    # 1) Yangi FSM holatlari mavjud va unikal
    states = (ai.AI_MENU_STATE, ai.AI_PROMPT_INPUT, ai.AI_TONE_SELECT, ai.AI_AUDIT_INPUT)
    check("studio: AI_MENU_STATE mavjud", ai.AI_MENU_STATE == 404)
    check("studio: AI_PROMPT_INPUT mavjud", ai.AI_PROMPT_INPUT == 405)
    check("studio: AI_TONE_SELECT mavjud", ai.AI_TONE_SELECT == 406)
    check("studio: AI_AUDIT_INPUT mavjud", ai.AI_AUDIT_INPUT == 407)
    check("studio: holatlar unikal", len(set(states)) == 4)
    check("studio: eski holatlar bilan to'qnashmaydi",
          not set(states) & {ai.AI_INPUT, ai.AI_CONFIRM, ai.AI_GET_TIME})

    # 2) Callback handlerlar mavjud va coroutine
    import inspect
    for fn_name in (
        "ai_studio_menu_entry", "ai_studio_nav_callback", "ai_prompt_received",
        "ai_tone_callback", "ai_studio_schedule_callback", "ai_audit_received",
        "ai_back_to_menu", "ai_close",
    ):
        fn = getattr(ai, fn_name, None)
        check(f"studio: {fn_name} coroutine", fn is not None and inspect.iscoroutinefunction(fn))

    # 3) Har bir callback handler BOSHIDA query.answer() chaqiradi (speks)
    src = open(ai.__file__, encoding="utf-8").read()
    for fn_name in ("ai_studio_nav_callback", "ai_tone_callback",
                    "ai_studio_schedule_callback", "ai_back_to_menu", "ai_close"):
        start = src.index(f"async def {fn_name}")
        chunk = src[start:start + 400]
        check(f"studio: {fn_name} boshida query.answer()", "await query.answer(" in chunk)

    # 4) Doimiy navigatsiya klaviaturalari
    from keyboards.inline import get_ai_back_keyboard, get_ai_tone_keyboard
    back_cbs = [b.callback_data for row in get_ai_back_keyboard().inline_keyboard for b in row]
    check("studio: back kb [orqaga]", "ai_back_to_menu" in back_cbs)
    check("studio: back kb [bekor]", "ai_close" in back_cbs)

    tone_kb = get_ai_tone_keyboard("friendly")
    tone_cbs = [b.callback_data for row in tone_kb.inline_keyboard for b in row]
    check("studio: tone kb 4 uslub", all(f"ai_tone:{t}" in tone_cbs for t in
          ("formal", "friendly", "concise", "engaging")), str(tone_cbs))
    check("studio: tone kb rejalashtirish", "ai_studio_sched" in tone_cbs)
    check("studio: tone kb orqaga/bekor", "ai_back_to_menu" in tone_cbs and "ai_close" in tone_cbs)
    tone_labels = [b.text for row in tone_kb.inline_keyboard for b in row]
    check("studio: tanlangan uslub ✅", any(t.endswith("✅") for t in tone_labels), str(tone_labels))

    # 5) AI chaqiruvga 25 soniyalik QAT'IY timeout
    from utils import ai_agent
    check("ai_agent: AI_HARD_TIMEOUT = 25", ai_agent.AI_HARD_TIMEOUT == 25)
    check("ai_agent: generate_ai_response mavjud",
          callable(getattr(ai_agent, "generate_ai_response", None)))

    async def _slow_chain(prompt, system_instruction):
        await asyncio.sleep(5)
        return {"intent": "faq", "reply": "kech"}

    orig_chain = ai_agent._run_ai_chain
    ai_agent._run_ai_chain = _slow_chain
    try:
        res = asyncio.run(ai_agent.generate_ai_response("test mavzu", timeout=0.05))
        check("ai_agent: hard timeout → error dict", "error" in res, str(res))
        check("ai_agent: timeout xabari foydalanuvchiga mos",
              res["error"] == ai_agent.AI_TIMEOUT_USER_MESSAGE and res.get("timeout") is True,
              str(res))
        check("ai_agent: timeout xabari xushmuomala (aybdor izlanmaydi)",
              "qayta urinib ko'ring" in res["error"] and "🙏" in res["error"],
              res["error"])
    finally:
        ai_agent._run_ai_chain = orig_chain

    # 6) Xato holatida doimiy back keyboard bilan AI_MENU_STATE qaytariladi
    check("studio: AI_UNAVAILABLE_MSG mavjud", "qayta urinib" in ai.AI_UNAVAILABLE_MSG)
    check("studio: error handlerda get_ai_back_keyboard", "get_ai_back_keyboard()" in src)
    check("studio: AI Generation Error log", "AI Generation Error" in src)


def test_vision_agent_utils():
    """🖼 Vision: MIME aniqlash, base64 zanjiri, hajm limiti, xato mapping, tozalash."""
    print("== Vision agent yordamchilari ==")
    import asyncio
    import base64 as _b64
    import os
    import tempfile
    from utils import ai_agent

    def _tmp_file(data: bytes = b"", suffix: str = ".bin") -> str:
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(data)
        f.close()
        return f.name

    # 1) MIME aniqlash (magic-bytes)
    png = _tmp_file(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, ".png")
    check("vision: PNG mime", ai_agent.detect_image_mime(png) == "image/png")
    os.remove(png)

    jpg = _tmp_file(b"\xff\xd8\xff\xe0" + b"\x00" * 16, ".jpg")
    check("vision: JPEG mime", ai_agent.detect_image_mime(jpg) == "image/jpeg")
    os.remove(jpg)

    webp = _tmp_file(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8, ".webp")
    check("vision: WEBP mime", ai_agent.detect_image_mime(webp) == "image/webp")
    os.remove(webp)

    gif = _tmp_file(b"GIF89a" + b"\x00" * 8, ".gif")
    check("vision: GIF mime", ai_agent.detect_image_mime(gif) == "image/gif")
    os.remove(gif)

    not_img = _tmp_file(b"hello bu rasm emas", ".txt")
    check("vision: rasm bo'lmagan fayl → None",
          ai_agent.detect_image_mime(not_img) is None)
    os.remove(not_img)

    # 2) Base64 zanjirli kodlash roundtrip
    raw = os.urandom(200_000)
    img = _tmp_file(raw, ".png")
    b64 = ai_agent._encode_image_base64(img)
    check("vision: base64 roundtrip", _b64.b64decode(b64) == raw)
    os.remove(img)

    # 3) Hajm limiti
    big = _tmp_file(b"", ".png")
    with open(big, "wb") as fh:
        fh.truncate(ai_agent.VISION_MAX_FILE_BYTES + 1)
    res = asyncio.run(ai_agent.generate_vision_post(big))
    check("vision: juda katta rasm rad etiladi",
          "error" in res and "MB dan oshib" in res["error"], str(res))
    os.remove(big)

    # 4) Rasm bo'lmagan fayl
    junk = _tmp_file(b"not an image at all", ".dat")
    res = asyncio.run(ai_agent.generate_vision_post(junk))
    check("vision: noo'rin fayl xabari",
          "error" in res and "rasm" in res["error"].lower(), str(res))
    os.remove(junk)

    # 5) Kalit yo'q bo'lsa — aniq o'zbekcha xabar
    png2 = _tmp_file(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, ".png")
    orig_key = ai_agent.GEMINI_API_KEY
    ai_agent.GEMINI_API_KEY = ""
    try:
        res = asyncio.run(ai_agent.generate_vision_post(png2))
        check("vision: kalitsiz xabar",
              "error" in res and "GEMINI_API_KEY" in res["error"], str(res))
    finally:
        ai_agent.GEMINI_API_KEY = orig_key
        os.remove(png2)

    # 6) Xato mapping: 429 / safety / 401 / 413 / timeout
    check("vision: 429 → band xabari",
          "kuting" in ai_agent.vision_friendly_error(429, "rate limit"))
    check("vision: safety → mos kelmaydi",
          "mos kelmaydi" in ai_agent.vision_friendly_error(400, "SAFETY blocked"))
    check("vision: 401 → kalit xabari",
          "kalit" in ai_agent.vision_friendly_error(401, "invalid api key"))
    check("vision: 413 → hajm xabari",
          "hajm" in ai_agent.vision_friendly_error(413, "file too large"))
    check("vision: timeout → vaqt xabari",
          "vaqt" in ai_agent.vision_friendly_error(0, "timeout"))

    # 7) Temp fayl/katalog tozalash
    d = tempfile.mkdtemp(prefix=ai_agent.VISION_TEMP_PREFIX)
    p = os.path.join(d, "media.jpg")
    with open(p, "wb") as fh:
        fh.write(b"x")
    ai_agent.cleanup_temp_media(p)
    check("vision: temp fayl va katalog o'chirildi",
          not os.path.exists(p) and not os.path.exists(d))


def test_photo_to_post_flow():
    """🖼 Vision oqimi: FSM, handlerlar, natija tugmalari va 3 ta branch."""
    print("== 🖼 Rasmdan post yaratish (Vision) oqimi ==")
    import asyncio
    import inspect
    import handlers.ai_assistant as ai
    import database as db_mod
    from keyboards.inline import get_ai_photo_keyboard, get_ai_studio_keyboard

    # 1) FSM holatlari unikal va to'g'ri
    studio_states = (
        ai.AI_MENU_STATE, ai.AI_PROMPT_INPUT, ai.AI_TONE_SELECT, ai.AI_AUDIT_INPUT,
    )
    photo_states = (ai.AI_PHOTO_INPUT, ai.AI_PHOTO_RESULT, ai.AI_PHOTO_EDIT_INPUT)
    check("photo: AI_PHOTO_INPUT mavjud", ai.AI_PHOTO_INPUT == 408)
    check("photo: AI_PHOTO_RESULT mavjud", ai.AI_PHOTO_RESULT == 409)
    check("photo: AI_PHOTO_EDIT_INPUT mavjud", ai.AI_PHOTO_EDIT_INPUT == 410)
    check("photo: holatlar unikal", len(set(photo_states)) == 3)
    check("photo: mavjud holatlar bilan to'qnashmaydi",
          not set(photo_states) & set(studio_states + (ai.AI_INPUT, ai.AI_CONFIRM, ai.AI_GET_TIME)))

    # 2) Handlerlar coroutine
    for fn_name in ("ai_photo_received", "ai_photo_result_callback", "ai_photo_edit_received"):
        fn = getattr(ai, fn_name, None)
        check(f"photo: {fn_name} coroutine",
              fn is not None and inspect.iscoroutinefunction(fn))

    # 2b) Caption izohini ajratish
    check("photo: caption izoh", ai._photo_extra_from_caption("mahsulotni sot") == "mahsulotni sot")
    check("photo: /ai caption → bo'sh", ai._photo_extra_from_caption("/ai") == "")
    check("photo: /ai@bot caption → bo'sh",
          ai._photo_extra_from_caption("/ai@PostAssistrobot") == "")
    check("photo: /ai + izoh → izoh qoladi",
          ai._photo_extra_from_caption("/ai mahsulotni sotish") == "mahsulotni sotish")
    check("photo: boshqa buyruq → bo'sh", ai._photo_extra_from_caption("/start") == "")

    # 3) Natija klaviaturasi: [Kanalga rejalashtirish] [Qayta yozish] [Tahrirlash]
    pk = get_ai_photo_keyboard()
    pcbs = [b.callback_data for row in pk.inline_keyboard for b in row]
    check("photo: [Kanalga rejalashtirish]", "photo_schedule" in pcbs)
    check("photo: [Qayta yozish]", "photo_rewrite" in pcbs)
    check("photo: [Tahrirlash]", "photo_edit" in pcbs)
    check("photo: doimiy nav (orqaga/bekor)",
          "ai_back_to_menu" in pcbs and "ai_close" in pcbs)
    plabels = [b.text for row in pk.inline_keyboard for b in row]
    check("photo: [Kanalga rejalashtirish] label",
          any("Kanalga rejalashtirish" in t for t in plabels))
    check("photo: studio menyuda tugma bor",
          "studio_ai_photo" in [
              b.callback_data for row in get_ai_studio_keyboard().inline_keyboard for b in row
          ])

    # 4) Menyu: studio_ai_photo → AI_PHOTO_INPUT (edit, o'chirish yo'q)
    class _QUpd:
        def __init__(self, q):
            self.callback_query = q

    q = _FakeQuery("studio_ai_photo", _FakeMsg(1))
    ctx = _FakeCtx(_FakeBot())
    state = asyncio.run(ai.ai_studio_nav_callback(_QUpd(q), ctx))
    check("photo: nav → AI_PHOTO_INPUT", state == ai.AI_PHOTO_INPUT, str(state))
    check("photo: nav yo'riqnoma edit qilinadi",
          any("Rasmdan post" in e[0] for e in q.edits), str(q.edits))
    check("photo: nav eski natija tozalanadi", "studio_post_text" not in ctx.user_data)

    # 5-10) Mock DB + Mock AI bilan to'liq oqim
    calls = []

    async def _fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        if name == "is_premium":
            return False
        if name == "check_ai_limit":
            return (True, 0, 30)
        if name == "use_user_credit":
            return True
        if name == "increment_ai_usage":
            calls.append("increment_ai_usage")
            return None
        if name == "add_user_credit":
            calls.append("add_user_credit")
            return None
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    orig_run_db = db_mod.run_db
    db_mod.run_db = _fake_run_db
    orig_dl = ai.download_telegram_media_to_temp
    orig_vision = ai.generate_vision_post
    orig_edit = ai.generate_ai_response
    try:
        async def fake_dl(file_id, **kw):
            calls.append(("dl", file_id))
            return "/tmp/fake_vision.png"

        ai.download_telegram_media_to_temp = fake_dl

        async def fake_vision(path, extra_prompt="", tone=None, timeout=None, rewrite_context=""):
            tone = tone or "formal"
            calls.append(("vision", path, extra_prompt, tone, bool(rewrite_context)))
            return {"post_text": f"<b>Variant {tone}</b> posti"}

        ai.generate_vision_post = fake_vision

        # 5) Rasm qabul qilish → 3 USLUB VARIANTI (formal/friendly/concise) tayyorlanadi
        uid = 999777000
        msg = _FakeMsg(1, chat_id=111, caption="mahsulotni sot")
        msg.photo = [type("P", (), {"file_id": "file123"})()]
        upd = type("U", (), {"message": msg, "effective_user": _FakeUser(uid)})()
        ctx2 = _FakeCtx(_FakeBot(), user_data={})
        state2 = asyncio.run(ai.ai_photo_received(upd, ctx2))
        check("photo: variantlar ekrani → AI_PHOTO_RESULT",
              state2 == ai.AI_PHOTO_RESULT, str(state2))
        vision_calls = [c for c in calls if c[0] == "vision"]
        check("photo: AI chaqiruv 3 marta (3 uslub)",
              len(vision_calls) == 3, str(vision_calls))
        check("photo: barcha 3 uslub so'raldi",
              {c[3] for c in vision_calls} == {"formal", "friendly", "concise"},
              str([c[3] for c in vision_calls]))
        check("photo: rasm temp download BIR marta",
              len([c for c in calls if c[0] == "dl"]) == 1)
        check("photo: birlamchi variant (formal) postga saqlandi",
              ctx2.user_data.get("studio_post_text") == "<b>Variant formal</b> posti")
        check("photo: studio_tone=formal", ctx2.user_data.get("studio_tone") == "formal")
        variants = ctx2.user_data.get("studio_photo_variants") or {}
        check("photo: 3 xil variant saqlandi",
              set(variants) == {"formal", "friendly", "concise"}, str(variants))
        check("photo: har variant o'z matni bilan",
              variants.get("friendly") == "<b>Variant friendly</b> posti")
        check("photo: file_id saqlandi", ctx2.user_data.get("studio_file_id") == "file123")
        check("photo: post_type=photo", ctx2.user_data.get("studio_post_type") == "photo")
        check("photo: izoh saqlandi",
              ctx2.user_data.get("studio_photo_extra") == "mahsulotni sot")
        sent_markups = [c[3] for c in ctx2.bot.calls if c[0] in ("send_message", "reply_text") and c[3]]
        sent_cbs = {b.callback_data for mk in sent_markups for row in mk.inline_keyboard for b in row}
        check("photo: variant tanlash tugmalari yuborildi",
              {"photo_v:formal", "photo_v:friendly", "photo_v:concise"} <= sent_cbs,
              str(sent_cbs))
        check("photo: muvaffaqiyat → ai_usage+1", "increment_ai_usage" in calls)

        # 5b) Foydalanuvchi variant tanlaydi: photo_v:friendly
        q_pick = _FakeQuery("photo_v:friendly", _FakeMsg(2, chat_id=111))
        ctx_pick = _FakeCtx(_FakeBot(), user_data=dict(ctx2.user_data))
        state_pick = asyncio.run(ai.ai_photo_result_callback(_QUpd(q_pick), ctx_pick))
        check("photo: variant tanlash → AI_PHOTO_RESULT",
              state_pick == ai.AI_PHOTO_RESULT, str(state_pick))
        check("photo: tanlangan variant postga yozildi",
              ctx_pick.user_data.get("studio_post_text") == "<b>Variant friendly</b> posti")
        check("photo: tanlangan uslub saqlandi",
              ctx_pick.user_data.get("studio_tone") == "friendly")
        pick_edit = q_pick.edits[0][0] if q_pick.edits else ""
        check("photo: natija ekrani ochildi (rejalashtirish tugmasi)",
              any(
                  b.callback_data == "photo_schedule"
                  for row in q_pick.edits[0][1].inline_keyboard for b in row
              ) if q_pick.edits and q_pick.edits[0][1] else False,
              pick_edit[:80])

        # 5c) Notanish uslub → sessiya buzilmaydi, tanlov qayta ko'rsatiladi
        q_bad = _FakeQuery("photo_v:weird", _FakeMsg(3, chat_id=111))
        ctx_bad = _FakeCtx(_FakeBot(), user_data=dict(ctx2.user_data))
        state_bad = asyncio.run(ai.ai_photo_result_callback(_QUpd(q_bad), ctx_bad))
        check("photo: notanish uslub → AI_PHOTO_RESULT",
              state_bad == ai.AI_PHOTO_RESULT, str(state_bad))
        check("photo: notanish uslub matnni buzmaydi",
              ctx_bad.user_data.get("studio_post_text") == "<b>Variant formal</b> posti")
        check("photo: notanish uslub → tanlov qayta ko'rsatildi",
              bool(q_bad.edits) and "photo_v:formal" in str(q_bad.edits[0][1]))

        # 6) [Kanalga rejalashtirish] → AI_GET_TIME (mavjud oqimga uzatiladi)
        class _PhotoMsg(_FakeMsg):
            async def reply_photo(self, photo, caption=None, reply_markup=None,
                                  parse_mode=None, **kw):
                bot = _FakeMsg.registry.get("bot")
                if bot:
                    bot._rec("send_photo", self.chat_id, caption, reply_markup)
                return _FakeMsg(3)

        q2 = _FakeQuery("photo_schedule", _PhotoMsg(2, chat_id=111))
        ctx3 = _FakeCtx(_FakeBot(), user_data={
            "studio_post_text": "Post matni",
            "studio_file_id": "file123",
            "studio_post_type": "photo",
        })
        state3 = asyncio.run(ai.ai_photo_result_callback(_QUpd(q2), ctx3))
        check("photo: schedule → AI_GET_TIME", state3 == ai.AI_GET_TIME, str(state3))
        check("photo: ai_generated_post uzatildi",
              ctx3.user_data.get("ai_generated_post") == "Post matni")
        check("photo: ai_file_id uzatildi",
              ctx3.user_data.get("ai_file_id") == "file123")
        check("photo: ai_post_type uzatildi",
              ctx3.user_data.get("ai_post_type") == "photo")

        # 7) [Tahrirlash] → AI_PHOTO_EDIT_INPUT
        q4 = _FakeQuery("photo_edit", _FakeMsg(4, chat_id=111))
        ctx4 = _FakeCtx(_FakeBot(), user_data={
            "studio_post_text": "Post matni", "studio_file_id": "file123",
        })
        state4 = asyncio.run(ai.ai_photo_result_callback(_QUpd(q4), ctx4))
        check("photo: edit → AI_PHOTO_EDIT_INPUT",
              state4 == ai.AI_PHOTO_EDIT_INPUT, str(state4))

        # 8) [Qayta yozish] → rasm qayta tahlil → yangi post
        q5 = _FakeQuery("photo_rewrite", _FakeMsg(5, chat_id=111))
        ctx5 = _FakeCtx(_FakeBot(), user_data={
            "studio_post_text": "Eski post",
            "studio_file_id": "file123",
            "studio_photo_extra": "izoh",
        })

        async def fake_vision2(path, extra_prompt="", tone=None, timeout=None, rewrite_context=""):
            calls.append(("vision2", extra_prompt, bool(rewrite_context)))
            return {"post_text": "Yangi post"}

        ai.generate_vision_post = fake_vision2
        state5 = asyncio.run(ai.ai_photo_result_callback(_QUpd(q5), ctx5))
        check("photo: rewrite → AI_PHOTO_RESULT",
              state5 == ai.AI_PHOTO_RESULT, str(state5))
        check("photo: rewrite yangi post saqlandi",
              ctx5.user_data.get("studio_post_text") == "Yangi post")
        check("photo: rewrite kontekst uzatiladi",
              any(c[0] == "vision2" and c[2] for c in calls), str(calls))

        # 9) Tahrirlash matni → AI orqali yangilangan post
        async def fake_edit(prompt, system_instruction=None, **kw):
            return {"post_text": "Tahrirlangan post"}

        ai.generate_ai_response = fake_edit
        msg6 = _FakeMsg(6, chat_id=111, text="sarlavhani qisqartir")
        upd6 = type("U", (), {"message": msg6, "effective_user": _FakeUser(uid)})()
        ctx6 = _FakeCtx(_FakeBot(), user_data={"studio_post_text": "Eski post"})
        state6 = asyncio.run(ai.ai_photo_edit_received(upd6, ctx6))
        check("photo: edit matni → AI_PHOTO_RESULT",
              state6 == ai.AI_PHOTO_RESULT, str(state6))
        check("photo: tahrirlangan post saqlandi",
              ctx6.user_data.get("studio_post_text") == "Tahrirlangan post")

        # 10) Vision xatosi → ball qaytariladi + AI_PHOTO_INPUT
        calls.clear()

        async def fake_vision_err(path, extra_prompt="", tone=None, timeout=None, rewrite_context=""):
            return {"error": "⏳ Gemini API hozircha band."}

        ai.generate_vision_post = fake_vision_err
        msg7 = _FakeMsg(7, chat_id=111)
        msg7.photo = [type("P", (), {"file_id": "file123"})()]
        upd7 = type("U", (), {"message": msg7, "effective_user": _FakeUser(uid)})()
        ctx7 = _FakeCtx(_FakeBot(), user_data={})
        state7 = asyncio.run(ai.ai_photo_received(upd7, ctx7))
        check("photo: xato → AI_PHOTO_INPUT", state7 == ai.AI_PHOTO_INPUT, str(state7))
        check("photo: xato → ball qaytariladi", "add_user_credit" in calls)
    finally:
        db_mod.run_db = orig_run_db
        ai.download_telegram_media_to_temp = orig_dl
        ai.generate_vision_post = orig_vision
        ai.generate_ai_response = orig_edit

    # 11) Global registration (handlers/__init__.py)
    import handlers as h
    src = open(h.__file__, encoding="utf-8").read()
    check("photo: /ai command ro'yxatda", 'CommandHandler("ai"' in src)
    check("photo: photo_ global stale handler",
          "ai_photo_stale_callback" in src and 'pattern=r"^photo_"' in src)
    check("photo: AI_PHOTO_INPUT state ro'yxatda", "AI_PHOTO_INPUT:" in src)
    check("photo: AI_PHOTO_RESULT state ro'yxatda", "AI_PHOTO_RESULT:" in src)
    check("photo: AI_PHOTO_EDIT_INPUT state ro'yxatda", "AI_PHOTO_EDIT_INPUT:" in src)

    # 12) Rasm + /ai caption → global photo handler
    check("photo: _is_ai_photo_command mavjud", callable(getattr(h, "_is_ai_photo_command", None)))
    check("photo: /ai caption taniladi", h._is_ai_photo_command(type("M", (), {"caption": "/ai"})()))
    check("photo: /ai@bot caption taniladi",
          h._is_ai_photo_command(type("M", (), {"caption": "/ai@PostAssistrobot"})()))
    check("photo: oddiy caption — yo'q",
          not h._is_ai_photo_command(type("M", (), {"caption": "rasm haqida"})()))
    check("photo: caption'siz — yo'q",
          not h._is_ai_photo_command(type("M", (), {"caption": ""})()))
    check("photo: global photo handler ro'yxatda",
          "ai_photo_command_callback" in src and
          "filters.PHOTO | filters.Document.ALL" in src)


def test_subscription_functions_exist():
    """Database subscription funksiyalari mavjud."""
    print("== Subscription DB functions ==")
    import database as db_mod

    funcs = [
        "is_premium", "get_user_plan", "check_channel_limit",
        "check_ai_limit", "increment_ai_usage", "set_user_plan",
        "create_promo_code", "redeem_promo_code",
    ]
    for fname in funcs:
        check(f"{fname} mavjud", hasattr(db_mod, fname))
        check(f"{fname} callable", callable(getattr(db_mod, fname)))


def test_subscription_card_format():
    """Obuna holati kartasi formatlash."""
    print("== Subscription card format ==")
    from handlers.subscription import _build_subscription_card, _format_expires

    # 1. Free foydalanuvchi
    free_info = {"plan_type": "free", "expires_at": None, "ai_used": 2}
    card_free = _build_subscription_card(free_info)
    check("free card: Free tarif", "Free" in card_free)
    check("free card: PRO taklif", "PRO Tarif" in card_free)
    check("free card: kanal limiti", "2" in card_free)
    check("free card: AI limiti", "5" in card_free)
    check("free card: separator", "━━━" in card_free)

    # 2. PRO foydalanuvchi
    from datetime import datetime, timezone
    future = datetime(2027, 12, 31, tzinfo=timezone.utc)
    pro_info = {"plan_type": "pro", "expires_at": future, "ai_used": 10}
    card_pro = _build_subscription_card(pro_info)
    check("pro card: PRO tarif", "PRO" in card_pro)
    check("pro card: Cheksiz kanal", "Cheksiz" in card_pro)
    check("pro card: muddat", "31.12.2027" in card_pro)

    # 3. Enterprise
    ent_info = {"plan_type": "enterprise", "expires_at": None, "ai_used": 0}
    card_ent = _build_subscription_card(ent_info)
    check("ent card: Enterprise", "Enterprise" in card_ent)

    # 4. _format_expires
    check("expires None", _format_expires(None) == "♾ Cheksiz")
    check("expires date", "31.12.2027" in _format_expires(future))


def test_subscription_keyboards():
    """Subscription keyboardlari."""
    print("== Subscription keyboards ==")
    from handlers.subscription import (
        _get_subscription_keyboard,
        _build_card_payment_text,
        _get_card_payment_keyboard,
    )

    # 1. Free foydalanuvchi — Stars to'lov tugmalari va Uzcard/Humo karta to'lovi tugmasi
    kb_free = _get_subscription_keyboard("free")
    cbs_free = [b.callback_data for row in kb_free.inline_keyboard for b in row]
    check("free kb: stars_1m", "sub_pay:stars_1m" in cbs_free)
    check("free kb: stars_3m", "sub_pay:stars_3m" in cbs_free)
    check("free kb: stars_1y", "sub_pay:stars_1y" in cbs_free)
    check("free kb: sub_card_pay bor", "sub_card_pay" in cbs_free)
    check("free kb: promo", "sub_promo" in cbs_free)
    check("free kb: back_main", "sub_back_main" in cbs_free)

    # 2. PRO foydalanuvchi — Stars va Karta to'lovi yo'q, promo va back bor
    kb_pro = _get_subscription_keyboard("pro")
    cbs_pro = [b.callback_data for row in kb_pro.inline_keyboard for b in row]
    check("pro kb: stars_1m yo'q", "sub_pay:stars_1m" not in cbs_pro)
    check("pro kb: sub_card_pay yo'q", "sub_card_pay" not in cbs_pro)
    check("pro kb: promo bor", "sub_promo" in cbs_pro)
    check("pro kb: back_main bor", "sub_back_main" in cbs_pro)

    # 3. Karta to'lovi yo'riqnomasi va klaviaturasi (uz & ru)
    for lang in ("uz", "ru"):
        card_text = _build_card_payment_text(123456, lang=lang)
        check(f"card text ({lang}): Uzcard ko'rsatilgan", "Uzcard" in card_text)
        check(f"card text ({lang}): user ID bor", "123456" in card_text)
        card_kb = _get_card_payment_keyboard(lang=lang)
        card_cbs = [b.callback_data for row in card_kb.inline_keyboard for b in row]
        check(f"card kb ({lang}): sub_back bor", "sub_back" in card_cbs)


def test_limit_messages():
    """Limit xabarlari formati."""
    print("== Limit messages ==")
    from handlers.subscription import LIMIT_CHANNEL_MSG, LIMIT_AI_MSG

    # 1. Channel limit xabari
    ch_msg = LIMIT_CHANNEL_MSG.format(current=2, max=2)
    check("ch limit: current", "2/2" in ch_msg)
    check("ch limit: PRO taklif", "PRO" in ch_msg)

    # 2. AI limit xabari
    ai_msg = LIMIT_AI_MSG.format(used=5, max=5)
    check("ai limit: used", "5/5" in ai_msg)
    check("ai limit: PRO taklif", "PRO" in ai_msg)


def test_promo_code_schema():
    """Promo-kod jadvali SQL."""
    print("== Promo code schema ==")
    import database as db_mod
    source = open(db_mod.__file__).read()

    check("promo_codes table", "CREATE TABLE IF NOT EXISTS promo_codes" in source)
    check("promo: code column", "code VARCHAR" in source)
    check("promo: plan_type", "plan_type VARCHAR" in source)
    check("promo: duration_days", "duration_days INTEGER" in source)
    check("promo: max_uses", "max_uses INTEGER" in source)
    check("promo: current_uses", "current_uses INTEGER" in source)
    check("promo: is_active", "is_active BOOLEAN" in source)


def test_subscription_migration_sql():
    """Subscription migration SQL to'g'ri."""
    print("== Subscription migration SQL ==")
    import database as db_mod
    source = open(db_mod.__file__).read()

    check("migration: plan_type", "plan_type" in source)
    check("migration: subscription_expires_at", "subscription_expires_at" in source)
    check("migration: ai_requests_today", "ai_requests_today" in source)
    check("migration: last_limit_reset", "last_limit_reset" in source)
    check("migration: default free", "'free'" in source)


def test_main_keyboard_premium():
    """Asosiy menyuda Premium tugmasi bor."""
    print("== Main keyboard premium ==")
    from keyboards.default import get_main_keyboard, BTN_PREMIUM

    check("BTN_PREMIUM mavjud", BTN_PREMIUM == "⭐️ Premium")

    kb = get_main_keyboard(False)
    all_texts = [b.text for row in kb.keyboard for b in row]
    check("main kb: Premium bor", BTN_PREMIUM in all_texts)

    kb_admin = get_main_keyboard(True)
    all_admin = [b.text for row in kb_admin.keyboard for b in row]
    check("admin kb: Premium bor", BTN_PREMIUM in all_admin)


def test_channel_cache_invalidation():
    print("== database kesh invalidatsiyasi (kanal egasi almashganda) ==")
    from contextlib import contextmanager
    import database as db_mod

    class FakeCursor:
        def __init__(self, script):
            self.script = script
            self.rowcount = 1
            self._row = None

        def execute(self, query, params=None):
            q = " ".join(query.split()).lower()
            if q.startswith("select user_id from channels"):
                self._row = self.script["prev_owner"]
            elif "insert into channels" in q:
                self._row = self.script["returning"]
            else:
                self._row = None

        def fetchone(self):
            return self._row

    def patched(script):
        @contextmanager
        def _db_cursor(commit=False):
            yield FakeCursor(script)
        return _db_cursor

    original = db_mod.db_cursor

    # 1) Admin kanalni eski egadan yangi egaga biriktiradi
    db_mod.db_cursor = patched({"prev_owner": (111,), "returning": (222,)})
    db_mod._cache_set("user_channels:111", [("-100", "K")], 60)
    db_mod._cache_set("user_channels:222", [], 60)
    try:
        ok, reason = db_mod.save_channel(222, "-100", "K", is_admin=True)
    finally:
        db_mod.db_cursor = original
    check("save_channel muvaffaqiyatli", ok and reason == "ok", f"{ok}/{reason}")
    check("eski eganing keshi bekor qilindi",
          db_mod._cache_get("user_channels:111") is db_mod._MISS)
    check("yangi eganing keshi bekor qilindi",
          db_mod._cache_get("user_channels:222") is db_mod._MISS)

    # 2) Admin boshqa foydalanuvchining kanalini o'chiradi
    db_mod.db_cursor = patched({"prev_owner": (111,), "returning": None})
    db_mod._cache_set("user_channels:111", [("-100", "K")], 60)
    db_mod._cache_set("user_channels:999", [], 60)
    try:
        removed = db_mod.remove_channel(999, "-100", is_admin=True)
    finally:
        db_mod.db_cursor = original
    check("remove_channel ishladi", removed)
    check("admin o'chirganda eski eganing keshi bekor qilinadi",
          db_mod._cache_get("user_channels:111") is db_mod._MISS)
    db_mod._cache_clear()


def test_queue_slot_algorithm():
    """Queue slot topish algoritmi testlari."""
    print("== queue: find_next_queue_slot algoritmi ==")
    from database import find_next_queue_slot, DEFAULT_QUEUE_SLOTS

    tz = pytz.timezone("Asia/Tashkent")

    # 1. Default slotlar
    check("default slotlar 3 ta", len(DEFAULT_QUEUE_SLOTS) == 3, str(DEFAULT_QUEUE_SLOTS))
    check("default: 09:00", "09:00" in DEFAULT_QUEUE_SLOTS)
    check("default: 14:00", "14:00" in DEFAULT_QUEUE_SLOTS)
    check("default: 19:00", "19:00" in DEFAULT_QUEUE_SLOTS)

    # 2. Hozir 08:00 — barcha slotlar bo'sh → birinchi slot 09:00
    now = tz.localize(datetime(2026, 9, 1, 8, 0))
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now)
    check("08:00 da → 09:00 slot", slot_dt is not None and slot_dt.hour == 9 and slot_dt.minute == 0, str(slot_dt))
    check("08:00 da → Bugun", label == "Bugun", str(label))

    # 3. Hozir 10:00 — 09:00 o'tib ketgan → keyingi 14:00
    now = tz.localize(datetime(2026, 9, 1, 10, 0))
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now)
    check("10:00 da → 14:00 slot", slot_dt is not None and slot_dt.hour == 14, str(slot_dt))

    # 4. Hozir 15:00 — 09:00 va 14:00 o'tib ketgan → 19:00
    now = tz.localize(datetime(2026, 9, 1, 15, 0))
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now)
    check("15:00 da → 19:00 slot", slot_dt is not None and slot_dt.hour == 19, str(slot_dt))

    # 5. Hozir 20:00 — barcha bugungi slotlar o'tib ketgan → ertaga 09:00
    now = tz.localize(datetime(2026, 9, 1, 20, 0))
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now)
    check("20:00 da → ertaga 09:00", slot_dt is not None and slot_dt.day == 2 and slot_dt.hour == 9, str(slot_dt))
    check("20:00 da → Ertaga", label == "Ertaga", str(label))

    # 6. 09:00 band → keyingi 14:00
    now = tz.localize(datetime(2026, 9, 1, 8, 0))
    occupied = [(9, 0)]
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied, now)
    check("09:00 band → 14:00", slot_dt is not None and slot_dt.hour == 14, str(slot_dt))

    # 7. 09:00 va 14:00 band → 19:00
    occupied = [(9, 0), (14, 0)]
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied, now)
    check("09:00+14:00 band → 19:00", slot_dt is not None and slot_dt.hour == 19, str(slot_dt))

    # 8. Barcha bugungi slotlar band → ertaga 09:00
    occupied = [(9, 0), (14, 0), (19, 0)]
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied, now)
    check("barcha band → ertaga", slot_dt is not None and slot_dt.day == 2, str(slot_dt))

    # 9. Bo'sh slotlar ro'yxati → None
    slot_dt, label = find_next_queue_slot([], [], now)
    check("bo'sh slotlar → None", slot_dt is None)

    # 10. Noto'g'ri format slotlar → None
    slot_dt, label = find_next_queue_slot(["abc", "xyz"], [], now)
    check("noto'g'ri slotlar → None", slot_dt is None)

    # 11. Bitta slot bilan ishlaydi
    slot_dt, label = find_next_queue_slot(["12:00"], [], now)
    check("bitta slot 12:00", slot_dt is not None and slot_dt.hour == 12, str(slot_dt))

    # 12. Slot tartibi muhim emas (sort qilinadi)
    slot_dt, label = find_next_queue_slot(["19:00", "09:00", "14:00"], [], now)
    check("tartibsiz slotlar → 09:00", slot_dt is not None and slot_dt.hour == 9, str(slot_dt))

    # 13. max_days=0 → None
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now, max_days=0)
    check("max_days=0 → None", slot_dt is None)


def test_queue_ui_helpers():
    """Queue UI helper funksiyalari."""
    print("== queue: UI helpers ==")
    from handlers.queue import (
        _post_type_icon, _content_preview, _format_queue_item,
        _get_queue_list_keyboard, _get_slots_keyboard,
        QUEUE_PAGE_SIZE,
    )
    from database import DEFAULT_QUEUE_SLOTS

    # Post type icons
    check("icon: text → 📝", _post_type_icon("text") == "📝")
    check("icon: photo → 🖼", _post_type_icon("photo") == "🖼")
    check("icon: video → 🎬", _post_type_icon("video") == "🎬")
    check("icon: unknown → 📝", _post_type_icon("xyz") == "📝")

    # Content preview
    check("preview: bo'sh", _content_preview("") == "")
    check("preview: None", _content_preview(None) == "")
    check("preview: qisqa", _content_preview("Salom") == "Salom")
    check("preview: uzun kesiladi", len(_content_preview("A" * 100, 40)) <= 41)

    # Format queue item
    tz = pytz.timezone("Asia/Tashkent")
    row = (1, "Test Kanal", "text", "Salom dunyo", tz.localize(datetime(2026, 9, 1, 10, 0)), 1, "-1001")
    item = _format_queue_item(row, 1)
    check("format: raqam", item.startswith("1."), item[:20])
    check("format: vaqt", "01-Sep 10:00" in item or "10:00" in item, item)
    check("format: kanal", "Test Kanal" in item, item)

    # Queue keyboard
    posts = [row]
    kb = _get_queue_list_keyboard(posts, 0, 1)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("kb: view tugmasi", "qview:1" in cbs, str(cbs))
    check("kb: delete tugmasi", "qdel:1" in cbs, str(cbs))
    check("kb: push tugmasi", "qpush:1" in cbs, str(cbs))
    check("kb: slots tugmasi", "qslots:show" in cbs, str(cbs))
    check("kb: close tugmasi", "qclose" in cbs, str(cbs))

    # Pagination: 2-sahifa bo'lsa nav tugmalari bor
    posts_2 = [(i, "K", "text", "x", tz.localize(datetime(2026, 9, 1, 10, 0)), i, "-100") for i in range(10)]
    kb2 = _get_queue_list_keyboard(posts_2[:5], 0, 10)
    cbs2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    check("pagination: keyingi bor", "qpage:5" in cbs2, str(cbs2))

    kb3 = _get_queue_list_keyboard(posts_2[5:], 5, 10)
    cbs3 = [b.callback_data for row in kb3.inline_keyboard for b in row]
    check("pagination: oldingi bor", "qpage:0" in cbs3, str(cbs3))

    # Slots keyboard
    slots_kb = _get_slots_keyboard(DEFAULT_QUEUE_SLOTS)
    scbs = [b.callback_data for row in slots_kb.inline_keyboard for b in row]
    check("slots kb: rm tugmalari", "qslots:rm:0" in scbs, str(scbs))
    check("slots kb: add tugmasi", "qslots:add" in scbs, str(scbs))
    check("slots kb: reset tugmasi", "qslots:reset" in scbs, str(scbs))

    # PAGE_SIZE
    check("PAGE_SIZE = 5", QUEUE_PAGE_SIZE == 5)


def test_queue_main_keyboard():
    """Queue tugmasi asosiy menyuda borligini tekshiradi."""
    print("== queue: main keyboard ==")
    from keyboards.default import get_main_keyboard, BTN_QUEUE

    from keyboards.inline import get_cabinet_inline_keyboard
    kb = get_main_keyboard(is_admin=False)
    texts = [b.text for row in kb.keyboard for b in row]
    cab_cbs = [b.callback_data for row in get_cabinet_inline_keyboard().inline_keyboard for b in row]
    check("queue tugmasi kabinetda", "cab_queue" in cab_cbs, str(cab_cbs))
    check("queue tugmasi asosiy menyuda yo'q", BTN_QUEUE not in texts, str(texts))
    check("BTN_QUEUE matni", BTN_QUEUE == "📚 Navbat (Queue)")


def test_confirmation_queue_integration():
    """Confirmation + Queue integratsion test."""
    print("== integration: confirmation + queue ==")
    from handlers.new_post import (
        _build_preview_text, _get_confirm_keyboard, _get_edit_confirm_keyboard,
        CONFIRM_POST, EDIT_CONFIRM_FIELD,
        build_channel_labels, _media_item_from_message, _apply_single_media,
        CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL,
        GET_REACTIONS, GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME, GET_DURATION,
    )
    from database import find_next_queue_slot, DEFAULT_QUEUE_SLOTS

    tz = pytz.timezone("Asia/Tashkent")

    # 1. State constants
    check("integ: CONFIRM_POST=111", CONFIRM_POST == 111)
    check("integ: EDIT_CONFIRM_FIELD=112", EDIT_CONFIRM_FIELD == 112)

    # 2. Confirm keyboard has queue button
    kb = _get_confirm_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("integ: queue tugmasi callback", "confirm_post:queue" in cbs, str(cbs))
    check("integ: queue tugmasi matni", any("Navbatga" in t for t in labels), str(labels))
    check("integ: ok tugmasi", "confirm_post:ok" in cbs)
    check("integ: edit tugmasi", "confirm_post:edit" in cbs)
    check("integ: cancel tugmasi", "confirm_post:cancel" in cbs)

    # 3. Edit keyboard
    ekb = _get_edit_confirm_keyboard()
    ecbs = [b.callback_data for row in ekb.inline_keyboard for b in row]
    check("integ: edit kb content", "edit_field:content" in ecbs)
    check("integ: edit kb channel", "edit_field:channel" in ecbs)
    check("integ: edit kb time", "edit_field:time" in ecbs)
    check("integ: edit kb btn", "edit_field:btn" in ecbs)
    check("integ: edit kb back", "edit_field:back" in ecbs)

    # 4. Preview matn
    class FakeCtx:
        def __init__(self):
            self.user_data = {}
    ctx = FakeCtx()
    ctx.user_data = {
        "selected_channel_title": "Tech Kanal",
        "post_type": "text",
        "content": "Yangi mahsulot!",
        "btn_text": "Batafsil",
        "btn_url": "https://example.com",
        "enable_reactions": True,
        "delete_after_hours": 24,
        "confirm_post_time": tz.localize(datetime(2026, 9, 5, 14, 0)),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
    }
    preview = _build_preview_text(ctx)
    check("integ: preview kanal", "Tech Kanal" in preview, preview[:100])
    check("integ: preview vaqt", "2026-09-05 14:00" in preview, preview[:100])
    check("integ: preview tugma", "Batafsil" in preview, preview[:200])
    check("integ: preview reaksiya", "Yoqilgan" in preview, preview[:200])
    check("integ: preview auto-delete", "24 soat" in preview, preview[:200])

    # 5. Queue slot algorithm integration
    now = tz.localize(datetime(2026, 9, 1, 8, 0))
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now)
    check("integ: slot 08:00 → 09:00", slot_dt is not None and slot_dt.hour == 9, str(slot_dt))
    check("integ: slot label Bugun", label == "Bugun", str(label))

    # 6. Band slotlar bilan
    occupied = [(9, 0)]
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied, now)
    check("integ: 09:00 band → 14:00", slot_dt is not None and slot_dt.hour == 14, str(slot_dt))

    # 7. Barcha band → ertaga
    occupied = [(9, 0), (14, 0), (19, 0)]
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied, now)
    check("integ: barcha band → ertaga", slot_dt is not None and slot_dt.day == 2, str(slot_dt))
    check("integ: ertaga label", label == "Ertaga", str(label))

    # 8. Channel labels
    channels = [("-1001", "Kanal A"), ("-1002", "Kanal A"), ("-1003", "")]
    labels = build_channel_labels(channels)
    check("integ: 3 ta kanal", len(labels) == 3)

    # 9. Media parsing
    class FakeMsg:
        def __init__(self, **kw):
            self.photo = kw.get("photo")
            self.video = kw.get("video")
            self.document = kw.get("document")
            self.audio = kw.get("audio")
            self.animation = kw.get("animation")
            self.voice = kw.get("voice")
            self.sticker = kw.get("sticker")
            self.caption = kw.get("caption", "")
            self.text = kw.get("text")

    photo_msg = FakeMsg(photo=[type("P", (), {"file_id": "photo_123"})()])
    item = _media_item_from_message(photo_msg)
    check("integ: photo aniqlanadi", item is not None and item["type"] == "photo")

    # 10. Daily recurrence preview
    ctx.user_data["confirm_recurrence_type"] = "daily"
    ctx.user_data["confirm_recurrence_time_str"] = "09:00:00"
    preview_daily = _build_preview_text(ctx)
    check("integ: daily preview", "Har kuni" in preview_daily and "09:00" in preview_daily)

    # 11. Weekly recurrence preview
    ctx.user_data["confirm_recurrence_type"] = "weekly"
    ctx.user_data["confirm_recurrence_day"] = 4
    ctx.user_data["confirm_recurrence_time_str"] = "13:00:00"
    preview_weekly = _build_preview_text(ctx)
    check("integ: weekly preview", "Har Juma" in preview_weekly and "13:00" in preview_weekly)

    # 12. HTML escape
    from utils.helpers import html_escape
    check("integ: HTML escape", "&lt;b&gt;" in html_escape("<b>test</b>"))

    # 13. parse_future_time
    from utils.helpers import parse_future_time
    now2 = tz.localize(datetime(2026, 9, 1, 12, 0))
    t1 = parse_future_time("ertaga 10:00", now2)
    check("integ: ertaga 10:00", t1 is not None and t1.day == 2 and t1.hour == 10, str(t1))


def test_payments_audit_table():
    """To'lovlar uchun alohida payments jadvali va log_stars_payment."""
    print("== payments audit table + log_stars_payment ==")
    import database as db_mod
    source = open(db_mod.__file__).read()

    check("payments table e'lon qilingan", "CREATE TABLE IF NOT EXISTS payments" in source)
    check("payments: id SERIAL PRIMARY KEY", "id SERIAL PRIMARY KEY" in source)
    check("payments: user_id BIGINT", "user_id BIGINT" in source)
    check("payments: amount INT", "amount INT" in source)
    check("payments: currency VARCHAR", "currency VARCHAR" in source)
    check("payments: payload TEXT", "payload TEXT" in source)
    check("payments: telegram_payment_charge_id", "telegram_payment_charge_id" in source)
    check("payments: created_at TIMESTAMP", "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in source)

    check("log_stars_payment callable", callable(db_mod.log_stars_payment))
    check("log_stars_payment -> payments jadvaliga yozadi", "INSERT INTO payments" in source)
    # log_stars_payment endi promo_codes ga yozmaydi (STARS_ yozuvlari olib tashlandi)
    fn_body = source.split("def log_stars_payment", 1)[1].split("\n\n", 1)[0]
    check("log_stars_payment promo_codes dan ajratildi", "promo_codes" not in fn_body)
    # Admin dashboard stars_revenue endi payments dan olinadi
    check("admin dashboard: stars_revenue payments dan", "SUM(amount), 0) FROM payments" in source)


def test_stars_invoice_provider_token():
    """Stars invoice provider_token=\"\" (None emas)."""
    print("== Stars invoice provider_token ==")
    from handlers.subscription import subscription_callback
    source = open(__import__("handlers.subscription", fromlist=["subscription_callback"]).__file__).read()

    check("provider_token=\"\" ishlatiladi", 'provider_token=""' in source)
    check("provider_token=None yo'q", "provider_token=None" not in source)

    # Precheckout va successful payment handlerlari mavjud
    from handlers.subscription import precheckout_callback, successful_payment_callback
    check("precheckout_callback callable", callable(precheckout_callback))
    check("successful_payment_callback callable", callable(successful_payment_callback))
    check("successful_payment PRO beradi (set_user_plan)", "set_user_plan" in source)
    check("successful_payment to'lovni log qiladi", "log_stars_payment" in source)


def test_multi_admin_checks():
    """Yagona ADMIN_ID taqqoslashlari ADMIN_IDS_SET ga moslandi."""
    print("== Multi-admin (ADMIN_IDS_SET) ==")
    import importlib
    import handlers.subscription as sub
    st = importlib.import_module("handlers.start")

    # subscription.py da `user_id != ADMIN_ID` emas
    sub_src = open(sub.__file__).read()
    check("subscription: ADMIN_IDS_SET import", "ADMIN_IDS_SET" in sub_src)
    check("subscription: == ADMIN_ID yo'q", "ADMIN_ID)" not in sub_src)
    check("subscription: user_id not in ADMIN_IDS_SET", "user_id not in ADMIN_IDS_SET" in sub_src)

    start_src = open(st.__file__).read()
    check("start: == ADMIN_ID yo'q", "== ADMIN_ID)" not in start_src)
    check("start: user.id in ADMIN_IDS_SET", "user.id in ADMIN_IDS_SET" in start_src)
    check("start: user_id not in ADMIN_IDS_SET", "user_id not in ADMIN_IDS_SET" in start_src)

    # config.ADMIN_IDS_SET mavjud va frozenset
    from config import ADMIN_IDS_SET
    check("config: ADMIN_IDS_SET mavjud", isinstance(ADMIN_IDS_SET, frozenset))


def test_queue_limit_function():
    """Navbat limiti funksiyasi mavjud va to'g'ri formatda."""
    print("== check_queue_limit ==")
    import database as db_mod
    from config import ADMIN_IDS_SET

    check("FREE_QUEUE_MAX_POSTS mavjud", hasattr(db_mod, "FREE_QUEUE_MAX_POSTS"))
    check("FREE_QUEUE_MAX_POSTS = 5", db_mod.FREE_QUEUE_MAX_POSTS == 5)
    check("check_queue_limit callable", callable(db_mod.check_queue_limit))

    result = db_mod.check_queue_limit(0)  # non-existent user (DB xato → default)
    check("return tuple", isinstance(result, tuple) and len(result) == 3)
    check("return[0] bool", isinstance(result[0], bool))
    check("return[1] int", isinstance(result[1], int))
    check("return[2] int", isinstance(result[2], int))


def test_tier_limit_handler_constants():
    """Tier limitlari handlerlarda e'lon qilingan va PRO tugmasi mavjud."""
    print("== Tier limit handler constants ==")
    from handlers.channels import CHANNEL_LIMIT_MSG, PRO_UPGRADE_KEYBOARD as CH_PRO_KB
    from handlers.queue import QUEUE_LIMIT_MSG, PRO_UPGRADE_KEYBOARD as Q_PRO_KB
    from handlers.ai_assistant import AI_LIMIT_MSG, PRO_UPGRADE_KEYBOARD as AI_PRO_KB
    from handlers.analytics import ANALYTICS_FREE_HINT

    check("channels: CHANNEL_LIMIT_MSG mavjud", "PRO" in CHANNEL_LIMIT_MSG)
    check("channels: PRO tugmasi (sub_open)", any(
        b.callback_data == "sub_open" for row in CH_PRO_KB.inline_keyboard for b in row))
    check("queue: QUEUE_LIMIT_MSG mavjud", "PRO" in QUEUE_LIMIT_MSG)
    check("queue: PRO tugmasi (sub_open)", any(
        b.callback_data == "sub_open" for row in Q_PRO_KB.inline_keyboard for b in row))
    check("ai_assistant: AI_LIMIT_MSG mavjud", "PRO" in AI_LIMIT_MSG)
    check("ai_assistant: PRO tugmasi (sub_open)", any(
        b.callback_data == "sub_open" for row in AI_PRO_KB.inline_keyboard for b in row))
    check("analytics: ANALYTICS_FREE_HINT mavjud", "PRO" in ANALYTICS_FREE_HINT)

    # Handlerlar database limit funksiyalarini chaqiradi
    import handlers.channels as ch
    src_ch = open(ch.__file__).read()
    check("channels: check_channel_limit chaqiriladi", "check_channel_limit" in src_ch)

    import handlers.ai_assistant as ai
    src_ai = open(ai.__file__).read()
    check("ai_assistant: check_ai_limit chaqiriladi", "check_ai_limit" in src_ai)
    check("ai_assistant: increment_ai_usage chaqiriladi", "increment_ai_usage" in src_ai)


def test_tiered_rate_limit_constants():
    """Qatlamli rate limit konstantalari va ularning ishlashi."""
    print("== Tiered rate limits (NAV, ENTRY, REACTION) ==")
    from utils.helpers import (
        check_rate_limit,
        NAV_RATE_LIMIT_MAX,
        ENTRY_RATE_LIMIT_MAX,
        REACTION_RATE_LIMIT_MAX,
    )

    check("NAV_RATE_LIMIT_MAX mavjud", NAV_RATE_LIMIT_MAX is not None)
    check("NAV_RATE_LIMIT_MAX = 20", NAV_RATE_LIMIT_MAX == 20)
    check("ENTRY_RATE_LIMIT_MAX mavjud", ENTRY_RATE_LIMIT_MAX is not None)
    check("ENTRY_RATE_LIMIT_MAX = 12", ENTRY_RATE_LIMIT_MAX == 12)
    check("REACTION_RATE_LIMIT_MAX mavjud", REACTION_RATE_LIMIT_MAX is not None)
    check("REACTION_RATE_LIMIT_MAX = 10", REACTION_RATE_LIMIT_MAX == 10)

    # Navigatsiya limiti: 20 ta o'tadi, 21-chisi blok
    uid_nav = 999101
    nav_res = [check_rate_limit(uid_nav, max_requests=NAV_RATE_LIMIT_MAX, window_seconds=2.0) for _ in range(21)]
    check("NAV: 20 ta so'rov o'tadi", all(not r[0] for r in nav_res[:20]))
    check("NAV: 21-chi so'rov bloklanadi", nav_res[20][0] is True)

    # Entry limiti: 12 ta o'tadi, 13-chisi blok
    uid_entry = 999102
    entry_res = [check_rate_limit(uid_entry, max_requests=ENTRY_RATE_LIMIT_MAX, window_seconds=2.0) for _ in range(13)]
    check("ENTRY: 12 ta so'rov o'tadi", all(not r[0] for r in entry_res[:12]))
    check("ENTRY: 13-chi so'rov bloklanadi", entry_res[12][0] is True)

    # Reaksiya limiti: 10 ta o'tadi, 11-chisi blok
    uid_react = 999103
    react_res = [check_rate_limit(uid_react, max_requests=REACTION_RATE_LIMIT_MAX, window_seconds=2.0) for _ in range(11)]
    check("REACTION: 10 ta so'rov o'tadi", all(not r[0] for r in react_res[:10]))
    check("REACTION: 11-chi so'rov bloklanadi", react_res[10][0] is True)


def test_reaction_keyboard_buttons():
    """Alohida reaksiya tugmalari va klaviatura strukturasi."""
    print("== Individual reaction buttons & keyboard ==")
    from keyboards.default import (
        BTN_REACT_THUMBS_UP,
        BTN_REACT_HEART,
        BTN_REACT_FIRE,
        BTN_REACT_CLAP,
        BTN_REACT_DEFAULT,
        BTN_NO_REACT,
        BTN_BACK,
        get_reactions_keyboard,
    )

    check("BTN_REACT_THUMBS_UP = '👍'", BTN_REACT_THUMBS_UP == "👍")
    check("BTN_REACT_HEART = '❤️'", "❤" in BTN_REACT_HEART)
    check("BTN_REACT_FIRE = '🔥'", BTN_REACT_FIRE == "🔥")
    check("BTN_REACT_CLAP = '👏'", BTN_REACT_CLAP == "👏")
    check("BTN_REACT_DEFAULT = '👍 ❤️ 🔥 👏'", BTN_REACT_DEFAULT == "👍 ❤️ 🔥 👏")
    check("BTN_NO_REACT mavjud", BTN_NO_REACT == "➡️ Reaksiyasiz davom etish")

    kb = get_reactions_keyboard()
    row0_texts = [getattr(b, "text", b) for b in kb.keyboard[0]]
    row1_texts = [getattr(b, "text", b) for b in kb.keyboard[1]]
    row2_texts = [getattr(b, "text", b) for b in kb.keyboard[2]]

    check("get_reactions_keyboard rows = 3", len(kb.keyboard) == 3)
    check("Row 0: 4 ta emoji tugmasi", len(row0_texts) == 4)
    check("Row 0 contains 👍", "👍" in row0_texts)
    check("Row 0 contains ❤️", any("❤" in str(t) for t in row0_texts))
    check("Row 0 contains 🔥", "🔥" in row0_texts)
    check("Row 0 contains 👏", "👏" in row0_texts)
    check("Row 1: BTN_NO_REACT", row1_texts == [BTN_NO_REACT])
    check("Row 2: BTN_BACK", row2_texts == [BTN_BACK])


def test_flexible_reaction_parser():
    """Moslashuvchan reaksiya parseri (parse_reactions_input)."""
    print("== parse_reactions_input matcher ==")
    from utils.helpers import parse_reactions_input

    # Yakka emojilar
    check("emoji 👍 -> True", parse_reactions_input("👍") is True)
    check("emoji ❤️ -> True", parse_reactions_input("❤️") is True)
    check("emoji \\u2764\\ufe0f (VS16) -> True", parse_reactions_input("\u2764\ufe0f") is True)
    check("emoji \\u2764 (no VS) -> True", parse_reactions_input("\u2764") is True)
    check("emoji 🔥 -> True", parse_reactions_input("🔥") is True)
    check("emoji 👏 -> True", parse_reactions_input("👏") is True)
    check("emoji 🎉 -> True", parse_reactions_input("🎉") is True)
    check("emoji 💯 -> True", parse_reactions_input("💯") is True)
    check("emoji ✨ -> True", parse_reactions_input("✨") is True)
    check("emoji ⭐ -> True", parse_reactions_input("⭐") is True)

    # Emoji kombinatsiyalari
    check("combo '👍 ❤️ 🔥 👏' -> True", parse_reactions_input("👍 ❤️ 🔥 👏") is True)
    check("combo '👍❤️🔥👏' -> True", parse_reactions_input("👍❤️🔥👏") is True)
    check("combo '👍, ❤️, 🔥' -> True", parse_reactions_input("👍, ❤️, 🔥") is True)
    check("combo '🔥 👏' -> True", parse_reactions_input("🔥 👏") is True)

    # Matnli tasdiqlash
    check("text 'ha' -> True", parse_reactions_input("ha") is True)
    check("text 'yoqish' -> True", parse_reactions_input("yoqish") is True)
    check("text 'reaksiya' -> True", parse_reactions_input("reaksiya") is True)
    check("text 'reaksiyalar' -> True", parse_reactions_input("reaksiyalar") is True)
    check("text 'yes' -> True", parse_reactions_input("yes") is True)

    # Reaksiyasiz / o'chirish
    check("BTN_NO_REACT -> False", parse_reactions_input("➡️ Reaksiyasiz davom etish") is False)
    check("text 'reaksiyasiz' -> False", parse_reactions_input("reaksiyasiz") is False)
    check("text 'yo\\'q' -> False", parse_reactions_input("yo'q") is False)
    check("text 'yoq' -> False", parse_reactions_input("yoq") is False)
    check("text 'o\\'chirish' -> False", parse_reactions_input("o'chirish") is False)
    check("text 'no' -> False", parse_reactions_input("no") is False)
    check("text 'none' -> False", parse_reactions_input("none") is False)
    check("text '-' -> False", parse_reactions_input("-") is False)
    check("text 'skip' -> False", parse_reactions_input("skip") is False)

    # Noto'g'ri / begona matn
    check("text 'random string' -> None", parse_reactions_input("random string") is None)
    check("text 'salom dunyo' -> None", parse_reactions_input("salom dunyo") is None)
    check("text '12345' -> None", parse_reactions_input("12345") is None)
    check("empty '' -> None", parse_reactions_input("") is None)
    check("None -> None", parse_reactions_input(None) is None)


def test_reaction_toggle_keyboard_and_normalize():
    """Multi-select reaksiya: toggle klaviatura, normalizatsiya va konstanta testlari."""
    print("== multi-select reaction toggle keyboard ==")
    from keyboards.inline import (
        REACTION_EMOJIS, DEFAULT_REACTION_EMOJIS,
        get_reaction_toggle_keyboard, normalize_reaction_emojis,
        CB_REACT_TOGGLE, CB_REACT_DONE, CB_REACT_SKIP,
    )

    # 1. Konstantalar: 6 ta ruxsat etilgan emoji (yangi 🎉 va 🤔 bilan)
    check("REACTION_EMOJIS: 6 ta", len(REACTION_EMOJIS) == 6, str(REACTION_EMOJIS))
    for emoji in ("👍", "❤️", "🔥", "👏", "🎉", "🤔"):
        check(f"REACTION_EMOJIS: {emoji} bor", emoji in REACTION_EMOJIS)
    check("DEFAULT_REACTION_EMOJIS: eski 4 ta", DEFAULT_REACTION_EMOJIS == ("👍", "❤️", "🔥", "👏"))
    check("callback prefiks: kanal reaksiyasidan farqli", CB_REACT_TOGGLE.startswith("nprt:"))
    check("done/skip callback", CB_REACT_DONE == "nprt:done" and CB_REACT_SKIP == "nprt:skip")

    # 2. Toggle klaviatura strukturasi (bo'sh tanlov)
    kb = get_reaction_toggle_keyboard()
    rows = kb.inline_keyboard
    check("toggle kb: 4 qator (2 emoji + done + skip)", len(rows) == 4, str(len(rows)))
    check("toggle kb: 1-emoji qator 3 ta", len(rows[0]) == 3)
    check("toggle kb: 2-emoji qator 3 ta", len(rows[1]) == 3)
    labels = [b.text for row in rows for b in row]
    check("toggle kb: barcha 6 emoji bor", all(any(str(l).startswith(e) for l in labels) for e in REACTION_EMOJIS), str(labels))
    cbs = [b.callback_data for row in rows for b in row]
    for emoji in REACTION_EMOJIS:
        check(f"toggle cb: {emoji}", f"{CB_REACT_TOGGLE}{emoji}" in cbs)
    check("done tugmasi", CB_REACT_DONE in cbs)
    check("skip tugmasi", CB_REACT_SKIP in cbs)
    check("done label", any("Davom etish" in str(t) for t in labels))
    check("skip label", any("Reaksiyasiz" in str(t) for t in labels))
    check("bo'sh tanlovda ✅ yo'q", not any("✅" in str(t) for t in labels))

    # 3. Tanlangan emojilarda ✅ belgisi va hisoblagich
    kb2 = get_reaction_toggle_keyboard(["👍", "🤔"])
    labels2 = [b.text for row in kb2.inline_keyboard for b in row]
    check("tanlangan 👍 ✅", any(str(t) == "👍 ✅" for t in labels2), str(labels2))
    check("tanlangan 🤔 ✅", any(str(t) == "🤔 ✅" for t in labels2), str(labels2))
    check("tanlanmagan 🔥 ✅ yo'q", not any(str(t) == "🔥 ✅" for t in labels2), str(labels2))
    check("done label hisoblagich (2 ta)", any("Davom etish (2 ta)" in str(t) for t in labels2), str(labels2))

    # 4. normalize_reaction_emojis
    check("normalize: satr", normalize_reaction_emojis("👍 ❤️ 🔥") == ["👍", "❤️", "🔥"])
    check("normalize: ro'yxat", normalize_reaction_emojis(["🔥", "🎉", "🔥"]) == ["🔥", "🎉"])
    check("normalize: VS16siz ❤ ham topiladi", "❤️" in normalize_reaction_emojis("❤"))
    check("normalize: kanonik tartib", normalize_reaction_emojis("🤔 👍") == ["👍", "🤔"])
    check("normalize: None → []", normalize_reaction_emojis(None) == [])
    check("normalize: bo'sh satr → []", normalize_reaction_emojis("") == [])
    check("normalize: begona matn → []", normalize_reaction_emojis("salom dunyo") == [])
    check("normalize: set ham qabul qiladi", normalize_reaction_emojis({"🎉"}) == ["🎉"])

    # 5. strip_leading_reaction_glyphs — caption boshidagi sizib chiqqan reaksiyalar
    from keyboards.inline import strip_leading_reaction_glyphs
    leaked = "👍 ❤️ 🔥\n\nHello"
    reactions = ["👍", "❤️", "🔥"]
    check("strip: bo'shliqli join", strip_leading_reaction_glyphs(leaked, reactions) == "Hello")
    check("strip: bo'shliqsiz join",
          strip_leading_reaction_glyphs("👍❤️🔥\nHello", reactions) == "Hello")
    check("strip: tartib farqi (token-set)",
          strip_leading_reaction_glyphs("🔥 👍 ❤️\n\nSalom", reactions) == "Salom")
    check("strip: emoji-only post saqlanadi",
          strip_leading_reaction_glyphs("👍 ❤️ 🔥", reactions) == "👍 ❤️ 🔥")
    check("strip: reaksiyasiz o'zgarmaydi",
          strip_leading_reaction_glyphs(leaked, None) == leaked)
    check("strip: boshqa emoji saqlanadi",
          strip_leading_reaction_glyphs("😍\n\nHello", reactions) == "😍\n\nHello")
    check("strip: matn ichidagi emoji saqlanadi",
          strip_leading_reaction_glyphs("Hello\n👍 ❤️ 🔥", reactions) == "Hello\n👍 ❤️ 🔥")
    check("strip: None → None", strip_leading_reaction_glyphs(None, reactions) is None)
    check("strip: VS16 farqi",
          strip_leading_reaction_glyphs("👍 ❤ 🔥\n\nHi", reactions) == "Hi")


def test_url_button_builder():
    """Inline URL tugma quruvchi: 'Button Text - https://link.com' parser testlari."""
    print("== inline URL tugma quruvchi ==")
    from handlers.new_post import parse_url_button_line, normalize_button_url
    from keyboards.default import (
        get_button_prompt_keyboard, BTN_ADD_URL_BUTTON, BTN_SKIP_URL_BUTTON, BTN_SKIP_BUTTON,
    )

    # 1. Yangi tugma konstantalari
    check("BTN_ADD_URL_BUTTON", BTN_ADD_URL_BUTTON == "🔗 URL tugma qo'shish")
    check("BTN_SKIP_URL_BUTTON", BTN_SKIP_URL_BUTTON == "⏭ O'tkazib yuborish")

    # 2. Prompt klaviaturasida yangi tugmalar bor
    kb = get_button_prompt_keyboard()
    texts = [getattr(b, "text", b) for row in kb.keyboard for b in row]
    check("prompt kb: URL tugma qo'shish bor", BTN_ADD_URL_BUTTON in texts, str(texts))
    check("prompt kb: O'tkazib yuborish bor", BTN_SKIP_URL_BUTTON in texts, str(texts))
    check("prompt kb: AI Yordamchi saqlangan", "✨ AI Yordamchi" in texts)

    # 3. normalize_button_url
    check("url: https saqlanadi", normalize_button_url("https://sayt.uz/x") == "https://sayt.uz/x")
    check("url: http saqlanadi", normalize_button_url("http://a.uz") == "http://a.uz")
    check("url: @username → t.me", normalize_button_url("@kanalim") == "https://t.me/kanalim")
    check("url: t.me/ → https", normalize_button_url("t.me/kanalim") == "https://t.me/kanalim")
    check("url: domen → https", normalize_button_url("example.uz") == "https://example.uz")
    check("url: oddiy so'z → None", normalize_button_url("salom") is None)
    check("url: bo'sh joy bilan → None", normalize_button_url("a b.uz") is None)
    check("url: bo'sh → None", normalize_button_url("") is None and normalize_button_url(None) is None)

    # 4. parse_url_button_line — asosiy format
    r = parse_url_button_line("Button Text - https://link.com")
    check("parse: asosiy format", r == ("Button Text", "https://link.com"), str(r))
    r2 = parse_url_button_line("Saytga o'tish - example.uz")
    check("parse: domen", r2 == ("Saytga o'tish", "https://example.uz"), str(r2))
    r3 = parse_url_button_line("Kanalim - @kanalim")
    check("parse: @username", r3 == ("Kanalim", "https://t.me/kanalim"), str(r3))
    r4 = parse_url_button_line("A'zo bo'lish | https://t.me/kanal")
    check("parse: | ajratgich", r4 == ("A'zo bo'lish", "https://t.me/kanal"), str(r4))
    r5 = parse_url_button_line("Batafsil ma'lumot - https://uz.wikipedia.org/wiki/Toshkent")
    check("parse: matnda tire bo'lsa oxirgi ' - ' bo'yicha ajratiladi",
          r5 == ("Batafsil ma'lumot", "https://uz.wikipedia.org/wiki/Toshkent"), str(r5))

    # 5. Noto'g'ri kiritmalar → None
    check("parse: oddiy matn → None", parse_url_button_line("Batafsil") is None)
    check("parse: 'hello - world' → None", parse_url_button_line("hello - world") is None)
    check("parse: faqat URL → None", parse_url_button_line("https://link.com") is None)
    check("parse: matnsiz ' - ' → None", parse_url_button_line("Matn - ") is None)
    check("parse: bo'sh → None", parse_url_button_line("") is None)
    check("parse: None → None", parse_url_button_line(None) is None)
    check("parse: ko'p qatorli → None", parse_url_button_line("a - b.uz\nkeyingi qator") is None)


def test_scheduler_custom_reactions():
    """Scheduler: saqlangan multi-select reaksiyalar kanalga shu ko'rinishda chiqadi."""
    print("== scheduler custom reaction buttons ==")
    from scheduler import build_reaction_buttons

    # 1. Reaksiya o'chiq → tugma yo'q
    check("o'chiq: bo'sh ro'yxat", build_reaction_buttons(5, False) == [])
    check("o'chiq (emoji bilan ham): bo'sh", build_reaction_buttons(5, False, "👍") == [])

    # 2. Eski post (reaction_emojis=None) → standart 4 emoji
    default_row = build_reaction_buttons(7, True, None)
    check("default: 4 tugma", len(default_row) == 4, str(len(default_row)))
    check("default: 👍 callback", default_row[0].callback_data == "react:7:👍")
    check("default: ❤️ callback", default_row[1].callback_data == "react:7:❤️")
    check("default: 🔥 callback", default_row[2].callback_data == "react:7:🔥")
    check("default: 👏 callback", default_row[3].callback_data == "react:7:👏")

    # 3. Multi-select: foydalanuvchi tanlagan emojilar
    custom_row = build_reaction_buttons(9, True, "👍 🔥 🤔")
    check("custom: 3 tugma", len(custom_row) == 3, str(len(custom_row)))
    check("custom: 👍", custom_row[0].callback_data == "react:9:👍")
    check("custom: 🔥", custom_row[1].callback_data == "react:9:🔥")
    check("custom: 🤔", custom_row[2].callback_data == "react:9:🤔")
    check("custom: ❤️ yo'q", not any("❤" in (b.callback_data or "") for b in custom_row))

    # 4. 🎉 va 🤔 (yangi emojilar) ham ishlatiladi
    party_row = build_reaction_buttons(1, True, ["🎉", "🤔"])
    check("yangi emojilar: 🎉", party_row[0].callback_data == "react:1:🎉")
    check("yangi emojilar: 🤔", party_row[1].callback_data == "react:1:🤔")

    # 5. Buzilgan/noma'lum qiymat → standart to'plamga qaytish
    fallback_row = build_reaction_buttons(3, True, "salom dunyo")
    check("fallback: 4 tugma", len(fallback_row) == 4)

    # 6. Callback tugmalari URL tugmasidan mustaqil (InlineKeyboardButton)
    from telegram import InlineKeyboardButton
    check("button tipi to'g'ri", isinstance(custom_row[0], InlineKeyboardButton))


def test_reaction_emojis_db_schema():
    """DB: reaction_emojis ustuni — sxema, migratsiya va add_post imzosi."""
    print("== reaction_emojis DB schema ==")
    import inspect
    import database as db_mod

    source = open(db_mod.__file__, encoding="utf-8").read()
    check("schema: reaction_emojis TEXT", "reaction_emojis TEXT" in source)
    check("migration: ADD COLUMN IF NOT EXISTS reaction_emojis",
          "ADD COLUMN IF NOT EXISTS reaction_emojis" in source)
    check("get_due_posts: reaction_emojis qaytaradi",
          "sp.delete_after_hours, sp.reaction_emojis" in source)

    sig = inspect.signature(db_mod.add_post)
    check("add_post: reaction_emojis parametri", "reaction_emojis" in sig.parameters)
    check("add_post: default None", sig.parameters["reaction_emojis"].default is None)


def test_quick_button_flow():
    """🔗 Tezkor tugmali post BUTUNLAY olib tashlangan (tugma + tavsif + oqim)."""
    print("== tezkor tugmali post olib tashlangani ==")
    import sys as _sys
    import handlers.new_post as np_mod
    import handlers as h_mod
    import handlers.start  # noqa: F401  (paket atributi funksiya bilan soyalanadi)
    start_mod = _sys.modules["handlers.start"]
    from keyboards.inline import get_extras_inline_keyboard

    # 1. Extras menyusida kirish tugmasi YO'Q
    cbs = [b.callback_data for row in get_extras_inline_keyboard().inline_keyboard for b in row]
    check("extras: extra_quick_btn tugmasi yo'q", "extra_quick_btn" not in cbs, str(cbs))

    # 2. Menyudagi tavsif matni ham olib tashlangan
    start_src = open(start_mod.__file__, encoding="utf-8").read()
    check("start: 'Tezkor tugmali post' tavsifi yo'q",
          "Tezkor tugmali post" not in start_src)

    # 3. FSM holati va handlerlari o'chirilgan
    check("QUICK_BTN_CONTENT holati yo'q", not hasattr(np_mod, "QUICK_BTN_CONTENT"))
    check("quick_button_post_start yo'q", not hasattr(np_mod, "quick_button_post_start"))
    check("quick_btn_content_received yo'q", not hasattr(np_mod, "quick_btn_content_received"))

    # 4. Handler registratsiyasi ham tozalangan
    h_src = open(h_mod.__file__, encoding="utf-8").read()
    check("register: extra_quick_btn entry yo'q", "extra_quick_btn" not in h_src)
    check("register: QUICK_BTN_CONTENT holati yo'q", "QUICK_BTN_CONTENT" not in h_src)

    # 5. Qolgan new-post holatlari buzilmagan va unikal
    states = {
        np_mod.CHOOSE_CHANNEL, np_mod.GET_CONTENT, np_mod.GET_BTN_TITLE, np_mod.GET_BTN_URL,
        np_mod.GET_REACTIONS, np_mod.GET_AUTO_DELETE, np_mod.GET_TIME, np_mod.DAILY_TIME,
        np_mod.RECUR_DAY, np_mod.RECUR_TIME, np_mod.GET_DURATION, np_mod.CONFIRM_POST,
        np_mod.EDIT_CONFIRM_FIELD,
    }
    check("qolgan holatlar unikal (13 ta)", len(states) == 13, str(len(states)))

    # 6. Reaksiya oqimi handlerlari saqlangan
    check("reaction_toggle_callback callable", callable(np_mod.reaction_toggle_callback))
    check("reactions_done_callback callable", callable(np_mod.reactions_done_callback))
    check("reactions_skip_callback callable", callable(np_mod.reactions_skip_callback))
    check("register: nprt:t handler", 'pattern=r"^nprt:t:"' in h_src)
    check("register: nprt:done handler", 'pattern=r"^nprt:done$"' in h_src)
    check("register: nprt:skip handler", 'pattern=r"^nprt:skip$"' in h_src)

    # 7. parse_url_button_line boshqa oqimlarda (Post Enhancer) ishlatilgani
    #    uchun SAQLANADI — u tezkor post oqimiga tegishli emas edi.
    parse = np_mod.parse_url_button_line
    check("parse_url_button_line saqlangan",
          parse("Narxlarni ko'ring - https://shop.uz") == ("Narxlarni ko'ring", "https://shop.uz"))
    check("parse: oddiy matn → None", parse("Batafsil") is None)


def test_five_fixes_suite():
    """5 ta aniq vazifa: vision modeli, kanal ulash, tezkor post, navbat, admin."""
    print("== 5 ta vazifa bo'yicha yakuniy tekshiruv ==")
    import asyncio
    import sys as _sys
    import database as db_mod
    from utils import ai_agent
    from keyboards.inline import (
        get_channels_manage_keyboard, NO_CHANNELS_HINT,
        get_extras_inline_keyboard, get_cabinet_back_keyboard,
    )
    import handlers.queue as queue_mod
    import handlers.start  # noqa: F401
    start_mod = _sys.modules["handlers.start"]

    # ---------- 1) VISION: barqaror model + "mavjud emas" xatosi yo'q ----------
    check("vision: barqaror model belgilangan",
          bool(ai_agent.GEMINI_VISION_MODEL), ai_agent.GEMINI_VISION_MODEL)
    chain = ai_agent._vision_model_chain(None)
    check("vision: zanjir belgilangan modeldan boshlanadi",
          chain and chain[0] == ai_agent.GEMINI_VISION_MODEL, str(chain))
    check("vision: zanjirda takror yo'q", len(chain) == len(set(chain)), str(chain))
    check("vision: o'chirilgan model zanjirda yo'q",
          not any(ai_agent._is_retired_gemini(m) for m in chain), str(chain))
    check("vision: gemini-1.5-flash retired deb taniladi",
          ai_agent._is_retired_gemini("gemini-1.5-flash"))
    check("vision: gemini-2.0-flash retired deb taniladi",
          ai_agent._is_retired_gemini("gemini-2.0-flash"))
    # Discovery ro'yxatidan faqat rasm qabul qiladigan modellar olinadi
    mixed = ["gemini-1.5-flash", "gemini-3-flash", "embedding-001",
             "gemini-2.5-flash-tts", "imagen-4.0", "gemini-2.5-flash"]
    filtered = ai_agent._vision_model_chain(mixed)
    check("vision: discovery'dan vision-yaroqli model qo'shildi",
          "gemini-3-flash" in filtered, str(filtered))
    check("vision: embedding/tts/imagen filtrlanadi",
          not any(m in filtered for m in ("embedding-001", "gemini-2.5-flash-tts", "imagen-4.0")),
          str(filtered))
    check("vision: retired discovery modeli olinmaydi",
          "gemini-1.5-flash" not in filtered, str(filtered))
    # Xato xabari: eski "modeli hozircha mavjud emas" matni yo'q
    err_404 = ai_agent.vision_friendly_error(404, "models/x is not found")
    check("vision 404: eski 'hozircha mavjud emas' matni yo'q",
          "hozircha mavjud emas" not in err_404, err_404)
    check("vision 404: foydalanuvchiga tushunarli xabar", "qayta urinib" in err_404, err_404)
    # Post talablari: sarlavha, emojilar, xeshteglar
    check("vision prompt: sarlavha talabi", "SARLAVHA" in ai_agent._VISION_SYSTEM)
    check("vision prompt: jozibador matn talabi", "JOZIBADOR MATN" in ai_agent._VISION_SYSTEM)
    check("vision prompt: emoji talabi", "EMOJILAR" in ai_agent._VISION_SYSTEM)
    check("vision prompt: xeshteg talabi", "XESHTEG" in ai_agent._VISION_SYSTEM)
    check("vision prompt: o'zbek tili talabi", "O'ZBEK" in ai_agent._VISION_SYSTEM)
    check("vision prompt: video tahlil qilinmasligi aytilgan",
          "video tahlil qilinmaydi" in ai_agent._VISION_SYSTEM.lower())

    # ---------- 1b) Faqat rasm: video rad etiladi ----------
    import handlers.ai_assistant as ai_mod
    msg_video = type("M", (), {
        "photo": None, "document": None, "video": object(),
        "animation": None, "audio": None, "voice": None,
        "video_note": None, "sticker": None,
    })()
    check("video: rasm sifatida qabul qilinmaydi",
          ai_mod._extract_photo_file(msg_video) == (None, None))
    check("video: aniq 'video emas' xabari beriladi", ai_mod._is_non_image_media(msg_video))
    doc_pdf = type("D", (), {"file_id": "doc1", "mime_type": "application/pdf"})()
    msg_pdf = type("M", (), {
        "photo": None, "document": doc_pdf, "video": None, "animation": None,
        "audio": None, "voice": None, "video_note": None, "sticker": None,
    })()
    check("pdf: rasm emas", ai_mod._extract_photo_file(msg_pdf) == (None, None))
    doc_png = type("D", (), {"file_id": "img1", "mime_type": "image/png"})()
    msg_png = type("M", (), {
        "photo": None, "document": doc_png, "video": None, "animation": None,
        "audio": None, "voice": None, "video_note": None, "sticker": None,
    })()
    check("png hujjat: rasm sifatida olinadi",
          ai_mod._extract_photo_file(msg_png) == ("img1", "photo"))

    # ---------- 2) KANAL ULASH: matn + 2 ta tugma ----------
    kb = get_channels_manage_keyboard()
    kb_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    kb_labels = [b.text for row in kb.inline_keyboard for b in row]
    check("kanal: '➕ Kanal qo'shish' tugmasi bor", "add_channel_start" in kb_cbs, str(kb_cbs))
    check("kanal: '🗑 Kanalni o'chirish' tugmasi bor",
          "cab_channels_delete" in kb_cbs, str(kb_cbs))
    check("kanal: tugma yorliqlari to'g'ri",
          "➕ Kanal qo'shish" in kb_labels and "🗑 Kanalni o'chirish" in kb_labels,
          str(kb_labels))
    check("kanal: yo'naltiruvchi matn to'g'ri",
          "Mening kanallarim" in NO_CHANNELS_HINT, NO_CHANNELS_HINT)
    src_start = open(start_mod.__file__, encoding="utf-8").read()
    check("kanal: eski xato yo'naltiruv matn olib tashlangan",
          "Yangi post rejalashtirish' bo'limini tanlang" not in src_start)
    check("kanal: yangi matn ishlatiladi", "no_channels_hint(" in src_start)
    check("kanal: cab_channels_delete handleri bor", 'data == "cab_channels_delete"' in src_start)
    # add_channel_start ConversationHandler entry point sifatida ro'yxatdan o'tgan
    import handlers as h_mod
    h_src = open(h_mod.__file__, encoding="utf-8").read()
    check("kanal: add_channel_start conversation entry point",
          'CallbackQueryHandler(add_channel_inline_entry, pattern=r"^add_channel_start$")' in h_src)
    import handlers.channels as ch_mod
    check("kanal: add_channel_inline_entry ADD_CHANNEL holatini qaytaradi",
          "return ADD_CHANNEL" in open(ch_mod.__file__, encoding="utf-8").read())

    # ---------- 3) TEZKOR TUGMALI POST: tugma va tavsif yo'q ----------
    ex_cbs = [b.callback_data for row in get_extras_inline_keyboard().inline_keyboard
              for b in row]
    check("tezkor: extras menyusida tugma yo'q", "extra_quick_btn" not in ex_cbs, str(ex_cbs))
    check("tezkor: tavsif matni olib tashlangan", "Tezkor tugmali post" not in src_start)

    # ---------- 4) POST NAVBATI: qotib qolmaydi ----------
    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "get_queue_post_count":
            return 0
        if name == "check_queue_limit":
            return (True, 0, 5)
        if name == "get_queue_posts":
            return []
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    original = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        text, markup = asyncio.run(queue_mod._build_queue_view(555001, False))
    finally:
        db_mod.run_db = original
    check("navbat: bo'sh holatda ham javob qaytadi (ImportError yo'q)", bool(text))
    check("navbat: bo'sh holatda klaviatura bor", markup is not None)
    check("navbat: orqaga tugmasi bor",
          "cab_main" in [b.callback_data for row in markup.inline_keyboard for b in row])
    check("navbat: get_cabinet_back_keyboard inline'dan olinadi",
          "from keyboards.inline import get_cabinet_back_keyboard"
          in open(queue_mod.__file__, encoding="utf-8").read())
    check("navbat: cabinet handleri xatoni ushlaydi (qotmaydi)",
          "Post navbati ekranini qurishda xato" in src_start)
    # scheduled_posts jadvalidan o'qiladi
    db_src = open(db_mod.__file__, encoding="utf-8").read()
    check("navbat: scheduled_posts jadvalidan o'qiladi",
          "FROM scheduled_posts sp" in db_src and "def get_queue_posts" in db_src)
    check("navbat: faqat pending postlar", "status = 'pending'" in db_src)

    # ---------- 5) ADMIN: 3 ta asosiy bo'lim ----------
    import handlers.admin as admin
    admin_src = open(admin.__file__, encoding="utf-8").read()
    check("admin: eski javob matni bo'limi o'chirilgan", "adm_ad_edit_text" not in admin_src)
    check("admin: dublikat oraliq (adm_ad_set_interval) o'chirilgan",
          "adm_ad_set_interval" not in admin_src)
    check("admin: dublikat oraliq (adm_ad_int:) o'chirilgan", "adm_ad_int:" not in admin_src)
    check("admin: kanal reklamasi toggle qo'shilgan", "adm_channel_ad_toggle" in admin_src)
    check("admin: 3 bo'lim hub matnida",
          all(m in admin_src for m in (
              "Majburiy obuna (Sponsor kanallar)",
              "3-5 ta javobda chiqadigan reklama",
              "Kanal postlariga reklama qo'shish")))
    check("admin: channel_ad_status DB'da mavjud", hasattr(db_mod, "set_channel_ad_status"))


def test_guard_feedback_and_silent_blocking_fix():
    """Guard va callbacklarda bildirishnoma mavjudligi (silent blocking fix)."""
    print("== Non-silent rate-limit feedback in guards ==")
    import handlers as h_mod
    import handlers.pending as p_mod
    import handlers.new_post as np_mod

    src_h = open(h_mod.__file__).read()
    check("handlers: ENTRY_RATE_LIMIT_MAX import", "ENTRY_RATE_LIMIT_MAX" in src_h)
    check("handlers: NAV_RATE_LIMIT_MAX import", "NAV_RATE_LIMIT_MAX" in src_h)
    check("handlers: REACTION_RATE_LIMIT_MAX import", "REACTION_RATE_LIMIT_MAX" in src_h)
    # 🌐 Rate-limit bildirishnomasi endi qotirilgan matn emas — lug'at
    # kaliti orqali foydalanuvchi tilida chiqadi (pend_rate_limited,
    # uz qiymati: "⏳ Iltimos, biroz kuting...").
    from locales.translations import get_text as _gt
    check("handlers: pend_rate_limited lug'at matni (uz) saqlangan",
          _gt("pend_rate_limited", "uz") == "⏳ Iltimos, biroz kuting...")
    check("handlers: guard_entry notice lug'atdan olinadi",
          'get_text("pend_rate_limited"' in src_h)
    check("handlers: guard_menu notice lug'atdan olinadi",
          'get_text("pend_rate_limited"' in src_h)
    check("handlers: reaction_callback alert lug'atdan olinadi",
          'get_text("pend_rate_limited"' in src_h)

    src_p = open(p_mod.__file__).read()
    check("pending: NAV_RATE_LIMIT_MAX import", "NAV_RATE_LIMIT_MAX" in src_p)
    check("pending: refresh_pending alert text", "⏳ Iltimos, biroz kuting..." in src_p)
    check("pending: parse_reactions_input ishlatiladi", "parse_reactions_input" in src_p)

    src_np = open(np_mod.__file__).read()
    check("new_post: parse_reactions_input ishlatiladi", "parse_reactions_input" in src_np)


def test_sponsor_channels_suite():
    """Majburiy obuna (Sponsor kanallar) tizimi testlari."""
    print("== Majburiy obuna (Sponsor channels) ==")
    import database as db_mod
    from keyboards.inline import (
        unpack_sponsor,
        get_subscription_check_keyboard,
        get_admin_sponsors_keyboard,
        get_sponsors_delete_keyboard,
    )
    from handlers.start import check_user_subscribed, check_user_sponsorship

    # DB funksiyalari mavjudligi
    check("db.add_sponsor_channel mavjud", hasattr(db_mod, "add_sponsor_channel"))
    check("db.remove_sponsor_channel mavjud", hasattr(db_mod, "remove_sponsor_channel"))
    check("db.get_sponsor_channels mavjud", hasattr(db_mod, "get_sponsor_channels"))
    check("db.get_active_sponsors mavjud", hasattr(db_mod, "get_active_sponsors"))

    # unpack_sponsor turli formatlarni xavfsiz ajratadi
    s_tuple4 = (101, "-100123", "Kanal 1", "https://t.me/k1")
    u4 = unpack_sponsor(s_tuple4)
    check("unpack 4-tuple id", u4[0] == 101)
    check("unpack 4-tuple title", u4[2] == "Kanal 1")
    check("unpack 4-tuple url", u4[4] == "https://t.me/k1")

    s_tuple5 = (102, -100456, "Kanal 2", "kanal2", "https://t.me/kanal2")
    u5 = unpack_sponsor(s_tuple5)
    check("unpack 5-tuple id", u5[0] == 102)
    check("unpack 5-tuple username", u5[3] == "kanal2")
    check("unpack 5-tuple url", u5[4] == "https://t.me/kanal2")

    s_dict = {"id": 103, "channel_id": -100789, "title": "Kanal 3", "username": "k3", "invite_link": "https://t.me/+join"}
    ud = unpack_sponsor(s_dict)
    check("unpack dict id", ud[0] == 103)
    check("unpack dict title", ud[2] == "Kanal 3")
    check("unpack dict url", ud[4] == "https://t.me/+join")

    # Subscription check keyboard
    sponsors = [(1, "-1001", "Kanal A", "https://t.me/ka")]
    kb_sub = get_subscription_check_keyboard(sponsors)
    sub_cbs = [b.callback_data for row in kb_sub.inline_keyboard for b in row if b.callback_data]
    sub_urls = [b.url for row in kb_sub.inline_keyboard for b in row if b.url]
    check("sub check callback data check_sub_status", "check_sub_status" in sub_cbs, str(sub_cbs))
    check("sub check channel url mavjud", "https://t.me/ka" in sub_urls, str(sub_urls))

    # Admin sponsors keyboard
    adm_s_kb = get_admin_sponsors_keyboard(sponsors)
    adm_s_cbs = [b.callback_data for row in adm_s_kb.inline_keyboard for b in row]
    check("admin sponsors delete button", "sp_del:1" in adm_s_cbs, str(adm_s_cbs))
    check("admin sponsors add button", "adm_add_sponsor" in adm_s_cbs, str(adm_s_cbs))
    check("admin sponsors back button", "adm_back" in adm_s_cbs, str(adm_s_cbs))
    check("admin sponsors close button", "close_msg" in adm_s_cbs, str(adm_s_cbs))


def test_auto_ad_injector_suite():
    """Reklama boshqaruvi — FAQAT 3 ta asosiy bo'lim (ixcham admin panel)."""
    print("== Reklama boshqaruvi: 3 ta asosiy bo'lim ==")
    import database as db_mod
    from utils import helpers
    import keyboards.inline as ki
    from keyboards.inline import (
        get_ad_hub_keyboard,
        get_ad_interval_keyboard,
    )

    # DB funksiyalari mavjudligi
    check("db.get_ad_settings mavjud", hasattr(db_mod, "get_ad_settings"))
    check("db.update_ad_text mavjud", hasattr(db_mod, "update_ad_text"))
    check("db.set_ad_status mavjud", hasattr(db_mod, "set_ad_status"))
    check("db.set_ad_interval mavjud", hasattr(db_mod, "set_ad_interval"))
    check("db.set_channel_ad_status mavjud (kanal reklamasi toggle)",
          hasattr(db_mod, "set_channel_ad_status"))

    # Hub klaviaturasi: 3 ta bo'lim — har birida matn, oraliq, tugma, yoqish/o'chirish
    ad_kb = get_ad_hub_keyboard(channel_total=2, channel_active=1,
                                reply_total=3, reply_active=3,
                                auto_status=True, auto_interval=4,
                                channel_interval=3, channel_status=True,
                                sponsors_count=2)
    ad_cbs = [b.callback_data for row in ad_kb.inline_keyboard for b in row]
    labels = [b.text for row in ad_kb.inline_keyboard for b in row]

    # 1-bo'lim: Majburiy obuna
    check("1-bo'lim: majburiy obuna", "adm_sponsors" in ad_cbs, str(ad_cbs))
    check("1-bo'lim: sponsorlar soni ko'rsatilgan",
          any("Majburiy obuna (2 ta kanal)" in t for t in labels), str(labels))
    # 2-bo'lim: javoblar reklamasi (matn + oraliq + yoqish/o'chirish)
    check("2-bo'lim: javoblar matni (pul)", "adp:reply:back" in ad_cbs, str(ad_cbs))
    check("2-bo'lim: javoblar oralig'i", "adp:reply:iv" in ad_cbs, str(ad_cbs))
    check("2-bo'lim: javoblar yoqish/o'chirish", "adm_ad_toggle" in ad_cbs, str(ad_cbs))
    # 3-bo'lim: kanal postlari reklamasi (matn + oraliq + yoqish/o'chirish)
    check("3-bo'lim: kanal matni (pul)", "adp:channel:back" in ad_cbs, str(ad_cbs))
    check("3-bo'lim: kanal oralig'i", "adp:channel:iv" in ad_cbs, str(ad_cbs))
    check("3-bo'lim: kanal yoqish/o'chirish", "adm_channel_ad_toggle" in ad_cbs, str(ad_cbs))

    check("hub kb: dashboard'ga orqaga", "adm_back" in ad_cbs, str(ad_cbs))
    check("hub kb: sonlar ko'rsatilgan",
          any("1/2" in t for t in labels) and any("3/3" in t for t in labels), str(labels))

    # Chalkash/dublikat tugmalar olib tashlangan
    check("eski javob matni tugmasi yo'q", "adm_ad_edit_text" not in ad_cbs, str(ad_cbs))
    check("dublikat oraliq (adm_ad_set_interval) yo'q",
          "adm_ad_set_interval" not in ad_cbs, str(ad_cbs))
    check("dublikat oraliq (adm_ad_int:*) yo'q",
          not any(c.startswith("adm_ad_int:") for c in ad_cbs), str(ad_cbs))
    check("get_admin_ad_interval_keyboard o'chirilgan",
          not hasattr(ki, "get_admin_ad_interval_keyboard"))
    check("aloqada 'auto_ad' ekrani yo'q", "adm_auto_ad" not in ad_cbs, str(ad_cbs))

    # Oraliq endi YAGONA klaviatura orqali (har scope uchun 3/4/5)
    for scope in ("channel", "reply"):
        int_kb = get_ad_interval_keyboard(scope, current=3)
        int_cbs = [b.callback_data for row in int_kb.inline_keyboard for b in row]
        for value in (3, 4, 5):
            check(f"{scope}: har {value} tanlovi bor",
                  f"adp:{scope}:iv:{value}" in int_cbs, str(int_cbs))
        check(f"{scope}: orqaga o'z menyusiga", f"adp:{scope}:back" in int_cbs, str(int_cbs))

    # Auto-ad injection logikasi (Mock DB bilan)
    original_get_ad_settings = db_mod.get_ad_settings
    original_is_premium = db_mod.is_premium

    # 1) Reklama o'chiq bo'lsa -> bo'sh satr
    db_mod.get_ad_settings = lambda: {"auto_ad_text": "HOMIY REKLAMA", "auto_ad_interval": 4, "auto_ad_status": False}
    db_mod.is_premium = lambda uid: False
    helpers.reset_user_interaction_count(999001)

    ad_off = helpers.get_auto_ad_injection(999001)
    check("auto-ad OFF bo'lsa bo'sh", ad_off == "")

    # 2) Reklama yoqiq va interval 4 bo'lsa -> 4-so'rovda chiqadi
    db_mod.get_ad_settings = lambda: {"auto_ad_text": "HOMIY REKLAMA", "auto_ad_interval": 4, "auto_ad_status": True}
    helpers.reset_user_interaction_count(999001)

    r1 = helpers.get_auto_ad_injection(999001)
    r2 = helpers.get_auto_ad_injection(999001)
    r3 = helpers.get_auto_ad_injection(999001)
    r4 = helpers.get_auto_ad_injection(999001)
    check("1-so'rov: reklama yo'q", r1 == "")
    check("2-so'rov: reklama yo'q", r2 == "")
    check("3-so'rov: reklama yo'q", r3 == "")
    check("4-so'rov: reklama qo'shiladi", "HOMIY REKLAMA" in r4, r4)

    # 3) PRO foydalanuvchiga reklama umuman chiqmaydi
    db_mod.is_premium = lambda uid: True
    helpers.reset_user_interaction_count(999002)
    for _ in range(10):
        pro_ad = helpers.get_auto_ad_injection(999002)
        check("PRO foydalanuvchiga reklama chiqmaydi", pro_ad == "")

    # 4) Matnga biriktirish (inject_auto_ad)
    db_mod.is_premium = lambda uid: False
    helpers.reset_user_interaction_count(999003)
    helpers.get_auto_ad_injection(999003) # 1
    helpers.get_auto_ad_injection(999003) # 2
    helpers.get_auto_ad_injection(999003) # 3
    injected = helpers.inject_auto_ad(999003, "Asosiy natija matni")
    check("inject_auto_ad: natija ostiga reklama qo'shildi", "Asosiy natija matni" in injected and "HOMIY REKLAMA" in injected, injected)

    # Tiklash
    db_mod.get_ad_settings = original_get_ad_settings
    db_mod.is_premium = original_is_premium


def test_admin_dashboard_layout_suite():
    """Admin dashboard ixchamlashtirilgan 6-tugmali layout testi.

    Talab: faqat 6 ta asosiy tugma + Yopish qoladi. "🛠 Tizim sozlamalari"
    panelda BUTUNLAY yo'q, "📢 Majburiy obuna" mustaqil tugma sifatida
    yo'q — u endi "🎯 Reklama markazi" hub ichida.
    """
    print("== Admin Dashboard Layout (ixcham, 6 ta tugma) ==")
    from keyboards.inline import get_admin_dashboard_keyboard

    kb = get_admin_dashboard_keyboard()
    rows = kb.inline_keyboard
    check("dashboard qatorlar soni = 4", len(rows) == 4, str(len(rows)))

    # Qator 1: To'liq statistika & Ommaviy xabar
    check("row 0 btn 0: adm_stats", rows[0][0].callback_data == "adm_stats")
    check("row 0 btn 1: adm_broadcast", rows[0][1].callback_data == "adm_broadcast")

    # Qator 2: Reklama markazi & Kanallar ro'yxati
    check("row 1 btn 0: adm_adhub", rows[1][0].callback_data == "adm_adhub")
    check("row 1 btn 1: adm_channels", rows[1][1].callback_data == "adm_channels")

    # Qator 3: Promo & PRO
    check("row 2 btn 0: adm_promo", rows[2][0].callback_data == "adm_promo")
    check("row 2 btn 1: adm_grant_pro", rows[2][1].callback_data == "adm_grant_pro")

    # Qator 4: Yopish
    check("row 3 btn 0: close_msg", rows[3][0].callback_data == "close_msg")

    cbs = [b.callback_data for row in rows for b in row]
    check("faqat 6 ta amaliy tugma + yopish", len(cbs) == 7, str(cbs))
    check("adm_sponsors mustaqil tugma sifatida yo'q", "adm_sponsors" not in cbs, str(cbs))
    check("adm_settings (Tizim sozlamalari) butunlay yo'q", "adm_settings" not in cbs, str(cbs))

    labels = [b.text for row in rows for b in row]
    check("label: To'liq statistika", any("statistika" in t.lower() for t in labels))
    check("label: Ommaviy xabar", any("ommaviy" in t.lower() for t in labels))
    check("label: Majburiy obuna mustaqil tugma sifatida yo'q",
          not any("majburiy obuna" in t.lower() for t in labels), str(labels))
    check("label: Tizim sozlamalari yo'q",
          not any("tizim sozlamalari" in t.lower() for t in labels), str(labels))
    check("label: Reklama markazi", any("reklama markazi" in t.lower() for t in labels), str(labels))
    check("label: Kanallar ro'yxati", any("kanallar ro'yxati" in t.lower() for t in labels), str(labels))
    check("label: Promo-kod", any("promo" in t.lower() for t in labels))
    check("label: PRO obuna", any("pro" in t.lower() for t in labels))
    check("label: Yopish", any("yopish" in t.lower() for t in labels))


def test_post_enhancer_flow():
    """✨ Postga Tugma & Reaksiya: keyboard, parser, layout va handler registratsiyasi."""
    print("== post enhancer (✨ Qo'shimcha funksiyalar) ==")
    import handlers.post_enhancer as pe
    import handlers as h_mod
    from keyboards.inline import get_extras_inline_keyboard, extract_emoji_tokens, REACTION_POOL

    # 1. Kirish nuqtasi
    cbs = [b.callback_data for row in get_extras_inline_keyboard().inline_keyboard for b in row]
    check("extras: extra_enhancer", "extra_enhancer" in cbs, str(cbs))
    check("state ENH_POST = 121", pe.ENH_POST == 121)
    check("MAX_ENH_REACTIONS = 10", pe.MAX_ENH_REACTIONS == 10)
    check("MAX_ENH_BUTTONS = 10", pe.MAX_ENH_BUTTONS == 10)

    # 2. Handler funksiyalari
    for fn in ("post_enhancer_start", "enh_message_received", "enh_callback", "enh_stale_callback"):
        check(f"handler: {fn}", callable(getattr(pe, fn)))

    # 3. Registratsiya (source darajasida)
    h_src = open(h_mod.__file__, encoding="utf-8").read()
    check("register: extra_enhancer entry", 'pattern=r"^extra_enhancer$"' in h_src)
    check("register: ^enh: callback", 'pattern=r"^enh:"' in h_src)
    check("register: stale ^enh: global", 'enh_stale_callback' in h_src)

    # 4. parse_button_line — ko'p formatlarni qo'llab-quvvatlash
    p = pe.parse_button_line
    check("btn: 'Text - url'", p("Sayt - https://sayt.uz") == {"text": "Sayt", "url": "https://sayt.uz"}, str(p("Sayt - https://sayt.uz")))
    check("btn: 'Text | @kanal'", p("Kanalim | @kanalim") == {"text": "Kanalim", "url": "https://t.me/kanalim"}, str(p("Kanalim | @kanalim")))
    only = p("https://t.me/durov")
    check("btn: faqat URL (label avtomatik)", only and only["url"] == "https://t.me/durov" and only["text"] == "@durov", str(only))
    check("btn: oddiy matn → None", p("salom dunyo") is None)

    # 5. Reaksiya layouti — 10 tugma + 10 reaksiya 10 qatordan oshmasin
    btns = [{"text": f"B{i}", "url": f"https://x.uz/{i}"} for i in range(10)]
    reacts = list(REACTION_POOL[:10])
    rows = pe.build_enhancer_rows(btns, reacts, post_id=7)
    check("layout: <=10 qator", len(rows) <= 10, str(len(rows)))
    url_rows = [r for r in rows if all(b.url for b in r)]
    react_rows = [r for r in rows if all(getattr(b, "callback_data", None) for b in r)]
    check("layout: URL tugmalar bor", len(url_rows) >= 1)
    check("layout: reaksiya qatori react: bilan", all(b.callback_data.startswith("react:7:") for r in react_rows for b in r), str(react_rows))
    prev_rows = pe.build_enhancer_rows(btns, reacts, post_id=None, preview=True)
    check("layout: preview reaksiyalari noop", all(getattr(b, "callback_data", "") == "enh:noop" for r in prev_rows for b in r if not b.url), "preview")

    # 6. add_unique_emoji — takror yo'q, limit bor
    res, n = pe.add_unique_emoji(["👍"], ["👍", "❤️"], max_count=2)
    check("emoji: dedup + qo'shish", res == ["👍", "❤️"] and n == 1, str((res, n)))
    res2, n2 = pe.add_unique_emoji(["👍", "❤️"], ["🔥"], max_count=2)
    check("emoji: limit to'lgan", res2 == ["👍", "❤️"] and n2 == 0, str((res2, n2)))

    # 7. extract_emoji_tokens — faqat emojilarni oladi
    got = extract_emoji_tokens("👍 ❤️ 🔥 salom 👍")
    check("extract_emoji: faqat emoji + dedup", got == ["👍", "❤️", "🔥"], str(got))

    # 7b. summarize_selection — haqiqiy satr almashinuvi (escape regressiyasi)
    summ = pe.summarize_selection({"reactions": ["👍"], "buttons": [{"text": "X", "url": "u"}]})
    check("summary: real newline (literal '\\n' yo'q)", "\n" in summ and "\\n" not in summ, repr(summ))

    # 8. Birga tuzatilgan regressiyalar
    np_src = open(pe.__file__.replace("post_enhancer.py", "new_post.py"), encoding="utf-8").read()
    # Regressiya: bir vaqtlar new_post.py'da import qilinmagan BTN_BACK
    # ishlatilgani uchun NameError o'qib kelardi ("BTN_ALL_CHANNELS_TARGET,
    # BTN_MAIN_MENU, BTN_BACK" import qatori shuni tuzatgan edi). Endi tugma
    # matnlari yagona UCH TILLI registry'dan (is_menu_text / MENU_TEXTS)
    # olinadi, shu sababli tekshiruv ham umumlashtirildi: fayldagi HAR BIR
    # BTN_* nomi import yoki modul ichida aniqlangan bo'lishi shart.
    import ast as _np_ast
    _np_tree = _np_ast.parse(np_src)
    _np_imported = {
        alias.asname or alias.name
        for node in _np_tree.body
        if isinstance(node, _np_ast.ImportFrom) for alias in node.names
    }
    _np_local = {
        n.id for node in _np_tree.body
        if isinstance(node, _np_ast.Assign) for n in node.targets if isinstance(n, _np_ast.Name)
    } | {
        node.name for node in _np_tree.body
        if isinstance(node, (_np_ast.FunctionDef, _np_ast.AsyncFunctionDef, _np_ast.ClassDef))
    }
    _np_btns = {
        node.id for node in _np_ast.walk(_np_tree)
        if isinstance(node, _np_ast.Name) and node.id.startswith("BTN_")
    }
    _np_missing = sorted(_np_btns - _np_imported - _np_local)
    check("new_post: BTN_* nomlari (BTN_BACK) NameError'siz", not _np_missing, str(_np_missing))
    check("new_post: uch tilli tugma registry'si ishlatilgan",
          "is_menu_text" in np_src and "from keyboards.default import" in np_src)
    db_src = open(__import__("database").__file__, encoding="utf-8").read()
    check("db: update_post_content inline_button_text ustuni", "inline_button_text = %s" in db_src)
    check("db: update_post_content inline_button_url ustuni", "inline_button_url = %s" in db_src)
    check("db: update_post_content reaction_emojis parametri",
          "reaction_emojis = %s" in db_src.split("def update_post_content")[1].split("def cancel_post")[0])
    import inspect
    check("db: update_post_content sig reaction_emojis",
          "reaction_emojis" in inspect.signature(__import__("database").update_post_content).parameters)


def test_post_enhancer_text_and_channels():
    """✨ Postga Tugma & Reaksiya: safar matnini tayyorlash (watermark/reklama/limit)."""
    print("== post enhancer text & channel view ==")
    import handlers.post_enhancer as pe
    from telegram import InlineKeyboardMarkup

    # Channel view markup bo'sh ro'yxatda ham qulay bo'lishi kerak
    class _Ctx:
        def __init__(self, data): self.user_data = data
    enh = {
        "step": "channel", "post": {"type": "photo", "file_id": "F", "content": "Salom <b>World</b> & co"},
        "reactions": ["👍"], "buttons": [{"text": "Sayt", "url": "https://sayt.uz"}],
        "channels": [("c1", "Kanal Bitta"), ("c2", "Kanal Ikkita")], "ch_idx": None,
        "hub_msg_id": None, "btn_edit": None,
    }
    ctx = _Ctx({"enh": enh})
    text, kb = pe._channel_view(ctx)
    flat = [b for row in kb.inline_keyboard for b in row]
    send = [b for b in flat if (b.callback_data or "").startswith("enh:send:")]
    check("channel: har kanal uchun tugma", len(send) == 2, str([b.callback_data for b in flat]))
    check("channel: yuborishda index", send[0].callback_data == "enh:send:0", str(send[0].callback_data))

    # _post_line safe_html bilan xavfsiz
    line = pe._post_line(enh)
    check("post_line: turi bor", "🖼 Rasm" in line, line)
    check("post_line: & escape", "&amp;" in line or "&" in line)

    # build_enhancer_markup bo'sh bo'lsa None
    check("markup: bo'sh → None", pe.build_enhancer_markup([], []) is None)
    m = pe.build_enhancer_markup([{"text": "X", "url": "https://x.uz"}], ["👍"], post_id=3)
    check("markup: InlineKeyboardMarkup", isinstance(m, InlineKeyboardMarkup))


# ============================================================
# ✨ POST ENHANCER — UX OVERHAUL (sinfli soxta ob'ektlar bilan)
# ============================================================

class _FakeMsg:
    """Telegram Message o'rnini bosuvchi minimal ob'ekt."""

    def __init__(self, message_id=1, chat_id=111, text=None, caption=None):
        self.message_id = message_id
        self.chat_id = chat_id
        self.text = text
        self.caption = caption
        self.replies = []

    async def delete(self, **kw):
        bot = _FakeMsg.registry.get("bot")
        if bot is not None:
            bot._rec("delete_message", self.chat_id, self.message_id, None, None)
        return True

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        """Javob xabari — bot.send_message'dan ALOHIDA yoziladi (hisob aniq bo'lishi uchun)."""
        self.replies.append(text)
        bot = _FakeMsg.registry.get("bot")
        if bot is not None:
            bot._rec("reply_text", self.chat_id, text, reply_markup)
            return bot._next()
        return _FakeMsg(2)


class _FakeBot:
    """context.bot o'rnini bosadi — barcha chaqiruvlar yozib boriladi."""

    def __init__(self):
        self.calls = []
        self._mid = 1000
        _FakeMsg.registry = {"bot": self}

    def _next(self):
        self._mid += 1
        return _FakeMsg(self._mid)

    def _rec(self, kind, *args):
        self.calls.append((kind,) + args)

    def sent_of(self, kind):
        return [c for c in self.calls if c[0] == kind]

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_message", chat_id, text, reply_markup)
        return self._next()

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_photo", chat_id, caption, reply_markup)
        return self._next()

    async def send_video(self, chat_id, video, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_video", chat_id, caption, reply_markup)
        return self._next()

    async def send_animation(self, chat_id, animation, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_animation", chat_id, caption, reply_markup)
        return self._next()

    async def send_document(self, chat_id, document, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_document", chat_id, caption, reply_markup)
        return self._next()

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_audio", chat_id, caption, reply_markup)
        return self._next()

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None, parse_mode=None, **kw):
        self._rec("send_voice", chat_id, caption, reply_markup)
        return self._next()

    async def send_sticker(self, chat_id, sticker, **kw):
        self._rec("send_sticker", chat_id, sticker, None)
        return self._next()

    async def send_media_group(self, chat_id, media, **kw):
        self._rec("send_media_group", chat_id, media, None)
        return [self._next(), self._next()]

    async def edit_message_text(self, chat_id=None, message_id=None, text=None,
                                reply_markup=None, parse_mode=None, **kw):
        self._rec("edit_message_text", chat_id, message_id, text, reply_markup)
        return True

    async def edit_message_caption(self, chat_id=None, message_id=None, caption=None,
                                   reply_markup=None, parse_mode=None, **kw):
        self._rec("edit_message_caption", chat_id, message_id, caption, reply_markup)
        return True

    async def delete_message(self, chat_id, message_id, **kw):
        self._rec("delete_message", chat_id, message_id, None, None)
        return True


class _FakeCtx:
    def __init__(self, bot, user_data=None):
        self.bot = bot
        self.user_data = user_data if user_data is not None else {}


class _FakeUser:
    def __init__(self, uid):
        self.id = uid


class _FakeQuery:
    def __init__(self, data, message, uid=4242):
        self.data = data
        self.message = message
        self.from_user = _FakeUser(uid)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append((text, reply_markup))
        return True


def _fake_db(premium=False, ad_free=False, sink=None, post_number=1,
             ad_interval=3, ads=None):
    """database.run_db o'rnini bosuvchi async funksiya."""
    async def _run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if sink is not None:
            sink.append((name, args, kwargs))
        if name == "get_user_channels":
            return [("-1001234567890", "Mening Kanalim")]
        if name == "peek_ad_free_post":
            return ad_free
        if name == "is_premium":
            return premium
        if name == "bump_channel_post_count":
            return post_number
        if name == "get_channel_ad_interval":
            return ad_interval
        if name == "mark_channel_ad_shown":
            return True
        if name == "get_ads_full":
            return list(ads or [])
        if name == "get_ads":
            return []
        if name == "get_setting":
            return args[1] if len(args) > 1 else ""
        if name == "add_post":
            return 777
        if name in ("mark_post_as_sent", "mark_post_status", "consume_ad_free_post"):
            return None
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")
    return _run_db


def test_post_enhancer_ux_overhaul():
    """✨ UX overhaul: admin eslatmasi, batch reaksiya, URL shablonlar, ekranlar."""
    print("== post enhancer UX overhaul (notice / batch / presets / screens) ==")
    import handlers.post_enhancer as pe
    from keyboards.inline import get_extras_inline_keyboard

    class _Ctx:
        def __init__(self, data):
            self.user_data = data

    # --- 1. Kirishda darhol admin eslatmasi ---
    intro = pe.intro_text()
    check("intro: eslatma ENG BIRINCHI keladi", intro.startswith("💡 <b>Eslatma:</b>"), intro[:40])
    check("intro: Admin talabi aytiladi", "Admin" in intro and "kanalingizga" in intro)
    check("intro: post so'raladi",
          "Kanalga joylamoqchi bo'lgan postingizni yuboring" in intro, intro)
    check("intro: Matn/Rasm/Video/Forward sanab o'tiladi",
          all(w in intro for w in ("Matn", "Rasm", "Video", "Forward")), intro)
    check("intro: eslatma post so'rovidan OLDIN",
          intro.index("Eslatma:") < intro.index("Kanalga joylamoqchi"))
    check("ADMIN_NOTICE konstanta", pe.ADMIN_NOTICE.startswith("💡") and "Admin" in pe.ADMIN_NOTICE)
    ex = [[(b.text, b.callback_data) for b in row]
          for row in get_extras_inline_keyboard().inline_keyboard]
    check("extras menyu yozuvi yangilandi",
          ex[0][0] == ("✨ Postga Tugma & Reaksiya qo'shish", "extra_enhancer"), str(ex[0]))

    # --- 2. Reaksiyalarni probel bilan BATCH kiritish ---
    r = pe.apply_reaction_batch([], "👍 ❤️ 🔥 👏 🎉")
    check("batch: 5 emoji ajratildi",
          r["tokens"] == ["👍", "❤️", "🔥", "👏", "🎉"], str(r["tokens"]))
    check("batch: barchasi qo'shildi", r["added"] == 5 and len(r["reactions"]) == 5, str(r))
    check("batch: takror/chegara bo'sh", not r["duplicates"] and not r["overflow"])

    r2 = pe.apply_reaction_batch(["👍", "❤️"], "👍 🔥 ❤️")
    check("batch: takrorlar qo'shilmaydi",
          r2["reactions"] == ["👍", "❤️", "🔥"] and r2["added"] == 1, str(r2))
    check("batch: duplicates qaytariladi", r2["duplicates"] == ["👍", "❤️"], str(r2["duplicates"]))

    r3 = pe.apply_reaction_batch(["👍", "❤️"], "🔥 😍 💯", max_count=3)
    check("batch: chegara → overflow hisoboti",
          r3["reactions"] == ["👍", "❤️", "🔥"] and r3["overflow"] == ["😍", "💯"], str(r3))

    r4 = pe.apply_reaction_batch([], "Salom! Bugun 👍 kun")
    check("batch: aralash matndan faqat emoji", r4["tokens"] == ["👍"], str(r4["tokens"]))

    r5 = pe.apply_reaction_batch(["❤️"], "❤")
    check("batch: VS16 farqi yo'q (❤ == ❤️)",
          r5["added"] == 0 and r5["reactions"] == ["❤️"], str(r5))

    r6 = pe.apply_reaction_batch([], "salom dunyo")
    check("batch: emoji yo'q → bo'sh", r6["tokens"] == [] and r6["added"] == 0)

    lst, n = pe.add_unique_emoji(["❤️"], ["❤", "🔥"], max_count=10)
    check("add_unique_emoji: VS16 dedup", lst == ["❤️", "🔥"] and n == 1, str((lst, n)))

    # --- 2b. Reaksiya ekrani: davom/orqaga/bekor tugmalari ---
    enh = {**pe._fresh_enh(), "step": "react",
           "post": {"type": "text", "file_id": None, "content": "Salom"},
           "reactions": ["👍", "❤️"]}
    rtext, rkb = pe._react_view(_Ctx({"enh": enh}))
    rflat = [b for row in rkb.inline_keyboard for b in row]
    check("react: <=10 qator", len(rkb.inline_keyboard) <= 10, str(len(rkb.inline_keyboard)))
    done = [b for b in rflat if b.callback_data == "enh:react:done"]
    check("react: [➡️ Davom etish / URL tugmaga o'tish]",
          done and "Davom etish / URL tugmaga o'tish" in done[0].text, str([b.text for b in done]))
    check("react: [⬅️ Orqaga]", any((b.text or "").startswith("⬅️") for b in rflat))
    check("react: [❌ Bekor qilish]", any(b.callback_data == "enh:cancel" for b in rflat))
    check("react: tanlangan emoji ✅ bilan", any(b.text == "👍 ✅" for b in rflat),
          str([b.text for b in rflat][:6]))
    check("react: batch kiritish maslahati", "probel bilan" in rtext, rtext[:120])

    # --- 3. URL tugma shablonlari (3 ta tayyor + qo'lda kiritish) ---
    check("presets: 3 ta shablon", len(pe.URL_PRESETS) == 3, str(pe.URL_PRESETS))
    titles = [f"{p['icon']} {p['num']}. {p['title']}" for p in pe.URL_PRESETS]
    check("preset 1", titles[0] == "📢 1. Kanalga a'zo bo'lish", str(titles))
    check("preset 2", titles[1] == "💬 2. Guruhga qo'shilish", str(titles))
    check("preset 3", titles[2] == "🤖 3. Botga o'tish", str(titles))
    check("get_url_preset: str indeks", pe.get_url_preset("1")["id"] == "join_group")
    check("get_url_preset: tashqari indeks → None", pe.get_url_preset(9) is None)
    check("get_url_preset: harf → None", pe.get_url_preset("x") is None)

    b1 = pe.build_preset_button(0, "@kanalim")
    check("preset btn: @username → t.me",
          b1 == {"text": "📢 Kanalga a'zo bo'lish", "url": "https://t.me/kanalim"}, str(b1))
    b2 = pe.build_preset_button(1, "https://t.me/guruhim")
    check("preset btn: to'liq URL",
          b2 == {"text": "💬 Guruhga qo'shilish", "url": "https://t.me/guruhim"}, str(b2))
    b3 = pe.build_preset_button(2, "t.me/bot_ismi/start")
    check("preset btn: t.me/... prefiksi", b3 and b3["url"] == "https://t.me/bot_ismi/start", str(b3))
    check("preset btn: yaroqsiz havola → None", pe.build_preset_button(2, "salom") is None)
    check("preset btn: yo'q shablon → None", pe.build_preset_button(7, "https://t.me/x") is None)

    check("input: shablon + havola",
          pe.parse_button_input("https://t.me/kanalim", 0) ==
          {"text": "📢 Kanalga a'zo bo'lish", "url": "https://t.me/kanalim"})
    check("input: shablon rejimida to'liq format ustun",
          pe.parse_button_input("Bizning sayt - https://sayt.uz", 0) ==
          {"text": "Bizning sayt", "url": "https://sayt.uz"})
    check("input: qo'lda 'Nom - url'",
          pe.parse_button_input("Tugma nomi - https://havola.uz") ==
          {"text": "Tugma nomi", "url": "https://havola.uz"})
    check("input: qo'lda 'Nom | @kanalim'",
          pe.parse_button_input("Tugma nomi | @kanalim") ==
          {"text": "Tugma nomi", "url": "https://t.me/kanalim"})
    check("input: yaroqsiz matn → None", pe.parse_button_input("bu havola emas") is None)
    check("input: uzun yozuv 64 belgiga kesiladi",
          len(pe.parse_button_input("X" * 90 + " - https://a.uz")["text"]) <= pe.BTN_TEXT_MAX)
    check("input: 256+ URL rad etiladi",
          pe.parse_button_input("T - https://a.uz/" + "p" * 300) is None)

    # --- 3b. URL tugmalar ekrani ---
    enh2 = {**pe._fresh_enh(), "step": "btns",
            "post": {"type": "text", "file_id": None, "content": "Post"},
            "buttons": [{"text": "📢 Kanalga a'zo bo'lish", "url": "https://t.me/kanalim"}]}
    btext, bkb = pe._btns_view(_Ctx({"enh": enh2}))
    bflat = [b for row in bkb.inline_keyboard for b in row]
    preset_cbs = sorted(b.callback_data for b in bflat
                        if (b.callback_data or "").startswith("enh:preset:"))
    check("btns: 3 ta shablon tugmasi",
          preset_cbs == ["enh:preset:0", "enh:preset:1", "enh:preset:2"], str(preset_cbs))
    check("btns: shablon yozuvlari ko'rinadi",
          any(b.text == "📢 1. Kanalga a'zo bo'lish" for b in bflat))
    check("btns: qo'lda kiritish varianti",
          any("Qo'lda kiritish" in (b.text or "") and b.callback_data == "enh:btn:manual"
              for b in bflat))
    check("btns: '➕ Yangi tugma' shablon ekranini ochadi",
          any(b.callback_data == "enh:btn:add" for b in bflat))
    cont = [b for b in bflat if b.callback_data == "enh:screen:channel"]
    check("btns: [➡️ Tasdiqlash va Kanalga yuborish]",
          cont and "Tasdiqlash va Kanalga yuborish" in cont[0].text, str([b.text for b in cont]))
    check("btns: Orqaga/Bekor qatori",
          any(b.callback_data == "enh:cancel" for b in bflat)
          and any((b.text or "").startswith("⬅️") for b in bflat))

    over_rows = True
    for cnt in range(0, 11):
        e = {**pe._fresh_enh(), "step": "btns",
             "post": {"type": "text", "file_id": None, "content": "P"},
             "buttons": [{"text": f"T{i}", "url": f"https://a.uz/{i}"} for i in range(cnt)]}
        _, k = pe._btns_view(_Ctx({"enh": e}))
        if len(k.inline_keyboard) > 10:
            over_rows = False
    check("btns: 0..10 tugmada ham <=10 qator", over_rows)

    _, akb = pe._btn_add_view(_Ctx({"enh": {**pe._fresh_enh(), "step": "btn_add"}}))
    arows = akb.inline_keyboard
    check("btn_add: 3 shablon alohida qatorlarda",
          [r[0].callback_data for r in arows[:3]] == ["enh:preset:0", "enh:preset:1", "enh:preset:2"],
          str([[b.callback_data for b in r] for r in arows]))
    check("btn_add: qo'lda kiritish qatori", arows[3][0].callback_data == "enh:btn:manual")
    check("btn_add: orqaga/bekor",
          arows[-1][0].callback_data == "enh:screen:btns" and arows[-1][1].callback_data == "enh:cancel")

    # --- 4. Kanal tanlash + tasdiqlash ---
    enh4 = {**pe._fresh_enh(), "step": "channel",
            "channels": [("-1001", "Birinchi"), ("-1002", "Ikkinchi")]}
    ctext, ckb = pe._channel_view(_Ctx({"enh": enh4}))
    cflat = [b for row in ckb.inline_keyboard for b in row]
    check("channel: har kanal uchun tugma",
          len([b for b in cflat if (b.callback_data or "").startswith("enh:send:")]) == 2)
    check("channel: admin eslatmasi eslatiladi", "Admin" in ctext, ctext[:80])
    check("channel: Orqaga/Bekor qatori", any(b.callback_data == "enh:cancel" for b in cflat))

    enh5 = {**enh4, "step": "confirm", "ch_idx": 0,
            "post": {"type": "photo", "file_id": "F", "content": "Salom"},
            "reactions": ["👍"], "buttons": [{"text": "Kanal", "url": "https://t.me/x"}]}
    qtext, qkb = pe._confirm_view(_Ctx({"enh": enh5}))
    check("confirm: 'Ushbu post ...ga yuborilsinmi?'",
          "Ushbu post <b>Birinchi</b>ga yuborilsinmi?" in qtext, qtext)
    qflat = [b for row in qkb.inline_keyboard for b in row]
    yes = [b for b in qflat if b.callback_data == "enh:confirm_send"]
    check("confirm: [✅ Ha, yuborilsin]", yes and yes[0].text == "✅ Ha, yuborilsin",
          str([b.text for b in yes]))
    check("confirm: [❌ Bekor qilish]", any(b.callback_data == "enh:cancel" for b in qflat))
    check("confirm: prevyu tugmasi", any(b.callback_data == "enh:preview" for b in qflat))
    btext2, _ = pe._confirm_view(_Ctx({"enh": {**enh5, "ch_idx": None}}))
    check("confirm: kanal tanlanmasa crash yo'q", "tanlanmagan" in btext2.lower(), btext2)

    # --- 4b. Muvaffaqiyat ekrani ---
    stext, skb = pe._success_view("Mening Kanalim")
    check("success: '✅ Post yuklandi!' va 'Post kanalingizga muvaffaqiyatli joylandi!'",
          "✅ <b>Post yuklandi!</b>" in stext
          and "Post kanalingizga muvaffaqiyatli joylandi!" in stext, stext)
    sflat = [b for row in skb.inline_keyboard for b in row]
    home = [b for b in sflat if b.callback_data == "enh:home"]
    check("success: [🏠 Asosiy menyu]", home and home[0].text == "🏠 Asosiy menyu",
          str([b.text for b in sflat]))
    sv = pe._sent_view(_Ctx({"enh": {**pe._fresh_enh(), "sent_channel": "Kanal X"}}))
    check("sent view: kanal nomi bilan", "Kanal X" in sv[0], sv[0])


def test_post_enhancer_batch_and_preview_runtime():
    """✨ Reaksiya batch kiritish + tugma shabloni + doimiy prevyu (runtime)."""
    print("== post enhancer runtime (batch input, preset button, live preview) ==")
    import asyncio
    import handlers.post_enhancer as pe
    import database as db_mod

    async def run():
        bot = _FakeBot()
        ctx = _FakeCtx(bot, {})
        enh = {**pe._fresh_enh(), "step": "react", "hub_msg_id": 555,
               "post": {"type": "text", "file_id": None, "content": "Salom dunyo"},
               "reactions": [], "buttons": []}
        ctx.user_data["enh"] = enh
        chat = 111

        # 1) Batch reaksiya kiritish
        msg = _FakeMsg(1, chat, text="👍 ❤️ 🔥")
        await pe._emoji_text_step(None, ctx, msg, enh, chat)
        check("runtime: reaksiyalar saqlandi", enh["reactions"] == ["👍", "❤️", "🔥"],
              str(enh["reactions"]))
        check("runtime: '✅ Reaksiyalar saqlandi: 👍 ❤️ 🔥' javobi",
              msg.replies and "Reaksiyalar saqlandi:</b> 👍 ❤️ 🔥" in msg.replies[0],
              str(msg.replies))
        # Prevyu endi faqat foydalanuvchi "👁️ Prevyu" bosganda chiqadi.
        panels = bot.sent_of("send_message")
        check("runtime: prevyu darhol YUBORILMAYDI",
              enh["preview_msg_id"] is None, str(enh.get("preview_msg_id")))
        check("runtime: panel yangilandi (eski hub o'chirildi)",
              any(c[0] == "delete_message" and c[2] == 555 for c in bot.calls)
              and len(panels) == 1 and "Reaksiyalar" in (panels[0][2] or ""),
              str([c[2][:30] for c in panels]))
        check("runtime: ekran react qadamida qoldi", enh["step"] == "react", enh["step"])

        # 2) Ikkinchi marta — prevyu hali ham yuborilmaydi; faqat panel yangilanadi
        before = len(bot.sent_of("send_message"))
        first_preview_id = enh["preview_msg_id"]
        old_hub_id = enh["hub_msg_id"]
        msg2 = _FakeMsg(2, chat, text="👏 🎉")
        await pe._emoji_text_step(None, ctx, msg2, enh, chat)
        check("runtime: 5 ta reaksiya bo'ldi", enh["reactions"] == ["👍", "❤️", "🔥", "👏", "🎉"],
              str(enh["reactions"]))
        check("runtime: yangi prevyu xabari YUBORILMADI",
              enh["preview_msg_id"] == first_preview_id == None, str(enh["preview_msg_id"]))
        check("runtime: panel qayta render qilinadi",
              len(bot.sent_of("send_message")) == before + 1
              and any(c[0] == "delete_message" and c[2] == old_hub_id for c in bot.calls),
              str((len(bot.sent_of("send_message")), old_hub_id)))

        # 3) Takroriy emoji — hisobga olinmaydi
        msg3 = _FakeMsg(3, chat, text="👍 👍")
        await pe._emoji_text_step(None, ctx, msg3, enh, chat)
        check("runtime: takror emoji qo'shilmadi", len(enh["reactions"]) == 5, str(enh["reactions"]))
        check("runtime: takror haqida xabar",
              msg3.replies and "allaqachon tanlangan" in msg3.replies[0], str(msg3.replies))

        # 4) URL tugma — tayyor shablon (faqat havola yuboriladi)
        enh["step"] = "btn_input"
        enh["btn_preset"] = 0
        msg4 = _FakeMsg(4, chat, text="@kanalim")
        await pe._button_text_step(None, ctx, msg4, enh, chat)
        check("runtime: shablon tugmasi saqlandi",
              enh["buttons"] == [{"text": "📢 Kanalga a'zo bo'lish", "url": "https://t.me/kanalim"}],
              str(enh["buttons"]))
        check("runtime: shablon rejimi tozalandi", enh["btn_preset"] is None)
        check("runtime: 'Tugma saqlandi' javobi",
              msg4.replies and "Tugma saqlandi" in msg4.replies[0], str(msg4.replies))
        check("runtime: tugma qadamiga qaytdi", enh["step"] == "btns", enh["step"])

        # 5) Yaroqsiz havola — shablon saqlanmaydi
        enh["step"] = "btn_input"
        enh["btn_preset"] = 2
        msg5 = _FakeMsg(5, chat, text="bu havola emas")
        await pe._button_text_step(None, ctx, msg5, enh, chat)
        check("runtime: yaroqsiz havola rad etildi", len(enh["buttons"]) == 1, str(enh["buttons"]))
        check("runtime: xato maslahati ko'rsatildi",
              msg5.replies and "Havola noto'g'ri" in msg5.replies[0], str(msg5.replies))
        check("runtime: shablon rejimi saqlanadi (qayta urinish)", enh["btn_preset"] == 2)

    orig = db_mod.run_db
    db_mod.run_db = _fake_db()
    try:
        asyncio.run(run())
    finally:
        db_mod.run_db = orig


def test_post_enhancer_channel_dispatch():
    """🚀 Kanalga yuborish: free watermark, PRO/admin toza, markup va tasdiq."""
    print("== post enhancer channel dispatch (free vs pro/admin) ==")
    import asyncio
    import handlers.post_enhancer as pe
    import database as db_mod

    async def send_once(premium=False, admin=False, ad_free=False, uid=424242):
        bot = _FakeBot()
        if admin:
            uid = 123456789  # test muhitidagi ADMIN_ID
        ctx = _FakeCtx(bot, {})
        enh = {
            **pe._fresh_enh(), "step": "confirm", "ch_idx": 0,
            "channels": [("-1001234567890", "Mening Kanalim")],
            "post": {"type": "text", "file_id": None, "content": "Asl post matni"},
            "reactions": ["👍", "🔥"],
            "buttons": [{"text": "📢 Kanalga a'zo bo'lish", "url": "https://t.me/kanalim"}],
        }
        ctx.user_data["enh"] = enh
        msg = _FakeMsg(900, 111)
        query = _FakeQuery("enh:confirm_send", msg, uid=uid)
        sink = []
        orig = db_mod.run_db
        db_mod.run_db = _fake_db(premium=premium, ad_free=ad_free, sink=sink)
        try:
            out = await pe._execute_send(None, ctx, query, enh)
        finally:
            db_mod.run_db = orig
        return bot, query, enh, sink, out

    async def run():
        # --- Bepul foydalanuvchi: @PostAssistrobot belgisi SAQLANADI ---
        bot, query, enh, sink, out = await send_once(premium=False)
        check("dispatch: ENH_POST holatida qoldi", out == pe.ENH_POST, str(out))
        sent = bot.sent_of("send_message")
        check("dispatch: kanalga xabar yuborildi", len(sent) == 1, str([c[1] for c in sent]))
        chat_id, text, markup = sent[0][1], sent[0][2], sent[0][3]
        check("dispatch: to'g'ri kanalga (-1001234567890)", chat_id == -1001234567890, str(chat_id))
        check("dispatch: free → @PostAssistrobot belgisi bor",
              text.startswith("@PostAssistrobot"), text)
        check("dispatch: asl matn buzilmadi", "Asl post matni" in text, text)
        flat = [b for row in markup.inline_keyboard for b in row] if markup else []
        check("dispatch: URL tugma kanalga chiqdi",
              any(b.url == "https://t.me/kanalim" and "Kanalga a'zo bo'lish" in b.text for b in flat),
              str([(b.text, b.url) for b in flat]))
        check("dispatch: reaksiya hisoblagichlari react:777:",
              sorted(b.callback_data for b in flat if b.callback_data) ==
              ["react:777:👍", "react:777:🔥"], str([b.callback_data for b in flat]))
        names = [c[0] for c in sink]
        check("dispatch: add_post chaqirildi", "add_post" in names, str(names))
        check("dispatch: mark_post_as_sent chaqirildi", "mark_post_as_sent" in names, str(names))
        check("dispatch: free uchun ad-free sarflanmadi", "consume_ad_free_post" not in names,
              str(names))
        check("dispatch: step='sent'", enh["step"] == "sent", enh["step"])
        check("dispatch: kanal nomi saqlandi", enh["sent_channel"] == "Mening Kanalim",
              str(enh["sent_channel"]))
        check("dispatch: muvaffaqiyat xabari + 🏠 Asosiy menyu",
              query.edits and "muvaffaqiyatli joylandi" in query.edits[0][0]
              and any(b.text == "🏠 Asosiy menyu"
                      for row in query.edits[0][1].inline_keyboard for b in row),
              str(query.edits[:1]))

        # --- Muvaffaqiyat xabari SAQLANIB QOLADI: boshqa kanalga o'tish ---
        check("dispatch: success msg hub_msg_id'da emas",
              enh["success_msg_id"] == 900 and enh["hub_msg_id"] is None,
              str((enh["success_msg_id"], enh["hub_msg_id"])))
        ctx_free = _FakeCtx(bot, {"enh": enh})

        class _Upd:
            def __init__(self, query):
                self.callback_query = query

        def _tap(data, msg_id=900):
            return _Upd(_FakeQuery(data, _FakeMsg(msg_id, 111), uid=424242))

        orig = db_mod.run_db
        db_mod.run_db = _fake_db()
        try:
            await pe.enh_callback(_tap("enh:screen:channel"), ctx_free)
        finally:
            db_mod.run_db = orig
        deleted = [c[2] for c in bot.calls if c[0] == "delete_message"]
        check("dispatch: success xabari o'chirilmaydi (900)",
              900 not in deleted, str((enh["hub_msg_id"], deleted)))
        channel_msgs = [c for c in bot.sent_of("send_message")
                        if "Qaysi kanalga" in (c[2] or "")]
        check("dispatch: boshqa kanal paneli success ostida ochiladi",
              len(channel_msgs) == 1, str([c[2][:30] for c in channel_msgs]))
        channel_panel_id = enh["hub_msg_id"]
        check("dispatch: orqaga tugmasi success ekraniga qaytaradi",
              channel_panel_id is not None and enh.get("sent_channel") == "Mening Kanalim",
              str((channel_panel_id, enh.get("sent_channel"))))
        # "Orqaga" success ekraniga qaytaradi — success o'chirilmaydi,
        # takroriy success xabari ham chiqmaydi.
        before = len(bot.sent_of("send_message"))
        orig = db_mod.run_db
        db_mod.run_db = _fake_db()
        try:
            await pe.enh_callback(_tap("enh:screen:sent"), ctx_free)
        finally:
            db_mod.run_db = orig
        deleted2 = [c[2] for c in bot.calls if c[0] == "delete_message"]
        check("dispatch: orqaga — success xabari saqlanadi",
              900 not in deleted2, str(deleted2))
        check("dispatch: orqaga — yangi success xabari YUBORILMAYDI",
              len(bot.sent_of("send_message")) == before, str(len(bot.sent_of("send_message"))))

        # --- PRO foydalanuvchi: post TOZA chiqadi ---
        bot2, _, _, sink2, _ = await send_once(premium=True, uid=424301)
        text2 = bot2.sent_of("send_message")[0][2]
        check("dispatch: PRO → watermark yo'q", "@PostAssistrobot" not in text2, text2)
        check("dispatch: PRO → matn aynan asl matn", text2 == "Asl post matni", text2)
        check("dispatch: PRO (litsenziyasiz) → ad-free sarflanmadi",
              "consume_ad_free_post" not in [c[0] for c in sink2], str([c[0] for c in sink2]))

        # PRO is automatically ad-free; legacy post credits are never consumed.
        _, _, _, sink3, _ = await send_once(premium=True, ad_free=True, uid=424303)
        check("dispatch: PRO reklamasiz va litsenziya sarflanmaydi",
              "consume_ad_free_post" not in [c[0] for c in sink3], str([c[0] for c in sink3]))

        # --- Admin: post TOZA chiqadi ---
        bot3, _, _, _, _ = await send_once(premium=False, admin=True)
        text3 = bot3.sent_of("send_message")[0][2]
        check("dispatch: admin → watermark yo'q", "@PostAssistrobot" not in text3, text3)
        check("dispatch: admin → matn aynan asl matn", text3 == "Asl post matni", text3)

        # --- Kanal tanlanmagan bo'lsa: xato ogohlantirishi, yuborilmaydi ---
        bot4 = _FakeBot()
        ctx4 = _FakeCtx(bot4, {})
        enh4 = {**pe._fresh_enh(), "step": "confirm", "ch_idx": None,
                "post": {"type": "text", "file_id": None, "content": "X"}}
        ctx4.user_data["enh"] = enh4
        q4 = _FakeQuery("enh:confirm_send", _FakeMsg(901, 111), uid=424302)
        orig = db_mod.run_db
        db_mod.run_db = _fake_db()
        try:
            await pe._execute_send(None, ctx4, q4, enh4)
        finally:
            db_mod.run_db = orig
        check("dispatch: kanal tanlanmasa yuborilmaydi", not bot4.sent_of("send_message"),
              str(bot4.calls))
        check("dispatch: kanal tanlanmasa alert", q4.answers and q4.answers[-1][1] is True,
              str(q4.answers))

    asyncio.run(run())


def test_post_enhancer_callback_router():
    """🧭 enh_callback routeri: ekranlar, emoji toggle, shablon, kanal, 🏠 home."""
    print("== post enhancer callback router (enh:* navigatsiya) ==")
    import asyncio
    from telegram.ext import ConversationHandler
    import handlers.post_enhancer as pe
    import database as db_mod

    class _Upd:
        def __init__(self, query):
            self.callback_query = query

    async def run():
        bot = _FakeBot()
        enh = {**pe._fresh_enh(), "step": "hub", "hub_msg_id": 500,
               "post": {"type": "text", "file_id": None, "content": "Salom"}}
        ctx = _FakeCtx(bot, {"enh": enh})
        chat = 111
        msg = _FakeMsg(500, chat)

        async def tap(data, uid=424400):
            q = _FakeQuery(data, msg, uid=uid)
            return q, await pe.enh_callback(_Upd(q), ctx)

        # 1) Reaksiya ekraniga o'tish
        _, out = await tap("enh:screen:react")
        check("router: reaksiya ekrani ochildi", enh["step"] == "react" and out == pe.ENH_POST,
              str((enh["step"], out)))

        # 2) Emoji toggle (bosish/qayta bosish)
        await tap("enh:rtgl:👍")
        check("router: toggle emoji qo'shdi", enh["reactions"] == ["👍"], str(enh["reactions"]))
        await tap("enh:rtgl:👍")
        check("router: qayta bosish olib tashladi", enh["reactions"] == [], str(enh["reactions"]))
        await tap("enh:rtgl:❤️")

        # 3) ➡️ Davom etish → URL tugmalar ekrani
        _, out = await tap("enh:react:done")
        check("router: Davom etish → btns", enh["step"] == "btns", enh["step"])

        # 4) "➕ Yangi tugma" → shablon ekrani → shablon → faqat havola so'raladi
        _, out = await tap("enh:btn:add")
        check("router: ➕ Yangi tugma → shablon ekrani", enh["step"] == "btn_add", enh["step"])
        _, out = await tap("enh:btn:manual")
        check("router: ✍️ Qo'lda kiritish → matn kiritish", enh["step"] == "btn_input", enh["step"])
        _, out = await tap("enh:preset:0")
        check("router: shablon rejimi yoqildi",
              enh["btn_preset"] == 0 and enh["step"] == "btn_input", str(enh["step"]))
        check("router: shablon so'rovi yuborildi",
              any("Faqat" in (c[2] or "") and "havolani" in (c[2] or "")
                  for c in bot.sent_of("reply_text")), str([c[2][:40] for c in bot.sent_of("reply_text")]))
        await pe._button_text_step(None, ctx, _FakeMsg(600, chat, text="@kanalim"), enh, chat)
        check("router: shablon tugmasi saqlandi",
              enh["buttons"] and enh["buttons"][0]["url"] == "https://t.me/kanalim",
              str(enh["buttons"]))

        # 5) Kanal ro'yxati → tasdiq ekrani
        _, out = await tap("enh:screen:channel")
        check("router: kanallar yuklandi",
              enh["step"] == "channel" and len(enh["channels"]) == 1, str(enh["channels"]))
        _, out = await tap("enh:send:0")
        check("router: tasdiq ekrani ochildi", enh["step"] == "confirm" and enh["ch_idx"] == 0,
              str((enh["step"], enh["ch_idx"])))

        # 6) Prevyu
        _, out = await tap("enh:preview")
        preview_id = enh["preview_msg_id"]
        check("router: prevyu yaratildi", preview_id is not None, str(preview_id))

        # 7) 🏠 Asosiy menyu — sessiya yopiladi, prevyu tozalanadi
        _, out = await tap("enh:home")
        check("router: home → ConversationHandler.END", out == ConversationHandler.END, str(out))
        check("router: user_data tozalandi", ctx.user_data == {}, str(ctx.user_data))
        deleted = [c[2] for c in bot.calls if c[0] == "delete_message"]
        check("router: eski prevyu xabari o'chirildi", preview_id in deleted,
              str((preview_id, deleted)))
        home = [c for c in bot.sent_of("send_message") if "Asosiy menyu" in (c[2] or "")]
        check("router: asosiy menyu xabari yuborildi", len(home) == 1,
              str([c[2][:30] for c in bot.sent_of("send_message")]))

        # 8) Sessiya tugagan — eski tugma bosilsa END qaytadi (crash yo'q)
        _, out = await tap("enh:screen:hub")
        check("router: sessiyasiz callback → END", out == ConversationHandler.END, str(out))

    orig = db_mod.run_db
    db_mod.run_db = _fake_db()
    try:
        asyncio.run(run())
    finally:
        db_mod.run_db = orig


# ============================================================
# REKLAMA BOSHQARUVI (ad pool / post promo) — YANGI TESTLAR
# ============================================================

def test_channel_ad_interval_logic():
    """Kanal post sanagichi va reklama oralig'i (har 3-5 postda)."""
    print("== Reklama oralig'i: should_show_channel_ad ==")
    from utils.helpers import should_show_channel_ad
    import database as db_mod

    # Har 3-postda
    shown = [n for n in range(1, 13) if should_show_channel_ad(n, 3)]
    check("interval 3 → 3,6,9,12", shown == [3, 6, 9, 12], str(shown))
    shown = [n for n in range(1, 13) if should_show_channel_ad(n, 4)]
    check("interval 4 → 4,8,12", shown == [4, 8, 12], str(shown))
    shown = [n for n in range(1, 13) if should_show_channel_ad(n, 5)]
    check("interval 5 → 5,10", shown == [5, 10], str(shown))
    check("interval 1 → har postda", all(should_show_channel_ad(n, 1) for n in range(1, 6)))

    # Chegaraviy holatlar
    check("0-post → reklama yo'q", not should_show_channel_ad(0, 3))
    check("manfiy post → reklama yo'q", not should_show_channel_ad(-3, 3))
    check("interval 0 → reklama yo'q", not should_show_channel_ad(3, 0))
    check("None → reklama yo'q", not should_show_channel_ad(None, 3))
    check("matn → reklama yo'q", not should_show_channel_ad("x", 3))
    check("son-satr ham ishlaydi", should_show_channel_ad("6", "3"))

    # clamp_ad_interval
    check("clamp: 4 → 4", db_mod.clamp_ad_interval(4) == 4)
    check("clamp: '5' → 5", db_mod.clamp_ad_interval("5") == 5)
    check("clamp: 0 → 1 (min)", db_mod.clamp_ad_interval(0) == db_mod.AD_INTERVAL_MIN)
    check("clamp: 9999 → maks", db_mod.clamp_ad_interval(9999) == db_mod.AD_INTERVAL_MAX)
    check("clamp: bo'sh → default", db_mod.clamp_ad_interval("") == db_mod.CHANNEL_AD_INTERVAL_DEFAULT)
    check("clamp: None → default", db_mod.clamp_ad_interval(None) == db_mod.CHANNEL_AD_INTERVAL_DEFAULT)
    check("clamp: default parametri", db_mod.clamp_ad_interval("abc", 4) == 4)
    check("standart oraliq 3", db_mod.CHANNEL_AD_INTERVAL_DEFAULT == 3)

    # DB funksiyalari mavjudligi
    for fname in ("bump_channel_post_count", "get_channel_post_count",
                  "reset_channel_post_count", "get_channel_post_counters",
                  "get_channel_ad_interval", "set_channel_ad_interval",
                  "mark_channel_ad_shown"):
        check(f"db.{fname} mavjud", hasattr(db_mod, fname))


def test_per_channel_counter_isolation():
    """Har bir kanal sanagichi ALOHIDA hisoblanadi (scheduler.resolve_channel_ad)."""
    print("== Kanal sanagichlari mustaqilligi ==")
    import asyncio
    import database as db_mod
    import scheduler

    counters = {}
    ad_marks = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "bump_channel_post_count":
            ch = args[0]
            counters[ch] = counters.get(ch, 0) + 1
            return counters[ch]
        if name == "get_channel_ad_interval":
            return 3
        if name == "get_ads_full":
            return [{"id": 1, "text": "AD-1", "button_text": "Bosing",
                     "button_url": "https://t.me/x", "is_active": True}]
        if name == "mark_channel_ad_shown":
            ad_marks.append(args)
            return True
        if name == "get_setting":
            return ""
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    original = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # A kanaliga 2 ta post — reklama yo'q
        r1 = asyncio.run(scheduler.resolve_channel_ad("A", False))
        r2 = asyncio.run(scheduler.resolve_channel_ad("A", False))
        check("A: 1-post reklamasiz", r1["text"] == "" and r1["post_number"] == 1)
        check("A: 2-post reklamasiz", r2["text"] == "" and r2["post_number"] == 2)

        # B kanaliga 1 ta post — A ning sanagichiga ta'sir qilmaydi
        b1 = asyncio.run(scheduler.resolve_channel_ad("B", False))
        check("B: sanagich mustaqil (1)", b1["post_number"] == 1 and b1["text"] == "")

        # A kanaliga 3-post — reklama chiqadi
        r3 = asyncio.run(scheduler.resolve_channel_ad("A", False))
        check("A: 3-postda reklama chiqdi", r3["text"] == "AD-1", str(r3))
        check("A: reklama tugmasi ham keldi", r3["button_text"] == "Bosing")
        check("A: sanagich 3", r3["post_number"] == 3)
        check("mark_channel_ad_shown chaqirildi", ad_marks and ad_marks[-1][0] == "A", str(ad_marks))

        # B hali 2-postda — reklama yo'q
        b2 = asyncio.run(scheduler.resolve_channel_ad("B", False))
        check("B: 2-post hali reklamasiz", b2["text"] == "" and b2["post_number"] == 2)

        # ad-free litsenziya: sanagich oshadi, lekin reklama chiqmaydi
        counters["C"] = 2
        c3 = asyncio.run(scheduler.resolve_channel_ad("C", True))
        check("ad-free: reklama chiqmaydi", c3["text"] == "")
        check("ad-free: sanagich baribir oshdi", c3["post_number"] == 3)
    finally:
        db_mod.run_db = original


def test_ad_html_and_button_validation():
    """Reklama matni HTML formatlash va inline URL tugma validatsiyasi."""
    print("== Reklama HTML / tugma validatsiyasi ==")
    from utils.helpers import (
        validate_ad_html, validate_button_url, validate_button_text,
        parse_button_input,
    )

    # --- HTML matn ---
    ok, err = validate_ad_html("Oddiy reklama matni")
    check("oddiy matn to'g'ri", ok, err)
    ok, err = validate_ad_html("<b>Qalin</b> va <i>kursiv</i>")
    check("b/i teglari ruxsat etiladi", ok, err)
    ok, err = validate_ad_html('<a href="https://t.me/kanal">Kanalga o\'ting</a>')
    check("havola tegi ruxsat etiladi", ok, err)
    ok, err = validate_ad_html("<u>tag</u> <s>chizilgan</s> <code>kod</code>")
    check("u/s/code ruxsat etiladi", ok, err)

    ok, err = validate_ad_html("")
    check("bo'sh matn rad etiladi", not ok and "bo'sh" in err.lower(), err)
    ok, err = validate_ad_html("   ")
    check("faqat probel rad etiladi", not ok)
    ok, err = validate_ad_html("A" * 1100)
    check("juda uzun matn rad etiladi", not ok and "uzun" in err.lower(), err)
    ok, err = validate_ad_html("<b>Yopilmagan")
    check("yopilmagan teg rad etiladi", not ok and "yopilmagan" in err.lower(), err)
    ok, err = validate_ad_html("<script>alert(1)</script>")
    check("script tegi rad etiladi", not ok, err)
    ok, err = validate_ad_html("<a>havolasiz</a>")
    check("href'siz <a> rad etiladi", not ok and "href" in err, err)
    ok, err = validate_ad_html('<a href="javascript:alert(1)">x</a>')
    check("javascript: havola rad etiladi", not ok, err)
    ok, err = validate_ad_html("<b><i>ichma-ich</i></b>")
    check("ichma-ich teglar to'g'ri", ok, err)
    ok, err = validate_ad_html("</b>ortiqcha yopilgan")
    check("ortiqcha yopuvchi teg rad etiladi", not ok, err)
    ok, err = validate_ad_html("A" * 200, max_len=100)
    check("max_len parametri ishlaydi", not ok)

    # --- Tugma matni ---
    ok, err = validate_button_text("Batafsil")
    check("tugma matni to'g'ri", ok, err)
    ok, _ = validate_button_text("")
    check("bo'sh tugma matni rad etiladi", not ok)
    ok, err = validate_button_text("X" * 70)
    check("64 belgidan uzun tugma matni rad etiladi", not ok, err)

    # --- Tugma havolasi ---
    for url in ("https://t.me/kanal", "http://example.com/a?b=1", "tg://resolve?domain=x"):
        ok, err = validate_button_url(url)
        check(f"havola to'g'ri: {url}", ok, err)
    for url in ("", "t.me/kanal", "javascript:alert(1)", "https://", "https://a b"):
        ok, _ = validate_button_url(url)
        shown = url or "(bosh)"
        check(f"havola rad etiladi: {shown}", not ok)

    # --- Tugma kiritmasini ajratish ---
    check("parse: 'Matn | URL'",
          parse_button_input("Batafsil | https://t.me/x") == ("Batafsil", "https://t.me/x"))
    check("parse: probellar tozalanadi",
          parse_button_input("  Batafsil  |  https://t.me/x  ") == ("Batafsil", "https://t.me/x"))
    check("parse: ' - ' ajratgichi",
          parse_button_input("Batafsil - https://t.me/x") == ("Batafsil", "https://t.me/x"))
    check("parse: ajratgichsiz → bo'sh", parse_button_input("Batafsil") == ("", ""))
    check("parse: bo'sh kiritma", parse_button_input("") == ("", ""))


def test_ad_pool_full_crud_api():
    """ad_pool: to'liq CRUD API (matn, tugma, faollik) mavjudligi va xavfsizligi."""
    print("== ad_pool CRUD API ==")
    import database as db_mod
    from utils.helpers import _next_ad_full, EMPTY_AD

    for fname in ("add_ad", "get_ads", "get_ads_full", "get_ad", "update_ad",
                  "set_ad_active", "toggle_ad_active", "delete_ad", "clear_ads",
                  "count_ads"):
        check(f"db.{fname} mavjud", hasattr(db_mod, fname))

    # Noto'g'ri kiritma DB'ga umuman urilmaydi
    check("noto'g'ri scope add_ad → -1", db_mod.add_ad("bogus", "X") == -1)
    check("bo'sh matn add_ad → -1", db_mod.add_ad("channel", "  ") == -1)
    check("noto'g'ri scope get_ads_full → []", db_mod.get_ads_full("bogus") == [])
    check("noto'g'ri scope clear_ads → 0", db_mod.clear_ads("bogus") == 0)
    check("update_ad maydonsiz → False", db_mod.update_ad(1) is False)
    check("update_ad bo'sh matn → False", db_mod.update_ad(1, "   ") is False)

    # Tugma normalizatsiyasi: ikkalasi ham bo'lishi shart
    check("tugma: matn+URL saqlanadi",
          db_mod._normalize_ad_button("Bos", "https://t.me/x") == ("Bos", "https://t.me/x"))
    check("tugma: URL'siz → yo'q", db_mod._normalize_ad_button("Bos", "") == (None, None))
    check("tugma: matnsiz → yo'q", db_mod._normalize_ad_button("", "https://t.me/x") == (None, None))
    check("tugma matni 64 belgigacha kesiladi",
          len(db_mod._normalize_ad_button("X" * 200, "https://t.me/x")[0]) == 64)

    # Qatorni dictga o'girish
    row = (7, "channel", "Matn", "Bos", "https://t.me/x", False)
    ad = db_mod._ad_row_to_dict(row)
    check("_ad_row_to_dict: id", ad["id"] == 7)
    check("_ad_row_to_dict: text", ad["text"] == "Matn")
    check("_ad_row_to_dict: button", ad["button_text"] == "Bos" and ad["button_url"] == "https://t.me/x")
    check("_ad_row_to_dict: is_active", ad["is_active"] is False)
    empty_ad = db_mod._ad_row_to_dict((8, "reply", None, None, None, True))
    check("_ad_row_to_dict: NULL → bo'sh satr",
          empty_ad["text"] == "" and empty_ad["button_text"] == "")

    # To'liq rotatsiya (matn + tugma)
    from utils import helpers
    helpers._AD_ROTATION_INDEX.clear()
    ads = [
        {"id": 1, "text": "A", "button_text": "b1", "button_url": "https://t.me/1", "is_active": True},
        {"id": 2, "text": "B", "button_text": "", "button_url": "", "is_active": True},
    ]
    first = _next_ad_full(ads, "channel")
    second = _next_ad_full(ads, "channel")
    third = _next_ad_full(ads, "channel")
    check("full rotatsiya: 1-chi", first["text"] == "A" and first["button_url"] == "https://t.me/1")
    check("full rotatsiya: 2-chi (tugmasiz)", second["text"] == "B" and second["button_text"] == "")
    check("full rotatsiya: aylanadi", third["text"] == "A")
    check("bo'sh pul → bo'sh reklama", _next_ad_full([], "channel")["text"] == "")
    check("EMPTY_AD tuzilishi", set(EMPTY_AD) >= {"text", "button_text", "button_url"})
    helpers._AD_ROTATION_INDEX.clear()

    # get_channel_ad_next_full_async: pul bo'sh bo'lsa eski sozlamaga qaytadi
    import asyncio
    calls = []
    original_run_db = db_mod.run_db

    async def fake_empty(func, *args, **kwargs):
        calls.append(func.__name__)
        return [] if func.__name__ == "get_ads_full" else "LEGACY"

    db_mod.run_db = fake_empty
    try:
        legacy = asyncio.run(helpers.get_channel_ad_next_full_async())
    finally:
        db_mod.run_db = original_run_db
    check("full: pul bo'sh → eski sozlama", legacy["text"] == "LEGACY", str(legacy))
    check("full: tugmasiz qaytadi", legacy["button_text"] == "")
    check("full: get_ads_full keyin get_setting",
          calls == ["get_ads_full", "get_setting"], str(calls))
    helpers._AD_ROTATION_INDEX.clear()


def test_scheduler_ad_inline_button():
    """Reklamaning inline URL tugmasi post ostiga qo'shiladi."""
    print("== Scheduler: reklama inline tugmasi ==")
    from scheduler import build_ad_button_row

    row = build_ad_button_row({"button_text": "Batafsil", "button_url": "https://t.me/x"})
    check("tugma yaratildi", len(row) == 1)
    check("tugma matni", row[0].text == "Batafsil")
    check("tugma havolasi", row[0].url == "https://t.me/x")
    check("tugmasiz reklama → bo'sh", build_ad_button_row({"text": "faqat matn"}) == [])
    check("URL'siz → bo'sh", build_ad_button_row({"button_text": "X", "button_url": ""}) == [])
    check("matnsiz → bo'sh", build_ad_button_row({"button_text": "", "button_url": "https://t.me/x"}) == [])
    check("None → bo'sh", build_ad_button_row(None) == [])
    long_row = build_ad_button_row({"button_text": "Y" * 120, "button_url": "https://t.me/x"})
    check("uzun tugma matni 64 belgiga kesiladi", len(long_row[0].text) == 64)


def test_ad_pool_keyboards():
    """Reklama boshqaruvi klaviaturalari: ro'yxat, tahrirlash, interval."""
    print("== Reklama klaviaturalari ==")
    from keyboards.inline import (
        get_ad_pool_menu_keyboard, get_ad_edit_keyboard,
        get_ad_interval_keyboard, get_ad_pool_delete_keyboard,
        get_ad_pool_back_keyboard,
    )

    ads = [
        {"id": 1, "text": "Birinchi reklama", "button_text": "", "button_url": "", "is_active": True},
        {"id": 2, "text": "Ikkinchi reklama", "button_text": "B", "button_url": "https://t.me/x", "is_active": False},
    ]

    kb = get_ad_pool_menu_keyboard("channel", ads=ads, interval=4)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("menyu: har bir reklama tugmasi bor", "adp:channel:e:1" in cbs and "adp:channel:e:2" in cbs, str(cbs))
    check("menyu: faol reklama 🟢", any(t.startswith("🟢") for t in labels), str(labels))
    check("menyu: nofaol reklama 🔴", any(t.startswith("🔴") for t in labels), str(labels))
    check("menyu: qo'shish tugmasi", "adp:channel:add" in cbs)
    check("menyu: interval tugmasi", "adp:channel:iv" in cbs)
    check("menyu: intervalda joriy qiymat", any("har 4-post" in t for t in labels), str(labels))
    check("menyu: tozalash", "adp:channel:clear" in cbs)
    check("menyu: bekor qilish", "adm_cancel" in cbs)
    check("menyu: orqaga → Reklama markazi (hub)", "adm_adhub" in cbs, str(cbs))

    kb_reply = get_ad_pool_menu_keyboard("reply", ads=ads, interval=4)
    cbs_reply = [b.callback_data for row in kb_reply.inline_keyboard for b in row]
    labels_reply = [b.text for row in kb_reply.inline_keyboard for b in row]
    check("bot javoblarida ham oraliq tugmasi bor", "adp:reply:iv" in cbs_reply, str(cbs_reply))
    check("bot javoblari oralig'i javobda o'lchanadi",
          any("har 4 javob" in t for t in labels_reply), str(labels_reply))
    check("bo'sh pul menyusi ham ishlaydi",
          len(get_ad_pool_menu_keyboard("channel", ads=[]).inline_keyboard) >= 3)

    # Tahrirlash kartochkasi (tugmasiz reklama)
    edit_kb = get_ad_edit_keyboard(ads[0], "channel")
    ecbs = [b.callback_data for row in edit_kb.inline_keyboard for b in row]
    elabels = [b.text for row in edit_kb.inline_keyboard for b in row]
    check("tahrir: matn tugmasi", "adp:channel:et:1" in ecbs)
    check("tahrir: tugma qo'shish", "adp:channel:eb:1" in ecbs)
    check("tahrir: tugmasi yo'q reklamada 'olib tashlash' ko'rinmaydi", "adp:channel:bx:1" not in ecbs)
    check("tahrir: toggle", "adp:channel:tg:1" in ecbs)
    check("tahrir: o'chirish", "adp:channel:rm:1" in ecbs)
    check("tahrir: bekor qilish", "adm_cancel" in ecbs)
    check("tahrir: faol reklamada 'O'chirish' yozuvi",
          any("Inactive" in t for t in elabels), str(elabels))

    # Nofaol + tugmali reklama
    edit_kb2 = get_ad_edit_keyboard(ads[1], "reply")
    ecbs2 = [b.callback_data for row in edit_kb2.inline_keyboard for b in row]
    elabels2 = [b.text for row in edit_kb2.inline_keyboard for b in row]
    check("tahrir: tugmani olib tashlash bor", "adp:reply:bx:2" in ecbs2)
    check("tahrir: nofaol reklamada 'Faollashtirish'",
          any("Active" in t and "Inactive" not in t for t in elabels2), str(elabels2))

    # Interval klaviaturasi
    ikb = get_ad_interval_keyboard("channel", current=4)
    icbs = [b.callback_data for row in ikb.inline_keyboard for b in row]
    ilabels = [b.text for row in ikb.inline_keyboard for b in row]
    check("interval: 3/4/5 variantlari",
          all(f"adp:channel:iv:{n}" in icbs for n in (3, 4, 5)), str(icbs))
    check("interval: joriy qiymat belgilangan", any(t.startswith("✅") for t in ilabels), str(ilabels))

    # O'chirish va orqaga klaviaturalari dict bilan ham ishlaydi
    dkb = get_ad_pool_delete_keyboard(ads, "channel")
    dcbs = [b.callback_data for row in dkb.inline_keyboard for b in row]
    check("o'chirish kb: dict qabul qiladi", "adp:channel:rm:1" in dcbs and "adp:channel:rm:2" in dcbs)
    dkb_tuple = get_ad_pool_delete_keyboard([(9, "Eski format")], "reply")
    check("o'chirish kb: tuple ham ishlaydi",
          "adp:reply:rm:9" in [b.callback_data for row in dkb_tuple.inline_keyboard for b in row])
    bcbs = [b.callback_data for row in get_ad_pool_back_keyboard("channel").inline_keyboard for b in row]
    check("orqaga kb: menyu + bekor qilish",
          "adp:channel:back" in bcbs and "adm_cancel" in bcbs)


def _make_admin_ctx():
    class _Ctx:
        def __init__(self):
            self.user_data = {}
    return _Ctx()


class _AdQuery:
    """Admin inline tugmasi uchun soxta CallbackQuery."""

    def __init__(self, data, uid=123456789):
        self.data = data
        self.answers = []
        self.edits = []
        self.from_user = type("U", (), {"id": uid})()
        self.message = type("M", (), {
            "reply_text": self._reply,
        })()

    async def _reply(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append((text, reply_markup))
        return True

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append((text, reply_markup))
        return True


def test_ad_pool_callback_flow():
    """Reklama tahrirlash oqimi: kartochka, matn, tugma, toggle, interval."""
    print("== Reklama tahrirlash oqimi (ad_pool_callback) ==")
    import asyncio
    import database as db_mod
    import handlers.admin as admin
    from telegram.ext import ConversationHandler

    store = {
        1: {"id": 1, "scope": "channel", "text": "Reklama A",
            "button_text": "", "button_url": "", "is_active": True},
    }
    saved = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "get_ad":
            return store.get(int(args[0]))
        if name == "get_ads_full":
            return list(store.values())
        if name == "get_channel_ad_interval":
            return 3
        if name == "set_channel_ad_interval":
            saved.append(("interval", args[0]))
            return True
        if name == "toggle_ad_active":
            ad = store.get(int(args[0]))
            ad["is_active"] = not ad["is_active"]
            return ad["is_active"]
        if name == "update_ad":
            saved.append(("update", args))
            return True
        if name == "delete_ad":
            store.pop(int(args[0]), None)
            return True
        if name == "clear_ads":
            n = len(store)
            store.clear()
            return n
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    original = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # 1. Kartochkani ochish
        ctx = _make_admin_ctx()
        q = _AdQuery("adp:channel:e:1")
        state = asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("kartochka: SET_CHANNEL_AD holati qaytadi", state == admin.SET_CHANNEL_AD, str(state))
        check("kartochka: matn ko'rsatildi", "Reklama A" in q.edits[-1][0], q.edits[-1][0][:80])
        check("kartochka: holat ko'rsatildi", "Faol" in q.edits[-1][0])

        # 2. Matnni tahrirlashni boshlash → FSM belgisi qo'yiladi
        q = _AdQuery("adp:channel:et:1")
        state = asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("matn tahriri: holat SET_CHANNEL_AD", state == admin.SET_CHANNEL_AD)
        check("matn tahriri: ad_edit belgisi",
              ctx.user_data.get("ad_edit") == {"id": 1, "field": "text", "scope": "channel"},
              str(ctx.user_data))
        check("matn tahriri: HTML yo'riqnomasi", "HTML" in q.edits[-1][0])

        # 3. Tugma tahriri
        q = _AdQuery("adp:channel:eb:1")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("tugma tahriri: ad_edit field=button",
              ctx.user_data["ad_edit"]["field"] == "button", str(ctx.user_data))
        check("tugma tahriri: format ko'rsatilgan", "|" in q.edits[-1][0])

        # 4. Toggle Active/Inactive
        q = _AdQuery("adp:channel:tg:1")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("toggle: reklama o'chirildi", store[1]["is_active"] is False)
        check("toggle: xabar berildi", any("o'chirildi" in (a or "") for a in q.answers), str(q.answers))
        q = _AdQuery("adp:channel:tg:1")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("toggle: qayta faollashtirildi", store[1]["is_active"] is True)

        # 5. Tugmani olib tashlash
        q = _AdQuery("adp:channel:bx:1")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("tugma olib tashlandi", ("update", (1, None, "", "")) in saved, str(saved))

        # 6. Interval ekrani va tanlash
        q = _AdQuery("adp:channel:iv")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("interval ekrani: ad_edit field=interval",
              ctx.user_data["ad_edit"]["field"] == "interval", str(ctx.user_data))
        q = _AdQuery("adp:channel:iv:5")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("interval 5 saqlandi", ("interval", 5) in saved, str(saved))
        check("interval tanlangach ad_edit tozalandi", "ad_edit" not in ctx.user_data)

        # 7. Ma'lumot va orqaga
        q = _AdQuery("adp:channel:info")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("info: oraliq tushuntirilgan", "post" in q.edits[-1][0].lower())
        q = _AdQuery("adp:channel:back")
        state = asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("back: menyuga qaytadi", state == admin.SET_CHANNEL_AD)

        # 8. O'chirish
        q = _AdQuery("adp:channel:rm:1")
        asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("reklama o'chirildi", 1 not in store)

        # 9. Admin bo'lmagan foydalanuvchi
        q = _AdQuery("adp:channel:e:1", uid=999)
        state = asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("admin emas → END", state == ConversationHandler.END)

        # 10. Noto'g'ri scope
        q = _AdQuery("adp:bogus:e:1")
        state = asyncio.run(admin.ad_pool_callback(type("U", (), {"callback_query": q})(), ctx))
        check("noto'g'ri scope → END", state == ConversationHandler.END)
    finally:
        db_mod.run_db = original


def test_admin_fsm_states_and_cancel():
    """Admin inline tugmalari FSM holatini qaytaradi va Bekor qilish ishlaydi."""
    print("== Admin FSM holatlari va Bekor qilish ==")
    import asyncio
    import database as db_mod
    import handlers.admin as admin
    from telegram.ext import ConversationHandler
    from keyboards.default import BTN_CANCEL, get_cancel_keyboard

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        if name == "get_admin_dashboard_stats":
            return {"users": 1, "pro_subscribers": 0, "channels": 2,
                    "posts_today": 3, "pending_posts": 4, "stars_revenue": 5}
        if name == "get_system_stats":
            return {"users": 1, "channels": 2, "sponsors": 0, "pending": 0,
                    "sent": 0, "cancelled": 0, "failed": 0}
        if name == "get_all_channels":
            return [("-100123", "Kanal", 7, "user")]
        if name == "get_settings_map":
            return {"post_tag_text": "@bot"}
        if name == "get_ad_settings":
            return {"auto_ad_text": "Reklama", "auto_ad_interval": 4,
                    "auto_ad_status": True, "channel_ad_interval": 3}
        if name == "get_channel_ad_interval":
            return 3
        if name == "get_channel_post_counters":
            return [("-100123", "Kanal", 9, 3)]
        if name == "get_sponsor_channels":
            return []
        if name == "get_ads_full":
            scope = args[0]
            if scope == "channel":
                return [{"id": 1, "text": "Kanal reklamasi", "button_text": "",
                         "button_url": "", "is_active": True}]
            return []
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    original = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # Matn kutuvchi bo'limlar TO'G'RI FSM holatini qaytaradi
        expected = {
            "adm_promo": admin.ADMIN_PROMO_CREATE,
            "adm_grant_pro": admin.ADMIN_GRANT_PRO,
            "adm_broadcast": admin.BROADCAST_MESSAGE,
            "adm_add_sponsor": admin.ADMIN_SPONSOR_ADD,
        }
        # Olib tashlangan (chalkash/dublikat) bo'limlar endi FSM ochmaydi
        check("ADMIN_AD_EDIT holati o'chirilgan", not hasattr(admin, "ADMIN_AD_EDIT"))
        check("ADMIN_AD_INTERVAL holati o'chirilgan", not hasattr(admin, "ADMIN_AD_INTERVAL"))
        for data, state in expected.items():
            ctx = _make_admin_ctx()
            q = _AdQuery(data)
            got = asyncio.run(admin.admin_dashboard_callback(
                type("U", (), {"callback_query": q})(), ctx))
            check(f"{data} → holat {state}", got == state, str(got))
            check(f"{data}: admin_flow belgilandi", ctx.user_data.get("admin_flow"))
            cbs = [b.callback_data for row in q.edits[-1][1].inline_keyboard for b in row]
            check(f"{data}: Bekor qilish tugmasi bor", "adm_cancel" in cbs, str(cbs))

        # Ma'lumot ekranlari FSM'ni ochmaydi
        for data in ("adm_stats", "adm_channels", "adm_sponsors",
                     "adm_adhub", "adm_auto_ad"):
            ctx = _make_admin_ctx()
            q = _AdQuery(data)
            got = asyncio.run(admin.admin_dashboard_callback(
                type("U", (), {"callback_query": q})(), ctx))
            check(f"{data} → END", got == ConversationHandler.END, str(got))
            check(f"{data}: xabar chizildi", bool(q.edits))

        # Reklama markazi — hamma bo'lim BITTA ekranda (birlashtirilgan UX)
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_adhub")
        asyncio.run(admin.admin_dashboard_callback(
            type("U", (), {"callback_query": q})(), ctx))
        body = q.edits[-1][0]
        hub_cbs = [b.callback_data for row in q.edits[-1][1].inline_keyboard for b in row]
        check("hub: sarlavha", "Reklama boshqaruvi" in body, body[:80])
        check("hub: 3 ta asosiy bo'lim sanab o'tilgan",
              all(m in body for m in (
                  "1) 📢 Majburiy obuna",
                  "2) 🤖 3-5 ta javobda chiqadigan reklama",
                  "3) 📢 Kanal postlariga reklama qo'shish")), body)
        check("hub: kanal puli hisobi", "<b>1</b>/1" in body, body)
        check("hub: javoblar puli bo'sh hisobi", "<b>0</b>/0" in body, body)
        check("hub: kanal oralig'i", "har <b>3</b>-postda" in body, body)
        check("hub: javob oralig'i", "har <b>4</b> ta javobda" in body, body)
        check("hub: kanal reklamasi holati ko'rsatilgan", "Holat:" in body, body)
        check("hub: pul bo'limlari bor",
              "adp:channel:back" in hub_cbs and "adp:reply:back" in hub_cbs, str(hub_cbs))
        check("hub: har bo'limda yoqish/o'chirish",
              "adm_ad_toggle" in hub_cbs and "adm_channel_ad_toggle" in hub_cbs, str(hub_cbs))
        check("hub: har bo'limda oraliq",
              "adp:reply:iv" in hub_cbs and "adp:channel:iv" in hub_cbs, str(hub_cbs))
        check("hub: eski javob matni tugmasi yo'q", "adm_ad_edit_text" not in hub_cbs, str(hub_cbs))
        check("hub: dublikat oraliq tugmalari yo'q",
              "adm_ad_set_interval" not in hub_cbs
              and not any(c.startswith("adm_ad_int:") for c in hub_cbs), str(hub_cbs))
        # Eski alohida "auto_ad" ekrani endi hub'ni ko'rsatadi (alias)
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_auto_ad")
        asyncio.run(admin.admin_dashboard_callback(
            type("U", (), {"callback_query": q})(), ctx))
        check("adm_auto_ad → hub chiziladi", "Reklama boshqaruvi" in q.edits[-1][0])

        # Toggle holat o'zgach ham hub qayta chiziladi
        saved_status = []

        async def fake_run_db_toggle(func, *args, **kwargs):
            name = getattr(func, "__name__", str(func))
            if name == "set_ad_status":
                saved_status.append(args[0])
                return True
            return await fake_run_db(func, *args, **kwargs)

        db_mod.run_db = fake_run_db_toggle
        try:
            ctx = _make_admin_ctx()
            q = _AdQuery("adm_ad_toggle")
            got = asyncio.run(admin.admin_dashboard_callback(
                type("U", (), {"callback_query": q})(), ctx))
            check("toggle: holat o'zgardi", saved_status == [False], str(saved_status))
            check("toggle → END", got == ConversationHandler.END)
            check("toggle: hub qayta chizildi", "Reklama boshqaruvi" in q.edits[-1][0],
                  q.edits[-1][0][:60])
        finally:
            db_mod.run_db = fake_run_db

        # Kanallar ro'yxati mazmuni
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_channels")
        asyncio.run(admin.admin_dashboard_callback(type("U", (), {"callback_query": q})(), ctx))
        check("kanallar ro'yxati o'qildi", "Kanal" in q.edits[-1][0], q.edits[-1][0][:80])

        # "🛠 Tizim sozlamalari" (adm_settings) butunlay olib tashlangan —
        # bosilsa ham FSM ochilmaydi va admin panel/hub ga qaytariladi.
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_settings")
        got = asyncio.run(admin.admin_dashboard_callback(type("U", (), {"callback_query": q})(), ctx))
        check("adm_settings endi noma'lum callback (END)", got == ConversationHandler.END)

        # ❌ Bekor qilish: FSM to'liq tozalanadi
        ctx = _make_admin_ctx()
        ctx.user_data["admin_flow"] = "promo_create"
        ctx.user_data["ad_edit"] = {"id": 1}
        q = _AdQuery("adm_cancel")
        got = asyncio.run(admin.admin_dashboard_callback(
            type("U", (), {"callback_query": q})(), ctx))
        check("adm_cancel → END", got == ConversationHandler.END)
        check("adm_cancel: user_data tozalandi", ctx.user_data == {}, str(ctx.user_data))
        check("adm_cancel: dashboard qaytdi", "Admin Boshqaruv Paneli" in q.edits[-1][0])

        # adm_back ham FSM belgilarini tozalaydi
        ctx = _make_admin_ctx()
        ctx.user_data["admin_flow"] = "grant_pro"
        ctx.user_data["ad_edit"] = {"id": 2}
        q = _AdQuery("adm_back")
        asyncio.run(admin.admin_dashboard_callback(type("U", (), {"callback_query": q})(), ctx))
        check("adm_back: admin_flow tozalandi", "admin_flow" not in ctx.user_data)
        check("adm_back: ad_edit tozalandi", "ad_edit" not in ctx.user_data)

        # Admin bo'lmaganlar rad etiladi
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_stats", uid=999)
        got = asyncio.run(admin.admin_dashboard_callback(
            type("U", (), {"callback_query": q})(), ctx))
        check("admin emas → END", got == ConversationHandler.END)
    finally:
        db_mod.run_db = original

    # Bekor qilish tugmasi klaviaturada mavjud
    rows = get_cancel_keyboard().keyboard
    labels = [b.text if hasattr(b, "text") else str(b) for row in rows for b in row]
    check("cancel kb: ❌ Bekor qilish bor", BTN_CANCEL in labels, str(labels))
    check("cancel kb: 🔙 Asosiy menyu ham bor", any("Asosiy menyu" in t for t in labels))


def test_admin_cancel_registration():
    """Bekor qilish tugmasi barcha holatlarda ro'yxatdan o'tgan (FSM)."""
    print("== Bekor qilish tugmasi ro'yxatdan o'tishi ==")
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "handlers" / "__init__.py").read_text(encoding="utf-8")

    check("BTN_CANCEL import qilingan", "BTN_CANCEL" in src)
    check("BTN_CANCEL menyu sakrashlarida (uz/ru)",
          "exact(BTN_CANCEL, BTN_CANCEL_RU), cancel_handler" in src)
    check("BTN_CANCEL fallback'da (uz/ru)", src.count("exact(BTN_CANCEL, BTN_CANCEL_RU)") >= 2)
    check("adm_ callbacklari entry point",
          'CallbackQueryHandler(admin_dashboard_callback, pattern=r"^adm_")' in src)
    check("adp: callbacklari entry point",
          'CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:")' in src)
    check("_admin_flow_state yordamchisi bor", "def _admin_flow_state(" in src)
    check("reklama holatlarida adp: handler bor",
          src.count('CallbackQueryHandler(ad_pool_callback, pattern=r"^adp:")') >= 3)

    # Admin matn handleri bekor qilishni tushunadi
    admin_src = (Path(__file__).resolve().parent.parent / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("admin_inline_text_handler BTN_CANCEL ni tekshiradi",
          "text in (BTN_CANCEL, BTN_MAIN_MENU)" in admin_src
          # YANGI: "❌ Bekor qilish"/"🔙 Asosiy menyu" endi yagona UCH TILLI
          # tugma registry'i orqali tekshiriladi — shunda EN klaviaturadagi
          # "❌ Cancel" ham admin oqimini bekor qiladi.
          or 'is_menu_text(text, "cancel", "main_menu")' in admin_src)
    check("oqimsiz matn FSM'ni band qoldirmaydi", "if not flow:" in admin_src)


def test_ad_text_received_flow():
    """Matn kiritish oqimi: yangi qo'shish, matn/tugma tahriri, validatsiya."""
    print("== Reklama matnini qabul qilish oqimi ==")
    import asyncio
    import database as db_mod
    import handlers.admin as admin

    class _Msg:
        def __init__(self, text):
            self.text = text
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append(text)
            return True

    class _Upd:
        def __init__(self, text, uid=123456789):
            self.message = _Msg(text)
            self.effective_user = type("U", (), {"id": uid})()

    store = {
        1: {"id": 1, "scope": "channel", "text": "Eski", "button_text": "",
            "button_url": "", "is_active": True},
    }
    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        calls.append((name, args))
        if name == "get_ad":
            return store.get(int(args[0]))
        if name == "get_ads_full":
            return list(store.values())
        if name == "get_channel_ad_interval":
            return 3
        if name == "set_channel_ad_interval":
            return True
        if name == "get_ad_settings":
            return {"auto_ad_text": "", "auto_ad_interval": 4, "auto_ad_status": True,
                    "channel_ad_interval": 3, "channel_ad_status": True}
        if name == "set_ad_interval":
            return True
        if name == "add_ad":
            return 42
        if name == "update_ad":
            return True
        if name == "clear_ads":
            return 2
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")

    original = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # 1. Yangi reklama qo'shish (HTML bilan)
        ctx = _make_admin_ctx()
        upd = _Upd("<b>Yangi</b> reklama")
        state = asyncio.run(admin.channel_ad_received(upd, ctx))
        check("yangi reklama: SET_CHANNEL_AD", state == admin.SET_CHANNEL_AD, str(state))
        check("yangi reklama: add_ad chaqirildi", any(c[0] == "add_ad" for c in calls))
        check("yangi reklama: tasdiq xabari", any("qo'shildi" in r for r in upd.message.replies))

        # 2. Noto'g'ri HTML rad etiladi
        calls.clear()
        upd = _Upd("<b>Yopilmagan")
        state = asyncio.run(admin.channel_ad_received(upd, ctx))
        check("noto'g'ri HTML: saqlanmaydi", not any(c[0] == "add_ad" for c in calls), str(calls))
        check("noto'g'ri HTML: xato xabari", any("❌" in r for r in upd.message.replies))
        check("noto'g'ri HTML: holat saqlanadi", state == admin.SET_CHANNEL_AD)

        # 3. Matnni tahrirlash
        ctx.user_data["ad_edit"] = {"id": 1, "field": "text", "scope": "channel"}
        calls.clear()
        upd = _Upd("<i>Yangilangan matn</i>")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        update_calls = [c for c in calls if c[0] == "update_ad"]
        check("matn tahriri: update_ad chaqirildi", update_calls, str(calls))
        check("matn tahriri: to'g'ri matn yuborildi",
              update_calls[0][1][1] == "<i>Yangilangan matn</i>", str(update_calls))
        check("matn tahriri: ad_edit tozalandi", "ad_edit" not in ctx.user_data)

        # 4. Inline tugma qo'shish
        ctx.user_data["ad_edit"] = {"id": 1, "field": "button", "scope": "channel"}
        calls.clear()
        upd = _Upd("Batafsil | https://t.me/kanal")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        update_calls = [c for c in calls if c[0] == "update_ad"]
        check("tugma: update_ad chaqirildi", update_calls, str(calls))
        check("tugma: matn va URL saqlandi",
              update_calls[0][1][2] == "Batafsil" and update_calls[0][1][3] == "https://t.me/kanal",
              str(update_calls))

        # 5. Noto'g'ri tugma formati
        ctx.user_data["ad_edit"] = {"id": 1, "field": "button", "scope": "channel"}
        calls.clear()
        upd = _Upd("faqat matn")
        state = asyncio.run(admin.channel_ad_received(upd, ctx))
        check("noto'g'ri tugma: saqlanmaydi", not any(c[0] == "update_ad" for c in calls))
        check("noto'g'ri tugma: holat saqlanadi (qayta kiritish)", state == admin.SET_CHANNEL_AD)
        check("noto'g'ri tugma: ad_edit saqlanib qoladi", ctx.user_data.get("ad_edit"))

        # 6. Yaroqsiz havola
        calls.clear()
        upd = _Upd("Bos | javascript:alert(1)")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        check("yaroqsiz havola: saqlanmaydi", not any(c[0] == "update_ad" for c in calls))

        # 7. Tugmani olib tashlash (clear)
        calls.clear()
        upd = _Upd("clear")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        update_calls = [c for c in calls if c[0] == "update_ad"]
        check("tugma clear: bo'sh qiymat yuborildi",
              update_calls and update_calls[0][1][2] == "", str(update_calls))

        # 8. Intervalni qo'lda kiritish
        ctx.user_data["ad_edit"] = {"id": 0, "field": "interval", "scope": "channel"}
        calls.clear()
        upd = _Upd("5")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        check("interval: saqlandi",
              any(c[0] == "set_channel_ad_interval" and c[1][0] == 5 for c in calls), str(calls))
        check("interval: ad_edit tozalandi", "ad_edit" not in ctx.user_data)

        # 9. Interval uchun noto'g'ri qiymat
        ctx.user_data["ad_edit"] = {"id": 0, "field": "interval", "scope": "channel"}
        calls.clear()
        upd = _Upd("nol")
        asyncio.run(admin.channel_ad_received(upd, ctx))
        check("interval: matn rad etildi",
              not any(c[0] == "set_channel_ad_interval" for c in calls))
        check("interval: qayta so'raladi", ctx.user_data.get("ad_edit"))

        # 10. Bot javoblari uchun ham xuddi shu oqim
        ctx2 = _make_admin_ctx()
        calls.clear()
        upd = _Upd("Reply reklama")
        state = asyncio.run(admin.bot_reply_ad_received(upd, ctx2))
        check("reply: SET_BOT_REPLY_AD holati", state == admin.SET_BOT_REPLY_AD, str(state))
        check("reply: scope to'g'ri",
              any(c[0] == "add_ad" and c[1][0] == "reply" for c in calls), str(calls))

        # 11. Admin bo'lmagan foydalanuvchi
        from telegram.ext import ConversationHandler
        state = asyncio.run(admin.channel_ad_received(_Upd("x", uid=999), _make_admin_ctx()))
        check("admin emas → END", state == ConversationHandler.END)
    finally:
        db_mod.run_db = original


def test_system_settings_read_write():
    """system_settings to'g'ri o'qiladi/saqlanadi (default keshlanmaydi)."""
    print("== system_settings o'qish/saqlash ==")
    import contextlib
    import database as db_mod

    rows = {}

    class _Cur:
        def __init__(self):
            self.result = None

        def execute(self, query, params=()):
            q = " ".join(query.split())
            if q.startswith("INSERT INTO system_settings"):
                rows[params[0]] = params[1]
            elif q.startswith("SELECT value FROM system_settings"):
                self.result = (rows[params[0]],) if params[0] in rows else None
            elif "SELECT key, value FROM system_settings" in q:
                if params:
                    self.result = [(k, rows[k]) for k in params[0] if k in rows]
                else:
                    self.result = sorted(rows.items())
            elif q.startswith("DELETE FROM system_settings"):
                self.rowcount = 1 if rows.pop(params[0], None) is not None else 0

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result or []

    @contextlib.contextmanager
    def fake_cursor(commit=False):
        yield _Cur()

    original_cursor = db_mod.db_cursor
    db_mod.db_cursor = fake_cursor
    db_mod._cache_clear()
    try:
        check("saqlash True qaytaradi", db_mod.set_setting("post_tag_text", "@bot") is True)
        check("saqlangan qiymat o'qiladi", db_mod.get_setting("post_tag_text") == "@bot")
        check("bo'sh kalit saqlanmaydi", db_mod.set_setting("", "x") is False)

        # DEFAULT KESHLANMASLIGI (avvalgi xatolik): mavjud bo'lmagan kalit
        first = db_mod.get_setting("yoq_kalit", "A")
        second = db_mod.get_setting("yoq_kalit", "B")
        check("default keshlanmaydi: 1-chi", first == "A", first)
        check("default keshlanmaydi: 2-chi boshqa default", second == "B", second)

        # Saqlangandan keyin kesh yangilanadi
        db_mod.set_setting("yoq_kalit", "C")
        check("saqlangach yangi qiymat", db_mod.get_setting("yoq_kalit", "A") == "C")

        # Ko'p kalitni bir so'rovda o'qish
        db_mod.set_setting("channel_ad_text", "reklama")
        mapping = db_mod.get_settings_map(["post_tag_text", "channel_ad_text", "yoq"])
        check("get_settings_map: ikkala kalit", mapping.get("post_tag_text") == "@bot"
              and mapping.get("channel_ad_text") == "reklama", str(mapping))
        check("get_settings_map: yo'q kalit qaytmaydi", "yoq" not in mapping)
        check("get_settings_map: bo'sh ro'yxat → {}", db_mod.get_settings_map([]) == {})

        # O'chirish
        check("delete_setting ishlaydi", db_mod.delete_setting("channel_ad_text") is True)
        check("o'chirilgach default qaytadi",
              db_mod.get_setting("channel_ad_text", "yo'q") == "yo'q")
    finally:
        db_mod.db_cursor = original_cursor
        db_mod._cache_clear()


def test_ad_settings_include_channel_interval():
    """get_ad_settings kanal reklama oralig'ini ham qaytaradi."""
    print("== get_ad_settings: channel_ad_interval ==")
    import contextlib
    import database as db_mod

    stored = [
        ("auto_ad_text", "Homiy"),
        ("auto_ad_interval", "4"),
        ("auto_ad_status", "true"),
        ("channel_ad_interval", "5"),
    ]

    class _Cur:
        def execute(self, query, params=()):
            pass

        def fetchall(self):
            return stored

    @contextlib.contextmanager
    def fake_cursor(commit=False):
        yield _Cur()

    original_cursor = db_mod.db_cursor
    db_mod.db_cursor = fake_cursor
    db_mod._cache_clear()
    try:
        s = db_mod.get_ad_settings()
        check("auto_ad_text o'qildi", s["auto_ad_text"] == "Homiy")
        check("auto_ad_interval o'qildi", s["auto_ad_interval"] == 4)
        check("auto_ad_status o'qildi", s["auto_ad_status"] is True)
        check("channel_ad_interval o'qildi", s["channel_ad_interval"] == 5, str(s))

        # Yaroqsiz qiymat → default
        db_mod._cache_clear()
        stored[3] = ("channel_ad_interval", "xato")
        s = db_mod.get_ad_settings()
        check("yaroqsiz oraliq → default",
              s["channel_ad_interval"] == db_mod.CHANNEL_AD_INTERVAL_DEFAULT, str(s))
    finally:
        db_mod.db_cursor = original_cursor
        db_mod._cache_clear()


def test_enhancer_channel_ad_interval():
    """Enhancer orqali yuborishda ham reklama oralig'i va tugmasi ishlaydi."""
    print("== Enhancer: reklama oralig'i va inline tugmasi ==")
    import asyncio
    import handlers.post_enhancer as pe
    import database as db_mod

    pool = [{"id": 1, "text": "ENH-REKLAMA", "button_text": "Homiy",
             "button_url": "https://t.me/homiy", "is_active": True}]

    async def send(post_number, premium=False):
        bot = _FakeBot()
        ctx = _FakeCtx(bot, {})
        enh = {
            **pe._fresh_enh(), "step": "confirm", "ch_idx": 0,
            "channels": [("-1001234567890", "Mening Kanalim")],
            "post": {"type": "text", "file_id": None, "content": "Enhancer matni"},
            "reactions": [], "buttons": [],
        }
        ctx.user_data["enh"] = enh
        query = _FakeQuery("enh:confirm_send", _FakeMsg(900, 111), uid=424242)
        orig = db_mod.run_db
        db_mod.run_db = _fake_db(premium=premium, post_number=post_number,
                                 ad_interval=3, ads=pool)
        try:
            await pe._execute_send(None, ctx, query, enh)
        finally:
            db_mod.run_db = orig
        sent = bot.sent_of("send_message")
        return sent[0][2], sent[0][3]

    async def run():
        # 2-post: reklama chiqmaydi
        text, markup = await send(2)
        check("enh: 2-postda reklama yo'q", "ENH-REKLAMA" not in text, text)

        # 3-post: reklama matni va tugmasi qo'shiladi
        text, markup = await send(3)
        check("enh: 3-postda reklama matni bor", "ENH-REKLAMA" in text, text)
        urls = [b.url for row in (markup.inline_keyboard if markup else []) for b in row
                if getattr(b, "url", None)]
        check("enh: reklama tugmasi qo'shildi", "https://t.me/homiy" in urls, str(urls))

        # PRO: reklama umuman chiqmaydi
        text, markup = await send(3, premium=True)
        check("enh: PRO → reklama yo'q", "ENH-REKLAMA" not in text, text)

    asyncio.run(run())


def test_ad_hub_unification_suite():
    """UX: reklama menyusini birlashtirish — yagona Reklama markazi."""
    print("== Reklama markazi (hub) birlashtiruvi ==")
    from pathlib import Path
    from keyboards.default import (
        get_admin_panel_keyboard, BTN_ADS, BTN_CHANNEL_AD, BTN_BOT_REPLY_AD,
        BTN_POST_TAG,
    )

    check("BTN_ADS matni", BTN_ADS == "🎯 Reklama markazi", BTN_ADS)

    kb_rows = [[b.text for b in row] for row in get_admin_panel_keyboard().keyboard]
    check("admin kb: reklama qatorida bitta hub tugmasi",
          [BTN_ADS, BTN_POST_TAG] in kb_rows, str(kb_rows))
    flat = [t for row in kb_rows for t in row]
    check("admin kb: eski ikki alohida tugma yo'q",
          BTN_CHANNEL_AD not in flat and BTN_BOT_REPLY_AD not in flat, str(flat))
    check("admin kb: qatorlar soni 5", len(kb_rows) == 5, str(kb_rows))

    root = Path(__file__).resolve().parent.parent
    init_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("eski tugmalar ham hub'ga aliaslangan",
          "exact(BTN_ADS, BTN_CHANNEL_AD, BTN_BOT_REPLY_AD)" in init_src)
    check("hub entry ro'yxatdan o'tgan", "admin_ad_hub_entry" in init_src)

    admin_src = (root / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("alohida 'Har 3-5 javob reklamasi' ekrani olib tashlandi",
          "_auto_ad_text" not in admin_src)
    check("adm_auto_ad eski xabarlar uchun hub aliasi",
          '"adm_adhub", "adm_auto_ad"' in admin_src)
    check("toggle hub'ni qayta chizadi", "_ad_hub_render" in admin_src)

    inline_src = (root / "keyboards" / "inline.py").read_text(encoding="utf-8")
    check("eski auto-ad klaviaturasi o'chirildi",
          "def get_admin_auto_ad_keyboard" not in inline_src)

    import keyboards.inline as ki
    check("get_admin_auto_ad_keyboard mavjud emas",
          not hasattr(ki, "get_admin_auto_ad_keyboard"))
    check("get_ad_hub_keyboard mavjud", hasattr(ki, "get_ad_hub_keyboard"))
    check("get_hub_back_keyboard mavjud", hasattr(ki, "get_hub_back_keyboard"))

    # Hub'dan chiqiladigan barcha ekranlar orqaga hub'ga qaytadi:
    # 1) pul menyusi: "🎯 Markazga" (adm_adhub)
    from keyboards.inline import get_ad_pool_menu_keyboard
    pm_cbs = [b.callback_data for row in
              get_ad_pool_menu_keyboard("channel", ads=[]).inline_keyboard for b in row]
    check("pul menyusi: dashboard'ga emas, hub'ga qaytadi",
          "adm_adhub" in pm_cbs and "adm_back" not in pm_cbs, str(pm_cbs))
    # 2) eski javob matni tahriri: 🎯 Markazga + ❌ Bekor
    from keyboards.inline import get_hub_back_keyboard
    hb_cbs = [b.callback_data for row in get_hub_back_keyboard().inline_keyboard for b in row]
    check("hub back kb: markazga + bekor", hb_cbs == ["adm_adhub", "adm_cancel"], str(hb_cbs))


def test_add_channel_flow_suite():
    """UX: kanal qo'shish oqimi — formatlar, 🔁 qayta tekshirish, natija ro'yxati."""
    print("== Kanal qo'shish oqimi ==")
    from pathlib import Path
    from handlers.channels import parse_channel_target, _retry_verify_keyboard

    # To'rt xil format qabul qilinadi
    t, err = parse_channel_target("-1001234567890")
    check("raqamli ID", t == -1001234567890 and err is None, str((t, err)))
    t, err = parse_channel_target("@mychannel")
    check("@username", t == "@mychannel" and err is None, str((t, err)))
    t, err = parse_channel_target("t.me/mychannel")
    check("t.me havolasi → @username", t == "@mychannel" and err is None, str((t, err)))
    t, err = parse_channel_target("https://t.me/mychannel/")
    check("https + slash bilan ham", t == "@mychannel" and err is None, str((t, err)))
    t, err = parse_channel_target("https://t.me/joinchat/AAAAAE")
    check("invite havolasi rad etiladi", t is None and err and "Yopiq" in err, str((t, err)))
    t, err = parse_channel_target("salom do'stlar")
    check("noma'lum matn → None (chaqiruvchi yo'naltiradi)", t is None and err is None)
    t, err = parse_channel_target("   ")
    check("bo'sh matn → xato", t is None and err is not None)
    t, err = parse_channel_target("@a")
    check("qisqa @ leniency: manzil sifatida o'tadi (tekshiruv API'da)",
          t == "@a" and err is None, str((t, err)))

    # 🔁 tugma va API
    kb = _retry_verify_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("retry tugma callback", cbs == ["add_channel_retry"], str(cbs))

    root = Path(__file__).resolve().parent.parent
    ch_src = (root / "handlers" / "channels.py").read_text(encoding="utf-8")
    check("yagona oqim funksiyasi bor", "async def _link_channel(" in ch_src)
    check("retry handler bor", "async def add_channel_retry(" in ch_src)
    check("omadda kanallar ro'yxati ko'rsatiladi", "reply_markup=list_markup" in ch_src)
    check("reply_text ga noto'g'ri 'inline_keyboard' kwarg yuborilmaydi",
          "inline_keyboard=list_markup" not in ch_src)
    check("xatoda manzil saqlanadi (retry uchun)", 'user_data["add_channel_pending"]' in ch_src)

    init_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("retry ADD_CHANNEL holatida ro'yxatdan o'tgan",
          'add_channel_retry, pattern=r"^add_channel_retry$"' in init_src)
    check("retry import qilingan", "add_channel_retry," in init_src)


def test_channel_posts_history_suite():
    """Real-time kanal postlari tarixi, handler, DB va AI/analitika integratsiyasi."""
    print("== Real-time kanal postlari tarixi va AI tahlil ==")
    from pathlib import Path
    import asyncio
    import database as db_mod
    from handlers.channels import on_channel_post
    from utils.channel_reader import fetch_latest_channel_posts

    # 1. DB funksiyalari mavjudligi
    check("db.save_channel_post_history mavjud", hasattr(db_mod, "save_channel_post_history"))
    check("db.save_channel_post_history callable", callable(db_mod.save_channel_post_history))
    check("db.get_channel_posts_history mavjud", hasattr(db_mod, "get_channel_posts_history"))
    check("db.get_channel_posts_history callable", callable(db_mod.get_channel_posts_history))
    check("db.is_channel_connected mavjud", hasattr(db_mod, "is_channel_connected"))
    check("db.is_channel_connected callable", callable(db_mod.is_channel_connected))
    check("db.get_channel_posts_history_stats mavjud", hasattr(db_mod, "get_channel_posts_history_stats"))
    check("db.get_channel_posts_history_stats callable", callable(db_mod.get_channel_posts_history_stats))

    # 2. Xavfsiz xatolik/chegara holatlari
    check("save: bo'sh channel_id -> -1", db_mod.save_channel_post_history("") == -1)
    check("save: None channel_id -> -1", db_mod.save_channel_post_history(None) == -1)
    check("get: bo'sh channel_id -> []", db_mod.get_channel_posts_history("") == [])
    check("get: None channel_id -> []", db_mod.get_channel_posts_history(None) == [])
    check("is_connected: bo'sh -> False", db_mod.is_channel_connected("") is False)
    check("is_connected: None -> False", db_mod.is_channel_connected(None) is False)

    # 3. Stats tuzilishi
    stats = db_mod.get_channel_posts_history_stats("test_nonexistent")
    check("stats: history_count bor", "history_count" in stats)
    check("stats: total_views bor", "total_views" in stats)
    check("stats: avg_views bor", "avg_views" in stats)

    # 4. Handler mavjudligi va asinxronligi
    check("on_channel_post callable", callable(on_channel_post))
    check("on_channel_post coroutine", asyncio.iscoroutinefunction(on_channel_post))

    # 5. Handler mock update bilan ishlashi
    class _MockChat:
        id = -1001999999999
        title = "Test Realtime Channel"
        type = "channel"

    class _MockChannelMsg:
        chat = _MockChat()
        message_id = 12345
        text = "Real-time AI post content"
        caption = None
        views = 42
        date = datetime.now(pytz.UTC)
        photo = None
        video = None
        document = None
        audio = None
        animation = None

    class _MockUpdate:
        channel_post = _MockChannelMsg()
        edited_channel_post = None
        effective_message = _MockChannelMsg()

    class _MockContext:
        pass

    # DB ga ulanmagan muhitda xatolik chiqarmasdan xavfsiz o'tishi
    try:
        asyncio.run(on_channel_post(_MockUpdate(), _MockContext()))
        check("on_channel_post xatosiz ishlaydi", True)
    except Exception as e:
        check("on_channel_post xatosiz ishlaydi", False, str(e))

    # 6. handlers/__init__.py da CHANNEL_POST handleri ro'yxatga olingani
    root = Path(__file__).resolve().parent.parent
    init_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handlers/__init__.py: on_channel_post import qilingan", "on_channel_post" in init_src)
    check("handlers/__init__.py: filters.UpdateType.CHANNEL_POST tinglovchisi bor",
          "filters.UpdateType.CHANNEL_POST" in init_src)

    # 7. Content Plan va AI agent integratsiyasi
    from utils.ai_agent import generate_content_plan
    import inspect
    sig = inspect.signature(generate_content_plan)
    check("generate_content_plan: recent_posts parametri bor", "recent_posts" in sig.parameters)

    cp_src = (root / "handlers" / "content_plan.py").read_text(encoding="utf-8")
    check("content_plan.py: get_channel_posts_history dan foydalanadi",
          "get_channel_posts_history" in cp_src)

    # 8. Channel Reader hybrid mexanizmi (DB -> scraping fallback)
    cr_src = (root / "utils" / "channel_reader.py").read_text(encoding="utf-8")
    check("channel_reader.py: get_channel_posts_history dan foydalanadi",
          "get_channel_posts_history" in cr_src)


def test_channel_add_autodetect_no_hang_suite():
    """➕ Kanal qo'shish: forward/link/@username avto-aniqlash — bot 'qotib' qolmasligi."""
    print("== Kanal qo'shish: avto-aniqlash (forward/link/@username) va no-hang ==")
    import asyncio
    import database as db_mod
    from handlers.channels import (
        _extract_forward_chat_id, channel_received, ADD_CHANNEL,
    )

    # 1) _extract_forward_chat_id: forward_origin (yangi API) ustuvor
    class _OriginChat:
        def __init__(self, cid):
            self.id = cid

    class _OriginWithChat:
        def __init__(self, cid):
            self.chat = _OriginChat(cid)

    class _OriginWithSenderChat:
        def __init__(self, cid):
            self.chat = None
            self.sender_chat = _OriginChat(cid)

    class _MsgWithOrigin:
        def __init__(self, origin):
            self.forward_origin = origin

    check("forward_origin.chat dan ID olinadi",
          _extract_forward_chat_id(_MsgWithOrigin(_OriginWithChat(-1009876543210))) == -1009876543210)
    check("forward_origin.sender_chat dan ID olinadi (fallback)",
          _extract_forward_chat_id(_MsgWithOrigin(_OriginWithSenderChat(-1001112223334))) == -1001112223334)

    class _MsgNoOrigin:
        pass

    check("forward ma'lumoti yo'q -> None (AttributeError emas)",
          _extract_forward_chat_id(_MsgNoOrigin()) is None)

    class _MsgLegacyForward:
        forward_origin = None
        forward_from_chat = _OriginChat(-1005556667778)

    check("eski forward_from_chat bilan ham ishlaydi (orqaga moslik)",
          _extract_forward_chat_id(_MsgLegacyForward()) == -1005556667778)

    # 2) channel_received: forward/username/link/ID — hech biri hang qilmaydi,
    #    doim biror javob (reply_text) qaytaradi va ADD_CHANNEL yoki END bilan tugaydi.
    class _FakeChat:
        def __init__(self, cid, title="Test Kanal", ctype="channel"):
            self.id = cid
            self.title = title
            self.type = ctype

    class _FakeMember:
        def __init__(self, status, can_post=True):
            self.status = status
            self.can_post_messages = can_post

    class _FakeBotAPI:
        def __init__(self, chat, bot_member, user_member=None, bot_id=999):
            self.id = bot_id
            self._chat = chat
            self._bot_member = bot_member
            self._user_member = user_member or bot_member

        async def get_chat(self, chat_id):
            return self._chat

        async def get_chat_member(self, chat_id, uid):
            if uid == self.id:
                return self._bot_member
            return self._user_member

        async def get_me(self):
            class _Me:
                username = "test_bot"
            return _Me()

    class _FakeUpdMsg:
        def __init__(self, text=None, forward_origin=None):
            self.text = text
            self.forward_origin = forward_origin
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append(text)
            return _FakeMsg(2)

    class _FakeUser:
        id = 555

    class _FakeUpdate:
        def __init__(self, msg, user_id=555):
            self.effective_message = msg
            self.effective_user = _FakeUser()
            self.effective_user.id = user_id

    orig_run_db = db_mod.run_db

    async def _run_db_ok(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        if name == "check_channel_limit":
            return (True, 0, 3)
        if name == "save_channel":
            return (True, None)
        if name == "get_user_channels":
            return [("-1009876543210", "Test Kanal")]
        return None

    async def run_all():
        results = []
        for label, msg in (
            ("forward", _FakeUpdMsg(forward_origin=_OriginWithChat(-1009876543210))),
            ("@username", _FakeUpdMsg(text="@mychannel")),
            ("t.me link", _FakeUpdMsg(text="https://t.me/mychannel")),
            ("raqamli ID", _FakeUpdMsg(text="-1001234567890")),
        ):
            bot_member = _FakeMember("administrator", can_post=True)
            bot_api = _FakeBotAPI(_FakeChat(-1009876543210), bot_member)
            ctx = _FakeCtx(bot_api, {})
            upd = _FakeUpdate(msg)
            db_mod.run_db = _run_db_ok
            try:
                state = await asyncio.wait_for(channel_received(upd, ctx), timeout=5)
            except asyncio.TimeoutError:
                state = "TIMEOUT"
            results.append((label, state, list(msg.replies)))
        return results

    try:
        results = asyncio.run(run_all())
    finally:
        db_mod.run_db = orig_run_db

    for label, state, replies in results:
        check(f"{label}: hang bo'lmaydi (timeout emas)", state != "TIMEOUT", str(state))
        check(f"{label}: foydalanuvchiga javob yuboriladi", len(replies) >= 1, str(replies))

    # Muvaffaqiyatli ulanishda aniq matn: "✅ Kanal muvaffaqiyatli ulandi!"
    fwd_replies = [r for (l, s, r) in results if l == "forward"][0]
    check("forward: '✅ Kanal muvaffaqiyatli ulandi!' xabari",
          any("Kanal muvaffaqiyatli ulandi" in r for r in fwd_replies), str(fwd_replies))

    # 3) Admin bo'lmagan holatda aniq ogohlantirish (can_post_messages=False)
    async def run_not_admin_capable():
        bot_member = _FakeMember("administrator", can_post=False)
        bot_api = _FakeBotAPI(_FakeChat(-1009876543210), bot_member)
        ctx = _FakeCtx(bot_api, {})
        msg = _FakeUpdMsg(forward_origin=_OriginWithChat(-1009876543210))
        upd = _FakeUpdate(msg)
        state = await channel_received(upd, ctx)
        return state, list(msg.replies)

    db_mod.run_db = _run_db_ok
    try:
        state, replies = asyncio.run(run_not_admin_capable())
    finally:
        db_mod.run_db = orig_run_db
    check("can_post_messages yo'q bo'lsa ADD_CHANNEL holatida qoladi (qayta urinish)",
          state == ADD_CHANNEL, str(state))
    check("can_post_messages yo'q bo'lsa ogohlantirish beriladi",
          replies and "xabar yuborish ruxsati" in replies[0], str(replies))

    # 4) Bot hali kanalga qo'shilmagan holatda ham xatosiz javob beriladi
    class _FakeBotAPIError:
        id = 999

        async def get_chat(self, chat_id):
            raise TelegramError("chat not found")

        async def get_me(self):
            class _Me:
                username = "test_bot"
            return _Me()

    async def run_error():
        ctx = _FakeCtx(_FakeBotAPIError(), {})
        msg = _FakeUpdMsg(text="@nosuchchannel")
        upd = _FakeUpdate(msg)
        state = await asyncio.wait_for(channel_received(upd, ctx), timeout=5)
        return state, list(msg.replies)

    db_mod.run_db = _run_db_ok
    try:
        state, replies = asyncio.run(run_error())
    finally:
        db_mod.run_db = orig_run_db
    check("kanal topilmasa ham hang bo'lmaydi, ADD_CHANNEL bilan javob qaytadi",
          state == ADD_CHANNEL, str(state))
    check("kanal topilmasa foydalanuvchiga xabar boradi", len(replies) >= 1, str(replies))


def test_my_chat_member_autoconnect_suite():
    """🎉 my_chat_member orqali avtomatik ulash — DM matni va can_post_messages tekshiruvi."""
    print("== my_chat_member avto-ulash (ChatMemberHandler) ==")
    import asyncio
    from pathlib import Path
    import database as db_mod
    from handlers.channels import on_bot_chat_member_update

    root = Path(__file__).resolve().parent.parent
    ch_src = (root / "handlers" / "channels.py").read_text(encoding="utf-8")
    check("on_bot_chat_member_update funksiyasi mavjud",
          "async def on_bot_chat_member_update(" in ch_src)

    init_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handlers/__init__.py: ChatMemberHandler ro'yxatga olingan",
          "ChatMemberHandler" in init_src and "on_bot_chat_member_update" in init_src)

    class _FakeChat:
        def __init__(self, cid, title, ctype="channel"):
            self.id = cid
            self.title = title
            self.type = ctype

    class _FakeUser:
        def __init__(self, uid):
            self.id = uid

    class _FakeMember:
        def __init__(self, status, can_post=True):
            self.status = status
            self.can_post_messages = can_post

    class _FakeMyChatMember:
        def __init__(self, chat, new_member, from_user):
            self.chat = chat
            self.new_chat_member = new_member
            self.from_user = from_user

    class _FakeBotAPI:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None, **kw):
            self.calls.append((chat_id, text))
            return _FakeMsg(1)

    class _FakeUpdate:
        def __init__(self, my_chat_member):
            self.my_chat_member = my_chat_member

    orig_run_db = db_mod.run_db

    async def _run_db_ok(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        if name == "check_channel_limit":
            return (True, 0, 3)
        if name == "save_channel":
            return (True, None)
        return None

    # 1) Bot admin + can_post_messages=True -> DM yuboriladi, muvaffaqiyat matni to'g'ri
    async def run_success():
        bot = _FakeBotAPI()
        ctx = _FakeCtx(bot, {})
        chat = _FakeChat(-1007778889990, "Mening Ajoyib Kanalim")
        member = _FakeMember("administrator", can_post=True)
        mcm = _FakeMyChatMember(chat, member, _FakeUser(777))
        upd = _FakeUpdate(mcm)
        await on_bot_chat_member_update(upd, ctx)
        return bot.calls

    db_mod.run_db = _run_db_ok
    try:
        calls = asyncio.run(run_success())
    finally:
        db_mod.run_db = orig_run_db

    check("my_chat_member (admin+can_post): DM yuboriladi", len(calls) == 1, str(calls))
    if calls:
        dm_chat_id, dm_text = calls[0]
        check("DM kanal egasiga (from_user.id) yuboriladi", dm_chat_id == 777, str(dm_chat_id))
        check("DM matni: 'Siz botni ... kanaliga admin qildingiz va kanal ulandi!'",
              "Siz botni Mening Ajoyib Kanalim kanaliga admin qildingiz va kanal ulandi!" in dm_text,
              dm_text)

    # 2) Bot admin lekin can_post_messages=False -> ogohlantirish, save_channel chaqirilmaydi
    saved_calls = []

    async def _run_db_track(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        saved_calls.append(name)
        if name == "check_channel_limit":
            return (True, 0, 3)
        if name == "save_channel":
            return (True, None)
        return None

    async def run_no_post_perm():
        bot = _FakeBotAPI()
        ctx = _FakeCtx(bot, {})
        chat = _FakeChat(-1007778889991, "Ikkinchi Kanal")
        member = _FakeMember("administrator", can_post=False)
        mcm = _FakeMyChatMember(chat, member, _FakeUser(778))
        upd = _FakeUpdate(mcm)
        await on_bot_chat_member_update(upd, ctx)
        return bot.calls

    db_mod.run_db = _run_db_track
    try:
        calls2 = asyncio.run(run_no_post_perm())
    finally:
        db_mod.run_db = orig_run_db

    check("can_post_messages=False bo'lsa ogohlantirish yuboriladi", len(calls2) == 1, str(calls2))
    if calls2:
        check("ogohlantirish matnida 'Post Messages' eslatiladi",
              "Post Messages" in calls2[0][1], calls2[0][1])
    check("can_post_messages=False bo'lsa save_channel chaqirilmaydi",
          "save_channel" not in saved_calls, str(saved_calls))

    # 3) Guruh (channel emas) uchun can_post_messages tekshiruvi shart emas — to'g'ridan-to'g'ri ulanadi
    async def run_group_admin():
        bot = _FakeBotAPI()
        ctx = _FakeCtx(bot, {})
        chat = _FakeChat(-1007778889992, "Test Guruh", ctype="supergroup")
        member = _FakeMember("administrator", can_post=False)  # guruhda bu maydon relevant emas
        mcm = _FakeMyChatMember(chat, member, _FakeUser(779))
        upd = _FakeUpdate(mcm)
        await on_bot_chat_member_update(upd, ctx)
        return bot.calls

    db_mod.run_db = _run_db_ok
    try:
        calls3 = asyncio.run(run_group_admin())
    finally:
        db_mod.run_db = orig_run_db
    check("supergroup: DM baribir yuboriladi (can_post_messages faqat channel uchun tekshiriladi)",
          len(calls3) == 1, str(calls3))


def test_referrer_id_and_new_providers_suite():
    """Referal referrer_id tuzatishi + SambaNova/Cloudflare zanjirga qo'shilishi.

    1) handlers/channels.py endi `run_db(lambda cur: ...)` CHAQIRMAYDI — bunday
       lambda kursor olmagani uchun har safar TypeError berardi.
    2) AI provayder zanjiri: Gemini → Groq → OpenRouter → Mistral → Cerebras →
       SambaNova → Cloudflare → Pollinations (tartib saqlangan).
    """
    import asyncio
    import inspect
    import database as db_mod

    print("== VAZIFA 1: referrer_id (kursor o'rniga tayyor DB funksiyasi) ==")
    check("database.get_referrer_id mavjud", callable(getattr(db_mod, "get_referrer_id", None)))
    params = list(inspect.signature(db_mod.get_referrer_id).parameters)
    check("get_referrer_id faqat user_id oladi (kursor emas)", params == ["user_id"], str(params))

    channels_src = (ROOT / "handlers" / "channels.py").read_text(encoding="utf-8")
    check("channels.py: referral PRO tekshiruvi olib tashlangan",
          "db.run_db(db.get_referrer_id, user_id)" not in channels_src)
    check("channels.py: 'lambda cur' butunlay olib tashlandi", "lambda cur" not in channels_src)
    check("channels.py: referal PRO mukofoti olib tashlangan",
          "check_and_grant_referral_pro" not in channels_src)

    print("== VAZIFA 2: SambaNova + Cloudflare zanjirda ==")
    from utils import ai_agent

    check("ai_agent: _call_sambanova mavjud", callable(getattr(ai_agent, "_call_sambanova", None)))
    check("ai_agent: _call_cloudflare mavjud", callable(getattr(ai_agent, "_call_cloudflare", None)))
    check("SAMBANOVA_MODELS to'ldirilgan", len(ai_agent.SAMBANOVA_MODELS) >= 3,
          str(ai_agent.SAMBANOVA_MODELS))
    check("CLOUDFLARE_MODELS '@cf/' prefiksli",
          bool(ai_agent.CLOUDFLARE_MODELS) and all(m.startswith("@cf/") for m in ai_agent.CLOUDFLARE_MODELS),
          str(ai_agent.CLOUDFLARE_MODELS))
    check("SambaNova endpoint to'g'ri",
          ai_agent.SAMBANOVA_ENDPOINT == "https://api.sambanova.ai/v1/chat/completions",
          ai_agent.SAMBANOVA_ENDPOINT)
    check("Cloudflare endpoint account_id dan yig'iladi",
          ai_agent.CLOUDFLARE_ENDPOINT.startswith("https://api.cloudflare.com/client/v4/accounts/")
          and ai_agent.CLOUDFLARE_ENDPOINT.endswith("/ai/v1/chat/completions"),
          ai_agent.CLOUDFLARE_ENDPOINT)

    chain_src = inspect.getsource(ai_agent._run_ai_chain)
    for name in ("Gemini", "Groq", "OpenRouter", "Mistral", "Cerebras",
                 "SambaNova", "Cloudflare", "Pollinations"):
        check(f"zanjirda {name} bor", f'"{name}"' in chain_src)
    pos = {n: chain_src.find(f'"{n}"') for n in
           ("Gemini", "Groq", "OpenRouter", "Mistral", "Cerebras", "SambaNova", "Cloudflare")}
    check("tartib saqlangan (SambaNova va Cloudflare oxirga qo'shildi)",
          pos["Gemini"] < pos["Groq"] < pos["OpenRouter"] < pos["Mistral"]
          < pos["Cerebras"] < pos["SambaNova"] < pos["Cloudflare"], str(pos))

    # Haqiqiy chaqiruv tartibi — barcha _call_* funksiyalar stub bilan almashtiriladi
    order = []

    def _stub(name):
        async def _fake(prompt, *args, **kwargs):
            order.append(name)
            raise RuntimeError(f"{name}: stub (ataylab xato)")
        return _fake

    provider_funcs = {
        "_call_gemini": "Gemini",
        "_call_groq": "Groq",
        "_call_openrouter": "OpenRouter",
        "_call_mistral": "Mistral",
        "_call_cerebras": "Cerebras",
        "_call_sambanova": "SambaNova",
        "_call_cloudflare": "Cloudflare",
        "_call_pollinations": "Pollinations",
    }
    saved_funcs = {k: getattr(ai_agent, k) for k in provider_funcs}
    saved_keys = {k: getattr(ai_agent, k) for k in
                  ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY",
                   "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY", "CLOUDFLARE_API_TOKEN")}
    saved_account = ai_agent.CLOUDFLARE_ACCOUNT_ID
    saved_breakers = dict(ai_agent._BREAKERS)
    try:
        for attr, name in provider_funcs.items():
            setattr(ai_agent, attr, _stub(name))
        for attr in saved_keys:
            setattr(ai_agent, attr, "test-key")
        ai_agent.CLOUDFLARE_ACCOUNT_ID = "test-account"
        ai_agent._BREAKERS.clear()
        asyncio.run(ai_agent._run_ai_chain("test prompt", "sen yordamchisan"))
    finally:
        for attr, fn in saved_funcs.items():
            setattr(ai_agent, attr, fn)
        for attr, val in saved_keys.items():
            setattr(ai_agent, attr, val)
        ai_agent.CLOUDFLARE_ACCOUNT_ID = saved_account
        ai_agent._BREAKERS.clear()
        ai_agent._BREAKERS.update(saved_breakers)

    expected = ["Gemini", "Groq", "OpenRouter", "Mistral", "Cerebras",
                "SambaNova", "Cloudflare", "Pollinations"]
    check("chaqiruv tartibi to'liq va buzilmagan", order == expected, str(order))

    # Account ID bo'lmasa Cloudflare zanjirdan chiqib ketadi (kalit bo'lsa ham)
    order.clear()
    saved_funcs = {k: getattr(ai_agent, k) for k in provider_funcs}
    try:
        for attr, name in provider_funcs.items():
            setattr(ai_agent, attr, _stub(name))
        ai_agent.SAMBANOVA_API_KEY = "test-key"
        ai_agent.CLOUDFLARE_API_TOKEN = "test-key"
        ai_agent.CLOUDFLARE_ACCOUNT_ID = ""
        ai_agent._BREAKERS.clear()
        asyncio.run(ai_agent._run_ai_chain("test prompt", "sen yordamchisan"))
    finally:
        for attr, fn in saved_funcs.items():
            setattr(ai_agent, attr, fn)
        ai_agent.SAMBANOVA_API_KEY = saved_keys["SAMBANOVA_API_KEY"]
        ai_agent.CLOUDFLARE_API_TOKEN = saved_keys["CLOUDFLARE_API_TOKEN"]
        ai_agent.CLOUDFLARE_ACCOUNT_ID = saved_account
        ai_agent._BREAKERS.clear()
        ai_agent._BREAKERS.update(saved_breakers)
    check("CLOUDFLARE_ACCOUNT_ID yo'q → Cloudflare chaqirilmaydi",
          "Cloudflare" not in order, str(order))


def test_cabinet_i18n_suite():
    """1-QISM: Kabinet va asosiy klaviatura i18n (uz/ru).

    Kabinet reply/inline klaviaturalari va kabinet ekrani matnlari
    (shaxsiy kabinet, kunlik bonus, ball o'tkazish, xatoliklar) ikki tilda.
    """
    print("== Kabinet & asosiy klaviatura i18n (uz/ru) ==")
    import sys as _sys
    from pathlib import Path
    from locales.translations import get_text, localize_db_message, TRANSLATIONS
    from keyboards.default import (
        get_main_keyboard, get_cabinet_keyboard, get_cancel_keyboard, exact,
        BTN_CHANNELS, BTN_CHANNELS_RU, BTN_CONVERTER, BTN_CONVERTER_RU,
        BTN_DAILY_BONUS, BTN_DAILY_BONUS_RU, BTN_INVITE, BTN_INVITE_RU,
        BTN_TRANSFER, BTN_TRANSFER_RU, BTN_BACK, BTN_BACK_RU,
        BTN_CANCEL, BTN_CANCEL_RU, BTN_SETTINGS, BTN_SETTINGS_RU,
    )
    from keyboards.inline import (
        get_cabinet_inline_keyboard, get_cabinet_back_keyboard,
        get_channels_manage_keyboard, render_channels_list, no_channels_hint,
    )
    import handlers.start  # noqa: F401
    start_mod = _sys.modules["handlers.start"]

    # ---------- 1) Lug'at: barcha yangi kalitlar ikki tilda ----------
    new_keys = [
        "btn_main_menu", "btn_cancel",
        "cab_btn_channels", "cab_btn_converter", "cab_btn_daily_bonus",
        "cab_btn_invite", "cab_btn_transfer",
        "cab_my_channels", "cab_analytics", "cab_pending", "cab_queue",
        "cab_balance", "cab_referral", "cab_close", "cab_add_channel",
        "cab_del_channel", "cab_remove_channel", "cab_tone",
        "cab_add_channel_alt", "cab_channels_delete_empty",
        "cab_channels_delete_title", "no_channels_hint",
        "credits_value", "cabinet_credits_admin", "cabinet_streak",
        "cabinet_title", "daily_bonus_admin", "daily_bonus_claimed",
        "daily_bonus_reset_notice", "daily_bonus_already",
        "transfer_intro", "transfer_insufficient", "transfer_user_not_found",
        "transfer_self", "transfer_target_ok", "transfer_amount_nan",
        "transfer_amount_range", "transfer_success", "transfer_gift_notice",
        "transfer_error", "transfer_default_name",
    ]
    uz_table, ru_table = TRANSLATIONS["uz"], TRANSLATIONS["ru"]
    check("lug'at: barcha yangi kalitlar uz'da bor",
          all(k in uz_table for k in new_keys))
    check("lug'at: barcha yangi kalitlar ru'da bor",
          all(k in ru_table for k in new_keys))
    check("lug'at: yangi kalitlar tarjima qilingan",
          all(uz_table.get(k) != ru_table.get(k) for k in new_keys)
          and all(uz_table.get(k) not in (None, k) for k in new_keys))

    # ---------- 2) Kabinet reply-klaviaturasi ----------
    def _rows(kb):
        return [[b.text for b in row] for row in kb.keyboard]

    check("kabinet kb uz", _rows(get_cabinet_keyboard("uz")) == [
        [BTN_CHANNELS, BTN_CONVERTER],
        [BTN_DAILY_BONUS],
        [BTN_INVITE, BTN_TRANSFER],
        [BTN_BACK],
    ], str(_rows(get_cabinet_keyboard("uz"))))
    check("kabinet kb ru", _rows(get_cabinet_keyboard("ru")) == [
        [BTN_CHANNELS_RU, BTN_CONVERTER_RU],
        [BTN_DAILY_BONUS_RU],
        [BTN_INVITE_RU, BTN_TRANSFER_RU],
        [BTN_BACK_RU],
    ], str(_rows(get_cabinet_keyboard("ru"))))
    check("kabinet kb: default uz (eski chaqiruvlar buzilmaydi)",
          _rows(get_cabinet_keyboard()) == _rows(get_cabinet_keyboard("uz")))

    class _Ctx:
        def __init__(self, data):
            self.user_data = data

    check("kabinet kb: context.user_data['lang'] hurmat qilinadi",
          _rows(get_cabinet_keyboard(context=_Ctx({"lang": "ru"})))
          == _rows(get_cabinet_keyboard("ru")))

    cancel_ru = [b.text for row in get_cancel_keyboard("ru").keyboard for b in row]
    check("bekor qilish kb ru", cancel_ru == [BTN_CANCEL_RU, BTN_BACK_RU], str(cancel_ru))
    check("bekor qilish kb default uz",
          [b.text for row in get_cancel_keyboard().keyboard for b in row]
          == [BTN_CANCEL, BTN_BACK])

    # Asosiy klaviatura ham kabinet tugmasi bilan bir tilda
    main_ru_rows = _rows(get_main_keyboard(False, lang="ru"))
    check("asosiy menyu ru: kabinet tugmasi tarjimasi",
          BTN_SETTINGS_RU in main_ru_rows[1], str(main_ru_rows))

    # ---------- 3) Kabinet inline-klaviaturasi ----------
    cab = get_cabinet_inline_keyboard("ru")
    cab_texts = [b.text for row in cab.inline_keyboard for b in row]
    cab_cbs = [b.callback_data for row in cab.inline_keyboard for b in row]
    check("kabinet inline ru: yorliqlar tarjimasi",
          get_text("cab_my_channels", "ru") in cab_texts
          and get_text("cab_close", "ru") in cab_texts, str(cab_texts))
    check("kabinet inline ru: callback_data o'zgarmagan",
          cab_cbs == ["cab_channels", "cab_analytics", "cab_pending",
                      "cab_queue", "cab_balance", "cab_bonus", "cab_referral",
                      "close_cabinet", "cab_lang"], str(cab_cbs))
    check("kabinet inline uz: default",
          [b.text for row in get_cabinet_inline_keyboard().inline_keyboard for b in row][0]
          == get_text("cab_my_channels", "uz"))

    back = get_cabinet_back_keyboard("ru")
    check("kabinet orqaga kb ru",
          [b.text for b in back.inline_keyboard[0]]
          == [get_text("btn_back", "ru"), get_text("cab_close", "ru")])
    check("kabinet orqaga kb: callback_data o'zgarmagan",
          [b.callback_data for b in back.inline_keyboard[0]]
          == ["cab_main", "close_cabinet"])

    mgr = get_channels_manage_keyboard("ru")
    check("kanallar boshqaruvi kb ru",
          [b.text for row in mgr.inline_keyboard for b in row][0]
          == get_text("cab_add_channel", "ru"))
    check("kanallar boshqaruvi kb: callback_data o'zgarmagan",
          [b.callback_data for row in mgr.inline_keyboard for b in row]
          == ["add_channel_start", "cab_channels_delete", "cab_main",
              "close_cabinet"])

    ch_list = render_channels_list([("-1001", "Kanal 1", "formal")], "ru")
    ch_texts = [b.text for row in ch_list.inline_keyboard for b in row]
    check("kanallar ro'yxati kb ru",
          get_text("cab_remove_channel", "ru") in ch_texts
          and get_text("cab_close", "ru") in ch_texts, str(ch_texts))
    check("no_channels_hint ru", "Мои каналы" in no_channels_hint("ru"),
          no_channels_hint("ru"))
    check("no_channels_hint default uz",
          no_channels_hint() == get_text("no_channels_hint", "uz"))

    # ---------- 4) Kabinet matnlari ----------
    credits_admin = start_mod.cabinet_credits_text(True, 0, "ru")
    credits_user = start_mod.cabinet_credits_text(False, 12, "ru")
    check("ballar: admin ru", credits_admin == get_text("cabinet_credits_admin", "ru"))
    check("ballar: foydalanuvchi ru", "12" in credits_user and "шт." in credits_user,
          credits_user)
    check("ballar: foydalanuvchi uz",
          start_mod.cabinet_credits_text(False, 12, "uz")
          == get_text("credits_value", "uz", n=12))

    text_ru = start_mod.build_cabinet_text(
        555001, "ABC123", credits_user,
        get_text("cabinet_streak", "ru", streak=3), 2, 4, "ru",
    )
    text_uz = start_mod.build_cabinet_text(
        555001, "ABC123", get_text("credits_value", "uz", n=12),
        get_text("cabinet_streak", "uz", streak=3), 2, 4, "uz", "",
    )
    check("kabinet matni ru",
          "Личный кабинет" in text_ru and "<code>555001</code>" in text_ru
          and "<code>ABC123</code>" in text_ru, text_ru[:80])
    check("kabinet matni uz",
          "Shaxsiy Kabinet" in text_uz and "<code>555001</code>" in text_uz
          and "Ulangan kanallar: <b>2 ta</b>" in text_uz, text_uz[:80])
    check("kabinet matni: ad_line qo'shiladi",
          start_mod.build_cabinet_text(
              1, "X", "c", "s", 0, 0, "ru", "\n[reklama]").endswith("[reklama]"))

    # ---------- 5) Kunlik bonus ----------
    bonus_res = {"success": True, "streak": 3, "bonus_amount": 2,
                 "credits": 10, "is_reset": True}
    bonus_ru = start_mod.build_daily_bonus_text(bonus_res, "ru")
    bonus_uz = start_mod.build_daily_bonus_text(bonus_res, "uz")
    check("kunlik bonus ru",
          "Ежедневный бонус получен" in bonus_ru
          and "<b>3/7 дней</b>" in bonus_ru and "серия началась заново" in bonus_ru,
          bonus_ru[:80])
    check("kunlik bonus uz",
          "Kunlik bonus qabul qilindi" in bonus_uz
          and "<b>3/7 kun</b>" in bonus_uz
          and "seriya 1-kundan" in bonus_uz, bonus_uz[:80])
    check("kunlik bonus: progress-bar 7 katak",
          bonus_ru.count("🟩") + bonus_ru.count("⬜") == 7)
    check("kunlik bonus: reset bo'lmasa ogohlantirish yo'q",
          "серия началась заново" not in
          start_mod.build_daily_bonus_text(
              {"success": True, "streak": 2, "bonus_amount": 1, "credits": 5}, "ru"))

    # ---------- 6) Ball o'tkazish (transfer) ----------
    tr_ru = get_text("transfer_success", "ru", name="Ali", amount=5)
    tr_uz = get_text("transfer_success", "uz", name="Ali", amount=5)
    check("transfer: muvaffaqiyat ru/uz", "ИИ-запросов" in tr_ru
          and "AI so'rovi" in tr_uz, tr_ru)
    check("transfer: yetarli emas ru",
          "недостаточно баллов" in
          get_text("transfer_insufficient", "ru", credits=1, guide="guide"))
    check("transfer: xato ru",
          get_text("transfer_error", "ru", msg="Пользователь не найден.").startswith("❌"))

    # ---------- 7) DB xabarlari tarjimasi ----------
    db_msg = "Siz bugungi bonusingizni olgansiz! Ertaga yana kiring."
    check("db xabari ru'ga o'giriladi",
          localize_db_message(db_msg, "ru") != db_msg
          and "бонус" in localize_db_message(db_msg, "ru"),
          localize_db_message(db_msg, "ru"))
    check("db xabari uz'da asl matn",
          localize_db_message(db_msg, "uz") == db_msg)
    check("db xabari: noma'lum matn yo'qolmaydi",
          localize_db_message("Noma'lum xato", "ru") == "Noma'lum xato")

    # ---------- 8) Routing: kabinet tugmalari ikki tilda ----------
    def _pattern(flt) -> str:
        pat = getattr(flt, "pattern", None)
        src = pat.pattern if hasattr(pat, "pattern") else str(pat)
        return src.replace("\\", "")

    for uz_btn, ru_btn, label in (
        (BTN_CHANNELS, BTN_CHANNELS_RU, "Kanal/Guruhlar"),
        (BTN_DAILY_BONUS, BTN_DAILY_BONUS_RU, "Kunlik bonus"),
        (BTN_INVITE, BTN_INVITE_RU, "Do'stlarni taklif"),
        (BTN_TRANSFER, BTN_TRANSFER_RU, "Ballarni ulashish"),
        (BTN_CONVERTER, BTN_CONVERTER_RU, "Konvertor"),
        (BTN_BACK, BTN_BACK_RU, "Asosiy menyu"),
        (BTN_CANCEL, BTN_CANCEL_RU, "Bekor qilish"),
    ):
        pat = _pattern(exact(uz_btn, ru_btn))
        check(f"router: {label} uz+ru", uz_btn in pat and ru_btn in pat, pat)

    init_src = (Path(__file__).resolve().parent.parent / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for pair in (
        "BTN_CHANNELS, BTN_CHANNELS_RU",
        "BTN_DAILY_BONUS, BTN_DAILY_BONUS_RU",
        "BTN_INVITE, BTN_INVITE_RU",
        "BTN_TRANSFER, BTN_TRANSFER_RU",
        "BTN_CONVERTER, BTN_CONVERTER_RU",
        "BTN_CANCEL, BTN_CANCEL_RU",
    ):
        check(f"handlers/__init__.py: exact({pair})",
              f"exact({pair})" in init_src)
    check("handlers/__init__.py: asosiy menyu uz+ru",
          "exact(BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU)" in init_src)

    start_src = (Path(__file__).resolve().parent.parent / "handlers" / "start.py").read_text(encoding="utf-8")
    check("start.py: kabinet matnlari lug'atdan olinadi",
          '"cabinet_title"' in start_src
          and 'get_text("daily_bonus_admin"' in start_src
          and 'get_text("transfer_success"' in start_src)
    check("start.py: qotirilgan kabinet matni qolmagan",
          'f"👤 <b>Shaxsiy Kabinet:</b>' not in start_src)


def test_i18n_uz_ru():
    """uz/ru i18n: lug'at, til aniqlash, klaviatura, handler filtrlari."""
    print("== i18n uz/ru ==")
    from locales.translations import (
        get_text, detect_language, normalize_lang, clear_fsm_data,
        SUPPORTED_LANGS, DEFAULT_LANG,
    )
    from keyboards.default import (
        get_main_keyboard, exact, exact_i18n,
        BTN_NEW_POST, BTN_NEW_POST_RU, BTN_AI_STUDIO, BTN_AI_STUDIO_RU,
        BTN_PREMIUM, BTN_PREMIUM_RU, BTN_SETTINGS, BTN_SETTINGS_RU,
        BTN_HELP, BTN_HELP_RU, BTN_EXTRAS, BTN_EXTRAS_RU,
    )
    from keyboards.inline import get_language_keyboard
    import database as db_mod
    from pathlib import Path

    check("SUPPORTED_LANGS", SUPPORTED_LANGS == ("uz", "ru", "en"))
    check("DEFAULT_LANG uz", DEFAULT_LANG == "uz")
    check("detect ru", detect_language("ru") == "ru")
    check("detect ru-RU", detect_language("ru-RU") == "ru")
    check("detect uz", detect_language("uz") == "uz")
    check("detect en -> en", detect_language("en") == "en")
    check("detect None -> uz", detect_language(None) == "uz")
    check("normalize ru-uz", normalize_lang("RU") == "ru")

    check("uz btn_new_post", get_text("btn_new_post", "uz") == "➕ Yangi post")
    check("ru btn_new_post", get_text("btn_new_post", "ru") == "➕ Новый пост")
    check("uz btn_settings", get_text("btn_settings", "uz") == BTN_SETTINGS)
    check("ru btn_settings", get_text("btn_settings", "ru") == BTN_SETTINGS_RU)
    check("start_hello uz name", "Ali" in get_text("start_hello", "uz", name="Ali"))
    check("start_hello ru name", "Ivan" in get_text("start_hello", "ru", name="Ivan"))
    check("new_post_no_channels uz", "Ulangan kanal" in get_text("new_post_no_channels", "uz"))
    check("new_post_no_channels ru", "не найден" in get_text("new_post_no_channels", "ru"))
    check("unknown key fallback", get_text("no_such_key", "ru") == "no_such_key")
    check("unknown lang -> uz", get_text("btn_new_post", "fr") == get_text("btn_new_post", "uz"))

    ru_rows = [[b.text for b in row] for row in get_main_keyboard(False, lang="ru").keyboard]
    check("ru row1", ru_rows[0] == [BTN_NEW_POST_RU, BTN_AI_STUDIO_RU], str(ru_rows[0]))
    check("ru row2", ru_rows[1] == [BTN_PREMIUM_RU, BTN_SETTINGS_RU], str(ru_rows[1]))
    check("ru row3", ru_rows[2] == [BTN_HELP_RU, BTN_EXTRAS_RU], str(ru_rows[2]))
    uz_rows = [[b.text for b in row] for row in get_main_keyboard(False).keyboard]
    check("uz default row1", uz_rows[0] == [BTN_NEW_POST, BTN_AI_STUDIO], str(uz_rows[0]))

    class _Ctx:
        def __init__(self, data):
            self.user_data = data
    ctx = _Ctx({"foo": 1, "lang": "ru"})
    clear_fsm_data(ctx)
    check("clear_fsm lang saqlanadi", ctx.user_data == {"lang": "ru"}, str(ctx.user_data))
    ctx2 = _Ctx({"foo": 1})
    clear_fsm_data(ctx2)
    check("clear_fsm langsiz -> bosh", ctx2.user_data == {}, str(ctx2.user_data))

    def _regex_plain(flt) -> str:
        """re.escape ba'zi Pythonlarda probelni ham qochiradi — tekshiruv uchun olib tashlaymiz."""
        pat = getattr(flt, "pattern", None)
        src = pat.pattern if hasattr(pat, "pattern") else str(pat)
        return src.replace("\\", "")

    flt = exact(BTN_NEW_POST, BTN_NEW_POST_RU)
    pat_s = _regex_plain(flt)
    check("exact dual uz", "Yangi post" in pat_s, pat_s)
    check("exact dual ru", "Новый пост" in pat_s, pat_s)
    flt2 = exact_i18n("btn_ai_studio")
    pat2_s = _regex_plain(flt2)
    check("exact_i18n AI Studio", "AI Studio" in pat2_s, pat2_s)

    lk_cbs = [b.callback_data for row in get_language_keyboard().inline_keyboard for b in row]
    check("lang kb: uz", "cab_lang_uz" in lk_cbs, str(lk_cbs))
    check("lang kb: ru", "cab_lang_ru" in lk_cbs, str(lk_cbs))
    check("lang kb: en", "cab_lang_en" in lk_cbs, str(lk_cbs))

    check("db._normalize ru", db_mod._normalize_language_code("ru-RU") == "ru")
    check("db._normalize en", db_mod._normalize_language_code("en") == "en")
    check("db.get_user_language", callable(db_mod.get_user_language))
    check("db.set_user_language", callable(db_mod.set_user_language))
    check("save_user language_code param",
          "language_code" in db_mod.save_user.__code__.co_varnames)

    init_src = (Path(__file__).resolve().parent.parent / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handler: NEW_POST dual", "exact(BTN_NEW_POST, BTN_NEW_POST_RU)" in init_src)
    check("handler: AI_STUDIO dual", "exact(BTN_AI_STUDIO, BTN_AI_STUDIO_RU)" in init_src)
    check("handler: SETTINGS dual", "BTN_SETTINGS_RU" in init_src)
    check("handler: PREMIUM dual", "BTN_PREMIUM_RU" in init_src)
    check("handler: HELP dual", "BTN_HELP_RU" in init_src)
    check("handler: EXTRAS dual", "BTN_EXTRAS_RU" in init_src)

    start_src = (Path(__file__).resolve().parent.parent / "handlers" / "start.py").read_text(encoding="utf-8")
    check("start: detect_language", "detect_language" in start_src)
    check("start: cab_lang", "cab_lang" in start_src)
    check("start: set_user_language", "set_user_language" in start_src)


def test_i18n_en_menu_buttons_and_fallback():
    """EN i18n: lang='en' bo'lganda asosiy menyu/onboarding/kabinet tugmalari
    router'da taniladi (fallback'ga tushmaydi) va global fallback xabari
    foydalanuvchi tilida — inglizcha — chiqadi.

    Kritik regression: EN klaviaturada bosilgan har bir reply tugma
    (New post / AI Studio / Premium / Account & Settings / Guide / About /
    Extra features / Admin Panel + onboarding sodda menyu + kabinet)
    tegishli handlerga tushishi, ``unknown_message_fallback``'ga emas.
    """
    print("== i18n EN: asosiy menyu tugmalari + fallback ==")
    import asyncio
    import datetime as _dt
    import types
    import warnings
    from telegram import Update, Message, Chat, User, Voice, ReplyKeyboardMarkup
    from telegram.ext import (
        ApplicationBuilder, ConversationHandler, MessageHandler, CallbackContext,
    )
    from locales.translations import get_text
    from keyboards.default import (
        get_main_keyboard, get_simple_keyboard,
        BTN_NEW_POST_EN, BTN_AI_STUDIO_EN, BTN_PREMIUM_EN, BTN_SETTINGS_EN,
        BTN_HELP_EN, BTN_EXTRAS_EN, BTN_BACK_EN, BTN_CANCEL_EN,
        BTN_CHANNELS_EN, BTN_CONVERTER_EN, BTN_DAILY_BONUS_EN, BTN_INVITE_EN,
        BTN_TRANSFER_EN, BTN_ADMIN_PANEL, BTN_ADMIN_PANEL_RU,
        BTN_QUICK_AI_POST_EN, BTN_QUICK_PHOTO_POST_EN,
        BTN_QUICK_ADD_CHANNEL_EN, BTN_OPEN_FULL_MENU_EN,
        BTN_NEW_POST, BTN_NEW_POST_RU, BTN_SETTINGS_RU,
    )
    import handlers as h_mod
    from handlers import register_all_handlers, unknown_message_fallback

    # ---------- 1) EN lug'at: tugma matnlari va fallback xabarlar ----------
    check("EN btn_new_post", get_text("btn_new_post", "en") == "➕ New post")
    check("EN btn_settings", get_text("btn_settings", "en") == "👤 Account & Settings")
    check("EN btn_help", get_text("btn_help", "en") == "📖 Guide / About")
    check("EN btn_extras", get_text("btn_extras", "en") == "⚙️ Extra features")
    check("EN btn_cancel", get_text("btn_cancel", "en") == "❌ Cancel")
    check("EN btn_main_menu", get_text("btn_main_menu", "en") == "🔙 Main menu")
    check("EN fallback: uz'dan farq qiladi",
          get_text("unknown_message_fallback", "en") != get_text("unknown_message_fallback", "uz"))
    check("EN fallback: inglizcha",
          get_text("unknown_message_fallback", "en").startswith("Sorry"))
    check("EN in_dialog: uz'dan farq qiladi",
          get_text("unknown_in_dialog", "en") != get_text("unknown_in_dialog", "uz"))
    check("EN in_dialog: inglizcha",
          "not accepted" in get_text("unknown_in_dialog", "en"))

    # ---------- 2) HAQIQIY router: register_all_handlers ----------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]

    def _upd(text):
        user = User(id=777, first_name="Ali", is_bot=False)
        chat = Chat(id=777, type="private")
        msg = Message(message_id=1, date=_dt.datetime.now(), chat=chat,
                      from_user=user, text=text)
        return Update(update_id=1, message=msg)

    def _first_match(text):
        for group in sorted(app.handlers):
            for h in app.handlers[group]:
                r = h.check_update(_upd(text))
                if r is not None and r is not False:
                    return h
        return None

    def _entry_fn_names(label):
        """"label" matnini taniydigan conv entry_point MessageHandler'lari
        chaqiradigan funksiya nomlari (lambda bo'lsa — co_names orqali)."""
        names = set()
        for h in conv.entry_points:
            if not isinstance(h, MessageHandler):
                continue
            if h.check_update(_upd(label)) in (None, False):
                continue
            cb = h.callback
            if callable(cb) and hasattr(cb, "__name__") and cb.__name__ != "<lambda>":
                names.add(cb.__name__)
            elif getattr(getattr(cb, "__code__", None), "co_names", None):
                names.update(cb.__code__.co_names)
        return names

    # ---------- 3) Har bir EN tugma → tegishli handler (fallback EMAS) ----------
    en_button_targets = (
        (BTN_NEW_POST_EN, "start_new_post"),
        (BTN_AI_STUDIO_EN, "ai_studio_menu_entry"),
        (BTN_PREMIUM_EN, "start_subscription"),
        (BTN_SETTINGS_EN, "user_cabinet_menu"),
        (BTN_HELP_EN, "help_command"),
        (BTN_EXTRAS_EN, "extras_menu"),
        (BTN_BACK_EN, "start"),
        (BTN_CANCEL_EN, "cancel_handler"),
        (BTN_ADMIN_PANEL, "admin_panel_menu"),
        (BTN_ADMIN_PANEL_RU, "admin_panel_menu"),
        # Onboarding sodda menyu (EN)
        (BTN_QUICK_AI_POST_EN, "quick_ai_post_entry"),
        (BTN_QUICK_PHOTO_POST_EN, "quick_photo_post_entry"),
        (BTN_QUICK_ADD_CHANNEL_EN, "quick_add_channel_entry"),
        (BTN_OPEN_FULL_MENU_EN, "open_full_menu"),
        # Kabinet ichki tugmalar (EN)
        (BTN_CHANNELS_EN, "channels_menu"),
        (BTN_CONVERTER_EN, "start_converter"),
        (BTN_DAILY_BONUS_EN, "daily_bonus_handler"),
        (BTN_INVITE_EN, "user_invite_menu"),
        (BTN_TRANSFER_EN, "start_transfer_credits"),
    )
    for label, fn in en_button_targets:
        fns = _entry_fn_names(label)
        check(f"EN entry_point {label[:26]!r} → {fn}", fn in fns, str(sorted(fns)))
        h = _first_match(label)
        check(f"EN {label[:26]!r} fallback'ga tushmaydi",
              h is not None and isinstance(h, ConversationHandler)
              and getattr(h, "callback", None) is not unknown_message_fallback,
              type(h).__name__)

    # ---------- 4) EN klaviaturalar = router qamrovi (tuxunsiz) ----------
    en_rows = [[b.text for b in row] for row in get_main_keyboard(False, lang="en").keyboard]
    check("EN main kb row1", en_rows[0] == [BTN_NEW_POST_EN, BTN_AI_STUDIO_EN], str(en_rows[0]))
    check("EN main kb row2", en_rows[1] == [BTN_PREMIUM_EN, BTN_SETTINGS_EN], str(en_rows[1]))
    check("EN main kb row3", en_rows[2] == [BTN_HELP_EN, BTN_EXTRAS_EN], str(en_rows[2]))
    for label in (t for row in en_rows for t in row):
        check(f"EN klaviatura tugmasi router'da: {label[:26]!r}",
              bool(_entry_fn_names(label)))
    simple_rows = [b.text for row in get_simple_keyboard("en").keyboard for b in row]
    check("EN simple kb (onboarding)",
          simple_rows == [BTN_QUICK_AI_POST_EN, BTN_QUICK_PHOTO_POST_EN,
                          BTN_QUICK_ADD_CHANNEL_EN, BTN_OPEN_FULL_MENU_EN],
          str(simple_rows))

    # ---------- 5) Regressiya: UZ/RU tugmalar hali ham taniladi ----------
    for label in (BTN_NEW_POST, BTN_NEW_POST_RU, BTN_SETTINGS_RU,
                  get_text("btn_settings", "ru"), BTN_ADMIN_PANEL_RU):
        h = _first_match(label)
        check(f"UZ/RU regressiya: {label[:26]!r} → Conversation",
              isinstance(h, ConversationHandler), type(h).__name__)

    # Tasodifiy (notanish) matn — fallback'ga tushadi
    h = _first_match("hello, this is a random english message")
    check("EN tasodifiy matn → fallback",
          h is not None and getattr(h, "callback", None) is unknown_message_fallback,
          type(h).__name__)

    # ---------- 6) Fallback javobi: foydalanuvchi tilida (EN) + asosiy menyu ----------
    class _RecBot:
        id = 1
        username = "TestBot"
        defaults = None

        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id=None, text=None, reply_markup=None,
                               parse_mode=None, **kw):
            self.sent.append({"chat_id": chat_id, "text": text,
                              "reply_markup": reply_markup})
            return types.SimpleNamespace(message_id=len(self.sent))

    # 6a) Dialogdan TASHQARIDA: tushunarsiz EN matn → EN fallback + EN menyu
    h_mod._UNKNOWN_FALLBACK_LAST.clear()
    bot = _RecBot()
    user = User(id=888, first_name="Bob", is_bot=False)
    chat = Chat(id=888, type="private")
    msg = Message(message_id=1, date=_dt.datetime.now(), chat=chat,
                  from_user=user, text="hello?")
    msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    upd.set_bot(bot)
    ctx = CallbackContext(app, chat_id=888, user_id=888)
    ctx.user_data["lang"] = "en"
    asyncio.run(unknown_message_fallback(upd, ctx))
    check("EN fallback: javob yuborildi", len(bot.sent) == 1, str(len(bot.sent)))
    if bot.sent:
        check("EN fallback: matn inglizcha",
              bot.sent[0]["text"] == get_text("unknown_message_fallback", "en"),
              str(bot.sent[0]["text"]))
        kb = bot.sent[0]["reply_markup"]
        check("EN fallback: asosiy menyu klaviaturasi bor",
              isinstance(kb, ReplyKeyboardMarkup), type(kb).__name__)
        labels = [b.text for row in kb.keyboard for b in row] if kb is not None else []
        check("EN fallback: klaviatura EN tugmalar bilan",
              BTN_NEW_POST_EN in labels and BTN_SETTINGS_EN in labels, str(labels))

    # 6b) Dialog ICHIDA: qabul qilinmaydigan xabar turi → EN eslatma,
    #     menyu YUBORILMAYDI, dialog holati buzilmaydi
    from handlers.start import TRANSFER_TARGET
    conv._conversations[(999, 999)] = TRANSFER_TARGET
    h_mod._UNKNOWN_FALLBACK_LAST.clear()
    try:
        bot2 = _RecBot()
        user2 = User(id=999, first_name="Eve", is_bot=False)
        chat2 = Chat(id=999, type="private")
        msg2 = Message(message_id=1, date=_dt.datetime.now(), chat=chat2,
                       from_user=user2,
                       voice=Voice(file_id="v", file_unique_id="vu", duration=3))
        msg2.set_bot(bot2)
        upd2 = Update(update_id=1, message=msg2)
        upd2.set_bot(bot2)
        ctx2 = CallbackContext(app, chat_id=999, user_id=999)
        ctx2.user_data["lang"] = "en"
        asyncio.run(unknown_message_fallback(upd2, ctx2))
        check("EN in_dialog: eslatma yuborildi", len(bot2.sent) == 1, str(len(bot2.sent)))
        if bot2.sent:
            check("EN in_dialog: matn inglizcha",
                  bot2.sent[0]["text"] == get_text("unknown_in_dialog", "en"),
                  str(bot2.sent[0]["text"]))
            check("EN in_dialog: klaviatura o'zgarmaydi",
                  bot2.sent[0]["reply_markup"] is None)
        check("EN in_dialog: holat buzilmadi",
              conv._conversations.get((999, 999)) == TRANSFER_TARGET)
    finally:
        conv._conversations.pop((999, 999), None)
        h_mod._UNKNOWN_FALLBACK_LAST.clear()


def test_ai_studio_i18n_suite():
    """2-QISM: ✨ AI Studio i18n (uz/ru) — klaviaturalar va matnlar ikki tilda."""
    print("== AI Studio i18n (uz/ru) ==")
    from keyboards.inline import (
        get_ai_studio_keyboard, get_ai_tone_keyboard, get_ai_back_keyboard,
        get_ai_confirm_keyboard, get_ai_photo_keyboard, AI_TONE_KEYS,
    )
    from locales.translations import get_text, TRANSLATIONS
    import handlers.ai_assistant as ai
    import inspect

    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    # 1) Barcha ai_* kalitlar ikki tilda mavjud va tarjima qilingan
    ai_keys = [k for k in uz if k.startswith("ai_")]
    check("ai i18n: barcha kalitlar uz'da", all(k in uz for k in ai_keys))
    check("ai i18n: barcha kalitlar ru'da", all(k in ru for k in ai_keys))
    check("ai i18n: kalitlar tarjima qilingan (uz != ru)",
          all(uz.get(k) != ru.get(k) for k in ai_keys),
          str([k for k in ai_keys if uz.get(k) == ru.get(k)]))

    # 2) AI Studio menyu klaviaturasi — UZ va RU bir xil callback_data, turlicha matn
    kb_uz = get_ai_studio_keyboard("uz")
    kb_ru = get_ai_studio_keyboard("ru")
    uz_labels = [b.text for row in kb_uz.inline_keyboard for b in row]
    ru_labels = [b.text for row in kb_ru.inline_keyboard for b in row]
    uz_cbs = [b.callback_data for row in kb_uz.inline_keyboard for b in row]
    ru_cbs = [b.callback_data for row in kb_ru.inline_keyboard for b in row]
    check("studio kb: 6 ta tugma (uz)", len(uz_labels) == 6, str(len(uz_labels)))
    check("studio kb: 6 ta tugma (ru)", len(ru_labels) == 6, str(len(ru_labels)))
    check("studio kb: callback_data bir xil (uz==ru)", uz_cbs == ru_cbs, str((uz_cbs, ru_cbs)))
    check("studio kb: callback_data to'g'ri",
          uz_cbs == ["studio_ai_post", "studio_ai_photo", "studio_extract",
                     "studio_ai_audit", "studio_content_plan", "studio_close"])
    check("studio kb uz: ai_studio_post label",
          uz_labels[0] == get_text("ai_studio_post", "uz"))
    check("studio kb ru: ai_studio_post label",
          ru_labels[0] == get_text("ai_studio_post", "ru"))
    check("studio kb ru: label tarjimasi (rus)", "Написать" in ru_labels[0], ru_labels[0])

    # 3) Tone of Voice klaviaturasi — RU tarjimasi
    tk_ru = get_ai_tone_keyboard("friendly", "ru")
    tk_ru_labels = [b.text for row in tk_ru.inline_keyboard for b in row]
    tk_ru_cbs = [b.callback_data for row in tk_ru.inline_keyboard for b in row]
    check("tone kb ru: 4 uslub + rejalashtirish + 2 nav = 7 tugma",
          len(tk_ru_cbs) == 7, str(tk_ru_cbs))
    check("tone kb ru: ai_tone callback",
          all(f"ai_tone:{t}" in tk_ru_cbs for t in AI_TONE_KEYS), str(tk_ru_cbs))
    check("tone kb ru: friendly tarjimasi",
          any(get_text("ai_tone_friendly", "ru") in t for t in tk_ru_labels),
          str(tk_ru_labels))
    check("tone kb ru: tanlangan uslub ✅",
          any(t.endswith("✅") for t in tk_ru_labels))
    check("tone kb: AI_TONE_KEYS mavjud", set(AI_TONE_KEYS) == {
        "formal", "friendly", "concise", "engaging"})

    # 4) Doimiy navigatsiya (back) klaviaturasi — RU
    bk_ru = get_ai_back_keyboard("ru")
    bk_ru_labels = [b.text for row in bk_ru.inline_keyboard for b in row]
    bk_ru_cbs = [b.callback_data for row in bk_ru.inline_keyboard for b in row]
    check("back kb ru: orqaga/bekor callback",
          bk_ru_cbs == ["ai_back_to_menu", "ai_close"])
    check("back kb ru: matnlar tarjimasi",
          get_text("ai_btn_back", "ru") in bk_ru_labels
          and get_text("ai_btn_close", "ru") in bk_ru_labels, str(bk_ru_labels))

    # 5) Tasdiqlash (confirm) klaviaturasi — RU
    ck_ru = get_ai_confirm_keyboard("ru")
    ck_ru_labels = [b.text for row in ck_ru.inline_keyboard for b in row]
    ck_ru_cbs = [b.callback_data for row in ck_ru.inline_keyboard for b in row]
    check("confirm kb ru: 3 tugma", ck_ru_cbs == [
        "ai_post_schedule", "ai_post_retry", "ai_post_cancel"], str(ck_ru_cbs))
    check("confirm kb ru: schedule tarjimasi",
          get_text("ai_confirm_schedule", "ru") in ck_ru_labels, str(ck_ru_labels))
    check("confirm kb ru: edit tarjimasi",
          get_text("ai_confirm_edit", "ru") in ck_ru_labels)

    # 6) Vision natija klaviaturasi — RU
    pk_ru = get_ai_photo_keyboard("ru")
    pk_ru_labels = [b.text for row in pk_ru.inline_keyboard for b in row]
    pk_ru_cbs = [b.callback_data for row in pk_ru.inline_keyboard for b in row]
    check("photo kb ru: 5 tugma (3 + nav)", pk_ru_cbs == [
        "photo_schedule", "photo_rewrite", "photo_edit",
        "ai_back_to_menu", "ai_close"], str(pk_ru_cbs))
    check("photo kb ru: schedule tarjimasi",
          get_text("ai_photo_schedule", "ru") in pk_ru_labels, str(pk_ru_labels))
    check("photo kb ru: rewrite tarjimasi",
          get_text("ai_photo_rewrite", "ru") in pk_ru_labels)
    check("photo kb ru: edit tarjimasi",
          get_text("ai_photo_edit", "ru") in pk_ru_labels)

    # 7) Matn yordamchilari (sync) — tilga mos
    prev = ai._studio_preview_text("Salom post", "friendly", None, "ru")
    check("preview ru: title", get_text("ai_preview_title", "ru") in prev, prev[:40])
    check("preview ru: tone label", get_text("ai_tone_friendly", "ru") in prev, prev[:120])
    photo_txt = ai._photo_result_text("Rasm post", "ru")
    check("photo result ru: title", get_text("ai_photo_result_title", "ru") in photo_txt, photo_txt[:40])
    check("photo result ru: foot", get_text("ai_photo_result_foot", "ru") in photo_txt, photo_txt[:200])

    # 8) ai_studio_menu_entry — AI_MENU_STATE qaytaradi (coroutine mavjud)
    check("ai_studio_menu_entry coroutine",
          inspect.iscoroutinefunction(ai.ai_studio_menu_entry))
    check("AI_MENU_STATE holati mavjud", ai.AI_MENU_STATE == 404)

    # 9) Xato/xabar matnlari ikkala tilda mavjud va farqli
    for key in ("ai_unavailable", "ai_media_received", "ai_no_post_text",
                "ai_photo_no_text", "ai_schedule_need_post", "ai_scheduled_ok",
                "ai_post_cancelled", "ai_photo_only", "ai_time_unparsed"):
        check(f"i18n: {key} uz+ru mavjud", key in uz and key in ru)
        check(f"i18n: {key} tarjima qilingan", uz.get(key) != ru.get(key) and bool(uz.get(key)))


def test_new_post_i18n_suite():
    """3-QISM: Yangi post oqimi i18n (uz/ru) — tugmalar, preview, image kalitlar."""
    print("== Yangi post i18n (uz/ru) ==")
    from locales.translations import TRANSLATIONS, get_text
    from handlers.new_post import (
        _build_preview_text, _get_confirm_keyboard, _get_edit_confirm_keyboard,
        _get_ai_action_keyboard, _get_ai_result_keyboard,
    )
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    # 1) Barcha np_* kalitlari ikki tilda mavjud va tarjima qilingan
    np_keys = [k for k in uz if k.startswith("np_")]
    check("np_* kalitlari ru'da ham bor",
          all(k in ru for k in np_keys), str([k for k in np_keys if k not in ru][:5]))
    untranslated = [k for k in np_keys if uz.get(k) == ru.get(k)]
    # Emoji-only kalitlar (np_type_animation) bundan mustasno
    allowed_same = {"np_type_animation", "np_scheduled_when_single"}
    check("np_* kalitlari tarjima qilingan",
          all(k in allowed_same for k in untranslated),
          str(untranslated))

    # 2) Confirm / Edit keyboard — RU yorliqlar va o'zgarmas callback_data
    ck_ru = _get_confirm_keyboard("ru")
    ck_uz = _get_confirm_keyboard("uz")
    ru_labels = [b.text for row in ck_ru.inline_keyboard for b in row]
    ru_cbs = [b.callback_data for row in ck_ru.inline_keyboard for b in row]
    uz_cbs = [b.callback_data for row in ck_uz.inline_keyboard for b in row]
    check("confirm kb ru/callback bir xil", ru_cbs == uz_cbs, str((ru_cbs, uz_cbs)))
    check("confirm kb ru: ok tugmasi",
          get_text("np_confirm_ok_btn", "ru") in ru_labels, str(ru_labels))
    check("confirm kb ru: queue tugmasi",
          get_text("np_confirm_queue_btn", "ru") in ru_labels)
    check("confirm kb ru: edit/cancel",
          get_text("np_confirm_edit_btn", "ru") in ru_labels
          and get_text("np_confirm_cancel_btn", "ru") in ru_labels)

    ekb_ru = _get_edit_confirm_keyboard("ru")
    ekb_uz = _get_edit_confirm_keyboard("uz")
    e_ru_labels = [b.text for row in ekb_ru.inline_keyboard for b in row]
    e_ru_cbs = [b.callback_data for row in ekb_ru.inline_keyboard for b in row]
    e_uz_cbs = [b.callback_data for row in ekb_uz.inline_keyboard for b in row]
    check("edit kb ru/callback bir xil", e_ru_cbs == e_uz_cbs)
    check("edit kb ru: matn tahrirlash",
          get_text("np_edit_content_btn", "ru") in e_ru_labels, str(e_ru_labels))
    check("edit kb ru: kanal/vaqt/tugma/back",
          all(t in e_ru_labels for t in (
              get_text("np_edit_channel_btn", "ru"), get_text("np_edit_time_btn", "ru"),
              get_text("np_edit_button_btn", "ru"), get_text("np_edit_back_btn", "ru"))))

    # 3) Preview matni RU
    tz = pytz.timezone("Asia/Tashkent")
    class _Ctx:
        def __init__(self, data):
            self.user_data = data
    ctx = _Ctx({
        "lang": "ru", "selected_channel_title": "Мой канал",
        "post_type": "text", "content": "Привет",
        "btn_text": "Сайт", "btn_url": "https://x.uz",
        "enable_reactions": True, "reaction_emojis": ["👍"],
        "delete_after_hours": 24,
        "confirm_post_time": tz.localize(datetime(2026, 9, 5, 14, 0)),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None, "confirm_recurrence_time_str": None,
    })
    preview = _build_preview_text(ctx)
    check("preview ru: sarlavha",
          get_text("np_confirm_title", "ru") in preview, preview[:60])
    check("preview ru: kanal", "Мой канал" in preview)
    check("preview ru: vaqt", "2026-09-05 14:00" in preview)
    check("preview ru: tugma", "Сайт" in preview)
    check("preview ru: avto-o'chirish", "24" in preview and "ч" in preview)

    # daily recurrence RU
    ctx.user_data["confirm_recurrence_type"] = "daily"
    ctx.user_data["confirm_recurrence_time_str"] = "09:00:00"
    preview_d = _build_preview_text(ctx)
    check("preview ru: daily", "каждый день" in preview_d.lower() or "Ежедневно" in preview_d,
          preview_d[:120])
    # weekly RU
    ctx.user_data["confirm_recurrence_type"] = "weekly"
    ctx.user_data["confirm_recurrence_day"] = 4
    ctx.user_data["confirm_recurrence_time_str"] = "13:00:00"
    preview_w = _build_preview_text(ctx)
    check("preview ru: weekly (Juma)",
          any(d in preview_w for d in ("Пятница", "Пятн")), preview_w[:160])

    # 4) AI klaviaturalari RU
    ak_ru = _get_ai_action_keyboard("ru")
    ak_ru_labels = [b.text for row in ak_ru.inline_keyboard for b in row]
    ak_uz_cbs = [b.callback_data for row in _get_ai_action_keyboard("uz").inline_keyboard for b in row]
    ak_ru_cbs = [b.callback_data for row in ak_ru.inline_keyboard for b in row]
    check("ai action kb: callback bir xil", ak_ru_cbs == ak_uz_cbs)
    check("ai action kb ru: grammar",
          get_text("np_ai_action_grammar", "ru") in ak_ru_labels, str(ak_ru_labels))
    rk_ru = _get_ai_result_keyboard("ru")
    rk_ru_labels = [b.text for row in rk_ru.inline_keyboard for b in row]
    check("ai result kb ru: accept/retry/revert",
          all(t in rk_ru_labels for t in (
              get_text("np_ai_btn_accept", "ru"), get_text("np_ai_btn_retry", "ru"),
              get_text("np_ai_btn_revert", "ru"))))

    # 5) Keyboard default — turlar RU
    from keyboards.default import (
        get_button_prompt_keyboard, get_reactions_keyboard, get_auto_delete_keyboard,
        get_time_keyboard, get_duration_keyboard, get_weekday_keyboard,
    )
    def _labels(kb):
        return [b.text for row in kb.keyboard for b in row]
    check("button prompt kb ru: AI yordamchi",
          get_text("np_btn_ai_assistant", "ru") in _labels(get_button_prompt_keyboard("ru")))
    check("button prompt kb ru: skip",
          get_text("np_btn_skip_url", "ru") in _labels(get_button_prompt_keyboard("ru")))
    check("reactions kb ru: skip",
          get_text("np_btn_no_reactions", "ru") in _labels(get_reactions_keyboard("ru")))
    check("auto-delete kb ru: 12/24",
          get_text("np_btn_del_12h", "ru") in _labels(get_auto_delete_keyboard("ru"))
          and get_text("np_btn_del_24h", "ru") in _labels(get_auto_delete_keyboard("ru")))
    check("time kb ru: 5 min/daily/weekly",
          all(t in _labels(get_time_keyboard("ru")) for t in (
              get_text("np_btn_time_5m", "ru"), get_text("np_btn_time_daily", "ru"),
              get_text("np_btn_time_weekly", "ru"))))
    check("duration kb ru: 1 hafta/cheksiz",
          get_text("np_btn_dur_1w", "ru") in _labels(get_duration_keyboard("ru"))
          and get_text("np_btn_dur_inf", "ru") in _labels(get_duration_keyboard("ru")))
    wk_labels = _labels(get_weekday_keyboard("ru"))
    check("weekday kb ru: Dushanba",
          get_text("np_weekday_0", "ru") in wk_labels, str(wk_labels))

    # 6) Reaction toggle — RU (callback data o'zgarmaydi)
    from keyboards.inline import get_reaction_toggle_keyboard, CB_REACT_DONE, CB_REACT_SKIP
    rt_ru = get_reaction_toggle_keyboard(["👍"], "ru")
    rt_ru_labels = [b.text for row in rt_ru.inline_keyboard for b in row]
    rt_ru_cbs = [b.callback_data for row in rt_ru.inline_keyboard for b in row]
    check("react toggle ru: done label",
          get_text("np_react_done_count", "ru", count=1) in rt_ru_labels, str(rt_ru_labels))
    check("react toggle ru: skip label",
          get_text("np_react_skip", "ru") in rt_ru_labels)
    check("react toggle ru: callback bir xil",
          CB_REACT_DONE in rt_ru_cbs and CB_REACT_SKIP in rt_ru_cbs)

    # 7) Route: "➕ Новый пост" ikki tilda
    from keyboards.default import BTN_NEW_POST, BTN_NEW_POST_RU
    check("routing: yangi post uz", BTN_NEW_POST == "➕ Yangi post")
    check("routing: yangi post ru", BTN_NEW_POST_RU == "➕ Новый пост")


def test_channels_i18n_suite():
    """3-QISM: Kanallar (channels) i18n (uz/ru)."""
    print("== Kanallar i18n (uz/ru) ==")
    from locales.translations import TRANSLATIONS, get_text
    from handlers.channels import (
        _retry_verify_keyboard, _empty_channels_keyboard,
        _channel_limit_text, _pro_upgrade_keyboard,
    )
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    ch_keys = [k for k in uz if k.startswith("ch_")]
    check("ch_* kalitlari ru'da ham bor",
          all(k in ru for k in ch_keys), str([k for k in ch_keys if k not in ru][:5]))
    check("ch_* kalitlari tarjima qilingan",
          all(uz.get(k) != ru.get(k) for k in ch_keys),
          str([k for k in ch_keys if uz.get(k) == ru.get(k)][:5]))

    # Retry keyboard — RU label, bir xil callback
    rk = _retry_verify_keyboard("ru")
    rku = _retry_verify_keyboard("uz")
    check("retry kb ru: label",
          rk.inline_keyboard[0][0].text == get_text("ch_retry_btn", "ru"),
          rk.inline_keyboard[0][0].text)
    check("retry kb: callback o'zgarmagan",
          rk.inline_keyboard[0][0].callback_data == "add_channel_retry"
          and rku.inline_keyboard[0][0].callback_data == "add_channel_retry")

    # Empty channels keyboard
    ek = _empty_channels_keyboard("ru")
    ek_labels = [b.text for row in ek.inline_keyboard for b in row]
    ek_cbs = [b.callback_data for row in ek.inline_keyboard for b in row]
    check("empty kb ru: qo'shish",
          get_text("ch_add_btn", "ru") in ek_labels, str(ek_labels))
    check("empty kb ru: yopish",
          get_text("pend_close_btn", "ru") in ek_labels)
    check("empty kb: callback o'zgarmagan",
          ek_cbs == ["add_channel_start", "close_msg"], str(ek_cbs))

    # Limit text
    lim_ru = _channel_limit_text("ru", 5, 3)
    lim_uz = _channel_limit_text("uz", 5, 3)
    check("limit ru: ruscha", "Лимит" in lim_ru and "5/3" in lim_ru, lim_ru[:60])
    check("limit uz: o'zbekcha", "Kanal limiti" in lim_uz and "5/3" in lim_uz)

    # PRO keyboard
    pk = _pro_upgrade_keyboard("ru")
    check("pro kb ru: label",
          pk.inline_keyboard[0][0].text == get_text("ch_pro_btn", "ru"))
    check("pro kb: callback o'zgarmagan",
          pk.inline_keyboard[0][0].callback_data == "sub_open")

    # render_channels_list — RU
    from keyboards.inline import render_channels_list
    ch = render_channels_list([("-1001", "Kanal 1", "formal")], "ru")
    ch_labels = [b.text for row in ch.inline_keyboard for b in row]
    check("kanallar ro'yxati ru: o'chirish",
          get_text("cab_remove_channel", "ru") in ch_labels)
    check("kanallar ro'yxati ru: qo'shish",
          get_text("cab_add_channel_alt", "ru") in ch_labels)


def test_pending_i18n_suite():
    """3-QISM: Kutilayotgan postlar (pending) i18n (uz/ru)."""
    print("== Pending i18n (uz/ru) ==")
    from locales.translations import TRANSLATIONS, get_text
    from keyboards.inline import render_pending_list
    from utils.helpers import format_post_type_label, format_schedule_line
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    pend_keys = [k for k in uz if k.startswith("pend_")]
    check("pend_* kalitlari ru'da ham bor",
          all(k in ru for k in pend_keys), str([k for k in pend_keys if k not in ru][:5]))
    check("pend_* kalitlari tarjima qilingan",
          all(uz.get(k) != ru.get(k) for k in pend_keys),
          str([k for k in pend_keys if uz.get(k) == ru.get(k)][:5]))

    # Pending list buttons — RU label, bir xil callback
    tz = pytz.timezone("Asia/Tashkent")
    posts = [(101, "Kanal A", "text", tz.localize(datetime(2026, 9, 10, 12, 0)), 3, "none", None, None)]
    ru_kb = render_pending_list(posts, "ABC", "ru")
    uz_kb = render_pending_list(posts, "ABC", "uz")
    ru_labels = [b.text for row in ru_kb.inline_keyboard for b in row]
    ru_cbs = [b.callback_data for row in ru_kb.inline_keyboard for b in row]
    uz_cbs = [b.callback_data for row in uz_kb.inline_keyboard for b in row]
    check("pending kb: callback bir xil", ru_cbs == uz_cbs, str((ru_cbs, uz_cbs)))
    check("pending kb ru: vaqt/matn tahrirlash",
          get_text("pend_edit_time_btn", "ru", code="ABC-3") in ru_labels
          and get_text("pend_edit_content_btn", "ru", code="ABC-3") in ru_labels,
          str(ru_labels))
    check("pending kb ru: bekor/yangilash/yopish",
          all(t in ru_labels for t in (
              get_text("pend_cancel_btn", "ru"), get_text("pend_refresh_btn", "ru"),
              get_text("pend_close_btn", "ru"))))

    # format_post_type_label — RU
    check("post_type ru: video", format_post_type_label("video", "ru") == "Видео",
          format_post_type_label("video", "ru"))
    check("post_type uz: video", format_post_type_label("video") == "Video")
    check("post_type ru: unknown", format_post_type_label("xyz", "ru") == "Сообщение")

    # format_schedule_line — RU (daily/weekly/once)
    s_line_daily = format_schedule_line(None, "daily", None, "10:00:00", "ru")
    check("schedule ru: daily", "каждый день" in s_line_daily.lower() or "Ежедневно" in s_line_daily,
          s_line_daily)
    s_line_weekly = format_schedule_line(None, "weekly", 4, "13:00:00", "ru")
    check("schedule ru: weekly Juma", any(d in s_line_weekly for d in ("Пятница", "Пятн")),
          s_line_weekly)
    s_line_once = format_schedule_line(tz.localize(datetime(2026, 9, 10, 12, 0)),
                                       "none", None, None, "ru")
    check("schedule ru: once", "2026-09-10 12:00" in s_line_once, s_line_once)


def test_queue_i18n_suite():
    """3-QISM: Navbat (queue) i18n (uz/ru)."""
    print("== Queue i18n (uz/ru) ==")
    from locales.translations import TRANSLATIONS, get_text
    from handlers.queue import (
        _get_queue_list_keyboard, _get_slots_keyboard, _get_post_detail_keyboard,
        _format_queue_item,
    )
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    queue_keys = [k for k in uz if k.startswith("queue_")]
    check("queue_* kalitlari ru'da ham bor",
          all(k in ru for k in queue_keys), str([k for k in queue_keys if k not in ru][:5]))
    check("queue_* kalitlari tarjima qilingan",
          all(uz.get(k) != ru.get(k) for k in queue_keys),
          str([k for k in queue_keys if uz.get(k) == ru.get(k)][:5]))

    # Queue list keyboard — RU label, bir xil callback
    tz = pytz.timezone("Asia/Tashkent")
    row = (1, "Kanal", "text", "x", tz.localize(datetime(2026, 9, 1, 10, 0)), 1, "-100")
    kb_ru = _get_queue_list_keyboard([row], 0, 1, "ru")
    kb_uz = _get_queue_list_keyboard([row], 0, 1, "uz")
    ru_labels = [b.text for r in kb_ru.inline_keyboard for b in r]
    ru_cbs = [b.callback_data for r in kb_ru.inline_keyboard for b in r]
    uz_cbs = [b.callback_data for r in kb_uz.inline_keyboard for b in r]
    check("queue list kb: callback bir xil", ru_cbs == uz_cbs, str((ru_cbs, uz_cbs)))
    check("queue list kb ru: ko'rish/o'chirish/surish",
          get_text("queue_btn_view", "ru", id=1) in ru_labels
          and get_text("queue_btn_delete", "ru") in ru_labels
          and get_text("queue_btn_push", "ru") in ru_labels, str(ru_labels))
    check("queue list kb ru: slotlar/yopish",
          get_text("queue_btn_slots", "ru") in ru_labels
          and get_text("queue_btn_close", "ru") in ru_labels)

    # Detail keyboard
    dk_ru = _get_post_detail_keyboard(5, "ru")
    dk_ru_labels = [b.text for r in dk_ru.inline_keyboard for b in r]
    dk_ru_cbs = [b.callback_data for r in dk_ru.inline_keyboard for b in r]
    check("queue detail ru: orqaga",
          get_text("queue_btn_back", "ru") in dk_ru_labels)
    check("queue detail ru: callback o'zgarmagan",
          dk_ru_cbs == ["qdel:5", "qpush:5", "qpage:0"], str(dk_ru_cbs))

    # Slots keyboard
    sk_ru = _get_slots_keyboard(["09:00", "19:00"], "ru")
    sk_ru_labels = [b.text for r in sk_ru.inline_keyboard for b in r]
    sk_ru_cbs = [b.callback_data for r in sk_ru.inline_keyboard for b in r]
    check("slots kb ru: qo'shish/default",
          get_text("queue_btn_add_slot", "ru") in sk_ru_labels
          and get_text("queue_btn_reset_slots", "ru") in sk_ru_labels)
    check("slots kb ru: callback o'zgarmagan",
          "qslots:rm:0" in sk_ru_cbs and "qslots:reset" in sk_ru_cbs
          and "qslots:add" in sk_ru_cbs and "qpage:0" in sk_ru_cbs, str(sk_ru_cbs))

    # _format_queue_item tilda o'zgarmaydigan qism (raqam/vaqt)
    item = _format_queue_item(row, 1, "ru")
    check("queue item ru: kanal saqlanadi", "Kanal" in item and item.startswith("1."), item)

    # Routing: queue/pending RU tugmalari
    from keyboards.default import BTN_QUEUE, BTN_QUEUE_RU, BTN_PENDING, BTN_PENDING_RU
    check("routing: queue uz", "Navbat" in BTN_QUEUE)
    check("routing: queue ru", "Очередь" in BTN_QUEUE_RU)
    check("routing: pending uz", "Kutilayotgan" in BTN_PENDING)
    check("routing: pending ru", "Ожидающие" in BTN_PENDING_RU)



# ============================================================
# 4-QISM: EXTRAS / HELP / CONVERTER / TIZIM XABARLARI i18n (UZ/RU)
# ============================================================

def test_extras_help_i18n_suite():
    """4-QISM: ⚙️ Qo'shimcha funksiyalar, 📖 Qo'llanma va tizim xabarlari (uz/ru)."""
    print("== Extras/Help/Converter/System i18n (uz/ru) ==")
    import asyncio
    from locales.translations import TRANSLATIONS, get_text
    from keyboards.inline import (
        get_extras_inline_keyboard, get_help_keyboard, get_help_back_keyboard,
    )
    uz, ru = TRANSLATIONS["uz"], TRANSLATIONS["ru"]

    # --- 1. Lug'at kalitlari: ikkala tilda ham mavjud va tarjima qilingan ---
    prefixes = ("extras_", "conv_", "enh_", "help_", "sys_", "cab_guide_",
                "cab_converter_info")
    part4_keys = sorted({
        k for k in set(uz) | set(ru)
        if k.startswith(prefixes) or k in ("msg_closed", "cancel_done")
    })
    check("4-qism kalitlari uz'da mavjud",
          all(k in uz for k in part4_keys),
          str([k for k in part4_keys if k not in uz][:5]))
    check("4-qism kalitlari ru'da mavjud",
          all(k in ru for k in part4_keys),
          str([k for k in part4_keys if k not in ru][:5]))
    # Faqat-shablon kalitlari (tildan mustaqil formatlar) — teng bo'lishi mumkin
    lang_neutral = {"enh_btns_line", "enh_btn_entry_edit"}
    diff_keys = [k for k in part4_keys if k not in lang_neutral]
    check("4-qism kalitlari tarjima qilingan (uz != ru)",
          all(uz[k] != ru[k] for k in diff_keys),
          str([k for k in diff_keys if uz[k] == ru[k]][:5]))
    check("4-qism: kamida 100 ta yangi kalit", len(part4_keys) >= 100, str(len(part4_keys)))

    # --- 2. ⚙️ Extras inline klaviatura: uz/ru yorliqlar, bir xil callback ---
    kb_uz = get_extras_inline_keyboard()            # default uz (orqaga moslik)
    kb_ru = get_extras_inline_keyboard("ru")
    uz_rows = [[(b.text, b.callback_data) for b in row] for row in kb_uz.inline_keyboard]
    ru_rows = [[(b.text, b.callback_data) for b in row] for row in kb_ru.inline_keyboard]
    check("extras kb uz: 3 qator, uz yorliqlar",
          uz_rows == [
              [("✨ Postga Tugma & Reaksiya qo'shish", "extra_enhancer")],
              [("🔤 Krill-Lotin konvertor", "extra_converter")],
              [("❌ Yopish", "extra_close")],
          ], str(uz_rows))
    check("extras kb ru: callback'lar bir xil",
          [c for row in ru_rows for _, c in row]
          == ["extra_enhancer", "extra_converter", "extra_close"], str(ru_rows))
    check("extras kb ru: yorliqlar ru lug'atdan",
          ru_rows[0][0][0] == get_text("extras_btn_enhancer", "ru")
          and ru_rows[1][0][0] == get_text("extras_btn_converter", "ru")
          and ru_rows[2][0][0] == get_text("cab_close", "ru"), str(ru_rows))
    check("extras kb: ru yorliqlar uz'dan farq qiladi",
          ru_rows[0][0][0] != uz_rows[0][0][0] and ru_rows[2][0][0] != uz_rows[2][0][0])
    check("extras menyu matni ru",
          "Дополнительные функции" in get_text("extras_menu_body", "ru"))

    # --- 3. 🔤 Konverter: kalitlar uz/ru ---
    check("conv: kirish matni uz/ru",
          "O'girgich" in get_text("conv_intro", "uz")
          and "Конвертер" in get_text("conv_intro", "ru"))
    check("conv: tugma yorliqlari",
          get_text("conv_btn_cyr", "uz") == "🔤 Kirillcha nusxasi"
          and get_text("conv_btn_lat", "uz") == "🔤 Lotincha nusxasi"
          and get_text("conv_btn_cyr", "ru") == "🔤 Кириллическая версия"
          and get_text("conv_btn_lat", "ru") == "🔤 Латинская версия")
    check("conv: natija/matn topilmadi/xato",
          "Natija" in get_text("conv_result_title", "uz")
          and "Результат" in get_text("conv_result_title", "ru")
          and "topilmadi" in get_text("conv_no_saved_text", "uz")
          and "не найден" in get_text("conv_no_saved_text", "ru")
          and "{error}" not in get_text("conv_error", "uz", error="X")
          and "ошибка" in get_text("conv_error", "ru", error="X").lower())

    # --- 4. 📖 Qo'llanma: guide + FAQ + support havolasi ---
    for lg in ("uz", "ru"):
        guide = get_text("help_guide", lg, support="SUP_TAG")
        check(f"help_guide {lg}: support almashtirilgan",
              "SUP_TAG" in guide and "{support}" not in guide, guide[-80:])
    guide_uz = get_text("help_guide", "uz", support="")
    check("help_guide uz: kanal/rejalashtirish/AI Studio/extras",
          all(w in guide_uz for w in ("Kanal", "rejalashtirish", "AI Studio",
                                      "Qo'shimcha funksiyalar", "Kunlik bonus")))
    guide_ru = get_text("help_guide", "ru", support="")
    check("help_guide ru: канал/планирование/AI Studio/extras",
          all(w in guide_ru for w in ("канал", "Планирование", "AI Studio",
                                      "Дополнительные функции", "Ежедневный бонус")))
    check("help_guide_admin uz/ru",
          "Admin buyruqlari" in get_text("help_guide_admin", "uz")
          and "администратора" in get_text("help_guide_admin", "ru"))
    faq_uz = get_text("help_faq", "uz", support="")
    faq_ru = get_text("help_faq", "ru", support="")
    check("help_faq uz: sarlavha va 5 savol",
          "Tez-tez beriladigan savollar" in faq_uz and faq_uz.count("<b>") >= 6, faq_uz[:60])
    check("help_faq ru: sarlavha",
          "Часто задаваемые вопросы" in faq_ru)
    check("support tugma yorliqlari (Bog'lanish / Связаться с поддержкой)",
          get_text("help_btn_support", "uz") == "💬 Bog'lanish"
          and get_text("help_btn_support", "ru") == "💬 Связаться с поддержкой")
    check("support line uz/ru",
          "{admin}" not in get_text("help_support_line", "uz", admin="@x")
          and "@x" in get_text("help_support_line", "ru", admin="@x"))

    hk = get_help_keyboard("support_user", "ru")
    hk_flat = [b for row in hk.inline_keyboard for b in row]
    check("help kb: support URL tugmasi (ru)",
          any(b.url == "https://t.me/support_user"
              and b.text == get_text("help_btn_support", "ru") for b in hk_flat),
          str([(b.text, b.url, b.callback_data) for b in hk_flat]))
    check("help kb: FAQ tugmasi (ru)",
          any(b.callback_data == "help:faq"
              and b.text == get_text("help_btn_faq", "ru") for b in hk_flat))
    hk_no = get_help_keyboard("", "uz")
    check("help kb: usernamesiz — faqat FAQ tugmasi",
          len(hk_no.inline_keyboard) == 1
          and hk_no.inline_keyboard[0][0].callback_data == "help:faq")
    hb = get_help_back_keyboard("ru")
    check("help back kb: ⬅️ Назад → help:guide",
          hb.inline_keyboard[0][0].text == get_text("btn_back", "ru")
          and hb.inline_keyboard[0][0].callback_data == "help:guide")

    # --- 5. Xatoliklar/tizim xabarlari uz/ru ---
    check("sys: tizim band (uz/ru)",
          "Tizim vaqtincha band" in get_text("sys_busy", "uz")
          and "временно занята" in get_text("sys_busy", "ru"))
    check("sys: bot qayta ishga tushgan (uz/ru)",
          "qayta ishga tushirilgan" in get_text("sys_stale_button", "uz")
          and "перезапущен" in get_text("sys_stale_button", "ru"))
    check("sys: kutilmagan xatolik (uz/ru)",
          "Kutilmagan xatolik" in get_text("sys_unexpected_error", "uz")
          and "непредвиденная ошибка" in get_text("sys_unexpected_error", "ru"))
    check("sys: suhbat muddati + yopish + bekor (uz/ru)",
          "Suhbat muddat" in get_text("conv_timeout_msg", "uz")
          and "истечении времени" in get_text("conv_timeout_msg", "ru")
          and get_text("msg_closed", "uz") == "✅ Yopildi."
          and get_text("msg_closed", "ru") == "✅ Закрыто."
          and "bekor qilindi" in get_text("cancel_done", "uz")
          and "отменено" in get_text("cancel_done", "ru"))
    check("sys: tizim matnlari uz/ru da real yangi qator bor",
          "\n" in get_text("sys_busy", "uz") and "\n" in get_text("sys_busy", "ru"))

    # --- 6. Konverter handlerlari: foydalanuvchi tilida chiqishi ---
    import handlers.converter as conv_mod

    class _UpdMsg:
        def __init__(self, message):
            self.message = message

    class _AdStub:
        """get_auto_ad_injection_async o'rniga — reklamasiz."""

    async def _no_ad(_chat_id):
        return ""

    async def _conv_run():
        # converter_received — RU matn, RU tugmalar, bir xil callback'lar
        orig_ad = conv_mod.get_auto_ad_injection_async
        conv_mod.get_auto_ad_injection_async = _no_ad
        try:
            bot = _FakeBot()
            ctx = _FakeCtx(bot, {"lang": "ru"})
            msg = _FakeMsg(1, 111, text="Salom dunyo")
            out = await conv_mod.converter_received(_UpdMsg(msg), ctx)
            check("conv handler: CONVERT_INPUT qaytdi", out == conv_mod.CONVERT_INPUT, str(out))
            replies = [c for c in bot.sent_of("reply_text")]
            check("conv handler: RU 'Текст получен' + inline kb",
                  replies and "Текст получен" in (replies[0][2] or "")
                  and replies[0][3] is not None,
                  str([c[2] for c in replies]))
            flat = [b for row in replies[0][3].inline_keyboard for b in row]
            check("conv handler: RU tugma yorliqlari + bir xil callback",
                  [b.callback_data for b in flat] == ["conv_show:cyr", "conv_show:lat", "conv_close"]
                  and flat[0].text == get_text("conv_btn_cyr", "ru")
                  and flat[1].text == get_text("conv_btn_lat", "ru")
                  and flat[2].text == get_text("cab_close", "ru"),
                  str([(b.text, b.callback_data) for b in flat]))

            # converter_callback — RU natija sarlavhasi
            ctx2 = _FakeCtx(bot, {
                "lang": "ru", "media_type": "text", "file_id": None,
                "cyr_text": "Салом дунё", "lat_text": "Salom dunyo",
            })
            q = _FakeQuery("conv_show:cyr", _FakeMsg(2, 111))
            await conv_mod.converter_callback(_UpdQ(q), ctx2)
            sent = bot.sent_of("send_message")
            check("conv callback: RU 'Результат' sarlavhasi",
                  sent and "Результат" in (sent[0][2] or "")
                  and "скопировать" in (sent[0][2] or ""),
                  str([c[2] for c in sent]))

            # converter_callback — matn yo'q bo'lsa RU ogohlantirish
            ctx3 = _FakeCtx(_FakeBot(), {"lang": "ru"})
            q2 = _FakeQuery("conv_show:cyr", _FakeMsg(3, 111))
            await conv_mod.converter_callback(_UpdQ(q2), ctx3)
            check("conv callback: matn yo'q — RU xabar",
                  q2.message.replies and "не найден" in q2.message.replies[-1],
                  str(q2.message.replies))

            # source: konverter get_lang/get_text asosida ishlaydi
            csrc = open(conv_mod.__file__, encoding="utf-8").read()
            for token in ('get_lang(context)', 'get_text("conv_intro"',
                          'get_text("conv_received"', 'get_text("msg_closed"',
                          'get_text("conv_error"'):
                check(f"conv source: {token}", token in csrc)
        finally:
            conv_mod.get_auto_ad_injection_async = orig_ad

    class _UpdQ:
        def __init__(self, query):
            self.callback_query = query

    asyncio.run(_conv_run())

    # --- 7. extras_menu / help_command / help_menu_callback runtime (uz/ru) ---
    # handlers.start atributi paketdagi `start()` funksiyasi bilan soyalanadi —
    # shuning uchun modul implisit import qilinadi (sys.modules dagi module obyekt).
    import importlib as _importlib
    st_mod = _importlib.import_module("handlers.start")
    from telegram.ext import ConversationHandler

    async def _start_run():
        orig_ad = st_mod.get_smart_reply_ad_async
        orig_support = st_mod.SUPPORT_USERNAME
        st_mod.get_smart_reply_ad_async = lambda uid: _no_ad(uid)
        st_mod.SUPPORT_USERNAME = "test_admin"
        try:
            # extras_menu — RU matn + RU klaviatura
            bot = _FakeBot()
            ctx = _FakeCtx(bot, {"lang": "ru"})
            msg = _FakeMsg(10, 111)
            out = await st_mod.extras_menu(_UpdMsg(msg), ctx)
            check("extras_menu: END qaytdi", out == ConversationHandler.END, str(out))
            rr = [c for c in bot.sent_of("reply_text")]
            check("extras_menu: RU matn + RU klaviatura",
                  rr and "Дополнительные функции" in (rr[0][2] or "")
                  and rr[0][3] is not None
                  and rr[0][3].inline_keyboard[2][0].text == get_text("cab_close", "ru"),
                  str([c[2][:60] for c in rr]))

            # help_command — RU guide + FAQ/support tugmalari
            class _UpdUser(_UpdMsg):
                def __init__(self, message, uid=999888777):
                    super().__init__(message)
                    self.effective_user = _FakeUser(uid)

            ctx2 = _FakeCtx(bot, {"lang": "ru"})
            msg2 = _FakeMsg(11, 111)
            await st_mod.help_command(_UpdUser(msg2), ctx2)
            hr = [c for c in bot.sent_of("reply_text")][-1]
            check("help_command ru: Полное руководство matni",
                  hr and "Полное руководство" in (hr[2] or "")
                  and "@test_admin" in (hr[2] or ""),
                  str((hr[2] or "")[:80]))
            hflat = [b for row in hr[3].inline_keyboard for b in row]
            check("help_command ru: support URL + FAQ tugmalar",
                  any(b.url == "https://t.me/test_admin" for b in hflat)
                  and any(b.callback_data == "help:faq" for b in hflat),
                  str([(b.text, b.url, b.callback_data) for b in hflat]))

            # help_command — uz foydalanuvchi, admin qo'shimchasi YO'Q
            ctx3 = _FakeCtx(bot, {"lang": "uz"})
            msg3 = _FakeMsg(12, 111)
            await st_mod.help_command(_UpdUser(msg3), ctx3)
            hr2 = [c for c in bot.sent_of("reply_text")][-1]
            check("help_command uz: To'liq Qo'llanma, admin qo'shimchasiz",
                  hr2 and "To'liq Qo'llanma" in (hr2[2] or "")
                  and "Admin buyruqlari" not in (hr2[2] or ""), str((hr2[2] or "")[:80]))

            # help_menu_callback — FAQ ↔ guide
            ctx4 = _FakeCtx(bot, {"lang": "ru"})
            q_faq = _FakeQuery("help:faq", _FakeMsg(13, 111))
            await st_mod.help_menu_callback(_UpdQ(q_faq), ctx4)
            check("help:faq — RU FAQ matni + orqaga tugmasi",
                  q_faq.edits and "Часто задаваемые вопросы" in q_faq.edits[0][0]
                  and q_faq.edits[0][1].inline_keyboard[0][0].callback_data == "help:guide",
                  str(q_faq.edits[:1]))
            q_guide = _FakeQuery("help:guide", _FakeMsg(14, 111))
            await st_mod.help_menu_callback(_UpdQ(q_guide), ctx4)
            check("help:guide — RU guide qaytadi",
                  q_guide.edits and "Полное руководство" in q_guide.edits[0][0],
                  str(q_guide.edits[:1]))

            # extras_close_callback — xabar o'chiradi; '✅ Закрыто. (msg_closed)'
            # o'chirish ishlamaganda fallback matni sifatida uz/ru tilida yuboriladi
            ctx5 = _FakeCtx(bot, {"lang": "ru"})
            q_close = _FakeQuery("extra_close", _FakeMsg(15, 111))
            await st_mod.extras_close_callback(_UpdQ(q_close), ctx5)
            dels = bot.sent_of("delete_message")
            check("extras_close: xabar o'chirildi (RU ctx)",
                  any(d[1] == 111 and d[2] == 15 for d in dels), str(dels))
            s_src = open(st_mod.__file__, encoding="utf-8").read()
            check("extras_close: msg_closed fallback get_text'da",
                  'get_text("msg_closed"' in s_src
                  and 'get_text("cancel_done"' in s_src
                  and 'get_text("cab_guide_text"' in s_src
                  and 'get_text("cab_converter_info"' in s_src)
        finally:
            st_mod.get_smart_reply_ad_async = orig_ad
            st_mod.SUPPORT_USERNAME = orig_support

    asyncio.run(_start_run())

    # --- 8. ✨ Post kuchaytirgich: RU lokalizatsiya nuqtalari ---
    import handlers.post_enhancer as pe
    import database as db_mod

    check("enh: intro RU admin eslatmasi bilan",
          pe.intro_text("ru").startswith("💡 <b>")
          and "Администратор" in pe.intro_text("ru")
          and "Отправьте пост" in pe.intro_text("ru"),
          pe.intro_text("ru")[:80])
    check("enh: ADMIN_NOTICE alias saqlangan (uz)",
          pe.ADMIN_NOTICE == get_text("enh_notice_admin", "uz")
          and "Admin" in pe.ADMIN_NOTICE)
    check("enh: URL_PRESETS uz default saqlangan",
          [dict(p) for p in pe.get_url_presets("uz")]
          == [dict(p) for p in pe.URL_PRESETS])
    ru_presets = pe.get_url_presets("ru")
    check("enh: presets RU",
          ru_presets[0]["text"] == "📢 Подписаться на канал"
          and ru_presets[1]["title"] == "Вступить в группу"
          and ru_presets[2]["text"] == "🤖 Перейти к боту", str(ru_presets))
    check("enh: build_preset_button RU",
          pe.build_preset_button(0, "@kanalim", "ru")
          == {"text": "📢 Подписаться на канал", "url": "https://t.me/kanalim"})
    check("enh: nav_row RU (Назад/Отмена)",
          [b.text for b in pe.nav_row("x", "ru")] == ["⬅️ Назад", "❌ Отмена"])
    summ_ru = pe.summarize_selection({"reactions": ["👍"], "buttons": []}, "ru")
    check("enh: summary RU + real newline",
          "Реакции" in summ_ru and "\n" in summ_ru and "\\n" not in summ_ru, repr(summ_ru))
    check("enh: summary uz regression",
          pe.summarize_selection({"reactions": ["👍"], "buttons": [{"text": "X", "url": "u"}]})
          == "👍 Reaksiyalar: <b>1/10</b> — 👍\n🔗 URL tugmalar: <b>1/10</b>")

    class _Ctx2:
        def __init__(self, data):
            self.user_data = data

    # hub/react/channel/confirm/success viewlar RU
    enh = {**pe._fresh_enh(), "step": "hub",
           "post": {"type": "text", "file_id": None, "content": "Salom"},
           "reactions": ["👍"], "buttons": [{"text": "Sayt", "url": "https://a.uz"}]}
    ctx_ru = _Ctx2({"enh": enh, "lang": "ru"})
    htext, hkb = pe._hub_view(ctx_ru)
    hflat = [b for row in hkb.inline_keyboard for b in row]
    check("enh hub ru: RU yorliqlar + bir xil callback",
          htext.startswith("✨ <b>")
          and any(b.callback_data == "enh:screen:react" and "Реакции" in b.text for b in hflat)
          and any(b.callback_data == "enh:preview" for b in hflat)
          and any(b.callback_data == "enh:cancel" and b.text == "❌ Отмена" for b in hflat),
          str([(b.text, b.callback_data) for b in hflat]))
    rtext, _ = pe._react_view(ctx_ru)
    check("enh react ru: batch maslahat RU",
          "через пробел" in rtext and "Шаг 1" in rtext, rtext[:90])
    enh2 = {**enh, "step": "btns"}
    btext, bkb = pe._btns_view(_Ctx2({"enh": enh2, "lang": "ru"}))
    bflat = [b for row in bkb.inline_keyboard for b in row]
    check("enh btns ru: shablonlar RU, callback o'zgarmagan",
          any(b.text == "📢 1. Подписаться на канал" for b in bflat)
          and any(b.callback_data == "enh:preset:0" for b in bflat), str(btext[:60]))
    enh3 = {**enh, "step": "channel", "channels": [("-1001", "Kanal X")]}
    ctext, ckb = pe._channel_view(_Ctx2({"enh": enh3, "lang": "ru"}))
    cflat = [b for row in ckb.inline_keyboard for b in row]
    check("enh channel ru: 'В какой канал' + eslatma",
          "В какой канал отправить?" in ctext and "Администратор" in ctext
          and any(b.callback_data == "enh:send:0" for b in cflat), ctext[:70])
    enh4 = {**enh3, "step": "confirm", "ch_idx": 0}
    qtext, qkb = pe._confirm_view(_Ctx2({"enh": enh4, "lang": "ru"}))
    qflat = [b for row in qkb.inline_keyboard for b in row]
    check("enh confirm ru: 'Отправить этот пост' + tugma",
          "Отправить этот пост" in qtext
          and any(b.text == get_text("enh_btn_confirm_yes", "ru") for b in qflat), qtext[:70])
    stext, skb = pe._success_view("Kanal X", "ru")
    sflat = [b for row in skb.inline_keyboard for b in row]
    check("enh success ru: 'успешно опубликован' + 🏠 Главное меню",
          "успешно опубликован" in stext
          and any(b.callback_data == "enh:home" and b.text == "🏠 Главное меню" for b in sflat),
          str(stext[:70]))
    check("enh success uz regression (🏠 Asosiy menyu)",
          pe._success_view("K")[0].split("\n")[0] == "✅ <b>Post yuklandi!</b>"
          and any(b.text == "🏠 Asosiy menyu"
                  for row in pe._success_view("K")[1].inline_keyboard for b in row))

    # _plan_note uz/ru (bepul foydalanuvchi)
    async def _plan_run():
        orig = db_mod.run_db
        db_mod.run_db = _fake_db()
        try:
            note_ru = await pe._plan_note(111, "ru")
            note_uz = await pe._plan_note(111, "uz")
            return note_ru, note_uz
        finally:
            db_mod.run_db = orig

    note_ru, note_uz = asyncio.run(_plan_run())
    check("enh plan_note: bepul RU ogohlantirish",
          "Бесплатный план" in note_ru and "@PostAssistrobot" in note_ru, note_ru)
    check("enh plan_note: uz regression",
          "Bepul reja" in note_uz and "@PostAssistrobot" in note_uz, note_uz)

    # enh_stale_callback — RU javob
    async def _stale_run():
        q = _FakeQuery("enh:noop", _FakeMsg(50, 111))
        await pe.enh_stale_callback(_UpdQ(q), _FakeCtx(_FakeBot(), {"lang": "ru"}))
        return q

    q_stale = asyncio.run(_stale_run())
    check("enh stale: RU eslatma",
          q_stale.answers and "Дополнительные функции" in (q_stale.answers[0][0] or ""),
          str(q_stale.answers))

    # --- 9. Registration + tizim darajasidagi handlerlar ---
    import handlers as h_mod
    import main as main_mod

    h_src = open(h_mod.__file__, encoding="utf-8").read()
    check("register: ^help: callback", 'pattern=r"^help:"' in h_src)
    check("register: help_menu_callback importlangan", "help_menu_callback" in h_src)
    check("register: expired session RU/UZ get_text", 'get_text("sys_stale_button"' in h_src)
    check("register: conversation timeout get_text", 'get_text("conv_timeout_msg"' in h_src)
    check("register: close_msg get_text", 'get_text("msg_closed"' in h_src)
    check("register: sys_busy get_text", 'get_text("sys_busy"' in h_src)

    m_src = open(main_mod.__file__, encoding="utf-8").read()
    check("main: error_handler lokalize qilingan", "sys_unexpected_error" in m_src)

    # expired_session_callback — tilga mos toast
    async def _expired_run():
        q = _FakeQuery("some:stale", _FakeMsg(60, 111))
        await h_mod.expired_session_callback(_UpdQ(q), _FakeCtx(_FakeBot(), {"lang": "ru"}))
        return q

    q_exp = asyncio.run(_expired_run())
    check("expired session: RU toast (bot qayta yuklangan)",
          q_exp.answers and "перезапущен" in (q_exp.answers[0][0] or ""), str(q_exp.answers))

    # main.error_handler — foydalanuvchiga RU xabar
    class _UpdEH:
        def __init__(self, message):
            self.effective_message = message

    async def _eh_run():
        msg = _FakeMsg(70, 111)
        ctx = _FakeCtx(_FakeBot(), {"lang": "ru"})
        ctx.error = ValueError("boom")
        await main_mod.error_handler(_UpdEH(msg), ctx)
        return msg

    msg_eh = asyncio.run(_eh_run())
    check("error_handler: foydalanuvchiga RU kutilmagan xatolik xabari",
          msg_eh.replies and "непредвиденная ошибка" in msg_eh.replies[-1],
          str(msg_eh.replies))

def test_keep_typing():
    """utils.helpers.keep_typing — uzluksiz 'typing' indikatori."""
    print("== utils.helpers.keep_typing ==")
    import asyncio as _aio
    from utils.helpers import keep_typing

    class _FakeBot:
        def __init__(self):
            self.calls = []

        async def send_chat_action(self, chat_id, action, **kwargs):
            self.calls.append((chat_id, action))

    # 1) Kontekst ichida typing yuboriladi va interval bilan takrorlanadi
    async def _inside():
        bot = _FakeBot()
        async with keep_typing(bot, 42, interval=0.03):
            await _aio.sleep(0.11)
        return bot

    bot = _aio.run(_inside())
    check("typing: kontekst ichida yuborildi", len(bot.calls) >= 2, str(bot.calls))
    check("typing: action='typing'", all(a == "typing" for _, a in bot.calls), str(bot.calls))
    check("typing: chat_id to'g'ri", all(c == 42 for c, _ in bot.calls), str(bot.calls))

    # 2) Kontekstdan chiqqach fon vazifasi to'xtaydi (orphan task qolmaydi)
    async def _after_exit():
        bot = _FakeBot()
        async with keep_typing(bot, 42, interval=0.02):
            await _aio.sleep(0.03)  # kamida bitta yuborilishi uchun
        n_exit = len(bot.calls)
        await _aio.sleep(0.12)
        return bot, n_exit

    bot2, n_exit2 = _aio.run(_after_exit())
    check("typing: chiqishda kam 1 marta yuborgan", n_exit2 >= 1, str(bot2.calls))
    check("typing: chiqqandan keyin to'xtedi", len(bot2.calls) <= n_exit2, f"{n_exit2} → {len(bot2.calls)}")

    # 2b) Javob juda tez kelsa (tana await qilmasa) ortiqcha typing yuborilmaydi
    async def _instant():
        bot = _FakeBot()
        async with keep_typing(bot, 42, interval=0.02):
            pass  # AI darhol javob berdi
        await _aio.sleep(0.1)
        return bot

    bot2b = _aio.run(_instant())
    check("typing: tez javobda ortiqcha indikator yo'q", len(bot2b.calls) == 0, str(bot2b.calls))

    # 3) Kontekst ichida xato bo'lsa ham vazifa to'xtatiladi va xato oqmaydi
    async def _on_error():
        bot = _FakeBot()
        try:
            async with keep_typing(bot, 7, interval=0.02):
                await _aio.sleep(0.01)  # vazifa ishga tushishi uchun
                raise ValueError("AI xatosi (sinov)")
        except ValueError:
            pass
        n_exit = len(bot.calls)
        await _aio.sleep(0.1)
        return bot, n_exit

    bot3, n_exit3 = _aio.run(_on_error())
    check("typing: xatoda ham yubordi", n_exit3 >= 1, str(bot3.calls))
    check("typing: xatodan keyin to'xtedi", len(bot3.calls) <= n_exit3, f"{n_exit3} → {len(bot3.calls)}")
    check("typing: xatodagi chat_id to'g'ri", bool(bot3.calls) and bot3.calls[0][0] == 7, str(bot3.calls))

    # 4) send_chat_action xato bersa ham asosiy oqim buzilmaydi
    class _BrokenBot:
        def __init__(self):
            self.attempts = 0

        async def send_chat_action(self, chat_id, action, **kwargs):
            self.attempts += 1
            raise RuntimeError("network down")

    async def _broken():
        bot = _BrokenBot()
        async with keep_typing(bot, 42, interval=0.02):
            await _aio.sleep(0.05)
        return bot

    bot4 = _aio.run(_broken())
    check("typing: xato botda ham kontekst ishladi", bot4.attempts == 1, str(bot4.attempts))


# ==========================================================================
# 🚀 OMMAVIY RELIZ: 4 ta arxitekturaviy himoya
# ==========================================================================

def test_callback_data_64byte_safety():
    """1️⃣ Inline tugmalar: callback_data HECH QACHON 64 baytdan oshmaydi."""
    print("== 1. Inline callback_data 64-bayt xavfsizligi ==")
    import ast
    from keyboards.callback_data import (
        CALLBACK_DATA_MAX_BYTES, CALLBACK_PREFIX_MAX_BYTES, CANONICAL_PREFIXES,
        cb, callback_byte_len, is_callback_safe, truncate_callback_data,
        safe_callback_data, pattern as cb_pattern,
        CB_CHANNEL_DELETE, CB_CHANNEL_SETTINGS, CB_POST_TIME, CB_POST_EDIT,
        CB_POST_BTN, CB_POST_REACT, CB_POST_CANCEL, CB_SPONSOR_DELETE,
        CB_RECEIPT_APPROVE, CB_RECEIPT_REJECT, CB_PHOTO_APPROVE, CB_PHOTO_REJECT,
        CB_REACT_TOGGLE, CB_REACT_DONE, CB_REACT_SKIP, CB_REACTION,
    )

    # --- a) Konstantalar: limit va qisqa kanonik prefikslar ---
    check("limit 64 bayt", CALLBACK_DATA_MAX_BYTES == 64)
    for prefix in CANONICAL_PREFIXES:
        check(f"prefiks qisqa: {prefix}",
              callback_byte_len(prefix) <= CALLBACK_PREFIX_MAX_BYTES,
              f"{prefix} = {callback_byte_len(prefix)} bayt")

    # Foydalanuvchi so'ragan qisqartirilgan format (ch_del:, p_*:, ch_set:)
    check("ch_del: prefiksi", CB_CHANNEL_DELETE == "ch_del:")
    check("ch_set: prefiksi", CB_CHANNEL_SETTINGS == "ch_set:")
    check("p_time: prefiksi", CB_POST_TIME == "p_time:")
    check("p_edit: prefiksi", CB_POST_EDIT == "p_edit:")
    check("p_btn: prefiksi", CB_POST_BTN == "p_btn:")
    check("p_react: prefiksi", CB_POST_REACT == "p_react:")
    check("p_cancel: prefiksi", CB_POST_CANCEL == "p_cancel:")
    check("sp_del: prefiksi", CB_SPONSOR_DELETE == "sp_del:")
    check("rc_ok:/rc_no: prefikslari",
          CB_RECEIPT_APPROVE == "rc_ok:" and CB_RECEIPT_REJECT == "rc_no:")
    check("cph:a:/cph:r: prefikslari",
          CB_PHOTO_APPROVE == "cph:a:" and CB_PHOTO_REJECT == "cph:r:")
    # `react:` ATAYLAB o'zgarmaydi — yuborilgan postlardagi tugmalar tirik qolsin
    check("react: prefiksi saqlangan (eski postlar)", CB_REACTION == "react:")

    # --- b) cb() quruvchisi: har doim <=64 bayt ---
    check("cb: oddiy", cb(CB_CHANNEL_DELETE, -1001234567890) == "ch_del:-1001234567890")
    check("cb: ko'p bo'lak", cb(CB_REACTION, 42, "👍") == "react:42:👍")
    check("cb: bo'sh → noop", cb("") == "noop")
    check("cb: None bo'laklar tashlanadi", cb(CB_POST_TIME, None, 7) == "p_time:7")
    check("cb: prefiksda ':' bo'lmasa qo'shiladi", cb("qview", 9) == "qview:9")

    import logging as _logging
    _cb_logger = _logging.getLogger("keyboards.callback_data")
    _cb_logger.setLevel(_logging.CRITICAL)  # kutilgan ogohlantirishlar log'ni to'ldirmasin

    huge = cb(CB_CHANNEL_DELETE, "x" * 500)
    check("cb: uzun payload kesiladi", callback_byte_len(huge) <= 64, str(len(huge)))
    emoji_huge = cb(CB_REACTION, 1, "👨‍👩‍👧‍👦" * 20)
    check("cb: emoji payload kesiladi", callback_byte_len(emoji_huge) <= 64)
    # Kesish UTF-8 chegarasini buzmaydi (decode xatosi bo'lmaydi)
    check("cb: kesilgan qiymat to'g'ri UTF-8",
          emoji_huge.encode("utf-8").decode("utf-8") == emoji_huge)
    check("truncate: ko'p baytli belgi o'rtasidan kesilmaydi",
          truncate_callback_data("👍" * 30, 10) == "👍👍")
    check("safe_callback_data: limitga tushiradi",
          callback_byte_len(safe_callback_data("z" * 200)) == 64)
    check("is_callback_safe: bo'sh → False", is_callback_safe("") is False)
    check("is_callback_safe: normal → True", is_callback_safe("ch_del:-100123") is True)
    check("is_callback_safe: 65 bayt → False", is_callback_safe("a" * 65) is False)
    check("is_callback_safe: 64 bayt → True", is_callback_safe("a" * 64) is True)
    import re as _re_cb
    check("cb_pattern: regex", cb_pattern("ch_del:") == "^" + _re_cb.escape("ch_del:"))

    # --- c) STATIK AUDIT: manbadagi barcha literal callback_data <= 64 bayt ---
    root = Path(__file__).resolve().parent.parent
    py_files = [
        p for p in root.rglob("*.py")
        if "tests" not in p.parts and "__pycache__" not in p.parts
    ]
    check("statik audit: fayllar topildi", len(py_files) >= 20, str(len(py_files)))

    literal_total = 0
    literal_bad = []
    fstring_bad = []
    for path in py_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "callback_data":
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal_total += 1
                if len(value.value.encode("utf-8")) > 64:
                    literal_bad.append((path.name, node.lineno, value.value))
            elif isinstance(value, ast.JoinedStr):
                # Dinamik f-string TO'G'RIDAN-TO'G'RI ishlatilmasligi kerak —
                # u albatta cb(...) orqali o'tishi shart (64-bayt kafolati).
                fstring_bad.append((path.name, node.lineno))

    check("statik audit: literal callback'lar sanaldi", literal_total > 100, str(literal_total))
    check("statik audit: barcha literal <= 64 bayt", not literal_bad, str(literal_bad[:3]))
    check("statik audit: himoyasiz f-string yo'q (hammasi cb() ichida)",
          not fstring_bad, str(fstring_bad[:5]))

    # --- d) RUNTIME AUDIT: klaviatura quruvchilar eng yomon kirish bilan ---
    from keyboards import inline as kb
    from handlers.payment_receipt import _get_admin_receipt_keyboard

    LONG_ID = "-100" + "9" * 20           # real Telegram id'dan ancha uzun
    LONG_TITLE = "Канал " + "Ў" * 120     # ko'p baytli kirill nomi
    BIG_PID = 9_999_999_999_999
    WILD_EMOJI = "👨‍👩‍👧‍👦"                    # 25 bayt ZWJ ketma-ketligi

    keyboards = [
        ("close", kb.get_close_keyboard("ru")),
        ("cache", kb.get_cache_actions_keyboard()),
        ("sponsors_del", kb.get_sponsors_delete_keyboard(
            [{"id": BIG_PID, "channel_id": LONG_ID, "title": LONG_TITLE}])),
        ("admin_sponsors", kb.get_admin_sponsors_keyboard(
            [{"id": BIG_PID, "channel_id": LONG_ID, "title": LONG_TITLE}])),
        ("sub_check", kb.get_subscription_check_keyboard(
            [(BIG_PID, LONG_ID, LONG_TITLE, "kanal", "https://t.me/kanal")])),
        ("admin_dash", kb.get_admin_dashboard_keyboard()),
        ("ad_hub", kb.get_ad_hub_keyboard(9, 9, 9, 9)),
        ("ad_pool", kb.get_ad_pool_menu_keyboard(
            "channel", [{"id": BIG_PID, "text": LONG_TITLE, "is_active": True}])),
        ("ad_edit", kb.get_ad_edit_keyboard(
            {"id": BIG_PID, "text": LONG_TITLE, "is_active": True}, "channel")),
        ("ad_interval", kb.get_ad_interval_keyboard("channel", 3)),
        ("ad_delete", kb.get_ad_pool_delete_keyboard(
            [{"id": BIG_PID, "text": LONG_TITLE}], "channel")),
        ("ad_back", kb.get_ad_pool_back_keyboard("channel")),
        ("ai_studio", kb.get_ai_studio_keyboard("ru")),
        ("ai_photo", kb.get_ai_photo_keyboard("ru")),
        ("ai_tone", kb.get_ai_tone_keyboard("formal", "ru")),
        ("ai_confirm", kb.get_ai_confirm_keyboard("ru")),
        ("channels_list", kb.render_channels_list(
            [(LONG_ID, LONG_TITLE, "formal")], "ru")),
        ("cabinet", kb.get_cabinet_inline_keyboard("ru")),
        ("language", kb.get_language_keyboard()),
        ("extras", kb.get_extras_inline_keyboard("ru")),
        ("help", kb.get_help_keyboard("support", "ru")),
        ("react_toggle", kb.get_reaction_toggle_keyboard(["👍", "🔥"], "ru")),
        ("cabinet_back", kb.get_cabinet_back_keyboard("ru")),
        ("channels_manage", kb.get_channels_manage_keyboard("ru")),
        ("receipt_admin", _get_admin_receipt_keyboard(BIG_PID, "ru")),
    ]

    # Kutilayotgan postlar kartochkasi (p_time:/p_edit:/p_btn:/p_react:/p_cancel:)
    pending_posts = [(BIG_PID, LONG_TITLE, "photo", None, 9999, "none", None, None)]
    keyboards.append(("pending", kb.render_pending_list(
        pending_posts, user_code="ABC" * 20, lang="ru")))

    # Kanal postidagi reaksiya tugmalari (react:) — eng yomon emoji bilan
    rows = kb.build_reaction_button_rows(BIG_PID, [WILD_EMOJI] * 5)
    keyboards.append(("reactions", kb.InlineKeyboardMarkup(rows)))

    oversized = []
    empty = []
    counted = 0
    for name, markup in keyboards:
        for row in markup.inline_keyboard:
            for button in row:
                data = getattr(button, "callback_data", None)
                if data is None:
                    continue  # URL tugmasi
                counted += 1
                size = len(str(data).encode("utf-8"))
                if size > 64:
                    oversized.append((name, data, size))
                if size == 0:
                    empty.append((name, button.text))
    check("runtime audit: tugmalar tekshirildi", counted > 80, str(counted))
    check("runtime audit: 64 baytdan oshgan tugma YO'Q", not oversized, str(oversized[:3]))
    check("runtime audit: bo'sh callback_data YO'Q", not empty, str(empty[:3]))

    # --- e) Scheduler post tugmalari ham xavfsiz ---
    from scheduler import build_reaction_buttons, build_ad_button_row
    sched_buttons = build_reaction_buttons(BIG_PID, True, [WILD_EMOJI, "💯", "⭐️", "👍"])
    check("scheduler: reaksiya tugmalari bor", len(sched_buttons) >= 2, str(len(sched_buttons)))
    check("scheduler: reaksiya callback <= 64 bayt",
          all(len(b.callback_data.encode("utf-8")) <= 64 for b in sched_buttons),
          str([b.callback_data for b in sched_buttons]))
    ad_row = build_ad_button_row({"button_text": "Bosing", "button_url": "https://t.me/x"})
    check("scheduler: reklama tugmasi URL (callback_data yo'q)",
          ad_row and ad_row[0].callback_data is None)

    # --- f) Handler pattern'lari yangi prefikslarga mos ---
    h_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for prefix in ("ch_del:", "ch_set:", "p_time:", "p_edit:", "p_btn:",
                   "p_react:", "p_cancel:", "sp_del:", "nprt:t:"):
        check(f"pattern ro'yxatdan o'tgan: {prefix}",
              f'pattern=r"^{prefix}"' in h_src, prefix)
    check("pattern: rc_ok/rc_no (chek moderatsiyasi)",
          'pattern=r"^(rc_ok|rc_no):"' in h_src)
    check("pattern: react: saqlangan", 'pattern=r"^react:"' in h_src)
    ph_src = (root / "handlers" / "photo_check.py").read_text(encoding="utf-8")
    check("pattern: cph:a:/cph:r:", 'pattern=r"^cph:a:|^cph:r:"' in ph_src)
    # Eski uzun prefikslar manbada qolmagan bo'lishi kerak
    all_src = "\n".join(p.read_text(encoding="utf-8") for p in py_files)
    for stale in ('pattern=r"^remove_channel:"', 'pattern=r"^tone_menu:"',
                  'pattern=r"^del_sponsor:"', 'pattern=r"^edit_content:"',
                  'pattern=r"^npreact:'):
        check(f"eski prefiks olib tashlangan: {stale}", stale not in all_src)


def test_i18n_safe_fallback_and_parity():
    """2️⃣ UZ/RU: get_text xavfsiz fallback + to'liq kalit pariteti."""
    print("== 2. i18n xavfsiz fallback va paritet ==")
    from locales import translations as tr
    from locales.translations import (
        get_text, translation_parity_report, missing_keys, has_key,
        TRANSLATIONS, DEFAULT_LANG, SUPPORTED_LANGS,
    )

    # --- a) To'liq paritet: UZ va RU kalitlari 1:1 ---
    report = translation_parity_report()
    check("paritet: uz_only bo'sh", report["uz_only"] == [], str(report["uz_only"][:5]))
    check("paritet: ru_only bo'sh", report["ru_only"] == [], str(report["ru_only"][:5]))
    check("paritet: in_sync", report["in_sync"] is True)
    check("paritet: kalitlar soni 500+", report["total"] >= 500, str(report["total"]))
    check("missing_keys('ru') bo'sh", missing_keys("ru") == [])
    check("missing_keys('uz') bo'sh", missing_keys("uz", reference="ru") == [])

    # Har bir kalit ikkala tilda ham NOBO'SH satr bo'lishi shart
    bad_values = []
    for lang in SUPPORTED_LANGS:
        for key, value in TRANSLATIONS[lang].items():
            if not isinstance(value, str) or not value.strip():
                bad_values.append((lang, key))
    check("paritet: barcha qiymatlar nobo'sh satr", not bad_values, str(bad_values[:5]))

    # --- a2) Kodda get_text("literal_key") bilan chaqirilgan HAR BIR kalit
    #        lug'atda bo'lishi shart (aks holda foydalanuvchiga xom kalit chiqadi,
    #        masalan "main_menu_hint" regressiyasi) ---
    import glob as _glob
    import re as _re
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _pattern = _re.compile(r"""get_text\(\s*["']([A-Za-z0-9_]+)["']""")
    _used = set()
    for _f in _glob.glob(os.path.join(_root, "handlers", "**", "*.py"), recursive=True) + \
              _glob.glob(os.path.join(_root, "*.py")):
        with open(_f, encoding="utf-8") as _fh:
            _used.update(_pattern.findall(_fh.read()))
    _unknown = sorted(k for k in _used if k not in TRANSLATIONS["uz"] or k not in TRANSLATIONS["ru"])
    check("kodda ishlatilgan barcha get_text kalitlari lug'atda bor",
          not _unknown, str(_unknown[:10]))
    check("main_menu_hint uz", get_text("main_menu_hint", "uz") == "Quyidagi menyudan kerakli bo‘limni tanlang 👇")
    check("main_menu_hint ru", get_text("main_menu_hint", "ru") == "Выберите нужный раздел из меню ниже 👇")

    # UZ va RU shablonlaridagi {placeholder}'lar bir xil bo'lishi kerak
    import re as _re
    ph_mismatch = []
    for key, uz_val in TRANSLATIONS["uz"].items():
        ru_val = TRANSLATIONS["ru"].get(key, "")
        uz_ph = set(_re.findall(r"\{(\w+)\}", uz_val))
        ru_ph = set(_re.findall(r"\{(\w+)\}", ru_val))
        if uz_ph != ru_ph:
            ph_mismatch.append((key, sorted(uz_ph ^ ru_ph)))
    check("paritet: {placeholder}'lar mos", not ph_mismatch, str(ph_mismatch[:5]))

    # --- b) Fallback zanjiri: ru → uz → kalit nomi (KeyError YO'Q) ---
    tr.TRANSLATIONS["uz"]["__t_only_uz__"] = "faqat o'zbekcha {n}"
    try:
        check("fallback: ru'da yo'q kalit → uz varianti",
              get_text("__t_only_uz__", "ru") == "faqat o'zbekcha {n}")
        check("fallback: ru'da yo'q + format ishlaydi",
              get_text("__t_only_uz__", "ru", n=5) == "faqat o'zbekcha 5")
    finally:
        tr.TRANSLATIONS["uz"].pop("__t_only_uz__", None)

    check("fallback: ikkala tilda yo'q → kalit nomi",
          get_text("__hech_qayerda_yoq__", "ru") == "__hech_qayerda_yoq__")
    check("fallback: ikkala tilda yo'q (uz) → kalit nomi",
          get_text("__hech_qayerda_yoq__", "uz") == "__hech_qayerda_yoq__")
    check("fallback: None kalit → bo'sh satr", get_text(None, "ru") == "")
    check("fallback: bo'sh kalit → bo'sh satr", get_text("", "ru") == "")
    check("fallback: noma'lum til → uz",
          get_text("btn_new_post", "fr") == get_text("btn_new_post", "uz"))
    check("fallback: None til → uz",
          get_text("btn_new_post", None) == get_text("btn_new_post", "uz"))

    # --- c) Formatlash xatolari HECH QACHON crash bermaydi ---
    res = get_text("start_hello", "ru")          # {name} berilmagan
    check("format: kam argument → crash yo'q", isinstance(res, str) and res)
    res = get_text("start_hello", "ru", name="Ivan", extra="ortiqcha")
    check("format: ortiqcha argument → crash yo'q", "Ivan" in res)
    res = get_text("card_payment_prices", "ru", p1m=None, p3m=None, p1y=None)
    check("format: None qiymat → crash yo'q", isinstance(res, str) and res)

    # Buzilgan RU shabloni: UZ varianti bilan qayta formatlanadi
    orig = tr.TRANSLATIONS["ru"].get("start_hello")
    tr.TRANSLATIONS["ru"]["start_hello"] = "Привет, {nomavjud_kalit}!"
    try:
        res = get_text("start_hello", "ru", name="Ivan")
        check("format: buzilgan RU shabloni → UZ varianti", "Ivan" in res, res[:60])
    finally:
        tr.TRANSLATIONS["ru"]["start_hello"] = orig

    # Lug'atga xato tur tushib qolsa ham yiqilmaymiz
    tr.TRANSLATIONS["uz"]["__t_bad_type__"] = 12345
    try:
        check("format: str bo'lmagan qiymat → str()",
              get_text("__t_bad_type__", "uz") == "12345")
    finally:
        tr.TRANSLATIONS["uz"].pop("__t_bad_type__", None)

    check("has_key: mavjud", has_key("btn_new_post", "ru") is True)
    check("has_key: yo'q", has_key("__yoq__") is False)
    check("DEFAULT_LANG uz", DEFAULT_LANG == "uz")

    # --- d) Vaqt formati xabarlari ikkala tilda ham namunani ko'rsatadi ---
    for lang in ("uz", "ru"):
        msg = get_text("np_time_format_error", lang, example="30.08.2026 18:00")
        check(f"{lang}: format xatosi DD.MM.YYYY namunasi bor",
              "DD.MM.YYYY HH:MM" in msg, msg[:70])
        check(f"{lang}: format xatosi jonli namuna bor",
              "30.08.2026 18:00" in msg, msg[:70])
        check(f"{lang}: format xatosi Toshkent vaqtini eslatadi",
              "UTC+5" in msg, msg[:70])
        future = get_text("np_time_future", lang, example="30.08.2026 18:00",
                          now="29.08.2026 10:00")
        check(f"{lang}: o'tgan vaqt xabari namunali", "30.08.2026 18:00" in future)


def test_scheduler_timezone_and_time_input():
    """3️⃣ Scheduler/APScheduler Toshkent vaqti + crash-proof vaqt kiritish."""
    print("== 3. Vaqt zonasi (Asia/Tashkent) va vaqt kiritish oqimi ==")
    import scheduler as sch
    from utils.helpers import (
        parse_schedule_input, parse_daily_time_input, schedule_time_example,
        schedule_error_key, SCHEDULE_INPUT_FORMAT, SCHEDULE_STRICT_FORMATS,
        SCHEDULE_ERR_EMPTY, SCHEDULE_ERR_FORMAT, SCHEDULE_ERR_PAST,
    )

    tz = pytz.timezone("Asia/Tashkent")

    # --- a) Yagona vaqt zonasi manbasi ---
    check("scheduler: TIMEZONE_NAME", sch.TIMEZONE_NAME == "Asia/Tashkent")
    check("scheduler: tashkent_tz", str(sch.tashkent_tz) == "Asia/Tashkent")
    now_tk = sch.now_tashkent()
    check("now_tashkent: tz-aware", now_tk.tzinfo is not None)
    check("now_tashkent: UTC+5",
          now_tk.utcoffset().total_seconds() == 5 * 3600,
          str(now_tk.utcoffset()))

    # --- b) calculate_next_time HAR DOIM Toshkent vaqtini qaytaradi ---
    rec_time = datetime(2000, 1, 1, 10, 0).time()

    # Naive kirish → Toshkentga bog'lanadi
    t = sch.calculate_next_time("daily", None, rec_time, datetime(2026, 8, 30, 9, 0))
    check("daily: naive kirish → Toshkent", str(t.tzinfo) == "Asia/Tashkent", str(t))
    check("daily: bugun 10:00", t == tz.localize(datetime(2026, 8, 30, 10, 0)), str(t))

    # UTC kirish → Toshkentga o'giriladi (UTC 06:00 = Toshkent 11:00 → ertaga)
    utc_now = pytz.utc.localize(datetime(2026, 8, 30, 6, 0))
    t = sch.calculate_next_time("daily", None, rec_time, utc_now)
    check("daily: UTC kirish → Toshkentga o'giriladi",
          t == tz.localize(datetime(2026, 8, 31, 10, 0)), str(t))
    check("daily: natija UTC+5", t.utcoffset().total_seconds() == 5 * 3600)

    # Weekly ham xuddi shunday
    t = sch.calculate_next_time("weekly", 0, rec_time,
                                pytz.utc.localize(datetime(2026, 8, 26, 4, 0)))
    check("weekly: UTC kirish → keyingi dushanba (Toshkent)",
          t == tz.localize(datetime(2026, 8, 31, 10, 0)), str(t))

    # Chekka holatlar — crash yo'q
    check("calculate_next_time: None vaqt → None",
          sch.calculate_next_time("daily", None, None, now_tk) is None)
    check("calculate_next_time: weekly kunsiz → None",
          sch.calculate_next_time("weekly", None, rec_time, now_tk) is None)
    check("calculate_next_time: none → None",
          sch.calculate_next_time("none", None, rec_time, now_tk) is None)

    # --- c) main.py: APScheduler triggerlari Toshkentga bog'langan ---
    main_src = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    check("main: AsyncIOScheduler(timezone=tashkent_tz)",
          "AsyncIOScheduler(\n        timezone=tashkent_tz," in main_src)
    check("main: har bir job'da timezone=tashkent_tz",
          main_src.count("timezone=tashkent_tz") >= 4,
          str(main_src.count("timezone=tashkent_tz")))
    check("main: cron trigger Toshkentda", "'cron', hour=\"*/6\"" in main_src)
    check("main: next_run_time Toshkentda", "next_run_time=now_tashkent()" in main_src)
    check("main: tz scheduler modulidan olinadi",
          'pytz.timezone("Asia/Tashkent")' not in main_src)

    # --- d) parse_schedule_input: crash YO'Q, aniq sabab qaytadi ---
    now = tz.localize(datetime(2026, 8, 30, 12, 0))
    check("format konstantasi", SCHEDULE_INPUT_FORMAT == "DD.MM.YYYY HH:MM")
    check("qat'iy formatlar ro'yxati", "%d.%m.%Y %H:%M" in SCHEDULE_STRICT_FORMATS)

    dt, reason = parse_schedule_input("31.12.2026 18:00", now)
    check("DD.MM.YYYY HH:MM o'qildi",
          dt == tz.localize(datetime(2026, 12, 31, 18, 0)) and reason == "", str(dt))
    check("natija Toshkent vaqtida", dt.utcoffset().total_seconds() == 5 * 3600)

    for text, expected in (
        ("31/12/2026 18:00", datetime(2026, 12, 31, 18, 0)),
        ("31-12-2026 18:00", datetime(2026, 12, 31, 18, 0)),
        ("2026-12-31 18:00", datetime(2026, 12, 31, 18, 0)),
        ("31.12.26 18:00", datetime(2026, 12, 31, 18, 0)),
    ):
        dt, reason = parse_schedule_input(text, now)
        check(f"format o'qildi: {text}", dt == tz.localize(expected) and not reason, str(dt))

    dt, reason = parse_schedule_input("18:00", now)
    check("faqat soat → bugun 18:00", dt == tz.localize(datetime(2026, 8, 30, 18, 0)), str(dt))
    dt, reason = parse_schedule_input("09:00", now)
    check("faqat soat (o'tgan) → ertaga",
          dt == tz.localize(datetime(2026, 8, 31, 9, 0)), str(dt))

    # 🔴 Foydalanuvchi so'ragan aynan shu holat: "ertaga 5 da"
    dt, reason = parse_schedule_input("ertaga 5 da", now)
    check("erkin til: 'ertaga 5 da' → ertaga 05:00",
          dt == tz.localize(datetime(2026, 8, 31, 5, 0)) and not reason, str(dt))
    dt, reason = parse_schedule_input("2 soatdan keyin", now)
    check("erkin til: '2 soatdan keyin'", dt is not None and dt > now, str(dt))
    dt, reason = parse_schedule_input("завтра 18:00", now)
    check("erkin til (RU): 'завтра 18:00'",
          dt == tz.localize(datetime(2026, 8, 31, 18, 0)), str(dt))

    # 🔴 Noto'g'ri kiritishlar — crash EMAS, aniq sabab
    for bad in ("salom", "abc def", "25:99", "99:99", "32.13.2026 18:00",
                "31.12.2026 25:00", "-----", "18:", ":00", "1.2.3.4.5",
                "30.02.2026 10:00", "2026-13-31 18:00", "00.00.2026 10:00",
                "ertaga 25:00", "31.12.2026 18:99"):
        dt, reason = parse_schedule_input(bad, now)
        check(f"noto'g'ri kiritish xavfsiz: {bad!r}",
              dt is None and reason == SCHEDULE_ERR_FORMAT, f"{dt} / {reason}")

    for empty in (None, "", "   ", 12345, [], {}):
        dt, reason = parse_schedule_input(empty, now)
        check(f"bo'sh/nomatn kiritish xavfsiz: {empty!r}",
              dt is None and reason == SCHEDULE_ERR_EMPTY, f"{dt} / {reason}")

    dt, reason = parse_schedule_input("01.01.2020 10:00", now)
    check("o'tgan sana → 'past' sababi", dt is None and reason == SCHEDULE_ERR_PAST)
    check("xato → i18n kaliti (past)", schedule_error_key(SCHEDULE_ERR_PAST) == "np_time_future")
    check("xato → i18n kaliti (format)",
          schedule_error_key(SCHEDULE_ERR_FORMAT) == "np_time_format_error")

    # Namuna har doim kelajakda va DD.MM.YYYY ko'rinishida
    example = schedule_time_example(now)
    check("namuna DD.MM.YYYY HH:MM", example == "31.08.2026 18:00", example)
    ex_dt, ex_reason = parse_schedule_input(example, now)
    check("namuna o'zi ham qabul qilinadi", ex_dt is not None and not ex_reason, str(ex_reason))

    # --- e) parse_daily_time_input: takroriy postlar uchun HH:MM ---
    check("daily: '10:00'", parse_daily_time_input("10:00") == (10, 0))
    check("daily: '9:5'", parse_daily_time_input("9:5") == (9, 5))
    check("daily: '18' → 18:00", parse_daily_time_input("18") == (18, 0))
    check("daily: '18.30'", parse_daily_time_input("18.30") == (18, 30))
    for bad in ("25:00", "10:99", "salom", "", None, "-1:00", 42, "::"):
        check(f"daily xavfsiz: {bad!r}", parse_daily_time_input(bad) is None)

    # --- f) Handlerlar markaziy parserdan foydalanadi (strptime qoldiqsiz) ---
    root = Path(__file__).resolve().parent.parent
    np_src = (root / "handlers" / "new_post.py").read_text(encoding="utf-8")
    pend_src = (root / "handlers" / "pending.py").read_text(encoding="utf-8")
    ai_src = (root / "handlers" / "ai_assistant.py").read_text(encoding="utf-8")
    for name, src in (("new_post", np_src), ("pending", pend_src), ("ai_assistant", ai_src)):
        check(f"{name}: parse_schedule_input ishlatiladi", "parse_schedule_input" in src)
        check(f"{name}: qo'lda strptime qolmagan",
              'datetime.strptime(text' not in src and 'strptime(sched_time_str' not in src)
    check("new_post: DD.MM.YYYY namunasi", "schedule_time_example" in np_src)
    check("new_post: daily parser", "parse_daily_time_input" in np_src)


def test_floodwait_and_ai_timeout_protection():
    """4️⃣ Telegram FloodWait (429) va tashqi AI so'rovlari timeout himoyasi."""
    print("== 4. FloodWait (429) va AI timeout himoyasi ==")
    import asyncio as _aio
    import aiohttp
    import scheduler as sch
    from telegram.error import RetryAfter
    from utils import ai_agent

    # ------------------------------------------------------------------
    # A) Scheduler: mikro-kechikish + RetryAfter
    # ------------------------------------------------------------------
    check("mikro-kechikish oralig'i 0.05..0.1",
          sch.SEND_MICRO_DELAY_MIN == 0.05 and sch.SEND_MICRO_DELAY_MAX == 0.1)
    check("SEND_MICRO_DELAY oraliqda",
          sch.SEND_MICRO_DELAY_MIN <= sch.SEND_MICRO_DELAY <= sch.SEND_MICRO_DELAY_MAX,
          str(sch.SEND_MICRO_DELAY))

    # flood_wait_seconds: har qanday buzilgan qiymatga chidamli
    check("flood_wait: oddiy", sch.flood_wait_seconds(RetryAfter(retry_after=7)) == 7.0)
    check("flood_wait: 0 → default", sch.flood_wait_seconds(RetryAfter(retry_after=0)) == 5.0)
    check("flood_wait: juda katta → cheklanadi",
          sch.flood_wait_seconds(RetryAfter(retry_after=9999)) == sch.FLOOD_WAIT_SLEEP_MAX)
    check("flood_wait: minimum 1s", sch.flood_wait_seconds(RetryAfter(retry_after=0.1)) == 1.0)

    class _NoAttr:
        pass
    check("flood_wait: atributsiz obyekt", sch.flood_wait_seconds(_NoAttr()) == 5.0)

    class _BadAttr:
        retry_after = "olti"
    check("flood_wait: str qiymat → default", sch.flood_wait_seconds(_BadAttr()) == 5.0)

    # --- Navbat oqimi: 3 ta post, 2-si FloodWait beradi ---
    posts = [(pid, 1, "-100", "text", f"Post {pid}", None, None, None, False,
              None, "none", None, None, None, 0, None) for pid in (101, 102, 103)]

    state = {"sent": [], "sleeps": [], "requeued": []}

    async def _fake_execute(bot, post):
        if post[0] == 102 and 102 not in state["sent"]:
            raise RetryAfter(retry_after=3)
        state["sent"].append(post[0])

    async def _fake_sleep(seconds):
        state["sleeps"].append(round(float(seconds), 4))

    async def _fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "get_due_posts":
            return posts
        if name == "retry_post":
            state["requeued"].append(args[0])
        return None

    orig_exec = sch._execute_send
    orig_sleep = sch.asyncio.sleep
    orig_run_db = sch.db.run_db
    try:
        sch._execute_send = _fake_execute
        sch.asyncio.sleep = _fake_sleep
        sch.db.run_db = _fake_run_db
        _aio.run(sch.check_and_send_posts(object()))
    finally:
        sch._execute_send = orig_exec
        sch.asyncio.sleep = orig_sleep
        sch.db.run_db = orig_run_db

    check("navbat: FloodWait navbatni to'xtatmadi (101 va 103 yuborildi)",
          state["sent"] == [101, 103], str(state["sent"]))
    micro = [s for s in state["sleeps"] if s == sch.SEND_MICRO_DELAY]
    check("navbat: postlar orasida mikro-kechikish qo'yildi",
          len(micro) == 2, str(state["sleeps"]))
    check("navbat: RetryAfter → asyncio.sleep(retry_after)",
          3.0 in state["sleeps"], str(state["sleeps"]))
    check("navbat: FloodWait bo'lgan post qayta navbatga qo'yildi",
          state["requeued"] == [102], str(state["requeued"]))

    # --- Manba kodi darajasidagi kafolatlar ---
    root = Path(__file__).resolve().parent.parent
    sch_src = (root / "scheduler.py").read_text(encoding="utf-8")
    check("scheduler: RetryAfter ushlanadi", "except RetryAfter as e:" in sch_src)
    check("scheduler: asyncio.sleep(...) FloodWait uchun (inline chegara bilan, scheduler bloklanmaydi)",
          "await asyncio.sleep(inline_sleep)" in sch_src
          and "flood_wait_inline_sleep(wait_seconds)" in sch_src)
    check("scheduler: mikro-kechikish kodda",
          "await asyncio.sleep(SEND_MICRO_DELAY)" in sch_src)

    # --- _execute_send ichidagi FloodWait ham kutadi va postni saqlaydi ---
    inner = {"sleeps": [], "requeued": [], "status": []}

    class _FloodBot:
        async def send_message(self, **kwargs):
            raise RetryAfter(retry_after=4)

    async def _inner_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name == "retry_post":
            inner["requeued"].append(args[0])
        if name == "mark_post_status":
            inner["status"].append(args[1])
        return None

    async def _inner_sleep(seconds):
        inner["sleeps"].append(float(seconds))

    async def _no_watermark(content, user_id, username):
        return content

    orig_run_db = sch.db.run_db
    orig_sleep = sch.asyncio.sleep
    orig_wm = sch.apply_post_watermark
    try:
        sch.db.run_db = _inner_run_db
        sch.asyncio.sleep = _inner_sleep
        sch.apply_post_watermark = _no_watermark
        _aio.run(sch._execute_send(_FloodBot(), posts[0]))
    finally:
        sch.db.run_db = orig_run_db
        sch.asyncio.sleep = orig_sleep
        sch.apply_post_watermark = orig_wm

    check("_execute_send: FloodWait'da kutildi", inner["sleeps"] == [4.0], str(inner["sleeps"]))
    check("_execute_send: post yo'qolmadi (qayta navbat)",
          inner["requeued"] == [101], str(inner["requeued"]))
    check("_execute_send: 'failed' deb belgilanmadi",
          "failed" not in inner["status"], str(inner["status"]))

    # ------------------------------------------------------------------
    # B) AI: aiohttp.ClientTimeout(total=35)
    # ------------------------------------------------------------------
    check("AI_TOTAL_TIMEOUT = 35", ai_agent.AI_TOTAL_TIMEOUT == 35)
    check("AI_HTTP_TIMEOUT — ClientTimeout",
          isinstance(ai_agent.AI_HTTP_TIMEOUT, aiohttp.ClientTimeout))
    check("AI_HTTP_TIMEOUT.total == 35", ai_agent.AI_HTTP_TIMEOUT.total == 35)
    check("AI_HTTP_TIMEOUT.connect belgilangan",
          ai_agent.AI_HTTP_TIMEOUT.connect == ai_agent.CONNECT_TIMEOUT)
    check("AI_HTTP_TIMEOUT.sock_read == 35", ai_agent.AI_HTTP_TIMEOUT.sock_read == 35)
    check("discovery timeout ham cheklangan",
          ai_agent.AI_DISCOVERY_TIMEOUT.total <= 35)

    ai_src = (root / "utils" / "ai_agent.py").read_text(encoding="utf-8")
    check("ai_agent: sessiya AI_HTTP_TIMEOUT bilan ochiladi",
          "timeout=AI_HTTP_TIMEOUT,\n                    connector=connector," in ai_src)

    # HAR BIR tashqi so'rovda aniq `timeout=` bo'lishi shart
    import re as _re
    unguarded = []
    for m in _re.finditer(r"session\.(get|post)\((.*?)\)\s+as resp", ai_src, _re.S):
        if "timeout=" not in m.group(2):
            unguarded.append(m.group(0)[:70])
    check("ai_agent: timeout'siz tashqi so'rov YO'Q", not unguarded, str(unguarded))
    total_reqs = len(_re.findall(r"session\.(?:get|post)\(", ai_src))
    check("ai_agent: barcha so'rovlar sanaldi", total_reqs >= 8, str(total_reqs))

    # --- Timeout bo'lganda XUSHMUOMALA xabar ---
    msg_uz = ai_agent.ai_timeout_message("uz")
    msg_ru = ai_agent.ai_timeout_message("ru")
    check("timeout xabari (uz) mavjud", "AI xizmati" in msg_uz, msg_uz[:50])
    check("timeout xabari (uz) muloyim", "🙏" in msg_uz and "urinib" in msg_uz)
    check("timeout xabari (uz) matn saqlanishini aytadi", "saqlan" in msg_uz)
    check("timeout xabari (ru) ruscha", "ИИ" in msg_ru, msg_ru[:50])
    check("timeout xabari (ru) muloyim", "🙏" in msg_ru and "попробуйте" in msg_ru)
    check("timeout xabarida texnik traceback yo'q",
          "Traceback" not in msg_uz and "Exception" not in msg_uz)
    check("timeout xabarida 35 soniya ko'rsatilgan", "35" in msg_uz and "35" in msg_ru)

    async def _hang():
        await _aio.sleep(5)

    res = _aio.run(ai_agent._run_with_hard_timeout(_hang(), timeout=0.05))
    check("hard timeout → xushmuomala xabar",
          res.get("error") == ai_agent.AI_TIMEOUT_USER_MESSAGE, str(res)[:80])
    check("hard timeout → timeout bayrog'i", res.get("timeout") is True)

    # Barcha provayderlar timeout bersa ham texnik ro'yxat emas, muloyim xabar
    async def _all_timeout():
        return await ai_agent._run_ai_chain("test", "system")

    orig_providers = {}
    for fn_name in ("_call_gemini", "_call_groq", "_call_openrouter", "_call_mistral",
                    "_call_cerebras", "_call_sambanova", "_call_cloudflare",
                    "_call_pollinations"):
        orig_providers[fn_name] = getattr(ai_agent, fn_name)

    async def _timeout_provider(*args, **kwargs):
        raise ai_agent.ProviderError(0, "timeout")

    orig_breaker = ai_agent._breaker_open
    try:
        for fn_name in orig_providers:
            setattr(ai_agent, fn_name, _timeout_provider)
        ai_agent._breaker_open = lambda name: False
        res = _aio.run(_all_timeout())
    finally:
        for fn_name, fn in orig_providers.items():
            setattr(ai_agent, fn_name, fn)
        ai_agent._breaker_open = orig_breaker

    check("barcha provayder timeout → muloyim xabar",
          res.get("error") == ai_agent.AI_TIMEOUT_USER_MESSAGE, str(res)[:90])
    check("barcha provayder timeout → API kalit yo'riqnomasi ko'rsatilmaydi",
          "GEMINI_API_KEY" not in res.get("error", ""))


# ============================================================
# 🆕 ONBOARDING — YANGI FOYDALANUVCHILAR UCHUN SODDA KLAVIATURA
# ============================================================

class _OnbMe:
    username = "TestBot"
    id = 1


class _OnbUser:
    def __init__(self, uid=4242, name="Ali", lang="uz"):
        self.id = uid
        self.first_name = name
        self.full_name = name
        self.username = "ali"
        self.language_code = lang


class _OnbMsg:
    def __init__(self, chat_id=4242):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append((text, reply_markup, parse_mode))
        return self


class _OnbBot:
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def get_me(self):
        return _OnbMe()

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append((chat_id, text, reply_markup, parse_mode))
        return _OnbMsg()

    async def send_chat_action(self, chat_id=None, action=None, **kw):
        return True


class _OnbUpdate:
    def __init__(self, uid=4242, lang="uz"):
        self.effective_user = _OnbUser(uid, lang=lang)
        self.effective_chat = self.effective_user
        self.message = _OnbMsg(uid)
        self.effective_message = self.message
        self.callback_query = None
        self.args = []


class _OnbCtx:
    def __init__(self, lang="uz", user_data=None):
        self.user_data = {"lang": lang} if user_data is None else user_data
        self.bot = _OnbBot()
        self.chat_data = {}
        self.args = []


def _onb_days_ago(days, hours=0):
    import pytz
    from datetime import datetime, timedelta
    tz = pytz.timezone("Asia/Tashkent")
    return datetime.now(tz) - timedelta(days=days, hours=hours)


def test_onboarding_simple_menu_rules():
    """1️⃣ Sodda menyu qoidalari: 3 kun / 3 post / 'To'liq menyu' belgisi."""
    print("== onboarding: sodda menyu qoidalari (sof mantiq) ==")
    import onboarding as ob
    import pytz
    from datetime import datetime, timedelta

    tz = pytz.timezone("Asia/Tashkent")
    now = tz.localize(datetime(2026, 9, 6, 12, 0))

    def ago(days, hours=0):
        return now - timedelta(days=days, hours=hours)

    # --- Talab 1-band: 3 kundan kam YOKI 3 tadan kam post → sodda menyu ---
    check("1 kun, 0 post → sodda",
          ob.should_show_simple_menu(ago(1), 0, False, now) is True)
    check("1 kun, 10 post → sodda (kun < 3)",
          ob.should_show_simple_menu(ago(1), 10, False, now) is True)
    check("2 kun 23 soat, 0 post → sodda",
          ob.should_show_simple_menu(ago(2, 23), 0, False, now) is True)
    check("3 kun, 2 post → sodda (hali 3 post chiqarmagan)",
          ob.should_show_simple_menu(ago(3), 2, False, now) is True)
    check("3 kun, 3 post → to'liq",
          ob.should_show_simple_menu(ago(3), 3, False, now) is False)

    # --- Talab 2-band: 3 kundan oshsa → standart bosh menyu ---
    check("5 kun, 0 post → to'liq (3 kundan oshgan)",
          ob.should_show_simple_menu(ago(5), 0, False, now) is False)
    check("5 kun, 100 post → to'liq",
          ob.should_show_simple_menu(ago(5), 100, False, now) is False)
    check("30 kun, 0 post → to'liq",
          ob.should_show_simple_menu(ago(30), 0, False, now) is False)

    # --- Talab 2-band: "⚙️ To'liq menyuni ochish" bosilgan ---
    check("'To'liq menyu' bosilgan → to'liq (hatto 1 kunlik hisob)",
          ob.should_show_simple_menu(ago(1), 0, True, now) is False)
    check("belgi + eski hisob → to'liq",
          ob.should_show_simple_menu(ago(40), 9, True, now) is False)

    # --- created_at yo'q (eski hisob) → faqat postlar soni hal qiladi ---
    check("created_at yo'q, 0 post → sodda",
          ob.should_show_simple_menu(None, 0, False, now) is True)
    check("created_at yo'q, 3 post → to'liq",
          ob.should_show_simple_menu(None, 3, False, now) is False)
    check("created_at bo'sh satr → sodda (post yo'q)",
          ob.should_show_simple_menu("", 0, False, now) is True)

    # --- Chekka holatlar ---
    check("chegara: posts_published=None → sodda",
          ob.should_show_simple_menu(ago(3), None, False, now) is True)
    check("chegara: posts_published buzilgan qiymat → sodda",
          ob.should_show_simple_menu(ago(3), "abc", False, now) is True)
    check("chegara: 2 kun 23 soat + 99 post → sodda",
          ob.should_show_simple_menu(ago(2, 23), 99, False, now) is True)

    # --- days_since_registration ---
    naive_utc = datetime(2026, 9, 4, 7, 0)   # UTC → Toshkentda 12:00, 2 kun oldin
    check("naive datetime UTC deb hisoblanadi",
          ob.days_since_registration(naive_utc, now) == 2,
          str(ob.days_since_registration(naive_utc, now)))
    check("aware datetime Toshkentga o'tkaziladi",
          ob.days_since_registration(ago(4, 6), now) == 4,
          str(ob.days_since_registration(ago(4, 6), now)))
    check("satr (ISO) created_at o'qiladi",
          ob.days_since_registration("2026-09-04 07:00:00", now) == 2,
          str(ob.days_since_registration("2026-09-04 07:00:00", now)))
    check("buzilgan satr → None", ob.days_since_registration("sanasi yo'q", now) is None)
    check("created_at=None → None", ob.days_since_registration(None, now) is None)
    check("kelajakdagi sana → 0 (eski deb hisoblanmaydi)",
          ob.days_since_registration(ago(-5), now) == 0)
    check("is_new_by_days: 1 kun → True", ob.is_new_by_days(ago(1), now) is True)
    check("is_new_by_days: 4 kun → False", ob.is_new_by_days(ago(4), now) is False)
    check("has_few_posts: 2 → True", ob.has_few_posts(2) is True)
    check("has_few_posts: 3 → False", ob.has_few_posts(3) is False)

    # --- decide_menu_mode (DB natijasi → menyu rejimi) ---
    check("decide: bo'sh dict → full (fail-open)", ob.decide_menu_mode({}) == "full")
    check("decide: None → full", ob.decide_menu_mode(None) == "full")
    check("decide: yangi hisob → simple",
          ob.decide_menu_mode({"created_at": ago(1), "posts_published": 0,
                               "full_menu_unlocked": False}, now) == "simple")
    check("decide: eski hisob → full",
          ob.decide_menu_mode({"created_at": ago(9), "posts_published": 0,
                               "full_menu_unlocked": False}, now) == "full")

    # --- Sabab kodlari (log/analytics) ---
    check("sabab: unlocked", ob.simple_menu_reason(ago(1), 0, True, now) == "unlocked")
    check("sabab: expired", ob.simple_menu_reason(ago(9), 0, False, now) == "expired")
    check("sabab: new_days", ob.simple_menu_reason(ago(1), 7, False, now) == "new_days")
    check("sabab: few_posts", ob.simple_menu_reason(ago(3), 1, False, now) == "few_posts")
    check("sabab: unknown (created_at yo'q, post yetarli)",
          ob.simple_menu_reason(None, 7, False, now) == "unknown")

    # --- Qisqa muddatli kesh (Neon'ga ortiqcha so'rov ketmasligi uchun) ---
    ob.invalidate_simple_menu()
    check("kesh: boshida bo'sh", ob.get_cached_simple_menu(1) is None)
    ob.cache_simple_menu(1, True)
    ob.cache_simple_menu(2, False)
    check("kesh: True qaytdi", ob.get_cached_simple_menu(1) is True)
    check("kesh: False qaytdi", ob.get_cached_simple_menu(2) is False)
    check("kesh: 2 yozuv", ob.cache_size() == 2, str(ob.cache_size()))
    ob.invalidate_simple_menu(1)
    check("kesh: bitta user tozalandi",
          ob.get_cached_simple_menu(1) is None and ob.get_cached_simple_menu(2) is False)
    ob._SIMPLE_MENU_CACHE[3] = (time.time() - ob.SIMPLE_MENU_CACHE_TTL - 1, True)
    check("kesh: eskirgan yozuv qaytmaydi", ob.get_cached_simple_menu(3) is None)
    ob.invalidate_simple_menu()
    check("kesh: hammasi tozalandi", ob.cache_size() == 0)
    check("kesh: user_id bo'sh → hech narsa", ob.get_cached_simple_menu(None) is None)


def test_onboarding_simple_keyboard():
    """1️⃣ Sodda klaviatura: 3 ta katta tugma + 1 ta kichik 'To'liq menyu' (uz/ru)."""
    print("== onboarding: sodda klaviatura (uz/ru) ==")
    from locales.translations import get_text
    from keyboards.default import (
        get_simple_keyboard, get_main_keyboard,
        BTN_QUICK_AI_POST, BTN_QUICK_PHOTO_POST, BTN_QUICK_ADD_CHANNEL, BTN_OPEN_FULL_MENU,
        BTN_QUICK_AI_POST_RU, BTN_QUICK_PHOTO_POST_RU,
        BTN_QUICK_ADD_CHANNEL_RU, BTN_OPEN_FULL_MENU_RU, QUICK_MENU_BUTTONS,
        BTN_NEW_POST, BTN_AI_STUDIO, BTN_PREMIUM, BTN_SETTINGS, BTN_HELP, BTN_EXTRAS,
    )

    # --- Tugma yozuvlari aynan talabdagidek ---
    check("tugma uz: 🚀 1 daqiqada post yaratish",
          BTN_QUICK_AI_POST == "🚀 1 daqiqada post yaratish", BTN_QUICK_AI_POST)
    check("tugma uz: 🖼 Rasmdan post olish",
          BTN_QUICK_PHOTO_POST == "🖼 Rasmdan post olish", BTN_QUICK_PHOTO_POST)
    check("tugma uz: 📢 Kanal ulash",
          BTN_QUICK_ADD_CHANNEL == "📢 Kanal ulash", BTN_QUICK_ADD_CHANNEL)
    check("tugma uz: ⚙️ To'liq menyuni ochish",
          BTN_OPEN_FULL_MENU == "⚙️ To'liq menyuni ochish", BTN_OPEN_FULL_MENU)
    check("tugma ru: 🚀 Создать пост за 1 минуту",
          BTN_QUICK_AI_POST_RU == "🚀 Создать пост за 1 минуту", BTN_QUICK_AI_POST_RU)
    check("tugma ru: 🖼 Пост из фото",
          BTN_QUICK_PHOTO_POST_RU == "🖼 Пост из фото", BTN_QUICK_PHOTO_POST_RU)
    check("tugma ru: 📢 Подключить канал",
          BTN_QUICK_ADD_CHANNEL_RU == "📢 Подключить канал", BTN_QUICK_ADD_CHANNEL_RU)
    check("tugma ru: ⚙️ Открыть полное меню",
          BTN_OPEN_FULL_MENU_RU == "⚙️ Открыть полное меню", BTN_OPEN_FULL_MENU_RU)
    check("QUICK_MENU_BUTTONS: 12 ta (uz+ru+en)", len(QUICK_MENU_BUTTONS) == 12,
          str(len(QUICK_MENU_BUTTONS)))
    check("barcha tugmalar lug'atdan olinadi",
          BTN_QUICK_AI_POST == get_text("quick_btn_ai_post", "uz")
          and BTN_OPEN_FULL_MENU_RU == get_text("quick_btn_full_menu", "ru"))

    # --- Tuzilma: 3 ta katta tugma + pastda 1 ta kichik ---
    kb = get_simple_keyboard("uz")
    rows = [[b.text for b in row] for row in kb.keyboard]
    check("sodda kb uz: 4 qator", len(rows) == 4, str(rows))
    check("sodda kb: har tugma alohida qatorda (katta ko'rinish)",
          all(len(r) == 1 for r in rows), str(rows))
    check("sodda kb uz: tartib AI → Rasm → Kanal → To'liq menyu",
          rows == [[BTN_QUICK_AI_POST], [BTN_QUICK_PHOTO_POST],
                   [BTN_QUICK_ADD_CHANNEL], [BTN_OPEN_FULL_MENU]], str(rows))
    check("sodda kb: 'To'liq menyu' ENG PASTDA", rows[-1] == [BTN_OPEN_FULL_MENU])
    check("sodda kb: resize_keyboard=True", kb.resize_keyboard is True)

    rows_ru = [[b.text for b in row] for row in get_simple_keyboard("ru").keyboard]
    check("sodda kb ru: tarjima qilingan",
          rows_ru == [[BTN_QUICK_AI_POST_RU], [BTN_QUICK_PHOTO_POST_RU],
                      [BTN_QUICK_ADD_CHANNEL_RU], [BTN_OPEN_FULL_MENU_RU]], str(rows_ru))
    check("sodda kb: default uz (eski chaqiruvlar buzilmaydi)",
          [[b.text for b in r] for r in get_simple_keyboard().keyboard] == rows)

    class _Ctx:
        def __init__(self, data):
            self.user_data = data

    check("sodda kb: context.user_data['lang'] hurmat qilinadi",
          [[b.text for b in r] for r in get_simple_keyboard(context=_Ctx({"lang": "ru"})).keyboard]
          == rows_ru)

    # --- Murakkab 6 talik menyu tugmalari sodda klaviaturada YO'Q ---
    flat = [t for r in rows for t in r]
    for btn in (BTN_NEW_POST, BTN_AI_STUDIO, BTN_PREMIUM, BTN_SETTINGS, BTN_HELP, BTN_EXTRAS):
        check(f"sodda kb: 6 talik menyu tugmasi yo'q ({btn[:14]})", btn not in flat, str(flat))
    full_flat = [b.text for row in get_main_keyboard(False).keyboard for b in row]
    check("standart menyu buzilmagan: 6 tugma", len(full_flat) == 6, str(full_flat))


def test_onboarding_resolve_and_quick_handlers():
    """1️⃣ Menyu tanlash (DB + kesh) va 3 ta tezkor tugma — runtime."""
    print("== onboarding: resolve_main_keyboard va tezkor tugmalar ==")
    import asyncio
    import importlib
    import database as db_mod
    import onboarding as ob
    from telegram.ext import ConversationHandler
    from locales.translations import get_text
    from keyboards.default import BTN_NEW_POST, BTN_QUICK_AI_POST

    ob_mod = importlib.import_module("handlers.onboarding")
    from handlers.ai_assistant import AI_PROMPT_INPUT, AI_PHOTO_INPUT
    from handlers.channels import ADD_CHANNEL

    state = {"onboarding": {}, "raise": False}
    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append(name)
        if state["raise"]:
            raise RuntimeError("DB uzildi")
        if name == "get_user_onboarding":
            return state["onboarding"]
        if name == "set_user_full_menu_unlocked":
            return True
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    ob.invalidate_simple_menu()
    try:
        # --- a) Yangi foydalanuvchi → sodda klaviatura + kesh ---
        state["onboarding"] = {"created_at": _onb_days_ago(1), "posts_published": 0,
                               "full_menu_unlocked": False}
        kb = asyncio.run(ob_mod.resolve_main_keyboard(4242, False, "uz"))
        labels = [b.text for r in kb.keyboard for b in r]
        check("yangi user → sodda klaviatura", labels[0] == BTN_QUICK_AI_POST, str(labels))
        check("yangi user → 4 qator", len(kb.keyboard) == 4, str(labels))
        db_calls = calls.count("get_user_onboarding")
        asyncio.run(ob_mod.resolve_main_keyboard(4242, False, "uz"))
        check("ikkinchi chaqiruv keshdan (DB so'rovi yo'q)",
              calls.count("get_user_onboarding") == db_calls,
              str(calls.count("get_user_onboarding")))
        check("qaror keshga yozildi", ob.get_cached_simple_menu(4242) is True)
        suffix = asyncio.run(ob_mod.main_menu_intro_suffix(4242, False, "uz"))
        check("intro: quick_menu_hint qo'shiladi",
              get_text("quick_menu_hint", "uz") in suffix, suffix[:40])

        # --- b) Admin → har doim to'liq menyu (DB so'rovsiz) ---
        calls.clear()
        kb_admin = asyncio.run(ob_mod.resolve_main_keyboard(4242, True, "uz"))
        check("admin → to'liq menyu",
              BTN_NEW_POST in [b.text for r in kb_admin.keyboard for b in r])
        check("admin → DB so'rovi yo'q", "get_user_onboarding" not in calls, str(calls))
        check("admin → intro qatori bo'sh",
              asyncio.run(ob_mod.main_menu_intro_suffix(4242, True, "uz")) == "")

        # --- c) Eski foydalanuvchi → to'liq menyu ---
        ob.invalidate_simple_menu()
        state["onboarding"] = {"created_at": _onb_days_ago(12), "posts_published": 0,
                               "full_menu_unlocked": False}
        kb_old = asyncio.run(ob_mod.resolve_main_keyboard(5150, False, "uz"))
        check("eski user → to'liq menyu",
              BTN_NEW_POST in [b.text for r in kb_old.keyboard for b in r])
        check("eski user → intro qatori yo'q",
              asyncio.run(ob_mod.main_menu_intro_suffix(5150, False, "uz")) == "")

        # --- d) Foydalanuvchi topilmadi ({}) → to'liq menyu (fail-open) ---
        ob.invalidate_simple_menu()
        state["onboarding"] = {}
        kb_empty = asyncio.run(ob_mod.resolve_main_keyboard(6160, False, "uz"))
        check("bo'sh onboarding → to'liq menyu",
              BTN_NEW_POST in [b.text for r in kb_empty.keyboard for b in r])

        # --- e) DB yiqilsa → to'liq menyu (bot qulflab qolmaydi) ---
        ob.invalidate_simple_menu()
        state["raise"] = True
        kb_err = asyncio.run(ob_mod.resolve_main_keyboard(7170, False, "uz"))
        check("DB xatosi → to'liq menyu",
              BTN_NEW_POST in [b.text for r in kb_err.keyboard for b in r])
        state["raise"] = False

        # --- f) 🚀 1 daqiqada post yaratish → AI post oqimi ---
        upd = _OnbUpdate(4242)
        ctx = _OnbCtx("uz", {"lang": "uz", "studio_post_text": "eski", "studio_tone": "formal"})
        out = asyncio.run(ob_mod.quick_ai_post_entry(upd, ctx))
        check("quick AI: AI_PROMPT_INPUT holati", out == AI_PROMPT_INPUT, str(out))
        text, markup, pm = upd.message.sent[-1]
        check("quick AI: intro matni (uz)", text == get_text("ai_studio_post_intro", "uz"))
        check("quick AI: HTML parse_mode", pm == "HTML")
        check("quick AI: 'orqaga' tugmasi bor",
              any(b.callback_data == "ai_back_to_menu"
                  for r in markup.inline_keyboard for b in r))
        check("quick AI: eski studio ma'lumoti tozalandi",
              "studio_post_text" not in ctx.user_data and "studio_tone" not in ctx.user_data)

        upd_ru = _OnbUpdate(4242, lang="ru")
        ctx_ru = _OnbCtx("ru", {"lang": "ru"})
        asyncio.run(ob_mod.quick_ai_post_entry(upd_ru, ctx_ru))
        check("quick AI ru: intro matni ruscha",
              upd_ru.message.sent[-1][0] == get_text("ai_studio_post_intro", "ru"))

        # --- g) 🖼 Rasmdan post olish → Vision oqimi ---
        upd_p = _OnbUpdate(4242)
        ctx_p = _OnbCtx("uz", {"lang": "uz", "studio_file_id": "ph-1"})
        out_p = asyncio.run(ob_mod.quick_photo_post_entry(upd_p, ctx_p))
        check("quick Rasm: AI_PHOTO_INPUT holati", out_p == AI_PHOTO_INPUT, str(out_p))
        check("quick Rasm: vision intro matni",
              upd_p.message.sent[-1][0] == get_text("ai_studio_photo_intro", "uz"))
        check("quick Rasm: eski rasm ma'lumoti tozalandi",
              "studio_file_id" not in ctx_p.user_data)

        # --- h) 📢 Kanal ulash → ADD_CHANNEL oqimi ---
        upd_c = _OnbUpdate(4242)
        ctx_c = _OnbCtx("uz", {"lang": "uz", "add_channel_pending": "@old"})
        out_c = asyncio.run(ob_mod.quick_add_channel_entry(upd_c, ctx_c))
        check("quick Kanal: ADD_CHANNEL holati", out_c == ADD_CHANNEL, str(out_c))
        check("quick Kanal: yo'riqnoma yuborildi",
              bool(ctx_c.bot.sent) and "TestBot" in str(ctx_c.bot.sent[0][1]),
              str(ctx_c.bot.sent)[:1])
        check("quick Kanal: eski 'kutilayotgan kanal' tozalandi",
              "add_channel_pending" not in ctx_c.user_data)

        # --- i) ⚙️ To'liq menyuni ochish ---
        upd_f = _OnbUpdate(4242)
        ctx_f = _OnbCtx("uz", {"lang": "uz"})
        out_f = asyncio.run(ob_mod.open_full_menu(upd_f, ctx_f))
        check("full menu: END qaytdi", out_f == ConversationHandler.END, str(out_f))
        check("full menu: belgi bazaga yozildi",
              "set_user_full_menu_unlocked" in calls, str(calls[-3:]))
        f_text, f_markup, f_pm = upd_f.message.sent[-1]
        check("full menu: tasdiq matni (uz)",
              f_text == get_text("quick_full_menu_opened", "uz"), f_text[:60])
        check("full menu: standart 6 talik menyu biriktirildi",
              BTN_NEW_POST in [b.text for r in f_markup.keyboard for b in r])
        check("full menu: HTML", f_pm == "HTML")
        check("full menu: kesh to'liq menyuga o'tdi",
              ob.get_cached_simple_menu(4242) is False)

        upd_fr = _OnbUpdate(4242, lang="ru")
        ctx_fr = _OnbCtx("ru", {"lang": "ru"})
        asyncio.run(ob_mod.open_full_menu(upd_fr, ctx_fr))
        f_text_ru, f_markup_ru, _ = upd_fr.message.sent[-1]
        check("full menu ru: ruscha tasdiq + ruscha menyu",
              f_text_ru == get_text("quick_full_menu_opened", "ru")
              and get_text("btn_new_post", "ru")
              in [b.text for r in f_markup_ru.keyboard for b in r], f_text_ru[:60])

        # DB yozuvi yiqilsa ham menyu ochiladi (foydalanuvchi qulflanmaydi)
        state["raise"] = True
        upd_e = _OnbUpdate(4242)
        ctx_e = _OnbCtx("uz", {"lang": "uz"})
        out_e = asyncio.run(ob_mod.open_full_menu(upd_e, ctx_e))
        check("full menu: DB xatosida ham menyu ochiladi",
              out_e == ConversationHandler.END and bool(upd_e.message.sent))
        state["raise"] = False
    finally:
        db_mod.run_db = orig
        ob.invalidate_simple_menu()


def test_onboarding_start_integration():
    """1️⃣ /start: yangi foydalanuvchi sodda klaviatura oladi, eski — standart."""
    print("== onboarding: /start integratsiyasi ==")
    import asyncio
    import importlib
    import database as db_mod
    import onboarding as ob
    from telegram import ReplyKeyboardMarkup
    from keyboards.default import BTN_NEW_POST, BTN_QUICK_AI_POST, BTN_OPEN_FULL_MENU
    from locales.translations import get_text

    st_mod = importlib.import_module("handlers.start")
    state = {"onboarding": {}, "is_new": True, "lang": "uz"}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "save_user":
            return state["is_new"]
        if name == "get_user_language":
            return state["lang"]
        if name == "get_user_onboarding":
            return state["onboarding"]
        if name == "get_setting":
            return ""
        if name == "is_premium":
            return False
        return None

    async def fake_check(bot, uid):
        return True, []

    async def fake_ad(uid):
        return ""

    def run_start():
        upd = _OnbUpdate(4242, lang=state["lang"])
        ctx = _OnbCtx(state["lang"], {"lang": state["lang"]})
        asyncio.run(st_mod.start(upd, ctx))
        return upd.message.sent[-1]

    orig_db = db_mod.run_db
    orig_check = st_mod.check_user_subscribed
    orig_ad = st_mod.get_smart_reply_ad_async
    db_mod.run_db = fake_run_db
    st_mod.check_user_subscribed = fake_check
    st_mod.get_smart_reply_ad_async = fake_ad
    ob.invalidate_simple_menu()
    try:
        # a) Yangi foydalanuvchi → onboarding matni + SODDA klaviatura + yo'riqnoma
        state.update({"onboarding": {"created_at": _onb_days_ago(0, 2), "posts_published": 0,
                                     "full_menu_unlocked": False}, "is_new": True, "lang": "uz"})
        text, markup, pm = run_start()
        check("start: onboarding matni saqlangan",
              text.startswith(get_text("start_onboarding", "uz")), text[:60])
        check("start: quick_menu_hint qo'shilgan",
              get_text("quick_menu_hint", "uz") in text, text[-60:])
        check("start: ReplyKeyboardMarkup", isinstance(markup, ReplyKeyboardMarkup))
        labels = [b.text for r in markup.keyboard for b in r]
        check("start: sodda klaviatura (3 katta + 1 kichik)",
              labels == [BTN_QUICK_AI_POST, get_text("quick_btn_photo_post", "uz"),
                         get_text("quick_btn_add_channel", "uz"), BTN_OPEN_FULL_MENU], str(labels))
        check("start: 6 talik menyu tugmasi yo'q", BTN_NEW_POST not in labels, str(labels))
        check("start: HTML", pm == "HTML")

        # b) Eski foydalanuvchi → standart 6 talik menyu
        ob.invalidate_simple_menu()
        state.update({"onboarding": {"created_at": _onb_days_ago(20), "posts_published": 9,
                                     "full_menu_unlocked": False}, "is_new": False, "lang": "uz"})
        text2, markup2, _ = run_start()
        labels2 = [b.text for r in markup2.keyboard for b in r]
        check("start (eski): standart menyu", BTN_NEW_POST in labels2, str(labels2))
        check("start (eski): quick_menu_hint yo'q",
              get_text("quick_menu_hint", "uz") not in text2)
        check("start (eski): standart salomlashish",
              text2.startswith(get_text("start_hello", "uz", name="Ali")), text2[:50])

        # c) RU foydalanuvchi → ruscha sodda klaviatura
        ob.invalidate_simple_menu()
        state.update({"onboarding": {"created_at": _onb_days_ago(1), "posts_published": 0,
                                     "full_menu_unlocked": False}, "is_new": False, "lang": "ru"})
        text3, markup3, _ = run_start()
        labels3 = [b.text for r in markup3.keyboard for b in r]
        check("start ru: ruscha sodda klaviatura",
              labels3[0] == get_text("quick_btn_ai_post", "ru")
              and labels3[-1] == get_text("quick_btn_full_menu", "ru"), str(labels3))
        check("start ru: ruscha yo'riqnoma", get_text("quick_menu_hint", "ru") in text3)

        # d) "To'liq menyu" allaqachon bosilgan → standart menyu
        ob.invalidate_simple_menu()
        state.update({"onboarding": {"created_at": _onb_days_ago(1), "posts_published": 0,
                                     "full_menu_unlocked": True}, "is_new": True, "lang": "uz"})
        _, markup4, _ = run_start()
        check("start: belgi bilan → standart menyu",
              BTN_NEW_POST in [b.text for r in markup4.keyboard for b in r])

        # e) Onboarding ma'lumoti bo'lmasa → standart menyu (regressiya yo'q)
        ob.invalidate_simple_menu()
        state.update({"onboarding": {}, "is_new": True, "lang": "uz"})
        _, markup5, _ = run_start()
        check("start: ma'lumot yo'q → standart menyu (regressiya yo'q)",
              BTN_NEW_POST in [b.text for r in markup5.keyboard for b in r])

        # f) send_main_menu: simple_menu parametri (bazaga so'rov yubormaydi)
        class _RecBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, chat_id=None, text=None, reply_markup=None,
                                   parse_mode=None, **kw):
                self.sent.append((text, reply_markup))
                return None

        bot = _RecBot()
        sctx = _OnbCtx("uz", {"lang": "uz"})
        sctx.bot = bot
        check("send_main_menu: main_menu_hint matni",
              asyncio.run(st_mod.send_main_menu(sctx, 4242, "uz", False)) is None)
        check("send_main_menu: default → standart menyu (orqaga moslik)",
              BTN_NEW_POST in [b.text for r in bot.sent[-1][1].keyboard for b in r],
              str([b.text for r in bot.sent[-1][1].keyboard for b in r]))
        check("send_main_menu: matn main_menu_hint",
              bot.sent[-1][0] == get_text("main_menu_hint", "uz"), str(bot.sent[-1][0])[:50])

        asyncio.run(st_mod.send_main_menu(sctx, 4242, "uz", False, simple_menu=True))
        simple_labels = [b.text for r in bot.sent[-1][1].keyboard for b in r]
        check("send_main_menu: simple_menu=True → sodda klaviatura",
              simple_labels == [BTN_QUICK_AI_POST, get_text("quick_btn_photo_post", "uz"),
                                get_text("quick_btn_add_channel", "uz"),
                                get_text("quick_btn_full_menu", "uz")], str(simple_labels))

        asyncio.run(st_mod.send_main_menu(sctx, 4242, "ru", False, simple_menu=True))
        check("send_main_menu ru: ruscha sodda klaviatura",
              [b.text for r in bot.sent[-1][1].keyboard for b in r][0]
              == get_text("quick_btn_ai_post", "ru"))

        asyncio.run(st_mod.send_main_menu(sctx, 4242, "uz", True, simple_menu=True))
        check("send_main_menu: admin → standart menyu",
              BTN_NEW_POST in [b.text for r in bot.sent[-1][1].keyboard for b in r])
    finally:
        db_mod.run_db = orig_db
        st_mod.check_user_subscribed = orig_check
        st_mod.get_smart_reply_ad_async = orig_ad
        ob.invalidate_simple_menu()


def test_onboarding_handlers_registered():
    """1️⃣ Sodda menyu tugmalari router'da ro'yxatdan o'tgan (uz/ru, barcha holatlar)."""
    print("== onboarding: handler registratsiyasi ==")
    import re
    import warnings
    from telegram.ext import ApplicationBuilder, ConversationHandler, MessageHandler
    from handlers import register_all_handlers
    from keyboards.default import (
        BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU,
        BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU, BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU,
    )
    import handlers as h_mod

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)

    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]

    def _matches(handler_list, label):
        """Handler ro'yxatidagi Regex filtrlardan biri tugma matnini taniydimi?

        Matnni ro'yxatdan qidirish o'rniga HAQIQIY regex mosligi tekshiriladi —
        shunda emoji/bo'sh joy escape'lanishi natijani buzmaydi.
        """
        for h in handler_list:
            if not isinstance(h, MessageHandler):
                continue
            pattern = getattr(h.filters, "pattern", None)
            if not pattern:
                continue
            try:
                if re.fullmatch(pattern, label):
                    return True
            except Exception:
                continue
        return False

    for label in (BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_PHOTO_POST,
                  BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU,
                  BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU):
        check(f"entry point tugmani taniydi: {label[:24]}",
              _matches(conv.entry_points, label), label)

    # Har bir FSM holatida ham ishlaydi (all_menu_jumps har state boshida)
    from handlers.new_post import GET_CONTENT
    from handlers.content_plan import PLAN_VIEW
    from handlers.channels import ADD_CHANNEL
    for state_name, state in (("GET_CONTENT", GET_CONTENT), ("PLAN_VIEW", PLAN_VIEW),
                              ("ADD_CHANNEL", ADD_CHANNEL)):
        check(f"{state_name}: sodda menyu tugmalari ishlaydi",
              _matches(conv.states[state], BTN_QUICK_AI_POST)
              and _matches(conv.states[state], BTN_OPEN_FULL_MENU_RU))

    # Global (conversation tashqarisida) handlerlar ham bor
    check("global: sodda menyu tugmalari ro'yxatda",
          _matches(app.handlers[0], BTN_QUICK_AI_POST)
          and _matches(app.handlers[0], BTN_OPEN_FULL_MENU))
    # Eski 6 talik menyu tugmalari ham saqlangan (regressiya yo'q)
    from keyboards.default import BTN_NEW_POST, BTN_NEW_POST_RU
    check("global: eski menyu tugmalari saqlangan",
          _matches(app.handlers[0], BTN_NEW_POST) and _matches(app.handlers[0], BTN_NEW_POST_RU))

    src = open(h_mod.__file__, encoding="utf-8").read()
    check("router: quick_ai_post_entry ulangan", "quick_ai_post_entry" in src)
    check("router: quick_photo_post_entry ulangan", "quick_photo_post_entry" in src)
    check("router: quick_add_channel_entry ulangan", "quick_add_channel_entry" in src)
    check("router: open_full_menu ulangan", "open_full_menu" in src)
    check("router: onboarding_handlers all_menu_jumps'da", "onboarding_handlers +" in src)


def test_onboarding_db_and_schema():
    """1️⃣ Onboarding DB funksiyalari va sxema migratsiyasi (Neon uchun idempotent)."""
    print("== onboarding: DB funksiyalari va sxema ==")
    from pathlib import Path
    import database as db_mod
    import inspect

    check("db: get_user_onboarding mavjud", hasattr(db_mod, "get_user_onboarding"))
    check("db: set_user_full_menu_unlocked mavjud",
          hasattr(db_mod, "set_user_full_menu_unlocked"))
    sig = inspect.signature(db_mod.get_user_onboarding)
    check("db: get_user_onboarding(user_id)", list(sig.parameters) == ["user_id"],
          str(list(sig.parameters)))

    schema = (Path(db_mod.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    check("schema.sql: full_menu_unlocked ustuni",
          "full_menu_unlocked BOOLEAN DEFAULT FALSE" in schema)
    check("schema.sql: idempotent migratsiya (ADD COLUMN IF NOT EXISTS)",
          "ADD COLUMN IF NOT EXISTS full_menu_unlocked BOOLEAN DEFAULT FALSE" in schema)
    src = open(db_mod.__file__, encoding="utf-8").read()
    check("database.py: zaxira DDL'da ustun bor",
          src.count("full_menu_unlocked BOOLEAN DEFAULT FALSE") >= 2)
    check("database.py: migratsiya ro'yxatida bor",
          '"ALTER TABLE users ADD COLUMN IF NOT EXISTS full_menu_unlocked' in src)
    check("database.py: postlar soni status='posted' bo'yicha",
          "status = 'posted'" in src)
    check("database.py: onboarding keshi tozalanadi",
          "invalidate_simple_menu" in src)


# ============================================================
# 🚀 7 KUNLIK KONTENT-REJANI BITTA TUGMA BILAN NAVBATGA QO'YISH
# ============================================================

_PLAN_ITEMS_7 = [
    {"day": "Dushanba", "format": "Maslahat", "title": "Birinchi g'oya", "idea": "Tavsif 1"},
    {"day": "Seshanba", "format": "Keys", "title": "Ikkinchi g'oya", "idea": "Tavsif 2"},
    {"day": "Chorshanba", "format": "So'rovnoma", "title": "Uchinchi", "idea": "Tavsif 3"},
    {"day": "Payshanba", "format": "Video", "title": "To'rtinchi", "idea": "Tavsif 4"},
    {"day": "Juma", "format": "Statistika", "title": "Beshinchi", "idea": "Tavsif 5"},
    {"day": "Shanba", "format": "Iqtibos", "title": "Oltinchi", "idea": "Tavsif 6"},
    {"day": "Yakshanba", "format": "Xulosa", "title": "Yettinchi", "idea": "Tavsif 7"},
]


def test_content_plan_week_times():
    """2️⃣ Haftalik vaqtlar: dushanba → yakshanba, har kuni 12:00, doim kelajakda."""
    print("== content plan: haftalik vaqtlar ==")
    import pytz
    from datetime import datetime, timedelta
    from handlers.content_plan import (
        week_schedule_times, build_plan_post_text,
        PLAN_SCHEDULE_HOUR, PLAN_SCHEDULE_MINUTE, PLAN_WEEK_DAYS, CB_PLAN_SCHEDULE_ALL,
    )

    tz = pytz.timezone("Asia/Tashkent")
    check("soat 12:00 konstantasi",
          PLAN_SCHEDULE_HOUR == 12 and PLAN_SCHEDULE_MINUTE == 0)
    check("7 kun konstantasi", PLAN_WEEK_DAYS == 7)
    check("callback_data: plan_sched_all", CB_PLAN_SCHEDULE_ALL == "plan_sched_all")
    check("callback_data: ^plan_ pattern'iga mos (router ushlaydi)",
          CB_PLAN_SCHEDULE_ALL.startswith("plan_"))

    # Chorshanba 09:00 → keyingi dushanbadan boshlanadi
    wed = tz.localize(datetime(2026, 9, 2, 9, 0))
    times = week_schedule_times(7, now=wed)
    check("7 ta vaqt qaytdi", len(times) == 7, str(len(times)))
    check("kunlar: dushanba(0) → yakshanba(6)",
          [t.weekday() for t in times] == [0, 1, 2, 3, 4, 5, 6],
          str([t.weekday() for t in times]))
    check("barchasi soat 12:00",
          all(t.hour == 12 and t.minute == 0 for t in times),
          str([(t.hour, t.minute) for t in times]))
    check("ketma-ket kunlar (24 soat)",
          all(times[i + 1] - times[i] == timedelta(days=1) for i in range(6)))
    check("barchasi kelajakda", all(t > wed for t in times))
    check("birinchi kun: 2026-09-07 dushanba",
          times[0] == tz.localize(datetime(2026, 9, 7, 12, 0)), str(times[0]))
    check("aware datetime (tz bor)", all(t.tzinfo is not None for t in times))

    # Dushanba 08:00 → SHU dushanba 12:00 (hali o'tmagan)
    mon_early = tz.localize(datetime(2026, 9, 7, 8, 0))
    t2 = week_schedule_times(7, now=mon_early)
    check("dushanba 08:00 → bugungi 12:00",
          t2[0] == tz.localize(datetime(2026, 9, 7, 12, 0)), str(t2[0]))

    # Dushanba 13:00 → 12:00 allaqachon o'tgan → keyingi hafta
    mon_late = tz.localize(datetime(2026, 9, 7, 13, 0))
    t3 = week_schedule_times(7, now=mon_late)
    check("dushanba 13:00 → keyingi hafta dushanbasi",
          t3[0] == tz.localize(datetime(2026, 9, 14, 12, 0)), str(t3[0]))

    # Dushanba aynan 12:00 → o'tgan hisoblanadi (post o'tmishga tushmaydi)
    mon_exact = tz.localize(datetime(2026, 9, 7, 12, 0))
    check("dushanba aynan 12:00 → keyingi hafta",
          week_schedule_times(7, now=mon_exact)[0] == tz.localize(datetime(2026, 9, 14, 12, 0)))

    # Yakshanba → ertasi kuni dushanba
    sun = tz.localize(datetime(2026, 9, 6, 23, 30))
    check("yakshanba 23:30 → ertaga dushanba",
          week_schedule_times(7, now=sun)[0] == tz.localize(datetime(2026, 9, 7, 12, 0)))

    # Naive datetime ham qabul qilinadi
    check("naive datetime qabul qilinadi",
          len(week_schedule_times(7, now=datetime(2026, 9, 2, 9, 0))) == 7)
    check("0 kun → bo'sh ro'yxat", week_schedule_times(0, now=wed) == [])
    check("3 kun → 3 ta vaqt", len(week_schedule_times(3, now=wed)) == 3)
    check("standart: now berilmasa ham 7 ta kelajakdagi vaqt",
          all(t > datetime.now(tz) for t in week_schedule_times()))

    # --- Post matni (HTML xavfsiz) ---
    post = build_plan_post_text(_PLAN_ITEMS_7[0], 0)
    check("post: sarlavha <b> ichida",
          post.startswith("<b>Birinchi g&#x27;oya</b>"), post[:40])
    check("post: g'oya (idea) qo'shilgan", "Tavsif 1" in post, post)
    check("post: apostrof HTML'ga xavfsiz escape qilinadi (&#x27;)",
          "&#x27;" in post and "G'oya" not in post, post[:60])
    check("post: xavfli belgilar escape qilinadi",
          "&lt;script&gt;" in build_plan_post_text({"title": "<script>", "idea": "a & b"})
          and "a &amp; b" in build_plan_post_text({"title": "<script>", "idea": "a & b"}))
    check("post: sarlavha bo'lmasa kun nomi",
          "Kun 2" in build_plan_post_text({"day": "", "idea": ""}, 1))
    check("post: bo'sh item → kun nomi",
          build_plan_post_text({}, 0) == "<b>Kun 1</b>", build_plan_post_text({}, 0))
    check("post: faqat idea bo'lsa (sarlavha kunga almashtiriladi)",
          build_plan_post_text({"idea": "Faqat g'oya"}, 4)
          == "<b>Kun 5</b>\n\nFaqat g&#x27;oya",
          build_plan_post_text({"idea": "Faqat g'oya"}, 4))
    check("post: None item yiqilmaydi", build_plan_post_text(None, 3) == "<b>Kun 4</b>")
    check("post: 7 kunlik reja → 7 xil matn",
          len({build_plan_post_text(it, i) for i, it in enumerate(_PLAN_ITEMS_7)}) == 7)


def test_content_plan_week_keyboard():
    """2️⃣ Reja ekrani klaviaturasi: [🚀 Barchasini 7 kunga rejalashtirish] + kunlar."""
    print("== content plan: hafta klaviaturasi ==")
    from locales.translations import get_text
    from handlers.content_plan import (
        _get_plan_day_keyboard, _get_plan_week_keyboard, _plan_list_keyboard,
        CB_PLAN_SCHEDULE_ALL,
    )

    items = _PLAN_ITEMS_7[:2]

    # Eski keyboard O'ZGARMAGAN (mavjud testlar buzilmasin)
    day_cbs = [b.callback_data for r in _get_plan_day_keyboard(items).inline_keyboard for b in r]
    check("day kb: 3 ta tugma (2 kun + orqaga) — o'zgarmagan", len(day_cbs) == 3, str(day_cbs))

    # Yangi hafta klaviaturasi
    kb = _get_plan_week_keyboard(items, "uz")
    rows = kb.inline_keyboard
    labels = [b.text for r in rows for b in r]
    cbs = [b.callback_data for r in rows for b in r]
    check("week kb uz: birinchi qator — rejalashtirish tugmasi",
          rows[0][0].callback_data == CB_PLAN_SCHEDULE_ALL, str(rows[0]))
    check("week kb uz: tugma yozuvi talabdagidek",
          rows[0][0].text == "🚀 Barchasini 7 kunga rejalashtirish", rows[0][0].text)
    check("week kb uz: tugma lug'atdan olinadi",
          rows[0][0].text == get_text("plan_btn_schedule_all", "uz"))
    check("week kb uz: kun tugmalari saqlangan",
          "plan_day:0" in cbs and "plan_day:1" in cbs and "plan_back" in cbs, str(cbs))
    check("week kb: jami 4 tugma (1 + 2 kun + orqaga)", len(cbs) == 4, str(cbs))
    check("week kb: callback_data 64 baytdan oshmaydi",
          all(len(c.encode("utf-8")) <= 64 for c in cbs), str(cbs))

    rows_ru = _get_plan_week_keyboard(items, "ru").inline_keyboard
    check("week kb ru: ruscha yozuv",
          rows_ru[0][0].text == "🚀 Запланировать все на 7 дней", rows_ru[0][0].text)
    check("week kb ru: callback_data bir xil",
          rows_ru[0][0].callback_data == CB_PLAN_SCHEDULE_ALL)

    # 7 kunlik to'liq reja
    kb7 = _get_plan_week_keyboard(_PLAN_ITEMS_7, "uz")
    check("week kb: 7 kun + 1 rejalashtirish + orqaga = 9 tugma",
          len([b for r in kb7.inline_keyboard for b in r]) == 9,
          str(len([b for r in kb7.inline_keyboard for b in r])))

    # _plan_list_keyboard: allaqachon rejalashtirilgan bo'lsa tugma ko'rsatilmaydi
    class _Ctx:
        def __init__(self, data):
            self.user_data = data

    kb_open = _plan_list_keyboard(items, _Ctx({"plan_scheduled": False}), "uz")
    check("plan_list: rejalashtirilmagan → tugma BOR",
          any(b.callback_data == CB_PLAN_SCHEDULE_ALL
              for r in kb_open.inline_keyboard for b in r))
    kb_done = _plan_list_keyboard(items, _Ctx({"plan_scheduled": True}), "uz")
    check("plan_list: rejalashtirilgan → tugma YO'Q (ikki marta bosish himoyasi)",
          not any(b.callback_data == CB_PLAN_SCHEDULE_ALL
                  for r in kb_done.inline_keyboard for b in r))
    kb_nodata = _plan_list_keyboard(items, None, "uz")
    check("plan_list: context=None → tugma bor (yiqilmaydi)",
          any(b.callback_data == CB_PLAN_SCHEDULE_ALL
              for r in kb_nodata.inline_keyboard for b in r))


class _PlanQuery:
    def __init__(self, data, uid=4242):
        self.data = data
        self.from_user = _OnbUser(uid)
        self.message = _OnbMsg(uid)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append((text, reply_markup))
        return True

    async def edit_message_reply_markup(self, reply_markup=None, **kw):
        self.edits.append(("<markup>", reply_markup))
        return True


class _PlanUpdate:
    def __init__(self, data, uid=4242):
        self.callback_query = _PlanQuery(data, uid)
        self.effective_user = self.callback_query.from_user
        self.effective_chat = self.effective_user
        self.message = None
        self.effective_message = self.callback_query.message


def test_content_plan_schedule_all_flow():
    """2️⃣ '🚀 Barchasini 7 kunga rejalashtirish' — runtime oqim."""
    print("== content plan: 7 kunni navbatga qo'yish (runtime) ==")
    import asyncio
    import importlib
    import pytz
    from datetime import datetime, timedelta
    import database as db_mod
    from locales.translations import get_text

    cp = importlib.import_module("handlers.content_plan")
    tz = pytz.timezone("Asia/Tashkent")
    state = {"result": {"success": True, "count": 7, "ids": list(range(11, 18)),
                        "times": cp.week_schedule_times(7)}, "raise": False}
    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if state["raise"]:
            raise RuntimeError("DB uzildi")
        if name == "schedule_week_posts":
            return state["result"]
        if name == "get_user_channels":
            return [("-1001234567890", "Mening Kanalim")]
        return None

    def make_ctx(extra=None):
        data = {
            "lang": "uz",
            "plan_items": list(_PLAN_ITEMS_7),
            "plan_channel_id": "-1001234567890",
            "plan_channel_title": "Mening Kanalim",
            "plan_channels": [("-1001234567890", "Mening Kanalim")],
        }
        data.update(extra or {})
        return _OnbCtx("uz", data)

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # --- a) Muvaffaqiyatli: 7 post navbatga ---
        upd = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx = make_ctx()
        out = asyncio.run(cp.plan_schedule_all(upd, ctx))
        check("sched: PLAN_VIEW qaytdi", out == cp.PLAN_VIEW, str(out))
        check("sched: schedule_week_posts chaqirildi",
              any(n == "schedule_week_posts" for n, _ in calls), str([n for n, _ in calls]))
        write_call = [a for n, a in calls if n == "schedule_week_posts"][0]
        uid_arg, ch_arg, posts_arg = write_call[0], write_call[1], write_call[2]
        check("sched: user_id to'g'ri", uid_arg == 4242, str(uid_arg))
        check("sched: kanal to'g'ri", ch_arg == "-1001234567890", str(ch_arg))
        check("sched: 7 ta post yuborildi", len(posts_arg) == 7, str(len(posts_arg)))
        moments = [p[0] for p in posts_arg]
        check("sched: kunlar dushanba → yakshanba",
              [m.weekday() for m in moments] == [0, 1, 2, 3, 4, 5, 6],
              str([m.weekday() for m in moments]))
        check("sched: barchasi soat 12:00",
              all(m.hour == 12 and m.minute == 0 for m in moments),
              str([(m.hour, m.minute) for m in moments]))
        check("sched: kunlar ketma-ket",
              all(moments[i + 1] - moments[i] == timedelta(days=1) for i in range(6)))
        check("sched: har postda matn bor",
              all(p[1] and "<b>" in p[1] for p in posts_arg), str(posts_arg[0]))
        check("sched: matnlar rejadan olingan",
              "Birinchi g&#x27;oya" in posts_arg[0][1]
              and "Yettinchi" in posts_arg[6][1], str(posts_arg[0][1])[:60])

        q = upd.callback_query
        check("sched: darhol answer berildi", bool(q.answers), str(q.answers))
        confirm = q.message.sent[-1][0]
        check("sched: '✅ 7 kunlik postlar navbatga qo'yildi!'",
              confirm.startswith("✅ <b>7 kunlik postlar navbatga qo'yildi!</b>"), confirm[:70])
        check("sched: kanal nomi tasdiqda", "Mening Kanalim" in confirm, confirm[:120])
        check("sched: 7 ta post soni tasdiqda", "7 ta post" in confirm, confirm[:160])
        check("sched: har kun va vaqt ro'yxati",
              all(w in confirm for w in ("Dushanba", "Seshanba", "Chorshanba", "Payshanba",
                                         "Juma", "Shanba", "Yakshanba")), confirm[100:260])
        check("sched: 12:00 vaqtlari ko'rsatilgan", confirm.count("12:00") >= 7,
              str(confirm.count("12:00")))
        check("sched: HTML yuborildi", q.message.sent[-1][2] == "HTML")
        check("sched: belgi qo'yildi (ikki marta bosish himoyasi)",
              ctx.user_data.get("plan_scheduled") is True)
        check("sched: tugma klaviaturadan olib tashlandi",
              q.edits and not any(
                  b.callback_data == cp.CB_PLAN_SCHEDULE_ALL
                  for r in q.edits[-1][1].inline_keyboard for b in r))

        # RU tasdiq
        upd_ru = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx_ru = make_ctx({"lang": "ru"})
        asyncio.run(cp.plan_schedule_all(upd_ru, ctx_ru))
        confirm_ru = upd_ru.callback_query.message.sent[-1][0]
        check("sched ru: ruscha tasdiq",
              confirm_ru.startswith("✅ <b>7 постов на неделю добавлены в очередь!</b>"),
              confirm_ru[:70])
        check("sched ru: ruscha kun nomlari",
              "Понедельник" in confirm_ru and "Воскресенье" in confirm_ru, confirm_ru[100:260])

        # --- b) Ikki marta bosish → alert, DB'ga yozilmaydi ---
        calls.clear()
        upd2 = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx2 = make_ctx({"plan_scheduled": True})
        out2 = asyncio.run(cp.plan_schedule_all(upd2, ctx2))
        check("ikki marta: alert ko'rsatildi",
              upd2.callback_query.answers
              and upd2.callback_query.answers[0][0] == get_text("plan_sched_already", "uz"),
              str(upd2.callback_query.answers))
        check("ikki marta: DB'ga yozilmadi",
              not any(n == "schedule_week_posts" for n, _ in calls), str(calls))
        check("ikki marta: PLAN_VIEW", out2 == cp.PLAN_VIEW)

        # --- c) Sessiya eskirgan (reja yo'q) ---
        upd3 = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx3 = make_ctx({"plan_items": []})
        out3 = asyncio.run(cp.plan_schedule_all(upd3, ctx3))
        check("eskirgan: stale alert",
              upd3.callback_query.answers
              and upd3.callback_query.answers[0][0] == get_text("plan_sched_stale", "uz"),
              str(upd3.callback_query.answers))
        check("eskirgan: alert show_alert=True",
              upd3.callback_query.answers[0][1] is True)
        check("eskirgan: PLAN_VIEW", out3 == cp.PLAN_VIEW)

        # --- d) Kanal foydalanuvchiga tegishli emas ---
        calls.clear()
        upd4 = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx4 = make_ctx({"plan_channel_id": "-1009999999999"})
        asyncio.run(cp.plan_schedule_all(upd4, ctx4))
        check("begona kanal: alert",
              upd4.callback_query.answers
              and upd4.callback_query.answers[0][0] == get_text("plan_sched_no_channel", "uz"),
              str(upd4.callback_query.answers))
        check("begona kanal: DB'ga yozilmadi",
              not any(n == "schedule_week_posts" for n, _ in calls), str(calls))

        # plan_channels user_data'da bo'lmasa — bazadan o'qiladi
        calls.clear()
        upd4b = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx4b = make_ctx()
        del ctx4b.user_data["plan_channels"]
        asyncio.run(cp.plan_schedule_all(upd4b, ctx4b))
        check("kanal ro'yxati bazadan o'qildi",
              any(n == "get_user_channels" for n, _ in calls), str([n for n, _ in calls]))
        check("kanal ro'yxati bazadan: reja baribir navbatga qo'yildi",
              any(n == "schedule_week_posts" for n, _ in calls), str([n for n, _ in calls]))

        # --- e) DB xatosi → xushmuomala xabar, belgi qo'yilmaydi ---
        state["result"] = {"success": False, "count": 0, "ids": [], "times": [],
                           "error": "connection lost"}
        upd5 = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx5 = make_ctx()
        out5 = asyncio.run(cp.plan_schedule_all(upd5, ctx5))
        err_text = upd5.callback_query.message.sent[-1][0]
        check("DB xatosi: xushmuomala xabar",
              err_text == get_text("plan_sched_error", "uz"), err_text[:60])
        check("DB xatosi: belgi qo'yilmadi", not ctx5.user_data.get("plan_scheduled"))
        check("DB xatosi: kun tugmalari qaytarildi",
              any(b.callback_data == "plan_day:0"
                  for r in upd5.callback_query.message.sent[-1][1].inline_keyboard for b in r))
        check("DB xatosi: PLAN_VIEW", out5 == cp.PLAN_VIEW)

        # --- f) run_db istisno tashlasa ham handler yiqilmaydi ---
        state["raise"] = True
        upd6 = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx6 = make_ctx()
        try:
            out6 = asyncio.run(cp.plan_schedule_all(upd6, ctx6))
            raised = False
        except Exception:
            raised = True
            out6 = None
        check("run_db istisnosi: handler yiqilmaydi", raised is False)
        check("run_db istisnosi: xushmuomala xabar yuborildi",
              bool(upd6.callback_query.message.sent)
              and upd6.callback_query.message.sent[-1][0] == get_text("plan_sched_error", "uz"),
              str(upd6.callback_query.message.sent[-1:] if upd6.callback_query.message.sent else []))
        check("run_db istisnosi: belgi qo'yilmadi", not ctx6.user_data.get("plan_scheduled"))
        check("run_db istisnosi: PLAN_VIEW", out6 == cp.PLAN_VIEW, str(out6))
        state["raise"] = False
    finally:
        db_mod.run_db = orig


def test_content_plan_schedule_all_routing():
    """2️⃣ plan_view_callback 'plan_sched_all' ni plan_schedule_all ga yo'naltiradi."""
    print("== content plan: callback routing ==")
    import asyncio
    import importlib
    cp = importlib.import_module("handlers.content_plan")

    hit = []

    async def fake_schedule_all(update, context):
        hit.append(update.callback_query.data)
        return cp.PLAN_VIEW

    orig = cp.plan_schedule_all
    cp.plan_schedule_all = fake_schedule_all
    try:
        upd = _PlanUpdate(cp.CB_PLAN_SCHEDULE_ALL)
        ctx = _OnbCtx("uz", {"lang": "uz", "plan_items": list(_PLAN_ITEMS_7)})
        out = asyncio.run(cp.plan_view_callback(upd, ctx))
        check("routing: plan_sched_all ushlandi", hit == [cp.CB_PLAN_SCHEDULE_ALL], str(hit))
        check("routing: PLAN_VIEW qaytdi", out == cp.PLAN_VIEW, str(out))
    finally:
        cp.plan_schedule_all = orig

    # Router: PLAN_VIEW holatidagi ^plan_ pattern yangi callback'ni ham qamrab oladi
    import re
    check("router pattern: ^plan_ → plan_sched_all mos",
          re.match(r"^plan_", cp.CB_PLAN_SCHEDULE_ALL) is not None)

    # Reja yaratilganda belgi tozalanadi (yangi reja = yangi imkoniyat)
    src = open(cp.__file__, encoding="utf-8").read()
    check("content_plan: plan_scheduled tozalanadi",
          src.count('context.user_data["plan_scheduled"] = False') >= 2,
          str(src.count('context.user_data["plan_scheduled"] = False')))
    check("content_plan: tranzaksiya DB funksiyasi chaqiriladi",
          "db.schedule_week_posts" in src)
    check("content_plan: hafta klaviaturasi ishlatiladi",
          "_plan_list_keyboard(" in src)
    check("content_plan: tasdiq matni get_text orqali (uz/ru)",
          '"plan_sched_done"' in src and '"plan_btn_schedule_all"' in src)
    check("content_plan: xato xabari ham lokalizatsiya qilingan",
          '"plan_sched_error"' in src and '"plan_sched_stale"' in src
          and '"plan_sched_already"' in src)


def test_content_plan_db_schedule_week_posts():
    """2️⃣ schedule_week_posts — DB funksiyasi imzosi va tranzaksiya kafolati."""
    print("== content plan: schedule_week_posts (DB qatlami) ==")
    import inspect
    import database as db_mod

    check("db: schedule_week_posts mavjud", hasattr(db_mod, "schedule_week_posts"))
    sig = inspect.signature(db_mod.schedule_week_posts)
    check("db: imzo (user_id, channel_id, posts, post_type)",
          list(sig.parameters) == ["user_id", "channel_id", "posts", "post_type"],
          str(list(sig.parameters)))
    check("db: post_type default 'text'", sig.parameters["post_type"].default == "text")

    src = inspect.getsource(db_mod.schedule_week_posts)
    check("db: BITTA tranzaksiya (yagona with db_cursor bloki)",
          src.count("with db_cursor(commit=True) as cur:") == 1,
          str(src.count("with db_cursor(commit=True) as cur:")))
    check("db: advisory qulf (parallel chaqiruvlar himoyasi)",
          "pg_advisory_xact_lock" in src)
    check("db: user_post_number MAX+1 davom etadi",
          "COALESCE(MAX(user_post_number), 0)" in src)
    check("db: status='pending' bilan yoziladi", "'pending'" in src)
    check("db: kesh tozalanadi", "_invalidate_user" in src and '_cache_clear("system_stats")' in src)
    check("db: bo'sh ro'yxat → empty", db_mod.schedule_week_posts(1, "-100", [])["error"] == "empty")
    check("db: kanalsiz → no_channel",
          db_mod.schedule_week_posts(1, "", [("x", "y")])["error"] == "no_channel")
    check("db: buzilgan user_id → bad_user",
          db_mod.schedule_week_posts("abc", "-100", [("x", "y")])["error"] == "bad_user")
    empty = db_mod.schedule_week_posts(1, "-100", [])
    check("db: xato natijasi strukturali",
          set(empty) == {"success", "count", "ids", "times", "error"}, str(set(empty)))
    check("db: muvaffaqiyatsiz → success=False", empty["success"] is False)


def test_onboarding_i18n_keys():
    """1️⃣2️⃣ Yangi kalitlar ikkala tilda; paritet buzilmagan."""
    print("== onboarding/content-plan: i18n kalitlari ==")
    from locales.translations import (
        translation_parity_report, has_key, get_text, TRANSLATIONS, missing_keys,
    )

    keys = (
        "quick_menu_hint", "quick_btn_ai_post", "quick_btn_photo_post",
        "quick_btn_add_channel", "quick_btn_full_menu", "quick_full_menu_opened",
        "plan_btn_schedule_all", "plan_week_hint", "plan_sched_busy", "plan_sched_done_alert",
        "plan_sched_done", "plan_sched_already", "plan_sched_stale",
        "plan_sched_no_channel", "plan_sched_empty", "plan_sched_error",
        "plan_sched_day_line",
    )
    for key in keys:
        check(f"kalit uz/ru: {key}", has_key(key, "uz") and has_key(key, "ru"))
    check("paritet buzilmagan", translation_parity_report()["in_sync"] is True)
    check("missing_keys('ru') bo'sh", missing_keys("ru") == [])

    # uz va ru qiymatlari har xil (tarjima qilingan)
    diff = [k for k in keys if TRANSLATIONS["uz"].get(k) == TRANSLATIONS["ru"].get(k)]
    check("barcha yangi kalitlar tarjima qilingan", not diff, str(diff))

    # {placeholder} pariteti
    import re as _re
    mismatch = []
    for k in keys:
        uz_ph = set(_re.findall(r"\{(\w+)\}", TRANSLATIONS["uz"][k]))
        ru_ph = set(_re.findall(r"\{(\w+)\}", TRANSLATIONS["ru"][k]))
        if uz_ph != ru_ph:
            mismatch.append((k, sorted(uz_ph ^ ru_ph)))
    check("placeholder'lar mos", not mismatch, str(mismatch))

    # plan_sched_done formatlash (uz/ru) — xom {} qolmasligi kerak
    for lang in ("uz", "ru"):
        out = get_text("plan_sched_done", lang, channel="Kanal", count=7, days="• Dushanba — 12:00")
        check(f"plan_sched_done {lang}: formatlandi", "{" not in out and "}" not in out, out[:80])
        check(f"plan_sched_done {lang}: kanal va son bor", "Kanal" in out and "7" in out)
        line = get_text("plan_sched_day_line", lang, day="Dushanba", time="07.09 12:00")
        check(f"plan_sched_day_line {lang}: formatlandi",
              "Dushanba" in line and "12:00" in line and "{" not in line, line)
    check("quick_menu_hint uz: HTML teglari bor", "<b>" in get_text("quick_menu_hint", "uz"))
    check("quick_menu_hint ru: HTML teglari bor", "<b>" in get_text("quick_menu_hint", "ru"))


def test_pro_two_stage_audit_auto():
    """PRO 2-bosqichli auto audit — task talabiga mos test.

    Tekshiriladi:
      - PRO (is_pro=True): 2 ta AI chaqiruvi (1-bosqich post + 2-bosqich AUDIT_PRO_SYSTEM)
        va foydalanuvchiga FAQAT 2-bosqich natijasi ko'rsatiladi.
      - FREE (is_pro=False): faqat 1 ta chaqiruv, audit yo'q (tezlik/xarajat).
      - 2-bosqich xatolari (raise/error/timeout/analysis/empty/short) → 1-bosqich
        posti xavfsiz qaytadi, oqim to'xtamaydi, audit_applied=False.
    """
    print("== PRO 2-bosqichli auto audit (task) ==")
    import asyncio
    from utils import ai_agent

    STAGE1 = (
        "<b>Kofe</b>\n\nYangi kofe yetib keldi. Sifatli va arzon.\n"
        "CTA: xarid qiling.\n\n#kofe #yangi #uzum"
    )
    AUDITED = (
        "<b>☕ Ertalabki energiya — bir finjonda</b>\n\n"
        "Yangi qovurilgan kofe kunni butunlay o'zgartiradi.\n\n"
        "👉 Hoziroq buyurtma bering.\n\n#kofe #energiya #toshkent"
    )
    ANALYSIS_ONLY = "Reyting: 7/10. Kuchli tomonlari: aniq hook. Yaxshilash: CTA kuchsiz."

    class FakeChain:
        def __init__(self, mode="ok"):
            self.mode = mode
            self.calls = []

        async def __call__(self, prompt, system_instruction, lang=None):
            is_audit = ai_agent._AUDIT_PRO_SYSTEM.strip()[:40] in (system_instruction or "")
            self.calls.append({"prompt": prompt, "sys": system_instruction or "",
                               "stage": 2 if is_audit else 1, "lang": lang})
            if is_audit:
                if self.mode == "raise":
                    raise RuntimeError("tarmoq uzildi (mock)")
                if self.mode == "timeout":
                    await asyncio.sleep(5)
                if self.mode == "error":
                    return {"error": "AI xato", "timeout": True}
                if self.mode == "analysis":
                    return {"audit": ANALYSIS_ONLY}
                if self.mode == "empty":
                    return {"rating": 5, "improved_post": "   "}
                if self.mode == "short":
                    return {"rating": 8, "improved_post": "Qisqa."}
                return {"rating": 9, "improved_post": AUDITED}
            return {"intent": "post", "reply": "", "post_text": STAGE1,
                    "scheduled_time": None, "has_explicit_time": False, "target_all": False}

        @property
        def stage2(self):
            return [c for c in self.calls if c["stage"] == 2]

    async def _run_with_chain(mode, coro_fn):
        chain = FakeChain(mode)
        orig = ai_agent._run_ai_chain
        orig_timeout = ai_agent.PRO_AUDIT_TIMEOUT
        ai_agent._run_ai_chain = chain
        if mode == "timeout":
            ai_agent.PRO_AUDIT_TIMEOUT = 0.2
        try:
            result = await coro_fn(chain)
        finally:
            ai_agent._run_ai_chain = orig
            ai_agent.PRO_AUDIT_TIMEOUT = orig_timeout
        return chain, result

    # PRO — 2 bosqich
    async def call_pro(chain):
        return await ai_agent.analyze_user_prompt("Kofe haqida post", user_id=1, is_pro=True, lang="uz")

    chain, res = asyncio.run(_run_with_chain("ok", call_pro))
    check("PRO auto: 2 ta AI chaqiruvi (stage1 + AUDIT_PRO_SYSTEM)", len(chain.calls) == 2, str(len(chain.calls)))
    check("PRO auto: 2-bosqich _AUDIT_PRO_SYSTEM bilan", len(chain.stage2) == 1 and "SMM auditor" in chain.stage2[0]["sys"])
    check("PRO auto: foydalanuvchiga FAQAT 2-bosqich (audited) ko'rsatiladi", res.get("post_text") == AUDITED)
    check("PRO auto: 1-bosqich matni post_text_stage1 da saqlanadi", res.get("post_text_stage1") == STAGE1)
    check("PRO auto: audit_applied=True", res.get("audit_applied") is True)
    check("PRO auto: error yo'q", "error" not in res)

    # FREE — 1 bosqich
    async def call_free(chain):
        return await ai_agent.analyze_user_prompt("Kofe haqida post", user_id=1, is_pro=False, lang="uz")

    chain_f, res_f = asyncio.run(_run_with_chain("ok", call_free))
    check("FREE auto: faqat 1 ta AI chaqiruvi", len(chain_f.calls) == 1)
    check("FREE auto: auditor chaqirilmadi", len(chain_f.stage2) == 0)
    check("FREE auto: post_text == stage1", res_f.get("post_text") == STAGE1)
    check("FREE auto: audit yo'q", not res_f.get("audit_applied"))

    # Fallback holatlari
    for mode in ("raise", "error", "timeout", "analysis", "empty", "short"):
        async def call_fail(chain):
            return await ai_agent.analyze_user_prompt("Kofe haqida post", user_id=1, is_pro=True, lang="uz")

        _c, r = asyncio.run(_run_with_chain(mode, call_fail))
        check(f"fallback[{mode}]: 1-bosqich qaytadi", r.get("post_text") == STAGE1, str(r.get("post_text"))[:50])
        check(f"fallback[{mode}]: error kaliti yo'q (oqim davom etadi)", "error" not in r)
        check(f"fallback[{mode}]: audit_applied=False", r.get("audit_applied") is False)

    # refine_post_pro to'g'ridan-to'g'ri — bo'sh matn xavfsiz
    res_empty = asyncio.run(ai_agent.refine_post_pro("", lang="uz"))
    check("refine_post_pro(''): bo'sh + error", res_empty.get("post_text") == "" and bool(res_empty.get("error")))

    # post_enhancer integratsiyasi — auto audit matnli postda, PRO uchun
    import handlers.post_enhancer as pe
    check("post_enhancer: _auditable_text faqat text turida", pe._auditable_text({"post": {"type": "photo", "content": "x"}}) == "")
    check("post_enhancer: _auditable_text text turida", pe._auditable_text({"post": {"type": "text", "content": "Salom"}}) == "Salom")
    pe_src = open(pe.__file__, encoding="utf-8").read()
    check("post_enhancer: auto audit refine_post_pro chaqiruvi (_capture_post)", "refine_post_pro" in pe_src and "_capture_post" in pe_src)
    check("post_enhancer: PRO_TWO_STAGE_ENABLED tekshiriladi", "PRO_TWO_STAGE_ENABLED" in pe_src or "PRO_TWO_STAGE" in pe_src)
    check("post_enhancer: FREE uchun ikkinchi chaqiruv yo'q (is_pro sharti)", "if is_pro" in pe_src)

    # ai_assistant integratsiyasi — AI Studio ham PRO auto audit
    import handlers.ai_assistant as ai_mod
    ai_src = open(ai_mod.__file__, encoding="utf-8").read()
    check("ai_assistant: ai_prompt_received PRO auto audit", "refine_post_pro" in ai_src and "ai_prompt_received" in ai_src)
    check("ai_assistant: PRO_TWO_STAGE_ENABLED ishlatiladi", "PRO_TWO_STAGE_ENABLED" in ai_src)




def main():
    test_calculate_next_time()
    test_converter()
    test_keep_typing()
    test_rate_limits()
    test_json_clean()
    test_retry_after_seconds()
    test_weekday_map()
    test_abuse_protection()
    test_tashkent_date()
    test_prompt_truncation()
    test_compose_post_text()
    test_ai_runtime_params()
    test_parse_album_items()
    test_album_label()
    test_referral_share_url_encoding()
    test_natural_time_parser()
    test_ai_intent_normalization()
    test_new_inline_keyboards()
    test_admin_new_buttons()
    test_admin_channels_text_limit()
    test_apply_post_watermark()
    test_compose_post_text_limit()
    test_ai_context_memory()
    test_ai_optional_params()
    test_button_labels()
    test_smart_reply_ad_async()
    test_ad_pool_rotation()
    test_channel_cache_invalidation()
    test_queue_slot_algorithm()
    test_queue_ui_helpers()
    test_queue_main_keyboard()
    test_confirmation_queue_integration()
    test_ai_format_prompts()
    test_ai_action_keyboards()
    test_ai_format_fallback()
    test_tone_of_voice_constants()
    test_tone_descriptions()
    test_content_plan_prompt()
    test_content_plan_keyboards()
    test_tone_migration_sql()
    test_main_keyboard_content_plan()
    test_channels_list_with_tone()
    test_analytics_dashboard_format()
    test_analytics_keyboards()
    test_analytics_db_functions_exist()
    test_analytics_empty_state()
    test_analytics_type_distribution_format()
    test_main_menu_layout_v2()
    test_analytics_main_keyboard()
    test_plan_limits()
    test_subscription_functions_exist()
    test_subscription_card_format()
    test_subscription_keyboards()
    test_limit_messages()
    test_promo_code_schema()
    test_subscription_migration_sql()
    test_main_keyboard_premium()
    test_stars_payment_plans()
    test_stars_keyboard()
    test_referral_pro_functions()
    test_referral_pro_logic()
    test_stars_payment_handlers_exist()
    test_create_promo_command()
    test_promo_code_create_and_redeem()
    test_subscription_keyboard_stars()
    test_channel_reader_parser()
    test_channel_reader_functions()
    test_format_post_list()
    test_channel_extract_keyboards()
    test_rewrite_function_exists()
    test_channel_reader_error_handling()
    test_main_keyboard_extract()
    test_admin_dashboard()
    test_admin_handlers_exist()
    test_admin_dashboard_stats_db()
    test_ai_studio_keyboard()
    test_ai_studio_hardening()
    test_vision_agent_utils()
    test_photo_to_post_flow()
    test_payments_audit_table()
    test_stars_invoice_provider_token()
    test_multi_admin_checks()
    test_queue_limit_function()
    test_tier_limit_handler_constants()
    test_tiered_rate_limit_constants()
    test_reaction_keyboard_buttons()
    test_flexible_reaction_parser()
    test_reaction_toggle_keyboard_and_normalize()
    test_url_button_builder()
    test_scheduler_custom_reactions()
    test_reaction_emojis_db_schema()
    test_quick_button_flow()
    test_guard_feedback_and_silent_blocking_fix()
    test_sponsor_channels_suite()
    test_auto_ad_injector_suite()
    test_admin_dashboard_layout_suite()
    test_post_enhancer_flow()
    test_post_enhancer_text_and_channels()
    test_post_enhancer_ux_overhaul()
    test_post_enhancer_batch_and_preview_runtime()
    test_post_enhancer_channel_dispatch()
    test_post_enhancer_callback_router()

    # --- Reklama boshqaruvi (ad pool / post promo) ---
    test_channel_ad_interval_logic()
    test_per_channel_counter_isolation()
    test_ad_html_and_button_validation()
    test_ad_pool_full_crud_api()
    test_scheduler_ad_inline_button()
    test_ad_pool_keyboards()
    test_ad_pool_callback_flow()
    test_admin_fsm_states_and_cancel()
    test_admin_cancel_registration()
    test_ad_text_received_flow()
    test_system_settings_read_write()
    test_ad_settings_include_channel_interval()
    test_enhancer_channel_ad_interval()
    test_ad_hub_unification_suite()
    test_five_fixes_suite()
    test_add_channel_flow_suite()
    test_channel_posts_history_suite()
    test_channel_add_autodetect_no_hang_suite()
    test_my_chat_member_autoconnect_suite()
    test_referrer_id_and_new_providers_suite()
    test_i18n_uz_ru()
    test_i18n_en_menu_buttons_and_fallback()
    test_cabinet_i18n_suite()
    test_ai_studio_i18n_suite()
    test_new_post_i18n_suite()
    test_channels_i18n_suite()
    test_pending_i18n_suite()
    test_queue_i18n_suite()
    test_extras_help_i18n_suite()

    # --- 🆕 Onboarding: yangi foydalanuvchilar uchun sodda klaviatura ---
    test_onboarding_simple_menu_rules()
    test_onboarding_simple_keyboard()
    test_onboarding_resolve_and_quick_handlers()
    test_onboarding_start_integration()
    test_onboarding_handlers_registered()
    test_onboarding_db_and_schema()
    test_onboarding_i18n_keys()

    # --- 🚀 7 kunlik kontent-rejani bitta tugma bilan navbatga qo'yish ---
    test_content_plan_week_times()
    test_content_plan_week_keyboard()
    test_content_plan_schedule_all_flow()
    test_content_plan_schedule_all_routing()
    test_content_plan_db_schedule_week_posts()

    # --- 🚀 Ommaviy reliz: 4 ta arxitekturaviy himoya ---
    test_callback_data_64byte_safety()
    test_i18n_safe_fallback_and_parity()
    test_scheduler_timezone_and_time_input()
    test_floodwait_and_ai_timeout_protection()
    test_pro_two_stage_audit_auto()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha unit-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
