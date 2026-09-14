"""English overlay applied on top of UZ keys (full key coverage, EN UI)."""

EN_OVERLAY = {
    "btn_new_post": "➕ New post",
    "btn_ai_studio": "✨ AI Studio",
    # UX V2 (6-button standard) — EN parity (legacy names stay in the
    # alias lists in keyboards/default.py for backward compatibility).
    "btn_premium": "💎 PRO",
    "btn_settings": "⚙️ Settings",
    "btn_help": "📖 Guide / About",
    "btn_extras": "⚙️ Extra features",
    # 🆕 UX V2 main menu — STRICT 6-BUTTON standard (EN):
    #   [✨ Create content]  [📢 My channels]
    #   [📅 Scheduled]       [📊 Statistics]
    #   [💎 PRO]             [⚙️ Settings]
    "btn_create_content": "✨ Create content",
    "btn_my_channels": "📢 My channels",
    "btn_scheduled": "📅 Scheduled",
    "btn_statistics": "📊 Statistics",
    "start_hello": (
        "Hi, <b>{name}</b>! 👋\n\n"
        "🤖 @PostAssistrobot — schedule posts on time, write copy and content plans with AI.\n\n"
        "Pick a section 👇"
    ),
    # UX V2: compact onboarding — 3 input modes (photo / text / voice)
    # + promise (mirrors UZ/RU).
    "start_onboarding": (
        "👋 Hi!\n"
        "I'm PostAssist — your AI SMM assistant.\n"
        "\n"
        "📸 Send a photo\n"
        "📝 Write a text\n"
        "🎙 Send a voice note\n"
        "\n"
        "I'll prepare a professional post for you."
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
    "ai_quota": (
        "⚠️ AI quota exceeded. "
        "Please wait and try again."
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
    "cab_queue": "📅 Scheduled",
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
    # 🌍 Payment-region choice (GEOGRAPHIC — never tied to language).
    "pay_region_title": (
        "💳 <b>Select your payment region</b>\n\n"
        "🌐 The payment method does NOT depend on your language — you can "
        "pay in any region no matter which language is set.\n"
        "📌 Which region will you pay from? 👇"
    ),
    "pay_region_uz": "🇺🇿 Uzbekistan (Uzcard / Humo)",
    "pay_region_intl": "🌍 International (Stars / Crypto / Card)",
    "pay_region_selected": "🎫 Selected plan: <b>{tarif}</b>",
    "intl_payment_title": (
        "🌍 <b>International payment</b>\n\n"
        "⭐️ Telegram Stars — instant payment, PRO turns on automatically.\n"
        "🪙 Crypto (USDT) and 💳 international cards (Visa / Mastercard)."
    ),
    "intl_tariff_1m": "⭐️ 1 month — 75 Stars (~$1.5)",
    "intl_tariff_3m": "⭐️ 3 months — 175 Stars (~$3.5)",
    "intl_tariff_1y": "⭐️ 1 year — 550 Stars (~$11.0)",
    "intl_payment_selected": (
        "🎫 Selected plan: <b>{tarif}</b>\n"
        "⭐️ Price: <b>{stars} Stars</b> (~${usd})"
    ),
    "intl_payment_hint": (
        "👇 Tap the button below — the Telegram Stars payment window opens and "
        "PRO is activated automatically after the payment.\n"
        "🪙 Crypto or international card help: {admin}"
    ),
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
    "receipt_save_error": (
        "⚠️ Failed to save your receipt. Please send it again."
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

    # ============================================================
    # ⚙️ EXTRA FEATURES & GUIDE — 3-language finalization (EN)
    # ============================================================
    "extras_menu_body": (
        "⚙️ <b>Extra features</b>\n\n"
        "✨ <b>Add Buttons & Reactions to post</b> — send a ready post (text, photo, "
        "video, album or forward): the original text stays untouched, add up to "
        "10 reactions and up to 10 URL buttons and publish instantly to any channel\n"
        "🔤 <b>Cyrillic-Latin converter</b> — convert texts between two alphabets\n\n"
        "Pick a tool below 👇"
    ),
    "extras_btn_enhancer": "✨ Add Buttons & Reactions to post",
    "extras_btn_converter": "🔤 Cyrillic-Latin converter",
    "extras_closed": "✅ <b>Extra features</b> section closed.",
    "conv_intro": (
        "🔤 <b>Latin ⇄ Cyrillic Text Converter:</b>\n\n"
        "Send the <b>text</b> or <b>photo/video/file</b> (with caption) you want to convert:\n\n"
        "<i>Press '🔙 Main menu' to cancel.</i>"
    ),
    "conv_no_text": (
        "⚠️ No text (caption) found in this file.\n"
        "Please send text or resend the file with a caption:"
    ),
    "conv_received": (
        "📝 <b>Text received!</b>\n\n"
        "Which alphabet to convert to? Pick one below 👇"
    ),
    "conv_btn_cyr": "🔤 Cyrillic version",
    "conv_btn_lat": "🔤 Latin version",
    "conv_no_saved_text": "⚠️ Text not found, please send it again.",
    "conv_result_title": "📋 <b>Result:</b>",
    "conv_result_part1": "📋 <b>Result (part 1):</b>",
    "conv_result_part2": "📋 <b>Result (part 2):</b>",
    "conv_copy_hint": "<i>(Tap the text to copy)</i>",
    "conv_cont_title": "ℹ️ <i>Continued:</i>",
    "conv_error": "⚠️ Error occurred: {error}",
    "conv_timeout_msg": (
        "⏰ <b>Conversation ended due to timeout.</b>\n"
        "You are back in the main menu. Pick a section again 👇"
    ),
    "cab_converter_info": (
        "🔤 <b>Cyrillic-Latin converter:</b>\n\n"
        "Send text in Latin or Cyrillic — I'll convert it automatically.\n\n"
        "<i>Example: Salom dunyo → Салом дунё</i>"
    ),
    "help_guide": (
        "📖 <b>PostAssistrobot — Complete Guide:</b>\n\n"
        "🔹 <b>1. Connect channel/group:</b>\n"
        "• Add the bot as <b>administrator</b> to your channel (with permission to send messages).\n"
        "• Go to «👤 Account & Settings» → «📢 My channels» and forward any post from the channel or send @username.\n\n"
        "🔹 <b>2. Schedule a new post:</b>\n"
        "• Schedule text, photo, video, audio or <b>album</b> (multiple photos/videos) for any date.\n"
        "• URL buttons, reactions and auto-delete (12, 24, 48, 72 hours).\n"
        "• <i>PRO posts are automatically 100% ad-free!</i>\n\n"
        "🔹 <b>3. ✨ AI Studio:</b>\n"
        "• Create AI post, photo-to-post (Vision), AI audit and content plan.\n"
        "• Ask a question or send text/photo/forward — get a professional post.\n"
        "• Free-form command: <i>«schedule to all channels tomorrow at 9 am»</i>.\n"
        "• Edit post: <i>«add phone number at the end»</i>.\n\n"
        "🔹 <b>4. Credits & Daily Streak:</b>\n"
        "• Open the bot daily and tap <b>'🎁 Daily bonus'</b>.\n"
        "• Day 1 (+1), Day 2 (+1), Day 3 (+2), ..., Day 7 (+4 credits)!\n\n"
        "🔹 <b>5. ⚙️ Extra features:</b>\n"
        "• ✨ Add Buttons & Reactions to post — instantly boost a ready post.\n"
        "• 🔤 Latin ⇄ Cyrillic text converter.\n\n"
        "⚙️ <b>Quick commands:</b>\n"
        "/start — Main menu\n"
        "/newpost — New post\n"
        "/profile — Account\n"
        "/help — Guide\n"
        "/cancel — Cancel\n\n"
        "{support}"
    ),
    "help_guide_admin": (
        "\n\n👑 <b>Admin commands:</b>\n"
        "/admin — Control panel\n"
        "/broadcast — Broadcast\n"
        "/stats — Statistics"
    ),
    "help_btn_faq": "❓ Frequently asked questions",
    "help_btn_support": "💬 Contact support",
    "help_support_line": "👨‍💻 <b>Need help?</b> Contact {admin}.",
    "help_admin_fallback": "bot administrator",
    "cab_guide_text": (
        "📖 <b>PostAssistrobot — Complete Guide:</b>\n\n"
        "🔹 <b>1. Schedule a new post:</b>\n"
        "• Schedule text, photo, video, audio or <b>album</b> for any date.\n"
        "• URL buttons, reactions and auto-delete.\n\n"
        "🔹 <b>2. AI Assistant:</b>\n"
        "• Ask a question or send text/photo — get a professional post.\n"
        "• Free form: <i>\"tomorrow at 9 am to all channels\"</i>.\n\n"
        "🔹 <b>3. Credits & Daily Streak:</b>\n"
        "• Open bot daily and claim bonus (Day 7 +4 credits).\n\n"
        "⚙️ <b>Quick commands:</b>\n"
        "/start — Main menu\n"
        "/profile — Account\n"
        "/help — Guide\n"
        "/cancel — Cancel"
    ),

    # ⚠️ Errors and system messages (EN)
    "sys_busy": (
        "⚠️ <b>The system is temporarily busy.</b>\n"
        "Please tap /start again a bit later."
    ),
    "sys_stale_button": (
        "♻️ This button is stale (the bot was restarted). "
        "Open the menu again: /start"
    ),
    "sys_unexpected_error": (
        "⚠️ <b>An unexpected error occurred.</b>\n"
        "Please try again a bit later or tap /start."
    ),
    # 🌐 Short toast messages (callback throttle / stale menu fallbacks).
    "sys_error_short": "⚠️ An error occurred",
    "sys_wait_short": "⏳ Please wait...",
    "admin_only_cmd": "❌ This command can only be used by an administrator.",
    "np_callback_wait": "⏳ Processing, please wait...",
    "noop_channel_info": (
        "This is an info button. To delete the channel, tap the ❌ button "
        "next to it."
    ),
    "ai_menu_stale": (
        "⚠️ <b>This menu is stale.</b>\n"
        "To continue, tap the ✨ AI Studio button again."
    ),
    "ai_photo_stale": (
        "⚠️ <b>This menu is stale.</b>\n"
        "To create a post from an image, open ✨ AI Studio → 🖼 Post from "
        "image again."
    ),

    # 🩺 PHASE 7: System health monitoring (/health — admins only)
    "health_title": "🩺 <b>SYSTEM HEALTH</b>",
    "health_overall": "📊 <b>Overall status:</b>",
    "health_checked_at": "🕐 Checked: {time} (UTC)",
    "health_uptime": "⏱ Uptime: {uptime}",
    "health_db_title": "🗄 <b>Database:</b> {status}",
    "health_db_latency": "• Neon DB response time: {latency} ms",
    "health_db_error": "• Error: {error}",
    "health_db_pool": "• Connection pool: {used}/{max} in use ({available} free)",
    "health_scheduler_title": "⏰ <b>Scheduler (apscheduler):</b> {status}",
    "health_sched_jobs": "• Active jobs: {count}",
    "health_posts_pending": "• ⏳ Pending posts: {count}",
    "health_posts_failed": "• ⚠️ Failed posts: {count}",
    "health_posts_dead": "• ☠️ Dead-letter posts: {count}",
    "health_posts_processing": "• ⚙️ Posts in processing: {count}",
    "health_posts_unknown": "• ❔ UNKNOWN delivery (check manually): {count}",
    "health_ai_errors": "• Open circuit-breakers: {open} | consecutive errors: {errors}",
    "health_payments_title": "💳 <b>Payments:</b> {status}",
    "health_payments_pending": "• Pending receipts: {count}",
    "health_payments_24h": "• 24h: approved {approved} | Stars {stars}",
    "health_posts_stale": "• 🧊 Stuck (stale) posts: {count}",
    "health_ai_title": "🤖 <b>AI providers:</b> {status}",
    "health_ai_provider": "• {name}: {status}",
    "health_system_title": "🖥 <b>System resources:</b>",
    "health_errors": "• Errors — last 1h: {hour} | 24h: {day}",
    "health_tasks": "• Active asyncio tasks: {count}",

    # ============================================================
    # FULL EN COVERAGE — batch A: new-post entry, AI Studio, content plan
    # (PostAssist V2 i18n audit: every key below was falling back to UZ.)
    # ============================================================
    "new_post_no_channels": (
        "⚠️ <b>No connected channel or group found!</b>\n\n"
        "First connect your channel or group in the '📢 Channels/Groups' section."
    ),
    "new_post_choose_channel": (
        "📢 <b>Which channel or group should we schedule the post for?</b>\n"
        "Pick from the list 👇"
    ),
    "no_channels_hint": (
        "First connect your channel or group in the "
        "<b>\"My channels\"</b> section."
    ),
    "ai_studio_menu": (
        "🤖 <b>PostAssist AI Studio</b>\n\n"
        "💎 Available AI requests: {credits}\n\n"
        "Pick a tool to create channel content 👇"
    ),
    "ai_studio_post": "✍️ Create AI post",
    "ai_studio_photo": "🖼 Post from photo",
    "ai_studio_extract": "📢 Take from public channel",
    "ai_studio_audit": "🔍 AI post audit",
    "ai_studio_post_intro": (
        "✍️ <b>Create AI post</b>\n\n"
        "Write the post topic or send a photo/file.\n"
        "<i>Example: \"Motivational post about a healthy lifestyle\"</i>"
    ),
    "ai_studio_photo_intro": (
        "🖼 <b>Post from photo</b>\n\n"
        "Send a photo — AI will analyze it deeply and write a "
        "professional SMM post for your Telegram channel:\n"
        "• ✨ Nicely formatted headline (<b>...</b>)\n"
        "• 📝 Interesting / selling copy\n"
        "• 😎 Emojis and lists\n"
        "• 👉 Call to action (CTA) and hashtags\n\n"
        "<i>Optionally send a caption with the photo — e.g.: "
        "\"focus on selling the product in the photo\".</i>"
    ),
    "ai_studio_audit_intro": (
        "🔍 <b>AI post audit</b>\n\n"
        "Send your finished post text — AI will audit it:\n"
        "• ✍️ Spelling and grammar\n"
        "• 🎯 Appeal and CTA\n"
        "• 🧩 Structure recommendations\n"
        "• ⭐️ Overall score (1-10)"
    ),
    "ai_studio_extract_intro": (
        "📢 <b>Take from public channel</b>\n\n"
        "Enter the channel username (e.g.: <code>@kunuzofficial</code> or <code>daryo</code>):\n\n"
        "<i>Works for public channels only.</i>"
    ),
    "ai_studio_no_channel": (
        "⚠️ <b>Connect a channel first.</b>\n\n"
        "You need at least one channel to build a content plan.\n"
        "Connect a channel in the 📢 Channels section."
    ),
    "plan_btn_schedule_all": "🚀 Schedule all for 7 days",
    "plan_week_hint": "\n\n🚀 <i>Or queue the whole week with one tap.</i>",
    "plan_sched_busy": "⏳ Queueing 7 days of posts...",
    "plan_sched_done_alert": "✅ 7 days of posts queued!",
    "plan_sched_done": (
        "✅ <b>7 days of posts queued!</b>\n\n"
        "📢 Channel: <b>{channel}</b>\n"
        "📦 Queued: <b>{count} posts</b>\n\n"
        "{days}\n\n"
        "🤖 Posts will go out automatically every day at <b>12:00</b>.\n"
        "📋 You can edit or cancel any post in "
        "\"📅 Scheduled\"."
    ),
    "plan_sched_already": "ℹ️ This content plan is already queued.",
    "plan_sched_stale": (
        "⚠️ Session expired. Recreate the content plan — "
        "then you can schedule 7 days with one tap."
    ),
    "plan_sched_no_channel": (
        "⚠️ <b>Channel not found.</b>\n\n"
        "Connect a channel first, then recreate the content plan."
    ),
    "plan_sched_empty": "⚠️ The plan is empty — create the content plan first.",
    "plan_sched_error": "❌ Failed to queue the posts. Please try again.",
    "plan_sched_day_line": "• {day} — {time}",

    # ============================================================
    # FULL EN COVERAGE — batch B: AI tones, photo flow, scheduling
    # ============================================================
    "ai_tone_formal": "👔 Formal",
    "ai_tone_friendly": "😊 Friendly",
    "ai_tone_concise": "⚡️ Short",
    "ai_tone_engaging": "🎉 Engaging",
    "ai_tone_schedule": "➡️ Go to scheduling",
    "ai_photo_schedule": "📅 Schedule to channel",
    "ai_photo_rewrite": "🔄 Rewrite",
    "ai_photo_edit": "✏️ Edit",
    "ai_photo_result_title": "🖼 <b>Post made from photo:</b>\n\n",
    "ai_photo_result_foot": (
        "\n\n🖼 <i>The sent photo will be attached to this post.</i>\n\n"
        "Pick the next step 👇"
    ),
    "ai_btn_back": "⬅️ Back",
    "ai_btn_close": "❌ Cancel",
    "ai_btn_main_menu": "⬅️ Main menu",
    "ai_confirm_schedule": "✅ Schedule to channel",
    "ai_confirm_edit": "📝 Edit text",
    "ai_preview_title": "✨ <b>AI post is ready!</b>\n\n",
    "ai_preview_foot": (
        "\n\n🎨 <b>Style:</b> {tone}{media}\n\n"
        "Change the style or go to scheduling 👇"
    ),
    "ai_preview_media_note": "\n🖼 <i>Media will be attached to the post.</i>",
    "ai_thinking": "🤖 <i>AI is preparing a reply...</i>",
    "ai_saving": "💾 Saving...",
    "ai_wait_post": "🤖 <i>AI is writing the post...</i>",
    "ai_wait_audit": "🔍 <i>AI is auditing...</i>",
    "ai_wait_photo": "🖼 <i>AI is analyzing the photo...</i>",
    "ai_photo_variants_ask": (
        "🎨 <b>3 style variants</b> are ready for the photo. "
        "Pick one — the chosen text will open 👇"
    ),
    "ai_wait_edit": "✏️ <i>AI is editing the post...</i>",
    "ai_rate_limit": (
        "⏳ <i>You are sending AI requests too often. Please wait 1 minute...</i>"
    ),
    "ai_daily_limit": (
        "⚠️ <i>Daily AI request limit reached (30/day). Try again tomorrow.</i>"
    ),
    "ai_limit_msg": (
        "🚫 <b>Daily AI limit reached!</b>\n\n"
        "Today <b>{used}/{max}</b> AI requests were used.\n"
        "The Free plan allows max <b>{max}</b> AI requests per day.\n\n"
        "⭐️ Switch to PRO for unlimited AI."
    ),
    "ai_media_received": (
        "🖼 <b>Media received!</b>\n\nNow write the post topic or text."
    ),
    "ai_faq_footer": "\n\n<i>Write another topic or go back 👇</i>",
    "ai_no_post_text": "⚠️ Could not determine the post text. Try phrasing the topic differently.",
    "ai_session_expired": "⚠️ Session expired. Send the topic again.",
    "ai_audit_result_title": "🔍 <b>AI audit result:</b>\n\n",
    "ai_audit_no_result": "⚠️ AI could not return the audit result. Please try again.",
    "ai_photo_only": (
        "🖼 Please send a photo (JPG/PNG/WEBP):\n"
        "• <i>You can add a caption to the photo</i>\n"
        "• <i>Video is not analyzed — photo only</i>"
    ),
    "ai_video_rejected": (
        "🎬 <b>Video is not analyzed.</b>\n\n"
        "To save server resources, only <b>photos</b> are analyzed.\n"
        "Please send the <b>photo</b> to analyze (JPG/PNG/WEBP)."
    ),
    "ai_photo_no_text": "⚠️ AI could not prepare the post text. Send the photo again.",
    "ai_photo_retry_hint": "🖼 Send another photo or return to the menu 👇",
    "ai_photo_edit_intro": (
        "✏️ <b>Edit post</b>\n\n"
        "What should change? Send text:\n"
        "<i>Example: \"rewrite the headline\", \"shorten\", \"add the price\"</i>"
    ),
    "ai_photo_edit_hint": "✏️ Send text to edit:",
    "ai_photo_edit_no_result": "⚠️ AI could not return the edited text. Please try again.",
    "ai_photo_rewrite_wait": "🔄 <i>AI is re-analyzing the photo...</i>",
    "ai_photo_rewrite_keep": "⚠️ AI could not rewrite the post. The original post is kept.",
    "ai_tone_applying": "🎨 <i>Applying the {tone} style...</i>",
    "ai_schedule_need_post": "⚠️ Create a post first. Write the topic:",
    "ai_close_session": "❌ AI Studio session finished.",
    "ai_close_main_menu": "🏠 Main menu.",
    "ai_not_found": "Sorry, I could not find an answer.",
    "ai_tone_unknown": "⚠️ Session expired. Send the topic again.",
    "ai_rate_limit_alert": "⏳ Too many requests. Please wait 1 minute.",
    "ai_schedule_header": "✨ <b>Post received!</b>\n\n",
    "ai_schedule_foot": (
        "🕒 <b>When should this post go out to the channel?</b>\n"
        "Pick a button below or write freely:\n"
        "• <i>\"tomorrow morning at 9\"</i>\n"
        "• <i>\"today at 15:45 to all channels\"</i>\n"
        "• <i>\"in 1 hour\"</i>"
    ),
    "ai_media_caption_note": "\n\n⬆️ The media above will be attached to this post.",
    "ai_confirm_title": (
        "✨ <b>Prepared post:</b>\n\n"
        "{post}\n\n"
        "🕒 <b>Publish time:</b> <code>{time}</code>{target}\n\n"
        "Shall we schedule this post?"
    ),
    "ai_media_received_scheduled": (
        "🖼 <b>Media received and attached to the post!</b>\n\n"
        "Now write the publish time (e.g.: <i>\"today at 18:00\"</i>) or tap a button:"
    ),
    "ai_only_one_time": (
        "ℹ️ <i>Only a one-time post can be scheduled via the AI assistant.</i>\n"
        "For daily/weekly recurring posts use the <b>➕ Schedule new post</b> section.\n\n"
        "Write the time (e.g.: <i>\"tomorrow at 10:00\"</i>) or tap a quick button:"
    ),
    "ai_time_fast": (
        "⏳ <i>You are sending requests too often. Wait 1 minute or "
        "write the time in exact format: <code>2026-08-30 18:00</code></i>"
    ),
    "ai_time_ask": (
        "🤖 {reply}\n\n"
        "Write the post time like this: <i>\"tomorrow at 10:00\"</i> or tap a button:"
    ),
    "ai_time_unparsed": (
        "⚠️ <b>Could not determine the time, or it has passed.</b>\n\n"
        "Write like this:\n"
        "• <i>\"today at 18:00\"</i>\n"
        "• <i>\"tomorrow morning at 9\"</i>\n"
        "• <i>\"in 30 minutes\"</i>\n"
        "Or exact format: <code>DD.MM.YYYY HH:MM</code> "
        "(e.g. <code>30.08.2026 18:00</code>)\n\n"
        "🕒 <i>Tashkent time (UTC+5).</i>"
    ),
    "ai_time_detecting": "🤖 <i>Detecting time...</i>",
    "ai_full_post_text": "📝 <b>Post text (full):</b>\n\n{text}",
    "ai_post_ready": "✨ <b>Post is ready!</b>\n\n",
    "ai_post_ready_foot": (
        "\n\n🕒 <b>Publish time:</b> <code>{time}</code>{target}\n\n"
        "Shall we schedule it?"
    ),
    "ai_post_cancelled": "🚫 Post cancelled. Pick a section from the menu.",
    "ai_post_retry": (
        "📝 <b>How shall we change the post?</b>\n\n"
        "E.g.: <i>\"add phone number at the end\"</i>, <i>\"shorten the text\"</i>, "
        "<i>\"change the headline\"</i> — or send a new post."
    ),
    "ai_no_channel_schedule": (
        "⚠️ <b>No connected channels found.</b>\n\n"
        "First connect a channel in the '📢 Channels/Groups' section, then reschedule the post."
    ),
    "ai_scheduled_ok": (
        "✅ <b>AI post scheduled successfully!</b>\n\n"
        "📢 Placement: <b>{channel}</b>\n"
        "⏰ Publish time: <b>{time}</b>\n\n"
        "Tap <b>🤖 AI Assistant</b> to create another post or return to the menu."
    ),
    "ai_schedule_error": "❌ Error saving. Please try again later.",
    "ai_photo_media_received": (
        "🖼 <b>Media received!</b>\n\nNow write the post topic or text."
    ),

    # ============================================================
    # FULL EN COVERAGE — batch C: new-post buttons, weekdays, reactions
    # ============================================================
    "np_btn_skip": "➡️ Continue without button",
    "np_btn_skip_url": "⏭ Skip",
    "np_btn_url_add": "🔗 Add URL button",
    "np_btn_ai_assistant": "✨ AI Assistant",
    "np_btn_title_details": "Details",
    "np_btn_title_join": "Join channel",
    "np_btn_title_site": "Visit site",
    "np_btn_title_contact": "Contact",
    "np_btn_no_reactions": "➡️ Continue without reactions",
    "np_btn_del_never": "❌ Never delete (Permanent)",
    "np_btn_del_12h": "⏳ 12 hours",
    "np_btn_del_24h": "⏳ 24 hours (1 day)",
    "np_btn_del_48h": "⏳ 48 hours (2 days)",
    "np_btn_del_72h": "⏳ 72 hours (3 days)",
    "np_btn_time_5m": "⚡ 5 minutes",
    "np_btn_time_15m": "⚡ 15 minutes",
    "np_btn_time_1h": "⚡ 1 hour",
    "np_btn_time_daily": "🔁 Daily (same time)",
    "np_btn_time_weekly": "📅 Weekly (same weekday)",
    "np_btn_dur_1w": "1 week",
    "np_btn_dur_1m": "1 month",
    "np_btn_dur_3m": "3 months",
    "np_btn_dur_6m": "6 months",
    "np_btn_dur_1y": "1 year",
    "np_btn_dur_inf": "♾ Forever",
    "np_weekday_0": "Monday",
    "np_weekday_1": "Tuesday",
    "np_weekday_2": "Wednesday",
    "np_weekday_3": "Thursday",
    "np_weekday_4": "Friday",
    "np_weekday_5": "Saturday",
    "np_weekday_6": "Sunday",
    "np_btn_back_confirm": "🔙 Back",
    "np_btn_all_channels": "🌐 To all at once",
    "np_label_today": "Today",
    "np_label_tomorrow": "Tomorrow",
    "np_channel_selected": (
        "✅ Selected: <b>{channel}</b>\n\n"
        "📝 <b>Send content for the post:</b>\n"
        "(Text, photo, video, album, document, audio or GIF — "
        "stickers and voice messages are not accepted)"
    ),
    "np_channel_not_found": "⚠️ No such channel found. Pick again:",
    "np_media_not_allowed": (
        "Sorry, stickers are not accepted as a post. "
        "Please send a photo, video or text"
    ),
    "np_all_channel_title": "🌐 All",
    "np_button_ask": (
        "🔘 <b>Add a link button under the post?</b> (optional)\n\n"
        "⚡️ <b>Quick way:</b> send the button label and link in one line:\n"
        "<code>Button Text - https://link.com</code>\n\n"
        "Or pick a ready label / send your own (link will be asked next).\n\n"
        "If not needed, tap <b>⏭ Skip</b>:"
    ),
    "np_button_ready": (
        "✅ <b>Inline button is ready:</b>\n"
        "🔘 Label: <b>{title}</b>\n"
        "🔗 Link: <code>{url}</code>"
    ),
    "np_button_url_ask": (
        "🔗 Send the link or channel username that opens when the "
        "<b>'{title}'</b> button is tapped:\n\n"
        "E.g.: <code>@kanalim</code> or <code>https://sayt.uz</code>\n\n"
        "<i>Or in one line: <code>{title} - https://link.com</code></i>"
    ),
    "np_button_url_add_ask": (
        "🔗 <b>Add URL button</b>\n\n"
        "Send the button label and link <b>in one line, separated by \" - \"</b>:\n"
        "<code>Button Text - https://link.com</code>\n\n"
        "<i>E.g.:</i> <code>Visit site - https://sayt.uz</code> or\n"
        "<code>My channel - @kanalim</code>"
    ),
    "np_reactions_ask": (
        "👍 <b>Which reaction buttons to add under the post?</b>\n\n"
        "Tap the emojis you need — they get ✅ (tap again to remove).\n"
        "Or write freely, e.g.: <code>👍 ❤️ 🔥</code> — you can send "
        "several separated by space.\n"
        "If you send a sticker — its emoji is added to reactions too.\n"
        "When done, tap <b>➡️ Continue</b>.\n"
        "If no reactions needed — <b>⏭ Skip reactions</b>."
    ),
    "np_reactions_selected": (
        "✅ Selected: {emojis}\n"
        "You can add more emojis or tap <b>➡️ Continue</b>:"
    ),
    "np_reactions_use_inline": (
        "⚠️ <b>Please use the inline buttons below:</b>\n"
        "• Tap emojis to select (marked ✅)\n"
        "• You can also send emojis freely: <code>👍 ❤️ 🔥</code>\n"
        "• If you send a sticker — its emoji is added to reactions\n"
        "• <b>➡️ Continue</b> — next step with selected\n"
        "• <b>⏭ Skip reactions</b> — without reactions"
    ),

    # ============================================================
    # FULL EN COVERAGE — batch D: time, duration, confirmation, album, edit
    # ============================================================
    "np_reactions_none": "ℹ️ No reactions selected — the post will go out without reactions.",
    "np_react_done": "➡️ Continue",
    "np_react_done_count": "➡️ Continue ({count})",
    "np_react_skip": "⏭ Skip reactions",
    "np_auto_delete_ask": (
        "🗑️ <b>How long should the post stay in the channel?</b>\n\n"
        "After the set time, the bot will automatically delete it from the channel:"
    ),
    "np_time_ask": (
        "🕒 <b>When should the post go out?</b>\n\n"
        "Pick a ready button or write the exact time.\n"
        "Format: <code>DD.MM.YYYY HH:MM</code>\n"
        "Example: <code>{example}</code>\n\n"
        "🕒 <i>Tashkent time (UTC+5).</i>"
    ),
    "np_time_future": (
        "⚠️ <b>This time has already passed.</b>\n\n"
        "Please enter a time in the FUTURE.\n"
        "Example: <code>{example}</code>\n\n"
        "🕒 <i>Now in Tashkent: {now}</i>"
    ),
    "np_time_format_error": (
        "⚠️ <b>Time format not recognized.</b>\n\n"
        "Correct format: <code>DD.MM.YYYY HH:MM</code>\n"
        "Example: <code>{example}</code>\n\n"
        "Or write one of these:\n"
        "• time only — <code>18:00</code> (today, or tomorrow if passed)\n"
        "• <code>tomorrow 18:00</code>\n"
        "• <code>in 2 hours</code>\n\n"
        "🕒 <i>All times are Tashkent time (UTC+5).</i>"
    ),
    "np_daily_time_ask": (
        "🔁 <b>What time should it go out daily?</b>\n"
        "E.g.: <code>10:00</code> or <code>18:30</code>"
    ),
    "np_daily_time_format": (
        "⚠️ <b>Wrong time format.</b>\n\n"
        "Write only the time as <code>HH:MM</code>.\n"
        "Example: <code>10:00</code> or <code>18:30</code>\n\n"
        "🕒 <i>Tashkent time (UTC+5).</i>"
    ),
    "np_weekday_ask": "📅 <b>Which weekday should it go out?</b>",
    "np_weekday_invalid": "⚠️ Pick one of the days:",
    "np_recur_time_ask": (
        "🕒 <b>What time every {day}?</b>\n"
        "E.g.: <code>10:00</code>"
    ),
    "np_recur_time_format": (
        "⚠️ <b>Wrong format!</b> Write the time as <code>HH:MM</code>. "
        "Example: <code>10:00</code> 🕒 <i>(Tashkent time, UTC+5)</i>"
    ),
    "np_duration_ask_daily": "⏳ <b>How long should the post go out daily?</b>",
    "np_duration_ask_weekly": "⏳ <b>How long should this post keep going out?</b>",
    "np_duration_invalid": "⚠️ Pick one of the options:",
    "np_confirm_title": "📋 <b>Confirm the post:</b>",
    "np_confirm_channel": "📢 <b>Channel:</b> {channel}",
    "np_confirm_type": "📦 <b>Type:</b> {type}",
    "np_type_text": "📝 Text",
    "np_type_photo": "🖼 Photo",
    "np_type_video": "🎬 Video",
    "np_type_document": "📄 Document",
    "np_type_audio": "🎵 Audio",
    "np_type_voice": "🎙 Voice",
    "np_type_sticker": "😀 Sticker",
    "np_type_album": "🖼 Album",
    "np_type_animation": "🎞 GIF",
    "np_type_unknown": "📝 Message",
    "np_confirm_album_photos": "🖼 Album: {count} photos",
    "np_confirm_album_videos": "🎬 Album: {count} videos",
    "np_confirm_album_mixed": "🖼 Album: {photos} photos, {videos} videos",
    "np_confirm_album_files": "🖼 Album: {count} files",
    "np_confirm_content_truncated": (
        "⚠️ Note: the text is {total} chars — due to Telegram's {limit}-char "
        "limit only that much will show in the channel post. The full text is saved."
    ),
    "np_confirm_time_none": "⏰ Time not set",
    "np_confirm_time_single": "⏰ {time} (Tashkent time)",
    "np_confirm_time_daily": "🔁 Daily at {time}",
    "np_confirm_time_weekly": "📅 Every {day} at {time}",
    "np_confirm_content": "📋 <b>Text:</b>\n{content}",
    "np_confirm_button": "🔘 Button: <b>{text}</b>",
    "np_confirm_reactions": "👍 Reactions: {emojis}",
    "np_confirm_reactions_on": "👍 Reactions: On",
    "np_confirm_auto_delete": "⏳ Auto-delete: {hours} h",
    "np_confirm_ok_btn": "✅ Confirm & schedule",
    "np_confirm_queue_btn": "⏳ Add to queue",
    "np_confirm_edit_btn": "✏️ Edit",
    "np_album_warning": (
        "⚠️ Per Telegram rules, link or reaction buttons cannot be added "
        "to multi-photo albums. \n"
        "Buttons or reactions only work for 1 photo (or plain text)."
    ),
    "np_album_choice_first_photo": "🖼 Keep 1st photo + add button",
    "np_album_choice_full": "⏩ Publish full album without buttons",
    "np_album_first_photo_done": (
        "✅ Post changed to a single photo — now you can add a button or reactions."
    ),
    "np_album_full_done": (
        "✅ Full album ({count} files) will go out without buttons or reactions."
    ),
    "np_edit_menu_title": "✏️ <b>Which part to edit?</b>",
    "np_edit_content_btn": "📝 Text",
    "np_edit_channel_btn": "📢 Channel",
    "np_edit_time_btn": "⏰ Time",
    "np_edit_button_btn": "🔘 Button",
    "np_edit_back_btn": "⬅️ Back (to confirmation)",
    "np_edit_content_ask": "📝 <b>Send the new text:</b>",
    "np_edit_channel_ask": "📢 <b>Which channel?</b>",
    "np_edit_time_ask": "🕒 <b>New time:</b> <code>{example}</code>",
    "np_edit_button_ask": (
        "🔘 <b>Button:</b> <code>Text | https://link.uz</code>\n"
        "Delete: <code>no</code>"
    ),
    "np_edit_channel_not_found": "⚠️ Channel not found.",

    # ============================================================
    # FULL EN COVERAGE — batch E: scheduling results, AI helper
    # ============================================================
    "np_cancelled": "🚫 <b>Post cancelled.</b>\nYou are back in the main menu 👇",
    "np_no_time": "⚠️ <b>Time not set.</b>",
    "np_no_channel": "⚠️ <b>Channel not selected.</b>",
    "np_no_slot": (
        "⚠️ <b>No free slot found.</b>\nAll slots are busy for 7 days."
    ),
    "np_scheduled_ok": (
        "✅ <b>Post scheduled successfully!</b>\n\n"
        "📢 Placement: <b>{channel}</b>\n"
        "{when}{del_info}"
    ),
    "np_scheduled_when_single": "⏰ {time}",
    "np_scheduled_when_daily": "🔁 Daily at {time}",
    "np_scheduled_when_weekly": "📅 Every {day} at {time}",
    "np_scheduled_del": "\n⏳ Time in channel: <b>{hours} h</b>",
    "np_queue_added": (
        "⚡️ <b>Post queued!</b>\n\n"
        "📅 {label} at {time}\n"
        "📢 Channel: <b>{channel}</b>{ad_line}"
    ),
    "np_queue_error": "❌ <b>Error queueing the post.</b>",
    "np_save_error": "❌ Error saving.",
    "np_save_error_bold": "❌ <b>Error saving.</b>",
    "np_ai_menu_title": (
        "✨ <b>AI Assistant</b>\n\n"
        "📋 Current text:\n<i>{preview}</i>\n\n"
        "Which action?"
    ),
    "np_ai_empty_content": "⚠️ <b>Post text is empty.</b>\nEnter text first.",
    "np_ai_empty_alert": "⚠️ Text is empty!",
    "np_ai_working": "⏳ AI is working...",
    "np_ai_empty_result": "⚠️ AI reply is empty. Original text kept.",
    "np_ai_accepted_alert": "✅ Accepted!",
    "np_ai_accept_msg": "✅ <b>New text accepted!</b>\n\n{content}",
    "np_ai_reverted_alert": "❌ Reverted to original!",
    "np_ai_revert_msg": "❌ <b>Original text restored.</b>",
    "np_ai_retrying": "🔄 Retrying...",
    "np_ai_action_grammar": "✍️ Spelling & style",
    "np_ai_action_emoji": "🎨 Emojis",
    "np_ai_action_hashtags": "🏷 Hashtags",
    "np_ai_action_tldr": "✂️ Shorten",
    "np_ai_btn_back": "⬅️ Back",
    "np_ai_btn_accept": "✅ Accept",
    "np_ai_btn_retry": "🔄 Retry",
    "np_ai_btn_revert": "❌ Revert to original",

    # ============================================================
    # FULL EN COVERAGE — batch F: channels
    # ============================================================
    "ch_empty_title": (
        "📢 <b>You have no connected channels yet.</b>\n\n"
        "Tap the button below to connect a channel 👇\n\n"
        "<i>You will need to add the bot as an administrator to your channel "
        "(with permission to send messages).</i>"
    ),
    "ch_list_title": (
        "📢 <b>Your connected channels ({count}):</b>\n\n"
        "Tap '❌ Delete' to remove a channel, or connect a new one 👇"
    ),
    "ch_all_removed": (
        "📢 <b>All channels removed.</b>\n\n"
        "Tap the button below to connect a new channel 👇"
    ),
    "ch_add_btn": "➕ Connect channel/group",
    "ch_add_instructions": (
        "➕ <b>Connect a new channel or group:</b>\n\n"
        "1. Add the bot (<code>@{bot}</code>) to your channel or group as an "
        "<b>Administrator</b> (with permission to send messages).\n"
        "2. Then send the channel source in one of four formats:\n"
        "   • <b>Forward</b> any message from the channel;\n"
        "   • <code>@channel_name</code>;\n"
        "   • <code>t.me/channel_name</code> or <code>https://t.me/channel_name</code>;\n"
        "   • channel ID (e.g.: <code>-1001234567890</code>).\n\n"
        "<i>To cancel, tap '🔙 Main menu'.</i>"
    ),
    "ch_retry_btn": "🔁 I made the bot admin — check again",
    "ch_empty_target": (
        "❌ Empty message received. <b>Forward</b> a message from the channel, "
        "or send <code>@username</code>, ID or a <code>t.me/channel</code> link."
    ),
    "ch_invite_blocked": (
        "🔒 <b>A closed channel cannot be connected via an invite link.</b>\n\n"
        "Since the bot is already a channel admin, send <code>@username</code> "
        "or <b>forward</b> any message from the channel — then we'll detect it."
    ),
    "ch_not_found": "❌ Channel or group not found. Forward a message or send the correct ID.",
    "ch_cannot_verify": (
        "⚠️ <b>The bot is not in this channel or rights could not be verified.</b>\n\n"
        "First make the bot an administrator (with permission to send messages)."
    ),
    "ch_not_admin": (
        "⚠️ <b>The bot is not an administrator of this channel!</b>\n\n"
        "Please first grant the bot permission to send messages in the channel."
    ),
    "ch_no_post_permission": (
        "⚠️ <b>The bot was not granted permission to send messages in the channel.</b>\n\n"
        "Enable the <b>Post Messages</b> right in the administrator settings."
    ),
    "ch_user_verify_fail": (
        "⚠️ <b>Could not verify your rights in this channel.</b>\n\n"
        "Only a channel/group administrator can connect a channel to the bot."
    ),
    "ch_forbidden": (
        "🚫 <b>No access.</b>\n\n"
        "Only a channel or group <b>administrator</b> can connect a channel to this bot."
    ),
    "ch_unknown_target": (
        "❌ Channel data not detected. Please <b>forward</b> a message from the channel "
        "or send <code>@username</code>, a <code>t.me/channel_name</code> link, or the ID "
        "(e.g.: <code>-1001234567890</code>)."
    ),
    "ch_empty_target_short": "❌ Channel data not detected. Please forward a message from the channel:",
    "ch_unexpected_error": (
        "⚠️ <b>An unexpected error occurred.</b>\n\n"
        "Please forward the channel message again or send "
        "<code>@username</code> / <code>t.me/channel</code>."
    ),
    "ch_retry_after": (
        "{error}\n\nAfter granting rights to the bot, tap the button below "
        "or resend the channel source 👇"
    ),
    "ch_limit_msg": (
        "🚫 <b>Channel limit reached!</b>\n\n"
        "You now have <b>{current}/{max}</b> channels connected.\n"
        "The Free plan allows max <b>{max}</b> channels.\n\n"
        "⭐️ Switch to PRO for unlimited use."
    ),
    "ch_success": (
        "✅ <b>Channel connected successfully!</b>\n\n"
        "📢 Name: <b>{title}</b>\n"
        "🆔 ID: <code>{channel_id}</code>\n\n"
        "📋 <b>Your channels ({count}):</b>"
    ),
    "ch_success_footer": "To delete a channel or change its style 👇",
    "ch_taken": (
        "🚫 <b>This channel is already connected to another user.</b>\n\n"
        "It cannot be taken over. If this is your channel, the owner must first remove it from the bot."
    ),
    "ch_save_error": "❌ Error saving the channel.",
    "ch_remove_not_found": "❌ Channel not found or not yours.",
    "ch_no_perm_dm": (
        "⚠️ <b>The bot was made an administrator, but the permission to send messages "
        "(Post Messages) was not granted!</b>\n\n"
        "📢 Channel: <b>{channel}</b>\n\n"
        "Please enable the <b>Post Messages</b> right for the bot in the channel settings — "
        "the channel will then connect automatically."
    ),
    "ch_autoconnect_success": (
        "🎉 <b>You made the bot an admin of {channel} — the channel is connected!</b>\n\n"
        "🆔 <code>{channel_id}</code>\n\n"
        "Now you can schedule posts to this channel 👇"
    ),
    "ch_default_title": "Telegram Channel",

    # ============================================================
    # FULL EN COVERAGE — batch G: pending posts
    # ============================================================
    "pend_empty": "⏳ <b>You have no pending active posts.</b>",
    "pend_list_title": "⏳ <b>Your pending posts ({count}):</b>",
    "pend_item": (
        "🔹 <b>Post: {code}</b>\n"
        "📢 Channel: <b>{channel}</b>\n"
        "📦 Type: <b>{type}</b>\n"
        "{time}\n\n"
    ),
    "pend_channel_fallback": "Channel",
    "pend_edit_time_btn": "🕒 {code} time",
    "pend_edit_content_btn": "✏️ {code} text",
    "pend_edit_btn_btn": "🔗 Button",
    "pend_edit_react_btn": "👍 Reactions",
    "pend_cancel_btn": "❌ Cancel",
    "pend_refresh_btn": "🔄 Refresh",
    "pend_close_btn": "❌ Close",
    "pend_refreshed": "✅ Refreshed",
    "pend_refresh_fail": "Could not refresh",
    "pend_rate_limited": "⏳ Please wait a bit...",
    "pend_error": "⚠️ Error: {error}",
    "pend_not_found": "❌ Post not found.",
    "pend_not_owned": "❌ This post is not yours.",
    "pend_time_ask": (
        "🕒 <b>Send the new publish time for the post:</b>\n\n"
        "• For a one-time post: <code>DD.MM.YYYY HH:MM</code> "
        "(e.g. <code>30.08.2026 20:00</code>)\n"
        "• Free format also works: <code>tomorrow 18:00</code>, <code>today 10:00</code>\n"
        "• For a daily post, time only: <code>10:00</code>"
    ),
    "pend_time_success": "✅ <b>Post time updated successfully!</b>",
    "pend_time_format": (
        "⚠️ <b>Time format not recognized.</b>\n\n"
        "Correct format: <code>DD.MM.YYYY HH:MM</code>\n"
        "Example: <code>{example}</code> or time only — <code>18:00</code>\n\n"
        "🕒 <i>Tashkent time (UTC+5).</i>"
    ),
    "pend_content_ask": (
        "✏️ <b>Send the new post text:</b>\n\n"
        "HTML tags (<b>bold</b>, <i>italic</i>, <code>code</code>) are supported."
    ),
    "pend_content_success": "✅ <b>Post text updated!</b>",
    "pend_btn_ask": (
        "🔗 <b>Send the new button text:</b>\n\n"
        "Format: <code>Button text | https://link.uz</code>\n"
        "To delete the button, write: <code>no</code>."
    ),
    "pend_btn_removed": "✅ <b>Button deleted!</b>",
    "pend_btn_updated": "✅ <b>Button updated:</b> <code>{text}</code>",
    "pend_btn_format": (
        "⚠️ Wrong format!\nE.g.: <code>Details | https://sayt.uz</code>\n"
        "Or delete: <code>no</code>"
    ),
    "pend_react_ask": (
        "👍 <b>Change post reactions:</b>\n\nPick one of the options:"
    ),
    "pend_react_invalid": "⚠️ Pick one of the buttons:",
    "pend_react_off": "✅ <b>Reactions turned off!</b>",
    "pend_react_updated": "✅ <b>Reactions updated:</b> {emojis}",
    "pend_react_on": "✅ <b>Reactions turned on!</b>",
    "pend_update_fail": "❌ Could not change.",
    "pend_schedule_daily": "🔁 <b>Daily</b> at <b>{time}</b>",
    "pend_schedule_weekly": "📅 <b>Every {day}</b> at <b>{time}</b>",
    "pend_schedule_once": "⏰ Time: <b>{time}</b>",
    "pend_schedule_unknown": "⏰ Time: unknown",

    # ============================================================
    # FULL EN COVERAGE — batch H: queue & slots
    # ============================================================
    "queue_db_error": (
        "📅 <b>Scheduled</b>\n\n"
        "⚠️ Could not load scheduled posts right now "
        "(database connection error).\n"
        "Please try again in a bit."
    ),
    "queue_title": "📅 <b>Scheduled</b> — {count} post(s):",
    "queue_title_range": "📅 <b>Scheduled</b> — {count} post(s) ({start}-{end}):",
    "queue_empty": (
        "📅 <b>Scheduled</b>\n\n"
        "No scheduled posts yet.\n"
        "Create a new post and set its publishing time."
    ),
    "queue_empty_short": "📅 <b>Scheduled</b>\n\nNo scheduled posts.",
    "queue_limit_msg": (
        "🚫 <b>Scheduled posts limit reached!</b>\n\n"
        "You have <b>{current}/{max}</b> scheduled posts.\n"
        "The Free plan allows max <b>{max}</b> posts in the schedule.\n\n"
        "⭐️ Switch to PRO for unlimited scheduling."
    ),
    "queue_not_found": "⚠️ Post not found or already deleted.",
    "queue_not_found_short": "⚠️ Post not found!",
    "queue_no_slot": "⚠️ No free slot found!",
    "queue_deleted_alert": "🗑 Deleted!",
    "queue_view_title": "👁 <b>Post #{id}</b>",
    "queue_view_channel": "📢 Channel: {channel}",
    "queue_view_type": "📦 Type: {type}",
    "queue_view_time": "⏰ Time: {time}",
    "queue_view_content": "📋 Text:\n{content}",
    "queue_view_button": "🔘 Button: {text}",
    "queue_view_reactions": "👍 Reactions: On",
    "queue_view_auto_delete": "⏳ Auto-delete: {hours} h",
    "queue_btn_view": "👁 View #{id}",
    "queue_btn_delete": "🗑 Delete",
    "queue_btn_push": "⏩ Push",
    "queue_btn_prev": "⬅️ Previous",
    "queue_btn_next": "Next ➡️",
    "queue_btn_slots": "⚙️ Configure slots",
    "queue_btn_close": "❌ Close",
    "queue_btn_back": "⬅️ Back to list",
    "queue_btn_add_slot": "➕ Add new slot",
    "queue_btn_reset_slots": "🔄 Default slots",
    "queue_slots_title": (
        "⚙️ <b>Slot settings</b>\n\n"
        "Current slots: <code>{slots}</code>\n\n"
        "Posts are automatically scheduled for these times every day."
    ),
    "queue_slots_reset": (
        "⚙️ <b>Slot settings</b>\n\n"
        "Current slots: <code>{slots}</code>\n\n"
        "Default slots restored."
    ),
    "queue_slot_add_ask": (
        "➕ <b>Add new slot</b>\n\n"
        "Time format: <code>HH:MM</code>\n"
        "E.g.: <code>22:00</code>"
    ),
    "queue_slot_added": (
        "✅ Slot added: <code>{slot}</code>\n\n"
        "⚙️ <b>Slot settings</b>\n\n"
        "Current slots: <code>{slots}</code>"
    ),
    "queue_slot_exists": "⚠️ <code>{slot}</code> already exists!",
    "queue_slot_max": "⚠️ You can add max 10 slots!",
    "queue_slot_format": (
        "⚠️ Wrong format! Write as <code>HH:MM</code>.\n"
        "E.g.: <code>22:00</code>"
    ),
    "queue_slot_min": "⚠️ At least one slot must remain!",
    "queue_slot_reset_alert": "🔄 Default slots restored!",
    "btn_pending": "⏳ Pending posts",
    "btn_queue": "📅 Scheduled",

    # ============================================================
    # FULL EN COVERAGE — batch I-1: post enhancer (hub, reactions, buttons)
    # ============================================================
    "enh_notice_admin": (
        "💡 <b>Note:</b> for the bot to publish the post to your channel, "
        "first make sure you added it to the channel as an <b>Admin</b>."
    ),
    "enh_post_request": (
        "Send the post you want to publish to the channel "
        "(Text, Photo, Video or Forward from another channel):"
    ),
    "enh_intro_features": (
        "✅ The original text stays untouched — only:\n"
        "• 👍 up to 10 reactions (batch entry with spaces allowed),\n"
        "• 🔗 up to 10 URL buttons (with ready templates),\n"
        "• 👁 preview on request and 🚀 instant send to the channel."
    ),
    "enh_preset1_title": "Join channel",
    "enh_preset1_text": "📢 Join channel",
    "enh_preset2_title": "Join group",
    "enh_preset2_text": "💬 Join group",
    "enh_preset3_title": "Go to bot",
    "enh_preset3_text": "🤖 Go to bot",
    "enh_summary": (
        "👍 Reactions: <b>{rn}/{maxr}</b>{emojis}\n"
        "🔗 URL buttons: <b>{bn}/{maxb}</b>"
    ),
    "enh_post_line_type": "📦 <b>Type:</b> {type}",
    "enh_post_line_album_count": " ({n} media)",
    "enh_post_line_text": "\n📝 <b>Text:</b> <i>{preview}</i>",
    "enh_post_line_no_text": "\n📝 <b>Text:</b> <i>(no caption — media only)</i>",
    "enh_hub_title": (
        "✨ <b>Add Buttons & Reactions to post</b>\n\n"
        "{post}\n\n"
        "{summary}\n"
        "{note}{notice}\n\n"
        "Pick a step 👇"
    ),
    "enh_hub_btn_reacts": "👍 1. Reactions ({n}/{max})",
    "enh_hub_btn_buttons": "🔗 2. URL buttons ({n}/{max})",
    "enh_btn_preview": "👁️ Preview",
    "enh_btn_send_channel": "🚀 Send to channel",
    "enh_btn_replace": "🔁 Replace post",
    # ✨ PRO two-stage AI review — the button is visible ONLY to PRO users and
    # the post text changes only when the user taps it.
    "enh_btn_ai_audit": "✨ AI review (PRO)",
    "enh_audit_wait": "✨ AI review is running — polishing your post...",
    "enh_audit_done": (
        "✅ AI review (PRO) done — the post was replaced with the improved version."
    ),
    "enh_audit_fallback": (
        "⚠️ The AI review did not respond — your original post was kept unchanged."
    ),
    "enh_audit_text_only": "ℹ️ The AI review works only for text posts.",
    "enh_audit_pro_only": "⭐️ The AI review (2 stages) is available on the PRO plan only.",
    "enh_react_title": (
        "👍 <b>Step 1. Reactions</b> (<b>{n}/{max}</b>)\n\n"
        "Selected: {sel}\n\n"
        "• Tap an emoji button — it gets ✅, tap again to remove;\n"
        "• Or send several emojis <b>separated by space</b> in one message "
        "(e.g.: <code>👍 ❤️ 🔥 👏 🎉</code>);\n"
        "• You can add <b>{left}</b> more reactions.\n\n"
        "<i>The post is shown only at the final preview/confirmation step.</i>"
    ),
    "enh_react_none": "— (nothing selected)",
    "enh_react_done": "➡️ Continue / Go to URL buttons",
    "enh_react_done_count": "➡️ Continue / Go to URL buttons ({n})",
    "enh_btn_clear": "🗑 Clear",
    "enh_btns_title": (
        "🔗 <b>Step 2. URL buttons</b> (<b>{n}/{max}</b>)\n\n"
        "{body}\n\n"
        "Pick a ready template — the bot will ask only for the link.\n"
        "Manual entry: <code>Button name - https://link.com</code> or "
        "<code>Button name | @mychannel</code>"
    ),
    "enh_btns_empty": "<i>No buttons yet — pick a template or enter manually.</i>",
    "enh_btns_line": "{mark} <b>{text}</b> → <code>{url}</code>",
    "enh_btn_fallback": "Button",
    "enh_btn_add_new": "➕ Add new button",
    "enh_btn_manual": "✍️ Enter manually",
    "enh_btn_confirm_send": "➡️ Confirm & Send to channel",
    "enh_btn_entry_edit": "✏️ {num}. {text}",
    "enh_btn_add_title": (
        "➕ <b>New URL button</b> (<b>{n}/{max}</b>)\n\n"
        "Pick one of the ready templates — the bot will ask for <b>only the link</b>.\n\n"
        "Or send in one line via <b>✍️ Enter manually</b>:\n"
        "<code>Button name - https://link.com</code>\n"
        "<code>Button name | @mychannel</code>"
    ),
    "enh_channel_title": (
        "📢 <b>Which channel to send to?</b> ({n})\n\n"
        "<i>The post goes directly to the selected channel (no scheduling). "
        "Confirmation is asked at the end.</i>\n\n"
        "{notice}"
    ),
    "enh_channel_fallback": "Channel",
    "enh_channels_more": "…and {n} more (pick via the add-channel section)",
    "enh_confirm_no_channel": "⚠️ <b>Channel not selected.</b>\n\nPick a channel from the list.",
    "enh_btn_channel_list": "📢 Channel list",

    # ============================================================
    # FULL EN COVERAGE — batch I-2: post enhancer (confirm, send, errors)
    # ============================================================
    "enh_confirm_title": (
        "📢 <b>Confirm sending</b>\n\n"
        "Send this post to <b>{channel}</b>?\n\n"
        "{post}\n\n"
        "{summary}\n"
        "{note}"
        "\n<i>The post cannot be changed after sending.</i>"
    ),
    "enh_btn_confirm_yes": "✅ Yes, send it",
    "enh_btn_preview_first": "👁️ Preview first",
    "enh_success_text": (
        "✅ <b>Post published!</b>\n"
        "The post was successfully published to your channel!{where}\n\n"
        "If you want, you can send this post to another channel or enhance a new post 👇"
    ),
    "enh_success_where": "\n📢 <b>Channel:</b> {channel}",
    "enh_btn_home": "🏠 Main menu",
    "enh_btn_other_channel": "📢 To another channel",
    "enh_btn_new_post": "🚀 New post",
    "enh_btn_finish": "❌ Finish",
    "enh_note_admin": "👑 <i>Admin — the post goes out clean.</i>\n",
    "enh_note_free": (
        "🆓 <i>Free plan: when sent to the channel, {bot} is added "
        "to the top of the post.</i>\n"
    ),
    "enh_use_buttons": (
        "👇 <b>To enhance the post, pick one of the buttons below.</b>\n"
        "To replace the post — tap <b>🔁 Replace post</b>."
    ),
    "enh_album_reject": "⚠️ This media type cannot be added to an album — send it alone:",
    "enh_empty_msg": "⚠️ Empty message not accepted. Send the post text or media:",
    "enh_react_saved": "✅ <b>Reactions saved:</b> {sel}\nTotal: <b>{total}/{max}</b>{extra}",
    "enh_react_overflow_part": "\n⚠️ Limit is <b>{max}</b> — {items} did not fit.",
    "enh_react_dups_part": "\nℹ️ Duplicate emojis were ignored.",
    "enh_react_dups": "ℹ️ These emojis are already selected: {items}\nTotal: <b>{total}/{max}</b>",
    "enh_react_full": (
        "⚠️ <b>Reaction limit reached</b> (max {max}). Remove one first."
    ),
    "enh_react_hint_msg": (
        "ℹ️ Send only <b>emojis</b> — if several, <b>separated by space</b> "
        "(e.g.: <code>👍 ❤️ 🔥 👏 🎉</code>) or use the buttons below."
    ),
    "enh_bad_link": (
        "⚠️ <b>Invalid link.</b>\n\n"
        "Send only the link, e.g.: <code>{hint}</code>\n"
        "or <code>@channel_name</code>"
    ),
    "enh_bad_format": (
        "⚠️ <b>Wrong button format.</b>\n\n"
        "Send again:\n"
        "<code>Visit site - https://sayt.uz</code>\n"
        "<code>My channel | @kanalim</code>\n"
        "<code>https://t.me/bot_name/start</code> (label picked automatically)"
    ),
    "enh_btn_limit_reached": (
        "⚠️ You can add max <b>{max} URL buttons</b>. Delete one first."
    ),
    "enh_btn_verb_saved": "saved",
    "enh_btn_verb_updated": "updated",
    "enh_btn_saved": "✅ <b>Button {verb}:</b> {text} → <code>{url}</code>",
    "enh_session_expired": "⚠️ Session expired — reopen the menu.",
    "enh_home_msg": "🏠 <b>Main menu</b> — pick a section 👇",
    "enh_no_channels_alert": (
        "⚠️ No connected channels — first connect a channel and add the bot to it as Admin."
    ),
    "enh_react_limit_alert": "⚠️ Max {max} reactions!",
    "enh_channel_gone_alert": "⚠️ This channel is no longer in the list.",
    "enh_preset_missing": "⚠️ Template not found.",
    "enh_btn_limit_alert": "⚠️ Max {max} buttons!",
    "enh_btn_back_cancel": "⬅️ Cancel",
    "enh_btn_missing_alert": "⚠️ Button not found.",
    "enh_preview_follow_note": (
        "👆 <i>Above is the preview. The buttons will appear under this post in the channel.</i>"
    ),
    "enh_preview_failed": "⚠️ Could not build preview (media file invalid).",
    "enh_preview_error": "⚠️ Could not show preview.",
    "enh_too_fast": "⏳ Too fast — try again in a bit.",
    "enh_no_channel_sel": "⚠️ Channel not selected.",
    "enh_channel_not_owned": "⚠️ This channel is no longer in your list.",
    "enh_prepare_failed": "⚠️ Could not prepare the post. Please try again.",
    "enh_send_no_rights": (
        "⚠️ The bot is not a channel admin (or has no rights). "
        "Add the bot to the channel as admin."
    ),
    "enh_send_failed": "⚠️ Could not send: {error}",
    "enh_stale_notice": "⚠️ This menu has expired — reopen ⚙️ Extra features.",

    # ============================================================
    # FULL EN COVERAGE — batch J: misc
    # ============================================================
    "msg_closed": "✅ Closed.",
    "np_sticker_not_allowed": (
        "Sorry, stickers are not accepted as a post. "
        "Please send a photo, video or text"
    ),

    # ============================================================
    # FULL EN COVERAGE — batch K: shared / legacy AI / extract
    # ============================================================
    "op_cancelled": "❌ Cancelled.",
    "btn_share_referral": "🚀 Share with friends",
    "btn_check_subscription": "✅ Check subscription",
    "ref_share_text": "Hi! Schedule posts for your Telegram channels automatically and easily with this bot:",
    "sub_sponsor_fallback": "Sponsor channel",
    "pr_no_permission": "❌ You don't have permission to confirm payments.",
    "pr_error": "❌ An error occurred.",
    "ai_analyzing": "🤖 <i>AI is analyzing...</i>",
    "ai_legacy_welcome": (
        "🤖 <b>Welcome to the AI Assistant!</b>\n\n"
        "💎 Available AI requests: {credits}\n\n"
        "I can help you with:\n"
        "❓ <b>Q&A</b> — ask about the bot, posts, credits and channels.\n"
        "📝 <b>Post creation</b> — write a post topic or send a ready post/photo.\n"
        "🕒 <b>Free scheduling</b> — e.g.: <i>“prepare a post for all channels for today 15:45”</i>.\n\n"
        "👉 Write a post topic or your question.\n"
        "<i>To exit, press “{main_menu}”.</i>"
    ),
    "ai_legacy_media_hint": (
        "🖼 <b>Photo/media received!</b>\n\n"
        "Now send the post text or write the time, e.g.: <i>“for today 18:00”</i>."
    ),
    "ai_legacy_input_hint": "Please send post text, your question, or a photo/file:",
    "ai_legacy_faq_fallback": (
        "Sorry, I can only help with managing Telegram channels "
        "and scheduling posts."
    ),
    "ai_legacy_faq_footer": "\n\n<i>Ask another question or send a post topic 👇</i>",
    "ai_legacy_no_post": "Could not determine the post text. Please resend.",
    "ai_legacy_target_all": "\n🌐 <b>Channel:</b> To all connected channels",
    "ext_intro": (
        "📢 <b>Get a post from a public channel</b>\n\n"
        "Send the channel username OR link:\n"
        "• <code>@kunuzofficial</code>\n"
        "• <code>https://t.me/kunuzofficial</code>\n\n"
        "Or send a website link (e.g.: <code>https://kun.uz/</code>) — "
        "the bot will read the page and prepare an AI analysis.\n\n"
        "<i>Works for public channels only.</i>"
    ),
    "ext_btn_other_post": "🔙 Choose another post",
    "ext_btn_rewrite": "🔄 Rewrite",
    "ext_btn_refresh": "🔄 Refresh",
    "ext_media_preview": "🖼 Photo/Video",
    "ext_reading_site": "⏳ Reading the site...",
    "ext_site_read_failed": "⚠️ Could not read text from the site. Check the address and resend.",
    "ext_ai_analyzing_page": "⏳ AI is analyzing the page...",
    "ext_ai_page_failed": "⚠️ AI could not process the page.",
    "ext_ai_proposal_src": "✨ <b>AI suggestion ({src}):</b>\n\n{text}",
    "ext_ai_proposal": "✨ <b>AI suggestion:</b>\n\n{text}",
    "ext_reading_posts": "⏳ Reading channel posts...",
    "ext_post_accepted": (
        "✅ <b>Post accepted!</b>\n\n"
        "Now enter the button, time and other settings."
    ),
    "ext_private_channel_full": (
        "🔒 <b>This is a private channel.</b>\n\n"
        "Send a public channel or one where you are an admin.\n"
        "Example: <code>@kunuzofficial</code> or "
        "<code>https://t.me/kunuzofficial</code>"
    ),
    "ext_private_channel": (
        "🔒 This is a private channel. Send public channels or ones "
        "where you are an admin."
    ),
    "ext_not_found": (
        "❌ <b>{text}</b> — no such channel found.\n\n"
        "Check the address and resend:\n"
        "<code>@kanal</code> or <code>https://t.me/kanal</code>"
    ),
    "ext_invalid_username": (
        "⚠️ Invalid channel username or link. Please re-enter:\n"
        "<code>@kanal</code>, <code>kanal</code> or <code>https://t.me/kanal</code>\n\n"
        "Or a website link: <code>https://kun.uz/</code>"
    ),
    "ext_empty": (
        "📭 No posts found in <b>{channel}</b>.\n\n"
        "Send another channel or website link:"
    ),
    "ext_read_failed": (
        "❌ Could not read posts from <b>{channel}</b>.\n\n"
        "Reasons:\n"
        "• Channel is private\n"
        "• Wrong channel username\n"
        "• Channel has no posts\n\n"
        "Try again:"
    ),
    "ext_list_header": "📢 <b>@{channel}</b> — latest posts:\n",
    "ext_list_choose": "Choose which post to process 👇",
    "ext_media_only": "(image/video)",
    "ext_no_list": "⚠️ Post list is unavailable. Send a new channel or website link:",
    "ext_no_posts": "⚠️ No posts found.",
    "ext_invalid_post": "❌ Invalid post selected.",
    "ext_post_no_text": "⚠️ This post has no text (image/video only). Choose another post.",
    "ext_ai_rewriting": "⏳ AI is rewriting the post...",
    "ext_ai_rewrite_failed": "⚠️ AI could not rewrite the post.",
    "ext_no_post_text": "⚠️ Post text not found.",
    "ext_refreshing": "🔄 Refreshing...",
    "ext_rewriting": "🔄 Rewriting...",

    # ============================================================
    # FULL EN COVERAGE — batch L: content plan
    # ============================================================
    "cp_btn_create_post": "📝 Create post",
    "cp_btn_regenerate": "🔄 Regenerate",
    "cp_btn_back": "🔙 Back",
    "cp_btn_create_on_topic": "📝 Create a post on this topic",
    "cp_no_channel": (
        "⚠️ <b>Connect a channel first.</b>\n\n"
        "You need at least one channel to build a content plan.\n"
        "📢 Connect a channel in the Channels section."
    ),
    "cp_choose_channel": (
        "🧠 <b>Content Plan Generator</b>\n\n"
        "Which channel should we build a content plan for?"
    ),
    "cp_back_title": "🧠 <b>Which channel should we build a content plan for?</b>",
    "cp_closed": "❌ Closed.",
    "cp_topic_ask": (
        "🧠 <b>Content plan: {channel}</b>\n\n"
        "Briefly describe the channel topic.\n\n"
        "<i>For example:</i>\n"
        "• English from scratch\n"
        "• Kitchenware store\n"
        "• Healthy lifestyle\n"
        "• IT news"
    ),
    "cp_topic_short": "⚠️ Topic is too short. Write at least 3 characters.",
    "cp_ai_building": "⏳ AI is building the content plan...",
    "cp_ai_failed": "⚠️ AI could not build the plan.",
    "cp_ai_failed_retry": "⚠️ AI could not build the plan. Please try again.",
    "cp_plan_header": (
        "🧠 <b>7-day content plan</b>\n"
        "📢 Channel: <b>{channel}</b>\n"
        "📝 Topic: <i>{topic}</i>\n\n"
    ),
    "cp_plan_header_new": (
        "🧠 <b>7-day content plan (new)</b>\n"
        "📢 Channel: <b>{channel}</b>\n"
        "📝 Topic: <i>{topic}</i>\n\n"
    ),
    "cp_plan_day": "<b>📅 {day}</b> — {fmt}\n  📌 <b>{title}</b>\n",
    "cp_plan_idea": "  <i>{idea}</i>\n",
    "cp_day_fallback": "Day {n}",
    "cp_plan_footer": "\n\nPick a day and create a post right away 👇",
    "cp_regenerating": "🔄 Regenerating...",
    "cp_invalid_day": "❌ Invalid day selected.",
    "cp_day_detail": "📅 <b>{day}</b> — {fmt}\n\n📌 <b>{title}</b>\n\n{idea}\n\n{ask}",
    "cp_day_ask": "Do you want to create a post on this topic?",
    "cp_choose_day": "📅 <b>Which day should we create a post for?</b>",
    "cp_ai_writing": "⏳ AI is preparing the post text...",
    "cp_ai_write_failed": "⚠️ AI could not prepare the post text.",
    "cp_post_ready": (
        "✅ <b>Ready post:</b>\n\n{preview}\n\n"
        "📢 Channel: <b>{channel}</b>\n\n"
        "Now enter the button, time and other settings."
    ),
    "cp_button_ask": (
        "🔘 <b>Add a button?</b>\n\n"
        "Write the button text and URL:\n"
        "<code>Text | https://example.com</code>\n\n"
        "Or continue without a button 👇"
    ),

    # ============================================================
    # FULL EN COVERAGE — batch M: subscription / analytics
    # ============================================================
    "sub_pay_1m": "⭐️ 1 month (75 Stars)",
    "sub_pay_3m": "⭐️ 3 months (175 Stars)",
    "sub_pay_1y": "⭐️ 1 year (550 Stars)",
    "sub_pay_1m_full": "⭐️ For 1 month (75 Stars)",
    "sub_pay_3m_full": "⭐️ For 3 months (175 Stars)",
    "sub_pay_1y_full": "⭐️ For 1 year (550 Stars)",
    "sub_btn_promo": "🎁 Enter promo code",
    "sub_btn_send_receipt_admin": "✉️ Send receipt to admin",
    "sub_inv_title_1m": "⭐️ PostAssist PRO (1 month)",
    "sub_inv_title_3m": "⭐️ PostAssist PRO (3 months)",
    "sub_inv_title_1y": "⭐️ PostAssist PRO (1 year)",
    "sub_inv_desc_1m": "Full PRO features for 1 month",
    "sub_inv_desc_3m": "Full PRO features for 3 months",
    "sub_inv_desc_1y": "Full PRO features for 1 year (discounted)",
    "sub_invalid_plan": "❌ Invalid plan selected.",
    "sub_invoice_error": "⚠️ Error opening the payment window. Please try again.",
    "sub_promo_ask": (
        "🎁 <b>Enter the promo code:</b>\n\n"
        "Type the promo code or press “{back}”."
    ),
    "sub_promo_success": "✅ <b>{msg}</b>\n\nYour new plan features are activated!",
    "sub_promo_fail": "❌ <b>{msg}</b>\n\nTry again or press “{back}”.",
    "sub_pro_granted": (
        "🎉 <b>Congratulations!</b>\n\n"
        "You have been granted a <b>{days}-day PRO plan</b>!\n"
        "You can enjoy all PRO features."
    ),
    "sub_pay_activate_error": (
        "⚠️ Payment received, but plan activation failed.\n"
        "Please contact the admin."
    ),
    "sub_pay_duplicate": "✅ This payment has already been processed. Your PRO plan is already active.",
    "sub_pay_success": (
        "🎉 <b>Payment successful!</b>\n\n"
        "⭐️ {stars} Stars received.\n"
        "📅 <b>{days}-day PRO plan</b> activated!\n\n"
        "You can enjoy all PRO features:\n"
        "• Unlimited channels\n"
        "• Unlimited AI\n"
        "• Full analytics"
    ),
    "sub_pay_err_payload": "Invalid payment payload.",
    "sub_pay_err_user": "Payment does not match the user.",
    "sub_pay_err_user_id": "Invalid user ID.",
    "sub_pay_err_plan": "Invalid plan.",
    "sub_pay_err_currency": "Invalid payment currency.",
    "sub_pay_err_amount": "Payment amount does not match the plan.",
    "sub_pay_err_amount_bad": "Invalid payment amount.",
    "sub_pay_err_incomplete": "Payment details incomplete.",
    "sub_pay_err_bad_request": "Invalid payment request.",
    "an_all_channels": "All channels",
    "an_btn_all": "📊 All channels",
    "an_btn_other": "📢 Another channel",
    "an_btn_refresh": "🔄 Refresh",
    "an_refreshing": "🔄 Refreshing...",
    "an_free_hint": (
        "📊 <b>Analytics</b>\n\n"
        "📌 On the Free plan, statistics for the last <b>7 days</b> are shown.\n"
        "⭐️ The <b>PRO</b> plan unlocks full analytics (30 days, all posts, peak hours)!"
    ),
    "an_no_channels": (
        "⚠️ <b>You have no connected channels yet.</b>\n\n"
        "To view statistics, connect a channel first."
    ),
    "an_choose": "📊 <b>Analytics & Statistics</b>\n\nWhich channel's statistics do you want to see?",
    "an_choose_short": "📊 <b>Which channel's statistics do you want to see?</b>",
    "an_channel_fallback": "Channel",
    "an_dash_header": "📊 <b>{channel}</b> — Channel statistics",
    "an_dash_div": "━━━━━━━━━━━━━━━━━",
    "an_dash_empty": (
        "📊 <b>{channel}</b> — Channel statistics\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "📭 <b>No posts yet.</b>\n\n"
        "Schedule your first post and track statistics here!\n"
        "━━━━━━━━━━━━━━━━━"
    ),
    "an_dash_7d": "📤 Last 7 days: <b>{n}</b> posts",
    "an_dash_30d": "📦 Last 30 days: <b>{n}</b> posts",
    "an_dash_all": "📋 Total published: <b>{n}</b> posts",
    "an_dash_pending": "⏳ Waiting in queue: <b>{n}</b> posts",
    "an_dash_peak": "🕒 Peak hours: <b>{hours}</b>",
    "an_dash_types": "📁 Post types: {types}",
    "an_dash_no_data": "No data",
    "an_type_text": "Text",
    "an_type_photo": "Photo",
    "an_type_video": "Video",
    "an_type_document": "Document",
    "an_type_audio": "Audio",
    "an_type_animation": "GIF",
    "an_type_album": "Album",
    # ============================================================
    # 🌐 DATES (utils.date_format) and MANUAL PHOTO MODERATION (photo_check)
    # ============================================================
    "dt_today": "Today",
    "dt_tomorrow": "Tomorrow",
    # ── 🤖 AI Studio / Vision ──
    "ai_photo_unavailable": "⚠️ AI couldn't analyze this image. Please try again in a moment.",
    "ai_target_all_line": "🌐 <b>Channel:</b> All connected channels",
    "ai_target_all_name": "All connected channels",
    # ── 📸 IMAGE → POST (Killer Feature #3) ──
    "image_post_intro": (
        "📸 <b>Image → Post</b>\n\nSend a photo — I will identify the product, category, "
        "colour, material and use price/size/delivery details from its caption.\n\n"
        "<i>No AI credit is spent at this stage.</i>"
    ),
    "image_photo_only": "🖼 Please send a JPG, PNG or WEBP image.",
    "image_analysis_summary": (
        "📸 <b>Product identified:</b> {product}\n"
        "📂 Category: {category}\n"
        "🎨 Colour: {color} · 🧵 Material: {material}\n"
        "✨ Design: {design} · Style: {style}{facts}"
    ),
    "image_choose_style": "Which style should we use for the sales post? 👇",
    "image_choose_style_again": "Choose another style — a new credit is spent only after selection.",
    "image_style_sales": "🔥 Sales",
    "image_style_premium": "💎 Premium",
    "image_style_simple": "😊 Simple",
    "image_style_discount": "📢 Discount/Offer",
    "image_style_review": "📰 Review",
    "image_btn_cancel": "❌ Cancel",
    "image_btn_send": "📢 Send to channel",
    "image_btn_schedule": "📅 Schedule",
    "image_btn_restyle": "🔄 Another style",
    "image_btn_send_all": "📢 All channels ({count})",
    "image_analysis_error": "⚠️ Could not analyze the photo. Please send another image.",
    "image_generation_error": "⚠️ Could not create the post. Your credit was refunded; try again.",
    "image_no_credit": "🚫 You do not have enough AI credits. Get a bonus or switch to PRO.",
    "image_generating": "🤖 Creating a {style} post...",
    "image_preview_ready": "✅ Post ready! Photo and caption preview below:",
    "image_cancelled": "❌ Image → Post cancelled. No credit was spent.",
    "image_session_expired": "⚠️ The Image → Post session expired. Send the photo again.",
    "image_no_channels": "⚠️ Connect at least one channel first.",
    "image_choose_channel": "📢 Which channel should receive it?",
    "image_sent_ok": "✅ Photo post sent to {count} channel(s).",
    "image_send_error": "❌ Could not send to the channel. Please try again.",
    "image_schedule_prompt": "📅 Save it for what time? For example: <code>2026-09-13 18:30</code>",
    "image_schedule_invalid": "⚠️ Send the time as YYYY-MM-DD HH:MM.",
    "image_schedule_error": "❌ The photo post was not saved to the scheduler. Please try again.",
    "image_schedule_ok": "✅ Photo post saved for <b>{channel}</b> (ID: {post_id}).",
    # ── 📷 Manual photo check (handlers/photo_check.py) ──
    "pc_sent_user": "📸 Your photo was sent to the admin. Awaiting approval.",
    "pc_admin_caption": "🆔 User ID: <code>{user_id}</code>\n📷 Photo received.",
    "pc_btn_approve": "✅ Approve",
    "pc_btn_reject": "❌ Reject",
    "pc_approved_admin": "✅ <b>Approved!</b>\n\nPRO has been granted to user <code>{user_id}</code>.",
    "pc_rejected_admin": "❌ <b>Rejected.</b>\n\nThe user's PRO request was declined.",
    "pc_pro_granted": "🎉 <b>Congratulations!</b>\n\nYou have been granted the <b>30-day PRO plan</b>!\nAll PRO features are now available to you.",
    "pc_reject_notice": "⚠️ <b>Your photo was not approved.</b>\n\nPlease try again or contact the admin @shmat_uz for help.",
    "pc_no_permission": "❌ Not allowed.",
    "pc_no_pro_permission": "❌ You don't have permission to grant PRO to users.",
    "pc_bad_callback": "Invalid callback data.",
    "pc_bad_user_id": "Invalid user ID.",
    "pc_db_error": "Something went wrong.",


}
