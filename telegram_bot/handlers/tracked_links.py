"""🔗 Manba havolalari: har reklama joyi / hamkor uchun alohida ``?start=s_<kod>`` havolasi va uning natijasi.

Admin (RBAC ``manage_promos``): ``/links`` — ro'yxat va statistika; ``/link KOD`` — tafsilot va kimlar kelgani;
``/link_new KOD [@egasi|ID] Nomi`` — yangi; ``/link_off KOD`` / ``/link_on KOD``; ``/link_user ID|@username`` — foydalanuvchi
qaysi havola bilan kelgani. Egasi: ``/mylinks`` — o'z havolalari (faqat sonlar, boshqalarning shaxsiy ma'lumoti yo'q).
Panel: «Promo-kod» ekranidagi «🔗 Havolalar» tugmasi (``adm_links``) shu ro'yxatni ko'rsatadi.

/start: ``s_<kod>`` faol havola bo'lsa tashrif yoziladi; havolaning egasi bo'lsa yangi foydalanuvchi uning taklifi
sifatida saqlanadi (``ReferralService`` qoidalari: o'zini taklif qilish rad etiladi, ball birinchi postdan keyin).
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import database as db
from locales.translations import get_lang
from repositories import tracked_links_repository as TL
from services.rbac_service import PERM_MANAGE_PROMOS, has_permission
from translations.tracked_links import links_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

LIST_LIMIT = 15
JOINS_LIMIT = 20


def _date(value) -> str:
    try:
        return value.strftime("%d.%m.%Y")
    except Exception:  # noqa: BLE001
        return "—"


def _pct(part, whole) -> str:
    return f"{round(100 * part / whole)}%" if whole else "—"


def link_url(bot_username: str | None, code: str) -> str:
    return f"https://t.me/{bot_username or 'bot'}?start={TL.payload_for(code)}"


def _allowed(user_id) -> bool:
    return bool(user_id) and has_permission(user_id, PERM_MANAGE_PROMOS)


# ---------------------------------------------------------------- matn quruvchilar (DB'siz, testlanadi)

def build_list_text(items: list, lang: str) -> str:
    lines = [links_t("tl_list_title", lang)]
    if not items:
        return "\n".join(lines + ["", links_t("tl_empty", lang)])
    total = lambda key: sum(int(it.get(key) or 0) for it in items)  # noqa: E731
    lines.append(links_t("tl_list_head", lang, n=len(items), clicks=total("clicks"), new=total("new_users"),
                         posted=total("posted"), paid=total("paid")))
    lines.append("")
    for it in items[:LIST_LIMIT]:
        owner = links_t("tl_owner_suffix", lang, owner=it["owner_id"]) if it.get("owner_id") else ""
        lines.append(links_t(
            "tl_row", lang, icon="🟢" if it.get("is_active") else "⚪️", code=html_escape(it["code"]),
            title=html_escape(it["title"]), owner=owner, clicks=it.get("clicks") or 0, visitors=it.get("visitors") or 0,
            new=it.get("new_users") or 0, chan=it.get("with_channel") or 0, posted=it.get("posted") or 0, paid=it.get("paid") or 0,
        ))
    if len(items) > LIST_LIMIT:
        lines.append(links_t("tl_more", lang, n=len(items) - LIST_LIMIT))
    lines += ["", links_t("tl_legend", lang), "", links_t("tl_hint", lang)]
    return "\n".join(lines)


def _person(j: dict) -> str:
    name = html_escape(j.get("full_name") or "") or "—"
    user = f" @{html_escape(j['username'])}" if j.get("username") else ""
    return f"{name}{user} (<code>{j['user_id']}</code>)"


def build_detail_text(link: dict, stats: dict, joins: list, bot_username: str | None, lang: str) -> str:
    new = int(stats.get("new_users") or 0)
    owner_line = (links_t("tl_detail_owner", lang, owner=link["owner_id"]) if link.get("owner_id")
                  else links_t("tl_detail_no_owner", lang))
    text = links_t(
        "tl_detail", lang, title=html_escape(link["title"]), status=links_t("tl_st_on" if link.get("is_active") else "tl_st_off", lang),
        code=html_escape(link["code"]), url=link_url(bot_username, link["code"]), owner_line=owner_line,
        created=_date(link.get("created_at")), clicks=link.get("clicks") or 0, visitors=stats.get("visitors") or 0, new=new,
        chan=stats.get("with_channel") or 0, chan_pct=_pct(stats.get("with_channel") or 0, new),
        posted=stats.get("posted") or 0, posted_pct=_pct(stats.get("posted") or 0, new),
        paid=stats.get("paid") or 0, paid_pct=_pct(stats.get("paid") or 0, new),
    )
    if not joins:
        return text + "\n\n" + links_t("tl_no_joins", lang)
    rows = []
    for j in joins:
        badges = "".join(b for b, ok in (("📢", j.get("has_channel")), ("📝", j.get("posted")), ("💎", j.get("paid"))) if ok)
        rows.append(links_t("tl_join_row", lang, name=_person(j), when=_date(j.get("joined_at")), badges=badges))
    return text + "\n\n" + links_t("tl_joins_title", lang) + "\n" + "\n".join(rows)


def build_my_text(items: list, bot_username: str | None, lang: str) -> str:
    if not items:
        return links_t("tl_my_empty", lang)
    blocks = [links_t("tl_my_title", lang), ""]
    for it in items[:LIST_LIMIT]:
        blocks.append(links_t(
            "tl_my_row", lang, title=html_escape(it["title"]), status="" if it.get("is_active") else links_t("tl_st_off", lang),
            url=link_url(bot_username, it["code"]), clicks=it.get("clicks") or 0, new=it.get("new_users") or 0,
            posted=it.get("posted") or 0, paid=it.get("paid") or 0,
        ))
        blocks.append("")
    blocks.append(links_t("tl_my_note", lang))
    return "\n".join(blocks)


def parse_new_args(args: list) -> tuple[str | None, str | None, str]:
    """``/link_new KOD [@egasi|ID] Nomi...`` -> (kod, egasi_tokeni|None, nom)."""
    if not args:
        return None, None, ""
    code, rest = args[0], list(args[1:])
    owner = None
    if rest and (rest[0].startswith("@") or rest[0].isdigit()):
        owner = rest.pop(0)
    return code, owner, " ".join(rest)


def list_keyboard(lang: str) -> InlineKeyboardMarkup:
    from keyboards.nav import nav_button

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(links_t("tl_btn_refresh", lang), callback_data="adm_links")],
        [nav_button("back", "adm_promo"), nav_button("close")],
    ])


async def load_list_text(lang: str) -> str:
    items = await db.run_db(TL.list_links, 200)
    return build_list_text(items, lang)


# ---------------------------------------------------------------- /start integratsiyasi

async def link_for_start(arg) -> dict | None:
    """``s_<kod>`` faol havola bo'lsa uni qaytaradi; aks holda (yoki DB xatosida) ``None`` — /start buzilmaydi."""
    code = TL.code_from_payload(arg)
    if not code:
        return None
    try:
        link = await db.run_db(TL.get_link, code)
    except Exception:  # noqa: BLE001
        logger.warning("Manba havolasi o'qilmadi (kod=%s)", code)
        return None
    return link if link and link.get("is_active") else None


async def record_start_visit(link_id: int, user_id: int, is_new: bool) -> None:
    try:
        await db.run_db(TL.record_visit, link_id, user_id, is_new)
    except Exception:  # noqa: BLE001 — statistika /start ni buzmasin
        logger.warning("Manba havolasi tashrifi yozilmadi (link=%s user=%s)", link_id, user_id)


# ---------------------------------------------------------------- buyruqlar

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    lang = get_lang(context)
    await update.message.reply_text(await load_list_text(lang), parse_mode="HTML", disable_web_page_preview=True)


async def link_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    lang = get_lang(context)
    args = context.args or []
    if not args:
        await update.message.reply_text(links_t("tl_usage_detail", lang))
        return
    link = await db.run_db(TL.get_link, args[0])
    if link is None:
        await update.message.reply_text(links_t("tl_not_found", lang))
        return
    stats = await db.run_db(TL.link_stats, link["id"])
    joins = await db.run_db(TL.recent_joins, link["id"], JOINS_LIMIT)
    await update.message.reply_text(build_detail_text(link, stats, joins, context.bot.username, lang),
                                    parse_mode="HTML", disable_web_page_preview=True)


async def link_new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _allowed(user_id):
        return
    lang = get_lang(context)
    code, owner_token, title = parse_new_args(context.args or [])
    if not code:
        await update.message.reply_text(links_t("tl_usage_new", lang))
        return
    owner_id = None
    if owner_token:
        owner_id = await db.run_db(TL.find_user_id, owner_token)
        if owner_id is None:
            await update.message.reply_text(links_t("tl_err_owner_unknown", lang))
            return
    res = await db.run_db(TL.create_link, code, title, owner_id, user_id)
    if not res.get("ok"):
        await update.message.reply_text(links_t("tl_err_" + res.get("error", "bad_code"), lang))
        return
    link = res["link"]
    owner_line = (links_t("tl_created_owner", lang, owner=owner_id) if owner_id else links_t("tl_created_no_owner", lang))
    await update.message.reply_text(
        links_t("tl_created", lang, title=html_escape(link["title"]), url=link_url(context.bot.username, link["code"]),
                owner_line=owner_line, code=html_escape(link["code"])),
        parse_mode="HTML", disable_web_page_preview=True,
    )


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, active: bool):
    if not _allowed(update.effective_user.id):
        return
    lang = get_lang(context)
    args = context.args or []
    if not args:
        await update.message.reply_text(links_t("tl_usage_toggle", lang))
        return
    code = TL.normalize_code(args[0])
    if not code or not await db.run_db(TL.set_active, code, active):
        await update.message.reply_text(links_t("tl_not_found", lang))
        return
    await update.message.reply_text(links_t("tl_set_on" if active else "tl_set_off", lang, code=html_escape(code)),
                                    parse_mode="HTML")


async def link_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, False)


async def link_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, True)


async def link_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    lang = get_lang(context)
    args = context.args or []
    if not args:
        await update.message.reply_text(links_t("tl_usage_user", lang))
        return
    target = await db.run_db(TL.find_user_id, args[0])
    if target is None:
        await update.message.reply_text(links_t("tl_user_unknown", lang))
        return
    src = await db.run_db(TL.source_of_user, target)
    await update.message.reply_text(build_user_text(target, src, lang), parse_mode="HTML")


def build_user_text(user_id: int, src: dict | None, lang: str) -> str:
    if not src:
        return links_t("tl_user_none", lang, user=user_id)
    origin = src.get("origin")
    head = (links_t("tl_user_origin", lang, user=user_id, code=html_escape(origin["code"]), title=html_escape(origin["title"]),
                    when=_date(origin.get("first_at")))
            if origin else links_t("tl_user_no_origin", lang, user=user_id))
    codes = ", ".join(f"<code>{html_escape(v['code'])}</code>" for v in src.get("visits") or [])
    return head + "\n" + links_t("tl_user_visits", lang, codes=codes)


async def my_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    items = await db.run_db(TL.list_links, 50, update.effective_user.id)
    await update.message.reply_text(build_my_text(items, context.bot.username, lang), parse_mode="HTML",
                                    disable_web_page_preview=True)
