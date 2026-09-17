"""🗓 KONTENT REJA GENERATORI — 51-band (PHASE 12).

1, 7, 14 yoki 30 kunlik kontent rejasi: har bir kun uchun

    Kun / sana / kun nomi → FORMAT → MAVZU → HOOK g'oyasi → MAQSAD → CTA

Siyosat va kafolatlar
--------------------
* ``PLAN_DURATIONS = (1, 7, 14, 30)`` — boshqa qiymatlar ``invalid_duration``
  bilan rad etiladi (``handlers/content_calendar`` konventsiyasi bilan bir xil);
* **FREE** — 1 va 7 kunlik reja; **14/30 kunlik reja FAQAT PRO**
  (``pro_required``). Entitlement DB xatosida FAIL-CLOSED (PRO berilmaydi);
* kunlar soni qanchalik katta bo'lmasin, AI'ga **7 kundan ortiq bo'lmagan
  batchlar** yuboriladi (4096 limitiga urilib JSON kesilib qolmasligi uchun);
* AI javobi — ishonchsiz: faqat qisqa, lug'at shaklidagi maydonlar qabul
  qilinadi, format/maqsad/CTA vaqt rejasi lokal rotatsiyadan keladi va
  kunlar soni bilan cheklanadi. Model reja «o'ylab topgan» bo'lsa ham
  natural hodisa kabi buziladi: ``len(items) == days`` doim o'rinli;
* barcha chiqishlar ``sanitize_html`` (Phase 2) va 4096 belgili chunk'lar.

Kvota: butun reja (30 kun = 5 ta AI batchi) uchun BITTA atomik bron.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .smm_common import (
    CHUNK_SAFE_LIMIT,
    DEFAULT_LANG,
    QuotaTicket,
    SMMFeatureService,
    bold,
    clip,
    escape_literal,
    extract_json,
    lang_text,
    normalize_lang,
    strip_html,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SIYOSAT
# ---------------------------------------------------------------------------
#: Ruxsat etilgan reja davomiyliklari (kun).
PLAN_DURATIONS: tuple[int, ...] = (1, 7, 14, 30)
#: FREE tarifda ruxsat etilgan maksimal davomiylik.
FREE_MAX_DAYS = 7
#: Bitta AI so'rovida so'raladigan maksimal kunlar soni (4096 chegarasi uchun).
AI_BATCH_DAYS = 7
#: Bir kun uchun maydon chegaralari (reja xavfsiz va ixcham bo'lsin).
TOPIC_LIMIT = 160
HOOK_LIMIT = 180
GOAL_LIMIT = 90
CTA_LIMIT = 140

#: Kunlik eng yaxshi vaqtlar (format bo'yicha, Telegram o'rtacha auditoriyasi).
WEEKDAY_SHORT = {
    "uz": ["Du", "Se", "Chor", "Pay", "Jum", "Shan", "Yak"],
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


@dataclass(frozen=True)
class PlanFormat:
    """Rejadagi «format» — rubrika, maqsad, hook qolipi va vaqt."""

    key: str
    emoji: str
    label: dict
    goal: dict
    hook: dict
    cta: dict
    time: str
    hashtags: tuple

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_goal(self, lang: Any) -> str:
        return lang_text(self.goal, lang, "")

    def t_hook(self, lang: Any) -> str:
        return lang_text(self.hook, lang, "")

    def t_cta(self, lang: Any) -> str:
        return lang_text(self.cta, lang, "")


#: Tartib muhim: rotatsiya shu tartib bo'yicha haftaning kunlariga bog'lanadi.
PLAN_FORMATS: tuple[PlanFormat, ...] = (
    PlanFormat(
        key="educational", emoji="📚", time="10:30",
        label={"uz": "Foydali maslahat", "ru": "Полезный совет", "en": "How-to"},
        goal={"uz": "Ekspertlik va ishonch oshirish", "ru": "Экспертность и доверие",
              "en": "Build authority and trust"},
        hook={"uz": "{topic}: 3 qadamda bajariladigan maslahat",
              "ru": "{topic}: совет, который выполняется в 3 шага",
              "en": "{topic}: a tip you can apply in three steps"},
        cta={"uz": "📌 Saqlab oling va amaliyotda sinang",
             "ru": "📌 Сохраните и попробуйте на практике",
             "en": "📌 Save it and try it this week"},
        hashtags=("#maslahat", "#foydali", "#smm"),
    ),
    PlanFormat(
        key="engagement", emoji="💬", time="19:00",
        label={"uz": "Muloqot / savol", "ru": "Вовлечение / вопрос", "en": "Engagement"},
        goal={"uz": "Izoh va fikr-mulohaza yig'ish", "ru": "Собрать комментарии и мнения",
              "en": "Collect comments and opinions"},
        hook={"uz": "{topic} — sizcha qaysi variant to'g'ri?",
              "ru": "{topic} — какой вариант верный, по-вашему?",
              "en": "{topic} — which option do you think is right?"},
        cta={"uz": "💬 Javobingizni izohga yozing — poll ochamiz",
             "ru": "💬 Напишите ответ в комментариях — откроем опрос",
             "en": "💬 Drop your answer — we'll open a poll"},
        hashtags=("#so'rov", "#fikr", "#jamoa"),
    ),
    PlanFormat(
        key="social_proof", emoji="🏆", time="13:00",
        label={"uz": "Mijoz natijasi / keys", "ru": "Кейс / результат клиента", "en": "Social proof"},
        goal={"uz": "Ishonchni isbot bilan mustahkamlash",
              "ru": "Подкрепить доверие доказательством",
              "en": "Reinforce trust with proof"},
        hook={"uz": "{topic}: [mijoz] 30 kun da [natija]ga qanday erishdi",
              "ru": "{topic}: как [клиент] получил [результат] за 30 дней",
              "en": "{topic}: how [client] reached [result] in 30 days"},
        cta={"uz": "🔗 Xuddi shunday natija kerakmi — yozing",
             "ru": "🔗 Нужен такой же результат — напишите нам",
             "en": "🔗 Want the same result? Message us"},
        hashtags=("#keys", "#natija", "#mijoz"),
    ),
    PlanFormat(
        key="offer", emoji="💰", time="11:00",
        label={"uz": "Taklif / aksiya", "ru": "Оффер / акция", "en": "Offer"},
        goal={"uz": "Sotuv yoki ariza oqimini oshirish",
              "ru": "Увеличить поток заявок и продаж",
              "en": "Drive sales and leads"},
        hook={"uz": "{topic}: [narx] — faqat [sana] gacha",
              "ru": "{topic}: [цена] — только до [дата]",
              "en": "{topic}: [price] — until [date] only"},
        cta={"uz": "🛒 Joylar soni cheklangan — hoziroq yozing",
             "ru": "🛒 Мест мало — напишите сегодня",
             "en": "🛒 Limited spots — message today"},
        hashtags=("#aksiya", "#taklif", "#chegirma"),
    ),
    PlanFormat(
        key="storytelling", emoji="🎬", time="20:30",
        label={"uz": "Hikoya / brend ortida", "ru": "История / за кулисами", "en": "Storytelling"},
        goal={"uz": "Brendga hissiy bog'lanish yaratish",
              "ru": "Создать эмоциональную связь с брендом",
              "en": "Build an emotional bond with the brand"},
        hook={"uz": "{topic} haqida: eng qiyin kunimiz va undan chiqish yo'li",
              "ru": "{topic}: наш самый трудный день и как мы вышли из него",
              "en": "{topic}: our hardest day and how we came through"},
        cta={"uz": "💬 Sizda shunday bo'ldimi? Yozing",
             "ru": "💬 Было такое у вас? Расскажите",
             "en": "💬 Did this happen to you? Tell us"},
        hashtags=("#hikoya", "#brend", "#tajriba"),
    ),
    PlanFormat(
        key="faq", emoji="❓", time="16:00",
        label={"uz": "Savol-javob", "ru": "Вопрос-ответ", "en": "FAQ"},
        goal={"uz": "Xarid to'siqlarini olib tashlash",
              "ru": "Снять возражения перед покупкой",
              "en": "Remove objections before purchase"},
        hook={"uz": "{topic}: eng ko'p beriladigan 3 ta savolga javob",
              "ru": "{topic}: ответы на 3 самых частых вопроса",
              "en": "{topic}: answers to the three most common questions"},
        cta={"uz": "❓ Savolingiz ro'yxatda yo'qmi? Yozing",
             "ru": "❓ Не нашли свой вопрос? Напишите нам",
             "en": "❓ Question not listed? Ask us"},
        hashtags=("#faq", "#javob", "#savallar"),
    ),
    PlanFormat(
        key="recap", emoji="📊", time="09:30",
        label={"uz": "Xulosa / haftalik natija", "ru": "Итоги / недельный результат", "en": "Weekly recap"},
        goal={"uz": "Jamoatni davomiylikka undash",
              "ru": "Удержать аудиторию на длинную дистанцию",
              "en": "Keep the audience coming back"},
        hook={"uz": "{topic}: haftaning 3 ta muhim raqami",
              "ru": "{topic}: три важные цифры недели",
              "en": "{topic}: three numbers that mattered this week"},
        cta={"uz": "🔁 Keyingi hafta ham shu vaqtda — izohda fikringizni qoldiring",
             "ru": "🔁 На следующей неделе в это же время — делитесь мнением в комментариях",
             "en": "🔁 Same time next week — share your take in the comments"},
        hashtags=("#natijalar", "#tahlil", "#hafta"),
    ),
)

#: Dushanbadan boshlab kun → format tartibi (7 kunlik sikl).
WEEKLY_ROTATION: tuple[str, ...] = (
    "educational", "engagement", "social_proof", "offer",
    "storytelling", "faq", "recap",
)

#: «Kun N» so'zi (reja sarlavhalari uchun).
_DAY_WORD = {"uz": "Kun", "ru": "День", "en": "Day"}

_FORMAT_INDEX = {item.key: item for item in PLAN_FORMATS}
#: Eski/erga nomlar ham taniladi (UI va eski testlar uchun).
_FORMAT_ALIASES = {
    "maslahat": "educational", "foyda": "educational", "howto": "educational",
    "savol": "engagement", "poll": "engagement", "вовлечение": "engagement",
    "case": "social_proof", "otzyv": "social_proof", "keys": "social_proof",
    "sotuv": "offer", "aksiya": "offer", "sale": "offer", "промо": "offer",
    "blog": "storytelling", "histoya": "storytelling", "история": "storytelling",
    "savol_javob": "faq", "q": "faq", "а": "faq",
    "itijor": "recap", "итоги": "recap", "digest": "recap",
}


def resolve_format(value: Any) -> PlanFormat:
    """Kalit/alias/noaniq matn → PlanFormat (topilmasasa birinchi format)."""
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in _FORMAT_INDEX:
        return _FORMAT_INDEX[raw]
    if raw in _FORMAT_ALIASES:
        return _FORMAT_INDEX[_FORMAT_ALIASES[raw]]
    for key, item in _FORMAT_INDEX.items():
        if key in raw:
            return item
    return PLAN_FORMATS[0]


# ---------------------------------------------------------------------------
# ENTITLEMENT
# ---------------------------------------------------------------------------
def normalize_days(value: Any) -> int:
    """Qiymatni ruxsat etilgan davomiylikka keltirish (bo'lmasa 0)."""
    text = str(value or "").strip().lower()
    match = re.search(r"\d+", text)
    if not match:
        aliases = {"bir": 1, "bu": 7, "hafta": 7, "bir_hafta": 7, "ikki_hafta": 14,
                   "oy": 30, "месяц": 30, "неделя": 7, "month": 30, "week": 7}
        return aliases.get(text.replace(" ", "_"), 0)
    days = int(match.group(0))
    return days if days in PLAN_DURATIONS else days


def plan_entitlement(days: int, is_pro: bool) -> tuple[bool, str]:
    """(ruxsat, sabab) — fail-closed: noma'lum davomiylik va PRO tekshiruvi."""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return False, "invalid_duration"
    if value not in PLAN_DURATIONS:
        return False, "invalid_duration"
    if value > FREE_MAX_DAYS and not is_pro:
        return False, "pro_required"
    return True, "ok"


def is_pro_user(user_id: Any, db_module: Any) -> bool:
    """PRO entitlement (DB xatosida FAIL-CLOSED — PRO berilmaydi)."""
    if db_module is None or db_module is False:
        return False
    try:
        return bool(db_module.is_premium(int(user_id or 0)))
    except Exception as exc:  # noqa: BLE001 — xavfsizlik nuqtai nazaridan False
        logger.warning("plan entitlement xatosi (user=%s): %s", user_id, exc)
        return False


def resolve_start_date(value: Any) -> date:
    """'YYYY-MM-DD' yoki ``date`` → date; yaroqsiz bo'lsa bugun (UTC)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if text:
        try:
            return date.fromisoformat(text[:10])
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# MODELLAR
# ---------------------------------------------------------------------------
@dataclass
class PlanDay:
    """Rejaning bitta kuni."""

    day: int
    iso_date: str = ""
    weekday: str = ""
    format: str = "educational"
    format_label: str = ""
    topic: str = ""
    hook: str = ""
    goal: str = ""
    cta: str = ""
    time: str = "10:30"
    hashtags: list = field(default_factory=list)
    source: str = "local"

    @property
    def date(self) -> str:
        """API qulayligi: ``iso_date`` maydonining qisqa taxallusi."""
        return self.iso_date

    def render(self, lang: str = "uz") -> str:
        code = normalize_lang(lang)
        label = _DAY_WORD[code]
        header = f"{label} {self.day} · {self.iso_date} ({self.weekday}) · {self.time}"
        lines = [
            bold(escape_literal(f"🗓 {header}")),
            f"🧩 <b>Format:</b> {escape_literal(self.format_label)}",
            f"📌 <b>Mavzu:</b> {escape_literal(self.topic)}",
            f"💡 <b>Hook:</b> {escape_literal(self.hook)}",
            f"🎯 <b>Maqsad:</b> {escape_literal(self.goal)}",
            f"👉 <b>CTA:</b> {escape_literal(self.cta)}",
        ]
        if self.hashtags:
            lines.append(" ".join(escape_literal(tag) for tag in self.hashtags[:5]))
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "day": self.day, "date": self.iso_date, "weekday": self.weekday,
            "format": self.format, "format_label": self.format_label,
            "topic": self.topic, "hook": self.hook, "goal": self.goal,
            "cta": self.cta, "time": self.time,
            "hashtags": list(self.hashtags), "source": self.source,
        }


@dataclass
class ContentPlanResult:
    """Reja generatorining yakuniy natijasi."""

    success: bool = False
    days: int = 0
    items: list = field(default_factory=list)
    weeks: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    lang: str = DEFAULT_LANG
    topic: str = ""
    start_date: str = ""
    plan_id: str = ""
    provider_used: str = "none"
    ai_merged: bool = False
    entitlement: str = "ok"
    paid: bool = False
    refund_issued: bool = False
    cost: int = 0
    reservation_id: Any = None
    quota: dict = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None

    def topics(self) -> list[str]:
        return [item.topic for item in self.items]

    def formats(self) -> list[str]:
        return [item.format for item in self.items]

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "days": self.days,
            "plan_id": self.plan_id,
            "start_date": self.start_date,
            "lang": self.lang,
            "topic": self.topic,
            "entitlement": self.entitlement,
            "paid": self.paid,
            "refund_issued": self.refund_issued,
            "provider_used": self.provider_used,
            "ai_merged": self.ai_merged,
            "cost": self.cost,
            "reservation_id": self.reservation_id,
            "quota": dict(self.quota),
            "error": self.error,
            "error_code": self.error_code,
            "items": [item.as_dict() for item in self.items],
            "chunks": list(self.chunks),
        }


# ---------------------------------------------------------------------------
# LOKAL (KAFOLATLANGAN) REJA
# ---------------------------------------------------------------------------
def build_local_plan(topic: str, days: int, start: date, lang: str = "uz") -> list[PlanDay]:
    """Deterministik asos: format rotatsiyasi + hook/maqsad/CTA qoliplari."""
    code = normalize_lang(lang)
    safe_topic = clip(str(topic or "").strip(), 80) or (
        {"uz": "Bizning yo'nalish", "ru": "Наше направление", "en": "Our niche"}[code])
    items: list[PlanDay] = []
    for offset in range(max(1, int(days))):
        current = start + timedelta(days=offset)
        number = offset + 1
        fmt = _FORMAT_INDEX[WEEKLY_ROTATION[current.weekday() % len(WEEKLY_ROTATION)]]
        # Hafta soni — yumshoqroq kontent: shuning uchun sekund sikl suriladi.
        if current.weekday() >= 5 and fmt.key in ("offer", "social_proof"):
            fmt = PLAN_FORMATS[(PLAN_FORMATS.index(fmt) + 3) % len(PLAN_FORMATS)]
        items.append(PlanDay(
            day=number,
            iso_date=current.isoformat(),
            weekday=WEEKDAY_SHORT[code][current.weekday() % 7],
            format=fmt.key,
            format_label=fmt.t_label(code),
            topic=safe_topic,
            hook=clip(fmt.t_hook(code).format(topic=safe_topic), HOOK_LIMIT),
            goal=fmt.t_goal(code),
            cta=fmt.t_cta(code),
            time=fmt.time,
            hashtags=list(fmt.hashtags),
            source="local",
        ))
    return items


def build_plan_prompt(topic: str, days: int, start_day: int, lang: str = "uz") -> str:
    """AI'dan faqat MAVZU va HOOK so'raladi (batch — 7 kundan oshmaydi)."""
    code = normalize_lang(lang)
    lead = {
        "uz": "Kontent-reja uchun har bir kunga aniq, amaliy mavzu va hook yozing.",
        "ru": "Для контент-плана напишите конкретную тему и хук для каждого дня.",
        "en": "For each day of the content plan write a concrete topic and a hook.",
    }[code]
    asked = {
        "uz": f"Kunlar: {start_day}–{start_day + days - 1} ({days} kun).",
        "ru": f"Дни: {start_day}–{start_day + days - 1} ({days} дн.).",
        "en": f"Days {start_day}-{start_day + days - 1} ({days} days).",
    }[code]
    niche_word = {"uz": "Yo'nalish", "ru": "Направление", "en": "Niche"}[code]
    return "\n".join([
        f"[SMM TASK: content_plan — {days} days, starting day {start_day}]",
        lead,
        f"{niche_word}: {escape_literal(clip(topic, 120))}",
        asked,
        f"Formatlar ro'yxati (kalitlar): {', '.join(item.key for item in PLAN_FORMATS)}.",
        "Javobni FAQAT bitta JSON obyektida qaytaring (izohsiz):",
        '{"plan": [{"day": 1, "topic": "...", "hook": "...", "cta": "..."}]}',
        "Topic 160, hook 180, cta 140 belgidan oshmasin. Hashtag, markdown va "
        "HTML teglari ishlatmang.",
    ])


def parse_plan_json(payload: Any, days: int, start_day: int) -> dict[int, dict]:
    """Model javobidagi reja yozuvlarini {kun: maydonlar} ko'rinishiga keltirish.

    Kunlar sonidan tashqari yozuvlar tashlab yuboriladi (AI «20 kunlik reja»
    berib yuborsa ham), takroriy kunlar birinchisi saqlanadi.
    """
    out: dict[int, dict] = {}
    if not isinstance(payload, dict):
        return out
    raw_items = payload.get("plan") or payload.get("days") or payload.get("items") or []
    if not isinstance(raw_items, list):
        return out
    for position, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        try:
            day_no = int(item.get("day") or (start_day + position))
        except (TypeError, ValueError):
            day_no = start_day + position
        if day_no < start_day or day_no > days:
            continue
        if day_no in out:
            continue
        fields = {}
        for key, limit in (("topic", TOPIC_LIMIT), ("hook", HOOK_LIMIT),
                          ("cta", CTA_LIMIT), ("format", 40)):
            value = clip(strip_html(item.get(key, "")), limit)
            if len(value) >= 4:
                fields[key] = value
        if fields:
            out[day_no] = fields
    return out


def merge_plan(items: list[PlanDay], merged: Iterable[tuple[int, dict]], lang: str) -> int:
    """AI maydonlarini lokal karkasga qo'shadi (faqat matnlar, kunlar soni o'zgarmaydi)."""
    code = normalize_lang(lang)
    applied = 0
    by_day = {day: fields for day, fields in merged}
    for item in items:
        fields = by_day.get(item.day)
        if not fields:
            continue
        changed = False
        if fields.get("topic") and fields["topic"] != item.topic:
            # Faqat MAVZU yangilanadi: hook qolipi format + yo'nalish
            # asosida lokal hisoblanadi (model hook bermasa), shunda ikki
            # qo'shma sarlavha chiqmaydi va qatorlar bir-biriga to'g'ri keladi.
            item.topic = clip(fields["topic"], TOPIC_LIMIT)
            changed = True
        if fields.get("hook"):
            item.hook = clip(fields["hook"], HOOK_LIMIT)
            changed = True
        if fields.get("cta"):
            item.cta = clip(fields["cta"], CTA_LIMIT)
            changed = True
        if fields.get("format"):
            resolved = resolve_format(fields["format"])
            if resolved.key != item.format:
                item.format = resolved.key
                item.format_label = resolved.t_label(code)
                item.goal = resolved.t_goal(code)
                item.time = resolved.time
                item.hashtags = list(resolved.hashtags)
                changed = True
        if changed:
            item.source = "ai"
            applied += 1
    return applied


def render_plan(items: list[PlanDay], topic: str, lang: str, weeks_header: bool = True) -> list[str]:
    """Rejani hafta-blok'lariga chizadi (har bir blok keyin chunk qilinadi)."""
    code = normalize_lang(lang)
    titles = {
        "uz": {"week": "hafta", "of": "reja"},
        "ru": {"week": "неделя", "of": "план"},
        "en": {"week": "week", "of": "plan"},
    }[code]
    blocks: list[str] = []
    lead = bold(f"🗓 {escape_literal(clip(topic, 80))}") + f" · {len(items)} kunlik {titles['of']}"
    blocks.append(lead)
    for start in range(0, len(items), 7):
        week_items = items[start:start + 7]
        if weeks_header and len(items) > 7:
            week_no = start // 7 + 1
            span = (f"{week_items[0].iso_date} — {week_items[-1].iso_date}"
                    if len(week_items) > 1 else week_items[0].iso_date)
            blocks.append(bold(escape_literal(f"📅 {titles['week']} {week_no} · {span}")))
        for item in week_items:
            blocks.append(item.render(code))
    return blocks


# ---------------------------------------------------------------------------
# XIZMAT
# ---------------------------------------------------------------------------
class ContentPlanService(SMMFeatureService):
    """Kontent reja generatori (51-band)."""

    feature = "planner"
    quota_operation = "content_calendar:plan"
    quota_cost = 1

    async def generate_plan(
        self,
        user_id: int | None,
        topic: str,
        days: Any = 7,
        lang: str = DEFAULT_LANG,
        *,
        start_date: Any = None,
        db_module: Any = None,
        is_pro: bool | None = None,
        use_ai: bool = True,
        orchestrator: Any = None,
    ) -> ContentPlanResult:
        """``days`` kunlik reja tuzadi (mock/offline rejimda ham to'liq)."""
        code = normalize_lang(lang)
        safe_topic = clip(strip_html(str(topic or "")), 120)
        requested = normalize_days(days)
        start = resolve_start_date(start_date)

        def failure(error: str, code_name: str, entitlement: str = "ok") -> ContentPlanResult:
            return ContentPlanResult(success=False, lang=code, topic=safe_topic,
                                     days=max(0, int(requested or 0)),
                                     start_date=start.isoformat(),
                                     entitlement=entitlement,
                                     error=error, error_code=code_name)

        if len(safe_topic) < 3:
            return failure("empty_topic", "INVALID_INPUT")
        pro_flag = is_pro if isinstance(is_pro, bool) else is_pro_user(user_id, db_module)
        allowed, reason = plan_entitlement(requested, pro_flag)
        if not allowed:
            return failure(reason, reason.upper(), entitlement=reason)
        if orchestrator is not None:
            self._injected_orchestrator = orchestrator

        # 1 kunlik reja va AI'siz rejim — bron qilinmaydi (narx 0).
        paid_step = bool(use_ai and requested > 1)
        ticket = (await self.acquire_quota(db_module, user_id) if paid_step
                  else QuotaTicket(allowed=True, skipped=True, reason="free_plan"))
        if not ticket.allowed:
            reason = ticket.reason or "quota_denied"
            denied_code = ("QUOTA_EXCEEDED" if reason in {
                "insufficient_balance", "user_not_found", "quota_denied"}
                else "QUOTA_UNAVAILABLE")
            return ContentPlanResult(
                success=False, lang=code, topic=safe_topic, days=requested,
                start_date=start.isoformat(), entitlement="quota",
                error=reason, error_code=denied_code, quota=ticket.as_dict(),
            )

        items = build_local_plan(safe_topic, requested, start, code)
        merged_pairs: list[tuple[int, dict]] = []
        providers: list[str] = []

        if use_ai and requested > 1:
            for start_day in range(1, requested + 1, AI_BATCH_DAYS):
                batch = min(AI_BATCH_DAYS, requested - start_day + 1)
                outcome = await self.ask(
                    build_plan_prompt(safe_topic, batch, start_day, code),
                    user_id=user_id, lang=code,
                    context={
                        "smm_mode": "PLANNER",
                        "smm_plan_batch": batch,
                        "smm_plan_start": start_day,
                        "smm_topic": clip(safe_topic, 120),
                    },
                )
                if outcome.provider and outcome.provider != "none":
                    providers.append(outcome.provider)
                if outcome.error_code == "CANCELLED":
                    await self.release_quota(ticket)
                    return ContentPlanResult(
                        success=False, lang=code, topic=safe_topic, days=requested,
                        start_date=start.isoformat(), error="cancelled",
                        error_code="CANCELLED", cost=ticket.cost,
                        reservation_id=ticket.reservation_id, quota=ticket.as_dict(),
                    )
                payload = extract_json(outcome.text or outcome.raw) if outcome.ok else None
                merged_pairs.extend(parse_plan_json(payload, requested, start_day).items())

        applied = merge_plan(items, merged_pairs, code) if merged_pairs else 0
        # 💳 AI biror kunni ham boyitmagan bo'lsa — bron foydalanuvchiga
        # qaytariladi (biz lokal karkas uchun pul olmaymiz).
        paid = paid_step and applied > 0
        refund_issued = False
        if paid_step and applied == 0:
            refund_issued = await self.release_quota(ticket)
            if refund_issued:
                ticket.cost = 0
        blocks = render_plan(items, safe_topic, code)
        chunks = self.render(blocks, limit=CHUNK_SAFE_LIMIT)
        plan_id = f"plan_{(user_id or 0)}_{start.isoformat()}_{requested}"
        weeks: list[dict] = []
        for offset in range(0, len(items), 7):
            slice_items = items[offset:offset + 7]
            weeks.append({
                "index": offset // 7 + 1,
                "from": slice_items[0].iso_date,
                "to": slice_items[-1].iso_date,
                "days": [item.day for item in slice_items],
            })
        self._log("reja tayyor (user=%s, days=%s, merged=%s, lang=%s)",
                  user_id, requested, applied, code)
        return ContentPlanResult(
            success=True,
            days=requested,
            items=items,
            weeks=weeks,
            chunks=chunks,
            lang=code,
            topic=safe_topic,
            start_date=start.isoformat(),
            plan_id=plan_id,
            provider_used=providers[0] if providers else ("local" if not use_ai else "MockFallback"),
            ai_merged=bool(applied),
            entitlement="ok",
            paid=paid,
            refund_issued=refund_issued,
            cost=ticket.cost,
            reservation_id=ticket.reservation_id,
            quota=ticket.as_dict(),
        )


default_planner = ContentPlanService()


async def generate_content_plan(user_id: int | None, topic: str, days: Any = 7,
                                lang: str = "uz", **kwargs: Any) -> ContentPlanResult:
    """Yordamchi funksiya: ``ContentPlanService().generate_plan(...)``."""
    return await ContentPlanService().generate_plan(user_id, topic, days, lang, **kwargs)


__all__ = [
    "PLAN_DURATIONS",
    "PLAN_FORMATS",
    "FREE_MAX_DAYS",
    "AI_BATCH_DAYS",
    "WEEKLY_ROTATION",
    "PlanFormat",
    "PlanDay",
    "ContentPlanResult",
    "ContentPlanService",
    "build_local_plan",
    "build_plan_prompt",
    "merge_plan",
    "normalize_days",
    "parse_plan_json",
    "plan_entitlement",
    "is_pro_user",
    "render_plan",
    "resolve_format",
    "resolve_start_date",
    "generate_content_plan",
    "default_planner",
]
