"""/health — tizim holati monitoringi (PostAssist V2 — 7-BOSQICH).

Faqat ``system_settings`` ruxsati (RBAC) bo'lgan adminlarga:

* ✅ Database holati + javob vaqti (latency ms);
* ✅ apscheduler holati + pending/failed/dead-letter postlar soni;
* ✅ AI provayderlar holati (OK / DEGRADED / UNCONFIGURED);
* ✅ bot uptime, faol ulanishlar va xatolar statistikasi.

Oddiy foydalanuvchi ``/health`` ni chaqirsa — handler ICHIGA KIRMAYDI
(``@require_permission`` rad javobini yuboradi) — RBAC tekshiruvi
testlar bilan qamrab olingan.
"""

from __future__ import annotations

import logging

from services.rbac_service import (
    PERM_SYSTEM_SETTINGS,
    require_permission,
)
from locales.translations import get_lang

logger = logging.getLogger(__name__)

#: RBAC rad javobi (uz; boshqa tillar uchun umumiy xabar qulay).
HEALTH_DENIED_MESSAGE = "❌ Sizda tizim holatini ko'rish uchun ruxsat yo'q."


@require_permission(PERM_SYSTEM_SETTINGS, message=HEALTH_DENIED_MESSAGE)
async def health_command(update, context) -> None:
    """/health — to'liq tizim holati hisobotini yuboradi (faqat admin)."""
    from services.health_service import format_health_report  # lazy import

    lang = get_lang(context)
    try:
        report = await format_health_report(lang=lang)
    except Exception as e:
        # Health hisoboti o'zi yiqilsa ham foydalanuvchi xavfsiz javob oladi —
        # hech qanday traceback/ichki tafsilot ko'rsatilmaydi.
        logger.error("health: hisobot yaratishda xato: %s", e)
        from locales.translations import get_text
        report = get_text("sys_busy", lang)

    try:
        await update.effective_message.reply_text(report, parse_mode="HTML")
    except Exception as e:
        logger.warning("health: hisobot yuborilmadi: %s", e)


async def admin_health_callback(update, context) -> None:
    """Admin inline tugmasi uchun zaxira (``adm_health``) — hozircha
    dashboardda tugma YO'Q (ixcham layout saqlanadi), lekin callback
    xavfsiz ishlaydi: xuddi shu RBAC tekshiruvi + hisobot."""
    from services.rbac_service import has_permission

    query = getattr(update, "callback_query", None)
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None)
    if not has_permission(user_id, PERM_SYSTEM_SETTINGS):
        if query is not None:
            try:
                await query.answer(HEALTH_DENIED_MESSAGE, show_alert=True)
            except Exception:
                pass
        return
    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
    await health_command(update, context)
