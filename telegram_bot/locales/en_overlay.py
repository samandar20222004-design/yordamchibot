"""English overlay applied on top of UZ keys (full key coverage, EN UI)."""

EN_OVERLAY = {
    "btn_new_post": "➕ New post",
    "btn_ai_studio": "✨ AI Studio",
    "btn_premium": "⭐️ Premium",
    "btn_settings": "👤 Account & Settings",
    "btn_help": "📖 Guide / About",
    "btn_extras": "⚙️ Extra features",
    "start_hello": (
        "Hi, <b>{name}</b>! 👋\n\n"
        "🤖 @PostAssistrobot — schedule posts on time, write copy and content plans with AI.\n\n"
        "Pick a section 👇"
    ),
    "start_onboarding": (
        "👋 Welcome! Ready to create a professional post for your channel in 1 minute?\n"
        "\n"
        "✍️ AI writing\n"
        "📅 Schedule for any time\n"
        "📢 Auto-post to channels\n"
        "\n"
        "Choose a section below to make your first post 👇"
    ),
    "quick_menu_hint": (
        "👋 <b>Welcome!</b>\n\n"
        "Tap one of the <b>3 buttons</b> below — we handle the rest.\n\n"
        "🚀 AI writes a post  •  🖼 Post from a photo  •  📢 Connects a channel\n\n"
        "<i>Need every section? Tap «⚙️ Open full menu».</i>"
    ),
    "quick_btn_ai_post": "🚀 Create a post in 1 minute",
    "quick_btn_photo_post": "🖼 Post from a photo",
    "quick_btn_add_channel": "📢 Connect a channel",
    "quick_btn_full_menu": "⚙️ Open full menu",
    # Kabinet (Account & Settings) ichidagi reply tugmalar — EN klaviaturada
    # inglizcha chiqadi va routing ularni taniydi (fallback'ga tushmaydi).
    "cab_btn_channels": "📢 Channels/Groups",
    "cab_btn_converter": "🔤 Cyrillic-Latin converter",
    "cab_btn_daily_bonus": "🎁 Daily bonus",
    "cab_btn_invite": "🚀 Invite friends",
    "cab_btn_transfer": "🔄 Transfer credits",
    "quick_full_menu_opened": (
        "✅ <b>Full menu is open!</b>\n\n"
        "All sections are available — pick one below 👇"
    ),
    "lang_prompt": "🌐 <b>Tilni tanlang / Выберите язык / Choose language:</b>",
    "lang_changed": "✅ Language switched to English.",
    "lang_button": "🌐 Language",
    "btn_cancel": "❌ Cancel",
    "btn_main_menu": "🔙 Main menu",
    "btn_back": "⬅️ Back",
    "cab_close": "❌ Close",
    "ai_studio_content_plan": "🧠 Content plan",
    "ai_studio_content_plan_intro": (
        "🧠 <b>Content-plan generator</b>\n\nWhich channel should we plan for?"
    ),
    "np_confirm_cancel_btn": "❌ Cancel",
    "cancel_done": (
        "🚫 <b>Cancelled.</b>\n"
        "You are back in the main menu. Pick a section 👇"
    ),
    "main_menu_hint": "Pick a section from the menu below 👇",
    "ai_unavailable": (
        "⚠️ Temporary issue in the AI service. "
        "Please try again in a moment."
    ),
    "help_faq": (
        "❓ <b>FAQ</b>\n\n"
        "<b>1. My post did not appear — what now?</b>\n"
        "Make sure the bot is an <b>administrator</b> with post permission, "
        "then connect the channel in «📢 My channels».\n\n"
        "<b>2. How do I get AI credits?</b>\n"
        "Tap daily bonus, invite friends, or switch to ⭐️ PRO for unlimited AI.\n\n"
        "<b>3. Can I edit a scheduled post?</b>\n"
        "Yes — Account → Pending posts.\n\n"
        "<b>4. How do I turn off ads?</b>\n"
        "⭐️ PRO removes ads from posts and bot replies.\n\n"
        "<b>5. Which languages does the bot support?</b>\n"
        "Uzbek, Russian and English. Change it in Account → Language.\n\n"
        "{support}"
    ),
    # 🤷 Global fallback: foydalanuvchi tushunarsiz matn yuborsa — xabar
    # foydalanuvchi tanlangan tilida (uz/ru/en) chiqadi.
    "unknown_message_fallback": (
        "Sorry, I didn't understand that message. "
        "Please choose a section from the menu below 👇"
    ),
    # Dialog ICHIDA joriy bosqich qabul qilmaydigan xabar turi kelsa
    "unknown_in_dialog": (
        "⚠️ This type of message is not accepted at this step. "
        "Please send the requested information or press the 🔙 Main menu button."
    ),

    # ================================================================
    # ACCOUNT & SETTINGS — full EN coverage for Cabinet & Settings
    # ================================================================

    # Inline keyboard buttons
    "cab_my_channels": "📢 My channels",
    "cab_analytics": "📊 Channel analytics",
    "cab_pending": "📅 Pending posts",
    "cab_queue": "⏳ Post queue (Queue)",
    "cab_balance": "💎 Credits & Ad mode",
    "cab_referral": "👥 Invite friends",
    "cab_add_channel": "➕ Add channel",
    "cab_del_channel": "🗑 Delete channel",
    "cab_remove_channel": "❌ Delete",
    "cab_tone": "Style",
    "cab_add_channel_alt": "➕ Connect new channel/group",

    # My channels list
    "my_channels_title": "📢 <b>My channels:</b>",
    "my_channels_empty": (
        "📢 <b>My channels:</b>\n\n"
        "No channels connected yet.\n\n"
        "{hint}\n\n"
        "⚠️ <i>Add the bot as an administrator to your channel/group "
        "(with permission to send messages), then tap "
        "<b>➕ Add channel</b>.</i>"
    ),
    "my_channels_list": "📢 <b>My channels ({count} total):</b>\n\n",
    "my_channels_footer": "\nTo connect a new channel or delete an existing one 👇",

    # Channel deletion
    "cab_channels_delete_empty": (
        "📢 <b>My channels:</b>\n\n"
        "No channels to delete yet.\n\n"
        "{hint}"
    ),
    "cab_channels_delete_title": (
        "🗑 <b>Delete channel</b> ({count} total)\n\n"
        "Tap <b>❌ Delete</b> next to the channel you want to remove 👇"
    ),

    # Cabinet screen
    "credits_value": "<b>{n} pcs</b>",
    "cabinet_credits_admin": "♾ Unlimited (Super Admin)",
    "cabinet_streak": "🔥 <b>{streak}/7 days</b>",
    "cabinet_title": (
        "👤 <b>Personal Account:</b>\n\n"
        "🆔 Your ID: <code>{user_id}</code>\n"
        "🔑 Your code: <code>{user_code}</code>\n"
        "💎 Available AI requests: {credits}\n"
        "🔥 Daily streak: {streak}\n"
        "📢 Connected channels: <b>{channels} total</b>\n"
        "👥 Friends invited: <b>{referrals} total</b>\n\n"
        "Choose a section below 👇{ad_line}"
    ),

    # Balance & credits
    "balance_card": (
        "💎 <b>Credits & Ad Mode:</b>\n\n"
        "🤖 AI requests: {credits}\n"
        "📢 Ad mode: {ad_mode}\n\n"
        "To earn more credits:\n"
        "• 🎁 Claim daily bonus\n"
        "• 👥 Invite friends (1–3rd friend: +3, after: +1)\n"
        "• ⭐️ Switch to PRO (unlimited AI, 100% ad-free posts)"
    ),

    # Daily bonus
    "daily_bonus_admin": (
        "👑 <b>You are a Super Admin</b> — you have unlimited requests!"
    ),
    "daily_bonus_claimed": (
        "🎉 <b>Daily bonus claimed!</b>\n\n"
        "{reset_notice}"
        "🔥 Your streak: <b>{streak}/7 days</b>\n"
        "{bar}\n\n"
        "🎁 Today's gift: <b>+{bonus} AI requests</b>\n"
        "💎 Total balance: <b>{credits} pcs</b>\n\n"
        "📌 <i>Come back tomorrow and on day 7 get a "
        "<b>+4 super bonus</b>!</i>"
    ),
    "daily_bonus_reset_notice": (
        "\n⚠️ <i>You missed a day, so the streak restarted from day 1.</i>\n"
    ),
    "daily_bonus_already": (
        "ℹ️ {msg}\n\n💎 Total credits: <b>{credits} pcs</b>"
    ),

    # Referral
    "referral_reward_notice": (
        "🎉 <b>A new friend was invited!</b>\n\n"
        "<b>+{reward} AI credits</b> were added to your account. "
        "First 3 friends: +3 each, after that: +1 each. 🚀"
    ),
    "referral_menu": (
        "🚀 <b>Invite friends and earn AI credits:</b>\n\n"
        "🎁 <i>For the 1st, 2nd and 3rd friend: +3 each; from the 4th: +1 AI credit.</i>\n\n"
        "💎 Your AI credits: {credits}\n👥 Invited: <b>{count}</b>\n\n"
        "🔗 <b>Your referral link:</b>\n<code>{link}</code>"
    ),

    # Transfer
    "transfer_intro": (
        "🔄 <b>Transfer credits (AI requests):</b>\n\n"
        "Send the <b>ID</b>, "
        "<b>Telegram username (@...)</b> or <b>special code</b> "
        "of your friend:\n"
        "<i>(Note: credits can only be transferred to active "
        "registered users)</i>"
    ),
    "transfer_insufficient": (
        "⚠️ <b>You don't have enough credits!</b>\n\n"
        "To transfer, you need at least <b>3 credits</b>. "
        "You have: <b>{credits} pcs</b>.\n"
        "{guide}\n"
        "Or collect credits using your referral link!"
    ),
    "transfer_user_not_found": (
        "❌ <b>User not found!</b>\n\n"
        "This user has not registered in the bot yet or the data "
        "was entered incorrectly.\n"
        "Your friend should first open the bot and press <b>/start</b>.\n\n"
        "Enter the correct ID or code:"
    ),
    "transfer_self": (
        "⚠️ You cannot transfer credits to yourself! "
        "Enter another friend's details:"
    ),
    "transfer_target_ok": (
        "✅ <b>Recipient:</b> <b>{name}</b> "
        "(ID: <code>{user_id}</code>)\n\n"
        "How many credits to send? <i>(At least <b>3</b>, "
        "up to <b>20</b>)</i>:"
    ),
    "transfer_amount_nan": (
        "Please enter the amount as numbers only (e.g.: 5):"
    ),
    "transfer_amount_range": (
        "⚠️ Transfer amount must be at least <b>3</b> and at most "
        "<b>20 credits</b>. Please re-enter:"
    ),
    "transfer_success": (
        "🎉 <b>Success!</b>\n\n"
        "<b>+{amount} AI requests</b> were transferred to "
        "<b>{name}</b>'s account! 🚀"
    ),
    "transfer_gift_notice": (
        "🎁 <b>You received a gift!</b>\n\n"
        "<b>{name}</b> sent you <b>+{amount} AI requests</b>! 🎉"
    ),
    "transfer_error": "❌ <b>Error:</b> {msg}",
    "transfer_default_name": "Your friend",

    # Channel tone / voice
    "ch_tone_title": (
        "🎭 <b>Choose channel style:</b>\n\n"
        "Current style: <b>{current}</b>\n\n"
        "Style determines the tone and style of posts:"
    ),
    "ch_tone_formal": "👔 Formal / Business",
    "ch_tone_friendly": "😊 Friendly / Warm",
    "ch_tone_concise": "⚡️ Brief / News",
    "ch_tone_engaging": "🎉 Fun / Emotional",
    "ch_tone_cancelled": "✅ Style change cancelled.",
    "ch_tone_invalid": "❌ Invalid style. Please tap one of the buttons.",
    "ch_tone_success": (
        "✅ <b>Channel style updated!</b>\n\n"
        "🎭 New style: <b>{tone}</b>\n\n"
        "AI will now generate posts in this style."
    ),
    "ch_tone_error": "❌ Error saving style. Please try again.",

    "ch_voice_btn": "🎙 Channel voice analysis",
    "ch_voice_analyzing": (
        "🎙 <b>Analyzing channel voice...</b>\n\n"
        "AI is studying the channel's recent posts to determine its style."
    ),
    "ch_voice_no_posts": (
        "⚠️ Not enough posts in the channel for analysis. "
        "Add the bot as admin, wait for posts, then try again."
    ),
    "ch_voice_result": (
        "🎙 <b>Channel voice analysis result:</b>\n\n"
        "✅ Style: <b>{tone}</b>\n💬 {reason}\n\n"
        "This style has been saved to your channel profile and will be used in future AI generations."
    ),
    "ch_voice_error": "⚠️ Could not perform channel voice analysis. Please try again later.",

    # Timezone selection
    "tz_prompt": "🌍 <b>Choose your timezone:</b>",
    "tz_changed": "✅ Timezone changed to <b>{tz}</b>.",
    "tz_btn_tashkent": "🇺🇿 Tashkent (UTC+5)",
    "tz_btn_moscow": "🇷🇺 Moscow (UTC+3)",
    "tz_btn_utc": "🌐 UTC (UTC+0)",
    "tz_btn_samarkand": "🇺🇿 Samarkand (UTC+5)",
    "tz_current": "🌍 Timezone: <b>{tz}</b>",

    # ============================================================
    # ⭐️ PREMIUM / PRO — to'lov, chek va obuna oqimi (EN)
    # ------------------------------------------------------------
    # ``TRANSLATIONS["en"]`` UZ blokasidan nusxalanib faqat shu overlay bilan
    # to'ldiriladi (translations.py oxiri). Overlay'da bo'lmagan har bir kalit
    # EN foydalanuvchisiga **o'zbekcha** matn qaytaradi. Quyidagi guruh —
    # Premium/to'lov ekrani kalitlari: bu yerga qo'shilmasa, EN'da butun
    # «⭐️ Premium» bo'limi o'zbekcha ko'rinadi.
    # Qoidalar: {placeholder} to'plami UZ bilan bir xil, HTML teglari
    # (<b>/<i>/<code>) va emoji'lar saqlanadi.
    # ============================================================
    # «btn_premium» (⭐️ Premium) allaqachon overlay boshida — 3 tilda ham bir xil
    # brend yozuvi, qasddan tarjimasi yo'q.
    # Premium / tarif ekrani
    "ch_pro_btn": "⭐️ Go PRO",
    "ad_mode_admin": "👑 <b>Admin</b> — no ads",
    "ad_mode_pro": "✨ <b>PRO</b> — posts and bot replies are automatically 100% ad-free",
    "ad_mode_free": "🆓 <b>Free</b> — ads appear at a set interval (turned off automatically in PRO)",
    # AI limitlari va kunlik bonus
    "ai_credits_unlimited": "♾ Unlimited",
    "ai_credits_unlimited_pro": "♾ Unlimited (PRO)",
    "no_credits": (
        "⚠️ <b>You have run out of free AI requests!</b>\n\n"
        "Invite friends to get more.\n"
        "🎁 <i>+3 credits for the 1st, 2nd and 3rd friend; +1 for each friend from the 4th on.</i>\n"
        "{guide}\n\n"
        "🔗 Your referral link:\n"
        "<code>{link}</code>"
    ),
    "daily_bonus_guide": (
        "🎁 To claim your daily free AI credits, open 'Account & Settings' → '🎁 Daily bonus'."
    ),
    # AI Studio / post enhancer promptlari (PRO rejasi matnlari)
    "ai_prompt_hint": "✍️ Write the post topic or send a photo/file:",
    "ai_audit_prompt_hint": "🔍 Send the post text you want audited:",
    "ai_time_prompt_hint": "Please write the publishing time (e.g.: <i>“tomorrow at 10:00”</i>):",
    "np_ai_proposal": (
        "✨ <b>AI suggestion:</b>\n\n"
        "{new}\n\n"
        "📝 Original: <i>{old}</i>"
    ),
    "np_ai_retry_proposal": "✨ <b>AI suggestion (retry):</b>\n\n{new}",
    "enh_note_pro": "✨ <i>PRO — no via/watermark added, the post goes out clean.</i>\n",
    "enh_again_prompt": (
        "{notice}\n\n"
        "🚀 <b>New post</b> — send the post you want to enhance "
        "(text, photo, video, album or forward):"
    ),
    "enh_replace_prompt": (
        "🔁 <b>Send the new post</b> — the current post (text/media) will be replaced. "
        "Reactions and buttons are kept 👇"
    ),
    "enh_edit_prompt": (
        "✏️ <b>Editing button {num}</b>\n\n"
        "Current: <b>{text}</b> → <code>{url}</code>\n\n"
        "Send the new value in one line:\n"
        "<code>New label - https://new-link.com</code>"
    ),
    "enh_manual_prompt": (
        "✍️ <b>New URL button (manual entry)</b>\n\n"
        "Send it in one line:\n"
        "<code>Button label - https://site.com</code>\n"
        "<code>Button label | @mychannel</code>\n"
        "<code>My bot - t.me/bot_name/start</code>"
    ),
    "enh_preset_prompt": (
        "{icon} <b>{num}. {title}</b>\n\n"
        "Send <b>only the link</b> (e.g.: <code>{hint}</code>) — "
        "the button label is added automatically.\n\n"
        "<i>Full format also works: <code>Label - https://site.com</code></i>"
    ),
    # 💳 Karta orqali to'lov oqimi
    "btn_card_payment": "💳 Card payment (Uzcard / Humo)",
    "card_tariff_title": "💳 <b>Card payment</b>\n\n📌 Which plan are you paying for? Pick a plan 👇",
    "card_plan_1m": "1 month",
    "card_plan_3m": "3 months",
    "card_plan_1y": "1 year",
    "card_tariff_1m": "1 month — {price} so'm",
    "card_tariff_3m": "3 months — {price} so'm",
    "card_tariff_1y": "1 year — {price} so'm",
    "card_payment_title": "💳 <b>Card payment (Uzcard / Humo)</b>",
    "card_payment_prices": (
        "💰 <b>Amount to pay:</b>\n"
        "• 1 month — <b>{p1m} so'm</b>\n"
        "• 3 months — <b>{p3m} so'm</b>\n"
        "• 1 year — <b>{p1y} so'm</b>"
    ),
    "card_payment_selected": (
        "🎫 Selected plan: <b>{tarif}</b>\n"
        "💰 Amount to pay: <b>{summa} so'm</b>"
    ),
    "card_payment_card": (
        "💳 <b>Card number:</b> <code>{card}</code>\n"
        "👤 <b>Card holder:</b> {holder}"
    ),
    "card_payment_no_card": "ℹ️ Contact the admin to get the card details.",
    "card_payment_admin_missing": "admin (contact details in the '📖 Guide / About' section)",
    "card_payment_steps": (
        "📝 <b>Instructions:</b>\n"
        "1️⃣ Transfer the selected amount to the card above.\n"
        "2️⃣ Get the payment receipt (screenshot or PDF).\n"
        "3️⃣ Tap the <b>\"📸 Send receipt\"</b> button below and send the receipt here.\n"
        "4️⃣ Your ID: <code>{user_id}</code> — used when the receipt is checked.\n\n"
        "Once the admin approves it, the <b>PRO plan</b> is activated.\n"
        "⚡️ For instant activation, pay with ⭐️ Stars — PRO turns on right away.\n"
        "Questions: {admin}"
    ),
    # 📸 Chek (receipt) oqimi — foydalanuvchi + admin tomoni
    "btn_send_receipt": "📸 Send receipt",
    "receipt_prompt": (
        "📸 <b>Send your payment receipt:</b>\n\n"
        "🎫 Selected plan: {tarif} ({summa} so'm)\n\n"
        "Send the receipt (screenshot or PDF) as a <b>photo or document</b>. "
        "The bot forwards the receipt to the admins.\n"
        "🆔 Your ID: <code>{user_id}</code>\n\n"
        "Once the admin approves it, the <b>PRO</b> plan is activated automatically."
    ),
    "receipt_saved": (
        "✅ Your receipt was received and sent to the admin. "
        "We will check it soon and activate PRO."
    ),
    "receipt_bad_media": (
        "⚠️ Please send the receipt as a <b>photo</b> or a <b>PDF document</b>. "
        "Other files are not accepted as a receipt."
    ),
    "receipt_approved_user": (
        "🎉 <b>Congratulations!</b>\n\n"
        "Your payment receipt has been approved and the <b>{days}-day PRO plan</b> is now active!\n"
        "You can use everything PRO offers. 🚀"
    ),
    "receipt_rejected_user": (
        "❌ <b>Receipt rejected</b>\n\n"
        "Unfortunately your payment receipt was not approved. "
        "Please try again or contact the admin in the '⭐️ Premium' section."
    ),
    "receipt_admin_title": "💳 <b>New payment receipt!</b>",
    "receipt_admin_ask": "📝 Check the receipt and tap one of the buttons below:",
    "receipt_admin_already": "This receipt has already been reviewed.",
    "receipt_admin_done_ok": "✅ Approved. PRO has been granted to the user.",
    "receipt_admin_done_reject": "❌ Rejected.",
    "receipt_admin_user_line": "👤 User: {name} (@{username})",
    "receipt_admin_user_nick_line": "👤 User: {name}",
    # ID qatori — talab bo'yicha barcha tillarda bir xil (lang-neutral).
    "receipt_admin_user_id_line": "🆔 ID: {user_id}",
    "receipt_admin_tarif_line": "🎫 Selected plan: {tarif} ({summa} so'm)",
    "receipt_admin_time_line": "🕐 Time: {sana}",
    "receipt_btn_approve": "✅ Approve",
    "receipt_btn_reject": "❌ Reject",
    # 🔒 Kanalga obuna (majburiy) ekrani
    "sub_required": "⚠️ <b>To use the bot fully, join the official channels below:</b>",
    "sub_not_yet_alert": "⚠️ You have not joined all the channels yet! Please join all of them.",
    "sub_not_yet_msg": "⚠️ You have not joined all the channels yet! Join using the buttons below.",
    "sub_confirmed": (
        "✅ Subscription confirmed!\n\n"
        "Welcome, <b>{name}</b>! All features are now open to you.\n\n"
        "{hint}"
    ),
}
