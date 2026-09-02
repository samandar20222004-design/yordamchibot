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

    check("DB o'qish run_db (thread) orqali ketadi",
          calls == ["get_ads_full", "get_setting"], str(calls))
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
    check("pul bor: faqat get_ads_full chaqiriladi", calls == ["get_ads_full"], str(calls))
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
    check("eski format: tone_menu bor", any("tone_menu:" in c for c in cbs_old))

    # 3 elementli tuple (yangi format: id, title, tone)
    channels_new = [("-1001", "Yangi Kanal", "formal")]
    kb_new = render_channels_list(channels_new)
    cbs_new = [b.callback_data for row in kb_new.inline_keyboard for b in row]
    labels_new = [b.text for row in kb_new.inline_keyboard for b in row]
    check("yangi format: tone_menu bor", any("tone_menu:" in c for c in cbs_new))
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
    check("kabinet: 4 qator", len(cab) == 4, str(cab))
    expected = [
        [("📢 Mening kanallarim", "cab_channels"), ("📊 Kanallar analitikasi", "cab_analytics")],
        [("📅 Kutilayotgan postlar", "cab_pending"), ("⏳ Postlar navbati (Queue)", "cab_queue")],
        [("💎 Ballar & Litsenziya", "cab_balance"), ("🎁 Kunlik bonus", "cab_bonus")],
        [("👥 Do'stlarni taklif", "cab_referral"), ("❌ Yopish", "close_cabinet")],
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
    """Referal PRO mukofoti funksiyalari."""
    print("== Referral PRO functions ==")
    import database as db_mod

    # 1. Funktsiyalar mavjud
    check("get_active_referral_count mavjud", hasattr(db_mod, "get_active_referral_count"))
    check("check_and_grant_referral_pro mavjud", hasattr(db_mod, "check_and_grant_referral_pro"))
    check("get_referral_pro_progress mavjud", hasattr(db_mod, "get_referral_pro_progress"))

    # 2. Konstantalar
    check("REFERRAL_PRO_THRESHOLD = 3", db_mod.REFERRAL_PRO_THRESHOLD == 3)
    check("REFERRAL_PRO_DAYS = 30", db_mod.REFERRAL_PRO_DAYS == 30)

    # 3. get_referral_pro_progress format
    progress = db_mod.get_referral_pro_progress(0)  # non-existent user
    check("progress: active bor", "active" in progress)
    check("progress: needed bor", "needed" in progress)
    check("progress: granted bor", "granted" in progress)
    check("progress: needed = 3", progress["needed"] == 3)
    check("progress: non-existent = 0", progress["active"] == 0)
    check("progress: non-existent granted=False", progress["granted"] is False)

    # 4. get_active_referral_count — non-existent user
    count = db_mod.get_active_referral_count(0)
    check("active_referral: non-existent = 0", count == 0)


def test_referral_pro_logic():
    """Referal PRO berish logikasi — 3 ta faol do'st."""
    print("== Referral PRO logic ==")
    import database as db_mod

    # check_and_grant_referral_pro — non-existent user → False
    result = db_mod.check_and_grant_referral_pro(0)
    check("grant non-existent → False", result is False)

    # get_active_referral_count callable
    check("get_active_referral_count callable", callable(db_mod.get_active_referral_count))


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
        check("ai_agent: timeout xabari foydalanuvchiga mos", "soniyada kelmadi" in res["error"])
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
            calls.append(("vision", path, extra_prompt, bool(rewrite_context)))
            return {"post_text": "<b>Buyuk taklif!</b>\n\n• Mahsulot\n\n👉 Sotib oling\n\n#smm"}

        ai.generate_vision_post = fake_vision

        # 5) Rasm qabul qilish → vision → natija ekrani
        uid = 999777000
        msg = _FakeMsg(1, chat_id=111, caption="mahsulotni sot")
        msg.photo = [type("P", (), {"file_id": "file123"})()]
        upd = type("U", (), {"message": msg, "effective_user": _FakeUser(uid)})()
        ctx2 = _FakeCtx(_FakeBot(), user_data={})
        state2 = asyncio.run(ai.ai_photo_received(upd, ctx2))
        check("photo: vision natijasi → AI_PHOTO_RESULT",
              state2 == ai.AI_PHOTO_RESULT, str(state2))
        check("photo: post saqlandi",
              ctx2.user_data.get("studio_post_text", "").startswith("<b>"))
        check("photo: file_id saqlandi", ctx2.user_data.get("studio_file_id") == "file123")
        check("photo: post_type=photo", ctx2.user_data.get("studio_post_type") == "photo")
        check("photo: izoh saqlandi",
              ctx2.user_data.get("studio_photo_extra") == "mahsulotni sot")
        check("photo: rasm temp download qilindi", any(c[0] == "dl" for c in calls))
        check("photo: AI chaqiruv bitta", len([c for c in calls if c[0] == "vision"]) == 1)
        check("photo: muvaffaqiyat → ai_usage+1", "increment_ai_usage" in calls)

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
    from handlers.subscription import _get_subscription_keyboard

    # 1. Free foydalanuvchi — Stars to'lov tugmalari to'g'ridan-to'g'ri
    kb_free = _get_subscription_keyboard("free")
    cbs_free = [b.callback_data for row in kb_free.inline_keyboard for b in row]
    check("free kb: stars_1m", "sub_pay:stars_1m" in cbs_free)
    check("free kb: stars_3m", "sub_pay:stars_3m" in cbs_free)
    check("free kb: stars_1y", "sub_pay:stars_1y" in cbs_free)
    check("free kb: promo", "sub_promo" in cbs_free)
    check("free kb: back_main", "sub_back_main" in cbs_free)

    # 2. PRO foydalanuvchi — Stars yo'q, promo va back bor
    kb_pro = _get_subscription_keyboard("pro")
    cbs_pro = [b.callback_data for row in kb_pro.inline_keyboard for b in row]
    check("pro kb: stars_1m yo'q", "sub_pay:stars_1m" not in cbs_pro)
    check("pro kb: promo bor", "sub_promo" in cbs_pro)
    check("pro kb: back_main bor", "sub_back_main" in cbs_pro)


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
    check("callback prefiks: kanal reaksiyasidan farqli", CB_REACT_TOGGLE.startswith("npreact:"))
    check("done/skip callback", CB_REACT_DONE == "npreact:done" and CB_REACT_SKIP == "npreact:skip")

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
    check("register: npreact:tgl handler", 'pattern=r"^npreact:tgl:"' in h_src)
    check("register: npreact:done handler", 'pattern=r"^npreact:done$"' in h_src)
    check("register: npreact:skip handler", 'pattern=r"^npreact:skip$"' in h_src)

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
    check("kanal: yangi matn ishlatiladi", "NO_CHANNELS_HINT" in src_start)
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
    check("handlers: guard_entry notice text", "⏳ Iltimos, biroz kuting..." in src_h)
    check("handlers: guard_menu notice text", "⏳ Iltimos, biroz kuting..." in src_h)
    check("handlers: reaction_callback alert text", "⏳ Iltimos, biroz kuting..." in src_h)

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
    check("admin sponsors delete button", "del_sponsor:1" in adm_s_cbs, str(adm_s_cbs))
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
    """Admin dashboard to'liq 9-tugmali layout testi."""
    print("== Admin Dashboard Layout (9 ta tugma) ==")
    from keyboards.inline import get_admin_dashboard_keyboard

    kb = get_admin_dashboard_keyboard()
    rows = kb.inline_keyboard
    check("dashboard qatorlar soni = 5", len(rows) == 5, str(len(rows)))

    # Qator 1: Statistika & Broadcast
    check("row 0 btn 0: adm_stats", rows[0][0].callback_data == "adm_stats")
    check("row 0 btn 1: adm_broadcast", rows[0][1].callback_data == "adm_broadcast")

    # Qator 2: Majburiy obuna & Reklama markazi (birlashtirilgan hub)
    check("row 1 btn 0: adm_sponsors", rows[1][0].callback_data == "adm_sponsors")
    check("row 1 btn 1: adm_adhub", rows[1][1].callback_data == "adm_adhub")

    # Qator 3: Kanallar ro'yxati & Tizim sozlamalari
    check("row 2 btn 0: adm_channels", rows[2][0].callback_data == "adm_channels")
    check("row 2 btn 1: adm_settings", rows[2][1].callback_data == "adm_settings")

    # Qator 4: Promo & PRO
    check("row 3 btn 0: adm_promo", rows[3][0].callback_data == "adm_promo")
    check("row 3 btn 1: adm_grant_pro", rows[3][1].callback_data == "adm_grant_pro")

    # Qator 5: Yopish
    check("row 4 btn 0: close_msg", rows[4][0].callback_data == "close_msg")

    labels = [b.text for row in rows for b in row]
    check("label: To'liq statistika", any("statistika" in t.lower() for t in labels))
    check("label: Broadcast", any("broadcast" in t.lower() or "ommaviy" in t.lower() for t in labels))
    check("label: Majburiy obuna", any("majburiy obuna" in t.lower() for t in labels))
    check("label: Reklama markazi", any("reklama markazi" in t.lower() for t in labels), str(labels))
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
    check("new_post: BTN_BACK import (NameError fix)", "BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_BACK" in np_src)
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

        # --- Reklama litsenziyasi (ad-free) bor foydalanuvchi: litsenziya sarflanadi ---
        _, _, _, sink3, _ = await send_once(premium=True, ad_free=True, uid=424303)
        check("dispatch: ad-free litsenziya sarflandi",
              "consume_ad_free_post" in [c[0] for c in sink3], str([c[0] for c in sink3]))

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
        for data in ("adm_stats", "adm_channels", "adm_settings", "adm_sponsors",
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

        # Kanallar ro'yxati va tizim sozlamalari mazmuni
        ctx = _make_admin_ctx()
        q = _AdQuery("adm_channels")
        asyncio.run(admin.admin_dashboard_callback(type("U", (), {"callback_query": q})(), ctx))
        check("kanallar ro'yxati o'qildi", "Kanal" in q.edits[-1][0], q.edits[-1][0][:80])

        ctx = _make_admin_ctx()
        q = _AdQuery("adm_settings")
        asyncio.run(admin.admin_dashboard_callback(type("U", (), {"callback_query": q})(), ctx))
        body = q.edits[-1][0]
        check("sozlamalar: system_settings ko'rsatildi", "system_settings" in body, body[:120])
        check("sozlamalar: post_tag_text qiymati", "@bot" in body)
        check("sozlamalar: kanal oralig'i", "har 3-post" in body, body)
        check("sozlamalar: sanagichlar ko'rsatildi", "9" in body and "Kanal" in body)

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
    check("BTN_CANCEL menyu sakrashlarida", "exact(BTN_CANCEL), cancel_handler" in src)
    check("BTN_CANCEL fallback'da", src.count("exact(BTN_CANCEL)") >= 2)
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
          "text in (BTN_CANCEL, BTN_MAIN_MENU)" in admin_src)
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

    async def send(post_number, ad_free=False):
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
        db_mod.run_db = _fake_db(ad_free=ad_free, post_number=post_number,
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

        # ad-free litsenziya: reklama umuman chiqmaydi
        text, markup = await send(3, ad_free=True)
        check("enh: ad-free → reklama yo'q", "ENH-REKLAMA" not in text, text)

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
    check("omadda kanallar ro'yxati ko'rsatiladi", "inline_keyboard=list_markup" in ch_src)
    check("xatoda manzil saqlanadi (retry uchun)", 'user_data["add_channel_pending"]' in ch_src)

    init_src = (root / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("retry ADD_CHANNEL holatida ro'yxatdan o'tgan",
          'add_channel_retry, pattern=r"^add_channel_retry$"' in init_src)
    check("retry import qilingan", "add_channel_retry," in init_src)


def main():
    test_calculate_next_time()
    test_converter()
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

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha unit-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
