"""🧰 VOSITALAR — yordamchi vositalar submenyusi (PostAssist V2 · 3-qadam).

Muammo (3-qadam auditi): ⚙️ Sozlamalar menyusi «yagona tartibli menyu»
bo'lishi kerak edi, lekin ichida ikki xil muammo bor edi:

  1) eski kabinetning tezkor tugmalari (📢 Mening kanallarim, 📅 Rejalashtirilgan,
     📅 Kutilayotgan, 💎 Ballar & reklama rejimi) menyu ICHIDA takrorlanardi —
     ular o'z asosiy menyularida bor (`handlers.channels`, `handlers.queue`);
  2) foydali, lekin yashirinib qolgan ikkita vosita — 🔤 Kirill-Lotin Konvertor
     (#38) va ✨ Tugma & Reaksiyalar / Post Enhancer (#9) — faqat eski
     «⚙️ Qo'shimcha funksiyalar» reply-tugmasi orqali ochilardi.

Yechim: ⚙️ Sozlamalar menyusiga aynan bitta yangi tugma — [🧰 Vositalar]
qo'shildi, u quyidagi submenyuni ochadi:

    [🔤 Kirill-Lotin Konvertor]
    [✨ Tugma & Reaksiyalar (Post Enhancer)]
                [◀️ Orqaga]

Modul mas'uliyati:
  * ``render_tools_menu`` — submenyu ekranini chizadi (xabar EDIT qilinadi,
    yangi xabar yuborilmaydi — navigatsiya "bitta xabar" qoidasiga mos);
  * ``TOOLS_ENTRIES`` — submenyu tugmalarining callback → oqim shartnomasi
    (test va audit uchun yagona manba).

MUHIM: bu modul YANGI FSM yaratmaydi va yangi callback prefiksi kiritmaydi —
konvertor ham, post kuchaytirgich ham o'zlarining mavjud, sinovdan o'tgan
``extra_converter`` / ``extra_enhancer`` entry-point'larini ishlatadi
(``handlers/__init__.py`` — main_conv entry_points). Shu sababli eski
«⚙️ Qo'shimcha funksiyalar» tugmasi ham buzilmaydi: ikkala yo'l bitta oqimga
olib boradi.
"""

import logging

from telegram import InlineKeyboardMarkup

from keyboards.inline import get_tools_keyboard
from locales.translations import get_text
from translations import settings_stats_t

logger = logging.getLogger(__name__)

#: 🧰 Vositalar submenyusi shartnomasi: (callback_data, oqim nomi, manba).
#: Testlar shu jadval orqali «tugma → oqim» bog'lanishini qo'riqlaydi.
TOOLS_ENTRIES = (
    ("extra_converter", "CONVERT_INPUT", "handlers.converter.converter_inline_entry"),
    ("extra_enhancer", "ENH_POST", "handlers.post_enhancer.post_enhancer_start"),
)

#: Submenyu «Orqaga» tugmasi — ⚙️ Sozlamalar menyusini qayta chizadi.
TOOLS_BACK_CALLBACK = "stgs_hub"

#: Submenyu callback'lari tartibida (test/audit uchun).
TOOLS_MENU_CALLBACKS = tuple(cb for cb, _state, _src in TOOLS_ENTRIES) + (
    TOOLS_BACK_CALLBACK,
)


def build_tools_text(lang: str = "uz") -> str:
    """🧰 Vositalar ekranining matni (UZ/RU/EN — ``ss_tools_title``)."""
    text = settings_stats_t("ss_tools_title", lang)
    if not text or text == "ss_tools_title":  # pragma: no cover - himoya
        text = get_text("extras_menu_body", lang)
    return text


def build_tools_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """🧰 Vositalar ekranining klaviaturasi (3 tugma: 2 vosita + Orqaga)."""
    return get_tools_keyboard(lang)


async def render_tools_menu(query, lang: str = "uz") -> None:
    """🧰 Vositalar submenyusini ko'rsatadi (xabar edit qilinadi).

    Callback query javobsiz qolmasligi kafolatlanadi: ``edit_message_text``
    iloji bo'lmasa (xabar o'chgan/eskirgan) yangi xabar yuboriladi.
    """
    text = build_tools_text(lang)
    markup = build_tools_keyboard(lang)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:  # pragma: no cover - Telegram xatosi (xabar o'chgan)
            logger.debug("🧰 Vositalar ekranini ko'rsatib bo'lmadi")
