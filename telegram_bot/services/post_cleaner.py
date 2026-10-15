"""🧹 POST AUTO-CLEANER — ENTITY-SAFE tozalash dvigateli (Custom Signature).

Nima qiladi
-----------
Tashqi manbalardan kelgan post matnidan:

  1. **begona ``@username`` eslatmalarini** (mention),
  2. **begona Telegram havolalarini** (``t.me/...``, ``telegram.me/...``),
  3. **footer (pastki) reklama/imzo qatorlarini** ("Reklama:", "Obuna bo'ling",
     "Источник:", "Read more", "© ..." va h.k.)

olib tashlaydi va (agar foydalanuvchi saqlagan bo'lsa) o'rniga **o'zining
havolasi/imzosi**ni qo'yadi.

Nega alohida modul (va nega regex'ning o'zi YETMAYDI)
----------------------------------------------------
Telegram posti — bu shunchaki matn EMAS: matn + **formatlash daraxti**
(bold/italic/havola/kod/spoiler). Oddiy ``re.sub`` teg yoki entity
chegaralarini buzadi: ``<a href="...">t.me/x</a>`` ichidagi havolani o'chirsangiz
BO'SH havola qoladi, entity offset'lari esa BUTUNLAY siljiydi — natijada bold
boshqa so'zga tushadi yoki Telegram ``MESSAGE_ENTITIES_INVALID`` qaytaradi.

Shu sababli dvigatel **uch qatlamli**:

  * **yadro** — matn + ``Span`` (formatlash oralig'i) modeli ustida ishlaydi.
    O'chiriladigan joylar avval HISOBLANADI, so'ng har bir o'zgartirish
    **prefix-sum** xaritasi bilan birga qaytariladi va barcha span offset'lari
    o'sha xarita orqali qayta hisoblanadi. Muhim qoida: matn ustida hech
    qanday "keyingi" regex tuzatishi prefix'siz bajarilmaydi — har bir
    bosqich (o'chirish → bo'shliq kollapsi) O'Z xaritasini qaytaradi va
    span'lar ketma-ket qayta xaritalanadi. Shu sababli offset'lar hech qachon
    siljimaydi, "yetim" (matnsiz) formatlash qolmaydi;
  * **adapterlar** — HTML / Telegram ``MessageEntity`` / Markdown ↔ yadro
    modeli. Har biri o'z formatining qoidalarini biladi (``pre`` ichidagi til,
    ``blockquote expandable``, ``custom_emoji_id``, UTF-16 offset'lari);
  * **siyosat** — nima o'chirilishini hal qiluvchi yengil regex'lar va
    foydalanuvchi sozlamalari.

Xavfsizlik / mustahkamlik
-------------------------
  * ``code`` / ``pre`` ichidagi matn **HECH QACHON** tozalanmaydi — u yerda
    ``@kanal`` va ``t.me/...`` LITERAL ma'noda (kod namunasi) bo'lishi mumkin;
  * foydalanuvchining **o'z kanallari** (``own_usernames``) saqlanadi;
  * imzo URL bo'lsa — ``utils.security.validate_button_url`` orqali
    tekshiriladi (SSRF/phishing/``javascript:`` rad etiladi);
  * tozalash natijasi BO'SH bo'lib qolsa — asl matn qaytariladi
    (fail-safe: post hech qachon "yo'qolib qolmaydi");
  * yadroda hech qanday tarmoq/DB chaqiruvi yo'q — sof funksiya.

Ko'p davlatlilik
----------------
Reklama kalit so'zlari **uch tilda** (uz/ru/en) berilgan va ro'yxat
KENGAYTIRUVCHAN: yangi til = yangi kalit so'zlar, kod o'zgarmaydi. Hech qanday
mamlakat/mintaqa cheklovi yo'q — tozalash faqat MATN naqshiga qaraydi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from html import escape
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

__all__ = [
    "Span",
    "Segment",
    "CleanerConfig",
    "CleanResult",
    "DEFAULT_CONFIG",
    "clean_segment",
    "clean_plain",
    "clean_html",
    "clean_markdown",
    "normalize_signature",
    "signature_is_empty",
    "load_cleaner_config",
    "own_channel_usernames",
    "DEMO_SOURCE_HTML",
    "MAX_SIGNATURE_LEN",
    "MAX_SIGNATURE_LINES",
    "SIGNATURE_MAX_LINES",
    "SIGNATURE_MAX_WORDS",
    "SIGNATURE_MAX_CHARS",
    "TEXT_LIMIT",
    "CAPTION_LIMIT",
    "QuickCleanResult",
    "strip_tail_junk",
    "signature_problems",
    "link_to_url",
    "find_link_url",
    "signature_from_message",
    "wrap_signature_link",
    "quick_clean",
]

# Imzo normalizatsiyasi BOG'LIQLIKSIZ modulda yashaydi (``utils`` namespace
# package) — ``repositories.users_repository`` ham uni import qiladi va
# ``repositories`` → ``services`` sikli yuzaga kelmaydi. Bu yerda qayta
# eksport qilinadi, shu sababli ``from services.post_cleaner import
# normalize_signature`` ham ishlayveradi.
from utils.post_signature import (  # noqa: E402
    MAX_SIGNATURE_LEN,
    MAX_SIGNATURE_LINES,
    normalize_signature,
    signature_is_empty,
)

# ============================================================
# 1) YADRO MODEL — matn + formatlash oralig'lari (span)
# ============================================================
BOLD = "bold"
ITALIC = "italic"
UNDERLINE = "underline"
STRIKE = "strike"
SPOILER = "spoiler"
CODE = "code"
PRE = "pre"
LINK = "link"
QUOTE = "blockquote"
CUSTOM_EMOJI = "custom_emoji"

#: ``code`` / ``pre`` — LITERAL matn: bu oralig'ichda tozalash ISHLAMAYDI.
LITERAL_KINDS = frozenset({CODE, PRE})


@dataclass(frozen=True)
class Span:
    """Matnning ``[start, end)`` oraliqni qamrab oluvchi formatlash birligi.

    Offset'lar yadro ichida **Python (kod nuqtasi) indekslarida** — Telegram
    entity'lariga o'tishda adapter UTF-16 ga alohida konvertatsiya qiladi.
    """

    kind: str
    start: int
    end: int
    url: str = ""
    language: str = ""
    expandable: bool = False
    custom_emoji_id: str = ""

    def shifted(self, start: int, end: int) -> "Span":
        return replace(self, start=start, end=end)


@dataclass(frozen=True)
class Segment:
    """Yadro modeli: toza matn + ustma-ust tushmaydigan formatlash daraxti."""

    text: str
    spans: tuple = ()

    def literal_mask(self) -> list:
        """``code``/``pre`` ostidagi indekslar uchun ``True`` niqob."""
        mask = [False] * len(self.text)
        for span in self.spans:
            if span.kind in LITERAL_KINDS:
                for index in range(max(0, span.start), min(len(mask), span.end)):
                    mask[index] = True
        return mask


@dataclass(frozen=True)
class CleanResult:
    """Tozalash natijasi + hisobot (UI'dagi «🧪 Namuna» ekrani uchun)."""

    text: str
    spans: tuple = ()
    entities: tuple = ()
    removed_mentions: int = 0
    removed_links: int = 0
    removed_promo_lines: int = 0
    signature_added: bool = False
    changed: bool = False

    def as_dict(self) -> dict:
        return {
            "removed_mentions": self.removed_mentions,
            "removed_links": self.removed_links,
            "removed_promo_lines": self.removed_promo_lines,
            "signature_added": self.signature_added,
            "changed": self.changed,
        }


# ============================================================
# 2) SIYOSAT — nima o'chiriladi
# ============================================================
#: ``@username`` — Telegram username qoidalari (5..32, harf bilan boshlanadi).
#: ``(?<![\w@])`` — email (``a@b.com``) va ``@@`` ichiga tushmaslik uchun.
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})(?![\w])")

#: Begona Telegram havolalari (ixtiyoriy ``https://`` va ``www.`` bilan).
TELEGRAM_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:t\.me|telegram\.me|telegram\.dog)/[^\s<>\"'()\[\]]+",
    re.IGNORECASE,
)

# --- Footer reklama/imzo qatorlari (KO'P DAVLATLI: uz / ru / en) -----------
#: Qator shu naqshdan boshlansa — kuchli reklama belgisi.
STRONG_PROMO_RE = re.compile(
    r"^\s*(?:[^\w]{0,8})?"
    r"(?:reklama|homiy|sponsor(?:lik|ed)?|advertisement|promo)"
    r"\s*[:\-–—|]\s*",
    re.IGNORECASE,
)

#: Reklama/atributsiya KALIT SO'ZLARI — uch tilda. Yangi til qo'shish uchun
#: shu ro'yxatni kengaytirish kifoya (kod o'zgarmaydi).
PROMO_KEYWORDS: tuple = (
    # 🇺🇿 o'zbek
    "obuna bo'ling", "obuna bo‘ling", "obuna boling", "kanalimizga",
    "bizning kanal", "bizni kuzating", "manba", "batafsil", "davomi",
    "to'liq versiya", "reklama", "homiy",
    # 🇷🇺 rus
    "подписывайтесь", "подпишись", "подписаться", "наш канал",
    "наш телеграм", "читай нас", "источник", "читать далее",
    "читать полностью", "продолжение", "реклама", "спонсор",
    # 🇬🇧 ingliz
    "subscribe", "our channel", "follow us", "join our", "read more",
    "continue reading", "full article", "source", "advertisement",
    "sponsored", "brought to you by",
)

#: Qator uzunligi chegarasi — uzun ma'noLI matn reklama deb o'chirilmaydi.
PROMO_LINE_MAX_LEN = 160
#: Atributsiya qatori (``Manba: https://...``) chegarasi.
SOURCE_LINE_MAX_LEN = 120

#: Qator BUTUNLAY atributsiya bo'lsa (``Manba: X`` / ``Source: X`` / ``via X``).
SOURCE_LINE_RE = re.compile(
    r"^\s*(?:[^\w]{0,8})?"
    r"(?:manba|manbasi|источник|source|via|оригинал|original)"
    r"\s*[:\-–—|]\s*\S.*$",
    re.IGNORECASE,
)

#: Mualliflik/huquq qatori (``© 2026 Kun.uz``).
COPYRIGHT_RE = re.compile(r"^\s*(?:[^\w]{0,4})?[©℗®]\s*\S.*$")

#: Faqat havola/mention dan iborat qator (imzo qatori).
ONLY_LINK_RE = re.compile(
    r"^\s*(?:[^\w]{0,8})?"
    r"(?:(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/\S+"
    r"|@[A-Za-z][A-Za-z0-9_]{3,31})"
    r"\s*$"
)

# ============================================================
# 3) FOYDALANUVCHI SOZLAMALARI
# ============================================================


@dataclass(frozen=True)
class CleanerConfig:
    """🧹 Auto-cleaner sozlamalari (sof ma'lumot — DB'ga bog'liq emas).

    ``enabled=False`` bo'lsa dvigatel matnga UMUMAN tegmaydi (opt-in).
    """

    enabled: bool = False
    strip_mentions: bool = True
    strip_links: bool = True
    strip_promo: bool = True
    signature: str = ""
    #: Imzo qayerga qo'yiladi: ``"end"`` (standart) yoki ``"start"``.
    signature_position: str = "end"
    #: Foydalanuvchining O'Z kanallari (@siz, kichik harfda) — saqlanadi.
    own_usernames: frozenset = frozenset()

    def with_signature(self, signature: str) -> "CleanerConfig":
        return replace(self, signature=normalize_signature(signature))


DEFAULT_CONFIG = CleanerConfig()

# ============================================================
# 4) YADRO — prefix-sum xaritasi (offset'lar siljimaydi)
# ============================================================
def _filter_chars(text: str, keep) -> tuple:
    """``keep`` niqobi bo'yicha matnni qisqartiradi.

    Qaytadi: ``(yangi_matn, prefix)`` — ``prefix[i]`` = ``[0, i)`` dagi
    SAQLANGAN belgilar soni. Shu xarita orqali har qanday offset aniq
    qayta hisoblanadi (bu modulning butun entity-xavfsizligi shu yerda).
    """
    prefix = [0] * (len(text) + 1)
    running = 0
    out = []
    for index, char in enumerate(text):
        prefix[index] = running
        if keep[index]:
            out.append(char)
            running += 1
    prefix[len(text)] = running
    return "".join(out), prefix


def _remap_spans(spans, prefix) -> tuple:
    """Span'larni ``prefix`` xaritasi orqali qayta hisoblaydi.

    Har bir span ``[start, end)`` → ``[prefix[start], prefix[end])``.
    Natija bo'sh bo'lsa (butunlay o'chirilgan) span TUSHIRIB QOLDIRILADI;
    qisman o'chirilgani esa tabiiy ravishda QIRQILADI — shu sababli hech
    qachon "matnsiz" (yetim) formatlash qolmaydi.
    """
    last = len(prefix) - 1
    out = []
    for span in spans:
        start = max(0, min(span.start, last))
        end = max(0, min(span.end, last))
        new_start, new_end = prefix[start], prefix[end]
        if new_end > new_start:
            out.append(span.shifted(new_start, new_end))
    return tuple(sorted(out, key=lambda s: (s.start, -s.end, s.kind)))


def _merge_intervals(spans) -> list:
    """O'chirish oraliqlarini tartiblaydi va ustma-ust tushganlarini birlashtiradi."""
    merged: list = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _absorb_spaces(text: str, start: int, end: int) -> tuple:
    """O'chirilayotgan bo'lak atrofidagi ORTIQCHA bo'shliqni ham oladi.

    ``"Salom @kanal dunyo"`` → ``"Salom dunyo"`` (ikki bo'shliq qolmaydi).
    """
    left = start
    while left > 0 and text[left - 1] in " \t":
        left -= 1
    right = end
    while right < len(text) and text[right] in " \t":
        right += 1
    # Ikkala tomonni bir vaqtda yutmaslik: chapda ham, o'ngda ham bo'shliq
    # bo'lsa — faqat bittasi olinadi (so'zlar orasi bitta bo'shliq qoladi).
    if left < start and right > end:
        right = end
    return left, right


def _collapse_whitespace(text: str) -> tuple:
    """Ortiqcha bo'shliq/bo'sh qatorlarni oladi — **prefix bilan birga**.

    Prefix'siz ``re.sub`` qilish offset'larni siljitib yuborardi; shu sababli
    bu yerda ham niqob + xarita quriladi (``_filter_chars``).
    """
    length = len(text)
    keep = [True] * length

    # 1) Ketma-ket bo'shliq/tablardan bittasi qoladi.
    index = 0
    while index < length:
        if text[index] in " \t":
            run = index
            while run < length and text[run] in " \t":
                run += 1
            for extra in range(index + 1, run):
                keep[extra] = False
            # Bo'shliq to'g'ridan-to'g'ri "\n" oldida tursa — butunlay o'chadi.
            if run < length and text[run] == "\n":
                keep[index] = False
            index = run
        else:
            index += 1

    # 2) 3+ bo'sh qator → 2 ta.
    index = 0
    while index < length:
        if text[index] == "\n":
            run = index
            while run < length and text[run] == "\n":
                run += 1
            if run - index > 2:
                for extra in range(index + 2, run):
                    keep[extra] = False
            index = run
        else:
            index += 1

    # 3) Boshidagi/oxiridagi bo'shliq.
    left = 0
    while left < length and (not keep[left] or text[left].isspace()):
        left += 1
    right = length
    while right > left and (not keep[right - 1] or text[right - 1].isspace()):
        right -= 1
    for index in range(0, left):
        keep[index] = False
    for index in range(right, length):
        keep[index] = False

    return _filter_chars(text, keep)


def _protected(index: int, mask) -> bool:
    """Indeks ``code``/``pre`` ichidami? (LITERAL — tozalanmaydi)."""
    return index < len(mask) and mask[index]


def _find_removals(segment: Segment, config: CleanerConfig) -> tuple:
    """O'chiriladigan ``(start, end)`` oraliqlari + hisoblagichlar.

    Qoidalar:
      1. ``code``/``pre`` ichidagi hech narsa tegilmaydi (LITERAL);
      2. foydalanuvchining o'z kanali (@username yoki t.me/own) saqlanadi;
      3. mention/havola o'chirilsa — atrofidagi ortiqcha bo'shliq ham;
      4. footer reklama qatorlari butunlay (qator oxirigacha) o'chiriladi.
    """
    text = segment.text
    mask = segment.literal_mask()
    own = {str(u).strip().lower().lstrip("@") for u in config.own_usernames if u}
    removals: list = []
    mentions = links = 0

    if config.strip_mentions:
        for match in MENTION_RE.finditer(text):
            if _protected(match.start(), mask):
                continue
            if match.group(1).lower() in own:
                continue
            mentions += 1
            removals.append(_absorb_spaces(text, match.start(), match.end()))

    if config.strip_links:
        for match in TELEGRAM_LINK_RE.finditer(text):
            if _protected(match.start(), mask):
                continue
            tail = match.group(0).rstrip("/").split("/")[-1].lower()
            if tail.lstrip("@") in own:
                continue
            links += 1
            removals.append(_absorb_spaces(text, match.start(), match.end()))

    promo = 0
    if config.strip_promo:
        promo_spans, promo = _find_promo_lines(text, mask, own)
        removals.extend(promo_spans)

    return _merge_intervals(removals), mentions, links, promo


#: Kalit-soz qoidasi uchun zarur BO'LMAGAN (bo'sh) qatorlar soni — qisqa post
#: (1–2 qator) "footer" deb hisoblanmaydi, aks holda butun post o'chib ketadi.
_MIN_LINES_FOR_FOOTER_RULE = 3
#: "Pointer-shell" qatorida qolishi mumkin bo'lgan eng ko'p so'z soni.
_SHELL_MAX_WORDS = 5

#: Atributsiya MARKERLARI (uz/ru/en) — pointer-shell qoidasi faqat shu
#: so'zlardan biri qatorda qolgandagina ishlaydi. Shu sababli oddiy kontent
#: qatori ("Salom @kanal dunyo") hech qachon reklama deb o'chirilmaydi.
ATTRIBUTION_MARKERS: tuple = (
    "orqali", "tarqatildi", "manba", "manbasi", "e'lon", "joylandi",
    "joylashtirildi", "olindi", "kanalimiz",
    "via", "channel", "source", "published", "posted", "shared", "credit",
    "через", "канал", "источник", "опубликовано", "размещено", "поделился",
)


def _find_promo_lines(text: str, mask, own=frozenset()) -> tuple:
    """Reklama/imzo QATORLARINI topadi.

    Ikki darajali qoida (ikkalasi ham KO'P DAVLATLI — uz/ru/en kalit so'zlar):

    **A. Kuchli naqshlar** — qatorning o'zi shundan iborat, shu sababli
    matndagi o'rnidan QAT'I NAZAR o'chiriladi: ``Reklama: ...``,
    ``Manba: ...`` / ``Source: ...`` / ``via ...``, ``© ...``, yoki butunlay
    bitta havola/@username dan iborat imzo qatori.

    **B. Zaif (footer) naqshlar** — faqat matnning OXIRGI ~25% (bo'sh
    bo'lmagan) qatorida va kamida ``_MIN_LINES_FOR_FOOTER_RULE`` ta qator
    bo'lsagina: kalit so'z ("obuna bo'ling", "источник", "read more" ...)
    + qisqa uzunlik. Shu cheklov tufayli 1–2 qatorli post hech qachon
    "footer" deb butunlay o'chirilmaydi.

    **C. Pointer-shell** — qator deyarli faqat begona havola/mention dan
    iborat bo'lsa (ular o'chirilgach atributsiya marker'i — "orqali",
    "источник", "via" — va ≤5 ta so'z qolsa), qator butunlay o'chiriladi.
    Bu ``"📢 @source_news orqali tarqatildi"`` kabi atributsiya qoldig'ini
    yo'q qiladi (aks holda "📢 orqali tarqatildi" qolib ketardi), lekin
    ``"Salom @x dunyo"`` kabi ODDIY kontentni saqlaydi (marker yo'q).

    Qaytadi: ``((start, end) ..., count)`` — ``end`` qator oxiridagi ``\\n``
    ni ham oladi, shunda bo'sh qatorlar qolmaydi.
    """
    if not text.strip():
        return (), 0

    offsets: list = []
    position = 0
    for line in text.split("\n"):
        offsets.append((position, position + len(line)))
        position += len(line) + 1

    # Footer mintaqasi BO'SH BO'LMAGAN qatorlar bo'yicha hisoblanadi.
    filled = [i for i, (start, end) in enumerate(offsets) if text[start:end].strip()]
    if len(filled) >= _MIN_LINES_FOR_FOOTER_RULE:
        tail = max(1, len(filled) // 4)
        footer_ids = set(filled[len(filled) - tail:])
    else:
        footer_ids = set()

    found: list = []
    for index, (start, end) in enumerate(offsets):
        stripped = text[start:end].strip()
        if not stripped or len(stripped) > PROMO_LINE_MAX_LEN:
            continue
        if _protected(start, mask):
            continue

        lowered = stripped.lower()
        is_promo = False
        if STRONG_PROMO_RE.match(stripped) or COPYRIGHT_RE.match(stripped):
            is_promo = True
        elif SOURCE_LINE_RE.match(stripped) and len(stripped) <= SOURCE_LINE_MAX_LEN:
            is_promo = True
        elif ONLY_LINK_RE.match(stripped):
            is_promo = True
        elif _is_pointer_shell(stripped, own):
            is_promo = True
        elif index in footer_ids and any(kw in lowered for kw in PROMO_KEYWORDS):
            # Uzun ma'noli matnni saqlash: havola/mention bo'lmasa va so'zlar
            # soni ko'p bo'lsa — bu reklama emas, kontent.
            has_pointer = bool(
                TELEGRAM_LINK_RE.search(stripped)
                or MENTION_RE.search(stripped)
                or "http" in lowered
            )
            if has_pointer or len(stripped.split()) <= 8:
                is_promo = True

        if not is_promo:
            continue
        line_end = end
        if line_end < len(text) and text[line_end] == "\n":
            line_end += 1
        found.append((start, line_end))

    return tuple(found), len(found)


def _is_pointer_shell(line: str, own=frozenset()) -> bool:
    """Qator deyarli faqat BEGONA havola/mention + atributsiya so'zlarimi?

    Ikki shart BIRGA bajarilishi shart:
      1. qatorda kamida bitta BEGONA pointer bor (o'z kanali hisoblanmaydi);
      2. pointer'lar o'chirilgach qolgan so'zlar orasida atributsiya
         MARKER'I bor va ular soni ``_SHELL_MAX_WORDS`` dan oshmaydi.

    Shu sababli ``"📢 @source_news orqali tarqatildi"`` o'chadi (qoldiq:
    "orqali tarqatildi" → marker bor, 2 so'z), lekin ``"Salom @x dunyo"``
    SAQLANADI (qoldiqda atributsiya marker'i yo'q).
    """
    had_foreign = False
    for match in TELEGRAM_LINK_RE.finditer(line):
        tail = match.group(0).rstrip("/").split("/")[-1].lower().lstrip("@")
        if tail not in own:
            had_foreign = True
    for match in MENTION_RE.finditer(line):
        if match.group(1).lower() not in own:
            had_foreign = True
    if not had_foreign:
        return False

    without = TELEGRAM_LINK_RE.sub(" ", MENTION_RE.sub(" ", line))
    words = [word for word in re.sub(r"[^\w\s]", " ", without).split() if word]
    if not words or len(words) > _SHELL_MAX_WORDS:
        return False
    lowered = " ".join(words).lower()
    return any(marker in lowered for marker in ATTRIBUTION_MARKERS)


def _compose_signature(text: str, config: CleanerConfig) -> tuple:
    """Imzoni qo'shadi → ``(matn, qo'shildimi)``. Idempotent."""
    signature = normalize_signature(config.signature)
    if not signature:
        return text, False
    body = text.strip()
    if signature in body:
        return text, False
    if config.signature_position == "start":
        return (f"{signature}\n\n{body}" if body else signature), True
    return (f"{body}\n\n{signature}" if body else signature), True


def clean_segment(segment: Segment, config: CleanerConfig = DEFAULT_CONFIG) -> CleanResult:
    """YADRO: ``Segment`` ni tozalaydi (formatlash daraxtini saqlab).

    Ikkita bosqich, har biri O'Z prefix xaritasi bilan:
    (1) o'chirishlar, (2) bo'shliq kollapsi. Span'lar ketma-ket qayta
    xaritalanadi — shu sababli offset'lar har doim matn bilan sinxron.
    """
    original = segment.text
    if not config.enabled or not original.strip():
        return CleanResult(text=original, spans=segment.spans, changed=False)

    removals, mentions, links, promo = _find_removals(segment, config)

    if removals:
        keep = [True] * len(original)
        for start, end in removals:
            for index in range(max(0, start), min(len(original), end)):
                keep[index] = False
        text, prefix = _filter_chars(original, keep)
        spans = _remap_spans(segment.spans, prefix)
    else:
        text, spans = original, segment.spans

    text, prefix = _collapse_whitespace(text)
    spans = _remap_spans(spans, prefix)

    # FAIL-SAFE: tozalash matnni butunlay yeb qo'ysa — asl matn qaytariladi.
    if not text.strip():
        logger.info("post_cleaner: tozalash natijasi bo'sh — asl matn saqlandi")
        return CleanResult(text=original, spans=segment.spans, changed=False)

    text, added = _compose_signature(text, config)
    return CleanResult(
        text=text,
        spans=spans,
        removed_mentions=mentions,
        removed_links=links,
        removed_promo_lines=promo,
        signature_added=added,
        changed=(text != original),
    )


# ============================================================
# 5) ADAPTER A — ODDIY MATN (+ Telegram MessageEntity)
# ============================================================
#: Telegram ``MessageEntity.type`` → yadro ``Span.kind``.
_ENTITY_TO_KIND = {
    "bold": BOLD,
    "italic": ITALIC,
    "underline": UNDERLINE,
    "strikethrough": STRIKE,
    "spoiler": SPOILER,
    "code": CODE,
    "pre": PRE,
    "text_link": LINK,
    "blockquote": QUOTE,
    "custom_emoji": CUSTOM_EMOJI,
}
_KIND_TO_ENTITY = {
    BOLD: "bold",
    ITALIC: "italic",
    UNDERLINE: "underline",
    STRIKE: "strikethrough",
    SPOILER: "spoiler",
    CODE: "code",
    PRE: "pre",
    LINK: "text_link",
    QUOTE: "blockquote",
    CUSTOM_EMOJI: "custom_emoji",
}


def _entity_field(entity, name, default=None):
    """PTB obyekti, ``dict`` yoki ``namedtuple`` — uchalasidan ham o'qiydi."""
    if isinstance(entity, dict):
        return entity.get(name, default)
    return getattr(entity, name, default)


def _utf16_offsets(text: str) -> list:
    """Python indeksi → UTF-16 offset xaritasi (``len(text)+1`` uzunlikda)."""
    out = [0]
    total = 0
    for char in text:
        total += 2 if ord(char) > 0xFFFF else 1
        out.append(total)
    return out


def _py_index_from_utf16(text: str, utf16_offset: int) -> int:
    """UTF-16 offset → Python indeksi (chegaradan oshsa qirqiladi)."""
    total = 0
    for index, char in enumerate(text):
        if total >= utf16_offset:
            return index
        total += 2 if ord(char) > 0xFFFF else 1
    return len(text)


def entities_to_spans(text: str, entities) -> tuple:
    """Telegram ``MessageEntity`` ro'yxati → yadro ``Span`` lari.

    Entity offset'lari UTF-16 da — Python indeksiga aylantiriladi
    (emoji'lar 2 birlik, shu sababli konvertatsiya MAJBURIY).
    """
    spans = []
    for entity in entities or ():
        kind = _ENTITY_TO_KIND.get(str(_entity_field(entity, "type", "")))
        if not kind:
            continue  # noma'lum tur (url/hashtag/mention) — formatlash emas
        offset = int(_entity_field(entity, "offset", 0) or 0)
        length = int(_entity_field(entity, "length", 0) or 0)
        if length <= 0:
            continue
        start = _py_index_from_utf16(text, offset)
        end = _py_index_from_utf16(text, offset + length)
        if end <= start:
            continue
        spans.append(
            Span(
                kind=kind,
                start=start,
                end=end,
                url=str(_entity_field(entity, "url", "") or ""),
                language=str(_entity_field(entity, "language", "") or ""),
                custom_emoji_id=str(_entity_field(entity, "custom_emoji_id", "") or ""),
            )
        )
    return tuple(sorted(spans, key=lambda s: (s.start, -s.end, s.kind)))


def spans_to_entities(spans, text: str) -> tuple:
    """Yadro ``Span`` lari → Telegram ``MessageEntity`` (PTB obyektlari).

    PTB o'rnatilmagan muhitda (yengil testlar) oddiy ``dict`` qaytariladi —
    shartnoma bir xil: ``type`` / ``offset`` (UTF-16) / ``length`` (UTF-16).
    """
    offsets = _utf16_offsets(text)
    try:
        from telegram import MessageEntity
    except Exception:  # pragma: no cover - PTB yo'q muhit
        MessageEntity = None

    out = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        entity_type = _KIND_TO_ENTITY.get(span.kind)
        if not entity_type:
            continue
        start = max(0, min(span.start, len(text)))
        end = max(0, min(span.end, len(text)))
        if end <= start:
            continue
        payload = {
            "type": entity_type,
            "offset": offsets[start],
            "length": offsets[end] - offsets[start],
        }
        if span.kind == LINK and span.url:
            payload["url"] = span.url
        if span.kind == PRE and span.language:
            payload["language"] = span.language
        if span.kind == CUSTOM_EMOJI and span.custom_emoji_id:
            payload["custom_emoji_id"] = span.custom_emoji_id
        if MessageEntity is None:
            out.append(payload)
            continue
        if entity_type == "text_link" and not payload.get("url"):
            continue  # havolasiz text_link Telegram tomonidan rad etiladi
        out.append(MessageEntity(**payload))
    return tuple(out)


def clean_plain(text: str, entities=None, config: CleanerConfig = DEFAULT_CONFIG) -> CleanResult:
    """Oddiy matn + (ixtiyoriy) Telegram entity'lar → tozalangan natija.

    ``result.entities`` — Telegram'ga yuborishga TAYYOR, qayta hisoblangan
    offset'lar bilan (yoki PTB bo'lmasa bir xil shartnomadagi ``dict``).
    """
    raw = "" if text is None else str(text)
    segment = Segment(raw, entities_to_spans(raw, entities))
    result = clean_segment(segment, config)
    return replace(result, entities=spans_to_entities(result.spans, result.text))


# ============================================================
# 6) ADAPTER B — HTML (repo'dagi kanonik post formati)
# ============================================================
#: Kanonik HTML teg ↔ yadro kind (``telegram_sanitizer`` alias'lariga mos).
_TAG_TO_KIND = {
    "b": BOLD, "i": ITALIC, "u": UNDERLINE, "s": STRIKE,
    "tg-spoiler": SPOILER, "code": CODE, "pre": PRE, "a": LINK,
    "blockquote": QUOTE,
}
_KIND_TO_TAG = {
    BOLD: "b", ITALIC: "i", UNDERLINE: "u", STRIKE: "s",
    SPOILER: "tg-spoiler", CODE: "code", PRE: "pre", QUOTE: "blockquote",
}


class _HtmlToModel(HTMLParser):
    """Balanslangan HTML → ``(matn, span)`` modeli (stack asosida)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.CDATA_CONTENT_ELEMENTS = ()
        self.parts: list = []
        self.spans: list = []
        self.stack: list = []

    def _length(self) -> int:
        return sum(len(part) for part in self.parts)

    # -- matn ------------------------------------------------------------
    def handle_data(self, data):
        if data:
            self.parts.append(data)

    # -- teglar ----------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        kind = _TAG_TO_KIND.get(tag)
        if kind is None:
            return  # noma'lum teg — sanitize_html allaqachon matnga aylantirgan
        attributes = dict(attrs)
        self.stack.append(
            (
                kind,
                self._length(),
                str(attributes.get("href", "") or ""),
                str(attributes.get("class", "") or ""),
                "expandable" in attributes,
            )
        )

    def handle_startendtag(self, tag, attrs):
        depth = len(self.stack)
        self.handle_starttag(tag, attrs)
        if len(self.stack) > depth:
            self._close()

    def handle_endtag(self, tag):
        kind = _TAG_TO_KIND.get(tag)
        if kind is None:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == kind:
                while len(self.stack) > index:
                    self._close()
                return

    def _close(self):
        kind, start, href, css, expandable = self.stack.pop()
        end = self._length()
        if end <= start:
            return
        language = css[len("language-"):] if (kind == CODE and css.startswith("language-")) else ""
        self.spans.append(
            Span(kind=kind, start=start, end=end, url=href,
                 language=language, expandable=expandable)
        )

    def result(self) -> Segment:
        while self.stack:
            self._close()
        return Segment("".join(self.parts), tuple(self.spans))


def _merge_pre_code(spans) -> tuple:
    """``<pre><code class="language-x">`` juftligini BITTA ``pre`` span'ga
    birlashtiradi (aks holda qayta yozishda ikki qatlam chiqadi)."""
    ordered = sorted(spans, key=lambda s: (s.start, -s.end, s.kind))
    consumed: set = set()
    out: list = []
    for index, span in enumerate(ordered):
        if index in consumed:
            continue
        if span.kind == PRE:
            for other_index, other in enumerate(ordered):
                if other_index <= index or other_index in consumed:
                    continue
                if (other.kind == CODE and other.start == span.start
                        and other.end == span.end):
                    consumed.add(other_index)
                    out.append(replace(span, language=other.language or span.language))
                    break
            else:
                out.append(span)
        else:
            out.append(span)
    return tuple(out)


def html_to_segment(html: str) -> Segment:
    """HTML → yadro modeli. Avval ``sanitize_html`` bilan balanslanadi.

    Buzilgan/noma'lum teglar ``telegram_sanitizer`` tomonidan YOZUVCHA
    matnga aylantiriladi (teg sifatida yuborilmaydi) — shu sababli parser
    har doim balanslangan kirish oladi.
    """
    from utils.telegram_sanitizer import sanitize_html

    parser = _HtmlToModel()
    parser.feed(sanitize_html("" if html is None else str(html), None))
    parser.close()
    segment = parser.result()
    return Segment(segment.text, _merge_pre_code(segment.spans))


def _open_tag(span) -> str:
    if span.kind == LINK:
        return f'<a href="{escape(span.url, quote=True)}">'
    if span.kind == PRE:
        if span.language:
            return f'<pre><code class="language-{escape(span.language, quote=True)}">'
        return "<pre>"
    if span.kind == QUOTE:
        return "<blockquote expandable>" if span.expandable else "<blockquote>"
    return f"<{_KIND_TO_TAG[span.kind]}>"


def _close_tag(span) -> str:
    if span.kind == PRE:
        return "</code></pre>" if span.language else "</pre>"
    if span.kind == QUOTE:
        return "</blockquote>"
    if span.kind == LINK:
        return "</a>"
    return f"</{_KIND_TO_TAG[span.kind]}>"


def segment_to_html(segment) -> str:
    """Yadro modeli → kanonik Telegram HTML (teglar yopilgan, escape qilingan).

    Tartib qoidalari (ichma-ich formatlash to'g'ri chiqishi uchun):
      * bir xil nuqtada avval YOPILADI, keyin ochiladi;
      * yopilishda ICHKI (start'i katta) avval, ochilishda TASHQI (end'i
        katta) avval — shunda teglar kesishmaydi.
    """
    text = segment.text
    opens: dict = {}
    closes: dict = {}
    for span in segment.spans:
        if span.kind == LINK and not span.url:
            continue  # havolasiz <a> ma'nosiz — matn saqlanadi
        opens.setdefault(span.start, []).append(span)
        closes.setdefault(span.end, []).append(span)
    for bucket in opens.values():
        bucket.sort(key=lambda s: -s.end)
    for bucket in closes.values():
        bucket.sort(key=lambda s: -s.start)

    out: list = []
    for index, char in enumerate(text):
        for span in closes.get(index, ()):
            out.append(_close_tag(span))
        for span in opens.get(index, ()):
            out.append(_open_tag(span))
        out.append(escape(char, quote=False))
    for span in closes.get(len(text), ()):
        out.append(_close_tag(span))
    return "".join(out)


def _safe_signature_html(signature: str) -> str:
    """Imzo HTML'i: yozuvcha matn escape qilinadi, URL esa havola bo'ladi."""
    signature = normalize_signature(signature)
    if not signature:
        return ""
    url = signature.strip()
    if "\n" not in url and re.fullmatch(r"https?://\S+", url):
        try:
            from utils.security import validate_button_url

            if validate_button_url(url):
                return f'<a href="{escape(url, quote=True)}">{escape(url, quote=False)}</a>'
        except Exception:  # pragma: no cover - himoya
            logger.debug("post_cleaner: imzo URL tekshiruvi bajarilmadi", exc_info=True)
    return escape(signature, quote=False)


def clean_html(html: str, config: CleanerConfig = DEFAULT_CONFIG) -> CleanResult:
    """HTML postni ENTITY-SAFE tozalaydi (teg daraxti saqlanadi).

    ``result.text`` — Telegram'ga ``parse_mode="HTML"`` bilan yuborishga
    tayyor, balanslangan HTML. Imzo URL bo'lsa ``<a>`` teg bo'lib chiqadi.
    """
    raw = "" if html is None else str(html)
    if not config.enabled or not raw.strip():
        return CleanResult(text=raw, changed=False)

    segment = html_to_segment(raw)
    if not segment.text.strip():
        return CleanResult(text=raw, changed=False)

    signature = normalize_signature(config.signature)
    result = clean_segment(segment, config.with_signature(""))

    body_html = segment_to_html(Segment(result.text, result.spans))
    signature_html = _safe_signature_html(signature) if signature else ""
    if signature_html and signature_html in body_html:
        signature_html = ""  # idempotent: dublikat qo'shilmaydi

    added = bool(signature_html)
    if added:
        if config.signature_position == "start":
            text = f"{signature_html}\n\n{body_html}" if body_html else signature_html
        else:
            text = f"{body_html}\n\n{signature_html}" if body_html else signature_html
    else:
        text = body_html

    return replace(result, text=text, entities=(),
                   signature_added=added, changed=(text != raw))


# ============================================================
# 7) ADAPTER C — MARKDOWN (MarkdownV2 uslubidagi belgilar)
# ============================================================
_MD_TOKENS = (
    (re.compile(r"\*\*(.+?)\*\*", re.S), BOLD),
    (re.compile(r"__(.+?)__", re.S), ITALIC),
    (re.compile(r"~~(.+?)~~", re.S), STRIKE),
    (re.compile(r"\|\|(.+?)\|\|", re.S), SPOILER),
    (re.compile(r"`([^`]+)`", re.S), CODE),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)", re.S), LINK),
)


def markdown_to_segment(markdown: str) -> Segment:
    """Yengil Markdown → yadro modeli (ichma-ich belgilar saqlanadi)."""
    parts: list = []
    spans: list = []

    def length() -> int:
        return sum(len(part) for part in parts)

    def walk(chunk: str) -> int:
        """Chunk'ni ``parts`` ga qo'shadi; NECHTA belgi qo'shilganini qaytaradi."""
        before = length()
        position = 0
        while position < len(chunk):
            match = kind = None
            for pattern, token_kind in _MD_TOKENS:
                candidate = pattern.match(chunk, position)
                if candidate:
                    match, kind = candidate, token_kind
                    break
            if match is None:
                parts.append(chunk[position])
                position += 1
                continue
            inner = match.group(1)
            start = length()
            inner_len = walk(inner)
            if kind == LINK:
                spans.append(Span(kind=LINK, start=start, end=start + inner_len,
                                  url=match.group(2)))
            else:
                spans.append(Span(kind=kind, start=start, end=start + inner_len))
            position = match.end()
        return length() - before

    walk("" if markdown is None else str(markdown))
    return Segment("".join(parts), tuple(sorted(
        spans, key=lambda s: (s.start, -s.end, s.kind))))


_MD_MARKERS = {
    BOLD: ("**", "**"),
    ITALIC: ("__", "__"),
    STRIKE: ("~~", "~~"),
    SPOILER: ("||", "||"),
    CODE: ("`", "`"),
}


def segment_to_markdown(segment) -> str:
    """Yadro modeli → Markdown (ichma-ich belgilar to'g'ri yopiladi)."""
    text = segment.text
    opens: dict = {}
    closes: dict = {}
    for span in segment.spans:
        opens.setdefault(span.start, []).append(span)
        closes.setdefault(span.end, []).append(span)
    for bucket in opens.values():
        bucket.sort(key=lambda s: -s.end)
    for bucket in closes.values():
        bucket.sort(key=lambda s: -s.start)

    out: list = []
    for index, char in enumerate(text):
        for span in closes.get(index, ()):
            out.append(_md_close(span))
        for span in opens.get(index, ()):
            out.append(_md_open(span))
        out.append(char)
    for span in closes.get(len(text), ()):
        out.append(_md_close(span))
    return "".join(out)


def _md_open(span) -> str:
    if span.kind == LINK:
        return "["
    return _MD_MARKERS.get(span.kind, ("", ""))[0]


def _md_close(span) -> str:
    if span.kind == LINK:
        return f"]({span.url})"
    return _MD_MARKERS.get(span.kind, ("", ""))[1]


def clean_markdown(markdown: str, config: CleanerConfig = DEFAULT_CONFIG) -> CleanResult:
    """Markdown postni ENTITY-SAFE tozalaydi (belgilar daraxti saqlanadi)."""
    raw = "" if markdown is None else str(markdown)
    if not config.enabled or not raw.strip():
        return CleanResult(text=raw, changed=False)
    segment = markdown_to_segment(raw)
    if not segment.text.strip():
        return CleanResult(text=raw, changed=False)
    result = clean_segment(segment, config)
    text = segment_to_markdown(Segment(result.text, result.spans))
    return replace(result, text=text, entities=(),
                   changed=(text != raw) or result.signature_added)


# ============================================================
# 8) QULAY YORDAMCHILAR (DB ulanmasi — fail-soft)
# ============================================================
_SETTING_KEYS = ("post_auto_clean", "post_clean_mentions", "post_clean_links",
                 "post_clean_promo")
_SETTING_DEFAULTS = {"post_auto_clean": False, "post_clean_mentions": True,
                     "post_clean_links": True, "post_clean_promo": True}


async def load_cleaner_config(user_id: int, *, db_module=None,
                              own_usernames=None) -> CleanerConfig:
    """Foydalanuvchi sozlamalaridan ``CleanerConfig`` yasaydi (fail-soft).

    DB bo'lmasa/xato bo'lsa — ``enabled=False`` qaytadi, ya'ni tozalash
    ISHLAMAYDI (post buzilmaydi). Bu funksiya hech qachon exception
    tashlamaydi — ingest oqimi tozalash sababli to'xtab qolmasligi kerak.
    """
    if not user_id:
        return DEFAULT_CONFIG
    try:
        import database as db
    except Exception:  # pragma: no cover - test muhiti
        return DEFAULT_CONFIG
    db = db_module or db
    try:
        runner = getattr(db, "run_db", None)
        combined_getter = getattr(db, "get_user_settings_and_signature", None)
        getter = getattr(db, "get_user_post_signature", None)
        if callable(runner) and callable(combined_getter):
            combined = await runner(
                combined_getter, user_id, list(_SETTING_KEYS), _SETTING_DEFAULTS,
            )
            if isinstance(combined, tuple) and len(combined) == 2:
                values, signature = combined
            else:  # legacy adapter/test double without combined-query support
                values = await runner(db.get_user_settings_bulk, user_id,
                                      list(_SETTING_KEYS), _SETTING_DEFAULTS)
                signature = await runner(getter, user_id) if callable(getter) else ""
        elif callable(runner):
            values = await runner(db.get_user_settings_bulk, user_id,
                                  list(_SETTING_KEYS), _SETTING_DEFAULTS)
            signature = await runner(getter, user_id) if callable(getter) else ""
        else:
            import asyncio

            if callable(combined_getter):
                combined = await asyncio.to_thread(
                    combined_getter, user_id, list(_SETTING_KEYS), _SETTING_DEFAULTS,
                )
            else:
                combined = None
            if isinstance(combined, tuple) and len(combined) == 2:
                values, signature = combined
            else:
                values = await asyncio.to_thread(db.get_user_settings_bulk, user_id,
                                                 list(_SETTING_KEYS), _SETTING_DEFAULTS)
                signature = await asyncio.to_thread(getter, user_id) if callable(getter) else ""
    except Exception:
        logger.debug("post_cleaner: sozlamalarni o'qib bo'lmadi (o'chirilgan)",
                     exc_info=True)
        return DEFAULT_CONFIG

    values = values or _SETTING_DEFAULTS
    return CleanerConfig(
        enabled=bool(values.get("post_auto_clean", False)),
        strip_mentions=bool(values.get("post_clean_mentions", True)),
        strip_links=bool(values.get("post_clean_links", True)),
        strip_promo=bool(values.get("post_clean_promo", True)),
        signature=normalize_signature(signature),
        own_usernames=frozenset(own_usernames or ()),
    )


async def own_channel_usernames(user_id: int, db_module=None) -> frozenset:
    """Foydalanuvchi O'Z kanallari username'lari (tozalashda saqlanadi)."""
    try:
        import database as db
    except Exception:  # pragma: no cover - test muhiti
        return frozenset()
    db = db_module or db
    getter = getattr(db, "get_user_channels", None)
    if not callable(getter):
        return frozenset()
    try:
        runner = getattr(db, "run_db", None)
        rows = await runner(getter, user_id) if callable(runner) else getter(user_id)
    except Exception:
        logger.debug("post_cleaner: kanallarni o'qib bo'lmadi", exc_info=True)
        return frozenset()

    names = set()
    for row in rows or ():
        candidates = []
        if isinstance(row, dict):
            candidates = [row.get("title"), row.get("username")]
        else:
            try:
                candidates = [row[1]] if len(row) > 1 else []
            except Exception:
                candidates = []
        for value in candidates:
            text = str(value or "")
            for match in MENTION_RE.finditer(text):
                names.add(match.group(1).lower())
            for match in TELEGRAM_LINK_RE.finditer(text):
                tail = match.group(0).rstrip("/").split("/")[-1].lower()
                if tail:
                    names.add(tail.lstrip("@"))
    return frozenset(names)


async def resolve_config(user_id: int, db_module=None) -> CleanerConfig:
    """Bitta chaqiruvda to'liq konfiguratsiya (toggle'lar + ✍️ imzo + kanallar).

    Batch oqimlarda (masalan RSS tekshiruvi N ta elementni qayta ishlaydi)
    bu funksiya BIR MARTA chaqiriladi va natija har bir elementga uzatiladi —
    har element uchun DB'ga qayta chiqilmaydi.

    Hech qachon exception tashlamaydi: xatoda ``DEFAULT_CONFIG``
    (``enabled=False``) qaytadi, ya'ni tozalash ishlamaydi va post buzilmaydi.
    """
    if not user_id:
        return DEFAULT_CONFIG
    own = await own_channel_usernames(user_id, db_module)
    return await load_cleaner_config(user_id, db_module=db_module,
                                     own_usernames=own)


#: 🧪 Namuna (demo) uchun — real hayotdagi "iflos" manba posti.
DEMO_SOURCE_HTML = (
    "<b>Yangi telefon taqdimoti bo'lib o'tdi</b>\n\n"
    "Kompaniya bugun yangi flagman modelini ko'rsatdi. Batafsil ma'lumot "
    "rasmiy saytda e'lon qilindi.\n\n"
    "📢 <a href=\"https://t.me/source_news\">@source_news</a> orqali tarqatildi\n"
    "Reklama: @promo_uz — obuna bo'ling!\n"
    "Manba: https://t.me/source_news/123"
)


# ============================================================
# 9) TEZKOR REJIM — faqat post OXIRINI tozalash + imzo
# ============================================================
# «🧹 Postni tozalash» rejimi: foydalanuvchi postni yuboradi, bot faqat
# OXIRIDAGI begona havola/reklama qatorlarini olib tashlaydi, post matnining
# qolgan qismiga (va formatlashiga) TEGMAYDI, so'ng oxiriga foydalanuvchi
# imzosini qo'shadi. Hech qanday tarmoq/DB chaqiruvi yo'q — bir zumda ishlaydi.

#: Imzo cheklovlari (foydalanuvchiga aniq tushuntiriladi).
SIGNATURE_MAX_LINES = 10
SIGNATURE_MAX_WORDS = 300
SIGNATURE_MAX_CHARS = 2000

#: Telegram cheklovlari (UTF-16 birliklarida): oddiy xabar va media izohi.
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

#: Oxiridan ko'pi bilan shuncha qator olib tashlanadi (post "yeyilib" ketmasin).
_TAIL_MAX_LINES = 6
#: Begona havolasi bor qatorda (havolasiz) shundan ko'p so'z bo'lsa — kontent.
_TAIL_POINTER_MAX_WORDS = 8

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_ALNUM_RE = re.compile(r"[^\W_]", re.UNICODE)


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


_TG_NAME_RE = re.compile(
    r"(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?@?([A-Za-z0-9_+]+)", re.IGNORECASE,
)


def _is_foreign_url(url: str, own) -> bool:
    """Havola foydalanuvchining O'Z kanaliga olib bormasa — begona."""
    match = _TG_NAME_RE.search(url or "")
    if match:
        return match.group(1).lower() not in own
    return bool(url)


def _line_pointers(line: str, link_urls, own) -> tuple:
    """Qatordagi begona havola/eslatmalar soni va ular olingandagi so'zlar."""
    foreign = 0
    for match in TELEGRAM_LINK_RE.finditer(line):
        if _is_foreign_url(match.group(0), own):
            foreign += 1
    for match in MENTION_RE.finditer(line):
        if match.group(1).lower() not in own:
            foreign += 1
    for match in _URL_RE.finditer(line):
        if not TELEGRAM_LINK_RE.match(match.group(0)):
            foreign += 1
    for url in link_urls:
        if _is_foreign_url(url, own):
            foreign += 1
    rest = _URL_RE.sub(" ", TELEGRAM_LINK_RE.sub(" ", MENTION_RE.sub(" ", line)))
    words = [w for w in re.sub(r"[^\w\s']", " ", rest).split() if w]
    return foreign, words


def _is_tail_junk(line: str, link_urls, own, removed_so_far: int) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if not _ALNUM_RE.search(stripped):
        # Ajratuvchi/emoji qatori ("➖➖➖") — faqat reklama ostida qolsa.
        return removed_so_far > 0 and not link_urls
    foreign, words = _line_pointers(stripped, link_urls, own)
    lowered = stripped.lower()
    if STRONG_PROMO_RE.match(stripped) or COPYRIGHT_RE.match(stripped):
        return True
    if SOURCE_LINE_RE.match(stripped) and len(stripped) <= SOURCE_LINE_MAX_LEN:
        return True
    if foreign and len(words) <= _TAIL_POINTER_MAX_WORDS:
        return True
    if (len(stripped) <= PROMO_LINE_MAX_LEN and len(words) <= _TAIL_POINTER_MAX_WORDS
            and any(kw in lowered for kw in PROMO_KEYWORDS)):
        return True
    return False


def strip_tail_junk(segment: Segment, own=frozenset()) -> tuple:
    """Post OXIRIDAGI begona havola/reklama qatorlarini olib tashlaydi.

    Faqat ketma-ket oxirgi qatorlar tekshiriladi; birinchi "oddiy" qatorda
    to'xtaydi — post matnining qolgan qismi va formatlashi o'zgarmaydi.
    Kod (``code``/``pre``) ichidagi qatorlarga tegilmaydi. Tozalashdan keyin
    matn bo'sh qolsa — asl post qaytariladi.

    Qaytadi: ``(segment, olib_tashlangan_qatorlar_soni)``.
    """
    text = segment.text
    own = frozenset(str(o).lower().lstrip("@") for o in own or ())
    mask = segment.literal_mask()
    lines, pos = [], 0
    for line in text.split("\n"):
        lines.append((pos, pos + len(line)))
        pos += len(line) + 1

    cut = len(text)
    removed = 0
    for start, end in reversed(lines):
        line = text[start:end]
        if not line.strip():
            continue
        if removed >= _TAIL_MAX_LINES or any(mask[start:end]):
            break
        link_urls = [s.url for s in segment.spans
                     if s.kind == LINK and s.url and s.start < end and s.end > start]
        if not _is_tail_junk(line, link_urls, own, removed):
            break
        removed += 1
        cut = start

    if not removed:
        return segment, 0
    new_text = text[:cut].rstrip()
    if not new_text.strip():
        return segment, 0
    limit = len(new_text)
    spans = tuple(
        s.shifted(s.start, min(s.end, limit))
        for s in segment.spans if s.start < limit and min(s.end, limit) > s.start
    )
    return Segment(new_text, spans), removed


def _trim_segment(segment: Segment) -> Segment:
    text = segment.text
    left = len(text) - len(text.lstrip())
    right = len(text.rstrip())
    if left == 0 and right == len(text):
        return segment
    spans = []
    for s in segment.spans:
        start, end = max(s.start, left), min(s.end, right)
        if end > start:
            spans.append(s.shifted(start - left, end - left))
    return Segment(text[left:right], tuple(spans))


def signature_problems(text: str) -> dict:
    """Imzo cheklovlarini tekshiradi → buzilgan cheklovlar lug'ati (bo'sh = OK).

    Kalitlar: ``lines`` / ``words`` / ``chars`` — har biri ``(hozirgi, chegara)``.
    """
    body = (text or "").strip()
    problems = {}
    lines = len(body.split("\n")) if body else 0
    words = len(body.split())
    chars = _utf16(body)
    if lines > SIGNATURE_MAX_LINES:
        problems["lines"] = (lines, SIGNATURE_MAX_LINES)
    if words > SIGNATURE_MAX_WORDS:
        problems["words"] = (words, SIGNATURE_MAX_WORDS)
    if chars > SIGNATURE_MAX_CHARS:
        problems["chars"] = (chars, SIGNATURE_MAX_CHARS)
    return problems


#: Havola atrofidagi tasodifiy belgilar: ``<https://t.me/x>``, ``(t.me/x).``, «@x»,
#: ``"https://..."`` va gap oxiridagi tinish belgilari.
_LINK_WRAP_LEFT = "<([{«\"'`"
_LINK_WRAP_RIGHT = ">)]}»\"'`.,;:!?…"
#: Sxemasiz domen: ``example.com``, ``www.example.uz/yol`` (TO'LIQ moslik kerak).
_BARE_DOMAIN_RE = re.compile(
    r"(?:www\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?:[/?#]\S*)?"
)


def link_to_url(raw: str) -> str:
    """``@kanal`` / ``t.me/kanal`` / ``example.com`` / ``https://...`` → xavfsiz URL.

    Qabul qilinadi: ``https://t.me/kanal``, ``t.me/kanal``, ``@kanal``,
    sxemasiz domen (``example.com/yol``), burchak/qavs/qo'shtirnoq ichidagi va
    gap oxiridagi tinish belgisi bilan yozilgan havola (``<https://t.me/x>``,
    ``"@kanal".``). Xavfli sxemalar (``javascript:``, ``data:``) rad etiladi.
    Yaroqsiz kiritish — ``""``.
    """
    value = (raw or "").strip()
    value = value.lstrip(_LINK_WRAP_LEFT).rstrip(_LINK_WRAP_RIGHT).strip()
    if re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{3,31}", value):
        value = f"https://t.me/{value[1:]}"
    elif re.fullmatch(r"(?:www\.)?(?:t\.me|telegram\.me)/\S+", value, re.IGNORECASE):
        value = f"https://{value}"
    elif _BARE_DOMAIN_RE.fullmatch(value):
        value = f"https://{value}"
    if not re.fullmatch(r"(?:https?|tg)://\S+", value, re.IGNORECASE):
        return ""
    try:
        from utils.security import validate_button_url
    except Exception:  # pragma: no cover - himoya
        return ""
    return value if validate_button_url(value) else ""


def find_link_url(raw: str) -> str:
    """Matndan BIRINCHI yaroqli havolani topadi (``link_to_url`` + so'zma-so'z qidiruv).

    Foydalanuvchi havolani izoh bilan yozishi mumkin: ``👉 Obuna: @kanal`` —
    butun matn havola bo'lmasa, so'zlar ketma-ket tekshiriladi.
    """
    whole = link_to_url(raw)
    if whole:
        return whole
    for token in str(raw or "").split():
        url = link_to_url(token)
        if url:
            return url
    return ""


def signature_from_message(text: str, entities=None) -> tuple:
    """Telegram xabaridan imzo HTML'i → ``(html, havolasi_bormi)``.

    Formatlash (qalin, kursiv, havola ulangan so'zlar) saqlanadi; xavfli
    havolalar (``javascript:`` va h.k.) olib tashlanadi, matni qoladi.
    """
    raw = "" if text is None else str(text)
    segment = _trim_segment(Segment(raw, entities_to_spans(raw, entities)))
    spans = []
    has_link = False
    for span in segment.spans:
        if span.kind == LINK:
            url = link_to_url(span.url)
            if not url:
                continue
            span = replace(span, url=url)
            has_link = True
        spans.append(span)
    segment = Segment(segment.text, tuple(spans))
    if (TELEGRAM_LINK_RE.search(segment.text) or MENTION_RE.search(segment.text)
            or _URL_RE.search(segment.text)):
        has_link = True
    return segment_to_html(segment), has_link


def wrap_signature_link(signature_html: str, url: str) -> str:
    """Butun imzo matnini havolaga ulaydi (``<a href=url>…</a>``)."""
    segment = html_to_segment(signature_html)
    spans = tuple(s for s in segment.spans if s.kind != LINK)
    spans += (Span(kind=LINK, start=0, end=len(segment.text), url=url),)
    return segment_to_html(Segment(segment.text, spans))


@dataclass(frozen=True)
class QuickCleanResult:
    """Tezkor tozalash natijasi."""

    html: str
    length: int
    removed_lines: int = 0
    signature_added: bool = False


def quick_clean(text: str, entities=None, signature_html: str = "",
                own=frozenset()) -> QuickCleanResult:
    """Postni tezkor tozalaydi: oxiridagi keraksiz qatorlar → imzo.

    ``length`` — Telegram hisoblaydigan uzunlik (UTF-16), cheklovni
    tekshirish uchun (matn: 4096, media izohi: 1024).
    """
    raw = "" if text is None else str(text)
    segment = Segment(raw, entities_to_spans(raw, entities))
    body, removed = strip_tail_junk(segment, own)
    body = _trim_segment(body)
    body_html = segment_to_html(body)

    sig_segment = html_to_segment(signature_html) if signature_html else Segment("")
    sig_text = sig_segment.text.strip()
    added = bool(sig_text) and not body.text.rstrip().endswith(sig_text)
    if added:
        html = f"{body_html}\n\n{signature_html}" if body.text else signature_html
        length = _utf16(body.text) + (2 if body.text else 0) + _utf16(sig_segment.text)
    else:
        html = body_html
        length = _utf16(body.text)
    return QuickCleanResult(html=html, length=length, removed_lines=removed,
                            signature_added=added)


def clean_editor_html(html: str, signature_html: str = "") -> QuickCleanResult:
    """Tahrirlagichdagi HTML-matnni tozalaydi (Mini App): oxiridagi begona qatorlar olinadi, imzo qo'shiladi.

    ``quick_clean`` bilan bir xil qoidalar; farqi — kirish Telegram entity'lari emas, HTML.
    """
    segment = html_to_segment(html)
    body, removed = strip_tail_junk(segment)
    body = _trim_segment(body)
    body_html = segment_to_html(body)
    sig_segment = html_to_segment(signature_html) if signature_html else Segment("")
    sig_text = sig_segment.text.strip()
    added = bool(sig_text) and not body.text.rstrip().endswith(sig_text)
    if added:
        out = f"{body_html}\n\n{signature_html}" if body.text else signature_html
        length = _utf16(body.text) + (2 if body.text else 0) + _utf16(sig_segment.text)
    else:
        out = body_html
        length = _utf16(body.text)
    return QuickCleanResult(html=out, length=length, removed_lines=removed, signature_added=added)
