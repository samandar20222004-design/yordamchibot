"""🧭 FAZA 17 — KANONIK NAVIGATSIYA STANDARTI (yagona ma'no qoidalari).

Loyihadagi HAR BIR inline va reply klaviatura tugmasi quyidagi qat'iy
ma'no qoidasiga bo'ysunadi:

    ┌──────────────────────────┬──────────────────────────────────────────┐
    │ Tugma (UZ)               │ MA'NO (faqat bitta vazifa)               │
    ├──────────────────────────┼──────────────────────────────────────────┤
    │ ◀️/⬅️ Orqaga             │ oldingi oyna (parent screen)             │
    │ ❌ Bekor qilish          │ joriy FSM harakatini to'xtatish          │
    │ 🏠/🔙 Asosiy menyu       │ bosh menyuga qaytish                     │
    │ ❌ Yopish                │ vaqtinchalik inline xabarni o'chirish    │
    └──────────────────────────┴──────────────────────────────────────────┘

QAT'IY QOIDA: bir xil oynada bir xil vazifani bajaruvchi IKKITA alohida
tugma paydo bo'lishi TAQIQLANADI (masalan, bitta klaviaturada ham «◀️
Orqaga», ham «⬅️ Orqaga»; yoki ikkita «❌ Yopish»).

Yagona manba (single source of truth):

  * yorliqlar — i18n kalitlari orqali (``btn_back`` / ``btn_cancel`` /
    ``btn_main_menu`` / ``cab_close``), UZ/RU/EN paritetda;
  * callback → semantika xaritasi — ``keyboards.callback_data``
    (``CALLBACK_SEMANTICS``, FAZA 19 registry bilan bitta joyda);
  * qoidabuzarlik detektori — :func:`find_nav_conflicts` (testlar ham,
    ishlab chiqish ham shu funksiya orqali klaviaturalarni tekshiradi).

Bu modul FAQAT standartni tasvirlaydi va quruvchi/yordamchi funksiyalarni
beradi; mavjud klaviaturalarning rendered matnlari O'ZGARMAYDI (uz
yorliqlari avvalgi qiymatlar bilan bir xil — regressiya yo'q).
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton

from locales.translations import get_text
from keyboards.callback_data import (
    NAV_SEMANTIC_BACK,
    NAV_SEMANTIC_CANCEL,
    NAV_SEMANTIC_CLOSE,
    NAV_SEMANTIC_HOME,
    callback_semantic,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kanonik yorliq kalitlari (i18n — uz/ru/en paritetida)
# ---------------------------------------------------------------------------
#: ◀️/⬅️ Orqaga — uz: «⬅️ Orqaga», ru: «⬅️ Назад», en: «⬅️ Back».
NAV_LABEL_KEY_BACK = "btn_back"
#: ❌ Bekor qilish — uz: «❌ Bekor qilish», ru: «❌ Отмена», en: «❌ Cancel».
NAV_LABEL_KEY_CANCEL = "btn_cancel"
#: 🏠/🔙 Asosiy menyu — uz: «🔙 Asosiy menyu», ru: «🔙 Главное меню»,
#: en: «🔙 Main menu» (routing ``🏠 asosiy menyu`` yozuvini ham taniydi —
#: ``middlewares.fsm_cleaner.START_AND_MENU_COMMANDS``).
NAV_LABEL_KEY_HOME = "btn_main_menu"
#: ❌ Yopish — uz: «❌ Yopish», ru: «❌ Закрыть», en: «❌ Close».
NAV_LABEL_KEY_CLOSE = "cab_close"

#: Semantika → i18n yorliq kaliti (yagona xarita).
NAV_LABEL_KEYS = {
    NAV_SEMANTIC_BACK: NAV_LABEL_KEY_BACK,
    NAV_SEMANTIC_CANCEL: NAV_LABEL_KEY_CANCEL,
    NAV_SEMANTIC_HOME: NAV_LABEL_KEY_HOME,
    NAV_SEMANTIC_CLOSE: NAV_LABEL_KEY_CLOSE,
}

#: Semantika → standart callback (context-specific bo'lsa None —
#: chaqiruvchi aniq callback uzatishi SHART).
NAV_DEFAULT_CALLBACKS = {
    NAV_SEMANTIC_BACK: None,          # parent oyna kontekstga bog'liq
    NAV_SEMANTIC_CANCEL: None,        # FSM oqimiga bog'liq (adm_cancel, mnp_cancel...)
    NAV_SEMANTIC_HOME: None,          # reply yorliq yoki studio_close kabi
    NAV_SEMANTIC_CLOSE: "close_msg",  # yagona yopish callback'i
}

#: Kanonik semantikalar (tartibi — hujjat/jadval tartibi).
NAV_SEMANTICS = (
    NAV_SEMANTIC_BACK,
    NAV_SEMANTIC_CANCEL,
    NAV_SEMANTIC_HOME,
    NAV_SEMANTIC_CLOSE,
)


def nav_label(semantic: str, lang: str = "uz") -> str:
    """Semantika bo'yicha kanonik (tilga mos) tugma yorlig'i."""
    key = NAV_LABEL_KEYS.get(semantic)
    if not key:
        return ""
    return get_text(key, lang)


def nav_button(semantic: str, callback: str | None = None, lang: str = "uz",
               **kwargs) -> InlineKeyboardButton:
    """Kanonik navigatsiya tugmasi quradi (yorliq i18n'dan, ma'no bir xil).

    Args:
        semantic: ``nav.*`` semantikasi (back/cancel/home/close).
        callback: callback_data; bo'sh bo'lsa semantik standart qiymat
            (faqat ``close`` uchun ``close_msg`` mavjud) ishlatiladi.
        lang: foydalanuvchi tili (uz/ru/en) — yorliq shu tilda chiziladi.
    """
    cb_data = callback or NAV_DEFAULT_CALLBACKS.get(semantic)
    if not cb_data:
        raise ValueError(
            f"nav_button: '{semantic}' semantikasi uchun callback SHART "
            "(parent oyna / FSM oqimi kontekstga bog'liq)"
        )
    return InlineKeyboardButton(nav_label(semantic, lang), callback_data=cb_data, **kwargs)


# ---------------------------------------------------------------------------
# Yorliq matni bo'yicha semantika aniqlash (3 til + ko'rinish variantlari)
# ---------------------------------------------------------------------------
_BACK_LABEL_TOKENS = ("orqaga", "назад", "back", "menyuga")
_CANCEL_LABEL_TOKENS = ("bekor qilish", "отмена", "cancel")
_CLOSE_LABEL_TOKENS = ("yopish", "закрыть", "close")
_HOME_LABEL_TOKENS = ("asosiy menyu", "главное меню", "main menu")


def _clean_label(text) -> str:
    """Yorliqni solishtirishga tayyorlaydi (emoji, probel, katta-kichik)."""
    if not text:
        return ""
    raw = str(text)
    # Boshidagi emoji/piktogrammalarni tashlab, faqat matn qoldiramiz.
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch in "ʻ'`- ":
            cleaned.append(ch)
    return " ".join("".join(cleaned).split()).lower().strip()


def classify_nav_label(text) -> str | None:
    """Tugma YORLIG'I bo'yicha navigatsiya semantikasi (yoki None).

    Qoidalar (birinchi mos — eng aniq):
      * «❌ Bekor qilish» (uz/ru/en)  → cancel
      * «❌ Yopish» (uz/ru/en)        → close
      * «🏠/🔙 Asosiy menyu»          → home
      * «◀️/⬅️ Orqaga / Menyuga»     → back
    """
    low = _clean_label(text)
    if not low:
        return None
    if any(t in low for t in _CANCEL_LABEL_TOKENS):
        return NAV_SEMANTIC_CANCEL
    if any(t in low for t in _CLOSE_LABEL_TOKENS):
        return NAV_SEMANTIC_CLOSE
    if any(t in low for t in _HOME_LABEL_TOKENS):
        return NAV_SEMANTIC_HOME
    if any(t in low for t in _BACK_LABEL_TOKENS):
        return NAV_SEMANTIC_BACK
    return None


def classify_nav_button(text, callback_data=None) -> str | None:
    """Tugmani (yorliq + callback) navigatsiya semantikasi bo'yicha aniqlaydi.

    Ikkala belgi ham bilsa va ular MOS KELMASA — yorliq (foydalanuvchi
    ko'radigan standart) ustuvor hisoblanadi va ``label`` qaytariladi;
    mos kelmaslik :func:`find_nav_conflicts` tomonidan QOIDABUZARLIK sifatida
    qayd etiladi.
    """
    label_sem = classify_nav_label(text)
    cb_sem = callback_semantic(callback_data) if callback_data else None
    if label_sem and cb_sem and label_sem != cb_sem:
        # Aniq yorliq ustuvor — lekin mosizlik qayd etiladi (detektor ko'radi).
        return label_sem
    return label_sem or cb_sem


def _iter_buttons(markup):
    """InlineKeyboardMarkup yoki qatorlar ro'yxatidan tugmalarni yig'adi."""
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None and isinstance(markup, (list, tuple)):
        rows = markup
    for row in rows or []:
        for btn in row:
            yield btn


def find_nav_conflicts(markup, where: str = "") -> list[str]:
    """Klaviaturadagi FAZA 17 qoidabuzarliklari ro'yxati (bo'sh = toza).

    Tekshiruvlar:
      1. Bitta oynada IKKITA xuddi shu semantikali NAVIGATSIYA tugmasi
         (masalan «◀️ Orqaga» + «⬅️ Orqaga» yoki ikkita «❌ Yopish»).
         Semantika KO'RINADIGAN yorliqdan olinadi: yorlig'i navigatsion
         bo'lmagan tugma (masalan «🤖 Javoblar reklamasi: matn» — bo'lim
         ochuvchi) navigatsiya tugmasi hisoblanmaydi, hatto callback'i
         ``*:back`` bo'lsa ham;
      2. Yorliq ↔ callback mosizligi (masalan «❌ Yopish» yorlig'i ostida
         parent menyuga qaytaruvchi ``stgs_hub`` callback'i).
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    for btn in _iter_buttons(markup):
        text = getattr(btn, "text", "") or ""
        cb_data = getattr(btn, "callback_data", None) or getattr(btn, "url", "") or ""
        label_sem = classify_nav_label(text)
        cb_sem = callback_semantic(cb_data) if cb_data else None
        if label_sem and cb_sem and label_sem != cb_sem:
            problems.append(
                f"{where}: yorliq/callback mosizlik — {text!r} ({cb_data!r}): "
                f"label={label_sem}, callback={cb_sem}"
            )
        # Dublikat hisobi FAQAT ko'rinadigan (yorliq) semantika bo'yicha:
        # foydalanuvchi ikkita «Orqaga» ko'rsa — bu qoidabuzarlik; «Orqaga»
        # yorlig'i bo'lmagan bo'lim tugmasi esa navigatsiya emas.
        sem = label_sem
        if not sem:
            continue
        if sem in seen:
            problems.append(
                f"{where}: bir xil semantikali IKKITA tugma — "
                f"{seen[sem]!r} va {text!r} ({sem})"
            )
        else:
            seen[sem] = text
    return problems


def nav_row(*semantics_with_callbacks, lang: str = "uz") -> list[InlineKeyboardButton]:
    """Bir qatorli kanonik navigatsiya (masalan back + cancel).

    Har bir element — ``(semantic, callback)`` juftligi yoki ``semantic``
    (standart callback'i bo'lsa). Dublikat semantika ``ValueError`` beradi —
    qoidabuzar klaviatura umuman qurilmaydi (fail-fast).
    """
    row: list[InlineKeyboardButton] = []
    seen: set[str] = set()
    for item in semantics_with_callbacks:
        if isinstance(item, (tuple, list)):
            semantic, callback = item[0], item[1] if len(item) > 1 else None
        else:
            semantic, callback = item, None
        if semantic in seen:
            raise ValueError(f"nav_row: dublikat semantika — {semantic!r}")
        seen.add(semantic)
        row.append(nav_button(semantic, callback, lang))
    return row
