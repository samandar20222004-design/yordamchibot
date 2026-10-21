"""🎁 Admin: promo-kod ro'yxati/tafsiloti/o'chirish-yoqish va admin buyruqlari ro'yxati.

``/promos`` — barcha kodlar (ishlatilgan / qolgan / holat); ``/promo KOD`` — tafsilot va kim ishlatgani;
``/promo_off KOD`` / ``/promo_on KOD``; ``/admin_help`` — admin buyruqlari. Hammasi RBAC bilan (promo: ``manage_promos``).
Panel tugmalari (``adm_promos``, ``adm_cmds``) ``handlers/admin.py`` dagi dashboard callback'i orqali shu matnlarni chiqaradi.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import database as db
from locales.translations import get_lang
from services.promo_service import PromoService
from services.rbac_service import PERM_MANAGE_PROMOS, has_permission, is_admin
from translations import admin_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

LIST_LIMIT = 15
_ICONS = {"active": "🟢", "used_up": "🔴", "expired": "⏳", "disabled": "⚪️"}


def _date(value) -> str:
    try:
        return value.strftime("%d.%m.%Y")
    except Exception:  # noqa: BLE001
        return "—"


def _max(item, lang) -> str:
    return admin_t("pr_unlimited", lang) if item["max_uses"] is None else str(item["max_uses"])


def _left(item, lang) -> str:
    return admin_t("pr_unlimited", lang) if item["remaining_uses"] is None else str(item["remaining_uses"])


def build_list_text(items: list, totals: dict, lang: str) -> str:
    lines = [admin_t("pr_list_title", lang)]
    if not items:
        lines += ["", admin_t("pr_empty", lang)]
        return "\n".join(lines)
    unl = totals.get("unlimited") or 0
    lines.append(admin_t(
        "pr_totals", lang, total=totals["total"], active=totals["active"], used_up=totals["used_up"],
        expired=totals["expired"], disabled=totals["disabled"], redemptions=totals["redemptions"],
        remaining=totals["remaining_uses"], unl=admin_t("pr_unl_suffix", lang, n=unl) if unl else "",
    ))
    lines.append("")
    for it in items[:LIST_LIMIT]:
        exp = admin_t("pr_exp", lang, date=_date(it["expires_at"])) if it["expires_at"] else ""
        lines.append(admin_t(
            "pr_row", lang, icon=_ICONS.get(it["status"], "•"), code=html_escape(it["code"]),
            plan=html_escape(str(it["plan_type"]).upper()), days=it["duration_days"],
            used=it["current_uses"], max=_max(it, lang), left=_left(it, lang), exp=exp,
        ))
    if len(items) > LIST_LIMIT:
        lines.append(admin_t("pr_more", lang, n=len(items) - LIST_LIMIT))
    lines += ["", admin_t("pr_hint", lang)]
    return "\n".join(lines)


async def load_list_text(lang: str) -> str:
    items = await db.run_db(PromoService.list_promos, 200)
    totals = await db.run_db(PromoService.promo_totals)
    return build_list_text(items, totals, lang)


def build_detail_text(stats: dict, redeemers: list, lang: str) -> str:
    st = stats["status"]
    text = admin_t(
        "pr_detail", lang, code=html_escape(stats["code"]), status=f"{_ICONS.get(st, '')} {admin_t('pr_st_' + st, lang)}",
        plan=html_escape(str(stats["plan_type"]).upper()), days=stats["duration_days"], used=stats["current_uses"],
        max=_max(stats, lang), left=_left(stats, lang),
        exp=_date(stats["expires_at"]) if stats["expires_at"] else admin_t("pr_no_expiry", lang),
        created=_date(stats["created_at"]),
    )
    if not redeemers:
        return text + "\n\n" + admin_t("pr_no_redeemers", lang)
    rows = [admin_t("pr_redeemer_row", lang, user=r["user_id"], when=_date(r["redeemed_at"])) for r in redeemers]
    return text + "\n\n" + admin_t("pr_redeemers", lang) + "\n" + "\n".join(rows)


def list_keyboard(lang: str) -> InlineKeyboardMarkup:
    from keyboards.nav import nav_button

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(admin_t("pr_btn_refresh", lang), callback_data="adm_promos")],
        [nav_button("back", "adm_promo"), nav_button("close")],
    ])


def commands_text(lang: str) -> str:
    return admin_t("cmd_title", lang) + "\n\n" + admin_t("cmd_body", lang)


async def _find(code: str) -> dict | None:
    items = await db.run_db(PromoService.list_promos, 200)
    from services.promo_service import normalize_promo_input

    wanted = normalize_promo_input(code)
    return next((it for it in items if it["code"] == wanted), None)


def _allowed(user_id) -> bool:
    return bool(user_id) and has_permission(user_id, PERM_MANAGE_PROMOS)


async def promos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(await load_list_text(get_lang(context)), parse_mode="HTML")


async def promo_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    lang = get_lang(context)
    args = context.args or []
    if not args:
        await update.message.reply_text(admin_t("pr_usage_detail", lang))
        return
    item = await _find(args[0])
    if item is None:
        await update.message.reply_text(admin_t("pr_not_found", lang))
        return
    redeemers = await db.run_db(PromoService.recent_redemptions, item["code"], 10)
    await update.message.reply_text(build_detail_text(item, redeemers, lang), parse_mode="HTML")


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, active: bool):
    user_id = update.effective_user.id
    if not _allowed(user_id):
        return
    lang = get_lang(context)
    args = context.args or []
    if not args:
        await update.message.reply_text(admin_t("pr_usage_toggle", lang))
        return
    item = await _find(args[0])
    if item is None:
        await update.message.reply_text(admin_t("pr_not_found", lang))
        return
    if not await db.run_db(PromoService.set_promo_active, item["code"], active, user_id):
        await update.message.reply_text(admin_t("pr_not_found", lang))
        return
    await update.message.reply_text(admin_t("pr_set_on" if active else "pr_set_off", lang, code=html_escape(item["code"])),
                                    parse_mode="HTML")


async def promo_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, False)


async def promo_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, True)


async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(commands_text(get_lang(context)), parse_mode="HTML")
