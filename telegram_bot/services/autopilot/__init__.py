"""🚀 AI AUTOPILOT xizmat qatlami (PostAssist V2 — PHASE C, 7-band).

Foydalanuvchi mavzu/yo'nalish kiritadi, AI kanalning Channel DNA uslubi va
Smart Best Time tavsiyalariga tayangan holda 7 kunlik (Dushanba–Yakshanba)
to'liq post rejasini tuzadi. Har bir kun uchun: aniq vaqt, mavzu/format,
tayyor post matni va CTA.

Modullar:
    * :mod:`services.autopilot.planner` — PURE reja mantig'i (vaqtlar,
      normalizatsiya, quota, atomik rejalash) + AI generatsiya nuqtalari;

Xavfsizlik: kanalga bog'liq barcha so'rovlar (DNA, best time, kanal tarixi)
``user_id`` ownership tekshiruvidan o'tadi (IDOR himoyasi); navbat limiti
``check_queue_limit`` orqali qat'iy nazorat qilinadi (fail-closed).
"""

from services.autopilot.planner import (  # noqa: F401
    AUTOPILOT_DAYS,
    DEFAULT_POST_HOUR,
    build_week_plan,
    check_week_quota,
    compose_post_text,
    create_autopilot_plan,
    flag_duplicate_days,
    generate_autopilot_week,
    load_recent_channel_texts,
    next_week_start,
    normalize_ai_plan,
    resolve_post_hour,
    rewrite_flagged_posts,
    schedule_autopilot_week,
    week_times,
)

__all__ = [
    "AUTOPILOT_DAYS",
    "DEFAULT_POST_HOUR",
    "build_week_plan",
    "check_week_quota",
    "compose_post_text",
    "create_autopilot_plan",
    "flag_duplicate_days",
    "generate_autopilot_week",
    "load_recent_channel_texts",
    "next_week_start",
    "normalize_ai_plan",
    "resolve_post_hour",
    "rewrite_flagged_posts",
    "schedule_autopilot_week",
    "week_times",
]
