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
    BTN_MAIN_MENU, BTN_CANCEL,
    is_menu_text,
)
from keyboards.inline import (
    get_sponsors_delete_keyboard, get_cache_actions_keyboard,
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


def format_admin_channels_list(channels: list) -> str:
    """Eng so'nggi kanallar uchun HTML-xavfsiz, 4096 dan oshmaydigan matn."""
    header = (
        f"📋 <b>Eng so'nggi {len(channels)} ta ulangan kanal "
        f"(ko'pi bilan {ADMIN_CHANNELS_LIMIT}):</b>\n\n"
    )
    entries = []
    for channel_id, title, user_id, username in channels:
        title = _short_text(title or "Kanal", 160)
        channel_id = _short_text(channel_id, 64)
        owner = f"@{_short_text(username, 64)}" if username else f"ID:{user_id}"
        entries.append(
            f"📢 <b>{html_escape(title)}</b> (<code>{html_escape(channel_id)}</code>)\n"
            f"   👤 Egasi: {html_escape(owner)}\n\n"
        )

    visible_entries = entries[:]
    while True:
        omitted = len(entries) - len(visible_entries)
        footer = (
            f"… {omitted} ta kanal Telegramning 4096 belgilik limiti sabab ko'rsatilmagan."
            if omitted else ""
        )
        text = header + "".join(visible_entries) + footer
        if _telegram_text_length(text) <= TELEGRAM_TEXT_LIMIT or not visible_entries:
            return text
        # Eng yangi kanallar yuqorida qoladi; faqat sig'magan eski qatorni olamiz.
        visible_entries.pop()


# Admin panelda ko'rsatiladigan AI parametrlari (kalit -> (DB key, UI belgi, tavsif))
AI_SETTINGS_KEYS = {
    "temperature": ("ai_temperature", "🌡 temperature", "0.0–2.0 (0.2 = aniq)"),
    "max_tokens": ("ai_max_tokens", "📄 max_tokens", "128–8192 (1024) yoki off"),
    "top_p": ("ai_top_p", "🎯 top_p", "0.0–1.0 (1.0) yoki off"),
    "max_prompt_chars": ("ai_max_prompt_chars", "🧩 prompt limiti", "500–12000 belgi (3000)"),
    "context_chars": ("ai_context_chars", "💬 kontekst hajmi", "500–20000 belgi (4000)"),
    "context_messages": ("ai_context_messages", "🧠 kontekst xabarlari", "0–20 dona (6)"),
    "extra_context": ("ai_extra_context", "📌 qo'shimcha ko'rsatma", "matn (bo'sh qoldirsangiz o'chadi)"),
}


def _ai_settings_text() -> str:
    params = ai_agent.get_runtime_params()
    lines = []
    for key, (db_key, label, hint) in AI_SETTINGS_KEYS.items():
        value = params.get(key)
        value_text = "-" if value in (None, "") else str(value)
        lines.append(f"   • <b>{label}</b> = <code>{html_escape(value_text)}</code>  <i>({hint})</i>")
    return "\n".join(lines)


def _build_dashboard_text(stats: dict) -> str:
    """Admin dashboard matnini yaratadi."""
    return (
        "👑 <b>Admin Boshqaruv Paneli</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"⭐️ PRO obunachilar: <b>{stats['pro_subscribers']} ta</b>\n"
        f"📢 Ulangan faol kanallar: <b>{stats['channels']} ta</b>\n"
        f"📝 Bugun chiqarilgan postlar: <b>{stats['posts_today']} ta</b>\n"
        f"⏳ Navbatdagi postlar: <b>{stats['pending_posts']} ta</b>\n"
        f"⭐️ Telegram Stars tushumi: <b>{stats['stars_revenue']} XTR</b>\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang 👇"
    )


def _build_full_stats_text(stats: dict) -> str:
    """📊 YAGONA «To'liq statistika» ekrani (4-qadam: dublikatlar birlashdi).

    Bir vaqtda UCHTA dublikat handler bu matnni chizardi (``adm_stats``
    callback'i, ``/admin_stats`` buyrug'i va «📊 Statistika» reply-tugmasi /
    ``/stats``). Endi hammasi SHU bitta builder'ga ulangan — ekran ham,
    raqamlar ham har doim bir xil (eski yo'llar alias sifatida ishlaydi).
    """
    return (
        "📊 <b>To'liq Statistika:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"📢 Ulangan kanallar: <b>{stats['channels']} ta</b>\n"
        f"📢 Homiy kanallar: <b>{stats['sponsors']} ta</b>\n"
        f"⏳ Kutilayotgan postlar: <b>{stats['pending']} ta</b>\n"
        f"✅ Yuborilgan postlar: <b>{stats['sent']} ta</b>\n"
        f"🚫 Bekor qilingan: <b>{stats['cancelled']} ta</b>\n"
        f"⚠️ Xatolik: <b>{stats['failed']} ta</b>"
    )


def _build_admin_posts_text(posts: list) -> str:
    """📋 YAGONA «Barcha postlar» ekrani (``adm_posts`` + eski reply-tugma).

    ``posts`` — ``db.get_recent_posts`` natijasi (pid, uid, title, ptype,
    stime, status). Bo'sh ro'yxat uchun ham xavfsiz matn qaytaradi.
    """
    if not posts:
        return "📋 <b>Barcha postlar</b>\n\n<i>Hozircha hech qanday post mavjud emas.</i>"
    text = f"📋 <b>Oxirgi {len(posts)} ta post:</b>\n\n"
    for p in posts:
        pid, uid, title, ptype, stime, status = (list(p) + [None] * 6)[:6]
        title_str = title or "Noma'lum kanal"
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "posted" else "🚫")
        text += (
            f"{status_emoji} <b>#{pid}</b> | {html_escape(str(title_str))}"
            f" | {format_post_type_label(ptype)} | {html_escape(str(status))}\n"
        )
    return text


def _build_dbcache_text(status: dict) -> str:
    """🗄️ YAGONA «DB / Kesh holati» ekrani (``adm_dbcache`` + eski reply-tugma)."""
    collapsed_label = "yo'q" if status.get("collapsed") else "ha"
    cache_label = "yoqilgan" if status.get("cache_enabled") else "o'chirilgan"
    pool_label = "✅ ishlayapti" if status.get("ready") else "⏳ hali ochilmagan"
    return (
        "🗄️ <b>DB Pool va Kesh holati:</b>\n\n"
        f"   • Pool: <b>{pool_label}</b> ({status.get('message', '')})\n"
        f"   • Min/Maks: <b>{status.get('min')} / {status.get('max')}</b>\n"
        f"   • Band: <b>{status.get('used')}</b> | Bo'sh: <b>{status.get('available')}</b>"
        f" | Yopiq: <b>{collapsed_label}</b>\n"
        f"   • Kesh: <b>{cache_label}</b> — <b>{status.get('cache_entries')} ta</b> yozuv\n\n"
        "Kesh TTL o'zgarishlarsiz avtomatik eskiradi. Tozalash kerak bo'lsa pastdagi tugmani bosing."
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
    text = _build_dashboard_text(stats)
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
        _build_full_stats_text(stats),
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


async def _build_audit_roles_text(limit: int = 10) -> str:
    """📜 YAGONA «Audit | Rollar» ekrani matni (``adm_audit_roles``).

    Ikki blok: (1) oxirgi admin harakatlari — ``/audit`` buyrug'i bilan
    AYNAN bir xil format; (2) ``admin_roles`` jadvalidagi faol rollar.
    DB xatosida ham crash qilmaydi — bo'sh blok matni qaytaradi.
    """
    lines = ["📜 <b>Audit jurnali</b> (oxirgi harakatlar)",
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
        lines.append("<i>Audit jurnali hozircha bo'sh.</i>")

    lines += ["", "👥 <b>Rollar</b> (RBAC — /setrole, /delrole)",
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
        lines.append("<i>Qo'shimcha rollar berilmagan (faqat legacy ADMIN_IDS).</i>")
    return "\n".join(lines)


async def _ad_hub_render() -> tuple[str, InlineKeyboardMarkup]:
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
        return "✅ Yoqilgan" if on else "❌ O'chirilgan"

    lines = [
        "🎯 <b>Reklama boshqaruvi</b> — 3 ta asosiy bo'lim",
        "━━━━━━━━━━━━━━━━━",
        f"<b>1) 📢 Majburiy obuna (Sponsor kanallar)</b>\n"
        f"   Ulangan kanallar: <b>{len(sponsors)} ta</b> — "
        "matn/tugma va o'chirish bo'lim ichida.",
        "━━━━━━━━━━━━━━━━━",
        f"<b>2) 🤖 3-5 ta javobda chiqadigan reklama</b>\n"
        f"   Matn: pulda <b>{rp_active}</b>/{len(reply_ads)} ta faol\n"
        f"   Oraliq: har <b>{reply_interval}</b> ta javobda\n"
        f"   Holat: {_mark(reply_status)}",
        "━━━━━━━━━━━━━━━━━",
        f"<b>3) 📢 Kanal postlariga reklama qo'shish</b>\n"
        f"   Matn: pulda <b>{ch_active}</b>/{len(channel_ads)} ta faol\n"
        f"   Oraliq: har <b>{interval}</b>-postda (har kanal uchun alohida)\n"
        f"   Holat: {_mark(channel_status)}",
        "━━━━━━━━━━━━━━━━━",
        "Bo'limni tanlang 👇 Matn yuborsangiz 📢 Kanal posti puliga qo'shiladi.",
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


async def admin_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard inline tugmalari.

    Har bir matn kutuvchi bo'lim tegishli FSM holatini QAYTARADI — shu sababli
    admin yozgan javob to'g'ri handlerga tushadi (avval holat qaytarilmagani
    uchun matnli oqimlar ishlamay qolardi).
    """
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return ConversationHandler.END
    # 11-bosqich (P0): server-side RBAC — payload emas, from_user.id hal qiladi.
    if not verify_admin_callback(update):
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return ConversationHandler.END
    data = query.data

    if data == "adm_cancel":
        # Universal "Bekor qilish": FSM tozalanadi va dashboard qaytariladi.
        await query.answer("🚫 Bekor qilindi")
        clear_fsm_data(context)
        stats = await db.run_db(db.get_admin_dashboard_stats)
        await _admin_edit(query, _build_dashboard_text(stats), get_admin_dashboard_keyboard())
        return ConversationHandler.END

    if data == "adm_stats":
        await query.answer()
        stats = await db.run_db(db.get_system_stats)
        # 4-qadam: YAGONA statistika ekrani (reply-tugma va /admin_stats
        # buyrug'i ham aynan shu matnni chiqaradi).
        await _admin_edit(query, _build_full_stats_text(stats), get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_channels":
        await query.answer()
        channels = await db.run_db(db.get_all_channels, ADMIN_CHANNELS_LIMIT)
        if channels:
            text = format_admin_channels_list(channels)
        else:
            text = "📋 <b>Ulangan kanallar</b>\n\n<i>Hozircha hech qanday kanal ulanmagan.</i>"
        await _admin_edit(query, text, get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_posts":
        # 📋 Barcha postlar — eski «📋 Barcha postlar» reply-tugmasi va
        # ``admin_all_posts`` handleri bilan AYNAN bir xil ekran (4-qadam:
        # reply-klaviatura to'liq dashboard'ga integratsiya qilindi).
        await query.answer()
        recent_posts = await db.run_db(db.get_recent_posts, 15)
        await _admin_edit(query, _build_admin_posts_text(recent_posts),
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
            "🏷 <b>Post nishoni (watermark):</b>\n\n"
            "Hozirgi qiymat: <code>" + html_escape(current_tag or "(bo'sh — nishon yo'q)") + "</code>\n\n"
            "Postlar oxiriga qo'shiladigan matnni yuboring.\n"
            "Masalan: <code>@PostAssistrobot</code>\n"
            "O'chirish uchun <code>clear</code> deb yozing.",
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
            "⚙️ <b>AI parametrlarni boshqarish:</b>\n\n"
            f"{_ai_settings_text()}\n\n"
            "O'zgartirish uchun quyidagi formatda satrlarni yuboring:\n"
            "<code>kalit=qiymat</code>\n\n"
            "Masalan:\n"
            "<code>temperature=0.4</code>\n"
            "<code>max_tokens=2048</code>\n"
            "<code>context_messages=8</code>\n"
            "<code>max_tokens=off</code>  <i>(parametr umuman yuborilmaydi)</i>\n\n"
            "👉 Hammasini defaultga qaytarish uchun <code>reset</code> deb yozing.",
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
        await _admin_edit(query, _build_dbcache_text(status),
                          get_cache_actions_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_audit_roles":
        # 📜 Audit | 👥 Rollar — /audit buyrug'i bilan bir xil ma'lumot +
        # RBAC rollari ro'yxati. Faqat OWNER/SUPER_ADMIN (``/audit`` bilan
        # bir xil qoida — ``admin_audit_command`` dekoratori).
        if not has_role(query.from_user.id, Role.SUPER_ADMIN):
            await query.answer("❌ Audit jurnalini faqat OWNER yoki SUPER_ADMIN ko'ra oladi.",
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(query, await _build_audit_roles_text(),
                          get_admin_back_keyboard())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_health":
        # 🩺 Tizim monitoringi — to'liq Health hisoboti. Yuqoridagi is_admin
        # + verify_admin_callback tekshiruvlaridan o'tgan bo'lsa ham, hisobot
        # faqat system_settings ruxsati (RBAC) bo'lgan adminlarga ochiladi
        # (/health buyrug'i bilan bir xil qoida — fail-closed).
        if not has_permission(query.from_user.id, PERM_SYSTEM_SETTINGS):
            await query.answer("❌ Sizda tizim holatini ko'rish uchun ruxsat yo'q.",
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        from services.health_service import format_health_report

        lang = get_lang(context)
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
            await query.answer("❌ Sizda promo-kod boshqaruvi uchun ruxsat yo'q.",
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            "🎁 <b>Promo-kod yaratish:</b>\n\n"
            "Format: <code>KOD KUNLAR [MAKS_ISHLATISH]</code>\n\n"
            "Masalan:\n"
            "• <code>MAXSUS30 30 50</code> — 30 kun PRO, 50 marta\n"
            "• <code>YANGI2026 30</code> — 30 kun PRO, cheksiz\n\n"
            "Promo-kodni yozing:",
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "promo_create"
        return ADMIN_PROMO_CREATE

    if data == "adm_grant_pro":
        if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
            await query.answer("❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.",
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            "⭐️ <b>Foydalanuvchiga PRO berish:</b>\n\n"
            "Format: <code>USER_ID KUNLAR</code>\n\n"
            "Masalan: <code>123456789 30</code>\n\n"
            "User ID va kunlar sonini yozing:",
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "grant_pro"
        return ADMIN_GRANT_PRO

    if data == "adm_broadcast":
        if not has_permission(query.from_user.id, PERM_MANAGE_USERS):
            await query.answer("❌ Sizda broadcast yuborish uchun ruxsat yo'q.",
                               show_alert=True)
            return ConversationHandler.END
        await query.answer()
        await _admin_edit(
            query,
            "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\n"
            "Yuboriladigan xabar matnini yozing:",
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "broadcast"
        return BROADCAST_MESSAGE

    if data == "adm_sponsors":
        await query.answer()
        sponsors = await db.run_db(db.get_sponsor_channels) or []
        count = len(sponsors)
        text = (
            "📢 <b>Majburiy obuna (Sponsor kanallar) boshqaruvi:</b>\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"Ulangan kanallar soni: <b>{count} ta</b>\n\n"
        )
        if sponsors:
            for idx, s in enumerate(sponsors, 1):
                s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
                u_info = f" (@{username})" if username else ""
                link_info = f"\n   🔗 {ch_url}" if ch_url else ""
                text += f"{idx}. <b>{html_escape(ch_title)}</b>{u_info} (<code>{ch_id}</code>){link_info}\n\n"
        else:
            text += "<i>Hozircha hech qanday sponsor kanal ulanmagan.</i>\n\n"
        text += "━━━━━━━━━━━━━━━━━\nKanalni o'chirish uchun tegishli tugmani bosing yoki yangi kanal qo'shing 👇"
        await _admin_edit(query, text, get_admin_sponsors_keyboard(sponsors))
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_add_sponsor":
        await query.answer()
        await _admin_edit(
            query,
            "➕ <b>Yangi majburiy obuna kanali qo'shish:</b>\n\n"
            "Kanalning <code>@username</code>ini yoki kanal ID sini "
            "(masalan: <code>-1001234567890</code>) yuboring.\n\n"
            "⚠️ <b>Muhim shartlar:</b>\n"
            "1. Bot ushbu kanalda <b>administrator</b> bo'lishi shart.\n"
            "2. Botga kanal a'zolarini ko'rish huquqi berilgan bo'lishi kerak.\n\n"
            "Bekor qilish uchun ❌ Bekor qilish tugmasini bosing.",
            get_admin_back_keyboard(),
        )
        context.user_data["admin_flow"] = "add_sponsor"
        return ADMIN_SPONSOR_ADD

    if data in ("adm_adhub", "adm_auto_ad"):
        # Yagona Reklama markazi. ``adm_auto_ad`` — eski xabarlar uchun
        # orqaga moslik aliasi (dashboard eski versiyasida shu tugma bor edi).
        await query.answer()
        text, markup = await _ad_hub_render()
        await _admin_edit(query, text, markup)
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    if data == "adm_ad_toggle":
        ad_settings = await db.run_db(db.get_ad_settings)
        new_status = not ad_settings.get("auto_ad_status", False)
        await db.run_db(db.set_ad_status, new_status)
        await query.answer(
            "Javoblar reklamasi yoqildi ✅" if new_status
            else "Javoblar reklamasi o'chirildi ❌"
        )
        # Holat o'zgach to'liq hub qayta chiziladi — eski alohida ekran
        # (Har 3-5 javob reklamasi) endi mavjud emas.
        text, markup = await _ad_hub_render()
        await _admin_edit(query, text, markup)
        return ConversationHandler.END

    if data == "adm_channel_ad_toggle":
        # 3-bo'lim: 📢 Kanal postlariga reklama qo'shish — yoqish/o'chirish.
        ad_settings = await db.run_db(db.get_ad_settings)
        new_status = not ad_settings.get("channel_ad_status", True)
        await db.run_db(db.set_channel_ad_status, new_status)
        await query.answer(
            "Kanal posti reklamasi yoqildi ✅" if new_status
            else "Kanal posti reklamasi o'chirildi ❌"
        )
        text, markup = await _ad_hub_render()
        await _admin_edit(query, text, markup)
        return ConversationHandler.END

    if data == "adm_back":
        await query.answer()
        stats = await db.run_db(db.get_admin_dashboard_stats)
        await _admin_edit(query, _build_dashboard_text(stats), get_admin_dashboard_keyboard())
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

    # "Bekor qilish"/"Asosiy menyu" har qanday admin oqimida va UCHALA TILDA
    # ishlashi kerak (admin klaviaturasi ham tilga qarab chiziladi).
    # 🧭 4-qadam standarti: [❌ Bekor qilish] — kontekst tozalanib BO'LIM
    # BOSHIGA (admin dashboard) qaytadi; [🏠 Asosiy menyu] — asosiy menyu.
    if is_menu_text(text, "cancel", "main_menu"):
        clear_fsm_data(context)
        if is_menu_text(text, "cancel"):
            stats = await db.run_db(db.get_admin_dashboard_stats)
            await update.message.reply_text(
                "🚫 <b>Jarayon bekor qilindi.</b>\n\n" + _build_dashboard_text(stats),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            from handlers.navigation import clear_section
            clear_section(context)
            await update.message.reply_text(
                "🚫 <b>Jarayon bekor qilindi.</b>",
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
                "❌ Sizda foydalanuvchilarga PRO berish uchun ruxsat yo'q.",
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Noto'g'ri format. <code>USER_ID KUNLAR</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        try:
            target_id = int(parts[0])
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Raqamlar noto'g'ri. <code>USER_ID KUNLAR</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        if days <= 0:
            await update.message.reply_text(
                "❌ Kunlar soni 0 dan katta bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        success = await db.run_db(db.set_user_plan, target_id, "pro", days,
                                  admin_id=update.effective_user.id)
        if success:
            await update.message.reply_text(
                f"✅ <b>PRO tarif berildi!</b>\n\n"
                f"👤 Foydalanuvchi: <code>{target_id}</code>\n"
                f"📅 Muddat: <b>{days} kun</b>",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"🎉 <b>Tabriklaymiz!</b>\n\n"
                        f"Sizga <b>{days} kunlik PRO tarif</b> berildi!\n"
                        f"Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(
                "❌ Xatolik yuz berdi. User ID to'g'riligini tekshiring.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_GRANT_PRO

    if flow == "promo_create":
        if not has_permission(update.effective_user.id, PERM_MANAGE_PROMOS):
            await update.message.reply_text(
                "❌ Sizda promo-kod yaratish uchun ruxsat yo'q.",
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Noto'g'ri format. <code>KOD KUNLAR [MAKS]</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        code = parts[0].upper()
        try:
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Kunlar soni raqam bo'lishi kerak.",
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
                    "❌ Maks ishlatish soni raqam bo'lishi kerak.",
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                return ADMIN_PROMO_CREATE
        if days <= 0:
            await update.message.reply_text(
                "❌ Kunlar soni 0 dan katta bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        success = await db.run_db(db.create_promo_code, code, "pro", days, max_uses,
                                  admin_id=update.effective_user.id)
        if success:
            max_str = f"{max_uses} marta" if max_uses else "cheksiz"
            await update.message.reply_text(
                f"✅ <b>Promo-kod yaratildi!</b>\n\n"
                f"🏷 Kod: <code>{code}</code>\n"
                f"📅 Muddat: <b>{days} kun</b> PRO\n"
                f"🔢 Maks ishlatish: <b>{max_str}</b>",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "❌ Promo-kod yaratishda xatolik. Bu kod allaqachon mavjud bo'lishi mumkin.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_PROMO_CREATE

    if flow == "broadcast":
        if not has_permission(update.effective_user.id, PERM_MANAGE_USERS):
            await update.message.reply_text(
                "❌ Sizda broadcast yuborish uchun ruxsat yo'q.",
                reply_markup=get_admin_back_keyboard(),
            )
            context.user_data.pop("admin_flow", None)
            return ConversationHandler.END
        user_ids = await db.run_db(db.get_all_user_ids)
        await update.message.reply_text(
            f"⏳ Xabar <b>{len(user_ids)} ta</b> foydalanuvchiga yuborilmoqda...\n"
            f"<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>",
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
                        f"✅ <b>Homiy kanal muvaffaqiyatli qo'shildi!</b>\n\n"
                        f"📢 <b>{html_escape(title)}</b> (<code>{ch_id}</code>)\n"
                        f"🔗 {url}",
                        reply_markup=get_admin_back_keyboard(),
                        parse_mode="HTML",
                    )
                    context.user_data.pop("admin_flow", None)
                    return ConversationHandler.END
                else:
                    await update.message.reply_text(
                        "❌ Saqlashda xatolik yuz berdi.",
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
                    f"❌ <b>Bot bu kanalda admin emas!</b>\n\n"
                    f"Kanal: <b>{html_escape(chat.title or '')}</b> (<code>{chat.id}</code>)\n\n"
                    "Iltimos, avval botni ushbu kanalga <b>admin</b> qilib qo'shing va qaytadan yuboring:",
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

            title = chat.title or "Sponsor Kanal"
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
                    f"✅ <b>Sponsor kanal muvaffaqiyatli qo'shildi!</b>\n\n"
                    f"📢 <b>{html_escape(title)}</b>\n"
                    f"🆔 <code>{chat.id}</code>\n"
                    f"{user_line}"
                    f"🔗 {invite_link}",
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                context.user_data.pop("admin_flow", None)
                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    "❌ Bazaga saqlashda xatolik yuz berdi.",
                    reply_markup=get_admin_back_keyboard(),
                )
                return ADMIN_SPONSOR_ADD
        except Exception as e:
            logger.error(f"Sponsor kanal tekshirish xatosi: {e}")
            await update.message.reply_text(
                f"❌ <b>Kanal topilmadi yoki bot u yerda admin emas!</b>\n\n"
                f"Xatolik tafsiloti: <i>{html_escape(str(e))}</i>\n\n"
                "Iltimos, botni kanalga admin qilganingizga ishonch hosil qilib, @username yoki ID sini qayta yuboring:",
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
    await update.message.reply_text(
        "⚙️ <b>AI parametrlarni boshqarish:</b>\n\n"
        f"{_ai_settings_text()}\n\n"
        "O'zgartirish uchun quyidagi formatda satrlarni yuboring:\n"
        "<code>kalit=qiymat</code>\n\n"
        "Masalan:\n"
        "<code>temperature=0.4</code>\n"
        "<code>max_tokens=2048</code>\n"
        "<code>context_messages=8</code>\n"
        "<code>max_tokens=off</code>  <i>(parametr umuman yuborilmaydi)</i>\n\n"
        "👉 Hammasini defaultga qaytarish uchun <code>reset</code> deb yozing.\n"
        "Bekor qilish uchun asosiy menyu tugmasini bosing.",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return AI_SETTINGS


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="❌ AI parametrlarini faqat bot egasi (OWNER) o'zgartira oladi.")
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
        await update.message.reply_text(
            "✅ <b>Barcha AI parametrlar default holatga qaytarildi.</b>\n\n"
            f"{_ai_settings_text()}",
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
            errors.append(f"<code>{html_escape(key)}</code> — noma'lum kalit")
            continue
        import utils.ai_agent as _agent
        valid = _agent._set_runtime_param(key, value)
        if not valid:
            errors.append(f"<code>{html_escape(key)}</code> = <code>{html_escape(value)}</code> — noto'g'ri qiymat")
            continue
        updates[AI_SETTINGS_KEYS[key][0]] = value.strip()
        updates["__ui_key__"] = key

    if errors:
        await update.message.reply_text(
            "⚠️ <b>Quyidagi kalitlarni o'zgartirib bo'lmadi:</b>\n" + "\n".join(errors),
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
            "✅ <b>AI parametrlar yangilandi:</b>\n\n"
            f"{_ai_settings_text()}",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
    elif not errors:
        await update.message.reply_text(
            "⚠️ Hech qanday kalit kiritilmadi. <code>kalit=qiymat</code> formatida yuboring.",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
    return AI_SETTINGS


async def cache_db_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    status = await db.run_db(db.get_db_pool_status)
    collapsed_label = "yo'q" if status.get("collapsed") else "ha"
    cache_label = "yoqilgan" if status.get("cache_enabled") else "o'chirilgan"
    pool_label = "✅ ishlayapti" if status.get("ready") else "⏳ hali ochilmagan"
    text = (
        "🗄️ <b>DB Pool va Kesh holati:</b>\n\n"
        f"   • Pool: <b>{pool_label}</b> ({status.get('message', '')})\n"
        f"   • Min/Maks: <b>{status.get('min')} / {status.get('max')}</b>\n"
        f"   • Band: <b>{status.get('used')}</b> | Bo'sh: <b>{status.get('available')}</b>"
        f" | Yopiq: <b>{collapsed_label}</b>\n"
        f"   • Kesh: <b>{cache_label}</b> — <b>{status.get('cache_entries')} ta</b> yozuv\n\n"
        "Kesh TTL o'zgarishlarsiz avtomatik eskiradi. Tozalash kerak bo'lsa pastdagi tugmani bosing."
    )
    await update.message.reply_text(
        text,
        reply_markup=get_cache_actions_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="❌ Keshni faqat bot egasi (OWNER) tozalay oladi.")
async def cache_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return
    await db.run_db(AuditService.log_action, query.from_user.id, "system_settings",
                    target_type="system_settings", target_id="cache_clear",
                    new_value={"action": "cache_clear"})
    await db.run_db(db.cache_clear)
    status = await db.run_db(db.get_db_pool_status)
    await query.answer("✅ Kesh tozalandi.")
    collapsed_label = "yo'q" if status.get("collapsed") else "ha"
    cache_label = "yoqilgan" if status.get("cache_enabled") else "o'chirilgan"
    pool_label = "✅ ishlayapti" if status.get("ready") else "⏳ hali ochilmagan"
    try:
        await query.edit_message_text(
            "🗄️ <b>DB Pool va Kesh holati:</b>\n\n"
            f"   • Pool: <b>{pool_label}</b>\n"
            f"   • Min/Maks: <b>{status.get('min')} / {status.get('max')}</b>\n"
            f"   • Band: <b>{status.get('used')}</b> | Bo'sh: <b>{status.get('available')}</b>"
            f" | Yopiq: <b>{collapsed_label}</b>\n"
            f"   • Kesh: <b>{cache_label}</b> — <b>{status.get('cache_entries')} ta</b> yozuv\n\n"
            "✅ <b>Kesh tozalandi.</b>",
            reply_markup=get_cache_actions_keyboard(),
            parse_mode="HTML",
        )
    except TelegramError:
        pass


async def start_set_post_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    current_tag = await db.run_db(db.get_setting, "post_tag_text", "")
    await update.message.reply_text(
        "🏷 <b>Post nishoni (watermark):</b>\n\n"
        "Hozirgi qiymat: <code>" + html_escape(current_tag or "(bo'sh — nishon yo'q)") + "</code>\n\n"
        "Postlar oxiriga qo'shiladigan matnni yuboring.\n"
        "Masalan: <code>@PostAssistrobot</code>\n"
        "O'chirish uchun <code>clear</code> deb yozing.",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return SET_POST_TAG


@require_permission(PERM_SYSTEM_SETTINGS,
                    message="❌ Post nishonini faqat bot egasi (OWNER) o'zgartira oladi.")
async def post_tag_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
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
            "✅ <b>Post nishoni o'chirildi</b> — postlar toza chiqadi.",
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
            f"✅ <b>Post nishoni saqlandi:</b>\n\n<code>{html_escape(text)}</code>",
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
    return ConversationHandler.END


@require_role(Role.OWNER, strict=True,
              message="❌ Rol berish/olishni faqat OWNER (bot egasi) bajaradi.")
async def admin_set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/setrole <user_id> <rol>` — admin rolini berish (faqat OWNER).

    Rollar: ``owner``, ``super_admin``, ``admin``, ``moderator``, ``finance``.
    ``user`` berilsa rol olib tashlanadi. Har bir amal ``admin_audit_logs``
    jadvaliga yoziladi (``set_role`` / ``remove_role``).
    """
    args = getattr(context, "args", None) or []
    if len(args) < 2:
        await update.message.reply_text(
            "📝 Foydalanish: <code>/setrole &lt;user_id&gt; &lt;rol&gt;</code>\n\n"
            "Rollar: <code>owner</code>, <code>super_admin</code>, <code>admin</code>, "
            "<code>moderator</code>, <code>finance</code>\n"
            "Rolni olib tashlash uchun <code>user</code> yozing.",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(args[0])
    except (TypeError, ValueError):
        await update.message.reply_text(
            "❌ Noto'g'ri foydalanuvchi ID. Masalan: /setrole 123456789 admin"
        )
        return
    role = parse_role(args[1])
    if role is None:
        await update.message.reply_text(
            "❌ Noma'lum rol. Mumkin: owner, super_admin, admin, moderator, finance, user."
        )
        return
    admin_id = update.effective_user.id
    ok = await db.run_db(set_role, target_id, role, granted_by=admin_id)
    if not ok:
        await update.message.reply_text("❌ Rolni saqlab bo'lmadi (baza bilan aloqa).")
        return
    if role is Role.USER:
        text = (f"✅ <b>Rol olib tashlandi.</b>\n\n"
                f"👤 Foydalanuvchi: <code>{target_id}</code>")
    else:
        perms = ", ".join(required_permissions(role)) or "—"
        text = (f"✅ <b>Rol berildi.</b>\n\n"
                f"👤 Foydalanuvchi: <code>{target_id}</code>\n"
                f"🎖 Rol: <b>{html_escape(role.value.upper())}</b>\n"
                f"🔑 Ruxsatlar: <code>{html_escape(perms)}</code>")
    await update.message.reply_text(text, parse_mode="HTML")


@require_role(Role.OWNER, strict=True,
              message="❌ Rol olishni faqat OWNER (bot egasi) bajaradi.")
async def admin_del_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/delrole <user_id>` — admin rolini olib tashlash (faqat OWNER)."""
    args = getattr(context, "args", None) or []
    if not args:
        await update.message.reply_text(
            "📝 Foydalanish: <code>/delrole &lt;user_id&gt;</code>", parse_mode="HTML",
        )
        return
    try:
        target_id = int(args[0])
    except (TypeError, ValueError):
        await update.message.reply_text("❌ Noto'g'ri foydalanuvchi ID.")
        return
    admin_id = update.effective_user.id
    ok = await db.run_db(remove_role, target_id, granted_by=admin_id)
    if not ok:
        await update.message.reply_text(
            f"❌ <code>{target_id}</code> foydalanuvchida DB'dagi rol topilmadi."
        )
        return
    await update.message.reply_text(
        f"✅ <b>Rol olib tashlandi.</b>\n\n👤 Foydalanuvchi: <code>{target_id}</code>",
        parse_mode="HTML",
    )


@require_role(Role.SUPER_ADMIN,
              message="❌ Audit jurnalini faqat OWNER yoki SUPER_ADMIN ko'ra oladi.")
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
    rows = await db.run_db(db.get_admin_audit_logs, limit=limit)
    if not rows:
        await update.message.reply_text(
            "📝 <b>Audit jurnali hozircha bo'sh.</b>\n"
            "<i>Admin harakatlari (chek, PRO, promo, sozlamalar) shu yerda ko'rinadi.</i>",
            parse_mode="HTML",
        )
        return
    lines = [f"📝 <b>Oxirgi admin harakatlari</b> (jami {len(rows)} ta):",
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
        _build_full_stats_text(stats),
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
        _build_admin_posts_text(recent_posts),
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )


async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📋 Barcha kanal/guruhlar» reply-tugmasi — ``adm_channels`` bilan bir xil ekran."""
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    channels = await db.run_db(db.get_all_channels, ADMIN_CHANNELS_LIMIT)
    if not channels:
        await update.message.reply_text("Hozircha ulangan kanallar yo'q.", reply_markup=get_admin_dashboard_keyboard())
        return

    text = format_admin_channels_list(channels)
    await update.message.reply_text(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")


async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    _remember_admin_section(context)
    sponsors = await db.run_db(db.get_sponsor_channels)
    if sponsors is None:
        await update.message.reply_text(
            "⚠️ Homiy kanallarni bazadan o'qib bo'lmadi. Keyinroq urinib ko'ring.",
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return
    count = len(sponsors)
    text = f"📢 <b>Majburiy a'zolik (Homiy) kanallari ({count} ta):</b>\n━━━━━━━━━━━━━━━━━\n"
    if sponsors:
        for idx, s in enumerate(sponsors, 1):
            s_id, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
            u_info = f" (@{username})" if username else ""
            text += f"{idx}. 🔹 <b>{html_escape(ch_title)}</b>{u_info} (<code>{ch_id}</code>)\n   🔗 Havola: {ch_url}\n\n"
    else:
        text += "Hozircha hech qanday homiy kanal qo'shilmagan.\n\n"

    text += "━━━━━━━━━━━━━━━━━\nO'chirish uchun pastdagi ro'yxatdan tanlang yoki yangi kanal qo'shing 👇"
    await update.message.reply_text(text, reply_markup=get_admin_sponsors_keyboard(sponsors), parse_mode="HTML")


async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    await update.message.reply_text(
        "➕ <b>Homiy kanal qo'shish:</b>\n\n"
        "Kanalning <code>@username</code>ini, ID sini (masalan: <code>-1001234567890</code>) yoki formatda yuboring:\n"
        "<code>KANAL_ID|KANAL_NOMI|HAVOLA</code>\n\n"
        "⚠️ <i>Bot ushbu kanalda administrator bo'lishi shart.</i>",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML"
    )
    return ADD_SPONSOR_CHANNEL


async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()

    if "|" in text:
        parts = text.split("|")
        if len(parts) >= 3:
            ch_id, title, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
            success = await db.run_db(db.add_sponsor_channel, ch_id, title=title, invite_link=url)
            if success:
                await update.message.reply_text(
                    f"✅ Homiy kanal qo'shildi: <b>{html_escape(title)}</b>",
                    reply_markup=get_admin_dashboard_keyboard(),
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_admin_dashboard_keyboard())
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
                f"❌ <b>Bot bu kanalda admin emas!</b>\n\n"
                f"Kanal: <b>{html_escape(chat.title or '')}</b> (<code>{chat.id}</code>)\n\n"
                "Iltimos, avval botni ushbu kanalga <b>admin</b> qiling va qayta yuboring:",
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

        title = chat.title or "Sponsor Kanal"
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
                f"✅ Homiy kanal muvaffaqiyatli qo'shildi: <b>{html_escape(title)}</b>",
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_admin_dashboard_keyboard())
    except Exception as e:
        logger.error(f"Sponsor kanal tekshirish xatosi: {e}")
        await update.message.reply_text(
            f"❌ Kanal topilmadi yoki bot u yerda admin emas ({html_escape(str(e))}). Qaytadan kiriting:",
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
            await query.message.reply_text("🚫 Ruxsat yo'q.")
        except Exception:
            pass
        return
    # 11-bosqich (P0): payload ID qat'iy tekshiriladi (tampering himoyasi).
    try:
        (s_id,) = admin_callback_guard(update, CB_SPONSOR_DELETE, 1)
    except CallbackTampering:
        return
    removed = await db.run_db(db.remove_sponsor_channel, s_id)
    if not removed:
        try:
            await query.message.reply_text("⚠️ Homiy kanal o'chirilmadi. Qayta urinib ko'ring.")
        except Exception:
            pass
    # Yangilangan ro'yxatni qayta chizamiz
    sponsors = await db.run_db(db.get_sponsor_channels) or []
    count = len(sponsors)
    text = (
        "📢 <b>Majburiy obuna (Sponsor kanallar) boshqaruvi:</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"Ulangan kanallar soni: <b>{count} ta</b>\n\n"
    )
    if sponsors:
        for idx, s in enumerate(sponsors, 1):
            s_id_item, ch_id, ch_title, username, ch_url = unpack_sponsor(s)
            u_info = f" (@{username})" if username else ""
            link_info = f"\n   🔗 {ch_url}" if ch_url else ""
            text += f"{idx}. <b>{html_escape(ch_title)}</b>{u_info} (<code>{ch_id}</code>){link_info}\n\n"
    else:
        text += "<i>Hozircha hech qanday sponsor kanal ulanmagan.</i>\n\n"
    text += "━━━━━━━━━━━━━━━━━\nKanalni o'chirish uchun tegishli tugmani bosing yoki yangi kanal qo'shing 👇"

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
AD_SCOPE_META = {
    "channel": {
        "title": "📢 Kanal postlari",
        "state": SET_CHANNEL_AD,
    },
    "reply": {
        "title": "🤖 Bot javoblari",
        "state": SET_BOT_REPLY_AD,
    },
}

AD_HTML_HINT = (
    "💡 <b>HTML formatlash mumkin:</b>\n"
    "<code>&lt;b&gt;qalin&lt;/b&gt;</code>, <code>&lt;i&gt;kursiv&lt;/i&gt;</code>, "
    "<code>&lt;u&gt;tagchiziq&lt;/u&gt;</code>, "
    "<code>&lt;a href=\"https://t.me/kanal\"&gt;havola&lt;/a&gt;</code>"
)


def _ad_scope_state(scope: str):
    """Scope uchun FSM holati (matn kutilayotgan holat)."""
    return AD_SCOPE_META.get(scope, {}).get("state", SET_CHANNEL_AD)


def _format_ad_pool(ads) -> str:
    """Rotatsiya puli ro'yxatini HTML-xavfsiz matn ko'rinishida chiqaradi."""
    if not ads:
        return "   <i>(Hozircha hech qanday reklama yo'q)</i>"
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


def _format_ad_card(ad: dict, scope: str) -> str:
    """Bitta reklama kartochkasi (tahrirlash ekrani uchun)."""
    ad = ad or {}
    title = AD_SCOPE_META.get(scope, {}).get("title", scope)
    status = "🟢 Faol (Active)" if ad.get("is_active", True) else "🔴 O'chirilgan (Inactive)"
    btn_text = (ad.get("button_text") or "").strip()
    btn_url = (ad.get("button_url") or "").strip()
    if btn_text and btn_url:
        button_line = f"<b>{html_escape(btn_text)}</b> → {html_escape(btn_url)}"
    else:
        button_line = "<i>(tugma yo'q)</i>"
    return (
        f"✏️ <b>Reklamani tahrirlash</b> — {title}\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{ad.get('id', 0)}</code>\n"
        f"📊 Holat: {status}\n"
        f"🔗 Inline tugma: {button_line}\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Matn (HTML):</b>\n<code>{html_escape(ad.get('text') or '')}</code>\n\n"
        "👁 <b>Ko'rinishi:</b>\n"
        f"{safe_html(ad.get('text') or '')}\n\n"
        "Quyidagi tugmalar orqali tahrirlang 👇"
    )


async def _ad_pool_menu_text(scope: str) -> str:
    """Reklama puli menyusi uchun matn (sarlavha + ro'yxat + yo'riqnoma)."""
    ads = await db.run_db(db.get_ads_full, scope, True)
    meta = AD_SCOPE_META.get(scope, {})
    title = meta.get("title", scope)
    active = sum(1 for a in ads if a.get("is_active", True))
    text = (
        f"{title} — <b>avto-rotatsiya</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"📦 Jami: <b>{len(ads)} ta</b>  |  🟢 Faol: <b>{active} ta</b>\n"
    )
    if scope == "channel":
        interval = await db.run_db(db.get_channel_ad_interval)
        text += f"⏱ Reklama oralig'i: <b>har {interval}-post</b> (kanal bo'yicha alohida)\n"
    else:
        settings = await db.run_db(db.get_ad_settings)
        interval = settings.get("auto_ad_interval", 4)
        text += f"⏱ Reklama oralig'i: <b>har {interval} javob</b>\n"
    text += (
        "━━━━━━━━━━━━━━━━━\n"
        f"<b>Reklama puli:</b>\n{_format_ad_pool(ads)}\n\n"
        "Reklamani tahrirlash uchun uning ustiga bosing. "
        "Bot faqat 🟢 <b>faol</b> reklamalarni navbatma-navbat qo'shadi."
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


async def _show_ad_pool_menu(query, scope: str):
    """Reklama puli menyusini (matn + klaviatura) qayta chizadi."""
    text = await _ad_pool_menu_text(scope)
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


async def _show_ad_card(query, scope: str, ad_id: int) -> bool:
    """Bitta reklama kartochkasini ko'rsatadi. Topilmasa False."""
    ad = await db.run_db(db.get_ad, ad_id)
    if not ad:
        await _show_ad_pool_menu(query, scope)
        return False
    await _edit_or_send(query, _format_ad_card(ad, scope), get_ad_edit_keyboard(ad, scope))
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
    text, markup = await _ad_hub_render()
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return SET_CHANNEL_AD


async def start_set_channel_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop("ad_edit", None)
    text = await _ad_pool_menu_text("channel")
    markup = await _ad_pool_menu_markup("channel")
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    await update.message.reply_text(
        "Yangi reklama matnini shu yerga yozib yuborishingiz mumkin (pulga qo'shiladi).\n"
        f"{AD_HTML_HINT}\n\n"
        "Bekor qilish uchun ❌ Bekor qilish tugmasini bosing.",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )
    return SET_CHANNEL_AD


async def start_set_bot_reply_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop("ad_edit", None)
    text = await _ad_pool_menu_text("reply")
    markup = await _ad_pool_menu_markup("reply")
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    await update.message.reply_text(
        "Yangi reklama matnini shu yerga yozib yuborishingiz mumkin (pulga qo'shiladi).\n"
        f"{AD_HTML_HINT}\n\n"
        "Bekor qilish uchun ❌ Bekor qilish tugmasini bosing.",
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

    # --- 1. Mavjud reklamaning inline URL tugmasini tahrirlash ---
    if pending.get("field") == "button" and pending.get("scope") == scope:
        if text.lower() in ("clear", "-", "yo'q", "yoq"):
            await db.run_db(db.update_ad, pending["id"], None, "", "")
            context.user_data.pop("ad_edit", None)
            await update.message.reply_text(
                "🚫 <b>Inline tugma olib tashlandi.</b>",
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
            await _send_ad_card(update, context, scope, pending["id"])
            return state

        btn_text, btn_url = parse_button_input(text)
        if not btn_text or not btn_url:
            await update.message.reply_text(
                "❌ Noto'g'ri format. <code>Tugma matni | https://havola</code> ko'rinishida yuboring.\n"
                "Tugmani olib tashlash uchun <code>clear</code> deb yozing.",
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
                f"✅ <b>Inline tugma saqlandi:</b> {html_escape(btn_text)} → {html_escape(btn_url)}",
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.",
                                            reply_markup=get_admin_dashboard_keyboard())
        await _send_ad_card(update, context, scope, pending["id"])
        return state

    # --- 2. Mavjud reklama matnini tahrirlash ---
    if pending.get("field") == "text" and pending.get("scope") == scope:
        ok, err = validate_ad_html(text, max_len=db.AD_TEXT_MAX_LEN)
        if not ok:
            await update.message.reply_text(
                f"❌ {err}\n\n{AD_HTML_HINT}",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return state
        saved = await db.run_db(db.update_ad, pending["id"], text)
        context.user_data.pop("ad_edit", None)
        if saved:
            await update.message.reply_text(
                "✅ <b>Reklama matni yangilandi!</b>",
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.",
                                            reply_markup=get_admin_dashboard_keyboard())
        await _send_ad_card(update, context, scope, pending["id"])
        return state

    # --- 3. Kanal reklama oralig'ini qo'lda kiritish ---
    if pending.get("field") == "interval" and pending.get("scope") == scope:
        try:
            value = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Faqat butun son kiriting (masalan: 3, 4 yoki 5).",
                reply_markup=get_admin_back_keyboard(),
            )
            return state
        if value < db.AD_INTERVAL_MIN or value > db.AD_INTERVAL_MAX:
            await update.message.reply_text(
                f"❌ Oraliq {db.AD_INTERVAL_MIN} va {db.AD_INTERVAL_MAX} orasida bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
            )
            return state
        if scope == "channel":
            await db.run_db(db.set_channel_ad_interval, value)
            unit = "post"
        else:
            await db.run_db(db.set_ad_interval, value)
            unit = "javob"
        context.user_data.pop("ad_edit", None)
        await update.message.reply_text(
            f"✅ <b>Reklama oralig'i yangilandi:</b> endi har <b>{value}-{unit}da</b> reklama chiqadi.\n"
            + ("<i>Sanagich har bir kanal uchun alohida yuritiladi.</i>"
               if scope == "channel" else "<i>Har bir foydalanuvchi uchun alohida hisoblanadi.</i>"),
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
        await _send_ad_menu(update, context, scope)
        return state

    # --- 4. Yangi reklama qo'shish ---
    if text.lower() == "clear":
        removed = await db.run_db(db.clear_ads, scope)
        await update.message.reply_text(
            f"🧹 Reklamalar tozalandi ({removed} ta).",
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return ConversationHandler.END

    ok, err = validate_ad_html(text, max_len=db.AD_TEXT_MAX_LEN)
    if not ok:
        await update.message.reply_text(
            f"❌ {err}\n\n{AD_HTML_HINT}",
            reply_markup=get_admin_back_keyboard(),
            parse_mode="HTML",
        )
        return state

    ad_id = await db.run_db(db.add_ad, scope, text)
    if ad_id > 0:
        await update.message.reply_text(
            "✅ <b>Reklama rotatsiya puliga qo'shildi!</b>\n"
            "Inline URL tugma qo'shish uchun ro'yxatdan uni tanlang.",
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.",
                                        reply_markup=get_admin_dashboard_keyboard())
    await _send_ad_menu(update, context, scope)
    return state


async def _send_ad_menu(update, context, scope: str):
    """Yangilangan reklama menyusini yangi xabar sifatida yuboradi."""
    menu = await _ad_pool_menu_text(scope)
    markup = await _ad_pool_menu_markup(scope)
    await update.message.reply_text(menu, reply_markup=markup, parse_mode="HTML")


async def _send_ad_card(update, context, scope: str, ad_id: int):
    """Tahrirlangan reklama kartochkasini yangi xabar sifatida yuboradi."""
    ad = await db.run_db(db.get_ad, ad_id)
    if not ad:
        await _send_ad_menu(update, context, scope)
        return
    await update.message.reply_text(
        _format_ad_card(ad, scope),
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
    title = meta["title"]
    state = meta["state"]

    def _ad_id():
        try:
            return int(arg)
        except (TypeError, ValueError):
            return None

    if action == "add":
        context.user_data.pop("ad_edit", None)
        text = (
            f"✍️ <b>{title}</b> — yangi reklama matnini yozing.\n\n"
            f"{AD_HTML_HINT}\n\n"
            "<i>Barcha reklamalarni o'chirish uchun</i> <code>clear</code> <i>deb yozing.</i>"
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "e":
        ad_id = _ad_id()
        context.user_data.pop("ad_edit", None)
        if ad_id is None:
            await _show_ad_pool_menu(query, scope)
            return state
        await _show_ad_card(query, scope, ad_id)
        return state

    if action == "et":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope)
            return state
        ad = await db.run_db(db.get_ad, ad_id)
        if not ad:
            await _show_ad_pool_menu(query, scope)
            return state
        context.user_data["ad_edit"] = {"id": ad_id, "field": "text", "scope": scope}
        text = (
            f"✏️ <b>#{ad_id} — yangi matnni yuboring:</b>\n\n"
            f"<b>Hozirgi matn:</b>\n<code>{html_escape(ad.get('text') or '')}</code>\n\n"
            f"{AD_HTML_HINT}"
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "eb":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope)
            return state
        ad = await db.run_db(db.get_ad, ad_id)
        if not ad:
            await _show_ad_pool_menu(query, scope)
            return state
        context.user_data["ad_edit"] = {"id": ad_id, "field": "button", "scope": scope}
        current = ""
        if (ad.get("button_text") or "").strip():
            current = (
                f"<b>Hozirgi tugma:</b> {html_escape(ad['button_text'])} → "
                f"{html_escape(ad.get('button_url') or '')}\n\n"
            )
        text = (
            f"🔗 <b>#{ad_id} — inline URL tugma:</b>\n\n"
            f"{current}"
            "Quyidagi formatda yuboring:\n"
            "<code>Tugma matni | https://t.me/kanal</code>\n\n"
            "Tugmani olib tashlash uchun <code>clear</code> deb yozing."
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "bx":
        ad_id = _ad_id()
        if ad_id is not None:
            await db.run_db(db.update_ad, ad_id, None, "", "")
            context.user_data.pop("ad_edit", None)
            await _show_ad_card(query, scope, ad_id)
        return state

    if action == "tg":
        ad_id = _ad_id()
        if ad_id is None:
            await _show_ad_pool_menu(query, scope)
            return state
        new_status = await db.run_db(db.toggle_ad_active, ad_id)
        if new_status is None:
            await _show_ad_pool_menu(query, scope)
            return state
        try:
            await query.answer("🟢 Reklama faollashtirildi" if new_status else "🔴 Reklama o'chirildi")
        except Exception:
            pass
        await _show_ad_card(query, scope, ad_id)
        return state

    if action == "rm":
        ad_id = _ad_id()
        if ad_id is not None:
            await db.run_db(db.delete_ad, ad_id)
            context.user_data.pop("ad_edit", None)
        await _show_ad_pool_menu(query, scope)
        return state

    if action == "del":
        ads = await db.run_db(db.get_ads_full, scope, True)
        text = f"🗑 <b>{title}</b> — o'chiriladigan reklamani tanlang:\n\n{_format_ad_pool(ads)}"
        await _edit_or_send(query, text, get_ad_pool_delete_keyboard(ads, scope))
        return state

    if action == "clear":
        removed = await db.run_db(db.clear_ads, scope)
        context.user_data.pop("ad_edit", None)
        try:
            await query.answer(f"🧹 {removed} ta reklama o'chirildi")
        except Exception:
            pass
        await _show_ad_pool_menu(query, scope)
        return state

    if action == "iv":
        # Reklama oralig'i — HAR BIR BO'LIM uchun o'z sozlamasi:
        #   channel → har nechanchi POSTDA,  reply → har nechta JAVOBDA.
        is_channel = (scope == "channel")
        unit = "post" if is_channel else "javob"
        if arg is not None:
            value = db.clamp_ad_interval(arg, 3 if is_channel else 4)
            if is_channel:
                await db.run_db(db.set_channel_ad_interval, value)
            else:
                await db.run_db(db.set_ad_interval, value)
            context.user_data.pop("ad_edit", None)
            try:
                await query.answer(f"✅ Endi har {value}-{unit}da reklama chiqadi")
            except Exception:
                pass
            await _show_ad_pool_menu(query, scope)
            return state

        if is_channel:
            current = await db.run_db(db.get_channel_ad_interval)
        else:
            settings = await db.run_db(db.get_ad_settings)
            current = settings.get("auto_ad_interval", 4)
        context.user_data["ad_edit"] = {"id": 0, "field": "interval", "scope": scope}
        if is_channel:
            explain = (
                "Bot har nechanchi postda reklama qo'shsin? Sanagich <b>har bir "
                "kanal uchun alohida</b> yuritiladi — bir kanaldagi postlar "
                "boshqasiga ta'sir qilmaydi."
            )
        else:
            explain = (
                "Bot har nechta javobda reklama qo'shsin? Standart qiymat: "
                "<b>4</b> (ya'ni har 3-5 ta javobda)."
            )
        text = (
            "⏱ <b>Reklama oralig'ini sozlash</b>\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"Hozirgi qiymat: <b>har {current}-{unit}</b>\n\n"
            f"{explain}\n\n"
            f"Tugmalardan tanlang yoki {db.AD_INTERVAL_MIN}–{db.AD_INTERVAL_MAX} "
            "oralig'idagi sonni yozib yuboring."
        )
        await _edit_or_send(query, text, get_ad_interval_keyboard(scope, current))
        return state

    if action == "info":
        interval_line = ""
        if scope == "channel":
            interval = await db.run_db(db.get_channel_ad_interval)
            interval_line = (
                f"• Kanal postlari: har <b>{interval}-postda</b> bitta reklama "
                "(sanagich har bir kanal uchun alohida).\n"
            )
        text = (
            f"ℹ️ <b>{title} — avto-rotatsiya</b>\n\n"
            "Pulga bir nechta reklama qo'shsangiz, bot ularni navbatma-navbat "
            "(round-robin) qo'shadi.\n"
            f"{interval_line}"
            "• Bot javoblari: har 3-xabarga bitta reklama.\n"
            "• 🔴 holatdagi reklamalar rotatsiyada qatnashmaydi.\n"
            "• Har bir reklamaga inline URL tugma biriktirish mumkin.\n\n"
            "Pul bo'sh bo'lsa eski yagona reklama ishlashda davom etadi."
        )
        await _edit_or_send(query, text, get_ad_pool_back_keyboard(scope))
        return state

    if action == "back":
        context.user_data.pop("ad_edit", None)
        await _show_ad_pool_menu(query, scope)
        return state

    return state


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    _remember_admin_section(context)
    await update.message.reply_text(
        "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\nYuboriladigan xabar matnini yozing:",
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML"
    )
    return BROADCAST_MESSAGE


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    # Avvalgi broadcast hali davom etayotgan bo'lsa — takroriy ishga tushirmaymiz
    if _broadcast_lock.locked():
        await update.message.reply_text(
            "⏳ <b>Avvalgi xabar yuborilishi hali davom etmoqda.</b>\n"
            "Iltimos, yakunlanishini kuting (natija haqida xabar keladi).",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    if not has_permission(update.effective_user.id, PERM_MANAGE_USERS):
        await update.message.reply_text("❌ Sizda broadcast yuborish uchun ruxsat yo'q.")
        return ConversationHandler.END

    text = update.message.text
    # DB chaqiruvini event loop'ni bloklamasdan thread'da bajarish
    user_ids = await db.run_db(db.get_all_user_ids)

    await update.message.reply_text(
        f"⏳ Xabar <b>{len(user_ids)} ta</b> foydalanuvchiga yuborilmoqda...\n"
        f"<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>",
        parse_mode="HTML"
    )

    # Broadcast fon vazifasi sifatida ishlaydi — admin boshqa buyruqlarni
    # bemalol ishlatishi mumkin, Telegram esa rate-limitga tushmaydi.
    async def _broadcast_task():
        async with _broadcast_lock:
            await _run_broadcast(context.bot, user_ids, text, update.effective_user.id)

    asyncio.create_task(_broadcast_task())
    return ConversationHandler.END


async def _run_broadcast(bot, user_ids, text, admin_id):
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
            text=(
                f"✅ <b>Xabar tarqatildi!</b>\n\n"
                f"Yetib bordi: <b>{sent} / {len(user_ids)}</b> ta foydalanuvchiga.\n"
                f"❌ Yuborilmagan: <b>{failed} ta</b>."
            ),
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
