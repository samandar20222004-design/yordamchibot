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
}
