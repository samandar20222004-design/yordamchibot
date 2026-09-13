"""Inline tugmalar uchun ``callback_data`` xavfsizligi (Telegram 64-bayt limiti).

Telegram Bot API `InlineKeyboardButton.callback_data` uchun **1..64 bayt**
(UTF-8) chegarasini belgilaydi. Chegaradan oshgan qiymat butun klaviaturani
``BadRequest: BUTTON_DATA_INVALID`` bilan rad ettiradi — ya'ni bitta uzun
tugma tufayli FOYDALANUVCHI XABARNI UMUMAN OLMAYDI.

Shu sababli barcha dinamik (kanal id, post id, emoji, action kabi qiymatlar
qo'shiladigan) callback'lar shu moduldagi :func:`cb` orqali quriladi:

    >>> cb(CB_CHANNEL_DELETE, -1001234567890)
    'ch_del:-1001234567890'

Kafolatlar:
  * natija hech qachon 64 baytdan oshmaydi (kerak bo'lsa oxirgi bo'lak
    UTF-8 chegaralarini buzmasdan qisqartiriladi va WARNING log yoziladi);
  * natija hech qachon bo'sh bo'lmaydi (Telegram bo'sh qiymatni ham rad etadi);
  * prefikslar qisqa va kanonik — pastdagi ``CB_*`` konstantalari yagona
    manba (single source of truth) bo'lib, handler ``pattern`` lari ham
    shulardan quriladi.
"""

import logging

logger = logging.getLogger(__name__)

# Telegram Bot API qat'iy chegarasi (bayt, UTF-8).
CALLBACK_DATA_MAX_BYTES = 64

# Dinamik qiymat qo'shiladigan callback'lar uchun prefiks byudjeti: prefiks
# o'zi 16 baytdan oshmasligi kerak — qolgan >=48 bayt payload (id/emoji) uchun.
CALLBACK_PREFIX_MAX_BYTES = 16

# ---------------------------------------------------------------------------
# Kanonik QISQA prefikslar
# ---------------------------------------------------------------------------
# Eslatma: `react:` prefiksi ATAYLAB o'zgartirilmagan — u kanallarga ALLAQACHON
# yuborilgan postlar tugmalarida yashaydi; nomini o'zgartirish eski postlardagi
# reaksiya tugmalarini o'lik qilib qo'yadi. U allaqachon 6 bayt — xavfsiz.

# Kanal boshqaruvi (avval: remove_channel: / tone_menu:)
CB_CHANNEL_DELETE = "ch_del:"
CB_CHANNEL_SETTINGS = "ch_set:"

# Rejalashtirilgan post kartochkasi (avval: edit_time: / edit_content: / ...)
CB_POST_TIME = "p_time:"
CB_POST_EDIT = "p_edit:"
CB_POST_BTN = "p_btn:"
CB_POST_REACT = "p_react:"
CB_POST_CANCEL = "p_cancel:"
# Navbatdagi postni ko'rish. Bu yerda ATAYLAB "p_view:" emas, mavjud "qview:"
# saqlangan: u allaqachon 6 bayt (p_view: dan ham qisqa) va navbat modulining
# qolgan callback'lari (qdel:/qpush:/qpage:) bilan bitta nom fazosida turadi.
CB_POST_VIEW = "qview:"

# Homiy kanallar (avval: del_sponsor:)
CB_SPONSOR_DELETE = "sp_del:"

# To'lov cheki moderatsiyasi (avval: receipt_appr: / receipt_rej:)
CB_RECEIPT_APPROVE = "rc_ok:"
CB_RECEIPT_REJECT = "rc_no:"

# Rasm moderatsiyasi (avval: check_photo:app: / check_photo:rej:)
CB_PHOTO_APPROVE = "cph:a:"
CB_PHOTO_REJECT = "cph:r:"

# 🖼 Rasm → post: 3 uslub variantidan birini tanlash (formal/friendly/concise)
CB_PHOTO_VARIANT = "photo_v:"

# 🎙 Kanal ovozi tahlili (AI) — kanal profil tugmasi
CB_CHANNEL_VOICE = "ch_voice:"

# Yangi post oqimidagi reaksiya tanlash (avval: npreact:tgl: / done / skip)
CB_REACT_TOGGLE = "nprt:t:"
CB_REACT_DONE = "nprt:done"
CB_REACT_SKIP = "nprt:skip"

# Kanal postidagi reaksiya hisoblagichi — O'ZGARMAYDI (eski postlar bilan mos).
CB_REACTION = "react:"

# 📊 Post Score & Improver (Killer Feature #4).
# ``ps_eval:<flow>`` — Magic Post / Voice / Image natijasidagi «📊 Baholash»
# tugmasi (flow = magic | voice | image); ``ps_ch:<idx>`` — kanal tanlash.
CB_POST_SCORE_EVAL = "ps_eval:"
CB_POST_SCORE_CHANNEL = "ps_ch:"
# Statik (payload'siz) post-score amallari.
CB_POST_SCORE_IMPROVE = "ps_improve"
CB_POST_SCORE_SEND = "ps_send"
CB_POST_SCORE_SCHEDULE = "ps_sched"
CB_POST_SCORE_NEW = "ps_new"
CB_POST_SCORE_SEND_ALL = "ps_chall"

#: Barcha kanonik prefikslar (test va audit uchun).
CANONICAL_PREFIXES = (
    CB_CHANNEL_DELETE,
    CB_CHANNEL_SETTINGS,
    CB_POST_TIME,
    CB_POST_EDIT,
    CB_POST_BTN,
    CB_POST_REACT,
    CB_POST_CANCEL,
    CB_POST_VIEW,
    CB_SPONSOR_DELETE,
    CB_RECEIPT_APPROVE,
    CB_RECEIPT_REJECT,
    CB_PHOTO_APPROVE,
    CB_PHOTO_REJECT,
    CB_PHOTO_VARIANT,
    CB_REACT_TOGGLE,
    CB_REACTION,
    # 📊 Post Score — dinamik payload qo'shiladigan prefikslar.
    CB_POST_SCORE_EVAL,
    CB_POST_SCORE_CHANNEL,
)


def callback_byte_len(data) -> int:
    """``callback_data`` ning UTF-8 dagi bayt uzunligi (None → 0)."""
    if data is None:
        return 0
    try:
        return len(str(data).encode("utf-8"))
    except Exception:  # pragma: no cover — str() deyarli hech qachon yiqilmaydi
        return CALLBACK_DATA_MAX_BYTES + 1


def is_callback_safe(data) -> bool:
    """Qiymat Telegram limitiga mos (1..64 bayt) ekanini tekshiradi."""
    size = callback_byte_len(data)
    return 1 <= size <= CALLBACK_DATA_MAX_BYTES


def truncate_callback_data(data, max_bytes: int = CALLBACK_DATA_MAX_BYTES) -> str:
    """Qiymatni UTF-8 chegaralarini buzmasdan ``max_bytes`` gacha qisqartiradi.

    Ko'p baytli belgi (emoji, kirill) o'rtasidan kesilmaydi — aks holda
    ``UnicodeDecodeError`` yoki buzilgan matn chiqadi.
    """
    text = "" if data is None else str(data)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def cb(prefix: str, *parts, sep: str = ":") -> str:
    """64-bayt kafolatli ``callback_data`` quradi.

    ``prefix`` odatda ``CB_*`` konstantasi (o'zida ``:`` bilan tugashi mumkin),
    ``parts`` — qo'shiladigan qiymatlar (id, action, emoji ...).

    Agar yig'ilgan qiymat 64 baytdan oshsa — oxirgi bo'lak xavfsiz kesiladi
    va WARNING log yoziladi (klaviatura BadRequest bilan yiqilmasligi uchun).
    """
    head = "" if prefix is None else str(prefix)
    tail_parts = [str(p) for p in parts if p is not None and str(p) != ""]

    if head and tail_parts and not head.endswith(sep):
        data = head + sep + sep.join(tail_parts)
    else:
        data = head + sep.join(tail_parts)

    if not data:
        # Bo'sh callback_data ham Telegram tomonidan rad etiladi.
        return "noop"

    if callback_byte_len(data) > CALLBACK_DATA_MAX_BYTES:
        safe = truncate_callback_data(data)
        logger.warning(
            "callback_data 64 baytdan oshdi va qisqartirildi: %r → %r", data, safe
        )
        data = safe or "noop"
    return data


def safe_callback_data(data) -> str:
    """Tayyor qiymatni limitga moslashtiradi (bo'sh bo'lsa ``noop``)."""
    return cb(data)


def pattern(prefix: str) -> str:
    """``CallbackQueryHandler`` uchun prefiksdan regex qoliplaydi."""
    import re as _re

    return r"^" + _re.escape(str(prefix))


def split_callback(data, maxsplit: int = -1) -> list:
    """``callback_data`` ni ``:`` bo'yicha xavfsiz ajratadi (None → [])."""
    if not data:
        return []
    text = str(data)
    return text.split(":", maxsplit) if maxsplit and maxsplit > 0 else text.split(":")
