"""🚀 AI AUTOPILOT matnlari (UZ/RU/EN, bir xil kalitlar — PHASE C + PHASE 8 V2)."""

from locales.translations import normalize_lang

AUTOPILOT_I18N = {
    "uz": {
        # --- Kirish / generatsiya ---
        "intro": "🚀 <b>AI AVTOPILOT</b>\n\nKanal: <b>{channel}</b>\n\n"
                 "Mavzu yoki yo'nalishni kiriting — AI kanalingiz uslubi "
                 "(Channel DNA) va eng yaxshi vaqt tavsiyalariga tayangan "
                 "holda 7 kunlik to'liq post rejasini tuzadi "
                 "(Dushanba–Yakshanba):\n\n"
                 "<i>Masalan: Kofeynya yangi menyusi; Onlayn ingliz tili "
                 "kurslari; Avtoulov yuvish xizmati</i>",
        "generating": "⏳ 7 kunlik reja tuzilmoqda... Bir oz kuting.",
        "ai_failed": "Reja hozircha tuzilmadi. Keyinroq qayta urinib "
                     "ko'ring yoki mavzuni aniqroq yozib ko'ring.",
        "topic_too_short": "Mavzu juda qisqa. Iltimos, yo'nalishni "
                           "yozing (kamida 3 belgi):",
        # --- Reja ko'rinishi ---
        "plan_header": "🚀 <b>7 KUNLIK AI AVTOPILOT REJASI</b>\n"
                       "Kanal: <b>{channel}</b>\nMavzu: <b>{topic}</b>\n"
                       "{time_note}\n\n",
        "time_note_best": "⏰ Vaqtlar kanalning eng yaxshi vaqt "
                          "statistikasi bo'yicha ({window}).",
        "time_note_default": "⏰ Kanal vaqt statistikasi yetarli emas — "
                             "standart {hour}:00 ishlatildi.",
        "plan_day": "<b>{n}-kun · {weekday} ({date}) — {time}</b>\n"
                    "<i>Format: {fmt}</i>\n\n{post}\n\n"
                    "➖➖➖➖➖➖➖➖➖➖➖➖➖\n",
        "confirm_hint": "👇 Rejani tasdiqlang:",
        # --- Tugmalar ---
        "btn_schedule_all": "🚀 Hammasi",
        "btn_edit": "✏️ Tahrirlash",
        "btn_regen": "🔄 Qayta yaratish",
        "btn_cancel": "❌ Bekor qilish",
        # --- Tahrirlash ---
        "edit_pick": "✏️ Qaysi kunni tahrirlaymiz?",
        "edit_day_btn": "{n}-kun · {weekday}",
        "edit_prompt": "✏️ <b>{n}-kun ({weekday})</b> uchun yangi post "
                       "matnini yuboring (CTA bilan birga):",
        "edit_done": "✅ {n}-kun posti yangilandi.",
        "edit_back": "◀️ Orqaga — rejaga",
        # --- Limit / navbat nazorati ---
        "quota_full": "⚠️ <b>Navbat limiti</b>\n\nHozir navbatda: "
                      "<b>{current}/{max}</b> post.\n7 kunlik reja uchun "
                      "yetarli joy yo'q (kamida <b>{needed}</b> bo'sh joy "
                      "kerak).\n\nEski postlarni o'chiring yoki 💎 PRO "
                      "tarifiga o'ting — u yerda navbat cheksiz.",
        "quota_btn_pro": "💎 PRO",
        "sched_ok": "✅ <b>{count} ta post navbatga qo'yildi!</b>\n\n"
                    "Barchasi bitta atomik tranzaksiyada saqlandi — "
                    "yarim-yorti reja qolmaydi.\n\n{lines}",
        "sched_day_line": "• {weekday} ({date}) — {time}",
        "sched_error": "⚠️ Postlarni navbatga qo'yishda xatolik yuz berdi. "
                       "Hech narsa saqlanmadi (atomik). Keyinroq urinib "
                       "ko'ring.",
        # --- Dublikat ogohlantirishi ---
        "dup_header": "⚠️ O'xshash post topildi. Bu post yaqindagi "
                      "postingizga juda o'xshaydi.",
        "dup_days": "\n\nTa'sirlangan kunlar: {days}\nO'xshashlik: {score}%",
        "dup_match": "\n\n<i>Kanalning oxirgi postidan parcha:</i>\n"
                     "<blockquote>{preview}</blockquote>",
        "btn_dup_force": "🚀 Baribir",
        "btn_dup_refresh": "✨ AI bilan",
        "dup_refreshing": "⏳ O'xshash postlar AI bilan yangilanmoqda...",
        "dup_refresh_done": "✨ Ta'sirlangan postlar yangilandi — endi "
                            "boshqacha. Qayta tekshirib ko'ring.",
        "dup_refresh_failed": "⚠️ AI bilan yangilash hozircha ishlamadi. "
                              "Postlarni qo'lda tahrirlashingiz mumkin.",
        # --- Umumiy ---
        "cancel_done": "❌ Avtopilot bekor qilindi.",
        "stale": "Sessiya eskirgan — avtopilotni qaytadan boshlang.",
        "no_channel": "Kanal topilmadi.",
        # PHASE 3 — RBAC/IDOR: ruxsatsiz avtopilot urinishi (yopiq rad).
        "no_permission": (
            "⛔ Ruxsat yo'q (Permission Denied). Bu kanalda avtopilot "
            "rejasini rejalashtirish huquqingiz yo'q."
        ),
        # --- PHASE 8: 7-Day Autopilot V2 (Strategy & Approval Modes) ---
        "v2_strategy_box": (
            "\n\n🧭 <b>Strategiya (V2):</b>\n"
            "• 🎯 Maqsad: <b>{goal}</b>\n"
            "• 📊 Chastota: <b>{frequency}x / kun</b>\n"
            "• 🛡 Rejim: <b>{mode}</b>\n"
            "• 🌙 Tinchlik soati: <b>{quiet}</b>"
        ),
        "v2_post_card": (
            "📄 <b>Post #{n} · {weekday} ({date}) — {time}</b>\n"
            "📌 Mavzu: <b>{topic}</b>\n"
            "🏷 Format: <i>{fmt}</i> · ⭐ Sifat: <b>{score}%</b>\n"
            "📌 Holat: <b>{status}</b>{quiet_note}\n\n"
            "{post}"
        ),
        "v2_quiet_shifted": "\n🌙 <i>Quiet Hours sababli ertalabki optimal vaqtga ko'chirildi</i>",
        "v2_status_pending": "⏳ Tasdiq kutmoqda",
        "v2_status_approved": "✅ Jadvalda",
        "v2_status_auto": "⚡ Avto-jadvalda",
        "v2_status_review": "⚠️ Ko'rib chiqish kerak",
        "v2_semi_summary": (
            "⚡ <b>SEMI-AUTO:</b> yuqori sifatli (≥80%) <b>{auto_count}</b> ta post "
            "avtomatik rejalashtirildi; <b>{review_count}</b> ta post tasdiq kutmoqda."
        ),
        "v2_auto_pro_only": (
            "🔒 <b>AUTO rejimi faqat 💎 PRO foydalanuvchilar uchun!</b>\n"
            "PRO tarifiga o'ting yoki MANUAL / SEMI-AUTO rejimini tanlang."
        ),
        "v2_post_approved": "✅ {n}-post tasdiqlandi va jadvalga qo'yildi!",
        "v2_post_deleted": "🗑 {n}-post rejadan o'chirildi.",
        "v2_post_regenerated": "🔄 {n}-post AI bilan yangilandi.",
        "btn_post_approve": "✅ Tasdiqlash",
        "btn_post_edit": "✏️ Tahrirlash",
        "btn_post_regen": "🔄 Yangilash",
        "btn_post_delete": "🗑 O'chirish",
        "btn_goal_growth": "📈 O'sish",
        "btn_goal_sales": "💰 Sotuv",
        "btn_goal_engagement": "💬 Faollik",
        "btn_goal_expertise": "🎯 Ekspertiza",
        "btn_mode_manual": "👁 Manual",
        "btn_mode_semi": "⚡ Semi-Auto",
        "btn_mode_auto": "🤖 Auto (PRO)",
        "btn_quiet_on": "🌙 23:00-08:00",
        "btn_quiet_off": "🔔 Tinchlik: Yo'q",
    },
    "ru": {
        "intro": "🚀 <b>AI АВТОПИЛОТ</b>\n\nКанал: <b>{channel}</b>\n\n"
                 "Введите тему или направление — AI с учётом стиля канала "
                 "(Channel DNA) и лучшего времени составит полный план "
                 "постов на 7 дней (понедельник–воскресенье):\n\n"
                 "<i>Например: новое меню кофейни; онлайн-курсы английского; "
                 "автомойка</i>",
        "generating": "⏳ Составляю план на 7 дней... Подождите немного.",
        "ai_failed": "План пока не удалось составить. Попробуйте позже или "
                     "уточните тему.",
        "topic_too_short": "Тема слишком короткая. Напишите направление "
                           "(минимум 3 символа):",
        "plan_header": "🚀 <b>7-ДНЕВНЫЙ ПЛАН AI АВТОПИЛОТА</b>\n"
                       "Канал: <b>{channel}</b>\nТема: <b>{topic}</b>\n"
                       "{time_note}\n\n",
        "time_note_best": "⏰ Время — по статистике лучшего времени канала "
                          "({window}).",
        "time_note_default": "⏣ Статистики времени канала мало — "
                             "использовано стандартное {hour}:00.",
        "plan_day": "<b>День {n} · {weekday} ({date}) — {time}</b>\n"
                    "<i>Формат: {fmt}</i>\n\n{post}\n\n"
                    "➖➖➖➖➖➖➖➖➖➖➖➖➖\n",
        "confirm_hint": "👇 Подтвердите план:",
        "btn_schedule_all": "🚀 Всё",
        "btn_edit": "✏️ Изменить",
        "btn_regen": "🔄 Создать заново",
        "btn_cancel": "❌ Отмена",
        "edit_pick": "✏️ Какой день изменяем?",
        "edit_day_btn": "День {n} · {weekday}",
        "edit_prompt": "✏️ Отправьте новый текст поста для <b>дня {n} "
                       "({weekday})</b> (вместе с CTA):",
        "edit_done": "✅ Пост дня {n} обновлён.",
        "edit_back": "◀️ Назад к плану",
        "quota_full": "⚠️ <b>Лимит очереди</b>\n\nСейчас в очереди: "
                      "<b>{current}/{max}</b> постов.\nДля 7-дневного плана "
                      "не хватает места (нужно минимум <b>{needed}</b> "
                      "свободных слотов).\n\nУдалите старые посты или "
                      "перейдите на 💎 PRO — там очередь без ограничений.",
        "quota_btn_pro": "💎 PRO",
        "sched_ok": "✅ <b>{count} постов поставлено в очередь!</b>\n\n"
                    "Всё сохранено одной атомарной транзакцией — "
                    "частичного плана не будет.\n\n{lines}",
        "sched_day_line": "• {weekday} ({date}) — {time}",
        "sched_error": "⚠️ Не удалось поставить посты в очередь. Ничего не "
                       "сохранено (атомарно). Попробуйте позже.",
        "dup_header": "⚠️ Найден похожий пост. Этот пост очень похож на "
                      "ваш недавний.",
        "dup_days": "\n\nЗатронутые дни: {days}\nСходство: {score}%",
        "dup_match": "\n\n<i>Фрагмент последнего поста канала:</i>\n"
                     "<blockquote>{preview}</blockquote>",
        "btn_dup_force": "🚀 Всё равно",
        "btn_dup_refresh": "✨ Обновить (AI)",
        "dup_refreshing": "⏳ Похожие посты обновляются с помощью AI...",
        "dup_refresh_done": "✨ Похожие посты обновлены — теперь другие. "
                            "Проверьте ещё раз.",
        "dup_refresh_failed": "⚠️ Обновление через AI сейчас не сработало. "
                              "Вы можете отредактировать посты вручную.",
        "cancel_done": "❌ Автопилот отменён.",
        "stale": "Сессия устарела — начните автопилот заново.",
        "no_channel": "Канал не найден.",
        # PHASE 3 — RBAC/IDOR: отказ в доступе (закрытое отклонение).
        "no_permission": (
            "⛔ Нет доступа (Permission Denied). У вас нет прав "
            "планировать автопилот в этом канале."
        ),
        # --- PHASE 8: 7-Day Autopilot V2 (Strategy & Approval Modes) ---
        "v2_strategy_box": (
            "\n\n🧭 <b>Стратегия (V2):</b>\n"
            "• 🎯 Цель: <b>{goal}</b>\n"
            "• 📊 Частота: <b>{frequency}x / день</b>\n"
            "• 🛡 Режим: <b>{mode}</b>\n"
            "• 🌙 Тихие часы: <b>{quiet}</b>"
        ),
        "v2_post_card": (
            "📄 <b>Пост #{n} · {weekday} ({date}) — {time}</b>\n"
            "📌 Тема: <b>{topic}</b>\n"
            "🏷 Формат: <i>{fmt}</i> · ⭐ Качество: <b>{score}%</b>\n"
            "📌 Статус: <b>{status}</b>{quiet_note}\n\n"
            "{post}"
        ),
        "v2_quiet_shifted": "\n🌙 <i>Перенесён на утро из-за тихих часов</i>",
        "v2_status_pending": "⏳ Ожидает одобрения",
        "v2_status_approved": "✅ Запланирован",
        "v2_status_auto": "⚡ Авто-запланирован",
        "v2_status_review": "⚠️ Требует проверки",
        "v2_semi_summary": (
            "⚡ <b>SEMI-AUTO:</b> высококачественных (≥80%) постов запланировано: "
            "<b>{auto_count}</b>; ожидают подтверждения: <b>{review_count}</b>."
        ),
        "v2_auto_pro_only": (
            "🔒 <b>Режим AUTO доступен только для 💎 PRO!</b>\n"
            "Перейдите на PRO или выберите режим MANUAL / SEMI-AUTO."
        ),
        "v2_post_approved": "✅ Пост #{n} одобрен и поставлен в очередь!",
        "v2_post_deleted": "🗑 Пост #{n} удалён из плана.",
        "v2_post_regenerated": "🔄 Пост #{n} обновлён с помощью AI.",
        "btn_post_approve": "✅ Одобрить",
        "btn_post_edit": "✏️ Изменить",
        "btn_post_regen": "🔄 Обновить",
        "btn_post_delete": "🗑 Удалить",
        "btn_goal_growth": "📈 Рост",
        "btn_goal_sales": "💰 Продажи",
        "btn_goal_engagement": "💬 Актив",
        "btn_goal_expertise": "🎯 Эксперт",
        "btn_mode_manual": "👁 Вручную",
        "btn_mode_semi": "⚡ Полуавто",
        "btn_mode_auto": "🤖 Авто (PRO)",
        "btn_quiet_on": "🌙 23:00-08:00",
        "btn_quiet_off": "🔔 Тишина: Нет",
    },
    "en": {
        "intro": "🚀 <b>AI AUTOPILOT</b>\n\nChannel: <b>{channel}</b>\n\n"
                 "Enter a topic or direction — AI will build a full 7-day "
                 "post plan (Monday–Sunday) based on your channel's style "
                 "(Channel DNA) and best-time statistics:\n\n"
                 "<i>For example: new coffee shop menu; online English "
                 "courses; car wash service</i>",
        "generating": "⏳ Building your 7-day plan... Please wait.",
        "ai_failed": "The plan could not be created right now. Try again "
                     "later or make the topic more specific.",
        "topic_too_short": "The topic is too short. Please describe the "
                           "direction (at least 3 characters):",
        "plan_header": "🚀 <b>7-DAY AI AUTOPILOT PLAN</b>\n"
                       "Channel: <b>{channel}</b>\nTopic: <b>{topic}</b>\n"
                       "{time_note}\n\n",
        "time_note_best": "⏰ Times follow the channel's best-time "
                          "statistics ({window}).",
        "time_note_default": "⏰ Not enough channel time statistics — "
                             "default {hour}:00 used.",
        "plan_day": "<b>Day {n} · {weekday} ({date}) — {time}</b>\n"
                    "<i>Format: {fmt}</i>\n\n{post}\n\n"
                    "➖➖➖➖➖➖➖➖➖➖➖➖➖\n",
        "confirm_hint": "👇 Confirm the plan:",
        "btn_schedule_all": "🚀 Schedule all",
        "btn_edit": "✏️ Edit",
        "btn_regen": "🔄 Regenerate",
        "btn_cancel": "❌ Cancel",
        "edit_pick": "✏️ Which day do you want to edit?",
        "edit_day_btn": "Day {n} · {weekday}",
        "edit_prompt": "✏️ Send the new post text for <b>day {n} "
                       "({weekday})</b> (including the CTA):",
        "edit_done": "✅ Day {n} post updated.",
        "edit_back": "◀️ Back",
        "quota_full": "⚠️ <b>Queue limit</b>\n\nCurrently in queue: "
                      "<b>{current}/{max}</b> posts.\nThere is not enough "
                      "room for a 7-day plan (at least <b>{needed}</b> free "
                      "slots required).\n\nDelete old posts or upgrade to "
                      "💎 PRO — its queue is unlimited.",
        "quota_btn_pro": "💎 PRO",
        "sched_ok": "✅ <b>{count} posts scheduled!</b>\n\nEverything was "
                    "saved in a single atomic transaction — no half-saved "
                    "plans.\n\n{lines}",
        "sched_day_line": "• {weekday} ({date}) — {time}",
        "sched_error": "⚠️ Failed to schedule the posts. Nothing was saved "
                       "(atomic). Please try again later.",
        "dup_header": "⚠️ Similar post found. This post is very similar to "
                      "your recent one.",
        "dup_days": "\n\nAffected days: {days}\nSimilarity: {score}%",
        "dup_match": "\n\n<i>Fragment of the channel's recent post:</i>\n"
                     "<blockquote>{preview}</blockquote>",
        "btn_dup_force": "🚀 Post anyway",
        "btn_dup_refresh": "✨ Refresh with AI",
        "dup_refreshing": "⏳ Refreshing similar posts with AI...",
        "dup_refresh_done": "✨ Affected posts refreshed — now different. "
                            "Check again.",
        "dup_refresh_failed": "⚠️ AI refresh is unavailable right now. You "
                              "can edit the posts manually.",
        "cancel_done": "❌ Autopilot cancelled.",
        "stale": "Session expired — start the autopilot again.",
        "no_channel": "Channel not found.",
        # PHASE 3 — RBAC/IDOR: permission denied (closed rejection).
        "no_permission": (
            "⛔ Permission denied. You are not allowed to schedule the "
            "autopilot plan in this channel."
        ),
        # --- PHASE 8: 7-Day Autopilot V2 (Strategy & Approval Modes) ---
        "v2_strategy_box": (
            "\n\n🧭 <b>Strategy (V2):</b>\n"
            "• 🎯 Goal: <b>{goal}</b>\n"
            "• 📊 Frequency: <b>{frequency}x / day</b>\n"
            "• 🛡 Mode: <b>{mode}</b>\n"
            "• 🌙 Quiet Hours: <b>{quiet}</b>"
        ),
        "v2_post_card": (
            "📄 <b>Post #{n} · {weekday} ({date}) — {time}</b>\n"
            "📌 Topic: <b>{topic}</b>\n"
            "🏷 Format: <i>{fmt}</i> · ⭐ Quality: <b>{score}%</b>\n"
            "📌 Status: <b>{status}</b>{quiet_note}\n\n"
            "{post}"
        ),
        "v2_quiet_shifted": "\n🌙 <i>Shifted to morning optimal time due to Quiet Hours</i>",
        "v2_status_pending": "⏳ Pending approval",
        "v2_status_approved": "✅ Scheduled",
        "v2_status_auto": "⚡ Auto-scheduled",
        "v2_status_review": "⚠️ Needs review",
        "v2_semi_summary": (
            "⚡ <b>SEMI-AUTO:</b> high-quality (≥80%) posts auto-scheduled: "
            "<b>{auto_count}</b>; awaiting approval: <b>{review_count}</b>."
        ),
        "v2_auto_pro_only": (
            "🔒 <b>AUTO mode is available for 💎 PRO users only!</b>\n"
            "Upgrade to PRO or choose MANUAL / SEMI-AUTO mode."
        ),
        "v2_post_approved": "✅ Post #{n} approved and scheduled!",
        "v2_post_deleted": "🗑 Post #{n} deleted from the plan.",
        "v2_post_regenerated": "🔄 Post #{n} regenerated with AI.",
        "btn_post_approve": "✅ Approve",
        "btn_post_edit": "✏️ Edit",
        "btn_post_regen": "🔄 Regenerate",
        "btn_post_delete": "🗑 Delete",
        "btn_goal_growth": "📈 Growth",
        "btn_goal_sales": "💰 Sales",
        "btn_goal_engagement": "💬 Engage",
        "btn_goal_expertise": "🎯 Expert",
        "btn_mode_manual": "👁 Manual",
        "btn_mode_semi": "⚡ Semi-Auto",
        "btn_mode_auto": "🤖 Auto (PRO)",
        "btn_quiet_on": "🌙 23:00-08:00",
        "btn_quiet_off": "🔔 Quiet: Off",
    },
}

AUTOPILOT_KEYS = tuple(sorted(AUTOPILOT_I18N["uz"]))


def autopilot_t(key: str, lang: str = "uz", **kwargs) -> str:
    """Tilga mos matn (noma'lum til → uz, noma'lum kalit → uz qiymati)."""
    table = AUTOPILOT_I18N.get(normalize_lang(lang), AUTOPILOT_I18N["uz"])
    text = table.get(key, AUTOPILOT_I18N["uz"][key])
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def autopilot_parity_report() -> dict:
    """UZ ↔ RU ↔ EN kalit pariteti hisoboti (testlar uchun)."""
    return {
        lang: tuple(sorted(values)) == AUTOPILOT_KEYS
        for lang, values in AUTOPILOT_I18N.items()
    }
