"""📋 POST SHABLONLARI matnlari (UZ/RU/EN, bir xil kalitlar — PHASE C, 9-band)."""

from locales.translations import normalize_lang

TEMPLATES_I18N = {
    "uz": {
        # --- Menyu ---
        "menu_title": "📋 <b>SHABLONLAR</b>\n\nKanal: <b>{channel}</b>\n"
                      "Takroriy postlaringizni shablon qilib saqlang — "
                      "o'zgaruvchilarni to'ldirib 1 soniyada qayta ishlating.",
        "btn_new": "➕ Yangi shablon",
        "btn_use": "📋 Shablonni ishlatish",
        "btn_delete": "🗑 O'chirish",
        "btn_back": "◀️ Orqaga",
        "btn_cancel": "❌ Bekor qilish",
        # --- Yangi shablon ---
        "ask_name": "✍️ Shablon nomini kiriting (masalan: Chegirma e'loni):",
        "ask_content": "📝 Shablon matnini kiriting.\n\n"
                       "Mavjud o'zgaruvchilar: <code>{TITLE}</code>, "
                       "<code>{TEXT}</code>, <code>{PRICE}</code>, "
                       "<code>{LINK}</code>, <code>{CTA}</code>, "
                       "<code>{SOURCE}</code>, <code>{DATE}</code>\n\n"
                       "Misol:\n<code>🔥 {{TITLE}}\n{{TEXT}}\n\n💰 Narxi: "
                       "{{PRICE}}\n👉 {{CTA}}: {{LINK}}</code>",
        "created": "✅ Shablon saqlandi: <b>{name}</b>",
        "name_too_long": "⚠️ Nom juda uzun (maksimal 128 belgi). Qayta kiriting:",
        "content_invalid": "⚠️ Shablon matni bo'sh yoki juda uzun "
                           "(maksimal 4000 belgi). Qayta kiriting:",
        "limit_reached": "⚠️ Shablonlar limiti to'lgan ({limit} ta). "
                         "Eskilarini o'chiring.",
        # --- Ro'yxat ---
        "empty_list": "📭 Sizda hozircha shablon yo'q.\n\n"
                      "[➕ Yangi shablon] tugmasi bilan boshlang.",
        "use_pick": "📋 Qaysi shablonni ishlatamiz?",
        "delete_pick": "🗑 Qaysi shablonni o'chiramiz?",
        "tpl_button": "📋 {name}",
        "not_found": "⚠️ Shablon topilmadi (yoki sizga tegishli emas).",
        "deleted": "🗑 Shablon o'chirildi: <b>{name}</b>",
        # --- O'zgaruvchilarni to'ldirish ---
        "vars_prompt": "🔧 Shablon o'zgaruvchilarini to'ldiring — har biri "
                       "YANGI qatorda, <code>NOMI: qiymat</code> tarzida:\n\n"
                       "{vars}\n\n<i>Misol:</i>\n<code> TITLE: Yangi "
                       "chegirma\n PRICE: 99 000 so'm</code>",
        "rendered_title": "📋 <b>SHABLON NATIJASI</b>\n\n",
        "rendered_foot": "\n\n👇 Post paneli bilan davom eting — darhol "
                         "yuborish yoki rejalashtirish mumkin.",
        "render_error": "⚠️ Shablonni render qilib bo'lmadi. Qaytadan "
                        "harakat qiling.",
        # --- Umumiy ---
        "stale": "Sessiya eskirgan — shablonlar menyusini qaytadan oching.",
        "cancel_done": "❌ Shablonlar yopildi.",
    },
    "ru": {
        "menu_title": "📋 <b>ШАБЛОНЫ</b>\n\nКанал: <b>{channel}</b>\n"
                      "Сохраняйте повторяющиеся посты как шаблоны — "
                      "заполните переменные и используйте заново за секунду.",
        "btn_new": "➕ Новый шаблон",
        "btn_use": "📋 Использовать шаблон",
        "btn_delete": "🗑 Удалить",
        "btn_back": "◀️ Назад",
        "btn_cancel": "❌ Отмена",
        "ask_name": "✍️ Введите название шаблона (например: Анонс скидки):",
        "ask_content": "📝 Введите текст шаблона.\n\n"
                       "Доступные переменные: <code>{TITLE}</code>, "
                       "<code>{TEXT}</code>, <code>{PRICE}</code>, "
                       "<code>{LINK}</code>, <code>{CTA}</code>, "
                       "<code>{SOURCE}</code>, <code>{DATE}</code>\n\n"
                       "Пример:\n<code>🔥 {{TITLE}}\n{{TEXT}}\n\n💰 Цена: "
                       "{{PRICE}}\n👉 {{CTA}}: {{LINK}}</code>",
        "created": "✅ Шаблон сохранён: <b>{name}</b>",
        "name_too_long": "⚠️ Название слишком длинное (максимум 128 "
                         "символов). Введите заново:",
        "content_invalid": "⚠️ Текст шаблона пустой или слишком длинный "
                           "(максимум 4000 символов). Введите заново:",
        "limit_reached": "⚠️ Достигнут лимит шаблонов ({limit}). Удалите "
                         "старые.",
        "empty_list": "📭 У вас пока нет шаблонов.\n\nНачните с кнопки "
                      "«➕ Новый шаблон».",
        "use_pick": "📋 Какой шаблон используем?",
        "delete_pick": "🗑 Какой шаблон удаляем?",
        "tpl_button": "📋 {name}",
        "not_found": "⚠️ Шаблон не найден (или не принадлежит вам).",
        "deleted": "🗑 Шаблон удалён: <b>{name}</b>",
        "vars_prompt": "🔧 Заполните переменные шаблона — каждая с НОВОЙ "
                       "строки, в виде <code>ИМЯ: значение</code>:\n\n"
                       "{vars}\n\n<i>Пример:</i>\n<code> TITLE: Новая "
                       "скидка\n PRICE: 99 000 сум</code>",
        "rendered_title": "📋 <b>РЕЗУЛЬТАТ ШАБЛОНА</b>\n\n",
        "rendered_foot": "\n\n👇 Продолжайте с панелью поста — отправка "
                         "сейчас или планирование доступны.",
        "render_error": "⚠️ Не удалось отрендерить шаблон. Попробуйте "
                        "ещё раз.",
        "stale": "Сессия устарела — откройте меню шаблонов заново.",
        "cancel_done": "❌ Шаблоны закрыты.",
    },
    "en": {
        "menu_title": "📋 <b>TEMPLATES</b>\n\nChannel: <b>{channel}</b>\n"
                      "Save your recurring posts as templates — fill in the "
                      "variables and reuse them in a second.",
        "btn_new": "➕ New template",
        "btn_use": "📋 Use template",
        "btn_delete": "🗑 Delete",
        "btn_back": "◀️ Back",
        "btn_cancel": "❌ Cancel",
        "ask_name": "✍️ Enter the template name (for example: Sale "
                    "announcement):",
        "ask_content": "📝 Enter the template text.\n\n"
                       "Available variables: <code>{TITLE}</code>, "
                       "<code>{TEXT}</code>, <code>{PRICE}</code>, "
                       "<code>{LINK}</code>, <code>{CTA}</code>, "
                       "<code>{SOURCE}</code>, <code>{DATE}</code>\n\n"
                       "Example:\n<code>🔥 {{TITLE}}\n{{TEXT}}\n\n💰 Price: "
                       "{{PRICE}}\n👉 {{CTA}}: {{LINK}}</code>",
        "created": "✅ Template saved: <b>{name}</b>",
        "name_too_long": "⚠️ The name is too long (max 128 characters). "
                         "Try again:",
        "content_invalid": "⚠️ The template text is empty or too long "
                           "(max 4000 characters). Try again:",
        "limit_reached": "⚠️ Template limit reached ({limit}). Delete old "
                         "ones.",
        "empty_list": "📭 You have no templates yet.\n\nStart with the "
                      "«➕ New template» button.",
        "use_pick": "📋 Which template do you want to use?",
        "delete_pick": "🗑 Which template do you want to delete?",
        "tpl_button": "📋 {name}",
        "not_found": "⚠️ Template not found (or not yours).",
        "deleted": "🗑 Template deleted: <b>{name}</b>",
        "vars_prompt": "🔧 Fill in the template variables — one per line, "
                       "as <code>NAME: value</code>:\n\n{vars}\n\n"
                       "<i>Example:</i>\n<code> TITLE: New sale\n PRICE: "
                       "99,000 UZS</code>",
        "rendered_title": "📋 <b>TEMPLATE RESULT</b>\n\n",
        "rendered_foot": "\n\n👇 Continue with the post panel — send now "
                         "or schedule.",
        "render_error": "⚠️ Could not render the template. Try again.",
        "stale": "Session expired — reopen the templates menu.",
        "cancel_done": "❌ Templates closed.",
    },
}

TEMPLATES_KEYS = tuple(sorted(TEMPLATES_I18N["uz"]))


def templates_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Tilga mos matn (noma'lum til → uz, noma'lum kalit → uz qiymati)."""
    table = TEMPLATES_I18N.get(normalize_lang(lang), TEMPLATES_I18N["uz"])
    text = table.get(key, TEMPLATES_I18N["uz"][key])
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def templates_parity_report() -> dict:
    """UZ ↔ RU ↔ EN kalit pariteti hisoboti (testlar uchun)."""
    return {
        lang: tuple(sorted(values)) == TEMPLATES_KEYS
        for lang, values in TEMPLATES_I18N.items()
    }
