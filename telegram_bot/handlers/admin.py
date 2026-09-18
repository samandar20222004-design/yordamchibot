import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError, BadRequest
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    # ⛔️ Eski admin reply-klaviaturasi (get_admin_panel_keyboard) endi
    # CHAQIRILMAYDI: 3-bosqichda butun admin boshqaruvi yagona INLINE
    # panelga o'tkazildi. Funksiya API mosligi uchun `keyboards.default`
    # da qoldi va endi har doim ReplyKeyboardRemove qaytaradi.
    get_main_keyboard,
    is_menu_text,
)
from keyboards.inline import (
    get_cache_actions_keyboard,
    get_admin_dashboard_keyboard, get_admin_back_keyboard,
    get_admin_monitoring_keyboard,
    get_ad_pool_menu_keyboard, get_ad_pool_delete_keyboard,
    get_ad_pool_back_keyboard, get_admin_sponsors_keyboard,
    get_ad_hub_keyboard,
    get_ad_edit_keyboard, get_ad_interval_keyboard,
    unpack_sponsor,
)
from utils import ai_agent
from locales.translations import clear_fsm_data, get_lang, get_text
# 👑 FAZA 26 — admin panelning BARCHA matnlari yagona i18n lug'atidan
# (translations/admin_panel.py — uz/ru/en 100% paritet) olinadi.
from translations import admin_t
# 6-bosqich: RBAC (rollar/ruxsatlar) va admin harakatlari auditi.
from keyboards.callback_data import CB_SPONSOR_DELETE
from services.rbac_service import (
    Role,
    CallbackTampering,
    admin_callback_guard,
    parse_callback_id,
    verify_admin_callback,
    PERM_MANAGE_PROMOS,
    PERM_MANAGE_USERS,
    PERM_SYSTEM_SETTINGS,
    has_permission,
    has_role,
    parse_role,
    remove_role,
    require_permission,
    require_role,
    required_permissions,
    set_role,
)
from services.audit_service import AuditService
from utils.helpers import (
    html_escape, safe_html, format_post_type_label,
    validate_ad_html, validate_button_text, validate_button_url,
    parse_button_input,
)

logger = logging.getLogger(__name__)

BROADCAST_MESSAGE = 801
ADD_SPONSOR_CHANNEL = 802
SET_CHANNEL_AD = 803
SET_BOT_REPLY_AD = 804
AI_SETTINGS = 805
SET_POST_TAG = 806
ADMIN_GRANT_PRO = 807
ADMIN_PROMO_CREATE = 808
ADMIN_SPONSOR_ADD = 809

# Broadcast har 20 xabardan keyin shuncha kutadi (Telegram ~30 msg/s limiti).
# 20 xabar / 0.7 s ≈ 28 msg/s — limitdan xavfsiz past.
BROADCAST_BATCH_SIZE = 20
BROADCAST_BATCH_DELAY = 0.7

# Bir vaqtda faqat bitta broadcast ishlashi uchun qulf
_broadcast_lock = asyncio.Lock()

# Telegram matnining ruxsat etilgan maksimal hajmi. UTF-16 birliklarini
# sanaymiz va HTML teglarini ham hisobga olamiz — bu API chegarasidan
# ehtiyotkorlik bilan pastda qoladi.
TELEGRAM_TEXT_LIMIT = 4096
ADMIN_CHANNELS_LIMIT = 20


def _short_text(value, max_length: int) -> str:
    """Ro'yxat qatori haddan tashqari uzun bo'lmasligi uchun qisqartiradi."""
    value = str(value or "")
    if len(value) <= max_length:
        return value
    return f"{value[:max_length - 1]}…"


def _telegram_text_length(text: str) -> int:
    """Telegram amalda ishlatadigan UTF-16 belgilar sonini qaytaradi."""
    return len(text.encode("utf-16-le")) // 2


def format_admin_channels_list(channels: list, lang: str = "uz") -> str:
    """Eng so'nggi kanallar uchun HTML-xavfsiz, 4096 dan oshmaydigan matn.

    🧹 FAZA 26: barcha yorliqlar i18n'dan (``admin_t``) — foydalanuvchi
    (admin) tanlagan tilda.
    """
    header = (
        admin_t("channels_recent_header", lang,
                count=len(channels), limit=ADMIN_CHANNELS_LIMIT)
        + "\n\n"
    )
    entries = []
    for channel_id, title, user_id, username in channels:
        title = _short_text(title or admin_t("channel_generic_title", lang), 160)
        channel_id = _short_text(channel_id, 64)
        owner = f"@{_short_text(username, 64)}" if username else f"ID:{user_id}"
        entries.append(
            admin_t("channels_entry", lang,
                    title=html_escape(title),
                    channel=html_escape(channel_id),
                    owner=html_escape(owner))
            + "\n\n"
        )

    visible_entries = entries[:]
    while True:
        omitted = len(entries) - len(visible_entries)
        footer = (
            admin_t("channels_omitted_footer", lang, count=omitted)
            if omitted else ""
        )
        text = header + "".join(visible_entries) + footer
        if _telegram_text_length(text) <= TELEGRAM_TEXT_LIMIT or not visible_entries:
            return text
        # Eng yangi kanallar yuqorida qoladi; faqat sig'magan eski qatorni olamiz.
        visible_entries.pop()


# Admin panelda ko'rsatiladigan AI parametrlari (kalit -> (DB key, UI belgi,
# i18n tavsif kaliti)). 🧹 FAZA 26: tavsiflar endi ``admin_t()`` orqali
# uchala tilda (uz/ru/en) chiziladi — UI belgilari texnik atamalar.
AI_SETTINGS_KEYS = {
    "temperature": ("ai_temperature", "🌡 temperature", "ai_hint_temperature"),
    "max_tokens": ("ai_max_tokens", "📄 max_tokens", "ai_hint_max_tokens"),
    "top_p": ("ai_top_p", "🎯 top_p", "ai_hint_top_p"),
    "max_prompt_chars": ("ai_max_prompt_chars", "🧩 prompt limiti", "ai_hint_max_prompt_chars"),
    "context_chars": ("ai_context_chars", "💬 kontekst hajmi", "ai_hint_context_chars"),
    "context_messages": ("ai_context_messages", "🧠 kontekst xabarlari", "ai_hint_context_messages"),
    "extra_context": ("ai_extra_context", "📌 qo'shimcha ko'rsatma", "ai_hint_extra_context"),
}


def _ai_settings_text(lang: str = "uz") -> str:
    params = ai_agent.get_runtime_params()
    lines = []
    for key, (db_key, label, hint_key) in AI_SETTINGS_KEYS.items():
        value = params.get(key)
        value_text = "-" if value in (None, "") else str(value)
        hint = admin_t(hint_key, lang)
        lines.append(f"   • <b>{label}</b> = <code>{html_escape(value_text)}</code>  <i>({hint})</i>")
    return "\n".join(lines)


def _build_dashboard_text(stats: dict, lang: str = "uz") -> str:
    """Admin dashboard matnini yaratadi (admin tilida — FAZA 26)."""
    return (
        admin_t("dash_title", lang) + "\n"
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("dash_users", lang, users=stats['users']) + "\n"
        + admin_t("dash_pro", lang, pro=stats['pro_subscribers']) + "\n"
        + admin_t("dash_channels", lang, channels=stats['channels']) + "\n"
        + admin_t("dash_posts_today", lang, posts=stats['posts_today']) + "\n"
        + admin_t("dash_pending", lang, pending=stats['pending_posts']) + "\n"
        + admin_t("dash_stars", lang, stars=stats['stars_revenue']) + "\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        + admin_t("dash_pick_section", lang)
    )


def _build_full_stats_text(stats: dict, lang: str = "uz") -> str:
    """📊 YAGONA «To'liq statistika» ekrani (4-qadam: dublikatlar birlashdi).

    Bir vaqtda UCHTA dublikat handler bu matnni chizardi (``adm_stats``
    callback'i, ``/admin_stats`` buyrug'i va «📊 Statistika» reply-tugmasi /
    ``/stats``). Endi hammasi SHU bitta builder'ga ulangan — ekran ham,
    raqamlar ham har doim bir xil (eski yo'llar alias sifatida ishlaydi).
    FAZA 26: matn admin tilida (``lang``) chiziladi.
    """
    return (
        admin_t("fs_title", lang) + "\n\n"
        + admin_t("fs_users", lang, users=stats['users']) + "\n"
        + admin_t("fs_channels", lang, channels=stats['channels']) + "\n"
        + admin_t("fs_sponsors", lang, sponsors=stats['sponsors']) + "\n"
        + admin_t("fs_pending", lang, pending=stats['pending']) + "\n"
        + admin_t("fs_sent", lang, sent=stats['sent']) + "\n"
        + admin_t("fs_cancelled", lang, cancelled=stats['cancelled']) + "\n"
        + admin_t("fs_failed", lang, failed=stats['failed'])
    )


def _build_admin_posts_text(posts: list, lang: str = "uz") -> str:
    """📋 YAGONA «Barcha postlar» ekrani (``adm_posts`` + eski reply-tugma).

    ``posts`` — ``db.get_recent_posts`` natijasi (pid, uid, title, ptype,
    stime, status). Bo'sh ro'yxat uchun ham xavfsiz matn qaytaradi.
    """
    if not posts:
        return (admin_t("posts_empty_title", lang) + "\n\n"
                + admin_t("posts_empty_body", lang))
    text = admin_t("posts_recent_header", lang, count=len(posts)) + "\n\n"
    for p in posts:
        pid, uid, title, ptype, stime, status = (list(p) + [None] * 6)[:6]
        title_str = title or admin_t("posts_unknown_channel", lang)
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "posted" else "🚫")
        text += (
            f"{status_emoji} <b>#{pid}</b> | {html_escape(str(title_str))}"
            f" | {format_post_type_label(ptype)} | {html_escape(str(status))}\n"
        )
    return text


def _dbcache_labels(status: dict, lang: str = "uz") -> dict:
    """🗄️ DB/Kesh ekranining tilga mos yorliqlari (3 xil chaqiruvchi uchun umumiy)."""
    return {
        "collapsed": admin_t("lbl_no", lang) if status.get("collapsed") else admin_t("lbl_yes", lang),
        "cache": (admin_t("lbl_cache_on", lang) if status.get("cache_enabled")
                  else admin_t("lbl_cache_off", lang)),
        "pool": (admin_t("lbl_pool_ready", lang) if status.get("ready")
                 else admin_t("lbl_pool_init", lang)),
    }


def _build_dbcache_text(status: dict, lang: str = "uz",
                        pool_message: bool = True, cleared: bool = False) -> str:
    """🗄️ YAGONA «DB / Kesh holati» ekrani (``adm_dbcache`` + eski reply-tugma).

    🧹 FAZA 26: ``cache_db_menu`` va ``cache_clear_callback`` ham shu
    builder'dan foydalanadi — dublikat matn bloklari yo'q; matn admin
    tilida. ``cleared=True`` — kesh tozalangach ko'rsatiladigan footer.
    """
    labels = _dbcache_labels(status, lang)
    pool_line = admin_t("dbc_pool", lang, pool=labels["pool"],
                        message=status.get("message", "")) if pool_message else (
        f"   • Pool: <b>{labels['pool']}</b>\n")
    footer = admin_t("dbc_cleared_footer", lang) if cleared else admin_t("dbc_footer", lang)
    return (
        admin_t("dbc_title", lang) + "\n\n"
        + pool_line
        + admin_t("dbc_minmax", lang, minv=status.get("min"), maxv=status.get("max")) + "\n"
        + admin_t("dbc_usage", lang, used=status.get("used"),
                  available=status.get("available"), collapsed=labels["collapsed"]) + "\n"
        + admin_t("dbc_cache", lang, cache=labels["cache"],
                  entries=status.get("cache_entries")) + "\n\n"
        + footer
    )


#: Holat → emoji (health_service'dagi bilan bir xil qoida).
_HEALTH_STATUS_EMOJI = {
    "OK": "✅", "HEALTHY": "✅", "RUNNING": "✅",
    "DEGRADED": "⚠️", "STOPPED": "🛑", "UNCONFIGURED": "⚪️",
    "UNHEALTHY": "❌", "UNKNOWN": "❔", "DISABLED": "⚪️",
}


def _health_mark(status) -> str:
    return _HEALTH_STATUS_EMOJI.get(str(status or ""), "❔")


async def build_admin_health_block(lang: str = "uz") -> str:
    """⚙️ ADMIN PANEL — tizim monitoringi (Health status) bloki.

    Faqat admin panelga kirilganda dashboard matniga qo'shiladi va 4 ta
    majburiy bo'limni ixcham ko'rsatadi:

      * 🖥 Bot & DB holati (latency bilan);
      * ⏰ Scheduler holati (faol joblar soni);
      * 🤖 AI provayderlar (Gemini, Groq, OpenRouter ...);
      * 💳 Pending manual to'lovlar (tasdiq kutilayotgan cheklar).

    Qat'iy qoida: health bloki HECH QACHON istisno ko'tarmaydi — xato
    bo'lsa bo'sh satr qaytadi (dashboard baribir chiqadi).
    """
    from translations import settings_stats_t

    try:
        from services.health_service import get_system_health

        health = await get_system_health()
        db_info = health.get("database") or {}
        sched = health.get("scheduler") or {}
        ai = health.get("ai_providers") or {}
        pay = health.get("payments") or {}

        lines = [
            "━━━━━━━━━━━━━━━━━",
            settings_stats_t("ss_health_title", lang),
        ]
        db_line = settings_stats_t(
            "ss_health_bot_db", lang,
            status=f"{_health_mark(db_info.get('status'))} {db_info.get('status', '❔')}",
        )
        if db_info.get("latency_ms") is not None:
            db_line += settings_stats_t(
                "ss_health_db_latency", lang, ms=int(db_info["latency_ms"]),
            )
        lines.append(db_line)

        sched_line = settings_stats_t(
            "ss_health_scheduler", lang,
            status=f"{_health_mark(sched.get('status'))} {sched.get('status', '❔')}",
        )
        if sched.get("jobs") is not None:
            sched_line += settings_stats_t(
                "ss_health_jobs", lang, n=int(sched["jobs"]),
            )
        lines.append(sched_line)

        lines.append(settings_stats_t("ss_health_ai", lang))
        for provider in ai.get("providers") or []:
            lines.append(settings_stats_t(
                "ss_health_ai_row", lang,
                name=provider.get("name", "?"),
                status=f"{_health_mark(provider.get('status'))} "
                       f"{provider.get('status', '❔')}",
            ))

        lines.append(settings_stats_t(
            "ss_health_pending_pays", lang,
            n=int(pay.get("pending_receipts") or 0),
        ))
        lines.append("━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:  # pragma: no cover - health himoyasi
        logger.debug("Admin health bloki qurilmadi: %s", e)
        return ""


def is_admin(user_id: int) -> bool:
    """Admin tekshiruvi: legacy ``ADMIN_IDS`` yoki RBAC roli bo'lsa.

    Tez yo'l — eski ``ADMIN_ID``/``ADMIN_IDS`` ro'yxati (DB'siz ishlaydi).
    Qo'shimcha: 6-bosqichda DB orqali berilgan rol (``admin_roles``) ham
    admin panelini ochishga haqli (natija 60 soniya keshlanadi).
    """
    if user_id in ADMIN_IDS_SET:
        return True
    try:
        from services.rbac_service import is_admin as rbac_is_admin
        return rbac_is_admin(user_id)
    except Exception:  # pragma: no cover - RBAC import/DB xatosi
        return False


def _remember_admin_section(context) -> None:
    """🧭 4-qadam: admin bo'limi yozuvi — [❌ Bekor qilish] dashboard'ga qaytadi.

    Eski admin reply-tugmalari (⚙️ AI parametrlari, 🗄️ DB/Kesh, 🏷 Post
    nishoni, 📢 Ommaviy xabar ...) dashboard'ga integratsiya qilinganidan
    keyin ham to'g'ridan-to'g'ri ochilishi mumkin — shu yerda ham foydalanuvchi
    admin bo'limida ekanini belgilab qo'yamiz.
    """
    try:
        from handlers.navigation import remember_section, SECTION_ADMIN
        remember_section(context, SECTION_ADMIN)
    except Exception:  # pragma: no cover — navigatsiya xizmati majburiy emas
        logger.debug("admin nav_section yozilmadi")


# ============================================================
# ADMIN PANEL DASHBOARD
# ============================================================

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Admin Panel — FAQAT adminlar uchun (RBAC qat'iy tekshiruvi).

    Oddiy foydalanuvchi bu yerga HECH QACHON kira olmaydi: ``is_admin``
    (legacy ADMIN_IDS + RBAC rollari) tekshiruvidan o'tmagan update jim
    rad etiladi. Admin kirganda dashboard bilan birga TIZIM MONITORINGI
    (Health status) bloki ham ko'rsatiladi: Bot & DB, Scheduler, AI
    provayderlar (Gemini/Groq/OpenRouter) va pending manual to'lovlar.

    ⛔️ 3-bosqich: pastdagi oq 10 talik ADMIN REPLY-KLAVIATURASI BU YERDA
    HAM, boshqa admin handlerlarida ham CHIZILMAYDI — panel faqat INLINE
    (``get_admin_dashboard_keyboard``) bo'lib qoldi. Reply klaviatura
    o'rnida foydalanuvchining mavjud asosiy menyusi saqlanadi; eski admin
    matnlari esa faqat routing ALIAS'i (chat tarixidan yozilsa ishlaydi).
    """
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    clear_fsm_data(context)
    # 🧭 4-qadam: admin endi «👑 Admin» bo'limida — admin FSM oqimlarida
    # [❌ Bekor qilish] (adm_cancel) aynan shu dashboard'ga qaytadi.
    from handlers.navigation import remember_section, SECTION_ADMIN
    remember_section(context, SECTION_ADMIN)
    stats = await db.run_db(db.get_admin_dashboard_stats)
    text = _build_dashboard_text(stats, get_lang(context))
    # 🩺 Tizim monitoringi — faqat adminlar ko'radi (health hech qachon
    # istisno ko'tarmaydi; xato bo'lsa dashboard baribir chiqadi).
    health_block = await build_admin_health_block(get_lang(context))
    if health_block:
        text = f"{text}\n{health_block}"
    await update.message.reply_text(
        text,
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/admin_stats` — eski buyruq, endi YAGONA «To'liq statistika» ekrani.

    4-qadam: dublikat statistika handlerlari (``/admin_stats``, ``/stats``
    va «📊 Statistika» reply-tugmasi) bitta ekranga birlashtirildi — hammasi
    ``_build_full_stats_text`` orqali AYNAN bir xil matn chiqaradi.
    """
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    stats = await db.run_db(db.get_system_stats)
    await update.message.reply_text(
        _build_full_stats_text(stats, get_lang(context)),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# ADMIN INLINE CALLBACK HANDLERS
# ============================================================

async def _admin_edit(query, text: str, reply_markup=None):
    """Admin ekranini tahrirlaydi; imkoni bo'lmasa yangi xabar yuboradi."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramError:
        try:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except TelegramError:
            logger.debug("Admin ekranini ko'rsatib bo'lmadi")


async def _build_audit_roles_text(limit: int = 10, lang: str = "uz") -> str:
    """📜 YAGONA «Audit | Rollar» ekrani matni (``adm_audit_roles``).

    Ikki blok: (1) oxirgi admin harakatlari — ``/audit`` buyrug'i bilan
    AYNAN bir xil format; (2) ``admin_roles`` jadvalidagi faol rollar.
    DB xatosida ham crash qilmaydi — bo'sh blok matni qaytaradi.
    """
    lines = [admin_t("audit_log_title", lang),
             "━━━━━━━━━━━━━━━━━"]
    try:
        rows = await db.run_db(db.get_admin_audit_logs, limit=limit) or []
    except Exception as e:  # pragma: no cover — DB xatosi ham ekranni buzmaydi
        logger.warning("adm_audit_roles: audit o'qilmadi: %s", e)
        rows = []
    if rows:
        for row in rows:
            created = row.get("created_at")
            try:
                when = created.strftime("%d.%m.%Y %H:%M")
            except Exception:
                when = str(created or "")[:16]
            target = ""
            if row.get("target_type"):
                target = f" → <code>{html_escape(str(row.get('target_type')))}"
                if row.get("target_id"):
                    target += f"#{html_escape(str(row.get('target_id')))}"
                target += "</code>"
            lines.append(
                f"🕒 <b>{html_escape(when)}</b> | 👤 <code>{html_escape(str(row.get('admin_id')))}</code>\n"
                f"   {html_escape(str(row.get('action')))}{target}"
            )
    else:
        lines.append(admin_t("audit_empty_inline", lang))

    lines += ["", admin_t("audit_roles_title", lang),
              "━━━━━━━━━━━━━━━━━"]
    try:
        roles = await db.run_db(db.list_admin_roles, limit=20) or []
    except Exception as e:  # pragma: no cover — DB xatosi ham ekranni buzmaydi
        logger.warning("adm_audit_roles: rollar o'qilmadi: %s", e)
        roles = []
    if roles:
        for r in roles:
            lines.append(
                f"👤 <code>{r.get('user_id')}</code> — 🎖 <b>{html_escape(str(r.get('role')))}</b>"
            )
    else:
        lines.append(admin_t("audit_roles_empty", lang))
    return "\n".join(lines)


async def _ad_hub_render(lang: str = "uz") -> tuple[str, InlineKeyboardMarkup]:
    """Reklama boshqaruvi ekrani — FAQAT 3 ta asosiy bo'lim.

    1) 📢 Majburiy obuna (Sponsor kanallar)
    2) 🤖 3-5 ta javobda chiqadigan reklama
    3) 📢 Kanal postlariga reklama qo'shish

    Har bir bo'limda: matn (reklama puli), oraliq, tugma va yoqish/o'chirish.
    """
    settings = await db.run_db(db.get_ad_settings)
    interval = await db.run_db(db.get_channel_ad_interval)
    channel_ads = await db.run_db(db.get_ads_full, "channel", True)
    reply_ads = await db.run_db(db.get_ads_full, "reply", True)
    sponsors = await db.run_db(db.get_sponsor_channels) or []
    ch_active = sum(1 for a in channel_ads if a.get("is_active", True))
    rp_active = sum(1 for a in reply_ads if a.get("is_active", True))
    reply_status = bool(settings.get("auto_ad_status", False))
    channel_status = bool(settings.get("channel_ad_status", True))
    reply_interval = settings.get("auto_ad_interval", 4)

    def _mark(on: bool) -> str:
        return admin_t("lbl_on", lang) if on else admin_t("lbl_off", lang)

    lines = [
        admin_t("ad_hub_title", lang),
        "━━━━━━━━━━━━━━━━━",
        admin_t("ad_hub_s1_title", lang) + "\n"
        + admin_t("ad_hub_s1_line", lang, count=len(sponsors)),
        "━━━━━━━━━━━━━━━━━",
        admin_t("ad_hub_s2_title", lang) + "\n"
        + admin_t("ad_hub_pool_line", lang, active=rp_active, total=len(reply_ads)) + "\n"
        + admin_t("ad_hub_interval_reply", lang, interval=reply_interval) + "\n"
        + admin_t("ad_hub_state_line", lang, state=_mark(reply_status)),
        "━━━━━━━━━━━━━━━━━",
        admin_t("ad_hub_s3_title", lang) + "\n"
        + admin_t("ad_hub_pool_line", lang, active=ch_active, total=len(channel_ads)) + "\n"
        + admin_t("ad_hub_interval_channel", lang, interval=interval) + "\n"
        + admin_t("ad_hub_state_line", lang, state=_mark(channel_status)),
        "━━━━━━━━━━━━━━━━━",
        admin_t("ad_hub_pick", lang),
    ]
    markup = get_ad_hub_keyboard(
        channel_total=len(channel_ads), channel_active=ch_active,
        reply_total=len(reply_ads), reply_active=rp_active,
        auto_status=reply_status, auto_interval=reply_interval,
        channel_interval=interval, channel_status=channel_status,
        sponsors_count=len(sponsors),
    )
    return "\n".join(lines), markup


# ESLATMA: "🛠 Tizim sozlamalari" (``adm_settings``) bo'limi admin paneldan
# BUTUNLAY olib tashlandi (ixchamlashtirish talabi). Post nishoni (watermark)
# sozlamasi hamon "🏷 Post nishoni" reply-tugmasi orqali (start_set_post_tag /
# post_tag_received) o'zgartiriladi — faqat inline dashboard'dagi alohida
# "Tizim sozlamalari" ko'rish ekrani va uning dublikat statistikasi
# (kanal post sanagichlari, reklama holati) olib tashlandi.


def _build_sponsor_manage_text(sponsors: list, lang: str = "uz") -> str:
    """📢 Sponsor kanallar boshqaruvi matni (``adm_sponsors`` + ``del_sponsor``).

    🧹 FAZA 26: ikkala handler AYNAN shu builder'dan foydalanadi — dublikat
    matn bloklari yo'q; matn admin tilida (uz/ru/en).
    """
    sponsors = sponsors or []
    count = len(sponsors)
    text = (
        admin_t("sp_manage_title", lang) + "\n"
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("sp_count", lang, count=count) + "\n\n"
    )
    if sponsors:
        for idx, s in enumerate(sponsors, 1):
            s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
            u_info = f" (@{username})" if username else ""
            link_info = f"\n   🔗 {ch_url}" if ch_url else ""
            text += (
                f"{idx}. <b>{html_escape(ch_title)}</b>{u_info} "
                f"(<code>{ch_id}</code>){link_info}\n\n"
            )
    else:
        text += admin_t("sp_empty_inline", lang) + "\n\n"
    text += "━━━━━━━━━━━━━━━━━\n" + admin_t("sp_manage_footer", lang)
    return text


async def admin_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard inline tugmalari.

    Har bir matn kutuvchi bo'lim tegishli FSM holatini QAYTARADI — shu sababli
    admin yozgan javob to'g'ri handlerga tushadi (avval holat qaytarilmagani
    uchun matnli oqimlar ishlamay qolardi).
    """
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer(admin_t("rbac_denied", get_lang(context)), show_alert=True)
        return ConversationHandler.END
    # 11-bosqich (P0): server-side RBAC — payload emas, from_user.id hal qiladi.
    if not verify_admin_callback(update):
        await query.answer(admin_t("rbac_denied", get_lang(context)), show_alert=True)
        return ConversationHandler.END
    data = query.data
    # 🧹 FAZA 26: butun dashboard adminning TANLANGAN tilida chiziladi.
    lang = get_lang(context)

    if data == "adm_cancel":
        # Universal "Bekor qilish": FSM tozalanadi va dashboard qaytariladi.
        await query.answer(admin_t("cancelled_toast", lang))
        clear_fsm_data(context)
        stats = await db.run_db(db.get_admin_dashboard_stats)
        await _admin_edit(query, _build_dashboard_text(stats, lang), get_admin_dashboard_keyboard())
        return ConversationHandler.END

    if data == "adm_stats":
        await query.answer()
        stats = await db.run_db(db.get_system_stats)
        # 4-qadam: YAGONA statistika ekrani (reply-tugma va /admin_stats
        # buyrug'i ham aynan shu matnni chiqaradi).
        await _admin_edit(query, _build_full_stats_text(stats, lang), get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_channels":
        await query.answer()
        channels = await db.run_db(db.get_all_channels, ADMIN_CHANNELS_LIMIT)
        if channels:
            text = format_admin_channels_list(channels, lang)
        else:
            text = (admin_t("channels_empty_title", lang) + "\n\n"
                    + admin_t("channels_empty_body", lang))
        await _admin_edit(query, text, get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_posts":
        # 📋 Barcha postlar — eski «📋 Barcha postlar» reply-tugmasi va
        # ``admin_all_posts`` handleri bilan AYNAN bir xil ekran (4-qadam:
        # reply-klaviatura to'liq dashboard'ga integratsiya qilindi).
        await query.answer()
        recent_posts = await db.run_db(db.get_recent_posts, 15)
        await _admin_edit(query, _build_admin_posts_text(recent_posts, lang),
                          get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_tag":
        # 🏷 Post nishoni (watermark) — eski reply-tugma oqimini ochadi
        # (``start_set_post_tag`` / ``post_tag_received``). Matn kutish
        # FSM holati talab qilgani uchun SET_POST_TAG qaytariladi; o'zgarish
        #ning o'zi ``post_tag_received`` ichida OWNER ruxsati bilan
        # fail-closed tekshiriladi.
        await query.answer()
        current_tag = await db.run_db(db.get_setting, "post_tag_text", "")
        await _admin_edit(
            query,
            admin_t("tag_title", lang) + "\n\n"
            + admin_t("tag_current", lang, value=html_escape(
                current_tag or admin_t("tag_empty_value", lang))) + "\n\n"
            + admin_t("tag_howto", lang),
            get_admin_back_keyboard(),
        )
        context.user_data.pop("admin_flow", None)
        return SET_POST_TAG

    if data == "adm_ai":
        # ⚙️ AI parametrlari — eski reply-tugma oqimini ochadi
        # (``ai_settings_menu`` / ``ai_settings_received``). Parametrni
        # O'ZGARTIRISH faqat OWNER (system_settings) ruxsati bilan —
        # ``ai_settings_received`` dekoratorida fail-closed.
        await query.answer()
        await _admin_edit(
            query,
            admin_t("ai_title", lang) + "\n\n"
            f"{_ai_settings_text(lang)}\n\n"
            + admin_t("ai_howto", lang) + "\n\n"
            + admin_t("ai_reset_hint", lang),
            get_admin_back_keyboard(),
        )
        context.user_data.pop("admin_flow", None)
        return AI_SETTINGS

    if data == "adm_dbcache":
        # 🗄️ DB / Kesh holati — eski reply-tugma ekrani bilan AYNAN bir xil
        # (``cache_db_menu``); keshni tozalash tugmasi ham shu yerda qoladi
        # (``cache_clear`` — OWNER ruxsati bilan fail-closed).
        await query.answer()
        status = await db.run_db(db.get_db_pool_status)
        await _admin_edit(query, _build_dbcache_text(status, lang),
                          get_cache_actions_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_audit_roles":
        # 📜 Audit | 👥 Rollar — /audit buyrug'i bilan bir xil ma'lumot +
        # RBAC rollari ro'yxati. Faqat OWNER/SUPER_ADMIN (``/audit`` bilan
        # bir xil qoida — ``admin_audit_command`` dekoratori).
        if not has_role(query.from_user.id, Role.SUPER_ADMIN):
            await query.answer(admin_t("audit_denied", lang),
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(query, await _build_audit_roles_text(lang=lang),
                          get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_health":
        # 🩺 Tizim monitoringi — to'liq Health hisoboti. Yuqoridagi is_admin
        # + verify_admin_callback tekshiruvlaridan o'tgan bo'lsa ham, hisobot
        # faqat system_settings ruxsati (RBAC) bo'lgan adminlarga ochiladi
        # (/health buyrug'i bilan bir xil qoida — fail-closed).
        if not has_permission(query.from_user.id, PERM_SYSTEM_SETTINGS):
            await query.answer(admin_t("perm_health", lang),
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        from services.health_service import format_health_report

        try:
            text = await format_health_report(lang=lang)
        except Exception as e:
            logger.error("adm_health: hisobot yaratishda xato: %s", e)
            text = get_text("sys_busy", lang)
        # 3-bosqich: «📜 Audit | 👥 Rollar» dashboard'dan shu monitoring
        # ekraniga ko'chirildi (yagona dashboard 12 tugma standarti), lekin
        # ``adm_audit_roles`` callback'i va uning RBAC tekshiruvi o'zgarmadi.
        await _admin_edit(query, text, get_admin_monitoring_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_promo":
        if not has_permission(query.from_user.id, PERM_MANAGE_PROMOS):
            await query.answer(admin_t("perm_promo", lang),
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            admin_t("promo_title", lang) + "\n\n" + admin_t("promo_howto", lang),
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "promo_create"
        return ADMIN_PROMO_CREATE

    if data == "adm_grant_pro":
        if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
            await query.answer(admin_t("perm_grant_pro", lang),
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            admin_t("gp_title", lang) + "\n\n" + admin_t("gp_howto", lang),
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "grant_pro"
        return ADMIN_GRANT_PRO

    if data == "adm_broadcast":
        if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
            await query.answer(admin_t("perm_broadcast", lang),
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            admin_t("bc_title", lang) + "\n\n" + admin_t("bc_prompt", lang),
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "broadcast"
        return BROADCAST_MESSAGE

    if data == "adm_sponsors":
        await query.answer()
        sponsors = await db.run_db(db.get_sponsor_channels) or []
        text = _build_sponsor_manage_text(sponsors, lang)
        await _admin_edit(query, text, get_admin_sponsors_keyboard(sponsors))
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_add_sponsor":
        await query.answer()
        await _admin_edit(
            query,
            admin_t("sp_add_inline_title", lang) + "\n\n"
            + admin_t("sp_add_inline_howto", lang),
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "add_sponsor"
        return ADMIN_SPONSOR_ADD

    if data in ("adm_adhub", "adm_auto_ad"):
        # Yagona Reklama markazi. ``adm_auto_ad`` — eski xabarlar uchun
        # orqaga moslik aliasi (dashboard eski versiyasida shu tugma bor edi).
        await query.answer()
        text, markup = await _ad_hub_render(lang)
        await _admin_edit(query, text, markup)
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_ad_toggle":
        ad_settings = await db.run_db(db.get_ad_settings)
        new_status = not ad_settings.get("auto_ad_status", False)
        await db.run_db(db.set_ad_status, new_status)
        await query.answer(
            admin_t("ad_toggle_on", lang) if new_status
            else admin_t("ad_toggle_off", lang)
        )
        # Holat o'zgach to'liq hub qayta chiziladi — eski alohida ekran
        # (Har 3-5 javob reklamasi) endi mavjud emas.
        text, markup = await _ad_hub_render(lang)
        await _admin_edit(query, text, markup)
        return ConversationHandler.END

    if data == "adm_channel_ad_toggle":
        # 3-bo'lim: 📢 Kanal postlariga reklama qo'shish — yoqish/o'chirish.
        ad_settings = await db.run_db(db.get_ad_settings)
        new_status = not ad_settings.get("channel_ad_status", True)
        await db.run_db(db.set_channel_ad_status, new_status)
        await query.answer(
            admin_t("ch_ad_toggle_on", lang) if new_status
            else admin_t("ch_ad_toggle_off", lang)
        )
        text, markup = await _ad_hub_render(lang)
        await _admin_edit(query, text, markup)
        return ConversationHandler.END

    if data == "adm_back":
        await query.answer()
        stats = await db.run_db(db.get_admin_dashboard_stats)
        await _admin_edit(query, _build_dashboard_text(stats, lang), get_admin_dashboard_keyboard())
        context.user_data.pop("admin_flow", None)
        context.user_data.pop("ad_edit", None)
        return ConversationHandler.END

    await query.answer()
    return ConversationHandler.END


async def admin_inline_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin inline flow'dan kelgan matnlarni qayta ishlash."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    flow = context.user_data.get("admin_flow")
    text = update.message.text.strip()
    # 🧹 FAZA 26: rad/xato xabarlari admin tilida.
    lang = get_lang(context)

    # "Bekor qilish"/"Asosiy menyu" har qanday admin oqimida va UCHALA TILDA
    # ishlashi kerak (admin klaviaturasi ham tilga qarab chiziladi).
    # 🧭 4-qadam standarti: [❌ Bekor qilish] — kontekst tozalanib BO'LIM
    # BOSHIGA (admin dashboard) qaytadi; [🏠 Asosiy menyu] — asosiy menyu.
    if is_menu_text(text, "cancel", "main_menu"):
        clear_fsm_data(context)
        if is_menu_text(text, "cancel"):
            stats = await db.run_db(db.get_admin_dashboard_stats)
            await update.message.reply_text(
                admin_t("cancelled_html", lang) + "\n\n" + _build_dashboard_text(stats, lang),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            from handlers.navigation import clear_section
            clear_section(context)
            await update.message.reply_text(
                admin_t("cancelled_html", lang),
                reply_markup=get_main_keyboard(
                    update.effective_user.id in ADMIN_IDS_SET,
                    lang=get_lang(context),
                ),
                parse_mode="HTML",
            )
        return ConversationHandler.END

    if not flow:
        # Holat bor, lekin oqim yo'q — foydalanuvchini band qoldirmaymiz.
        return ConversationHandler.END

    if flow == "grant_pro":
        if not has_permission(update.effective_user.id, PERM_MANAGE_USERS):
            await update.message.reply_text(
                admin_t("perm_grant_pro", lang),
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                admin_t("gp_bad_format", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        try:
            target_id = int(parts[0])
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                admin_t("gp_bad_numbers", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        if days <= 0:
            await update.message.reply_text(
                admin_t("days_positive", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        success = await db.run_db(db.set_user_plan, target_id, "pro", days,
                                  admin_id=update.effective_user.id)
        if success:
            await update.message.reply_text(
                admin_t("gp_granted", lang, user=target_id, days=days),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=admin_t("gp_user_notice", lang, days=days),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(
                admin_t("gp_error", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_GRANT_PRO

    if flow == "promo_create":
        if not has_permission(update.effective_user.id, PERM_MANAGE_PROMOS):
            await update.message.reply_text(
                admin_t("perm_promo_create", lang),
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                admin_t("promo_bad_format", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        code = parts[0].upper()
        try:
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                admin_t("promo_days_not_number", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        max_uses = None
        if len(parts) >= 3:
            try:
                max_uses = int(parts[2])
            except ValueError:
                await update.message.reply_text(
                    admin_t("promo_max_not_number", lang),
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                return ADMIN_PROMO_CREATE
        if days <= 0:
            await update.message.reply_text(
                admin_t("days_positive", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        success = await db.run_db(db.create_promo_code, code, "pro", days, max_uses,
                                  admin_id=update.effective_user.id)
        if success:
            max_str = (admin_t("lbl_times_n", lang, count=max_uses) if max_uses
                       else admin_t("lbl_unlimited", lang))
            await update.message.reply_text(
                admin_t("promo_created", lang, code=code, days=days, max_str=max_str),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                admin_t("promo_exists", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_PROMO_CREATE

    if flow == "broadcast":
        if not has_permission(update.effective_user.id, PERM_MANAGE_USERS):
            await update.message.reply_text(
                admin_t("perm_broadcast", lang),
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        user_ids = await db.run_db(db.get_all_user_ids)
        await update.message.reply_text(
            admin_t("bc_started", lang, count=len(user_ids)),
            parse_mode="HTML",
        )
        async def _broadcast_task():
            async with _broadcast_lock:
                await _run_broadcast(context.bot, user_ids, text, update.effective_user.id)
        asyncio.create_task(_broadcast_task())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if flow == "add_sponsor":
        # 1. Format: ID|TITLE|URL (legacy manual format)
        if "|" in text:
            parts = text.split("|")
            if len(parts) >= 3:
                ch_id, title, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
                success = await db.run_db(db.add_sponsor_channel, ch_id, title=title, invite_link=url)
                if success:
                    await update.message.reply_text(
                        admin_t("sp_added", lang, title=html_escape(title),
                                channel=ch_id, url=url),
                        reply_markup=get_admin_back_keyboard(),
                        parse_mode="HTML",
                    )
                    context.user_data.pop("admin_flow", None)
                    return ConversationHandler.END
                else:
                    await update.message.reply_text(
                        admin_t("sp_save_error", lang),
                        reply_markup=get_admin_back_keyboard(),
                    )
                    return ADMIN_SPONSOR_ADD

        # 2. Avtomatik tekshiruv: @username yoki ID
        raw_target = text.strip()
        if raw_target.startswith("https://t.me/"):
            raw_target = "@" + raw_target.replace("https://t.me/", "").strip("/").split("/")[0]

        chat_target = raw_target
        if raw_target.lstrip("-").isdigit():
            try:
                chat_target = int(raw_target)
            except ValueError:
                chat_target = raw_target

        try:
            chat = await context.bot.get_chat(chat_id=chat_target)
            bot_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)
            if bot_member.status not in ("administrator", "creator"):
                await update.message.reply_text(
                    admin_t("sp_not_admin_title", lang) + "\n\n"
                    + admin_t("sp_not_admin_channel", lang,
                              title=html_escape(chat.title or ""),
                              chat=chat.id) + "\n\n"
                    + admin_t("sp_not_admin_howto", lang),
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                return ADMIN_SPONSOR_ADD

            invite_link = chat.invite_link or ""
            if not invite_link and chat.username:
                invite_link = f"https://t.me/{chat.username}"
            if not invite_link:
                try:
                    invite_link = await context.bot.export_chat_invite_link(chat_id=chat.id)
                except Exception:
                    pass
            if not invite_link and chat.username:
                invite_link = f"https://t.me/{chat.username}"
            if not invite_link:
                invite_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"

            title = chat.title or admin_t("sp_generic_title", lang)
            username = chat.username or ""

            success = await db.run_db(
                db.add_sponsor_channel,
                channel_id=chat.id,
                title=title,
                username=username,
                invite_link=invite_link
            )
            if success:
                user_line = f"👤 @{username}\n" if username else ""
                await update.message.reply_text(
                    admin_t("sp_added_detailed", lang,
                            title=html_escape(title), channel=chat.id,
                            user=user_line, url=invite_link),
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                context.user_data.pop("admin_flow", None)
                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    admin_t("sp_db_save_error", lang),
                    reply_markup=get_admin_back_keyboard(),
                )
                return ADMIN_SPONSOR_ADD
        except Exception as e:
            logger.error("Sponsor kanal tekshirish xatosi: %s", e)
            await update.message.reply_text(
                admin_t("sp_not_found_title", lang) + "\n\n"
                + admin_t("sp_not_found_details", lang,
                          error=html_escape(str(e))) + "\n\n"
                + admin_t("sp_retry_hint", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_SPONSOR_ADD

    return ConversationHandler.END


# ============================================================
# LEGACY ADMIN HANDLERS — ROUTING ALIAS sifatida ishlaydi
# ============================================================
# Bu bo'limdagi handlerlar ilgari eski admin REPLY-KLAVIATURASI
# tugmalariga bog'langan edi. 3-bosqichdan keyin pastdagi admin
# klaviaturasi YO'Q, lekin har bir handler (a) yagona inline panelning
# ``adm_*`` callback'i orqali va (b) eski matn router ALIAS'i orqali
# (chat tarixidan qo'lda yozilganda) baribir ochiladi. Har bir ekran
# esa endi INLINE tugmalar bilan chiziladi.

async def ai_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    lang = get_lang(context)
    await update.message.reply_text(
        admin_t("ai_title", lang) + "\n\n"
        f"{_ai_settings_text(lang)}\n\n"
        + admin_t("ai_howto", lang) + "\n\n"
        + admin_t("ai_reset_hint", lang) + "\n"
        + admin_t("ai_cancel_hint", lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return AI_SETTINGS


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="adm:ai_denied_owner")
async def ai_settings_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    # "🔙 Asosiy menyu"/"⬅️ Back"/"❌ Cancel" — har qanday tilda bu bosqichdan
    # chiqadi (avval faqat UZ yorlig'i solishtirilgani uchun EN/RU da kiritilgan
    # matn AI parametri sifatida o'qib, xato berardi).
    if is_menu_text(text, "main_menu", "back", "cancel"):
        return ConversationHandler.END

    if text.lower() == "reset":
        for db_key, *_ in AI_SETTINGS_KEYS.values():
            await db.run_db(db.set_setting, db_key, "")
        await ai_agent.reload_runtime_params()
        lang = get_lang(context)
        await update.message.reply_text(
            admin_t("ai_reset_done", lang) + "\n\n"
            f"{_ai_settings_text(lang)}",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
        return AI_SETTINGS

    updates = {}
    errors = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key not in AI_SETTINGS_KEYS:
            errors.append(admin_t("ai_err_unknown_key", lang, key=html_escape(key)))
            continue
        import utils.ai_agent as _agent
        valid = _agent._set_runtime_param(key, value)
        if not valid:
            errors.append(admin_t("ai_err_bad_value", lang,
                                  key=html_escape(key), value=html_escape(value)))
            continue
        updates[AI_SETTINGS_KEYS[key][0]] = value.strip()
        updates["__ui_key__"] = key

    lang = get_lang(context)
    if errors:
        await update.message.reply_text(
            admin_t("ai_err_header", lang) + "\n" + "\n".join(errors),
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )

    applied = [(k, v) for k, v in updates.items() if k != "__ui_key__"]
    if applied:
        for db_key, value in applied:
            await db.run_db(db.set_setting, db_key, value)
        # Runtime parametrlarni DB value'lar asosida yangilaymiz.
        await ai_agent.reload_runtime_params()
        await update.message.reply_text(
            admin_t("ai_updated", lang) + "\n\n"
            f"{_ai_settings_text(lang)}",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
    elif not errors:
        await update.message.reply_text(
            admin_t("ai_err_nothing", lang),
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
    return AI_SETTINGS


async def cache_db_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    status = await db.run_db(db.get_db_pool_status)
    # 🧹 FAZA 26: matn endi yagona builder'dan va admin tilida.
    await update.message.reply_text(
        _build_dbcache_text(status, get_lang(context)),
        reply_markup=get_cache_actions_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="adm:cache_denied_owner")
async def cache_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer(admin_t("rbac_denied", get_lang(context)), show_alert=True)
        return
    lang = get_lang(context)
    await db.run_db(AuditService.log_action, query.from_user.id, "system_settings",
                    target_type="system_settings", target_id="cache_clear",
                    new_value={"action": "cache_clear"})
    await db.run_db(db.cache_clear)
    status = await db.run_db(db.get_db_pool_status)
    await query.answer(admin_t("cache_clear_toast", lang))
    try:
        await query.edit_message_text(
            # 🧹 FAZA 26: yagona builder (pool xabari bu yerda qisqa ko'rsatiladi)
            # + "tozalandi" footeri.
            _build_dbcache_text(status, lang, pool_message=False, cleared=True),
            reply_markup=get_cache_actions_keyboard(),
            parse_mode="HTML",
        )
    except TelegramError:
        pass


async def start_set_post_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    lang = get_lang(context)
    current_tag = await db.run_db(db.get_setting, "post_tag_text", "")
    await update.message.reply_text(
        admin_t("tag_title", lang) + "\n\n"
        + admin_t("tag_current", lang, value=html_escape(
            current_tag or admin_t("tag_empty_value", lang))) + "\n\n"
        + admin_t("tag_howto", lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return SET_POST_TAG


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="adm:tag_denied_owner")
async def post_tag_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    lang = get_lang(context)
    text = update.message.text.strip()
    # 6-bosqich: eski qiymat audit uchun (o'zgarishdan oldin o'qiladi).
    old_tag = await db.run_db(db.get_setting, "post_tag_text", "")
    if text.lower() == "clear":
        await db.run_db(db.set_setting, "post_tag_text", "")
        await db.run_db(AuditService.log_action, update.effective_user.id,
                        "system_settings", target_type="system_settings",
                        target_id="post_tag_text",
                        old_value={"post_tag_text": old_tag},
                        new_value={"post_tag_text": ""})
        await update.message.reply_text(
            admin_t("tag_cleared", lang),
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
    else:
        # HTML matn buzilmasligi uchun nishonni xavfsiz saqlaymiz.
        await db.run_db(db.set_setting, "post_tag_text", text)
        await db.run_db(AuditService.log_action, update.effective_user.id,
                        "system_settings", target_type="system_settings",
                        target_id="post_tag_text",
                        old_value={"post_tag_text": old_tag},
                        new_value={"post_tag_text": text})
        await update.message.reply_text(
            admin_t("tag_saved", lang, value=html_escape(text)),
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
    return ConversationHandler.END


@require_role(Role.OWNER, strict=True,
              message="adm:role_denied_grant")
async def admin_set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/setrole <user_id> <rol>` — admin rolini berish (faqat OWNER).

    Rollar: ``owner``, ``super_admin``, ``admin``, ``moderator``, ``finance``.
    ``user`` berilsa rol olib tashlanadi. Har bir amal ``admin_audit_logs``
    jadvaliga yoziladi (``set_role`` / ``remove_role``).
    """
    args = getattr(context, "args", None) or []
    # 🧹 FAZA 26: barcha javoblar buyruq yozgan admin tilida.
    lang = get_lang(context)
    if len(args) < 2:
        await update.message.reply_text(
            admin_t("role_usage_set", lang),
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(args[0])
    except (TypeError, ValueError):
        await update.message.reply_text(admin_t("role_bad_id", lang))
        return
    role = parse_role(args[1])
    if role is None:
        await update.message.reply_text(admin_t("role_unknown", lang))
        return
    admin_id = update.effective_user.id
    ok = await db.run_db(set_role, target_id, role, granted_by=admin_id)
    if not ok:
        await update.message.reply_text(admin_t("role_save_failed", lang))
        return
    if role is Role.USER:
        text = admin_t("role_removed", lang, user=target_id)
    else:
        perms = ", ".join(required_permissions(role)) or "—"
        text = admin_t("role_granted", lang, user=target_id,
                       role=html_escape(role.value.upper()),
                       perms=html_escape(perms))
    await update.message.reply_text(text, parse_mode="HTML")


@require_role(Role.OWNER, strict=True,
              message="adm:role_denied_revoke")
async def admin_del_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/delrole <user_id>` — admin rolini olib tashlash (faqat OWNER)."""
    args = getattr(context, "args", None) or []
    lang = get_lang(context)
    if not args:
        await update.message.reply_text(
            admin_t("role_usage_del", lang), parse_mode="HTML",
        )
        return
    try:
        target_id = int(args[0])
    except (TypeError, ValueError):
        await update.message.reply_text(admin_t("role_bad_id_short", lang))
        return
    admin_id = update.effective_user.id
    ok = await db.run_db(remove_role, target_id, granted_by=admin_id)
    if not ok:
        await update.message.reply_text(
            admin_t("role_not_found", lang, user=target_id)
        )
        return
    await update.message.reply_text(
        admin_t("role_removed", lang, user=target_id),
        parse_mode="HTML",
    )


@require_role(Role.SUPER_ADMIN,
              message="adm:audit_denied")
async def admin_audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/audit [N]` — oxirgi admin harakatlari (6-bosqich auditi).

    Har bir qatorda: vaqt | admin | amal | obyekt. Faqat OWNER/SUPER_ADMIN
    ko'ra oladi (`@require_role`), boshqalarga rad javobi yuboriladi.
    """
    args = getattr(context, "args", None) or []
    limit = 10
    if args:
        try:
            limit = max(1, min(int(args[0]), 50))
        except (TypeError, ValueError):
            limit = 10
    lang = get_lang(context)
    rows = await db.run_db(db.get_admin_audit_logs, limit=limit)
    if not rows:
        await update.message.reply_text(
            admin_t("audit_cmd_empty", lang),
            parse_mode="HTML",
        )
        return
    lines = [admin_t("audit_cmd_header", lang, count=len(rows)),
             "━━━━━━━━━━━━━━━━━"]
    for row in rows:
        created = row.get("created_at")
        try:
            when = created.strftime("%d.%m.%Y %H:%M")
        except Exception:
            when = str(created or "")[:16]
        target = ""
        if row.get("target_type"):
            target = f" → <code>{html_escape(row['target_type'])}"
            if row.get("target_id"):
                target += f"#{html_escape(row['target_id'])}"
            target += "</code>"
        lines.append(
            f"🕒 <b>{html_escape(when)}</b> | 👤 <code>{html_escape(row.get('admin_id'))}</code>\n"
            f"   {html_escape(row.get('action'))}{target}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📊 Statistika» reply-tugmasi va ``/stats`` — YAGONA statistika ekrani.

    4-qadam: ``adm_stats`` callback'i, ``/admin_stats`` buyrug'i va shu
    handler — hammasi ``_build_full_stats_text`` dan AYNAN bir xil matn
    oladi (dublikat ekranlar birlashtirildi; eski yo'llar alias qoldi).
    """
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    stats = await db.run_db(db.get_system_stats)
    await update.message.reply_text(
        _build_full_stats_text(stats, get_lang(context)),
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )


async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📋 Barcha postlar» reply-tugmasi — ``adm_posts`` bilan bir xil ekran."""
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    recent_posts = await db.run_db(db.get_recent_posts, 15)
    await update.message.reply_text(
        _build_admin_posts_text(recent_posts, get_lang(context)),
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )


async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📋 Barcha kanal/guruhlar» reply-tugmasi — ``adm_channels`` bilan bir xil ekran."""
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    channels = await db.run_db(db.get_all_channels, ADMIN_CHANNELS_LIMIT)
    lang = get_lang(context)
    if not channels:
        await update.message.reply_text(
            admin_t("channels_none_legacy", lang),
            reply_markup=get_admin_dashboard_keyboard())
        return

    text = format_admin_channels_list(channels, lang)
    await update.message.reply_text(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")


async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    lang = get_lang(context)
    sponsors = await db.run_db(db.get_sponsor_channels)
    if sponsors is None:
        await update.message.reply_text(
            admin_t("sp_db_error", lang),
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return
    count = len(sponsors)
    text = (admin_t("sp_list_header", lang, count=count)
            + "\n━━━━━━━━━━━━━━━━━\n")
    if sponsors:
        for idx, s in enumerate(sponsors, 1):
            s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
            u_info = f" (@{username})" if username else ""
            text += admin_t("sp_list_entry", lang, idx=idx,
                            title=html_escape(ch_title), user=u_info,
                            channel=ch_id, url=ch_url) + "\n\n"
    else:
        text += admin_t("sp_list_empty", lang) + "\n\n"

    text += "━━━━━━━━━━━━━━━━━\n" + admin_t("sp_list_footer", lang)
    await update.message.reply_text(text, reply_markup=get_admin_sponsors_keyboard(sponsors), parse_mode="HTML")


async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    lang = get_lang(context)
    await update.message.reply_text(
        admin_t("sp_add_title", lang) + "\n\n" + admin_t("sp_add_howto", lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML"
    )
    return ADD_SPONSOR_CHANNEL


async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    lang = get_lang(context)
    text = update.message.text.strip()

    if "|" in text:
        parts = text.split("|")
        if len(parts) >= 3:
            ch_id, title, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
            success = await db.run_db(db.add_sponsor_channel, ch_id, title=title, invite_link=url)
            if success:
                await update.message.reply_text(
                    admin_t("sp_added_short", lang, title=html_escape(title)),
                    reply_markup=get_admin_dashboard_keyboard(),
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(admin_t("sp_save_error", lang),
                                                reply_markup=get_admin_dashboard_keyboard())
            return ConversationHandler.END

    raw_target = text
    if raw_target.startswith("https://t.me/"):
        raw_target = "@" + raw_target.replace("https://t.me/", "").strip("/").split("/")[0]

    chat_target = raw_target
    if raw_target.lstrip("-").isdigit():
        try:
            chat_target = int(raw_target)
        except ValueError:
            chat_target = raw_target

    try:
        chat = await context.bot.get_chat(chat_id=chat_target)
        bot_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                admin_t("sp_not_admin_title", lang) + "\n\n"
                + admin_t("sp_not_admin_channel", lang,
                          title=html_escape(chat.title or ""), chat=chat.id) + "\n\n"
                + admin_t("sp_not_admin_howto_short", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADD_SPONSOR_CHANNEL

        invite_link = chat.invite_link or ""
        if not invite_link and chat.username:
            invite_link = f"https://t.me/{chat.username}"
        if not invite_link:
            try:
                invite_link = await context.bot.export_chat_invite_link(chat_id=chat.id)
            except Exception:
                pass
        if not invite_link and chat.username:
            invite_link = f"https://t.me/{chat.username}"
        if not invite_link:
            invite_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"

        title = chat.title or admin_t("sp_generic_title", lang)
        username = chat.username or ""

        success = await db.run_db(
            db.add_sponsor_channel,
            channel_id=chat.id,
            title=title,
            username=username,
            invite_link=invite_link
        )
        if success:
            await update.message.reply_text(
                admin_t("sp_added_full", lang, title=html_escape(title)),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(admin_t("sp_save_error", lang),
                                            reply_markup=get_admin_dashboard_keyboard())
    except Exception as e:
        logger.error("Sponsor kanal tekshirish xatosi: %s", e)
        await update.message.reply_text(
            admin_t("sp_not_found_legacy", lang, error=html_escape(str(e))),
            reply_markup=get_admin_back_keyboard(),
        )
        return ADD_SPONSOR_CHANNEL

    return ConversationHandler.END


async def del_sponsor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    if not is_admin(query.from_user.id):
        try:
            await query.message.reply_text(admin_t("rbac_denied_msg", get_lang(context)))
        except Exception:
            pass
        return
    # 11-bosqich (P0): payload ID qat'iy tekshiriladi (tampering himoyasi).
    try:
        (s_id,) = admin_callback_guard(update, CB_SPONSOR_DELETE, 1)
    except CallbackTampering:
        return
    lang = get_lang(context)
    removed = await db.run_db(db.remove_sponsor_channel, s_id)
    if not removed:
        try:
            await query.message.reply_text(admin_t("sp_delete_failed", lang))
        except Exception:
            pass
    # Yangilangan ro'yxatni qayta chizamiz (yagona builder — FAZA 26).
    sponsors = await db.run_db(db.get_sponsor_channels) or []
    text = _build_sponsor_manage_text(sponsors, lang)

    try:
        await query.edit_message_text(
            text,
            reply_markup=get_admin_sponsors_keyboard(sponsors),
            parse_mode="HTML",
        )
    except TelegramError:
        pass


# ============================================================
# AVTOMATIK REKLAMA ROTATSIYA (ad_pool) — TO'LIQ BOSHQARUV
# ============================================================
# Har bir "joy" (kanal posti / bot javobi) uchun mustaqil pul. Admin panelda
# bir nechta reklama saqlanadi, bot ularni navbatma-navbat (round-robin)
# qo'shadi. Har bir reklamani alohida tahrirlash mumkin:
#   • matn (HTML formatlash: <b>, <i>, <a href="...">),
#   • inline URL tugma (tugma matni + havolasi),
#   • faollik holati (Toggle Active/Inactive),
#   • o'chirish.
# Kanal postlarida reklama har nechanchi postda chiqishi ham shu yerda
# sozlanadi (har 3-, 4- yoki 5-post) — sanagich HAR BIR KANAL uchun alohida.
# 🧹 FAZA 26: scope sarlavhalari endi i18n kalitlari (``ad_scope_*``) —
# matn ``admin_t()`` orqali tilga mos chiziladi.
AD_SCOPE_META = {
    "channel": {
        "title": "ad_scope_channel",
        "state": SET_CHANNEL_AD,
    },
    "reply": {
        "title": "ad_scope_reply",
        "state": SET_BOT_REPLY_AD,
    },
}


def _ad_scope_title(scope: str, lang: str = "uz") -> str:
    """Scope sarlavhasi — i18n orqali (uz/ru/en)."""
    meta = AD_SCOPE_META.get(scope) or {}
    return admin_t(meta.get("title", "ad_scope_channel"), lang)


def _ad_html_hint(lang: str = "uz") -> str:
    """HTML formatlash yo'riqnomasi — i18n (uz/ru/en)."""
    return admin_t("ad_html_hint", lang)


def _ad_scope_state(scope: str):
    """Scope uchun FSM holati (matn kutilayotgan holat)."""
    return AD_SCOPE_META.get(scope, {}).get("state", SET_CHANNEL_AD)


def _format_ad_pool(ads, lang: str = "uz") -> str:
    """Rotatsiya puli ro'yxatini HTML-xavfsiz matn ko'rinishida chiqaradi."""
    if not ads:
        return admin_t("ad_pool_empty", lang)
    lines = []
    for ad in ads:
        if isinstance(ad, dict):
            ad_id = ad.get("id")
            text = ad.get("text") or ""
            badge = "🟢" if ad.get("is_active", True) else "🔴"
            btn = ""
            if (ad.get("button_text") or "").strip() and (ad.get("button_url") or "").strip():
                btn = f"\n      🔗 <b>{html_escape(_short_text(ad['button_text'], 32))}</b> → {html_escape(_short_text(ad['button_url'], 48))}"
        else:
            ad_id, text = ad[0], ad[1]
            badge, btn = "🟢", ""
        lines.append(f"   {badge} <b>#{ad_id}</b>. {html_escape(_short_text(text, 80))}{btn}")
    return "\n".join(lines)


def _format_ad_card(ad: dict, scope: str, lang: str = "uz") -> str:
    """Bitta reklama kartochkasi (tahrirlash ekrani uchun)."""
    ad = ad or {}
    title = _ad_scope_title(scope, lang)
    status = (admin_t("ad_status_active", lang) if ad.get("is_active", True)
              else admin_t("ad_status_inactive", lang))
    btn_text = (ad.get("button_text") or "").strip()
    btn_url = (ad.get("button_url") or "").strip()
    if btn_text and btn_url:
        button_line = f"<b>{html_escape(btn_text)}</b> → {html_escape(btn_url)}"
    else:
        button_line = admin_t("ad_button_none", lang)
    return (
        admin_t("ad_card_title", lang, title=title) + "\n"
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("ad_card_id", lang, id=ad.get('id', 0)) + "\n"
        + admin_t("ad_card_status", lang, status=status) + "\n"
        + admin_t("ad_card_button", lang, button=button_line) + "\n"
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("ad_card_text", lang, text=html_escape(ad.get('text') or '')) + "\n\n"
        + admin_t("ad_card_preview", lang) + "\n"
        + f"{safe_html(ad.get('text') or '')}\n\n"
        + admin_t("ad_card_edit_hint", lang)
    )


async def _ad_pool_menu_text(scope: str, lang: str = "uz") -> str:
    """Reklama puli menyusi uchun matn (sarlavha + ro'yxat + yo'riqnoma)."""
    ads = await db.run_db(db.get_ads_full, scope, True)
    title = _ad_scope_title(scope, lang)
    active = sum(1 for a in ads if a.get("is_active", True))
    text = (
        admin_t("ad_pool_title", lang, title=title) + "\n"
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("ad_pool_counts", lang, total=len(ads), active=active) + "\n"
    )
    if scope == "channel":
        interval = await db.run_db(db.get_channel_ad_interval)
        text += admin_t("ad_pool_interval_channel", lang, interval=interval) + "\n"
    else:
        settings = await db.run_db(db.get_ad_settings)
        interval = settings.get("auto_ad_interval", 4)
        text += admin_t("ad_pool_interval_reply", lang, interval=interval) + "\n"
    text += (
        "━━━━━━━━━━━━━━━━━\n"
        + admin_t("ad_pool_list_title", lang) + "\n"
        + _format_ad_pool(ads, lang) + "\n\n"
        + admin_t("ad_pool_footer", lang)
    )
    return text


async def _ad_pool_menu_markup(scope: str):
    """Reklama puli menyusi klaviaturasi (ro'yxat + interval bilan)."""
    ads = await db.run_db(db.get_ads_full, scope, True)
    if scope == "channel":
        interval = await db.run_db(db.get_channel_ad_interval)
    else:
        settings = await db.run_db(db.get_ad_settings)
        interval = settings.get("auto_ad_interval", 4)
    return get_ad_pool_menu_keyboard(scope, ads=ads, interval=interval)


async def _show_ad_pool_menu(query, scope: str, lang: str = "uz"):
    """Reklama puli menyusini (matn + klaviatura) qayta chizadi."""
    text = await _ad_pool_menu_text(scope, lang)
    markup = await _ad_pool_menu_markup(scope)
    await _edit_or_send(query, text, markup)


async def _edit_or_send(query, text: str, reply_markup=None):
    """Xabarni tahrirlaydi; imkoni bo'lmasa yangisini yuboradi."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramError:
        try:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except TelegramError:
            logger.debug("Reklama menyusini ko'rsatib bo'lmadi")


async def _show_ad_card(query, scope: str, ad_id: int, lang: str = "uz") -> bool:
    """Bitta reklama kartochkasini ko'rsatadi. Topilmasa False."""
    ad = await db.run_db(db.get_ad, ad_id)
    if not ad:
        await _show_ad_pool_menu(query, scope, lang)
        return False
    await _edit_or_send(query, _format_ad_card(ad, scope, lang),
                        get_ad_edit_keyboard(ad, scope))
    return True


async def admin_ad_hub_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply-klaviaturadagi "🎯 Reklama markazi" tugmasi — yagona hub.

    Avval foydalanuvchi ikki alohida tugma ("Kanal posti reklamasi" / "Bot
    xabari reklamasi") orasidan tanlar, har biri faqat o'z puliga olib
    kirardi. Endi bitta tugada ikkala pul, oraliklar va javoblar reklamasi
    holati — bitta ekranda ko'rinadi.

    Holat ``SET_CHANNEL_AD`` qaytariladi: shu paytdan yozilgan matn 📢 kanal
    posti puliga qo'shiladi (holat ichida ``adp:`` tugmalari va ikkala scope
    matn-qabul qiluvchilari ham faol).
    """
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    context.user_data.pop("ad_edit", None)
    text, markup = await _ad_hub_render(get_lang(context))
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return SET_CHANNEL_AD


async def _ad_new_text_prompt(lang: str) -> str:
    """«Yangi reklama matnini yozing» yo'riqnomasi (i18n, FAZA 26)."""
    return (admin_t("ad_new_prompt", lang) + "\n"
            + _ad_html_hint(lang) + "\n\n"
            + admin_t("ad_cancel_hint", lang))


async def start_set_channel_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop("ad_edit", None)
    lang = get_lang(context)
    text = await _ad_pool_menu_text("channel", lang)
    markup = await _ad_pool_menu_markup("channel")
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    await update.message.reply_text(
        _ad_new_text_prompt(lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return SET_CHANNEL_AD


async def start_set_bot_reply_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop("ad_edit", None)
    lang = get_lang(context)
    text = await _ad_pool_menu_text("reply", lang)
    markup = await _ad_pool_menu_markup("reply")
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    await update.message.reply_text(
        _ad_new_text_prompt(lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return SET_BOT_REPLY_AD


async def _ad_text_received(update, context, scope: str):
    """Reklama matni kiritildi: yangi qo'shish YOKI mavjudini tahrirlash.

    Tahrirlash rejimi ``context.user_data["ad_edit"]`` orqali aniqlanadi
    (``{"id": ..., "field": "text"|"button", "scope": ...}``).
    """
    state = _ad_scope_state(scope)
    text = (update.message.text or "").strip()
    pending = context.user_data.get("ad_edit") or {}
    # 🧹 FAZA 26: barcha javoblar admin tilida (uz/ru/en).
    lang = get_lang(context)

    # --- 1. Mavjud reklamaning inline URL tugmasini tahrirlash ---
    if pending.get("field") == "button" and pending.get("scope") == scope:
        # 🌐 FAZA 26: "tozalash" buyrug'i uchala tilda ham qabul qilinadi
        # (bu Foydalanuvchi KIRITISH tokenlari — ko'rsatiladigan matn emas).
        if text.lower() in ("clear", "-", "yo'q", "yoq", "нет", "no", "none"):
            await db.run_db(db.update_ad, pending["id"], None, "", "")
            context.user_data.pop("ad_edit", None)
            await update.message.reply_text(
                admin_t("ad_btn_removed", lang),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
            await _send_ad_card(update, context, scope, pending["id"], lang)
            return state

        btn_text, btn_url = parse_button_input(text)
        if not btn_text or not btn_url:
            await update.message.reply_text(
                admin_t("ad_btn_bad_format", lang),
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return state
        ok, err = validate_button_text(btn_text)
        if not ok:
            await update.message.reply_text(f"❌ {err}", reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
            return state
        ok, err = validate_button_url(btn_url)
        if not ok:
            await update.message.reply_text(f"❌ {err}", reply_markup=get_admin_back_keyboard(), parse_mode="HTML")
            return state

        saved = await db.run_db(db.update_ad, pending["id"], None, btn_text, btn_url)
        context.user_data.pop("ad_edit", None)
        if saved:
            await update.message.reply_text(
                admin_t("ad_btn_saved", lang, text=html_escape(btn_text),
                        url=html_escape(btn_url)),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(admin_t("sp_save_error", lang),
                                            reply_markup=get_admin_dashboard_keyboard())
        await _send_ad_card(update, context, scope, pending["id"], lang)
        return state

    # --- 2. Mavjud reklama matnini tahrirlash ---
    if pending.get("field") == "text" and pending.get("scope") == scope:
        ok, err = validate_ad_html(text, max_len=db.AD_TEXT_MAX_LEN)
        if not ok:
            await update.message.reply_text(
                f"❌ {err}\n\n{_ad_html_hint(lang)}",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return state
        saved = await db.run_db(db.update_ad, pending["id"], text)
        context.user_data.pop("ad_edit", None)
        if saved:
            await update.message.reply_text(
                admin_t("ad_text_updated", lang),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(admin_t("sp_save_error", lang),
                                            reply_markup=get_admin_dashboard_keyboard())
        await _send_ad_card(update, context, scope, pending["id"], lang)
        return state

    # --- 3. Kanal reklama oralig'ini qo'lda kiritish ---
    if pending.get("field") == "interval" and pending.get("scope") == scope:
        try:
            value = int(text)
        except ValueError:
            await update.message.reply_text(
                admin_t("ad_iv_bad_number", lang),
                reply_markup=get_admin_back_keyboard(),
            )
            return state
        if value < db.AD_INTERVAL_MIN or value > db.AD_INTERVAL_MAX:
            await update.message.reply_text(
                admin_t("ad_iv_out_of_range", lang,
                        min=db.AD_INTERVAL_MIN, max=db.AD_INTERVAL_MAX),
                reply_markup=get_admin_back_keyboard(),
            )
            return state
        if scope == "channel":
            await db.run_db(db.set_channel_ad_interval, value)
            unit = admin_t("ad_unit_post", lang)
        else:
            await db.run_db(db.set_ad_interval, value)
            unit = admin_t("ad_unit_reply", lang)
        context.user_data.pop("ad_edit", None)
        await update.message.reply_text(
            admin_t("ad_iv_updated", lang, value=value, unit=unit) + "\n"
            + (admin_t("ad_iv_counter_channel", lang) if scope == "channel"
               else admin_t("ad_iv_counter_user", lang)),
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
        await _send_ad_menu(update, context, scope, lang)
        return state

    # --- 4. Yangi reklama qo'shish ---
    if text.lower() == "clear":
        removed = await db.run_db(db.clear_ads, scope)
        await update.message.reply_text(
            admin_t("ad_cleared_msg", lang, count=removed),
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return ConversationHandler.END

    ok, err = validate_ad_html(text, max_len=db.AD_TEXT_MAX_LEN)
    if not ok:
        await update.message.reply_text(
            f"❌ {err}\n\n{_ad_html_hint(lang)}",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
        return state

    ad_id = await db.run_db(db.add_ad, scope, text)
    if ad_id > 0:
        await update.message.reply_text(
            admin_t("ad_added", lang),
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(admin_t("sp_save_error", lang),
                                        reply_markup=get_admin_dashboard_keyboard())
    await _send_ad_menu(update, context, scope, lang)
    return state


async def _send_ad_menu(update, context, scope: str, lang: str = "uz"):
    """Yangilangan reklama menyusini yangi xabar sifatida yuboradi."""
    menu = await _ad_pool_menu_text(scope, lang)
    markup = await _ad_pool_menu_markup(scope)
    await update.message.reply_text(menu, reply_markup=markup, parse_mode="HTML")


async def _send_ad_card(update, context, scope: str, ad_id: int, lang: str = "uz"):
    """Tahrirlangan reklama kartochkasini yangi xabar sifatida yuboradi."""
    ad = await db.run_db(db.get_ad, ad_id)
    if not ad:
        await _send_ad_menu(update, context, scope, lang)
        return
    await update.message.reply_text(
        _format_ad_card(ad, scope, lang),
        reply_markup=get_ad_edit_keyboard(ad, scope),
        parse_mode="HTML",
    )


async def channel_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    return await _ad_text_received(update, context, "channel")


async def bot_reply_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    return await _ad_text_received(update, context, "reply")


async def ad_pool_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reklama rotatsiya puli inline tugmalari (``adp:...``).

    Qo'llab-quvvatlanadigan amallar:
      ``add`` yangi, ``e`` kartochka, ``et`` matn, ``eb`` tugma, ``bx`` tugmani
      o'chirish, ``tg`` faollik toggle, ``rm`` o'chirish, ``clear`` tozalash,
      ``iv`` reklama oralig'i, ``info`` yordam, ``back`` menyu.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    # 11-bosqich (P0): server-side RBAC (payload'ga ishonilmaydi).
    if not verify_admin_callback(update):
        return ConversationHandler.END

    parts = (query.data or "").split(":")
    if len(parts) < 3 or len(parts) > 4 or parts[0] != "adp":
        return ConversationHandler.END
    scope = parts[1]
    action = parts[2]
    arg = parts[3] if len(parts) >= 4 else None
    if arg is not None and parse_callback_id(arg) is None:
        # Reklama ID'si qat'iy musbat int bo'lishi shart.
        return ConversationHandler.END
    meta = AD_SCOPE_META.get(scope)
    if not meta:
        return ConversationHandler.END
    # 🧹 FAZA 26: sarlavha va barcha matnlar admin tilida (uz/ru/en).
    lang = get_lang(context)
    title = _ad_scope_title(scope, lang)
    state = meta["state"]

    def _ad_id():
        try:
            return int(arg)
        except (TypeError, ValueError):
            return None

    if action == "add":
        context.user_data.pop("ad_edit", None)
        text = (
            admin_t("ad_add_new_title", lang, title=title) + "\n\n"
            + _ad_html_hint(lang) + "\n\n"
            + admin_t("ad_add_clear_hint", lang)
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "e":
        ad_id = _ad_id()
        context.user_data.pop("ad_edit", None)
        if ad_id is None:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        await _show_ad_card(query, scope, ad_id, lang)
        return state

    if action == "et":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        ad = await db.run_db(db.get_ad, ad_id)
        if not ad:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        context.user_data["ad_edit"] = {"id": ad_id, "field": "text", "scope": scope}
        text = (
            admin_t("ad_et_title", lang, id=ad_id) + "\n\n"
            + admin_t("ad_et_current", lang,
                      text=html_escape(ad.get('text') or '')) + "\n\n"
            + _ad_html_hint(lang)
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "eb":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        ad = await db.run_db(db.get_ad, ad_id)
        if not ad:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        context.user_data["ad_edit"] = {"id": ad_id, "field": "button", "scope": scope}
        current = ""
        if (ad.get("button_text") or "").strip():
            current = admin_t("ad_eb_current", lang,
                              text=html_escape(ad['button_text']),
                              url=html_escape(ad.get('button_url') or '')) + "\n\n"
        text = (
            admin_t("ad_eb_title", lang, id=ad_id) + "\n\n"
            + current
            + admin_t("ad_eb_howto", lang)
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "bx":
        ad_id = _ad_id()
        if ad_id is not None:
            await db.run_db(db.update_ad, ad_id, None, "", "")
            context.user_data.pop("ad_edit", None)
            await _show_ad_card(query, scope, ad_id, lang)
        return state

    if action == "tg":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        new_status = await db.run_db(db.toggle_ad_active, ad_id)
        if new_status is None:
            await _show_ad_pool_menu(query, scope, lang)
            return state
        try:
            await query.answer(admin_t("ad_tg_on_toast", lang) if new_status
                               else admin_t("ad_tg_off_toast", lang))
        except Exception:
            pass
        await _show_ad_card(query, scope, ad_id, lang)
        return state

    if action == "rm":
        ad_id = _ad_id()
        if ad_id is not None:
            await db.run_db(db.delete_ad, ad_id)
            context.user_data.pop("ad_edit", None)
        await _show_ad_pool_menu(query, scope, lang)
        return state

    if action == "del":
        ads = await db.run_db(db.get_ads_full, scope, True)
        text = (admin_t("ad_del_pick", lang, title=title) + "\n\n"
                + _format_ad_pool(ads, lang))
        await _edit_or_send(query, text, get_ad_pool_delete_keyboard(ads, scope))
        return state

    if action == "clear":
        removed = await db.run_db(db.clear_ads, scope)
        context.user_data.pop("ad_edit", None)
        try:
            await query.answer(admin_t("ad_clear_toast", lang, count=removed))
        except Exception:
            pass
        await _show_ad_pool_menu(query, scope, lang)
        return state

    if action == "iv":
        # Reklama oralig'i — HAR BIR BO'LIM uchun o'z sozlamasi:
        #   channel → har nechanchi POSTDA,  reply → har nechta JAVOBDA.
        is_channel = (scope == "channel")
        unit = (admin_t("ad_unit_post", lang) if is_channel
                else admin_t("ad_unit_reply", lang))
        if arg is not None:
            value = db.clamp_ad_interval(arg, 3 if is_channel else 4)
            if is_channel:
                await db.run_db(db.set_channel_ad_interval, value)
            else:
                await db.run_db(db.set_ad_interval, value)
            context.user_data.pop("ad_edit", None)
            try:
                await query.answer(admin_t("ad_iv_toast", lang, value=value, unit=unit))
            except Exception:
                pass
            await _show_ad_pool_menu(query, scope, lang)
            return state

        if is_channel:
            current = await db.run_db(db.get_channel_ad_interval)
        else:
            settings = await db.run_db(db.get_ad_settings)
            current = settings.get("auto_ad_interval", 4)
        context.user_data["ad_edit"] = {"id": 0, "field": "interval", "scope": scope}
        if is_channel:
            explain = admin_t("ad_iv_explain_channel", lang)
        else:
            explain = admin_t("ad_iv_explain_reply", lang)
        text = (
            admin_t("ad_iv_title", lang) + "\n"
            "━━━━━━━━━━━━━━━━━\n"
            + admin_t("ad_iv_current", lang, value=current, unit=unit) + "\n\n"
            + f"{explain}\n\n"
            + admin_t("ad_iv_hint", lang, min=db.AD_INTERVAL_MIN, max=db.AD_INTERVAL_MAX)
        )
        await _edit_or_send(query, text, get_ad_interval_keyboard(scope, current))
        return state

    if action == "info":
        interval_line = ""
        if scope == "channel":
            interval = await db.run_db(db.get_channel_ad_interval)
            interval_line = admin_t("ad_info_interval_channel", lang, interval=interval)
        text = (
            admin_t("ad_info_title", lang, title=title) + "\n\n"
            + admin_t("ad_info_body", lang, interval_line=interval_line)
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "back":
        context.user_data.pop("ad_edit", None)
        await _show_ad_pool_menu(query, scope, lang)
        return state

    return state


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    lang = get_lang(context)
    await update.message.reply_text(
        admin_t("bc_title", lang) + "\n\n" + admin_t("bc_prompt", lang),
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML"
    )
    return BROADCAST_MESSAGE


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    lang = get_lang(context)
    # Avvalgi broadcast hali davom etayotgan bo'lsa — takroriy ishga tushirmaymiz
    if _broadcast_lock.locked():
        await update.message.reply_text(
            admin_t("bc_busy", lang),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    if not has_permission(update.effective_user.id, PERM_MANAGE_USERS):
        await update.message.reply_text(admin_t("perm_broadcast", lang))
        return ConversationHandler.END

    text = update.message.text
    # DB chaqiruvini event loop'ni bloklamasdan thread'da bajarish
    user_ids = await db.run_db(db.get_all_user_ids)

    await update.message.reply_text(
        admin_t("bc_started", lang, count=len(user_ids)),
        parse_mode="HTML"
    )

    # Broadcast fon vazifasi sifatida ishlaydi — admin boshqa buyruqlarni
    # bemalol ishlatishi mumkin, Telegram esa rate-limitga tushmaydi.
    async def _broadcast_task():
        async with _broadcast_lock:
            await _run_broadcast(context.bot, user_ids, text, update.effective_user.id, lang)

    asyncio.create_task(_broadcast_task())
    return ConversationHandler.END


async def _run_broadcast(bot, user_ids, text, admin_id, lang: str = "uz"):
    """Broadcastni batch'lar bilan, rate-limit va retry bilan yuborish."""
    sent = 0
    failed = 0
    parse_mode = "HTML"

    for i, uid in enumerate(user_ids):
        delivered = False
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode=parse_mode)
                sent += 1
                delivered = True
                break
            except RetryAfter as e:
                # Telegram aytgan vaqtgacha kutamiz va qayta urinamiz
                wait = min(max(int(getattr(e, "retry_after", 2) or 2), 1), 30)
                await asyncio.sleep(wait)
            except BadRequest:
                # HTML xato bo'lsa — oddiy matn sifatida qayta yuboramiz
                try:
                    await bot.send_message(chat_id=uid, text=text)
                    sent += 1
                except TelegramError:
                    failed += 1
                delivered = True
                break
            except (TimedOut, NetworkError):
                if attempt == 2:
                    failed += 1
                    delivered = True  # 3 ta urinish ham tugadi
                else:
                    await asyncio.sleep(1 + attempt)
            except TelegramError:
                # Bot bloklangan / xabar qabul qilinmagan
                failed += 1
                delivered = True
                break
        # Barcha 3 urinish RetryAfter bilan tugasa ham foydalanuvchi
        # "yuborilmagan" hisobiga kiritilishi kerak (jim o'tib ketmasligi uchun).
        if not delivered:
            failed += 1

        # Har batch'da qisqa pauza — Telegram'ning 30 msg/s limitidan oshmaymiz
        if i and i % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(BROADCAST_BATCH_DELAY)

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=admin_t("bc_done", lang, sent=sent, total=len(user_ids), failed=failed),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Broadcast yakuni haqida admin xabari yuborilmadi")
    logger.info("Broadcast yakunlandi: sent=%d, failed=%d, total=%d", sent, failed, len(user_ids))
    # 6-bosqich: broadcast ham admin harakati sifatida auditga yoziladi.
    try:
        await db.run_db(AuditService.log_action, admin_id, "broadcast",
                        target_type="users", target_id="all",
                        new_value={"sent": sent, "failed": failed,
                                   "total": len(user_ids)})
    except Exception as e:  # pragma: no cover - audit botni to'xtatmaydi
        logger.warning("Broadcast auditi yozilmadi: %s", e)
