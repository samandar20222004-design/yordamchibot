"""💰 REKLAMA BIRJASI — bot ekranlari: katalog, kanal kartasi, so'rov/yozishma, kanal egasi paneli.

Barcha callback'lar ``mk:`` prefiksida. Matn kiritish (so'rov, javob, narx, tavsif) ``ConversationHandler``siz:
``context.user_data["mk_input"]`` (10 daqiqa amal qiladi) + ``MarketInputFilter`` — filtr faqat shu holat bor
foydalanuvchining oddiy matniga mos keladi, shu sababli asosiy FSM va menyu tugmalari bilan to'qnashmaydi.
``/cancel`` ``clear_fsm_data`` orqali holatni tozalaydi.

Biznes-qoidalar (limit, blok, egalik) — ``repositories/ad_market_repository.py``; hisob-kitob — ``services/ad_market.py``.
"""
from __future__ import annotations

import logging
import time
from datetime import timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes, filters

import database as db
from config import ADMIN_IDS_SET
from repositories import ad_market_repository as repo
from services import ad_market as svc
from translations import market_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

INPUT_KEY = "mk_input"
INPUT_TTL = 600  # soniya
_TZ = ZoneInfo("Asia/Tashkent")
_APP = None  # MarketInputFilter foydalanuvchi holatini shu Application orqali o'qiydi


def set_market_application(app) -> None:
    global _APP
    _APP = app


# ------------------------------------------------------------------ umumiy yordamchilar

async def _lang(context, user_id: int) -> str:
    try:
        from handlers.start import ensure_user_lang

        return await ensure_user_lang(context, user_id)
    except Exception:  # noqa: BLE001
        from locales.translations import get_lang

        return get_lang(context)


def _kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows if r])


def _btn(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data) if url is None else InlineKeyboardButton(text, url=url)


async def _show(update: Update, text: str, markup=None) -> None:
    """Callback bo'lsa xabarni tahrirlaydi, buyruq bo'lsa yangi xabar yuboradi."""
    query = update.callback_query
    if query is not None and query.message is not None:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                          disable_web_page_preview=True)
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            logger.debug("mk: edit bo'lmadi (%s), yangi xabar yuboriladi", exc)
        except TelegramError:
            logger.debug("mk: edit xatosi", exc_info=True)
    chat = update.effective_chat
    if chat is not None:
        await chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)


async def _toast(update: Update, text: str = "", alert: bool = False) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.answer(text[:190], show_alert=alert)
        except TelegramError:
            pass


def _set_input(context, kind: str, **data) -> None:
    context.user_data[INPUT_KEY] = {"kind": kind, "ts": time.time(), **data}


def _get_input(context) -> dict | None:
    data = context.user_data.get(INPUT_KEY)
    if not data:
        return None
    if time.time() - float(data.get("ts", 0)) > INPUT_TTL:
        context.user_data.pop(INPUT_KEY, None)
        return None
    return data


def _fmt_when(dt) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TZ).strftime("%d.%m %H:%M")


def _cat_label(key: str, lang: str) -> str:
    return market_t(f"mk_cat_{svc.normalize_category(key)}", lang)


def _price_text(price, lang: str) -> str:
    if price is None:
        return market_t("mk_price_negotiable", lang)
    return f"{svc.format_price(price, '')} {market_t('mk_currency', lang)}"


def card_text(listing: dict, lang: str, *, owner_view: bool = False) -> str:
    """Kanal kartasi (HTML). Noma'lum ko'rsatkich «—» yoki «ma'lumot yetarli emas» — soxta 0 EMAS."""
    t = lambda key, **kw: market_t(key, lang, **kw)  # noqa: E731
    members = listing.get("members")
    growth = listing.get("growth_30d")
    growth_txt = ""
    if growth is not None:
        growth_txt = f" ({'+' if growth >= 0 else ''}{svc.format_count(growth)} {t('mk_f_growth')})"
    views = listing.get("avg_views")
    er = listing.get("er_percent")
    lines = [
        f"📣 <b>{html_escape(listing.get('title') or listing.get('username'))}</b>",
        f"@{html_escape(listing['username'])} · {_cat_label(listing['category'], lang)}",
        "",
        f"{t('mk_f_members')}: <b>{svc.format_count(members)}</b>{growth_txt}",
        f"{t('mk_f_views')}: <b>{svc.format_count(views) if views is not None else t('mk_views_unknown')}</b>",
        f"{t('mk_f_er')}: <b>{f'{er}%' if er is not None else '—'}</b>",
        f"{t('mk_f_posts')}: <b>{listing.get('posts_30d') if listing.get('posts_30d') is not None else '—'}</b>",
        f"{t('mk_f_price')}: <b>{_price_text(listing.get('price_post'), lang)}</b>",
    ]
    badges = [t(f"mk_badge_{b}") for b in svc.listing_badges(listing)]
    if badges:
        lines += ["", " · ".join(badges)]
    if listing.get("description"):
        lines += ["", html_escape(listing["description"])]
    lines += ["", t("mk_verified"), t("mk_updated", when=_fmt_when(listing.get("stats_updated_at"))), t("mk_stats_note")]
    if owner_view:
        lines += ["", t("mk_manage", views=listing.get("view_count", 0), inquiries=listing.get("inquiry_count", 0))]
    return "\n".join(lines)


# ------------------------------------------------------------------ bosh ekran

def _home_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = lambda key: market_t(key, lang)  # noqa: E731
    markup = _kb([
        [_btn(t("mk_btn_catalog"), "mk:cat"), _btn(t("mk_btn_my"), "mk:my")],
        [_btn(t("mk_btn_inbox"), "mk:inbox"), _btn(t("mk_btn_how"), "mk:how")],
        [_btn(t("mk_btn_close"), "mk:close")],
    ])
    from miniapp_api.menu import with_miniapp_row

    return with_miniapp_row(markup, lang, "market", before_last=True)  # Mini App yoqilgan bo'lsagina «📱 Mini App»


async def market_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    context.user_data.pop(INPUT_KEY, None)
    lang = await _lang(context, user.id)
    try:
        totals = await db.run_db(repo.market_totals)
    except Exception:  # noqa: BLE001
        logger.exception("mk: jami statistika o'qilmadi")
        totals = {"listings": 0, "inquiries": 0}
    await _toast(update)
    await _show(update, market_t("mk_home", lang, **totals), _home_keyboard(lang))


async def market_how(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(context, update.effective_user.id)
    await _toast(update)
    await _show(update, market_t("mk_how", lang), _kb([[_btn(market_t("mk_btn_back", lang), "mk:home")]]))


async def market_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toast(update)
    query = update.callback_query
    if query is not None and query.message is not None:
        try:
            await query.message.delete()
        except TelegramError:
            pass


# ------------------------------------------------------------------ katalog

async def market_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _lang(context, update.effective_user.id)
    rows = [[_btn(market_t("mk_cat_all", lang), "mk:l:all:m:0")]]
    cats = list(svc.CATEGORIES)
    for i in range(0, len(cats), 2):
        rows.append([_btn(_cat_label(c, lang), f"mk:l:{c}:m:0") for c in cats[i:i + 2]])
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:home")])
    await _toast(update)
    await _show(update, market_t("mk_cat_pick", lang), _kb(rows))


async def market_list(update: Update, context: ContextTypes.DEFAULT_TYPE, cat: str, sort: str, page: int) -> None:
    lang = await _lang(context, update.effective_user.id)
    cat = cat if cat == "all" or cat in svc.CATEGORIES else "all"
    sort = sort if sort in ("m", "p", "e") else "m"
    page = max(0, page)
    data = await db.run_db(repo.list_catalog, cat, sort, page)
    total, items = data["total"], data["items"]
    pages = max(1, -(-total // repo.PAGE_SIZE))
    if page >= pages:
        page = pages - 1
        data = await db.run_db(repo.list_catalog, cat, sort, page)
        items = data["items"]
    rows = []
    for it in items:
        price = svc.format_count(it["price_post"]) if it["price_post"] is not None else market_t("mk_price_negotiable", lang)
        label = f"{(it['title'] or it['username'])[:20]} · {svc.format_count(it['members'])} · {price}"
        rows.append([_btn(label, f"mk:v:{it['id']}")])
    sorts = [_btn(("• " if sort == k else "") + market_t(f"mk_sort_{k}", lang), f"mk:l:{cat}:{k}:0") for k in ("m", "p", "e")]
    rows.append(sorts)
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"mk:l:{cat}:{sort}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_btn("▶️", f"mk:l:{cat}:{sort}:{page + 1}"))
    rows.append(nav)
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:cat")])
    cat_label = market_t("mk_cat_all", lang) if cat == "all" else _cat_label(cat, lang)
    text = market_t("mk_list_title", lang, cat=cat_label, total=total, sort=market_t(f"mk_sort_{sort}", lang),
                    page=page + 1, pages=pages)
    if not items:
        text += "\n\n" + market_t("mk_list_empty", lang)
    await _toast(update)
    await _show(update, text, _kb(rows))


async def _fresh_listing(listing: dict) -> dict:
    """Ko'rsatkichlar eskirgan bo'lsa bazadagi ma'lumotdan qayta hisoblaydi (Telegram so'rovisiz)."""
    if svc.stats_are_stale(listing):
        try:
            stats = await db.run_db(svc.refresh_listing_stats, listing["id"], listing["channel_id"], listing.get("members"))
            listing = {**listing, **stats}
            from datetime import datetime
            listing["stats_updated_at"] = datetime.now(timezone.utc)
        except Exception:  # noqa: BLE001
            logger.exception("mk: ko'rsatkichlarni yangilab bo'lmadi (e'lon %s)", listing.get("id"))
    return listing


async def market_card(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    listing = await db.run_db(repo.get_public_listing, listing_id, user.id)
    if listing is None:
        await _toast(update, market_t("mk_gone", lang), alert=True)
        return
    listing = await _fresh_listing(listing)
    t = lambda key: market_t(key, lang)  # noqa: E731
    rows = [[_btn(t("mk_btn_contact"), f"mk:q:{listing['id']}"),
             _btn(t("mk_btn_open"), url=f"https://t.me/{listing['username']}")],
            [_btn(t("mk_btn_report"), f"mk:rp:{listing['id']}"), _btn(t("mk_btn_back"), "mk:cat")]]
    await _toast(update)
    await _show(update, card_text(listing, lang), _kb(rows))


async def market_report(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    result = await db.run_db(repo.report_listing, listing_id, user.id)
    if not result["ok"]:
        key = "mk_report_own" if result["reason"] == "own" else "mk_gone"
        await _toast(update, market_t(key, lang), alert=True)
        return
    await _toast(update, market_t("mk_report_again" if result["reason"] == "again" else "mk_report_ok", lang), alert=True)
    if result["blocked"]:
        listing = await db.run_db(repo.get_listing, listing_id)
        for admin_id in ADMIN_IDS_SET:
            try:
                await context.bot.send_message(admin_id, market_t("mk_admin_blocked", "uz", id=listing_id,
                                                                  username=(listing or {}).get("username", "?"),
                                                                  count=result["count"]))
            except TelegramError:
                logger.debug("mk: admin %s ga xabar yetmadi", admin_id)


# ------------------------------------------------------------------ so'rov va yozishma

async def market_inquiry_start(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    listing = await db.run_db(repo.get_public_listing, listing_id, user.id)
    if listing is None:
        await _toast(update, market_t("mk_gone", lang), alert=True)
        return
    if listing["owner_id"] == user.id:
        await _toast(update, market_t("mk_inq_own", lang), alert=True)
        return
    _set_input(context, "inq", listing_id=listing_id)
    await _toast(update)
    await update.effective_chat.send_message(
        market_t("mk_inq_prompt", lang, title=html_escape(listing.get("title") or listing["username"]),
                 min=svc.INQUIRY_MIN, max=svc.INQUIRY_MAX),
        parse_mode=ParseMode.HTML)


def _thread_keyboard(inq: dict, lang: str) -> InlineKeyboardMarkup:
    t = lambda key: market_t(key, lang)  # noqa: E731
    rows = [[_btn(t("mk_btn_reply"), f"mk:r:{inq['id']}"), _btn(t("mk_btn_share"), f"mk:c:{inq['id']}")],
            [_btn(t("mk_btn_end"), f"mk:x:{inq['id']}")]]
    if inq["role"] == "owner":
        rows[1].append(_btn(t("mk_btn_block"), f"mk:b:{inq['id']}"))
    rows.append([_btn(t("mk_btn_scam"), f"mk:f:{inq['id']}")])
    try:  # Mini App yoqilgan bo'lsa suhbatni to'g'ridan-to'g'ri Mini App ichida ochish tugmasi
        from miniapp_api.menu import miniapp_button

        app_btn = miniapp_button(lang, "market", extra={"thread": int(inq["id"])}, label=t("mk_btn_open_app"))
        if app_btn is not None:
            rows.insert(0, [app_btn])
    except Exception:  # noqa: BLE001 — qo'shimcha tugma asosiy ekranni buzmasin
        logger.debug("mk: Mini App tugmasi qo'shilmadi", exc_info=True)
    return _kb(rows)


_UNSAFE_KEY = {"card": "mk_unsafe_card", "wallet": "mk_unsafe_wallet", "link": "mk_unsafe_link"}
_FAIL_KEY = {"limit": "mk_inq_limit", "blocked": "mk_inq_blocked", "own": "mk_inq_own", "open_exists": "mk_inq_exists",
             "banned": "mk_banned", "busy": "mk_busy", "spam": "mk_spam"}


async def _deliver(context, to_id: int, text: str, markup=None) -> bool:
    try:
        await context.bot.send_message(to_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                       disable_web_page_preview=True)
        return True
    except (Forbidden, BadRequest):
        return False
    except TelegramError:
        logger.warning("mk: xabar yetkazilmadi (%s)", to_id, exc_info=True)
        return False


async def _handle_inquiry_text(update, context, data: dict, text: str, lang: str) -> None:
    user = update.effective_user
    if len(text) < svc.INQUIRY_MIN:
        await update.message.reply_text(market_t("mk_inq_short", lang, min=svc.INQUIRY_MIN))
        return
    verdict = await db.run_db(svc.screen_message, user.id, text, first_message=True, owner_sender=False)
    if not verdict["ok"]:
        await update.message.reply_text(market_t(_UNSAFE_KEY[verdict["reason"]], lang))
        return
    res = await db.run_db(repo.create_inquiry, data["listing_id"], user.id, text, verdict["packed"])
    context.user_data.pop(INPUT_KEY, None)
    if not res["ok"]:
        await update.message.reply_text(market_t(_FAIL_KEY.get(res["reason"], "mk_gone"), lang, limit=repo.INQUIRIES_PER_DAY))
        return
    listing = await db.run_db(repo.get_listing, data["listing_id"])
    owner_lang = await db.run_db(db.get_user_language, res["owner_id"]) or "uz"
    trust = await db.run_db(svc.peer_context, user.id)
    inq = {"id": res["inquiry_id"], "role": "owner"}
    body = (market_t("mk_inq_owner_new", owner_lang, title=html_escape((listing or {}).get("title") or ""), text=html_escape(text))
            + svc.trust_text(trust, owner_lang) + svc.warn_text(verdict["flags"], owner_lang) + "\n\n" + market_t("mk_safety_tip", owner_lang))
    delivered = await _deliver(context, res["owner_id"], body, _thread_keyboard(inq, owner_lang))
    await update.message.reply_text(market_t("mk_inq_sent" if delivered else "mk_peer_unreachable", lang))


async def market_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    inq = await db.run_db(repo.get_inquiry, inquiry_id, user.id)
    if inq is None or inq["status"] != "open":
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    _set_input(context, "reply", inquiry_id=inquiry_id)
    await _toast(update)
    await update.effective_chat.send_message(market_t("mk_reply_prompt", lang))


async def _handle_reply_text(update, context, data: dict, text: str, lang: str) -> None:
    user = update.effective_user
    info = await db.run_db(repo.get_inquiry, data["inquiry_id"], user.id)
    if info is None:
        context.user_data.pop(INPUT_KEY, None)
        await update.message.reply_text(market_t("mk_thread_closed", lang))
        return
    verdict = await db.run_db(svc.screen_message, user.id, text[:svc.INQUIRY_MAX], first_message=False,
                              owner_sender=(info["role"] == "owner"))
    if not verdict["ok"]:
        await update.message.reply_text(market_t(_UNSAFE_KEY[verdict["reason"]], lang))
        return
    context.user_data.pop(INPUT_KEY, None)
    res = await db.run_db(repo.add_message, data["inquiry_id"], user.id, text[:svc.INQUIRY_MAX], verdict["packed"])
    if not res["ok"]:
        key = {"full": "mk_thread_full", "banned": "mk_banned", "spam": "mk_spam"}.get(res["reason"], "mk_thread_closed")
        await update.message.reply_text(market_t(key, lang, limit=repo.MAX_MESSAGES_PER_INQUIRY))
        return
    peer_lang = await db.run_db(db.get_user_language, res["recipient_id"]) or "uz"
    peer_role = market_t("mk_role_owner" if info["role"] == "owner" else "mk_role_adv", peer_lang)
    peer_view = {"id": info["id"], "role": "advertiser" if info["role"] == "owner" else "owner"}
    ok = await _deliver(
        context, res["recipient_id"],
        market_t("mk_msg_in", peer_lang, title=html_escape(info["title"] or ""), role=peer_role,
                 text=html_escape(text[:svc.INQUIRY_MAX])) + svc.warn_text(verdict["flags"], peer_lang),
        _thread_keyboard(peer_view, peer_lang))
    await update.message.reply_text(market_t("mk_msg_sent" if ok else "mk_peer_unreachable", lang))


async def market_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    items = await db.run_db(repo.list_user_inquiries, user.id)
    rows = []
    for it in items:
        role = market_t("mk_role_owner" if it["role"] == "owner" else "mk_role_adv", lang)
        rows.append([_btn(f"{(it['title'] or '')[:22]} · {role}"[:60], f"mk:t:{it['id']}")])
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:home")])
    await _toast(update)
    await _show(update, market_t("mk_inbox_title" if items else "mk_inbox_empty", lang), _kb(rows))


async def market_thread(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    inq = await db.run_db(repo.get_inquiry, inquiry_id, user.id)
    if inq is None:
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    msgs = await db.run_db(repo.recent_messages, inquiry_id, user.id)
    peer_role = market_t("mk_role_adv" if inq["role"] == "owner" else "mk_role_owner", lang)
    body = "\n\n".join(
        f"<b>{market_t('mk_you', lang) if m['sender_id'] == user.id else peer_role}</b> · {_fmt_when(m['created_at'])}\n"
        f"{html_escape(m['body'])}" for m in msgs)
    text = market_t("mk_thread", lang, title=html_escape(inq["title"] or ""), role=peer_role, messages=body)
    rows = list(_thread_keyboard(inq, lang).inline_keyboard) if inq["status"] == "open" else []
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:inbox")])
    await _toast(update)
    await _show(update, text[:4000], InlineKeyboardMarkup(rows))


async def market_close_thread(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    info = await db.run_db(repo.close_inquiry, inquiry_id, user.id)
    if info is None:
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    peer_lang = await db.run_db(db.get_user_language, info["peer_id"]) or "uz"
    await _deliver(context, info["peer_id"], market_t("mk_closed_notice", peer_lang, title=html_escape(info["title"] or "")))
    await _toast(update)
    await market_inbox(update, context)


async def market_block(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    info = await db.run_db(repo.block_advertiser, user.id, inquiry_id)
    if info is None:
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    await _toast(update, market_t("mk_blocked_ok", lang), alert=True)
    await market_inbox(update, context)


async def market_report_user(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    """🚩 Firibgar: suhbat yopiladi (egasi bo'lsa — reklama beruvchi bloklanadi), 3 ta turli shikoyat -> global ban."""
    user = update.effective_user
    lang = await _lang(context, user.id)
    res = await db.run_db(repo.report_user, user.id, inquiry_id)
    if not res["ok"]:
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    info = await db.run_db(repo.get_inquiry, inquiry_id, user.id)
    if info is not None and info["role"] == "owner":
        await db.run_db(repo.block_advertiser, user.id, inquiry_id)
    else:
        await db.run_db(repo.close_inquiry, inquiry_id, user.id)
    await _toast(update, market_t("mk_report_user_again" if res["reason"] == "again" else "mk_report_user_ok", lang), alert=True)
    if res["banned"]:
        for admin_id in ADMIN_IDS_SET:
            try:
                await context.bot.send_message(admin_id, market_t("mk_admin_user_banned", "uz", id=res["reported_id"], count=res["count"]))
            except TelegramError:
                logger.debug("mk: admin %s ga xabar yetmadi", admin_id)
    await market_inbox(update, context)


async def market_share_contact(update: Update, context: ContextTypes.DEFAULT_TYPE, inquiry_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    inq = await db.run_db(repo.get_inquiry, inquiry_id, user.id)
    if inq is None or inq["status"] != "open":
        await _toast(update, market_t("mk_thread_closed", lang), alert=True)
        return
    name = html_escape(user.full_name or "user")
    contact = f'<a href="tg://user?id={user.id}">{name}</a>'
    if user.username:
        contact += f" (@{html_escape(user.username)})"
    peer_lang = await db.run_db(db.get_user_language, inq["peer_id"]) or "uz"
    role = market_t("mk_role_owner" if inq["role"] == "owner" else "mk_role_adv", peer_lang)
    ok = await _deliver(context, inq["peer_id"], market_t("mk_contact_in", peer_lang, role=role, contact=contact))
    await _toast(update, market_t("mk_contact_sent" if ok else "mk_peer_unreachable", lang), alert=True)


# ------------------------------------------------------------------ kanal egasi

def _status_icon(status, lang: str) -> str:
    return market_t({"active": "mk_st_active", "paused": "mk_st_paused", "blocked": "mk_st_blocked"}.get(status, "mk_st_none"), lang)


async def market_my(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    channels = await db.run_db(repo.list_owner_channels, user.id)
    rows = [[_btn(f"{_status_icon(c['status'], lang)} {(c['title'] or str(c['channel_id']))[:30]}", f"mk:lc:{c['channel_id']}")]
            for c in channels]
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:home")])
    await _toast(update)
    await _show(update, market_t("mk_my_title" if channels else "mk_my_empty", lang), _kb(rows))


async def market_channel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str) -> None:
    """Kanal paneli / «Kanal qo'yish» ro'yxatidan: e'lon bor bo'lsa boshqaruv, yo'q bo'lsa yangi e'lon oqimi."""
    user = update.effective_user
    lang = await _lang(context, user.id)
    channel = await db.run_db(repo.get_owned_channel, user.id, channel_id)
    if channel is None:
        await _toast(update, market_t("mk_err_admin", lang), alert=True)
        return
    for c in await db.run_db(repo.list_owner_channels, user.id):
        if str(c["channel_id"]) == str(channel_id) and c["listing_id"]:
            await market_manage(update, context, c["listing_id"])
            return
    await _start_new_listing(update, context, channel, lang)


async def _start_new_listing(update, context, channel: dict, lang: str) -> None:
    user = update.effective_user
    if await db.run_db(repo.count_owner_listings, user.id) >= repo.MAX_LISTINGS_PER_USER:
        await _toast(update, market_t("mk_err_limit", lang, limit=repo.MAX_LISTINGS_PER_USER), alert=True)
        return
    raw = channel["channel_id"]
    info = await svc.verify_channel_ownership(context.bot, user.id, raw)
    if not info["ok"]:
        key = {"private": "mk_err_private", "tg_error": "mk_err_tg"}.get(info["reason"], "mk_err_admin")
        await _toast(update, market_t(key, lang), alert=True)
        return
    context.user_data["mk_new"] = {"channel_id": str(raw), "username": info["username"],
                                   "title": info["title"] or channel.get("title") or info["username"],
                                   "members": info["members"], "ts": time.time()}
    cats = list(svc.CATEGORIES)
    rows = [[_btn(_cat_label(c, lang), f"mk:nc:{c}") for c in cats[i:i + 2]] for i in range(0, len(cats), 2)]
    rows.append([_btn(market_t("mk_btn_back", lang), "mk:my")])
    await _toast(update)
    await _show(update, market_t("mk_new_intro", lang, title=html_escape(context.user_data["mk_new"]["title"])), _kb(rows))


async def market_new_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    new = context.user_data.get("mk_new")
    if not new or time.time() - new["ts"] > INPUT_TTL:
        await _toast(update, market_t("mk_stale", lang), alert=True)
        return
    new["category"] = svc.normalize_category(category)
    _set_input(context, "price_new")
    await _toast(update)
    await update.effective_chat.send_message(market_t("mk_price_prompt", lang), parse_mode=ParseMode.HTML)


def _manage_keyboard(listing: dict, lang: str) -> InlineKeyboardMarkup:
    t = lambda key: market_t(key, lang)  # noqa: E731
    lid = listing["id"]
    toggle = (_btn(t("mk_btn_resume"), f"mk:pa:{lid}") if listing["status"] == "paused" else _btn(t("mk_btn_pause"), f"mk:pa:{lid}"))
    rows = [[_btn(t("mk_btn_price"), f"mk:ep:{lid}"), _btn(t("mk_btn_desc"), f"mk:ed:{lid}"), _btn(t("mk_btn_cat"), f"mk:ec:{lid}")],
            [_btn(t("mk_btn_refresh"), f"mk:rf:{lid}")]]
    if listing["status"] != "blocked":
        rows[1].insert(0, toggle)
    rows.append([_btn(t("mk_btn_delete"), f"mk:dl:{lid}"), _btn(t("mk_btn_back"), "mk:my")])
    return _kb(rows)


async def market_manage(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int, prefix: str = "") -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    listing = await db.run_db(repo.get_listing_for_owner, listing_id, user.id)
    if listing is None:
        await _toast(update, market_t("mk_gone", lang), alert=True)
        return
    listing = await _fresh_listing(listing)
    text = card_text(listing, lang, owner_view=True)
    if listing["status"] == "blocked":
        text = market_t("mk_listing_blocked", lang) + "\n\n" + text
    elif listing["status"] == "paused":
        text = market_t("mk_paused", lang) + "\n\n" + text
    if prefix:
        text = prefix + "\n\n" + text
    await _toast(update)
    await _show(update, text, _manage_keyboard(listing, lang))


async def market_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    listing = await db.run_db(repo.get_listing_for_owner, listing_id, user.id)
    if listing is not None and listing["status"] != "blocked":
        new_status = "active" if listing["status"] == "paused" else "paused"
        await db.run_db(repo.set_listing_status, listing_id, user.id, new_status)
    await market_manage(update, context, listing_id)


async def market_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    listing = await db.run_db(repo.get_listing_for_owner, listing_id, user.id)
    if listing is None:
        await _toast(update, market_t("mk_gone", lang), alert=True)
        return
    live = None
    raw = listing["channel_id"]
    try:
        live = await context.bot.get_chat_member_count(int(raw) if str(raw).lstrip("-").isdigit() else raw)
    except TelegramError:
        logger.debug("mk: jonli obunachi soni olinmadi (%s)", raw)
    await db.run_db(svc.refresh_listing_stats, listing_id, listing["channel_id"], live)
    await market_manage(update, context, listing_id, prefix=market_t("mk_refreshed", lang))


async def market_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    lang = await _lang(context, update.effective_user.id)
    await _toast(update)
    await _show(update, market_t("mk_confirm_delete", lang), _kb([[
        _btn(market_t("mk_btn_yes", lang), f"mk:dy:{listing_id}"), _btn(market_t("mk_btn_no", lang), f"mk:m:{listing_id}")]]))


async def market_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    await db.run_db(repo.delete_listing, listing_id, user.id)
    await _toast(update, market_t("mk_deleted", lang))
    await market_my(update, context)


async def market_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int, field: str) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    if await db.run_db(repo.get_listing_for_owner, listing_id, user.id) is None:
        await _toast(update, market_t("mk_gone", lang), alert=True)
        return
    _set_input(context, "price_edit" if field == "price" else "desc_edit", listing_id=listing_id)
    await _toast(update)
    key = "mk_price_prompt" if field == "price" else "mk_desc_prompt"
    await update.effective_chat.send_message(market_t(key, lang, max=svc.DESCRIPTION_MAX), parse_mode=ParseMode.HTML)


async def market_edit_category(update: Update, context: ContextTypes.DEFAULT_TYPE, listing_id: int, category: str | None) -> None:
    user = update.effective_user
    lang = await _lang(context, user.id)
    if category is None:
        cats = list(svc.CATEGORIES)
        rows = [[_btn(_cat_label(c, lang), f"mk:es:{listing_id}:{c}") for c in cats[i:i + 2]] for i in range(0, len(cats), 2)]
        rows.append([_btn(market_t("mk_btn_back", lang), f"mk:m:{listing_id}")])
        await _toast(update)
        await _show(update, market_t("mk_cat_pick", lang), _kb(rows))
        return
    await db.run_db(repo.update_listing_fields, listing_id, user.id, category=svc.normalize_category(category))
    await market_manage(update, context, listing_id, prefix=market_t("mk_saved", lang))


def _parse_price_input(text: str, lang: str):
    status, value = svc.parse_price(text)
    if status == "error":
        return None, market_t("mk_price_bad", lang, min=svc.PRICE_MIN, max=svc.PRICE_MAX)
    return ("ok", value), None


async def _handle_price_new(update, context, text: str, lang: str) -> None:
    parsed, err = _parse_price_input(text, lang)
    if err:
        await update.message.reply_text(err)
        return
    new = context.user_data.get("mk_new")
    if not new:
        context.user_data.pop(INPUT_KEY, None)
        await update.message.reply_text(market_t("mk_stale", lang))
        return
    new["price"] = parsed[1]
    _set_input(context, "desc_new")
    await update.message.reply_text(market_t("mk_desc_prompt", lang, max=svc.DESCRIPTION_MAX))


async def _handle_desc_new(update, context, text: str, lang: str) -> None:
    user = update.effective_user
    new = context.user_data.get("mk_new")
    context.user_data.pop(INPUT_KEY, None)
    if not new:
        await update.message.reply_text(market_t("mk_stale", lang))
        return
    desc = None if text.strip() in ("-", "—") else (svc.clean_text(text, svc.DESCRIPTION_MAX) or None)
    res = await db.run_db(repo.create_listing, user.id, new["channel_id"], new["username"], new["title"],
                          new.get("category", "other"), new.get("price"), desc)
    context.user_data.pop("mk_new", None)
    if not res["ok"]:
        if res["reason"] == "exists":
            await update.message.reply_text(market_t("mk_saved", lang))
            return
        key = "mk_err_limit" if res["reason"] == "limit" else "mk_err_admin"
        await update.message.reply_text(market_t(key, lang, limit=repo.MAX_LISTINGS_PER_USER))
        return
    await db.run_db(svc.refresh_listing_stats, res["listing_id"], new["channel_id"], new.get("members"))
    listing = await db.run_db(repo.get_listing_for_owner, res["listing_id"], user.id)
    await update.message.reply_text(
        market_t("mk_published", lang) + "\n\n" + card_text(listing, lang, owner_view=True),
        parse_mode=ParseMode.HTML, reply_markup=_manage_keyboard(listing, lang), disable_web_page_preview=True)


async def _handle_price_edit(update, context, data: dict, text: str, lang: str) -> None:
    parsed, err = _parse_price_input(text, lang)
    if err:
        await update.message.reply_text(err)
        return
    context.user_data.pop(INPUT_KEY, None)
    ok = await db.run_db(repo.update_listing_fields, data["listing_id"], update.effective_user.id, price_post=parsed[1])
    await update.message.reply_text(market_t("mk_saved" if ok else "mk_gone", lang),
                                    reply_markup=_kb([[_btn("📊", f"mk:m:{data['listing_id']}")]]))


async def _handle_desc_edit(update, context, data: dict, text: str, lang: str) -> None:
    context.user_data.pop(INPUT_KEY, None)
    desc = None if text.strip() in ("-", "—") else (svc.clean_text(text, svc.DESCRIPTION_MAX) or None)
    ok = await db.run_db(repo.update_listing_fields, data["listing_id"], update.effective_user.id, description=desc)
    await update.message.reply_text(market_t("mk_saved" if ok else "mk_gone", lang),
                                    reply_markup=_kb([[_btn("📊", f"mk:m:{data['listing_id']}")]]))


# ------------------------------------------------------------------ matn kiritish

class _MarketInputFilter(filters.MessageFilter):
    """Faqat faol ``mk_input`` holati bor foydalanuvchining oddiy matniga mos (menyu tugmasi matni bundan mustasno)."""

    name = "MarketInputFilter"

    def filter(self, message) -> bool:
        if _APP is None or message is None or not message.text or message.text.startswith("/"):
            return False
        user = message.from_user
        if user is None:
            return False
        data = (_APP.user_data.get(user.id) or {}).get(INPUT_KEY)
        if not data or time.time() - float(data.get("ts", 0)) > INPUT_TTL:
            return False
        try:
            from keyboards.default import is_menu_text

            if is_menu_text(message.text):
                _APP.user_data[user.id].pop(INPUT_KEY, None)
                return False
        except Exception:  # noqa: BLE001
            logger.debug("mk: menyu matni tekshiruvi ishlamadi", exc_info=True)
        return True


MarketInputFilter = _MarketInputFilter()


async def market_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _get_input(context)
    if data is None:
        return
    user = update.effective_user
    lang = await _lang(context, user.id)
    text = (update.message.text or "").strip()
    kind = data["kind"]
    try:
        if kind == "inq":
            await _handle_inquiry_text(update, context, data, text, lang)
        elif kind == "reply":
            await _handle_reply_text(update, context, data, text, lang)
        elif kind == "price_new":
            await _handle_price_new(update, context, text, lang)
        elif kind == "desc_new":
            await _handle_desc_new(update, context, text, lang)
        elif kind == "price_edit":
            await _handle_price_edit(update, context, data, text, lang)
        elif kind == "desc_edit":
            await _handle_desc_edit(update, context, data, text, lang)
    except Exception:  # noqa: BLE001
        logger.exception("mk: matn kiritishda xato (%s)", kind)
        context.user_data.pop(INPUT_KEY, None)
        await update.message.reply_text(market_t("mk_err_generic", lang))


# ------------------------------------------------------------------ marshrutlash

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await market_home(update, context)


def _int(parts: list[str], i: int, default: int = 0) -> int:
    try:
        return int(parts[i])
    except (IndexError, ValueError):
        return default


async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``mk:<amal>[:arg...]`` — barcha birja tugmalari shu yerdan tarqaladi."""
    query = update.callback_query
    if query is None or not query.data or update.effective_user is None:
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "home"
    try:
        if action == "home":
            await market_home(update, context)
        elif action == "how":
            await market_how(update, context)
        elif action == "close":
            await market_close(update, context)
        elif action == "cat":
            await market_categories(update, context)
        elif action == "l":
            await market_list(update, context, parts[2] if len(parts) > 2 else "all",
                              parts[3] if len(parts) > 3 else "m", _int(parts, 4))
        elif action == "v":
            await market_card(update, context, _int(parts, 2))
        elif action == "rp":
            await market_report(update, context, _int(parts, 2))
        elif action == "q":
            await market_inquiry_start(update, context, _int(parts, 2))
        elif action == "inbox":
            await market_inbox(update, context)
        elif action == "t":
            await market_thread(update, context, _int(parts, 2))
        elif action == "r":
            await market_reply_start(update, context, _int(parts, 2))
        elif action == "x":
            await market_close_thread(update, context, _int(parts, 2))
        elif action == "b":
            await market_block(update, context, _int(parts, 2))
        elif action == "c":
            await market_share_contact(update, context, _int(parts, 2))
        elif action == "f":
            await market_report_user(update, context, _int(parts, 2))
        elif action == "my":
            await market_my(update, context)
        elif action == "lc":
            await market_channel_entry(update, context, ":".join(parts[2:]))
        elif action == "nc":
            await market_new_category(update, context, parts[2] if len(parts) > 2 else "other")
        elif action == "m":
            await market_manage(update, context, _int(parts, 2))
        elif action == "pa":
            await market_toggle(update, context, _int(parts, 2))
        elif action == "rf":
            await market_refresh(update, context, _int(parts, 2))
        elif action == "dl":
            await market_delete_confirm(update, context, _int(parts, 2))
        elif action == "dy":
            await market_delete(update, context, _int(parts, 2))
        elif action == "ep":
            await market_edit_start(update, context, _int(parts, 2), "price")
        elif action == "ed":
            await market_edit_start(update, context, _int(parts, 2), "desc")
        elif action == "ec":
            await market_edit_category(update, context, _int(parts, 2), None)
        elif action == "es":
            await market_edit_category(update, context, _int(parts, 2), parts[3] if len(parts) > 3 else "other")
        else:
            await _toast(update)
    except Exception:  # noqa: BLE001
        logger.exception("mk: callback xatosi (%s)", query.data)
        await _toast(update, market_t("mk_err_generic", await _lang(context, update.effective_user.id)), alert=True)


async def market_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: ``/market_ban <id>`` — e'lonni bloklash, ``/market_unban <id>`` — qayta faollashtirish (shikoyatlar tozalanadi)."""
    user = update.effective_user
    if user is None or user.id not in ADMIN_IDS_SET or update.message is None:
        return
    command = (update.message.text or "").split()[0].lstrip("/").split("@")[0].lower()
    try:
        listing_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(f"/{command} <id>")
        return
    if command in ("market_userban", "market_userunban"):
        await db.run_db(repo.admin_set_ban, listing_id, command == "market_userban")
        await update.message.reply_text(f"OK: user {listing_id} -> {'banned' if command == 'market_userban' else 'unbanned'}")
        return
    status = "blocked" if command == "market_ban" else "active"
    changed = await db.run_db(repo.admin_set_listing_status, listing_id, status)
    await update.message.reply_text(f"{'OK' if changed else 'not found'}: #{listing_id} → {status}")
