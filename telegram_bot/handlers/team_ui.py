"""👥 Jamoa va rol — bot ekranlari (Sozlamalar → «Jamoa va rol», ``/team``) va taklifni qabul qilish (``/start team_<token>``).

Egasi: yordamchi taklif qiladi (kanal + rol → bir martalik havola), a'zolarni boshqaradi. Yordamchi: ish joylarini ko'radi,
Mini App'da ishlaydi. Hamma: «Men kimman?» rejimi. Qoidalar va xavfsizlik — ``services/team_invites.py``
(ULTRA: egasi + 2 yordamchi; PRO/FREE: bitta odam). Callback'lar ``tm_*``; hech qaysi callback ID'ga ishonmaydi:
egalik serverda ``channels.user_id`` / ``channel_members`` orqali tekshiriladi.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import database as db
from miniapp_api.menu import miniapp_button
from services import team_invites as TI
from translations.team_ui import team_t
from utils.helpers import html_escape
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

PRESET_BUTTONS = (("full", "tm_btn_full"), ("editor", "tm_btn_editor"), ("scheduler", "tm_btn_scheduler"),
                  ("analyst", "tm_btn_analyst"), ("view", "tm_btn_view"))
_JOIN_ERRORS = {"invalid": "tm_join_invalid", "used": "tm_join_used", "expired": "tm_join_expired", "revoked": "tm_join_revoked",
                "self": "tm_join_self", "no_team": "tm_join_no_team", "seats_full": "tm_join_seats_full", "failed": "tm_err_generic"}


def perms_text(perms, lang: str) -> str:
    """Ruxsatlar qisqa matni: «hammasi» / «faqat ko'rish» / nomlar ro'yxati."""
    perms = list(perms or [])
    if not perms:
        return team_t("tm_perms_viewonly", lang)
    if set(perms) >= set(TI.PERMS):
        return team_t("tm_perms_all", lang)
    return ", ".join(team_t(f"tm_perm_{p}", lang) for p in perms)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _back(lang: str, to: str = "tm_home") -> list:
    return [_btn(team_t("tm_btn_back", lang), to)]


async def _lang(context, user_id: int) -> str:
    try:
        from handlers.start import ensure_user_lang

        return await ensure_user_lang(context, user_id)
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.team_ui:_lang", exc)
        return "uz"


async def _show(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as exc:  # noqa: BLE001 — «message is not modified» va h.k.
            log_silent_failure("handlers.team_ui:_show", exc)
            try:
                await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
            except Exception as exc2:  # noqa: BLE001
                log_silent_failure("handlers.team_ui:_show:reply", exc2)
            return
    await update.effective_message.reply_text(text, reply_markup=markup, parse_mode="HTML")


# ------------------------------------------------------------------ bosh ekran
async def build_home(user_id: int, lang: str):
    from config import ULTRA_TEAM_SEATS

    team = await db.run_db(TI.list_team, user_id)
    workspaces = await db.run_db(TI.workspaces_for, user_id)
    mode = await db.run_db(TI.get_mode, user_id)
    seats = team["seats"]
    lines = [team_t("tm_title", lang), ""]
    lines.append(team_t({"owner": "tm_role_owner", "helper": "tm_role_helper"}.get(mode, "tm_role_none"), lang))
    lines.append("")
    if seats["limit"] > 0:
        pending = team_t("tm_seats_pending", lang, n=seats["pending"]) if seats["pending"] else ""
        lines.append(team_t("tm_seats", lang, used=seats["used"], limit=seats["limit"], pending=pending, total=seats["limit"] + 1))
    else:
        lines.append(team_t("tm_no_team", lang, limit=ULTRA_TEAM_SEATS, total=ULTRA_TEAM_SEATS + 1))
    if workspaces:
        lines += ["", team_t("tm_ws_head", lang)]
        for ws in workspaces:
            owner = html_escape(ws["owner_name"] or str(ws["owner_id"]))
            if ws["suspended"]:
                lines.append(team_t("tm_ws_row_off", lang, owner=owner))
            else:
                chs = ", ".join(f"{html_escape(c['title'] or c['channel_id'])} ({perms_text(c['perms'], lang)})" for c in ws["channels"])
                lines.append(team_t("tm_ws_row", lang, owner=owner, chs=chs))
    rows = [[_btn(team_t("tm_btn_role", lang), "tm_mode")]]
    if seats["limit"] > 0:
        rows.append([_btn(team_t("tm_btn_invite", lang), "tm_inv"), _btn(team_t("tm_btn_members", lang), "tm_mem")])
    else:
        rows.append([_btn(team_t("tm_btn_ultra", lang), "sub_open")])
    if workspaces:
        rows.append([_btn(team_t("tm_btn_ws", lang), "tm_ws")])
    rows.append(_back(lang, "stgs_hub"))
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    lang = await _lang(context, user.id)
    text, markup = await build_home(user.id, lang)
    await _show(update, text, markup)


# ------------------------------------------------------------------ callback'lar
async def _member_screen(update: Update, user_id: int, lang: str, action: str, ch_id: str, member: int):
    """A'zo ekrani (ruxsat katakchalari) va olib tashlash tasdig'i."""
    team = await db.run_db(TI.list_team, user_id)
    ch = next((c for c in team["channels"] if c["channel_id"] == ch_id), None)
    m = next((x for x in (ch or {}).get("members", []) if x["user_id"] == member), None)
    if ch is None or m is None:
        return await _show(update, team_t("tm_err_generic", lang), InlineKeyboardMarkup([_back(lang, "tm_mem")]))
    title = html_escape(ch["title"] or ch_id)
    if action == "tm_md":
        markup = InlineKeyboardMarkup([[_btn(team_t("tm_btn_yes", lang), f"tm_mdy:{ch_id}:{member}")], _back(lang, f"tm_mm:{ch_id}:{member}")])
        return await _show(update, team_t("tm_remove_ask", lang, uid=member, title=title), markup)
    if action == "tm_mdy":
        await db.run_db(TI.remove_member, user_id, ch_id, member)
        return await _show(update, team_t("tm_member_removed", lang), InlineKeyboardMarkup([_back(lang, "tm_mem")]))
    rows = [[_btn(("✅ " if p in m["perms"] else "⬜ ") + team_t(f"tm_perm_{p}", lang), f"tm_pt:{ch_id}:{member}:{p}")] for p in TI.PERMS]
    rows.append([_btn(team_t("tm_btn_remove", lang), f"tm_md:{ch_id}:{member}")])
    rows.append(_back(lang, "tm_mem"))
    text = team_t("tm_member_title", lang, uid=member, name=html_escape(m["name"] or ""), title=title, role=perms_text(m["perms"], lang))
    return await _show(update, text + "\n\n" + team_t("tm_perms_note", lang), InlineKeyboardMarkup(rows))


async def team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    try:
        await query.answer()
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.team_ui:answer", exc)
    user_id = query.from_user.id
    lang = await _lang(context, user_id)
    parts = (query.data or "").split(":")
    action = "tm_home" if parts[0] == "stgs_team" else parts[0]

    if action == "tm_home":
        text, markup = await build_home(user_id, lang)
        return await _show(update, text, markup)

    if action == "tm_mode":
        markup = InlineKeyboardMarkup([[_btn(team_t("tm_btn_owner", lang), "tm_set:owner"), _btn(team_t("tm_btn_helper", lang), "tm_set:helper")],
                                       _back(lang)])
        return await _show(update, team_t("tm_mode_title", lang), markup)

    if action == "tm_set" and len(parts) == 2 and parts[1] in TI.MODES:
        ok = await db.run_db(TI.set_mode, user_id, parts[1])
        key = "tm_mode_owner_ok" if parts[1] == "owner" else "tm_mode_helper_ok"
        markup = InlineKeyboardMarkup([_back(lang)])
        return await _show(update, team_t(key if ok else "tm_err_generic", lang), markup)

    if action == "tm_inv":
        team = await db.run_db(TI.list_team, user_id)
        if team["seats"]["limit"] <= 0:
            return await _show(update, team_t("tm_err_no_team", lang), InlineKeyboardMarkup([[_btn(team_t("tm_btn_ultra", lang), "sub_open")], _back(lang)]))
        if not team["channels"]:
            return await _show(update, team_t("tm_inv_no_channels", lang), InlineKeyboardMarkup([_back(lang)]))
        rows = [[_btn((c["title"] or c["channel_id"])[:30], f"tm_ic:{c['channel_id']}")] for c in team["channels"][:10]]
        rows.append(_back(lang))
        return await _show(update, team_t("tm_inv_pick_channel", lang), InlineKeyboardMarkup(rows))

    if action == "tm_ic" and len(parts) == 2:
        team = await db.run_db(TI.list_team, user_id)
        ch = next((c for c in team["channels"] if c["channel_id"] == parts[1]), None)
        if ch is None:
            return await _show(update, team_t("tm_err_generic", lang), InlineKeyboardMarkup([_back(lang)]))
        rows = [[_btn(team_t(key, lang), f"tm_ir:{ch['channel_id']}:{preset}")] for preset, key in PRESET_BUTTONS]
        rows.append(_back(lang, "tm_inv"))
        text = team_t("tm_inv_pick_role", lang, title=html_escape(ch["title"] or ch["channel_id"]), help=team_t("tm_roles_help", lang))
        return await _show(update, text, InlineKeyboardMarkup(rows))

    if action == "tm_ir" and len(parts) == 3 and parts[2] in dict(PRESET_BUTTONS):
        invite_perms = [] if parts[2] == "view" else parts[2]
        res = await db.run_db(TI.create_invite, user_id, [parts[1]], invite_perms)
        if not res.get("ok"):
            key = {"no_team": "tm_err_no_team", "seats_full": "tm_err_seats_full", "too_many_pending": "tm_err_seats_full"}.get(res.get("error"), "tm_err_generic")
            return await _show(update, team_t(key, lang), InlineKeyboardMarkup([_back(lang)]))
        username = getattr(await context.bot.get_me(), "username", None) if hasattr(context.bot, "get_me") else None
        if not username:
            return await _show(update, team_t("tm_inv_no_username", lang), InlineKeyboardMarkup([_back(lang)]))
        link = f"https://t.me/{username}?start=team_{res['token']}"
        team = await db.run_db(TI.list_team, user_id)
        title = next((c["title"] for c in team["channels"] if c["channel_id"] == parts[1]), parts[1])
        from urllib.parse import quote

        share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(team_t('tm_share_text', lang))}"
        shown = [] if parts[2] == "view" else list(TI.PRESETS[parts[2]])
        text = team_t("tm_inv_ready", lang, title=html_escape(title or ""), role=perms_text(shown, lang), days=TI.INVITE_TTL_DAYS, link=link)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(team_t("tm_btn_share", lang), url=share)],
                                       [_btn(team_t("tm_btn_revoke", lang), f"tm_rv:{res['id']}")], _back(lang)])
        return await _show(update, text, markup)

    if action == "tm_rv" and len(parts) == 2 and parts[1].isdigit():
        await db.run_db(TI.revoke_invite, user_id, int(parts[1]))
        return await _show(update, team_t("tm_invite_revoked", lang), InlineKeyboardMarkup([_back(lang)]))

    if action == "tm_mem":
        team = await db.run_db(TI.list_team, user_id)
        lines = [team_t("tm_members_head", lang)]
        rows = []
        any_row = False
        for ch in team["channels"]:
            if not ch["members"] and not ch["invites"]:
                continue
            lines.append(team_t("tm_members_ch", lang, title=html_escape(ch["title"] or ch["channel_id"])))
            for m in ch["members"]:
                any_row = True
                lines.append(team_t("tm_member_row", lang, uid=m["user_id"], name=html_escape(m["name"] or m["username"] or ""),
                                    role=perms_text(m["perms"], lang), off="" if m["active"] else team_t("tm_member_off", lang)))
                rows.append([_btn(f"{(m['name'] or m['user_id'])!s:.14} · {(ch['title'] or '')[:10]}", f"tm_mm:{ch['channel_id']}:{m['user_id']}")])
            for i in ch["invites"]:
                any_row = True
                lines.append(team_t("tm_invite_row", lang, role=perms_text(i["perms"], lang)))
                rows.append([_btn(f"❌ {team_t('tm_btn_revoke', lang)}", f"tm_rv:{i['id']}")])
        if not any_row:
            lines += ["", team_t("tm_members_empty", lang)]
        rows.append(_back(lang))
        return await _show(update, "\n".join(lines), InlineKeyboardMarkup(rows[:30]))

    if action in ("tm_mm", "tm_md", "tm_mdy") and len(parts) == 3 and parts[2].isdigit():
        return await _member_screen(update, user_id, lang, action, parts[1], int(parts[2]))

    if action == "tm_pt" and len(parts) == 4 and parts[2].isdigit() and parts[3] in TI.PERMS:
        team = await db.run_db(TI.list_team, user_id)
        ch = next((c for c in team["channels"] if c["channel_id"] == parts[1]), None)
        m = next((x for x in (ch or {}).get("members", []) if x["user_id"] == int(parts[2])), None)
        if m is not None:
            now = [p for p in TI.PERMS if (p in m["perms"]) != (p == parts[3])]  # shu ruxsatni almashtiramiz
            await db.run_db(TI.set_member_perms, user_id, parts[1], int(parts[2]), now)
        return await _member_screen(update, user_id, lang, "tm_mm", parts[1], int(parts[2]))

    if action == "tm_ws":
        workspaces = await db.run_db(TI.workspaces_for, user_id)
        if not workspaces:
            return await _show(update, team_t("tm_ws_none", lang), InlineKeyboardMarkup([_back(lang)]))
        lines = [team_t("tm_ws_head", lang)]
        rows = []
        for ws in workspaces:
            owner = html_escape(ws["owner_name"] or str(ws["owner_id"]))
            if ws["suspended"]:
                lines.append(team_t("tm_ws_row_off", lang, owner=owner))
            else:
                chs = ", ".join(f"{html_escape(c['title'] or c['channel_id'])} ({perms_text(c['perms'], lang)})" for c in ws["channels"])
                lines.append(team_t("tm_ws_row", lang, owner=owner, chs=chs))
                app = miniapp_button(lang, "post", label=team_t("tm_btn_open_app", lang), extra={"ws": ws["owner_id"]})
                if app is not None:
                    rows.append([app])
            rows.append([_btn(f"{team_t('tm_btn_leave', lang)} · {(ws['owner_name'] or ws['owner_id'])!s:.14}", f"tm_lv:{ws['owner_id']}")])
        rows.append(_back(lang))
        return await _show(update, "\n".join(lines), InlineKeyboardMarkup(rows))

    if action == "tm_lv" and len(parts) == 2 and parts[1].isdigit():
        await db.run_db(TI.leave, user_id, int(parts[1]))
        return await _show(update, team_t("tm_left", lang), InlineKeyboardMarkup([_back(lang)]))

    text, markup = await build_home(user_id, lang)
    await _show(update, text, markup)


# ------------------------------------------------------------------ taklifni qabul qilish (/start team_<token>)
async def accept_team_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, lang: str) -> None:
    """``/start team_<token>``: taklifni qabul qiladi, yordamchiga natijani, egasiga bildirishnoma yuboradi."""
    user = update.effective_user
    msg = update.effective_message
    res = await db.run_db(TI.accept_invite, token, user.id)
    if not res.get("ok"):
        await msg.reply_text(team_t(_JOIN_ERRORS.get(res.get("error"), "tm_err_generic"), lang))
        return
    owner_id = res["owner_id"]
    try:
        info = await db.run_db(TI.workspaces_for, user.id)
        owner_name = next((w["owner_name"] for w in info if w["owner_id"] == owner_id), "") or str(owner_id)
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.team_ui:owner_name", exc)
        owner_name = str(owner_id)
    rows = []
    app = miniapp_button(lang, "post", label=team_t("tm_btn_open_app", lang), extra={"ws": owner_id})
    if app is not None:
        rows.append([app])
    await msg.reply_text(
        team_t("tm_joined", lang, owner=html_escape(owner_name), title=html_escape(res["title"]), role=perms_text(res["perms"], lang)),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows) if rows else None)
    try:
        owner_lang = await db.run_db(db.get_user_language, owner_id) or "uz"
        await context.bot.send_message(
            chat_id=owner_id, parse_mode="HTML",
            text=team_t("tm_joined_owner", owner_lang, name=html_escape(user.full_name or user.username or str(user.id)),
                        title=html_escape(res["title"]), role=perms_text(res["perms"], owner_lang)))
    except Exception as exc:  # noqa: BLE001 — egasiga xabar yetmasa ham taklif qabul qilingan
        log_silent_failure("handlers.team_ui:notify_owner", exc)
