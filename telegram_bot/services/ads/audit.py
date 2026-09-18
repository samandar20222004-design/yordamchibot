"""🛡 REKLAMA AUDITI VA XAVFSIZLIK TEKSHIRUVI — FAZA 16.

Reklama posti kanalga chiqishidan OLDIN avtomatik tekshiruvdan o'tadi:

=====  ====================  =================================================
  #    Mezon                 Nima tekshiriladi
=====  ====================  =================================================
 1     🧬 DNA mosligi        Channel DNA profili bilan uslub mosligi (uzunlik,
                             emoji darajasi, CTA uslubi, formatlash)
 2     📣 CTA aniqligi       Harakatga chaqiruv bormi, oxirgi qatorlarda turibdi,
                             brief'dagi CTA/havola postga tushganmi
 3     🚫 Asossiz da'volar   Foydalanuvchi BERMAGAN narx, kafolat, reyting,
                             sertifikat, statistika (unsupported claims)
 4     📖 O'qilishi          Uzunlik, qator/jumla hajmi, emoji zichligi,
                             "baqirish" (ALL CAPS), abzaslar
=====  ====================  =================================================

NO FABRICATION — bu modulning YADROSİ
------------------------------------
``scan_unsupported_claims()`` postdagi har bir sonli/kalit da'voni
foydalanuvchi bergan **faktlar korpusi** bilan solishtiradi. Faktlar orasida
bo'lmagan narx, foiz, kafolat, reyting yoki sertifikat ``ClaimFinding``
sifatida qaytadi; ``strip_unsupported_claims()`` esa shu da'voni matndan
OLIB TASHLAYDI (jumla darajasida). Bu yagona siyosat ham generatsiya
dvigatelida (:mod:`services.ads.engine`), ham auditda ishlatiladi — shu
sababli "to'qima" reklama foydalanuvchigacha yetib bormaydi.

Audit natijasi muammoli bo'lsa ``requires_admin_approval=True`` qaytadi va
``evaluate_publish()`` nashrni **FAIL-CLOSED** tarzda to'sadi: admin tasdig'i
bo'lmasa reklama chiqmaydi.

Modul ``services.ai`` poydevoriga tayanadi (sanitizer, til yordamchilari,
``grade_for``) — yangi parallel tizim YO'Q.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from services.ai.smm_common import (
    CHUNK_SAFE_LIMIT,
    DEFAULT_LANG,
    TELEGRAM_TEXT_LIMIT,
    coerce_int,
    lang_text,
    normalize_lang,
    sanitize_html,
    strip_html,
    word_count,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 1) ASOSSIZ DA'VOLAR (UNSUPPORTED CLAIMS) — NO FABRICATION SIYOSATI
# ===========================================================================
CLAIM_PRICE = "price"
CLAIM_GUARANTEE = "guarantee"
CLAIM_RATING = "rating"
CLAIM_CERTIFICATE = "certificate"
CLAIM_STATISTIC = "statistic"
CLAIM_ABSOLUTE = "absolute"
CLAIM_DURATION = "duration"

CLAIM_KINDS: tuple[str, ...] = (
    CLAIM_PRICE, CLAIM_GUARANTEE, CLAIM_RATING, CLAIM_CERTIFICATE,
    CLAIM_STATISTIC, CLAIM_ABSOLUTE, CLAIM_DURATION,
)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

#: Og'irlik tartibi (kattasi g'olib).
SEVERITY_RANK = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}

#: Da'vo turi → inson o'qiydigan nom (uz/ru/en).
CLAIM_KIND_LABELS: dict[str, dict] = {
    CLAIM_PRICE: {"uz": "Narx/summa da'vosi", "ru": "Заявление о цене",
                  "en": "Price claim"},
    CLAIM_GUARANTEE: {"uz": "Kafolat da'vosi", "ru": "Гарантийное заявление",
                      "en": "Guarantee claim"},
    CLAIM_RATING: {"uz": "Reyting/baho da'vosi", "ru": "Заявление о рейтинге",
                   "en": "Rating claim"},
    CLAIM_CERTIFICATE: {"uz": "Sertifikat/litsenziya da'vosi",
                        "ru": "Заявление о сертификате",
                        "en": "Certificate claim"},
    CLAIM_STATISTIC: {"uz": "Statistika da'vosi", "ru": "Статистическое заявление",
                      "en": "Statistic claim"},
    CLAIM_ABSOLUTE: {"uz": "Mutlaq (superlativ) da'vo", "ru": "Абсолютное заявление",
                     "en": "Absolute claim"},
    CLAIM_DURATION: {"uz": "Muddat/vaqt da'vosi", "ru": "Заявление о сроке",
                     "en": "Duration claim"},
}

#: Da'vo turi → qat'iyligi. Muddat da'volari ogohlantirish, qolgani — kritik.
CLAIM_KIND_SEVERITY: dict[str, str] = {
    CLAIM_PRICE: SEVERITY_CRITICAL,
    CLAIM_GUARANTEE: SEVERITY_CRITICAL,
    CLAIM_RATING: SEVERITY_CRITICAL,
    CLAIM_CERTIFICATE: SEVERITY_CRITICAL,
    CLAIM_STATISTIC: SEVERITY_CRITICAL,
    CLAIM_ABSOLUTE: SEVERITY_WARNING,
    CLAIM_DURATION: SEVERITY_WARNING,
}

# ---------------------------------------------------------------------------
# REGEXLAR (sof stdlib)
# ---------------------------------------------------------------------------
_NBSP_RE = re.compile(r"[\u00a0\u2007\u202f\u200b\u2060]")
_SPACE_RE = re.compile(r"\s+")
#: Son tokeni: "120 000", "1,500", "1.5", "45%" ning son qismi.
_NUM_TOKEN = r"\d[\d\u00a0\u2007\u202f\s'’.,]{0,14}\d|\d"

_CURRENCY_UNITS = (
    r"%|％|foiz|prosent|процент|percent|"
    r"so[\u02bb\u2018\u2019'`]?m|s[ou]m|сум|сўм|"
    r"usd|uzs|eur|rub|\$|€|₽|¥|₸|dollar|доллар|евро|рубл"
)
_PEOPLE_UNITS = (
    r"mijoz\w*|foydalanuvchi\w*|obunachi\w*|odam\w*|kishi\w*|talaba\w*|"
    r"клиент\w*|покупател\w*|пользовател\w*|подписчик\w*|человек\w*|"
    r"client\w*|customer\w*|user\w*|buyer\w*|student\w*|people"
)
_RATING_UNITS = (
    r"yulduz\w*|⭐|ball|reyting\w*|baholash\w*|"
    r"звезд\w*|рейтинг\w*|оценк\w*|"
    r"star\w*|rating|review\w*|score"
)
_TIME_UNITS = (
    r"kun|oy|yil|soat|daqiqa|hafta|"
    r"дн\w*|месяц\w*|недел\w*|год\w*|лет|час\w*|минут\w*|"
    r"day\w*|month\w*|week\w*|year\w*|hour\w*|minute\w*"
)
_MULTIPLIER_UNITS = r"x\b|karra|barobar|baravar|раз(?:а)?\b|times?\b|fold"

_NUMERIC_CLAIM_RE = re.compile(
    rf"(?<![\w.,])(?P<num>{_NUM_TOKEN})\s*(?P<unit>{_CURRENCY_UNITS})\b"
    rf"|(?<![\w.,])(?P<num_p>{_NUM_TOKEN})\s*(?P<unit_p>{_PEOPLE_UNITS})\b"
    rf"|(?<![\w.,])(?P<num_r>{_NUM_TOKEN})\s*(?P<unit_r>{_RATING_UNITS})\b"
    rf"|(?<![\w.,])(?P<num_t>{_NUM_TOKEN})\s*(?P<unit_t>{_TIME_UNITS})\b"
    rf"|(?<![\w.,])(?P<num_m>{_NUM_TOKEN})\s*(?P<unit_m>{_MULTIPLIER_UNITS})"
    rf"|(?<![\w.,])(?P<pct>{_NUM_TOKEN})\s*(?:%|％)",
    re.IGNORECASE,
)

#: Reyting/o'rin da'volari (raqam bilan yoki belgi bilan).
_RANK_CLAIM_RE = re.compile(
    r"№\s*\d|#\s*\d{1,3}\b|\d{1,3}\s*[-–]\s*(?:o[\u02bb'`]rin|орин|place|место)"
    r"|top\s*[-–]?\s*\d{1,3}\b"
    r"|(?:[\d.,]+)\s*/\s*5\b",
    re.IGNORECASE,
)
_STAR_CLAIM_RE = re.compile(r"⭐{1,10}|[\d.,]+\s*(?:yulduz|звезд|star)", re.IGNORECASE)

#: Kalit so'zli (raqamsiz) da'vo banki — til bo'yicha.
_GUARANTEE_TERMS: tuple[str, ...] = (
    # 🇺🇿
    "kafolat", "kafolatlay", "kafolatli", "garantiya", "garant",
    "pulni qaytar", "pul qaytar", "pulini qaytar", "xavf yo'q", "xavfsiz kafolat",
    "bepul qaytar", "natijaga kafolat", "100% natija", "100 foiz",
    # 🇷🇺
    "гарант", "возврат денег", "вернем деньги", "вернём деньги", "деньги назад",
    "без риска", "100% результат",
    # 🇬🇧
    "guarantee", "guaranteed", "money back", "money-back", "risk free",
    "risk-free", "100% result", "refund",
)

_CERTIFICATE_TERMS: tuple[str, ...] = (
    "sertifikat", "sertifikatlangan", "litsenziya", "litsenziyalangan",
    "davlat tomonidan tasdiqlangan", "xalqaro sertifikat", "akreditatsiya",
    "сертификат", "лицензи", "аккредит", "гост",
    "certified", "certificate", "certification", "licensed", "licence",
    "license", "accredited", "iso 9001", "fda approved",
)

_ABSOLUTE_TERMS: tuple[str, ...] = (
    "eng yaxshi", "eng arzon", "eng tez", "eng samarali", "eng sifatli",
    "yagona", "misli ko'rilmagan", "raqamli bir", "birinchi raqamli",
    "лучший", "самый лучший", "единственный", "не имеет аналогов", "номер один",
    "best in", "number one", "no.1", "unmatched", "the only",
)

_TERM_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CLAIM_GUARANTEE, _GUARANTEE_TERMS),
    (CLAIM_CERTIFICATE, _CERTIFICATE_TERMS),
    (CLAIM_ABSOLUTE, _ABSOLUTE_TERMS),
)

#: Bir da'vo parchasining maksimal uzunligi (hisobot uchun).
SNIPPET_LIMIT = 90
#: Jumla chegaralari (da'voni olib tashlashda).
_CLAUSE_DELIMS = ".!?;\n…"


# ---------------------------------------------------------------------------
# Normalizatsiya
# ---------------------------------------------------------------------------
def normalize_claim_text(text: Any) -> str:
    """Da'volarni solishtirish uchun matnni normallashtirish.

    HTML teglari olib tashlanadi, NBSP/tor bo'shliqlar oddiy bo'shliqqa
    aylanadi, registr pasaytiriladi va bo'shliqlar bitta qatorga yig'iladi.
    """
    value = _NBSP_RE.sub(" ", strip_html(text))
    value = value.lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'")
    return _SPACE_RE.sub(" ", value).strip()


def normalize_number(token: Any) -> str:
    """``"120 000"`` / ``"1,500"`` / ``"1.5"`` → taqqoslanadigan shakl.

    Qaytariladigan shakl: guruhlovchi ajratgichlarsiz butun son yoki
    o'nlik kasr (``1.5``). Muvaffaqiyatsiz holatda xom satr qaytadi.
    """
    raw = _NBSP_RE.sub("", str(token or ""))
    raw = raw.replace(" ", "").replace("'", "").replace("’", "").strip(".,")
    if not raw:
        return ""
    decimal = re.fullmatch(r"\d{1,9}[.,]\d{1,4}", raw)
    if decimal:
        return raw.replace(",", ".")
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return raw.lower()
    if "." in raw or "," in raw:
        # "1.200.000" / "1,200,000" — guruhlash; kasr qismi yo'q.
        cleaned = raw.replace(",", "").replace(".", "")
        if cleaned.isdigit():
            return cleaned
    return digits


def number_variants(token: Any) -> set[str]:
    """Sonning barcha mumkin bo'lgan taqqoslash shakllari.

    ``"1,500"`` inglizcha minglik ajratgich ham, o'zbek/ruscha o'nlik vergul
    ham bo'lishi mumkin — shu sababli IKKALA talqin ham qaytariladi. Bu
    YO'LDA soxta ogohlantirishlar (false positive) sonini kamaytiradi:
    foydalanuvchi faktga ``1,500`` deb yozsa, postdagi ``1500`` ham
    tasdiqlangan hisoblanadi.
    """
    raw = _NBSP_RE.sub("", str(token or ""))
    raw = raw.replace(" ", "").replace("'", "").replace("’", "").strip(".,")
    if not raw:
        return set()
    out = {normalize_number(raw)}
    digits = re.sub(r"[^\d]", "", raw)
    if digits:
        out.add(digits)
    stripped = raw.replace(",", "").replace(".", "")
    if stripped.isdigit():
        out.add(stripped)
    out.discard("")
    return out


def extract_numbers(text: Any) -> set[str]:
    """Matndagi barcha sonlarni normallashtirilgan ko'rinishda yig'ish."""
    plain = _NBSP_RE.sub(" ", strip_html(text))
    out: set[str] = set()
    for match in re.finditer(_NUM_TOKEN, plain):
        out |= number_variants(match.group(0))
    return out


def claim_corpus(values: Any) -> str:
    """Foydalanuvchi bergan barcha ma'lumotlardan bitta korpus matni yasash.

    ``str``, ro'yxat/tuple/set yoki lug'at (``text``/``value``/``fact``
    maydonlari) qabul qilinadi — brief ob'ektini import qilmasdan.
    """
    if values is None:
        return ""
    if isinstance(values, str):
        return values
    if isinstance(values, dict):
        return values.get("text") or values.get("value") or values.get("fact") or ""
    if isinstance(values, (list, tuple, set)):
        parts = [str(claim_corpus(item) or "") for item in values]
        return " \n ".join(part for part in parts if part)
    text = getattr(values, "corpus", None)
    if callable(text):
        try:
            return str(text() or "")
        except Exception:  # noqa: BLE001 — fail-soft
            return ""
    return str(values)


@dataclass(frozen=True)
class ClaimFinding:
    """Bitta asossiz (faktlarda bo'lmagan) da'vo."""

    kind: str
    snippet: str
    evidence: str = ""
    severity: str = SEVERITY_CRITICAL

    @property
    def label(self) -> dict:
        return CLAIM_KIND_LABELS.get(self.kind, {})

    def label_for(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.kind)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "snippet": self.snippet,
            "evidence": self.evidence,
            "severity": self.severity,
        }


def _kind_for_unit(unit: str) -> str:
    low = str(unit or "").lower()
    if re.fullmatch(_CURRENCY_UNITS, low):
        return CLAIM_PRICE
    if re.fullmatch(_PEOPLE_UNITS, low):
        return CLAIM_STATISTIC
    if re.fullmatch(_RATING_UNITS, low):
        return CLAIM_RATING
    if re.fullmatch(_TIME_UNITS, low):
        return CLAIM_DURATION
    if low in {"%", "％"}:
        return CLAIM_PRICE
    return CLAIM_STATISTIC


def scan_unsupported_claims(text: Any, facts: Any = None,
                            lang: Any = DEFAULT_LANG) -> list[ClaimFinding]:
    """Postdagi **faktlarda bo'lmagan** da'volarni topadi (deterministik).

    Args:
        text: reklama matni (HTML bo'lishi mumkin).
        facts: foydalanuvchi bergan faktlar — satr, ro'yxat yoki brief.
        lang: hisobot tili.

    Returns:
        ``ClaimFinding`` ro'yxati (bo'sh = matn toza).
    """
    code = normalize_lang(lang)
    raw = str(text or "")
    if not raw.strip():
        return []
    corpus = claim_corpus(facts)
    corpus_norm = normalize_claim_text(corpus)
    allowed_numbers = extract_numbers(corpus)
    findings: list[ClaimFinding] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, snippet: str, evidence: str,
            severity: str | None = None) -> None:
        clean = _SPACE_RE.sub(" ", snippet or "").strip()
        if not clean:
            return
        key = (kind, clean.lower())
        if key in seen:
            return
        seen.add(key)
        findings.append(ClaimFinding(
            kind=kind,
            snippet=clean if len(clean) <= SNIPPET_LIMIT else clean[:SNIPPET_LIMIT - 1] + "…",
            evidence=evidence,
            severity=severity or CLAIM_KIND_SEVERITY.get(kind, SEVERITY_CRITICAL),
        ))

    # --- 1) sonli da'volar (narx, statistika, reyting, muddat) ------------
    for match in _NUMERIC_CLAIM_RE.finditer(raw):
        groups = match.groupdict()
        if groups.get("pct"):
            number, unit, kind = groups["pct"], "%", CLAIM_PRICE
        else:
            number = (groups.get("num") or groups.get("num_p") or groups.get("num_r")
                      or groups.get("num_t") or groups.get("num_m") or "")
            unit = (groups.get("unit") or groups.get("unit_p") or groups.get("unit_r")
                    or groups.get("unit_t") or groups.get("unit_m") or "")
            kind = _kind_for_unit(unit)
        normalized = normalize_number(number)
        if not normalized:
            continue
        if normalized in allowed_numbers:
            continue
        if number_variants(number) & allowed_numbers:
            continue
        add(kind, match.group(0),
            f"'{number.strip()}' soni berilgan faktlarda yo'q (kod: {code})")

    # --- 2) reyting/o'rin da'volari --------------------------------------
    for match in _RANK_CLAIM_RE.finditer(raw):
        snippet = match.group(0)
        numbers = {normalize_number(item)
                   for item in re.findall(r"\d+", snippet) if item}
        if numbers and numbers <= allowed_numbers and \
                normalize_claim_text(snippet) in corpus_norm:
            continue
        add(CLAIM_RATING, snippet, "Reyting/o'rin da'vosi faktlarda tasdiqlanmagan")

    for match in _STAR_CLAIM_RE.finditer(raw):
        snippet = match.group(0)
        if normalize_claim_text(snippet) in corpus_norm:
            continue
        # Bitta ⭐ — bezak; 3+ yulduz yoki "4.9 yulduz" — baho da'vosi.
        if snippet.count("⭐") < 3 and not re.search(r"\d", snippet):
            continue
        add(CLAIM_RATING, snippet, "Yulduzli baho da'vosi faktlarda yo'q")

    # --- 3) kalit so'zli da'volar (kafolat, sertifikat, superlativ) -------
    lowered = normalize_claim_text(raw)
    for kind, terms in _TERM_TABLES:
        for term in terms:
            if term in lowered and term not in corpus_norm:
                add(kind, term, f"'{term}' da'vosi foydalanuvchi faktlarida yo'q")

    return findings


def worst_severity(findings: Sequence[ClaimFinding]) -> str:
    """Topilgan da'volarning eng og'ir darajasi (yo'q bo'lsa — info)."""
    worst = SEVERITY_INFO
    for item in findings or []:
        if SEVERITY_RANK.get(getattr(item, "severity", SEVERITY_INFO), 0) > \
                SEVERITY_RANK.get(worst, 0):
            worst = item.severity
    return worst


# ---------------------------------------------------------------------------
# Da'volarni matndan OLIB TASHLASH (generatsiya dvigateli shu bilan tozalaydi)
# ---------------------------------------------------------------------------
def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Da'vo joylashgan jumlaning chegaralarini topadi."""
    left = max(0, min(start, len(text)))
    while left > 0 and text[left - 1] not in _CLAUSE_DELIMS:
        left -= 1
    right = max(left, min(end, len(text)))
    while right < len(text) and text[right] not in _CLAUSE_DELIMS:
        right += 1
    if right < len(text):
        right += 1  # delimiter ham o'chsin
    return left, right


def _merge_spans(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Kesishadigan/yonma-yon oraliqlarni bittaga birlashtiradi."""
    ordered = sorted((max(0, start), max(start, end)) for start, end in spans)
    merged: list[list[int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            continue
        merged.append([start, end])
    return [(start, end) for start, end in merged]


def collect_claim_spans(text: Any, findings: Sequence[ClaimFinding],
                        min_severity: str = SEVERITY_WARNING
                        ) -> list[tuple[int, int, ClaimFinding]]:
    """Da'volarning asl (HTML'li) matndagi oraliqlarini yig'adi.

    Offsetlar asl matn bo'yicha hisoblanadi — shu sababli HTML teglari ichidagi
    da'volar ham to'g'ri topiladi.
    """
    raw = str(text or "")
    threshold = SEVERITY_RANK.get(min_severity, SEVERITY_WARNING)
    active = [item for item in findings
              if SEVERITY_RANK.get(item.severity, 0) >= threshold]
    if not raw or not active:
        return []

    wanted: dict[str, list[ClaimFinding]] = {}
    for finding in active:
        wanted.setdefault(finding.snippet.lower(), []).append(finding)

    spans: list[tuple[int, int, ClaimFinding]] = []
    patterns = (_NUMERIC_CLAIM_RE, _RANK_CLAIM_RE, _STAR_CLAIM_RE)
    for pattern in patterns:
        for match in pattern.finditer(raw):
            snippet = _SPACE_RE.sub(" ", match.group(0)).strip().lower()
            for key, group in wanted.items():
                if key in snippet or snippet in key:
                    spans.append((match.start(), match.end(), group[0]))
                    break
    for kind, terms in _TERM_TABLES:
        for term in terms:
            group = wanted.get(term)
            if not group or group[0].kind != kind:
                continue
            for match in re.finditer(re.escape(term), raw, re.IGNORECASE):
                spans.append((match.start(), match.end(), group[0]))
    return spans


def strip_unsupported_claims(text: Any, facts: Any = None,
                            lang: Any = DEFAULT_LANG,
                            min_severity: str = SEVERITY_WARNING
                            ) -> tuple[str, list[ClaimFinding]]:
    """Asossiz da'volarni matndan olib tashlaydi (jumla darajasida).

    Qaytadi: ``(tozalangan matn, olib tashlangan da'volar)``. Hech qachon
    istisno ko'tarmaydi — xatoda asl matn qaytariladi (chunki keyingi qadam
    audit yana tekshiradi va nashrni FAIL-CLOSED to'sadi).
    """
    code = normalize_lang(lang)
    raw = str(text or "")
    findings = scan_unsupported_claims(raw, facts, lang=code)
    if not findings:
        return raw, []
    try:
        spans = collect_claim_spans(raw, findings, min_severity)
        if not spans:
            return raw, []
        # 1) da'vo oraliqlari → jumla chegaralari; 2) kesishganlari birlashtiriladi.
        clause_spans = _merge_spans([_clause_bounds(raw, start, end)
                                     for start, end, _ in spans])
        owners: dict[tuple[int, int], list[ClaimFinding]] = {}
        for start, end, finding in spans:
            for left, right in clause_spans:
                if left <= start and end <= right:
                    owners.setdefault((left, right), []).append(finding)
                    break
        result = raw
        removed: list[ClaimFinding] = []
        for left, right in sorted(clause_spans, key=lambda item: item[0], reverse=True):
            removed.extend(owners.get((left, right), []))
            result = result[:left] + result[right:]
    except Exception as exc:  # noqa: BLE001 — fail-soft, audit keyin to'sadi
        logger.warning("strip_unsupported_claims xatosi: %s", exc)
        return raw, findings

    cleaned = _cleanup_after_strip(result)
    unique: list[ClaimFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in removed:
        key = (finding.kind, finding.snippet.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return cleaned, unique


def _cleanup_after_strip(text: str) -> str:
    """O'chirishdan keyingi kosmetik tozalash."""
    value = re.sub(r"[ \t]{2,}", " ", text)
    value = re.sub(r"\n{3,}", "\n\n", value)
    lines: list[str] = []
    for line in value.split("\n"):
        item = line.strip()
        item = re.sub(r"^[•\-–—,;:]+\s*", "", item)
        item = re.sub(r"\s+([.,;:!?])", r"\1", item).strip()
        if not item:
            lines.append("")
            continue
        if len(item) < 3 and not re.search(r"[\w]", item):
            continue
        lines.append(item)
    return "\n".join(lines).strip()


# ===========================================================================
# 2) AUDIT MEZONLARI
# ===========================================================================
DNA_CHECK = "dna_fit"
CTA_CHECK = "cta_clarity"
CLAIMS_CHECK = "unsupported_claims"
READABILITY_CHECK = "readability"

AD_AUDIT_CHECK_KEYS: tuple[str, ...] = (
    DNA_CHECK, CTA_CHECK, CLAIMS_CHECK, READABILITY_CHECK,
)

#: Og'irliklar (jami 100). Asossiz da'vo — eng og'ir mezon.
AD_AUDIT_WEIGHTS: dict[str, int] = {
    DNA_CHECK: 20,
    CTA_CHECK: 20,
    CLAIMS_CHECK: 40,
    READABILITY_CHECK: 20,
}

#: Ball chegaralari (repo POST_SCORE standarti bilan bir xil).
CRITERION_MIN, CRITERION_MAX = 1, 10
OVERALL_MAX = 100

#: DNA mosligi o'tish chegarasi (1-10).
DNA_FIT_MIN = 6
#: Audit "yashil" hisoblanadigan minimal umumiy ball.
AUDIT_PASS_SCORE = 70
#: Format bo'yicha hajm chegaralari (o'qiladigan belgilar).
FORMAT_LENGTH_RANGE: dict[str, tuple[int, int]] = {
    "native": (180, 2200),
    "short": (60, 600),
    "educational": (220, 2600),
    "soft": (150, 1800),
}
DEFAULT_LENGTH_RANGE = (120, 2600)
MAX_LINE_CHARS = 140
MAX_AVG_SENTENCE_WORDS = 30
MAX_EMOJI_DENSITY = 0.08

#: CTA fe'llari (uz/ru/en) — harakatga chaqiruv aniqligi uchun.
CTA_VERBS: dict[str, tuple[str, ...]] = {
    "uz": ("yozing", "yozib", "buyurtma", "bog'lan", "murojaat", "o'ting",
           "bosing", "tanlang", "oling", "ro'yxatdan", "hoziroq", "so'rang",
           "obuna", "qo'ng'iroq", "👉", "🛒", "📞", "🔗", "🤍"),
    "ru": ("напиш", "закаж", "свяж", "позвон", "перейд", "нажм", "выбер",
           "узнай", "подпиш", "оформ", "успей", "👉", "🛒", "📞", "🔗", "🤍"),
    "en": ("message", "order", "buy", "contact", "click", "tap", "choose",
           "sign up", "call", "book", "get in touch", "subscribe",
           "👉", "🛒", "📞", "🔗", "🤍"),
}

_CTA_WINDOW_LINES = 3


@dataclass(frozen=True)
class AdAuditCriterion:
    """Audit mezoni meta-ma'lumoti (i18n bilan)."""

    key: str
    emoji: str
    label: dict
    problem: dict
    fix: dict

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_problem(self, lang: Any) -> str:
        return lang_text(self.problem, lang, "")

    def t_fix(self, lang: Any) -> str:
        return lang_text(self.fix, lang, "")


AD_AUDIT_CRITERIA: tuple[AdAuditCriterion, ...] = (
    AdAuditCriterion(
        key=DNA_CHECK, emoji="🧬",
        label={"uz": "Kanal ohangi (DNA)", "ru": "Тон канала (DNA)",
               "en": "Channel tone (DNA)"},
        problem={"uz": "Reklama kanalning Channel DNA uslubidan chetga chiqdi.",
                 "ru": "Реклама выбивается из Channel DNA стиля канала.",
                 "en": "The ad drifts away from the channel's Channel DNA style."},
        fix={"uz": "Uzunlik, emoji darajasi va CTA uslubini kanal DNA'siga moslang.",
             "ru": "Подгоните длину, уровень эмодзи и стиль CTA под DNA канала.",
             "en": "Match length, emoji level and CTA style to the channel DNA."},
    ),
    AdAuditCriterion(
        key=CTA_CHECK, emoji="📣",
        label={"uz": "CTA aniqligi", "ru": "Ясность CTA", "en": "CTA clarity"},
        problem={"uz": "Harakatga chaqiruv aniq emas yoki postning oxirida emas.",
                 "ru": "Призыв к действию неясен или стоит не в конце поста.",
                 "en": "The call to action is unclear or not at the end."},
        fix={"uz": "Oxirgi qatorlarga BITTA aniq chaqiruv va havolani qo'ying.",
             "ru": "Поставьте ОДИН чёткий призыв и ссылку в последние строки.",
             "en": "Put ONE clear ask and the link in the final lines."},
    ),
    AdAuditCriterion(
        key=CLAIMS_CHECK, emoji="🚫",
        label={"uz": "Asossiz da'volar", "ru": "Необоснованные заявления",
               "en": "Unsupported claims"},
        problem={"uz": "Foydalanuvchi bermagan narx/kafolat/reyting da'vosi topildi.",
                 "ru": "Найдены цена/гарантия/рейтинг, которых пользователь не давал.",
                 "en": "Prices/guarantees/ratings the user never provided were found."},
        fix={"uz": "Da'voni olib tashlang yoki uni tasdiqlovchi faktni brief'ga qo'shing.",
             "ru": "Уберите заявление или добавьте подтверждающий факт в бриф.",
             "en": "Remove the claim or add the supporting fact to the brief."},
    ),
    AdAuditCriterion(
        key=READABILITY_CHECK, emoji="📖",
        label={"uz": "Uzunlik va o'qilishi", "ru": "Длина и читаемость",
               "en": "Length and readability"},
        problem={"uz": "Matn juda uzun/qisqa yoki o'qish qiyin (uzun qatorlar, emoji spam).",
                 "ru": "Текст слишком длинный/короткий или тяжело читается.",
                 "en": "The text is too long/short or hard to read."},
        fix={"uz": "Qatorlarni qisqartiring, abzaslarni ajrating, emoji sonini kamaytiring.",
             "ru": "Сократите строки, разделите абзацы, уменьшите число эмодзи.",
             "en": "Shorten lines, split paragraphs and reduce the emoji count."},
    ),
)


@dataclass
class AdAuditCheck:
    """Bitta mezon natijasi."""

    key: str
    emoji: str
    label: str
    passed: bool
    score: int
    severity: str = SEVERITY_INFO
    detail: str = ""
    fix: str = ""
    skipped: bool = False
    weight: int = 0
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "emoji": self.emoji,
            "label": self.label,
            "passed": self.passed,
            "score": self.score,
            "severity": self.severity,
            "detail": self.detail,
            "fix": self.fix,
            "skipped": self.skipped,
            "weight": self.weight,
            "metrics": dict(self.metrics),
        }


@dataclass
class AdAuditResult:
    """Reklama auditi hisoboti."""

    ok: bool = True
    post: str = ""
    format: str = "native"
    lang: str = DEFAULT_LANG
    score: int = 0
    grade: str = "E"
    checks: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    reason_codes: list = field(default_factory=list)
    dna_applied: bool = False
    dna_confidence: str = ""
    dna_sample_size: int = 0
    chars: int = 0
    words: int = 0
    readability: dict = field(default_factory=dict)
    requires_admin_approval: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.ok and not self.blockers)

    def check(self, key: str) -> AdAuditCheck | None:
        for item in self.checks:
            if item.key == key:
                return item
        return None

    def severity(self) -> str:
        return worst_severity(self.claims) if self.claims else (
            SEVERITY_WARNING if self.warnings else SEVERITY_INFO)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "passed": self.passed,
            "format": self.format,
            "lang": self.lang,
            "score": self.score,
            "grade": self.grade,
            "checks": [item.as_dict() for item in self.checks],
            "claims": [item.as_dict() for item in self.claims],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "reason_codes": list(self.reason_codes),
            "dna_applied": self.dna_applied,
            "dna_confidence": self.dna_confidence,
            "dna_sample_size": self.dna_sample_size,
            "chars": self.chars,
            "words": self.words,
            "readability": dict(self.readability),
            "requires_admin_approval": self.requires_admin_approval,
            "error": self.error,
        }


@dataclass
class AdPublishDecision:
    """Nashr qarori (fail-closed admin tasdig'i darvozasi)."""

    allowed: bool = False
    requires_admin_approval: bool = False
    admin_approved: bool = False
    approved_by: int | None = None
    reason_codes: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    message: str = ""
    score: int = 0

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "requires_admin_approval": self.requires_admin_approval,
            "admin_approved": self.admin_approved,
            "approved_by": self.approved_by,
            "reason_codes": list(self.reason_codes),
            "blockers": list(self.blockers),
            "message": self.message,
            "score": self.score,
        }


# ===========================================================================
# 3) DNA MOSLIGI
# ===========================================================================
def _profile_value(profile: dict, *keys: str) -> Any:
    """Kengaytirilgan (wrapped) va oddiy DNA profilidan qiymat olish."""
    for key in keys:
        value = profile.get(key)
        if isinstance(value, dict):
            value = value.get("value", value.get(key))
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_dna_profile(dna: Any) -> dict:
    """Turli manbalardan kelgan DNA natijasini yagona profil shakliga keltirish.

    ``get_channel_dna()`` javobi, ``compute_channel_dna()`` natijasi yoki
    to'g'ridan-to'g'ri profil lug'ati qabul qilinadi.
    """
    if not isinstance(dna, dict) or not dna:
        return {}
    if "profile" in dna and isinstance(dna.get("profile"), dict):
        profile = dict(dna["profile"])
        profile.setdefault("sample_size", dna.get("sample_size"))
        profile.setdefault("confidence", dna.get("confidence"))
        return profile
    return dict(dna)


def dna_sample_size(profile: dict) -> int:
    return coerce_int(_profile_value(profile, "sample_size"), 0, 0, 10 ** 9)


def dna_is_sufficient(profile: dict) -> bool:
    try:
        from services.channels.dna import MIN_POSTS_FOR_DNA
        minimum = int(MIN_POSTS_FOR_DNA)
    except Exception:  # noqa: BLE001 — fail-soft
        minimum = 5
    return dna_sample_size(profile) >= minimum


def _emoji_density(text: str) -> float:
    try:
        from services.channels.monitoring import emoji_density
        return float(emoji_density(text))
    except Exception:  # noqa: BLE001 — fail-soft
        return 0.0


def _emoji_level(density: float) -> str:
    try:
        from services.channels.dna import classify_emoji_level
        return str(classify_emoji_level(density))
    except Exception:  # noqa: BLE001 — fail-soft
        if density < 0.004:
            return "low"
        if density < 0.012:
            return "medium"
        return "high"


def _has_cta(text: str, lang: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in CTA_VERBS.get(lang, CTA_VERBS["uz"]))


def score_dna_fit(post: Any, dna: Any, lang: Any = DEFAULT_LANG) -> dict:
    """Channel DNA profili bilan moslikni baholaydi (1-10 + metrikalar).

    DNA yetarli bo'lmasa ``skipped=True`` qaytadi — soxta baholash yo'q.
    """
    code = normalize_lang(lang)
    profile = normalize_dna_profile(dna)
    plain = strip_html(post)
    length = len(plain)
    if not profile or not dna_is_sufficient(profile):
        try:
            from services.channels.dna import INSUFFICIENT_DATA_MESSAGE
            message = INSUFFICIENT_DATA_MESSAGE
        except Exception:  # noqa: BLE001
            message = "DNA uchun yetarli ma'lumot yo'q"
        return {"skipped": True, "score": 0, "length": length,
                "detail": message, "sample_size": dna_sample_size(profile)}

    avg_length = coerce_int(_profile_value(profile, "average_post_length",
                                           "avg_length"), 0, 0, 10 ** 6)
    emoji_target = str(_profile_value(profile, "emoji_level") or "").lower()
    cta_style = str(_profile_value(profile, "cta_style") or "").lower()
    formatting = str(_profile_value(profile, "formatting_style") or "").lower()
    density = _emoji_density(plain)
    emoji_actual = _emoji_level(density)
    has_cta = _has_cta(plain, code)

    scores: list[int] = []
    metrics: dict[str, Any] = {
        "length": length,
        "dna_length": avg_length,
        "emoji_actual": emoji_actual,
        "emoji_target": emoji_target,
        "emoji_density": round(density, 4),
        "cta_style": cta_style,
        "cta_detected": has_cta,
        "formatting_style": formatting,
        "sample_size": dna_sample_size(profile),
    }
    notes: list[str] = []

    if avg_length > 0:
        deviation = abs(length - avg_length) / avg_length
        if deviation <= 0.35:
            scores.append(10)
        elif deviation <= 0.6:
            scores.append(8)
        elif deviation <= 1.0:
            scores.append(6)
        elif deviation <= 1.6:
            scores.append(4)
        else:
            scores.append(2)
            notes.append(f"uzunlik {length} / DNA {avg_length}")
        metrics["length_deviation"] = round(deviation, 2)
        # Hajm — DNA'ning eng ko'zga tashlanadigan belgisi: post kanal
        # me'yoridan 2.6 barobar uzun/qisqa bo'lsa, emoji/CTA mos kelishi
        # uni OQLAMAYDI (umumiy ball past chegaraga tushiriladi).
        if deviation > 1.6:
            metrics["length_cap"] = DNA_FIT_MIN - 1

    if emoji_target:
        order = ("low", "medium", "high")
        if emoji_actual == emoji_target:
            scores.append(10)
        elif abs(order.index(emoji_actual) - order.index(emoji_target)) == 1:
            scores.append(7)
        else:
            scores.append(3)
            notes.append(f"emoji {emoji_actual} / DNA {emoji_target}")
        metrics["emoji_level_diff"] = emoji_actual != emoji_target

    if cta_style in {"always", "most"}:
        scores.append(10 if has_cta else 3)
        if not has_cta:
            notes.append("kanalda CTA doim bor, reklamada yo'q")

    if formatting == "short":
        scores.append(10 if length <= 220 else 5)
    elif formatting == "long_form":
        scores.append(10 if length >= 400 else 6)
    elif formatting == "media_rich":
        scores.append(8)
        notes.append("kanal media-rich: rasm/video biriktirish tavsiya etiladi")
    else:
        scores.append(9)

    score = int(round(sum(scores) / len(scores))) if scores else 0
    cap = int(metrics.get("length_cap") or CRITERION_MAX)
    score = min(score, cap)
    return {
        "skipped": False,
        "score": max(CRITERION_MIN, min(CRITERION_MAX, score)),
        "detail": "; ".join(notes),
        "metrics": metrics,
        "sample_size": dna_sample_size(profile),
        "confidence": str(profile.get("confidence") or ""),
    }


# ===========================================================================
# 4) CTA VA O'QILISH
# ===========================================================================
def score_cta(post: Any, cta: Any = "", link: Any = "",
              lang: Any = DEFAULT_LANG) -> dict:
    """Harakatga chaqiruv aniqligini baholaydi (1-10)."""
    code = normalize_lang(lang)
    plain = strip_html(post)
    lines = [item.strip() for item in plain.split("\n") if item.strip()]
    tail = " ".join(lines[-_CTA_WINDOW_LINES:]).lower()
    verbs = CTA_VERBS.get(code, CTA_VERBS["uz"])
    has_verb = any(term in plain.lower() for term in verbs)
    tail_verb = any(term in tail for term in verbs)
    wanted_cta = str(cta or "").strip()
    wanted_link = str(link or "").strip()
    link_present = bool(wanted_link) and wanted_link.lower() in str(post or "").lower()
    cta_present = True
    if wanted_cta:
        tokens = [word for word in re.findall(r"[\w']{4,}", wanted_cta.lower())]
        cta_present = any(word in plain.lower() for word in tokens) if tokens else True

    metrics = {
        "has_cta_verb": has_verb,
        "cta_in_tail": tail_verb,
        "link_required": bool(wanted_link),
        "link_present": link_present,
        "cta_required": bool(wanted_cta),
        "cta_present": cta_present,
    }
    notes: list[str] = []
    if not has_verb:
        score = 3
        notes.append("harakatga chaqiruv fe'li yo'q")
    elif not tail_verb:
        score = 6
        notes.append("CTA postning oxirida emas")
    else:
        score = 10
    if wanted_link and not link_present:
        score = min(score, 5)
        notes.append("berilgan havola postga tushmagan")
    if wanted_cta and not cta_present:
        score = min(score, 6)
        notes.append("brief'dagi CTA matni postda yo'q")
    return {"score": max(CRITERION_MIN, min(CRITERION_MAX, score)),
            "detail": "; ".join(notes), "metrics": metrics}


def score_readability(post: Any, format_key: str = "native") -> dict:
    """Uzunlik va o'qilishni baholaydi (1-10)."""
    plain = strip_html(post)
    length = len(plain)
    lo, hi = FORMAT_LENGTH_RANGE.get(format_key, DEFAULT_LENGTH_RANGE)
    lines = [item for item in plain.split("\n") if item.strip()]
    longest = max((len(item) for item in lines), default=0)
    words = word_count(plain)
    sentences = [item for item in re.split(r"[.!?…\n]+", plain) if len(item.strip()) > 3]
    avg_sentence_words = (words / len(sentences)) if sentences else float(words)
    density = _emoji_density(plain)
    caps_lines = [item for item in lines
                  if len(item.split()) >= 3
                  and sum(1 for ch in item if ch.isupper()) >= 0.7 * max(1, len(re.sub(r"\W", "", item)))]
    has_paragraphs = "\n\n" in plain

    metrics = {
        "chars": length,
        "min_chars": lo,
        "max_chars": hi,
        "longest_line": longest,
        "avg_sentence_words": round(avg_sentence_words, 1),
        "emoji_density": round(density, 4),
        "caps_lines": len(caps_lines),
        "has_paragraphs": has_paragraphs,
        "lines": len(lines),
    }
    notes: list[str] = []
    score = 10
    if length < lo:
        score -= 4
        notes.append(f"matn juda qisqa ({length} < {lo})")
    if length > hi:
        score -= 3
        notes.append(f"matn juda uzun ({length} > {hi})")
    if longest > MAX_LINE_CHARS:
        score -= 2
        notes.append(f"eng uzun qator {longest} belgi")
    if avg_sentence_words > MAX_AVG_SENTENCE_WORDS:
        score -= 2
        notes.append("jumlalar juda uzun")
    if density > MAX_EMOJI_DENSITY:
        score -= 2
        notes.append("emoji juda ko'p")
    if caps_lines:
        score -= 1
        notes.append(f"{len(caps_lines)} ta qator KATTA HARFLARDA")
    if length > 500 and not has_paragraphs:
        score -= 1
        notes.append("abzaslar ajratilmagan")
    return {"score": max(CRITERION_MIN, min(CRITERION_MAX, score)),
            "detail": "; ".join(notes), "metrics": metrics}


# ===========================================================================
# 5) AUDIT XIZMATI
# ===========================================================================
class AdAuditService:
    """Reklama posti auditi (deterministik + Channel DNA).

    AI chaqiruvi YO'Q: barcha ballar lokal hisoblanadi — model o'z reklamasi
    uchun "100/100" deb yoza olmaydi (manipulyatsiyaga yopiq eshik).
    """

    feature = "ads_audit"

    def audit(self, post: Any, *, facts: Any = None, product: Any = "",
              offer: Any = "", audience: Any = "", cta: Any = "",
              link: Any = "", format: str = "native", lang: Any = DEFAULT_LANG,
              dna: Any = None) -> AdAuditResult:
        code = normalize_lang(lang)
        text = str(post or "")
        corpus = claim_corpus([
            claim_corpus(facts), claim_corpus(product), claim_corpus(offer),
            claim_corpus(audience), claim_corpus(cta), claim_corpus(link),
        ])
        result = AdAuditResult(post=text, format=format, lang=code,
                               chars=len(strip_html(text)),
                               words=word_count(text))
        if len(strip_html(text).strip()) < 20:
            result.ok = False
            result.error = "empty_post"
            result.blockers.append("Post bo'sh yoki juda qisqa — audit bajarilmadi")
            result.reason_codes.append("EMPTY_POST")
            result.requires_admin_approval = True
            return result

        # --- 🚫 asossiz da'volar (eng og'ir mezon) -------------------------
        claims = scan_unsupported_claims(text, corpus, lang=code)
        result.claims = claims
        claims_score = CRITERION_MAX
        if claims:
            critical = [item for item in claims
                        if item.severity == SEVERITY_CRITICAL]
            if critical:
                claims_score = CRITERION_MIN
            else:
                claims_score = 5
        claim_check = self._criterion(
            CLAIMS_CHECK, passed=not claims, score=claims_score,
            severity=worst_severity(claims), lang=code,
            detail=self._claims_detail(claims, code) or
            "Asossiz narx/kafolat/reyting da'vosi topilmadi",
            fix_when_failed=True,
            metrics={"count": len(claims),
                     "kinds": sorted({item.kind for item in claims})},
        )
        result.checks.append(claim_check)
        for item in claims:
            line = f"{item.label_for(code)}: «{item.snippet}»"
            if item.severity == SEVERITY_CRITICAL:
                result.blockers.append(line)
                result.reason_codes.append(f"UNSUPPORTED_{item.kind.upper()}")
            else:
                result.warnings.append(line)
                result.reason_codes.append(f"REVIEW_{item.kind.upper()}")

        # --- 🧬 DNA mosligi -------------------------------------------------
        dna_info = score_dna_fit(text, dna, lang=code)
        result.dna_sample_size = int(dna_info.get("sample_size") or 0)
        result.dna_confidence = str(dna_info.get("confidence") or "")
        result.dna_applied = not dna_info.get("skipped", True)
        dna_skipped = bool(dna_info.get("skipped"))
        result.checks.append(self._criterion(
            DNA_CHECK, passed=True if dna_skipped
            else int(dna_info.get("score") or 0) >= DNA_FIT_MIN,
            score=int(dna_info.get("score") or 0),
            severity=SEVERITY_INFO if dna_skipped else SEVERITY_WARNING,
            lang=code,
            detail=dna_info.get("detail") or "",
            skipped=dna_skipped,
            fix_when_failed=True,
            metrics=dna_info.get("metrics") or {},
        ))
        if result.dna_applied and dna_info.get("score", 0) < DNA_FIT_MIN:
            result.warnings.append(
                "Reklama kanal ohangiga (Channel DNA) to'liq mos kelmadi: "
                f"{dna_info.get('detail') or ''}".strip(": "))
            result.reason_codes.append("DNA_MISMATCH")

        # --- 📣 CTA aniqligi ------------------------------------------------
        cta_info = score_cta(text, cta, link, lang=code)
        result.checks.append(self._criterion(
            CTA_CHECK, passed=cta_info["score"] >= 7, score=cta_info["score"],
            severity=SEVERITY_WARNING, lang=code,
            detail=cta_info["detail"] or "CTA aniq va postning oxirida",
            fix_when_failed=True, metrics=cta_info["metrics"],
        ))
        if cta_info["score"] < 7:
            result.blockers.append(
                "CTA aniq emas" + (f": {cta_info['detail']}" if cta_info["detail"] else ""))
            result.reason_codes.append("CTA_UNCLEAR")

        # --- 📖 O'qilishi ---------------------------------------------------
        read_info = score_readability(text, format)
        result.readability = read_info["metrics"]
        result.checks.append(self._criterion(
            READABILITY_CHECK, passed=read_info["score"] >= 6,
            score=read_info["score"], severity=SEVERITY_WARNING, lang=code,
            detail=read_info["detail"] or "Matn hajmi va tuzilishi me'yorda",
            fix_when_failed=True, metrics=read_info["metrics"],
        ))
        if read_info["score"] < 6:
            result.warnings.append(
                f"O'qilish past: {read_info['detail']}".strip(": "))
            result.reason_codes.append("READABILITY_LOW")

        # --- Umumiy ball ----------------------------------------------------
        result.score = self.overall(result.checks)
        if any(item.severity == SEVERITY_CRITICAL for item in claims):
            result.score = min(result.score, 40)
        try:
            from services.ai.audit import grade_for
            result.grade = grade_for(result.score)
        except Exception:  # noqa: BLE001 — fail-soft
            result.grade = "E"
        result.requires_admin_approval = bool(result.blockers)
        return result

    # -- yordamchi ---------------------------------------------------------
    @staticmethod
    def overall(checks: Sequence[AdAuditCheck]) -> int:
        """Og'irlikka ko'ra 0-100 ball (o'tkazib yuborilgan mezonlar hisobga olinmaydi)."""
        weight_total = 0
        total = 0.0
        for item in checks:
            if item.skipped:
                continue
            weight = int(item.weight or AD_AUDIT_WEIGHTS.get(item.key, 0))
            weight_total += weight
            total += coerce_int(item.score, CRITERION_MIN, CRITERION_MIN,
                                CRITERION_MAX) * weight
        if not weight_total:
            return 0
        return max(0, min(OVERALL_MAX, int(round(total / weight_total * CRITERION_MAX))))

    @staticmethod
    def _criterion(key: str, *, passed: bool, score: int, severity: str,
                   lang: str, detail: str, fix_when_failed: bool = False,
                   skipped: bool = False, metrics: dict | None = None
                   ) -> AdAuditCheck:
        meta = next((item for item in AD_AUDIT_CRITERIA if item.key == key), None)
        fix = meta.t_fix(lang) if (meta and fix_when_failed and not passed) else ""
        return AdAuditCheck(
            key=key,
            emoji=meta.emoji if meta else "•",
            label=meta.t_label(lang) if meta else key,
            passed=passed,
            score=coerce_int(score, 0, 0, CRITERION_MAX),
            severity=severity,
            detail=detail,
            fix=fix,
            skipped=skipped,
            weight=AD_AUDIT_WEIGHTS.get(key, 0),
            metrics=metrics or {},
        )

    @staticmethod
    def _claims_detail(claims: Sequence[ClaimFinding], lang: str) -> str:
        if not claims:
            return ""
        kinds = sorted({item.label_for(lang) for item in claims})
        return ", ".join(kinds)

    # -- hisobot ------------------------------------------------------------
    def render_report(self, audit: AdAuditResult, lang: Any = DEFAULT_LANG) -> str:
        """Audit hisobotini Telegram HTML xabariga aylantirish (sanitize + chunk)."""
        code = normalize_lang(lang)
        header = {
            "uz": "🛡 Reklama auditi",
            "ru": "🛡 Аудит рекламы",
            "en": "🛡 Ad audit",
        }[code]
        lines = [f"<b>{header}</b>",
                 f"Ball: <b>{audit.score}/100</b> ({audit.grade})"]
        for check in audit.checks:
            mark = "⏭" if check.skipped else ("✅" if check.passed else "⚠️")
            line = f"{mark} {check.emoji} {check.label}: {check.score}/10"
            if check.detail:
                line += f" — {check.detail}"
            lines.append(line)
        if audit.claims:
            lines.append("")
            lines.append({"uz": "<b>Asossiz da'volar:</b>",
                          "ru": "<b>Необоснованные заявления:</b>",
                          "en": "<b>Unsupported claims:</b>"}[code])
            for item in audit.claims[:8]:
                lines.append(f"• {item.label_for(code)}: «{item.snippet}»")
        if audit.requires_admin_approval:
            lines.append("")
            lines.append({
                "uz": "⛔ Nashr uchun ADMIN tasdig'i talab qilinadi.",
                "ru": "⛔ Для публикации требуется подтверждение АДМИНА.",
                "en": "⛔ Publishing requires ADMIN approval.",
            }[code])
        else:
            lines.append("")
            lines.append({
                "uz": "✅ Nashr uchun yaroqli.",
                "ru": "✅ Готово к публикации.",
                "en": "✅ Ready to publish.",
            }[code])
        return sanitize_html("\n".join(lines), min(CHUNK_SAFE_LIMIT,
                                                  TELEGRAM_TEXT_LIMIT))


#: Modul darajasidagi standart namuna.
default_auditor = AdAuditService()


def audit_ad(post: Any, *, lang: Any = DEFAULT_LANG, **kwargs: Any) -> AdAuditResult:
    """Yordamchi: ``AdAuditService().audit(...)``."""
    return default_auditor.audit(post, lang=lang, **kwargs)


def render_audit_report(audit: AdAuditResult, lang: Any = DEFAULT_LANG) -> str:
    return default_auditor.render_report(audit, lang=lang)


# ===========================================================================
# 6) NASHR DARVOZASI (FAIL-CLOSED ADMIN TASDIG'I)
# ===========================================================================
_APPROVAL_MESSAGES = {
    "blocked": {
        "uz": "⛔ Reklama auditi muammo topdi — nashr ADMIN tasdig'isiz amalga oshirilmaydi.",
        "ru": "⛔ Аудит нашёл проблемы — публикация без подтверждения АДМИНА невозможна.",
        "en": "⛔ The audit found issues — publishing is blocked without ADMIN approval.",
    },
    "approved": {
        "uz": "✅ Admin tasdiqladi — reklama nashr uchun ruxsat etildi.",
        "ru": "✅ Админ подтвердил — реклама разрешена к публикации.",
        "en": "✅ Admin approved — the ad is cleared for publishing.",
    },
    "clean": {
        "uz": "✅ Audit toza — reklama nashrga tayyor.",
        "ru": "✅ Аудит чист — реклама готова к публикации.",
        "en": "✅ Audit is clean — the ad is ready to publish.",
    },
}


def evaluate_publish(audit: AdAuditResult | None, *, admin_approved: bool = False,
                     approved_by: int | None = None,
                     lang: Any = DEFAULT_LANG) -> AdPublishDecision:
    """Audit natijasidan nashr qarorini chiqaradi (FAIL-CLOSED).

    Qoidalar:
      * audit yo'q / ``ok=False`` → nashr TAQIQLANADI (hatto admin tasdig'i
        bo'lsa ham: bo'sh/buzuq post chiqmaydi);
      * ``requires_admin_approval=True`` va admin tasdig'i YO'Q → TAQIQLANADI;
      * ``requires_admin_approval=True`` + admin tasdig'i BOR → ruxsat
        (``admin_approved=True``, ``approved_by`` qayd etiladi);
      * muammo yo'q → ruxsat.
    """
    code = normalize_lang(lang)
    if audit is None:
        return AdPublishDecision(
            allowed=False, requires_admin_approval=True,
            admin_approved=bool(admin_approved), approved_by=approved_by,
            reason_codes=["NO_AUDIT"], blockers=["Audit natijasi yo'q"],
            message=lang_text(_APPROVAL_MESSAGES["blocked"], code, ""),
        )
    if not audit.ok:
        return AdPublishDecision(
            allowed=False, requires_admin_approval=True,
            admin_approved=bool(admin_approved), approved_by=approved_by,
            reason_codes=list(audit.reason_codes) + ["AUDIT_FAILED"],
            blockers=list(audit.blockers) or ["Audit bajarilmadi"],
            message=lang_text(_APPROVAL_MESSAGES["blocked"], code, ""),
            score=audit.score,
        )
    if not audit.requires_admin_approval:
        return AdPublishDecision(
            allowed=True, requires_admin_approval=False,
            admin_approved=bool(admin_approved), approved_by=approved_by,
            reason_codes=list(audit.reason_codes), blockers=[],
            message=lang_text(_APPROVAL_MESSAGES["clean"], code, ""),
            score=audit.score,
        )
    if admin_approved:
        return AdPublishDecision(
            allowed=True, requires_admin_approval=True, admin_approved=True,
            approved_by=approved_by, reason_codes=list(audit.reason_codes),
            blockers=list(audit.blockers),
            message=lang_text(_APPROVAL_MESSAGES["approved"], code, ""),
            score=audit.score,
        )
    return AdPublishDecision(
        allowed=False, requires_admin_approval=True, admin_approved=False,
        approved_by=None, reason_codes=list(audit.reason_codes),
        blockers=list(audit.blockers),
        message=lang_text(_APPROVAL_MESSAGES["blocked"], code, ""),
        score=audit.score,
    )


def gate_with_workflow(workflow: Any, post_id: Any, actor_id: int | None,
                       audit: AdAuditResult | None, *,
                       lang: Any = DEFAULT_LANG) -> dict:
    """Audit qarorini mavjud ``ApprovalWorkflow`` bilan bog'laydi.

    Muammoli reklama ``services.channels.team.ApprovalWorkflow`` ga
    ``pending_approval`` holatiga TUSHIRILADI — bu state machine hech bir
    bosqichni o'tkazib yubormaydi, shuning uchun admin ``approve()``
    qilgunicha postni ``schedule()``/``publish()`` qilib BO'LMAYDI.

    Audit toza bo'lsa hech narsa majburan yuborilmaydi: qaror chaqiruvchiga
    qaytariladi va u o'z oqimini davom ettiradi.

    Qaytadi: ``{"allowed", "status", "requires_admin_approval", "submitted",
    "reason_codes", "blockers", "message", "score"}``.
    """
    code = normalize_lang(lang)
    decision = evaluate_publish(audit, lang=code)
    result: dict[str, Any] = {
        "allowed": decision.allowed,
        "status": None,
        "requires_admin_approval": decision.requires_admin_approval,
        "submitted": False,
        "reason_codes": list(decision.reason_codes),
        "blockers": list(decision.blockers),
        "message": decision.message,
        "score": decision.score,
    }
    if not decision.requires_admin_approval:
        post = None
        if hasattr(workflow, "get"):
            try:
                post = workflow.get(post_id)
            except Exception:  # noqa: BLE001 — fail-soft
                post = None
        result["status"] = post.get("status") if isinstance(post, dict) else None
        return result

    submitted = False
    if hasattr(workflow, "submit_for_approval"):
        try:
            submitted = bool(workflow.submit_for_approval(post_id, actor_id))
        except Exception as exc:  # noqa: BLE001 — xato nashrni OCHMAYDI
            logger.warning("gate_with_workflow submit xatosi: %s", exc)
            submitted = False
    result["submitted"] = submitted
    result["allowed"] = False
    try:
        post = workflow.get(post_id) if hasattr(workflow, "get") else None
        result["status"] = post.get("status") if isinstance(post, dict) else None
    except Exception:  # noqa: BLE001
        result["status"] = "pending_approval" if submitted else None
    return result


__all__ = [
    "AD_AUDIT_CHECK_KEYS",
    "AD_AUDIT_CRITERIA",
    "AD_AUDIT_WEIGHTS",
    "AUDIT_PASS_SCORE",
    "CLAIM_ABSOLUTE",
    "CLAIM_CERTIFICATE",
    "CLAIM_DURATION",
    "CLAIM_GUARANTEE",
    "CLAIM_KINDS",
    "CLAIM_KIND_LABELS",
    "CLAIM_KIND_SEVERITY",
    "CLAIM_PRICE",
    "CLAIM_RATING",
    "CLAIM_STATISTIC",
    "CLAIMS_CHECK",
    "ClaimFinding",
    "CTA_CHECK",
    "CRITERION_MAX",
    "CRITERION_MIN",
    "DNA_CHECK",
    "DNA_FIT_MIN",
    "FORMAT_LENGTH_RANGE",
    "OVERALL_MAX",
    "READABILITY_CHECK",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "AdAuditCheck",
    "AdAuditCriterion",
    "AdAuditResult",
    "AdAuditService",
    "AdPublishDecision",
    "audit_ad",
    "claim_corpus",
    "default_auditor",
    "dna_is_sufficient",
    "evaluate_publish",
    "extract_numbers",
    "gate_with_workflow",
    "normalize_claim_text",
    "normalize_dna_profile",
    "normalize_number",
    "render_audit_report",
    "scan_unsupported_claims",
    "score_cta",
    "score_dna_fit",
    "score_readability",
    "strip_unsupported_claims",
    "worst_severity",
]
