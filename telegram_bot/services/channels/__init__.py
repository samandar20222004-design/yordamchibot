"""🧠 Channel Intelligence (PostAssist V2 — PHASE B).

Kanal monitoringi va aqlli tahlil qatlami:

* :mod:`services.channels.monitoring` — kanal postlarining metama'lumotlarini
  ``channel_post_events`` jadvaliga IDEMPOTENT (ON CONFLICT DO NOTHING) yozish
  — asinxron va bloklamaydigan rejimda (channel post handler ichida task sifatida);
* :mod:`services.channels.dna` — Channel DNA profili (average_post_length,
  emoji_level, cta_style, formatting_style, sample_size, confidence_score)
  hisoblash, ``channel_intelligence_profiles`` ga saqlash va AI orkestrator
  promptiga ixcham system-prompt bloki sifatida ulash;
* :mod:`services.channels.best_time` — post chiqarish statistikasi bo'yicha
  eng maqbul vaqt oynalari (soxta raqamlar UYDIRMAYDI — yetarli ma'lumot
  bo'lmasa "insufficient data" holati qaytadi).

Xavfsizlik: barcha foydalanuvchiga ochiladigan so'rovlar (DNA / best time)
``user_id`` + ``channel_id`` ownership tekshiruvidan o'tadi (IDOR himoyasi).
"""

from services.channels.best_time import (  # noqa: F401
    MIN_POSTS_FOR_BEST_TIME,
    compute_best_time,
    format_hour,
    get_best_time,
    hour_window,
)
from services.channels.dna import (  # noqa: F401
    MIN_POSTS_FOR_DNA,
    attach_dna_to_context,
    build_dna_system_prompt,
    compute_channel_dna,
    get_channel_dna,
)
from services.channels.monitoring import (  # noqa: F401
    detect_cta,
    emoji_density,
    extract_event_metadata,
    ingest_channel_post_event,
    schedule_post_event_ingest,
)

__all__ = [
    "MIN_POSTS_FOR_BEST_TIME",
    "MIN_POSTS_FOR_DNA",
    "attach_dna_to_context",
    "build_dna_system_prompt",
    "compute_best_time",
    "compute_channel_dna",
    "detect_cta",
    "emoji_density",
    "extract_event_metadata",
    "format_hour",
    "get_best_time",
    "get_channel_dna",
    "hour_window",
    "ingest_channel_post_event",
    "schedule_post_event_ingest",
]
