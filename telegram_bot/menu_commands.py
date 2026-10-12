"""📋 TELEGRAM «MENU» TUGMASI VA BUYRUQLAR RO'YXATI — YAGONA MANBA (SSOT).

Telegram chat maydonining yonidagi **«Menu» (☰)** tugmasi bosilganda
foydalanuvchi ``set_my_commands`` orqali ro'yxatdan o'tkazilgan buyruqlar
ro'yxatini ko'radi. Ro'yxat TILGA QARAB tanlanadi: Telegram klient
``language_code`` bo'yicha mos to'plamni oladi (``uz`` / ``ru`` / ``en``),
mos kelmasa — ``language_code`` SIZ (standart) to'plam ishlatiladi.

Nega alohida modul?

  * YAGONA manba: buyruq nomlari, TARTIBI, i18n kalitlari va Telegram
    cheklovlari faqat shu yerda e'lon qilinadi — ``main.set_bot_commands``
    shu yerdan o'qib Telegram'ga yuboradi (nusxa ko'chirilgan ro'yxat yo'q);
  * Ro'yxat **IXCHAM** — 5 ta ASOSIY amal (asosiy reply-menyu standartiga
    mos). Texnik yoki admin buyruqlari (``/admin``, ``/stats``, ``/audit``,
    ``/privacy`` ...) ☰ menyuga CHIQARILMAYDI: ular ishlashda davom etadi,
    lekin foydalanuvchi ro'yxatini to'ldirmaydi;
  * Har bir buyruq nomi REAL handlerga ega (``handlers/__init__.py``
    ro'yxatga olgan) — foydalanuvchi tugmani bosganda oqim DARHOL ochiladi,
    oraliq qadam yo'q.

Telegram talablari (BotCommand):
  * nom — ``a-z``, ``0-9`` va ``_``; uzunligi 1..32, faqat kichik harf;
  * tavsif — 1..256 belgi (emoji mumkin, markdown YO'Q).
"""

from __future__ import annotations

import re

from telegram import BotCommand, MenuButtonCommands

from locales.translations import (
    DEFAULT_LANG,
    EN_OVERLAY,
    get_text,
    normalize_lang,
)

# ============================================================
# 1) RO'YXAT — buyruq nomi → i18n kaliti (KO'RSATISH TARTIBI bilan)
# ============================================================
#: ☰ «Menu» tugmasidagi ASOSIY buyruqlar (yuqoridan pastga shu tartibda).
#: Birinchi element — ``/start`` (har doim birinchi turadi), oxirgisi
#: ``/help`` (yordam oxirida).
MENU_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "menu_cmd_start"),
    ("newpost", "menu_cmd_newpost"),
    ("cleaner", "menu_cmd_cleaner"),
    ("settings", "menu_cmd_settings"),
    ("help", "menu_cmd_help"),
)

#: Buyruq nomlari (tartib bilan) — tez tekshiruvlar uchun.
MENU_COMMAND_NAMES: tuple[str, ...] = tuple(name for name, _key in MENU_COMMANDS)

#: Buyruq nomi → i18n kaliti.
MENU_COMMAND_I18N: dict[str, str] = dict(MENU_COMMANDS)

#: ``set_my_commands(language_code=...)`` uchun alohida ro'yxatlar tillari.
MENU_COMMAND_LOCALES: tuple[str, ...] = ("uz", "ru", "en")

#: ``language_code`` SIZ (standart) ro'yxat tili — botning asosiy tili.
#: Telegram mos tilni topmasa (masalan, "de"), AYNAN shu ro'yxat ko'rinadi.
DEFAULT_MENU_LANG: str = DEFAULT_LANG

#: Telegram BotCommand nomi uchun ruxsat etilgan shakl (1..32 belgi).
COMMAND_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")

#: Telegram BotCommand tavsifi uchun chegara (belgi).
COMMAND_DESCRIPTION_MAX_LEN = 256


# ============================================================
# 2) QURUVCHILAR
# ============================================================
def command_description(command: str, lang: str = DEFAULT_MENU_LANG) -> str:
    """Buyruq uchun LOKALIZATSIYA qilingan tavsif (uz/ru/en).

    Noma'lum buyruq nomi yoki yo'q kalit uchun bo'sh satr qaytadi (crash
    yo'q — ``get_text`` ham hech qachon ``KeyError`` bermaydi).
    """
    key = MENU_COMMAND_I18N.get(str(command or "").strip().lower())
    if not key:
        return ""
    return str(get_text(key, normalize_lang(lang)) or "").strip()


def build_bot_commands(lang: str = DEFAULT_MENU_LANG) -> list[BotCommand]:
    """Bitta til uchun ``BotCommand`` ro'yxati (tartib: ``MENU_COMMANDS``)."""
    code = normalize_lang(lang)
    return [
        BotCommand(name, command_description(name, code))
        for name in MENU_COMMAND_NAMES
    ]


def localized_command_lists() -> dict[str, list[BotCommand]]:
    """``language_code`` → ``BotCommand`` ro'yxati (uz/ru/en)."""
    return {lang: build_bot_commands(lang) for lang in MENU_COMMAND_LOCALES}


def default_menu_button() -> MenuButtonCommands:
    """Standart «Menu» tugmasi — BUYRUQLAR ro'yxatini ko'rsatadigan tur.

    Telegram'da uch xil menu button bor: ``commands`` (☰ standart ro'yxat),
    ``web_app`` va ``default``. Botda web-app yo'q, shu sababli AYNAN
    ``commands`` turi o'rnatiladi — aks holda (masalan, tugma ilgari
    boshqa turga o'zgartirilgan bo'lsa) foydalanuvchi ☰ ni bosganda
    buyruqlar ro'yxati o'rniga boshqa narsa ko'rishi mumkin edi.
    """
    return MenuButtonCommands()


# ============================================================
# 3) DIAGNOSTIKA — paritet hisoboti (testlar/health uchun)
# ============================================================
def menu_commands_parity_report() -> dict:
    """☰ menyu ro'yxatining uchala tildagi to'liqligi hisoboti.

    Qaytaradi::

        {
            "commands": [...],        # ro'yxatdagi buyruqlar (tartib bilan)
            "locales": [...],         # alohida ro'yxat tillari
            "missing_keys": {...},    # til → tavsifi YO'Q buyruqlar
            "overlay_missing": [...], # EN_OVERLAY'da qolmagan kalitlar
            "identical": [...],       # uchala tilda bir xil tavsif (lokalizatsiya yo'q)
            "invalid_names": [...],   # Telegram nom qoidasiga mos kelmaydiganlar
            "too_long": [...],        # tavsifi 256 belgidan uzun
            "in_sync": True,          # hammasi joyidami
        }
    """
    missing_keys: dict[str, list[str]] = {}
    identical: list[str] = []
    invalid_names: list[str] = []
    too_long: list[str] = []

    for name in MENU_COMMAND_NAMES:
        texts: list[str] = []
        for lang in MENU_COMMAND_LOCALES:
            text = command_description(name, lang)
            if not text:
                missing_keys.setdefault(lang, []).append(name)
            if len(text) > COMMAND_DESCRIPTION_MAX_LEN:
                too_long.append(f"{lang}:{name}")
            texts.append(text)
        if len(texts) == len(MENU_COMMAND_LOCALES) and len(set(texts)) == 1:
            # Uchala tilda bir xil matn — lokalizatsiya qilinmagan.
            identical.append(name)
        if not COMMAND_NAME_RE.match(name):
            invalid_names.append(name)

    overlay_missing = sorted(
        name for name in MENU_COMMAND_NAMES
        if MENU_COMMAND_I18N[name] not in EN_OVERLAY
    )
    in_sync = not (
        missing_keys or overlay_missing or identical
        or invalid_names or too_long
    )
    return {
        "commands": list(MENU_COMMAND_NAMES),
        "locales": list(MENU_COMMAND_LOCALES),
        "missing_keys": missing_keys,
        "overlay_missing": overlay_missing,
        "identical": identical,
        "invalid_names": invalid_names,
        "too_long": too_long,
        "in_sync": in_sync,
    }
