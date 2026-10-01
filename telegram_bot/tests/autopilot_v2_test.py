"""🧪 PHASE 8 — 7-DAY AUTOPILOT V2 (Strategy-Driven Scheduler with Approval Modes) testlari.

Qamrov:
  1. ContentLoop + Channel DNA + Gaps integratsiyasi (growth, sales,
     engagement, expertise; chastota 1, 2, 3 post/kun; RBAC/IDOR).
  2. Quiet Hours (masalan 23:00 - 08:00) va Smart Rescheduling (kechki/tungi
     vaqtlarni ertalabki ruxsat etilgan optimal vaqtga avtomatik ko'chirish).
  3. Tasdiqlash va boshqaruv rejimlari (MANUAL, SEMI_AUTO >= 0.8, AUTO faqat
     PRO foydalanuvchilar uchun).
  4. Dublikat tekshiruvi: 7 kunlik reja ICHIDA (intra-plan) va kanalning
     so'nggi 30 kunlik postlari bilan mavzu hamda matn o'xshashligi.
  5. Handler va UX integratsiyasi: Strategiya sozlamalari + har bir postni
     ko'rish (View), tasdiqlash (Approve), tahrirlash (Edit), qayta generatsiya
     qilish (Regenerate) va o'chirish (Delete).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Test muhiti uchun minimal env
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_FOR_AUTOPILOT_V2")
os.environ.setdefault("ADMIN_ID", "999001")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/test_db")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_THIS_DIR)
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

import pytz  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

import handlers.autopilot as AP  # noqa: E402
from keyboards.nav import find_nav_conflicts  # noqa: E402
from services.autopilot import (  # noqa: E402
    APPROVAL_AUTO,
    APPROVAL_MANUAL,
    APPROVAL_SEMI_AUTO,
    ApprovalMode,
    AutopilotConfig,
    AutopilotGoal,
    ContentIntelligenceLoop,
    ContentLoop,
    DEFAULT_QUIET_HOURS,
    SEMI_AUTO_QUALITY_THRESHOLD,
    apply_approval_mode_schedule,
    apply_quiet_hours,
    approve_single_plan_post,
    build_content_loop_prompt_block,
    build_daily_slot_hours,
    build_week_plan,
    check_plan_duplicates,
     compute_content_gaps,
    compute_post_quality_score,
    create_autopilot_plan,
    create_autopilot_v2_plan,
    delete_plan_post,
    edit_plan_post,
    flag_duplicate_days,
    format_quiet_hours,
    is_in_quiet_hours,
    load_recent_channel_posts_30d,
    normalize_approval_mode,
    normalize_frequency,
    normalize_goal,
    parse_quiet_hours,
    partition_by_approval_mode,
    regenerate_single_plan_post,
    reschedule_from_quiet_hours,
    resolve_morning_optimal_hour,
    validate_approval_mode_access,
    view_plan_post,
)
from services.channels.content_loop import filter_posts_last_n_days  # noqa: E402
from translations.autopilot import autopilot_parity_report  # noqa: E402

tashkent_tz = pytz.timezone("Asia/Tashkent")

PASSED = 0
FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _now() -> datetime:
    return tashkent_tz.localize(datetime(2026, 9, 18, 12, 0, 0))


# ---------------------------------------------------------------------------
# Fake DB va yordamchi strukturalar
# ---------------------------------------------------------------------------
USER_ID = 701001
OTHER_USER_ID = 701999
CH_ID = "-1009988776655"
CH_TITLE = "Tech & Biznes Kanal"


class _FakeDB:
    def __init__(self, *, owner_id: int = USER_ID, is_pro: bool = True, peak_utc_hour: int = 14):
        self.owner_id = owner_id
        self.is_pro = is_pro
        self.peak_utc_hour = peak_utc_hour
        self.scheduled: list[dict] = []
        self.history: list[dict] = []
        self.free_slots = 50
        self.current_queue = 0
        self.max_queue = 50

        # Best time va DNA uchun post tarixi (10 ta post)
        base_dt = datetime(2026, 9, 15, peak_utc_hour, 0, tzinfo=timezone.utc)
        self.events: list[dict] = []
        for i in range(10):
            dt_item = base_dt - timedelta(days=i + 1)
            text_item = (
                f"📌 Oldingi tahliliy maqola #{i + 1}: sun'iy intellekt va "
                f"avtomatlashtirish yordamida biznes samaradorligini oshirish.\n\n"
                f"👉 Batafsil: @tech_biznes"
            )
            self.history.append({
                "id": i + 1,
                "channel_id": CH_ID,
                "message_id": 100 + i,
                "content": text_item,
                "views": 1200 + i * 150,
                "post_date": dt_item.isoformat(),
            })
            self.events.append({
                "channel_id": CH_ID,
                "message_id": 100 + i,
                "text": text_item,
                "length": len(text_item),
                "emoji_count": 2,
                "emoji_density": 0.02,
                "has_cta": True,
                "cta_detected": True,
                "format": "list" if i % 2 == 0 else "structured",
                "posted_at": dt_item,
                "hour": (peak_utc_hour + 5) % 24,
                "post_hour": (peak_utc_hour + 5) % 24,
                "weekday": dt_item.weekday(),
                "post_weekday": dt_item.weekday(),
            })

    async def run_db(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def get_channel_owner_id(self, channel_id: str):
        return self.owner_id if str(channel_id) == CH_ID else None

    def get_channel_post_events(self, channel_id: str, limit: int = 500):
        if str(channel_id) != CH_ID:
            return []
        return list(self.events[:limit])

    def save_channel_intelligence_profile(self, channel_id: str, **kwargs):
        return True

    def get_channel_posts_history(self, channel_id: str, limit: int = 50):
        if str(channel_id) != CH_ID:
            return []
        return list(self.history[:limit])

    def get_channel_intelligence_profile(self, channel_id: str):
        return None

    def save_channel_dna_profile(self, channel_id: str, profile: dict, **kwargs):
        return True

    def is_premium(self, user_id: int) -> bool:
        return bool(self.is_pro) and int(user_id) == self.owner_id

    def check_queue_limit(self, user_id: int):
        can_add = (self.max_queue - self.current_queue) > 0
        return (can_add, self.current_queue, self.max_queue)

    def schedule_week_posts(self, user_id: int, channel_id: str, posts: list):
        if not posts:
            return {"success": False, "count": 0, "ids": [], "times": [], "error": "empty"}
        ids = []
        times = []
        for idx, (moment, text) in enumerate(posts):
            pid = len(self.scheduled) + 1
            self.scheduled.append({
                "id": pid,
                "user_id": int(user_id),
                "channel_id": str(channel_id),
                "scheduled_time": moment,
                "content": text,
                "idx": idx,
            })
            ids.append(pid)
            times.append(moment)
        return {"success": True, "count": len(ids), "ids": ids, "times": times, "error": None}


def _make_unique_ai_days(count: int = 7) -> list[dict]:
    """Bir-biridan farq qiluvchi ``count`` ta boy post ro'yxati."""
    themes = [
        ("SaaS onboarding xatolari va yechimlari", "checklist",
         "🔥 <b>SaaS onboardingda mijozlarni yo'qotmaslik uchun 5 qadam</b>\n\n"
         "Ko'plab startaplar birinchi 3 daqiqada foydalanuvchini chalg'itib qo'yadi. "
         "Interaktiv ro'yxat orqali konversiyani 34% ga oshiring.",
         "👉 Ro'yxatni saqlab oling: @tech_biznes"),
        ("B2B sotuv voronkasini tezlashtirish", "case_study",
         "💼 <b>B2B sotuv siklini 45 kundan 14 kungacha qisqartirgan keys</b>\n\n"
         "Demodan oldin avtomatlashtirilgan diagnostika savollarini yuborish "
         "orqali bitimlar ulushi ikki barobar o'sdi.",
         "👉 Keys tahlilini o'qing: @tech_biznes"),
        ("Telegram kanallar uchun kontent-strategiya", "guide",
         "📈 <b>Telegram kanalni reklamasiz organik o'stirish formulasi</b>\n\n"
         "Ulashiladigan karusel va chuqur qo'llanmalar oddiy yangiliklarga "
         "nisbatan 4x ko'proq forward yig'adi.",
         "👉 Do'stlaringizga ulashing: @tech_biznes"),
        ("Mijozlar e'tirozlari bilan ishlash", "faq_objection",
         "❓ <b>«Narxi qimmat» degan e'tirozga 3 ta professional javob</b>\n\n"
         "Chegirma berishga shoshilmang — avval ROI va tejab qolinadigan "
         "soatlarni aniq raqamlarda ko'rsating.",
         "👉 Savolingizni izohda qoldiring: @tech_biznes"),
        ("Haftalik IT va AI vositalar dayjesti", "tool_review",
         "🛠 <b>Jamoa unumdorligini oshiruvchi 4 ta yangi AI vosita</b>\n\n"
         "Uchrashuv transkripsiyasi, kod auditi va dizayn prototiplarini "
         "tezlashtiruvchi eng foydali servislar sharhi.",
         "👉 Qaysi birini sinab ko'rdingiz? @tech_biznes"),
        ("Obunachilar o'rtasida jonli so'rovnoma", "poll",
         "📊 <b>Sizning biznesingizda qaysi jarayon eng ko'p vaqt oladi?</b>\n\n"
         "1) Kontent tayyorlash\n2) Lidlar bilan muloqot\n3) Hisobot va analitika\n"
         "Ovoz bering — eng ko'p ovoz olgan mavzuda yechim chiqaramiz!",
         "👉 Izohlarda raqam qoldiring: @tech_biznes"),
        ("Ekspert tahlili: 2026-yil raqamli bozor trendlari", "deep_analysis",
         "🎯 <b>2026-yilda kichik biznes uchun 3 ta asosiy o'sish nuqtasi</b>\n\n"
         "Shaxsiylashtirilgan mikro-avtomatlashtirish va hamjamiyat "
         "asosidagi sotuvlar klassik targetdan o'zib ketmoqda.",
         "👉 Haftalik xulosani saqlang: @tech_biznes"),
    ]
    out: list[dict] = []
    for i in range(count):
        topic, fmt, content, cta = themes[i % len(themes)]
        if i >= len(themes):
            variant = (i // len(themes)) + 1
            topic = f"{topic} — {variant}-bosqich amaliyot"
            content = f"{content}\n\n⚡ Amaliy blok #{variant}-{i + 1}: maxsus stsenariy."
        out.append({
            "topic": topic,
            "format": fmt,
            "content": content,
            "cta": cta,
        })
    return out


# ---------------------------------------------------------------------------
# TEST 1 — ContentLoop + Channel DNA + Gaps
# ---------------------------------------------------------------------------
def test_content_loop_and_strategy():
    print("\n== TEST 1: 🔄 ContentLoop + Channel DNA + Gaps integratsiyasi ==")

    check("goal normalizatsiya: growth", normalize_goal("Auditoriyani o'stirish") == AutopilotGoal.GROWTH)
    check("goal normalizatsiya: sales", normalize_goal("Sotuv") == AutopilotGoal.SALES)
    check("goal normalizatsiya: engagement", normalize_goal("Faollik") == AutopilotGoal.ENGAGEMENT)
    check("goal normalizatsiya: expertise", normalize_goal("Ekspertiza") == AutopilotGoal.EXPERTISE)
    check("frequency normalizatsiya: 1..3",
          [normalize_frequency(0), normalize_frequency(2), normalize_frequency(9)] == [1, 2, 3])
    check("approval_mode normalizatsiya",
          [normalize_approval_mode("manual"), normalize_approval_mode("semi-auto"), normalize_approval_mode("auto")]
          == [APPROVAL_MANUAL, APPROVAL_SEMI_AUTO, APPROVAL_AUTO])

    # Content gaps hisoblash
    dna_sample = {
        "language": "uz",
        "tone": "rasmiy va tahliliy",
        "average_post_length": 420,
        "sample_size": 12,
        "emoji_level": "medium",
        "formatting_style": "structured",
        "cta_style": "frequent",
        "top_topics": ["ai", "saas", "marketing", "analitika"],
        "high_performing_formats_value": ["case_study", "checklist"],
    }
    insights_sample = {
        "content_gaps": ["poll", "video"],
        "format_distribution": {"text": 5},
    }
    gaps_sales = compute_content_gaps(
        dna_sample, insights_sample, recent_posts=[], goal="sales", total_slots=14
    )
    check("ContentLoop gaps: format_gaps aniqlandi",
          "poll" in gaps_sales["format_gaps"] and "pas_offer" in gaps_sales["format_gaps"],
          str(gaps_sales["format_gaps"]))
    check("ContentLoop gaps: 14 ta slot uchun recommended_formats",
          len(gaps_sales["recommended_formats"]) == 14,
          str(len(gaps_sales["recommended_formats"])))
    check("ContentLoop gaps: DNA high_performing_formats olindi",
          gaps_sales["high_performing_formats"] == ["case_study", "checklist"])

    prompt_block = build_content_loop_prompt_block(
        dna_sample, gaps_sales, goal="sales", frequency=2, lang="uz"
    )
    check("Prompt blokda KANAL USLUBI saqlangan", "KANAL USLUBI" in prompt_block)
    check("Prompt blokda CONTENT LOOP STRATEGIYASI bor",
          "CONTENT LOOP STRATEGIYASI" in prompt_block and "Sotuv" in prompt_block)

    # ContentLoop.analyze (async + IDOR)
    db = _FakeDB(owner_id=USER_ID)
    loop = ContentLoop(db_module=db)
    res_ok = _run(loop.analyze(CH_ID, USER_ID, goal="engagement", frequency=2, lang="uz", now=_now()))
    check("ContentLoop.analyze: ok=True (kanal egasi)", res_ok.get("ok") is True)
    check("ContentLoop.analyze: 14 ta tavsiya format (7 kun * 2x)",
          len(res_ok.get("recommended_formats") or []) == 14)
    check("ContentLoop.analyze: 30 kunlik postlar olindi",
          len(res_ok.get("recent_texts") or []) == 10)
    check("ContentIntelligenceLoop aliasi mavjud", ContentIntelligenceLoop is ContentLoop)

    res_idor = _run(loop.analyze(CH_ID, OTHER_USER_ID, goal="growth", db_module=db)
                    if False else loop.analyze(CH_ID, OTHER_USER_ID, goal="growth"))
    check("ContentLoop.analyze IDOR: begona foydalanuvchi FORBIDDEN",
          res_idor.get("ok") is False and res_idor.get("error_code") == "FORBIDDEN",
          str(res_idor))


# ---------------------------------------------------------------------------
# TEST 2 — Quiet Hours va Smart Rescheduling
# ---------------------------------------------------------------------------
def test_quiet_hours_and_smart_rescheduling():
    print("\n== TEST 2: 🌙 Quiet Hours (23:00 - 08:00) va Smart Rescheduling ==")

    check("parse_quiet_hours: '23:00 - 08:00' -> (23, 8)",
          parse_quiet_hours("23:00 - 08:00") == (23, 8))
    check("parse_quiet_hours: 'off' -> None",
          parse_quiet_hours("off") is None)
    check("format_quiet_hours: (23, 8) -> '23:00 - 08:00'",
          format_quiet_hours((23, 8)) == "23:00 - 08:00")

    check("23:00 quiet hours ichida", is_in_quiet_hours(23, "23:00 - 08:00") is True)
    check("02:00 quiet hours ichida", is_in_quiet_hours(2, "23:00 - 08:00") is True)
    check("07:00 quiet hours ichida", is_in_quiet_hours(7, "23:00 - 08:00") is True)
    check("08:00 quiet hours tashqarisida (ruxsat etilgan)",
          is_in_quiet_hours(8, "23:00 - 08:00") is False)
    check("19:00 quiet hours tashqarisida",
          is_in_quiet_hours(19, "23:00 - 08:00") is False)

    # Best hours ichida 10:00 bo'lsa ertalabki optimal soat sifatida 10:00 tanlanadi
    opt_h = resolve_morning_optimal_hour("23:00 - 08:00", best_hours=[23, 1, 10, 19])
    check("resolve_morning_optimal_hour: best_hours'dan 10:00 olindi", opt_h == 10, str(opt_h))

    # Kechki 23:30 -> keyingi kun ertalabki optimal vaqtga ko'chadi
    late_dt = tashkent_tz.localize(datetime(2026, 9, 21, 23, 30))
    shifted_dt, was_shifted = reschedule_from_quiet_hours(
        late_dt, "23:00 - 08:00", best_hours=[9, 19]
    )
    check("23:30 post ko'chirildi (was_shifted=True)", was_shifted is True)
    check("23:30 post ertalabki 09:00 ga ko'chirildi",
          shifted_dt.hour == 9 and not is_in_quiet_hours(shifted_dt, "23:00 - 08:00"),
          str(shifted_dt))

    # Tungi 03:15 -> shu kuni ertalabki 09:00 ga ko'chadi
    early_dt = tashkent_tz.localize(datetime(2026, 9, 22, 3, 15))
    shifted_early = apply_quiet_hours(early_dt, "23:00 - 08:00", best_hours=[9])
    check("03:15 post shu kuni 09:00 ga ko'chirildi",
          shifted_early.date() == early_dt.date() and shifted_early.hour == 9,
          str(shifted_early))

    # Kuniga 3 post va primary_hour=23 (Quiet Hours ichida) bo'lganda build_week_plan
    raw_items = _make_unique_ai_days(21)
    days_21 = build_week_plan(
        raw_items,
        hour=23,  # Quiet Hours ichidagi soat!
        now=_now(),
        frequency=3,
        quiet_hours="23:00 - 08:00",
        best_hours=[9, 14, 23],
        goal="growth",
    )
    check("frequency=3 -> jami 21 ta post (7 kun * 3)", len(days_21) == 21)
    check("HECH BIR post Quiet Hours (23:00-08:00) ichida qolmadi",
          all(not is_in_quiet_hours(d["scheduled_time"], "23:00 - 08:00") for d in days_21),
          str([d["time"] for d in days_21[:6]]))
    check("Quiet Hours dan ko'chirilgan postlarda rescheduled_from_quiet_hours=True",
          any(d.get("rescheduled_from_quiet_hours") for d in days_21))


# ---------------------------------------------------------------------------
# TEST 3 — Approval Modes: MANUAL, SEMI_AUTO (>= 0.8), AUTO (Pro only)
# ---------------------------------------------------------------------------
def test_approval_modes_and_pro_gate():
    print("\n== TEST 3: 🛡 Approval Modes (MANUAL / SEMI_AUTO / AUTO) va PRO nazorati ==")

    # 1. Ruxsat tekshiruvi: AUTO faqat PRO uchun
    acc_free_auto = validate_approval_mode_access(ApprovalMode.AUTO, is_pro=False)
    check("FREE user + AUTO -> allowed=False (PRO_REQUIRED)",
          acc_free_auto["allowed"] is False and acc_free_auto["error_code"] == "PRO_REQUIRED")

    acc_pro_auto = validate_approval_mode_access(ApprovalMode.AUTO, is_pro=True)
    check("PRO user + AUTO -> allowed=True", acc_pro_auto["allowed"] is True)

    # 2. Postlar tayyorlaymiz: 5 tasi yuqori sifatli (>=0.85), 2 tasi past sifatli (0.55)
    items = _make_unique_ai_days(7)
    for idx, item in enumerate(items):
        item["quality_score"] = 0.91 if idx < 5 else 0.55
    days = build_week_plan(items, hour=19, now=_now(), quiet_hours=DEFAULT_QUIET_HOURS)

    # 3. MANUAL rejim: barchasi tasdiq kutadi, 0 tasi avto-yoziladi
    db_manual = _FakeDB(owner_id=USER_ID, is_pro=True)
    res_manual = _run(apply_approval_mode_schedule(
        USER_ID, CH_ID, days, approval_mode=APPROVAL_MANUAL, is_pro=True, db_module=db_manual
    ))
    check("MANUAL: scheduled_count=0, pending_approval_count=7",
          res_manual["ok"] is True
          and res_manual["scheduled_count"] == 0
          and res_manual["pending_approval_count"] == 7,
          str(res_manual))
    check("MANUAL: DB ga hech narsa avto-yozilmadi", len(db_manual.scheduled) == 0)

    # 4. SEMI_AUTO rejim: >=0.8 bo'lgan 5 ta post avto-yoziladi, 2 tasi tasdiqqa qoladi
    days_semi = build_week_plan(items, hour=19, now=_now(), quiet_hours=DEFAULT_QUIET_HOURS)
    db_semi = _FakeDB(owner_id=USER_ID, is_pro=False)
    res_semi = _run(apply_approval_mode_schedule(
        USER_ID, CH_ID, days_semi,
        approval_mode=APPROVAL_SEMI_AUTO,
        is_pro=False,
        semi_auto_threshold=SEMI_AUTO_QUALITY_THRESHOLD,
        db_module=db_semi,
    ))
    check("SEMI_AUTO: 5 ta post avtomatik rejalashtirildi (>=0.8)",
          res_semi["ok"] is True and res_semi["scheduled_count"] == 5,
          str(res_semi))
    check("SEMI_AUTO: 2 ta shubhali (<0.8) post tasdiqqa qoldirildi",
          res_semi["pending_approval_count"] == 2
          and res_semi["needs_approval_indices"] == [5, 6],
          str(res_semi))
    check("SEMI_AUTO: DB ga aynan 5 ta post tushdi", len(db_semi.scheduled) == 5)

    # 5. AUTO rejim (FREE foydalanuvchi -> PRO_REQUIRED)
    days_auto_free = build_week_plan(items, hour=19, now=_now())
    db_auto_free = _FakeDB(owner_id=USER_ID, is_pro=False)
    res_auto_free = _run(apply_approval_mode_schedule(
        USER_ID, CH_ID, days_auto_free,
        approval_mode=APPROVAL_AUTO,
        is_pro=False,
        db_module=db_auto_free,
    ))
    check("AUTO (FREE): rad etildi (PRO_REQUIRED) va DB bo'sh",
          res_auto_free["ok"] is False
          and res_auto_free["error_code"] == "PRO_REQUIRED"
          and len(db_auto_free.scheduled) == 0)

    # 6. AUTO rejim (PRO foydalanuvchi -> barcha 7 post darhol jadvalda)
    days_auto_pro = build_week_plan(items, hour=19, now=_now())
    db_auto_pro = _FakeDB(owner_id=USER_ID, is_pro=True)
    res_auto_pro = _run(apply_approval_mode_schedule(
        USER_ID, CH_ID, days_auto_pro,
        approval_mode=APPROVAL_AUTO,
        is_pro=True,
        db_module=db_auto_pro,
    ))
    check("AUTO (PRO): barcha 7 post to'g'ridan-to'g'ri jadvalga qo'yildi",
          res_auto_pro["ok"] is True
          and res_auto_pro["scheduled_count"] == 7
          and res_auto_pro["pending_approval_count"] == 0
          and len(db_auto_pro.scheduled) == 7)


# ---------------------------------------------------------------------------
# TEST 4 — Dublikat tekshiruvi (7-kunlik reja ichida + 30-kunlik kanal tarixi)
# ---------------------------------------------------------------------------
def test_duplicate_detection_7d_and_30d():
    print("\n== TEST 4: 🔁 Dublikat tekshiruvi (7-kunlik reja ichida + 30-kunlik tarix) ==")

    now_utc = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    raw_rows = [
        {
            "content": "Yangi iPhone 17 Pro Max obzori va O'zbekistondagi narxlari haqida to'liq ma'lumot",
            "topic": "Yangi iPhone 17 Pro Max obzori",
            "post_date": (now_utc - timedelta(days=10)).isoformat(),
        },
        {
            "content": "Juda eski post: 2025 yilgi archa bayrami aksiyasi va sovg'alar",
            "topic": "2025 yilgi archa bayrami aksiyasi",
            "post_date": (now_utc - timedelta(days=45)).isoformat(),  # 30 kundan eski!
        },
    ]
    recent_30d = filter_posts_last_n_days(raw_rows, days=30, now=now_utc)
    check("30 kunlik filtr: 10 kun oldingi post kirdi, 45 kun oldingi post chiqarib tashlandi",
          len(recent_30d) == 1 and "iPhone 17" in recent_30d[0]["content"])

    # 1) Reja ichida (intra-plan) matn va mavzu dublikati
    items = _make_unique_ai_days(7)
    # 4-kun (index=3) mavzusini 1-kun (index=0) bilan bir xil qilamiz (intra-plan topic duplicate)
    items[3]["topic"] = items[0]["topic"]
    # 6-kun (index=5) matnini 2-kun (index=1) bilan bir xil qilamiz (intra-plan text duplicate)
    items[5]["content"] = items[1]["content"]
    # 2-kun (index=1) mavzusini 30 kunlik tarixdagi postga o'xshatamiz (history duplicate)
    items[2]["content"] = "Yangi iPhone 17 Pro Max obzori va O'zbekistondagi narxlari haqida to'liq ma'lumot!"

    plan_days = build_week_plan(items, hour=19, now=_now())
    dup_res = check_plan_duplicates(
        plan_days,
        recent_texts=[p["content"] for p in recent_30d],
        recent_topics=[p["topic"] for p in recent_30d],
    )
    check("30-kunlik tarix bilan matn dublikati ushlandi (index=2)",
          2 in dup_res["history_flagged"] and 2 in dup_res["flagged"],
          str(dup_res))
    check("7-kunlik reja ichidagi MAVZU dublikati ushlandi (index=3)",
          3 in dup_res["internal_flagged"] and 3 in dup_res["topic_flagged"],
          str(dup_res))
    check("7-kunlik reja ichidagi MATN dublikati ushlandi (index=5)",
          5 in dup_res["internal_flagged"] and 5 in dup_res["text_flagged"],
          str(dup_res))
    check("flag_duplicate_days ham barcha dublikatlarni qaytaradi",
          flag_duplicate_days(plan_days, [p["content"] for p in recent_30d])["flagged"]
          == dup_res["flagged"])


# ---------------------------------------------------------------------------
# TEST 5 — End-to-End Plan & Handler UX (View, Approve, Edit, Regenerate, Delete)
# ---------------------------------------------------------------------------
class _DummyUser:
    def __init__(self, uid: int = USER_ID):
        self.id = uid


class _DummyMessage:
    def __init__(self, text: str = "", user_id: int = USER_ID):
        self.text = text
        self.from_user = _DummyUser(user_id)
        self.sent: list[dict] = []

    async def reply_text(self, text: str, reply_markup=None, parse_mode=None):
        self.sent.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})
        return self


class _DummyQuery:
    def __init__(self, data: str, user_id: int = USER_ID):
        self.data = data
        self.from_user = _DummyUser(user_id)
        self.message = _DummyMessage(user_id=user_id)
        self.edits: list[dict] = []
        self.answers: list[dict] = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text: str, reply_markup=None, parse_mode=None):
        self.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


class _DummyUpdate:
    def __init__(self, *, query: _DummyQuery | None = None, message: _DummyMessage | None = None):
        self.callback_query = query
        self.message = message
        self.effective_message = message or (query.message if query else None)
        self.effective_user = (query.from_user if query else (message.from_user if message else _DummyUser()))


class _DummyContext:
    def __init__(self, lang: str = "uz"):
        self.user_data = {"lang": lang}


def test_end_to_end_v2_and_handler_controls():
    print("\n== TEST 5: 🎛 Autopilot V2 End-to-End + Post Actions (View/Approve/Edit/Regen/Delete) ==")

    import services.autopilot.planner as planner_mod

    # 1) create_autopilot_v2_plan: peak_utc_hour=19 -> 00:00 Tashkent (Quiet Hours ichida!)
    #    Dvigatel uni ertalabki optimal vaqtga ko'chirishi shart.
    db = _FakeDB(owner_id=USER_ID, is_pro=True, peak_utc_hour=19)
    orig_gen = planner_mod.generate_autopilot_week

    async def _fake_gen(topic, lang="uz", dna_block="", best_hour=None, days=7):
        return _make_unique_ai_days(days)

    planner_mod.generate_autopilot_week = _fake_gen
    try:
        v2_res = _run(create_autopilot_v2_plan(
            USER_ID,
            CH_ID,
            "B2B SaaS sotuvlarini oshirish",
            goal="sales",
            frequency=2,
            approval_mode="SEMI_AUTO",
            quiet_hours="23:00 - 08:00",
            is_pro=True,
            auto_execute_schedule=True,
            db_module=db,
            now=_now(),
        ))
    finally:
        planner_mod.generate_autopilot_week = orig_gen

    check("create_autopilot_v2_plan: ok=True", v2_res.get("ok") is True, str(v2_res))
    check("create_autopilot_v2_plan: 14 ta post (7 kun * 2x)",
          len(v2_res.get("days") or []) == 14)
    check("create_autopilot_v2_plan: ContentLoop ulangan",
          v2_res.get("content_loop_attached") is True and len(v2_res.get("content_gaps") or []) > 0)
    check("create_autopilot_v2_plan: 00:00 (Quiet Hours) ertalabga ko'chirildi",
          v2_res.get("quiet_hours_rescheduled") is True
          and all(not is_in_quiet_hours(d["scheduled_time"], "23:00 - 08:00") for d in v2_res["days"]))
    check("create_autopilot_v2_plan: SEMI_AUTO sifatli postlarni DB ga yozdi",
          (v2_res.get("schedule_result") or {}).get("scheduled_count", 0) > 0)

    # 2) Handler strategiya callbacklari (goal, freq, mode, quiet)
    ctx = _DummyContext("uz")
    ctx.user_data[AP.UD_CHANNEL] = CH_ID
    ctx.user_data[AP.UD_TITLE] = CH_TITLE

    q_goal = _DummyQuery("ap_goal:sales")
    st_goal = _run(AP.autopilot_strategy_callback(_DummyUpdate(query=q_goal), ctx))
    check("Handler strategy: goal=sales",
          st_goal == AP.AUTOPILOT_TOPIC and ctx.user_data[AP.UD_CONFIG]["goal"] == "sales")

    q_freq = _DummyQuery("ap_freq:3")
    st_freq = _run(AP.autopilot_strategy_callback(_DummyUpdate(query=q_freq), ctx))
    check("Handler strategy: frequency=3",
          st_freq == AP.AUTOPILOT_TOPIC and ctx.user_data[AP.UD_CONFIG]["frequency"] == 3)

    q_mode = _DummyQuery("ap_mode:SEMI_AUTO")
    st_mode = _run(AP.autopilot_strategy_callback(_DummyUpdate(query=q_mode), ctx))
    check("Handler strategy: approval_mode=SEMI_AUTO",
          st_mode == AP.AUTOPILOT_TOPIC and ctx.user_data[AP.UD_CONFIG]["approval_mode"] == "SEMI_AUTO")

    q_quiet = _DummyQuery("ap_quiet:off")
    st_quiet = _run(AP.autopilot_strategy_callback(_DummyUpdate(query=q_quiet), ctx))
    check("Handler strategy: quiet_hours=None (off)",
          st_quiet == AP.AUTOPILOT_TOPIC and ctx.user_data[AP.UD_CONFIG]["quiet_hours"] is None)

    # FREE user AUTO rejimni tanlay olmaydi
    orig_check_pro = AP.check_user_is_pro

    async def _not_pro(uid, db_module=None):
        return False

    AP.check_user_is_pro = _not_pro
    try:
        q_auto_free = _DummyQuery("ap_mode:AUTO")
        _run(AP.autopilot_strategy_callback(_DummyUpdate(query=q_auto_free), ctx))
        check("Handler strategy: FREE user AUTO tanlaganda SEMI_AUTO'da qoldi va PRO ogohlantirish chiqdi",
              ctx.user_data[AP.UD_CONFIG]["approval_mode"] == "SEMI_AUTO"
              and any("PRO" in e["text"] for e in q_auto_free.edits))
    finally:
        AP.check_user_is_pro = orig_check_pro

    # 3) Post darajasidagi amallar: View -> Approve -> Edit -> Regenerate -> Delete
    days_7 = build_week_plan(_make_unique_ai_days(7), hour=19, now=_now())
    ctx.user_data[AP.UD_DAYS] = days_7
    ctx.user_data[AP.UD_TOPIC] = "SaaS o'sish strategiyasi"

    # View (ap_pview:1)
    q_view = _DummyQuery("ap_pview:1")
    st_view = _run(AP.autopilot_post_view_callback(_DummyUpdate(query=q_view), ctx))
    check("Post View: AUTOPILOT_EDIT_INPUT holati va 2-post kartochkasi",
          st_view == AP.AUTOPILOT_EDIT_INPUT and "Post #2" in q_view.edits[-1]["text"])

    # Approve single post (ap_papp:1)
    orig_guard = AP.autopilot_channel_guard
    orig_approve = AP.approve_single_plan_post

    async def _allow_guard(uid, ch_id, act):
        return True

    async def _fake_approve_single(uid, ch_id, days_list, idx, **kw):
        return await approve_single_plan_post(uid, ch_id, days_list, idx, db_module=db)

    AP.autopilot_channel_guard = _allow_guard
    AP.approve_single_plan_post = _fake_approve_single
    try:
        before_sched = len(db.scheduled)
        q_app = _DummyQuery("ap_papp:1")
        st_app = _run(AP.autopilot_post_approve_callback(_DummyUpdate(query=q_app), ctx))
        check("Post Approve: AUTOPILOT_VIEW ga qaytdi va 1 ta post jadvalga qo'yildi",
              st_app == AP.AUTOPILOT_VIEW
              and len(db.scheduled) == before_sched + 1
              and days_7[1].get("already_scheduled") is True)
    finally:
        AP.autopilot_channel_guard = orig_guard
        AP.approve_single_plan_post = orig_approve

    # Edit single post (ap_pedit:2 -> matn yuborish)
    q_pedit = _DummyQuery("ap_pedit:2")
    st_pedit = _run(AP.autopilot_post_edit_callback(_DummyUpdate(query=q_pedit), ctx))
    check("Post Edit callback: AUTOPILOT_EDIT_INPUT", st_pedit == AP.AUTOPILOT_EDIT_INPUT)
    m_edit = _DummyMessage("🔥 Yangilangan 3-post: maxsus B2B taklif va 30% chegirma!")
    st_edited = _run(AP.autopilot_edit_input_received(_DummyUpdate(message=m_edit), ctx))
    check("Post Edit text: 3-post matni yangilandi va VIEW'ga qaytdi",
          st_edited == AP.AUTOPILOT_VIEW
          and "maxsus B2B taklif" in ctx.user_data[AP.UD_DAYS][2]["post_text"])

    # Regenerate single post (ap_pregen:3)
    orig_rewrite = planner_mod.rewrite_flagged_posts

    async def _fake_rewrite(topic, flagged, lang="uz", dna_block=""):
        return [{
            "index": flagged[0]["index"],
            "topic": "AI qayta yozgan yangi mavzu",
            "content": "✨ AI tomonidan butunlay yangidan yozilgan 4-post matni!",
        }]

    planner_mod.rewrite_flagged_posts = _fake_rewrite
    try:
        q_pregen = _DummyQuery("ap_pregen:3")
        st_pregen = _run(AP.autopilot_post_regen_callback(_DummyUpdate(query=q_pregen), ctx))
        check("Post Regenerate: 4-post AI bilan yangilandi",
              st_pregen == AP.AUTOPILOT_EDIT_INPUT
              and "AI tomonidan butunlay yangidan" in ctx.user_data[AP.UD_DAYS][3]["post_text"])
    finally:
        planner_mod.rewrite_flagged_posts = orig_rewrite

    # Delete single post (ap_pdel:4)
    q_pdel = _DummyQuery("ap_pdel:4")
    st_pdel = _run(AP.autopilot_post_delete_callback(_DummyUpdate(query=q_pdel), ctx))
    check("Post Delete: 5-post o'chirildi, 6 ta post qoldi",
          st_pdel == AP.AUTOPILOT_VIEW and len(ctx.user_data[AP.UD_DAYS]) == 6)

    # 4) UI/UX va i18n paritet tekshiruvi
    parity = autopilot_parity_report()
    check("Autopilot V2 i18n pariteti (uz/ru/en)", all(parity.values()), str(parity))
    for lang in ("uz", "ru", "en"):
        kb_strat = AP.autopilot_strategy_keyboard(ctx.user_data[AP.UD_CONFIG], lang)
        kb_act = AP.autopilot_post_action_keyboard(0, lang)
        check(f"[{lang}] strategy keyboard nav conflicts yo'q",
              find_nav_conflicts(kb_strat, f"strategy_{lang}") == [])
        check(f"[{lang}] post action keyboard nav conflicts yo'q",
              find_nav_conflicts(kb_act, f"post_action_{lang}") == [])


def main() -> int:
    print("=" * 70)
    print(" 🧪 PHASE 8 — 7-DAY AUTOPILOT V2 TEST SUITE")
    print("=" * 70)
    test_content_loop_and_strategy()
    test_quiet_hours_and_smart_rescheduling()
    test_approval_modes_and_pro_gate()
    test_duplicate_detection_7d_and_30d()
    test_end_to_end_v2_and_handler_controls()
    print("=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    if FAILED:
        print(" [FAIL] PHASE 8 AUTOPILOT V2 TESTDA XATOLIKLAR BOR ^^^")
        return 1
    print(" [OK] BARCHA PHASE 8 AUTOPILOT V2 TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
