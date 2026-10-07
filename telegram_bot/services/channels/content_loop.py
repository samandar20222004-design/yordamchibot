"""🔄 CONTENT INTELLIGENCE LOOP — Channel DNA + Gaps + Strategy (PHASE 7/8).

Kanalning **Channel DNA** profili (``services.channels.dna``), **Weekly
Advisor / Gaps** tahlili (``services.channels.advisor``) va **Smart Best
Time** statistikasi (``services.channels.best_time``) ni yagona strategik
kontent sikliga (``ContentLoop``) birlashtiradi.

Autopilot V2 ushbu modul orqali:
  * kanalning kuchli formatlari (``high_performing_formats``) va uslubini;
  * oxirgi postlarda yetishmayotgan kontent bo'shliqlarini (``content_gaps``);
  * tanlangan strategik maqsadga (``growth``, ``sales``, ``engagement``,
    ``expertise``) mos muvozanatlangan formatlar ketma-ketligini;
  * oxirgi 30 kunlik postlar tarixini (mavzu va matn dublikatlarini oldini
    olish uchun) oladi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from services.channels.advisor import compute_weekly_insights
from services.channels.analytics import (
    attach_analytics_summary,
    summarize_posts_locally,
)
from services.channels.best_time import get_best_time
from services.channels.dna import (
    build_dna_system_prompt,
    get_channel_dna,
    get_channel_dna_extended,
)

logger = logging.getLogger(__name__)

#: Strategik maqsadlar (kanonik kodlar).
STRATEGIC_GOALS = ("growth", "sales", "engagement", "expertise")

#: Har bir maqsad uchun 7 kunlik muvozanatlangan format matritsasi.
GOAL_FORMAT_MATRICES: dict[str, list[str]] = {
    "growth": [
        "viral_hook",
        "guide",
        "checklist",
        "trend",
        "myth_busting",
        "story",
        "digest",
    ],
    "sales": [
        "pas_offer",
        "case_study",
        "social_proof",
        "faq_objection",
        "comparison",
        "limited_offer",
        "cta_summary",
    ],
    "engagement": [
        "poll",
        "question_qa",
        "debate",
        "challenge",
        "behind_scenes",
        "community",
        "discussion",
    ],
    "expertise": [
        "deep_analysis",
        "framework",
        "case_breakdown",
        "tutorial",
        "benchmark",
        "tool_review",
        "summary",
    ],
}

#: Maqsad yorliqlari (uz / ru / en).
GOAL_LABELS: dict[str, dict[str, str]] = {
    "uz": {
        "growth": "Auditoriyani o'stirish",
        "sales": "Sotuv",
        "engagement": "Faollik",
        "expertise": "Ekspertiza",
    },
    "ru": {
        "growth": "Рост аудитории",
        "sales": "Продажи",
        "engagement": "Вовлечённость",
        "expertise": "Экспертиза",
    },
    "en": {
        "growth": "Audience growth",
        "sales": "Sales",
        "engagement": "Engagement",
        "expertise": "Expertise",
    },
}

_GOAL_ALIASES: dict[str, str] = {
    "growth": "growth",
    "auditoriyani o'stirish": "growth",
    "auditoriyani ostirish": "growth",
    "o'sish": "growth",
    "osish": "growth",
    "o'stirish": "growth",
    "рост": "growth",
    "рост аудитории": "growth",
    "audience growth": "growth",
    "sales": "sales",
    "sotuv": "sales",
    "savdo": "sales",
    "продажи": "sales",
    "engagement": "engagement",
    "faollik": "engagement",
    "aktivlik": "engagement",
    "вовлеченность": "engagement",
    "вовлечённость": "engagement",
    "expertise": "expertise",
    "authority": "expertise",
    "ekspertiza": "expertise",
    "ekspertlik": "expertise",
    "экспертиза": "expertise",
}


def normalize_strategic_goal(goal: Any) -> str:
    """Foydalanuvchi kiritgan maqsadni kanonik kodga keltiradi (PURE)."""
    raw = str(goal or "").strip().lower()
    if not raw:
        return "growth"
    if raw in _GOAL_ALIASES:
        return _GOAL_ALIASES[raw]
    for alias, target in _GOAL_ALIASES.items():
        if alias in raw:
            return target
    return "growth"


def _parse_iso_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def extract_headline_topic(text: Any) -> str:
    """Post matnining birinchi mazmunli qatoridan mavzu/sarlavha ajratadi."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    for line in raw.splitlines():
        cleaned = line.strip()
        if len(cleaned) >= 3:
            return cleaned[:160]
    return raw[:160]


def filter_posts_last_n_days(
    rows: list[Any],
    days: int = 30,
    now: datetime | None = None,
) -> list[dict]:
    """Oxirgi ``days`` kun ichidagi postlarni ajratib oladi (PURE).

    Sana maydoni bo'lmagan yozuvlar (masalan, test mock'lari) xavfsiz
    saqlanadi — dublikat tekshiruvi ularni o'tkazib yubormasligi uchun.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    cutoff = ref - timedelta(days=max(1, int(days)))
    filtered: list[dict] = []
    for row in rows or ():
        if isinstance(row, dict):
            content = str(row.get("content") or row.get("text") or "").strip()
            topic = str(row.get("topic") or "").strip() or extract_headline_topic(content)
            raw_date = row.get("post_date") or row.get("date") or row.get("created_at")
            dt = _parse_iso_dt(raw_date)
            if dt is not None and dt < cutoff:
                continue
            filtered.append({
                **row,
                "content": content,
                "topic": topic,
            })
        elif isinstance(row, (list, tuple)) and len(row) >= 4:
            content = str(row[3] or "").strip()
            raw_date = row[5] if len(row) > 5 else None
            dt = _parse_iso_dt(raw_date)
            if dt is not None and dt < cutoff:
                continue
            filtered.append({
                "content": content,
                "topic": extract_headline_topic(content),
                "post_date": dt.isoformat() if dt else "",
            })
        elif isinstance(row, str) and row.strip():
            content = row.strip()
            filtered.append({
                "content": content,
                "topic": extract_headline_topic(content),
                "post_date": "",
            })
    return filtered


def compute_content_gaps(
    dna_profile: dict | None = None,
    weekly_insights: dict | None = None,
    recent_posts: list[dict] | None = None,
    goal: str = "growth",
    total_slots: int = 7,
) -> dict:
    """Channel DNA va oxirgi postlar tahlilidan kontent bo'shliqlari (PURE).

    Qaytadi::

        {
            "format_gaps": [...],
            "topic_gaps": [...],
            "high_performing_formats": [...],
            "dna_topics": [...],
            "recommended_formats": [...],  # total_slots uzunlikda
        }
    """
    canon_goal = normalize_strategic_goal(goal)
    goal_formats = list(GOAL_FORMAT_MATRICES.get(canon_goal, GOAL_FORMAT_MATRICES["growth"]))

    profile = dna_profile if isinstance(dna_profile, dict) else {}
    insights = weekly_insights if isinstance(weekly_insights, dict) else {}

    # 1) Yuqori samarali formatlar (DNA dan)
    high_formats: list[str] = []
    raw_hf = profile.get("high_performing_formats_value")
    if not raw_hf and isinstance(profile.get("high_performing_formats"), dict):
        raw_hf = profile["high_performing_formats"].get("value")
    if isinstance(raw_hf, (list, tuple)):
        high_formats = [str(f).strip() for f in raw_hf if str(f).strip()]
    elif profile.get("formatting_style"):
        high_formats = [str(profile["formatting_style"]).strip()]

    # 2) Advisor aniqlagan format bo'shliqlari
    advisor_gaps = [
        str(g).strip()
        for g in (insights.get("content_gaps") or [])
        if str(g).strip()
    ]

    # Oxirgi postlarda ishlatilgan formatlar
    observed_formats = set((insights.get("format_distribution") or {}).keys())
    for p in recent_posts or ():
        if isinstance(p, dict) and p.get("format"):
            observed_formats.add(str(p["format"]).strip().lower())

    format_gaps: list[str] = []
    for fmt in advisor_gaps + goal_formats:
        if fmt not in observed_formats and fmt not in format_gaps:
            format_gaps.append(fmt)

    # 3) DNA mavzulari va mavzu bo'shliqlari
    dna_topics: list[str] = []
    raw_topics = profile.get("topics_value")
    if not raw_topics and isinstance(profile.get("topics"), dict):
        raw_topics = profile["topics"].get("value")
    if not raw_topics and isinstance(profile.get("top_topics"), list):
        raw_topics = profile["top_topics"]
    if isinstance(raw_topics, (list, tuple)):
        dna_topics = [str(t).strip() for t in raw_topics if str(t).strip()]

    recent_topic_tokens = {
        str(p.get("topic") or "").strip().lower()
        for p in (recent_posts or ())
        if isinstance(p, dict) and p.get("topic")
    }
    topic_gaps = [t for t in dna_topics if t.lower() not in recent_topic_tokens]

    # 4) 7 kunlik (yoki total_slots) muvozanatlangan formatlar ketma-ketligi:
    #    Maqsad matritsasi + Gap formatlar + DNA kuchli formatlari
    slot_count = max(1, int(total_slots or 7))
    recommended_formats: list[str] = []
    pool: list[str] = []
    for idx in range(max(len(goal_formats), len(format_gaps), len(high_formats), 7)):
        if idx < len(goal_formats):
            pool.append(goal_formats[idx])
        if idx < len(format_gaps) and format_gaps[idx] not in pool:
            pool.append(format_gaps[idx])
        if idx < len(high_formats) and high_formats[idx] not in pool:
            pool.append(high_formats[idx])
    if not pool:
        pool = goal_formats

    for i in range(slot_count):
        recommended_formats.append(pool[i % len(pool)])

    return {
        "goal": canon_goal,
        "format_gaps": format_gaps,
        "topic_gaps": topic_gaps,
        "high_performing_formats": high_formats,
        "dna_topics": dna_topics,
        "recommended_formats": recommended_formats,
    }


def build_content_loop_prompt_block(
    dna_profile: dict | None,
    gaps_info: dict | None = None,
    goal: str = "growth",
    frequency: int = 1,
    lang: str = "uz",
) -> str:
    """AI generator uchun Channel DNA + ContentLoop + Goal blokini quradi (PURE).

    ``build_dna_system_prompt`` chaqiruvi saqlanadi — shunda mavjud
    ``"KANAL USLUBI"`` kontrakti 100% bajariladi.
    """
    blocks: list[str] = []
    if isinstance(dna_profile, dict) and dna_profile:
        dna_text = build_dna_system_prompt(dna_profile, lang=lang)
        if dna_text:
            blocks.append(dna_text)

    canon_goal = normalize_strategic_goal(goal)
    freq = max(1, min(3, int(frequency or 1)))
    gaps = gaps_info if isinstance(gaps_info, dict) else {}
    fmt_gaps = ", ".join((gaps.get("format_gaps") or [])[:4]) or "—"
    rec_fmts = ", ".join((gaps.get("recommended_formats") or [])[:7]) or "—"
    goal_label = (GOAL_LABELS.get(lang) or GOAL_LABELS["uz"]).get(canon_goal, canon_goal)

    if lang == "ru":
        loop_line = (
            f"СТРАТЕГИЯ CONTENT LOOP: цель={goal_label} ({canon_goal}); "
            f"частота={freq} пост/день; пробелы форматов={fmt_gaps}; "
            f"рекомендуемый баланс форматов={rec_fmts}."
        )
    elif lang == "en":
        loop_line = (
            f"CONTENT LOOP STRATEGY: goal={goal_label} ({canon_goal}); "
            f"frequency={freq} post(s)/day; format gaps={fmt_gaps}; "
            f"recommended format mix={rec_fmts}."
        )
    else:
        loop_line = (
            f"CONTENT LOOP STRATEGIYASI: maqsad={goal_label} ({canon_goal}); "
            f"chastota=kuniga {freq} ta post; format bo'shliqlari={fmt_gaps}; "
            f"tavsiya etilgan formatlar balansi={rec_fmts}."
        )
    blocks.append(loop_line)
    return "\n\n".join(b for b in blocks if b).strip()


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


class ContentLoop:
    """Channel DNA + Weekly Insights/Gaps + 30-kunlik tarix integratsiyasi."""

    def __init__(self, db_module: Any = None):
        self.db = db_module if db_module is not None else _import_database()

    async def analyze(
        self,
        channel_id: str | int,
        user_id: int,
        *,
        goal: str = "growth",
        frequency: int = 1,
        days: int = 7,
        lang: str = "uz",
        now: datetime | None = None,
    ) -> dict:
        """Kanal uchun DNA, Best Time, Gaps va 30 kunlik tarixni yig'adi."""
        ch_id = str(channel_id or "").strip()
        if not ch_id:
            return {"ok": False, "error_code": "INVALID_CHANNEL",
                    "message": "Kanal ID bo'sh"}

        dna_result = await get_channel_dna(ch_id, user_id, db_module=self.db)
        if not dna_result.get("ok"):
            return {
                "ok": False,
                "error_code": dna_result.get("error_code", "DB_UNAVAILABLE"),
                "message": dna_result.get("message", "Kanal topilmadi"),
            }

        best_result = await get_best_time(ch_id, user_id, db_module=self.db)
        if not best_result.get("ok"):
            return {
                "ok": False,
                "error_code": best_result.get("error_code", "DB_UNAVAILABLE"),
                "message": best_result.get("message", "Kanal topilmadi"),
            }

        # Kengaytirilgan DNA (agar mavjud bo'lsa)
        ext_profile = None
        try:
            ext_res = await get_channel_dna_extended(ch_id, user_id, db_module=self.db)
            if ext_res.get("ok") and isinstance(ext_res.get("profile"), dict):
                ext_profile = ext_res["profile"]
        except Exception:
            logger.debug("ContentLoop: extended DNA olinmadi", exc_info=True)

        profile = dna_result.get("profile") or ext_profile or {}
        if isinstance(ext_profile, dict) and isinstance(profile, dict):
            merged_profile = {**ext_profile, **profile}
        else:
            merged_profile = profile if isinstance(profile, dict) else {}

        # Oxirgi 30 kunlik postlar tarixi (fail-soft)
        raw_history: list[Any] = []
        if self.db is not None and hasattr(self.db, "get_channel_posts_history"):
            try:
                raw_history = await _db_call(
                    self.db, self.db.get_channel_posts_history, ch_id, 50
                ) or []
            except Exception:
                logger.debug("ContentLoop: history o'qilmadi", exc_info=True)

        recent_posts_30d = filter_posts_last_n_days(raw_history, days=30, now=now)
        recent_texts = [p["content"] for p in recent_posts_30d if p.get("content")]
        recent_topics = [p["topic"] for p in recent_posts_30d if p.get("topic")]

        # 📊 P1 (5-qadam): Content Learning Loop uchun agregatlangan xulosa —
        # o'rtacha ko'rishlar va eng yaxshi formatlar DB DARAJASIDA (bitta
        # batch so'rov). Postlar soni qancha bo'lsa ham qo'shimcha so'rov
        # soni O'ZGARMAYDI (N+1 query yo'q); DB agregatsiyasi mavjud
        # bo'lmasa — lokal (PURE) hisob-kitob ishlatiladi.
        analytics_summary = None
        analytics_source = "local_fallback"
        if self.db is not None and hasattr(self.db, "get_channel_analytics_summary"):
            try:
                raw_summary = await _db_call(
                    self.db, self.db.get_channel_analytics_summary, ch_id, 30
                )
                if isinstance(raw_summary, dict) and raw_summary:
                    analytics_summary = raw_summary
                    analytics_source = "db_aggregate"
            except Exception:
                logger.debug("ContentLoop: DB agregatsiyasi olinmadi", exc_info=True)
        if analytics_summary is None:
            analytics_summary = summarize_posts_locally(recent_posts_30d, days=30)

        # Weekly advisor insights & gaps
        weekly_insights = compute_weekly_insights(recent_posts_30d, now=now, days=30)
        freq = max(1, min(3, int(frequency or 1)))
        total_slots = max(1, int(days or 7)) * freq
        gaps_info = compute_content_gaps(
            merged_profile,
            weekly_insights,
            recent_posts_30d,
            goal=goal,
            total_slots=total_slots,
        )

        # Best hours ro'yxati
        best_hours: list[int] = []
        if isinstance(merged_profile.get("best_hours_value"), list):
            best_hours = [int(h) for h in merged_profile["best_hours_value"] if isinstance(h, int)]
        if not best_hours and not best_result.get("insufficient"):
            peak = best_result.get("peak_hour")
            if isinstance(peak, int) and 0 <= peak <= 23:
                best_hours.append(peak)
            hour_dist = best_result.get("hour_distribution") or {}
            for h_str, _ in sorted(hour_dist.items(), key=lambda kv: (-int(kv[1]), int(kv[0]))):
                try:
                    h_val = int(h_str)
                    if 0 <= h_val <= 23 and h_val not in best_hours:
                        best_hours.append(h_val)
                except (TypeError, ValueError):
                    continue

        # Prompt uchun profil: DB agregatsiyasi bergan eng yaxshi formatlar
        # FAQAT yetishmayotgan kalitni to'ldiradi (mavjud DNA qiymatlari
        # hech qachon qayta yozilmaydi).
        prompt_profile = merged_profile if dna_result.get("profile") else None
        if analytics_summary and analytics_source == "db_aggregate":
            prompt_profile = attach_analytics_summary(prompt_profile, analytics_summary)

        prompt_block = build_content_loop_prompt_block(
            prompt_profile,
            gaps_info=gaps_info,
            goal=goal,
            frequency=freq,
            lang=lang,
        )

        return {
            "ok": True,
            "channel_id": ch_id,
            "goal": normalize_strategic_goal(goal),
            "frequency": freq,
            "dna_result": dna_result,
            "dna_profile": merged_profile if dna_result.get("profile") else None,
            "best_time_result": best_result,
            "best_hours": best_hours,
            "weekly_insights": weekly_insights,
            "gaps": gaps_info,
            "content_gaps": gaps_info["format_gaps"],
            "topic_gaps": gaps_info["topic_gaps"],
            "recommended_formats": gaps_info["recommended_formats"],
            "recent_posts_30d": recent_posts_30d,
            "recent_texts": recent_texts,
            "recent_topics": recent_topics,
            # 📊 P1 (5-qadam): DB darajasidagi agregatsiya (o'rtacha
            # ko'rishlar, eng yaxshi formatlar) — mavjud kalitlar
            # o'zgarmagan, bu QO'SHIMCHA ma'lumot.
            "analytics_summary": analytics_summary,
            "analytics_source": analytics_source,
            "avg_views": (analytics_summary or {}).get("avg_views", 0.0),
            "best_formats": list((analytics_summary or {}).get("best_formats") or []),
            "prompt_block": prompt_block,
        }


ContentIntelligenceLoop = ContentLoop


async def analyze_channel_content_loop(
    channel_id: str | int,
    user_id: int,
    *,
    goal: str = "growth",
    frequency: int = 1,
    days: int = 7,
    lang: str = "uz",
    db_module: Any = None,
) -> dict:
    """Qisqa yordamchi: ``ContentLoop(db_module).analyze(...)``."""
    return await ContentLoop(db_module=db_module).analyze(
        channel_id, user_id, goal=goal, frequency=frequency, days=days, lang=lang
    )


__all__ = [
    "ContentIntelligenceLoop",
    "ContentLoop",
    "GOAL_FORMAT_MATRICES",
    "GOAL_LABELS",
    "STRATEGIC_GOALS",
    "analyze_channel_content_loop",
    "build_content_loop_prompt_block",
    "compute_content_gaps",
    "extract_headline_topic",
    "filter_posts_last_n_days",
    "normalize_strategic_goal",
]
