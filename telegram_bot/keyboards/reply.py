"""Pastki (reply) klaviaturalar — handlerlar uchun QULAY FASAD.

Bu modul ``keyboards/default.py`` dagi pastki klaviaturalarni alohida nom bilan
qayta eksport qiladi: handler kodida «bu yerda inline tugmalar emas, foydalanuvchi
klaviaturasidagi tugmalar chiziladi» degan niyat aniq ko'rinishi uchun::

    from keyboards.reply import get_content_creation_keyboard, get_main_keyboard

MANTIQ (yorliqlar, tilga moslash, ``MENU_TEXTS`` registrlari) SHA YERDA
YASHIMAYDI — hammasi ``keyboards/default.py`` da yagona manba bo'lib qoladi,
aks holda ikki faylda ikki xil klaviatura paydo bo'lib paritet buzilardi.
Import yo'nalishi faqat bittа: ``reply → default`` (tsikl yo'q).
"""

from keyboards.default import (  # noqa: F401  (qayta eksport — API)
    BTN_CONTENT_AI,
    BTN_CONTENT_AI_EN,
    BTN_CONTENT_AI_RU,
    BTN_CONTENT_BACK,
    BTN_CONTENT_BACK_EN,
    BTN_CONTENT_BACK_RU,
    BTN_CONTENT_IMAGE,
    BTN_CONTENT_IMAGE_EN,
    BTN_CONTENT_IMAGE_RU,
    BTN_CONTENT_MAGIC,
    BTN_CONTENT_MAGIC_EN,
    BTN_CONTENT_MAGIC_RU,
    BTN_CONTENT_TEXT,
    BTN_CONTENT_TEXT_EN,
    BTN_CONTENT_TEXT_RU,
    BTN_CONTENT_VOICE,
    BTN_CONTENT_VOICE_EN,
    BTN_CONTENT_VOICE_RU,
    BTN_CREATE_CONTENT,
    BTN_IMAGE_POST,
    BTN_IMAGE_POST_EN,
    BTN_IMAGE_POST_RU,
    BTN_MAGIC_POST,
    BTN_MAGIC_POST_EN,
    BTN_MAGIC_POST_RU,
    content_ai_label,
    content_back_label,
    content_creation_labels,
    content_creation_rows,
    content_image_label,
    content_magic_label,
    content_text_label,
    content_voice_label,
    get_content_creation_keyboard,
    get_main_keyboard,
    get_simple_keyboard,
)

#: «✨ Kontent yaratish» submenu'sining 5 ta yaratish yo'li + ◀️ Orqaga —
#: testlar va hujjatlashtirish uchun qulay konstanta.
CONTENT_CREATION_BUTTONS = ("✨ Magic Post", "📝 Matn → Post", "📸 Rasm → Post",
                            "🎙 Ovoz → Post", "🤖 AI Yordamchi")

__all__ = [
    "CONTENT_CREATION_BUTTONS",
    "BTN_CONTENT_AI", "BTN_CONTENT_AI_EN", "BTN_CONTENT_AI_RU",
    "BTN_CONTENT_BACK", "BTN_CONTENT_BACK_EN", "BTN_CONTENT_BACK_RU",
    "BTN_CONTENT_IMAGE", "BTN_CONTENT_IMAGE_EN", "BTN_CONTENT_IMAGE_RU",
    "BTN_CONTENT_MAGIC", "BTN_CONTENT_MAGIC_EN", "BTN_CONTENT_MAGIC_RU",
    "BTN_CONTENT_TEXT", "BTN_CONTENT_TEXT_EN", "BTN_CONTENT_TEXT_RU",
    "BTN_CONTENT_VOICE", "BTN_CONTENT_VOICE_EN", "BTN_CONTENT_VOICE_RU",
    "BTN_CREATE_CONTENT",
    "BTN_IMAGE_POST", "BTN_IMAGE_POST_EN", "BTN_IMAGE_POST_RU",
    "BTN_MAGIC_POST", "BTN_MAGIC_POST_EN", "BTN_MAGIC_POST_RU",
    "content_ai_label", "content_back_label", "content_creation_labels",
    "content_creation_rows", "content_image_label", "content_magic_label",
    "content_text_label", "content_voice_label",
    "get_content_creation_keyboard", "get_main_keyboard", "get_simple_keyboard",
]
