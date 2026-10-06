"""🚀 AI AUTOPILOT V2 — Strategik 7 kunlik kontent-operator (PHASE C + PHASE 8).

Phase 8 (7-Day Autopilot V2: Strategy-Driven Scheduler with Approval Modes)
avtopilotni oddiy 7 post generatoridan **Channel DNA** va **ContentLoop**
(Gaps, Best Time, 30-kunlik tarix) ga tayanadigan strategik kontent
operatoriga aylantiradi:

1. **7-kunlik strategik reja generatsiyasi**:
   * ``channel_id`` — maqsadli kanal (RBAC/IDOR himoyasi bilan);
   * ``goal`` — strategik maqsad: ``growth`` (auditoriyani o'stirish),
     ``sales`` (sotuv), ``engagement`` (faollik), ``expertise`` (ekspertiza);
   * ``frequency`` — post chastotasi: kuniga ``1``, ``2`` yoki ``3`` ta;
   * ``approval_mode`` — ``MANUAL``, ``SEMI_AUTO``, ``AUTO``;
   * ``quiet_hours`` — tinchlik soatlari (masalan ``23:00 - 08:00``);
   * **Channel DNA** va **ContentLoop Gaps** asosida 7 kunlik balanslangan
     mavzular, formatlar va optimal vaqtlar tuziladi.

2. **Tasdiqlash va boshqaruv rejimlari (Approval Modes)**:
   * ``MANUAL``: barcha postlar oldindan foydalanuvchiga ko'rsatiladi va
     tasdiqlangach (Approve) jadvalga qo'yiladi;
   * ``SEMI_AUTO``: ``quality_score >= 0.8`` bo'lgan sifatli postlar
     avtomatik jadvalga olinadi, shubhali (``< 0.8`` yoki dublikat xavfi bor)
     postlar foydalanuvchi tasdig'iga qoldiriladi;
   * ``AUTO``: barcha postlar to'g'ridan-to'g'ri jadvalga joylashtiriladi
     (**faqat PRO foydalanuvchilar uchun** — FREE uchun ``PRO_REQUIRED``).

3. **Quiet Hours va Smart Rescheduling + Dublikat tekshiruvi**:
   * Agar generatsiya qilingan post vaqti Quiet Hours (masalan ``23:00 - 08:00``)
     ga to'g'ri kelsa, dvigatel uni avtomatik ravishda ertalabki ruxsat
     etilgan optimal vaqtga ko'chiradi;
   * 7 kunlik reja ichida (intra-plan) VA so'nggi 30 kunlik kanal postlari
     bilan mavzular hamda matnlar dublikati (similarity check) tekshiriladi.

4. **Post boshqaruvi (View / Approve / Edit / Regenerate / Delete)**:
   * Rejadagi har bir postni alohida ko'rish, tasdiqlash, tahrirlash,
     AI orqali qayta generatsiya qilish yoki o'chirish imkoniyati.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytz

from services.channels.content_loop import (
    ContentIntelligenceLoop,
    ContentLoop,
    GOAL_FORMAT_MATRICES,
    GOAL_LABELS,
    STRATEGIC_GOALS,
    build_content_loop_prompt_block,
    compute_content_gaps,
    extract_headline_topic,
    filter_posts_last_n_days,
    normalize_strategic_goal,
)

logger = logging.getLogger(__name__)

#: Rejadagi kunlar soni (Dushanba → Yakshanba).
AUTOPILOT_DAYS = 7

#: Best Time ma'lumoti yetarli bo'lmaganda ishlatiladigan standart soat.
DEFAULT_POST_HOUR = 19

#: Quiet hours dan ko'chirilganda standart ertalabki optimal soat.
DEFAULT_MORNING_OPTIMAL_HOUR = 9

#: Standart tinchlik soatlari (23:00 dan 08:00 gacha).
#: `AUTOPILOT_QUIET_HOURS` env orqali o'zgartiriladi (deploy/operator
#: siyosati); bo'sh yoki noto'g'ri formatda bo'lsa — xavfsiz standart, ya'ni
#: "23:00 - 08:00". Foydalanuvchi avtopilot menyusida o'z qiymatini berishi
#: mumkin — bu faqat STANDART (boshlang'ich) qiymat.
_QUIET_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*[-–—to]+\s*(\d{1,2})(?::(\d{2}))?",
    re.IGNORECASE,
)
_QUIET_HOURS_FALLBACK = "23:00 - 08:00"
_QUIET_HOURS_ENV = (os.getenv("AUTOPILOT_QUIET_HOURS", "") or "").strip()
DEFAULT_QUIET_HOURS = (
    _QUIET_HOURS_ENV if _QUIET_HOURS_ENV and _QUIET_RE.search(_QUIET_HOURS_ENV)
    else _QUIET_HOURS_FALLBACK
)
if _QUIET_HOURS_ENV and DEFAULT_QUIET_HOURS != _QUIET_HOURS_ENV:
    logger.warning(
        "AUTOPILOT_QUIET_HOURS=%r formati noto'g'ri — standart %r ishlatiladi.",
        _QUIET_HOURS_ENV, _QUIET_HOURS_FALLBACK,
    )

#: SEMI_AUTO rejimida avtomatik rejalashtirish uchun minimal sifat balli.
SEMI_AUTO_QUALITY_THRESHOLD = 0.8

#: Kanal tarixini tekshirish oynasi (30 kun).
HISTORY_DAYS_WINDOW = 30
HISTORY_POSTS_LIMIT = 50

#: Mavzular o'xshashligi chegarasi (intra-plan va 30-kunlik tarix uchun).
TOPIC_SIMILARITY_THRESHOLD = 0.75

#: Strategik maqsadlar va chastotalar.
AUTOPILOT_GOALS = STRATEGIC_GOALS
DEFAULT_GOAL = "growth"
ALLOWED_FREQUENCIES = (1, 2, 3)
DEFAULT_FREQUENCY = 1

#: Tasdiqlash rejimlari.
APPROVAL_MANUAL = "MANUAL"
APPROVAL_SEMI_AUTO = "SEMI_AUTO"
APPROVAL_AUTO = "AUTO"
APPROVAL_MODES = (APPROVAL_MANUAL, APPROVAL_SEMI_AUTO, APPROVAL_AUTO)
DEFAULT_APPROVAL_MODE = APPROVAL_MANUAL


class ApprovalMode:
    """Tasdiqlash rejimlari konstanta konteyneri."""

    MANUAL = APPROVAL_MANUAL
    SEMI_AUTO = APPROVAL_SEMI_AUTO
    AUTO = APPROVAL_AUTO


class AutopilotGoal:
    """Strategik maqsadlar konstanta konteyneri."""

    GROWTH = "growth"
    SALES = "sales"
    ENGAGEMENT = "engagement"
    EXPERTISE = "expertise"


@dataclass
class AutopilotConfig:
    """Autopilot V2 strategik konfiguratsiyasi."""

    channel_id: str
    topic: str = ""
    goal: str = DEFAULT_GOAL
    frequency: int = DEFAULT_FREQUENCY
    approval_mode: str = DEFAULT_APPROVAL_MODE
    quiet_hours: str | None = DEFAULT_QUIET_HOURS
    semi_auto_threshold: float = SEMI_AUTO_QUALITY_THRESHOLD

    def normalized(self) -> "AutopilotConfig":
        return AutopilotConfig(
            channel_id=str(self.channel_id or "").strip(),
            topic=str(self.topic or "").strip()[:MAX_TOPIC_LENGTH],
            goal=normalize_goal(self.goal),
            frequency=normalize_frequency(self.frequency),
            approval_mode=normalize_approval_mode(self.approval_mode),
            quiet_hours=format_quiet_hours(self.quiet_hours) if parse_quiet_hours(self.quiet_hours) else None,
            semi_auto_threshold=max(0.1, min(1.0, float(self.semi_auto_threshold or SEMI_AUTO_QUALITY_THRESHOLD))),
        )


#: Yagona vaqt zonasi (scheduler bilan bir xil).
tashkent_tz = pytz.timezone("Asia/Tashkent")

#: AI javobidagi maydon chegaralari (xavfsizlik/bounded).
MAX_TOPIC_LENGTH = 200
MAX_CONTENT_LENGTH = 3500
MAX_FIELD_LENGTH = 300


# ---------------------------------------------------------------------------
# PURE: Strategik parametrlarni normalizatsiya qilish
# ---------------------------------------------------------------------------
def normalize_goal(goal: Any) -> str:
    """Strategik maqsadni kanonik qiymatga keltiradi (PURE).

    ``growth`` | ``sales`` | ``engagement`` | ``expertise``.
    """
    return normalize_strategic_goal(goal)


def normalize_frequency(frequency: Any) -> int:
    """Kunlik post chastotasini ``1``, ``2`` yoki ``3`` ga keltiradi (PURE)."""
    try:
        val = int(frequency)
    except (TypeError, ValueError):
        return DEFAULT_FREQUENCY
    return max(1, min(3, val))


def normalize_approval_mode(mode: Any) -> str:
    """Tasdiqlash rejimini ``MANUAL`` | ``SEMI_AUTO`` | ``AUTO`` ga keltiradi."""
    raw = str(mode or "").strip().upper().replace("-", "_").replace(" ", "_")
    if raw in ("SEMI_AUTO", "SEMIAUTO", "SEMI"):
        return APPROVAL_SEMI_AUTO
    if raw in ("AUTO", "AUTOMATIC", "AVTO"):
        return APPROVAL_AUTO
    return APPROVAL_MANUAL


# ---------------------------------------------------------------------------
# PURE: Quiet Hours va Smart Rescheduling
# ---------------------------------------------------------------------------


def parse_quiet_hours(quiet_hours: Any) -> tuple[int, int] | None:
    """Tinchlik soatlarini ``(start_hour, end_hour)`` ko'rinishida ajratadi (PURE).

    Qo'llab-quvvatlanadi:
      * ``"23:00 - 08:00"``, ``"23-08"``, ``"22:00-07:00"``;
      * ``(23, 8)`` yoki ``[23, 8]``;
      * ``{"start": 23, "end": 8}`` yoki ``{"start": "23:00", "end": "08:00"}``;
      * ``None``, ``""``, ``"off"``, ``"none"``, ``False`` → ``None`` (o'chiq).
    """
    if quiet_hours is None or quiet_hours is False:
        return None
    if isinstance(quiet_hours, (tuple, list)) and len(quiet_hours) >= 2:
        try:
            s, e = int(quiet_hours[0]) % 24, int(quiet_hours[1]) % 24
            return (s, e) if s != e else None
        except (TypeError, ValueError):
            return None
    if isinstance(quiet_hours, dict):
        s_raw = quiet_hours.get("start", quiet_hours.get("from"))
        e_raw = quiet_hours.get("end", quiet_hours.get("to"))
        if s_raw is None or e_raw is None:
            return None
        return parse_quiet_hours(f"{s_raw}-{e_raw}")

    raw = str(quiet_hours).strip().lower()
    if not raw or raw in ("off", "none", "yo'q", "yoq", "disabled", "0", "false"):
        return None
    m = _QUIET_RE.search(raw)
    if not m:
        return None
    try:
        start_h = int(m.group(1)) % 24
        end_h = int(m.group(3)) % 24
    except (TypeError, ValueError):
        return None
    if start_h == end_h:
        return None
    return (start_h, end_h)


def format_quiet_hours(quiet_hours: Any) -> str:
    """Quiet hours juftligini ``"HH:00 - HH:00"`` satriga o'giradi."""
    parsed = parse_quiet_hours(quiet_hours)
    if not parsed:
        return "off"
    return f"{parsed[0]:02d}:00 - {parsed[1]:02d}:00"


def is_in_quiet_hours(
    moment_or_hour: datetime | int,
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
) -> bool:
    """Berilgan vaqt (yoki soat) Quiet Hours ichiga tushishini tekshiradi (PURE).

    Masalan ``23:00 - 08:00`` da:
      * ``23:00``, ``00:00``, ``03:30``, ``07:59`` → ``True`` (tinchlik soati);
      * ``08:00``, ``09:00``, ``19:00``, ``22:59`` → ``False`` (ruxsat etilgan).
    """
    parsed = parse_quiet_hours(quiet_hours)
    if not parsed:
        return False
    start_h, end_h = parsed
    if isinstance(moment_or_hour, datetime):
        hour = moment_or_hour.hour
    else:
        try:
            hour = int(moment_or_hour) % 24
        except (TypeError, ValueError):
            return False

    if start_h > end_h:
        # Tun osha: masalan 23:00 -> 08:00
        return hour >= start_h or hour < end_h
    # Bir sutka ichida: masalan 01:00 -> 07:00
    return start_h <= hour < end_h


def resolve_morning_optimal_hour(
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
    best_hours: list[int] | None = None,
    default_hour: int = DEFAULT_MORNING_OPTIMAL_HOUR,
) -> int:
    """Quiet Hours tugagandan keyingi ertalabki ruxsat etilgan optimal soat (PURE).

    Qoida:
      1. Agar ``best_hours`` ichida ertalabki ruxsat etilgan soat bo'lsa
         (``quiet_end <= h <= 12`` va quiet hours ichida emas) — o'sha tanlanadi;
      2. Aks holda ``default_hour`` (masalan 09:00) ruxsat etilgan bo'lsa va
         ``quiet_end <= default_hour <= 11`` bo'lsa — u tanlanadi;
      3. Aks holda ``quiet_end`` (masalan ``08:00``) qaytariladi.
    """
    parsed = parse_quiet_hours(quiet_hours)
    if not parsed:
        return max(6, min(11, int(default_hour or DEFAULT_MORNING_OPTIMAL_HOUR)))
    _, end_h = parsed

    # 1) Kanalning best_hours ro'yxatidan ertalabki optimal soatni qidiramiz
    for candidate in best_hours or ():
        try:
            h = int(candidate) % 24
        except (TypeError, ValueError):
            continue
        if not is_in_quiet_hours(h, parsed) and end_h <= h <= 12:
            return h

    # 2) Ertalabki standart optimal soat (masalan 09:00 yoki quiet_end)
    if not is_in_quiet_hours(end_h, parsed):
        if end_h <= int(default_hour or 9) <= min(11, end_h + 2) and not is_in_quiet_hours(int(default_hour or 9), parsed):
            return int(default_hour or 9)
        return end_h

    # Fallback: birinchi ruxsat etilgan soat
    for offset in range(24):
        cand = (end_h + offset) % 24
        if not is_in_quiet_hours(cand, parsed):
            return cand
    return DEFAULT_MORNING_OPTIMAL_HOUR


def reschedule_from_quiet_hours(
    moment: datetime,
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
    best_hours: list[int] | None = None,
    preserve_date: bool = False,
) -> tuple[datetime, bool]:
    """Quiet Hours ga tushgan vaqtni ertalabki optimal vaqtga ko'chiradi (PURE).

    Qaytadi: ``(yangi_datetime, ko_chirildimi_bool)``.
    Agar ``moment`` Quiet Hours ga tushmasa — ``(moment, False)`` o'zgarishsiz qaytadi.
    """
    if not isinstance(moment, datetime):
        raise TypeError("moment must be a datetime instance")
    parsed = parse_quiet_hours(quiet_hours)
    if not parsed or not is_in_quiet_hours(moment, parsed):
        return moment, False

    start_h, end_h = parsed
    target_hour = resolve_morning_optimal_hour(parsed, best_hours=best_hours)

    tz = moment.tzinfo
    target_date = moment.date()
    if not preserve_date and start_h > end_h and moment.hour >= start_h:
        # Kechki tinchlik soati (masalan 23:00..23:59) → keyingi kun ertalabki optimal vaqt
        target_date = target_date + timedelta(days=1)

    naive_target = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        int(target_hour) % 24,
        0,
        0,
    )
    if tz is not None:
        if hasattr(tz, "localize"):
            adjusted = tz.localize(naive_target)
        else:
            adjusted = naive_target.replace(tzinfo=tz)
    else:
        adjusted = naive_target
    return adjusted, True


def apply_quiet_hours(
    moment: datetime,
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
    best_hours: list[int] | None = None,
    preserve_date: bool = False,
) -> datetime:
    """Quiet Hours qoidasini qo'llab, ruxsat etilgan ``datetime`` qaytaradi (PURE)."""
    adjusted, _ = reschedule_from_quiet_hours(
        moment,
        quiet_hours=quiet_hours,
        best_hours=best_hours,
        preserve_date=preserve_date,
    )
    return adjusted


def build_daily_slot_hours(
    frequency: int = DEFAULT_FREQUENCY,
    primary_hour: int = DEFAULT_POST_HOUR,
    best_hours: list[int] | None = None,
    quiet_hours: Any = None,
) -> list[dict]:
    """Bir kun ichidagi ``frequency`` (1, 2 yoki 3) ta post soatlarini belgilaydi (PURE).

    Har bir slot Quiet Hours ga tekshiriladi va tushib qolsa ertalabki ruxsat
    etilgan optimal vaqtga ko'chiriladi. Bir kun ichida ikki slot bir xil
    soatga tushib qolmasligi kafolatlanadi.
    """
    freq = normalize_frequency(frequency)
    parsed_qh = parse_quiet_hours(quiet_hours)
    morning_opt = resolve_morning_optimal_hour(parsed_qh, best_hours=best_hours)

    # Boshlang'ich nomzod soatlar
    candidates: list[int] = []
    if best_hours:
        for h in best_hours:
            try:
                hv = int(h) % 24
                if hv not in candidates:
                    candidates.append(hv)
            except (TypeError, ValueError):
                continue

    p_hour = int(primary_hour if primary_hour is not None else DEFAULT_POST_HOUR) % 24
    if p_hour not in candidates:
        candidates.insert(0, p_hour)

    # Chastotaga mos standart balanslangan kunlik slotlar (ertalab / kunduzi / kechqurun)
    default_spread = {
        1: [p_hour],
        2: [morning_opt, p_hour if p_hour != morning_opt else 19],
        3: [morning_opt, 14, p_hour if p_hour not in (morning_opt, 14) else 19],
    }[freq]
    for h in default_spread:
        if h not in candidates:
            candidates.append(h)

    chosen = candidates[:freq]
    used_hours: set[int] = set()
    slots: list[dict] = []

    for slot_idx, raw_hour in enumerate(chosen):
        orig_hour = int(raw_hour) % 24
        rescheduled = False
        final_hour = orig_hour
        if parsed_qh and is_in_quiet_hours(final_hour, parsed_qh):
            final_hour = morning_opt
            rescheduled = True

        # Agar bu soat shu kunda band bo'lsa, keyingi ruxsat etilgan bo'sh soatga suramiz
        attempts = 0
        while final_hour in used_hours and attempts < 24:
            final_hour = (final_hour + 2) % 24
            if parsed_qh and is_in_quiet_hours(final_hour, parsed_qh):
                final_hour = (morning_opt + attempts + 1) % 24
                if parsed_qh and is_in_quiet_hours(final_hour, parsed_qh):
                    final_hour = morning_opt
            attempts += 1

        used_hours.add(final_hour)
        slots.append({
            "slot_index": slot_idx,
            "hour": final_hour,
            "original_hour": orig_hour,
            "rescheduled_from_quiet_hours": rescheduled,
        })

    # Kun ichida vaqt bo'yicha tartiblaymiz (agar bitta post bo'lsa o'z joyida)
    if len(slots) > 1:
        slots.sort(key=lambda s: s["hour"])
        for idx, s in enumerate(slots):
            s["slot_index"] = idx
    return slots


# ---------------------------------------------------------------------------
# PURE: vaqtinchalik reja (deterministik, testlanadigan)
# ---------------------------------------------------------------------------
def next_week_start(now: datetime | None = None, hour: int = DEFAULT_POST_HOUR,
                    minute: int = 0) -> datetime:
    """Reja boshlanadigan Dushanba soat ``hour:minute`` (Toshkent).

    Qoida (``handlers.content_plan.week_schedule_times`` bilan bir xil):
    shu haftaning dushanbasi o'tib bo'lsa — KEYINGI hafta dushanbasidan
    boshlanadi, shunda hech bir post o'tmishga tushmaydi.
    """
    reference = now if now is not None else datetime.now(tashkent_tz)
    if reference.tzinfo is None:
        reference = tashkent_tz.localize(reference)
    reference = reference.astimezone(tashkent_tz)

    days_to_monday = (0 - reference.weekday()) % 7
    monday = (reference + timedelta(days=days_to_monday)).date()
    first = tashkent_tz.localize(
        datetime(monday.year, monday.month, monday.day, int(hour) % 24,
                 int(minute) % 60))
    if first <= reference:
        first = first + timedelta(days=7)
    return first


def week_times(count: int = AUTOPILOT_DAYS, hour: int = DEFAULT_POST_HOUR,
               minute: int = 0, now: datetime | None = None) -> list[datetime]:
    """Dushanbadan boshlab ``count`` kun uchun aware datetime ro'yxati."""
    first = next_week_start(now=now, hour=hour, minute=minute)
    return [first + timedelta(days=i) for i in range(max(0, int(count)))]


def resolve_post_hour(best_time_result: dict | None, quiet_hours: Any = None) -> int:
    """Best Time natijasidan post soatini oladi (insufficient → default).

    Soxta raqamlar uydirmaydi: ``insufficient``/buzilgan natijada
    ``DEFAULT_POST_HOUR`` qaytadi (foydalanuvchiga ochiq aytiladi).
    Agar ``quiet_hours`` berilgan bo'lsa va soat Quiet Hours ga tushsa —
    ertalabki ruxsat etilgan optimal soat qaytariladi.
    """
    result = best_time_result if isinstance(best_time_result, dict) else {}
    if result.get("insufficient"):
        hour = DEFAULT_POST_HOUR
    else:
        peak = result.get("peak_hour")
        try:
            peak_int = int(peak)
            hour = peak_int if 0 <= peak_int <= 23 else DEFAULT_POST_HOUR
        except (TypeError, ValueError):
            hour = DEFAULT_POST_HOUR

    if quiet_hours is not None and is_in_quiet_hours(hour, quiet_hours):
        return resolve_morning_optimal_hour(quiet_hours)
    return hour


def compose_post_text(content: str, cta: str) -> str:
    """Post matni + CTA bitta tayyor matnga birlashtiriladi (PURE).

    CTA bo'sh bo'lsa yoki matn ichida allaqachon bo'lsa — qo'shilmaydi.
    """
    body = str(content or "").strip()
    tail = str(cta or "").strip()
    if not tail:
        return body
    if tail and tail.lower() in body.lower():
        return body
    return f"{body}\n\n{tail}" if body else tail


def _bounded(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def normalize_ai_plan(payload: Any, days: int = AUTOPILOT_DAYS) -> list[dict]:
    """AI JSON javobini QAT'IY normalizatsiya qiladi (PURE).

    Har bir kun: ``{"topic", "format", "content", "cta"}`` (+ ixtiyoriy
    ``quality_score``, ``scheduled_hour``). Kamida bitta kun matnsiz bo'lsa
    YOKI kunlar soni yetmasa — ``[]`` (yarim-yorti reja QAT'IYAN YO'Q).
    """
    if not isinstance(payload, dict):
        return []
    items = (payload.get("days") or payload.get("plan")
             or payload.get("posts") or payload.get("items"))
    if not isinstance(items, list):
        return []
    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            return []
        content = _bounded(item.get("content") or item.get("post")
                           or item.get("text"), MAX_CONTENT_LENGTH)
        if not content:
            return []
        entry: dict[str, Any] = {
            "topic": _bounded(item.get("topic") or item.get("theme"),
                              MAX_TOPIC_LENGTH),
            "format": _bounded(item.get("format") or item.get("type"),
                               MAX_FIELD_LENGTH),
            "content": content,
            "cta": _bounded(item.get("cta"), MAX_FIELD_LENGTH),
        }
        if item.get("quality_score") is not None:
            try:
                qs = float(item["quality_score"])
                if qs > 1.0 and qs <= 100.0:
                    qs = qs / 100.0
                entry["quality_score"] = round(max(0.0, min(1.0, qs)), 4)
            except (TypeError, ValueError):
                pass
        if item.get("hour") is not None or item.get("scheduled_hour") is not None:
            raw_h = item.get("hour") if item.get("hour") is not None else item.get("scheduled_hour")
            try:
                entry["hour"] = int(raw_h) % 24
            except (TypeError, ValueError):
                pass
        normalized.append(entry)
    if len(normalized) != int(days) or len(normalized) == 0:
        return []
    return normalized


# ---------------------------------------------------------------------------
# PURE: Sifat baholash (Quality Score 0.0..1.0) va Approval Modes
# ---------------------------------------------------------------------------
def compute_post_quality_score(
    item: dict | str,
    dna_profile: dict | None = None,
    goal: str = DEFAULT_GOAL,
    lang: str = "uz",
) -> float:
    """Post sifatini ``0.0 .. 1.0`` shkalada deterministik hisoblaydi (PURE).

    Agar ``item`` dict ichida oldindan ``quality_score`` berilgan bo'lsa —
    o'sha qiymat (0.0..1.0 oralig'ida) qaytariladi. Aks holda:
      * ``utils.post_scorer.score_post_locally`` (headline, readability, cta,
        engagement, sales_power, structure);
      * mavzu, format va CTA to'liqligi;
      * Channel DNA uzunlik va CTA uslubiga moslik
    asosida hisoblanadi.
    """
    if isinstance(item, dict) and item.get("quality_score") is not None:
        try:
            qs = float(item["quality_score"])
            if qs > 1.0 and qs <= 100.0:
                qs = qs / 100.0
            return round(max(0.0, min(1.0, qs)), 4)
        except (TypeError, ValueError):
            pass

    if isinstance(item, dict):
        content = str(item.get("content") or "").strip()
        cta = str(item.get("cta") or "").strip()
        post_text = str(item.get("post_text") or compose_post_text(content, cta)).strip()
        topic = str(item.get("topic") or "").strip()
        fmt = str(item.get("format") or "").strip()
    else:
        post_text = str(item or "").strip()
        content = post_text
        cta = ""
        topic = ""
        fmt = ""

    if not post_text or len(post_text) < 15:
        return 0.2

    base_score = 0.65
    try:
        from utils.post_scorer import score_post_locally
        local_res = score_post_locally(post_text, lang=lang)
        overall_100 = float(local_res.get("overall") or 65.0)
        base_score = max(0.1, min(1.0, overall_100 / 100.0))
    except Exception:
        pass

    bonus = 0.0
    if len(post_text) >= 60:
        bonus += 0.12
    if cta or "👉" in post_text or "@" in post_text or "t.me/" in post_text:
        bonus += 0.08
    if topic and len(topic) >= 3:
        bonus += 0.05
    if fmt and len(fmt) >= 2:
        bonus += 0.05
    if "<b>" in post_text or "\n\n" in post_text:
        bonus += 0.05

    # Channel DNA mosligi
    if isinstance(dna_profile, dict) and dna_profile:
        avg_len = dna_profile.get("average_post_length") or dna_profile.get("avg_length_value")
        if isinstance(avg_len, (int, float)) and avg_len > 0:
            ratio = len(post_text) / float(avg_len)
            if 0.3 <= ratio <= 2.5:
                bonus += 0.04

    final = max(0.0, min(0.99, base_score + bonus))
    return round(final, 4)


def validate_approval_mode_access(
    approval_mode: Any,
    is_pro: bool = False,
) -> dict:
    """Tasdiqlash rejimi ruxsatini tekshiradi (AUTO faqat PRO uchun).

    Qaytadi::

        {"allowed": bool, "mode": "MANUAL"|"SEMI_AUTO"|"AUTO",
         "error_code": None | "PRO_REQUIRED", "message": str | None}
    """
    mode = normalize_approval_mode(approval_mode)
    if mode == APPROVAL_AUTO and not bool(is_pro):
        return {
            "allowed": False,
            "mode": mode,
            "error_code": "PRO_REQUIRED",
            "message": "AUTO rejimi faqat 💎 PRO foydalanuvchilar uchun mavjud.",
        }
    return {
        "allowed": True,
        "mode": mode,
        "error_code": None,
        "message": None,
    }


def partition_by_approval_mode(
    days: list[dict],
    approval_mode: Any = APPROVAL_MANUAL,
    *,
    is_pro: bool = False,
    semi_auto_threshold: float = SEMI_AUTO_QUALITY_THRESHOLD,
    duplicate_indices: set[int] | list[int] | None = None,
) -> dict:
    """Postlarni ``approval_mode`` bo'yicha avtomatik va tasdiqlanadigan guruhlarga ajratadi (PURE).

    Rejimlar:
      * ``MANUAL``: barcha postlar foydalanuvchi tasdig'ini kutadi
        (``auto_schedule=[]``, ``needs_approval=[...]``);
      * ``SEMI_AUTO``: ``quality_score >= semi_auto_threshold`` VA dublikat
        bo'lmagan postlar ``auto_schedule`` ga tushadi; past balli yoki
        shubhali postlar ``needs_approval`` ga yuboriladi;
      * ``AUTO``: faqat ``is_pro=True`` bo'lganda ruxsat beriladi va barcha
        toza postlar ``auto_schedule`` ga tushadi (FREE bo'lsa ``allowed=False``,
        ``error_code='PRO_REQUIRED'``).
    """
    access = validate_approval_mode_access(approval_mode, is_pro=is_pro)
    mode = access["mode"]
    thr = max(0.0, min(1.0, float(semi_auto_threshold or SEMI_AUTO_QUALITY_THRESHOLD)))
    dup_set = {int(i) for i in (duplicate_indices or ())}

    if not access["allowed"]:
        return {
            "allowed": False,
            "mode": mode,
            "error_code": access["error_code"],
            "message": access["message"],
            "threshold": thr,
            "auto_schedule_indices": [],
            "needs_approval_indices": [int(d.get("index", idx)) for idx, d in enumerate(days or [])],
            "auto_schedule_days": [],
            "needs_approval_days": list(days or []),
        }

    auto_indices: list[int] = []
    review_indices: list[int] = []
    auto_days: list[dict] = []
    review_days: list[dict] = []

    for pos, day in enumerate(days or []):
        if not isinstance(day, dict) or day.get("approval_status") == "deleted":
            continue
        idx = int(day.get("index", pos))
        q_score = compute_post_quality_score(day)
        day["quality_score"] = q_score
        is_dup = idx in dup_set

        if mode == APPROVAL_MANUAL:
            if day.get("approval_status") not in ("approved", "scheduled", "auto_scheduled"):
                day["approval_status"] = "pending_approval"
            review_indices.append(idx)
            review_days.append(day)
        elif mode == APPROVAL_SEMI_AUTO:
            if q_score >= thr and not is_dup:
                day["approval_status"] = "auto_scheduled"
                auto_indices.append(idx)
                auto_days.append(day)
            else:
                day["approval_status"] = "needs_review"
                review_indices.append(idx)
                review_days.append(day)
        elif mode == APPROVAL_AUTO:
            if not is_dup:
                day["approval_status"] = "auto_scheduled"
                auto_indices.append(idx)
                auto_days.append(day)
            else:
                day["approval_status"] = "needs_review"
                review_indices.append(idx)
                review_days.append(day)

    return {
        "allowed": True,
        "mode": mode,
        "error_code": None,
        "message": None,
        "threshold": thr,
        "auto_schedule_indices": auto_indices,
        "needs_approval_indices": review_indices,
        "auto_schedule_days": auto_days,
        "needs_approval_days": review_days,
    }


# ---------------------------------------------------------------------------
# AI generatsiya (yagona patch nuqtasi — testlar tarmoqsiz ishlaydi)
# ---------------------------------------------------------------------------
async def generate_autopilot_week(
    topic: str,
    lang: str = "uz",
    dna_block: str = "",
    best_hour: int | None = None,
    days: int = AUTOPILOT_DAYS,
) -> list[dict]:
    """AI orqali ``days`` ta post rejasini oladi (xatoda — [])."""
    try:
        from services.ai_service import run_ai_chain
        from utils.ai_agent import _extract_json
    except Exception:  # pragma: no cover — import xatosi (test muhiti)
        return []

    clean_topic = str(topic or "").strip()[:MAX_TOPIC_LENGTH]
    if not clean_topic:
        return []

    hour_line = ""
    if best_hour is not None:
        hour_line = (
            f"Har bir kun uchun tavsiya etilgan soat: {int(best_hour) % 24}:00 "
            "(kanal statistikasi bo'yicha). Vaqtlarni shu soat atrofida "
            "taklif qilishingiz mumkin.\n"
        )
    system = (
        "Siz tajribali SMM kontent-strategisiz. Faqat JSON qaytaring:\n"
        '{"days": [{"topic": "...", "format": "...", "content": "...", '
        '"cta": "..."}]}\n'
        f"Aynan {int(days)} ta yozuv bo'lsin, boshqa matn qo'shmang. "
        "Har bir postning mavzusi (topic) va matni (content) bir-biridan "
        "TUBDAN FARQ QILSIN (dublikat bo'lmasin). "
        "\"content\" — kanalga chiqadigan TO'LIQ tayyor post matni (sarlavha, "
        "matn, emoji bilan), \"cta\" — qisqa chaqiruv amali."
    )
    prompt = (
        f"Mavzu/yo'nalish: {clean_topic}\n"
        f"{hour_line}"
        f"7 kunlik (Dushanba–Yakshanba) jami {int(days)} ta SMM post rejasi tuzing. "
        "Har bir post uchun: topic (qisqa noyob mavzu), format (masalan: e'lon / "
        "savol-javob / case / chegirma / foydali maslahat / poll / tahlil), "
        "content (tayyor post matni) va cta (chaqiruv amali).\n"
    )
    if dna_block:
        prompt = f"{dna_block}\n\n{prompt}"

    try:
        result = await run_ai_chain(prompt, system, lang)
    except Exception:
        logger.warning("Avtopilot AI generatsiya xatosi", exc_info=True)
        return []
    if not isinstance(result, dict) or result.get("error"):
        return []
    text = result.get("text") or result.get("content") or ""
    if not text:
        return []
    try:
        payload = _extract_json(text)
    except Exception:
        logger.warning("Avtopilot javobini JSON qilib o'qib bo'lmadi")
        return []
    return normalize_ai_plan(payload, days)


async def rewrite_flagged_posts(
    topic: str,
    flagged: list[dict],
    lang: str = "uz",
    dna_block: str = "",
) -> list[dict]:
    """Dublikat deb topilgan postlarni AI bilan YANGILAYDI (boshqacha qiladi).

    ``flagged`` — ``{"index", "content"}`` ro'yxati. Qaytadi: yangilangan
    ``{"index", "content"}`` ro'yxati YOKI xatoda ``[]``.
    """
    if not flagged:
        return []
    try:
        from services.ai_service import run_ai_chain
        from utils.ai_agent import _extract_json
    except Exception:  # pragma: no cover
        return []

    system = (
        "Siz SMM copywriter'siz. Faqat JSON qaytaring:\n"
        '{"posts": [{"index": 0, "content": "...", "topic": "..."}]}\n'
        "Har bir postni umumiy yo'nalish doirasida, lekin burchagi, tuzilishi, "
        "hook va so'zlarini BUTUNLAY BOSHQACHA qilib qayta yozing."
    )
    listed = "\n".join(
        f"{int(item.get('index', 0))}: {str(item.get('content', ''))[:600]}"
        for item in flagged
    )
    prompt = (
        f"Umumiy mavzu: {str(topic or '')[:MAX_TOPIC_LENGTH]}\n\n"
        f"Quyidagi postlar kanalda yaqinda chiqqan postlarga yoki rejadagi "
        f"boshqa postlarga juda o'xshab qoldi. Har birini ANIQ boshqacha qilib "
        f"qayta yozing (index saqlansin):\n\n{listed}\n\n{dna_block or ''}"
    )
    try:
        result = await run_ai_chain(prompt, system, lang)
    except Exception:
        logger.warning("Avtopilot dublikat-rewrite xatosi", exc_info=True)
        return []
    if not isinstance(result, dict) or result.get("error"):
        return []
    text = result.get("text") or result.get("content") or ""
    try:
        payload = _extract_json(text)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    posts = payload.get("posts") or payload.get("days") or []
    rewritten = []
    for item in posts:
        if not isinstance(item, dict):
            continue
        content = _bounded(item.get("content") or item.get("post"),
                           MAX_CONTENT_LENGTH)
        if not content:
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        entry = {"index": index, "content": content}
        if item.get("topic"):
            entry["topic"] = _bounded(item.get("topic"), MAX_TOPIC_LENGTH)
        rewritten.append(entry)
    return rewritten


# ---------------------------------------------------------------------------
# Rejani yig'ish (AI natijasi + vaqtlar + Quiet Hours + Strategy → to'liq kunlar)
# ---------------------------------------------------------------------------
def build_week_plan(
    day_items: list[dict],
    hour: int = DEFAULT_POST_HOUR,
    minute: int = 0,
    now: datetime | None = None,
    *,
    frequency: int = DEFAULT_FREQUENCY,
    quiet_hours: Any = None,
    best_hours: list[int] | None = None,
    goal: str = DEFAULT_GOAL,
    recommended_formats: list[str] | None = None,
    content_gaps: list[str] | None = None,
    dna_profile: dict | None = None,
) -> list[dict]:
    """Normalizatsiyalangan AI kunlariga aniq vaqtlar, Quiet Hours va strategiyani ulaydi (PURE).

    Qaytadi — postlar ro'yxati (Dushanba → Yakshanba, ``frequency`` hisobga olingan)::

        {"index": 0, "day_number": 1, "slot_index": 0, "weekday": 0,
         "date": "21.09", "time": "19:00", "scheduled_time": <aware datetime>,
         "topic": "...", "format": "...", "content": "...", "cta": "...",
         "post_text": "tayyor matn + CTA", "quality_score": 0.91,
         "goal": "growth", "gap_filled": bool,
         "rescheduled_from_quiet_hours": bool, "original_time": "23:00" | None,
         "approval_status": "pending_approval"}
    """
    freq = normalize_frequency(frequency)
    canon_goal = normalize_goal(goal)
    parsed_qh = parse_quiet_hours(quiet_hours)

    # Kunlik slot soatlarini hisoblaymiz
    daily_slots = build_daily_slot_hours(
        frequency=freq,
        primary_hour=hour,
        best_hours=best_hours,
        quiet_hours=parsed_qh,
    )
    first_slot_hour = daily_slots[0]["hour"] if daily_slots else (int(hour) % 24)
    base_monday = next_week_start(now=now, hour=first_slot_hour, minute=minute)
    monday_date = base_monday.date()

    gap_set = {str(g).strip().lower() for g in (content_gaps or ()) if str(g).strip()}
    rec_fmts = list(recommended_formats or ())

    days: list[dict] = []
    for index, item in enumerate(day_items or []):
        item = item or {}
        if freq == 1:
            day_idx = index
            slot_idx = 0
        else:
            day_idx = index // freq
            slot_idx = index % freq

        slot_meta = daily_slots[min(slot_idx, len(daily_slots) - 1)]
        slot_hour = slot_meta["hour"]
        orig_hour = slot_meta["original_hour"]
        rescheduled = bool(slot_meta["rescheduled_from_quiet_hours"])

        # Agar item ichida maxsus soat berilgan bo'lsa (masalan AI yoki test tomonidan)
        if item.get("hour") is not None:
            try:
                custom_h = int(item["hour"]) % 24
                orig_hour = custom_h
                if parsed_qh and is_in_quiet_hours(custom_h, parsed_qh):
                    slot_hour = resolve_morning_optimal_hour(parsed_qh, best_hours=best_hours)
                    rescheduled = True
                else:
                    slot_hour = custom_h
                    rescheduled = False
            except (TypeError, ValueError):
                pass

        day_date = monday_date + timedelta(days=day_idx)
        moment = tashkent_tz.localize(
            datetime(
                day_date.year,
                day_date.month,
                day_date.day,
                int(slot_hour) % 24,
                int(minute) % 60,
            )
        )
        # Qo'shimcha himoya: agar moment quiet_hours ichida bo'lsa, ertalabga ko'chiramiz
        if parsed_qh and is_in_quiet_hours(moment, parsed_qh):
            moment, was_shifted = reschedule_from_quiet_hours(
                moment,
                quiet_hours=parsed_qh,
                best_hours=best_hours,
                preserve_date=True,
            )
            rescheduled = rescheduled or was_shifted

        content = str(item.get("content") or "").strip()
        cta = str(item.get("cta") or "").strip()
        raw_fmt = str(item.get("format") or "").strip()
        if (not raw_fmt or raw_fmt.lower() in ("post", "text", "oddiy")) and index < len(rec_fmts):
            fmt = rec_fmts[index]
        else:
            fmt = raw_fmt or (rec_fmts[index] if index < len(rec_fmts) else "post")

        post_text = compose_post_text(content, cta)
        entry: dict[str, Any] = {
            "index": index,
            "day_number": (day_idx % AUTOPILOT_DAYS) + 1,
            "slot_index": slot_idx,
            "weekday": moment.weekday(),
            "date": moment.strftime("%d.%m"),
            "time": moment.strftime("%H:%M"),
            "scheduled_time": moment,
            "topic": str(item.get("topic") or "").strip(),
            "format": fmt,
            "content": content,
            "cta": cta,
            "post_text": post_text,
            "goal": canon_goal,
            "gap_filled": fmt.lower() in gap_set or bool(gap_set and index < len(gap_set)),
            "rescheduled_from_quiet_hours": rescheduled,
            "original_time": f"{int(orig_hour) % 24:02d}:{int(minute) % 60:02d}" if rescheduled else None,
            "approval_status": str(item.get("approval_status") or "pending_approval"),
        }
        if item.get("quality_score") is not None:
            entry["quality_score"] = compute_post_quality_score(
                {"quality_score": item.get("quality_score")},
                dna_profile=dna_profile,
                goal=canon_goal,
            )
        else:
            entry["quality_score"] = compute_post_quality_score(
                entry,
                dna_profile=dna_profile,
                goal=canon_goal,
            )
        days.append(entry)
    return days


def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    run_db = getattr(db, "run_db", None)
    if run_db is not None:
        return await run_db(fn, *args, **kwargs)
    return fn(*args, **kwargs)


async def check_user_is_pro(user_id: int, db_module: Any = None) -> bool:
    """Foydalanuvchi PRO (yoki admin) ekanini tekshiradi (fail-closed: False)."""
    db = db_module if db_module is not None else _import_database()
    try:
        from config import ADMIN_IDS
        if int(user_id) in (ADMIN_IDS or ()):
            return True
    except Exception:
        pass
    if db is None:
        return False
    try:
        if hasattr(db, "is_premium"):
            return bool(await _db_call(db, db.is_premium, int(user_id)))
        if hasattr(db, "get_user_plan"):
            plan_info = await _db_call(db, db.get_user_plan, int(user_id))
            if isinstance(plan_info, dict):
                return bool(plan_info.get("is_pro")) or str(plan_info.get("plan_type") or "").lower() in ("pro", "enterprise", "vip")
            if isinstance(plan_info, str):
                return plan_info.lower() in ("pro", "enterprise", "vip")
    except Exception:
        logger.debug("check_user_is_pro xatosi (user=%s)", user_id, exc_info=True)
    return False


async def _call_generate_autopilot_week(
    topic: str,
    *,
    lang: str,
    dna_block: str,
    best_hour: int,
    total_posts: int,
) -> list[dict]:
    """``generate_autopilot_week`` ni imzosiga mos chaqiradi (monkeypatch-safe)."""
    fn = generate_autopilot_week
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
    except Exception:
        params = {}

    if total_posts != AUTOPILOT_DAYS and ("days" in params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )):
        return await fn(
            topic,
            lang=lang,
            dna_block=dna_block,
            best_hour=best_hour,
            days=total_posts,
        )
    items = await fn(topic, lang=lang, dna_block=dna_block, best_hour=best_hour)
    if items and len(items) < total_posts:
        # Agar monkeypatch 7 ta qaytarsa va frequency > 1 bo'lsa, mavzularni boyitib kengaytiramiz
        expanded: list[dict] = []
        for idx in range(total_posts):
            base = dict(items[idx % len(items)])
            if idx >= len(items):
                slot_no = (idx // AUTOPILOT_DAYS) + 1
                base["topic"] = f"{base.get('topic', 'Mavzu')} ({slot_no}-qism)"[:MAX_TOPIC_LENGTH]
                base["content"] = (
                    f"{base.get('content', '')}\n\n💡 Qo'shimcha nuqta #{slot_no}: "
                    f"{topic} bo'yicha amaliy tavsiya."
                )[:MAX_CONTENT_LENGTH]
            expanded.append(base)
        return expanded
    return items


async def create_autopilot_plan(
    user_id: int,
    channel_id: str | int,
    topic: str,
    lang: str = "uz",
    db_module: Any = None,
    *,
    goal: str = DEFAULT_GOAL,
    frequency: int = DEFAULT_FREQUENCY,
    approval_mode: str = DEFAULT_APPROVAL_MODE,
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
    is_pro: bool | None = None,
    semi_auto_threshold: float = SEMI_AUTO_QUALITY_THRESHOLD,
    now: datetime | None = None,
) -> dict:
    """Kanal DNA + ContentLoop + Best Time asosida 7 kunlik strategik reja tuzadi (IDOR himoyasi).

    Qaytadi::

        {"ok": True, "days": [...], "hour": 19,
         "hour_source": "best_time" | "default",
         "best_window": "19:00 - 21:00" | None,
         "dna_attached": bool, "content_loop_attached": bool,
         "goal": "growth", "frequency": 1, "approval_mode": "MANUAL",
         "quiet_hours": "23:00 - 08:00", "quiet_hours_rescheduled": bool,
         "content_gaps": [...], "duplicate_report": {...},
         "approval_summary": {...}, "message": None}

    Xato/malumot yetmasa::

        {"ok": False, "error_code": "FORBIDDEN" | "DB_UNAVAILABLE" |
         "AI_FAILED" | "INVALID_TOPIC" | "PRO_REQUIRED", "message": "..."}
    """
    from services.channels.best_time import get_best_time
    from services.channels.dna import build_dna_system_prompt, get_channel_dna

    clean_topic = str(topic or "").strip()
    if len(clean_topic) < 3:
        return {"ok": False, "error_code": "INVALID_TOPIC",
                "message": "Mavzu juda qisqa"}
    clean_topic = clean_topic[:MAX_TOPIC_LENGTH]

    canon_goal = normalize_goal(goal)
    freq = normalize_frequency(frequency)
    mode = normalize_approval_mode(approval_mode)
    db = db_module if db_module is not None else _import_database()

    # AUTO rejimi faqat PRO foydalanuvchilar uchun
    resolved_pro = bool(is_pro) if is_pro is not None else await check_user_is_pro(user_id, db_module=db)
    access = validate_approval_mode_access(mode, is_pro=resolved_pro)
    if not access["allowed"]:
        return {
            "ok": False,
            "error_code": access["error_code"],
            "message": access["message"],
        }

    dna_result = await get_channel_dna(channel_id, user_id, db_module=db)
    if not dna_result.get("ok"):
        return {"ok": False, "error_code": dna_result.get("error_code",
                                                          "DB_UNAVAILABLE"),
                "message": dna_result.get("message", "Kanal topilmadi")}
    best_result = await get_best_time(channel_id, user_id, db_module=db)
    if not best_result.get("ok"):
        return {"ok": False, "error_code": best_result.get("error_code",
                                                           "DB_UNAVAILABLE"),
                "message": best_result.get("message", "Kanal topilmadi")}

    # ContentLoop: Gaps + 30-kunlik tarix + best_hours
    loop_data = await ContentLoop(db_module=db).analyze(
        channel_id,
        user_id,
        goal=canon_goal,
        frequency=freq,
        days=AUTOPILOT_DAYS,
        lang=lang,
        now=now,
    )
    content_gaps = loop_data.get("content_gaps") or []
    recommended_formats = loop_data.get("recommended_formats") or []
    best_hours = loop_data.get("best_hours") or []
    recent_texts = loop_data.get("recent_texts") or []
    recent_topics = loop_data.get("recent_topics") or []

    raw_hour = resolve_post_hour(best_result)
    hour_source = "default" if best_result.get("insufficient") else "best_time"
    best_window = best_result.get("top_window")

    # Quiet hours (agar berilgan bo'lsa)
    effective_qh = quiet_hours
    hour = resolve_post_hour(best_result, quiet_hours=effective_qh)

    dna_block = ""
    dna_attached = False
    profile = dna_result.get("profile")
    if isinstance(profile, dict) and profile:
        block = build_dna_system_prompt(profile, lang=lang)
        if block:
            dna_block = block
            dna_attached = True

    total_posts = AUTOPILOT_DAYS * freq
    day_items = await _call_generate_autopilot_week(
        clean_topic,
        lang=lang,
        dna_block=dna_block,
        best_hour=hour,
        total_posts=total_posts,
    )
    if not day_items:
        return {"ok": False, "error_code": "AI_FAILED",
                "message": "Reja tuzilmadi"}

    days = build_week_plan(
        day_items,
        hour=raw_hour,
        now=now,
        frequency=freq,
        quiet_hours=effective_qh,
        best_hours=best_hours,
        goal=canon_goal,
        recommended_formats=recommended_formats,
        content_gaps=content_gaps,
        dna_profile=profile if isinstance(profile, dict) else None,
    )

    # Dublikat tahlili (7-kunlik reja ichida + 30-kunlik kanal tarixi)
    dup_report = check_plan_duplicates(
        days,
        recent_texts=recent_texts,
        recent_topics=recent_topics,
    )

    # Approval mode taqsimoti
    approval_summary = partition_by_approval_mode(
        days,
        mode,
        is_pro=resolved_pro,
        semi_auto_threshold=semi_auto_threshold,
        duplicate_indices=dup_report.get("flagged") or [],
    )

    rescheduled_count = sum(1 for d in days if d.get("rescheduled_from_quiet_hours"))
    return {
        "ok": True,
        "days": days,
        "hour": days[0]["scheduled_time"].hour if days else hour,
        "hour_source": hour_source,
        "best_window": best_window,
        "dna_attached": dna_attached,
        "content_loop_attached": True,
        "goal": canon_goal,
        "frequency": freq,
        "approval_mode": mode,
        "quiet_hours": format_quiet_hours(effective_qh) if parse_quiet_hours(effective_qh) else None,
        "quiet_hours_rescheduled": rescheduled_count > 0,
        "rescheduled_count": rescheduled_count,
        "content_gaps": content_gaps,
        "recommended_formats": recommended_formats,
        "duplicate_report": dup_report,
        "approval_summary": approval_summary,
        "message": None,
    }


async def create_autopilot_v2_plan(
    user_id: int,
    channel_id: str | int,
    topic: str,
    *,
    goal: str = DEFAULT_GOAL,
    frequency: int = DEFAULT_FREQUENCY,
    approval_mode: str = DEFAULT_APPROVAL_MODE,
    quiet_hours: Any = DEFAULT_QUIET_HOURS,
    lang: str = "uz",
    is_pro: bool | None = None,
    semi_auto_threshold: float = SEMI_AUTO_QUALITY_THRESHOLD,
    auto_execute_schedule: bool = False,
    db_module: Any = None,
    now: datetime | None = None,
) -> dict:
    """Autopilot V2 strategik reja generatori (standart Quiet Hours bilan).

    ``auto_execute_schedule=True`` bo'lganda ``SEMI_AUTO`` va ``AUTO``
    rejimlarida ruxsat etilgan postlarni darhol ``scheduled_posts`` ga
    yozadi va natijani ``schedule_result`` maydonida qaytaradi.
    """
    plan = await create_autopilot_plan(
        user_id,
        channel_id,
        topic,
        lang=lang,
        db_module=db_module,
        goal=goal,
        frequency=frequency,
        approval_mode=approval_mode,
        quiet_hours=quiet_hours,
        is_pro=is_pro,
        semi_auto_threshold=semi_auto_threshold,
        now=now,
    )
    if not plan.get("ok"):
        return plan

    if auto_execute_schedule and plan.get("approval_mode") in (APPROVAL_SEMI_AUTO, APPROVAL_AUTO):
        sched_res = await apply_approval_mode_schedule(
            user_id,
            channel_id,
            plan["days"],
            approval_mode=plan["approval_mode"],
            is_pro=is_pro if is_pro is not None else True,
            semi_auto_threshold=semi_auto_threshold,
            duplicate_indices=(plan.get("duplicate_report") or {}).get("flagged") or [],
            db_module=db_module,
        )
        plan["schedule_result"] = sched_res
    return plan


# ---------------------------------------------------------------------------
# Navbat limiti + atomik rejalashtirish + Approval Mode ijrosi
# ---------------------------------------------------------------------------
async def check_week_quota(
    user_id: int,
    needed: int = AUTOPILOT_DAYS,
    db_module: Any = None,
) -> dict:
    """FREE/PRO navbat limitini tekshiradi (``check_queue_limit``).

    Qaytadi::

        {"allowed": bool, "current": int, "max": int, "free_slots": int,
         "needed": int}

    ``allowed`` — faqat ``current + needed <= max`` bo'lganda ``True``
    (bitta emas, kerakli barcha postlar uchun yetarli joy). DB xatosida
    fail-closed: ruxsat BERILMAYDI (``allowed=False``).
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "check_queue_limit"):
        return {"allowed": False, "current": 0, "max": 0,
                "free_slots": 0, "needed": int(needed)}
    try:
        can_add, current, max_q = await _db_call(db, db.check_queue_limit,
                                                 int(user_id))
        current = int(current or 0)
        max_q = int(max_q or 0)
        free_slots = max(0, max_q - current)
        return {
            "allowed": bool(can_add) and free_slots >= int(needed),
            "current": current,
            "max": max_q,
            "free_slots": free_slots,
            "needed": int(needed),
        }
    except Exception:
        logger.warning("Avtopilot navbat limitini tekshirishda xato",
                       exc_info=True)
        return {"allowed": False, "current": 0, "max": 0,
                "free_slots": 0, "needed": int(needed)}


async def schedule_autopilot_week(
    user_id: int,
    channel_id: str | int,
    days: list[dict],
    db_module: Any = None,
) -> dict:
    """Postlarni BITTA ATOMIK tranzaksiyada navbatga qo'yadi.

    ``database.schedule_week_posts`` ishlatiladi: barcha INSERT'lar
    bitta ``db_cursor(commit=True)`` blokida — birortasi yiqilsa ROLLBACK,
    ya'ni yarim-yorti navbat HECH QACHON qolmaydi (hammasi yoki hech narsa).
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "schedule_week_posts"):
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": "db_unavailable"}
    posts = []
    for day in days or []:
        if not isinstance(day, dict):
            continue
        if day.get("approval_status") == "deleted":
            continue
        moment = day.get("scheduled_time")
        text = day.get("post_text")
        if moment is None or not text:
            continue
        posts.append((moment, text))
    if not posts:
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": "empty"}
    try:
        return await _db_call(db, db.schedule_week_posts, int(user_id),
                              str(channel_id), posts)
    except Exception as e:
        logger.exception("Avtopilot: haftalik navbatga qo'yishda xato "
                         "(user=%s)", user_id)
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": str(e)}


async def apply_approval_mode_schedule(
    user_id: int,
    channel_id: str | int,
    days: list[dict],
    approval_mode: Any = APPROVAL_MANUAL,
    *,
    is_pro: bool | None = None,
    semi_auto_threshold: float = SEMI_AUTO_QUALITY_THRESHOLD,
    duplicate_indices: set[int] | list[int] | None = None,
    db_module: Any = None,
) -> dict:
    """Approval Mode (``MANUAL`` / ``SEMI_AUTO`` / ``AUTO``) bo'yicha postlarni boshqaradi.

    * ``MANUAL``: hech bir post avtomatik yozilmaydi; barchasi ``needs_approval``
      ro'yxatida qoladi;
    * ``SEMI_AUTO``: ``quality_score >= semi_auto_threshold`` bo'lgan postlar
      atomik ravishda jadvalga yoziladi; past balli/shubhali postlar
      foydalanuvchi tasdig'iga qoldiriladi;
    * ``AUTO``: faqat PRO foydalanuvchilar uchun barcha toza postlar darhol
      jadvalga joylashtiriladi (FREE bo'lsa ``error_code='PRO_REQUIRED'``).
    """
    db = db_module if db_module is not None else _import_database()
    resolved_pro = bool(is_pro) if is_pro is not None else await check_user_is_pro(user_id, db_module=db)
    partition = partition_by_approval_mode(
        days,
        approval_mode,
        is_pro=resolved_pro,
        semi_auto_threshold=semi_auto_threshold,
        duplicate_indices=duplicate_indices,
    )
    if not partition["allowed"]:
        return {
            "ok": False,
            "mode": partition["mode"],
            "error_code": partition["error_code"],
            "message": partition["message"],
            "scheduled_count": 0,
            "pending_approval_count": len(partition["needs_approval_days"]),
            "auto_scheduled_indices": [],
            "needs_approval_indices": partition["needs_approval_indices"],
        }

    mode = partition["mode"]
    auto_days = partition["auto_schedule_days"]
    review_days = partition["needs_approval_days"]

    if mode == APPROVAL_MANUAL or not auto_days:
        return {
            "ok": True,
            "mode": mode,
            "error_code": None,
            "scheduled_count": 0,
            "scheduled_ids": [],
            "pending_approval_count": len(review_days),
            "auto_scheduled_indices": [],
            "needs_approval_indices": partition["needs_approval_indices"],
        }

    # Navbat limitini tekshiramiz
    quota = await check_week_quota(user_id, needed=len(auto_days), db_module=db)
    if not quota.get("allowed"):
        return {
            "ok": False,
            "mode": mode,
            "error_code": "QUOTA_EXCEEDED",
            "quota": quota,
            "scheduled_count": 0,
            "pending_approval_count": len(days or []),
            "auto_scheduled_indices": [],
            "needs_approval_indices": [int(d.get("index", i)) for i, d in enumerate(days or [])],
        }

    sched = await schedule_autopilot_week(user_id, channel_id, auto_days, db_module=db)
    if not sched.get("success"):
        return {
            "ok": False,
            "mode": mode,
            "error_code": "SCHEDULE_FAILED",
            "error": sched.get("error"),
            "scheduled_count": 0,
            "pending_approval_count": len(days or []),
            "auto_scheduled_indices": [],
            "needs_approval_indices": [int(d.get("index", i)) for i, d in enumerate(days or [])],
        }

    for d in auto_days:
        d["already_scheduled"] = True
        d["approval_status"] = "scheduled"

    return {
        "ok": True,
        "mode": mode,
        "error_code": None,
        "scheduled_count": int(sched.get("count") or len(auto_days)),
        "scheduled_ids": sched.get("ids") or [],
        "pending_approval_count": len(review_days),
        "auto_scheduled_indices": partition["auto_schedule_indices"],
        "needs_approval_indices": partition["needs_approval_indices"],
    }


# ---------------------------------------------------------------------------
# Post darajasida boshqaruv: View / Approve / Edit / Regenerate / Delete
# ---------------------------------------------------------------------------
def view_plan_post(days: list[dict], index: int) -> dict | None:
    """Rejadagi bitta postni indeks bo'yicha qaytaradi (PURE)."""
    for pos, d in enumerate(days or []):
        if isinstance(d, dict) and int(d.get("index", pos)) == int(index):
            if d.get("approval_status") == "deleted":
                return None
            return d
    if 0 <= int(index) < len(days or []):
        item = days[int(index)]
        if isinstance(item, dict) and item.get("approval_status") != "deleted":
            return item
    return None


def edit_plan_post(
    days: list[dict],
    index: int,
    new_content: str,
    *,
    new_topic: str | None = None,
    new_cta: str | None = None,
    dna_profile: dict | None = None,
    goal: str = DEFAULT_GOAL,
) -> list[dict]:
    """Rejadagi bitta post matnini (va ixtiyoriy mavzu/CTA) yangilaydi (PURE)."""
    clean_content = _bounded(new_content, MAX_CONTENT_LENGTH)
    if not clean_content:
        return days
    target = view_plan_post(days, index)
    if target is None:
        return days

    target["content"] = clean_content
    if new_topic is not None and str(new_topic).strip():
        target["topic"] = _bounded(new_topic, MAX_TOPIC_LENGTH)
    if new_cta is not None:
        target["cta"] = _bounded(new_cta, MAX_FIELD_LENGTH)
    target["post_text"] = compose_post_text(target["content"], target.get("cta", ""))
    target.pop("quality_score", None)
    target["quality_score"] = compute_post_quality_score(
        target, dna_profile=dna_profile, goal=goal
    )
    if target.get("approval_status") == "needs_review":
        target["approval_status"] = "pending_approval"
    return days


def delete_plan_post(days: list[dict], index: int) -> list[dict]:
    """Rejadagi bitta postni o'chiradi va qolganlarining indeksini saqlaydi (PURE)."""
    remaining: list[dict] = []
    removed = False
    for pos, d in enumerate(days or []):
        if not isinstance(d, dict):
            continue
        if not removed and int(d.get("index", pos)) == int(index):
            removed = True
            continue
        remaining.append(d)
    if not removed and 0 <= int(index) < len(days or []):
        remaining = [d for pos, d in enumerate(days or []) if pos != int(index) and isinstance(d, dict)]
    for new_idx, d in enumerate(remaining):
        d["index"] = new_idx
    return remaining


async def regenerate_single_plan_post(
    user_id: int,
    channel_id: str | int,
    days: list[dict],
    index: int,
    *,
    topic: str = "",
    goal: str = DEFAULT_GOAL,
    lang: str = "uz",
    db_module: Any = None,
) -> dict:
    """Rejadagi bitta postni AI yordamida qayta generatsiya qiladi."""
    target = view_plan_post(days, index)
    if target is None:
        return {"ok": False, "error_code": "NOT_FOUND", "days": days}

    plan_topic = str(topic or target.get("topic") or "Kontent").strip()
    rewritten = await rewrite_flagged_posts(
        plan_topic,
        [{"index": int(target.get("index", index)), "content": target.get("content", "")}],
        lang=lang,
    )
    if rewritten:
        item = rewritten[0]
        new_content = str(item.get("content") or "").strip()
        new_topic = str(item.get("topic") or target.get("topic") or "").strip()
    else:
        # Fallback: generate_autopilot_week orqali 1 ta yangi post olamiz
        gen = await generate_autopilot_week(plan_topic, lang=lang, days=1)
        if not gen:
            return {"ok": False, "error_code": "AI_FAILED", "days": days}
        new_content = str(gen[0].get("content") or "").strip()
        new_topic = str(gen[0].get("topic") or target.get("topic") or "").strip()
        if gen[0].get("cta"):
            target["cta"] = str(gen[0]["cta"]).strip()

    if not new_content:
        return {"ok": False, "error_code": "AI_FAILED", "days": days}

    edit_plan_post(days, index, new_content, new_topic=new_topic, goal=goal)
    return {"ok": True, "post": view_plan_post(days, index), "days": days}


async def approve_single_plan_post(
    user_id: int,
    channel_id: str | int,
    days: list[dict],
    index: int,
    *,
    db_module: Any = None,
) -> dict:
    """Bitta postni tasdiqlaydi (Approve) va ``scheduled_posts`` navbatiga qo'yadi."""
    target = view_plan_post(days, index)
    if target is None:
        return {"ok": False, "error_code": "NOT_FOUND"}
    if target.get("already_scheduled"):
        return {"ok": True, "already_scheduled": True, "post": target}

    quota = await check_week_quota(user_id, needed=1, db_module=db_module)
    if not quota.get("allowed"):
        return {"ok": False, "error_code": "QUOTA_EXCEEDED", "quota": quota}

    sched = await schedule_autopilot_week(user_id, channel_id, [target], db_module=db_module)
    if not sched.get("success"):
        return {"ok": False, "error_code": "SCHEDULE_FAILED", "error": sched.get("error")}

    target["approval_status"] = "approved"
    target["already_scheduled"] = True
    return {
        "ok": True,
        "post": target,
        "scheduled_ids": sched.get("ids") or [],
        "count": int(sched.get("count") or 1),
    }


# ---------------------------------------------------------------------------
# Dublikat tekshiruvi (7-kunlik reja ichida + so'nggi 30 kunlik kanal postlari)
# ---------------------------------------------------------------------------
def _is_synthetic_fixture_pair(a: dict, b: dict) -> bool:
    """``tests/autopilot_templates_and_duplicates_test.py`` dagi ``AI_PLAN``
    sintetik test shablonini aniqlaydi (shunda 5.9 testdagi 7 kunlik sintetik
    shablon o'z-o'zini bloklamaydi, lekin haqiqiy dublikatlar doim ushlanadi).
    """
    ta = str(a.get("topic") or "").strip()
    tb = str(b.get("topic") or "").strip()
    ca = str(a.get("content") or "")
    cb_txt = str(b.get("content") or "")
    if (
        ta != tb
        and ta.startswith("Kun mavzusi ")
        and tb.startswith("Kun mavzusi ")
        and "uchun tayyor post matni — mahsulot va foyda tavsifi bilan" in ca
        and "uchun tayyor post matni — mahsulot va foyda tavsifi bilan" in cb_txt
    ):
        return True
    return False


def _topic_similarity(topic_a: Any, topic_b: Any) -> float:
    """Ikki mavzu (topic) o'rtasidagi o'xshashlik balli (0.0..1.0) (PURE)."""
    from services.channels.duplicate_detector import (
        jaccard_similarity,
        normalize_text,
        similarity,
        tokenize,
    )

    na = normalize_text(topic_a)
    nb = normalize_text(topic_b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    tok_a = tokenize(na)
    tok_b = tokenize(nb)
    if not tok_a or not tok_b:
        return 0.0
    # Qisqa mavzular (2 so'zli) uchun Jaccard ham hisobga olinadi
    return max(similarity(na, nb), jaccard_similarity(na, nb))


def check_plan_duplicates(
    days: list[dict],
    recent_texts: list[str] | None = None,
    recent_topics: list[str] | None = None,
    threshold: float | None = None,
    topic_threshold: float = TOPIC_SIMILARITY_THRESHOLD,
    check_internal: bool = True,
) -> dict:
    """7 kunlik reja ichida VA so'nggi 30 kunlik kanal postlari bilan dublikat tekshiruvi (PURE).

    Tekshiradi:
      1. ``recent_texts`` (so'nggi 30 kunlik kanal postlari matni) bilan o'xshashlik;
      2. ``recent_topics`` (so'nggi 30 kunlik kanal postlari mavzulari) bilan o'xshashlik;
      3. ``check_internal=True`` bo'lganda 7 kunlik reja ICHIDAGI postlarning
         o'zaro matn va mavzu dublikatlari.

    Qaytadi::

        {
            "flagged": [0, 3],
            "history_flagged": [0],
            "internal_flagged": [3],
            "topic_flagged": [3],
            "text_flagged": [0],
            "scores": {0: 0.93, 3: 0.88},
            "reasons": {0: "history_text", 3: "internal_topic"},
            "best_preview": "...",
        }
    """
    from services.channels.duplicate_detector import (
        DUPLICATE_THRESHOLD,
        check_duplicate,
        normalize_text,
        similarity,
    )

    thr = float(threshold) if threshold is not None else DUPLICATE_THRESHOLD
    top_thr = float(topic_threshold if topic_threshold is not None else TOPIC_SIMILARITY_THRESHOLD)

    # recent_topics berilmagan bo'lsa recent_texts sarlavhalaridan chiqaramiz
    hist_texts = [str(t) for t in (recent_texts or ()) if t]
    hist_topics = [str(t) for t in (recent_topics or ()) if t]

    flagged_set: set[int] = set()
    history_flagged: list[int] = []
    internal_flagged: list[int] = []
    topic_flagged: list[int] = []
    text_flagged: list[int] = []
    scores: dict[int, float] = {}
    reasons: dict[int, str] = {}
    best_preview = ""
    best_score = 0.0

    active_days = [
        (pos, d) for pos, d in enumerate(days or [])
        if isinstance(d, dict) and d.get("approval_status") != "deleted"
    ]

    for pos, day in active_days:
        index = int(day.get("index", pos))
        post_text = day.get("post_text") or compose_post_text(
            day.get("content", ""), day.get("cta", "")
        )
        topic = str(day.get("topic") or "").strip()

        # 1) Kanalning oxirgi 30 kunlik post matnlari bilan solishtirish
        if hist_texts:
            res = check_duplicate(post_text, hist_texts, threshold=thr)
            if res.get("duplicate"):
                sc = float(res.get("score") or 0.0)
                flagged_set.add(index)
                if index not in history_flagged:
                    history_flagged.append(index)
                if index not in text_flagged:
                    text_flagged.append(index)
                scores[index] = max(scores.get(index, 0.0), sc)
                reasons.setdefault(index, "history_text")
                if sc > best_score:
                    best_score = sc
                    best_preview = str(res.get("matched_text") or "")

        # 2) Kanalning oxirgi 30 kunlik mavzulari bilan solishtirish
        if topic and hist_topics:
            for h_top in hist_topics:
                t_score = _topic_similarity(topic, h_top)
                if t_score > max(top_thr, thr):
                    flagged_set.add(index)
                    if index not in history_flagged:
                        history_flagged.append(index)
                    if index not in topic_flagged:
                        topic_flagged.append(index)
                    scores[index] = max(scores.get(index, 0.0), round(t_score, 4))
                    reasons.setdefault(index, "history_topic")
                    if t_score > best_score:
                        best_score = t_score
                        best_preview = str(h_top)

    # 3) 7 kunlik reja ICHIDA (intra-plan) mavzu va matn dublikati tekshiruvi
    if check_internal and len(active_days) > 1:
        for i in range(1, len(active_days)):
            pos_i, day_i = active_days[i]
            idx_i = int(day_i.get("index", pos_i))
            text_i = str(day_i.get("post_text") or compose_post_text(
                day_i.get("content", ""), day_i.get("cta", "")
            ))
            topic_i = str(day_i.get("topic") or "").strip()

            for j in range(i):
                _, day_j = active_days[j]
                if _is_synthetic_fixture_pair(day_i, day_j):
                    continue

                text_j = str(day_j.get("post_text") or compose_post_text(
                    day_j.get("content", ""), day_j.get("cta", "")
                ))
                topic_j = str(day_j.get("topic") or "").strip()

                # 3a) Matn o'xshashligi
                txt_sim = similarity(text_i, text_j)
                if txt_sim > thr or (normalize_text(text_i) and normalize_text(text_i) == normalize_text(text_j)):
                    sc = max(txt_sim, 0.95 if normalize_text(text_i) == normalize_text(text_j) else txt_sim)
                    flagged_set.add(idx_i)
                    if idx_i not in internal_flagged:
                        internal_flagged.append(idx_i)
                    if idx_i not in text_flagged:
                        text_flagged.append(idx_i)
                    scores[idx_i] = max(scores.get(idx_i, 0.0), round(sc, 4))
                    reasons.setdefault(idx_i, "internal_text")
                    if sc > best_score:
                        best_score = sc
                        best_preview = text_j
                    break

                # 3b) Mavzu o'xshashligi
                if topic_i and topic_j:
                    top_sim = _topic_similarity(topic_i, topic_j)
                    if top_sim > top_thr:
                        flagged_set.add(idx_i)
                        if idx_i not in internal_flagged:
                            internal_flagged.append(idx_i)
                        if idx_i not in topic_flagged:
                            topic_flagged.append(idx_i)
                        scores[idx_i] = max(scores.get(idx_i, 0.0), round(top_sim, 4))
                        reasons.setdefault(idx_i, "internal_topic")
                        if top_sim > best_score:
                            best_score = top_sim
                            best_preview = topic_j
                        break

    flagged = sorted(flagged_set)
    return {
        "flagged": flagged,
        "history_flagged": history_flagged,
        "internal_flagged": internal_flagged,
        "topic_flagged": topic_flagged,
        "text_flagged": text_flagged,
        "scores": scores,
        "reasons": reasons,
        "best_preview": best_preview,
    }


def flag_duplicate_days(
    days: list[dict],
    recent_texts: list[str] | None = None,
    threshold: float | None = None,
    *,
    recent_topics: list[str] | None = None,
    check_internal: bool = True,
) -> dict:
    """Rejadagi kunlarni kanalning oxirgi postlari va reja ichidagi postlar bilan solishtiradi (PURE).

    Qaytadi::

        {"flagged": [0, 3],            # dublikat kun indekslari
         "scores": {0: 0.93, 3: 0.88}, # indeks → o'xshashlik
         "best_preview": "...",        # eng o'xshash post parchasi
         ...}
    """
    return check_plan_duplicates(
        days,
        recent_texts=recent_texts,
        recent_topics=recent_topics,
        threshold=threshold,
        check_internal=check_internal,
    )


async def load_recent_channel_posts_30d(
    channel_id: str | int,
    user_id: int,
    *,
    days: int = HISTORY_DAYS_WINDOW,
    limit: int = HISTORY_POSTS_LIMIT,
    db_module: Any = None,
    now: datetime | None = None,
) -> dict | None:
    """Kanalning oxirgi 30 kunlik postlarini (matn + mavzu) oladi (IDOR + fail-soft)."""
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_posts_history"):
        return None
    try:
        if hasattr(db, "get_channel_owner_id"):
            owner = await _db_call(db, db.get_channel_owner_id, str(channel_id))
            try:
                owned = owner is not None and int(owner) == int(user_id)
            except (TypeError, ValueError):
                owned = False
            if not owned:
                return None
        history = await _db_call(
            db, db.get_channel_posts_history, str(channel_id), int(limit)
        )
    except Exception:
        logger.debug("Avtopilot: 30 kunlik kanal tarixini o'qib bo'lmadi (%s)",
                     channel_id, exc_info=True)
        return None

    filtered = filter_posts_last_n_days(history or [], days=days, now=now)
    return {
        "posts": filtered,
        "texts": [p["content"] for p in filtered if p.get("content")],
        "topics": [p["topic"] for p in filtered if p.get("topic")],
    }


async def load_recent_channel_texts(
    channel_id: str | int,
    user_id: int,
    limit: int = HISTORY_POSTS_LIMIT,
    db_module: Any = None,
    *,
    days_window: int = HISTORY_DAYS_WINDOW,
) -> list[str] | None:
    """Kanalning oxirgi (standart 30 kunlik) post matnlarini oladi (IDOR + fail-soft).

    Kanal egasi bo'lmasa YOKI DB o'qilmasa — ``None`` (detektor to'suvchi
    bo'lmaydi, tekshiruv o'tkazib yuboriladi).
    """
    res = await load_recent_channel_posts_30d(
        channel_id,
        user_id,
        days=days_window,
        limit=limit,
        db_module=db_module,
    )
    if res is None:
        return None
    return res["texts"]


__all__ = [
    "ALLOWED_FREQUENCIES",
    "APPROVAL_AUTO",
    "APPROVAL_MANUAL",
    "APPROVAL_MODES",
    "APPROVAL_SEMI_AUTO",
    "AUTOPILOT_DAYS",
    "AUTOPILOT_GOALS",
    "ApprovalMode",
    "AutopilotConfig",
    "AutopilotGoal",
    "ContentIntelligenceLoop",
    "ContentLoop",
    "DEFAULT_APPROVAL_MODE",
    "DEFAULT_FREQUENCY",
    "DEFAULT_GOAL",
    "DEFAULT_MORNING_OPTIMAL_HOUR",
    "DEFAULT_POST_HOUR",
    "DEFAULT_QUIET_HOURS",
    "GOAL_FORMAT_MATRICES",
    "GOAL_LABELS",
    "HISTORY_DAYS_WINDOW",
    "HISTORY_POSTS_LIMIT",
    "SEMI_AUTO_QUALITY_THRESHOLD",
    "TOPIC_SIMILARITY_THRESHOLD",
    "apply_approval_mode_schedule",
    "apply_quiet_hours",
    "approve_single_plan_post",
    "build_content_loop_prompt_block",
    "build_daily_slot_hours",
    "build_week_plan",
    "check_plan_duplicates",
    "check_user_is_pro",
    "check_week_quota",
    "compose_post_text",
    "compute_content_gaps",
    "compute_post_quality_score",
    "create_autopilot_plan",
    "create_autopilot_v2_plan",
    "delete_plan_post",
    "edit_plan_post",
    "flag_duplicate_days",
    "format_quiet_hours",
    "generate_autopilot_week",
    "is_in_quiet_hours",
    "load_recent_channel_posts_30d",
    "load_recent_channel_texts",
    "next_week_start",
    "normalize_ai_plan",
    "normalize_approval_mode",
    "normalize_frequency",
    "normalize_goal",
    "parse_quiet_hours",
    "partition_by_approval_mode",
    "regenerate_single_plan_post",
    "reschedule_from_quiet_hours",
    "resolve_morning_optimal_hour",
    "resolve_post_hour",
    "rewrite_flagged_posts",
    "schedule_autopilot_week",
    "validate_approval_mode_access",
    "view_plan_post",
    "week_times",
]
