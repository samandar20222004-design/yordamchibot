"""Sodda i18n lug'ati: o'zbek (uz) va rus (ru).

Foydalanish:
    get_text("start_hello", lang="ru", name="Ivan")
"""

DEFAULT_LANG = "uz"
SUPPORTED_LANGS = ("uz", "ru")
LANG_KEY = "lang"

TRANSLATIONS = {
    "uz": {
        "btn_new_post": "➕ Yangi post",
        "btn_ai_studio": "✨ AI Studio",
        "btn_premium": "⭐️ Premium",
        "btn_settings": "👤 Kabinet & Sozlamalar",
        "btn_help": "📖 Qo'llanma / Bot haqida",
        "btn_extras": "⚙️ Qo'shimcha funksiyalar",
        "start_hello": (
            "Salom, <b>{name}</b>! 👋\n\n"
            "🤖 @PostAssistrobot — kanallarga postlarni vaqtida joylash, "
            "AI yordamida matnlar va kontent-reja tuzish bo'yicha aqlli yordamchingiz.\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "my_channels_title": "📢 <b>Mening kanallarim:</b>",
        "my_channels_empty": (
            "📢 <b>Mening kanallarim:</b>\n\n"
            "Hozircha hech qanday kanal ulanmagan.\n\n"
            "{hint}\n\n"
            "⚠️ <i>Botni kanal/guruhingizga administrator qilib (xabar "
            "yuborish ruxsati bilan) qo'shing, so'ng pastdagi "
            "<b>➕ Kanal qo'shish</b> tugmasini bosing.</i>"
        ),
        "my_channels_list": "📢 <b>Mening kanallarim ({count} ta):</b>\n\n",
        "my_channels_footer": "\nYangi kanal ulash yoki mavjudini o'chirish uchun 👇",
        "new_post_no_channels": (
            "⚠️ <b>Ulangan kanal yoki guruh topilmadi!</b>\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal yoki guruhingizni ulang."
        ),
        "new_post_choose_channel": (
            "📢 <b>Qaysi kanal yoki guruhga post rejalashtiramiz?</b>\n"
            "Ro'yxatdan tanlang 👇"
        ),
        "lang_prompt": "🌐 <b>Tilni tanlang / Выберите язык:</b>",
        "lang_changed": "✅ Til o'zbekchaga o'zgartirildi.",
        "lang_button": "🌐 Til / Язык",
        "referral_reward_notice": (
            "🎉 <b>Yangi do'st taklif qilindi!</b>\n\n"
            "Hisobingizga <b>+{reward} ta AI ball</b> qo'shildi. "
            "Birinchi 3 do'st uchun +3 tadan, keyingilar uchun +1 tadan beriladi. 🚀"
        ),
        "referral_menu": (
            "🚀 <b>Do'stlarni taklif qiling va AI ball oling:</b>\n\n"
            "🎁 <i>1-, 2- va 3-do'st uchun +3 tadan; 4-do'stdan boshlab har biri uchun +1 AI ball.</i>\n\n"
            "💎 Mavjud AI ballaringiz: {credits}\n👥 Takliflar: <b>{count} ta</b>\n\n"
            "🔗 <b>Taklif havolangiz:</b>\n<code>{link}</code>"
        ),
        "daily_bonus_guide": (
            "🎁 Kunlik bepul AI ballaringizni olish uchun "
            "'Kabinet & Sozlamalar' → '🎁 Kunlik bonus' bo'limiga kiring."
        ),
        "no_credits": (
            "⚠️ <b>Sizda bepul AI so'rovlari soni tugadi!</b>\n\n"
            "Ko'proq so'rov olish uchun do'stlaringizni taklif qiling.\n"
            "🎁 <i>1-, 2- va 3-do'st uchun +3 tadan, 4-do'stdan boshlab har biri uchun +1 AI ball beriladi.</i>\n"
            "{guide}\n\n"
            "🔗 Sizning taklif havolangiz:\n<code>{link}</code>"
        ),
        "balance_card": (
            "💎 <b>Ballar & Reklama rejimi:</b>\n\n"
            "🤖 AI so'rovlar: {credits}\n"
            "📢 Reklama rejimi: {ad_mode}\n\n"
            "Ballarni ko'paytirish uchun:\n"
            "• 🎁 Kunlik bonus oling\n"
            "• 👥 Do'stlarni taklif qiling (1–3-do'st: +3, keyingilar: +1)\n"
            "• ⭐️ PRO tarifga o'ting (cheksiz AI, 100% reklamasiz postlar)"
        ),
        "ad_mode_admin": "👑 <b>Admin</b> — reklamasiz",
        "ad_mode_pro": "✨ <b>PRO</b> — postlar va bot javoblari avtomatik 100% reklamasiz",
        "ad_mode_free": "🆓 <b>Bepul</b> — belgilangan oraliqda reklama chiqadi (PRO'da avtomatik o'chadi)",
        "btn_card_payment": "💳 Karta orqali to'lov (Uzcard / Humo)",
        "btn_back": "⬅️ Orqaga",
        "card_payment_title": "💳 <b>Karta orqali to'lov (Uzcard / Humo)</b>",
        "card_payment_prices": (
            "💰 <b>To'lov summasi:</b>\n"
            "• 1 oy — <b>{p1m} so'm</b>\n"
            "• 3 oy — <b>{p3m} so'm</b>\n"
            "• 1 yil — <b>{p1y} so'm</b>"
        ),
        "card_payment_card": "💳 <b>Karta raqami:</b> <code>{card}</code>\n👤 <b>Karta egasi:</b> {holder}",
        "card_payment_no_card": "ℹ️ Karta rekvizitlarini olish uchun adminga murojaat qiling.",
        "card_payment_steps": (
            "📝 <b>Yo'riqnoma:</b>\n"
            "1️⃣ Tanlagan tarif summasini yuqoridagi kartaga o'tkazing.\n"
            "2️⃣ To'lov chekini (skrinshot) adminga yuboring: {admin}\n"
            "3️⃣ Xabarda o'z ID raqamingizni ko'rsating: <code>{user_id}</code>\n"
            "4️⃣ Admin tekshirgach PRO tarif 24 soat ichida faollashtiriladi.\n\n"
            "⚡️ Tezroq bo'lishi uchun ⭐️ Stars orqali to'lasangiz PRO darhol yoqiladi."
        ),
        "card_payment_admin_missing": "admin (Bot haqida bo'limidagi aloqa orqali)",
        # --- 1-QISM: Asosiy klaviatura & Kabinet (i18n) ---
        # Umumiy tugmalar (kabinet va jarayon klaviaturalarida ishlatiladi)
        "btn_main_menu": "🔙 Asosiy menyu",
        "btn_cancel": "❌ Bekor qilish",

        # Kabinet reply-klaviaturasi tugmalari
        "cab_btn_channels": "📢 Kanal/Guruhlar",
        "cab_btn_converter": "🔤 Krill-Lotin konvertor",
        "cab_btn_daily_bonus": "🎁 Kunlik bonus",
        "cab_btn_invite": "🚀 Do'stlarni taklif qilish",
        "cab_btn_transfer": "🔄 Ballarni ulashish",

        # Kabinet inline-klaviaturasi tugmalari
        "cab_my_channels": "📢 Mening kanallarim",
        "cab_analytics": "📊 Kanallar analitikasi",
        "cab_pending": "📅 Kutilayotgan postlar",
        "cab_queue": "⏳ Postlar navbati (Queue)",
        "cab_balance": "💎 Ballar & Reklama rejimi",
        "cab_referral": "👥 Do'stlarni taklif",
        "cab_close": "❌ Yopish",
        "cab_add_channel": "➕ Kanal qo'shish",
        "cab_del_channel": "🗑 Kanalni o'chirish",
        "cab_del_channel": "🗑 Kanalni o'chirish",
        "cab_remove_channel": "❌ O'chirish",
        "cab_tone": "Uslub",
        "cab_add_channel_alt": "➕ Yangi kanal/guruh ulash",
        "cab_channels_delete_empty": (
            "📢 <b>Mening kanallarim:</b>\n\n"
            "Hozircha o'chirish uchun kanal yo'q.\n\n"
            "{hint}"
        ),
        "cab_channels_delete_title": (
            "🗑 <b>Kanalni o'chirish</b> ({count} ta)\n\n"
            "O'chirmoqchi bo'lgan kanalingiz yonidagi <b>❌ O'chirish</b> "
            "tugmasini bosing 👇"
        ),

        "no_channels_hint": (
            "Avval <b>«Mening kanallarim»</b> bo'limidan kanal yoki "
            "guruhingizni ulang."
        ),

        # Kabinet ekrani matnlari
        "credits_value": "<b>{n} ta</b>",
        "cabinet_credits_admin": "♾ Cheksiz (Super Admin)",
        "cabinet_streak": "🔥 <b>{streak}/7 kun</b>",
        "cabinet_title": (
            "👤 <b>Shaxsiy Kabinet:</b>\n\n"
            "🆔 Sizning ID: <code>{user_id}</code>\n"
            "🔑 Maxsus kodingiz: <code>{user_code}</code>\n"
            "💎 Mavjud AI so'rovlar soni: {credits}\n"
            "🔥 Ketma-ket kunlik seriya: {streak}\n"
            "📢 Ulangan kanallar: <b>{channels} ta</b>\n"
            "👥 Taklif qilgan do'stlaringiz: <b>{referrals} ta</b>\n\n"
            "Quyidagi bo'limlardan birini tanlang 👇{ad_line}"
        ),

        # Kunlik bonus
        "daily_bonus_admin": (
            "👑 <b>Siz Super Adminsiz</b> — hisobingizda cheksiz so'rov mavjud!"
        ),
        "daily_bonus_claimed": (
            "🎉 <b>Kunlik bonus qabul qilindi!</b>\n\n"
            "{reset_notice}"
            "🔥 Sizning ketma-ketlik seriyangiz: <b>{streak}/7 kun</b>\n"
            "{bar}\n\n"
            "🎁 Bugungi sovg'a: <b>+{bonus} ta AI so'rovi</b>\n"
            "💎 Jami balansingiz: <b>{credits} ta</b>\n\n"
            "📌 <i>Eslatma: Ertaga ham botga kiring va 7-kunda "
            "<b>+4 ta super-bonus</b> oling!</i>"
        ),
        "daily_bonus_reset_notice": (
            "\n⚠️ <i>Orada kun o'tkazib yuborilgani sababli seriya 1-kundan "
            "qayta boshlandi.</i>\n"
        ),
        "daily_bonus_already": (
            "ℹ️ {msg}\n\n💎 Sizdagi jami ballar: <b>{credits} ta</b>"
        ),

        # Ballarni ulashish (transfer)
        "transfer_intro": (
            "🔄 <b>Ballarni (AI so'rovlarni) ulashish:</b>\n\n"
            "Do'stingizning <b>ID raqamini</b>, "
            "<b>Telegram usernamesini (@...)</b> yoki botdagi "
            "<b>maxsus kodini</b> yuboring:\n"
            "<i>(Eslatma: Faqat botdan ro'yxatdan o'tgan faol "
            "foydalanuvchilarga ball o'tkazish mumkin)</i>"
        ),
        "transfer_insufficient": (
            "⚠️ <b>Hisobingizda yetarli ball yo'q!</b>\n\n"
            "Ball o'tkazish uchun kamida <b>3 ta ball</b> kerak. "
            "Sizda esa: <b>{credits} ta</b>.\n"
            "{guide}\n"
            "Yoki taklif havolasi orqali ball to'plashingiz mumkin!"
        ),
        "transfer_user_not_found": (
            "❌ <b>Foydalanuvchi topilmadi!</b>\n\n"
            "Ushbu foydalanuvchi hali botdan ro'yxatdan o'tmagan yoki "
            "ma'lumot xato kiritildi.\n"
            "Do'stingiz avval botga kirib <b>/start</b> bosishi kerak.\n\n"
            "Qaytadan to'g'ri ID raqam yoki kodni kiriting:"
        ),
        "transfer_self": (
            "⚠️ O'zingizga ball o'tkaza olmaysiz! "
            "Boshqa do'stingiz ma'lumotini kiriting:"
        ),
        "transfer_target_ok": (
            "✅ <b>Qabul qiluvchi:</b> <b>{name}</b> "
            "(ID: <code>{user_id}</code>)\n\n"
            "Nechta ball yubormoqchisiz? <i>(Kamida <b>3 ta</b>, "
            "ko'pi bilan <b>20 ta</b>)</i>:"
        ),
        "transfer_amount_nan": (
            "Iltimos, miqdorni faqat raqamlarda yozing (masalan: 5):"
        ),
        "transfer_amount_range": (
            "⚠️ O'tkazish miqdori kamida <b>3 ta</b> va ko'pi bilan "
            "<b>20 ta</b> bo'lishi kerak. Qaytadan kiriting:"
        ),
        "transfer_success": (
            "🎉 <b>Muvaffaqiyatli!</b>\n\n"
            "<b>{name}</b> hisobiga <b>+{amount} ta AI so'rovi</b> "
            "o'tkazildi! 🚀"
        ),
        "transfer_gift_notice": (
            "🎁 <b>Sizga sovg'a!</b>\n\n"
            "<b>{name}</b> sizga <b>+{amount} ta AI so'rovi</b> yubordi! 🎉"
        ),
        "transfer_error": "❌ <b>Xatolik:</b> {msg}",
        "transfer_default_name": "Do'stingiz",

        # --- 2-QISM: ✨ AI Studio i18n ---
        "ai_studio_menu": (
            "🤖 <b>PostAssist AI Studio</b>\n\n"
            "💎 Mavjud AI so'rovlari: {credits}\n\n"
            "Kanal kontentini yaratish uchun kerakli vositani tanlang 👇"
        ),
        "ai_studio_post": "✍️ AI Post yaratish",
        "ai_studio_photo": "🖼 Rasmdan post yaratish",
        "ai_studio_extract": "📢 Ochiq kanaldan olish",
        "ai_studio_audit": "🔍 AI Post auditi",
        "ai_studio_content_plan": "🧠 Kontent-reja",
        "ai_studio_post_intro": (
            "✍️ <b>AI Post yaratish</b>\n\n"
            "Post mavzusini yozing yoki rasm/fayl yuboring.\n"
            "<i>Masalan: «Sog'lom turmush tarzi haqida motivatsion post»</i>"
        ),
        "ai_studio_photo_intro": (
            "🖼 <b>Rasmdan post yaratish</b>\n\n"
            "Rasm yuboring — AI uni chuqur tahlil qilib, Telegram kanalingiz uchun "
            "professional SMM post yozadi:\n"
            "• ✨ Chiroyli formatlangan sarlavha (<b>...</b>)\n"
            "• 📝 Qiziqarli / sotuvchi matn\n"
            "• 😎 Emojilar va bandlar\n"
            "• 👉 Harakatga chaqiruv (CTA) va xeshteglar\n\n"
            "<i>Xohlasangiz rasm bilan birga izoh ham yuboring — masalan: "
            "«rasmdagi mahsulotni sotishga urg'u ber».</i>"
        ),
        "ai_studio_audit_intro": (
            "🔍 <b>AI Post auditi</b>\n\n"
            "Tayyor post matningizni yuboring — AI uni tahlil qiladi:\n"
            "• ✍️ Imlo va grammatika\n"
            "• 🎯 Jozibadorlik va CTA\n"
            "• 🧩 Struktura tavsiyalari\n"
            "• ⭐️ Umumiy baho (1-10)"
        ),
        "ai_studio_extract_intro": (
            "📢 <b>Ochiq kanaldan olish</b>\n\n"
            "Kanal nikini kiriting (masalan: <code>@kunuzofficial</code> yoki <code>daryo</code>):\n\n"
            "<i>Faqat ochiq kanallar uchun ishlaydi.</i>"
        ),
        "ai_studio_content_plan_intro": (
            "🧠 <b>Kontent-reja generatori</b>\n\nQaysi kanal uchun kontent-reja tuzamiz?"
        ),
        "ai_studio_no_channel": (
            "⚠️ <b>Avval kanal ulang.</b>\n\n"
            "Kontent-reja tuzish uchun kamida bitta kanal bo'lishi kerak.\n"
            "📢 Kanallar bo'limidan kanal ulang."
        ),
        "ai_tone_formal": "👔 Rasmiy",
        "ai_tone_friendly": "😊 Do'stona",
        "ai_tone_concise": "⚡️ Qisqa",
        "ai_tone_engaging": "🎉 Jozibali",
        "ai_tone_schedule": "➡️ Rejalashtirishga o'tish",
        "ai_photo_schedule": "📅 Kanalga rejalashtirish",
        "ai_photo_rewrite": "🔄 Qayta yozish",
        "ai_photo_edit": "✏️ Tahrirlash",
        "ai_photo_result_title": "🖼 <b>Rasmdan tayyorlangan post:</b>\n\n",
        "ai_photo_result_foot": (
            "\n\n🖼 <i>Yuborilgan rasm ushbu postga biriktiriladi.</i>\n\n"
            "Keyingi qadamni tanlang 👇"
        ),
        "ai_btn_back": "⬅️ Orqaga",
        "ai_btn_close": "❌ Bekor qilish",
        "ai_btn_main_menu": "⬅️ Asosiy menyu",
        "ai_confirm_schedule": "✅ Kanalga rejalashtirish",
        "ai_confirm_edit": "📝 Matnni tahrirlash",
        "ai_preview_title": "✨ <b>AI Post tayyor!</b>\n\n",
        "ai_preview_foot": (
            "\n\n🎨 <b>Uslub:</b> {tone}{media}\n\n"
            "Uslubni almashtiring yoki rejalashtirishga o'ting 👇"
        ),
        "ai_preview_media_note": "\n🖼 <i>Media postga biriktiriladi.</i>",
        "ai_thinking": "🤖 <i>AI javob tayyorlamoqda...</i>",
        "ai_saving": "💾 Saqlanmoqda...",
        "ai_wait_post": "🤖 <i>AI post yozmoqda...</i>",
        "ai_wait_audit": "🔍 <i>AI audit qilmoqda...</i>",
        "ai_wait_photo": "🖼 <i>AI rasmni tahlil qilmoqda...</i>",
        "ai_wait_edit": "✏️ <i>AI postni tahrirlamoqda...</i>",
        "ai_unavailable": (
            "⚠️ AI xizmatida vaqtinchalik uzilish yuz berdi. "
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        ),
        "ai_rate_limit": (
            "⏳ <i>AI so'rovlarini juda tez-tez yuboryapsiz. Iltimos, 1 daqiqa kuting...</i>"
        ),
        "ai_daily_limit": (
            "⚠️ <i>Kunlik AI so'rovlar limiti tugadi (30 ta/kun). Ertaga qayta urinib ko'ring.</i>"
        ),
        "ai_limit_msg": (
            "🚫 <b>Kunlik AI limiti tugadi!</b>\n\n"
            "Bugun <b>{used}/{max}</b> ta AI so'rovi ishlatildi.\n"
            "Free tarifida kuniga maksimal <b>{max}</b> ta AI so'rovi.\n\n"
            "⭐️ Cheksiz AI uchun PRO tarifiga o'ting."
        ),
        "ai_credits_unlimited": "♾ Cheksiz",
        "ai_credits_unlimited_pro": "♾ Cheksiz (PRO)",
        "ai_media_received": (
            "🖼 <b>Media qabul qilindi!</b>\n\nEndi post mavzusini yoki matnini yozing."
        ),
        "ai_prompt_hint": "✍️ Post mavzusini yozing yoki rasm/fayl yuboring:",
        "ai_faq_footer": "\n\n<i>Yana mavzu yozing yoki orqaga qayting 👇</i>",
        "ai_no_post_text": "⚠️ Post matnini aniqlab bo'lmadi. Mavzuni boshqacharoq yozib ko'ring.",
        "ai_session_expired": "⚠️ Sessiya eskirgan. Mavzuni qaytadan yuboring.",
        "ai_audit_prompt_hint": "🔍 Auditlash uchun post matnini yuboring:",
        "ai_audit_result_title": "🔍 <b>AI Audit natijasi:</b>\n\n",
        "ai_audit_no_result": "⚠️ AI audit natijasini qaytara olmadi. Qaytadan urinib ko'ring.",
        "ai_photo_only": (
            "🖼 Iltimos, rasm (JPG/PNG/WEBP) yuboring:\n"
            "• <i>Rasm bilan birga izoh yuborish mumkin</i>\n"
            "• <i>Video tahlil qilinmaydi — faqat rasm</i>"
        ),
        "ai_video_rejected": (
            "🎬 <b>Video tahlil qilinmaydi.</b>\n\n"
            "Server resursini tejash uchun faqat <b>rasm</b> tahlil qilinadi.\n"
            "Iltimos, tahlil qilinishi kerak bo'lgan <b>rasmni</b> (JPG/PNG/WEBP) yuboring."
        ),
        "ai_photo_no_text": "⚠️ AI post matnini tayyorlay olmadi. Rasmni qaytadan yuboring.",
        "ai_photo_retry_hint": "🖼 Yana rasm yuboring yoki menyuga qayting 👇",
        "ai_photo_edit_intro": (
            "✏️ <b>Postni tahrirlash</b>\n\n"
            "Qanday o'zgarish kerak? Matn yuboring:\n"
            "<i>Masalan: «sarlavhani boshqacha yoz», «qisqartir», «narxni qo'sh»</i>"
        ),
        "ai_photo_edit_hint": "✏️ Tahrirlash uchun matn yuboring:",
        "ai_photo_edit_no_result": "⚠️ AI tahrirlangan matnni qaytara olmadi. Qaytadan urinib ko'ring.",
        "ai_photo_rewrite_wait": "🔄 <i>AI rasmni qayta tahlil qilmoqda...</i>",
        "ai_photo_rewrite_keep": "⚠️ AI qayta yozishda post tayyorlay olmadi. Asl post saqlanib qoldi.",
        "ai_tone_applying": "🎨 <i>{tone} uslubi qo'llanmoqda...</i>",
        "ai_schedule_need_post": "⚠️ Avval post yarating. Mavzuni yozing:",
        "ai_close_session": "❌ AI Studio sessiyasi yakunlandi.",
        "ai_close_main_menu": "🏠 Asosiy menyu.",
        "ai_not_found": "Kechirasiz, javob topa olmadim.",
        "ai_tone_unknown": "⚠️ Sessiya eskirgan. Mavzuni qaytadan yuboring.",
        "ai_rate_limit_alert": "⏳ Juda tez-tez so'rov. Iltimos, 1 daqiqa kuting.",
        "ai_schedule_header": "✨ <b>Post qabul qilindi!</b>\n\n",
        "ai_schedule_foot": (
            "🕒 <b>Ushbu post qachon kanalga chiqsin?</b>\n"
            "Quyidagi tugmalardan tanlang yoki erkin yozing:\n"
            "• <i>“ertaga ertalab 9 ga”</i>\n"
            "• <i>“bugun 15:45 ga hamma kanalga”</i>\n"
            "• <i>“1 soatdan keyin”</i>"
        ),
        "ai_media_caption_note": "\n\n⬆️ Yuqoridagi media ushbu postga biriktiriladi.",
        "ai_confirm_title": (
            "✨ <b>Tayyorlangan post:</b>\n\n"
            "{post}\n\n"
            "🕒 <b>Chiqish vaqti:</b> <code>{time}</code>{target}\n\n"
            "Ushbu postni rejalashtiramizmi?"
        ),
        "ai_media_received_scheduled": (
            "🖼 <b>Media qabul qilindi va postga biriktirildi!</b>\n\n"
            "Endi chiqish vaqtini yozing (masalan: <i>“bugun 18:00 ga”</i>) yoki tugmani tanlang:"
        ),
        "ai_time_prompt_hint": "Iltimos, chiqish vaqtini yozing (masalan: <i>“ertaga 10:00 ga”</i>):",
        "ai_only_one_time": (
            "ℹ️ <i>AI yordamchisi orqali faqat bir martalik post rejalashtiriladi.</i>\n"
            "Har kunlik/haftalik takrorlanuvchi postlar uchun <b>➕ Yangi post rejalashtirish</b> bo'limidan foydalaning.\n\n"
            "Vaqtni yozing (masalan: <i>“ertaga 10:00 ga”</i>) yoki tezkor tugmani tanlang:"
        ),
        "ai_time_fast": (
            "⏳ <i>Juda tez-tez so'rov yuboryapsiz. 1 daqiqa kuting yoki vaqtni "
            "aniq formatda yozing: <code>2026-08-30 18:00</code></i>"
        ),
        "ai_time_ask": (
            "🤖 {reply}\n\n"
            "Post vaqtini esa quyidagicha yozing: <i>“ertaga 10:00 ga”</i> yoki tugmani tanlang:"
        ),
        "ai_time_unparsed": (
            "⚠️ <b>Vaqtni aniqlab bo'lmadi yoki u o'tib ketgan.</b>\n\n"
            "Quyidagicha yozing:\n"
            "• <i>“bugun 18:00 ga”</i>\n"
            "• <i>“ertaga ertalab 9 ga”</i>\n"
            "• <i>“30 daqiqadan keyin”</i>\n"
            "Yoki aniq format: <code>2026-08-30 18:00</code>"
        ),
        "ai_post_ready": "✨ <b>Post tayyor!</b>\n\n",
        "ai_post_ready_foot": (
            "\n\n🕒 <b>Chiqish vaqti:</b> <code>{time}</code>{target}\n\n"
            "Rejalashtiramizmi?"
        ),
        "ai_post_cancelled": "🚫 Post bekor qilindi. Menyudan kerakli bo'limni tanlang.",
        "ai_post_retry": (
            "📝 <b>Postni qanday o'zgartiramiz?</b>\n\n"
            "Masalan: <i>“oxiriga telefon raqam qo'sh”</i>, <i>“matnni qisqartir”</i>, "
            "<i>“sarlavhani o'zgartir”</i> — yoki yangi post yuboring."
        ),
        "ai_no_channel_schedule": (
            "⚠️ <b>Sizda ulangan kanallar topilmadi.</b>\n\n"
            "Avval '📢 Kanal/Guruhlar' bo'limidan kanal ulang, keyin postni qayta rejalashtiring."
        ),
        "ai_scheduled_ok": (
            "✅ <b>AI Posti muvaffaqiyatli rejalashtirildi!</b>\n\n"
            "📢 Joylash: <b>{channel}</b>\n"
            "⏰ Chiqish vaqti: <b>{time}</b>\n\n"
            "Yana post yaratish uchun <b>🤖 AI Yordamchi</b> ni bosing yoki menyuga qayting."
        ),
        "ai_schedule_error": "❌ Saqlashda xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.",
        "ai_photo_media_received": (
            "🖼 <b>Media qabul qilindi!</b>\n\nEndi post mavzusini yoki matnini yozing."
        ),

    },
    "ru": {
        "btn_new_post": "➕ Новый пост",
        "btn_ai_studio": "✨ AI Studio",
        "btn_premium": "⭐️ Premium",
        "btn_settings": "👤 Кабинет & Настройки",
        "btn_help": "📖 Руководство / О боте",
        "btn_extras": "⚙️ Дополнительные функции",
        "start_hello": (
            "Привет, <b>{name}</b>! 👋\n\n"
            "🤖 @PostAssistrobot — умный помощник для своевременной публикации "
            "постов в каналы, текстов и контент-плана с помощью ИИ.\n\n"
            "Выберите нужный раздел 👇"
        ),
        "my_channels_title": "📢 <b>Мои каналы:</b>",
        "my_channels_empty": (
            "📢 <b>Мои каналы:</b>\n\n"
            "Пока ни один канал не подключён.\n\n"
            "{hint}\n\n"
            "⚠️ <i>Сначала добавьте бота администратором канала/группы "
            "(с правом отправки сообщений), затем нажмите "
            "<b>➕ Добавить канал</b>.</i>"
        ),
        "my_channels_list": "📢 <b>Мои каналы ({count} шт.):</b>\n\n",
        "my_channels_footer": "\nЧтобы подключить новый канал или удалить существующий 👇",
        "new_post_no_channels": (
            "⚠️ <b>Подключённый канал или группа не найдены!</b>\n\n"
            "Сначала подключите канал или группу в разделе «📢 Каналы/Группы»."
        ),
        "new_post_choose_channel": (
            "📢 <b>В какой канал или группу запланируем пост?</b>\n"
            "Выберите из списка 👇"
        ),
        "lang_prompt": "🌐 <b>Tilni tanlang / Выберите язык:</b>",
        "lang_changed": "✅ Язык изменён на русский.",
        "lang_button": "🌐 Til / Язык",
        "referral_reward_notice": (
            "🎉 <b>Приглашён новый друг!</b>\n\n"
            "На ваш счёт начислено <b>+{reward} ИИ-балла</b>. "
            "За первых 3 друзей начисляется по +3, за каждого следующего — +1. 🚀"
        ),
        "referral_menu": (
            "🚀 <b>Приглашайте друзей и получайте ИИ-баллы:</b>\n\n"
            "🎁 <i>За 1-го, 2-го и 3-го друга — по +3; начиная с 4-го — по +1 ИИ-баллу.</i>\n\n"
            "💎 Ваши ИИ-баллы: {credits}\n👥 Приглашено: <b>{count}</b>\n\n"
            "🔗 <b>Ваша реферальная ссылка:</b>\n<code>{link}</code>"
        ),
        "daily_bonus_guide": (
            "🎁 Чтобы получить ежедневные бесплатные ИИ-баллы, откройте "
            "«Кабинет & Настройки» → «🎁 Ежедневный бонус»."
        ),
        "no_credits": (
            "⚠️ <b>У вас закончились бесплатные ИИ-запросы!</b>\n\n"
            "Чтобы получить больше, приглашайте друзей.\n"
            "🎁 <i>За 1-го, 2-го и 3-го друга — по +3, начиная с 4-го — по +1 ИИ-баллу.</i>\n"
            "{guide}\n\n"
            "🔗 Ваша реферальная ссылка:\n<code>{link}</code>"
        ),
        "balance_card": (
            "💎 <b>Баллы & Режим рекламы:</b>\n\n"
            "🤖 ИИ-запросы: {credits}\n"
            "📢 Режим рекламы: {ad_mode}\n\n"
            "Чтобы получить больше баллов:\n"
            "• 🎁 Забирайте ежедневный бонус\n"
            "• 👥 Приглашайте друзей (1–3-й друг: +3, далее: +1)\n"
            "• ⭐️ Перейдите на PRO (безлимитный ИИ, посты 100% без рекламы)"
        ),
        "ad_mode_admin": "👑 <b>Админ</b> — без рекламы",
        "ad_mode_pro": "✨ <b>PRO</b> — посты и ответы бота автоматически 100% без рекламы",
        "ad_mode_free": "🆓 <b>Бесплатный</b> — реклама показывается с заданным интервалом (в PRO отключается автоматически)",
        "btn_card_payment": "💳 Оплата картой (Uzcard / Humo)",
        "btn_back": "⬅️ Назад",
        "card_payment_title": "💳 <b>Оплата картой (Uzcard / Humo)</b>",
        "card_payment_prices": (
            "💰 <b>Сумма оплаты:</b>\n"
            "• 1 месяц — <b>{p1m} сум</b>\n"
            "• 3 месяца — <b>{p3m} сум</b>\n"
            "• 1 год — <b>{p1y} сум</b>"
        ),
        "card_payment_card": "💳 <b>Номер карты:</b> <code>{card}</code>\n👤 <b>Владелец:</b> {holder}",
        "card_payment_no_card": "ℹ️ Чтобы получить реквизиты карты, обратитесь к администратору.",
        "card_payment_steps": (
            "📝 <b>Инструкция:</b>\n"
            "1️⃣ Переведите сумму выбранного тарифа на карту выше.\n"
            "2️⃣ Отправьте чек (скриншот) администратору: {admin}\n"
            "3️⃣ Укажите в сообщении свой ID: <code>{user_id}</code>\n"
            "4️⃣ После проверки PRO активируется в течение 24 часов.\n\n"
            "⚡️ Для мгновенной активации оплатите через ⭐️ Stars."
        ),
        "card_payment_admin_missing": "администратор (контакты в разделе «О боте»)",

        # --- 1-QISM: Asosiy klaviatura & Kabinet (i18n) ---
        # Umumiy tugmalar (kabinet va jarayon klaviaturalarida ishlatiladi)
        "btn_main_menu": "🔙 Главное меню",
        "btn_cancel": "❌ Отмена",

        # Kabinet reply-klaviaturasi tugmalari
        "cab_btn_channels": "📢 Каналы/Группы",
        "cab_btn_converter": "🔤 Кирилл-Латиница",
        "cab_btn_daily_bonus": "🎁 Ежедневный бонус",
        "cab_btn_invite": "🚀 Пригласить друзей",
        "cab_btn_transfer": "🔄 Передать баллы",

        # Kabinet inline-klaviaturasi tugmalari
        "cab_my_channels": "📢 Мои каналы",
        "cab_analytics": "📊 Аналитика каналов",
        "cab_pending": "📅 Ожидающие посты",
        "cab_queue": "⏳ Очередь постов (Queue)",
        "cab_balance": "💎 Баллы & Режим рекламы",
        "cab_referral": "👥 Пригласить друзей",
        "cab_close": "❌ Закрыть",
        "cab_add_channel": "➕ Добавить канал",
        "cab_del_channel": "🗑 Удалить канал",
        "cab_del_channel": "🗑 Удалить канал",
        "cab_remove_channel": "❌ Удалить",
        "cab_tone": "Стиль",
        "cab_add_channel_alt": "➕ Подключить канал/группу",
        "cab_channels_delete_empty": (
            "📢 <b>Мои каналы:</b>\n\n"
            "Пока нет каналов для удаления.\n\n"
            "{hint}"
        ),
        "cab_channels_delete_title": (
            "🗑 <b>Удаление канала</b> ({count} шт.)\n\n"
            "Нажмите <b>❌ Удалить</b> рядом с нужным каналом 👇"
        ),

        "no_channels_hint": (
            "Сначала подключите канал или группу в разделе "
            "<b>«Мои каналы»</b>."
        ),

        # Kabinet ekrani matnlari
        "credits_value": "<b>{n} шт.</b>",
        "cabinet_credits_admin": "♾ Безлимитно (Супер-админ)",
        "cabinet_streak": "🔥 <b>{streak}/7 дней</b>",
        "cabinet_title": (
            "👤 <b>Личный кабинет:</b>\n\n"
            "🆔 Ваш ID: <code>{user_id}</code>\n"
            "🔑 Ваш код: <code>{user_code}</code>\n"
            "💎 Доступно ИИ-запросов: {credits}\n"
            "🔥 Серия дней подряд: {streak}\n"
            "📢 Подключено каналов: <b>{channels} шт.</b>\n"
            "👥 Приглашено друзей: <b>{referrals} шт.</b>\n\n"
            "Выберите нужный раздел 👇{ad_line}"
        ),

        # Kunlik bonus
        "daily_bonus_admin": (
            "👑 <b>Вы супер-админ</b> — у вас безлимитные запросы!"
        ),
        "daily_bonus_claimed": (
            "🎉 <b>Ежедневный бонус получен!</b>\n\n"
            "{reset_notice}"
            "🔥 Ваша серия: <b>{streak}/7 дней</b>\n"
            "{bar}\n\n"
            "🎁 Подарок на сегодня: <b>+{bonus} ИИ-запросов</b>\n"
            "💎 Общий баланс: <b>{credits} шт.</b>\n\n"
            "📌 <i>Заходите и завтра — на 7-й день получите "
            "<b>+4 супер-бонуса</b>!</i>"
        ),
        "daily_bonus_reset_notice": (
            "\n⚠️ <i>Был пропущен день, поэтому серия началась заново "
            "с 1-го дня.</i>\n"
        ),
        "daily_bonus_already": (
            "ℹ️ {msg}\n\n💎 Всего баллов: <b>{credits} шт.</b>"
        ),

        # Ballarni ulashish (transfer)
        "transfer_intro": (
            "🔄 <b>Передача баллов (ИИ-запросов):</b>\n\n"
            "Отправьте <b>ID</b> друга, его "
            "<b>Telegram username (@...)</b> или <b>специальный код</b> "
            "в боте:\n"
            "<i>(Примечание: передавать баллы можно только активным "
            "пользователям, зарегистрированным в боте)</i>"
        ),
        "transfer_insufficient": (
            "⚠️ <b>На вашем счету недостаточно баллов!</b>\n\n"
            "Для передачи нужно минимум <b>3 балла</b>. "
            "У вас: <b>{credits} шт.</b>.\n"
            "{guide}\n"
            "Или пригласите друзей по реферальной ссылке!"
        ),
        "transfer_user_not_found": (
            "❌ <b>Пользователь не найден!</b>\n\n"
            "Этот пользователь ещё не зарегистрирован в боте или данные "
            "введены неверно.\n"
            "Друг должен сначала зайти в бот и нажать <b>/start</b>.\n\n"
            "Введите правильный ID или код:"
        ),
        "transfer_self": (
            "⚠️ Нельзя передавать баллы самому себе! "
            "Введите данные другого друга:"
        ),
        "transfer_target_ok": (
            "✅ <b>Получатель:</b> <b>{name}</b> "
            "(ID: <code>{user_id}</code>)\n\n"
            "Сколько баллов отправить? <i>(Минимум <b>3</b>, "
            "максимум <b>20</b>)</i>:"
        ),
        "transfer_amount_nan": (
            "Пожалуйста, введите количество только цифрами "
            "(например: 5):"
        ),
        "transfer_amount_range": (
            "⚠️ Сумма перевода должна быть минимум <b>3</b> и максимум "
            "<b>20 баллов</b>. Введите заново:"
        ),
        "transfer_success": (
            "🎉 <b>Успешно!</b>\n\n"
            "На счёт <b>{name}</b> переведено "
            "<b>+{amount} ИИ-запросов</b>! 🚀"
        ),
        "transfer_gift_notice": (
            "🎁 <b>Вам подарок!</b>\n\n"
            "<b>{name}</b> отправил(а) вам <b>+{amount} ИИ-запросов</b>! 🎉"
        ),
        "transfer_error": "❌ <b>Ошибка:</b> {msg}",
        "transfer_default_name": "Ваш друг",

        # --- 2-QISM: ✨ AI Studio i18n (RU) ---
        "ai_studio_menu": (
            "🤖 <b>PostAssist AI Studio</b>\n\n"
            "💎 Доступно ИИ-запросов: {credits}\n\n"
            "Выберите нужный инструмент для создания контента канала 👇"
        ),
        "ai_studio_post": "✍️ Написать пост (AI)",
        "ai_studio_photo": "🖼 Создать пост из фото",
        "ai_studio_extract": "📢 Из открытого канала",
        "ai_studio_audit": "🔍 Аудит поста (ИИ)",
        "ai_studio_content_plan": "💡 Контент-план",
        "ai_studio_post_intro": (
            "✍️ <b>Написать пост (AI)</b>\n\n"
            "Напишите тему поста или отправьте фото/файл.\n"
            "<i>Например: «Мотивационный пост о здоровом образе жизни»</i>"
        ),
        "ai_studio_photo_intro": (
            "🖼 <b>Создать пост из фото</b>\n\n"
            "Отправьте фото — ИИ глубоко проанализирует его и напишет "
            "профессиональный SMM-пост для вашего канала:\n"
            "• ✨ Красиво оформленный заголовок (<b>...</b>)\n"
            "• 📝 Интересный / продающий текст\n"
            "• 😎 Эмодзи и списки\n"
            "• 👉 Призыв к действию (CTA) и хештеги\n\n"
            "<i>При желании отправьте подпись к фото — например: "
            "«сделай акцент на продаже товара на фото».</i>"
        ),
        "ai_studio_audit_intro": (
            "🔍 <b>Аудит поста (ИИ)</b>\n\n"
            "Отправьте готовый текст поста — ИИ проведёт аудит:\n"
            "• ✍️ Орфография и грамматика\n"
            "• 🎯 Привлекательность и CTA\n"
            "• 🧩 Рекомендации по структуре\n"
            "• ⭐️ Общая оценка (1-10)"
        ),
        "ai_studio_extract_intro": (
            "📢 <b>Взять из открытого канала</b>\n\n"
            "Введите @ник канала (например: <code>@kunuzofficial</code> или <code>daryo</code>):\n\n"
            "<i>Работает только для открытых каналов.</i>"
        ),
        "ai_studio_content_plan_intro": (
            "💡 <b>Генератор контент-плана</b>\n\nДля какого канала составим контент-план?"
        ),
        "ai_studio_no_channel": (
            "⚠️ <b>Сначала подключите канал.</b>\n\n"
            "Для составления контент-плана нужен хотя бы один канал.\n"
            "Подключите канал в разделе «Каналы»."
        ),
        "ai_tone_formal": "👔 Официальный",
        "ai_tone_friendly": "😊 Дружелюбный",
        "ai_tone_concise": "⚡️ Кратко",
        "ai_tone_engaging": "🎉 Привлекательный",
        "ai_tone_schedule": "➡️ Перейти к планированию",
        "ai_photo_schedule": "📅 Запланировать в канал",
        "ai_photo_rewrite": "🔄 Переписать",
        "ai_photo_edit": "✏️ Редактировать",
        "ai_photo_result_title": "🖼 <b>Пост, подготовленный по фото:</b>\n\n",
        "ai_photo_result_foot": (
            "\n\n🖼 <i>Отправленное фото будет прикреплено к посту.</i>\n\n"
            "Выберите следующий шаг 👇"
        ),
        "ai_btn_back": "⬅️ Назад",
        "ai_btn_close": "❌ Закрыть",
        "ai_btn_main_menu": "⬅️ Главное меню",
        "ai_confirm_schedule": "✅ Запланировать в канал",
        "ai_confirm_edit": "📝 Редактировать текст",
        "ai_preview_title": "✨ <b>ИИ-пост готов!</b>\n\n",
        "ai_preview_foot": (
            "\n\n🎨 <b>Стиль:</b> {tone}{media}\n\n"
            "Смените стиль или перейдите к планированию 👇"
        ),
        "ai_preview_media_note": "\n🖼 <i>Будет прикреплено к медиа-посту.</i>",
        "ai_thinking": "🤖 <i>ИИ готовит ответ...</i>",
        "ai_saving": "💾 Сохранение...",
        "ai_wait_post": "🤖 <i>ИИ пишет пост...</i>",
        "ai_wait_audit": "🔍 <i>ИИ проводит аудит...</i>",
        "ai_wait_photo": "🖼 <i>ИИ анализирует изображение...</i>",
        "ai_wait_edit": "✏️ <i>ИИ редактирует пост...</i>",
        "ai_unavailable": (
            "⚠️ Временный сбой в сервисе ИИ. "
            "Пожалуйста, попробуйте ещё раз чуть позже."
        ),
        "ai_rate_limit": (
            "⏳ <i>Вы отправляете ИИ-запросы слишком часто. Подождите 1 минуту...</i>"
        ),
        "ai_daily_limit": (
            "⚠️ <i>Дневной лимит ИИ-запросов исчерпан (30/день). Попробуйте завтра.</i>"
        ),
        "ai_limit_msg": (
            "🚫 <b>Дневной лимит ИИ исчерпан!</b>\n\n"
            "Сегодня использовано <b>{used}/{max}</b> ИИ-запросов.\n"
            "На бесплатном тарифе максимум <b>{max}</b> ИИ-запросов в день.\n\n"
            "⭐️ Перейдите на PRO для безлимитного ИИ."
        ),
        "ai_credits_unlimited": "♾ Безлимит",
        "ai_credits_unlimited_pro": "♾ Безлимит (PRO)",
        "ai_media_received": (
            "🖼 <b>Медиа получено!</b>\n\nТеперь напишите тему поста или текст."
        ),
        "ai_prompt_hint": "✍️ Напишите тему поста или отправьте фото/файл:",
        "ai_faq_footer": "\n\n<i>Напишите ещё тему или вернитесь назад 👇</i>",
        "ai_no_post_text": "⚠️ Не удалось определить текст поста. Попробуйте иначе сформулировать тему.",
        "ai_session_expired": "⚠️ Сессия устарела. Отправьте тему заново.",
        "ai_audit_prompt_hint": "🔍 Отправьте текст поста для аудита:",
        "ai_audit_result_title": "🔍 <b>Результат аудита ИИ:</b>\n\n",
        "ai_audit_no_result": "⚠️ ИИ не смог вернуть результат аудита. Попробуйте ещё раз.",
        "ai_photo_only": (
            "🖼 Отправьте, пожалуйста, фото (JPG/PNG/WEBP):\n"
            "• <i>К фото можно добавить подпись</i>\n"
            "• <i>Видео не анализируется — только фото</i>"
        ),
        "ai_video_rejected": (
            "🎬 <b>Видео не анализируется.</b>\n\n"
            "Для экономии ресурсов анализируется только <b>фото</b>.\n"
            "Отправьте, пожалуйста, <b>фото</b> для анализа (JPG/PNG/WEBP)."
        ),
        "ai_photo_no_text": "⚠️ ИИ не смог подготовить текст поста. Отправьте фото ещё раз.",
        "ai_photo_retry_hint": "🖼 Отправьте фото ещё раз или вернитесь в меню 👇",
        "ai_photo_edit_intro": (
            "✏️ <b>Редактировать пост</b>\n\n"
            "Какие изменения нужны? Отправьте текст:\n"
            "<i>Например: «перепиши заголовок иначе», «сократи», «добавь цену»</i>"
        ),
        "ai_photo_edit_hint": "✏️ Отправьте текст для редактирования:",
        "ai_photo_edit_no_result": "⚠️ ИИ не смог вернуть отредактированный текст. Попробуйте ещё раз.",
        "ai_photo_rewrite_wait": "🔄 <i>ИИ заново анализирует фото...</i>",
        "ai_photo_rewrite_keep": "⚠️ ИИ не смог переписать пост. Исходный пост сохранён.",
        "ai_tone_applying": "🎨 <i>Применяется стиль: {tone}...</i>",
        "ai_schedule_need_post": "⚠️ Сначала создайте пост. Напишите тему:",
        "ai_close_session": "❌ Сессия AI Studio завершена.",
        "ai_close_main_menu": "🏠 Главное меню.",
        "ai_not_found": "Извините, не смог найти ответ.",
        "ai_tone_unknown": "⚠️ Сессия устарела. Отправьте тему заново.",
        "ai_rate_limit_alert": "⏳ Слишком частые запросы. Подождите 1 минуту.",
        "ai_schedule_header": "✨ <b>Пост получен!</b>\n\n",
        "ai_schedule_foot": (
            "🕒 <b>Когда этот пост должен выйти в канале?</b>\n"
            "Выберите из кнопок ниже или напишите свободно:\n"
            "• <i>«завтра утром в 9»</i>\n"
            "• <i>«сегодня в 15:45 во все каналы»</i>\n"
            "• <i>«через 1 час»</i>"
        ),
        "ai_media_caption_note": "\n\n⬆️ Прикреплённое выше медиа будет добавлено к посту.",
        "ai_confirm_title": (
            "✨ <b>Подготовленный пост:</b>\n\n"
            "{post}\n\n"
            "🕒 <b>Время выхода:</b> <code>{time}</code>{target}\n\n"
            "Запланировать этот пост?"
        ),
        "ai_media_received_scheduled": (
            "🖼 <b>Медиа получено и прикреплено к посту!</b>\n\n"
            "Теперь напишите время выхода (например: <i>«сегодня в 18:00»</i>) или нажмите кнопку:"
        ),
        "ai_time_prompt_hint": "Пожалуйста, напишите время выхода (например: <i>«завтра в 10:00»</i>):",
        "ai_only_one_time": (
            "ℹ️ <i>Через ИИ-помощника планируется только одноразовый пост.</i>\n"
            "Для ежедневных/еженедельных повторяющихся постов используйте раздел "
            "<b>➕ Запланировать новый пост</b>.\n\n"
            "Напишите время (например: <i>«завтра в 10:00»</i>) или нажмите быструю кнопку:"
        ),
        "ai_time_fast": (
            "⏳ <i>Вы отправляете запросы слишком часто. Подождите 1 минуту или "
            "напишите время в точном формате: <code>2026-08-30 18:00</code></i>"
        ),
        "ai_time_ask": (
            "🤖 {reply}\n\n"
            "Время поста напишите так: <i>«завтра в 10:00»</i> или нажмите кнопку:"
        ),
        "ai_time_unparsed": (
            "⚠️ <b>Не удалось определить время или оно уже прошло.</b>\n\n"
            "Напишите так:\n"
            "• <i>«сегодня в 18:00»</i>\n"
            "• <i>«завтра утром в 9»</i>\n"
            "• <i>«через 30 минут»</i>\n"
            "Или точный формат: <code>2026-08-30 18:00</code>"
        ),
        "ai_post_ready": "✨ <b>Пост готов!</b>\n\n",
        "ai_post_ready_foot": (
            "\n\n🕒 <b>Время выхода:</b> <code>{time}</code>{target}\n\n"
            "Запланировать?"
        ),
        "ai_post_cancelled": "🚫 Пост отменён. Выберите нужный раздел в меню.",
        "ai_post_retry": (
            "📝 <b>Как изменим пост?</b>\n\n"
            "Например: <i>«добавь в конец номер телефона»</i>, <i>«сократи текст»</i>, "
            "<i>«измени заголовок»</i> — или отправьте новый пост."
        ),
        "ai_no_channel_schedule": (
            "⚠️ <b>Подключённые каналы не найдены.</b>\n\n"
            "Сначала подключите канал в разделе «Каналы/Группы», затем запланируйте пост заново."
        ),
        "ai_scheduled_ok": (
            "✅ <b>ИИ-пост успешно запланирован!</b>\n\n"
            "📢 Размещение: <b>{channel}</b>\n"
            "⏰ Время выхода: <b>{time}</b>\n\n"
            "Нажмите <b>🤖 ИИ-помощник</b>, чтобы создать ещё пост, или вернитесь в меню."
        ),
        "ai_schedule_error": "❌ Ошибка при сохранении. Пожалуйста, попробуйте позже.",
        "ai_photo_media_received": (
            "🖼 <b>Медиа получено!</b>\n\nТеперь напишите тему поста или текст."
        ),
    },
}


def normalize_lang(lang) -> str:
    """Faqat 'uz' yoki 'ru' qaytaradi."""
    if lang is None:
        return DEFAULT_LANG
    raw = str(lang).strip().lower()
    if raw.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


def detect_language(telegram_language_code) -> str:
    """Telegram ``language_code`` dan bot tilini aniqlaydi.

    'ru', 'ru-RU', 'ru-UZ' → 'ru'; aks holda → 'uz'.
    """
    return normalize_lang(telegram_language_code)


def get_text(key, lang="uz", **kwargs) -> str:
    """Lug'atdan matn olish. Noma'lum kalit/til uchun o'zbekcha fallback."""
    lang = normalize_lang(lang)
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def get_lang(context, default=DEFAULT_LANG) -> str:
    """``context.user_data['lang']`` dan tilni o'qiydi (kesh)."""
    try:
        ud = getattr(context, "user_data", None) or {}
        return normalize_lang(ud.get(LANG_KEY, default))
    except Exception:
        return normalize_lang(default)


def set_lang_cache(context, lang: str) -> str:
    """Tilni ``context.user_data['lang']`` ga yozadi (DB so'rovisiz)."""
    lang = normalize_lang(lang)
    try:
        if context is not None and getattr(context, "user_data", None) is not None:
            context.user_data[LANG_KEY] = lang
    except Exception:
        pass
    return lang


def clear_fsm_data(context) -> None:
    """FSM holatini tozalaydi, lekin til keshini saqlab qoladi."""
    if context is None:
        return
    ud = getattr(context, "user_data", None)
    if ud is None:
        return
    lang = ud.get(LANG_KEY) if hasattr(ud, "get") else None
    ud.clear()
    if lang in SUPPORTED_LANGS:
        ud[LANG_KEY] = lang


# --- Ma'lumotlar bazasidan qaytadigan tayyor matnlar (uz) tarjimalari ---
# ``database.py`` dagi ayrim funksiyalar (kunlik bonus, ball o'tkazish)
# foydalanuvchiga ko'rsatiladigan matnni o'zbekchada qaytaradi. Bu lug'at
# ularni rus tiliga o'giradi; topilmasa asl (o'zbekcha) matn qaytariladi —
# ya'ni hech qanday xabar yo'qolmaydi.
DB_MESSAGE_TRANSLATIONS = {
    "ru": {
        "Foydalanuvchi topilmadi.": "Пользователь не найден.",
        "Siz bugungi bonusingizni olgansiz! Ertaga yana kiring.": (
            "Вы уже получили сегодняшний бонус! Заходите завтра."
        ),
        "Tizim xatoligi yuz berdi.": "Произошла системная ошибка.",
        "O'zingizga ball o'tkaza olmaysiz.": (
            "Нельзя переводить баллы самому себе."
        ),
        "O'tkazish miqdori kamida 3 ta, ko'pi bilan 20 ta bo'lishi kerak.": (
            "Сумма перевода — минимум 3, максимум 20 баллов."
        ),
        "Hisobingizda yetarli ball mavjud emas.": (
            "На вашем счету недостаточно баллов."
        ),
        "Qabul qiluvchi foydalanuvchi topilmadi.": "Получатель не найден.",
        "Ballar muvaffaqiyatli o'tkazildi!": "Баллы успешно переведены!",
        (
            "⚠️ <b>Xavfsizlik qoidasi:</b> Yangi ro'yxatdan o'tgan "
            "foydalanuvchilar ballarni <b>3 kun o'tgach</b> boshqalarga "
            "ulasha oladi."
        ): (
            "⚠️ <b>Правило безопасности:</b> новые пользователи могут "
            "переводить баллы другим <b>через 3 дня</b> после регистрации."
        ),
    },
}


def localize_db_message(message, lang="uz") -> str:
    """DB dan kelgan tayyor xabarni foydalanuvchi tiliga o'giradi.

    Tarjima topilmasa (yoki til o'zbekcha bo'lsa) asl matn qaytariladi.
    """
    if message is None:
        return ""
    text = str(message)
    if normalize_lang(lang) == DEFAULT_LANG:
        return text
    table = DB_MESSAGE_TRANSLATIONS.get(normalize_lang(lang)) or {}
    return table.get(text.strip(), text)
