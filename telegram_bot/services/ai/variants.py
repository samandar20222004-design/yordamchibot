"""✨ MULTI-VARIANT GENERATOR — 48-band (PHASE 11).

Bitta post mavzusidan **5 ta bir-biridan farq qiluvchi** post:

=====  ==========  ===============================================
  #      style      Burchak (angle) — har biri o'zining mantig'i bilan
=====  ==========  ===============================================
 1     🔥 viral      kuchli hook + munozarali savol + ulashishga chaqiriq
 2     💎 premium    bosiq, lakonik, ekspert/nufuzli ohang, bosimsiz CTA
 3     💰 sales      muammo → kuchaytirish → yechim (PAS) + aniq taklif
 4     📚 informative faktlar, raqamlar, tuzilmali foyda + xulosa
 5     🤳 blogger    samimiy shaxsiy tajriba, do'stona ohang, savol
=====  ==========  ===============================================

Talab: variantlar bir-birining SINONIMI bo'lmasligi kerak. Shu sababli:

* har bir uslub uchun **alohida AI chaqiruvi** (alohida tizim ko'rsatmasi,
  alohida struktura talabi) yuboriladi — bitta javobni qayta yozib
  «5 variant» qilib bo'lmaydi;
* javob olingach ``fingerprint`` + Jaccard o'xshashligi bilan solishtiriladi:
  ikki variant mazmunan bir xil bo'lsa, ikkinchisi uslub bankidagi
  deterministik burchakka almashtiriladi;
* har bir variant yakunda ``sanitize_html`` (Phase 2) orqali o'tadi va
  alohida Telegram xabari sifatida chunk qilinadi.

Integratsiya: AIOrchestrator (Phase 3) → Provider Chain → MockProvider;
kvota/kredit BITTA atomik bron (Phase 2 ``reserve_ai_request``) — 5 ta AI
chaqiruvi uchun ham 1 kredit sarflanadi, xatoda bron refund qilinadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from .smm_common import (
    CHUNK_SAFE_LIMIT,
    DEFAULT_LANG,
    SMMFeatureService,
    TELEGRAM_TEXT_LIMIT,
    clip,
    ensure_hashtags,
    escape_literal,
    fingerprint,
    lang_text,
    normalize_lang,
    same_content,
    sanitize_html,
    strip_html,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# USLUB LUG'ATI (5 ta, tartib muhim — UI shu tartibda chizadi)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VariantStyle:
    """Bitta variant uslubi (burchak)."""

    key: str
    emoji: str
    order: int
    label: dict
    angle: dict
    instruction: dict
    hashtags: tuple

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_angle(self, lang: Any) -> str:
        return lang_text(self.angle, lang, "")

    def t_instruction(self, lang: Any) -> str:
        return lang_text(self.instruction, lang, "")


VARIANT_STYLES: tuple[VariantStyle, ...] = (
    VariantStyle(
        key="viral",
        emoji="🔥",
        order=1,
        label={"uz": "Viral", "ru": "Вирусный", "en": "Viral"},
        angle={
            "uz": "Kuchli hook va munozarali savol — sharh va ulashishni og'ish",
            "ru": "Сильный хук и спорный вопрос — толкаем к комментариям и репостам",
            "en": "A hard hook plus a polarising question — drive comments and shares",
        },
        instruction={
            "uz": (
                "Birinchi qator — to'xtatuvchi, keskin va qat'iy <b>hook</b>. "
                "Ikkinchi qatorda o'quvchini bahslashuvga tortadigan BITA "
                "munozarali savol. 2-3 qisqa punkt (⚡️/💣), keyin "
                "«ulashing/izohda yozing» chaqrig'i. Rasmiy til TAQIQLANADI."
            ),
            "ru": (
                "Первая строка — останавливающий, резкий <b>хук</b>. Во второй — "
                "РОВНО один спорный вопрос, который провоцирует спор. 2-3 "
                "коротких пункта (⚡️/💣), в конце призыв «отправь другу» или "
                "«напиши в комментариях». Канцелярит запрещён."
            ),
            "en": (
                "First line — a scroll-stopping, sharp <b>hook</b>. Second line: "
                "exactly ONE polarising question that starts an argument. Two or "
                "three short bullets (⚡️/💣), then a share-or-comment ask. No "
                "corporate tone."
            ),
        },
        hashtags=("#viral", "#munozara", "#tezkor", "#trend"),
    ),
    VariantStyle(
        key="premium",
        emoji="💎",
        order=2,
        label={"uz": "Premium", "ru": "Премиум", "en": "Premium"},
        angle={
            "uz": "Bosiq, ekspert va nufuzli ohang — kam so'z, ko'p vazn",
            "ru": "Сдержанный, экспертный и статусный тон — мало слов, много веса",
            "en": "Restrained, expert, high-status tone — fewer words, more weight",
        },
        instruction={
            "uz": (
                "Ohang: xotirjam ishonch, nafis va lakonik. Har bir gap vaznli "
                "bo'lsin, undov belgilari kam. Chegirma/aksiya/«arzon» SO'ZLARI "
                "TAQIQLANGAN. 2 qisqa abzats + nafis, bosimsiz CTA "
                "(«yozing», «tanishing»). 1-2 emoji (💎 ✨ 🤍)."
            ),
            "ru": (
                "Тон: спокойная уверенность, изящество, лаконичность. Каждое "
                "предложение весомо, восклицаний почти нет. Слова «скидка», "
                "\"акция\", «дёшево» ЗАПРЕЩЕНЫ. Два коротких абзаца + мягкий CTA "
                "без давления. 1-2 эмодзи (💎 ✨ 🤍)."
            ),
            "en": (
                "Tone: calm authority, elegance, restraint. Every sentence "
                "carries weight; almost no exclamation marks. Words like "
                "\"discount\", \"promo\", \"cheap\" are FORBIDDEN. Two short "
                "paragraphs plus a soft, pressure-free CTA. 1-2 emojis (💎 ✨ 🤍)."
            ),
        },
        hashtags=("#premium", "#sifat", "#tanlov", "#standart"),
    ),
    VariantStyle(
        key="sales",
        emoji="💰",
        order=3,
        label={"uz": "Sotuv", "ru": "Продающий", "en": "Sales"},
        angle={
            "uz": "Muammo → kuchaytirish → yechim (PAS), aniq taklif va sotuv CTA",
            "ru": "Боль → усиление → решение (PAS), чёткий оффер и продающий CTA",
            "en": "Pain → agitation → solution (PAS), a clear offer and sales CTA",
        },
        instruction={
            "uz": (
                "PAS formulasi: 1) muammo (og'riq) aniq tasvirlansin; 2) "
                "oqibati bilan kuchaytirilsin; 3) yechim — taklif. ANIQ TAKLIF "
                "alohida qatorda <b>qalin</b> (narx bo'lmasa [narx] placeholder). "
                "Yakunda BITTA sotuv chaqrig'i: «🛒 Buyurtma bering» va cheklov "
                "(muddat/soni)."
            ),
            "ru": (
                "Формула PAS: 1) чётко описать боль; 2) усилить ценой бездействия; "
                "3) решение — наш оффер. ОТДЕЛЬНОЙ СТРОКОЙ жирным конкретный "
                "оффер (если цены нет — [цена]). Финал — ОДИН продающий CTA "
                "«🛒 Закажите» с ограничением по времени или количеству."
            ),
            "en": (
                "PAS formula: 1) name the pain; 2) agitate with the cost of doing "
                "nothing; 3) present the offer as the solution. A concrete offer "
                "on its own BOLD line (use [price] if unknown). Close with ONE "
                "sales CTA: “🛒 Order now”, with a time or quantity limit."
            ),
        },
        hashtags=("#aksiya", "#chegirma", "#buyurtma", "#taklif"),
    ),
    VariantStyle(
        key="informative",
        emoji="📚",
        order=4,
        label={"uz": "Informativ", "ru": "Информативный", "en": "Informative"},
        angle={
            "uz": "Faktlar, raqamlar va tuzilmali foyda — o'qib bo'lgach amaliyot",
            "ru": "Факты, цифры и структурная польза — применимо сразу после чтения",
            "en": "Facts, numbers and structured value — usable right after reading",
        },
        instruction={
            "uz": (
                "Tuzilma: 1 qator kirish, keyin 1./2./3. raqamli 3 punkt (har "
                "birida aniq fakt yoki o'lchanadigan natija), oxirida «🧠 Ekspert "
                "xulosasi». Uydirilgan statistika YO'Q — aniq raqam bo'lmasa "
                "[metrika] placeholder. Foyda: o'quvchi 30 sekundda amalni "
                "bilishi kerak."
            ),
            "ru": (
                "Структура: одна вводная строка, затем три нумерованных пункта "
                "(факт или измеримый результат), в конце «🧠 Вывод эксперта». "
                "Выдуманной статистики нет — вместо неизвестных цифр [метрика]. "
                "Польза: читатель уносит конкретное действие."
            ),
            "en": (
                "Structure: one lead line, three numbered points (each a fact or "
                "a measurable outcome), then “🧠 Expert takeaway”. Never invent "
                "statistics — use [metric] when a number is unknown. Value: the "
                "reader leaves with one concrete action."
            ),
        },
        hashtags=("#fakt", "#maslahat", "#tahlil", "#bilim"),
    ),
    VariantStyle(
        key="blogger",
        emoji="🤳",
        order=5,
        label={"uz": "Blogger", "ru": "Блогерский", "en": "Blogger"},
        angle={
            "uz": "Samimiy shaxsiy tajriba, do'stona ohang va ochiq savol",
            "ru": "Искренний личный опыт, дружеский тон и открытый вопрос",
            "en": "Honest personal experience, friendly tone and an open question",
        },
        instruction={
            "uz": (
                "Birinchi shaxsda yozing («men», «biz»), kundalik til, qisqa "
                "jumlar. Bitta aniq voqea/lahza so'zlasin: boshlang'ich holat → "
                "burilish → xulosa. Yakunda o'quvchiga SHAHSIY savol ("
                "«sizda qanday?») va javob berishga taklif. Rasmiy atamalar "
                "TAQIQLANADI."
            ),
            "ru": (
                "Пишите от первого лица («я», «мы»), разговорный стиль, короткие "
                "фразы. Один конкретный момент: точка старта → перелом → вывод. "
                "В конце ЛИЧНЫЙ вопрос читателю («а как у вас?») и приглашение "
                "ответить. Канцеляризмы запрещены."
            ),
            "en": (
                "First person (“I”, “we”), conversational, short sentences. One "
                "concrete moment: starting point → turn → takeaway. Close with a "
                "PERSONAL question (“how about you?”) and an invite to answer. "
                "No formal wording."
            ),
        },
        hashtags=("#kundalik", "#tajriba", "#samimiy", "#blog"),
    ),
)

#: style kaliti/emoji/label → kanonik VariantStyle (eski va emojili nomlar ham).
VARIANT_STYLE_INDEX: dict[str, VariantStyle] = {}
for _style in VARIANT_STYLES:
    VARIANT_STYLE_INDEX[_style.key] = _style
    VARIANT_STYLE_INDEX[_style.key.lower()] = _style
    VARIANT_STYLE_INDEX[_style.emoji + " " + _style.key] = _style
for _alias, _target in {
    "casual": "blogger",
    "blog": "blogger",
    "oddiy": "blogger",
    "обычный": "blogger",
    "ads": "sales",
    "ad": "sales",
    "reklama": "sales",
    "реклама": "sales",
    "sotuv": "sales",
    "informativ": "informative",
    "viral_post": "viral",
}.items():
    VARIANT_STYLE_INDEX[_alias] = VARIANT_STYLE_INDEX[_target]

#: Majburiy 5 ta uslub (testlar va UI shu tartibga tayanadi).
VARIANT_STYLE_KEYS: tuple[str, ...] = tuple(style.key for style in VARIANT_STYLES)
VARIANT_COUNT = len(VARIANT_STYLES)

#: Bir variantning Telegram chegarasi (sarlavha bloki uchun zaxira bilan).
VARIANT_BODY_LIMIT = 3600


def resolve_style(value: Any) -> VariantStyle | None:
    """'viral' / '🔥 viral' / 'Blogger' → VariantStyle (topilmasa None)."""
    if isinstance(value, VariantStyle):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in VARIANT_STYLE_INDEX:
        return VARIANT_STYLE_INDEX[raw]
    emoji = raw.split(" ", 1)[0]
    for style in VARIANT_STYLES:
        if raw == style.key or style.key in raw or emoji == style.emoji:
            return style
    return None


def styles_for(values: Sequence[str] | None) -> tuple[VariantStyle, ...]:
    """Tanlangan uslublar (noto'g'ri nomlar chiqib ketadi) yoki to'liq 5 ta."""
    if not values:
        return VARIANT_STYLES
    picked: list[VariantStyle] = []
    for value in values:
        style = resolve_style(value)
        if style is not None and style not in picked:
            picked.append(style)
    return tuple(picked) or VARIANT_STYLES


# ---------------------------------------------------------------------------
# PROMPT
# ---------------------------------------------------------------------------
def build_variant_prompt(topic: str, style: VariantStyle, lang: str = "uz",
                         *, audience: str = "", tone_note: str = "") -> str:
    """Bitta uslub uchun to'liq topshiriq (1-of-5 variant ekanligi belgilanadi).

    Matn niyatni (intent) ham aniq yo'naltiradi: «5 variants» qatori
    ``SMMIntentRouter`` uchun GENERATE_VARIANTS belgisi.
    """
    code = normalize_lang(lang)
    safe_topic = escape_literal(clip(topic, 300))
    title = {
        "uz": "Mana shu mavzuda BITTA post yozing",
        "ru": "Напишите ОДИН пост на эту тему",
        "en": "Write ONE post on this topic",
    }[code]
    topic_line = {
        "uz": f"Mavzu: {safe_topic}",
        "ru": f"Тема: {safe_topic}",
        "en": f"Topic: {safe_topic}",
    }[code]
    rules = {
        "uz": (
            "Umumiy qoidalar: Telegram HTML (<b>, <i>), 500-1200 belgi, "
            " strukturani buzma: hook → mazmun → CTA → 3-5 hashtag. "
            "Boshqa uslublarga o'xshamaydigan ANIQ shu burchakdan yozing. "
            "Foydalanuvchi so'zlarini qayta-yozib bermang — mavzuni oching."
        ),
        "ru": (
            "Общие правила: Telegram HTML (<b>, <i>), 500-1200 символов, "
            "структура обязательна: хук → содержание → CTA → 3-5 хэштегов. "
            "Пишите СТРОГО этот угол подачи, не похожий на другие варианты. "
            "Не пересказывайте слова пользователя — раскрывайте тему."
        ),
        "en": (
            "Global rules: Telegram HTML (<b>, <i>), 500-1200 characters, keep "
            "the structure hook → body → CTA → 3-5 hashtags. Write THIS angle "
            "only — it must not resemble the other variants. Do not echo the "
            "user's words; develop the topic."
        ),
    }[code]
    parts = [
        f"[SMM TASK: generate_variants — variant {style.order} of {VARIANT_COUNT} variants]",
        title,
        topic_line,
        f"Style: {style.emoji} {style.t_label(code)} ({style.t_angle(code)})",
        style.t_instruction(code),
    ]
    if audience:
        label = {"uz": "Auditoriya", "ru": "Аудитория", "en": "Audience"}[code]
        parts.append(f"{label}: {escape_literal(clip(audience, 160))}")
    if tone_note:
        parts.append(escape_literal(clip(tone_note, 240)))
    parts.append(rules)
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# NATIJA MODELLARI
# ---------------------------------------------------------------------------
@dataclass
class PostVariant:
    """Bitta tayyor variant (self-contained Telegram xabari)."""

    index: int
    style: str
    emoji: str
    label: str
    angle: str
    content: str
    source: str = "ai"
    chars: int = 0
    hashtags: list = field(default_factory=list)

    def __post_init__(self) -> None:
        from .smm_common import extract_hashtags, html_length
        self.content = sanitize_html(self.content, VARIANT_BODY_LIMIT)
        self.chars = html_length(self.content)
        self.hashtags = extract_hashtags(self.content)

    @property
    def header(self) -> str:
        return f"<b>{self.emoji} {escape_literal(self.label)} · {self.index}/{len(VARIANT_STYLES)}</b>"

    def render(self) -> str:
        """Sarlavha + burchak izohi + post matni (Telegram uchun xavfsiz)."""
        blocks = [self.header]
        if self.angle:
            blocks.append(f"<i>{escape_literal(self.angle)}</i>")
        blocks.append(self.content)
        return sanitize_html("\n\n".join(blocks), TELEGRAM_TEXT_LIMIT)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "style": self.style,
            "emoji": self.emoji,
            "label": self.label,
            "angle": self.angle,
            "content": self.content,
            "source": self.source,
            "chars": self.chars,
            "hashtags": list(self.hashtags),
            "message": self.render(),
        }


@dataclass
class VariantsResult:
    """Multi-variant generatsiyasining yakuniy natijasi."""

    success: bool
    variants: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    lang: str = DEFAULT_LANG
    topic: str = ""
    provider_used: str = "none"
    cost: int = 0
    reservation_id: Any = None
    quota: dict = field(default_factory=dict)
    paid: bool = False
    refund_issued: bool = False
    fallback_used: bool = False
    error: str | None = None
    error_code: str | None = None

    @property
    def count(self) -> int:
        return len(self.variants)

    def styles(self) -> list[str]:
        return [variant.style for variant in self.variants]

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "count": self.count,
            "styles": self.styles(),
            "lang": self.lang,
            "topic": self.topic,
            "provider_used": self.provider_used,
            "cost": self.cost,
            "reservation_id": self.reservation_id,
            "quota": dict(self.quota),
            "paid": self.paid,
            "refund_issued": self.refund_issued,
            "fallback_used": self.fallback_used,
            "error": self.error,
            "error_code": self.error_code,
            "variants": [variant.as_dict() for variant in self.variants],
            "chunks": list(self.chunks),
        }


# ---------------------------------------------------------------------------
# XIZMAT
# ---------------------------------------------------------------------------
class MultiVariantGenerator(SMMFeatureService):
    """5 xil burchakdagi postlar generatori (48-band)."""

    feature = "variants"
    #: Atomik bron oq ro'yxatidagi asos: ``magic_post`` (``:variants`` — belgi).
    quota_operation = "magic_post:variants"
    quota_cost = 1

    # -- public API --------------------------------------------------------
    async def generate(
        self,
        user_id: int | None,
        topic: str,
        lang: str = DEFAULT_LANG,
        *,
        db_module: Any = None,
        styles: Sequence[str] | None = None,
        audience: str = "",
        tone_note: str = "",
        orchestrator: Any = None,
    ) -> VariantsResult:
        """``topic`` mavzusida 5 ta farqli variant yaratadi (mock: 100% ishlaydi)."""
        code = normalize_lang(lang)
        chosen = styles_for(styles)
        clean_topic = str(topic or "").strip()
        if len(clean_topic) < 2:
            return VariantsResult(
                success=False, lang=code, topic=clean_topic,
                error="empty_topic", error_code="INVALID_INPUT",
            )

        if orchestrator is not None:
            self._injected_orchestrator = orchestrator

        ticket = await self.acquire_quota(db_module, user_id)
        if not ticket.allowed:
            return VariantsResult(
                success=False, lang=code, topic=clean_topic,
                error=ticket.reason or "quota_denied",
                error_code="QUOTA_EXCEEDED" if not ticket.reason or ticket.reason in {
                    "insufficient_balance", "user_not_found",
                } else "QUOTA_UNAVAILABLE",
                quota=ticket.as_dict(),
            )

        variants: list[PostVariant] = []
        used_providers: list[str] = []
        fatal_code: str | None = None
        fatal_error: str | None = None
        safe_topic_html = escape_literal(clip(clean_topic, 300))

        for position, style in enumerate(chosen, start=1):
            prompt = build_variant_prompt(clean_topic, style, code,
                                          audience=audience, tone_note=tone_note)
            outcome = await self.ask(
                prompt, user_id=user_id, lang=code,
                context={
                    "smm_mode": "VARIANTS",
                    "smm_variant_style": style.key,
                    "smm_topic": clip(clean_topic, 300),
                },
            )
            if outcome.provider and outcome.provider != "none":
                used_providers.append(outcome.provider)

            body = outcome.text if outcome.usable else ""
            source = "ai"
            if not body:
                body = self._fallback_post(style, code, safe_topic_html)
                source = "fallback"

            body = self._post_process(body, style, code)

            # Sinonim bo'lmasligi kerak: ustma-ust tushsa — alohida burchak.
            if body and any(self._collides(body, item) for item in variants):
                swapped = self._fallback_post(style, code, safe_topic_html)
                swapped = self._post_process(swapped, style, code)
                if swapped and not any(self._collides(swapped, item) for item in variants):
                    body, source = swapped, "fallback"
                elif swapped:
                    body = self._diversify(swapped, style, code)
            if not body:
                continue

            variants.append(PostVariant(
                index=position, style=style.key, emoji=style.emoji,
                label=style.t_label(code), angle=style.t_angle(code),
                content=body, source=source,
            ))

            if outcome.error_code in {"CANCELLED", "QUEUE_FULL"}:
                fatal_code, fatal_error = outcome.error_code, outcome.error
                break

        if not variants:
            await self.release_quota(ticket)
            return VariantsResult(
                success=False, lang=code, topic=clean_topic,
                provider_used=used_providers[0] if used_providers else "none",
                cost=ticket.cost, reservation_id=ticket.reservation_id,
                quota=ticket.as_dict(),
                error=fatal_error or "generation_failed",
                error_code=fatal_code or "GENERATION_FAILED",
            )

        provider = used_providers[0] if used_providers else "MockFallback"
        # 💳 Hech bo'lmasa BITTA variant AI'dan chiqsa — bron saqlanadi;
        # 5 tasi ham fallback bo'lsa (AI umuman ishlamadi) pul qaytariladi.
        paid = any(variant.source == "ai" for variant in variants)
        refund_issued = False
        if not paid:
            refund_issued = await self.release_quota(ticket)
            if refund_issued:
                ticket.cost = 0

        chunks = self.render([variant.render() for variant in variants],
                             limit=CHUNK_SAFE_LIMIT)
        self._log("variantlar tayyor (user=%s, count=%s, lang=%s)",
                  user_id, len(variants), code)
        return VariantsResult(
            success=True,
            variants=variants,
            chunks=chunks,
            lang=code,
            topic=clean_topic,
            provider_used=provider,
            cost=ticket.cost,
            reservation_id=ticket.reservation_id,
            quota=ticket.as_dict(),
            paid=paid,
            refund_issued=refund_issued,
            fallback_used=any(variant.source == "fallback" for variant in variants),
            error=fatal_error,
            error_code=fatal_code,
        )

    # -- ichiy mexanizm ----------------------------------------------------
    @staticmethod
    def _fallback_post(style: VariantStyle, lang: str, topic_html: str) -> str:
        """Uslub bankidagi deterministik matn (AI javob bermaganda)."""
        from .smm_mock import variant_post
        return variant_post(style.key, lang, topic_html)

    @staticmethod
    def _post_process(body: str, style: VariantStyle, lang: str) -> str:
        """Tozalash, sanitizer va hashtag kafolati."""
        text = str(body or "").strip()
        if not text:
            return ""
        text = sanitize_html(text, VARIANT_BODY_LIMIT)
        if len(strip_html(text)) < 20:
            return ""
        return ensure_hashtags(text, style.hashtags, minimum=3, maximum=5)

    @staticmethod
    def _collides(body: str, existing: PostVariant) -> bool:
        """Ikki variantning bir xilligini aniqlash (iz + Jaccard)."""
        if fingerprint(body) == fingerprint(existing.content):
            return True
        return same_content(body, existing.content, threshold=0.9)

    @staticmethod
    def _diversify(body: str, style: VariantStyle, lang: str) -> str:
        """Oxirgi chora: burchak qatorini qo'shib, matnni noyob qilish."""
        marker = lang_text({
            "uz": f"Bu variant — {style.t_label(lang)} burchagi uchun maxsus yozildi.",
            "ru": f"Этот вариант написан специально под угол «{style.t_label(lang)}».",
            "en": f"This variant is written for the “{style.t_label(lang)}” angle only.",
        }, lang, "")
        return sanitize_html(f"{body}\n\n<i>{escape_literal(marker)}</i>", VARIANT_BODY_LIMIT)


#: Moduldagi standart namuna (handler/testlar uchun).
default_generator = MultiVariantGenerator()


async def generate_post_variants(user_id: int | None, topic: str, lang: str = "uz",
                                 **kwargs: Any) -> VariantsResult:
    """Yordamchi funksiya: ``MultiVariantGenerator().generate(...)``."""
    return await MultiVariantGenerator().generate(user_id, topic, lang, **kwargs)


__all__ = [
    "VARIANT_STYLES",
    "VARIANT_STYLE_KEYS",
    "VARIANT_STYLE_INDEX",
    "VARIANT_COUNT",
    "VariantStyle",
    "PostVariant",
    "VariantsResult",
    "MultiVariantGenerator",
    "build_variant_prompt",
    "resolve_style",
    "styles_for",
    "generate_post_variants",
    "default_generator",
]
