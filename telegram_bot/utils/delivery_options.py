"""Localized, per-post delivery controls (off by default)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

DELIVERY_KEYS = ("disable_notification", "protect_content", "auto_pin")
_LABELS = {
    "uz": {
        "title": "⚙️ Qo'shimcha sozlamalar",
        "disable_notification": "Ovozsiz yuborish",
        "protect_content": "Forward/nusxa olishni taqiqlash",
        "auto_pin": "Avtomatik qadash",
        "yes": "Ha", "no": "Yo'q", "back": "⬅️ Orqaga",
    },
    "ru": {
        "title": "⚙️ Дополнительные настройки",
        "disable_notification": "Без звука",
        "protect_content": "Запретить пересылку/копирование",
        "auto_pin": "Автоматически закрепить",
        "yes": "Да", "no": "Нет", "back": "⬅️ Назад",
    },
    "en": {
        "title": "⚙️ Additional settings",
        "disable_notification": "Send silently",
        "protect_content": "Prevent forwarding/copying",
        "auto_pin": "Auto-pin",
        "yes": "Yes", "no": "No", "back": "⬅️ Back",
    },
}


def delivery_labels(lang):
    return _LABELS.get(lang, _LABELS["uz"])


def delivery_markup(options, lang):
    labels = delivery_labels(lang)
    rows = [[InlineKeyboardButton(
        f"{labels[key]}: {labels['yes'] if options.get(key) else labels['no']}",
        callback_data=f"mnp_delivery:{key}",
    )] for key in DELIVERY_KEYS]
    rows.append([InlineKeyboardButton(labels["back"], callback_data="mnp_panel")])
    return InlineKeyboardMarkup(rows)
