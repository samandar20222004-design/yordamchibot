"""🔄 CONTENT REPURPOSE — 49-band (PHASE 11).

Mavjud kontentni (yoki mavzuni) **5 ta platforma formatiga** moslashtirish:

=====  ==================  ==================================================
  #      platforma          Qat'iy format shartlari (lokal kafolatlanadi)
=====  ==================  ==================================================
 1     📢 Telegram Post     qalin hook, 2-4 abzats, 3-4 punkt, CTA, 3-5 hashtag
 2     📸 Instagram Caption 1 qator hook, ≤2200 belgi, alohida hashtag bloki
 3     🖼 Stories ssenariy   3-5 slayd, har birida BITTA gap (≤120 belgi), sticker
 4     🎬 Reels/Shorts       0-3s hook, sahnalar taymingi bilan, yakunda CTA
 5     📣 Reklama matni      Headline/Primary/Description/CTA (Meta limitlari)
=====  ==================  ==================================================

Nega «formatlash» lokal? Chunki platforma talablari — kontrakt: Instagram
caption 2200 belgidan oshsa post yopilmaydi, Stories slaydi 120 belgiga
sig'masa matn kesilib qoladi, Reels hook'i 3 sekunddan uzin bo'lsa video
to'xtatilmaydi. Model bu chegaralarni «taxminan» biladi, shuning uchun:

* AI har bir platforma uchun **matn yadrosini** (hook, formulalar, ohang)
  beradi — alohida prompt, alohida uslub ko'rsatmasi bilan;
* keyin shu yadro ``format_*`` funksiya orqali platformaning qat'iy
  strukturasiga joylanadi (sarlavha, slaydlar, tayminglar, Meta maydonlari);
* AI javobisiz ham (mock/offline) struktura buzilmaydi — matn manbai
  foydalanuvchi posti yoki deterministik banka bo'ladi.

Barcha chiqishlar ``sanitize_html`` (Phase 2) dan o'tadi va Telegram 4096
chegarasi bilan chunklanadi. Kvota: butun 5 platformali batch uchun BITTA
atomik bron (Phase 2).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from .smm_common import (
    CHUNK_SAFE_LIMIT,
    DEFAULT_LANG,
    SMMFeatureService,
    TELEGRAM_TEXT_LIMIT,
    bold,
    clip,
    ensure_hashtags,
    escape_literal,
    extract_hashtags,
    fingerprint,
    html_length,
    lang_text,
    normalize_lang,
    plain_sentences,
    same_content,
    sanitize_html,
    strip_hashtags,
    strip_html,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PLATFORMA QAT'IY CHEKLOVLARI
# ---------------------------------------------------------------------------
#: Telegram posti — vizual matn chegarasi (xabar bloki uchun zaxira bilan).
TELEGRAM_SAFE = 3600
#: Instagram caption chegarasi (bio havolasi va hashtag bloki bilan).
INSTAGRAM_CAPTION_LIMIT = 2200
#: Stories: har bir slaydda maksimum belgi va slaydlar soni.
STORIES_SLIDE_LIMIT = 120
STORIES_SLIDES_MIN, STORIES_SLIDES_MAX = 3, 5
#: Reels/Shorts: umumiy davomiylik va hook uzunligi.
REELS_MAX_SECONDS = 60
REELS_HOOK_MAX_CHARS = 90
#: Reklama (Meta) maydonlari.
AD_HEADLINE_LIMIT = 40
AD_PRIMARY_LIMIT = 125
AD_DESCRIPTION_LIMIT = 30
AD_BUTTON_LIMIT = 20

_CTA_MARKERS = {
    "uz": ("👉", "buyurtma", "yozing", "murojaat", "hoziroq", "obuna", "o'ting",
           "batafsil", "🔗", "📞", "ismatng", "yuboring"),
    "ru": ("👉", "закаж", "напиш", "перейд", "ссылк", "подпиш", "подробнее",
           "☎", "📞", "🔗"),
    "en": ("👉", "order", "message", "contact", "click", "subscribe", "dm ",
           "learn more", "🔗", "📞"),
}

_HASHTAG_BANK = {
    "uz": ("#smm", "#kontent", "#foydali", "#maslahat", "#biznes"),
    "ru": ("#smm", "#контент", "#полезно", "#совет", "#бизнес"),
    "en": ("#smm", "#content", "#tips", "#strategy", "#business"),
}


@dataclass(frozen=True)
class RepurposePlatform:
    """Bitta platforma formati (kontrakt + AI ko'rsatmasi)."""

    key: str
    emoji: str
    order: int
    label: dict
    spec: dict

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_spec(self, lang: Any) -> str:
        return lang_text(self.spec, lang, "")


REPURPOSE_PLATFORMS: tuple[RepurposePlatform, ...] = (
    RepurposePlatform(
        key="telegram", emoji="📢", order=1,
        label={"uz": "Telegram Post", "ru": "Пост для Telegram", "en": "Telegram Post"},
        spec={
            "uz": ("Telegram kanali posti: 1-qatorda qalin hook, 2-4 qisqa "
                   "abzats, ✅ bilan 3-4 punkt, oxirida bitta aniq CTA va 3-5 "
                   "hashtag."),
            "ru": ("Пост для Telegram-канала: жирный хук, 2-4 коротких абзаца, "
                   "3-4 пункта с ✅, один чёткий CTA и 3-5 хэштегов в конце."),
            "en": ("Telegram channel post: bold hook, 2-4 short paragraphs, 3-4 "
                   "✅ bullets, one clear CTA and 3-5 hashtags at the end."),
        },
    ),
    RepurposePlatform(
        key="instagram", emoji="📸", order=2,
        label={"uz": "Instagram Caption", "ru": "Caption для Instagram", "en": "Instagram Caption"},
        spec={
            "uz": ("Instagram caption: BIRINCHI qatorda emoji bilan kuchli hook "
                   "(qolgan qatorlarda takrorlanmasin), 2-3 qisqa abzats, "
                   "«saqlab oling / yuboring» chaqrig'i, hashtaglar alohida "
                   "blokda. Rasmiy ohang yo'q."),
            "ru": ("Caption для Instagram: СИЛЬНЫЙ хук в первой строке (не "
                   "повторять её дальше), 2-3 коротких абзаца, призыв «сохрани "
                   "и отправь другу», хэштеги отдельным блоком. Без канцелярита."),
            "en": ("Instagram caption: a strong hook on the FIRST line (don't "
                   "repeat it), 2-3 short paragraphs, a save-and-share ask, "
                   "hashtags in a separate block. No corporate tone."),
        },
    ),
    RepurposePlatform(
        key="stories", emoji="🖼", order=3,
        label={"uz": "Stories ssenariy", "ru": "Сценарий Stories", "en": "Stories script"},
        spec={
            "uz": ("Stories ssenariysi: har bir slaydda FAQAT BITTA gap, "
                   "tartib: muammo → dalil → yechim → harakatga chaqiriq. "
                   "Slayd matni 120 belgidan oshmasin, stiker/voprosnik "
                   "ko'rsatmasi bilan."),
            "ru": ("Сценарий Stories: ОДНА мысль на слайд, порядок: боль → "
                   "доказательство → решение → действие. Не длиннее 120 "
                   "символов, с указанием стикера."),
            "en": ("Stories script: ONE line per slide in the order pain → "
                   "proof → solution → action, max 120 characters, with a "
                   "sticker hint."),
        },
    ),
    RepurposePlatform(
        key="reels", emoji="🎬", order=4,
        label={"uz": "Reels/Shorts ssenariy", "ru": "Сценарий Reels/Shorts", "en": "Reels/Shorts script"},
        spec={
            "uz": ("Reels/Shorts hook-ssenariysi: 0-3s da «scroll-stopper» "
                   "jumla, keyin tez sahnalar (muammo, dalil, natija), oxirida "
                   "CTA va overlay yozuvi. Har bir sahna taymingi bilan."),
            "ru": ("Сценарий Reels/Shorts: в 0-3s фраза-стопер, затем быстрые "
                   "сцены (боль, доказательство, результат), в конце CTA и "
                   "текст на плашке. Для каждой сцены — тайминг."),
            "en": ("Reels/Shorts script: a scroll-stopper line in 0-3s, then "
                   "fast scenes (pain, proof, result), a closing CTA and an "
                   "on-screen caption. Every scene carries its timing."),
        },
    ),
    RepurposePlatform(
        key="ads", emoji="📣", order=5,
        label={"uz": "Reklama matni", "ru": "Рекламный текст", "en": "Ad copy"},
        spec={
            "uz": ("Reklama matni: muammo → yechim → taklif; Headline 40, "
                   "Primary text 125, Description 30 belgidan oshmasin; bitta "
                   "tugma matni (CTA)."),
            "ru": ("Рекламный текст: боль → решение → оффер; Headline ≤40, "
                   "Primary ≤125, Description ≤30 символов; одна кнопка CTA."),
            "en": ("Ad copy: pain → solution → offer; Headline ≤40, Primary "
                   "≤125, Description ≤30 characters; one CTA button label."),
        },
    ),
)

REPURPOSE_PLATFORM_KEYS: tuple[str, ...] = tuple(p.key for p in REPURPOSE_PLATFORMS)
#: Eski sinonimlar ham tanib oladi (UI/eski callback qatorlari uchun).
_PLATFORM_ALIASES = {
    "tg": "telegram", "post": "telegram", "telegram_post": "telegram",
    "insta": "instagram", "ig": "instagram", "caption": "instagram",
    "story": "stories", "stories_script": "stories",
    "reels": "reels", "shorts": "reels", "tiktok": "reels", "video": "reels",
    "ad": "ads", "advert": "ads", "reklama": "ads", "реклама": "ads",
}


def resolve_platform(value: Any) -> RepurposePlatform | None:
    if isinstance(value, RepurposePlatform):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    for platform in REPURPOSE_PLATFORMS:
        if raw == platform.key:
            return platform
    alias = _PLATFORM_ALIASES.get(raw)
    if alias:
        for platform in REPURPOSE_PLATFORMS:
            if platform.key == alias:
                return platform
    for platform in REPURPOSE_PLATFORMS:
        if platform.key in raw or platform.emoji in raw:
            return platform
    return None


def platforms_for(values: Sequence[str] | None) -> tuple[RepurposePlatform, ...]:
    if not values:
        return REPURPOSE_PLATFORMS
    picked: list[RepurposePlatform] = []
    for value in values:
        platform = resolve_platform(value)
        if platform is not None and platform not in picked:
            picked.append(platform)
    return tuple(picked) or REPURPOSE_PLATFORMS


def build_repurpose_prompt(source_text: str, platform: RepurposePlatform,
                            lang: str = "uz") -> str:
    """Platforma uchun AI topshirig'i (intent: CREATE_POST yo'nalishida)."""
    code = normalize_lang(lang)
    digest = build_digest(source_text, code)
    lead = {
        "uz": "Mavjud kontentni quyidagi platforma formatiga moslashtiring "
              "(yangi post yaratilmaydi — mazmun saqlanadi).",
        "ru": "Адаптируйте существующий контент под формат платформы "
              "(новый смысл не придумывайте, сохраните содержание).",
        "en": "Adapt the existing content to this platform format — keep the "
              "meaning, do not invent new claims.",
    }[code]
    topic = {
        "uz": f"Kontent: {escape_literal(clip(digest.headline, 260))}",
        "ru": f"Контент: {escape_literal(clip(digest.headline, 260))}",
        "en": f"Content: {escape_literal(clip(digest.headline, 260))}",
    }[code]
    return "\n".join([
        f"[SMM TASK: repurpose — target platform: {platform.key}]",
        lead,
        topic,
        f"Format: {platform.emoji} {platform.t_label(code)}",
        platform.t_spec(code),
        "Telegram HTML: <b> va <i> ruxsat, markdown (**, ##) TAQIQLANADI.",
    ])


# ---------------------------------------------------------------------------
# MANBA MATN «DIGJESTI» — platforma formatlovchilari shu asosda quradi
# ---------------------------------------------------------------------------
@dataclass
class SourceDigest:
    """Manba kontentning tahlil qilingan, xavfsiz ko'rinishi."""

    headline: str = ""
    sentences: list = field(default_factory=list)
    bullets: list = field(default_factory=list)
    hashtags: list = field(default_factory=list)
    links: list = field(default_factory=list)
    has_cta: bool = False
    chars: int = 0

    @property
    def body_sentences(self) -> list[str]:
        return self.sentences[:6]

    def first_bulletish(self) -> str:
        for item in self.bullets or self.sentences:
            if len(item) >= 12:
                return item
        return ""


#: Havola / manzil / telefon — platforma formatlari shu «kontakt qatorini»
#: alohida chizadi (IG da bio, Stories da link-sticker, Ads da tugma).
_LINK_RE = re.compile(r"(?:https?://\S+|t\.me/[A-Za-z0-9_+/]+|@[A-Za-z0-9_]{3,}"
                      r"|\+\d[\d\s()\-]{7,17})")
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-•*✅✔🔹▪️]|\d+[.)])\s+(?P<text>.+?)\s*$")


def build_digest(source_text: Any, lang: str = "uz") -> SourceDigest:
    """Matndan sarlavha/punkt/hashtag/havolani ajratish (hech qachon yiqilmaydi)."""
    raw = str(source_text or "").strip()
    if not raw:
        return SourceDigest()
    plain = strip_html(raw)
    lines = [line.strip() for line in re.split(r"\n+", plain) if line.strip()]
    headline = ""
    for line in lines:
        if 8 <= len(line) <= 160:
            headline = line.strip(" .—:")
            break
    if not headline:
        headline = clip(plain, 120).rstrip(" .—:")

    bullets: list[str] = []
    for line in lines:
        match = _BULLET_LINE_RE.match(line)
        if match:
            item = clip(match.group("text"), 160)
            if item:
                bullets.append(item)
    sentences = plain_sentences(raw, min_len=16, max_items=10)
    for item in sentences:
        if len(bullets) >= 4:
            break
        if item != headline and item not in bullets:
            bullets.append(clip(item, 160))

    code = normalize_lang(lang)
    cta_markers = _CTA_MARKERS.get(code, _CTA_MARKERS["uz"])
    lowered = plain.lower()
    return SourceDigest(
        headline=clip(headline, 160),
        sentences=sentences,
        bullets=bullets[:4],
        hashtags=extract_hashtags(raw)[:8],
        links=[clip(link, 120) for link in _LINK_RE.findall(raw)[:2]],
        has_cta=any(marker in lowered for marker in cta_markers),
        chars=len(plain),
    )


def _fallback_cta(lang: str, platform_key: str) -> str:
    code = normalize_lang(lang)
    table = {
        "uz": "👉 Batafsil ma'lumot uchun bizga yozing — javob beramiz.",
        "ru": "👉 Напишите нам, чтобы получить подробности — ответим.",
        "en": "👉 Message us for the full details — we'll reply.",
    }
    if platform_key == "instagram":
        table = {
            "uz": "📌 Saqlab oling va do'stingizga yuboring — havola bio'da.",
            "ru": "📌 Сохраните и отправьте другу — ссылка в профиле.",
            "en": "📌 Save it and send to a friend — link in bio.",
        }
    elif platform_key == "ads":
        table = {
            "uz": "🛒 Buyurtma berish",
            "ru": "🛒 Заказать",
            "en": "🛒 Order now",
        }
    return table[code]


def _ai_or_source(ai_text: str, digest: SourceDigest, lang: str) -> list[str]:
    """Platforma matnining qatorlari: avval AI, bo'lmasa manba/post banki.

    Sarlavha bilan takrorlanuvchi va hashtagli qatorlar chiqib ketadi —
    aks holda caption birinchi qatorni ikki marta yozib chiqadi.
    """
    from .smm_mock import platform_body
    body_source = strip_hashtags(strip_html(ai_text)) if ai_text else ""
    if not body_source:
        body_source = platform_body("telegram", lang)
    sentences = plain_sentences(body_source, min_len=14, max_items=6)
    head_print = fingerprint(digest.headline)
    unique: list[str] = []
    seen: set[str] = set()
    for item in sentences:
        current = fingerprint(item)
        if not current or current == head_print or current in seen:
            continue
        if same_content(item, digest.headline, threshold=0.85):
            continue
        seen.add(current)
        unique.append(item)
    if not unique:
        unique = [item for item in (digest.body_sentences or [clip(body_source, 200)]) if item]
    return unique


# ---------------------------------------------------------------------------
# FORMATLAGICHLAR (har biri qat'iy kontrakt kafolatlaydi)
# ---------------------------------------------------------------------------
def format_telegram(ai_text: str, digest: SourceDigest, lang: str) -> dict:
    """📢 Telegram Post — hook + abzats + punktlar + CTA + hashtag."""
    code = normalize_lang(lang)
    lines = _ai_or_source(ai_text, digest, code)
    blocks = [bold(digest.headline)]
    lead = lines[0] if lines else digest.headline
    blocks.append(escape_literal(lead))
    bullets: list[str] = []
    for item in (digest.bullets or []) + lines[1:]:
        if len(bullets) >= 4:
            break
        if fingerprint(item) == fingerprint(digest.headline) or item in bullets:
            continue
        bullets.append(item)
    if bullets:
        blocks.append(bold({"uz": "📌 Asosiy punktlar", "ru": "📌 Ключевые пункты",
                           "en": "📌 Key points"}[code]) + "\n" +
                      "\n".join(f"✅ {escape_literal(clip(item, 160))}" for item in bullets))
    cta = _fallback_cta(code, "telegram") if not digest.has_cta else ""
    tail = digest.links[0] if digest.links else ""
    cta_block = "\n".join(item for item in (cta, tail) if item)
    if cta_block:
        blocks.append(cta_block)
    text = ensure_hashtags("\n\n".join(blocks), _HASHTAG_BANK[code], 3, 5)
    return {
        "content": text,
        "blocks": bullets,
        "meta": {"cta_present": bool(cta_block or digest.has_cta),
                 "hashtags": len(extract_hashtags(text)),
                 "links": list(digest.links)},
    }


def format_instagram(ai_text: str, digest: SourceDigest, lang: str) -> dict:
    """📸 Instagram Caption — hook, qisqa matn, alohida hashtag bloki."""
    code = normalize_lang(lang)
    lines = _ai_or_source(ai_text, digest, code)
    hook = clip(re.sub(r"^[^\w]+", "", digest.headline), 124)
    body = [escape_literal(clip(line, 200)) for line in lines[:3]]
    caption_plain = "\n\n".join([hook] + body + [_fallback_cta(code, "instagram")])
    # Hashtag bloki alohida qatorda (IG amaliyoti) — 5..10 dona.
    tags = list(dict.fromkeys([tag for tag in digest.hashtags if len(tag) > 2]))
    for tag in _HASHTAG_BANK[code]:
        if len(tags) >= 7:
            break
        if tag not in tags:
            tags.append(tag)
    tag_block = " ".join(tags[:10])
    body_budget = INSTAGRAM_CAPTION_LIMIT - len(tag_block) - 2
    while html_length(f"{caption_plain}\n\n{tag_block}") > INSTAGRAM_CAPTION_LIMIT and len(body) > 1:
        body.pop()
        caption_plain = "\n\n".join([hook] + body + [_fallback_cta(code, "instagram")])
    if html_length(caption_plain) > max(200, body_budget):
        caption_plain = clip(caption_plain, max(200, body_budget))
    content = f"{caption_plain}\n\n{tag_block}" if tag_block else caption_plain
    return {
        "content": content,
        "blocks": [hook] + body,
        "meta": {"caption_chars": html_length(content),
                 "hashtag_count": len(tags[:10]),
                 "hook_first_line": hook,
                 "link_in_bio": True},
    }


def format_stories(ai_text: str, digest: SourceDigest, lang: str) -> dict:
    """🖼 Stories ssenariysi — 3-5 slayd, har birida BITTA gap + stiker."""
    code = normalize_lang(lang)
    roles = {
        "uz": ["Muammo (hook)", "Dalil", "Yechim", "Isbot/reviu", "Harakat (CTA)"],
        "ru": ["Боль (хук)", "Доказательство", "Решение", "Отзыв", "Действие (CTA)"],
        "en": ["Pain (hook)", "Proof", "Solution", "Review", "Action (CTA)"],
    }[code]
    stickers = {
        "uz": ["Stiker: savol", "Stiker: poll — 2 variant", "Stiker: hisoblagich",
               "Stiker: link", "Stiker: savol"],
        "ru": ["Стикер: вопрос", "Стикер: опрос — 2 варианта", "Стикер: таймер",
               "Стикер: ссылка", "Стикер: вопрос"],
        "en": ["Sticker: question", "Sticker: poll — 2 options", "Sticker: countdown",
               "Sticker: link", "Sticker: question"],
    }[code]
    lines = _ai_or_source(ai_text, digest, code)
    # Oxirgi slayd doim harakatga chaqiriq — shu sababli pooldan alohida.
    cta_line = clip(_fallback_cta(code, "telegram"), STORIES_SLIDE_LIMIT)
    pool = [clip(item, STORIES_SLIDE_LIMIT) for item in ([digest.headline] + lines) if item]
    pool = [item for item in dict.fromkeys(pool) if item]
    wanted = max(STORIES_SLIDES_MIN, min(STORIES_SLIDES_MAX, len(pool) + 1))

    slides: list[dict] = []
    taken: set[str] = set()
    cursor = 0
    for index in range(wanted - 1):
        text = ""
        for attempt in range(cursor, cursor + max(3, len(pool))):
            if not pool:
                break
            candidate = pool[attempt % len(pool)]
            if candidate.lower() not in taken:
                text = candidate
                taken.add(candidate.lower())
                cursor = attempt + 1
                break
        if not text:
            text = clip(f"{roles[index % len(roles)]} — {digest.headline}",
                        STORIES_SLIDE_LIMIT)
        slides.append({
            "index": index + 1,
            "role": roles[index % len(roles)],
            "text": text,
            "sticker": stickers[index % len(stickers)],
        })
    slides.append({
        "index": len(slides) + 1,
        "role": roles[-1],
        "text": cta_line,
        "sticker": stickers[-1],
    })

    rendered_parts = []
    for slide in slides:
        header = f"{slide['index']}/{len(slides)} \u00b7 {slide['role']}"
        rendered_parts.append(
            f"{bold('🖼 ' + escape_literal(header))}\n"
            f"{escape_literal(slide['text'])}\n"
            f"<i>{escape_literal(slide['sticker'])}</i>"
        )
    return {
        "content": "\n\n".join(rendered_parts),
        "blocks": slides,
        "meta": {"slides": len(slides),
                 "slide_limit": STORIES_SLIDE_LIMIT,
                 "duration_sec": len(slides) * 4},
    }


#: Sahna taymingi formati (model javobini tekshirish uchun).
_TIME_RE = re.compile(r"^\d+-\d+s$")


_SHOTS = {
    "uz": ["yupqa plan, ko'z bilan kontakt", "qo'l bilan ko'rsatish",
           "ekran/qadoq close-up", "raqam/foiz chiqadi", "muhit, yozuv ustida"],
    "ru": ["крупный план, контакт глазами", "показываем руками",
           "экран/упаковка крупно", "появляется цифра", "окружение, текст поверх"],
    "en": ["tight shot, eye contact", "hands-on demo",
           "screen/package close-up", "number pops on screen", "environment with caption"],
}


def format_reels(ai_text: str, digest: SourceDigest, lang: str) -> dict:
    """🎬 Reels/Shorts hook-ssenariysi — sahnalar + tayming + overlay."""
    code = normalize_lang(lang)
    lines = _ai_or_source(ai_text, digest, code)
    hook = clip(re.sub(r"^[^\w]+", "", digest.headline), REELS_HOOK_MAX_CHARS)
    scene_roles = {
        "uz": [("Hook", "0-3s"), ("Muammo", "3-9s"), ("Dalil", "9-18s"),
               ("Natija", "18-25s"), ("CTA", "25-30s")],
        "ru": [("Хук", "0-3s"), ("Боль", "3-9s"), ("Доказательство", "9-18s"),
               ("Результат", "18-25s"), ("CTA", "25-30s")],
        "en": [("Hook", "0-3s"), ("Pain", "3-9s"), ("Proof", "9-18s"),
               ("Result", "18-25s"), ("CTA", "25-30s")],
    }[code]
    shots = _SHOTS[code]
    pool = [clip(item, 160) for item in [hook] + lines if item]
    scenes: list[dict] = []
    for position, (role, timing) in enumerate(scene_roles):
        # Model yoki kengaytma noto'g'ri tayming bersa — tartiblangan
        # «N-Ms» qatorini o'zimiz hisoblaymiz (kontrakt buzilmasligi uchun).
        if not _TIME_RE.match(str(timing or "")):
            timing = f"{position * 6}-{(position + 1) * 6}s"
        text = pool[position] if position < len(pool) else f"{role}: {hook}"
        scenes.append({
            "index": position + 1,
            "role": role,
            "time": timing,
            "text": clip(strip_html(text), 160),
            "overlay": clip(f"{role.upper()} \u2014 {hook}", 40),
            "shot": shots[position % len(shots)],
        })
    parts = []
    for scene in scenes:
        header = f"{scene['time']} \u00b7 {scene['role']}"
        parts.append(
            f"{bold('🎬 ' + escape_literal(header))}\n"
            f"{escape_literal(scene['text'])}\n"
            f"<i>Overlay: {escape_literal(scene['overlay'])} \u00b7 "
            f"{escape_literal(scene['shot'])}</i>"
        )
    tail = {
        "uz": "⏱ Davomiylik: 30s · Vertikal 9:16 · Birinchi 3 sekund ovozsiz ham tushunarli",
        "ru": "⏱ Длительность: 30s · Вертикаль 9:16 · Первые 3 секунды понятны без звука",
        "en": "⏱ Length: 30s · Vertical 9:16 · First 3 seconds work on mute",
    }[code]
    return {
        "content": "\n\n".join(parts) + "\n\n" + escape_literal(tail),
        "blocks": scenes,
        "meta": {"scenes": len(scenes),
                 "hook": hook,
                 "total_seconds": REELS_MAX_SECONDS,
                 "timings": [scene["time"] for scene in scenes]},
    }


def format_ads(ai_text: str, digest: SourceDigest, lang: str) -> dict:
    """📣 Reklama matni — Meta maydonlari (headline/primary/description/CTA)."""
    code = normalize_lang(lang)
    lines = _ai_or_source(ai_text, digest, code)
    headline = clip(re.sub(r"^[^\w]+", "", digest.headline), AD_HEADLINE_LIMIT)
    primary = clip(lines[0] if lines else digest.headline, AD_PRIMARY_LIMIT)
    description = clip(lines[1] if len(lines) > 1 else
                      {"uz": "Cheklangan muddat — hoziroq tanlang",
                       "ru": "Количество мест ограничено",
                       "en": "Limited availability"}[code], AD_DESCRIPTION_LIMIT)
    button = {
        "uz": "Buyurtma berish",
        "ru": "Заказать",
        "en": "Order now",
    }[code][:AD_BUTTON_LIMIT]
    blocks = [
        f"{bold('Headline')}: {escape_literal(headline)}",
        f"{bold('Primary text')}: {escape_literal(primary)}",
        f"{bold('Description')}: {escape_literal(description)}",
        f"{bold('CTA tugmasi')}: {escape_literal(button)}",
    ]
    return {
        "content": "\n".join(blocks),
        "blocks": blocks,
        "meta": {"headline": headline, "headline_chars": len(headline),
                 "primary_text": primary, "primary_chars": len(primary),
                 "description": description, "description_chars": len(description),
                 "cta_button": button, "cta_chars": len(button)},
    }


_PLATFORM_FORMATTERS = {
    "telegram": format_telegram,
    "instagram": format_instagram,
    "stories": format_stories,
    "reels": format_reels,
    "ads": format_ads,
}


# ---------------------------------------------------------------------------
# NATIJA MODELLARI
# ---------------------------------------------------------------------------
@dataclass
class RepurposeOutput:
    """Bitta platformaga moslashtirilgan tayyor natija."""

    platform: str
    label: str
    emoji: str
    content: str
    blocks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    source: str = "ai"
    chars: int = 0

    def __post_init__(self) -> None:
        self.content = sanitize_html(self.content, TELEGRAM_TEXT_LIMIT)
        self.chars = html_length(self.content)

    def render(self) -> str:
        return sanitize_html(
            f"{bold(f'{self.emoji} {self.label}')}\n\n{self.content}",
            TELEGRAM_TEXT_LIMIT,
        )

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "label": self.label,
            "emoji": self.emoji,
            "content": self.content,
            "blocks": list(self.blocks),
            "meta": dict(self.meta),
            "source": self.source,
            "chars": self.chars,
            "message": self.render(),
        }


@dataclass
class RepurposeResult:
    """Repurpose batch natijasi (5 platforma)."""

    success: bool
    outputs: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    lang: str = DEFAULT_LANG
    provider_used: str = "none"
    cost: int = 0
    reservation_id: Any = None
    quota: dict = field(default_factory=dict)
    paid: bool = False
    refund_issued: bool = False
    fallback_used: bool = False
    error: str | None = None
    error_code: str | None = None

    def by_platform(self, platform: str) -> RepurposeOutput | None:
        for item in self.outputs:
            if item.platform == platform:
                return item
        return None

    def platforms(self) -> list[str]:
        return [item.platform for item in self.outputs]

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "platforms": self.platforms(),
            "lang": self.lang,
            "provider_used": self.provider_used,
            "cost": self.cost,
            "reservation_id": self.reservation_id,
            "quota": dict(self.quota),
            "paid": self.paid,
            "refund_issued": self.refund_issued,
            "fallback_used": self.fallback_used,
            "error": self.error,
            "error_code": self.error_code,
            "outputs": [item.as_dict() for item in self.outputs],
            "chunks": list(self.chunks),
        }


# ---------------------------------------------------------------------------
# XIZMAT
# ---------------------------------------------------------------------------
class ContentRepurposeService(SMMFeatureService):
    """Kontentni 5 platforma formatiga o'tkazish (49-band)."""

    feature = "repurpose"
    quota_operation = "magic_post:repurpose"
    quota_cost = 1

    async def repurpose(
        self,
        user_id: int | None,
        source_text: str,
        lang: str = DEFAULT_LANG,
        *,
        db_module: Any = None,
        platforms: Sequence[str] | None = None,
        orchestrator: Any = None,
    ) -> RepurposeResult:
        code = normalize_lang(lang)
        raw_source = str(source_text or "").strip()
        if len(strip_html(raw_source)) < 10:
            return RepurposeResult(
                success=False, lang=code, error="empty_source",
                error_code="INVALID_INPUT",
            )

        if orchestrator is not None:
            self._injected_orchestrator = orchestrator

        ticket = await self.acquire_quota(db_module, user_id)
        if not ticket.allowed:
            return RepurposeResult(
                success=False, lang=code,
                error=ticket.reason or "quota_denied",
                error_code="QUOTA_EXCEEDED" if not ticket.reason or ticket.reason in {
                    "insufficient_balance", "user_not_found",
                } else "QUOTA_UNAVAILABLE",
                quota=ticket.as_dict(),
            )

        digest = build_digest(raw_source, code)
        outputs: list[RepurposeOutput] = []
        used_providers: list[str] = []

        for platform in platforms_for(platforms):
            outcome = await self.ask(
                build_repurpose_prompt(raw_source, platform, code),
                user_id=user_id, lang=code,
                context={
                    "smm_mode": "REPURPOSE",
                    "smm_platform": platform.key,
                    "smm_topic": clip(digest.headline, 240),
                },
            )
            if outcome.provider and outcome.provider != "none":
                used_providers.append(outcome.provider)
            ai_text = outcome.text if outcome.usable else ""
            formatter = _PLATFORM_FORMATTERS.get(platform.key, format_telegram)
            try:
                payload = formatter(ai_text, digest, code)
            except Exception as exc:  # noqa: BLE001 — formatlash yiqilmasligi kerak
                logger.error("repurpose format xatosi (%s): %s", platform.key, exc)
                payload = format_telegram(ai_text, digest, code)
            outputs.append(RepurposeOutput(
                platform=platform.key, label=platform.t_label(code),
                emoji=platform.emoji, content=payload.get("content", ""),
                blocks=list(payload.get("blocks") or []),
                meta=dict(payload.get("meta") or {}),
                source="ai" if ai_text else "fallback",
            ))

        if not outputs:
            await self.release_quota(ticket)
            return RepurposeResult(success=False, lang=code, error="no_output",
                                   error_code="GENERATION_FAILED",
                                   quota=ticket.as_dict())

        paid = any(item.source == "ai" for item in outputs)
        refund_issued = False
        if not paid:
            refund_issued = await self.release_quota(ticket)
            if refund_issued:
                ticket.cost = 0

        chunks = self.render([item.render() for item in outputs], limit=CHUNK_SAFE_LIMIT)
        self._log("repurpose tayyor (user=%s, platforms=%s)", user_id,
                  ",".join(item.platform for item in outputs))
        return RepurposeResult(
            success=True,
            outputs=outputs,
            chunks=chunks,
            lang=code,
            provider_used=used_providers[0] if used_providers else "MockFallback",
            cost=ticket.cost,
            reservation_id=ticket.reservation_id,
            quota=ticket.as_dict(),
            paid=paid,
            refund_issued=refund_issued,
            fallback_used=any(item.source == "fallback" for item in outputs),
        )


default_repurpose = ContentRepurposeService()


async def repurpose_content(user_id: int | None, source_text: str,
                            lang: str = "uz", **kwargs: Any) -> RepurposeResult:
    """Yordamchi funksiya: ``ContentRepurposeService().repurpose(...)``."""
    return await ContentRepurposeService().repurpose(user_id, source_text, lang, **kwargs)


__all__ = [
    "REPURPOSE_PLATFORMS",
    "REPURPOSE_PLATFORM_KEYS",
    "RepurposePlatform",
    "RepurposeOutput",
    "RepurposeResult",
    "ContentRepurposeService",
    "SourceDigest",
    "build_digest",
    "build_repurpose_prompt",
    "format_telegram",
    "format_instagram",
    "format_stories",
    "format_reels",
    "format_ads",
    "resolve_platform",
    "platforms_for",
    "repurpose_content",
    "default_repurpose",
]
