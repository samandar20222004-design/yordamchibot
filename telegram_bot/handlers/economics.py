# -*- coding: utf-8 -*-
"""💰 SPRINT 4 — ``/economics``: UNIT ECONOMICS VA PRO TARIF RENTABELLIGI.

Admin buyrug'i bitta ekranda javob beradi:
  * davr bo'yicha AI so'rovlar, tokenlar va umumiy xarajat (USD + so'm);
  * O'RTACHA bitta faol foydalanuvchi sarfi;
  * PRO tarif narxi (19 000 so'm — ``PAYMENT_PRICE_1M_UZS``) bilan
    solishtirib marja, rentabellik xulosasi va zararsizlik nuqtasi;
  * eng ko'p sarflagan foydalanuvchilar (jarayon xotirasi kesimida).

Ma'lumot manbai: ``ai_usage_events`` (baza) + jarayon xotirasidagi ledger
(``services.ai.cost_tracker``). Jadvalda yo'q model narxi "noma'lum" deb
OCHIQ ko'rsatiladi — soxta raqam chop etilmaydi.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from locales.translations import get_lang
from services.ai import cost_tracker
from translations import admin_t
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

PERIOD_MONTHLY = "monthly"
PERIOD_DAILY = "daily"

#: Xulosa → i18n kaliti (verdict maydonlari).
_VERDICT_KEYS = {
    cost_tracker.VERDICT_HEALTHY: "eco_verdict_healthy",
    cost_tracker.VERDICT_WATCH: "eco_verdict_watch",
    cost_tracker.VERDICT_THIN: "eco_verdict_thin",
    cost_tracker.VERDICT_LOSS: "eco_verdict_loss",
}


def _is_admin(user_id) -> bool:
    from handlers.admin import is_admin

    return bool(is_admin(user_id))


def fmt_uzs(value) -> str:
    """``19000`` → ``"19 000"`` (so'm; faqat butun qism ko'rsatiladi)."""
    try:
        number = int(round(float(value or 0)))
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}".replace(",", " ")


def fmt_usd(value, digits: int = 4) -> str:
    """Xarajatni dollar ko'rinishida (kichik summada ko'proq xona)."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        number = 0.0
    if number and number < 0.01:
        digits = max(digits, 6)
    return f"{number:.{digits}f}"


def build_economics_text(summary: dict, *, lang: str = "uz",
                         top_users: list | None = None) -> str:
    """``/economics`` ekranini chizadi (pure — test uchun qulay)."""
    summary = summary or {}
    period_key = ("eco_period_monthly" if summary.get("period") == PERIOD_MONTHLY
                  else "eco_period_daily")
    lines = [
        admin_t("eco_title", lang),
        "━━━━━━━━━━━━━━━",
        admin_t("eco_line_period", lang, period=admin_t(period_key, lang)),
        admin_t("eco_line_requests", lang,
                requests=int(summary.get("requests") or 0),
                tokens=int(summary.get("total_tokens") or 0)),
        admin_t("eco_line_cost", lang,
                usd=fmt_usd(summary.get("total_cost_usd")),
                uzs=fmt_uzs(summary.get("total_cost_uzs"))),
        admin_t("eco_line_avg", lang,
                usd=fmt_usd(summary.get("avg_cost_usd")),
                uzs=fmt_uzs(summary.get("avg_cost_uzs")),
                users=int(summary.get("active_users") or 0)),
        "━━━━━━━━━━━━━━━",
        admin_t("eco_line_pro", lang,
                uzs=fmt_uzs(summary.get("pro_price_uzs")),
                usd=fmt_usd(summary.get("pro_price_usd"), 2)),
        admin_t("eco_line_margin", lang,
                uzs=fmt_uzs(summary.get("margin_uzs")),
                percent=f"{float(summary.get('margin_rate') or 0.0) * 100:.1f}"),
    ]
    verdict_key = _VERDICT_KEYS.get(str(summary.get("verdict") or ""),
                                    "eco_verdict_watch")
    lines.append(admin_t("eco_line_verdict", lang,
                         verdict=admin_t(verdict_key, lang),
                         share=f"{float(summary.get('cost_share') or 0.0) * 100:.1f}"))
    users_per_payment = summary.get("users_per_payment")
    if users_per_payment:
        lines.append(admin_t("eco_line_break_even", lang,
                             users=fmt_uzs(users_per_payment)))
    if int(summary.get("unpriced_requests") or 0) > 0:
        lines.append(admin_t("eco_note_unpriced", lang,
                             count=int(summary.get("unpriced_requests") or 0)))
    lines.append(admin_t("eco_note_source", lang,
                         source=str(summary.get("source") or "memory"),
                         rate=fmt_uzs(summary.get("rate_usd_uzs"))))
    if top_users:
        rows = [admin_t("eco_top_title", lang)]
        for row in top_users[:5]:
            rows.append(admin_t("eco_top_row", lang,
                                user_id=row.get("user_id"),
                                uzs=fmt_uzs(row.get("cost_uzs")),
                                requests=int(row.get("requests") or 0)))
        lines.append("\n".join(rows))
    return "\n".join(lines)


async def economics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``/economics [daily]`` — AI unit economics xulosasi (faqat admin)."""
    user = update.effective_user
    if not _is_admin(getattr(user, "id", None)):
        return
    lang = get_lang(context)
    args = [str(a or "").strip().lower() for a in (getattr(context, "args", None) or [])]
    period = PERIOD_DAILY if args and args[0] in ("daily", "kunlik", "day") \
        else PERIOD_MONTHLY
    try:
        summary = await db.run_db(cost_tracker.economics_summary,
                                  period=period, db_module=db)
        top_users = cost_tracker.default_ledger().top_users(period=period, limit=5)
        text = build_economics_text(summary, lang=lang, top_users=top_users)
    except Exception as exc:  # noqa: BLE001 — buyruq botni yiqitmaydi
        log_silent_failure("handlers.economics:economics_command", exc,
                           user_id=getattr(user, "id", None), lang=lang)
        text = admin_t("eco_unavailable", lang)
    try:
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.economics:economics_command:reply", exc,
                           user_id=getattr(user, "id", None), lang=lang)


__all__ = [
    "PERIOD_DAILY",
    "PERIOD_MONTHLY",
    "build_economics_text",
    "economics_command",
    "fmt_usd",
    "fmt_uzs",
]
