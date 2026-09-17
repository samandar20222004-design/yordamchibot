"""📥 KONTENT MANBALARI — URL → post, RSS/ATOM oqimi (PHASE D, 11 & 12-bandlar).

Paket tarkibi:

* :mod:`services.sources.url_extractor` — havoladan maqola matnini olish:
  **qat'iy SSRF himoyasi** (localhost/ichki IP/redirect bloklanadi), 5 MB va
  10 soniya chegarasi, Title + asosiy mazmun ajratish, paywall/login NI
  CHETLAB O'TMAYDI, manba matnini AI ga **UNTRUSTED DATA** sifatida uzatish
  (prompt-injection himoyasi) va Channel DNA asosida 4 format
  (📰 Yangilik | ⚡ Qisqa | 🧠 Ekspert | 📢 Reklama) tayyorlash;
* :mod:`services.sources.rss_service` — RSS 2.0 / Atom 1.0 oqimlarini o'qish,
  ``content_sources`` / ``source_items`` jadvallari orqali **dublikat
  qayta ishlanmasligi**, Channel DNA asosida post qoralamasi yaratish va
  (autopublish yoqilgan bo'lsa) reja navbatiga yuborish.

Xavfsizlik: ikkala modul ham xatoda istisno ko'tarmaydi (fail-soft) va
foydalanuvchi kanal egaligi (IDOR) tekshiruvidan o'tadi.
"""

from services.sources.rss_service import (  # noqa: F401
    DEFAULT_INTERVAL_MINUTES,
    MAX_ITEMS_PER_CHECK,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    FeedItem,
    RssService,
    autopublish_draft,
    canonical_url,
    clamp_interval,
    digest_draft,
    filter_new_items,
    is_source_due,
    next_check_at,
    parse_feed,
    parse_interval_input,
    poll_due_sources,
)
from services.sources.url_extractor import (  # noqa: F401
    ALLOWED_SCHEMES,
    ERROR_MESSAGES,
    FETCH_TIMEOUT_SECONDS,
    FORMAT_KEYS,
    FORMAT_LABELS,
    MAX_RESPONSE_BYTES,
    UrlPostService,
    build_article_prompt,
    build_untrusted_block,
    detect_paywall,
    detect_prompt_injection,
    extract_article,
    fetch_and_extract,
    fetch_url,
    format_label,
    is_blocked_ip,
    local_draft,
    neutralize_untrusted_text,
    parse_variants,
    user_message,
    validate_public_url,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_INTERVAL_MINUTES",
    "ERROR_MESSAGES",
    "FETCH_TIMEOUT_SECONDS",
    "FORMAT_KEYS",
    "FORMAT_LABELS",
    "FeedItem",
    "MAX_ITEMS_PER_CHECK",
    "MAX_INTERVAL_MINUTES",
    "MAX_RESPONSE_BYTES",
    "MIN_INTERVAL_MINUTES",
    "RssService",
    "UrlPostService",
    "autopublish_draft",
    "build_article_prompt",
    "build_untrusted_block",
    "canonical_url",
    "clamp_interval",
    "detect_paywall",
    "detect_prompt_injection",
    "digest_draft",
    "extract_article",
    "fetch_and_extract",
    "fetch_url",
    "filter_new_items",
    "format_label",
    "is_blocked_ip",
    "is_source_due",
    "local_draft",
    "neutralize_untrusted_text",
    "next_check_at",
    "parse_feed",
    "parse_interval_input",
    "parse_variants",
    "poll_due_sources",
    "user_message",
    "validate_public_url",
]
