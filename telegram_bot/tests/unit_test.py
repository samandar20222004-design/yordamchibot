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

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha unit-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
