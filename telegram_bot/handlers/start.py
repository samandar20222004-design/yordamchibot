import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, Forbidden
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard, get_cabinet_keyboard, get_cancel_keyboard
from keyboards.inline import (
    get_referral_share_keyboard, get_subscription_check_keyboard,
    get_cabinet_inline_keyboard, get_cabinet_back_keyboard,
    get_extras_inline_keyboard, get_language_keyboard,
    get_channels_manage_keyboard, render_channels_list, NO_CHANNELS_HINT,
    unpack_sponsor,
)
from locales.translations import (
    get_text, detect_language, get_lang, set_lang_cache, clear_fsm_data,
)
from utils.helpers import html_escape, get_smart_reply_ad_async

logger = logging.getLogger(__name__)

# Eslatma: 501-502 ANALYTICS bilan to'qnashgan edi — endi 511-512 unikal.
TRANSFER_TARGET = 511
TRANSFER_AMOUNT = 512

# Obuna holati keshi: (channel_id, user_id) -> (vaqt, a'zo_mi)
# Har /start da Telegram API'ga qayta-qayta so'rov yubormaslik uchun
# natija 60 soniya eslab qolinadi (ortiqcha yuklama kamayadi).
_membership_cache = {}
MEMBERSHIP_CACHE_TTL = 60
MEMBERSHIP_CACHE_MAX = 20000

async def check_user_subscribed(bot, user_id: int) -> tuple[bool, list | None]:
    """Homiy obunasini tekshiradi (fail-closed).

    Qaytadi:
      (True, [])            — ruxsat (admin yoki homiy yo'q yoki hammaga obuna)
      (False, [sponsors])   — obuna yo'q, ro'yxatni ko'rsatish
      (False, None)         — tizim xatosi (bazaga ulanib bo'lmadi) — o'tkazib yuborilmaydi
    """
    if user_id in ADMIN_IDS_SET:
        return True, []
    sponsors = await db.run_db(db.get_sponsor_channels)
    if sponsors is None:
        return False, None
    if not sponsors:
        return True, []

    unsubscribed = []
    now = time.time()
    for s in sponsors:
        s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
        cache_key = (str(ch_id), user_id)
        cached = _membership_cache.get(cache_key)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            if not cached[1]:
                unsubscribed.append(s)
            continue
        try:
            target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
            member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
            is_member = member.status in ("creator", "administrator", "member", "restricted")
        except Forbidden:
            # Bot homiy kanalga kira olmaydi (noto'g'ri sozlama) — bu sponsorni o'tkazib yuboramiz,
            # aks holda butun bot yopilib qoladi. Foydalanuvchi tekshiruvi emas.
            logger.error("Bot homiy kanalga kira olmaydi, o'tkazib yuborildi: %s", ch_id)
            is_member = True
        except TelegramError as e:
            err = str(e).lower()
            if "chat not found" in err or "bot was kicked" in err:
                logger.error("Homiy kanal noto'g'ri sozlangan (%s): %s", ch_id, e)
                is_member = True
            else:
                # Foydalanuvchi holatini aniqlab bo'lmasa — fail-closed (obuna emas).
                logger.warning("Obuna tekshiruvi fail-closed (%s / %s): %s", ch_id, user_id, e)
                is_member = False
        _membership_cache[cache_key] = (now, is_member)
        if not is_member:
            unsubscribed.append(s)

    # Kesh o'sishini cheklash
    if len(_membership_cache) > MEMBERSHIP_CACHE_MAX:
        cutoff = now - MEMBERSHIP_CACHE_TTL
        for k in [k for k, v in _membership_cache.items() if v[0] < cutoff]:
            _membership_cache.pop(k, None)

    return (len(unsubscribed) == 0), unsubscribed


# Alias
check_user_sponsorship = check_user_subscribed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user = update.effective_user
    detected = detect_language(getattr(user, "language_code", None))

    referrer_id = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))
            except ValueError:
                referrer_id = None

    is_new = await db.run_db(
        db.save_user, user.id, user.username or "", user.full_name or "",
        referrer_id=referrer_id, language_code=detected,
    )
    if is_new:
        lang = detected
    else:
        lang = await db.run_db(db.get_user_language, user.id)
    set_lang_cache(context, lang)

    if is_new and referrer_id:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text="🎉 <b>Yangi do'st taklif qilindi!</b>\n\nSizning taklif havolangiz orqali yangi foydalanuvchi qo'shildi va hisobingizga <b>+3 ta bepul AI so'rovi</b> qo'shildi! 🚀",
                parse_mode="HTML"
            )
        except Exception:
            pass

    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)
    if unsubs is None:
        await update.message.reply_text(
            "⚠️ <b>Tizim vaqtincha band.</b>\nIltimos, birozdan so'ng /start bosing.",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    if not is_sub:
        await update.message.reply_text(
            "⚠️ <b>Botdan to'liq foydalanish uchun quyidagi rasmiy kanallarga a'zo bo'ling:</b>",
            reply_markup=get_subscription_check_keyboard(unsubs),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    is_admin = (user.id in ADMIN_IDS_SET)
    ad_line = await get_smart_reply_ad_async(user.id)
    hello = get_text("start_hello", lang, name=html_escape(user.first_name))
    await update.message.reply_text(
        f"{hello}{ad_line}",
        reply_markup=get_main_keyboard(is_admin, lang=lang),
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def subscription_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    # Darhol javob
    try:
        await query.answer()
    except Exception:
        pass

    is_sub, unsubs = await check_user_subscribed(context.bot, user.id)

    if is_sub:
        try:
            await query.message.delete()
        except TelegramError:
            pass
        is_admin = (user.id in ADMIN_IDS_SET)
        lang = get_lang(context)
        await context.bot.send_message(
            chat_id=user.id,
            text=f"✅ Obuna tasdiqlandi!\n\nXush kelibsiz, <b>{html_escape(user.first_name)}</b>! Barcha imkoniyatlar siz uchun ochiq.",
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML"
        )
    else:
        try:
            await query.answer("⚠️ Hali barcha kanallarga a'zo bo'lmadingiz! Iltimos, barcha kanallarga a'zo bo'ling.", show_alert=True)
        except Exception:
            pass
        try:
            await query.edit_message_reply_markup(reply_markup=get_subscription_check_keyboard(unsubs))
        except TelegramError:
            pass
        try:
            await query.message.reply_text(
                "⚠️ Hali barcha kanallarga a'zo bo'lmadingiz! Pastdagi tugmalar orqali obuna bo'ling.",
                parse_mode="HTML",
            )
        except Exception:
            pass

async def user_cabinet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    stats = await db.run_db(db.get_referral_stats, user.id)
    channels = await db.run_db(db.get_user_channels, user.id)
    user_code = await db.run_db(db.get_user_code, user.id)
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    if is_admin:
        ad_free_text = "♾ Cheksiz (Super Admin)"
    else:
        status_badge = "🟢 Yoqilgan" if stats.get('ad_free_active', True) else "🔴 O'chirilgan"
        ad_free_text = f"<b>{stats['ad_free_posts']} ta</b> ({status_badge})"
        
    streak_val = stats.get('streak', 0)
    streak_text = f"🔥 <b>{streak_val}/7 kun</b>"
    ad_line = await get_smart_reply_ad_async(user.id)
    
    text = (
        f"👤 <b>Shaxsiy Kabinet:</b>\n\n"
        f"🆔 Sizning ID: <code>{user.id}</code>\n"
        f"🔑 Maxsus kodingiz: <code>{user_code}</code>\n"
        f"💎 Mavjud AI so'rovlar soni: {credits_text}\n"
        f"🔥 Ketma-ket kunlik seriya: {streak_text}\n"
        f"✨ Reklamasiz postlar litsenziyasi: {ad_free_text}\n"
        f"📢 Ulangan kanallar: <b>{len(channels)} ta</b>\n"
        f"👥 Taklif qilgan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
        f"Quyidagi bo'limlardan birini tanlang 👇{ad_line}"
    )
    await update.message.reply_text(text, reply_markup=get_cabinet_inline_keyboard(), parse_mode="HTML")

async def daily_bonus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    
    if is_admin:
        await update.message.reply_text("👑 <b>Siz Super Adminsiz</b> — hisobingizda cheksiz so'rov mavjud!", parse_mode="HTML")
        return
        
    res = await db.run_db(db.claim_daily_streak_bonus, user.id)
    if res.get("success"):
        streak = res["streak"]
        bonus = res["bonus_amount"]
        credits = res["credits"]
        
        progress_bar = "".join(["🟩" if i <= streak else "⬜" for i in range(1, 8)])
        reset_notice = "\n⚠️ <i>Orada kun o'tkazib yuborilgani sababli seriya 1-kundan qayta boshlandi.</i>\n" if res.get("is_reset") else ""
        
        text = (
            f"🎉 <b>Kunlik bonus qabul qilindi!</b>\n\n"
            f"{reset_notice}"
            f"🔥 Sizning ketma-ketlik seriyangiz: <b>{streak}/7 kun</b>\n"
            f"{progress_bar}\n\n"
            f"🎁 Bugungi sovg'a: <b>+{bonus} ta AI so'rovi</b>\n"
            f"💎 Jami balansingiz: <b>{credits} ta</b>\n\n"
            f"📌 <i>Eslatma: Ertaga ham botga kiring va 7-kunda <b>+4 ta super-bonus</b> oling!</i>"
        )
        await update.message.reply_text(text, reply_markup=get_cabinet_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(
            f"ℹ️ {res.get('msg')}\n\n💎 Sizdagi jami ballar: <b>{res.get('credits', 0)} ta</b>",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )

async def buy_ad_free_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    
    if is_admin:
        await update.message.reply_text("👑 Siz Super Adminsiz — barcha postlaringiz doim reklamasiz chiqadi!", parse_mode="HTML")
        return
        
    stats = await db.run_db(db.get_referral_stats, user.id)
    posts_count = stats['ad_free_posts']
    is_active = stats.get('ad_free_active', True)
    
    status_label = "🟢 Yoqilgan (Ishlatilmoqda)" if is_active else "🔴 O'chirilgan (Saqlanmoqda)"
    toggle_btn_text = "🔴 O'chirish (Tejash)" if is_active else "🟢 Yoqish (Ishlatish)"
    
    keyboard = [
        [InlineKeyboardButton(f"Holat: {toggle_btn_text}", callback_data="adfree_toggle")],
        [InlineKeyboardButton("➕ 5 ta post xarid qilish (1 ball)", callback_data="adfree_confirm")],
    ]
    if posts_count >= 5:
        keyboard.append([InlineKeyboardButton("🔄 Ballga qaytarish (5 post = 1 ball)", callback_data="adfree_refund")])
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="adfree_close")])
    
    await update.message.reply_text(
        f"💎 <b>Reklamasiz Toza Postlar Boshqaruvi:</b>\n\n"
        f"📊 Sizdagi mavjud toza postlar soni: <b>{posts_count} ta</b>\n"
        f"⚙️ Hozirgi holat: <b>{status_label}</b>\n\n"
        f"<i>Kerakli amalni tanlang:</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def ad_free_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    if data == "adfree_close":
        await query.message.delete()
        return

    if data == "adfree_toggle":
        success, new_status = await db.run_db(db.toggle_ad_free_status, user_id)
        stats = await db.run_db(db.get_referral_stats, user_id)
        posts_count = stats['ad_free_posts']
        status_label = "🟢 Yoqilgan (Ishlatilmoqda)" if new_status else "🔴 O'chirilgan (Saqlanmoqda)"
        toggle_btn_text = "🔴 O'chirish (Tejash)" if new_status else "🟢 Yoqish (Ishlatish)"
        
        keyboard = [
            [InlineKeyboardButton(f"Holat: {toggle_btn_text}", callback_data="adfree_toggle")],
            [InlineKeyboardButton("➕ 5 ta post xarid qilish (1 ball)", callback_data="adfree_confirm")],
        ]
        if posts_count >= 5:
            keyboard.append([InlineKeyboardButton("🔄 Ballga qaytarish (5 post = 1 ball)", callback_data="adfree_refund")])
        keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="adfree_close")])

        await query.edit_message_text(
            f"💎 <b>Reklamasiz Toza Postlar Boshqaruvi:</b>\n\n"
            f"📊 Sizdagi mavjud toza postlar soni: <b>{posts_count} ta</b>\n"
            f"⚙️ Hozirgi holat: <b>{status_label}</b>\n\n"
            f"<i>Holat muvaffaqiyatli yangilandi!</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return

    if data == "adfree_confirm":
        success, msg = await db.run_db(db.buy_ad_free_posts, user_id)
        await query.edit_message_text(msg, parse_mode="HTML")
        return

    if data == "adfree_refund":
        success, msg = await db.run_db(db.refund_ad_free_posts, user_id)
        await query.edit_message_text(msg, parse_mode="HTML")
        return

async def user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user = update.effective_user
    is_admin = (user.id in ADMIN_IDS_SET)
    bot_obj = await context.bot.get_me()
    stats = await db.run_db(db.get_referral_stats, user.id)
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    
    credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
    
    text = (
        f"🚀 <b>Do'stlarni taklif qiling va bepul AI so'rovlar oling:</b>\n\n"
        f"🎁 <i>Har bir yangi do'stingiz uchun hisobingizga <b>+3 ta bepul AI so'rovi</b> qo'shiladi!</i>\n\n"
        f"💎 Sizdagi mavjud AI so'rovlar soni: {credits_text}\n"
        f"👥 Taklif qilingan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
        f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_referral_share_keyboard(ref_link),
        parse_mode="HTML"
    )

async def start_transfer_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user_id = update.effective_user.id
    my_credits = await db.run_db(db.get_user_credits, user_id)
    
    if my_credits < 3 and user_id not in ADMIN_IDS_SET:
        await update.message.reply_text(
            f"⚠️ <b>Hisobingizda yetarli ball yo'q!</b>\n\n"
            f"Ball o'tkazish uchun kamida <b>3 ta ball</b> kerak. Sizda esa: <b>{my_credits} ta</b>.\n"
            f"Kunlik bonus yoki taklif havolasi orqali ball to'plashingiz mumkin!",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔄 <b>Ballarni (AI so'rovlarni) ulashish:</b>\n\n"
        "Do'stingizning <b>ID raqamini</b>, <b>Telegram usernamesini (@...)</b> yoki botdagi <b>maxsus kodini</b> yuboring:\n"
        "<i>(Eslatma: Faqat botdan ro'yxatdan o'tgan faol foydalanuvchilarga ball o'tkazish mumkin)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return TRANSFER_TARGET

async def transfer_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_input = update.message.text
    target_user = await db.run_db(db.find_user_by_target, target_input)
    
    # Ro'yxatdan o'tmagan foydalanuvchini qat'iy tekshirish
    if not target_user:
        await update.message.reply_text(
            "❌ <b>Foydalanuvchi topilmadi!</b>\n\n"
            "Ushbu foydalanuvchi hali botdan ro'yxatdan o'tmagan yoki ma'lumot xato kiritildi.\n"
            "Do'stingiz avval botga kirib <b>/start</b> bosishi kerak.\n\n"
            "Qaytadan to'g'ri ID raqam yoki kodni kiriting:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return TRANSFER_TARGET

    t_id, t_name, t_user, t_code, t_cred = target_user
    if t_id == update.effective_user.id:
        await update.message.reply_text("⚠️ O'zingizga ball o'tkaza olmaysiz! Boshqa do'stingiz ma'lumotini kiriting:")
        return TRANSFER_TARGET

    context.user_data["transfer_to_id"] = t_id
    context.user_data["transfer_to_name"] = t_name or t_user or str(t_id)
    
    await update.message.reply_text(
        f"✅ <b>Qabul qiluvchi:</b> <b>{html_escape(context.user_data['transfer_to_name'])}</b> (ID: <code>{t_id}</code>)\n\n"
        f"Nechta ball yubormoqchisiz? <i>(Kamida <b>3 ta</b>, ko'pi bilan <b>20 ta</b>)</i>:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return TRANSFER_AMOUNT

async def transfer_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Iltimos, miqdorni faqat raqamlarda yozing (masalan: 5):")
        return TRANSFER_AMOUNT
        
    amount = int(text)
    if amount < 3 or amount > 20:
        await update.message.reply_text("⚠️ O'tkazish miqdori kamida <b>3 ta</b> va ko'pi bilan <b>20 ta</b> bo'lishi kerak. Qaytadan kiriting:", parse_mode="HTML")
        return TRANSFER_AMOUNT

    from_id = update.effective_user.id
    to_id = context.user_data.get("transfer_to_id")
    to_name = context.user_data.get("transfer_to_name", "Do'stingiz")
    
    success, msg = await db.run_db(db.transfer_user_credits, from_id, to_id, amount)
    
    if success:
        await update.message.reply_text(
            f"🎉 <b>Muvaffaqiyatli!</b>\n\n"
            f"<b>{html_escape(to_name)}</b> hisobiga <b>+{amount} ta AI so'rovi</b> o'tkazildi! 🚀",
            reply_markup=get_cabinet_keyboard(),
            parse_mode="HTML"
        )
        try:
            sender_name = update.effective_user.first_name
            await context.bot.send_message(
                chat_id=to_id,
                text=f"🎁 <b>Sizga sovg'a!</b>\n\n<b>{html_escape(sender_name)}</b> sizga <b>+{amount} ta AI so'rovi</b> yubordi! 🎉",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(f"❌ <b>Xatolik:</b> {msg}", reply_markup=get_cabinet_keyboard(), parse_mode="HTML")
        
    clear_fsm_data(context)
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id in ADMIN_IDS_SET)
    ad_line = await get_smart_reply_ad_async(update.effective_user.id)
    text = (
        "📖 <b>PostAssistrobot — To'liq Qo'llanma:</b>\n\n"
        "🔹 <b>1. Yangi post rejalashtirish:</b>\n"
        "• Matn, rasm, video, audio yoki <b>albom</b> (bir nechta rasm/video) postlarni istalgan sanaga rejalashtirish.\n"
        "• Havola tugmalar (URL button), reaksiyalar va avto-o'chirish (12, 24, 48, 72 soat).\n"
        "• <i>Litsenziya bo'lsa reklamasiz toza post chiqadi!</i>\n\n"
        "🔹 <b>2. AI Yordamchi (savol-javob + postlar):</b>\n"
        "• Savol bering — bot imkoniyatlari, ballar, kanallar bo'yicha javob olasiz.\n"
        "• Matn yoki rasm/forward yuborib, professional post va she'rlar tayyorlash.\n"
        "• Erkin tilda buyruq: <i>“ertaga ertalab 9 ga hamma kanalga rejalashtir”</i>.\n"
        "• Postni tahrirlash: <i>“oxiriga telefon raqam qo'sh”</i>.\n"
        "• Tugma bosmasdan, istalgan vaqtda shunchaki xabar yozsangiz — AI javob beradi.\n\n"
        "🔹 <b>3. Ballar va Kunlik Seriya (Streak):</b>\n"
        "• Har kuni botga kiring va <b>'🎁 Kunlik bonus'</b> tugmasini bosing.\n"
        "• 1-kun (+1), 2-kun (+1), 3-kun (+2), ..., 7-kun (+4 ball) olasiz!\n\n"
        "🔹 <b>4. Matn O'girgich:</b>\n"
        "• Lotin ⇄ Kirill alifbolariga tezkor o'girish.\n\n"
        "⚙️ <b>Tezkor buyruqlar:</b>\n"
        "/start — Bosh menyu\n"
        "/newpost — Yangi post\n"
        "/profile — Kabinet\n"
        "/help — Qo'llanma\n"
        "/cancel — Bekor qilish"
    )
    if is_admin:
        text += "\n\n👑 <b>Admin buyruqlari:</b>\n/admin — Boshqaruv paneli\n/broadcast — Xabar yuborish\n/stats — Statistika"
    await update.message.reply_text(f"{text}{ad_line}", reply_markup=get_main_keyboard(is_admin, lang=get_lang(context)), parse_mode="HTML")

async def extras_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Qo'shimcha funksiyalar — inline menyu ko'rsatadi."""
    clear_fsm_data(context)
    await update.message.reply_text(
        "⚙️ <b>Qo'shimcha funksiyalar</b>\n\n"
        "✨ <b>Postga Tugma & Reaksiya qo'shish</b> — tayyor postni (matn, rasm, "
        "video, albom yoki forward) yuboring: asl matnga tegilmaydi, 10 tagacha "
        "reaksiya va 10 tagacha URL tugma qo'shib, istalgan kanalga bir zumda "
        "yuboriladi\n"
        "🔤 <b>Krill-Lotin konvertor</b> — matnlarni ikki alifbo orasida o'girish\n\n"
        "Kerakli vositani tanlang 👇",
        reply_markup=get_extras_inline_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def extras_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qo'shimcha funksiyalar oynasini yopadi."""
    query = update.callback_query
    await query.answer()
    is_admin = query.from_user.id in ADMIN_IDS_SET
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.message.reply_text("✅ Yopildi.", reply_markup=get_main_keyboard(is_admin, lang=get_lang(context)))


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi band holatda /cancel bosganda yoki tugma bosganda — aniq xabar."""
    is_admin = (update.effective_user.id in ADMIN_IDS_SET)
    lang = get_lang(context)
    clear_fsm_data(context)
    await update.message.reply_text(
        "🚫 <b>Jarayon bekor qilindi.</b>\n"
        "Asosiy menyuga qaytdingiz. Kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin, lang=lang),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cabinet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kabinet inline tugmalari — barcha ichki bo'limlar inline bilan."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if data == "close_cabinet":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text(
            "✅ Yopildi.",
            reply_markup=get_main_keyboard(is_admin, lang=get_lang(context)),
        )
        return

    if data == "cab_lang":
        await query.answer()
        lang = get_lang(context)
        try:
            await query.edit_message_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                get_text("lang_prompt", lang),
                reply_markup=get_language_keyboard(),
                parse_mode="HTML",
            )
        return

    if data in ("cab_lang_uz", "cab_lang_ru"):
        lang = "ru" if data.endswith("_ru") else "uz"
        await query.answer()
        await db.run_db(db.set_user_language, user_id, lang)
        set_lang_cache(context, lang)
        try:
            await query.edit_message_text(
                get_text("lang_changed", lang),
                reply_markup=get_language_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            pass
        await query.message.reply_text(
            get_text("lang_changed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
        return

    if data == "cab_main":
        await query.answer()
        stats = await db.run_db(db.get_referral_stats, user_id)
        channels = await db.run_db(db.get_user_channels, user_id)
        user_code = await db.run_db(db.get_user_code, user_id)

        credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
        if is_admin:
            ad_free_text = "♾ Cheksiz (Super Admin)"
        else:
            status_badge = "🟢 Yoqilgan" if stats.get('ad_free_active', True) else "🔴 O'chirilgan"
            ad_free_text = f"<b>{stats['ad_free_posts']} ta</b> ({status_badge})"

        streak_val = stats.get('streak', 0)
        streak_text = f"🔥 <b>{streak_val}/7 kun</b>"

        text = (
            f"👤 <b>Shaxsiy Kabinet:</b>\n\n"
            f"🆔 Sizning ID: <code>{user_id}</code>\n"
            f"🔑 Maxsus kodingiz: <code>{user_code}</code>\n"
            f"💎 Mavjud AI so'rovlar soni: {credits_text}\n"
            f"🔥 Ketma-ket kunlik seriya: {streak_text}\n"
            f"✨ Reklamasiz postlar litsenziyasi: {ad_free_text}\n"
            f"📢 Ulangan kanallar: <b>{len(channels)} ta</b>\n"
            f"👥 Taklif qilgan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
            f"Quyidagi bo'limlardan birini tanlang 👇"
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_inline_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_inline_keyboard(), parse_mode="HTML")
        return

    if data == "cab_channels":
        await query.answer()
        lang = get_lang(context)
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            text = get_text("my_channels_empty", lang, hint=NO_CHANNELS_HINT)
            markup = get_channels_manage_keyboard()
        else:
            text = get_text("my_channels_list", lang, count=len(channels))
            for i, ch in enumerate(channels, 1):
                ch_id, ch_title = ch[:2]
                text += f"{i}. <b>{html_escape(ch_title or 'Kanal')}</b> (<code>{ch_id}</code>)\n"
            text += get_text("my_channels_footer", lang)
            markup = get_channels_manage_keyboard()
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_channels_delete":
        await query.answer()
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            text = (
                "📢 <b>Mening kanallarim:</b>\n\n"
                "Hozircha o'chirish uchun kanal yo'q.\n\n"
                f"{NO_CHANNELS_HINT}"
            )
            markup = get_channels_manage_keyboard()
        else:
            text = (
                f"🗑 <b>Kanalni o'chirish</b> ({len(channels)} ta)\n\n"
                "O'chirmoqchi bo'lgan kanalingiz yonidagi <b>❌ O'chirish</b> "
                "tugmasini bosing 👇"
            )
            markup = render_channels_list(channels)
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_analytics":
        await query.answer()
        from handlers.analytics import _build_dashboard
        stats = await db.run_db(db.get_channel_post_stats, user_id, None)
        text = _build_dashboard(stats, "Barcha kanallar")
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        return

    if data == "cab_converter":
        await query.answer()
        text = (
            "🔤 <b>Krill-Lotin konverter:</b>\n\n"
            "Lotin yoki Kirill matn yuboring — men uni avtomatik o'girib beraman.\n\n"
            "<i>Masalan: Salom dunyo → Салом дунё</i>"
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        return

    if data == "cab_bonus":
        await query.answer()
        if is_admin:
            text = "👑 <b>Siz Super Adminsiz</b> — hisobingizda cheksiz so'rov mavjud!"
            try:
                await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
            except Exception:
                await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
            return

        res = await db.run_db(db.claim_daily_streak_bonus, user_id)
        if res.get("success"):
            streak = res["streak"]
            bonus = res["bonus_amount"]
            credits = res["credits"]
            progress_bar = "".join(["🟩" if i <= streak else "⬜" for i in range(1, 8)])
            reset_notice = "\n⚠️ <i>Orada kun o'tkazib yuborilgani sababli seriya 1-kundan qayta boshlandi.</i>\n" if res.get("is_reset") else ""
            text = (
                f"🎉 <b>Kunlik bonus qabul qilindi!</b>\n\n"
                f"{reset_notice}"
                f"🔥 Sizning ketma-ketlik seriyangiz: <b>{streak}/7 kun</b>\n"
                f"{progress_bar}\n\n"
                f"🎁 Bugungi sovg'a: <b>+{bonus} ta AI so'rovi</b>\n"
                f"💎 Jami balansingiz: <b>{credits} ta</b>\n\n"
                f"📌 <i>Eslatma: Ertaga ham botga kiring va 7-kunda <b>+4 ta super-bonus</b> oling!</i>"
            )
        else:
            text = f"ℹ️ {res.get('msg')}\n\n💎 Sizdagi jami ballar: <b>{res.get('credits', 0)} ta</b>"
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        return

    if data == "cab_referral":
        await query.answer()
        bot_obj = await context.bot.get_me()
        stats = await db.run_db(db.get_referral_stats, user_id)
        ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
        credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
        text = (
            f"🚀 <b>Do'stlarni taklif qiling va bepul AI so'rovlar oling:</b>\n\n"
            f"🎁 <i>Har bir yangi do'stingiz uchun hisobingizga <b>+3 ta bepul AI so'rovi</b> qo'shiladi!</i>\n\n"
            f"💎 Sizdagi mavjud AI so'rovlar soni: {credits_text}\n"
            f"👥 Taklif qilingan do'stlaringiz: <b>{stats['referrals_count']} ta</b>\n\n"
            f"🔗 <b>Sizning taklif havolangiz:</b>\n<code>{ref_link}</code>"
        )
        share_kb = get_referral_share_keyboard(ref_link)
        combined_kb = InlineKeyboardMarkup(
            share_kb.inline_keyboard + get_cabinet_back_keyboard().inline_keyboard
        )
        try:
            await query.edit_message_text(text, reply_markup=combined_kb, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=combined_kb, parse_mode="HTML")
        return

    if data == "cab_balance":
        await query.answer()
        stats = await db.run_db(db.get_referral_stats, user_id)
        credits_text = "♾ Cheksiz (Super Admin)" if is_admin else f"<b>{stats['ai_credits']} ta</b>"
        if is_admin:
            ad_free_text = "♾ Cheksiz (Super Admin)"
        else:
            status_badge = "🟢 Yoqilgan" if stats.get('ad_free_active', True) else "🔴 O'chirilgan"
            ad_free_text = f"<b>{stats['ad_free_posts']} ta</b> ({status_badge})"
        text = (
            f"💎 <b>Ballar & Litsenziya:</b>\n\n"
            f"🤖 AI so'rovlar: {credits_text}\n"
            f"✨ Reklamasiz postlar: {ad_free_text}\n\n"
            f"Ballarni ko'paytirish uchun:\n"
            f"• 🎁 Kunlik bonus oling\n"
            f"• 👥 Do'stlarni taklif qiling (+3 ball)\n"
            f"• ⭐️ PRO tarifga o'ting (cheksiz AI)"
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        return

    if data == "cab_pending":
        await query.answer()
        # Kabinet xabarini o'chirib, pending posts view'ni yangi xabar sifatida yuboramiz
        try:
            await query.message.delete()
        except Exception:
            pass
        from handlers.pending import _build_pending_view
        text, markup = await _build_pending_view(user_id)
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_queue":
        await query.answer()
        # Kabinet xabarini o'chirib, queue view'ni yangi xabar sifatida yuboramiz
        try:
            await query.message.delete()
        except Exception:
            pass
        from handlers.queue import _build_queue_view
        try:
            text, markup = await _build_queue_view(user_id, is_admin)
        except Exception:
            # Baza xatosi bo'lsa ham foydalanuvchi JAVOB olishi shart —
            # aks holda tugma "qotib qolgan" bo'lib ko'rinadi.
            logger.exception("Post navbati ekranini qurishda xato (user=%s)", user_id)
            text = (
                "📚 <b>Navbat (Queue)</b>\n\n"
                "⚠️ Rejalashtirilgan postlarni hozircha o'qib bo'lmadi "
                "(baza bilan aloqa xatosi).\n"
                "Iltimos, birozdan so'ng qayta urinib ko'ring."
            )
            markup = get_cabinet_back_keyboard()
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return

    if data == "cab_guide":
        await query.answer()
        text = (
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
        )
        try:
            await query.edit_message_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        except Exception:
            await query.message.reply_text(text, reply_markup=get_cabinet_back_keyboard(), parse_mode="HTML")
        return
