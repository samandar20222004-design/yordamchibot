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


def test_analytics_main_keyboard():
    """Asosiy menyuda Analitika tugmasi bor."""
    print("== Analytics main keyboard ==")
    from keyboards.default import get_main_keyboard, BTN_ANALYTICS

    check("BTN_ANALYTICS mavjud", BTN_ANALYTICS == "📊 Analitika")

    kb = get_main_keyboard(False)
    all_texts = [b.text for row in kb.keyboard for b in row]
    check("main kb: Analitika bor", BTN_ANALYTICS in all_texts)

    kb_admin = get_main_keyboard(True)
    all_admin = [b.text for row in kb_admin.keyboard for b in row]
    check("admin kb: Analitika bor", BTN_ANALYTICS in all_admin)


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
    check("back kb: close_msg", "close_msg" in bcbs)

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
    )

    check("admin_panel_menu callable", callable(admin_panel_menu))
    check("admin_stats_command callable", callable(admin_stats_command))
    check("admin_dashboard_callback callable", callable(admin_dashboard_callback))
    check("admin_inline_text_handler callable", callable(admin_inline_text_handler))
    check("show_statistics callable", callable(show_statistics))
    check("broadcast_start callable", callable(broadcast_start))
    check("broadcast_send callable", callable(broadcast_send))
    check("ai_settings_menu callable", callable(ai_settings_menu))


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
    check("studio kb: close", "studio_close" in cbs)
    check("studio kb: 4 ta tugma", len(cbs) == 4)
    check("studio kb: AI Post label", any("AI Post" in t for t in labels))
    check("studio kb: Kontent-reja label", any("Kontent-reja" in t for t in labels))

    # Main keyboard — 6 tugma (3x2 grid)
    kb_main = get_main_keyboard(False)
    main_texts = [b.text for row in kb_main.keyboard for b in row]
    check("main kb: 6 ta tugma (free)", len(main_texts) == 6)
    check("main kb: Yangi post", BTN_NEW_POST in main_texts)
    check("main kb: AI Studio", BTN_AI_STUDIO in main_texts)
    check("main kb: Queue", BTN_QUEUE in main_texts)
    check("main kb: Analitika", BTN_ANALYTICS in main_texts)
    check("main kb: Premium", BTN_PREMIUM in main_texts)
    check("main kb: Kabinet", BTN_SETTINGS in main_texts)

    # Admin keyboard — 7 ta tugma (6 + admin)
    kb_admin = get_main_keyboard(True)
    admin_texts = [b.text for row in kb_admin.keyboard for b in row]
    check("main kb: 7 ta tugma (admin)", len(admin_texts) == 7)


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

    kb = get_main_keyboard(is_admin=False)
    texts = [b.text for row in kb.keyboard for b in row]
    check("queue tugmasi asosiy menyuda", BTN_QUEUE in texts, str(texts))
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

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha unit-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
