"""📊 SHAXSIY STATISTIKA — asosiy menyudagi «📊 Statistika» tugmasi ekrani.

Nima uchun alohida modul?
-------------------------
Avval asosiy menyudagi «📊 Statistika» tugmasi ``handlers/__init__.py`` dagi
``statistics_button`` dispatcher'i orqali IKKI xil ekranga ulangan edi:

* ``ADMIN_IDS`` a'zosi → ``handlers.admin.show_statistics`` (bot bo'yicha
  «To'liq Statistika»: Jami foydalanuvchilar / Homiy kanallar / Bekor
  qilingan postlar ...);
* oddiy foydalanuvchi → ``handlers.analytics.start_analytics``.

Ya'ni ADMIN asosiy menyudan «📊 Statistika» bosganda o'z shaxsiy
hisoboti o'rniga ADMIN PANEL statistikasini ko'rardi. Endi bu qat'iy
ajratildi:

* asosiy menyudagi «📊 Statistika» (uz/ru/en) — FAQAT shu modul,
  ``show_user_statistics``; foydalanuvchi admin bo'ladimi, oddiy
  foydalanuvchimi — farqi YO'Q;
* admin (bot bo'yicha) statistikasi — FAQAT ``⚙️ Admin Panel`` →
  ``📊 To'liq statistika`` (``adm_stats`` / ``handlers.admin.show_statistics``)
  ichida. Tashqaridagi hech bir oddiy tugma uni ochmaydi.

Ekran (speks):

    📊 Sizning statistikangiz:
     📢 Ulangan kanallaringiz: X ta
     📝 Yaratilgan postlaringiz: X ta
     📅 Rejalashtirilgan postlar: X ta
     💎 Qolgan AI kreditlaringiz: X ta

Amallar: ``[📈 Kanal bo'yicha batafsil]`` ``[◀️ Orqaga]``.

«📈 Kanal bo'yicha batafsil» mavjud kanal analitikasini
(``handlers.analytics`` — ``an_detail`` → kanal tanlash → dashboard)
ochadi; undagi ``[◀️ Orqaga]`` (``an_overview``) esa shu shaxsiy
ekranga qaytaradi.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from handlers.analytics import ANALYTICS_VIEW
from keyboards.inline import get_user_overview_keyboard
from locales.translations import get_lang
from translations import settings_stats_t

logger = logging.getLogger(__name__)


def build_user_overview_text(stats: dict, credits: int = 0, lang: str = "uz") -> str:
    """📊 Shaxsiy statistika ekrani matnini tuzadi (uz/ru/en).

    ``stats`` — ``db.get_user_overview_stats`` natijasi
    (``channels`` / ``created_posts`` / ``scheduled_posts``),
    ``credits`` — ``db.get_user_credits`` natijasi (qolgan AI kreditlari).

    Matn FAQAT foydalanuvchining O'Z ko'rsatkichlarini o'z ichiga oladi —
    admin (bot bo'yicha) maydonlari bu yerga HECH QACHON qo'shilmaydi.
    ``None``/bo'sh ma'lumot ham xavfsiz (nollar chiziladi).
    """
    stats = stats or {}
    return "\n".join([
        settings_stats_t("ss_my_title", lang),
        settings_stats_t("ss_my_channels", lang, n=int(stats.get("channels", 0) or 0)),
        settings_stats_t("ss_my_created", lang, n=int(stats.get("created_posts", 0) or 0)),
        settings_stats_t("ss_my_scheduled", lang, n=int(stats.get("scheduled_posts", 0) or 0)),
        settings_stats_t("ss_my_credits", lang, n=int(credits or 0)),
    ])


async def show_user_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 Shaxsiy statistika — asosiy menyu «📊 Statistika» tugmasi handleri.

    Admin/oddiy foydalanuvchi farqi YO'Q: ikkalasi ham o'z shaxsiy
    hisobotini ko'radi. DB xatosida ham ekran ochiladi (nollar bilan) —
    foydalanuvchi hech qachon javobsiz qolmaydi.
    """
    user_id = update.effective_user.id
    lang = get_lang(context)

    stats = await db.run_db(db.get_user_overview_stats, user_id)
    try:
        credits = await db.run_db(db.get_user_credits, user_id)
    except Exception as exc:  # pragma: no cover - DB himoyasi
        logger.debug(f"Shaxsiy statistika: kreditlar o'qilmadi ({exc})")
        credits = 0

    # Kanal bo'yicha analitikaga o'tilganda «◀️ Orqaga» shu ekranga qaytishi
    # uchun belgi qo'yamiz (analytics.py shu bayroqqa qarab yo'naltiradi).
    context.user_data["statistics_overview"] = True
    context.user_data.pop("analytics_channel_id", None)

    await update.message.reply_text(
        build_user_overview_text(stats, credits, lang),
        reply_markup=get_user_overview_keyboard(lang),
        parse_mode="HTML",
    )
    return ANALYTICS_VIEW
