"""📢 REKLAMA DVIGATELI VA AUDITI — FAZA 15 & 16 (PostAssist V2).

Ikkita qatlam, bitta xavfsizlik siyosati:

* :mod:`services.ads.engine` — **reklama generatsiyasi dvigateli** (FAZA 15):
  brief (mahsulot, faktlar, taklif, auditoriya, CTA, havola) → 4 xil format
  (🧬 native / ⚡ short / 🎓 educational / 🌿 soft). ``native`` formati
  kanalning **Channel DNA** profili (``services.channels.dna``) bilan
  bog'lanadi; poydevor sifatida ``services.ai`` orkestratori, Phase 2 atomik
  kvotasi va HTML sanitizeri ishlatiladi (yangi AI quyi tizimi YO'Q).
* :mod:`services.ads.audit` — **reklama auditi** (FAZA 16): DNA mosligi, CTA
  aniqligi, **asossiz da'volar** (faktlarda bo'lmagan narx/kafolat/reyting/
  sertifikat) va o'qilish. Muammo bo'lsa ``requires_admin_approval=True`` va
  ``evaluate_publish()`` nashrni FAIL-CLOSED to'sadi.
* :mod:`services.ads.templates` — deterministik, raqamsiz zaxira bank
  (offline/mock rejimda ham "to'qima" reklama chiqmaydi).

NO FABRICATION — yagona siyosat
------------------------------
``services.ads.audit.scan_unsupported_claims()`` / ``strip_unsupported_claims()``
ham dvigatel (chiqish filtri), ham audit (tekshiruv) tomonidan ishlatiladi:
AI foydalanuvchi BERMAGAN narx, kafolat, reyting yoki sertifikatni yozsa ham,
bu da'vo postga TUSHMAYDI.
"""

from services.ads.audit import (  # noqa: F401
    AD_AUDIT_CHECK_KEYS,
    AD_AUDIT_CRITERIA,
    AD_AUDIT_WEIGHTS,
    CLAIM_ABSOLUTE,
    CLAIM_CERTIFICATE,
    CLAIM_DURATION,
    CLAIM_GUARANTEE,
    CLAIM_KINDS,
    CLAIM_PRICE,
    CLAIM_RATING,
    CLAIM_STATISTIC,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    AdAuditCheck,
    AdAuditResult,
    AdAuditService,
    AdPublishDecision,
    ClaimFinding,
    audit_ad,
    default_auditor,
    evaluate_publish,
    extract_numbers,
    gate_with_workflow,
    normalize_claim_text,
    normalize_number,
    render_audit_report,
    scan_unsupported_claims,
    score_cta,
    score_dna_fit,
    score_readability,
    strip_unsupported_claims,
)
from services.ads.engine import (  # noqa: F401
    AD_FORMATS,
    AD_FORMAT_COUNT,
    AD_FORMAT_INDEX,
    AD_FORMAT_KEYS,
    AdBrief,
    AdEngine,
    AdEngineResult,
    AdFormat,
    AdVariant,
    build_ad_prompt,
    build_dna_block,
    default_engine,
    formats_for,
    generate_ad_variants,
    is_safe_link,
    resolve_format,
)
from services.ads.templates import (  # noqa: F401
    AD_FORMAT_EDUCATIONAL,
    AD_FORMAT_NATIVE,
    AD_FORMAT_SHORT,
    AD_FORMAT_SOFT,
    build_ad_text,
    build_ad_text_from_payload,
)

__all__ = [
    # --- engine (FAZA 15) --------------------------------------------------
    "AD_FORMATS",
    "AD_FORMAT_COUNT",
    "AD_FORMAT_INDEX",
    "AD_FORMAT_KEYS",
    "AD_FORMAT_EDUCATIONAL",
    "AD_FORMAT_NATIVE",
    "AD_FORMAT_SHORT",
    "AD_FORMAT_SOFT",
    "AdBrief",
    "AdEngine",
    "AdEngineResult",
    "AdFormat",
    "AdVariant",
    "build_ad_prompt",
    "build_ad_text",
    "build_ad_text_from_payload",
    "build_dna_block",
    "default_engine",
    "formats_for",
    "generate_ad_variants",
    "is_safe_link",
    "resolve_format",
    # --- audit (FAZA 16) ---------------------------------------------------
    "AD_AUDIT_CHECK_KEYS",
    "AD_AUDIT_CRITERIA",
    "AD_AUDIT_WEIGHTS",
    "CLAIM_ABSOLUTE",
    "CLAIM_CERTIFICATE",
    "CLAIM_DURATION",
    "CLAIM_GUARANTEE",
    "CLAIM_KINDS",
    "CLAIM_PRICE",
    "CLAIM_RATING",
    "CLAIM_STATISTIC",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "AdAuditCheck",
    "AdAuditResult",
    "AdAuditService",
    "AdPublishDecision",
    "ClaimFinding",
    "audit_ad",
    "default_auditor",
    "evaluate_publish",
    "extract_numbers",
    "gate_with_workflow",
    "normalize_claim_text",
    "normalize_number",
    "render_audit_report",
    "scan_unsupported_claims",
    "score_cta",
    "score_dna_fit",
    "score_readability",
    "strip_unsupported_claims",
]
