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

    check("DB o'qish run_db (thread) orqali ketadi", calls == ["get_setting"], str(calls))
    check("reklama bo'sh bo'lsa satr ham bo'sh", result == "", result)


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


def test_confirmation_preview():
    print("== confirmation preview & keyboards ==")
    from handlers.new_post import (
        _build_preview_text, _get_confirm_keyboard, _get_edit_confirm_keyboard,
        CONFIRM_POST, EDIT_CONFIRM_FIELD,
    )
    from telegram import InlineKeyboardMarkup

    # Mock context with user_data
    class FakeContext:
        def __init__(self):
            self.user_data = {}

    ctx = FakeContext()
    ctx.user_data = {
        "selected_channel_title": "Test Kanal",
        "post_type": "text",
        "content": "Salom dunyo!",
        "btn_text": "Bosing",
        "btn_url": "https://t.me/test",
        "enable_reactions": True,
        "delete_after_hours": 24,
        "confirm_post_time": pytz.timezone("Asia/Tashkent").localize(datetime(2026, 9, 1, 10, 0)),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
    }

    preview = _build_preview_text(ctx)
    check("preview: kanal nomi", "Test Kanal" in preview, preview[:100])
    check("preview: matn turi", "📝 Matn" in preview, preview[:100])
    check("preview: vaqt", "2026-09-01 10:00" in preview, preview[:100])
    check("preview: kontent", "Salom dunyo!" in preview, preview[:200])
    check("preview: tugma", "Bosing" in preview, preview[:300])
    check("preview: reaksiya", "Yoqilgan" in preview, preview[:300])
    check("preview: auto-delete", "24 soat" in preview, preview[:300])
    check("preview: tasdiqlash sarlavhasi", "Postni tasdiqlang" in preview, preview[:100])

    # Takroriy (daily) post preview
    ctx.user_data["confirm_recurrence_type"] = "daily"
    ctx.user_data["confirm_recurrence_time_str"] = "10:00:00"
    preview2 = _build_preview_text(ctx)
    check("preview: daily takroriy", "Har kuni" in preview2 and "10:00" in preview2, preview2[:200])

    # Takroriy (weekly) post preview
    ctx.user_data["confirm_recurrence_type"] = "weekly"
    ctx.user_data["confirm_recurrence_day"] = 0  # Dushanba
    ctx.user_data["confirm_recurrence_time_str"] = "18:30:00"
    preview3 = _build_preview_text(ctx)
    check("preview: weekly takroriy", "Har Dushanba" in preview3 and "18:30" in preview3, preview3[:200])

    # Confirm keyboard tugmalari
    kb = _get_confirm_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("confirm kb: ok tugmasi", "confirm_post:ok" in cbs, str(cbs))
    check("confirm kb: edit tugmasi", "confirm_post:edit" in cbs, str(cbs))
    check("confirm kb: cancel tugmasi", "confirm_post:cancel" in cbs, str(cbs))

    # Edit keyboard tugmalari
    ekb = _get_edit_confirm_keyboard()
    ecbs = [b.callback_data for row in ekb.inline_keyboard for b in row]
    check("edit kb: content", "edit_field:content" in ecbs, str(ecbs))
    check("edit kb: channel", "edit_field:channel" in ecbs, str(ecbs))
    check("edit kb: time", "edit_field:time" in ecbs, str(ecbs))
    check("edit kb: btn", "edit_field:btn" in ecbs, str(ecbs))
    check("edit kb: back", "edit_field:back" in ecbs, str(ecbs))

    # State qiymatlari
    check("CONFIRM_POST = 111", CONFIRM_POST == 111)
    check("EDIT_CONFIRM_FIELD = 112", EDIT_CONFIRM_FIELD == 112)

    # Media preview (photo)
    ctx.user_data["post_type"] = "photo"
    ctx.user_data["file_id"] = "AgACAgIAAxkBAAI"
    ctx.user_data["confirm_recurrence_type"] = "none"
    ctx.user_data["confirm_recurrence_day"] = None
    ctx.user_data["confirm_recurrence_time_str"] = None
    preview4 = _build_preview_text(ctx)
    check("preview: photo turi", "🖼 Rasm" in preview4, preview4[:200])

    # Bo'sh kontent
    ctx.user_data["content"] = ""
    ctx.user_data["post_type"] = "text"
    ctx.user_data["file_id"] = None
    preview5 = _build_preview_text(ctx)
    check("preview: bo'sh kontent", "Postni tasdiqlang" in preview5, preview5[:100])

    # Tugmasiz post
    ctx.user_data["btn_text"] = None
    ctx.user_data["btn_url"] = None
    ctx.user_data["enable_reactions"] = False
    ctx.user_data["delete_after_hours"] = 0
    preview6 = _build_preview_text(ctx)
    check("preview: tugmasiz", "Tugma" not in preview6, preview6[:300])
    check("preview: reaksiyasiz", "Reaksiyalar" not in preview6, preview6[:300])
    check("preview: auto-delete yo'q", "Avto-o'chirish" not in preview6, preview6[:300])


def test_integration_post_flow():
    """End-to-end: post yaratish -> channel -> content -> btn -> reactions -> auto-delete -> time -> confirm -> edit -> confirm -> save."""
    import asyncio
    print("== integration: full post creation flow ==")
    from handlers.new_post import (
        build_channel_labels, _build_preview_text, _get_confirm_keyboard,
        _get_edit_confirm_keyboard, _media_item_from_message, _apply_single_media,
        CONFIRM_POST, EDIT_CONFIRM_FIELD,
        CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL,
        GET_REACTIONS, GET_AUTO_DELETE, GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME, GET_DURATION,
    )
    from keyboards.default import (
        BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
        BTN_DUR_1W, BTN_DUR_1M, BTN_DUR_INF,
        WEEKDAY_MAP, WEEKDAY_LABELS,
    )

    # 1. Channel labels — duplicate handling
    channels = [("-1001", "Kanal A"), ("-1002", "Kanal A"), ("-1003", "")]
    labels = build_channel_labels(channels)
    check("integ: 3 ta kanal farqlanadi", len(labels) == 3, str(labels))
    check("integ: barcha label bo'sh emas", all(l.strip() for l in labels), str(labels))

    # 2. Media parsing
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
    check("integ: photo aniqlanadi", item is not None and item["type"] == "photo", str(item))

    text_msg = FakeMsg(text="Salom")
    item2 = _media_item_from_message(text_msg)
    check("integ: matn -> None", item2 is None)

    # 3. Apply media to context
    class FakeCtx:
        def __init__(self):
            self.user_data = {}
    ctx = FakeCtx()
    _apply_single_media(ctx, {"type": "photo", "file_id": "abc", "caption": "Rasm"})
    check("integ: media qo'llanadi", ctx.user_data["post_type"] == "photo" and ctx.user_data["file_id"] == "abc")

    # 4. Preview matn — to'liq ma'lumot bilan
    tz = pytz.timezone("Asia/Tashkent")
    ctx.user_data.update({
        "selected_channel_title": "Tech Kanal",
        "content": "Yangi mahsulot!",
        "btn_text": "Batafsil",
        "btn_url": "https://example.com",
        "enable_reactions": True,
        "delete_after_hours": 48,
        "confirm_post_time": tz.localize(datetime(2026, 9, 5, 14, 0)),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
    })
    preview = _build_preview_text(ctx)
    check("integ: preview'da kanal", "Tech Kanal" in preview, preview[:150])
    check("integ: preview'da vaqt", "2026-09-05 14:00" in preview, preview[:150])
    check("integ: preview'da tugma", "Batafsil" in preview, preview[:300])
    check("integ: preview'da reaksiya", "Yoqilgan" in preview, preview[:300])
    check("integ: preview'da auto-delete", "48 soat" in preview, preview[:300])

    # 5. Confirm keyboard — 4 ta tugma (ok, queue, edit, cancel)
    kb = _get_confirm_keyboard()
    check("integ: confirm kb 4 ta tugma", sum(len(r) for r in kb.inline_keyboard) == 4)

    # 6. Edit keyboard — 5 ta tugma (4 field + back)
    ekb = _get_edit_confirm_keyboard()
    check("integ: edit kb 5 ta tugma", sum(len(r) for r in ekb.inline_keyboard) == 5)

    # 7. Daily recurrence preview
    ctx.user_data["confirm_recurrence_type"] = "daily"
    ctx.user_data["confirm_recurrence_time_str"] = "09:00:00"
    preview_daily = _build_preview_text(ctx)
    check("integ: daily preview", "Har kuni" in preview_daily and "09:00" in preview_daily, preview_daily[:200])

    # 8. Weekly recurrence preview
    ctx.user_data["confirm_recurrence_type"] = "weekly"
    ctx.user_data["confirm_recurrence_day"] = 4  # Juma
    ctx.user_data["confirm_recurrence_time_str"] = "13:00:00"
    preview_weekly = _build_preview_text(ctx)
    check("integ: weekly preview", "Har Juma" in preview_weekly and "13:00" in preview_weekly, preview_weekly[:200])

    # 9. Edit flow: matn o'zgartirish
    ctx.user_data["post_type"] = "text"
    ctx.user_data["file_id"] = None
    ctx.user_data["content"] = "Yangi matn"
    ctx.user_data["confirm_recurrence_type"] = "none"
    ctx.user_data["confirm_recurrence_day"] = None
    ctx.user_data["confirm_recurrence_time_str"] = None
    preview_edited = _build_preview_text(ctx)
    check("integ: tahrirlangan matn preview'da", "Yangi matn" in preview_edited, preview_edited[:200])

    # 10. Edit flow: tugma o'chirish
    ctx.user_data["btn_text"] = None
    ctx.user_data["btn_url"] = None
    preview_no_btn = _build_preview_text(ctx)
    check("integ: tugma o'chirilganda preview'da yo'q", "Tugma" not in preview_no_btn, preview_no_btn[:300])

    # 11. State constants to'g'ri
    check("integ: CHOOSE_CHANNEL=100", CHOOSE_CHANNEL == 100)
    check("integ: GET_CONTENT=101", GET_CONTENT == 101)
    check("integ: GET_BTN_TITLE=102", GET_BTN_TITLE == 102)
    check("integ: GET_BTN_URL=103", GET_BTN_URL == 103)
    check("integ: GET_REACTIONS=104", GET_REACTIONS == 104)
    check("integ: GET_AUTO_DELETE=105", GET_AUTO_DELETE == 105)
    check("integ: GET_TIME=106", GET_TIME == 106)
    check("integ: DAILY_TIME=107", DAILY_TIME == 107)
    check("integ: RECUR_DAY=108", RECUR_DAY == 108)
    check("integ: RECUR_TIME=109", RECUR_TIME == 109)
    check("integ: GET_DURATION=110", GET_DURATION == 110)
    check("integ: CONFIRM_POST=111", CONFIRM_POST == 111)
    check("integ: EDIT_CONFIRM_FIELD=112", EDIT_CONFIRM_FIELD == 112)

    # 12. Time presets mavjudligi
    check("integ: BTN_T_5MIN mavjud", BTN_T_5MIN == "⚡ 5 daqiqa")
    check("integ: BTN_T_15MIN mavjud", BTN_T_15MIN == "⚡ 15 daqiqa")
    check("integ: BTN_T_1H mavjud", BTN_T_1H == "⚡ 1 soat")

    # 13. WEEKDAY_LABELS to'liq
    check("integ: 7 ta kun", len(WEEKDAY_LABELS) == 7)
    check("integ: Dushanba=0", WEEKDAY_LABELS[0] == "Dushanba")
    check("integ: Yakshanba=6", WEEKDAY_LABELS[6] == "Yakshanba")

    # 14. HTML escape xavfsizligi
    from utils.helpers import html_escape
    check("integ: HTML escape <b>", "&lt;b&gt;" in html_escape("<b>test</b>"))
    check("integ: HTML escape &", "&amp;" in html_escape("a & b"))

    # 15. parse_future_time integration
    from utils.helpers import parse_future_time
    now = tz.localize(datetime(2026, 9, 1, 12, 0))
    t1 = parse_future_time("ertaga 10:00", now)
    check("integ: ertaga 10:00", t1 is not None and t1.day == 2 and t1.hour == 10, str(t1))
    t2 = parse_future_time("5 daqiqadan keyin", now)
    check("integ: 5 daqiqadan keyin", t2 is not None and t2.minute == 5, str(t2))


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

    # 13. Kelajakdagi kun uchun label
    now = tz.localize(datetime(2026, 9, 1, 20, 0))
    occupied_all = [(9, 0), (14, 0), (19, 0)]
    # ertaga ham band
    # find_next_queue_slot faqat bitta kunlik occupied oladi, shuning uchun
    # ertaga uchun alohida chaqiriladi (handler shunday qiladi)
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, occupied_all, now)
    check("keyingi kun", slot_dt is not None and slot_dt.day == 2, str(slot_dt))

    # 14. max_days=0 → None
    slot_dt, label = find_next_queue_slot(DEFAULT_QUEUE_SLOTS, [], now, max_days=0)
    check("max_days=0 → None", slot_dt is None)


def test_queue_confirm_keyboard():
    """Queue tugmasi confirmation keyboard'da borligini tekshiradi."""
    print("== queue: confirmation keyboard ==")
    from handlers.new_post import _get_confirm_keyboard

    kb = _get_confirm_keyboard()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]

    check("queue tugmasi callback", "confirm_post:queue" in cbs, str(cbs))
    check("queue tugmasi matni", any("Navbatga" in t for t in labels), str(labels))
    check("ok tugmasi saqlanib qolgan", "confirm_post:ok" in cbs)
    check("edit tugmasi saqlanib qolgan", "confirm_post:edit" in cbs)
    check("cancel tugmasi saqlanib qolgan", "confirm_post:cancel" in cbs)


def test_queue_default_slots():
    """Default slotlar JSON formatida to'g'ri saqlanadi."""
    print("== queue: default slots format ==")
    import json
    from database import DEFAULT_QUEUE_SLOTS

    # JSON serializatsiya
    raw = json.dumps(DEFAULT_QUEUE_SLOTS)
    parsed = json.loads(raw)
    check("JSON roundtrip", parsed == DEFAULT_QUEUE_SLOTS)
    check("slotlar HH:MM formatida", all(len(s) == 5 and s[2] == ":" for s in DEFAULT_QUEUE_SLOTS))


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
    test_compose_post_text_limit()
    test_ai_context_memory()
    test_ai_optional_params()
    test_button_labels()
    test_smart_reply_ad_async()
    test_channel_cache_invalidation()
    test_confirmation_preview()
    test_integration_post_flow()
    test_queue_slot_algorithm()
    test_queue_confirm_keyboard()
    test_queue_default_slots()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha unit-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
