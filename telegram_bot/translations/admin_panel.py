"""👑 ADMIN PANEL — i18n lug'ati (UZ / RU / EN, 100% paritet).

FAZA 26 — ``handlers/admin.py`` dagi QOTIB QOLGAN (hardcoded) o'zbekcha
matnlar shu modulga ko'chirildi. Endi admin panelning BARCHA foydalanuvchi
(admin) ko'radigan xabarlari ``admin_t()`` orqali, adminning TANLANGAN
tilida chiqadi (uz/ru/en) — qotirilgan matn qolmaydi.

Modul ``translations/settings_stats.py`` bilan bir xil naqshda ishlaydi:

    from translations import admin_t
    admin_t("dash_title", lang)               # «👑 Admin Boshqaruv Paneli»
    admin_t("gp_granted", lang, user=..., days=30)

Paritet qo'riqchisi: :func:`admin_panel_parity_report` — UZ kalitlari
asos qilib olinadi; RU/EN da kalit yetishmasa/ortiqcha bo'lsa yoki
``{format}`` ko'rsatkichlari mos kelmasa — ``in_sync: False`` (testlar shu
hisobotni qat'iy tekshiradi).

Eslatma (RBAC dekoratorlari): ``@require_permission(message=...)`` /
``@require_role(message=...)`` rad javoblari import paytida UZ yorlig'i
bilan bog'lanadi (``admin_t(key, "uz")``) — dekorator foydalanuvchi
kontekstisiz ishlaydi; rad matni baribir yagona lug'atdan olinadi.
"""

from __future__ import annotations

from locales.translations import normalize_lang, safe_t

# ---------------------------------------------------------------------------
# I18N LUG'ATI
# ---------------------------------------------------------------------------
ADMIN_PANEL_I18N = {
    # ------------------------------------------------------------
    # 🇺🇿 O'ZBEK TILI (asos — paritet shu kalitlar bo'yicha o'lchanadi)
    # ------------------------------------------------------------
    "uz": {
        # --- 👑 Admin dashboard ---
        "dash_title": "👑 <b>Admin Boshqaruv Paneli</b>",
        "dash_users": "👥 Jami foydalanuvchilar: <b>{users} ta</b>",
        "dash_pro": "⭐️ PRO obunachilar: <b>{pro} ta</b>",
        "dash_channels": "📢 Ulangan faol kanallar: <b>{channels} ta</b>",
        "dash_posts_today": "📝 Bugun chiqarilgan postlar: <b>{posts} ta</b>",
        "dash_pending": "⏳ Navbatdagi postlar: <b>{pending} ta</b>",
        "dash_stars": "⭐️ Telegram Stars tushumi: <b>{stars} XTR</b>",
        "dash_pick_section": "Kerakli bo'limni tanlang 👇",

        # --- 📊 To'liq statistika ---
        "fs_title": "📊 <b>To'liq Statistika:</b>",
        "fs_users": "👥 Jami foydalanuvchilar: <b>{users} ta</b>",
        "fs_channels": "📢 Ulangan kanallar: <b>{channels} ta</b>",
        "fs_sponsors": "📢 Homiy kanallar: <b>{sponsors} ta</b>",
        "fs_pending": "⏳ Kutilayotgan postlar: <b>{pending} ta</b>",
        "fs_sent": "✅ Yuborilgan postlar: <b>{sent} ta</b>",
        "fs_cancelled": "🚫 Bekor qilingan: <b>{cancelled} ta</b>",
        "fs_failed": "⚠️ Xatolik: <b>{failed} ta</b>",

        # --- 📋 Barcha postlar ---
        "posts_empty_title": "📋 <b>Barcha postlar</b>",
        "posts_empty_body": "<i>Hozircha hech qanday post mavjud emas.</i>",
        "posts_recent_header": "📋 <b>Oxirgi {count} ta post:</b>",
        "posts_unknown_channel": "Noma'lum kanal",

        # --- 📋 Ulangan kanallar ro'yxati ---
        "channels_recent_header": (
            "📋 <b>Eng so'nggi {count} ta ulangan kanal "
            "(ko'pi bilan {limit}):</b>"
        ),
        "channels_entry": "📢 <b>{title}</b> (<code>{channel}</code>)\n   👤 Egasi: {owner}",
        "channels_omitted_footer": (
            "… {count} ta kanal Telegramning 4096 belgilik limiti sabab "
            "ko'rsatilmagan."
        ),
        "channel_generic_title": "Kanal",
        "channels_empty_title": "📋 <b>Ulangan kanallar</b>",
        "channels_empty_body": "<i>Hozircha hech qanday kanal ulanmagan.</i>",
        "channels_none_legacy": "Hozircha ulangan kanallar yo'q.",

        # --- 🗄️ DB Pool va Kesh ---
        "dbc_title": "🗄️ <b>DB Pool va Kesh holati:</b>",
        "dbc_pool": "   • Pool: <b>{pool}</b> ({message})",
        "dbc_minmax": "   • Min/Maks: <b>{minv} / {maxv}</b>",
        "dbc_usage": (
            "   • Band: <b>{used}</b> | Bo'sh: <b>{available}</b> | "
            "Yopiq: <b>{collapsed}</b>"
        ),
        "dbc_cache": "   • Kesh: <b>{cache}</b> — <b>{entries} ta</b> yozuv",
        "dbc_footer": (
            "Kesh TTL o'zgarishlarsiz avtomatik eskiradi. Tozalash kerak "
            "bo'lsa pastdagi tugmani bosing."
        ),
        "dbc_cleared_footer": "✅ <b>Kesh tozalandi.</b>",
        "cache_clear_toast": "✅ Kesh tozalandi.",
        "cache_denied_owner": "❌ Keshni faqat bot egasi (OWNER) tozalay oladi.",
        "lbl_yes": "ha",
        "lbl_no": "yo'q",
        "lbl_cache_on": "yoqilgan",
        "lbl_cache_off": "o'chirilgan",
        "lbl_pool_ready": "✅ ishlayapti",
        "lbl_pool_init": "⏳ hali ochilmagan",

        # --- 📜 Audit | Rollar ---
        "audit_log_title": "📜 <b>Audit jurnali</b> (oxirgi harakatlar)",
        "audit_empty_inline": "<i>Audit jurnali hozircha bo'sh.</i>",
        "audit_roles_title": "👥 <b>Rollar</b> (RBAC — /setrole, /delrole)",
        "audit_roles_empty": "<i>Qo'shimcha rollar berilmagan (faqat legacy ADMIN_IDS).</i>",
        "audit_denied": "❌ Audit jurnalini faqat OWNER yoki SUPER_ADMIN ko'ra oladi.",
        "audit_cmd_empty": (
            "📝 <b>Audit jurnali hozircha bo'sh.</b>\n"
            "<i>Admin harakatlari (chek, PRO, promo, sozlamalar) shu yerda "
            "ko'rinadi.</i>"
        ),
        "audit_cmd_header": "📝 <b>Oxirgi admin harakatlari</b> (jami {count} ta):",

        # --- ⚙️ AI parametrlari ---
        "ai_title": "⚙️ <b>AI parametrlarni boshqarish:</b>",
        "ai_howto": (
            "O'zgartirish uchun quyidagi formatda satrlarni yuboring:\n"
            "<code>kalit=qiymat</code>\n\n"
            "Masalan:\n"
            "<code>temperature=0.4</code>\n"
            "<code>max_tokens=2048</code>\n"
            "<code>context_messages=8</code>\n"
            "<code>max_tokens=off</code>  <i>(parametr umuman yuborilmaydi)</i>"
        ),
        "ai_reset_hint": "👉 Hammasini defaultga qaytarish uchun <code>reset</code> deb yozing.",
        "ai_cancel_hint": "Bekor qilish uchun asosiy menyu tugmasini bosing.",
        "ai_reset_done": "✅ <b>Barcha AI parametrlar default holatga qaytarildi.</b>",
        "ai_updated": "✅ <b>AI parametrlar yangilandi:</b>",
        "ai_err_header": "⚠️ <b>Quyidagi kalitlarni o'zgartirib bo'lmadi:</b>",
        "ai_err_unknown_key": "<code>{key}</code> — noma'lum kalit",
        "ai_err_bad_value": "<code>{key}</code> = <code>{value}</code> — noto'g'ri qiymat",
        "ai_err_nothing": "⚠️ Hech qanday kalit kiritilmadi. <code>kalit=qiymat</code> formatida yuboring.",
        "ai_denied_owner": "❌ AI parametrlarini faqat bot egasi (OWNER) o'zgartira oladi.",
        "ai_hint_temperature": "0.0–2.0 (0.2 = aniq)",
        "ai_hint_max_tokens": "128–8192 (1024) yoki off",
        "ai_hint_top_p": "0.0–1.0 (1.0) yoki off",
        "ai_hint_max_prompt_chars": "500–12000 belgi (3000)",
        "ai_hint_context_chars": "500–20000 belgi (4000)",
        "ai_hint_context_messages": "0–20 dona (6)",
        "ai_hint_extra_context": "matn (bo'sh qoldirsangiz o'chadi)",

        # --- 🏷 Post nishoni (watermark) ---
        "tag_title": "🏷 <b>Post nishoni (watermark):</b>",
        "tag_current": "Hozirgi qiymat: <code>{value}</code>",
        "tag_empty_value": "(bo'sh — nishon yo'q)",
        "tag_howto": (
            "Postlar oxiriga qo'shiladigan matnni yuboring.\n"
            "Masalan: <code>@PostAssistrobot</code>\n"
            "O'chirish uchun <code>clear</code> deb yozing."
        ),
        "tag_denied_owner": "❌ Post nishonini faqat bot egasi (OWNER) o'zgartira oladi.",
        "tag_cleared": "✅ <b>Post nishoni o'chirildi</b> — postlar toza chiqadi.",
        "tag_saved": "✅ <b>Post nishoni saqlandi:</b>\n\n<code>{value}</code>",

        # --- RBAC rad javoblari ---
        "rbac_denied": "Ruxsat yo'q.",
        "rbac_denied_msg": "🚫 Ruxsat yo'q.",
        "perm_health": "❌ Sizda tizim holatini ko'rish uchun ruxsat yo'q.",
        "perm_promo": "❌ Sizda promo-kod boshqaruvi uchun ruxsat yo'q.",
        "perm_promo_create": "❌ Sizda promo-kod yaratish uchun ruxsat yo'q.",
        "perm_grant_pro": "❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.",
        "perm_broadcast": "❌ Sizda broadcast yuborish uchun ruxsat yo'q.",

        # --- ❌ Bekor qilish ---
        "cancelled_toast": "🚫 Bekor qilindi",
        "cancelled_html": "🚫 <b>Jarayon bekor qilindi.</b>",

        # --- 🎁 Promo-kod ---
        "promo_title": "🎁 <b>Promo-kod yaratish:</b>",
        "promo_howto": (
            "Format: <code>KOD KUNLAR [MAKS_ISHLATISH]</code>\n\n"
            "Masalan:\n"
            "• <code>MAXSUS30 30 50</code> — 30 kun PRO, 50 marta\n"
            "• <code>YANGI2026 30</code> — 30 kun PRO, cheksiz\n\n"
            "Promo-kodni yozing:"
        ),
        "promo_bad_format": "❌ Noto'g'ri format. <code>KOD KUNLAR [MAKS]</code> deb yozing.",
        "promo_days_not_number": "❌ Kunlar soni raqam bo'lishi kerak.",
        "promo_max_not_number": "❌ Maks ishlatish soni raqam bo'lishi kerak.",
        "days_positive": "❌ Kunlar soni 0 dan katta bo'lishi kerak.",
        "promo_created": (
            "✅ <b>Promo-kod yaratildi!</b>\n\n"
            "🏷 Kod: <code>{code}</code>\n"
            "📅 Muddat: <b>{days} kun</b> PRO\n"
            "🔢 Maks ishlatish: <b>{max_str}</b>"
        ),
        "promo_exists": "❌ Promo-kod yaratishda xatolik. Bu kod allaqachon mavjud bo'lishi mumkin.",
        "lbl_unlimited": "cheksiz",
        "lbl_times_n": "{count} marta",

        # --- ⭐️ PRO berish ---
        "gp_title": "⭐️ <b>Foydalanuvchiga PRO berish:</b>",
        "gp_howto": (
            "Format: <code>USER_ID KUNLAR</code>\n\n"
            "Masalan: <code>123456789 30</code>\n\n"
            "User ID va kunlar sonini yozing:"
        ),
        "gp_bad_format": "❌ Noto'g'ri format. <code>USER_ID KUNLAR</code> deb yozing.",
        "gp_bad_numbers": "❌ Raqamlar noto'g'ri. <code>USER_ID KUNLAR</code> deb yozing.",
        "gp_granted": (
            "✅ <b>PRO tarif berildi!</b>\n\n"
            "👤 Foydalanuvchi: <code>{user}</code>\n"
            "📅 Muddat: <b>{days} kun</b>"
        ),
        "gp_user_notice": (
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            "Sizga <b>{days} kunlik PRO tarif</b> berildi!\n"
            "Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
        ),
        "gp_error": "❌ Xatolik yuz berdi. User ID to'g'riligini tekshiring.",

        # --- ✉️ Broadcast ---
        "bc_title": "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>",
        "bc_prompt": "Yuboriladigan xabar matnini yozing:",
        "bc_started": (
            "⏳ Xabar <b>{count} ta</b> foydalanuvchiga yuborilmoqda...\n"
            "<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>"
        ),
        "bc_busy": (
            "⏳ <b>Avvalgi xabar yuborilishi hali davom etmoqda.</b>\n"
            "Iltimos, yakunlanishini kuting (natija haqida xabar keladi)."
        ),
        "bc_done": (
            "✅ <b>Xabar tarqatildi!</b>\n\n"
            "Yetib bordi: <b>{sent} / {total}</b> ta foydalanuvchiga.\n"
            "❌ Yuborilmagan: <b>{failed} ta</b>."
        ),

        # --- 📢 Homiy (sponsor) kanallar ---
        "sp_manage_title": "📢 <b>Majburiy obuna (Sponsor kanallar) boshqaruvi:</b>",
        "sp_count": "Ulangan kanallar soni: <b>{count} ta</b>",
        "sp_empty_inline": "<i>Hozircha hech qanday sponsor kanal ulanmagan.</i>",
        "sp_manage_footer": "Kanalni o'chirish uchun tegishli tugmani bosing yoki yangi kanal qo'shing 👇",
        "sp_list_header": "📢 <b>Majburiy a'zolik (Homiy) kanallari ({count} ta):</b>",
        "sp_list_entry": "{idx}. 🔹 <b>{title}</b>{user} (<code>{channel}</code>)\n   🔗 Havola: {url}",
        "sp_list_empty": "Hozircha hech qanday homiy kanal qo'shilmagan.",
        "sp_list_footer": "O'chirish uchun pastdagi ro'yxatdan tanlang yoki yangi kanal qo'shing 👇",
        "sp_db_error": "⚠️ Homiy kanallarni bazadan o'qib bo'lmadi. Keyinroq urinib ko'ring.",
        "sp_add_title": "➕ <b>Homiy kanal qo'shish:</b>",
        "sp_add_howto": (
            "Kanalning <code>@username</code>ini, ID sini (masalan: "
            "<code>-1001234567890</code>) yoki formatda yuboring:\n"
            "<code>KANAL_ID|KANAL_NOMI|HAVOLA</code>\n\n"
            "⚠️ <i>Bot ushbu kanalda administrator bo'lishi shart.</i>"
        ),
        "sp_add_inline_title": "➕ <b>Yangi majburiy obuna kanali qo'shish:</b>",
        "sp_add_inline_howto": (
            "Kanalning <code>@username</code>ini yoki kanal ID sini "
            "(masalan: <code>-1001234567890</code>) yuboring.\n\n"
            "⚠️ <b>Muhim shartlar:</b>\n"
            "1. Bot ushbu kanalda <b>administrator</b> bo'lishi shart.\n"
            "2. Botga kanal a'zolarini ko'rish huquqi berilgan bo'lishi kerak.\n\n"
            "Bekor qilish uchun ❌ Bekor qilish tugmasini bosing."
        ),
        "sp_added": (
            "✅ <b>Homiy kanal muvaffaqiyatli qo'shildi!</b>\n\n"
            "📢 <b>{title}</b> (<code>{channel}</code>)\n"
            "🔗 {url}"
        ),
        "sp_added_short": "✅ Homiy kanal qo'shildi: <b>{title}</b>",
        "sp_added_full": "✅ Homiy kanal muvaffaqiyatli qo'shildi: <b>{title}</b>",
        "sp_added_detailed": (
            "✅ <b>Sponsor kanal muvaffaqiyatli qo'shildi!</b>\n\n"
            "📢 <b>{title}</b>\n"
            "🆔 <code>{channel}</code>\n"
            "{user}"
            "🔗 {url}"
        ),
        "sp_save_error": "❌ Saqlashda xatolik yuz berdi.",
        "sp_db_save_error": "❌ Bazaga saqlashda xatolik yuz berdi.",
        "sp_not_admin_title": "❌ <b>Bot bu kanalda admin emas!</b>",
        "sp_not_admin_channel": "Kanal: <b>{title}</b> (<code>{chat}</code>)",
        "sp_not_admin_howto": (
            "Iltimos, avval botni ushbu kanalga <b>admin</b> qilib qo'shing "
            "va qaytadan yuboring:"
        ),
        "sp_not_admin_howto_short": (
            "Iltimos, avval botni ushbu kanalga <b>admin</b> qiling va "
            "qayta yuboring:"
        ),
        "sp_generic_title": "Sponsor Kanal",
        "sp_not_found_title": "❌ <b>Kanal topilmadi yoki bot u yerda admin emas!</b>",
        "sp_not_found_details": "Xatolik tafsiloti: <i>{error}</i>",
        "sp_retry_hint": (
            "Iltimos, botni kanalga admin qilganingizga ishonch hosil qilib, "
            "@username yoki ID sini qayta yuboring:"
        ),
        "sp_not_found_legacy": (
            "❌ Kanal topilmadi yoki bot u yerda admin emas ({error}). "
            "Qaytadan kiriting:"
        ),
        "sp_delete_failed": "⚠️ Homiy kanal o'chirilmadi. Qayta urinib ko'ring.",

        # --- 🎯 Reklama boshqaruvi (hub) ---
        "ad_hub_title": "🎯 <b>Reklama boshqaruvi</b> — 3 ta asosiy bo'lim",
        "ad_hub_s1_title": "<b>1) 📢 Majburiy obuna (Sponsor kanallar)</b>",
        "ad_hub_s1_line": (
            "   Ulangan kanallar: <b>{count} ta</b> — matn/tugma va "
            "o'chirish bo'lim ichida."
        ),
        "ad_hub_s2_title": "<b>2) 🤖 3-5 ta javobda chiqadigan reklama</b>",
        "ad_hub_pool_line": "   Matn: pulda <b>{active}</b>/{total} ta faol",
        "ad_hub_interval_reply": "   Oraliq: har <b>{interval}</b> ta javobda",
        "ad_hub_s3_title": "<b>3) 📢 Kanal postlariga reklama qo'shish</b>",
        "ad_hub_interval_channel": (
            "   Oraliq: har <b>{interval}</b>-postda (har kanal uchun alohida)"
        ),
        "ad_hub_state_line": "   Holat: {state}",
        "ad_hub_pick": "Bo'limni tanlang 👇 Matn yuborsangiz 📢 Kanal posti puliga qo'shiladi.",
        "lbl_on": "✅ Yoqilgan",
        "lbl_off": "❌ O'chirilgan",
        "ad_toggle_on": "Javoblar reklamasi yoqildi ✅",
        "ad_toggle_off": "Javoblar reklamasi o'chirildi ❌",
        "ch_ad_toggle_on": "Kanal posti reklamasi yoqildi ✅",
        "ch_ad_toggle_off": "Kanal posti reklamasi o'chirildi ❌",

        # --- 📦 Reklama rotatsiya puli (ad_pool) ---
        "ad_scope_channel": "📢 Kanal postlari",
        "ad_scope_reply": "🤖 Bot javoblari",
        "ad_html_hint": (
            "💡 <b>HTML formatlash mumkin:</b>\n"
            "<code>&lt;b&gt;qalin&lt;/b&gt;</code>, <code>&lt;i&gt;kursiv&lt;/i&gt;</code>, "
            "<code>&lt;u&gt;tagchiziq&lt;/u&gt;</code>, "
            "<code>&lt;a href=\"https://t.me/kanal\"&gt;havola&lt;/a&gt;</code>"
        ),
        "ad_pool_empty": "   <i>(Hozircha hech qanday reklama yo'q)</i>",
        "ad_card_title": "✏️ <b>Reklamani tahrirlash</b> — {title}",
        "ad_card_id": "🆔 ID: <code>{id}</code>",
        "ad_card_status": "📊 Holat: {status}",
        "ad_card_button": "🔗 Inline tugma: {button}",
        "ad_card_text": "📝 <b>Matn (HTML):</b>\n<code>{text}</code>",
        "ad_card_preview": "👁 <b>Ko'rinishi:</b>",
        "ad_card_edit_hint": "Quyidagi tugmalar orqali tahrirlang 👇",
        "ad_status_active": "🟢 Faol (Active)",
        "ad_status_inactive": "🔴 O'chirilgan (Inactive)",
        "ad_button_none": "<i>(tugma yo'q)</i>",
        "ad_pool_title": "{title} — <b>avto-rotatsiya</b>",
        "ad_pool_counts": "📦 Jami: <b>{total} ta</b>  |  🟢 Faol: <b>{active} ta</b>",
        "ad_pool_interval_channel": "⏱ Reklama oralig'i: <b>har {interval}-post</b> (kanal bo'yicha alohida)",
        "ad_pool_interval_reply": "⏱ Reklama oralig'i: <b>har {interval} javob</b>",
        "ad_pool_list_title": "<b>Reklama puli:</b>",
        "ad_pool_footer": (
            "Reklamani tahrirlash uchun uning ustiga bosing. "
            "Bot faqat 🟢 <b>faol</b> reklamalarni navbatma-navbat qo'shadi."
        ),
        "ad_add_new_title": "✍️ <b>{title}</b> — yangi reklama matnini yozing.",
        "ad_add_clear_hint": "<i>Barcha reklamalarni o'chirish uchun</i> <code>clear</code> <i>deb yozing.</i>",
        "ad_new_prompt": "Yangi reklama matnini shu yerga yozib yuborishingiz mumkin (pulga qo'shiladi).",
        "ad_cancel_hint": "Bekor qilish uchun ❌ Bekor qilish tugmasini bosing.",
        "ad_et_title": "✏️ <b>#{id} — yangi matnni yuboring:</b>",
        "ad_et_current": "<b>Hozirgi matn:</b>\n<code>{text}</code>",
        "ad_eb_title": "🔗 <b>#{id} — inline URL tugma:</b>",
        "ad_eb_current": "<b>Hozirgi tugma:</b> {text} → {url}",
        "ad_eb_howto": (
            "Quyidagi formatda yuboring:\n"
            "<code>Tugma matni | https://t.me/kanal</code>\n\n"
            "Tugmani olib tashlash uchun <code>clear</code> deb yozing."
        ),
        "ad_tg_on_toast": "🟢 Reklama faollashtirildi",
        "ad_tg_off_toast": "🔴 Reklama o'chirildi",
        "ad_del_pick": "🗑 <b>{title}</b> — o'chiriladigan reklamani tanlang:",
        "ad_clear_toast": "🧹 {count} ta reklama o'chirildi",
        "ad_cleared_msg": "🧹 Reklamalar tozalandi ({count} ta).",
        "ad_iv_toast": "✅ Endi har {value}-{unit}da reklama chiqadi",
        "ad_unit_post": "post",
        "ad_unit_reply": "javob",
        "ad_iv_title": "⏱ <b>Reklama oralig'ini sozlash</b>",
        "ad_iv_current": "Hozirgi qiymat: <b>har {value}-{unit}</b>",
        "ad_iv_explain_channel": (
            "Bot har nechanchi postda reklama qo'shsin? Sanagich <b>har bir "
            "kanal uchun alohida</b> yuritiladi — bir kanaldagi postlar "
            "boshqasiga ta'sir qilmaydi."
        ),
        "ad_iv_explain_reply": (
            "Bot har nechta javobda reklama qo'shsin? Standart qiymat: "
            "<b>4</b> (ya'ni har 3-5 ta javobda)."
        ),
        "ad_iv_hint": (
            "Tugmalardan tanlang yoki {min}–{max} oralig'idagi sonni "
            "yozib yuboring."
        ),
        "ad_iv_bad_number": "❌ Faqat butun son kiriting (masalan: 3, 4 yoki 5).",
        "ad_iv_out_of_range": "❌ Oraliq {min} va {max} orasida bo'lishi kerak.",
        "ad_iv_updated": "✅ <b>Reklama oralig'i yangilandi:</b> endi har <b>{value}-{unit}da</b> reklama chiqadi.",
        "ad_iv_counter_channel": "<i>Sanagich har bir kanal uchun alohida yuritiladi.</i>",
        "ad_iv_counter_user": "<i>Har bir foydalanuvchi uchun alohida hisoblanadi.</i>",
        "ad_info_title": "ℹ️ <b>{title} — avto-rotatsiya</b>",
        "ad_info_interval_channel": (
            "• Kanal postlari: har <b>{interval}-postda</b> bitta reklama "
            "(sanagich har bir kanal uchun alohida).\n"
        ),
        "ad_info_body": (
            "Pulga bir nechta reklama qo'shsangiz, bot ularni navbatma-navbat "
            "(round-robin) qo'shadi.\n"
            "{interval_line}"
            "• Bot javoblari: har 3-xabarga bitta reklama.\n"
            "• 🔴 holatdagi reklamalar rotatsiyada qatnashmaydi.\n"
            "• Har bir reklamaga inline URL tugma biriktirish mumkin.\n\n"
            "Pul bo'sh bo'lsa eski yagona reklama ishlashda davom etadi."
        ),
        "ad_added": (
            "✅ <b>Reklama rotatsiya puliga qo'shildi!</b>\n"
            "Inline URL tugma qo'shish uchun ro'yxatdan uni tanlang."
        ),
        "ad_text_updated": "✅ <b>Reklama matni yangilandi!</b>",
        "ad_btn_removed": "🚫 <b>Inline tugma olib tashlandi.</b>",
        "ad_btn_saved": "✅ <b>Inline tugma saqlandi:</b> {text} → {url}",
        "ad_btn_bad_format": (
            "❌ Noto'g'ri format. <code>Tugma matni | https://havola</code> "
            "ko'rinishida yuboring.\n"
            "Tugmani olib tashlash uchun <code>clear</code> deb yozing."
        ),

        # --- 👥 Rollar (RBAC buyruqlari) ---
        "role_usage_set": (
            "📝 Foydalanish: <code>/setrole &lt;user_id&gt; &lt;rol&gt;</code>\n\n"
            "Rollar: <code>owner</code>, <code>super_admin</code>, <code>admin</code>, "
            "<code>moderator</code>, <code>finance</code>\n"
            "Rolni olib tashlash uchun <code>user</code> yozing."
        ),
        "role_usage_del": "📝 Foydalanish: <code>/delrole &lt;user_id&gt;</code>",
        "role_bad_id": "❌ Noto'g'ri foydalanuvchi ID. Masalan: /setrole 123456789 admin",
        "role_bad_id_short": "❌ Noto'g'ri foydalanuvchi ID.",
        "role_unknown": "❌ Noma'lum rol. Mumkin: owner, super_admin, admin, moderator, finance, user.",
        "role_save_failed": "❌ Rolni saqlab bo'lmadi (baza bilan aloqa).",
        "role_removed": "✅ <b>Rol olib tashlandi.</b>\n\n👤 Foydalanuvchi: <code>{user}</code>",
        "role_granted": (
            "✅ <b>Rol berildi.</b>\n\n"
            "👤 Foydalanuvchi: <code>{user}</code>\n"
            "🎖 Rol: <b>{role}</b>\n"
            "🔑 Ruxsatlar: <code>{perms}</code>"
        ),
        "role_not_found": "❌ <code>{user}</code> foydalanuvchida DB'dagi rol topilmadi.",
        "role_denied_grant": "❌ Rol berish/olishni faqat OWNER (bot egasi) bajaradi.",
        "role_denied_revoke": "❌ Rol olishni faqat OWNER (bot egasi) bajaradi.",
    },
}

# ---------------------------------------------------------------------------
# 🇷🇺 RUZ TILI — UZ kalitlari bilan 100% paritet
# ---------------------------------------------------------------------------
ADMIN_PANEL_I18N["ru"] = {
    # --- 👑 Админ-панель ---
    "dash_title": "👑 <b>Панель управления администратора</b>",
    "dash_users": "👥 Всего пользователей: <b>{users}</b>",
    "dash_pro": "⭐️ PRO-подписчиков: <b>{pro}</b>",
    "dash_channels": "📢 Активных подключённых каналов: <b>{channels}</b>",
    "dash_posts_today": "📝 Опубликовано постов сегодня: <b>{posts}</b>",
    "dash_pending": "⏳ Посты в очереди: <b>{pending}</b>",
    "dash_stars": "⭐️ Доход Telegram Stars: <b>{stars} XTR</b>",
    "dash_pick_section": "Выберите нужный раздел 👇",

    # --- 📊 Полная статистика ---
    "fs_title": "📊 <b>Полная статистика:</b>",
    "fs_users": "👥 Всего пользователей: <b>{users}</b>",
    "fs_channels": "📢 Подключённых каналов: <b>{channels}</b>",
    "fs_sponsors": "📢 Спонсорских каналов: <b>{sponsors}</b>",
    "fs_pending": "⏳ Ожидающих постов: <b>{pending}</b>",
    "fs_sent": "✅ Отправленных постов: <b>{sent}</b>",
    "fs_cancelled": "🚫 Отменённых: <b>{cancelled}</b>",
    "fs_failed": "⚠️ Ошибок: <b>{failed}</b>",

    # --- 📋 Все посты ---
    "posts_empty_title": "📋 <b>Все посты</b>",
    "posts_empty_body": "<i>Пока нет ни одного поста.</i>",
    "posts_recent_header": "📋 <b>Последние {count} постов:</b>",
    "posts_unknown_channel": "Неизвестный канал",

    # --- 📋 Список подключённых каналов ---
    "channels_recent_header": (
        "📋 <b>Последние {count} подключённых каналов "
        "(макс. {limit}):</b>"
    ),
    "channels_entry": "📢 <b>{title}</b> (<code>{channel}</code>)\n   👤 Владелец: {owner}",
    "channels_omitted_footer": (
        "… {count} каналов не показано из-за лимита Telegram в 4096 символов."
    ),
    "channel_generic_title": "Канал",
    "channels_empty_title": "📋 <b>Подключённые каналы</b>",
    "channels_empty_body": "<i>Пока не подключён ни один канал.</i>",
    "channels_none_legacy": "Пока нет подключённых каналов.",

    # --- 🗄️ Пул БД и кэш ---
    "dbc_title": "🗄️ <b>Состояние пула БД и кэша:</b>",
    "dbc_pool": "   • Пул: <b>{pool}</b> ({message})",
    "dbc_minmax": "   • Мин/Макс: <b>{minv} / {maxv}</b>",
    "dbc_usage": "   • Занято: <b>{used}</b> | Свободно: <b>{available}</b> | Закрыто: <b>{collapsed}</b>",
    "dbc_cache": "   • Кэш: <b>{cache}</b> — <b>{entries}</b> записей",
    "dbc_footer": (
        "Кэш автоматически устаревает без изменения TTL. Для очистки "
        "используйте кнопку ниже."
    ),
    "dbc_cleared_footer": "✅ <b>Кэш очищен.</b>",
    "cache_clear_toast": "✅ Кэш очищен.",
    "cache_denied_owner": "❌ Кэш может очистить только владелец бота (OWNER).",
    "lbl_yes": "да",
    "lbl_no": "нет",
    "lbl_cache_on": "включён",
    "lbl_cache_off": "выключен",
    "lbl_pool_ready": "✅ работает",
    "lbl_pool_init": "⏳ ещё не открыт",

    # --- 📜 Аудит | Роли ---
    "audit_log_title": "📜 <b>Журнал аудита</b> (последние действия)",
    "audit_empty_inline": "<i>Журнал аудита пока пуст.</i>",
    "audit_roles_title": "👥 <b>Роли</b> (RBAC — /setrole, /delrole)",
    "audit_roles_empty": "<i>Дополнительные роли не выданы (только legacy ADMIN_IDS).</i>",
    "audit_denied": "❌ Журнал аудита могут смотреть только OWNER или SUPER_ADMIN.",
    "audit_cmd_empty": (
        "📝 <b>Журнал аудита пока пуст.</b>\n"
        "<i>Действия администраторов (чеки, PRO, промо, настройки) "
        "отображаются здесь.</i>"
    ),
    "audit_cmd_header": "📝 <b>Последние действия администраторов</b> (всего {count}):",

    # --- ⚙️ Параметры ИИ ---
    "ai_title": "⚙️ <b>Управление параметрами ИИ:</b>",
    "ai_howto": (
        "Для изменения отправьте строки в формате:\n"
        "<code>ключ=значение</code>\n\n"
        "Например:\n"
        "<code>temperature=0.4</code>\n"
        "<code>max_tokens=2048</code>\n"
        "<code>context_messages=8</code>\n"
        "<code>max_tokens=off</code>  <i>(параметр вообще не отправится)</i>"
    ),
    "ai_reset_hint": "👉 Чтобы вернуть всё к значениям по умолчанию, напишите <code>reset</code>.",
    "ai_cancel_hint": "Для отмены нажмите кнопку главного меню.",
    "ai_reset_done": "✅ <b>Все параметры ИИ возвращены к значениям по умолчанию.</b>",
    "ai_updated": "✅ <b>Параметры ИИ обновлены:</b>",
    "ai_err_header": "⚠️ <b>Следующие ключи изменить не удалось:</b>",
    "ai_err_unknown_key": "<code>{key}</code> — неизвестный ключ",
    "ai_err_bad_value": "<code>{key}</code> = <code>{value}</code> — неверное значение",
    "ai_err_nothing": "⚠️ Ни один ключ не введён. Отправьте в формате <code>ключ=значение</code>.",
    "ai_denied_owner": "❌ Параметры ИИ может менять только владелец бота (OWNER).",
    "ai_hint_temperature": "0.0–2.0 (0.2 = точность)",
    "ai_hint_max_tokens": "128–8192 (1024) или off",
    "ai_hint_top_p": "0.0–1.0 (1.0) или off",
    "ai_hint_max_prompt_chars": "500–12000 символов (3000)",
    "ai_hint_context_chars": "500–20000 символов (4000)",
    "ai_hint_context_messages": "0–20 шт. (6)",
    "ai_hint_extra_context": "текст (если оставить пустым — удалится)",

    # --- 🏷 Водяной знак поста ---
    "tag_title": "🏷 <b>Водяной знак поста (watermark):</b>",
    "tag_current": "Текущее значение: <code>{value}</code>",
    "tag_empty_value": "(пусто — знак отсутствует)",
    "tag_howto": (
        "Отправьте текст, добавляемый в конец постов.\n"
        "Например: <code>@PostAssistrobot</code>\n"
        "Для удаления напишите <code>clear</code>."
    ),
    "tag_denied_owner": "❌ Водяной знак может менять только владелец бота (OWNER).",
    "tag_cleared": "✅ <b>Водяной знак удалён</b> — посты будут чистыми.",
    "tag_saved": "✅ <b>Водяной знак сохранён:</b>\n\n<code>{value}</code>",

    # --- Ответы RBAC ---
    "rbac_denied": "Доступ запрещён.",
    "rbac_denied_msg": "🚫 Доступ запрещён.",
    "perm_health": "❌ У вас нет доступа к просмотру состояния системы.",
    "perm_promo": "❌ У вас нет доступа к управлению промо-кодами.",
    "perm_promo_create": "❌ У вас нет доступа к созданию промо-кодов.",
    "perm_grant_pro": "❌ У вас нет права выдавать PRO пользователям.",
    "perm_broadcast": "❌ У вас нет права отправлять рассылку.",

    # --- ❌ Отмена ---
    "cancelled_toast": "🚫 Отменено",
    "cancelled_html": "🚫 <b>Процесс отменён.</b>",

    # --- 🎁 Промо-код ---
    "promo_title": "🎁 <b>Создание промо-кода:</b>",
    "promo_howto": (
        "Формат: <code>КОД ДНИ [МАКС_ИСПОЛЬЗОВАНИЙ]</code>\n\n"
        "Например:\n"
        "• <code>MAXSUS30 30 50</code> — 30 дней PRO, 50 раз\n"
        "• <code>YANGI2026 30</code> — 30 дней PRO, без ограничений\n\n"
        "Введите промо-код:"
    ),
    "promo_bad_format": "❌ Неверный формат. Напишите: <code>КОД ДНИ [МАКС]</code>.",
    "promo_days_not_number": "❌ Количество дней должно быть числом.",
    "promo_max_not_number": "❌ Максимальное число использований должно быть числом.",
    "days_positive": "❌ Количество дней должно быть больше 0.",
    "promo_created": (
        "✅ <b>Промо-код создан!</b>\n\n"
        "🏷 Код: <code>{code}</code>\n"
        "📅 Срок: <b>{days} дн.</b> PRO\n"
        "🔢 Макс. использований: <b>{max_str}</b>"
    ),
    "promo_exists": "❌ Ошибка создания промо-кода. Возможно, такой код уже существует.",
    "lbl_unlimited": "без ограничений",
    "lbl_times_n": "{count} раз",

    # --- ⭐️ Выдача PRO ---
    "gp_title": "⭐️ <b>Выдача PRO пользователю:</b>",
    "gp_howto": (
        "Формат: <code>USER_ID ДНИ</code>\n\n"
        "Например: <code>123456789 30</code>\n\n"
        "Введите USER ID и количество дней:"
    ),
    "gp_bad_format": "❌ Неверный формат. Напишите: <code>USER_ID ДНИ</code>.",
    "gp_bad_numbers": "❌ Неверные числа. Напишите: <code>USER_ID ДНИ</code>.",
    "gp_granted": (
        "✅ <b>PRO-тариф выдан!</b>\n\n"
        "👤 Пользователь: <code>{user}</code>\n"
        "📅 Срок: <b>{days} дн.</b>"
    ),
    "gp_user_notice": (
        "🎉 <b>Поздравляем!</b>\n\n"
        "Вам выдан <b>PRO-тариф на {days} дн.</b>!\n"
        "Вы можете пользоваться всеми возможностями PRO."
    ),
    "gp_error": "❌ Произошла ошибка. Проверьте правильность USER ID.",

    # --- ✉️ Рассылка ---
    "bc_title": "✉️ <b>Рассылка всем пользователям:</b>",
    "bc_prompt": "Введите текст рассылки:",
    "bc_started": (
        "⏳ Сообщение отправляется <b>{count}</b> пользователям...\n"
        "<i>Это фоновый режим, отправка пакетами.</i>"
    ),
    "bc_busy": (
        "⏳ <b>Предыдущая рассылка ещё продолжается.</b>\n"
        "Пожалуйста, дождитесь завершения (придёт отчёт)."
    ),
    "bc_done": (
        "✅ <b>Рассылка завершена!</b>\n\n"
        "Доставлено: <b>{sent} / {total}</b> пользователям.\n"
        "❌ Не отправлено: <b>{failed}</b>."
    ),

    # --- 📢 Спонсорские каналы ---
    "sp_manage_title": "📢 <b>Управление обязательной подпиской (спонсорские каналы):</b>",
    "sp_count": "Количество подключённых каналов: <b>{count}</b>",
    "sp_empty_inline": "<i>Пока не подключён ни один спонсорский канал.</i>",
    "sp_manage_footer": "Для удаления канала нажмите соответствующую кнопку или добавьте новый 👇",
    "sp_list_header": "📢 <b>Каналы обязательной подписки ({count}):</b>",
    "sp_list_entry": "{idx}. 🔹 <b>{title}</b>{user} (<code>{channel}</code>)\n   🔗 Ссылка: {url}",
    "sp_list_empty": "Пока не добавлен ни один спонсорский канал.",
    "sp_list_footer": "Для удаления выберите из списка ниже или добавьте новый канал 👇",
    "sp_db_error": "⚠️ Не удалось прочитать спонсорские каналы из базы. Попробуйте позже.",
    "sp_add_title": "➕ <b>Добавление спонсорского канала:</b>",
    "sp_add_howto": (
        "Отправьте <code>@username</code> канала, его ID (например: "
        "<code>-1001234567890</code>) или в формате:\n"
        "<code>ID_КАНАЛА|НАЗВАНИЕ|ССЫЛКА</code>\n\n"
        "⚠️ <i>Бот должен быть администратором этого канала.</i>"
    ),
    "sp_add_inline_title": "➕ <b>Добавление канала обязательной подписки:</b>",
    "sp_add_inline_howto": (
        "Отправьте <code>@username</code> канала или его ID "
        "(например: <code>-1001234567890</code>).\n\n"
        "⚠️ <b>Важные условия:</b>\n"
        "1. Бот должен быть <b>администратором</b> этого канала.\n"
        "2. Боту должно быть дано право видеть участников канала.\n\n"
        "Для отмены нажмите кнопку «❌ Отмена»."
    ),
    "sp_added": (
        "✅ <b>Спонсорский канал успешно добавлен!</b>\n\n"
        "📢 <b>{title}</b> (<code>{channel}</code>)\n"
        "🔗 {url}"
    ),
    "sp_added_short": "✅ Спонсорский канал добавлен: <b>{title}</b>",
    "sp_added_full": "✅ Спонсорский канал успешно добавлен: <b>{title}</b>",
    "sp_added_detailed": (
        "✅ <b>Спонсорский канал успешно добавлен!</b>\n\n"
        "📢 <b>{title}</b>\n"
        "🆔 <code>{channel}</code>\n"
        "{user}"
        "🔗 {url}"
    ),
    "sp_save_error": "❌ Произошла ошибка при сохранении.",
    "sp_db_save_error": "❌ Произошла ошибка при сохранении в базу.",
    "sp_not_admin_title": "❌ <b>Бот не админ в этом канале!</b>",
    "sp_not_admin_channel": "Канал: <b>{title}</b> (<code>{chat}</code>)",
    "sp_not_admin_howto": (
        "Пожалуйста, сначала сделайте бота <b>администратором</b> этого "
        "канала и отправьте заново:"
    ),
    "sp_not_admin_howto_short": (
        "Пожалуйста, сначала сделайте бота <b>администратором</b> этого "
        "канала и отправьте заново:"
    ),
    "sp_generic_title": "Спонсорский канал",
    "sp_not_found_title": "❌ <b>Канал не найден или бот там не админ!</b>",
    "sp_not_found_details": "Детали ошибки: <i>{error}</i>",
    "sp_retry_hint": (
        "Пожалуйста, убедитесь, что бот добавлен администратором в канал, "
        "и отправьте @username или ID заново:"
    ),
    "sp_not_found_legacy": (
        "❌ Канал не найден или бот там не админ ({error}). Введите заново:"
    ),
    "sp_delete_failed": "⚠️ Спонсорский канал не удалён. Попробуйте ещё раз.",

    # --- 🎯 Центр управления рекламой (hub) ---
    "ad_hub_title": "🎯 <b>Управление рекламой</b> — 3 основных раздела",
    "ad_hub_s1_title": "<b>1) 📢 Обязательная подписка (спонсорские каналы)</b>",
    "ad_hub_s1_line": (
        "   Подключённых каналов: <b>{count}</b> — текст/кнопка и отключение "
        "внутри раздела."
    ),
    "ad_hub_s2_title": "<b>2) 🤖 Реклама в 3-5 ответах</b>",
    "ad_hub_pool_line": "   Текст: в пуле <b>{active}</b>/{total} активных",
    "ad_hub_interval_reply": "   Интервал: каждые <b>{interval}</b> ответа",
    "ad_hub_s3_title": "<b>3) 📢 Реклама в постах каналов</b>",
    "ad_hub_interval_channel": (
        "   Интервал: каждый <b>{interval}</b>-й пост (у каждого канала отдельно)"
    ),
    "ad_hub_state_line": "   Статус: {state}",
    "ad_hub_pick": "Выберите раздел 👇 Отправленный текст добавится в пул рекламы постов канала.",
    "lbl_on": "✅ Включено",
    "lbl_off": "❌ Выключено",
    "ad_toggle_on": "Реклама в ответах включена ✅",
    "ad_toggle_off": "Реклама в ответах выключена ❌",
    "ch_ad_toggle_on": "Реклама в постах канала включена ✅",
    "ch_ad_toggle_off": "Реклама в постах канала выключена ❌",

    # --- 📦 Пул ротации рекламы (ad_pool) ---
    "ad_scope_channel": "📢 Посты каналов",
    "ad_scope_reply": "🤖 Ответы бота",
    "ad_html_hint": (
        "💡 <b>Доступно HTML-форматирование:</b>\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>, "
        "<code>&lt;u&gt;подчёркнутый&lt;/u&gt;</code>, "
        "<code>&lt;a href=\"https://t.me/kanal\"&gt;ссылка&lt;/a&gt;</code>"
    ),
    "ad_pool_empty": "   <i>(Пока нет ни одной рекламы)</i>",
    "ad_card_title": "✏️ <b>Редактирование рекламы</b> — {title}",
    "ad_card_id": "🆔 ID: <code>{id}</code>",
    "ad_card_status": "📊 Статус: {status}",
    "ad_card_button": "🔗 Inline-кнопка: {button}",
    "ad_card_text": "📝 <b>Текст (HTML):</b>\n<code>{text}</code>",
    "ad_card_preview": "👁 <b>Предпросмотр:</b>",
    "ad_card_edit_hint": "Редактируйте через кнопки ниже 👇",
    "ad_status_active": "🟢 Активна (Active)",
    "ad_status_inactive": "🔴 Выключена (Inactive)",
    "ad_button_none": "<i>(кнопки нет)</i>",
    "ad_pool_title": "{title} — <b>авто-ротация</b>",
    "ad_pool_counts": "📦 Всего: <b>{total}</b>  |  🟢 Активных: <b>{active}</b>",
    "ad_pool_interval_channel": "⏱ Интервал рекламы: <b>каждый {interval}-й пост</b> (по каналам отдельно)",
    "ad_pool_interval_reply": "⏱ Интервал рекламы: <b>каждые {interval} ответа</b>",
    "ad_pool_list_title": "<b>Пул рекламы:</b>",
    "ad_pool_footer": (
        "Чтобы отредактировать рекламу, нажмите на неё. "
        "Бот добавляет только 🟢 <b>активные</b> рекламы по очереди."
    ),
    "ad_add_new_title": "✍️ <b>{title}</b> — введите текст новой рекламы.",
    "ad_add_clear_hint": "<i>Чтобы удалить все рекламы, напишите</i> <code>clear</code><i>.</i>",
    "ad_new_prompt": "Здесь можно отправить текст новой рекламы (добавится в пул).",
    "ad_cancel_hint": "Для отмены нажмите кнопку «❌ Отмена».",
    "ad_et_title": "✏️ <b>#{id} — отправьте новый текст:</b>",
    "ad_et_current": "<b>Текущий текст:</b>\n<code>{text}</code>",
    "ad_eb_title": "🔗 <b>#{id} — inline URL-кнопка:</b>",
    "ad_eb_current": "<b>Текущая кнопка:</b> {text} → {url}",
    "ad_eb_howto": (
        "Отправьте в формате:\n"
        "<code>Текст кнопки | https://t.me/kanal</code>\n\n"
        "Чтобы убрать кнопку, напишите <code>clear</code>."
    ),
    "ad_tg_on_toast": "🟢 Реклама активирована",
    "ad_tg_off_toast": "🔴 Реклама выключена",
    "ad_del_pick": "🗑 <b>{title}</b> — выберите рекламу для удаления:",
    "ad_clear_toast": "🧹 Удалено реклам: {count}",
    "ad_cleared_msg": "🧹 Рекламы очищены ({count} шт.).",
    "ad_iv_toast": "✅ Теперь реклама выходит каждые {value}-{unit}",
    "ad_unit_post": "пост",
    "ad_unit_reply": "ответ",
    "ad_iv_title": "⏱ <b>Настройка интервала рекламы</b>",
    "ad_iv_current": "Текущее значение: <b>каждые {value}-{unit}</b>",
    "ad_iv_explain_channel": (
        "После какого поста боту добавлять рекламу? Счётчик ведётся "
        "<b>для каждого канала отдельно</b> — посты одного канала не влияют "
        "на другой."
    ),
    "ad_iv_explain_reply": (
        "После скольких ответов боту добавлять рекламу? Стандартное "
        "значение: <b>4</b> (то есть каждые 3-5 ответов)."
    ),
    "ad_iv_hint": (
        "Выберите из кнопок или отправьте число в диапазоне {min}–{max}."
    ),
    "ad_iv_bad_number": "❌ Введите только целое число (например: 3, 4 или 5).",
    "ad_iv_out_of_range": "❌ Интервал должен быть между {min} и {max}.",
    "ad_iv_updated": "✅ <b>Интервал рекламы обновлён:</b> теперь реклама выходит каждые <b>{value}-{unit}</b>.",
    "ad_iv_counter_channel": "<i>Счётчик ведётся для каждого канала отдельно.</i>",
    "ad_iv_counter_user": "<i>Считается для каждого пользователя отдельно.</i>",
    "ad_info_title": "ℹ️ <b>{title} — авто-ротация</b>",
    "ad_info_interval_channel": (
        "• Посты каналов: одна реклама каждые <b>{interval} постов</b> "
        "(счётчик у каждого канала отдельный).\n"
    ),
    "ad_info_body": (
        "Если добавить в пул несколько реклам, бот добавляет их по очереди "
        "(round-robin).\n"
        "{interval_line}"
        "• Ответы бота: одна реклама на каждые 3 сообщения.\n"
        "• Рекламы в статусе 🔴 не участвуют в ротации.\n"
        "• К каждой рекламе можно привязать inline URL-кнопку.\n\n"
        "Если пул пуст, продолжает работать старая единая реклама."
    ),
    "ad_added": (
        "✅ <b>Реклама добавлена в пул ротации!</b>\n"
        "Чтобы добавить inline URL-кнопку, выберите её в списке."
    ),
    "ad_text_updated": "✅ <b>Текст рекламы обновлён!</b>",
    "ad_btn_removed": "🚫 <b>Inline-кнопка удалена.</b>",
    "ad_btn_saved": "✅ <b>Inline-кнопка сохранена:</b> {text} → {url}",
    "ad_btn_bad_format": (
        "❌ Неверный формат. Отправьте в виде "
        "<code>Текст кнопки | https://ссылка</code>.\n"
        "Чтобы убрать кнопку, напишите <code>clear</code>."
    ),

    # --- 👥 Роли (команды RBAC) ---
    "role_usage_set": (
        "📝 Использование: <code>/setrole &lt;user_id&gt; &lt;роль&gt;</code>\n\n"
        "Роли: <code>owner</code>, <code>super_admin</code>, <code>admin</code>, "
        "<code>moderator</code>, <code>finance</code>\n"
        "Чтобы снять роль, напишите <code>user</code>."
    ),
    "role_usage_del": "📝 Использование: <code>/delrole &lt;user_id&gt;</code>",
    "role_bad_id": "❌ Неверный ID пользователя. Например: /setrole 123456789 admin",
    "role_bad_id_short": "❌ Неверный ID пользователя.",
    "role_unknown": "❌ Неизвестная роль. Возможны: owner, super_admin, admin, moderator, finance, user.",
    "role_save_failed": "❌ Не удалось сохранить роль (нет связи с базой).",
    "role_removed": "✅ <b>Роль снята.</b>\n\n👤 Пользователь: <code>{user}</code>",
    "role_granted": (
        "✅ <b>Роль выдана.</b>\n\n"
        "👤 Пользователь: <code>{user}</code>\n"
        "🎖 Роль: <b>{role}</b>\n"
        "🔑 Разрешения: <code>{perms}</code>"
    ),
    "role_not_found": "❌ У пользователя <code>{user}</code> роль в БД не найдена.",
    "role_denied_grant": "❌ Выдавать/снимать роли может только OWNER (владелец бота).",
    "role_denied_revoke": "❌ Снимать роли может только OWNER (владелец бота).",
}

# ---------------------------------------------------------------------------
# 🇬🇧 INGLIZ TILI — UZ kalitlari bilan 100% paritet
# ---------------------------------------------------------------------------
ADMIN_PANEL_I18N["en"] = {
    # --- 👑 Admin dashboard ---
    "dash_title": "👑 <b>Admin Control Panel</b>",
    "dash_users": "👥 Total users: <b>{users}</b>",
    "dash_pro": "⭐️ PRO subscribers: <b>{pro}</b>",
    "dash_channels": "📢 Active connected channels: <b>{channels}</b>",
    "dash_posts_today": "📝 Posts published today: <b>{posts}</b>",
    "dash_pending": "⏳ Posts in queue: <b>{pending}</b>",
    "dash_stars": "⭐️ Telegram Stars revenue: <b>{stars} XTR</b>",
    "dash_pick_section": "Pick a section 👇",

    # --- 📊 Full statistics ---
    "fs_title": "📊 <b>Full Statistics:</b>",
    "fs_users": "👥 Total users: <b>{users}</b>",
    "fs_channels": "📢 Connected channels: <b>{channels}</b>",
    "fs_sponsors": "📢 Sponsor channels: <b>{sponsors}</b>",
    "fs_pending": "⏳ Pending posts: <b>{pending}</b>",
    "fs_sent": "✅ Sent posts: <b>{sent}</b>",
    "fs_cancelled": "🚫 Cancelled: <b>{cancelled}</b>",
    "fs_failed": "⚠️ Failed: <b>{failed}</b>",

    # --- 📋 All posts ---
    "posts_empty_title": "📋 <b>All posts</b>",
    "posts_empty_body": "<i>No posts yet.</i>",
    "posts_recent_header": "📋 <b>Last {count} posts:</b>",
    "posts_unknown_channel": "Unknown channel",

    # --- 📋 Connected channels list ---
    "channels_recent_header": (
        "📋 <b>Latest {count} connected channels "
        "(max {limit}):</b>"
    ),
    "channels_entry": "📢 <b>{title}</b> (<code>{channel}</code>)\n   👤 Owner: {owner}",
    "channels_omitted_footer": (
        "… {count} channels are hidden due to the Telegram 4096-character limit."
    ),
    "channel_generic_title": "Channel",
    "channels_empty_title": "📋 <b>Connected channels</b>",
    "channels_empty_body": "<i>No channels connected yet.</i>",
    "channels_none_legacy": "No connected channels yet.",

    # --- 🗄️ DB pool & cache ---
    "dbc_title": "🗄️ <b>DB Pool & Cache status:</b>",
    "dbc_pool": "   • Pool: <b>{pool}</b> ({message})",
    "dbc_minmax": "   • Min/Max: <b>{minv} / {maxv}</b>",
    "dbc_usage": "   • In use: <b>{used}</b> | Free: <b>{available}</b> | Closed: <b>{collapsed}</b>",
    "dbc_cache": "   • Cache: <b>{cache}</b> — <b>{entries}</b> entries",
    "dbc_footer": (
        "The cache expires automatically with an unchanged TTL. To clear it, "
        "use the button below."
    ),
    "dbc_cleared_footer": "✅ <b>Cache cleared.</b>",
    "cache_clear_toast": "✅ Cache cleared.",
    "cache_denied_owner": "❌ Only the bot owner (OWNER) can clear the cache.",
    "lbl_yes": "yes",
    "lbl_no": "no",
    "lbl_cache_on": "enabled",
    "lbl_cache_off": "disabled",
    "lbl_pool_ready": "✅ running",
    "lbl_pool_init": "⏳ not opened yet",

    # --- 📜 Audit | Roles ---
    "audit_log_title": "📜 <b>Audit log</b> (recent actions)",
    "audit_empty_inline": "<i>The audit log is empty for now.</i>",
    "audit_roles_title": "👥 <b>Roles</b> (RBAC — /setrole, /delrole)",
    "audit_roles_empty": "<i>No extra roles granted (legacy ADMIN_IDS only).</i>",
    "audit_denied": "❌ Only OWNER or SUPER_ADMIN can view the audit log.",
    "audit_cmd_empty": (
        "📝 <b>The audit log is empty for now.</b>\n"
        "<i>Admin actions (receipts, PRO, promos, settings) appear here.</i>"
    ),
    "audit_cmd_header": "📝 <b>Recent admin actions</b> ({count} total):",

    # --- ⚙️ AI parameters ---
    "ai_title": "⚙️ <b>AI parameters management:</b>",
    "ai_howto": (
        "To change a value, send lines in this format:\n"
        "<code>key=value</code>\n\n"
        "For example:\n"
        "<code>temperature=0.4</code>\n"
        "<code>max_tokens=2048</code>\n"
        "<code>context_messages=8</code>\n"
        "<code>max_tokens=off</code>  <i>(the parameter is not sent at all)</i>"
    ),
    "ai_reset_hint": "👉 To restore everything to defaults, type <code>reset</code>.",
    "ai_cancel_hint": "To cancel, tap the main menu button.",
    "ai_reset_done": "✅ <b>All AI parameters restored to defaults.</b>",
    "ai_updated": "✅ <b>AI parameters updated:</b>",
    "ai_err_header": "⚠️ <b>The following keys could not be changed:</b>",
    "ai_err_unknown_key": "<code>{key}</code> — unknown key",
    "ai_err_bad_value": "<code>{key}</code> = <code>{value}</code> — invalid value",
    "ai_err_nothing": "⚠️ No key entered. Send in <code>key=value</code> format.",
    "ai_denied_owner": "❌ Only the bot owner (OWNER) can change AI parameters.",
    "ai_hint_temperature": "0.0–2.0 (0.2 = precise)",
    "ai_hint_max_tokens": "128–8192 (1024) or off",
    "ai_hint_top_p": "0.0–1.0 (1.0) or off",
    "ai_hint_max_prompt_chars": "500–12000 characters (3000)",
    "ai_hint_context_chars": "500–20000 characters (4000)",
    "ai_hint_context_messages": "0–20 items (6)",
    "ai_hint_extra_context": "text (left empty — it is removed)",

    # --- 🏷 Post watermark ---
    "tag_title": "🏷 <b>Post watermark:</b>",
    "tag_current": "Current value: <code>{value}</code>",
    "tag_empty_value": "(empty — no watermark)",
    "tag_howto": (
        "Send the text to append at the end of posts.\n"
        "For example: <code>@PostAssistrobot</code>\n"
        "To remove it, type <code>clear</code>."
    ),
    "tag_denied_owner": "❌ Only the bot owner (OWNER) can change the watermark.",
    "tag_cleared": "✅ <b>Watermark removed</b> — posts will be clean.",
    "tag_saved": "✅ <b>Watermark saved:</b>\n\n<code>{value}</code>",

    # --- RBAC denials ---
    "rbac_denied": "Access denied.",
    "rbac_denied_msg": "🚫 Access denied.",
    "perm_health": "❌ You are not allowed to view system status.",
    "perm_promo": "❌ You are not allowed to manage promo codes.",
    "perm_promo_create": "❌ You are not allowed to create promo codes.",
    "perm_grant_pro": "❌ You are not allowed to grant PRO to users.",
    "perm_broadcast": "❌ You are not allowed to send broadcasts.",

    # --- ❌ Cancel ---
    "cancelled_toast": "🚫 Cancelled",
    "cancelled_html": "🚫 <b>Process cancelled.</b>",

    # --- 🎁 Promo code ---
    "promo_title": "🎁 <b>Promo code creation:</b>",
    "promo_howto": (
        "Format: <code>CODE DAYS [MAX_USES]</code>\n\n"
        "For example:\n"
        "• <code>MAXSUS30 30 50</code> — 30 days of PRO, 50 uses\n"
        "• <code>YANGI2026 30</code> — 30 days of PRO, unlimited\n\n"
        "Enter the promo code:"
    ),
    "promo_bad_format": "❌ Invalid format. Type: <code>CODE DAYS [MAX]</code>.",
    "promo_days_not_number": "❌ The number of days must be a number.",
    "promo_max_not_number": "❌ The max uses value must be a number.",
    "days_positive": "❌ The number of days must be greater than 0.",
    "promo_created": (
        "✅ <b>Promo code created!</b>\n\n"
        "🏷 Code: <code>{code}</code>\n"
        "📅 Duration: <b>{days} days</b> of PRO\n"
        "🔢 Max uses: <b>{max_str}</b>"
    ),
    "promo_exists": "❌ Failed to create the promo code. It may already exist.",
    "lbl_unlimited": "unlimited",
    "lbl_times_n": "{count} times",

    # --- ⭐️ Grant PRO ---
    "gp_title": "⭐️ <b>Grant PRO to a user:</b>",
    "gp_howto": (
        "Format: <code>USER_ID DAYS</code>\n\n"
        "For example: <code>123456789 30</code>\n\n"
        "Enter the USER ID and number of days:"
    ),
    "gp_bad_format": "❌ Invalid format. Type: <code>USER_ID DAYS</code>.",
    "gp_bad_numbers": "❌ Invalid numbers. Type: <code>USER_ID DAYS</code>.",
    "gp_granted": (
        "✅ <b>PRO plan granted!</b>\n\n"
        "👤 User: <code>{user}</code>\n"
        "📅 Duration: <b>{days} days</b>"
    ),
    "gp_user_notice": (
        "🎉 <b>Congratulations!</b>\n\n"
        "You have been granted <b>{days} days of PRO</b>!\n"
        "You can now use all PRO features."
    ),
    "gp_error": "❌ An error occurred. Please check the USER ID.",

    # --- ✉️ Broadcast ---
    "bc_title": "✉️ <b>Broadcast to all users:</b>",
    "bc_prompt": "Enter the broadcast message text:",
    "bc_started": (
        "⏳ The message is being sent to <b>{count}</b> users...\n"
        "<i>This runs in the background, in batches.</i>"
    ),
    "bc_busy": (
        "⏳ <b>The previous broadcast is still running.</b>\n"
        "Please wait for it to finish (a report will arrive)."
    ),
    "bc_done": (
        "✅ <b>Broadcast finished!</b>\n\n"
        "Delivered to: <b>{sent} / {total}</b> users.\n"
        "❌ Not sent: <b>{failed}</b>."
    ),

    # --- 📢 Sponsor channels ---
    "sp_manage_title": "📢 <b>Manage required subscription (sponsor channels):</b>",
    "sp_count": "Connected channels: <b>{count}</b>",
    "sp_empty_inline": "<i>No sponsor channels connected yet.</i>",
    "sp_manage_footer": "To remove a channel tap its button, or add a new one 👇",
    "sp_list_header": "📢 <b>Required-subscription (sponsor) channels ({count}):</b>",
    "sp_list_entry": "{idx}. 🔹 <b>{title}</b>{user} (<code>{channel}</code>)\n   🔗 Link: {url}",
    "sp_list_empty": "No sponsor channels added yet.",
    "sp_list_footer": "To remove, pick from the list below or add a new channel 👇",
    "sp_db_error": "⚠️ Could not read sponsor channels from the database. Try again later.",
    "sp_add_title": "➕ <b>Add a sponsor channel:</b>",
    "sp_add_howto": (
        "Send the channel's <code>@username</code>, its ID (for example: "
        "<code>-1001234567890</code>) or use this format:\n"
        "<code>CHANNEL_ID|CHANNEL_NAME|LINK</code>\n\n"
        "⚠️ <i>The bot must be an administrator of this channel.</i>"
    ),
    "sp_add_inline_title": "➕ <b>Add a required-subscription channel:</b>",
    "sp_add_inline_howto": (
        "Send the channel's <code>@username</code> or ID "
        "(for example: <code>-1001234567890</code>).\n\n"
        "⚠️ <b>Important requirements:</b>\n"
        "1. The bot must be an <b>administrator</b> of this channel.\n"
        "2. The bot must have permission to view channel members.\n\n"
        "To cancel, tap the «❌ Cancel» button."
    ),
    "sp_added": (
        "✅ <b>Sponsor channel added successfully!</b>\n\n"
        "📢 <b>{title}</b> (<code>{channel}</code>)\n"
        "🔗 {url}"
    ),
    "sp_added_short": "✅ Sponsor channel added: <b>{title}</b>",
    "sp_added_full": "✅ Sponsor channel added successfully: <b>{title}</b>",
    "sp_added_detailed": (
        "✅ <b>Sponsor channel added successfully!</b>\n\n"
        "📢 <b>{title}</b>\n"
        "🆔 <code>{channel}</code>\n"
        "{user}"
        "🔗 {url}"
    ),
    "sp_save_error": "❌ An error occurred while saving.",
    "sp_db_save_error": "❌ An error occurred while saving to the database.",
    "sp_not_admin_title": "❌ <b>The bot is not an admin in this channel!</b>",
    "sp_not_admin_channel": "Channel: <b>{title}</b> (<code>{chat}</code>)",
    "sp_not_admin_howto": (
        "Please first make the bot an <b>admin</b> of this channel "
        "and send it again:"
    ),
    "sp_not_admin_howto_short": (
        "Please first make the bot an <b>admin</b> of this channel "
        "and send it again:"
    ),
    "sp_generic_title": "Sponsor channel",
    "sp_not_found_title": "❌ <b>Channel not found or the bot is not an admin there!</b>",
    "sp_not_found_details": "Error details: <i>{error}</i>",
    "sp_retry_hint": (
        "Please make sure the bot has been added to the channel as an admin, "
        "then resend the @username or ID:"
    ),
    "sp_not_found_legacy": (
        "❌ Channel not found or the bot is not an admin there ({error}). "
        "Enter it again:"
    ),
    "sp_delete_failed": "⚠️ The sponsor channel was not removed. Please try again.",

    # --- 🎯 Ad management hub ---
    "ad_hub_title": "🎯 <b>Advertising management</b> — 3 main sections",
    "ad_hub_s1_title": "<b>1) 📢 Required subscription (sponsor channels)</b>",
    "ad_hub_s1_line": (
        "   Connected channels: <b>{count}</b> — text/button and disabling "
        "live inside the section."
    ),
    "ad_hub_s2_title": "<b>2) 🤖 Ad in every 3-5 replies</b>",
    "ad_hub_pool_line": "   Text: <b>{active}</b>/{total} active in the pool",
    "ad_hub_interval_reply": "   Interval: every <b>{interval}</b> replies",
    "ad_hub_s3_title": "<b>3) 📢 Ads in channel posts</b>",
    "ad_hub_interval_channel": (
        "   Interval: every <b>{interval}</b>-th post (per channel)"
    ),
    "ad_hub_state_line": "   Status: {state}",
    "ad_hub_pick": "Pick a section 👇 Text you send will be added to the channel-post ad pool.",
    "lbl_on": "✅ Enabled",
    "lbl_off": "❌ Disabled",
    "ad_toggle_on": "Reply ads enabled ✅",
    "ad_toggle_off": "Reply ads disabled ❌",
    "ch_ad_toggle_on": "Channel-post ads enabled ✅",
    "ch_ad_toggle_off": "Channel-post ads disabled ❌",

    # --- 📦 Ad rotation pool (ad_pool) ---
    "ad_scope_channel": "📢 Channel posts",
    "ad_scope_reply": "🤖 Bot replies",
    "ad_html_hint": (
        "💡 <b>HTML formatting supported:</b>\n"
        "<code>&lt;b&gt;bold&lt;/b&gt;</code>, <code>&lt;i&gt;italic&lt;/i&gt;</code>, "
        "<code>&lt;u&gt;underline&lt;/u&gt;</code>, "
        "<code>&lt;a href=\"https://t.me/kanal\"&gt;link&lt;/a&gt;</code>"
    ),
    "ad_pool_empty": "   <i>(No ads yet)</i>",
    "ad_card_title": "✏️ <b>Edit ad</b> — {title}",
    "ad_card_id": "🆔 ID: <code>{id}</code>",
    "ad_card_status": "📊 Status: {status}",
    "ad_card_button": "🔗 Inline button: {button}",
    "ad_card_text": "📝 <b>Text (HTML):</b>\n<code>{text}</code>",
    "ad_card_preview": "👁 <b>Preview:</b>",
    "ad_card_edit_hint": "Edit via the buttons below 👇",
    "ad_status_active": "🟢 Active",
    "ad_status_inactive": "🔴 Inactive",
    "ad_button_none": "<i>(no button)</i>",
    "ad_pool_title": "{title} — <b>auto-rotation</b>",
    "ad_pool_counts": "📦 Total: <b>{total}</b>  |  🟢 Active: <b>{active}</b>",
    "ad_pool_interval_channel": "⏱ Ad interval: <b>every {interval}-th post</b> (per channel)",
    "ad_pool_interval_reply": "⏱ Ad interval: <b>every {interval} replies</b>",
    "ad_pool_list_title": "<b>Ad pool:</b>",
    "ad_pool_footer": (
        "Tap an ad to edit it. "
        "The bot adds only 🟢 <b>active</b> ads, one by one."
    ),
    "ad_add_new_title": "✍️ <b>{title}</b> — enter the new ad text.",
    "ad_add_clear_hint": "<i>To delete all ads, type</i> <code>clear</code><i>.</i>",
    "ad_new_prompt": "You can send the new ad text here (it will be added to the pool).",
    "ad_cancel_hint": "To cancel, tap the «❌ Cancel» button.",
    "ad_et_title": "✏️ <b>#{id} — send the new text:</b>",
    "ad_et_current": "<b>Current text:</b>\n<code>{text}</code>",
    "ad_eb_title": "🔗 <b>#{id} — inline URL button:</b>",
    "ad_eb_current": "<b>Current button:</b> {text} → {url}",
    "ad_eb_howto": (
        "Send in this format:\n"
        "<code>Button text | https://t.me/kanal</code>\n\n"
        "To remove the button, type <code>clear</code>."
    ),
    "ad_tg_on_toast": "🟢 Ad activated",
    "ad_tg_off_toast": "🔴 Ad disabled",
    "ad_del_pick": "🗑 <b>{title}</b> — pick the ad to delete:",
    "ad_clear_toast": "🧹 {count} ads removed",
    "ad_cleared_msg": "🧹 Ads cleared ({count}).",
    "ad_iv_toast": "✅ Ads now appear every {value} {unit}",
    "ad_unit_post": "post",
    "ad_unit_reply": "replies",
    "ad_iv_title": "⏱ <b>Ad interval settings</b>",
    "ad_iv_current": "Current value: <b>every {value} {unit}</b>",
    "ad_iv_explain_channel": (
        "After how many posts should the bot add an ad? The counter is kept "
        "<b>separately for each channel</b> — posts in one channel do not "
        "affect another."
    ),
    "ad_iv_explain_reply": (
        "After how many replies should the bot add an ad? Default value: "
        "<b>4</b> (i.e. every 3-5 replies)."
    ),
    "ad_iv_hint": (
        "Pick from the buttons or send a number in the {min}–{max} range."
    ),
    "ad_iv_bad_number": "❌ Enter a whole number only (for example: 3, 4 or 5).",
    "ad_iv_out_of_range": "❌ The interval must be between {min} and {max}.",
    "ad_iv_updated": "✅ <b>Ad interval updated:</b> ads now appear every <b>{value} {unit}</b>.",
    "ad_iv_counter_channel": "<i>The counter is kept separately for each channel.</i>",
    "ad_iv_counter_user": "<i>Counted separately for each user.</i>",
    "ad_info_title": "ℹ️ <b>{title} — auto-rotation</b>",
    "ad_info_interval_channel": (
        "• Channel posts: one ad every <b>{interval} posts</b> "
        "(each channel has its own counter).\n"
    ),
    "ad_info_body": (
        "If you add several ads to the pool, the bot adds them one by one "
        "(round-robin).\n"
        "{interval_line}"
        "• Bot replies: one ad per 3 messages.\n"
        "• Ads with 🔴 status do not participate in rotation.\n"
        "• Every ad can have an inline URL button attached.\n\n"
        "If the pool is empty, the old single ad keeps working."
    ),
    "ad_added": (
        "✅ <b>The ad was added to the rotation pool!</b>\n"
        "To attach an inline URL button, pick the ad in the list."
    ),
    "ad_text_updated": "✅ <b>Ad text updated!</b>",
    "ad_btn_removed": "🚫 <b>Inline button removed.</b>",
    "ad_btn_saved": "✅ <b>Inline button saved:</b> {text} → {url}",
    "ad_btn_bad_format": (
        "❌ Invalid format. Send as "
        "<code>Button text | https://link</code>.\n"
        "To remove the button, type <code>clear</code>."
    ),

    # --- 👥 Roles (RBAC commands) ---
    "role_usage_set": (
        "📝 Usage: <code>/setrole &lt;user_id&gt; &lt;role&gt;</code>\n\n"
        "Roles: <code>owner</code>, <code>super_admin</code>, <code>admin</code>, "
        "<code>moderator</code>, <code>finance</code>\n"
        "To remove a role, type <code>user</code>."
    ),
    "role_usage_del": "📝 Usage: <code>/delrole &lt;user_id&gt;</code>",
    "role_bad_id": "❌ Invalid user ID. For example: /setrole 123456789 admin",
    "role_bad_id_short": "❌ Invalid user ID.",
    "role_unknown": "❌ Unknown role. Options: owner, super_admin, admin, moderator, finance, user.",
    "role_save_failed": "❌ Could not save the role (database unavailable).",
    "role_removed": "✅ <b>Role removed.</b>\n\n👤 User: <code>{user}</code>",
    "role_granted": (
        "✅ <b>Role granted.</b>\n\n"
        "👤 User: <code>{user}</code>\n"
        "🎖 Role: <b>{role}</b>\n"
        "🔑 Permissions: <code>{perms}</code>"
    ),
    "role_not_found": "❌ User <code>{user}</code> has no role in the database.",
    "role_denied_grant": "❌ Only the OWNER (bot owner) can grant/revoke roles.",
    "role_denied_revoke": "❌ Only the OWNER (bot owner) can revoke roles.",
}


def admin_t(key: str, lang: str = "uz", **kwargs) -> str:
    """👑 Admin panel matnini qaytaradi (uz / ru / en).

    Mantiq ``settings_stats_t`` bilan bir xil: kalit bu modulda bo'lmasa
    asosiy repo lug'atiga (``safe_t``) tushadi. Formatlash xatolarida
    handler hech qachon qulamaydi (formatlanmagan matn qaytariladi).
    """
    code = normalize_lang(lang)
    table = ADMIN_PANEL_I18N.get(code) or {}
    text = table.get(key)
    if text is None:
        text = (ADMIN_PANEL_I18N.get("uz") or {}).get(key)
    if text is None:
        return safe_t(key, code, **kwargs)
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:  # pragma: no cover — format himoyasi
        return text


def admin_panel_parity_report(langs=("uz", "ru", "en")) -> dict:
    """UZ ↔ RU ↔ EN kalit va format-argument pariteti hisoboti.

    ``settings_stats_parity_report`` bilan bir xil struktura:
    ``{"keys", "missing", "extra", "format_mismatch", "empty", "in_sync"}``.
    """
    from locales.translations import format_args

    base = ADMIN_PANEL_I18N.get("uz") or {}
    base_keys = set(base)
    missing, extra, fmt_mismatch, empty = {}, {}, {}, []
    for lang in langs:
        if lang == "uz":
            continue
        table = ADMIN_PANEL_I18N.get(lang) or {}
        lang_keys = set(table)
        missing[lang] = sorted(base_keys - lang_keys)
        extra[lang] = sorted(lang_keys - base_keys)
        for key in base_keys & lang_keys:
            if not str(table[key] or "").strip():
                empty.append(f"{lang}:{key}")
            if format_args(base[key]) != format_args(table[key]):
                fmt_mismatch.setdefault(
                    key, {"uz": format_args(base[key]), lang: format_args(table[key])}
                )
    # UZ bo'sh qiymatlar ham tekshiriladi.
    for key in base_keys:
        if not str(base[key] or "").strip():
            empty.append(f"uz:{key}")
    in_sync = not (missing["ru"] or missing["en"] or extra["ru"] or extra["en"]
                   or fmt_mismatch or empty)
    return {
        "keys": len(base_keys),
        "missing": missing,
        "extra": extra,
        "format_mismatch": fmt_mismatch,
        "empty": empty,
        "in_sync": in_sync,
    }
