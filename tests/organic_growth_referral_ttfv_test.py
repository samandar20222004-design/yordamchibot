#!/usr/bin/env python3
"""🌱 STEP 2 — ORGANIC GROWTH: action-based referal + TTFV + ACTION tugmalari.

Nima tekshiriladi
----------------
1. **Static qism (baza shart emas)**:
   - ReferralService ACTION-BASED modeli: /start da ``reward=0`` +
     ``reward_status``; mukofot FAQAT ``register_first_action`` da;
   - Konversiya bildirishnomalari navbati (bounded deque) va
     ``scheduler.referral_reward_notices_job`` flush logikasi (fake bot);
   - Hook'lar ulanishi (manba skani): ``posts_repository.add_post`` va
     ``scheduler_repository.schedule_week_posts`` → fail-soft
     ``register_first_action``; add_post cursor-kontrakti (3 so'rov) buzilmagan;
   - Post generatsiyasi ACTION tugmalari: [📋 Nusxalash] [🔄 Yangi variant]
     [📅 Rejalashtirish] [🔗 Do'stlarga] — 3 tilda, callback registry'da,
     handler'lar boshida ``query.answer``;
   - IXTIYORIY ulashish kanal postlariga MAJBURIY REKLAMA qo'shmasligi
     (``compose_post_text`` referal matnni bilmaydi; share handler publishing
     zanjiriga tegmaydi);
   - TTFV: ``record_first_value``/``ttfv_seconds`` aliaslari, ``fetch_report``
     referral bloki (hasattr-guard + TTL kesh + fail-soft);
   - ``/stats`` gauge matni: D1/D7 + ``lg_referral_conv`` (faqat referral
     bloki mavjud bo'lganda);
   - i18n: yangi kalitlar 3 tilda (paritet, placeholder, kirill/lotin).

2. **Real PostgreSQL qismi** (pgserver yoki URL):
   - To'liq oqim: /start (attribution, bonus YO'Q) → birinchi amal
     (``register_first_action`` yoki REAL ``add_post`` hook'i) → bonus +
     ledger auditi; takroriy amal → ``already_rewarded``;
   - Duplicate farming: bir xil referrer + bir xil profil barmog'i →
     attribution saqlanadi, mukofot DOIMIY bloklanadi, tarif hisobiga kirmaydi;
   - Self-referral → bonus yo'q;
   - ``get_referral_conversion_stats`` real hisob-kitobi.

Ishga tushirish::

    cd telegram_bot && python tests/organic_growth_referral_ttfv_test.py

Real PG bo'lmasa — live qism SKIP (credits_referral_test kabi).
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))
REPO = Path(__file__).resolve().parent.parent

failures = 0
passed = 0
skipped = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name} {reason}")


def _src(rel_path):
    return (REPO / rel_path).read_text(encoding="utf-8")


def _fn_src(module_src, fn_name, end_marker="\nasync def ", alt_marker="\ndef "):
    """Funksiya manbasini ajratib oladi (keyingi def gacha)."""
    start = module_src.index(f"def {fn_name}")
    rest = module_src[start:]
    ends = [rest.find(m, 10) for m in (end_marker, alt_marker)]
    ends = [e for e in ends if e > 0]
    return rest[:min(ends)] if ends else rest


def _code_only(fn_src):
    """Docstring va to'liq qatorli #-izohlarni olib tashlaydi.

    Token-skanlar uchun: izohda HUJJATLASHTIRILGAN nomlar (masalan,
    ``compose_post_text``) kod chaqiruvi emas — faqat IJRO etiladigan
    qatorlar tekshiriladi.
    """
    parts = fn_src.split('"""')
    if len(parts) >= 3:
        fn_src = parts[0] + "".join(parts[2:])
    lines = [ln for ln in fn_src.splitlines()
             if not ln.lstrip().startswith("#")]
    return "\n".join(lines)


# ============================================================
# 1. STATIC — ACTION-BASED REFERAL MODELI
# ============================================================
def test_action_based_model():
    print("== STEP 2: action-based referal modeli (API kontrakti) ==")
    from services import referral_service as rs
    from services.referral_service import ReferralService

    check("register_first_action mavjud",
          callable(getattr(ReferralService, "register_first_action", None)))
    check("signup_fingerprint mavjud", callable(rs.signup_fingerprint))
    check("reward status doimiylari",
          rs.REWARD_NONE == "none" and rs.REWARD_PENDING == "pending_first_action"
          and rs.REWARD_BLOCKED == "blocked")
    check("anti-abuse sabab doimiylari",
          rs.REASON_DUPLICATE_PROFILE == "duplicate_profile"
          and rs.REASON_ALREADY_REWARDED == "already_rewarded"
          and rs.BLOCK_DUPLICATE_PROFILE == "duplicate_profile")

    # Fingerprint: normallashtirish (lower + probel siqish) barqaror.
    fp1 = rs.signup_fingerprint("Ali Karimov", "Ali  Karimov")
    fp2 = rs.signup_fingerprint("ali  karimov", "ali karimov")
    fp3 = rs.signup_fingerprint("Ali", "Ali Karimov")
    check("fingerprint: registr/probel farqi yo'q", fp1 == fp2, f"{fp1} != {fp2}")
    check("fingerprint: boshqa profil → boshqa barmoq", fp1 != fp3)
    check("fingerprint: 64 belgi (sha256 hex)", len(fp1) == 64)

    # Noto'g'ri user_id → fail-soft (istisno yo'q).
    bad = ReferralService.register_first_action(None)
    check("register_first_action(None): granted=False, bad_user",
          bad.get("granted") is False and bad.get("reason") == rs.REASON_BAD_USER,
          str(bad))

    # /start oqimi DB'siz (xato bo'lsa ham fail-soft — db_error).
    res = ReferralService.register_new_user(1, "x")
    check("register_new_user (DB'siz muhit): istisno ko'tarmaydi",
          isinstance(res, dict) and "reward" in res, str(res))
    svc_src = _src("telegram_bot/services/referral_service.py")
    reg_src = svc_src[svc_src.index("def register_new_user"):
                      svc_src.index("def register_first_action")]
    reg_code = _code_only(reg_src)
    check("register_new_user: STEP 2 — reward doim 0 (manba skani)",
          'reward": 0' in reg_code)
    check("register_new_user: bonus grant'i YO'Q (grant_bonus_in_tx chaqirilmaydi)",
          "grant_bonus_in_tx" not in reg_code)
    check("register_new_user: reward_status qaytariladi",
          '"reward_status"' in reg_code)


def test_notice_queue_and_job():
    print("== STEP 2: konversiya bildirishnomalari navbati + scheduler job ==")
    from services import referral_service as rs
    import database as db_mod
    import scheduler as sch

    check("scheduler.referral_reward_notices_job mavjud",
          callable(getattr(sch, "referral_reward_notices_job", None)))

    # Navbat: bounded, FIFO, pop limit.
    rs.reset_pending_notices()
    check("navbat bo'sh (pending=0)", rs.pending_notice_count() == 0)
    for i in range(5):
        rs.queue_reward_notice(1000 + i, 3, 2000 + i)
    check("navbatga 5 ta qo'shildi", rs.pending_notice_count() == 5)
    popped = rs.pop_reward_notices(limit=2)
    check("pop(limit=2): 2 ta FIFO", [p["referrer_id"] for p in popped] == [1000, 1001],
          str(popped))
    check("pop'dan keyin navbatda 3 ta", rs.pending_notice_count() == 3)
    check("bildirishnoma shakli: referrer/reward/referred",
          popped[0] == {"referrer_id": 1000, "reward": 3, "referred_user_id": 2000},
          str(popped[0]))
    rs.reset_pending_notices()
    check("reset: navbat tozalandi", rs.pending_notice_count() == 0)

    # Bounded: maxlen'dan oshsa eng eski tushadi (xotira cheksiz o'smaydi).
    for i in range(600):
        rs.queue_reward_notice(1, 1, i)
    check("navbat bounded (≤500)", rs.pending_notice_count() <= 500,
          str(rs.pending_notice_count()))
    rs.reset_pending_notices()

    # Job: bot=None → no-op; bo'sh navbat → no-op; fake bot → xabarlar ketadi.
    check("job(bot=None): {sent:0}",
          asyncio.run(sch.referral_reward_notices_job(None)) == {"sent": 0, "skipped": 0})
    check("job(bo'sh navbat): {sent:0}",
          asyncio.run(sch.referral_reward_notices_job(object())) ==
          {"sent": 0, "skipped": 0})

    class _FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, parse_mode=None):
            self.sent.append((chat_id, text, parse_mode))

    async def _fake_run_db(fn, *a, **k):
        return "uz"

    rs.queue_reward_notice(777, 3, 888)
    bot = _FakeBot()
    orig_run_db = db_mod.run_db
    db_mod.run_db = _fake_run_db
    try:
        res = asyncio.run(sch.referral_reward_notices_job(bot))
    finally:
        db_mod.run_db = orig_run_db
    check("job: 1 ta xabar yuborildi", res == {"sent": 1, "skipped": 0}, str(res))
    check("job: referral_reward_notice matni (reward=3)",
          bot.sent and bot.sent[0][0] == 777 and "+3" in bot.sent[0][1]
          and "AI ball" in bot.sent[0][1], str(bot.sent))
    check("job: navbat bo'shadi", rs.pending_notice_count() == 0)

    # main.py wiring: 1 daqiqalik interval job.
    main_src = _src("telegram_bot/main.py")
    check("main.py: referral_reward_notices job'i ro'yxatdan o'tgan",
          'id="referral_reward_notices"' in main_src
          and "referral_reward_notices_job" in main_src
          and "seconds=60" in main_src)
    check("main.py: job bot bilan chaqiriladi (args=[application.bot])",
          "args=[application.bot], id=\"referral_reward_notices\"" in main_src)


def test_hooks_wired_fail_soft():
    print("== STEP 2: hook'lar (add_post + schedule_week_posts) fail-soft ==")
    posts_src = _src("telegram_bot/repositories/posts_repository.py")
    add_post_src = _fn_src(posts_src, "add_post", end_marker="\ndef ", alt_marker="\ndef ")
    check("add_post: register_first_action hook'i bor",
          "ReferralService.register_first_action(user_id)" in add_post_src)
    check("add_post: hook lazy import bilan",
          "from services.referral_service import ReferralService" in add_post_src)
    check("add_post: hook try/except ichida (fail-soft)",
          add_post_src.count("except Exception") >= 2)
    check("add_post: TTFP record_first_post saqlangan",
          "record_first_post(user_id)" in add_post_src)
    # Cursor kontrakti: with-blokdan KEYIN hech qanday cur.execute yo'q
    # (hook tranzaksiyadan tashqarida, DB'ga qo'shimcha cursor so'rovi yo'q).
    tail = add_post_src.split("post_id = cur.fetchone()[0]", 1)[-1]
    check("add_post: INSERT'dan keyin cursor chaqiruvi YO'Q (3-so'rov kontrakti)",
          "cur.execute" not in tail)

    sched_src = _src("telegram_bot/repositories/scheduler_repository.py")
    week_src = _fn_src(sched_src, "schedule_week_posts", end_marker="\ndef ",
                       alt_marker="\ndef ")
    check("schedule_week_posts: konversiya hook'i bor",
          "ReferralService.register_first_action(user_id)" in week_src)
    check("schedule_week_posts: hook try/except ichida (fail-soft)",
          "register_first_action(user_id)" in week_src
          and week_src.count("except Exception") >= 1)
    check("schedule_week_posts: hook MUVAFFAQIYATdan keyin (success=True)",
          week_src.index("register_first_action") > week_src.index('"success": True'))
    check("schedule_week_posts: TTFP ham belgilanadi",
          "record_first_post(user_id)" in week_src)

    # Jamoa workflow DRAFT postlari konversiya hisoblanmaydi (atalay).
    teams_src = _src("telegram_bot/repositories/teams_repository.py")
    check("teams_repository: draft post konversiya HISOBLANMAYDI",
          "register_first_action" not in teams_src)


def test_action_buttons():
    print("== STEP 2: post generatsiyasi ACTION tugmalari (3 til) ==")
    from keyboards.inline import get_ai_tone_keyboard, AI_TONE_KEYS
    from keyboards.callback_data import (
        CB_AI_COPY, CB_AI_REGEN, CB_AI_SHARE_REF, REGISTERED_STATIC_CALLBACKS,
        callback_byte_len,
    )

    check("callback doimiylari: ai_copy/ai_regen/ai_share_ref",
          CB_AI_COPY == "ai_copy" and CB_AI_REGEN == "ai_regen"
          and CB_AI_SHARE_REF == "ai_share_ref")
    check("registry: 3 ta action callback ro'yxatda",
          {"ai_copy", "ai_regen", "ai_share_ref"} <= set(REGISTERED_STATIC_CALLBACKS))
    check("callback'lar ≤64 bayt",
          all(callback_byte_len(c) <= 64 for c in (CB_AI_COPY, CB_AI_REGEN, CB_AI_SHARE_REF)))

    labels = {}
    for lang in ("uz", "ru", "en"):
        kb = get_ai_tone_keyboard("friendly", lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        labels[lang] = [b.text for row in kb.inline_keyboard for b in row
                        if b.callback_data in ("ai_copy", "ai_regen", "ai_share_ref")]
        check(f"{lang}: uslub qatorlari saqlangan (preview o'zgarmadi)",
              all(f"ai_tone:{t}" in cbs for t in AI_TONE_KEYS), str(cbs))
        check(f"{lang}: [📅 Rejalashtirish] o'z joyida", "ai_studio_sched" in cbs)
        check(f"{lang}: ACTION tugmalari mavjud (copy/regen/share)",
              all(c in cbs for c in ("ai_copy", "ai_regen", "ai_share_ref")), str(cbs))
        check(f"{lang}: navigatsiya saqlangan", "ai_back_to_menu" in cbs and "ai_close" in cbs)
        check(f"{lang}: 3 ta action yorlig'i bo'sh emas",
              len(labels[lang]) == 3 and all(labels[lang]), str(labels[lang]))
    check("action yorliqlari 3 tilda farqli",
          labels["uz"] != labels["ru"] != labels["en"] and labels["uz"] != labels["en"],
          str(labels))

    # Handler'lar: registratsiya + darhol query.answer (speks).
    ai_src = _src("telegram_bot/handlers/ai_assistant.py")
    for fn in ("ai_copy_post_callback", "ai_share_referral_callback"):
        start = ai_src.index(f"async def {fn}")
        chunk = ai_src[start:start + 400]
        check(f"{fn}: boshida query.answer", "await query.answer(" in chunk)
    tone_src = _fn_src(ai_src, "ai_tone_callback", end_marker="\nasync def ")
    check("ai_tone_callback: ai_regen tarmog'i bor", '"ai_regen"' in tone_src)

    init_src = _src("telegram_bot/handlers/__init__.py")
    check("handlers/__init__: ai_copy ro'yxatdan o'tgan",
          'CallbackQueryHandler(ai_copy_post_callback, pattern=r"^ai_copy$")' in init_src)
    check("handlers/__init__: ai_regen ro'yxatdan o'tgan",
          'CallbackQueryHandler(ai_tone_callback, pattern=r"^ai_regen$")' in init_src)
    check("handlers/__init__: ai_share_ref ro'yxatdan o'tgan",
          'CallbackQueryHandler(ai_share_referral_callback, pattern=r"^ai_share_ref$")' in init_src)

    # Copy handler preview'ni buzmaydi: matn <code> blokida, kesish chegarasi bor.
    copy_src = _fn_src(ai_src, "ai_copy_post_callback", end_marker="\nasync def ")
    check("ai_copy: <code> bloki + html_escape", "<code>" in copy_src and "html_escape" in copy_src)
    check("ai_copy: 4096 limiti (kesish chegarasi)", "AI_COPY_MAX_CHARS" in copy_src)
    check("ai_copy: preview holati saqlanadi (AI_TONE_SELECT qaytadi)",
          "return AI_TONE_SELECT" in copy_src)


def test_optional_share_no_forced_ads():
    print("== STEP 2: IXTIYORIY ulashish — kanal postlariga reklama YO'Q ==")
    ai_src = _src("telegram_bot/handlers/ai_assistant.py")
    share_src = _code_only(
        _fn_src(ai_src, "ai_share_referral_callback", end_marker="\nasync def "))
    # Share handler faqat shaxsiy chatga yozadi: publishing zanjiriga tegmaydi.
    for forbidden in ("compose_post_text", "scheduled_posts", "add_post",
                      "delivery_service", "ad_free", "auto_ad"):
        check(f"ai_share_ref: '{forbidden}' ga tegmaydi", forbidden not in share_src)
    check("ai_share_ref: faqat query.message.reply_text (shaxsiy chat)",
          "query.message.reply_text" in share_src)
    check("ai_share_ref: havola ref_ formatida", "?start=ref_" in share_src)
    check("ai_share_ref: share klaviaturasi (switch_inline_query)",
          "get_referral_share_keyboard" in share_src)

    # Kanal post matni yig'iladigan joy referal havolani HECH QACHON bilmaydi.
    sch_src = _src("telegram_bot/scheduler.py")
    compose_src = _fn_src(sch_src, "compose_post_text", end_marker="\nasync def ",
                          alt_marker="\ndef ")
    for token in ("ref_", "ai_share_ref", "referral_link", "start=ref"):
        check(f"compose_post_text: '{token}' yo'q (majburiy reklama yo'q)",
              token not in compose_src)

    # /start xabari: «do'st qo'shildi» (mukofot kutilmoqda), «bonus berildi» emas.
    start_src = _src("telegram_bot/handlers/start.py")
    notify_src = _code_only(
        _fn_src(start_src, "_notify_referrer_reward", end_marker="\nasync def ",
                alt_marker="\ndef "))
    check("start: friend-joined xabari (STEP 2)",
          '"referral_friend_joined_notice"' in notify_src)
    # Konversiya xabari kaliti ("referral_reward_notice") /start da ISHLATILMAYDI
    # (docstring'dagi referral_reward_notices_job nomi bilan chalkashmasligi
    # uchun tirnoqli kalit skan qilinadi).
    check("start: /start da 'bonus berildi' xabari yo'q",
          '"referral_reward_notice"' not in notify_src)


def test_ttfv_and_referral_stats_report():
    print("== STEP 2: TTFV telemetriya + fetch_report referral bloki ==")
    from services import onboarding_telemetry as tel

    tel.reset()
    tel.record_start(1, ts=100.0)
    tel.record_first_value(1, ts=160.0)
    mem = tel.in_memory_report()
    check("TTFV alias: record_first_value → xotira hisobotida 60s",
          mem.get("activated") == 1 and mem.get("avg_seconds") == 60.0, str(mem))
    tel.record_first_value(1, ts=999.0)
    mem2 = tel.in_memory_report()
    check("TTFV: faqat BIRINCHI qiymat (idempotent)",
          mem2.get("avg_seconds") == 60.0, str(mem2))
    check("TTFV == TTFP: bitta formula (alias)",
          tel.ttfv_seconds is tel.ttfp_seconds)
    tel.record_start(2, ts=10.0)
    mem3 = tel.in_memory_report()
    check("TTFV: birinchi postsiz foydalanuvchi 'waiting'",
          mem3.get("waiting") == 1 and mem3.get("started") == 2, str(mem3))
    tel.reset()

    # fetch_report: referral bloki hasattr-guard bilan.
    class _FullDB:
        def __init__(self):
            self.calls = {"cohort": 0, "referral": 0}

        def get_retention_cohort(self, days=30, limit=5000):
            self.calls["cohort"] += 1
            return [{"user_id": 1, "created_at": "2026-10-01T00:00:00",
                     "first_post_at": "2026-10-01T01:00:00",
                     "last_seen_at": "2026-10-02T00:00:00"}]

        def get_referral_conversion_stats(self, days=30):
            self.calls["referral"] += 1
            return {"window_days": 30, "referred_total": 4, "converted": 3,
                    "blocked": 1, "rate": 0.75}

    class _LegacyDB:
        """Eski baza-modul: get_retention_cohort BOR, referral funksiyasi YO'Q."""

        def get_retention_cohort(self, days=30, limit=5000):
            return []

    class _BrokenDB(_FullDB):
        def get_referral_conversion_stats(self, days=30):
            raise RuntimeError("db down")

    tel.reset_cache()
    full = _FullDB()
    rep = tel.fetch_report(full, 30, now=datetime(2026, 10, 5))
    check("fetch_report: referral bloki qo'shildi", rep.get("referral", {}).get("referred_total") == 4,
          str(rep.get("referral")))
    check("fetch_report: rate to'g'ri", rep["referral"]["rate"] == 0.75)
    rep2 = tel.fetch_report(full, 30, now=datetime(2026, 10, 5))
    check("fetch_report: TTL kesh (referral 1 marta so'raldi)",
          full.calls["referral"] == 1, str(full.calls))
    check("fetch_report: keshdan ham referral qaytadi",
          rep2.get("referral", {}).get("referred_total") == 4)
    tel.reset_cache()
    check("reset_cache: referral keshi ham tozalanadi",
          tel.fetch_report(full, 30, now=datetime(2026, 10, 5))["referral"]["referred_total"] == 4
          and full.calls["referral"] == 2)

    tel.reset_cache()
    legacy = _LegacyDB()
    rep3 = tel.fetch_report(legacy, 30, now=datetime(2026, 10, 5))
    check("eski db-modul: referral bloki YO'Q (orqa moslik)",
          "referral" not in rep3, str(rep3.get("referral")))
    tel.reset_cache()
    broken = _BrokenDB()
    rep4 = tel.fetch_report(broken, 30, now=datetime(2026, 10, 5))
    check("buzilgan referral so'rovi: hisobot yiqilmaydi (fail-soft)",
          isinstance(rep4, dict) and "referral" not in rep4)
    tel.reset_cache()
    check("fetch_referral_stats(None) → {}", tel.fetch_referral_stats(None) == {})
    import types
    check("fetch_referral_stats(SimpleNamespace) → {}",
          tel.fetch_referral_stats(types.SimpleNamespace()) == {})

    # Admin gauge: referral qatori FAQAT blok mavjud bo'lganda.
    from handlers.admin import _build_launch_gauges_text

    base_report = {
        "available": True, "window_days": 30, "registered": 10, "activated": 5,
        "activation_rate": 0.5,
        "ttfp": {"available": False},
        "retention": {"d1": {"rate": 0.4, "returned": 4, "eligible": 10},
                      "d7": {"rate": 0.2, "returned": 2, "eligible": 10}},
    }
    text_no_ref = _build_launch_gauges_text(dict(base_report), "uz")
    check("gauge: referral bloksiz matn o'zgarmaydi (qator yo'q)",
          "Referral konversiyasi" not in text_no_ref, text_no_ref)
    check("gauge: D1/D7 chiziladi",
          "D1 retention" in text_no_ref and "D7 retention" in text_no_ref)
    with_ref = dict(base_report)
    with_ref["referral"] = {"window_days": 30, "referred_total": 4,
                            "converted": 1, "blocked": 1, "rate": 0.25}
    text_ref = _build_launch_gauges_text(with_ref, "uz")
    check("gauge: referral konversiya qatori chizildi (25%, 1/4)",
          "Referral konversiyasi" in text_ref and "25%" in text_ref
          and "1/4" in text_ref, text_ref)
    text_ru = _build_launch_gauges_text(with_ref, "ru")
    check("gauge[ru]: konversiya kirillda",
          "Конверсия рефералов" in text_ru, text_ru)
    text_en = _build_launch_gauges_text(with_ref, "en")
    check("gauge[en]: konversiya lotinda",
          "Referral conversion" in text_en, text_en)
    zero_ref = dict(base_report)
    zero_ref["referral"] = {"window_days": 30, "referred_total": 0,
                            "converted": 0, "blocked": 0, "rate": 0.0}
    zero_text = _build_launch_gauges_text(zero_ref, "uz")
    check("gauge: referred_total=0 bo'lsa ham chiziladi (0/0)",
          "Referral konversiyasi" in zero_text and "0/0" in zero_text, zero_text)
    check("gauge: bo'sh hisobot → lg_no_data",
          _build_launch_gauges_text({}, "uz") != "")

    # Facade: yangi funksiya database.py orqali ham mavjud.
    import database as db_mod
    check("database facade: get_referral_conversion_stats re-eksport",
          callable(getattr(db_mod, "get_referral_conversion_stats", None)))

    # TTFV generatsiya nuqtalari (manba skani).
    ai_src = _src("telegram_bot/handlers/ai_assistant.py")
    check("ai_assistant: generatsiyada TTFV belgisi",
          "record_first_post(user_id)" in ai_src)
    magic_src = _src("telegram_bot/handlers/magic_post.py")
    check("magic_post: generatsiyada TTFV belgisi",
          "record_first_post(user_id)" in magic_src)
    check("magic_post: ACTION klaviaturasi O'ZGARMADI (frozen)",
          "ai_copy" not in magic_src and "ai_share_ref" not in magic_src)


def test_i18n_step2_keys():
    print("== STEP 2: i18n kalitlar (uz/ru/en paritet) ==")
    from locales.translations import TRANSLATIONS, get_text, format_args

    keys = ("ai_btn_copy", "ai_btn_regen", "ai_btn_share_ref", "ai_copy_done",
            "ai_copy_empty", "ai_share_ref_text", "referral_friend_joined_notice")
    for key in keys:
        vals = {c: TRANSLATIONS[c].get(key) for c in ("uz", "ru", "en")}
        check(f"{key}: 3 tilda mavjud", all(vals.values()), str(vals))
        check(f"{key}: 3 tilda farqli", len(set(vals.values())) == 3, str(vals))
        args = {c: format_args(vals[c] or "") for c in vals}
        check(f"{key}: placeholder pariteti", len({frozenset(a) for a in args.values()}) == 1,
              str(args))
    check("ai_share_ref_text: {link} placeholder'i bor",
          format_args(TRANSLATIONS["uz"]["ai_share_ref_text"]) == {"link"})

    cyr = re.compile(r"[\u0400-\u04FF]")
    check("referral_friend_joined_notice[ru] kirill",
          bool(cyr.search(TRANSLATIONS["ru"]["referral_friend_joined_notice"])))
    check("referral_friend_joined_notice[uz/en] lotin",
          not cyr.search(TRANSLATIONS["uz"]["referral_friend_joined_notice"])
          and not cyr.search(TRANSLATIONS["en"]["referral_friend_joined_notice"]))

    # referral_menu: tarif matni ("+3"/"+1") + placeholder to'plami SAQLANDI.
    for lang in ("uz", "ru"):
        menu = TRANSLATIONS[lang]["referral_menu"]
        check(f"referral_menu[{lang}]: '+3' va '+1' saqlangan",
              "+3" in menu and "+1" in menu, menu)
    ph = {c: sorted(format_args(TRANSLATIONS[c]["referral_menu"])) for c in ("uz", "ru", "en")}
    check("referral_menu: placeholderlar AYNAN {count,credits,link}",
          ph["uz"] == ["count", "credits", "link"] == ph["ru"] == ph["en"], str(ph))
    rendered = get_text("referral_menu", "uz", credits=7, count=2,
                        link="https://t.me/bot?start=ref_1")
    check("referral_menu render: link+count+credits ko'rinadi",
          "https://t.me/bot?start=ref_1" in rendered and "7" in rendered
          and "2" in rendered, rendered)
    for lang in ("uz", "ru", "en"):
        menu = TRANSLATIONS[lang]["referral_menu"]
        check(f"referral_menu[{lang}]: action sharti tushuntirilgan",
              any(w in menu for w in ("birinchi post", "первый пост", "first post")),
              menu)

    # referral_reward_notice (konversiya xabari) so'zlashuvi qotirilgan.
    check("referral_reward_notice[uz]: 'AI ball'",
          "AI ball" in get_text("referral_reward_notice", "uz", reward=3))
    check("referral_reward_notice[ru]: 'ИИ-балл'",
          "ИИ-балл" in get_text("referral_reward_notice", "ru", reward=3))
    check("referral_reward_notice[en]: 'AI credit'",
          "AI credit" in get_text("referral_reward_notice", "en", reward=3))

    # admin_panel: lg_referral_conv 3 tilda.
    from translations.admin_panel import ADMIN_PANEL_I18N, admin_t
    for lang in ("uz", "ru", "en"):
        val = ADMIN_PANEL_I18N[lang].get("lg_referral_conv")
        check(f"lg_referral_conv[{lang}] mavjud", bool(val), str(val))
        check(f"lg_referral_conv[{lang}] placeholderlari {{percent,converted,referred}}",
              sorted(format_args(val or "")) == ["converted", "percent", "referred"],
              str(val))
    line = admin_t("lg_referral_conv", "uz", percent="50", converted=1, referred=2)
    check("admin_t render: 50% va 1/2", "50%" in line and "1/2" in line, line)


# ============================================================
# 2. REAL POSTGRESQL (pgserver yoki URL)
# ============================================================
_local_server = []

OG_REFERRER = 81000001
OG_F1 = 81000010
OG_F2 = 81000011
OG_F3 = 81000012
OG_DUP = 81000013
OG_SOLO = 81000014
OG_PLAIN = 81000015
OG_CHANNEL = "-10081000011"
OG_IDS = (OG_REFERRER, OG_F1, OG_F2, OG_F3, OG_DUP, OG_SOLO, OG_PLAIN)


def _live_uri():
    for var in ("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url
    url = os.getenv("DATABASE_URL")
    if url and "user:pass" not in url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    if _local_server:
        return _local_server[0].get_uri()
    import tempfile
    try:
        server = pgserver.get_server(
            os.path.join(tempfile.gettempdir(), "yordamchi_pg_organic"))
    except Exception:  # pragma: no cover - muhitga bog'liq
        return None
    _local_server.append(server)
    return server.get_uri()


def _balance(db_mod, uid):
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _ledger(db_mod, uid):
    with db_mod.db_cursor() as cur:
        cur.execute(
            "SELECT amount, balance_after, operation_type, reference_id "
            "FROM credits_ledger WHERE user_id = %s ORDER BY id ASC", (uid,))
        return [{"amount": int(r[0]), "balance_after": int(r[1]),
                 "operation_type": r[2], "reference_id": r[3]} for r in cur.fetchall()]


def _block(db_mod, uid):
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT referral_block_reason FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    return row[0] if row else None


def _cleanup(db_mod):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (list(OG_IDS),))
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(OG_IDS),))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (list(OG_IDS),))
        cur.execute("UPDATE users SET referrer_id = NULL WHERE referrer_id = ANY(%s)",
                    (list(OG_IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(OG_IDS),))


def test_live(db_mod):
    from services.referral_service import ReferralService

    print("== STEP 2 (live): 1) /start — attribution, bonus YO'Q ==")
    db_mod.save_user(OG_REFERRER, "og_ref")
    for uid, uname, fname in ((OG_F1, "og_f1", "Friend One"),
                              (OG_F2, "og_f2", "Friend Two"),
                              (OG_F3, "og_f3", "Friend Three")):
        res = ReferralService.register_new_user(uid, uname, fname,
                                                referrer_id=OG_REFERRER)
        check(f"/start {uname}: is_new, reward=0, pending_first_action",
              res["is_new"] is True and res["reward"] == 0
              and res.get("reward_status") == "pending_first_action", str(res))
    check("/start fazasi: referrer balansi 5 (bonus yo'q)",
          _balance(db_mod, OG_REFERRER) == 5)
    check("/start fazasi: referral ledger bo'sh", _ledger(db_mod, OG_REFERRER) == [])

    stats = db_mod.get_referral_conversion_stats(30)
    check("stats: 3 taklif, 0 konversiya (rate=0)",
          stats.get("referred_total") == 3 and stats.get("converted") == 0
          and stats.get("rate") == 0.0, str(stats))

    print("== STEP 2 (live): 2) birinchi AMAL → mukofot (service orqali) ==")
    act = ReferralService.register_first_action(OG_F1)
    check("1-amal: granted=True reward=3", act["granted"] is True and act["reward"] == 3,
          str(act))
    check("1-amal: referrer balansi 8", _balance(db_mod, OG_REFERRER) == 8)
    rows = _ledger(db_mod, OG_REFERRER)
    check("1-amal: ledger +3 referral (reference=do'st ID)",
          len(rows) == 1 and rows[0]["amount"] == 3
          and rows[0]["balance_after"] == 8
          and rows[0]["operation_type"] == "referral"
          and rows[0]["reference_id"] == str(OG_F1), str(rows))
    again = ReferralService.register_first_action(OG_F1)
    check("takroriy amal: already_rewarded (double-claim yo'q)",
          again["granted"] is False and again["reason"] == "already_rewarded", str(again))
    check("takroriy amal: balans/ledger o'zgarmadi",
          _balance(db_mod, OG_REFERRER) == 8 and len(_ledger(db_mod, OG_REFERRER)) == 1)

    print("== STEP 2 (live): 3) REAL add_post hook'i → mukofot ==")
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title) "
                    "VALUES (%s, %s, 'OG kanal') ON CONFLICT (channel_id) DO NOTHING",
                    (OG_F2, OG_CHANNEL))
    post_id = db_mod.add_post(OG_F2, OG_CHANNEL, "text", "Birinchi post!", None,
                              datetime.utcnow() + timedelta(hours=1))
    check("add_post: post saqlandi (id qaytdi)", isinstance(post_id, int) and post_id > 0,
          str(post_id))
    check("add_post hook: referrer balansi 8+3=11 (2-do'st tarifi +3)",
          _balance(db_mod, OG_REFERRER) == 11, str(_balance(db_mod, OG_REFERRER)))
    rows = _ledger(db_mod, OG_REFERRER)
    check("add_post hook: ledger 2 yozuv (reference=OG_F2)",
          len(rows) == 2 and rows[-1]["reference_id"] == str(OG_F2)
          and rows[-1]["amount"] == 3 and rows[-1]["balance_after"] == 11, str(rows))
    act2 = ReferralService.register_first_action(OG_F2)
    check("add_post hook'dan keyin takroriy amal: already_rewarded",
          act2["granted"] is False and act2["reason"] == "already_rewarded", str(act2))

    print("== STEP 2 (live): 4) DUPLICATE farming bloklanadi ==")
    dup = ReferralService.register_new_user(OG_DUP, "OG_F3", "friend  three",
                                            referrer_id=OG_REFERRER)
    check("dup: reward_status='blocked'",
          dup["is_new"] is True and dup.get("reward_status") == "blocked", str(dup))
    check("dup: block belgisi bazada", _block(db_mod, OG_DUP) == "duplicate_profile")
    act_dup = ReferralService.register_first_action(OG_DUP)
    check("dup: amal mukofot BERMADI (duplicate_profile)",
          act_dup["granted"] is False and act_dup["reason"] == "duplicate_profile",
          str(act_dup))
    check("dup: balans/ledger o'zgarmadi (11, 2 yozuv)",
          _balance(db_mod, OG_REFERRER) == 11 and len(_ledger(db_mod, OG_REFERRER)) == 2)

    act3 = ReferralService.register_first_action(OG_F3)
    check("3-do'st (kopya emas): +3 (tarif 3-konversiya)",
          act3["granted"] is True and act3["reward"] == 3
          and _balance(db_mod, OG_REFERRER) == 14, str(act3))

    print("== STEP 2 (live): 5) self-referral + referrersiz amal ==")
    solo = ReferralService.register_new_user(OG_SOLO, "og_solo", referrer_id=OG_SOLO)
    check("self-referral: reward=0, status=none, reason=self_referral",
          solo["reward"] == 0 and solo.get("reward_status") == "none"
          and solo["reason"] == "self_referral", str(solo))
    act_solo = ReferralService.register_first_action(OG_SOLO)
    check("self-referral amali: mukofot yo'q (no_referral)",
          act_solo["granted"] is False and act_solo["reason"] == "no_referral", str(act_solo))
    db_mod.save_user(OG_PLAIN, "og_plain")
    act_plain = ReferralService.register_first_action(OG_PLAIN)
    check("referrersiz foydalanuvchi amali: no_referral (fail-soft)",
          act_plain["granted"] is False and act_plain["reason"] == "no_referral",
          str(act_plain))
    missing = ReferralService.register_first_action(999999998)
    check("mavjud bo'lmagan user: user_not_found",
          missing["granted"] is False and missing["reason"] == "user_not_found",
          str(missing))

    print("== STEP 2 (live): 6) konversiya statistikasi (real hisob) ==")
    stats = db_mod.get_referral_conversion_stats(30)
    check("stats: referred=4, converted=3, blocked=1",
          stats.get("referred_total") == 4 and stats.get("converted") == 3
          and stats.get("blocked") == 1, str(stats))
    check("stats: rate=0.75", stats.get("rate") == 0.75, str(stats))
    check("stats: window_days=30", stats.get("window_days") == 30, str(stats))
    stats7 = db_mod.get_referral_conversion_stats(7)
    check("stats(7 kun): oyna saqlanadi", stats7.get("window_days") == 7, str(stats7))
    check("stats(7 kun): hammasi yangi (referred=4)",
          stats7.get("referred_total") == 4, str(stats7))

    print("== STEP 2 (live): 7) TTFV hisoboti real baza bilan ==")
    from services import onboarding_telemetry as tel
    tel.reset_cache()
    rep = tel.fetch_report(db_mod, 30)
    check("fetch_report(real db): referral bloki bor",
          isinstance(rep.get("referral"), dict)
          and rep["referral"].get("referred_total") == 4, str(rep.get("referral")))
    tel.reset_cache()


def run_live():
    uri = _live_uri()
    if not uri:
        print("== Real PostgreSQL (o'tkazib yuborildi) ==")
        skip("live STEP 2 testlar", "(pgserver/URL mavjud emas)")
        return
    import database as db_mod
    db_mod.DATABASE_URL = uri
    os.environ["DATABASE_URL"] = uri
    db_mod._reset_pool()
    try:
        db_mod.init_db()
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        skip("live STEP 2 testlar", f"(PostgreSQL mavjud emas: {e})")
        return
    try:
        _cleanup(db_mod)
        test_live(db_mod)
    except Exception as e:  # pragma: no cover - xavfsizlik
        import traceback
        traceback.print_exc()
        check("live STEP 2 testlari xatosiz o'tdi", False, f"{type(e).__name__}: {e}")
    finally:
        _cleanup(db_mod)
        db_mod.close_pool()


if __name__ == "__main__":
    test_action_based_model()
    test_notice_queue_and_job()
    test_hooks_wired_fail_soft()
    test_action_buttons()
    test_optional_share_no_forced_ads()
    test_ttfv_and_referral_stats_report()
    test_i18n_step2_keys()
    run_live()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
        print("STEP 2 (ORGANIC GROWTH) testlarida xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0, O'tkazib yuborildi: {skipped}")
    print("Barcha STEP 2 (ORGANIC GROWTH) testlari muvaffaqiyatli o'tdi ✔")
