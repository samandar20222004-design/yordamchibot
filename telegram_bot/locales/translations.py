"""Sodda i18n lug'ati: o'zbek (uz) va rus (ru).

Foydalanish:
    get_text("start_hello", lang="ru", name="Ivan")
"""

import re
import string

DEFAULT_LANG = "uz"
SUPPORTED_LANGS = ("uz", "ru", "en")
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
        # 🚀 BIRINCHI MARTA kirgan foydalanuvchi uchun onboarding matni
        # (faqat ro'yxatdan yangi o'tganda ko'rsatiladi).
        "start_onboarding": (
            "👋 Xush kelibsiz! Telegram kanalingiz uchun 1 daqiqada professional post tayyorlaymizmi?\n"
            "\n"
            "✍️ AI post yozish\n"
            "📅 Istalgan vaqtga rejalashtirish\n"
            "📢 Avtomatik kanalga chiqarish\n"
            "\n"
            "Birinchi postingizni hoziroq tayyorlash uchun quyidagi bo'limni tanlang 👇"
        ),
        # 🆕 SODDA KLAVIATURA — yangi foydalanuvchilar (1-3 kun) uchun 3 ta
        # katta tugma + 1 ta kichik "to'liq menyu" tugmasi.
        "quick_menu_hint": (
            "👋 <b>Xush kelibsiz!</b>\n\n"
            "Boshlash uchun pastdagi <b>3 ta tugmadan</b> birini bosing — qolgani avtomatik.\n\n"
            "🚀 AI post yozadi  •  🖼 Rasmdan post oladi  •  📢 Kanalni ulaydi\n\n"
            "<i>Barcha bo'limlar kerak bo'lsa — pastdagi "
            "«⚙️ To'liq menyuni ochish» tugmasini bosing.</i>"
        ),
        "quick_btn_ai_post": "🚀 1 daqiqada post yaratish",
        "quick_btn_photo_post": "🖼 Rasmdan post olish",
        "quick_btn_add_channel": "📢 Kanal ulash",
        "quick_btn_full_menu": "⚙️ To'liq menyuni ochish",
        "quick_full_menu_opened": (
            "✅ <b>To'liq menyu ochildi!</b>\n\n"
            "Endi barcha bo'limlar sizga ochiq — pastdagi menyudan tanlang 👇"
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
        "card_tariff_title": (
            "💳 <b>Karta orqali to'lov</b>\n\n"
            "📌 Qaysi tarifga to'laysiz? Tarifni tanlang 👇"
        ),
        "card_plan_1m": "1 oy",
        "card_plan_3m": "3 oy",
        "card_plan_1y": "1 yil",
        "card_tariff_1m": "1 oy — {price} so'm",
        "card_tariff_3m": "3 oy — {price} so'm",
        "card_tariff_1y": "1 yil — {price} so'm",
        "card_payment_selected": (
            "🎫 Tanlangan tarif: <b>{tarif}</b>\n"
            "💰 To'lov summasi: <b>{summa} so'm</b>"
        ),
        "card_payment_card": "💳 <b>Karta raqami:</b> <code>{card}</code>\n👤 <b>Karta egasi:</b> {holder}",
        "card_payment_no_card": "ℹ️ Karta rekvizitlarini olish uchun adminga murojaat qiling.",
        "card_payment_steps": (
            "📝 <b>Yo'riqnoma:</b>\n"
            "1️⃣ Tanlangan summani yuqoridagi kartaga o'tkazing.\n"
            "2️⃣ To'lov chekini (skrinshot yoki PDF) oling.\n"
            "3️⃣ Pastdagi <b>\"📸 Chek yuborish\"</b> tugmasini bosing va chekni shu yerga yuboring.\n"
            "4️⃣ Sizning ID: <code>{user_id}</code> — chek tekshiruvida ishlatiladi.\n\n"
            "Admin tasdiqlagach <b>PRO tarif</b> faollashtiriladi.\n"
            "⚡️ Tezroq bo'lishi uchun ⭐️ Stars orqali to'lasangiz PRO darhol yoqiladi.\n"
            "Savol bo'lsa: {admin}"
        ),
        "card_payment_admin_missing": "admin (Bot haqida bo'limidagi aloqa orqali)",
        "btn_send_receipt": "📸 Chek yuborish",
        "receipt_prompt": (
            "📸 <b>To'lov chekini yuboring:</b>\n\n"
            "🎫 Tanlangan tarif: {tarif} ({summa} so'm)\n\n"
            "Chekni (skrinshot yoki PDF) <b>rasm yoki hujjat</b> ko'rinishida yuboring. "
            "Bot chekni adminlarga yuboradi.\n"
            "🆔 Sizning ID: <code>{user_id}</code>\n\n"
            "Admin tasdiqlagach <b>PRO tarif</b> avtomatik faollashtiriladi."
        ),
        "receipt_bad_media": (
            "⚠️ Iltimos, to'lov chekini <b>rasm (foto)</b> yoki <b>PDF hujjat</b> "
            "sifatida yuboring. Boshqa fayllar chek sifatida qabul qilinmaydi."
        ),
        "receipt_saved": (
            "✅ Chekingiz qabul qilindi va adminga yuborildi. "
            "Tez orada tekshirib PRO faollashtiriladi."
        ),
        "receipt_save_error": (
            "⚠️ Chekni saqlashda xatolik yuz berdi. "
            "Iltimos, qayta yuboring."
        ),
        "receipt_admin_title": "💳 <b>Yangi to'lov cheki!</b>",
        "receipt_admin_user_line": "👤 Foydalanuvchi: {name} (@{username})",
        "receipt_admin_user_nick_line": "👤 Foydalanuvchi: {name}",
        "receipt_admin_user_id_line": "🆔 ID: {user_id}",
        "receipt_admin_tarif_line": "🎫 Tanlangan tarif: {tarif} ({summa} so'm)",
        "receipt_admin_time_line": "🕐 Vaqti: {sana}",
        "receipt_admin_ask": "📝 Chekni tekshirib, pastdagi tugmalardan birini bosing:",
        "receipt_btn_approve": "✅ Tasdiqlash",
        "receipt_btn_reject": "❌ Rad etish",
        "receipt_admin_done_ok": "✅ Tasdiqlandi. Foydalanuvchiga PRO berildi.",
        "receipt_admin_done_reject": "❌ Rad etildi.",
        "receipt_admin_already": "Bu chek allaqachon ko'rib chiqilgan.",
        "receipt_approved_user": (
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            "To'lov chekingiz tasdiqlandi va <b>{days} kunlik PRO tarif</b> "
            "faollashtirildi!\nBarcha PRO imkoniyatlardan foydalanishingiz mumkin. 🚀"
        ),
        "receipt_rejected_user": (
            "❌ <b>Chek rad etildi</b>\n\n"
            "Afsuski, to'lov chekingiz tasdiqlanmadi. Iltimos, qayta urinib "
            "ko'ring yoki '⭐️ Premium' bo'limidan adminga murojaat qiling."
        ),
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
        # 🚀 7 KUNLIK KONTENT-REJANI BITTA TUGMA BILAN NAVBATGA QO'YISH
        "plan_btn_schedule_all": "🚀 Barchasini 7 kunga rejalashtirish",
        "plan_week_hint": "\n\n🚀 <i>Yoki bitta tugma bilan butun haftani "
                        "navbatga qo'ying.</i>",
        "plan_sched_busy": "⏳ 7 kunlik postlar navbatga qo'yilmoqda...",
        "plan_sched_done_alert": "✅ 7 kunlik postlar navbatda!",
        "plan_sched_done": (
            "✅ <b>7 kunlik postlar navbatga qo'yildi!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "📦 Navbatga qo'yildi: <b>{count} ta post</b>\n\n"
            "{days}\n\n"
            "🤖 Postlar har kuni soat <b>12:00</b> da avtomatik chiqadi.\n"
            "📋 Istalgan postni «👤 Kabinet & Sozlamalar» → "
            "«⏳ Postlar navbati (Queue)» bo'limidan tahrirlashingiz yoki "
            "bekor qilishingiz mumkin."
        ),
        "plan_sched_already": "ℹ️ Bu kontent-reja allaqachon navbatga qo'yilgan.",
        "plan_sched_stale": (
            "⚠️ Sessiya eskirgan. Kontent-rejani qayta yarating — "
            "shundan keyin bitta tugma bilan 7 kunga rejalashtirasiz."
        ),
        "plan_sched_no_channel": (
            "⚠️ <b>Kanal topilmadi.</b>\n\n"
            "Avval kanal ulang, so'ng kontent-rejani qayta yarating."
        ),
        "plan_sched_empty": "⚠️ Reja bo'sh — avval kontent-rejani yarating.",
        "plan_sched_error": "❌ Postlarni navbatga qo'yishda xatolik yuz berdi. Qaytadan urinib ko'ring.",
        "plan_sched_day_line": "• {day} — soat {time}",
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
        "ai_photo_variants_ask": (
            "🎨 Rasm bo'yicha <b>3 xil uslub</b> tayyorlandi. "
            "Birini tanlang — tanlangan matn ochiladi 👇"
        ),
        "ai_wait_edit": "✏️ <i>AI postni tahrirlamoqda...</i>",
        "ai_unavailable": (
            "⚠️ AI xizmatida vaqtinchalik uzilish yuz berdi. "
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        ),
        "ai_quota": (
            "⚠️ AI kvota yo‘qaldi. "
            "Vaqt o‘tgandan so‘ng qayta urinib ko'ring."
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
            "Yoki aniq format: <code>DD.MM.YYYY HH:MM</code> "
            "(masalan <code>30.08.2026 18:00</code>)\n\n"
            "🕒 <i>Toshkent vaqti (UTC+5).</i>"
        ),
        "ai_time_detecting": "🤖 <i>Vaqt aniqlanmoqda...</i>",
        "ai_full_post_text": "📝 <b>Post matni (to'liq):</b>\n\n{text}",
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

        # --- 3-QISM: ➕ Yangi post i18n (UZ) ---
        # Tugma yorliqlari (reply klaviatura)
        "np_btn_skip": "➡️ Tugmasiz davom etish",
        "np_btn_skip_url": "⏭ O'tkazib yuborish",
        "np_btn_url_add": "🔗 URL tugma qo'shish",
        "np_btn_ai_assistant": "✨ AI Yordamchi",
        "np_btn_title_details": "Batafsil",
        "np_btn_title_join": "Kanalga a'zo bo'lish",
        "np_btn_title_site": "Saytga o'tish",
        "np_btn_title_contact": "Bog'lanish",
        "np_btn_no_reactions": "➡️ Reaksiyasiz davom etish",
        "np_btn_del_never": "❌ O'chirilmasin (Doimiy)",
        "np_btn_del_12h": "⏳ 12 soat",
        "np_btn_del_24h": "⏳ 24 soat (1 kun)",
        "np_btn_del_48h": "⏳ 48 soat (2 kun)",
        "np_btn_del_72h": "⏳ 72 soat (3 kun)",
        "np_btn_time_5m": "⚡ 5 daqiqa",
        "np_btn_time_15m": "⚡ 15 daqiqa",
        "np_btn_time_1h": "⚡ 1 soat",
        "np_btn_time_daily": "🔁 Har kuni (bir vaqtda)",
        "np_btn_time_weekly": "📅 Har hafta (ma'lum kuni)",
        "np_btn_dur_1w": "1 hafta",
        "np_btn_dur_1m": "1 oy",
        "np_btn_dur_3m": "3 oy",
        "np_btn_dur_6m": "6 oy",
        "np_btn_dur_1y": "1 yil",
        "np_btn_dur_inf": "♾ Cheksiz",
        "np_weekday_0": "Dushanba",
        "np_weekday_1": "Seshanba",
        "np_weekday_2": "Chorshanba",
        "np_weekday_3": "Payshanba",
        "np_weekday_4": "Juma",
        "np_weekday_5": "Shanba",
        "np_weekday_6": "Yakshanba",
        "np_btn_back_confirm": "🔙 Orqaga",
        "np_btn_all_channels": "🌐 Barchasiga birdaniga",
        "np_label_today": "Bugun",
        "np_label_tomorrow": "Ertaga",

        # Yangi post jarayoni matnlari
        "np_channel_selected": (
            "✅ Tanlandi: <b>{channel}</b>\n\n"
            "📝 <b>Post uchun kontentni yuboring:</b>\n"
            "(Matn, rasm, video, albom, hujjat, audio yoki GIF — stiker va ovozli xabar qabul qilinmaydi)"
        ),
        "np_channel_not_found": "⚠️ Bunday kanal topilmadi. Qaytadan tanlang:",
        "np_media_not_allowed": (
            "Kechirasiz, stikerlar post sifatida qabul qilinmaydi. Iltimos, "
            "rasm, video yoki matn yuboring"
        ),
        "np_all_channel_title": "🌐 Barchasi",
        "np_button_ask": (
            "🔘 <b>Post ostiga havola tugma qo'shilsinmi?</b> (ixtiyoriy)\n\n"
            "⚡️ <b>Tezkor usul:</b> tugma yozuvi va havolani bir qatorda yuboring:\n"
            "<code>Button Text - https://link.com</code>\n\n"
            "Yoki tayyor yozuvlardan tanlang / o'z yozuvingizni yuboring "
            "(so'ng havola so'raladi).\n\n"
            "Kerak bo'lmasa, <b>⏭ O'tkazib yuborish</b> tugmasini bosing:"
        ),
        "np_button_ready": (
            "✅ <b>Inline tugma tayyor:</b>\n"
            "🔘 Yozuv: <b>{title}</b>\n"
            "🔗 Havola: <code>{url}</code>"
        ),
        "np_button_url_ask": (
            "🔗 <b>'{title}'</b> tugmasi bosilganda ochiladigan havola yoki "
            "kanal username'ini yuboring:\n\n"
            "Masalan: <code>@kanalim</code> yoki <code>https://sayt.uz</code>\n\n"
            "<i>Yoki bir qatorda yuboring: <code>{title} - https://link.com</code></i>"
        ),
        "np_button_url_add_ask": (
            "🔗 <b>URL tugma qo'shish</b>\n\n"
            "Tugma yozuvi va havolani <b>bir qatorda, \" - \" bilan ajratib</b> yuboring:\n"
            "<code>Button Text - https://link.com</code>\n\n"
            "<i>Masalan:</i> <code>Saytga o'tish - https://sayt.uz</code> yoki\n"
            "<code>Kanalim - @kanalim</code>"
        ),
        "np_reactions_ask": (
            "👍 <b>Post ostiga qaysi reaksiya tugmalari qo'shilsin?</b>\n\n"
            "Kerakli emojilarni bosing — ✅ belgilanadi (qayta bossangiz bekor bo'ladi).\n"
            "Yoki erkin yozing, masalan: <code>👍 ❤️ 🔥</code> — bir nechtasini "
            "probel bilan yuborsangiz ham bo'ladi.\n"
            "Stiker yuborsangiz — uning emojisi ham reaksiyaga qo'shiladi.\n"
            "Tanlab bo'lgach, <b>➡️ Davom etish</b> tugmasini bosing.\n"
            "Reaksiya kerak bo'lmasa — <b>⏭ Reaksiyasiz o'tish</b>."
        ),
        "np_reactions_selected": (
            "✅ Tanlanganlar: {emojis}\n"
            "Yana emoji qo'shishingiz yoki <b>➡️ Davom etish</b> ni bosishingiz mumkin:"
        ),
        "np_reactions_use_inline": (
            "⚠️ <b>Iltimos, pastdagi inline tugmalardan foydalaning:</b>\n"
            "• Emojilarni bosib tanlang (✅ belgilanadi)\n"
            "• Erkin emoji yuborish ham mumkin: <code>👍 ❤️ 🔥</code>\n"
            "• Stiker yuborsangiz — uning emojisi reaksiyaga qo'shiladi\n"
            "• <b>➡️ Davom etish</b> — tanlanganlar bilan keyingi qadam\n"
            "• <b>⏭ Reaksiyasiz o'tish</b> — reaksiyasiz"
        ),
        "np_reactions_none": (
            "ℹ️ Hech qanday reaksiya tanlanmadi — post reaksiyalarsiz chiqadi."
        ),
        "np_react_done": "➡️ Davom etish",
        "np_react_done_count": "➡️ Davom etish ({count} ta)",
        "np_react_skip": "⏭ Reaksiyasiz o'tish",
        "np_auto_delete_ask": (
            "🗑️ <b>Post kanalda qancha vaqt tursin?</b>\n\n"
            "Belgilangan vaqt o'tgach, bot uni kanaldan avtomatik o'chirib tashlaydi:"
        ),
        "np_time_ask": (
            "🕒 <b>Post qaysi vaqtda chiqsin?</b>\n\n"
            "Tayyor tugmalardan tanlang yoki aniq vaqtni yozing.\n"
            "Format: <code>DD.MM.YYYY HH:MM</code>\n"
            "Namuna: <code>{example}</code>\n\n"
            "🕒 <i>Toshkent vaqti (UTC+5).</i>"
        ),
        "np_time_future": (
            "⚠️ <b>Bu vaqt allaqachon o'tib ketgan.</b>\n\n"
            "Iltimos, KELAJAKDAGI vaqtni kiriting.\n"
            "Namuna: <code>{example}</code>\n\n"
            "🕒 <i>Hozir Toshkentda: {now}</i>"
        ),
        "np_time_format_error": (
            "⚠️ <b>Vaqt formati tushunarsiz.</b>\n\n"
            "To'g'ri format: <code>DD.MM.YYYY HH:MM</code>\n"
            "Namuna: <code>{example}</code>\n\n"
            "Yoki quyidagilardan birini yozing:\n"
            "• faqat soat — <code>18:00</code> (bugun, o'tgan bo'lsa ertaga)\n"
            "• <code>ertaga 18:00</code>\n"
            "• <code>2 soatdan keyin</code>\n\n"
            "🕒 <i>Barcha vaqtlar Toshkent vaqti (UTC+5) bo'yicha.</i>"
        ),
        "np_daily_time_ask": (
            "🔁 <b>Har kuni soat nechida chiqsin?</b>\n"
            "Masalan: <code>10:00</code> yoki <code>18:30</code>"
        ),
        "np_daily_time_format": (
            "⚠️ <b>Noto'g'ri vaqt formati.</b>\n\n"
            "Faqat soatni <code>HH:MM</code> ko'rinishida yozing.\n"
            "Namuna: <code>10:00</code> yoki <code>18:30</code>\n\n"
            "🕒 <i>Toshkent vaqti (UTC+5).</i>"
        ),
        "np_weekday_ask": "📅 <b>Haftaning qaysi kuni chiqsin?</b>",
        "np_weekday_invalid": "⚠️ Kunlardan birini tanlang:",
        "np_recur_time_ask": (
            "🕒 <b>Har {day} soat nechida chiqsin?</b>\n"
            "Masalan: <code>10:00</code>"
        ),
        "np_recur_time_format": (
            "⚠️ <b>Noto'g'ri format!</b> Soatni <code>HH:MM</code> ko'rinishida "
            "yozing. Namuna: <code>10:00</code> 🕒 <i>(Toshkent vaqti, UTC+5)</i>"
        ),
        "np_duration_ask_daily": (
            "⏳ <b>Post qancha muddat davomida har kuni chiqsin?</b>"
        ),
        "np_duration_ask_weekly": (
            "⏳ <b>Ushbu post qancha muddat davomida chiqsin?</b>"
        ),
        "np_duration_invalid": "⚠️ Variantlardan birini tanlang:",

        # Tasdiqlash (confirmation) ekrani
        "np_confirm_title": "📋 <b>Postni tasdiqlang:</b>",
        "np_confirm_channel": "📢 <b>Kanal:</b> {channel}",
        "np_confirm_type": "📦 <b>Turi:</b> {type}",
        "np_type_text": "📝 Matn",
        "np_type_photo": "🖼 Rasm",
        "np_type_video": "🎬 Video",
        "np_type_document": "📄 Hujjat",
        "np_type_audio": "🎵 Audio",
        "np_type_voice": "🎙 Ovozli",
        "np_type_sticker": "😀 Stiker",
        "np_type_album": "🖼 Albom",
        "np_type_animation": "🎞 GIF",
        "np_type_unknown": "📝 Xabar",
        # Albom xulosasi (preview'da nechta fayl borligi aniq ko'rinadi)
        "np_confirm_album_photos": "🖼 Albom: {count} ta rasm",
        "np_confirm_album_videos": "🎬 Albom: {count} ta video",
        "np_confirm_album_mixed": "🖼 Albom: {photos} ta rasm, {videos} ta video",
        "np_confirm_album_files": "🖼 Albom: {count} ta fayl",
        "np_confirm_content_truncated": (
            "⚠️ Eslatma: matn {total} belgi — Telegram {limit} belgi chegarasi "
            "tufayli kanaldagi postda shu limitgacha ko'rinadi. Matn to'liq saqlanadi."
        ),
        "np_confirm_time_none": "⏰ Vaqt belgilanmagan",
        "np_confirm_time_single": "⏰ {time} (Toshkent vaqti)",
        "np_confirm_time_daily": "🔁 Har kuni, soat {time} da",
        "np_confirm_time_weekly": "📅 Har {day}, soat {time} da",
        "np_confirm_content": "📋 <b>Matn:</b>\n{content}",
        "np_confirm_button": "🔘 Tugma: <b>{text}</b>",
        "np_confirm_reactions": "👍 Reaksiyalar: {emojis}",
        "np_confirm_reactions_on": "👍 Reaksiyalar: Yoqilgan",
        "np_confirm_auto_delete": "⏳ Avto-o'chirish: {hours} soat",
        "np_confirm_ok_btn": "✅ Tasdiqlash va rejalashtirish",
        "np_confirm_queue_btn": "⏳ Navbatga qo'shish",
        "np_confirm_edit_btn": "✏️ Tahrirlash",
        "np_confirm_cancel_btn": "❌ Bekor qilish",

        # 🖼 ALBOM + tugma/reaksiya ogohlantirishi (sendMediaGroup cheklovi)
        # Telegram Bot API qoidasi: sendMediaGroup'ga inline_keyboard (URL
        # tugma yoki reaksiya) ulab bo'lmaydi — albom yuborilganda foydalanuvchi
        # xushmuomala ogohlantirish + 2 ta tanlov oladi.
        "np_album_warning": (
            "⚠️ Telegram qoidalariga ko'ra bir nechta rasmli albomlarga havola yoki "
            "reaksiya tugmalarini qo'shib bo'lmaydi. \n"
            "Tugma yoki reaksiya faqat 1 ta rasm (yoki oddiy matn) uchun ishlaydi."
        ),
        "np_album_choice_first_photo": "🖼 1-rasm qolsin + tugma qo'shilsin",
        "np_album_choice_full": "⏩ Tugmalarsiz to'liq albom chiqsin",
        "np_album_first_photo_done": (
            "✅ Post bitta rasmga o'zgartirildi — endi tugma yoki reaksiya qo'sha olasiz."
        ),
        "np_album_full_done": (
            "✅ To'liq albom ({count} ta fayl) tugma va reaksiyasiz chiqariladi."
        ),

        # Tahrirlash sub-menyusi
        "np_edit_menu_title": "✏️ <b>Qaysi qismini tahrirlash kerak?</b>",
        "np_edit_content_btn": "📝 Matn",
        "np_edit_channel_btn": "📢 Kanal",
        "np_edit_time_btn": "⏰ Vaqt",
        "np_edit_button_btn": "🔘 Tugma",
        "np_edit_back_btn": "⬅️ Orqaga (tasdiqlashga)",
        "np_edit_content_ask": "📝 <b>Yangi matn yuboring:</b>",
        "np_edit_channel_ask": "📢 <b>Qaysi kanal?</b>",
        "np_edit_time_ask": "🕒 <b>Yangi vaqt:</b> <code>{example}</code>",
        "np_edit_button_ask": (
            "🔘 <b>Tugma:</b> <code>Matn | https://havola.uz</code>\n"
            "O'chirish: <code>yo'q</code>"
        ),
        "np_edit_channel_not_found": "⚠️ Kanal topilmadi.",

        # Yakuniy xabarlar
        "np_cancelled": "🚫 <b>Post bekor qilindi.</b>\nAsosiy menyuga qaytdingiz 👇",
        "np_no_time": "⚠️ <b>Vaqt belgilanmagan.</b>",
        "np_no_channel": "⚠️ <b>Kanal tanlanmagan.</b>",
        "np_no_slot": (
            "⚠️ <b>Bo'sh slot topilmadi.</b>\n7 kun ichida barcha slotlar band."
        ),
        "np_scheduled_ok": (
            "✅ <b>Post muvaffaqiyatli rejalashtirildi!</b>\n\n"
            "📢 Joylash: <b>{channel}</b>\n"
            "{when}{del_info}"
        ),
        "np_scheduled_when_single": "⏰ {time}",
        "np_scheduled_when_daily": "🔁 Har kuni, soat {time} da",
        "np_scheduled_when_weekly": "📅 Har {day}, soat {time} da",
        "np_scheduled_del": "\n⏳ Kanalda turish muddati: <b>{hours} soat</b>",
        "np_queue_added": (
            "⚡️ <b>Post navbatga qo'yildi!</b>\n\n"
            "📅 {label}, soat {time}\n"
            "📢 Kanal: <b>{channel}</b>{ad_line}"
        ),
        "np_queue_error": "❌ <b>Navbatga qo'yishda xatolik.</b>",
        "np_save_error": "❌ Saqlashda xatolik yuz berdi.",
        "np_save_error_bold": "❌ <b>Saqlashda xatolik.</b>",

        # AI Yordamchi (post tahrirlashda)
        "np_ai_menu_title": (
            "✨ <b>AI Yordamchi</b>\n\n"
            "📋 Joriy matn:\n<i>{preview}</i>\n\n"
            "Qaysi amalni bajaramiz?"
        ),
        "np_ai_empty_content": "⚠️ <b>Post matni bo'sh.</b>\nAvval matn kiriting.",
        "np_ai_empty_alert": "⚠️ Matn bo'sh!",
        "np_ai_working": "⏳ AI ishlayapti...",
        "np_ai_empty_result": "⚠️ AI javobi bo'sh. Asl matn saqlab qolindi.",
        "np_ai_proposal": (
            "✨ <b>AI taklifi:</b>\n\n{new}\n\n"
            "📝 Asl: <i>{old}</i>"
        ),
        "np_ai_retry_proposal": "✨ <b>AI taklifi (qayta):</b>\n\n{new}",
        "np_ai_accepted_alert": "✅ Qabul qilindi!",
        "np_ai_accept_msg": "✅ <b>Yangi matn qabul qilindi!</b>\n\n{content}",
        "np_ai_reverted_alert": "❌ Asl holatga qaytarildi!",
        "np_ai_revert_msg": "❌ <b>Asl matn qaytarildi.</b>",
        "np_ai_retrying": "🔄 Qayta urinilmoqda...",
        "np_ai_action_grammar": "✍️ Imlo va uslub",
        "np_ai_action_emoji": "🎨 Emojilar",
        "np_ai_action_hashtags": "🏷 Hashtaglar",
        "np_ai_action_tldr": "✂️ Qisqartirish",
        "np_ai_btn_back": "⬅️ Orqaga",
        "np_ai_btn_accept": "✅ Qabul qilish",
        "np_ai_btn_retry": "🔄 Qayta urinish",
        "np_ai_btn_revert": "❌ Asl holatga qaytarish",

        # --- 3-QISM: 📢 Mening kanallarim i18n (UZ) ---
        "ch_empty_title": (
            "📢 <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Kanal ulash uchun quyidagi tugmani bosing 👇\n\n"
            "<i>Botni kanalingizga administrator qilib (xabar yuborish ruxsati "
            "bilan) qo'shish kerak bo'ladi.</i>"
        ),
        "ch_list_title": (
            "📢 <b>Sizning ulangan kanallaringiz ({count} ta):</b>\n\n"
            "Kanalni o'chirish uchun '❌ O'chirish' tugmasini bosing yoki "
            "yangi kanal ulang 👇"
        ),
        "ch_all_removed": (
            "📢 <b>Barcha kanallar o'chirildi.</b>\n\n"
            "Yangi kanal ulash uchun quyidagi tugmani bosing 👇"
        ),
        "ch_add_btn": "➕ Kanal/Guruh ulash",
        "ch_add_instructions": (
            "➕ <b>Yangi kanal yoki guruh ulash:</b>\n\n"
            "1. Botni (<code>@{bot}</code>) kanalingizga yoki guruhingizga "
            "<b>Administrator</b> qilib qo'shing (xabar yuborish ruxsati bilan).\n"
            "2. So'ngra kanal manbasini yuboring — to'rt formatning birida:\n"
            "   • kanaldan istalgan xabarni <b>Forward (Uzatish)</b>;\n"
            "   • <code>@kanal_nomi</code>;\n"
            "   • <code>t.me/kanal_nomi</code> yoki <code>https://t.me/kanal_nomi</code>;\n"
            "   • kanal ID raqami (masalan: <code>-1001234567890</code>).\n\n"
            "<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>"
        ),
        "ch_retry_btn": "🔁 Botni admin qildim — qayta tekshirish",
        "ch_empty_target": (
            "❌ Bo'sh xabar qabul qilindi. Kanalni <b>forward</b> qiling, "
            "<code>@username</code>, ID yoki <code>t.me/kanal</code> havolasini yuboring."
        ),
        "ch_invite_blocked": (
            "🔒 <b>Yopiq kanal (invite) havolasi orqali ulab bo'lmaydi.</b>\n\n"
            "Bot kanalda administrator bo'lgani uchun <code>@username</code> "
            "yoki kanaldan istalgan xabarni <b>forward</b> qiling — shunda "
            "kanalni aniqlaymiz."
        ),
        "ch_not_found": (
            "❌ Kanal yoki guruh topilmadi. Forward qiling yoki to'g'ri ID yuboring."
        ),
        "ch_cannot_verify": (
            "⚠️ <b>Bot ushbu kanalda emas yoki huquqlarni tekshirib bo'lmadi.</b>\n\n"
            "Avval botni administrator qiling (xabar yuborish ruxsati bilan)."
        ),
        "ch_not_admin": (
            "⚠️ <b>Bot ushbu kanalda administrator emas!</b>\n\n"
            "Iltimos, avval botga kanalda xabar yuborish ruxsatini bering."
        ),
        "ch_no_post_permission": (
            "⚠️ <b>Botga kanalda xabar yuborish ruxsati berilmagan.</b>\n\n"
            "Administrator sozlamalarida <b>Post Messages</b> huquqini yoqing."
        ),
        "ch_user_verify_fail": (
            "⚠️ <b>Sizning ushbu kanaldagi huquqingizni tekshirib bo'lmadi.</b>\n\n"
            "Faqat kanal/guruh administratori botga kanal ulashi mumkin."
        ),
        "ch_forbidden": (
            "🚫 <b>Ruxsat yo'q.</b>\n\n"
            "Faqat kanal yoki guruh <b>administratori</b> ushbu botga kanal ulashi mumkin."
        ),
        "ch_unknown_target": (
            "❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni "
            "<b>forward</b> qiling yoki <code>@username</code>, "
            "<code>t.me/kanal_nomi</code> havolasi, ID raqamini "
            "(masalan: <code>-1001234567890</code>) yuboring."
        ),
        "ch_empty_target_short": (
            "❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni forward qiling:"
        ),
        "ch_unexpected_error": (
            "⚠️ <b>Kutilmagan xatolik yuz berdi.</b>\n\n"
            "Iltimos, kanalni qaytadan forward qiling yoki "
            "<code>@username</code> / <code>t.me/kanal</code> havolasini yuboring."
        ),
        "ch_retry_after": (
            "{error}\n\nBotga ruxsat berganingizdan so'ng quyidagi tugmani bosing "
            "yoki kanal manbasini qayta yuboring 👇"
        ),
        "ch_limit_msg": (
            "🚫 <b>Kanal limiti tugadi!</b>\n\n"
            "Sizda hozir <b>{current}/{max}</b> ta kanal ulangan.\n"
            "Free tarifida maksimal <b>{max}</b> ta kanal ulash mumkin.\n\n"
            "⭐️ Ushbu imkoniyatdan cheksiz foydalanish uchun PRO tarifiga o'ting."
        ),
        "ch_pro_btn": "⭐️ PRO tarifga o'tish",
        "ch_success": (
            "✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n"
            "📢 Nomi: <b>{title}</b>\n"
            "🆔 ID: <code>{channel_id}</code>\n\n"
            "📋 <b>Sizning kanallaringiz ({count} ta):</b>"
        ),
        "ch_success_footer": "Kanalni o'chirish yoki uslubini o'zgartirish uchun 👇",
        "ch_taken": (
            "🚫 <b>Bu kanal allaqachon boshqa foydalanuvchiga ulangan.</b>\n\n"
            "O'g'irlab bo'lmaydi. Agar bu sizning kanalingiz bo'lsa, avval egasi "
            "botdan o'chirishi kerak."
        ),
        "ch_save_error": "❌ Kanalni saqlashda xatolik yuz berdi.",
        "ch_remove_not_found": "❌ Kanal topilmadi yoki sizga tegishli emas.",
        "ch_no_perm_dm": (
            "⚠️ <b>Bot administrator qilindi, lekin xabar yuborish "
            "ruxsati (Post Messages) berilmagan!</b>\n\n"
            "📢 Kanal: <b>{channel}</b>\n\n"
            "Iltimos, kanal sozlamalarida botga <b>Post Messages</b> "
            "huquqini yoqing — shundan so'ng kanal avtomatik ulanadi."
        ),
        "ch_autoconnect_success": (
            "🎉 <b>Siz botni {channel} kanaliga admin qildingiz va kanal ulandi!</b>\n\n"
            "🆔 <code>{channel_id}</code>\n\n"
            "Endi ushbu kanalga postlarni rejalashtirishingiz mumkin 👇"
        ),
        "ch_default_title": "Telegram Kanal",
        "ch_tone_title": (
            "🎭 <b>Kanal uslubini tanlang:</b>\n\n"
            "Joriy uslub: <b>{current}</b>\n\n"
            "Uslub postlarning ohangi va uslubini belgilaydi:"
        ),
        "ch_tone_formal": "👔 Rasmiy / Biznes",
        "ch_tone_friendly": "😊 Do'stona / Samimiy",
        "ch_tone_concise": "⚡️ Qisqa / Yangiliklar",
        "ch_tone_engaging": "🎉 Ko'ngilochar / Emotsional",
        "ch_tone_cancelled": "✅ Uslub o'zgartirish bekor qilindi.",
        "ch_tone_invalid": "❌ Noto'g'ri uslub. Iltimos, tugmalardan birini bosing.",
        "ch_tone_success": (
            "✅ <b>Kanal uslubi yangilandi!</b>\n\n"
            "🎭 Yangi uslub: <b>{tone}</b>\n\n"
            "Endi AI postlarni shu uslubda tayyorlaydi."
        ),
        "ch_tone_error": "❌ Uslubni saqlashda xatolik. Qaytadan urinib ko'ring.",
        "ch_voice_btn": "🎙 Kanal ovozi tahlili",
        "ch_voice_analyzing": (
            "🎙 <b>Kanal ovozi tahlil qilinmoqda...</b>\n\n"
            "AI kanaldagi so'nggi postlarni o'rganib, kanal uslubini aniqlaydi."
        ),
        "ch_voice_no_posts": (
            "⚠️ Tahlil uchun kanalda yetarli post topilmadi. "
            "Bot kanalda admin bo'lib postlar yozilgach, qaytadan urinib ko'ring."
        ),
        "ch_voice_result": (
            "🎙 <b>Kanal ovozi tahlili natijasi:</b>\n\n"
            "✅ Uslub: <b>{tone}</b>\n💬 {reason}\n\n"
            "Bu uslub kanal profilingizga saqlandi va keyingi AI generatsiyalarda ishlatiladi."
        ),
        "ch_voice_error": "⚠️ Kanal ovozi tahlilini bajarib bo'lmadi. Bir ozdan so'ng qayta urinib ko'ring.",

        # --- 3-QISM: 📅 Kutilayotgan postlar i18n (UZ) ---
        "pend_empty": "⏳ <b>Sizda kutilayotgan faol postlar mavjud emas.</b>",
        "pend_list_title": "⏳ <b>Kutilayotgan postlaringiz ({count} ta):</b>",
        "pend_item": (
            "🔹 <b>Post: {code}</b>\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "📦 Turi: <b>{type}</b>\n"
            "{time}\n\n"
        ),
        "pend_channel_fallback": "Kanal",
        "pend_edit_time_btn": "🕒 {code} vaqt",
        "pend_edit_content_btn": "✏️ {code} matn",
        "pend_edit_btn_btn": "🔗 Tugma",
        "pend_edit_react_btn": "👍 Reaksiya",
        "pend_cancel_btn": "❌ Bekor",
        "pend_refresh_btn": "🔄 Yangilash",
        "pend_close_btn": "❌ Yopish",
        "pend_refreshed": "✅ Yangilandi",
        "pend_refresh_fail": "Yangilab bo'lmadi",
        "pend_rate_limited": "⏳ Iltimos, biroz kuting...",
        "pend_error": "⚠️ Xatolik: {error}",
        "pend_not_found": "❌ Post topilmadi.",
        "pend_not_owned": "❌ Bu post sizga tegishli emas.",
        "pend_time_ask": (
            "🕒 <b>Post uchun yangi chiqish vaqtini yuboring:</b>\n\n"
            "• Bir martalik post bo'lsa: <code>DD.MM.YYYY HH:MM</code> "
            "(masalan <code>30.08.2026 20:00</code>)\n"
            "• Erkin format ham ishlaydi: <code>ertaga 18:00</code>, <code>bugun 10:00</code>\n"
            "• Har kunlik post bo'lsa faqat soat: <code>10:00</code>"
        ),
        "pend_time_success": "✅ <b>Post vaqti muvaffaqiyatli yangilandi!</b>",
        "pend_time_format": (
            "⚠️ <b>Vaqt formati tushunarsiz.</b>\n\n"
            "To'g'ri format: <code>DD.MM.YYYY HH:MM</code>\n"
            "Namuna: <code>{example}</code> yoki faqat soat — <code>18:00</code>\n\n"
            "🕒 <i>Toshkent vaqti (UTC+5).</i>"
        ),
        "pend_content_ask": (
            "✏️ <b>Post uchun yangi matnni yuboring:</b>\n\n"
            "HTML teglar (<b>bold</b>, <i>italic</i>, <code>code</code>) qo'llab-quvvatlanadi."
        ),
        "pend_content_success": "✅ <b>Post matni yangilandi!</b>",
        "pend_btn_ask": (
            "🔗 <b>Yangi tugma matnini yuboring:</b>\n\n"
            "Format: <code>Tugma matni | https://havola.uz</code>\n"
            "Tugmani o'chirish uchun: <code>yo'q</code> deb yozing."
        ),
        "pend_btn_removed": "✅ <b>Tugma o'chirildi!</b>",
        "pend_btn_updated": "✅ <b>Tugma yangilandi:</b> <code>{text}</code>",
        "pend_btn_format": (
            "⚠️ Format xato!\nMasalan: <code>Batafsil | https://sayt.uz</code>\n"
            "Yoki o'chirish: <code>yo'q</code>"
        ),
        "pend_react_ask": (
            "👍 <b>Post reaksiyalarini o'zgartirish:</b>\n\n"
            "Quyidagidan birini tanlang:"
        ),
        "pend_react_invalid": "⚠️ Tugmalardan birini tanlang:",
        "pend_react_off": "✅ <b>Reaksiyalar o'chirildi!</b>",
        "pend_react_updated": "✅ <b>Reaksiyalar yangilandi:</b> {emojis}",
        "pend_react_on": "✅ <b>Reaksiyalar yoqildi!</b>",
        "pend_update_fail": "❌ O'zgartirib bo'lmadi.",
        "pend_schedule_daily": "🔁 <b>Har kuni</b>, soat <b>{time}</b> da",
        "pend_schedule_weekly": "📅 <b>Har {day}</b>, soat <b>{time}</b> da",
        "pend_schedule_once": "⏰ Vaqti: <b>{time}</b>",
        "pend_schedule_unknown": "⏰ Vaqti: Noma'lum",

        # --- 3-QISM: ⏳ Navbat va slotlar i18n (UZ) ---
        "queue_db_error": (
            "📚 <b>Navbat (Queue)</b>\n\n"
            "⚠️ Rejalashtirilgan postlarni hozircha o'qib bo'lmadi "
            "(baza bilan aloqa xatosi).\n"
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        ),
        "queue_title": "📚 <b>Navbatdagi postlar</b> ({count} ta):",
        "queue_title_range": "📚 <b>Navbatdagi postlar</b> ({count} ta, {start}-{end}):",
        "queue_empty": (
            "📚 <b>Navbat (Queue)</b>\n\n"
            "Hozircha navbatda postlar yo'q.\n"
            "Yangi post yaratib, <b>⏳ Navbatga qo'shish</b> tugmasini bosing."
        ),
        "queue_empty_short": "📚 <b>Navbat (Queue)</b>\n\nNavbatda postlar yo'q.",
        "queue_limit_msg": (
            "🚫 <b>Navbat limiti tugadi!</b>\n\n"
            "Sizda <b>{current}/{max}</b> ta navbatdagi post bor.\n"
            "Free tarifida maksimal <b>{max}</b> ta post navbatda turishi mumkin.\n\n"
            "⭐️ Cheksiz navbat uchun PRO tarifiga o'ting."
        ),
        "queue_not_found": "⚠️ Post topilmadi yoki allaqachon o'chirilgan.",
        "queue_not_found_short": "⚠️ Post topilmadi!",
        "queue_no_slot": "⚠️ Bo'sh slot topilmadi!",
        "queue_deleted_alert": "🗑 O'chirildi!",
        "queue_view_title": "👁 <b>Post #{id}</b>",
        "queue_view_channel": "📢 Kanal: {channel}",
        "queue_view_type": "📦 Turi: {type}",
        "queue_view_time": "⏰ Vaqt: {time}",
        "queue_view_content": "📋 Matn:\n{content}",
        "queue_view_button": "🔘 Tugma: {text}",
        "queue_view_reactions": "👍 Reaksiyalar: Yoqilgan",
        "queue_view_auto_delete": "⏳ Auto-o'chirish: {hours} soat",
        "queue_btn_view": "👁 Ko'rish #{id}",
        "queue_btn_delete": "🗑 O'chirish",
        "queue_btn_push": "⏩ Surish",
        "queue_btn_prev": "⬅️ Oldingi",
        "queue_btn_next": "Keyingi ➡️",
        "queue_btn_slots": "⚙️ Slotlarni sozlash",
        "queue_btn_close": "❌ Yopish",
        "queue_btn_back": "⬅️ Ro'yxatga qaytish",
        "queue_btn_add_slot": "➕ Yangi slot qo'shish",
        "queue_btn_reset_slots": "🔄 Default slotlar",
        "queue_slots_title": (
            "⚙️ <b>Slot sozlamalari</b>\n\n"
            "Mavjud slotlar: <code>{slots}</code>\n\n"
            "Har kuni shu vaqtlarda postlar avtomatik rejalashtiriladi."
        ),
        "queue_slots_reset": (
            "⚙️ <b>Slot sozlamalari</b>\n\n"
            "Mavjud slotlar: <code>{slots}</code>\n\n"
            "Default slotlar qaytarildi."
        ),
        "queue_slot_add_ask": (
            "➕ <b>Yangi slot qo'shish</b>\n\n"
            "Vaqt formati: <code>HH:MM</code>\n"
            "Masalan: <code>22:00</code>"
        ),
        "queue_slot_added": (
            "✅ Slot qo'shildi: <code>{slot}</code>\n\n"
            "⚙️ <b>Slot sozlamalari</b>\n\n"
            "Mavjud slotlar: <code>{slots}</code>"
        ),
        "queue_slot_exists": "⚠️ <code>{slot}</code> allaqachon mavjud!",
        "queue_slot_max": "⚠️ Maksimal 10 ta slot qo'shish mumkin!",
        "queue_slot_format": (
            "⚠️ Noto'g'ri format! <code>HH:MM</code> shaklida yozing.\n"
            "Masalan: <code>22:00</code>"
        ),
        "queue_slot_min": "⚠️ Kamida bitta slot bo'lishi kerak!",
        "queue_slot_reset_alert": "🔄 Default slotlar qaytarildi!",
        "btn_pending": "⏳ Kutilayotgan postlar",
        "btn_queue": "📚 Navbat (Queue)",

        # --- 4-QISM: ⚙️ Qo'shimcha funksiyalar, 📖 Qo'llanma va tizim xabarlari (i18n) ---

        # ⚙️ Qo'shimcha funksiyalar — inline menyu matni va tugmalari
        "extras_menu_body": (
            "⚙️ <b>Qo'shimcha funksiyalar</b>\n\n"
            "✨ <b>Postga Tugma & Reaksiya qo'shish</b> — tayyor postni (matn, rasm, "
            "video, albom yoki forward) yuboring: asl matnga tegilmaydi, 10 tagacha "
            "reaksiya va 10 tagacha URL tugma qo'shib, istalgan kanalga bir zumda "
            "yuboriladi\n"
            "🔤 <b>Krill-Lotin konvertor</b> — matnlarni ikki alifbo orasida o'girish\n\n"
            "Kerakli vositani tanlang 👇"
        ),
        "extras_btn_enhancer": "✨ Postga Tugma & Reaksiya qo'shish",
        "extras_btn_converter": "🔤 Krill-Lotin konvertor",
        "extras_closed": "✅ <b>Qo'shimcha funksiyalar</b> bo'limi yopildi.",

        # 🔤 Lotin ⇄ Kirill matn konvertori oqimi
        "conv_intro": (
            "🔤 <b>Lotin ⇄ Kirill Matn O'girgich:</b>\n\n"
            "O'girmoqchi bo'lgan <b>matnni</b> yoki <b>rasm/video/fayl</b> (tagida yozuvi bilan) yuboring:\n\n"
            "<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>"
        ),
        "conv_no_text": (
            "⚠️ Ushbu fayl tagida hech qanday yozuv (matn) topilmadi.\n"
            "Iltimos, matn yuboring yoki fayl tagiga izoh yozib qaytadan yuboring:"
        ),
        "conv_received": (
            "📝 <b>Matn qabul qilindi!</b>\n\n"
            "Qaysi alifboga o'girmoqchisiz? Quyidagi tugmalardan birini tanlang 👇"
        ),
        "conv_btn_cyr": "🔤 Kirillcha nusxasi",
        "conv_btn_lat": "🔤 Lotincha nusxasi",
        "conv_no_saved_text": "⚠️ Matn topilmadi, iltimos qaytadan yuboring.",
        "conv_result_title": "📋 <b>Natija:</b>",
        "conv_result_part1": "📋 <b>Natija (1-qism):</b>",
        "conv_result_part2": "📋 <b>Natija (2-qism):</b>",
        "conv_copy_hint": "<i>(Nusxalash uchun matn ustiga bosing)</i>",
        "conv_cont_title": "ℹ️ <i>Matn davomi:</i>",
        "conv_error": "⚠️ Xatolik yuz berdi: {error}",
        "cab_converter_info": (
            "🔤 <b>Krill-Lotin konverter:</b>\n\n"
            "Lotin yoki Kirill matn yuboring — men uni avtomatik o'girib beraman.\n\n"
            "<i>Masalan: Salom dunyo → Салом дунё</i>"
        ),

        # ✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer)
        "enh_notice_admin": (
            "💡 <b>Eslatma:</b> Bot postni kanalingizga joylashi uchun avval uni "
            "kanalingizga <b>Admin</b> qilib qo'shganingizga ishonch hosil qiling."
        ),
        "enh_post_request": (
            "Kanalga joylamoqchi bo'lgan postingizni yuboring "
            "(Matn, Rasm, Video yoki boshqa kanaldan Forward):"
        ),
        "enh_intro_features": (
            "✅ Asl matnga tegilmaydi — faqat:\n"
            "• 👍 10 tagacha reaksiya (probel bilan batch kiritish mumkin),\n"
            "• 🔗 10 tagacha URL tugma (tayyor shablonlar bilan),\n"
            "• 👁 so'ralganda prevyu va 🚀 kanalga bir zumda yuborish."
        ),
        "enh_preset1_title": "Kanalga a'zo bo'lish",
        "enh_preset1_text": "📢 Kanalga a'zo bo'lish",
        "enh_preset2_title": "Guruhga qo'shilish",
        "enh_preset2_text": "💬 Guruhga qo'shilish",
        "enh_preset3_title": "Botga o'tish",
        "enh_preset3_text": "🤖 Botga o'tish",
        "enh_summary": (
            "👍 Reaksiyalar: <b>{rn}/{maxr}</b>{emojis}\n"
            "🔗 URL tugmalar: <b>{bn}/{maxb}</b>"
        ),
        "enh_post_line_type": "📦 <b>Turi:</b> {type}",
        "enh_post_line_album_count": " ({n} ta media)",
        "enh_post_line_text": "\n📝 <b>Matn:</b> <i>{preview}</i>",
        "enh_post_line_no_text": "\n📝 <b>Matn:</b> <i>(yozuv yo'q — faqat media)</i>",
        "enh_hub_title": (
            "✨ <b>Postga Tugma & Reaksiya qo'shish</b>\n\n"
            "{post}\n\n"
            "{summary}\n"
            "{note}"
            "{notice}\n\n"
            "Kerakli qadamni tanlang 👇"
        ),
        "enh_hub_btn_reacts": "👍 1. Reaksiyalar ({n}/{max})",
        "enh_hub_btn_buttons": "🔗 2. URL tugmalar ({n}/{max})",
        "enh_btn_preview": "👁️ Prevyu",
        "enh_btn_send_channel": "🚀 Kanalga yuborish",
        "enh_btn_replace": "🔁 Postni almashtirish",
        "enh_react_title": (
            "👍 <b>1-qadam. Reaksiyalar</b> (<b>{n}/{max}</b>)\n\n"
            "Tanlangan: {sel}\n\n"
            "• Emoji tugmasini bosing — ✅ belgilanadi, qayta bossangiz olib tashlanadi;\n"
            "• Yoki bir nechta emojini <b>probel bilan</b> bir xabarda yuboring "
            "(masalan: <code>👍 ❤️ 🔥 👏 🎉</code>);\n"
            "• Yana <b>{left}</b> ta reaksiya qo'shsa bo'ladi.\n\n"
            "<i>Post faqat yakuniy prevyu/tasdiqlash bosqichida ko'rsatiladi.</i>"
        ),
        "enh_react_none": "— (hech narsa tanlanmagan)",
        "enh_react_done": "➡️ Davom etish / URL tugmaga o'tish",
        "enh_react_done_count": "➡️ Davom etish / URL tugmaga o'tish ({n})",
        "enh_btn_clear": "🗑 Tozalash",
        "enh_btns_title": (
            "🔗 <b>2-qadam. URL tugmalar</b> (<b>{n}/{max}</b>)\n\n"
            "{body}\n\n"
            "Tayyor shablonni tanlang — bot faqat havolani so'raydi.\n"
            "Qo'lda kiritish: <code>Tugma nomi - https://havola.uz</code> yoki "
            "<code>Tugma nomi | @kanalim</code>"
        ),
        "enh_btns_empty": "<i>Hozircha tugmalar yo'q — shablon tanlang yoki qo'lda kiriting.</i>",
        "enh_btns_line": "{mark} <b>{text}</b> → <code>{url}</code>",
        "enh_btn_fallback": "Tugma",
        "enh_btn_add_new": "➕ Yangi tugma qo'shish",
        "enh_btn_manual": "✍️ Qo'lda kiritish",
        "enh_btn_confirm_send": "➡️ Tasdiqlash va Kanalga yuborish",
        "enh_btn_entry_edit": "✏️ {num}. {text}",
        "enh_btn_add_title": (
            "➕ <b>Yangi URL tugma</b> (<b>{n}/{max}</b>)\n\n"
            "Tayyor shablonlardan birini tanlang — bot <b>faqat havolani</b> so'raydi.\n\n"
            "Yoki <b>✍️ Qo'lda kiritish</b> orqali bir qatorda yuboring:\n"
            "<code>Tugma nomi - https://havola.uz</code>\n"
            "<code>Tugma nomi | @kanalim</code>"
        ),
        "enh_channel_title": (
            "📢 <b>Qaysi kanalga yuborilsin?</b> ({n} ta)\n\n"
            "<i>Post tanlangan kanalga to'g'ridan-to'g'ri chiqadi "
            "(rejalashtirishsiz). Oxirida tasdiq so'raladi.</i>\n\n"
            "{notice}"
        ),
        "enh_channel_fallback": "Kanal",
        "enh_channels_more": "…va yana {n} ta (kanal qo'shish bo'limi orqali tanlang)",
        "enh_confirm_no_channel": "⚠️ <b>Kanal tanlanmagan.</b>\n\nRo'yxatdan kanalni tanlang.",
        "enh_btn_channel_list": "📢 Kanallar ro'yxati",
        "enh_confirm_title": (
            "📢 <b>Yuborishni tasdiqlang</b>\n\n"
            "Ushbu post <b>{channel}</b>ga yuborilsinmi?\n\n"
            "{post}\n\n"
            "{summary}\n"
            "{note}"
            "\n<i>Yuborilgandan keyin postni o'zgartirib bo'lmaydi.</i>"
        ),
        "enh_btn_confirm_yes": "✅ Ha, yuborilsin",
        "enh_btn_preview_first": "👁️ Avval prevyu",
        "enh_success_text": (
            "✅ <b>Post yuklandi!</b>\n"
            "Post kanalingizga muvaffaqiyatli joylandi!{where}\n\n"
            "Xohlasangiz shu postni boshqa kanalga ham yuborishingiz yoki yangi "
            "post kuchaytirishingiz mumkin 👇"
        ),
        "enh_success_where": "\n📢 <b>Kanal:</b> {channel}",
        "enh_btn_home": "🏠 Asosiy menyu",
        "enh_btn_other_channel": "📢 Boshqa kanalga",
        "enh_btn_new_post": "🚀 Yangi post",
        "enh_btn_finish": "❌ Tugatish",
        "enh_note_admin": "👑 <i>Admin — post toza chiqadi.</i>\n",
        "enh_note_pro": "✨ <i>PRO — via/watermark qo'shilmaydi, post toza chiqadi.</i>\n",
        "enh_note_free": "🆓 <i>Bepul reja: kanalga yuborilganda post boshiga {bot} qo'shiladi.</i>\n",
        "enh_use_buttons": (
            "👇 <b>Postni kuchaytirish uchun pastdagi tugmalardan birini tanlang.</b>\n"
            "Postni almashtirmoqchimisiz — <b>🔁 Postni almashtirish</b> tugmasini bosing."
        ),
        "enh_album_reject": "⚠️ Bu turdagi media albomga qo'shib bo'lmaydi — yakka yuboring:",
        "enh_empty_msg": "⚠️ Bo'sh xabar qabul qilinmadi. Post matnini yoki mediani yuboring:",
        "enh_react_saved": "✅ <b>Reaksiyalar saqlandi:</b> {sel}\nJami: <b>{total}/{max}</b>{extra}",
        "enh_react_overflow_part": "\n⚠️ Chegara <b>{max}</b> ta — {items} sig'madi.",
        "enh_react_dups_part": "\nℹ️ Takrorlangan emojilar hisobga olinmadi.",
        "enh_react_dups": "ℹ️ Bu emojilar allaqachon tanlangan: {items}\nJami: <b>{total}/{max}</b>",
        "enh_react_full": (
            "⚠️ <b>Reaksiyalar chegarasi to'ldi</b> (maks. {max} ta). "
            "Avval birortasini olib tashlang."
        ),
        "enh_react_hint_msg": (
            "ℹ️ Faqat <b>emoji</b> yuboring — bir nechta bo'lsa <b>probel bilan</b> "
            "(masalan: <code>👍 ❤️ 🔥 👏 🎉</code>) yoki pastdagi tugmalardan foydalaning."
        ),
        "enh_bad_link": (
            "⚠️ <b>Havola noto'g'ri.</b>\n\n"
            "Faqat havolani yuboring, masalan: <code>{hint}</code>\n"
            "yoki <code>@kanal_ismi</code>"
        ),
        "enh_bad_format": (
            "⚠️ <b>Tugma formati noto'g'ri.</b>\n\n"
            "Qaytadan yuboring:\n"
            "<code>Saytga o'tish - https://sayt.uz</code>\n"
            "<code>Kanalim | @kanalim</code>\n"
            "<code>https://t.me/bot_ism/start</code> (yozuv avtomatik tanlanadi)"
        ),
        "enh_btn_limit_reached": (
            "⚠️ <b>Maksimum {max} ta URL tugma</b> qo'shish mumkin. "
            "Avval bittasini o'chiring."
        ),
        "enh_btn_verb_saved": "saqlandi",
        "enh_btn_verb_updated": "yangilandi",
        "enh_btn_saved": "✅ <b>Tugma {verb}:</b> {text} → <code>{url}</code>",
        "enh_session_expired": "⚠️ Sessiya tugagan — menyuni qaytadan oching.",
        "enh_home_msg": "🏠 <b>Asosiy menyu</b> — kerakli bo'limni tanlang 👇",
        "enh_again_prompt": (
            "{notice}\n\n"
            "🚀 <b>Yangi post</b> — kuchaytirmoqchi bo'lgan postingizni yuboring "
            "(matn, rasm, video, albom yoki forward):"
        ),
        "enh_no_channels_alert": (
            "⚠️ Ulangan kanal yo'q — avval kanal ulang va botni "
            "kanalga Admin qilib qo'shing."
        ),
        "enh_react_limit_alert": "⚠️ Maksimum {max} ta reaksiya!",
        "enh_replace_prompt": (
            "🔁 <b>Yangi postni yuboring</b> — joriy post (matn/media) almashtiriladi. "
            "Reaksiyalar va tugmalar saqlanadi 👇"
        ),
        "enh_channel_gone_alert": "⚠️ Bu kanal endi ro'yxatda yo'q.",
        "enh_preset_missing": "⚠️ Shablon topilmadi.",
        "enh_btn_limit_alert": "⚠️ Maksimum {max} ta tugma!",
        "enh_preset_prompt": (
            "{icon} <b>{num}. {title}</b>\n\n"
            "Faqat <b>havolani</b> yuboring (masalan: <code>{hint}</code>) — "
            "tugma yozuvi avtomatik qo'yiladi.\n\n"
            "<i>To'liq formatda ham mumkin: <code>Yozuv - https://havola.uz</code></i>"
        ),
        "enh_btn_back_cancel": "⬅️ Bekor qilish",
        "enh_manual_prompt": (
            "✍️ <b>Yangi URL tugma (qo'lda kiritish)</b>\n\n"
            "Bir qatorda yuboring:\n"
            "<code>Tugma nomi - https://havola.uz</code>\n"
            "<code>Tugma nomi | @kanalim</code>\n"
            "<code>Botim - t.me/bot_ismi/start</code>"
        ),
        "enh_btn_missing_alert": "⚠️ Tugma topilmadi.",
        "enh_edit_prompt": (
            "✏️ <b>{num}-tugmani tahrirlash</b>\n\n"
            "Hozir: <b>{text}</b> → <code>{url}</code>\n\n"
            "Yangi qiymatni bir qatorda yuboring:\n"
            "<code>Yangi yozuv - https://yangi-havola.uz</code>"
        ),
        "enh_preview_follow_note": (
            "👆 <i>Yuqorida — prevyu. Tugmalar kanalda shu post ostida chiqadi.</i>"
        ),
        "enh_preview_failed": "⚠️ Prevyu yasab bo'lmadi (media fayli yaroqsiz).",
        "enh_preview_error": "⚠️ Prevyu ko'rsatib bo'lmadi.",
        "enh_too_fast": "⏳ Juda tez — birozdan so'ng qayta urinib ko'ring.",
        "enh_no_channel_sel": "⚠️ Kanal tanlanmagan.",
        "enh_channel_not_owned": "⚠️ Bu kanal endi sizning ro'yxatingizda yo'q.",
        "enh_prepare_failed": "⚠️ Postni tayyorlab bo'lmadi. Qaytadan urinib ko'ring.",
        "enh_send_no_rights": (
            "⚠️ Bot kanalda admin emas (yoki ruxsati yo'q). "
            "Kanalga admin qilib qo'shing."
        ),
        "enh_send_failed": "⚠️ Yuborib bo'lmadi: {error}",
        "enh_stale_notice": (
            "⚠️ Bu menyuning muddati tugagan — ⚙️ Qo'shimcha funksiyalarni qaytadan oching."
        ),

        # 📖 Qo'llanma / Bot haqida (/help)
        "help_guide": (
            "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
            "🔹 <b>1. Kanal/Guruh ulash:</b>\n"
            "• Botni kanalingizga <b>administrator</b> qilib (xabar yuborish ruxsati bilan) qo'shing.\n"
            "• «👤 Kabinet & Sozlamalar» → «📢 Mening kanallarim» orqali kanaldan istalgan xabarni botga forward qiling yoki @username yuboring.\n\n"
            "🔹 <b>2. Yangi post rejalashtirish:</b>\n"
            "• Matn, rasm, video, audio yoki <b>albom</b> (bir nechta rasm/video) postlarni istalgan sanaga rejalashtirish.\n"
            "• Havola tugmalar (URL button), reaksiyalar va avto-o'chirish (12, 24, 48, 72 soat).\n"
            "• <i>PRO tarifda postlar avtomatik reklamasiz (100% toza) chiqadi!</i>\n\n"
            "🔹 <b>3. ✨ AI Studio:</b>\n"
            "• AI Post yaratish, rasmdan post (Vision), AI post auditi va kontent-reja.\n"
            "• Savol bering yoki matn/rasm/forward yuboring — professional post va she'rlar tayyorlanadi.\n"
            "• Erkin tilda buyruq: <i>«ertaga ertalab 9 ga hamma kanalga rejalashtir»</i>.\n"
            "• Postni tahrirlash: <i>«oxiriga telefon raqam qo'sh»</i>.\n\n"
            "🔹 <b>4. Ballar va Kunlik Seriya (Streak):</b>\n"
            "• Har kuni botga kiring va <b>'🎁 Kunlik bonus'</b> tugmasini bosing.\n"
            "• 1-kun (+1), 2-kun (+1), 3-kun (+2), ..., 7-kun (+4 ball) olasiz!\n\n"
            "🔹 <b>5. ⚙️ Qo'shimcha funksiyalar:</b>\n"
            "• ✨ Postga Tugma & Reaksiya qo'shish — tayyor postni bir zumda kuchaytirish.\n"
            "• 🔤 Lotin ⇄ Kirill matn o'girgich.\n\n"
            "⚙️ <b>Tezkor buyruqlar:</b>\n"
            "/start — Bosh menyu\n"
            "/newpost — Yangi post\n"
            "/profile — Kabinet\n"
            "/help — Qo'llanma\n"
            "/cancel — Bekor qilish\n\n"
            "{support}"
        ),
        "help_guide_admin": (
            "\n\n👑 <b>Admin buyruqlari:</b>\n"
            "/admin — Boshqaruv paneli\n"
            "/broadcast — Xabar yuborish\n"
            "/stats — Statistika"
        ),
        "help_faq": (
            "❓ <b>Tez-tez beriladigan savollar (FAQ)</b>\n\n"
            "<b>1. Postim kanalga chiqmadi — nima qilaman?</b>\n"
            "Bot kanal/guruhingizda <b>administrator</b> va «xabar yuborish» huquqiga ega ekanini tekshiring — "
            "keyin uni «📢 Mening kanallarim» ro'yxatiga ulang.\n\n"
            "<b>2. AI so'rovlar (ballar) qanday olinadi?</b>\n"
            "Har kuni «🎁 Kunlik bonus» tugmasini bosing, do'stlaringizni taklif qiling "
            "(1–3-do'st: +3, keyingilar: +1) yoki ⭐️ PRO tarifga o'ting — PRO'da AI cheksiz.\n\n"
            "<b>3. Rejalashtirilgan postni tahrirlash mumkinmi?</b>\n"
            "Ha — «👤 Kabinet & Sozlamalar» → «📅 Kutilayotgan postlar» bo'limida vaqt, matn, "
            "tugma va reaksiyalarni alohida o'zgartirasiz.\n\n"
            "<b>4. Reklama qanday o'chadi?</b>\n"
            "⭐️ PRO tarif postlarni va bot javoblarini 100% reklamasiz qiladi (belgi avtomatik o'chadi).\n\n"
            "<b>5. Bot qaysi tillarda ishlaydi?</b>\n"
            "O'zbek va rus tillarida. Tilni «👤 Kabinet & Sozlamalar» → «🌐 Til / Язык» orqali almashtirasiz.\n\n"
            "{support}"
        ),
        "help_btn_faq": "❓ Tez-tez beriladigan savollar",
        "help_btn_support": "💬 Bog'lanish",
        "help_support_line": "👨‍💻 <b>Yordam kerakmi?</b> {admin} bilan bog'laning.",
        "help_admin_fallback": "bot administratori",
        "cab_guide_text": (
            "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
            "🔹 <b>1. Yangi post rejalashtirish:</b>\n"
            "• Matn, rasm, video, audio yoki <b>albom</b> postlarni istalgan sanaga rejalashtirish.\n"
            "• Havola tugmalar, reaksiyalar va avto-o'chirish.\n\n"
            "🔹 <b>2. AI Yordamchi:</b>\n"
            "• Savol bering yoki matn/rasm yuboring — professional post tayyorlaydi.\n"
            "• Erkin tilda: <i>\"ertaga ertalab 9 ga hamma kanalga\"</i>.\n\n"
            "🔹 <b>3. Ballar va Kunlik Seriya:</b>\n"
            "• Har kuni botga kiring va bonus oling (7-kunda +4 ball).\n\n"
            "⚙️ <b>Tezkor buyruqlar:</b>\n"
            "/start — Bosh menyu\n"
            "/profile — Kabinet\n"
            "/help — Qo'llanma\n"
            "/cancel — Bekor qilish"
        ),

        # ⚠️ Xatoliklar va tizimli xabarlar
        "sys_busy": (
            "⚠️ <b>Tizim vaqtincha band.</b>\n"
            "Iltimos, birozdan so'ng /start bosing."
        ),
        "sys_stale_button": (
            "♻️ Bu tugma eskirgan (bot qayta ishga tushirilgan). "
            "Menyuni qaytadan oching: /start"
        ),
        "sys_unexpected_error": (
            "⚠️ <b>Kutilmagan xatolik yuz berdi.</b>\n"
            "Iltimos, birozdan so'ng qayta urinib ko'ring yoki /start bosing."
        ),
        # 🌐 Qisqa toast-xabarlar — callback throttle/rate-limit va eskirgan
        # menyu fallbacklari uchun (avval qotirib yozilgan o'zbekcha edi).
        "sys_error_short": "⚠️ Xatolik yuz berdi",
        "sys_wait_short": "⏳ Iltimos, kuting...",
        "admin_only_cmd": "❌ Bu buyruqni faqat admin ishlata oladi.",
        "np_callback_wait": "⏳ Jarayon bajarilmoqda, iltimos kuting...",
        "noop_channel_info": (
            "Bu ma'lumot tugmasi. Kanalni o'chirish uchun yonidagi "
            "❌ tugmasini bosing."
        ),
        "ai_menu_stale": (
            "⚠️ <b>Bu menyu eskirgan.</b>\n"
            "Davom etish uchun ✨ AI Studio tugmasini qaytadan bosing."
        ),
        "ai_photo_stale": (
            "⚠️ <b>Bu menyu eskirgan.</b>\n"
            "Rasmdan post yaratish uchun ✨ AI Studio → 🖼 Rasmdan post "
            "yaratish bo'limini qaytadan tanlang."
        ),
        "conv_timeout_msg": (
            "⏰ <b>Suhbat muddat tugash sababli yakunlandi.</b>\n"
            "Asosiy menyuga qaytdingiz. Kerakli bo'limni qaytadan tanlang 👇"
        ),
        "msg_closed": "✅ Yopildi.",

        # 🩺 7-BOSQICH: Tizim holati monitoringi (/health — faqat adminlar)
        "health_title": "🩺 <b>TIZIM HOLATI (System Health)</b>",
        "health_overall": "📊 <b>Umumiy holat:</b>",
        "health_checked_at": "🕐 Tekshirildi: {time} (UTC)",
        "health_uptime": "⏱ Ishga tushganiga: {uptime}",
        "health_db_title": "🗄 <b>Ma'lumotlar bazasi:</b> {status}",
        "health_db_latency": "• Neon DB javob vaqti: {latency} ms",
        "health_db_error": "• Xato: {error}",
        "health_db_pool": "• Ulanishlar pool'i: {used}/{max} band ({available} bo'sh)",
        "health_scheduler_title": "⏰ <b>Scheduler (apscheduler):</b> {status}",
        "health_sched_jobs": "• Faol vazifalar: {count}",
        "health_posts_pending": "• ⏳ Kutilayotgan postlar: {count}",
        "health_posts_failed": "• ⚠️ Xatolikli postlar: {count}",
        "health_posts_dead": "• ☠️ Dead-letter postlar: {count}",
        "health_posts_stale": "• 🧊 Qotib qolgan (stale) postlar: {count}",
        "health_ai_title": "🤖 <b>AI provayderlar:</b> {status}",
        "health_ai_provider": "• {name}: {status}",
        "health_system_title": "🖥 <b>Tizim resurslari:</b>",
        "health_errors": "• Xatolar — oxirgi 1 soat: {hour} | 24 soat: {day}",
        "health_tasks": "• Faol asyncio vazifalari: {count}",

        "cancel_done": (
            "🚫 <b>Jarayon bekor qilindi.</b>\n"
            "Asosiy menyuga qaytdingiz. Kerakli bo'limni tanlang 👇"
        ),
        "main_menu_hint": "Quyidagi menyudan kerakli bo‘limni tanlang 👇",
        # Kutilmagan / notanish xabar (dialogdan tashqarida matn, voice, kontakt,
        # fayl...) — bot jim qolmaydi: xushmuomala xabar + asosiy menyu.
        "unknown_message_fallback": (
            "Kechirasiz, men bu xabarni tushunmadim. "
            "Iltimos, quyidagi menyudan kerakli bo‘limni tanlang 👇"
        ),
        # Dialog ICHIDA joriy bosqich qabul qilmaydigan xabar turi kelsa
        "unknown_in_dialog": (
            "⚠️ Bu turdagi xabar hozirgi bosqichda qabul qilinmaydi. "
            "Iltimos, so‘ralgan ma’lumotni yuboring yoki 🔙 Asosiy menyu tugmasini bosing."
        ),
        # Post tayyorlash bosqichida stiker yuborilsa
        "np_sticker_not_allowed": (
            "Kechirasiz, stikerlar post sifatida qabul qilinmaydi. "
            "Iltimos, rasm, video yoki matn yuboring"
        ),
        # Majburiy homiy-kanal obunasi (start / obuna tekshiruvi)
        "sub_required": (
            "⚠️ <b>Botdan to'liq foydalanish uchun quyidagi rasmiy kanallarga "
            "a'zo bo'ling:</b>"
        ),
        "sub_confirmed": (
            "✅ Obuna tasdiqlandi!\n\n"
            "Xush kelibsiz, <b>{name}</b>! Barcha imkoniyatlar siz uchun ochiq.\n\n"
            "{hint}"
        ),
        "sub_not_yet_alert": (
            "⚠️ Hali barcha kanallarga a'zo bo'lmadingiz! "
            "Iltimos, barcha kanallarga a'zo bo'ling."
        ),
        "sub_not_yet_msg": (
            "⚠️ Hali barcha kanallarga a'zo bo'lmadingiz! "
            "Pastdagi tugmalar orqali obuna bo'ling."
        ),

        # Vaqt mintaqasi tanlash (Timezone)
        "tz_prompt": "🌍 <b>Vaqt mintaqangizni tanlang:</b>",
        "tz_changed": "✅ Vaqt mintaqasi <b>{tz}</b> ga o'zgartirildi.",
        "tz_btn_tashkent": "🇺🇿 Toshkent (UTC+5)",
        "tz_btn_moscow": "🇷🇺 Moskva (UTC+3)",
        "tz_btn_utc": "🌐 UTC (UTC+0)",
        "tz_btn_samarkand": "🇺🇿 Samarqand (UTC+5)",
        "tz_current": "🌍 Vaqt mintaqasi: <b>{tz}</b>",

        # --- Umumiy operatsiyalar ---
        "op_cancelled": "❌ Bekor qilindi.",
        "btn_share_referral": "🚀 Do'stlarga ulashish",
        "btn_check_subscription": "✅ Obunani tekshirish",
        "ref_share_text": "Salom! Ushbu bot orqali Telegram kanallaringizga postlarni avtomatik va qulay rejalashtiring:",
        "sub_sponsor_fallback": "Homiy kanal",
        "pr_no_permission": "❌ Sizda to'lovni tasdiqlash uchun ruxsat yo'q.",
        "pr_error": "❌ Xatolik yuz berdi.",

        # --- AI yordamchi (legacy AI_INPUT oqimi) ---
        "ai_analyzing": "🤖 <i>AI tahlil qilmoqda...</i>",
        "ai_legacy_welcome": (
            "🤖 <b>AI Yordamchiga xush kelibsiz!</b>\n\n"
            "💎 Mavjud AI so'rovlari: {credits}\n\n"
            "Men sizga quyidagi ishlarda yordam bera olaman:\n"
            "❓ <b>Savol-javob</b> — bot, postlar, ballar, kanallar haqida savol bering.\n"
            "📝 <b>Post yaratish</b> — post mavzusini yozing yoki tayyor post/rasm yuboring.\n"
            "🕒 <b>Erkin rejalashtirish</b> — masalan: <i>“bugun 15:45 ga hamma kanalga post tayyorla”</i>.\n\n"
            "👉 Post mavzusini yoki savolingizni yozing.\n"
            "<i>Chiqish uchun '{main_menu}' tugmasini bosing.</i>"
        ),
        "ai_legacy_media_hint": (
            "🖼 <b>Rasm/media qabul qilindi!</b>\n\n"
            "Endi post matnini yuboring yoki vaqtni yozing, masalan: <i>“bugun 18:00 ga”</i>."
        ),
        "ai_legacy_input_hint": "Iltimos, post matnini, savolingizni yoki rasm/fayl yuboring:",
        "ai_legacy_faq_fallback": (
            "Kechirasiz, men faqat Telegram kanallarni boshqarish va postlarni "
            "rejalashtirish bo'yicha yordam bera olaman."
        ),
        "ai_legacy_faq_footer": "\n\n<i>Yana savol bering yoki post mavzusini yuboring 👇</i>",
        "ai_legacy_no_post": "Post matnini aniqlab bo'lmadi. Iltimos, qaytadan yuboring.",
        "ai_legacy_target_all": "\n🌐 <b>Kanal:</b> Barcha ulangan kanallarga",

        # --- Ochiq kanaldan post olish (extract) ---
        "ext_intro": (
            "📢 <b>Ochiq kanaldan post olish</b>\n\n"
            "Kanal nikini YOKI havolasini yuboring:\n"
            "• <code>@kunuzofficial</code>\n"
            "• <code>https://t.me/kunuzofficial</code>\n\n"
            "Yoki sayt havolasini yuboring (masalan: <code>https://kun.uz/</code>) — "
            "bot sahifani o'qib, AI tahlilini tayyorlaydi.\n\n"
            "<i>Faqat ochiq kanallar uchun ishlaydi.</i>"
        ),
        "ext_btn_other_post": "🔙 Boshqa post tanlash",
        "ext_btn_rewrite": "🔄 Qayta yozish",
        "ext_btn_refresh": "🔄 Yangilash",
        "ext_media_preview": "🖼 Rasm/Video",
        "ext_reading_site": "⏳ Sayt o'qilmoqda...",
        "ext_site_read_failed": "⚠️ Saytdan matn o'qib bo'lmadi. Manzilni tekshirib, qayta yuboring.",
        "ext_ai_analyzing_page": "⏳ AI sahifani tahlil qilmoqda...",
        "ext_ai_page_failed": "⚠️ AI sahifani qayta ishlolmadi.",
        "ext_ai_proposal_src": "✨ <b>AI taklifi ({src}):</b>\n\n{text}",
        "ext_ai_proposal": "✨ <b>AI taklifi:</b>\n\n{text}",
        "ext_reading_posts": "⏳ Kanal postlari o'qilmoqda...",
        "ext_post_accepted": (
            "✅ <b>Post qabul qilindi!</b>\n\n"
            "Endi tugma, vaqt va boshqa sozlamalarni kiriting."
        ),
        "ext_private_channel_full": (
            "🔒 <b>Bu yopiq kanal.</b>\n\n"
            "Ochiq kanallarni yoki o'zingiz admin bo'lgan kanallarni yuboring.\n"
            "Masalan: <code>@kunuzofficial</code> yoki "
            "<code>https://t.me/kunuzofficial</code>"
        ),
        "ext_private_channel": (
            "🔒 Bu yopiq kanal. Ochiq kanallarni yoki o'zingiz admin "
            "bo'lgan kanallarni yuboring."
        ),
        "ext_not_found": (
            "❌ <b>{text}</b> — bunday kanal topilmadi.\n\n"
            "Manzilni tekshirib, qayta yuboring:\n"
            "<code>@kanal</code> yoki <code>https://t.me/kanal</code>"
        ),
        "ext_invalid_username": (
            "⚠️ Noto'g'ri kanal niki yoki havolasi. Qaytadan kiriting:\n"
            "<code>@kanal</code>, <code>kanal</code> yoki <code>https://t.me/kanal</code>\n\n"
            "Yoki sayt havolasi: <code>https://kun.uz/</code>"
        ),
        "ext_empty": (
            "📭 <b>{channel}</b> kanalida postlar topilmadi.\n\n"
            "Boshqa kanal yoki sayt havolasini yuboring:"
        ),
        "ext_read_failed": (
            "❌ <b>{channel}</b> kanalidan postlar o'qilmadi.\n\n"
            "Sabablari:\n"
            "• Kanal yopiq (private)\n"
            "• Kanal niki noto'g'ri\n"
            "• Kanalda postlar yo'q\n\n"
            "Qaytadan urinib ko'ring:"
        ),
        "ext_list_header": "📢 <b>@{channel}</b> — so'nggi postlar:\n",
        "ext_list_choose": "Qaysi postni qayta ishlashni tanlang 👇",
        "ext_media_only": "(rasm/video)",
        "ext_no_list": "⚠️ Postlar ro'yxati mavjud emas. Yangi kanal yoki sayt havolasini yuboring:",
        "ext_no_posts": "⚠️ Postlar topilmadi.",
        "ext_invalid_post": "❌ Noto'g'ri post tanlandi.",
        "ext_post_no_text": "⚠️ Bu postda matn yo'q (faqat rasm/video). Boshqa postni tanlang.",
        "ext_ai_rewriting": "⏳ AI postni qayta yozmoqda...",
        "ext_ai_rewrite_failed": "⚠️ AI postni qayta yozolmadi.",
        "ext_no_post_text": "⚠️ Post matni topilmadi.",
        "ext_refreshing": "🔄 Yangilanmoqda...",
        "ext_rewriting": "🔄 Qayta yozilmoqda...",

        # --- Kontent reja (content plan) ---
        "cp_btn_create_post": "📝 Post yaratish",
        "cp_btn_regenerate": "🔄 Qayta generatsiya",
        "cp_btn_back": "🔙 Orqaga",
        "cp_btn_create_on_topic": "📝 Shu mavzuda post yaratish",
        "cp_no_channel": (
            "⚠️ <b>Avval kanal ulang.</b>\n\n"
            "Kontent-reja tuzish uchun kamida bitta kanal bo'lishi kerak.\n"
            "📢 Kanallar bo'limidan kanal ulang."
        ),
        "cp_choose_channel": (
            "🧠 <b>Kontent-reja generatori</b>\n\n"
            "Qaysi kanal uchun kontent-reja tuzamiz?"
        ),
        "cp_back_title": "🧠 <b>Qaysi kanal uchun kontent-reja tuzamiz?</b>",
        "cp_closed": "❌ Yopildi.",
        "cp_topic_ask": (
            "🧠 <b>Kontent-reja: {channel}</b>\n\n"
            "Kanal mavzusini qisqacha yozing.\n\n"
            "<i>Masalan:</i>\n"
            "• Ingliz tili noldan\n"
            "• Oshxona buyumlari do'koni\n"
            "• Sog'lom turmush tarzi\n"
            "• IT yangiliklar"
        ),
        "cp_topic_short": "⚠️ Mavzu juda qisqa. Kamida 3 ta belgi yozing.",
        "cp_ai_building": "⏳ AI kontent-reja tuzmoqda...",
        "cp_ai_failed": "⚠️ AI reja tuza olmadi.",
        "cp_ai_failed_retry": "⚠️ AI reja tuza olmadi. Qaytadan urinib ko'ring.",
        "cp_plan_header": (
            "🧠 <b>7 kunlik kontent-reja</b>\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "📝 Mavzu: <i>{topic}</i>\n\n"
        ),
        "cp_plan_header_new": (
            "🧠 <b>7 kunlik kontent-reja (yangi)</b>\n"
            "📢 Kanal: <b>{channel}</b>\n"
            "📝 Mavzu: <i>{topic}</i>\n\n"
        ),
        "cp_plan_day": "<b>📅 {day}</b> — {fmt}\n  📌 <b>{title}</b>\n",
        "cp_plan_idea": "  <i>{idea}</i>\n",
        "cp_day_fallback": "Kun {n}",
        "cp_plan_footer": "\n\nKunni tanlab, to'g'ridan-to'g'ri post yarating 👇",
        "cp_regenerating": "🔄 Qayta generatsiya...",
        "cp_invalid_day": "❌ Noto'g'ri kun tanlandi.",
        "cp_day_detail": "📅 <b>{day}</b> — {fmt}\n\n📌 <b>{title}</b>\n\n{idea}\n\n{ask}",
        "cp_day_ask": "Shu mavzuda post yaratishni xohlaysizmi?",
        "cp_choose_day": "📅 <b>Qaysi kun uchun post yaratamiz?</b>",
        "cp_ai_writing": "⏳ AI post matnini tayyorlamoqda...",
        "cp_ai_write_failed": "⚠️ AI post matni tayyorlay olmadi.",
        "cp_post_ready": (
            "✅ <b>Tayyor post:</b>\n\n{preview}\n\n"
            "📢 Kanal: <b>{channel}</b>\n\n"
            "Endi tugma, vaqt va boshqa sozlamalarni kiriting."
        ),
        "cp_button_ask": (
            "🔘 <b>Tugma qo'shasizmi?</b>\n\n"
            "Tugma matni va URL ni yozing:\n"
            "<code>Matn | https://havola.uz</code>\n\n"
            "Yoki tugmasiz davom eting 👇"
        ),

        # --- Obuna / to'lov (subscription) ---
        "sub_pay_1m": "⭐️ 1 oy (75 Stars)",
        "sub_pay_3m": "⭐️ 3 oy (175 Stars)",
        "sub_pay_1y": "⭐️ 1 yil (550 Stars)",
        "sub_pay_1m_full": "⭐️ 1 oylik (75 Stars)",
        "sub_pay_3m_full": "⭐️ 3 oylik (175 Stars)",
        "sub_pay_1y_full": "⭐️ 1 yillik (550 Stars)",
        "sub_btn_promo": "🎁 Promo-kod kiritish",
        "sub_btn_send_receipt_admin": "✉️ Adminga chek yuborish",
        "sub_inv_title_1m": "⭐️ PostAssist PRO (1 oy)",
        "sub_inv_title_3m": "⭐️ PostAssist PRO (3 oy)",
        "sub_inv_title_1y": "⭐️ PostAssist PRO (1 yil)",
        "sub_inv_desc_1m": "1 oylik to'liq PRO imkoniyatlar",
        "sub_inv_desc_3m": "3 oylik to'liq PRO imkoniyatlar",
        "sub_inv_desc_1y": "1 yillik to'liq PRO imkoniyatlar (chegirma bilan)",
        "sub_invalid_plan": "❌ Noto'g'ri tarif tanlandi.",
        "sub_invoice_error": "⚠️ To'lov oynasini ochishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
        "sub_promo_ask": (
            "🎁 <b>Promo-kodni kiriting:</b>\n\n"
            "Promo-kodni yozing yoki '{back}' tugmasini bosing."
        ),
        "sub_promo_success": "✅ <b>{msg}</b>\n\nYangi tarif imkoniyatlaringiz faollashtirildi!",
        "sub_promo_fail": "❌ <b>{msg}</b>\n\nQaytadan urinib ko'ring yoki '{back}' tugmasini bosing.",
        "sub_pro_granted": (
            "🎉 <b>Tabriklaymiz!</b>\n\n"
            "Sizga <b>{days} kunlik PRO tarif</b> berildi!\n"
            "Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
        ),
        "sub_pay_activate_error": (
            "⚠️ To'lov qabul qilindi, lekin tarifni faollashtirishda xatolik.\n"
            "Iltimos, admin bilan bog'laning."
        ),
        "sub_pay_duplicate": "✅ Bu to'lov avval qayta ishlangan. PRO tarifingiz allaqachon faol.",
        "sub_pay_success": (
            "🎉 <b>To'lov muvaffaqiyatli!</b>\n\n"
            "⭐️ {stars} Stars qabul qilindi.\n"
            "📅 <b>{days} kunlik PRO tarif</b> faollashtirildi!\n\n"
            "Barcha PRO imkoniyatlardan foydalanishingiz mumkin:\n"
            "• Cheksiz kanallar\n"
            "• Cheksiz AI\n"
            "• To'liq analitika"
        ),
        "sub_pay_err_payload": "Noto'g'ri to'lov payload'i.",
        "sub_pay_err_user": "To'lov foydalanuvchiga mos emas.",
        "sub_pay_err_user_id": "Noto'g'ri foydalanuvchi ID.",
        "sub_pay_err_plan": "Noto'g'ri tarif.",
        "sub_pay_err_currency": "To'lov valyutasi noto'g'ri.",
        "sub_pay_err_amount": "To'lov summasi tarifga mos emas.",
        "sub_pay_err_amount_bad": "To'lov summasi noto'g'ri.",
        "sub_pay_err_incomplete": "To'lov rekvizitlari to'liq emas.",
        "sub_pay_err_bad_request": "Noto'g'ri to'lov so'rovi.",

        # --- Analitika (analytics) ---
        "an_all_channels": "Barcha kanallar",
        "an_btn_all": "📊 Barcha kanallar",
        "an_btn_other": "📢 Boshqa kanal",
        "an_btn_refresh": "🔄 Yangilash",
        "an_refreshing": "🔄 Yangilanmoqda...",
        "an_free_hint": (
            "📊 <b>Analitika</b>\n\n"
            "📌 Free tarifida oxirgi <b>7 kunlik</b> statistika ko'rsatiladi.\n"
            "⭐️ <b>PRO</b> tarifida to'liq analitika (30 kun, barcha postlar, eng faol soatlar) ochiladi!"
        ),
        "an_no_channels": (
            "⚠️ <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Statistika ko'rish uchun avval kanal ulang."
        ),
        "an_choose": "📊 <b>Analitika va Statistika</b>\n\nQaysi kanal statistikasini ko'rasiz?",
        "an_choose_short": "📊 <b>Qaysi kanal statistikasini ko'rasiz?</b>",
        "an_channel_fallback": "Kanal",
        "an_dash_header": "📊 <b>{channel}</b> — Kanal statistikasi",
        "an_dash_div": "━━━━━━━━━━━━━━━━━",
        "an_dash_empty": (
            "📊 <b>{channel}</b> — Kanal statistikasi\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📭 <b>Hali post chiqarilmagan.</b>\n\n"
            "Birinchi postingizni rejalashtiring va bu yerda statistikani kuzating!\n"
            "━━━━━━━━━━━━━━━━━"
        ),
        "an_dash_7d": "📤 Oxirgi 7 kunda: <b>{n}</b> ta post",
        "an_dash_30d": "📦 Oxirgi 30 kunda: <b>{n}</b> ta post",
        "an_dash_all": "📋 Jami chiqarilgan: <b>{n}</b> ta post",
        "an_dash_pending": "⏳ Navbatda kutayotgan: <b>{n}</b> ta post",
        "an_dash_peak": "🕒 Eng faol vaqtlar: <b>{hours}</b>",
        "an_dash_types": "📁 Post turlari: {types}",
        "an_dash_no_data": "Ma'lumot yo'q",
        "an_type_text": "Matn",
        "an_type_photo": "Rasm",
        "an_type_video": "Video",
        "an_type_document": "Hujjat",
        "an_type_audio": "Audio",
        "an_type_animation": "GIF",
        "an_type_album": "Albom",
    # ============================================================
    # 🌐 SANALAR (utils.date_format) va RASM MODERATSIYASI (photo_check)
    #    Sana ko'rinishi, "Bugun/Ertaga" yorliqlari va moderatsiya xabarlari
    #    — avval bu faylda umuman EN/RU variantlari yo'q edi.
    # ============================================================
    "dt_today": "Bugun",
    "dt_tomorrow": "Ertaga",
    # ── 🤖 AI Studio / Vision ──
    "ai_photo_unavailable": "⚠️ AI rasmni tahlil qila olmadi. Iltimos, birozdan so'ng qayta urinib ko'ring.",
    "ai_target_all_line": "🌐 <b>Kanal:</b> Barcha ulangan kanallarga",
    "ai_target_all_name": "Barcha ulangan kanallarga",
    # ── 📷 Qo'lda rasm tekshiruvi (handlers/photo_check.py) ──
    "pc_sent_user": "📸 Rasmingiz adminga yuborildi. Tasdiqlanishi kutilmoqda.",
    "pc_admin_caption": "🆔 Foydalanuvchi ID: <code>{user_id}</code>\n📷 Rasm yuborildi.",
    "pc_btn_approve": "✅ Tasdiqlash",
    "pc_btn_reject": "❌ Rad etish",
    "pc_approved_admin": "✅ <b>Tasdiqlandi!</b>\n\nFoydalanuvchi <code>{user_id}</code> ga PRO berildi.",
    "pc_rejected_admin": "❌ <b>Rad etildi.</b>\n\nFoydalanuvchi PRO tarifi rad etildi.",
    "pc_pro_granted": "🎉 <b>Tabriklaymiz!</b>\n\nSizga <b>30 kunlik PRO tarif</b> berildi!\nBarcha PRO imkoniyatlardan foydalanishingiz mumkin.",
    "pc_reject_notice": "⚠️ <b>Rasmingiz tasdiqlanmadi.</b>\n\nIltimos, qayta urinib ko'ring yoki yordam uchun @shmat_uz adminiga murojaat qiling.",
    "pc_no_permission": "❌ Ruxsat yo'q.",
    "pc_no_pro_permission": "❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.",
    "pc_bad_callback": "Noto'g'ri callback data.",
    "pc_bad_user_id": "User ID xatosi.",
    "pc_db_error": "Xatolik yuz berdi.",

    # ============================================================
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
        # 🚀 Онбординг для ПЕРВОГО входа (показывается только новым пользователям)
        "start_onboarding": (
            "👋 Добро пожаловать! Готовы создать профессиональный пост для вашего канала всего за 1 минуту?\n"
            "\n"
            "✍️ Генерация постов через AI\n"
            "📅 Планирование на любое время\n"
            "📢 Автопостинг в каналы\n"
            "\n"
            "Чтобы создать свой первый пост прямо сейчас, выберите раздел ниже 👇"
        ),
        # 🆕 ПРОСТОЕ МЕНЮ — для новых пользователей (1-3 дня): 3 крупные кнопки
        # + 1 небольшая кнопка «открыть полное меню».
        "quick_menu_hint": (
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Нажмите одну из <b>3 кнопок ниже</b> — остальное сделаем автоматически.\n\n"
            "🚀 AI напишет пост  •  🖼 Пост из фото  •  📢 Подключит канал\n\n"
            "<i>Если нужны все разделы — нажмите "
            "«⚙️ Открыть полное меню» внизу.</i>"
        ),
        "quick_btn_ai_post": "🚀 Создать пост за 1 минуту",
        "quick_btn_photo_post": "🖼 Пост из фото",
        "quick_btn_add_channel": "📢 Подключить канал",
        "quick_btn_full_menu": "⚙️ Открыть полное меню",
        "quick_full_menu_opened": (
            "✅ <b>Полное меню открыто!</b>\n\n"
            "Теперь доступны все разделы — выберите нужный в меню ниже 👇"
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
        "card_tariff_title": (
            "💳 <b>Оплата картой</b>\n\n"
            "📌 За какой тариф платите? Выберите тариф 👇"
        ),
        "card_plan_1m": "1 месяц",
        "card_plan_3m": "3 месяца",
        "card_plan_1y": "1 год",
        "card_tariff_1m": "1 месяц — {price} сум",
        "card_tariff_3m": "3 месяца — {price} сум",
        "card_tariff_1y": "1 год — {price} сум",
        "card_payment_selected": (
            "🎫 Выбранный тариф: <b>{tarif}</b>\n"
            "💰 Сумма оплаты: <b>{summa} сум</b>"
        ),
        "card_payment_card": "💳 <b>Номер карты:</b> <code>{card}</code>\n👤 <b>Владелец:</b> {holder}",
        "card_payment_no_card": "ℹ️ Чтобы получить реквизиты карты, обратитесь к администратору.",
        "card_payment_steps": (
            "📝 <b>Инструкция:</b>\n"
            "1️⃣ Переведите выбранную сумму на карту выше.\n"
            "2️⃣ Получите чек (скриншот или PDF).\n"
            "3️⃣ Нажмите кнопку <b>\"📸 Отправить чек\"</b> ниже и отправьте чек сюда.\n"
            "4️⃣ Ваш ID: <code>{user_id}</code> — используется при проверке чека.\n\n"
            "После подтверждения администратором тариф <b>PRO</b> будет активирован.\n"
            "⚡️ Для мгновенной активации оплатите через ⭐️ Stars.\n"
            "Вопросы: {admin}"
        ),
        "card_payment_admin_missing": "администратор (контакты в разделе «О боте»)",
        "btn_send_receipt": "📸 Отправить чек",
        "receipt_prompt": (
            "📸 <b>Отправьте чек об оплате:</b>\n\n"
            "🎫 Выбранный тариф: {tarif} ({summa} сум)\n\n"
            "Отправьте чек (скриншот или PDF) в виде <b>фото или документа</b>. "
            "Бот отправит чек администраторам.\n"
            "🆔 Ваш ID: <code>{user_id}</code>\n\n"
            "После подтверждения администратором тариф <b>PRO</b> "
            "активируется автоматически."
        ),
        "receipt_bad_media": (
            "⚠️ Пожалуйста, отправьте чек в виде <b>фото</b> или "
            "<b>PDF-документа</b>. Другие файлы не принимаются как чек."
        ),
        "receipt_saved": (
            "✅ Ваш чек получен и отправлен администратору. "
            "Вскоре мы проверим его и активируем PRO."
        ),
        "receipt_save_error": (
            "⚠️ Не удалось сохранить чек. Пожалуйста, отправьте его ещё раз."
        ),
        "receipt_admin_title": "💳 <b>Новый платёжный чек!</b>",
        "receipt_admin_user_line": "👤 Пользователь: {name} (@{username})",
        "receipt_admin_user_nick_line": "👤 Пользователь: {name}",
        "receipt_admin_user_id_line": "🆔 ID: {user_id}",
        "receipt_admin_tarif_line": "🎫 Выбранный тариф: {tarif} ({summa} сум)",
        "receipt_admin_time_line": "🕐 Время: {sana}",
        "receipt_admin_ask": "📝 Проверьте чек и нажмите одну из кнопок ниже:",
        "receipt_btn_approve": "✅ Подтвердить",
        "receipt_btn_reject": "❌ Отклонить",
        "receipt_admin_done_ok": "✅ Подтверждено. Пользователю выдан PRO.",
        "receipt_admin_done_reject": "❌ Отклонено.",
        "receipt_admin_already": "Этот чек уже был рассмотрен.",
        "receipt_approved_user": (
            "🎉 <b>Поздравляем!</b>\n\n"
            "Ваш платёжный чек подтверждён, и тариф <b>PRO на {days} дней</b> "
            "активирован!\nВы можете пользоваться всеми возможностями PRO. 🚀"
        ),
        "receipt_rejected_user": (
            "❌ <b>Чек отклонён</b>\n\n"
            "К сожалению, ваш платёжный чек не был подтверждён. Пожалуйста, "
            "попробуйте ещё раз или свяжитесь с администратором в разделе "
            "'⭐️ Premium'."
        ),
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
        # 🚀 ПЛАНИРОВАНИЕ ВСЕГО КОНТЕНТ-ПЛАНА НА 7 ДНЕЙ ОДНОЙ КНОПКОЙ
        "plan_btn_schedule_all": "🚀 Запланировать все на 7 дней",
        "plan_week_hint": "\n\n🚀 <i>Или поставьте всю неделю в очередь "
                        "одной кнопкой.</i>",
        "plan_sched_busy": "⏳ Добавляем 7 постов в очередь...",
        "plan_sched_done_alert": "✅ 7 постов в очереди!",
        "plan_sched_done": (
            "✅ <b>7 постов на неделю добавлены в очередь!</b>\n\n"
            "📢 Канал: <b>{channel}</b>\n"
            "📦 В очередь добавлено: <b>{count} постов</b>\n\n"
            "{days}\n\n"
            "🤖 Посты будут выходить автоматически каждый день в <b>12:00</b>.\n"
            "📋 Любой пост можно изменить или отменить в разделе "
            "«👤 Кабинет & Настройки» → «⏳ Очередь постов (Queue)»."
        ),
        "plan_sched_already": "ℹ️ Этот контент-план уже добавлен в очередь.",
        "plan_sched_stale": (
            "⚠️ Сессия устарела. Создайте контент-план заново — "
            "после этого вы сможете запланировать 7 дней одной кнопкой."
        ),
        "plan_sched_no_channel": (
            "⚠️ <b>Канал не найден.</b>\n\n"
            "Сначала подключите канал, затем создайте контент-план заново."
        ),
        "plan_sched_empty": "⚠️ План пуст — сначала создайте контент-план.",
        "plan_sched_error": "❌ Не удалось добавить посты в очередь. Попробуйте ещё раз.",
        "plan_sched_day_line": "• {day} — {time}",
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
        "ai_photo_variants_ask": (
            "🎨 По фото готово <b>3 варианта стиля</b>. "
            "Выберите один — откроется выбранный текст 👇"
        ),
        "ai_wait_edit": "✏️ <i>ИИ редактирует пост...</i>",
        "ai_unavailable": (
            "⚠️ Временный сбой в сервисе ИИ. "
            "Пожалуйста, попробуйте ещё раз чуть позже."
        ),
        "ai_quota": (
            "⚠️ AI quota закончилась. "
            "Подождите и попробуйте снова."
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
            "Или точный формат: <code>DD.MM.YYYY HH:MM</code> "
            "(например <code>30.08.2026 18:00</code>)\n\n"
            "🕒 <i>Время по Ташкенту (UTC+5).</i>"
        ),
        "ai_time_detecting": "🤖 <i>Время определяется...</i>",
        "ai_full_post_text": "📝 <b>Полный текст поста:</b>\n\n{text}",
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

        # --- 3-QISM: ➕ Новый пост i18n (RU) ---
        "np_btn_skip": "➡️ Продолжить без кнопки",
        "np_btn_skip_url": "⏭ Пропустить",
        "np_btn_url_add": "🔗 Добавить URL-кнопку",
        "np_btn_ai_assistant": "✨ ИИ-помощник",
        "np_btn_title_details": "Подробнее",
        "np_btn_title_join": "Подписаться на канал",
        "np_btn_title_site": "Перейти на сайт",
        "np_btn_title_contact": "Связаться",
        "np_btn_no_reactions": "➡️ Продолжить без реакций",
        "np_btn_del_never": "❌ Не удалять (постоянно)",
        "np_btn_del_12h": "⏳ 12 часов",
        "np_btn_del_24h": "⏳ 24 часа (1 день)",
        "np_btn_del_48h": "⏳ 48 часов (2 дня)",
        "np_btn_del_72h": "⏳ 72 часа (3 дня)",
        "np_btn_time_5m": "⚡ 5 минут",
        "np_btn_time_15m": "⚡ 15 минут",
        "np_btn_time_1h": "⚡ 1 час",
        "np_btn_time_daily": "🔁 Ежедневно (в одно время)",
        "np_btn_time_weekly": "📅 Еженедельно (в определённый день)",
        "np_btn_dur_1w": "1 неделя",
        "np_btn_dur_1m": "1 месяц",
        "np_btn_dur_3m": "3 месяца",
        "np_btn_dur_6m": "6 месяцев",
        "np_btn_dur_1y": "1 год",
        "np_btn_dur_inf": "♾ Бессрочно",
        "np_weekday_0": "Понедельник",
        "np_weekday_1": "Вторник",
        "np_weekday_2": "Среда",
        "np_weekday_3": "Четверг",
        "np_weekday_4": "Пятница",
        "np_weekday_5": "Суббота",
        "np_weekday_6": "Воскресенье",
        "np_btn_back_confirm": "🔙 Назад",
        "np_btn_all_channels": "🌐 Сразу во все",
        "np_label_today": "Сегодня",
        "np_label_tomorrow": "Завтра",

        # Новый пост: тексты процесса
        "np_channel_selected": (
            "✅ Выбрано: <b>{channel}</b>\n\n"
            "📝 <b>Отправьте контент для поста:</b>\n"
            "(Текст, фото, видео, альбом, документ, аудио или GIF — стикеры и голосовые не принимаются)"
        ),
        "np_channel_not_found": "⚠️ Такой канал не найден. Выберите ещё раз:",
        "np_media_not_allowed": (
            "Извините, стикеры не принимаются в качестве поста. Пожалуйста, "
            "отправьте фото, видео или текст"
        ),
        "np_all_channel_title": "🌐 Все сразу",
        "np_button_ask": (
            "🔘 <b>Добавить кнопку-ссылку под пост?</b> (необязательно)\n\n"
            "⚡️ <b>Быстрый способ:</b> отправьте текст кнопки и ссылку в одной строке:\n"
            "<code>Button Text - https://link.com</code>\n\n"
            "Или выберите готовый вариант / отправьте свой текст "
            "(затем уточним ссылку).\n\n"
            "Если не нужно — нажмите <b>⏭ Пропустить</b>:"
        ),
        "np_button_ready": (
            "✅ <b>Инлайн-кнопка готова:</b>\n"
            "🔘 Текст: <b>{title}</b>\n"
            "🔗 Ссылка: <code>{url}</code>"
        ),
        "np_button_url_ask": (
            "🔗 <b>Отправьте ссылку или @username канала, который откроется "
            "по кнопке '{title}':</b>\n\n"
            "Например: <code>@kanalim</code> или <code>https://sayt.uz</code>\n\n"
            "<i>Или одной строкой: <code>{title} - https://link.com</code></i>"
        ),
        "np_button_url_add_ask": (
            "🔗 <b>Добавление URL-кнопки</b>\n\n"
            "Отправьте текст кнопки и ссылку <b>в одной строке, разделив \" - \"</b>:\n"
            "<code>Button Text - https://link.com</code>\n\n"
            "<i>Например:</i> <code>Перейти на сайт - https://sayt.uz</code> или\n"
            "<code>Мой канал - @kanalim</code>"
        ),
        "np_reactions_ask": (
            "👍 <b>Какие кнопки-реакции добавить под пост?</b>\n\n"
            "Нажимайте нужные эмодзи — отметятся ✅ (повторное нажатие отменяет).\n"
            "Или напишите свободно, например: <code>👍 ❤️ 🔥</code> — можно "
            "отправить несколько через пробел.\n"
            "Если отправите стикер — его эмодзи тоже добавится к реакциям.\n"
            "Выбрав, нажмите <b>➡️ Продолжить</b>.\n"
            "Если реакции не нужны — <b>⏭ Пропустить реакции</b>."
        ),
        "np_reactions_selected": (
            "✅ Выбрано: {emojis}\n"
            "Можно добавить ещё эмодзи или нажать <b>➡️ Продолжить</b>:"
        ),
        "np_reactions_use_inline": (
            "⚠️ <b>Пожалуйста, используйте инлайн-кнопки ниже:</b>\n"
            "• Нажмите эмодзи, чтобы выбрать (отметятся ✅)\n"
            "• Можно отправить эмодзи свободно: <code>👍 ❤️ 🔥</code>\n"
            "• Если отправите стикер — его эмодзи добавится к реакциям\n"
            "• <b>➡️ Продолжить</b> — перейти с выбранными\n"
            "• <b>⏭ Пропустить реакции</b> — без реакций"
        ),
        "np_reactions_none": (
            "ℹ️ Реакции не выбраны — пост выйдет без кнопок-реакций."
        ),
        "np_react_done": "➡️ Продолжить",
        "np_react_done_count": "➡️ Продолжить ({count} шт.)",
        "np_react_skip": "⏭ Пропустить реакции",
        "np_auto_delete_ask": (
            "🗑️ <b>Сколько времени пост должен оставаться в канале?</b>\n\n"
            "По истечении времени бот автоматически удалит его из канала:"
        ),
        "np_time_ask": (
            "🕒 <b>Когда должен выйти пост?</b>\n\n"
            "Выберите готовую кнопку или напишите точное время.\n"
            "Формат: <code>DD.MM.YYYY HH:MM</code>\n"
            "Пример: <code>{example}</code>\n\n"
            "🕒 <i>Время по Ташкенту (UTC+5).</i>"
        ),
        "np_time_future": (
            "⚠️ <b>Это время уже прошло.</b>\n\n"
            "Пожалуйста, укажите время в БУДУЩЕМ.\n"
            "Пример: <code>{example}</code>\n\n"
            "🕒 <i>Сейчас в Ташкенте: {now}</i>"
        ),
        "np_time_format_error": (
            "⚠️ <b>Формат времени не распознан.</b>\n\n"
            "Правильный формат: <code>DD.MM.YYYY HH:MM</code>\n"
            "Пример: <code>{example}</code>\n\n"
            "Или напишите одно из следующего:\n"
            "• только время — <code>18:00</code> (сегодня, если прошло — завтра)\n"
            "• <code>завтра 18:00</code>\n"
            "• <code>через 2 часа</code>\n\n"
            "🕒 <i>Всё время указывается по Ташкенту (UTC+5).</i>"
        ),
        "np_daily_time_ask": (
            "🔁 <b>Во сколько выходить ежедневно?</b>\n"
            "Например: <code>10:00</code> или <code>18:30</code>"
        ),
        "np_daily_time_format": (
            "⚠️ <b>Неверный формат времени.</b>\n\n"
            "Укажите только время в виде <code>HH:MM</code>.\n"
            "Пример: <code>10:00</code> или <code>18:30</code>\n\n"
            "🕒 <i>Время по Ташкенту (UTC+5).</i>"
        ),
        "np_weekday_ask": "📅 <b>В какой день недели выходить?</b>",
        "np_weekday_invalid": "⚠️ Выберите один из дней:",
        "np_recur_time_ask": (
            "🕒 <b>Во сколько выходить каждый {day}?</b>\n"
            "Например: <code>10:00</code>"
        ),
        "np_recur_time_format": (
            "⚠️ <b>Неверный формат!</b> Укажите время как <code>HH:MM</code>. "
            "Пример: <code>10:00</code> 🕒 <i>(время по Ташкенту, UTC+5)</i>"
        ),
        "np_duration_ask_daily": (
            "⏳ <b>Как долго пост должен выходить ежедневно?</b>"
        ),
        "np_duration_ask_weekly": (
            "⏳ <b>Как долго должен выходить этот пост?</b>"
        ),
        "np_duration_invalid": "⚠️ Выберите один из вариантов:",

        # Подтверждение
        "np_confirm_title": "📋 <b>Подтвердите пост:</b>",
        "np_confirm_channel": "📢 <b>Канал:</b> {channel}",
        "np_confirm_type": "📦 <b>Тип:</b> {type}",
        "np_type_text": "📝 Текст",
        "np_type_photo": "🖼 Фото",
        "np_type_video": "🎬 Видео",
        "np_type_document": "📄 Документ",
        "np_type_audio": "🎵 Аудио",
        "np_type_voice": "🎙 Голосовое",
        "np_type_sticker": "😀 Стикер",
        "np_type_album": "🖼 Альбом",
        "np_type_animation": "🎞 GIF",
        "np_type_unknown": "📝 Сообщение",
        # Сводка альбома (в предпросмотре видно, сколько файлов будет отправлено)
        "np_confirm_album_photos": "🖼 Альбом: {count} фото",
        "np_confirm_album_videos": "🎬 Альбом: {count} видео",
        "np_confirm_album_mixed": "🖼 Альбом: {photos} фото, {videos} видео",
        "np_confirm_album_files": "🖼 Альбом: {count} файлов",
        "np_confirm_content_truncated": (
            "⚠️ Примечание: текст {total} символов — из-за лимита Telegram "
            "{limit} символов в канале будет показано до этого лимита. "
            "Текст сохраняется полностью."
        ),
        "np_confirm_time_none": "⏰ Время не указано",
        "np_confirm_time_single": "⏰ {time} (время Ташкента)",
        "np_confirm_time_daily": "🔁 Ежедневно, в {time}",
        "np_confirm_time_weekly": "📅 Каждый {day}, в {time}",
        "np_confirm_content": "📋 <b>Текст:</b>\n{content}",
        "np_confirm_button": "🔘 Кнопка: <b>{text}</b>",
        "np_confirm_reactions": "👍 Реакции: {emojis}",
        "np_confirm_reactions_on": "👍 Реакции: Включены",
        "np_confirm_auto_delete": "⏳ Авто-удаление: {hours} ч.",
        "np_confirm_ok_btn": "✅ Подтвердить и запланировать",
        "np_confirm_queue_btn": "⏳ Добавить в очередь",
        "np_confirm_edit_btn": "✏️ Редактировать",
        "np_confirm_cancel_btn": "❌ Отмена",

        # 🖼 АЛЬБОМ + кнопка/реакция предупреждение (sendMediaGroup ограничение)
        # Правило Telegram Bot API: к sendMediaGroup нельзя привязать
        # inline_keyboard (URL-кнопку или реакции) — при отправке альбома
        # пользователь получает предупреждение + 2 варианта выбора.
        "np_album_warning": (
            "⚠️ По правилам Telegram к альбому из нескольких фото нельзя добавить "
            "кнопку-ссылку или кнопки реакций. \n"
            "Кнопка или реакции работают только для 1 фото (или простого текста)."
        ),
        "np_album_choice_first_photo": "🖼 Оставить 1 фото + добавить кнопку",
        "np_album_choice_full": "⏩ Опубликовать полный альбом без кнопок",
        "np_album_first_photo_done": (
            "✅ Пост изменён до одного фото — теперь можно добавить кнопку или реакции."
        ),
        "np_album_full_done": (
            "✅ Полный альбом ({count} файлов) будет опубликован без кнопок и реакций."
        ),

        # Меню редактирования
        "np_edit_menu_title": "✏️ <b>Что нужно отредактировать?</b>",
        "np_edit_content_btn": "📝 Текст",
        "np_edit_channel_btn": "📢 Канал",
        "np_edit_time_btn": "⏰ Время",
        "np_edit_button_btn": "🔘 Кнопка",
        "np_edit_back_btn": "⬅️ Назад (к подтверждению)",
        "np_edit_content_ask": "📝 <b>Отправьте новый текст:</b>",
        "np_edit_channel_ask": "📢 <b>Какой канал?</b>",
        "np_edit_time_ask": "🕒 <b>Новое время:</b> <code>{example}</code>",
        "np_edit_button_ask": (
            "🔘 <b>Кнопка:</b> <code>Текст | https://ссылка.uz</code>\n"
            "Удаление: <code>нет</code>"
        ),
        "np_edit_channel_not_found": "⚠️ Канал не найден.",

        # Итоговые сообщения
        "np_cancelled": "🚫 <b>Пост отменён.</b>\nВы вернулись в главное меню 👇",
        "np_no_time": "⚠️ <b>Время не указано.</b>",
        "np_no_channel": "⚠️ <b>Канал не выбран.</b>",
        "np_no_slot": (
            "⚠️ <b>Свободный слот не найден.</b>\nВсе слоты на 7 дней заняты."
        ),
        "np_scheduled_ok": (
            "✅ <b>Пост успешно запланирован!</b>\n\n"
            "📢 Размещение: <b>{channel}</b>\n"
            "{when}{del_info}"
        ),
        "np_scheduled_when_single": "⏰ {time}",
        "np_scheduled_when_daily": "🔁 Ежедневно, в {time}",
        "np_scheduled_when_weekly": "📅 Каждый {day}, в {time}",
        "np_scheduled_del": "\n⏳ Время в канале: <b>{hours} ч.</b>",
        "np_queue_added": (
            "⚡️ <b>Пост добавлен в очередь!</b>\n\n"
            "📅 {label}, в {time}\n"
            "📢 Канал: <b>{channel}</b>{ad_line}"
        ),
        "np_queue_error": "❌ <b>Ошибка при добавлении в очередь.</b>",
        "np_save_error": "❌ Ошибка при сохранении.",
        "np_save_error_bold": "❌ <b>Ошибка при сохранении.</b>",

        # ИИ-помощник (редактирование поста)
        "np_ai_menu_title": (
            "✨ <b>ИИ-помощник</b>\n\n"
            "📋 Текущий текст:\n<i>{preview}</i>\n\n"
            "Какое действие выполним?"
        ),
        "np_ai_empty_content": "⚠️ <b>Текст поста пуст.</b>\nСначала введите текст.",
        "np_ai_empty_alert": "⚠️ Текст пуст!",
        "np_ai_working": "⏳ ИИ работает...",
        "np_ai_empty_result": "⚠️ Ответ ИИ пуст. Исходный текст сохранён.",
        "np_ai_proposal": (
            "✨ <b>Предложение ИИ:</b>\n\n{new}\n\n"
            "📝 Исходный: <i>{old}</i>"
        ),
        "np_ai_retry_proposal": "✨ <b>Предложение ИИ (повторно):</b>\n\n{new}",
        "np_ai_accepted_alert": "✅ Принято!",
        "np_ai_accept_msg": "✅ <b>Новый текст принят!</b>\n\n{content}",
        "np_ai_reverted_alert": "❌ Возвращён исходный текст!",
        "np_ai_revert_msg": "❌ <b>Исходный текст возвращён.</b>",
        "np_ai_retrying": "🔄 Повторная попытка...",
        "np_ai_action_grammar": "✍️ Орфография и стиль",
        "np_ai_action_emoji": "🎨 Эмодзи",
        "np_ai_action_hashtags": "🏷 Хештеги",
        "np_ai_action_tldr": "✂️ Сократить",
        "np_ai_btn_back": "⬅️ Назад",
        "np_ai_btn_accept": "✅ Принять",
        "np_ai_btn_retry": "🔄 Повторить",
        "np_ai_btn_revert": "❌ Вернуть исходный",

        # --- 3-QISM: 📢 Мои каналы i18n (RU) ---
        "ch_empty_title": (
            "📢 <b>У вас пока нет подключённых каналов.</b>\n\n"
            "Нажмите кнопку ниже, чтобы подключить канал 👇\n\n"
            "<i>Сначала добавьте бота администратором вашего канала "
            "(с правом отправки сообщений).</i>"
        ),
        "ch_list_title": (
            "📢 <b>Ваши подключённые каналы ({count} шт.):</b>\n\n"
            "Чтобы удалить канал, нажмите '❌ Удалить' или подключите новый 👇"
        ),
        "ch_all_removed": (
            "📢 <b>Все каналы удалены.</b>\n\n"
            "Чтобы подключить новый канал, нажмите кнопку ниже 👇"
        ),
        "ch_add_btn": "➕ Подключить канал/группу",
        "ch_add_instructions": (
            "➕ <b>Подключение нового канала или группы:</b>\n\n"
            "1. Добавьте бота (<code>@{bot}</code>) в свой канал или группу "
            "<b>Администратором</b> (с правом отправки сообщений).\n"
            "2. Затем отправьте источник канала в одном из четырёх форматов:\n"
            "   • <b>Перешлите (Forward)</b> любое сообщение из канала;\n"
            "   • <code>@имя_канала</code>;\n"
            "   • <code>t.me/имя_канала</code> или <code>https://t.me/имя_канала</code>;\n"
            "   • ID канала (например: <code>-1001234567890</code>).\n\n"
            "<i>Для отмены нажмите '🔙 Главное меню'.</i>"
        ),
        "ch_retry_btn": "🔁 Я сделал бота админом — проверить снова",
        "ch_empty_target": (
            "❌ Получено пустое сообщение. <b>Перешлите</b> сообщение из канала, "
            "отправьте <code>@username</code>, ID или ссылку <code>t.me/kanal</code>."
        ),
        "ch_invite_blocked": (
            "🔒 <b>Закрытый канал (по invite-ссылке) подключить нельзя.</b>\n\n"
            "Раз бот уже администратор канала, отправьте <code>@username</code> "
            "или <b>перешлите</b> любое сообщение из канала — мы его определим."
        ),
        "ch_not_found": (
            "❌ Канал или группа не найдены. Перешлите сообщение или отправьте правильный ID."
        ),
        "ch_cannot_verify": (
            "⚠️ <b>Бот отсутствует в канале или не удалось проверить права.</b>\n\n"
            "Сначала добавьте бота администратором (с правом отправки сообщений)."
        ),
        "ch_not_admin": (
            "⚠️ <b>Бот не является администратором этого канала!</b>\n\n"
            "Пожалуйста, сначала дайте боту право отправлять сообщения в канале."
        ),
        "ch_no_post_permission": (
            "⚠️ <b>Боту не выдано право отправки сообщений в канале.</b>\n\n"
            "Включите право <b>Post Messages</b> в настройках администратора."
        ),
        "ch_user_verify_fail": (
            "⚠️ <b>Не удалось проверить ваши права в этом канале.</b>\n\n"
            "Подключить канал к боту может только администратор канала/группы."
        ),
        "ch_forbidden": (
            "🚫 <b>Нет доступа.</b>\n\n"
            "Подключить канал к боту может только <b>администратор</b> канала или группы."
        ),
        "ch_unknown_target": (
            "❌ Данные канала не определены. Пожалуйста, <b>перешлите</b> сообщение "
            "из канала или отправьте <code>@username</code>, "
            "<code>t.me/имя_канала</code>, ID (например: <code>-1001234567890</code>)."
        ),
        "ch_empty_target_short": (
            "❌ Данные канала не определены. Пожалуйста, перешлите сообщение из канала:"
        ),
        "ch_unexpected_error": (
            "⚠️ <b>Произошла непредвиденная ошибка.</b>\n\n"
            "Пожалуйста, перешлите сообщение из канала ещё раз или отправьте "
            "<code>@username</code> / <code>t.me/kanal</code>."
        ),
        "ch_retry_after": (
            "{error}\n\nПосле выдачи прав боту нажмите кнопку ниже "
            "или отправьте источник канала ещё раз 👇"
        ),
        "ch_limit_msg": (
            "🚫 <b>Лимит каналов исчерпан!</b>\n\n"
            "Сейчас подключено <b>{current}/{max}</b> каналов.\n"
            "На бесплатном тарифе можно подключить максимум <b>{max}</b> каналов.\n\n"
            "⭐️ Перейдите на PRO, чтобы использовать без ограничений."
        ),
        "ch_pro_btn": "⭐️ Перейти на PRO",
        "ch_success": (
            "✅ <b>Канал успешно подключён!</b>\n\n"
            "📢 Название: <b>{title}</b>\n"
            "🆔 ID: <code>{channel_id}</code>\n\n"
            "📋 <b>Ваши каналы ({count} шт.):</b>"
        ),
        "ch_success_footer": "Чтобы удалить канал или изменить стиль 👇",
        "ch_taken": (
            "🚫 <b>Этот канал уже подключён к другому пользователю.</b>\n\n"
            "Присвоить его нельзя. Если это ваш канал — сначала владелец "
            "должен удалить его из бота."
        ),
        "ch_save_error": "❌ Ошибка при сохранении канала.",
        "ch_remove_not_found": "❌ Канал не найден или не принадлежит вам.",
        "ch_no_perm_dm": (
            "⚠️ <b>Бот добавлен администратором, но право отправки сообщений "
            "(Post Messages) не выдано!</b>\n\n"
            "📢 Канал: <b>{channel}</b>\n\n"
            "Включите для бота право <b>Post Messages</b> в настройках канала — "
            "после этого канал подключится автоматически."
        ),
        "ch_autoconnect_success": (
            "🎉 <b>Вы назначили бота администратором канала {channel} — канал подключён!</b>\n\n"
            "🆔 <code>{channel_id}</code>\n\n"
            "Теперь вы можете планировать посты в этот канал 👇"
        ),
        "ch_default_title": "Telegram Канал",
        "ch_tone_title": (
            "🎭 <b>Выберите стиль канала:</b>\n\n"
            "Текущий стиль: <b>{current}</b>\n\n"
            "Стиль определяет тон и оформление постов:"
        ),
        "ch_tone_formal": "👔 Официальный / Бизнес",
        "ch_tone_friendly": "😊 Дружелюбный / Тёплый",
        "ch_tone_concise": "⚡️ Кратко / Новости",
        "ch_tone_engaging": "🎉 Развлекательный / Эмоциональный",
        "ch_tone_cancelled": "✅ Изменение стиля отменено.",
        "ch_tone_invalid": "❌ Неверный стиль. Пожалуйста, нажмите одну из кнопок.",
        "ch_tone_success": (
            "✅ <b>Стиль канала обновлён!</b>\n\n"
            "🎭 Новый стиль: <b>{tone}</b>\n\n"
            "Теперь ИИ будет готовить посты в этом стиле."
        ),
        "ch_tone_error": "❌ Ошибка при сохранении стиля. Попробуйте ещё раз.",
        "ch_voice_btn": "🎙 Голос канала",
        "ch_voice_analyzing": (
            "🎙 <b>Анализ голоса канала...</b>\n\n"
            "ИИ изучает последние посты канала и определяет его стиль."
        ),
        "ch_voice_no_posts": (
            "⚠️ На канале недостаточно постов для анализа. "
            "Добавьте бота администратором канала, дождитесь постов и повторите попытку."
        ),
        "ch_voice_result": (
            "🎙 <b>Результат анализа голоса канала:</b>\n\n"
            "✅ Стиль: <b>{tone}</b>\n💬 {reason}\n\n"
            "Стиль сохранён в профиле канала и будет использоваться в генерациях ИИ."
        ),
        "ch_voice_error": "⚠️ Не удалось выполнить анализ голоса канала. Попробуйте ещё раз чуть позже.",

        # --- 3-QISM: 📅 Ожидающие посты i18n (RU) ---
        "pend_empty": "⏳ <b>У вас нет ожидающих активных постов.</b>",
        "pend_list_title": "⏳ <b>Ваши ожидающие посты ({count} шт.):</b>",
        "pend_item": (
            "🔹 <b>Пост: {code}</b>\n"
            "📢 Канал: <b>{channel}</b>\n"
            "📦 Тип: <b>{type}</b>\n"
            "{time}\n\n"
        ),
        "pend_channel_fallback": "Канал",
        "pend_edit_time_btn": "🕒 {code} время",
        "pend_edit_content_btn": "✏️ {code} текст",
        "pend_edit_btn_btn": "🔗 Кнопка",
        "pend_edit_react_btn": "👍 Реакции",
        "pend_cancel_btn": "❌ Отмена",
        "pend_refresh_btn": "🔄 Обновить",
        "pend_close_btn": "❌ Закрыть",
        "pend_refreshed": "✅ Обновлено",
        "pend_refresh_fail": "Не удалось обновить",
        "pend_rate_limited": "⏳ Пожалуйста, подождите немного...",
        "pend_error": "⚠️ Ошибка: {error}",
        "pend_not_found": "❌ Пост не найден.",
        "pend_not_owned": "❌ Этот пост не принадлежит вам.",
        "pend_time_ask": (
            "🕒 <b>Отправьте новое время выхода поста:</b>\n\n"
            "• Для одноразового поста: <code>DD.MM.YYYY HH:MM</code> "
            "(например <code>30.08.2026 20:00</code>)\n"
            "• Работает свободный формат: <code>завтра 18:00</code>, <code>сегодня 10:00</code>\n"
            "• Для ежедневного поста только время: <code>10:00</code>"
        ),
        "pend_time_success": "✅ <b>Время поста успешно обновлено!</b>",
        "pend_time_format": (
            "⚠️ <b>Формат времени не распознан.</b>\n\n"
            "Правильный формат: <code>DD.MM.YYYY HH:MM</code>\n"
            "Пример: <code>{example}</code> или только время — <code>18:00</code>\n\n"
            "🕒 <i>Время по Ташкенту (UTC+5).</i>"
        ),
        "pend_content_ask": (
            "✏️ <b>Отправьте новый текст поста:</b>\n\n"
            "Поддерживаются HTML-теги (<b>bold</b>, <i>italic</i>, <code>code</code>)."
        ),
        "pend_content_success": "✅ <b>Текст поста обновлён!</b>",
        "pend_btn_ask": (
            "🔗 <b>Отправьте новый текст кнопки:</b>\n\n"
            "Формат: <code>Текст кнопки | https://ссылка.uz</code>\n"
            "Чтобы удалить кнопку, напишите: <code>нет</code>."
        ),
        "pend_btn_removed": "✅ <b>Кнопка удалена!</b>",
        "pend_btn_updated": "✅ <b>Кнопка обновлена:</b> <code>{text}</code>",
        "pend_btn_format": (
            "⚠️ Ошибка формата!\nНапример: <code>Подробнее | https://sayt.uz</code>\n"
            "Или удалить: <code>нет</code>"
        ),
        "pend_react_ask": (
            "👍 <b>Изменить реакции поста:</b>\n\nВыберите один из вариантов:"
        ),
        "pend_react_invalid": "⚠️ Выберите одну из кнопок:",
        "pend_react_off": "✅ <b>Реакции отключены!</b>",
        "pend_react_updated": "✅ <b>Реакции обновлены:</b> {emojis}",
        "pend_react_on": "✅ <b>Реакции включены!</b>",
        "pend_update_fail": "❌ Не удалось изменить.",
        "pend_schedule_daily": "🔁 <b>Ежедневно</b>, в <b>{time}</b>",
        "pend_schedule_weekly": "📅 <b>Каждый {day}</b>, в <b>{time}</b>",
        "pend_schedule_once": "⏰ Время: <b>{time}</b>",
        "pend_schedule_unknown": "⏰ Время: не указано",

        # --- 3-QISM: ⏳ Очередь и слоты i18n (RU) ---
        "queue_title": "📚 <b>Посты в очереди</b> ({count} шт.):",
        "queue_title_range": "📚 <b>Посты в очереди</b> ({count} шт., {start}-{end}):",
        "queue_empty": (
            "📚 <b>Очередь (Queue)</b>\n\n"
            "Пока в очереди нет постов.\n"
            "Создайте пост и нажмите <b>⏳ Добавить в очередь</b>."
        ),
        "queue_empty_short": "📚 <b>Очередь (Queue)</b>\n\nВ очереди нет постов.",
        "queue_limit_msg": (
            "🚫 <b>Лимит очереди исчерпан!</b>\n\n"
            "У вас <b>{current}/{max}</b> постов в очереди.\n"
            "На бесплатном тарифе максимум <b>{max}</b> постов в очереди.\n\n"
            "⭐️ Перейдите на PRO для безлимитной очереди."
        ),
        "queue_not_found": "⚠️ Пост не найден или уже удалён.",
        "queue_not_found_short": "⚠️ Пост не найден!",
        "queue_no_slot": "⚠️ Свободный слот не найден!",
        "queue_deleted_alert": "🗑 Удалено!",
        "queue_view_title": "👁 <b>Пост #{id}</b>",
        "queue_view_channel": "📢 Канал: {channel}",
        "queue_view_type": "📦 Тип: {type}",
        "queue_view_time": "⏰ Время: {time}",
        "queue_view_content": "📋 Текст:\n{content}",
        "queue_view_button": "🔘 Кнопка: {text}",
        "queue_view_reactions": "👍 Реакции: Включены",
        "queue_view_auto_delete": "⏳ Авто-удаление: {hours} ч.",
        "queue_btn_view": "👁 Смотреть #{id}",
        "queue_btn_delete": "🗑 Удалить",
        "queue_btn_push": "⏩ Сдвинуть",
        "queue_btn_prev": "⬅️ Назад",
        "queue_btn_next": "Вперёд ➡️",
        "queue_btn_slots": "⚙️ Настроить слоты",
        "queue_btn_close": "❌ Закрыть",
        "queue_btn_back": "⬅️ Вернуться к списку",
        "queue_btn_add_slot": "➕ Добавить слот",
        "queue_btn_reset_slots": "🔄 Слоты по умолчанию",
        "queue_slots_title": (
            "⚙️ <b>Настройки слотов</b>\n\n"
            "Текущие слоты: <code>{slots}</code>\n\n"
            "Посты автоматически планируются на это время каждый день."
        ),
        "queue_slots_reset": (
            "⚙️ <b>Настройки слотов</b>\n\n"
            "Текущие слоты: <code>{slots}</code>\n\n"
            "Слоты по умолчанию возвращены."
        ),
        "queue_slot_add_ask": (
            "➕ <b>Добавление нового слота</b>\n\n"
            "Формат времени: <code>HH:MM</code>\n"
            "Например: <code>22:00</code>"
        ),
        "queue_slot_added": (
            "✅ Слот добавлен: <code>{slot}</code>\n\n"
            "⚙️ <b>Настройки слотов</b>\n\n"
            "Текущие слоты: <code>{slots}</code>"
        ),
        "queue_slot_exists": "⚠️ <code>{slot}</code> уже существует!",
        "queue_slot_max": "⚠️ Можно добавить максимум 10 слотов!",
        "queue_slot_format": (
            "⚠️ Неверный формат! Пишите в виде <code>HH:MM</code>.\n"
            "Например: <code>22:00</code>"
        ),
        "queue_slot_min": "⚠️ Должен остаться хотя бы один слот!",
        "queue_db_error": (
            "📚 <b>Очередь (Queue)</b>\n\n"
            "⚠️ Пока не удалось загрузить запланированные посты "
            "(ошибка соединения с базой).\n"
            "Пожалуйста, попробуйте ещё раз чуть позже."
        ),
        "queue_slot_reset_alert": "🔄 Слоты по умолчанию возвращены!",
        "btn_pending": "⏳ Ожидающие посты",
        "btn_queue": "📚 Очередь (Queue)",

        # --- 4-ЧАСТЬ: ⚙️ Дополнительные функции, 📖 Руководство и системные сообщения (i18n) ---

        # ⚙️ Дополнительные функции — текст и кнопки inline-меню
        "extras_menu_body": (
            "⚙️ <b>Дополнительные функции</b>\n\n"
            "✨ <b>Кнопки и реакции к посту</b> — отправьте готовый пост (текст, "
            "фото, видео, альбом или репост): исходный текст не меняется, "
            "добавляются до 10 реакций и до 10 URL-кнопок, и пост мгновенно "
            "публикуется в нужный канал\n"
            "🔤 <b>Конвертер Кириллица-Латиница</b> — конвертация текстов между "
            "двумя алфавитами\n\n"
            "Выберите нужный инструмент 👇"
        ),
        "extras_btn_enhancer": "✨ Кнопки и реакции к посту",
        "extras_btn_converter": "🔤 Конвертер Кириллица-Латиница",
        "extras_closed": "✅ Раздел <b>«Дополнительные функции»</b> закрыт.",

        # 🔤 Конвертер Латиница ⇄ Кириллица
        "conv_intro": (
            "🔤 <b>Конвертер Латиница ⇄ Кириллица:</b>\n\n"
            "Отправьте <b>текст</b> или <b>фото/видео/файл</b> (с подписью), "
            "который нужно конвертировать:\n\n"
            "<i>Для отмены нажмите '🔙 Главное меню'.</i>"
        ),
        "conv_no_text": (
            "⚠️ В этом файле текст (подпись) не найден.\n"
            "Пожалуйста, отправьте текст или файл с подписью ещё раз:"
        ),
        "conv_received": (
            "📝 <b>Текст получен!</b>\n\n"
            "В какой алфавит конвертировать? Выберите одну из кнопок ниже 👇"
        ),
        "conv_btn_cyr": "🔤 Кириллическая версия",
        "conv_btn_lat": "🔤 Латинская версия",
        "conv_no_saved_text": "⚠️ Текст не найден, отправьте его ещё раз.",
        "conv_result_title": "📋 <b>Результат:</b>",
        "conv_result_part1": "📋 <b>Результат (часть 1):</b>",
        "conv_result_part2": "📋 <b>Результат (часть 2):</b>",
        "conv_copy_hint": "<i>(Нажмите на текст, чтобы скопировать)</i>",
        "conv_cont_title": "ℹ️ <i>Продолжение текста:</i>",
        "conv_error": "⚠️ Произошла ошибка: {error}",
        "cab_converter_info": (
            "🔤 <b>Конвертер Кириллица-Латиница:</b>\n\n"
            "Отправьте текст на латинице или кириллице — я автоматически "
            "сконвертирую его.\n\n"
            "<i>Например: Salom dunyo → Салом дунё</i>"
        ),

        # ✨ Кнопки и реакции к посту (Post Enhancer)
        "enh_notice_admin": (
            "💡 <b>Примечание:</b> чтобы бот мог опубликовать пост в вашем "
            "канале, сначала убедитесь, что вы добавили его в канал как "
            "<b>Администратора</b>."
        ),
        "enh_post_request": (
            "Отправьте пост, который хотите опубликовать в канале "
            "(Текст, Фото, Видео или репост из другого канала):"
        ),
        "enh_intro_features": (
            "✅ Исходный текст не меняется — только:\n"
            "• 👍 до 10 реакций (можно вводить пакетом через пробел),\n"
            "• 🔗 до 10 URL-кнопок (с готовыми шаблонами),\n"
            "• 👁 предпросмотр по запросу и 🚀 мгновенная отправка в канал."
        ),
        "enh_preset1_title": "Подписаться на канал",
        "enh_preset1_text": "📢 Подписаться на канал",
        "enh_preset2_title": "Вступить в группу",
        "enh_preset2_text": "💬 Вступить в группу",
        "enh_preset3_title": "Перейти к боту",
        "enh_preset3_text": "🤖 Перейти к боту",
        "enh_summary": (
            "👍 Реакции: <b>{rn}/{maxr}</b>{emojis}\n"
            "🔗 URL-кнопки: <b>{bn}/{maxb}</b>"
        ),
        "enh_post_line_type": "📦 <b>Тип:</b> {type}",
        "enh_post_line_album_count": " (медиа: {n})",
        "enh_post_line_text": "\n📝 <b>Текст:</b> <i>{preview}</i>",
        "enh_post_line_no_text": "\n📝 <b>Текст:</b> <i>(без текста — только медиа)</i>",
        "enh_hub_title": (
            "✨ <b>Кнопки и реакции к посту</b>\n\n"
            "{post}\n\n"
            "{summary}\n"
            "{note}"
            "{notice}\n\n"
            "Выберите нужный шаг 👇"
        ),
        "enh_hub_btn_reacts": "👍 1. Реакции ({n}/{max})",
        "enh_hub_btn_buttons": "🔗 2. URL-кнопки ({n}/{max})",
        "enh_btn_preview": "👁️ Превью",
        "enh_btn_send_channel": "🚀 Отправить в канал",
        "enh_btn_replace": "🔁 Заменить пост",
        "enh_react_title": (
            "👍 <b>Шаг 1. Реакции</b> (<b>{n}/{max}</b>)\n\n"
            "Выбрано: {sel}\n\n"
            "• Нажмите на эмодзи — ✅ отметится, повторное нажатие уберёт его;\n"
            "• Или отправьте несколько эмодзи <b>через пробел</b> одним "
            "сообщением (например: <code>👍 ❤️ 🔥 👏 🎉</code>);\n"
            "• Можно добавить ещё <b>{left}</b> реакций.\n\n"
            "<i>Пост показывается только на этапе финального превью/"
            "подтверждения.</i>"
        ),
        "enh_react_none": "— (ничего не выбрано)",
        "enh_react_done": "➡️ Продолжить / К URL-кнопкам",
        "enh_react_done_count": "➡️ Продолжить / К URL-кнопкам ({n})",
        "enh_btn_clear": "🗑 Очистить",
        "enh_btns_title": (
            "🔗 <b>Шаг 2. URL-кнопки</b> (<b>{n}/{max}</b>)\n\n"
            "{body}\n\n"
            "Выберите готовый шаблон — бот запросит только ссылку.\n"
            "Ручной ввод: <code>Название кнопки - https://sayt.uz</code> или "
            "<code>Название кнопки | @kanalim</code>"
        ),
        "enh_btns_empty": "<i>Пока кнопок нет — выберите шаблон или введите вручную.</i>",
        "enh_btns_line": "{mark} <b>{text}</b> → <code>{url}</code>",
        "enh_btn_fallback": "Кнопка",
        "enh_btn_add_new": "➕ Добавить новую кнопку",
        "enh_btn_manual": "✍️ Ввести вручную",
        "enh_btn_confirm_send": "➡️ Подтвердить и отправить в канал",
        "enh_btn_entry_edit": "✏️ {num}. {text}",
        "enh_btn_add_title": (
            "➕ <b>Новая URL-кнопка</b> (<b>{n}/{max}</b>)\n\n"
            "Выберите один из готовых шаблонов — бот запросит <b>только "
            "ссылку</b>.\n\n"
            "Или отправьте одной строкой через <b>✍️ Ввести вручную</b>:\n"
            "<code>Название кнопки - https://sayt.uz</code>\n"
            "<code>Название кнопки | @kanalim</code>"
        ),
        "enh_channel_title": (
            "📢 <b>В какой канал отправить?</b> ({n} шт.)\n\n"
            "<i>Пост выйдет сразу в выбранном канале (без планирования). "
            "В конце будет запрошено подтверждение.</i>\n\n"
            "{notice}"
        ),
        "enh_channel_fallback": "Канал",
        "enh_channels_more": "…и ещё {n} шт. (выберите через раздел добавления каналов)",
        "enh_confirm_no_channel": "⚠️ <b>Канал не выбран.</b>\n\nВыберите канал из списка.",
        "enh_btn_channel_list": "📢 Список каналов",
        "enh_confirm_title": (
            "📢 <b>Подтвердите отправку</b>\n\n"
            "Отправить этот пост в <b>{channel}</b>?\n\n"
            "{post}\n\n"
            "{summary}\n"
            "{note}"
            "\n<i>После отправки пост изменить нельзя.</i>"
        ),
        "enh_btn_confirm_yes": "✅ Да, отправить",
        "enh_btn_preview_first": "👁️ Сначала превью",
        "enh_success_text": (
            "✅ <b>Пост опубликован!</b>\n"
            "Пост успешно опубликован в вашем канале!{where}\n\n"
            "При желании вы можете отправить этот пост и в другой канал или "
            "усилить новый пост 👇"
        ),
        "enh_success_where": "\n📢 <b>Канал:</b> {channel}",
        "enh_btn_home": "🏠 Главное меню",
        "enh_btn_other_channel": "📢 В другой канал",
        "enh_btn_new_post": "🚀 Новый пост",
        "enh_btn_finish": "❌ Завершить",
        "enh_note_admin": "👑 <i>Админ — пост выйдет чистым.</i>\n",
        "enh_note_pro": "✨ <i>PRO — без via/водяного знака, пост выйдет чистым.</i>\n",
        "enh_note_free": (
            "🆓 <i>Бесплатный план: при отправке в канал в начало поста "
            "добавится {bot}.</i>\n"
        ),
        "enh_use_buttons": (
            "👇 <b>Чтобы усилить пост, выберите одну из кнопок ниже.</b>\n"
            "Хотите заменить пост — нажмите <b>🔁 Заменить пост</b>."
        ),
        "enh_album_reject": "⚠️ Этот тип медиа нельзя добавить в альбом — отправьте отдельно:",
        "enh_empty_msg": "⚠️ Пустое сообщение не принято. Отправьте текст поста или медиа:",
        "enh_react_saved": "✅ <b>Реакции сохранены:</b> {sel}\nВсего: <b>{total}/{max}</b>{extra}",
        "enh_react_overflow_part": "\n⚠️ Лимит — <b>{max}</b> шт. — {items} не поместились.",
        "enh_react_dups_part": "\nℹ️ Повторяющиеся эмодзи не учтены.",
        "enh_react_dups": "ℹ️ Эти эмодзи уже выбраны: {items}\nВсего: <b>{total}/{max}</b>",
        "enh_react_full": (
            "⚠️ <b>Лимит реакций исчерпан</b> (макс. {max} шт.). "
            "Сначала уберите одну из них."
        ),
        "enh_react_hint_msg": (
            "ℹ️ Отправляйте только <b>эмодзи</b> — если их несколько, то "
            "<b>через пробел</b> (например: <code>👍 ❤️ 🔥 👏 🎉</code>) или "
            "используйте кнопки ниже."
        ),
        "enh_bad_link": (
            "⚠️ <b>Неверная ссылка.</b>\n\n"
            "Отправьте только ссылку, например: <code>{hint}</code>\n"
            "или <code>@kanal_ismi</code>"
        ),
        "enh_bad_format": (
            "⚠️ <b>Неверный формат кнопки.</b>\n\n"
            "Отправьте ещё раз:\n"
            "<code>Перейти на сайт - https://sayt.uz</code>\n"
            "<code>Мой канал | @kanalim</code>\n"
            "<code>https://t.me/bot_ism/start</code> (название выберется автоматически)"
        ),
        "enh_btn_limit_reached": (
            "⚠️ Можно добавить <b>не более {max} URL-кнопок</b>. "
            "Сначала удалите одну из них."
        ),
        "enh_btn_verb_saved": "сохранена",
        "enh_btn_verb_updated": "обновлена",
        "enh_btn_saved": "✅ <b>Кнопка {verb}:</b> {text} → <code>{url}</code>",
        "enh_session_expired": "⚠️ Сессия истекла — откройте меню заново.",
        "enh_home_msg": "🏠 <b>Главное меню</b> — выберите нужный раздел 👇",
        "enh_again_prompt": (
            "{notice}\n\n"
            "🚀 <b>Новый пост</b> — отправьте пост, который хотите усилить "
            "(текст, фото, видео, альбом или репост):"
        ),
        "enh_no_channels_alert": (
            "⚠️ Подключённых каналов нет — сначала подключите канал и "
            "добавьте бота в него как Администратора."
        ),
        "enh_react_limit_alert": "⚠️ Максимум {max} реакций!",
        "enh_replace_prompt": (
            "🔁 <b>Отправьте новый пост</b> — текущий пост (текст/медиа) будет "
            "заменён. Реакции и кнопки сохранятся 👇"
        ),
        "enh_channel_gone_alert": "⚠️ Этого канала больше нет в списке.",
        "enh_preset_missing": "⚠️ Шаблон не найден.",
        "enh_btn_limit_alert": "⚠️ Максимум {max} кнопок!",
        "enh_preset_prompt": (
            "{icon} <b>{num}. {title}</b>\n\n"
            "Отправьте <b>только ссылку</b> (например: <code>{hint}</code>) — "
            "название кнопки подставится автоматически.\n\n"
            "<i>Можно и полным форматом: <code>Название - https://sayt.uz</code></i>"
        ),
        "enh_btn_back_cancel": "⬅️ Отмена",
        "enh_manual_prompt": (
            "✍️ <b>Новая URL-кнопка (ручной ввод)</b>\n\n"
            "Отправьте одной строкой:\n"
            "<code>Название кнопки - https://sayt.uz</code>\n"
            "<code>Название кнопки | @kanalim</code>\n"
            "<code>Мой бот - t.me/bot_ismi/start</code>"
        ),
        "enh_btn_missing_alert": "⚠️ Кнопка не найдена.",
        "enh_edit_prompt": (
            "✏️ <b>Редактирование кнопки {num}</b>\n\n"
            "Сейчас: <b>{text}</b> → <code>{url}</code>\n\n"
            "Отправьте новое значение одной строкой:\n"
            "<code>Новое название - https://novaya-ssylka.uz</code>"
        ),
        "enh_preview_follow_note": (
            "👆 <i>Выше — превью. Кнопки появятся под этим постом в канале.</i>"
        ),
        "enh_preview_failed": "⚠️ Не удалось создать превью (медиафайл недействителен).",
        "enh_preview_error": "⚠️ Не удалось показать превью.",
        "enh_too_fast": "⏳ Слишком быстро — попробуйте ещё раз чуть позже.",
        "enh_no_channel_sel": "⚠️ Канал не выбран.",
        "enh_channel_not_owned": "⚠️ Этого канала больше нет в вашем списке.",
        "enh_prepare_failed": "⚠️ Не удалось подготовить пост. Попробуйте ещё раз.",
        "enh_send_no_rights": (
            "⚠️ Бот не администратор канала (или нет прав). "
            "Добавьте бота в канал как администратора."
        ),
        "enh_send_failed": "⚠️ Не удалось отправить: {error}",
        "enh_stale_notice": (
            "⚠️ Срок действия этого меню истёк — откройте раздел "
            "«⚙️ Дополнительные функции» заново."
        ),

        # 📖 Руководство / О боте (/help)
        "help_guide": (
            "📖 <b>PostAssistrobot — Полное руководство:</b>\n\n"
            "🔹 <b>1. Подключение канала/группы:</b>\n"
            "• Добавьте бота <b>администратором</b> канала (с правом отправки сообщений).\n"
            "• Через «👤 Кабинет & Настройки» → «📢 Мои каналы» перешлите боту любое "
            "сообщение из канала или отправьте @username.\n\n"
            "🔹 <b>2. Планирование нового поста:</b>\n"
            "• Текст, фото, видео, аудио или <b>альбом</b> (несколько фото/видео) "
            "на любую дату.\n"
            "• URL-кнопки, реакции и авто-удаление (12, 24, 48, 72 часа).\n"
            "• <i>На тарифе PRO посты автоматически выходят без рекламы (100% чистые)!</i>\n\n"
            "🔹 <b>3. ✨ AI Studio:</b>\n"
            "• Создание AI-поста, пост из фото (Vision), AI-аудит поста и контент-план.\n"
            "• Задайте вопрос или отправьте текст/фото/репост — получите "
            "профессиональный пост и стихи.\n"
            "• Команда свободным текстом: <i>«запланируй всем каналам на завтра "
            "утром в 9»</i>.\n"
            "• Редактирование поста: <i>«добавь номер телефона в конец»</i>.\n\n"
            "🔹 <b>4. Баллы и ежедневная серия (Streak):</b>\n"
            "• Заходите в бот каждый день и нажимайте <b>«🎁 Ежедневный бонус»</b>.\n"
            "• 1-й день (+1), 2-й (+1), 3-й (+2), ..., 7-й день (+4 балла)!\n\n"
            "🔹 <b>5. ⚙️ Дополнительные функции:</b>\n"
            "• ✨ Кнопки и реакции к посту — мгновенное усиление готового поста.\n"
            "• 🔤 Конвертер Латиница ⇄ Кириллица.\n\n"
            "⚙️ <b>Быстрые команды:</b>\n"
            "/start — Главное меню\n"
            "/newpost — Новый пост\n"
            "/profile — Кабинет\n"
            "/help — Руководство\n"
            "/cancel — Отмена\n\n"
            "{support}"
        ),
        "help_guide_admin": (
            "\n\n👑 <b>Команды администратора:</b>\n"
            "/admin — Панель управления\n"
            "/broadcast — Рассылка\n"
            "/stats — Статистика"
        ),
        "help_faq": (
            "❓ <b>Часто задаваемые вопросы (FAQ)</b>\n\n"
            "<b>1. Мой пост не вышел в канал — что делать?</b>\n"
            "Убедитесь, что бот — <b>администратор</b> вашего канала/группы с правом "
            "«Отправка сообщений», затем подключите его в «📢 Мои каналы».\n\n"
            "<b>2. Как получить AI-запросы (баллы)?</b>\n"
            "Нажимайте «🎁 Ежедневный бонус» каждый день, приглашайте друзей "
            "(за 1–3-го: +3, далее: +1) или перейдите на ⭐️ PRO — там AI безлимитный.\n\n"
            "<b>3. Можно ли отредактировать запланированный пост?</b>\n"
            "Да — в разделе «👤 Кабинет & Настройки» → «📅 Ожидающие посты» время, "
            "текст, кнопку и реакции меняются отдельно.\n\n"
            "<b>4. Как отключить рекламу?</b>\n"
            "⭐️ Тариф PRO делает посты и ответы бота 100% без рекламы (автоматически).\n\n"
            "<b>5. На каких языках работает бот?</b>\n"
            "На узбекском и русском. Язык меняется через "
            "«👤 Кабинет & Настройки» → «🌐 Til / Язык».\n\n"
            "{support}"
        ),
        "help_btn_faq": "❓ Частые вопросы (FAQ)",
        "help_btn_support": "💬 Связаться с поддержкой",
        "help_support_line": "👨‍💻 <b>Нужна помощь?</b> Напишите: {admin}",
        "help_admin_fallback": "администратору бота",
        "cab_guide_text": (
            "📖 <b>PostAssistrobot — Полное руководство:</b>\n\n"
            "🔹 <b>1. Планирование нового поста:</b>\n"
            "• Текст, фото, видео, аудио или <b>альбом</b> на любую дату.\n"
            "• URL-кнопки, реакции и авто-удаление.\n\n"
            "🔹 <b>2. AI-помощник:</b>\n"
            "• Задайте вопрос или отправьте текст/фото — получите профессиональный пост.\n"
            "• Свободным текстом: <i>«завтра в 9 утра — во все каналы»</i>.\n\n"
            "🔹 <b>3. Баллы и ежедневная серия:</b>\n"
            "• Заходите каждый день и получайте бонус (на 7-й день +4 балла).\n\n"
            "⚙️ <b>Быстрые команды:</b>\n"
            "/start — Главное меню\n"
            "/profile — Кабинет\n"
            "/help — Руководство\n"
            "/cancel — Отмена"
        ),

        # ⚠️ Ошибки и системные сообщения
        "sys_busy": (
            "⚠️ <b>Система временно занята.</b>\n"
            "Пожалуйста, нажмите /start чуть позже."
        ),
        "sys_stale_button": (
            "♻️ Эта кнопка устарела (бот был перезапущен). "
            "Откройте меню заново: /start"
        ),
        "sys_unexpected_error": (
            "⚠️ <b>Произошла непредвиденная ошибка.</b>\n"
            "Пожалуйста, попробуйте ещё раз чуть позже или нажмите /start."
        ),
        # 🌐 Короткие toast-сообщения (callback throttle / устаревшие меню).
        "sys_error_short": "⚠️ Произошла ошибка",
        "sys_wait_short": "⏳ Пожалуйста, подождите...",
        "admin_only_cmd": "❌ Эту команду может использовать только администратор.",
        "np_callback_wait": "⏳ Идёт обработка, пожалуйста, подождите...",
        "noop_channel_info": (
            "Это информационная кнопка. Чтобы удалить канал, нажмите "
            "соседнюю кнопку ❌."
        ),
        "ai_menu_stale": (
            "⚠️ <b>Это меню устарело.</b>\n"
            "Чтобы продолжить, нажмите кнопку ✨ AI Studio ещё раз."
        ),
        "ai_photo_stale": (
            "⚠️ <b>Это меню устарело.</b>\n"
            "Чтобы создать пост из изображения, выберите ✨ AI Studio → "
            "🖼 Создать пост из изображения ещё раз."
        ),
        "conv_timeout_msg": (
            "⏰ <b>Диалог завершён по истечении времени.</b>\n"
            "Вы вернулись в главное меню. Выберите нужный раздел заново 👇"
        ),
        "msg_closed": "✅ Закрыто.",

        # 🩺 ЭТАП 7: мониторинг состояния системы (/health — только для админов)
        "health_title": "🩺 <b>СОСТОЯНИЕ СИСТЕМЫ (System Health)</b>",
        "health_overall": "📊 <b>Общий статус:</b>",
        "health_checked_at": "🕐 Проверено: {time} (UTC)",
        "health_uptime": "⏱ Время работы: {uptime}",
        "health_db_title": "🗄 <b>База данных:</b> {status}",
        "health_db_latency": "• Время ответа Neon DB: {latency} мс",
        "health_db_error": "• Ошибка: {error}",
        "health_db_pool": "• Пул соединений: {used}/{max} занято ({available} свободно)",
        "health_scheduler_title": "⏰ <b>Планировщик (apscheduler):</b> {status}",
        "health_sched_jobs": "• Активные задачи: {count}",
        "health_posts_pending": "• ⏳ Ожидающие посты: {count}",
        "health_posts_failed": "• ⚠️ Посты с ошибками: {count}",
        "health_posts_dead": "• ☠️ Dead-letter посты: {count}",
        "health_posts_stale": "• 🧊 Застрявшие (stale) посты: {count}",
        "health_ai_title": "🤖 <b>AI-провайдеры:</b> {status}",
        "health_ai_provider": "• {name}: {status}",
        "health_system_title": "🖥 <b>Ресурсы системы:</b>",
        "health_errors": "• Ошибки — за 1 час: {hour} | 24 часа: {day}",
        "health_tasks": "• Активные asyncio-задачи: {count}",

        "cancel_done": (
            "🚫 <b>Действие отменено.</b>\n"
            "Вы вернулись в главное меню. Выберите нужный раздел 👇"
        ),
        "main_menu_hint": "Выберите нужный раздел из меню ниже 👇",
        # Неизвестное / неожиданное сообщение вне диалога — бот не молчит
        "unknown_message_fallback": (
            "Извините, я не понял это сообщение. "
            "Пожалуйста, выберите нужный раздел из меню ниже 👇"
        ),
        # Внутри диалога пришло сообщение, которое текущий шаг не принимает
        "unknown_in_dialog": (
            "⚠️ Сообщение такого типа на этом шаге не принимается. "
            "Пожалуйста, отправьте запрошенные данные или нажмите 🔙 Главное меню."
        ),
        # Стикер на шаге подготовки поста
        "np_sticker_not_allowed": (
            "Извините, стикеры не принимаются в качестве поста. "
            "Пожалуйста, отправьте фото, видео или текст"
        ),
        # Обязательная подписка на спонсорские каналы (start / проверка подписки)
        "sub_required": (
            "⚠️ <b>Чтобы полноценно пользоваться ботом, подпишитесь на "
            "официальные каналы ниже:</b>"
        ),
        "sub_confirmed": (
            "✅ Подписка подтверждена!\n\n"
            "Добро пожаловать, <b>{name}</b>! Все возможности открыты для вас.\n\n"
            "{hint}"
        ),
        "sub_not_yet_alert": (
            "⚠️ Вы ещё не подписались на все каналы! "
            "Пожалуйста, подпишитесь на все каналы."
        ),
        "sub_not_yet_msg": (
            "⚠️ Вы ещё не подписались на все каналы! "
            "Подпишитесь с помощью кнопок ниже."
        ),

        # Выбор часового пояса (Timezone)
        "tz_prompt": "🌍 <b>Выберите часовой пояс:</b>",
        "tz_changed": "✅ Часовой пояс изменён на <b>{tz}</b>.",
        "tz_btn_tashkent": "🇺🇿 Ташкент (UTC+5)",
        "tz_btn_moscow": "🇷🇺 Москва (UTC+3)",
        "tz_btn_utc": "🌐 UTC (UTC+0)",
        "tz_btn_samarkand": "🇺🇿 Самарканд (UTC+5)",
        "tz_current": "🌍 Часовой пояс: <b>{tz}</b>",

        # --- Общие операции ---
        "op_cancelled": "❌ Отменено.",
        "btn_share_referral": "🚀 Поделиться с друзьями",
        "btn_check_subscription": "✅ Проверить подписку",
        "ref_share_text": "Привет! Планируйте посты для своих Telegram-каналов автоматически и удобно с помощью этого бота:",
        "sub_sponsor_fallback": "Спонсорский канал",
        "pr_no_permission": "❌ У вас нет прав для подтверждения оплаты.",
        "pr_error": "❌ Произошла ошибка.",

        # --- AI-помощник (legacy AI_INPUT поток) ---
        "ai_analyzing": "🤖 <i>ИИ анализирует...</i>",
        "ai_legacy_welcome": (
            "🤖 <b>Добро пожаловать в AI-помощник!</b>\n\n"
            "💎 Доступно AI-запросов: {credits}\n\n"
            "Я могу помочь вам со следующим:\n"
            "❓ <b>Вопросы и ответы</b> — спрашивайте о боте, постах, баллах и каналах.\n"
            "📝 <b>Создание постов</b> — напишите тему поста или отправьте готовый пост/фото.\n"
            "🕒 <b>Свободное планирование</b> — например: <i>«подготовь пост во все каналы на сегодня 15:45»</i>.\n\n"
            "👉 Напишите тему поста или ваш вопрос.\n"
            "<i>Для выхода нажмите кнопку «{main_menu}».</i>"
        ),
        "ai_legacy_media_hint": (
            "🖼 <b>Фото/медиа получено!</b>\n\n"
            "Теперь отправьте текст поста или напишите время, например: <i>«на сегодня 18:00»</i>."
        ),
        "ai_legacy_input_hint": "Пожалуйста, отправьте текст поста, ваш вопрос или фото/файл:",
        "ai_legacy_faq_fallback": (
            "Извините, я могу помочь только с управлением Telegram-каналами "
            "и планированием постов."
        ),
        "ai_legacy_faq_footer": "\n\n<i>Задайте ещё вопрос или отправьте тему поста 👇</i>",
        "ai_legacy_no_post": "Не удалось определить текст поста. Пожалуйста, отправьте ещё раз.",
        "ai_legacy_target_all": "\n🌐 <b>Канал:</b> Во все подключённые каналы",

        # --- Получение поста из открытого канала (extract) ---
        "ext_intro": (
            "📢 <b>Получение поста из открытого канала</b>\n\n"
            "Отправьте ник ИЛИ ссылку канала:\n"
            "• <code>@kunuzofficial</code>\n"
            "• <code>https://t.me/kunuzofficial</code>\n\n"
            "Или отправьте ссылку на сайт (например: <code>https://kun.uz/</code>) — "
            "бот прочитает страницу и подготовит AI-анализ.\n\n"
            "<i>Работает только для открытых каналов.</i>"
        ),
        "ext_btn_other_post": "🔙 Выбрать другой пост",
        "ext_btn_rewrite": "🔄 Переписать",
        "ext_btn_refresh": "🔄 Обновить",
        "ext_media_preview": "🖼 Фото/Видео",
        "ext_reading_site": "⏳ Читаю сайт...",
        "ext_site_read_failed": "⚠️ Не удалось прочитать текст с сайта. Проверьте адрес и отправьте снова.",
        "ext_ai_analyzing_page": "⏳ ИИ анализирует страницу...",
        "ext_ai_page_failed": "⚠️ ИИ не смог обработать страницу.",
        "ext_ai_proposal_src": "✨ <b>Предложение ИИ ({src}):</b>\n\n{text}",
        "ext_ai_proposal": "✨ <b>Предложение ИИ:</b>\n\n{text}",
        "ext_reading_posts": "⏳ Читаю посты канала...",
        "ext_post_accepted": (
            "✅ <b>Пост принят!</b>\n\n"
            "Теперь введите кнопку, время и другие настройки."
        ),
        "ext_private_channel_full": (
            "🔒 <b>Это закрытый канал.</b>\n\n"
            "Отправьте открытый канал или канал, где вы администратор.\n"
            "Например: <code>@kunuzofficial</code> или "
            "<code>https://t.me/kunuzofficial</code>"
        ),
        "ext_private_channel": (
            "🔒 Это закрытый канал. Отправьте открытые каналы или каналы, "
            "где вы администратор."
        ),
        "ext_not_found": (
            "❌ <b>{text}</b> — такой канал не найден.\n\n"
            "Проверьте адрес и отправьте снова:\n"
            "<code>@kanal</code> или <code>https://t.me/kanal</code>"
        ),
        "ext_invalid_username": (
            "⚠️ Неверный ник или ссылка канала. Введите заново:\n"
            "<code>@kanal</code>, <code>kanal</code> или <code>https://t.me/kanal</code>\n\n"
            "Или ссылка на сайт: <code>https://kun.uz/</code>"
        ),
        "ext_empty": (
            "📭 В канале <b>{channel}</b> посты не найдены.\n\n"
            "Отправьте другой канал или ссылку на сайт:"
        ),
        "ext_read_failed": (
            "❌ Не удалось прочитать посты из канала <b>{channel}</b>.\n\n"
            "Причины:\n"
            "• Канал закрыт (private)\n"
            "• Неверный ник канала\n"
            "• В канале нет постов\n\n"
            "Попробуйте ещё раз:"
        ),
        "ext_list_header": "📢 <b>@{channel}</b> — последние посты:\n",
        "ext_list_choose": "Выберите, какой пост обработать 👇",
        "ext_media_only": "(фото/видео)",
        "ext_no_list": "⚠️ Список постов недоступен. Отправьте новый канал или ссылку на сайт:",
        "ext_no_posts": "⚠️ Посты не найдены.",
        "ext_invalid_post": "❌ Выбран неверный пост.",
        "ext_post_no_text": "⚠️ В этом посте нет текста (только фото/видео). Выберите другой пост.",
        "ext_ai_rewriting": "⏳ ИИ переписывает пост...",
        "ext_ai_rewrite_failed": "⚠️ ИИ не смог переписать пост.",
        "ext_no_post_text": "⚠️ Текст поста не найден.",
        "ext_refreshing": "🔄 Обновляю...",
        "ext_rewriting": "🔄 Переписываю...",

        # --- Контент-план (content plan) ---
        "cp_btn_create_post": "📝 Создать пост",
        "cp_btn_regenerate": "🔄 Перегенерировать",
        "cp_btn_back": "🔙 Назад",
        "cp_btn_create_on_topic": "📝 Создать пост на эту тему",
        "cp_no_channel": (
            "⚠️ <b>Сначала подключите канал.</b>\n\n"
            "Для составления контент-плана нужен хотя бы один канал.\n"
            "📢 Подключите канал в разделе «Каналы»."
        ),
        "cp_choose_channel": (
            "🧠 <b>Генератор контент-плана</b>\n\n"
            "Для какого канала составляем контент-план?"
        ),
        "cp_back_title": "🧠 <b>Для какого канала составляем контент-план?</b>",
        "cp_closed": "❌ Закрыто.",
        "cp_topic_ask": (
            "🧠 <b>Контент-план: {channel}</b>\n\n"
            "Коротко напишите тематику канала.\n\n"
            "<i>Например:</i>\n"
            "• Английский с нуля\n"
            "• Магазин кухонных товаров\n"
            "• Здоровый образ жизни\n"
            "• IT-новости"
        ),
        "cp_topic_short": "⚠️ Тема слишком короткая. Напишите минимум 3 символа.",
        "cp_ai_building": "⏳ ИИ составляет контент-план...",
        "cp_ai_failed": "⚠️ ИИ не смог составить план.",
        "cp_ai_failed_retry": "⚠️ ИИ не смог составить план. Попробуйте ещё раз.",
        "cp_plan_header": (
            "🧠 <b>Контент-план на 7 дней</b>\n"
            "📢 Канал: <b>{channel}</b>\n"
            "📝 Тема: <i>{topic}</i>\n\n"
        ),
        "cp_plan_header_new": (
            "🧠 <b>Контент-план на 7 дней (новый)</b>\n"
            "📢 Канал: <b>{channel}</b>\n"
            "📝 Тема: <i>{topic}</i>\n\n"
        ),
        "cp_plan_day": "<b>📅 {day}</b> — {fmt}\n  📌 <b>{title}</b>\n",
        "cp_plan_idea": "  <i>{idea}</i>\n",
        "cp_day_fallback": "День {n}",
        "cp_plan_footer": "\n\nВыберите день и создавайте пост прямо отсюда 👇",
        "cp_regenerating": "🔄 Перегенерирую...",
        "cp_invalid_day": "❌ Выбран неверный день.",
        "cp_day_detail": "📅 <b>{day}</b> — {fmt}\n\n📌 <b>{title}</b>\n\n{idea}\n\n{ask}",
        "cp_day_ask": "Хотите создать пост на эту тему?",
        "cp_choose_day": "📅 <b>На какой день создаём пост?</b>",
        "cp_ai_writing": "⏳ ИИ готовит текст поста...",
        "cp_ai_write_failed": "⚠️ ИИ не смог подготовить текст поста.",
        "cp_post_ready": (
            "✅ <b>Готовый пост:</b>\n\n{preview}\n\n"
            "📢 Канал: <b>{channel}</b>\n\n"
            "Теперь введите кнопку, время и другие настройки."
        ),
        "cp_button_ask": (
            "🔘 <b>Добавить кнопку?</b>\n\n"
            "Напишите текст кнопки и URL:\n"
            "<code>Текст | https://example.com</code>\n\n"
            "Или продолжите без кнопки 👇"
        ),

        # --- Подписка / оплата (subscription) ---
        "sub_pay_1m": "⭐️ 1 месяц (75 Stars)",
        "sub_pay_3m": "⭐️ 3 месяца (175 Stars)",
        "sub_pay_1y": "⭐️ 1 год (550 Stars)",
        "sub_pay_1m_full": "⭐️ На 1 месяц (75 Stars)",
        "sub_pay_3m_full": "⭐️ На 3 месяца (175 Stars)",
        "sub_pay_1y_full": "⭐️ На 1 год (550 Stars)",
        "sub_btn_promo": "🎁 Ввести промокод",
        "sub_btn_send_receipt_admin": "✉️ Отправить чек администратору",
        "sub_inv_title_1m": "⭐️ PostAssist PRO (1 месяц)",
        "sub_inv_title_3m": "⭐️ PostAssist PRO (3 месяца)",
        "sub_inv_title_1y": "⭐️ PostAssist PRO (1 год)",
        "sub_inv_desc_1m": "Полные PRO-возможности на 1 месяц",
        "sub_inv_desc_3m": "Полные PRO-возможности на 3 месяца",
        "sub_inv_desc_1y": "Полные PRO-возможности на 1 год (со скидкой)",
        "sub_invalid_plan": "❌ Выбран неверный тариф.",
        "sub_invoice_error": "⚠️ Ошибка при открытии окна оплаты. Пожалуйста, попробуйте ещё раз.",
        "sub_promo_ask": (
            "🎁 <b>Введите промокод:</b>\n\n"
            "Напишите промокод или нажмите кнопку «{back}»."
        ),
        "sub_promo_success": "✅ <b>{msg}</b>\n\nНовые возможности тарифа активированы!",
        "sub_promo_fail": "❌ <b>{msg}</b>\n\nПопробуйте ещё раз или нажмите кнопку «{back}».",
        "sub_pro_granted": (
            "🎉 <b>Поздравляем!</b>\n\n"
            "Вам предоставлен <b>PRO-тариф на {days} дн.</b>!\n"
            "Вы можете пользоваться всеми PRO-возможностями."
        ),
        "sub_pay_activate_error": (
            "⚠️ Оплата получена, но при активации тарифа произошла ошибка.\n"
            "Пожалуйста, свяжитесь с администратором."
        ),
        "sub_pay_duplicate": "✅ Этот платёж уже был обработан. Ваш PRO-тариф уже активен.",
        "sub_pay_success": (
            "🎉 <b>Оплата прошла успешно!</b>\n\n"
            "⭐️ Получено {stars} Stars.\n"
            "📅 <b>PRO-тариф на {days} дн.</b> активирован!\n\n"
            "Вы можете пользоваться всеми PRO-возможностями:\n"
            "• Безлимитные каналы\n"
            "• Безлимитный ИИ\n"
            "• Полная аналитика"
        ),
        "sub_pay_err_payload": "Неверный payload платежа.",
        "sub_pay_err_user": "Платёж не соответствует пользователю.",
        "sub_pay_err_user_id": "Неверный ID пользователя.",
        "sub_pay_err_plan": "Неверный тариф.",
        "sub_pay_err_currency": "Неверная валюта платежа.",
        "sub_pay_err_amount": "Сумма платежа не соответствует тарифу.",
        "sub_pay_err_amount_bad": "Неверная сумма платежа.",
        "sub_pay_err_incomplete": "Реквизиты платежа неполные.",
        "sub_pay_err_bad_request": "Неверный запрос платежа.",

        # --- Аналитика (analytics) ---
        "an_all_channels": "Все каналы",
        "an_btn_all": "📊 Все каналы",
        "an_btn_other": "📢 Другой канал",
        "an_btn_refresh": "🔄 Обновить",
        "an_refreshing": "🔄 Обновляю...",
        "an_free_hint": (
            "📊 <b>Аналитика</b>\n\n"
            "📌 На тарифе Free показывается статистика за последние <b>7 дней</b>.\n"
            "⭐️ На тарифе <b>PRO</b> открывается полная аналитика (30 дней, все посты, самые активные часы)!"
        ),
        "an_no_channels": (
            "⚠️ <b>У вас пока нет подключённых каналов.</b>\n\n"
            "Чтобы посмотреть статистику, сначала подключите канал."
        ),
        "an_choose": "📊 <b>Аналитика и статистика</b>\n\nСтатистику какого канала показать?",
        "an_choose_short": "📊 <b>Статистику какого канала показать?</b>",
        "an_channel_fallback": "Канал",
        "an_dash_header": "📊 <b>{channel}</b> — Статистика канала",
        "an_dash_div": "━━━━━━━━━━━━━━━━━",
        "an_dash_empty": (
            "📊 <b>{channel}</b> — Статистика канала\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📭 <b>Постов пока не было.</b>\n\n"
            "Запланируйте свой первый пост и следите за статистикой здесь!\n"
            "━━━━━━━━━━━━━━━━━"
        ),
        "an_dash_7d": "📤 За последние 7 дней: <b>{n}</b> пост.",
        "an_dash_30d": "📦 За последние 30 дней: <b>{n}</b> пост.",
        "an_dash_all": "📋 Всего выпущено: <b>{n}</b> пост.",
        "an_dash_pending": "⏳ Ожидают в очереди: <b>{n}</b> пост.",
        "an_dash_peak": "🕒 Самое активное время: <b>{hours}</b>",
        "an_dash_types": "📁 Типы постов: {types}",
        "an_dash_no_data": "Нет данных",
        "an_type_text": "Текст",
        "an_type_photo": "Фото",
        "an_type_video": "Видео",
        "an_type_document": "Документ",
        "an_type_audio": "Аудио",
        "an_type_animation": "GIF",
    # ============================================================
    # 🌐 ДАТА / ВРЕМЯ (utils.date_format) и РУЧНАЯ ПРОВЕРКА ФОТО
    # ============================================================
    "dt_today": "Сегодня",
    "dt_tomorrow": "Завтра",
    # ── 🤖 AI Studio / Vision ──
    "ai_photo_unavailable": "⚠️ ИИ не смог проанализировать это изображение. Попробуйте ещё раз через минуту.",
    "ai_target_all_line": "🌐 <b>Канал:</b> Все подключённые каналы",
    "ai_target_all_name": "Все подключённые каналы",
    # ── 📷 Ручная проверка фото (handlers/photo_check.py) ──
    "pc_sent_user": "📸 Ваше фото отправлено администратору. Ожидается подтверждение.",
    "pc_admin_caption": "🆔 ID пользователя: <code>{user_id}</code>\n📷 Получено фото.",
    "pc_btn_approve": "✅ Подтвердить",
    "pc_btn_reject": "❌ Отклонить",
    "pc_approved_admin": "✅ <b>Подтверждено!</b>\n\nПользователю <code>{user_id}</code> выдан PRO.",
    "pc_rejected_admin": "❌ <b>Отклонено.</b>\n\nPRO-запрос пользователя отклонён.",
    "pc_pro_granted": "🎉 <b>Поздравляем!</b>\n\nВам выдан <b>тариф PRO на 30 дней</b>!\nТеперь доступны все возможности PRO.",
    "pc_reject_notice": "⚠️ <b>Фото не подтверждено.</b>\n\nПопробуйте ещё раз или обратитесь к администратору @shmat_uz.",
    "pc_no_permission": "❌ Нет доступа.",
    "pc_no_pro_permission": "❌ У вас нет прав выдавать PRO пользователям.",
    "pc_bad_callback": "Некорректные данные callback.",
    "pc_bad_user_id": "Ошибка ID пользователя.",
    "pc_db_error": "Произошла ошибка.",
        "an_type_album": "Альбом",

    },
}

try:
    from locales.en_overlay import EN_OVERLAY
except ImportError:
    from en_overlay import EN_OVERLAY  # type: ignore

TRANSLATIONS["en"] = dict(TRANSLATIONS["uz"])
TRANSLATIONS["en"].update(EN_OVERLAY)


def normalize_lang(lang) -> str:
    """Faqat 'uz', 'ru' yoki 'en' qaytaradi."""
    if lang is None:
        return DEFAULT_LANG
    raw = str(lang).strip().lower()
    if raw.startswith("ru"):
        return "ru"
    if raw.startswith("en"):
        return "en"
    return DEFAULT_LANG


def detect_language(telegram_language_code) -> str:
    """Telegram ``language_code`` dan bot tilini aniqlaydi.

    'ru', 'ru-RU', 'ru-UZ' → 'ru'; aks holda → 'uz'.
    """
    return normalize_lang(telegram_language_code)


def get_text(key, lang=DEFAULT_LANG, **kwargs) -> str:
    """Lug'atdan matn olish — HECH QACHON ``KeyError`` bermaydi.

    Fallback zanjiri (3 pog'ona):
      1. Foydalanuvchi tanlagan til (masalan ``ru``);
      2. Kalit u tilda YO'Q bo'lsa — avtomatik ``uz`` (``DEFAULT_LANG``);
      3. Kalit IKKALA tilda ham yo'q bo'lsa — kalit nomining o'zi
         (``"no_such_key"``), bot crash bo'lmaydi. Kalit ham bo'sh/None
         bo'lsa — bo'sh satr.

    Formatlash xavfsizligi: ``{name}`` kabi ko'rsatkich uchun qiymat
    berilmasa yoki RU shabloni UZ bilan mos kelmasa, ``KeyError`` /
    ``IndexError`` / ``ValueError`` / ``TypeError`` handler'ni qulatmaydi —
    avval boshqa til varianti sinaladi, u ham ishlamasa formatlanmagan
    asl matn qaytariladi.
    """
    # 0) Kalit va til normallashtiriladi (None/bo'sh ham xavfsiz).
    if key is None:
        return ""
    if not isinstance(key, str):
        key = str(key)
    if not key:
        return ""

    lang = normalize_lang(lang)

    # 1) Tanlangan til → 2) DEFAULT_LANG → 3) kalitning o'zi.
    table = TRANSLATIONS.get(lang)
    if not isinstance(table, dict):
        table = {}
    fallback_table = TRANSLATIONS.get(DEFAULT_LANG)
    if not isinstance(fallback_table, dict):
        fallback_table = {}

    text = table.get(key)
    if text is None:
        text = fallback_table.get(key)
    if text is None:
        # Har ikkala tilda ham topilmadi — crash o'rniga kalitning o'zi.
        return key
    if not isinstance(text, str):
        # Lug'atga xato tur tushib qolgan bo'lsa ham yiqilmaymiz.
        text = str(text)

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            # RU shablon UZ bilan mos kelmasa (yoki format ko'rsatkichi
            # qiymat turiga mos bo'lmasa) — boshqa til varianti sinanadi.
            if lang != DEFAULT_LANG:
                alt = fallback_table.get(key)
                if isinstance(alt, str) and alt != text:
                    try:
                        return alt.format(**kwargs)
                    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
                        pass
    return text


def safe_t(key, lang=DEFAULT_LANG, **kwargs) -> str:
    """Xavfsiz tarjima — HECH QACHON istisno (exception) bermaydi.

    Fallback zanjiri: ``lang`` → ``uz`` (``DEFAULT_LANG``) → kalit nomi.
    ``get_text()`` ning mustahkamlangan o'rami: kutilmagan xatolikda ham
    (masalan, lug'at buzilgan bo'lsa) kalit nomi (yoki bo'sh satr)
    qaytariladi — handler hech qachon qulamaydi.
    """
    try:
        return get_text(key, lang, **kwargs)
    except Exception:
        try:
            if key is None:
                return ""
            return key if isinstance(key, str) else str(key)
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# 🔘 REPLY-KLAVIATURA TUGMA MATNLARI — uchala tilda bir xil ishonchli
# ---------------------------------------------------------------------------
# Pastki (reply) klaviatura tugmalari foydalanuvchi TILIDA chiziladi:
# UZ "➕ Yangi post" | RU "➕ Новый пост" | EN "➕ New post".
# Shu sababli filtrlar va qo'lda solishtiruvchi handlerlar ham AYNAN shu uch
# matnni (va eski/variant yozilishlarini) TANISHI kerak. Aks holda tugma
# bosilganda javob "kutilmagan xabar" fallback'iga tushib qoladi.
#
# ``button_texts`` / ``is_button_text`` — shu ishning yagona manbasi:
#   • kalit bo'yicha uz/ru/en yorliqlarini yig'adi (takrorlanishlarsiz);
#   • solishtirishda NBSP, qo'shimcha probellar, emoji variatsiya tanlagichi
#     (\ufe0f) va boshidagi emoji/simvollar CHETLA O'TADI — ya'ni foydalanuvchi
#     "Yangi post" deb yozsa ham tugma ishlaydi.

#: Boshidagi emoji/punktni olib tashlash uchun (\w — kirill va o'zbek
#: lotin belgilarini ham "harf" deb hisoblaydi).
_BTN_LEADING_SYMBOLS_RE = re.compile(r"^[^\w]+", re.UNICODE)
_BTN_SPACES_RE = re.compile(r"\s+")

#: Kirill → lotin gomoglifi (tashqi jihatdan bir xil harflar). Foydalanuvchi
#: tugma matnini QO'lda yozganda (masalan "👤 Profil / Sozlamaлar") klaviatura
#: tilidagi harflar bilan aralash yozuv paydo bo'ladi — normallashtirishda
#: ular lotinsha ko'rinishga keltiriladi, shunda solishtiruv baribir yopiladi.
#: Eski/yangi formatni buzmaydi: ikkala tomon ham bir xil funksiya orqadan o'tadi.
_BTN_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
})


def normalize_button_text(text) -> str:
    """Tugma matnini solishtirishga tayyorlaydi (xavfsiz, istisno bermaydi).

    • ``\\xa0`` (NBSP) va ``\\u200b`` (zero-width) tozalanadi;
    • ketma-ket probellar bittaga tushadi, chetdagi bo'shliqlar olinadi;
    • emoji variatsiya tanlagichlari (``\\ufe0f``/``\\ufe0e``) olib tashlanadi
      — Telegram mijozlari "⭐️ Premium" ni ba'zan "⭐ Premium" qilib yuboradi;
    • katta/kichik harf farqi bekor qilinadi.
    """
    if text is None:
        return ""
    raw = text if isinstance(text, str) else str(text)
    cleaned = raw.replace("\u00a0", " ").replace("\u200b", "").replace("\u200e", "")
    cleaned = cleaned.replace("\ufe0f", "").replace("\ufe0e", "")
    cleaned = _BTN_SPACES_RE.sub(" ", cleaned).strip()
    return cleaned.casefold().translate(_BTN_HOMOGLYPHS)


def button_variants(text) -> tuple:
    """Berilgan matn uchun QABUL QILINADIGAN normallashtirilgan shakllar.

    To'liq matn + boshidagi emoji/simvollarsiz shakl (masalan
    "➕ New post" → {"➕ new post", "new post"}).
    """
    norm = normalize_button_text(text)
    if not norm:
        return ()
    out = [norm]
    bare = _BTN_LEADING_SYMBOLS_RE.sub("", norm).strip()
    if bare and bare not in out:
        out.append(bare)
    return tuple(out)


def button_texts(*keys, langs=SUPPORTED_LANGS, extra=()) -> tuple:
    """Lug'at kalitlarining BARCHA tildagi tugma matnlari (tartib saqlangan).

    Args:
        *keys:  ``TRANSLATIONS`` kalitlari (masalan ``"btn_new_post"``).
        langs:  qaysi tillar yig'iladi (standart: uz, ru, en).
        extra:  qo'shimcha alias matnlar (eski klaviatura yorliqlari...).

    Returns:
        Takrorlanmagan matnlar tuple'i — ``exact()``/``filters.Text()`` ga
        to'g'ridan-to'g'ri berish mumkin.
    """
    out = []
    for key in keys:
        for code in langs:
            if not has_key(key, code):
                # Lug'atda yo'q kalit — ``get_text`` kalit nomining o'zini
                # qaytaradi; uni tugma matni deb yubormaymiz.
                continue
            value = get_text(key, code)
            if not isinstance(value, str):
                continue
            value = value.strip()
            if value and value not in out:
                out.append(value)
    for value in extra:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value not in out:
            out.append(value)
    return tuple(out)


def is_button_text(text, *keys, langs=SUPPORTED_LANGS, extra=()) -> bool:
    """``text`` ushbu tugmalarning ISTALGANI (istalgan tilda) bilan mosmi?

    Handlerlar ichida ``text == BTN_X`` kabi qattiq solishtiruv o'rniga
    ishlatiladi — shunda klaviatura UZ/RU/EN tilda chizilganiga qaramay
    tugma BIR XIL ishlaydi.
    """
    needle_variants = button_variants(text)
    if not needle_variants:
        return False
    candidates = button_texts(*keys, langs=langs, extra=extra)
    if not candidates:
        return False
    for cand in candidates:
        for shape in button_variants(cand):
            if shape in needle_variants:
                return True
    return False


def is_main_menu_text(text) -> bool:
    """Matn biror tildagi «Asosiy menyu» tugmasi matniga mosmi?

    ConversationHandler'larning bekor/orqaga tekshiruvlarida ishlatiladi:
    foydalanuvchi RU/EN tanlagan bo'lsa ham menyu tugmasi to'g'ri
    taniladi (avval faqat UZ matnlar tekshirilardi).
    """
    if not text or not isinstance(text, str):
        return False
    # Eski oqimlardagi «🔙 Orqaga» varianti (orqaga moslik uchun).
    return is_button_text(text, "btn_main_menu", extra=("🔙 Orqaga",))


# ---------------------------------------------------------------------------
# Lug'at paritetini (UZ ↔ RU) tekshirish yordamchilari
# ---------------------------------------------------------------------------

def missing_keys(lang: str, reference: str = DEFAULT_LANG) -> list:
    """``reference`` tilida bor, lekin ``lang`` da YO'Q kalitlar ro'yxati."""
    ref = TRANSLATIONS.get(reference) or {}
    target = TRANSLATIONS.get(normalize_lang(lang)) or {}
    return sorted(set(ref) - set(target))


def translation_parity_report() -> dict:
    """UZ / RU / EN bo'limlari orasidagi TO'LIQ paritet hisoboti.

    Qaytaradi::

        {
            "uz_only": [...],        # faqat UZ'da bor kalitlar
            "ru_only": [...],        # faqat RU'da bor kalitlar
            "en_only": [...],        # faqat EN'da bor kalitlar
            "en_missing": [...],     # UZ'da bor, lekin EN_OVERLAY'da YO'Q kalitlar
            "total": 754,            # umumiy noyob kalitlar soni
            "in_sync": True,         # UZ ↔ RU to'liq paritet bormi
            "en_in_sync": True,      # EN ham UZ bilan to'liq qoplanganmi
            "all_in_sync": True,     # uchala til bir xil kalit to'plami
        }

    Eslatma: EN lug'ati ``TRANSLATIONS["uz"]`` dan nusxalanib, ustiga
    ``EN_OVERLAY`` qo'yilgani uchun kalitlar soni har doim teng chiqadi —
    lekin overlay'da YO'Q kalit jimgina o'zbekcha matn qaytaradi. Shu
    sababli ``en_missing`` (overlay qamrovi) ham hisobotga qo'shildi.
    """
    uz_keys = set(TRANSLATIONS.get("uz") or {})
    ru_keys = set(TRANSLATIONS.get("ru") or {})
    en_keys = set(TRANSLATIONS.get("en") or {})
    uz_only = sorted(uz_keys - ru_keys)
    ru_only = sorted(ru_keys - uz_keys)
    en_only = sorted(en_keys - uz_keys - ru_keys)
    try:
        overlay_keys = set(EN_OVERLAY or {})
    except Exception:  # pragma: no cover - himoya
        overlay_keys = set()
    # UZ'da bor, lekin EN overlay'da YO'Q kalitlar — ular EN'da o'zbekcha
    # chiqadi (jimgina buzilish). Bo'sh bo'lishi SHART.
    en_missing = sorted((uz_keys | ru_keys) - overlay_keys)
    return {
        "uz_only": uz_only,
        "ru_only": ru_only,
        "en_only": en_only,
        "en_missing": en_missing,
        "total": len(uz_keys | ru_keys | en_keys),
        "in_sync": not uz_only and not ru_only,
        "en_in_sync": not en_missing and not en_only,
        "all_in_sync": not uz_only and not ru_only and not en_missing and not en_only,
    }


def format_args(value) -> set:
    """Matndagi ``{name}`` ko'rsatkichlari to'plami (xavfsiz, hech qachon yiqilmaydi).

    Faqat NOMI qaytariladi — format spetsifikatsiyasi (``{n:,}``),
    konversiya (``{n!r}``) va atribut/indeks (``{user.name}``) dan tozalanadi,
    chunki paritet tekshiruvi uchun faqat argument nomlari ahamiyatli.
    """
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:  # pragma: no cover - himoya
        return set()
    names = set()
    try:
        for _literal, field, _spec, _conv in string.Formatter().parse(text):
            if not field:
                continue
            name = str(field)
            # "{n:>5}" → "n", "{n!r}" → "n", "{user.name}" → "user"
            name = name.split("!")[0].split(":")[0]
            name = name.split(".")[0].split("[")[0]
            if name:
                names.add(name)
    except (ValueError, AttributeError, TypeError, IndexError):
        return set()
    return names


def translation_format_report(langs=SUPPORTED_LANGS, reference: str = DEFAULT_LANG) -> dict:
    """Uchala tildagi format argumentlari ({user_id}, {days}, {balance}, ...) pariteti.

    Qaytaradi::

        {
            "mismatch": [{"key": "credits_value",
                          "args": {"uz": {"n"}, "ru": {"n"}, "en": {"n"}}}],
            "keys": 754,          # tekshirilgan kalitlar soni
            "in_sync": True,      # barcha kalitlarda argumentlar bir xil
            "empty": [...],       # bo'sh/None qiymatli kalitlar
        }

    Argumentlar mos kelmasa ``get_text`` formatlashdan qochib boshqa til
    variantiga o'tadi — ya'ni foydalanuvchi noto'g'ri tildagi matn ko'radi.
    Shu sababli bu hisobot ``100%`` bo'lishi kerak.
    """
    tables = {code: (TRANSLATIONS.get(code) or {}) for code in langs}
    ref_table = tables.get(reference) or {}
    mismatch = []
    empty = []
    for key in sorted(ref_table):
        per_lang = {code: format_args(table.get(key)) for code, table in tables.items()}
        values = {code: (table.get(key) if isinstance(table.get(key), str) else "")
                  for code, table in tables.items()}
        if any(not str(v).strip() for v in values.values()):
            empty.append(key)
        unique = {frozenset(args) for args in per_lang.values()}
        if len(unique) > 1:
            mismatch.append({"key": key, "args": {c: sorted(a) for c, a in per_lang.items()}})
    return {
        "mismatch": mismatch,
        "keys": len(ref_table),
        "in_sync": not mismatch,
        "empty": empty,
    }


# ---------------------------------------------------------------------------
# AI TIL QOIDALARI (UZ / RU / EN) — YAGONA MANBA (single source of truth)
# ---------------------------------------------------------------------------
# AI har bir foydalanuvchiga FAQAT uning tilida javob qaytarishi shart.
# Qoidalar shu yerda (i18n qatlami) saqlanadi; ``utils/ai_agent.py`` va
# ``services/ai_service.py`` aynan shu lug'atni ishlatadi — natijada prompt
# matni va testlar hech qachon bir-biridan chetga chiqmaydi.
AI_LANGUAGE_RULES = {
    "uz": "Barcha tahlil, post, reja va tavsiyalarni FAQAT O'ZBEK TILIDA yoz.",
    "ru": "Все ответы, посты, контент-планы и рекомендации пиши СТРОГО НА РУССКОМ ЯЗЫКЕ.",
    "en": "Provide all analysis, posts, content plans, and recommendations STRICTLY IN ENGLISH.",
}

#: Tilga xos "aralashtirma" ogohlantiruvi (prompt ichidagi qat'iy blok uchun).
AI_LANGUAGE_GUARDS = {
    "uz": (
        "Hech qanday holatda ruscha, inglizcha yoki boshqa tilni aralashtirma. "
        "Javob FAQAT o'zbek tilida, boshidan oxirigacha bir tilda bo'lsin "
        "(texnik JSON kalitlari bundan mustasno)."
    ),
    "ru": (
        "Ни в коем случае не смешивай языки: не добавляй узбекский или "
        "английский текст. Ответ ТОЛЬКО на русском языке от начала до конца "
        "(кроме технических ключей JSON)."
    ),
    "en": (
        "Never mix in any other language — no Uzbek, no Russian. "
        "The answer must be ONLY in English from the first word to the last "
        "(technical JSON keys are the only exception)."
    ),
}

#: Tizim promptidagi qat'iy til blokining sarlavhasi (til nomi bilan).
AI_LANGUAGE_NAMES = {
    "uz": "O'ZBEK TILI (UZ)",
    "ru": "РУССКИЙ ЯЗЫК (RU)",
    "en": "ENGLISH (EN)",
}

#: ``with_language()`` qo'llanilganligini bildiruvchi marker (idempotentlik uchun).
AI_LANGUAGE_MARKER = "STRICT LANGUAGE RULE"


def ai_language_rule(lang) -> str:
    """Foydalanuvchi tili uchun qat'iy til qoidasi (uz/ru/en)."""
    return AI_LANGUAGE_RULES.get(normalize_lang(lang), AI_LANGUAGE_RULES[DEFAULT_LANG])


def build_ai_language_directive(lang) -> str:
    """AI tizim promptining eng yuqorisiga qo'yiladigan qat'iy til bloki.

    Misol (``lang='ru'``)::

        ================= STRICT LANGUAGE RULE (РУССКИЙ ЯЗЫК (RU)) =================
        Все ответы, посты и рекомендации пиши СТРОГО НА РУССКОМ ЯЗЫКЕ.
        Ни в коем случае не смешивай языки: ...
        ================= END OF LANGUAGE RULE =================
    """
    code = normalize_lang(lang)
    rule = AI_LANGUAGE_RULES.get(code, AI_LANGUAGE_RULES[DEFAULT_LANG])
    guard = AI_LANGUAGE_GUARDS.get(code, AI_LANGUAGE_GUARDS[DEFAULT_LANG])
    name = AI_LANGUAGE_NAMES.get(code, AI_LANGUAGE_NAMES[DEFAULT_LANG])
    return (
        f"================= {AI_LANGUAGE_MARKER} ({name}) =================\n"
        f"{rule}\n"
        f"{guard}\n"
        f"================= END OF LANGUAGE RULE ================="
    )


def has_key(key, lang: str = None) -> bool:
    """Kalit lug'atda mavjudmi (``lang`` berilmasa — istalgan tilda)."""
    if not key:
        return False
    if lang is None:
        return any(key in (TRANSLATIONS.get(code) or {}) for code in SUPPORTED_LANGS)
    return key in (TRANSLATIONS.get(normalize_lang(lang)) or {})



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
        # Promo-kod xabarlari (services/promo_service.py).
        "Promo-kod kiritilmadi.": "Промокод не введён.",
        "Promo-kod topilmadi.": "Промокод не найден.",
        "Bu promo-kod o'chirilgan.": "Этот промокод отключён.",
        "Bu promo-kod muddati o'tgan.": "Срок действия этого промокода истёк.",
        "Bu promo-kod ishlatib bo'lingan.": "Этот промокод уже использован.",
        "Siz bu promo-kodni avval ishlatgansiz.": "Вы уже использовали этот промокод.",
        "Xatolik yuz berdi.": "Произошла ошибка.",
    },
    "en": {
        "Foydalanuvchi topilmadi.": "User not found.",
        "Siz bugungi bonusingizni olgansiz! Ertaga yana kiring.": (
            "You have already claimed today's bonus! Come back tomorrow."
        ),
        "Tizim xatoligi yuz berdi.": "A system error occurred.",
        "O'zingizga ball o'tkaza olmaysiz.": (
            "You cannot transfer credits to yourself."
        ),
        "O'tkazish miqdori kamida 3 ta, ko'pi bilan 20 ta bo'lishi kerak.": (
            "Transfer amount must be at least 3 and at most 20 credits."
        ),
        "Hisobingizda yetarli ball mavjud emas.": (
            "You don't have enough credits."
        ),
        "Qabul qiluvchi foydalanuvchi topilmadi.": "Recipient not found.",
        "Ballar muvaffaqiyatli o'tkazildi!": "Credits transferred successfully!",
        (
            "⚠️ <b>Xavfsizlik qoidasi:</b> Yangi ro'yxatdan o'tgan "
            "foydalanuvchilar ballarni <b>3 kun o'tgach</b> boshqalarga "
            "ulasha oladi."
        ): (
            "⚠️ <b>Security rule:</b> newly registered users can transfer credits to others "
            "<b>after 3 days</b>."
        ),
        # Promo-kod xabarlari (services/promo_service.py).
        "Promo-kod kiritilmadi.": "No promo code entered.",
        "Promo-kod topilmadi.": "Promo code not found.",
        "Bu promo-kod o'chirilgan.": "This promo code is disabled.",
        "Bu promo-kod muddati o'tgan.": "This promo code has expired.",
        "Bu promo-kod ishlatib bo'lingan.": "This promo code has already been used.",
        "Siz bu promo-kodni avval ishlatgansiz.": "You have already used this promo code.",
        "Xatolik yuz berdi.": "An error occurred.",
    },
}


# Dinamik DB xabarlari uchun regex andozalar:
# (pattern, ru_shablon, en_shablon). Guruhlar ``{g1}``, ``{g2}`` ... orqali
# shablonga qo'yiladi. Masalan promo muvaffaqiyat xabari:
# ``"Promo-kod faollashtirildi! 30 kunlik PRO tarif yoqildi."``
DB_MESSAGE_PATTERNS = [
    (
        r"^Promo-kod faollashtirildi! (\d+) kunlik (.+) tarif yoqildi\.$",
        "Промокод активирован! Тариф {g2} на {g1} дн. включён.",
        "Promo code activated! The {g2} plan for {g1} days is enabled.",
    ),
]


def localize_db_message(message, lang="uz") -> str:
    """DB dan kelgan tayyor xabarni foydalanuvchi tiliga o'giradi.

    Avval aniq moslik (``DB_MESSAGE_TRANSLATIONS``), keyin dinamik
    andozalar (``DB_MESSAGE_PATTERNS``) sinaladi. Tarjima topilmasa
    (yoki til o'zbekcha bo'lsa) asl matn qaytariladi.
    """
    if message is None:
        return ""
    text = str(message)
    code = normalize_lang(lang)
    if code == DEFAULT_LANG:
        return text
    table = DB_MESSAGE_TRANSLATIONS.get(code) or {}
    hit = table.get(text.strip())
    if hit is not None:
        return hit
    for pattern, ru_tpl, en_tpl in DB_MESSAGE_PATTERNS:
        try:
            m = re.match(pattern, text.strip(), re.DOTALL)
        except re.error:
            continue
        if m:
            tpl = ru_tpl if code == "ru" else en_tpl
            try:
                return tpl.format(
                    **{f"g{i + 1}": g for i, g in enumerate(m.groups())}
                )
            except (KeyError, IndexError, ValueError):
                return text
    return text


# --- AI/servis qatlamidan qaytadigan xatoliklar tarjimalari ---
# ``utils/ai_agent.py`` va ``utils/channel_reader.py`` funksiyalari
# ``{"error": "..."}`` ko'rinishida o'zbekcha xabar qaytaradi; handler'lar
# uni bevosita ko'rsatadi. Bu lug'at + prefiks qoidalari RU/EN
# foydalanuvchilarga o'z tilidagi xabarni ko'rsatadi. Texnik tafsilot
# (``{e}``) saqlanib qoladi — faqat o'zbekcha o'ram tarjima qilinadi.
SERVICE_ERROR_TRANSLATIONS = {
    "ru": {
        "Matn bo'sh.": "Текст пуст.",
        "Javob formati noto'g'ri": "Неверный формат ответа",
        "⚠️ AI javobi bo'sh qaytdi. Asl matningiz saqlab qolindi.": (
            "⚠️ ИИ вернул пустой ответ. Ваш исходный текст сохранён."
        ),
        "⚠️ Kanal postlari tarixi bo'sh — uslubni tahlil qilib bo'lmadi.": (
            "⚠️ История постов канала пуста — не удалось проанализировать стиль."
        ),
        "⚠️ AI xizmatida vaqtinchalik uzilish. Qaytadan urinib ko'ring.": (
            "⚠️ Временный сбой сервиса ИИ. Попробуйте ещё раз."
        ),
        "⚠️ AI kanal uslubini aniqlay olmadi. Qaytadan urinib ko'ring.": (
            "⚠️ ИИ не смог определить стиль канала. Попробуйте ещё раз."
        ),
        "⚠️ Mavzu kiritilmadi.": "⚠️ Тема не введена.",
        "⚠️ AI reja tuza olmadi. Qaytadan urinib ko'ring.": (
            "⚠️ ИИ не смог составить план. Попробуйте ещё раз."
        ),
        "⚠️ AI post matni tayyorlay olmadi.": (
            "⚠️ ИИ не смог подготовить текст поста."
        ),
        "⚠️ Post matni bo'sh.": "⚠️ Текст поста пуст.",
        "⚠️ AI rasmni tahlil qila olmadi (bo'sh javob). Iltimos, qayta urinib ko'ring.": (
            "⚠️ ИИ не смог проанализировать изображение (пустой ответ). "
            "Пожалуйста, попробуйте ещё раз."
        ),
        "🚫 Kechirasiz, bu rasm kontent xavfsizligi talablariga mos kelmaydi. Iltimos, boshqa rasm yuboring.": (
            "🚫 Извините, это изображение не соответствует требованиям "
            "безопасности контента. Пожалуйста, отправьте другое изображение."
        ),
        "🔑 Gemini API kaliti noto'g'ri yoki yaroqsiz. Iltimos, admin bilan bog'laning.": (
            "🔑 Ключ Gemini API неверный или недействительный. "
            "Пожалуйста, свяжитесь с администратором."
        ),
        "⏳ Gemini API hozircha band (rate limit / kvota). Iltimos, 1-2 daqiqa kuting va qayta urinib ko'ring.": (
            "⏳ Gemini API сейчас занят (rate limit / квота). "
            "Пожалуйста, подождите 1–2 минуты и попробуйте ещё раз."
        ),
        "🤖 Rasm tahlili modeli yangilanishi kerak (server sozlamasi). Iltimos, birozdan so'ng qayta urinib ko'ring yoki admin bilan bog'laning.": (
            "🤖 Модель анализа изображений нуждается в обновлении (настройка сервера). "
            "Пожалуйста, попробуйте позже или свяжитесь с администратором."
        ),
        "📦 Rasm hajmi juda katta. Iltimos, kichikroq rasm yuboring.": (
            "📦 Изображение слишком большое. Пожалуйста, отправьте изображение поменьше."
        ),
        "🖼 Rasm formati qo'llab-quvvatlanmaydi. JPG, PNG yoki WEBP formatidagi rasm yuboring.": (
            "🖼 Формат изображения не поддерживается. "
            "Отправьте изображение в формате JPG, PNG или WEBP."
        ),
        "⏱ AI rasmni tahlil qilishda vaqt tugadi. Tarmoq holatini tekshirib, qayta urinib ko'ring.": (
            "⏱ Время анализа изображения истекло. "
            "Проверьте сеть и попробуйте ещё раз."
        ),
        "⚠️ AI javob bermadi.": "⚠️ ИИ не ответил.",
        "⚠️ AI rasmni tahlil qila olmadi. Iltimos, birozdan so'ng qayta urinib ko'ring.": (
            "⚠️ ИИ не смог проанализировать изображение. "
            "Пожалуйста, попробуйте чуть позже."
        ),
        "⏳ <b>AI rasmni tahlil qilishga ulgurmadi.</b>\n\nServer hozir band ko'rinadi. Iltimos, bir daqiqadan so'ng qayta urinib ko'ring yoki kichikroq rasm yuboring. 🙏": (
            "⏳ <b>ИИ не успел проанализировать изображение.</b>\n\n"
            "Похоже, сервер сейчас занят. Пожалуйста, попробуйте через минуту "
            "или отправьте изображение поменьше. 🙏"
        ),
        "🖼 Bu fayl rasm emas yoki formati qo'llab-quvvatlanmaydi. JPG, PNG yoki WEBP yuboring.": (
            "🖼 Этот файл — не изображение или его формат не поддерживается. "
            "Отправьте JPG, PNG или WEBP."
        ),
        "🔑 Rasm tahlili uchun Gemini API kaliti kerak: <b>GEMINI_API_KEY</b> o'rnatilmagan. Iltimos, keyinroq qayta urinib ko'ring.": (
            "🔑 Для анализа изображений нужен ключ Gemini API: "
            "<b>GEMINI_API_KEY</b> не установлен. Пожалуйста, попробуйте позже."
        ),
        "⚠️ BOT_TOKEN topilmadi — rasmni yuklab bo'lmadi.": (
            "⚠️ BOT_TOKEN не найден — не удалось загрузить изображение."
        ),
        "⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.": (
            "⚠️ Не удалось загрузить изображение. Пожалуйста, попробуйте ещё раз."
        ),
        "⚠️ Rasm fayli bo'sh. Boshqa rasm yuboring.": (
            "⚠️ Файл изображения пуст. Отправьте другое изображение."
        ),
        "⚠️ Rasm faylini topib bo'lmadi. Rasmni qaytadan yuboring.": (
            "⚠️ Не удалось найти файл изображения. Отправьте фото ещё раз."
        ),
        "⚠️ Rasm faylini o'qib bo'lmadi. Rasmni qaytadan yuboring.": (
            "⚠️ Не удалось прочитать файл изображения. Отправьте фото ещё раз."
        ),
        "⚠️ Sayt manzili bo'sh.": "⚠️ Адрес сайта пуст.",
        "⚠️ Noto'g'ri sayt manzili. Qaytadan kiriting.": (
            "⚠️ Неверный адрес сайта. Введите заново."
        ),
        "⚠️ Bu Telegram havolasi. Iltimos, oddiy sayt manzilini yuboring.": (
            "⚠️ Это ссылка Telegram. Пожалуйста, отправьте обычный адрес сайта."
        ),
        "⚠️ Saytga ulanib bo'lmadi. Manzilni tekshirib, qayta yuboring.": (
            "⚠️ Не удалось подключиться к сайту. Проверьте адрес и отправьте снова."
        ),
        "⚠️ Bu havola matnli sahifa emas (rasm/fayl). Matnli sahifa havolasini yuboring.": (
            "⚠️ Эта ссылка — не текстовая страница (фото/файл). "
            "Отправьте ссылку на текстовую страницу."
        ),
        "⚠️ Saytdan matn o'qib bo'lmadi. Boshqa havolani urinib ko'ring.": (
            "⚠️ Не удалось прочитать текст с сайта. Попробуйте другую ссылку."
        ),
    },
    "en": {
        "Matn bo'sh.": "Text is empty.",
        "Javob formati noto'g'ri": "Invalid response format",
        "⚠️ AI javobi bo'sh qaytdi. Asl matningiz saqlab qolindi.": (
            "⚠️ AI returned an empty reply. Your original text was kept."
        ),
        "⚠️ Kanal postlari tarixi bo'sh — uslubni tahlil qilib bo'lmadi.": (
            "⚠️ Channel post history is empty — could not analyze the style."
        ),
        "⚠️ AI xizmatida vaqtinchalik uzilish. Qaytadan urinib ko'ring.": (
            "⚠️ Temporary AI service outage. Please try again."
        ),
        "⚠️ AI kanal uslubini aniqlay olmadi. Qaytadan urinib ko'ring.": (
            "⚠️ AI could not detect the channel style. Please try again."
        ),
        "⚠️ Mavzu kiritilmadi.": "⚠️ No topic entered.",
        "⚠️ AI reja tuza olmadi. Qaytadan urinib ko'ring.": (
            "⚠️ AI could not build the plan. Please try again."
        ),
        "⚠️ AI post matni tayyorlay olmadi.": (
            "⚠️ AI could not prepare the post text."
        ),
        "⚠️ Post matni bo'sh.": "⚠️ Post text is empty.",
        "⚠️ AI rasmni tahlil qila olmadi (bo'sh javob). Iltimos, qayta urinib ko'ring.": (
            "⚠️ AI could not analyze the image (empty reply). Please try again."
        ),
        "🚫 Kechirasiz, bu rasm kontent xavfsizligi talablariga mos kelmaydi. Iltimos, boshqa rasm yuboring.": (
            "🚫 Sorry, this image does not meet content safety requirements. "
            "Please send another image."
        ),
        "🔑 Gemini API kaliti noto'g'ri yoki yaroqsiz. Iltimos, admin bilan bog'laning.": (
            "🔑 The Gemini API key is invalid. Please contact the admin."
        ),
        "⏳ Gemini API hozircha band (rate limit / kvota). Iltimos, 1-2 daqiqa kuting va qayta urinib ko'ring.": (
            "⏳ Gemini API is busy right now (rate limit / quota). "
            "Please wait 1–2 minutes and try again."
        ),
        "🤖 Rasm tahlili modeli yangilanishi kerak (server sozlamasi). Iltimos, birozdan so'ng qayta urinib ko'ring yoki admin bilan bog'laning.": (
            "🤖 The image analysis model needs an update (server setting). "
            "Please try again later or contact the admin."
        ),
        "📦 Rasm hajmi juda katta. Iltimos, kichikroq rasm yuboring.": (
            "📦 The image is too large. Please send a smaller image."
        ),
        "🖼 Rasm formati qo'llab-quvvatlanmaydi. JPG, PNG yoki WEBP formatidagi rasm yuboring.": (
            "🖼 Image format not supported. Send an image in JPG, PNG or WEBP format."
        ),
        "⏱ AI rasmni tahlil qilishda vaqt tugadi. Tarmoq holatini tekshirib, qayta urinib ko'ring.": (
            "⏱ Image analysis timed out. Check your connection and try again."
        ),
        "⚠️ AI javob bermadi.": "⚠️ AI did not respond.",
        "⚠️ AI rasmni tahlil qila olmadi. Iltimos, birozdan so'ng qayta urinib ko'ring.": (
            "⚠️ AI could not analyze the image. Please try again shortly."
        ),
        "⏳ <b>AI rasmni tahlil qilishga ulgurmadi.</b>\n\nServer hozir band ko'rinadi. Iltimos, bir daqiqadan so'ng qayta urinib ko'ring yoki kichikroq rasm yuboring. 🙏": (
            "⏳ <b>AI did not manage to analyze the image in time.</b>\n\n"
            "The server seems busy right now. Please try again in a minute "
            "or send a smaller image. 🙏"
        ),
        "🖼 Bu fayl rasm emas yoki formati qo'llab-quvvatlanmaydi. JPG, PNG yoki WEBP yuboring.": (
            "🖼 This file is not an image or its format is not supported. "
            "Send JPG, PNG or WEBP."
        ),
        "🔑 Rasm tahlili uchun Gemini API kaliti kerak: <b>GEMINI_API_KEY</b> o'rnatilmagan. Iltimos, keyinroq qayta urinib ko'ring.": (
            "🔑 Image analysis needs a Gemini API key: "
            "<b>GEMINI_API_KEY</b> is not set. Please try again later."
        ),
        "⚠️ BOT_TOKEN topilmadi — rasmni yuklab bo'lmadi.": (
            "⚠️ BOT_TOKEN not found — could not download the image."
        ),
        "⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.": (
            "⚠️ Could not download the image. Please try again."
        ),
        "⚠️ Rasm fayli bo'sh. Boshqa rasm yuboring.": (
            "⚠️ The image file is empty. Send another image."
        ),
        "⚠️ Rasm faylini topib bo'lmadi. Rasmni qaytadan yuboring.": (
            "⚠️ Could not find the image file. Please resend the photo."
        ),
        "⚠️ Rasm faylini o'qib bo'lmadi. Rasmni qaytadan yuboring.": (
            "⚠️ Could not read the image file. Please resend the photo."
        ),
        "⚠️ Sayt manzili bo'sh.": "⚠️ Site address is empty.",
        "⚠️ Noto'g'ri sayt manzili. Qaytadan kiriting.": (
            "⚠️ Invalid site address. Please re-enter."
        ),
        "⚠️ Bu Telegram havolasi. Iltimos, oddiy sayt manzilini yuboring.": (
            "⚠️ This is a Telegram link. Please send a regular site address."
        ),
        "⚠️ Saytga ulanib bo'lmadi. Manzilni tekshirib, qayta yuboring.": (
            "⚠️ Could not connect to the site. Check the address and resend."
        ),
        "⚠️ Bu havola matnli sahifa emas (rasm/fayl). Matnli sahifa havolasini yuboring.": (
            "⚠️ This link is not a text page (image/file). Send a text-page link."
        ),
        "⚠️ Saytdan matn o'qib bo'lmadi. Boshqa havolani urinib ko'ring.": (
            "⚠️ Could not read text from the site. Try another link."
        ),
    },
}

# Texnik tafsilot (``{e}``) bilan keladigan xatoliklar — prefiks bo'yicha
# moslik: (uz_prefiks, ru_prefiks, en_prefiks). Qolgan qism o'zgarmaydi.
# TARTIB MUHIM: uzunroq (aniqroq) prefikslar birinchi turishi shart.
SERVICE_ERROR_PREFIXES = [
    (
        "⚠️ AI xizmatida vaqtinchalik uzilish. Asl matningiz saqlab qolindi.",
        "⚠️ Временный сбой сервиса ИИ. Ваш исходный текст сохранён.",
        "⚠️ Temporary AI service outage. Your original text was kept.",
    ),
    (
        "⚠️ AI xizmatida vaqtinchalik uzilish.",
        "⚠️ Временный сбой сервиса ИИ.",
        "⚠️ Temporary AI service outage.",
    ),
    (
        "⚠️ AI xizmatida xatolik yuz berdi:",
        "⚠️ Ошибка сервиса ИИ:",
        "⚠️ AI service error:",
    ),
    (
        "Audit xizmatida vaqtinchalik xatolik:",
        "Временная ошибка сервиса аудита:",
        "Temporary audit service error:",
    ),
    (
        "Noma'lum harakat:",
        "Неизвестное действие:",
        "Unknown action:",
    ),
]

# Dinamik servis xatoliklari uchun regex andozalar:
# (pattern, ru_shablon, en_shablon).
SERVICE_ERROR_PATTERNS = [
    (
        r"^⚠️ AI rasmni tahlil qila olmadi \(Gemini: HTTP ([^)]+)\)\. "
        r"Iltimos, birozdan so'ng qayta urinib ko'ring\.$",
        "⚠️ ИИ не смог проанализировать изображение (Gemini: HTTP {g1}). "
        "Пожалуйста, попробуйте чуть позже.",
        "⚠️ AI could not analyze the image (Gemini: HTTP {g1}). "
        "Please try again shortly.",
    ),
    (
        r"^⚠️ Sayt javob bermadi \(HTTP (\d+)\)\. "
        r"Manzilni tekshirib, qayta yuboring\.$",
        "⚠️ Сайт не отвечает (HTTP {g1}). Проверьте адрес и отправьте снова.",
        "⚠️ The site did not respond (HTTP {g1}). Check the address and resend.",
    ),
    (
        r"^Audit xizmatida vaqtinchalik xatolik: (.+)\. Qaytadan urinib ko'ring\.$",
        "Временная ошибка сервиса аудита: {g1}. Попробуйте ещё раз.",
        "Temporary audit service error: {g1}. Please try again.",
    ),
    (
        r"^⚠️ Rasmni yuklab bo'lmadi \(server HTTP (\d+)\)\.$",
        "⚠️ Не удалось загрузить изображение (сервер HTTP {g1}).",
        "⚠️ Could not download the image (server HTTP {g1}).",
    ),
    (
        r"^📦 Rasm hajmi (.+) MB dan oshib ketdi\. Iltimos, kichikroq rasm yuboring\.$",
        "📦 Размер изображения превышает {g1} МБ. "
        "Пожалуйста, отправьте изображение поменьше.",
        "📦 The image exceeds {g1} MB. Please send a smaller image.",
    ),
    (
        r"^📦 Rasm hajmi (.+) MB dan oshib ketdi — kichikroq rasm yuboring\.$",
        "📦 Размер изображения превышает {g1} МБ — отправьте изображение поменьше.",
        "📦 The image exceeds {g1} MB — send a smaller image.",
    ),
]


def _localize_ai_timeout(text: str, lang: str):
    """AI timeout xabari (``AI_TIMEOUT_USER_MESSAGE``) ni tarjima qiladi.

    Xabar ichidagi soniya qiymati regex orqali ajratib olinadi, shuning
    uchun ``utils.ai_agent`` ga import (va aylanma bog'liqlik) kerak emas.
    Timeout xabari bo'lmasa ``None`` qaytaradi.
    """
    marker = "AI xizmati hozir javob bermayapti"
    if marker not in text:
        return None
    try:
        m = re.search(r"So'rov (\d+) soniyada yakunlanmadi", text)
        secs = m.group(1) if m else "…"
    except re.error:
        secs = "…"
    if normalize_lang(lang) == "ru":
        return (
            "⏳ <b>Сервис ИИ сейчас не отвечает.</b>\n\n"
            f"Запрос не завершился за {secs} секунд — возможно, сервер "
            "загружен или соединение медленное.\n\n"
            "Пожалуйста, попробуйте ещё раз через минуту. "
            "Ваш текст сохранён. 🙏"
        )
    return (
        "⏳ <b>The AI service is not responding right now.</b>\n\n"
        f"The request did not finish in {secs} seconds — the server "
        "may be busy or the connection is slow.\n\n"
        "Please try again in a minute. Your text was saved. 🙏"
    )


def localize_service_error(error, lang="uz") -> str:
    """AI/servis qatlamidan kelgan xatolikni foydalanuvchi tiliga o'giradi.

    Moslik topilmasa (yoki til o'zbekcha bo'lsa) asl matn qaytariladi —
    hech qanday xabar yo'qolmaydi. Texnik tafsilotlar (``{e}``) saqlanadi.
    """
    if error is None:
        return ""
    text = str(error)
    code = normalize_lang(lang)
    if code == DEFAULT_LANG:
        return text
    stripped = text.strip()
    table = SERVICE_ERROR_TRANSLATIONS.get(code) or {}
    hit = table.get(stripped)
    if hit is not None:
        return hit
    # Regex andozalar prefiksdan oldin: aniqroq moslik ustun turadi
    # (masalan, Audit xatoligining dumidagi «Qaytadan urinib ko'ring»
    # ham tarjima qilinadi).
    for pattern, ru_tpl, en_tpl in SERVICE_ERROR_PATTERNS:
        try:
            m = re.match(pattern, stripped, re.DOTALL)
        except re.error:
            continue
        if m:
            tpl = ru_tpl if code == "ru" else en_tpl
            try:
                return tpl.format(
                    **{f"g{i + 1}": g for i, g in enumerate(m.groups())}
                )
            except (KeyError, IndexError, ValueError):
                return text
    for uz_prefix, ru_prefix, en_prefix in SERVICE_ERROR_PREFIXES:
        if stripped.startswith(uz_prefix):
            rest = stripped[len(uz_prefix):]
            return (ru_prefix if code == "ru" else en_prefix) + rest
    timeout_hit = _localize_ai_timeout(stripped, code)
    if timeout_hit is not None:
        return timeout_hit
    return text
