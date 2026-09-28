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
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from handlers.analytics import ANALYTICS_VIEW
from keyboards.inline import get_user_overview_keyboard
from locales.translations import get_lang
from translations import settings_stats_t

logger = logging.getLogger(__name__)

#: Tavsiya turlari (i18n kalitlari bilan bir-bir mos).
ADVICE_NO_CHANNEL = "no_channel"
ADVICE_INSUFFICIENT = "insufficient"
ADVICE_BEST_TIME = "best_time"

#: Kreditlar shu qiymatdan kam/teng bo'lsa — «PRO ga o'tish» tavsiyasi.
LOW_CREDITS_THRESHOLD = 0


def build_advice_line(advice: Optional[dict], lang: str = "uz",
                      scheduled: int = 0) -> str:
    """💡 Bitta ANIQ tavsiya qatori (uz/ru/en) — PURE, DB'siz.

    Args:
        advice: ``{"kind": ..., "time": "19:00 - 21:00"}`` —
            :func:`collect_advice` natijasi. ``None``/bo'sh/unknown →
            bo'sh qator qaytadi (ya'ni eski xulq saqlanadi).
        lang: foydalanuvchi tili (uz/ru/en).
        scheduled: rejalashtirilgan postlar soni — 0 bo'lsa tavsiya
            «birinchi postni joylashtiring» shakliga o'tadi.

    Returns:
        ``"💡 <b>Tavsiya:</b> ..."`` yoki ``""`` (tavsiya kerak emas).
    """
    advice = advice or {}
    kind = str(advice.get("kind") or "").strip()
    window = str(advice.get("time") or "").strip()

    if kind == ADVICE_BEST_TIME and window:
        key = ("ss_my_advice_idle" if int(scheduled or 0) <= 0
               else "ss_my_advice_best_time")
        body = settings_stats_t(key, lang, time=window)
    elif kind == ADVICE_INSUFFICIENT:
        body = settings_stats_t("ss_my_advice_insufficient", lang)
    elif kind == ADVICE_NO_CHANNEL:
        body = settings_stats_t("ss_my_advice_no_channel", lang)
    else:
        return ""

    return f"{settings_stats_t('ss_my_advice_title', lang)} {body}"


async def collect_advice(user_id: int, channels=None) -> dict:
    """Kanal faollik signalidan tavsiya manbasini yig'adi (async, fail-safe).

    Hech qanday xatoda bo'sh dict qaytadi — shunda ekranda tavsiya qatori
    umuman chiqmaydi, lekin asosiy statistika DOIM chiqadi (foydalanuvchi
    hech qachon javobsiz qolmaydi).

    Returns:
        ``{"kind": "best_time", "time": "19:00 - 21:00"}`` yoki
        ``{"kind": "insufficient"}`` / ``{"kind": "no_channel"}`` / ``{}``.
    """
    try:
        if channels is None:
            channels = await db.run_db(db.get_user_channels, user_id)
        rows = list(channels or [])
        if not rows:
            return {"kind": ADVICE_NO_CHANNEL}
        channel_id = str(rows[0][0])

        from services.channels.best_time import get_best_time

        result = await get_best_time(channel_id, user_id=user_id)
        if not result.get("ok") or result.get("insufficient"):
            return {"kind": ADVICE_INSUFFICIENT}
        window = str(result.get("top_window") or "").strip()
        if not window:
            return {"kind": ADVICE_INSUFFICIENT}
        return {"kind": ADVICE_BEST_TIME, "time": window}
    except Exception as exc:  # pragma: no cover — DB/service himoyasi
        logger.debug("Statistika tavsiyasi yig'ilmadi: %s", exc)
        return {}


def build_user_overview_text(stats: dict, credits: int = 0, lang: str = "uz",
                             advice: Optional[dict] = None) -> str:
    """📊 Shaxsiy statistika ekrani matnini tuzadi (uz/ru/en).

    ``stats`` — ``db.get_user_overview_stats`` natijasi
    (``channels`` / ``created_posts`` / ``scheduled_posts``),
    ``credits`` — ``db.get_user_credits`` natijasi (qolgan AI kreditlari),
    ``advice`` — :func:`collect_advice` natijasi (ixtiyoriy).

    Matn FAQAT foydalanuvchining O'Z ko'rsatkichlarini o'z ichiga oladi —
    admin (bot bo'yicha) maydonlari bu yerga HECH QACHON qo'shilmaydi.
    ``None``/bo'sh ma'lumot ham xavfsiz (nollar chiziladi).
    """
    stats = stats or {}
    scheduled = int(stats.get("scheduled_posts", 0) or 0)
    lines = [
        settings_stats_t("ss_my_title", lang),
        settings_stats_t("ss_my_channels", lang, n=int(stats.get("channels", 0) or 0)),
        settings_stats_t("ss_my_created", lang, n=int(stats.get("created_posts", 0) or 0)),
        settings_stats_t("ss_my_scheduled", lang, n=scheduled),
        settings_stats_t("ss_my_credits", lang, n=int(credits or 0)),
    ]

    # 💡 3-BOSQICH: aniq, bajariladigan tavsiya (kuruq raqamlar EMAS).
    # Kredit tugab qolganda — PRO taklifi MA'LUMOTDAN ustun (foydalanuvchiga
    # amaliy qadam kerak).
    if int(credits or 0) <= LOW_CREDITS_THRESHOLD:
        lines.append(
            f"{settings_stats_t('ss_my_advice_title', lang)} "
            f"{settings_stats_t('ss_my_advice_low_credits', lang)}"
        )
    else:
        advice_line = build_advice_line(advice, lang, scheduled)
        if advice_line:
            lines.append(advice_line)

    return "\n".join(lines)


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

    # 💡 3-BOSQICH: kanal faollik signali asosida ANIQ tavsiya.
    advice = await collect_advice(user_id)

    # Kanal bo'yicha analitikaga o'tilganda «◀️ Orqaga» shu ekranga qaytishi
    # uchun belgi qo'yamiz (analytics.py shu bayroqqa qarab yo'naltiradi).
    context.user_data["statistics_overview"] = True
    context.user_data.pop("analytics_channel_id", None)

    await update.message.reply_text(
        build_user_overview_text(stats, credits, lang, advice),
        reply_markup=get_user_overview_keyboard(lang),
        parse_mode="HTML",
    )
    return ANALYTICS_VIEW
