"""🛡 Reklama birjasi: firibgarlikdan himoya (sof funksiyalar, DB/tarmoqsiz).

Tahlil faqat matnning o'ziga qaraydi va ikki xil natija beradi:
  * **to'sish (block)** — xabar umuman yuborilmaydi: karta raqami, kripto hamyon manzili (pul so'rashning asosiy yo'li),
    hamda yangi/birinchi xabarda havola (fishing/soxta sayt);
  * **ogohlantirish belgilari (flags)** — xabar yuboriladi, lekin oluvchiga ⚠️ ko'rsatiladi: oldindan to'lov so'rovi,
    shoshiltirish, «kafolatlangan daromad» kabi iboralar, havola.

Qoidalar ataylab konservativ: «yolg'on ogohlantirish» kamroq zarar, «o'tkazib yuborilgan firibgarlik» ko'proq.
Boshqa qatlamlar (DB): kunlik so'rov limiti, bir xil matn spami, global ban, egasining kunlik kirim limiti.
"""
from __future__ import annotations

import re

NEW_ACCOUNT_DAYS = 2
INBOUND_PER_DAY = 30
DUPLICATE_LIMIT = 2
USER_BAN_THRESHOLD = 3

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)
_APOS = dict.fromkeys(map(ord, "ʻʼ‘’`´"), "'")

_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){15,19}(?!\d)")
_WALLET = re.compile(r"\b(?:T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,60}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_LINK = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|bit\.ly|tinyurl|\b[a-z0-9-]{2,}\.(?:com|ru|uz|org|net|io|me|xyz|top|cc|ly|site|online|link)\b)")

_PREPAY = (
    "oldindan to'lov", "oldindan tolov", "oldindan pul", "avans", "garov", "zaklad", "kafolat puli", "pul o'tkazing",
    "pul tashlang", "kartaga tashlang", "kartamga", "to'lov qiling", "predoplat", "предоплат", "залог", "переведите",
    "скиньте на карту", "перевод на карту", "prepay", "advance payment", "deposit", "send money", "wire transfer",
    "transfer to my card",
)
_PRESSURE = (
    "shoshiling", "hoziroq", "tezroq to'lang", "oxirgi imkoniyat", "faqat bugun", "срочно", "прямо сейчас", "последний шанс",
    "только сегодня", "urgent", "right now", "last chance", "act now",
)
_SCAM = (
    "100% kafolat", "kafolatlangan daromad", "kafolatlangan foyda", "pul ishlash", "tez boyish", "investitsiya", "kripto",
    "usdt", "crypto", "bitcoin", "гарантированный доход", "гарантия дохода", "инвестиц", "быстрый заработок",
    "криптовалют", "guaranteed income", "guaranteed profit", "get rich", "free money", "like bosish", "лайки",
)


def _normalize(text: str) -> str:
    return (text or "").translate(_ZERO_WIDTH).translate(_APOS).lower()


def normalize_for_dup(text: str) -> str:
    """Bir xil matn spamini aniqlash uchun: kichik harf, bo'shliqlar bitta."""
    return re.sub(r"\s+", " ", _normalize(text)).strip()


def assess(text: str, *, first_message: bool = False, account_age_days: float | None = None,
           owner_sender: bool = False) -> dict:
    """Matnni tekshiradi. Qaytadi ``{"ok": bool, "reason": "card"|"wallet"|"link"|None, "flags": [...], "risk": ...}``.

    ``owner_sender`` — xabarni kanal egasi yozyapti (u o'z kanalining havolasini yuborishi mumkin: havola to'silmaydi).
    ``account_age_days`` — yuboruvchi hisobi yoshi (``None`` — noma'lum; yangi hisob qatoriga kirmaydi).
    """
    norm = _normalize(text)
    flags: set[str] = set()
    reason = None
    if _CARD.search(norm):
        reason = "card"
    elif _WALLET.search(text or ""):
        reason = "wallet"
    has_link = bool(_LINK.search(norm))
    if has_link:
        new_account = account_age_days is not None and account_age_days < NEW_ACCOUNT_DAYS
        if reason is None and not owner_sender and (first_message or new_account):
            reason = "link"
        else:
            flags.add("link")
    if any(k in norm for k in _PREPAY):
        flags.add("prepay")
    if any(k in norm for k in _PRESSURE):
        flags.add("pressure")
    if any(k in norm for k in _SCAM):
        flags.add("scam")
    risk = "low"
    if "prepay" in flags or "scam" in flags or "link" in flags:
        risk = "medium"
    if ("prepay" in flags and ("pressure" in flags or "scam" in flags or "link" in flags)) or ("scam" in flags and "pressure" in flags):
        risk = "high"
    return {"ok": reason is None, "reason": reason, "flags": sorted(flags), "risk": risk}


def pack_flags(flags: list[str]) -> str:
    return ",".join(sorted(set(flags)))[:80]


def unpack_flags(raw: str | None) -> list[str]:
    return [f for f in (raw or "").split(",") if f]


def warning_keys(flags: list[str]) -> list[str]:
    """Belgilardan ogohlantirish matn kalitlari (tarjima handlerda/frontendda)."""
    order = ("prepay", "scam", "pressure", "link")
    return [f for f in order if f in flags]
