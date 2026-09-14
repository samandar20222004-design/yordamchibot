"""🧭 PostAssist V2 · 4-QADAM — NAVIGATSIYA STACKI (◀️ Orqaga / ❌ Bekor qilish).

STANDART (4-qadam topshirig'i):

  * **Oddiy ko'rish holatida** [◀️ Orqaga] — foydalanuvchini BOSGAN joyidan
    chiqib, ota (parent) menyuga qaytaradi:
      - Kontent yaratish → 🤖 AI Yordamchi → [◀️ Orqaga] → Kontent yaratish
        submenyusi (asosiy menyuga sakrab ketmaydi);
      - Kanallarim → Kanal → [◀️ Orqaga] → Kanallar ro'yxati
        (``ch_back`` / ``channels_list_callback``);
      - Sozlamalar → 🧰 Vositalar → [◀️ Orqaga] → Sozlamalar menyusi
        (``stgs_hub`` / ``settings_menu_callback``).

  * **Jarayon (FSM) ichida** [❌ Bekor qilish] — kontekst TOZALANADI va
    foydalanuvchi O'SHA BO'LIM BOSHIGA qaytadi (admin oqimlarida
    ``adm_cancel`` → dashboard; AI oqimlarida ``ai_close`` → AI Studio
    hub'i; Kontent oqimlarida ``cancel_handler`` → Kontent submenyusi).

  * [🏠 Asosiy menyu] — istalgan joydan asosiy 6 tugmali menyuga qaytaradi
    (``ai_exit_to_menu`` / ``content_creation_back`` / ``studio_close`` ...).

Modul mas'uliyati — foydalanuvchi qaysi bo'limda ekanini (``nav_section``)
eslab qolish va «bo'lim boshiga» qaytish ekranini chizish. Bu KICHIK,
muholatsiz (best-effort) yordamchi: ``render_section_start_message`` xato
bo'lsa ``False`` qaytaradi — chaqiruvchi asosiy menyuga fallback qiladi
(fail-safe: foydalanuvchi hech qachon javobsiz qolmaydi).

Bo'lim kalitlari (``NAV_SECTIONS``) — yagona manba; handlerlar va testlar
shu konstantalarni ishlatadi. ``clear_fsm_data`` ``user_data`` ni tozalashi
nav_section'ni ham o'chiradi — shu sababli avval bo'lim O'QILADI, keyin FSM
tozalanadi va kerak bo'lsa bo'lim QAYTA yoziladi (``keep_section_after_clear``).
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bo'lim kalitlari (yagona manba — handler + test shu konstantalarni ishlatadi)
# ---------------------------------------------------------------------------
SECTION_MAIN = "main"            # 🏠 Asosiy 6 tugmali menyu
SECTION_CONTENT = "content"      # 🧩 Kontent yaratish submenyusi
SECTION_AI_STUDIO = "ai_studio"  # 🤖 AI Yordamchi (AI Studio hub)
SECTION_CHANNELS = "channels"    # 📢 Kanallarim ro'yxati
SECTION_SETTINGS = "settings"    # ⚙️ Sozlamalar menyusi
SECTION_TOOLS = "tools"          # 🧰 Vositalar submenyusi
SECTION_ADMIN = "admin"          # 👑 Admin dashboard

#: Barcha ma'lum bo'lim kalitlari (noto'g'ri qiymat himoyasi uchun).
NAV_SECTIONS = (
    SECTION_MAIN, SECTION_CONTENT, SECTION_AI_STUDIO, SECTION_CHANNELS,
    SECTION_SETTINGS, SECTION_TOOLS, SECTION_ADMIN,
)

#: ``user_data`` kaliti — joriy bo'lim (navigatsiya stackining yagona yozuvi).
NAV_KEY = "nav_section"


def remember_section(context, section: str) -> None:
    """Foydalanuvchi endi shu bo'limda — cancel/orqaga shu yerga qaytadi."""
    if context is None:
        return
    try:
        ud = getattr(context, "user_data", None)
        if ud is None:
            return
        ud[NAV_KEY] = section if section in NAV_SECTIONS else SECTION_MAIN
    except Exception:  # pragma: no cover — context har doim dict'ga o'xshaydi
        logger.debug("nav_section yozilmadi: %r", section)


def current_section(context) -> str:
    """Joriy bo'lim kaliti (yozilmagan/noto'g'ri bo'lsa ``SECTION_MAIN``)."""
    try:
        ud = getattr(context, "user_data", None)
        if ud is None:
            return SECTION_MAIN
        section = ud.get(NAV_KEY)
        return section if section in NAV_SECTIONS else SECTION_MAIN
    except Exception:  # pragma: no cover
        return SECTION_MAIN


def clear_section(context) -> None:
    """Bo'lim yozuvini tozalaydi (asosiy menyuga qaytganda)."""
    if context is None:
        return
    try:
        ud = getattr(context, "user_data", None)
        if ud is not None:
            ud.pop(NAV_KEY, None)
    except Exception:  # pragma: no cover
        pass


def keep_section_after_clear(context) -> str:
    """``clear_fsm_data`` (user_data.clear()) dan keyin bo'limni tiklaydi.

    ``cancel_handler`` FSM tozalashidan OLDIN bo'limni o'qib, keyin shu
    funksiya orqali qayta yozadi — foydalanuvchi bekor qilganda ham
    navigatsiya stacki yo'qolmaydi.
    """
    section = current_section(context)
    remember_section(context, section)
    return section


async def render_section_start_message(msg, context, user_id: int,
                                       is_admin: bool, lang: str) -> bool:
    """Bo'lim BOSHIGA qaytish ekranini YANGI xabar sifatida yuboradi.

    Inline (edit) bo'limlar (kanal paneli, admin dashboard ...) o'z
    handlerlarida qayta chizilgani uchun bu yerda faqat XABAR asosidagi
    bo'lim boshlanishi qo'llab-quvvatlanadi. Xato bo'lsa ``False`` —
    chaqiruvchi asosiy menyuga fallback qiladi (fail-safe).

    Args:
        msg: ``update.message`` — javob shu chatga yuboriladi.
        context: PTB context (``user_data`` orqali bo'lim aniqlanadi).
        user_id: foydalanuvchi ID'si.
        is_admin: admin klaviatura qatori uchun (kerak bo'lgan bo'limlarda).
        lang: foydalanuvchi tili (uz/ru/en).
    """
    section = current_section(context)
    try:
        if section == SECTION_CONTENT:
            # 🧩 Kontent yaratish — bo'lim boshiga qaytish standarti.
            from keyboards.default import get_content_creation_keyboard
            from translations import content_menu_t

            await msg.reply_text(
                content_menu_t("cm_menu_intro", lang),
                reply_markup=get_content_creation_keyboard(lang),
                parse_mode="HTML",
            )
            return True

        if section == SECTION_AI_STUDIO:
            # 🤖 AI Yordamchi — bo'lim boshiasi AI Studio hub'i.
            from keyboards.inline import get_ai_studio_keyboard

            from handlers.ai_assistant import _studio_menu_text
            await msg.reply_text(
                await _studio_menu_text(user_id, lang),
                reply_markup=get_ai_studio_keyboard(lang),
                parse_mode="HTML",
            )
            return True

        if section == SECTION_CHANNELS:
            # 📢 Kanallarim — bo'lim boshiasi kanallar ro'yxati.
            from handlers.channels import _send_channels_list
            await _send_channels_list(msg, user_id, lang)
            return True

        if section == SECTION_TOOLS:
            # 🧰 Vositalar — bo'lim boshiasi vositalar submenyusi
            # (Konvertor + Post Enhancer + [◀️ Orqaga → Sozlamalar]).
            from handlers.tools import build_tools_keyboard, build_tools_text
            await msg.reply_text(
                build_tools_text(lang),
                reply_markup=build_tools_keyboard(lang),
                parse_mode="HTML",
            )
            return True

        if section == SECTION_SETTINGS:
            # ⚙️ Sozlamalar — bo'lim boshiasi sozlamalar hub'i: profil
            # kartasi + yagona 8 guruhli menyu.
            from handlers.settings import render_settings_hub
            await render_settings_hub(msg, context, user_id, lang, is_admin)
            return True

        if section == SECTION_ADMIN:
            # 👑 Admin — bo'lim boshiasi YAGONA dashboard (faqat admin!).
            from handlers.admin import _build_dashboard_text, is_admin as _is_admin
            from keyboards.inline import get_admin_dashboard_keyboard
            import database as db

            if not _is_admin(user_id):
                return False
            stats = await db.run_db(db.get_admin_dashboard_stats)
            await msg.reply_text(
                _build_dashboard_text(stats),
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
            return True

        return False
    except Exception as e:  # pragma: no cover — fail-safe fallback
        logger.debug("Bo'lim boshiga qaytib bo'lmadi (%s): %s", section, e)
        return False
