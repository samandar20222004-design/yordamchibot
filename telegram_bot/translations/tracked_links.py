"""🔗 MANBA HAVOLALARI — i18n lug'ati (UZ / RU / EN, 100% paritet).

``handlers/tracked_links.py`` matnlarining yagona manbasi. UZ↔RU↔EN pariteti ``tracked_links_parity_report()`` bilan
testda qo'riqlanadi; tugma yorlig'i (``tl_btn_*``) 18 belgidan oshmaydi (``tests/tracked_links_test.py``).
"""

from locales.translations import normalize_lang, safe_t

TRACKED_LINKS_I18N = {
    "uz": {
        "tl_list_title": "🔗 <b>Manba havolalari</b>",
        "tl_list_head": "Jami: <b>{n}</b> ta havola · bosish <b>{clicks}</b> · yangi <b>{new}</b> · post qilgan <b>{posted}</b> · to'lagan <b>{paid}</b>",
        "tl_row": "{icon} <code>{code}</code> — {title}{owner}\n     👆 {clicks} · 👤 {visitors} · 🆕 {new} · 📢 {chan} · 📝 {posted} · 💎 {paid}",
        "tl_owner_suffix": " · egasi <code>{owner}</code>",
        "tl_legend": "👆 bosish · 👤 noyob kirgan · 🆕 yangi ro'yxatdan o'tgan · 📢 kanal ulagan · 📝 post qilgan · 💎 to'lagan",
        "tl_empty": "Hali havola yo'q. Yaratish: /link_new KOD Nomi",
        "tl_more": "… va yana {n} ta.",
        "tl_hint": "Boshqarish: /link KOD — tafsilot va kimlar kelgani · /link_new KOD [@egasi] Nomi — yangi · /link_off KOD, /link_on KOD · /link_user ID — foydalanuvchi qayerdan kelgan",
        "tl_usage_new": "Foydalanish: /link_new KOD [@username yoki ID] Nomi\n\nMisol (reklama joyi): /link_new tech_kanal Texno kanalidagi reklama\nMisol (hamkor): /link_new ali @ali_smm Ali — SMM hamkor\n\nKOD: lotin harflari, raqam va _ (2–24 belgi). Egasi ko'rsatilsa, shu havola bilan ro'yxatdan o'tganlar uning takliflari sifatida yoziladi.",
        "tl_err_bad_code": "❌ KOD noto'g'ri: faqat lotin harflari, raqam va _ (2–24 belgi).",
        "tl_err_bad_title": "❌ Havola nomini yozing (masalan, qaysi kanalga qo'yilgani).",
        "tl_err_exists": "❌ Bunday KOD bor. Boshqasini tanlang yoki /link KOD bilan ko'ring.",
        "tl_err_limit": "❌ Havolalar soni chegarasiga yetildi. Keraksizlarini /link_off bilan o'chiring.",
        "tl_err_owner_unknown": "❌ Egasi topilmadi: u avval botga /start bosgan bo'lishi kerak (@username yoki ID).",
        "tl_created": "✅ Havola yaratildi: <b>{title}</b>\n\n{url}\n\n{owner_line}Shu havolani reklama joyiga qo'ying. Kim kirganini /link {code} da ko'rasiz.",
        "tl_created_owner": "Egasi: <code>{owner}</code> — shu havola bilan ro'yxatdan o'tganlar uning takliflari sifatida yoziladi (ball ularning birinchi postidan keyin).\n",
        "tl_created_no_owner": "Egasi yo'q — faqat statistika yig'iladi, ball hech kimga yozilmaydi.\n",
        "tl_detail": "🔗 <b>{title}</b> — {status}\nKod: <code>{code}</code>\nHavola: {url}\n{owner_line}Yaratilgan: {created}\n\n👆 Bosishlar: <b>{clicks}</b>\n👤 Noyob kirganlar: <b>{visitors}</b>\n🆕 Yangi ro'yxatdan o'tgan: <b>{new}</b>\n📢 Kanal ulagan: <b>{chan}</b> ({chan_pct})\n📝 Post qilgan: <b>{posted}</b> ({posted_pct})\n💎 To'lagan: <b>{paid}</b> ({paid_pct})",
        "tl_detail_owner": "Egasi: <code>{owner}</code> (ball unga yoziladi)\n",
        "tl_detail_no_owner": "Egasi: yo'q (faqat statistika)\n",
        "tl_st_on": "🟢 faol",
        "tl_st_off": "⚪️ o'chirilgan",
        "tl_joins_title": "👥 Oxirgi ro'yxatdan o'tganlar (📢 kanal · 📝 post · 💎 to'lov):",
        "tl_join_row": "• {name} — {when} {badges}",
        "tl_no_joins": "Hali hech kim bu havola orqali ro'yxatdan o'tmagan.",
        "tl_not_found": "❌ Bunday havola topilmadi. Ro'yxat: /links",
        "tl_usage_detail": "Foydalanish: /link KOD",
        "tl_usage_toggle": "Foydalanish: /link_off KOD yoki /link_on KOD",
        "tl_set_off": "✅ <code>{code}</code> o'chirildi: endi bu havola bilan kirganlar hisobga olinmaydi (bot ishlayveradi).",
        "tl_set_on": "✅ <code>{code}</code> qayta yoqildi.",
        "tl_usage_user": "Foydalanish: /link_user ID yoki /link_user @username",
        "tl_user_unknown": "❌ Foydalanuvchi topilmadi.",
        "tl_user_none": "👤 <code>{user}</code> hech qanday manba havolasi bilan kirmagan.",
        "tl_user_origin": "👤 <code>{user}</code> ro'yxatdan o'tgan havola: <code>{code}</code> — {title} ({when})",
        "tl_user_no_origin": "👤 <code>{user}</code> havola bilan ro'yxatdan o'tmagan (avvaldan botda bo'lgan).",
        "tl_user_visits": "Bosgan havolalari: {codes}",
        "tl_btn_list": "🔗 Havolalar",
        "tl_btn_refresh": "🔄 Yangilash",
        "tl_my_title": "🔗 <b>Sizning havolalaringiz</b>",
        "tl_my_row": "<b>{title}</b> {status}\n{url}\n👆 {clicks} · 🆕 {new} · 📝 {posted} · 💎 {paid}",
        "tl_my_note": "Shu havola bilan ro'yxatdan o'tganlar sizning takliflaringiz sifatida yoziladi: har biri birinchi postini qilganda sizga ball tushadi.",
        "tl_my_empty": "Sizga biriktirilgan havola yo'q. Hamkor bo'lish uchun admin bilan bog'laning.",
    },
    "ru": {
        "tl_list_title": "🔗 <b>Ссылки-источники</b>",
        "tl_list_head": "Всего: <b>{n}</b> ссылок · переходов <b>{clicks}</b> · новых <b>{new}</b> · сделали пост <b>{posted}</b> · оплатили <b>{paid}</b>",
        "tl_row": "{icon} <code>{code}</code> — {title}{owner}\n     👆 {clicks} · 👤 {visitors} · 🆕 {new} · 📢 {chan} · 📝 {posted} · 💎 {paid}",
        "tl_owner_suffix": " · владелец <code>{owner}</code>",
        "tl_legend": "👆 переходы · 👤 уникальные · 🆕 новые регистрации · 📢 подключили канал · 📝 сделали пост · 💎 оплатили",
        "tl_empty": "Ссылок пока нет. Создать: /link_new КОД Название",
        "tl_more": "… и ещё {n}.",
        "tl_hint": "Управление: /link КОД — подробности и кто пришёл · /link_new КОД [@владелец] Название — новая · /link_off КОД, /link_on КОД · /link_user ID — откуда пришёл пользователь",
        "tl_usage_new": "Использование: /link_new КОД [@username или ID] Название\n\nПример (рекламное место): /link_new tech_kanal Реклама в Техно-канале\nПример (партнёр): /link_new ali @ali_smm Али — SMM-партнёр\n\nКОД: латиница, цифры и _ (2–24 символа). Если указан владелец, зарегистрировавшиеся по ссылке засчитываются как его приглашения.",
        "tl_err_bad_code": "❌ Неверный КОД: только латиница, цифры и _ (2–24 символа).",
        "tl_err_bad_title": "❌ Укажите название ссылки (например, где она размещена).",
        "tl_err_exists": "❌ Такой КОД уже есть. Выберите другой или посмотрите /link КОД.",
        "tl_err_limit": "❌ Достигнут лимит ссылок. Отключите ненужные через /link_off.",
        "tl_err_owner_unknown": "❌ Владелец не найден: он должен сначала нажать /start в боте (@username или ID).",
        "tl_created": "✅ Ссылка создана: <b>{title}</b>\n\n{url}\n\n{owner_line}Разместите эту ссылку в рекламе. Кто пришёл — смотрите в /link {code}.",
        "tl_created_owner": "Владелец: <code>{owner}</code> — зарегистрировавшиеся по ссылке засчитываются как его приглашения (баллы после их первого поста).\n",
        "tl_created_no_owner": "Владельца нет — собирается только статистика, баллы никому не начисляются.\n",
        "tl_detail": "🔗 <b>{title}</b> — {status}\nКод: <code>{code}</code>\nСсылка: {url}\n{owner_line}Создана: {created}\n\n👆 Переходы: <b>{clicks}</b>\n👤 Уникальные: <b>{visitors}</b>\n🆕 Новые регистрации: <b>{new}</b>\n📢 Подключили канал: <b>{chan}</b> ({chan_pct})\n📝 Сделали пост: <b>{posted}</b> ({posted_pct})\n💎 Оплатили: <b>{paid}</b> ({paid_pct})",
        "tl_detail_owner": "Владелец: <code>{owner}</code> (баллы ему)\n",
        "tl_detail_no_owner": "Владелец: нет (только статистика)\n",
        "tl_st_on": "🟢 активна",
        "tl_st_off": "⚪️ отключена",
        "tl_joins_title": "👥 Последние регистрации (📢 канал · 📝 пост · 💎 оплата):",
        "tl_join_row": "• {name} — {when} {badges}",
        "tl_no_joins": "По этой ссылке ещё никто не зарегистрировался.",
        "tl_not_found": "❌ Такая ссылка не найдена. Список: /links",
        "tl_usage_detail": "Использование: /link КОД",
        "tl_usage_toggle": "Использование: /link_off КОД или /link_on КОД",
        "tl_set_off": "✅ <code>{code}</code> отключена: пришедшие по ней больше не учитываются (бот работает как обычно).",
        "tl_set_on": "✅ <code>{code}</code> снова включена.",
        "tl_usage_user": "Использование: /link_user ID или /link_user @username",
        "tl_user_unknown": "❌ Пользователь не найден.",
        "tl_user_none": "👤 <code>{user}</code> не приходил ни по одной ссылке-источнику.",
        "tl_user_origin": "👤 <code>{user}</code> зарегистрировался по ссылке: <code>{code}</code> — {title} ({when})",
        "tl_user_no_origin": "👤 <code>{user}</code> зарегистрировался не по ссылке (был в боте раньше).",
        "tl_user_visits": "Переходил по ссылкам: {codes}",
        "tl_btn_list": "🔗 Ссылки",
        "tl_btn_refresh": "🔄 Обновить",
        "tl_my_title": "🔗 <b>Ваши ссылки</b>",
        "tl_my_row": "<b>{title}</b> {status}\n{url}\n👆 {clicks} · 🆕 {new} · 📝 {posted} · 💎 {paid}",
        "tl_my_note": "Зарегистрировавшиеся по вашей ссылке засчитываются как ваши приглашения: за каждого вы получаете баллы после его первого поста.",
        "tl_my_empty": "За вами не закреплено ссылок. Чтобы стать партнёром, свяжитесь с админом.",
    },
    "en": {
        "tl_list_title": "🔗 <b>Source links</b>",
        "tl_list_head": "Total: <b>{n}</b> links · clicks <b>{clicks}</b> · new <b>{new}</b> · posted <b>{posted}</b> · paid <b>{paid}</b>",
        "tl_row": "{icon} <code>{code}</code> — {title}{owner}\n     👆 {clicks} · 👤 {visitors} · 🆕 {new} · 📢 {chan} · 📝 {posted} · 💎 {paid}",
        "tl_owner_suffix": " · owner <code>{owner}</code>",
        "tl_legend": "👆 clicks · 👤 unique · 🆕 new sign-ups · 📢 connected a channel · 📝 posted · 💎 paid",
        "tl_empty": "No links yet. Create one: /link_new CODE Title",
        "tl_more": "… and {n} more.",
        "tl_hint": "Manage: /link CODE — details and who came · /link_new CODE [@owner] Title — new · /link_off CODE, /link_on CODE · /link_user ID — where a user came from",
        "tl_usage_new": "Usage: /link_new CODE [@username or ID] Title\n\nExample (ad placement): /link_new tech_kanal Ad in the Tech channel\nExample (partner): /link_new ali @ali_smm Ali — SMM partner\n\nCODE: Latin letters, digits and _ (2–24 chars). If an owner is given, people who sign up via the link count as their referrals.",
        "tl_err_bad_code": "❌ Invalid CODE: Latin letters, digits and _ only (2–24 chars).",
        "tl_err_bad_title": "❌ Give the link a title (e.g. where it is placed).",
        "tl_err_exists": "❌ This CODE already exists. Pick another or check /link CODE.",
        "tl_err_limit": "❌ Link limit reached. Disable unused ones with /link_off.",
        "tl_err_owner_unknown": "❌ Owner not found: they must press /start in the bot first (@username or ID).",
        "tl_created": "✅ Link created: <b>{title}</b>\n\n{url}\n\n{owner_line}Put this link in your ad. See who came with /link {code}.",
        "tl_created_owner": "Owner: <code>{owner}</code> — people who sign up via this link count as their referrals (points after their first post).\n",
        "tl_created_no_owner": "No owner — only statistics are collected, no points are given.\n",
        "tl_detail": "🔗 <b>{title}</b> — {status}\nCode: <code>{code}</code>\nLink: {url}\n{owner_line}Created: {created}\n\n👆 Clicks: <b>{clicks}</b>\n👤 Unique: <b>{visitors}</b>\n🆕 New sign-ups: <b>{new}</b>\n📢 Connected a channel: <b>{chan}</b> ({chan_pct})\n📝 Posted: <b>{posted}</b> ({posted_pct})\n💎 Paid: <b>{paid}</b> ({paid_pct})",
        "tl_detail_owner": "Owner: <code>{owner}</code> (gets the points)\n",
        "tl_detail_no_owner": "Owner: none (statistics only)\n",
        "tl_st_on": "🟢 active",
        "tl_st_off": "⚪️ disabled",
        "tl_joins_title": "👥 Latest sign-ups (📢 channel · 📝 post · 💎 payment):",
        "tl_join_row": "• {name} — {when} {badges}",
        "tl_no_joins": "Nobody has signed up via this link yet.",
        "tl_not_found": "❌ Link not found. List: /links",
        "tl_usage_detail": "Usage: /link CODE",
        "tl_usage_toggle": "Usage: /link_off CODE or /link_on CODE",
        "tl_set_off": "✅ <code>{code}</code> disabled: people coming via it are no longer counted (the bot works as usual).",
        "tl_set_on": "✅ <code>{code}</code> enabled again.",
        "tl_usage_user": "Usage: /link_user ID or /link_user @username",
        "tl_user_unknown": "❌ User not found.",
        "tl_user_none": "👤 <code>{user}</code> never came via a source link.",
        "tl_user_origin": "👤 <code>{user}</code> signed up via: <code>{code}</code> — {title} ({when})",
        "tl_user_no_origin": "👤 <code>{user}</code> did not sign up via a link (was in the bot before).",
        "tl_user_visits": "Links clicked: {codes}",
        "tl_btn_list": "🔗 Links",
        "tl_btn_refresh": "🔄 Refresh",
        "tl_my_title": "🔗 <b>Your links</b>",
        "tl_my_row": "<b>{title}</b> {status}\n{url}\n👆 {clicks} · 🆕 {new} · 📝 {posted} · 💎 {paid}",
        "tl_my_note": "People who sign up via your link count as your referrals: you get points for each one after their first post.",
        "tl_my_empty": "No links are assigned to you. Contact the admin to become a partner.",
    },
}

TRACKED_LINKS_KEYS = tuple(TRACKED_LINKS_I18N["uz"])


def links_t(key: str, lang: str = "uz", **kwargs) -> str:
    code = normalize_lang(lang)
    text = (TRACKED_LINKS_I18N.get(code) or {}).get(key)
    if text is None:
        text = TRACKED_LINKS_I18N["uz"].get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError, ValueError):
        return text


def tracked_links_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti (boshqa ``*_parity_report`` lar bilan bir xil struktura)."""
    from locales.translations import format_args

    base = TRACKED_LINKS_I18N["uz"]
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        table = TRACKED_LINKS_I18N.get(lang) or {}
        if lang != "uz":
            missing[lang] = sorted(base_keys - set(table))
            extra[lang] = sorted(set(table) - base_keys)
            for key in base_keys & set(table):
                if format_args(base[key]) != format_args(table[key]):
                    fmt_mismatch.setdefault(key, {"uz": format_args(base[key]), lang: format_args(table[key])})
        empty.extend(f"{lang}:{k}" for k, v in table.items() if not str(v).strip())
    in_sync = (not any(missing.values()) and not any(extra.values()) and not fmt_mismatch and not empty)
    return {"keys": len(base_keys), "missing": missing, "extra": extra, "format_mismatch": fmt_mismatch,
            "empty": empty, "in_sync": in_sync}
