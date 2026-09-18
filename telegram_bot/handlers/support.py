"""💬 QO'LLAB-QUVVATLASH — BIR MARTALIK MUROJAAT + TO'G'RIDAN-TO'G'RI JAVOB.

PostAssist V2 · 4-QISM (so'nggi qism).

MUAMMO
------
Foydalanuvchi muammoga duch kelganda bot ichidan adminga yoza olmasdi
(yoki nazoratsiz spam yozib, adminga o'nlab xabar yuborardi).

YECHIM — IKKI QISM
------------------

1) **YAGONA MUROJAAT OQIMI (ONE-TIME TICKET FSM)** —``SUPPORT_TICKET_INPUT``::

       [💬 Qo'llab-quvvatlash] → «Savol yoki muammoingizni bitta xabarda
       to'liq yozib qoldiring…» + [◀️ Orqaga]
              ↓ foydalanuvchi matn (yoki rasm + izoh) yuboradi
       FSM holati DARHOL yopiladi  ← ketma-ket yozish = spam to'xtaydi
              ↓
       «✅ Murojaatingiz adminga yetkazildi. Javob shu yerda keladi.»

   Bitta murojaat = bitta xabar. Keyingi xabarlar adminga YUBORILMAYDI
   (holat yopilgan), ya'ni foydalanuvchi ketma-ket yozib adminga spam
   qila olmaydi. Qo'shimcha himoya: qisqa cooldown va kunlik soft-limit
   (``SUPPORT_TICKET_COOLDOWN_SEC`` / ``SUPPORT_TICKET_DAILY_LIMIT``).

2) **ADMINDAN TO'G'RIDAN-TO'G'RI JAVOB (ADMIN REPLY DISPATCHER)**

   Murojaat ``.env`` dagi ``ADMIN_IDS`` ro'yxatidagi HAR BIR adminga::

       📩 Yangi murojaat!
       👤 Kimdan: @username (ID: <code>123</code>)
       📝 Xabar:
       …

   ko'rinishida yuboriladi va Telegram qaytargan ``message_id`` murojaatga
   bog'lanadi (``support_ticket_deliveries`` jadvali + xotiradagi tez kesh).
   Admin o'sha xabarga Telegram'ning oddiy «Reply» (Javob berish) funksiyasi
   bilan yozsa — bot javobni ushlaydi va murojaat EGASIGA yetkazadi::

       💬 Qo'llab-quvvatlash xizmati javobi:

       {admin_javobi}

   So'ngra adminga «✅ Javob foydalanuvchiga yetkazildi» tasdig'i beriladi.

XAVFSIZLIK
----------
  * Reply handleri FAQAT ``ADMIN_IDS`` dagi foydalanuvchilar uchun
    ro'yxatdan o'tadi va handler ichida ham ``from_user.id`` QAYTA
    tekshiriladi (fail-closed) — oddiy foydalanuvchi hech qanday holatda
    bu oqimga ta'sir qila olmaydi;
  * murojaat matni adminga HTML-escape qilib yuboriladi (foydalanuvchi
    yozgan ``<b>``/``<a>`` teglar parse xatosiga olib kelmaydi);
  * qo'llab-quvvatlash adminlari sozlanmagan bo'lsa foydalanuvchiga
    muloyim, ROSTGO'Y javob beriladi (soxta «yetkazildi» YO'Q);
  * har bir qadam fail-soft: DB yoki Telegram xatosi oqimni yiqitmaydi.
"""

from __future__ import annotations

import logging
import time

from telegram.ext import ContextTypes, ConversationHandler, filters

from config import ADMIN_IDS_SET
from keyboards.inline import get_support_ticket_keyboard
from locales.translations import get_lang
from translations import support_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FSM holati va callback'lari
# ---------------------------------------------------------------------------
# 540 — 4-QISM: 529/530-539 (kontent manbalari) bandlaridan keyingi BO'SH
# oraliq. Boshqa oqimlar bilan to'qnashmaydi (testlar buni tekshiradi).
SUPPORT_TICKET_INPUT = 540

#: Murojaat ekranidagi [◀️ Orqaga] tugmasi (64 baytdan ancha qisqa).
CB_SUPPORT_BACK = "sup_back"

#: Admin xabarining «Reply» kuzatuvi uchun yagona filtr (handlers/__init__.py
#: dagi ro'yxatga olishda ishlatiladi; testlar ham shu obyektni tekshiradi).
#:
#:  * ``filters.REPLY`` — faqat Telegram «Reply» (javob) xabarlari;
#:  * ``filters.ChatType.PRIVATE`` — faqat bot bilan shaxsiy chat;
#:  * ``filters.User`` — FAQAT ``ADMIN_IDS`` dagi foydalanuvchilar. Ro'yxat
#:    bo'sh bo'lsa hech qachon mos kelmaydigan filtr quriladi (fail-closed):
#:    admin sozlanmagan muhitda oqim umuman ishga tushmaydi.
_ADMIN_IDS_LIST = sorted(int(a) for a in ADMIN_IDS_SET)
SUPPORT_ADMIN_REPLY_FILTER = (
    filters.REPLY
    & filters.ChatType.PRIVATE
    & filters.User(user_id=(_ADMIN_IDS_LIST or [-1]))
    & ~filters.COMMAND
)
#: Adminlar umuman sozlanmagan bo'lsa handler ro'yxatga OLINMAYDI.
SUPPORT_ADMIN_REPLY_ENABLED = bool(_ADMIN_IDS_LIST)

# ---------------------------------------------------------------------------
# Anti-spam cheklovlari
# ---------------------------------------------------------------------------
#: Bir foydalanuvchi ikki murojaat orasida kamida shuncha soniya kutadi
#: (tasodifiy ikki marta bosish / flood to'xtatiladi).
SUPPORT_TICKET_COOLDOWN_SEC = 20.0

#: 24 soat ichida yuborilishi mumkin bo'lgan murojaatlar soni (soft limit).
SUPPORT_TICKET_DAILY_LIMIT = 5

#: Admin rasmi bilan yuborilganda caption chegarasi (Telegram: 1024 belgi).
SUPPORT_CAPTION_LIMIT = 1000

#: Xotiradagi kesh chegarasi (delivery yozuvlari soni).
_DELIVERY_CACHE_MAX = 5000

# ---------------------------------------------------------------------------
# XOTIRADAGI KESHLAR (DB ishlamasa ham oqim davom etadi)
# ---------------------------------------------------------------------------
#: (admin_chat_id, admin_message_id) → murojaat dict'i. DB'dagi
#: ``support_ticket_deliveries`` jadvalining tez nusxasi (bot qayta ishga
#: tushsa kesh bo'shaydi — DB manba bo'lib qoladi).
_ADMIN_DELIVERIES: dict[tuple[int, int], dict] = {}

#: user_id → oxirgi murojaat vaqti (``time.monotonic()``).
_LAST_TICKET_AT: dict[int, float] = {}


def _remember_delivery(admin_chat_id: int, admin_message_id: int, ticket: dict) -> None:
    """Admin xabari ID'sini murojaatga bog'laydi (chegaralangan kesh)."""
    try:
        key = (int(admin_chat_id), int(admin_message_id))
    except (TypeError, ValueError):
        return
    if not key[0] or not key[1]:
        return
    if len(_ADMIN_DELIVERIES) >= _DELIVERY_CACHE_MAX:
        # Eng eski yozuvlarni bo'shatamiz (oddiy FIFO — dict tartibi saqlanadi).
        for old_key in list(_ADMIN_DELIVERIES)[: _DELIVERY_CACHE_MAX // 10 or 1]:
            _ADMIN_DELIVERIES.pop(old_key, None)
    _ADMIN_DELIVERIES[key] = dict(ticket)


def cached_delivery(admin_chat_id: int, admin_message_id: int) -> dict | None:
    """Keshdan murojaatni qaytaradi (tarmoqsiz, sinxron — filtr uchun)."""
    try:
        return _ADMIN_DELIVERIES.get((int(admin_chat_id), int(admin_message_id)))
    except (TypeError, ValueError):
        return None


def reset_support_runtime_state() -> None:
    """Kesh va cooldown'larni tozalaydi (testlar/diagnostika uchun)."""
    _ADMIN_DELIVERIES.clear()
    _LAST_TICKET_AT.clear()


def _remember_ticket_time(user_id: int, when: float | None = None) -> None:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return
    if not uid:
        return
    if len(_LAST_TICKET_AT) > 20000:
        # Xotira cheksiz o'smasin — eng eski yozuvlarni tashlaymiz.
        for old_uid in sorted(_LAST_TICKET_AT, key=_LAST_TICKET_AT.get)[:2000]:
            _LAST_TICKET_AT.pop(old_uid, None)
    _LAST_TICKET_AT[uid] = float(when if when is not None else time.monotonic())


def _cooldown_active(user_id: int) -> bool:
    """Foydalanuvchi juda tez qayta murojaat qilyaptimi (spam himoyasi)."""
    try:
        last = _LAST_TICKET_AT.get(int(user_id))
    except (TypeError, ValueError):
        return False
    if last is None:
        return False
    return (time.monotonic() - last) < SUPPORT_TICKET_COOLDOWN_SEC


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------

async def _safe_lang(context, user_id: int = 0) -> str:
    """Foydalanuvchi tilini xavfsiz aniqlaydi (DB xatosi oqimni yiqitmaydi)."""
    try:
        from handlers.start import ensure_user_lang

        return await ensure_user_lang(context, user_id)
    except Exception:
        logger.debug("Qo'llab-quvvatlash: til aniqlanmadi, kesh/default ishlatiladi")
        return get_lang(context)


def _is_admin(user_id) -> bool:
    """Server-side admin tekshiruvi (payload'ga HECH QACHON ishonilmaydi)."""
    try:
        return int(user_id) in ADMIN_IDS_SET
    except (TypeError, ValueError):
        return False


async def _edit_or_reply(query, text: str, reply_markup=None) -> None:
    """Ekranni tahrirlaydi; iloji bo'lmasa yangi xabar yuboradi (fail-soft)."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return
    except Exception:
        pass
    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        logger.debug("Qo'llab-quvvatlash ekranini ko'rsatib bo'lmadi")


async def _answer(query, text: str = "", alert: bool = False) -> None:
    try:
        await query.answer(text or None, show_alert=alert)
    except Exception:
        pass


async def _reply_text(msg, text: str, reply_markup=None) -> None:
    try:
        await msg.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        logger.debug("Qo'llab-quvvatlash: javob yuborib bo'lmadi")


def _extract_user_meta(user) -> tuple[int, str]:
    """``(user_id, @username yoki ism)`` — admin xabari uchun ko'rsatiladigan nom."""
    user_id = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "").strip().lstrip("@")
    if username:
        return user_id, f"@{username}"
    full_name = str(
        getattr(user, "full_name", None)
        or getattr(user, "first_name", "")
        or ""
    ).strip()
    return user_id, full_name


def _extract_photo_file_id(msg) -> str:
    """Xabardagi eng katta rasmning ``file_id`` si (rasm bo'lmasa — "")."""
    photos = getattr(msg, "photo", None)
    if not photos:
        return ""
    try:
        return str(getattr(photos[-1], "file_id", "") or "")
    except Exception:
        return ""


def has_submittable_content(msg) -> bool:
    """Xabar murojaat sifatida qabul qilinadimi (matn yoki rasm)."""
    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    return bool(text) or bool(_extract_photo_file_id(msg))


def build_admin_ticket_text(ticket: dict, lang: str = "uz") -> str:
    """Adminga yuboriladigan murojaat matnini quradi.

    Shakl (topshiriq bo'yicha)::

        📩 Yangi murojaat!
        👤 Kimdan: @username (ID: <code>123</code>)
        📝 Xabar:
        {matn}

        <i>Javob berish uchun shu xabarga «Reply» …</i>
    """
    handle = str(ticket.get("display_name") or ticket.get("username") or "").strip()
    if handle and not handle.startswith("@") and ticket.get("username"):
        handle = f"@{handle}"
    if not handle:
        handle = support_t("sp_unknown_user", lang)
    body = str(ticket.get("message_text") or "").strip()
    if not body:
        body = support_t("sp_admin_new_no_text", lang)
    key = "sp_admin_photo" if ticket.get("has_media") else "sp_admin_new"
    text = support_t(
        key, lang,
        username=html_escape(handle),
        user_id=int(ticket.get("user_id") or 0),
        message=html_escape(body),
    )
    return f"{text}\n\n{support_t('sp_admin_hint', lang)}"


async def resolve_ticket_by_reply(admin_chat_id: int, admin_message_id: int) -> dict | None:
    """«Reply» kuzatuvi: admin xabari ID'sidan murojaatni topadi.

    Avval xotiradagi kesh (tez), keyin DB (bot qayta ishga tushgan holat).
    """
    cached = cached_delivery(admin_chat_id, admin_message_id)
    if cached is not None:
        return cached
    try:
        import database as db

        ticket = await db.run_db(
            db.get_support_ticket_by_admin_message, admin_chat_id, admin_message_id,
        )
    except Exception as e:
        logger.warning("Qo'llab-quvvatlash: reply kuzatuvi DB'dan o'qilmadi: %s", e)
        return None
    if ticket:
        _remember_delivery(admin_chat_id, admin_message_id, ticket)
    return ticket


# ---------------------------------------------------------------------------
# 1) FOYDALANUVCHI: YAGONA MUROJAAT OQIMI (ONE-TIME TICKET FSM)
# ---------------------------------------------------------------------------

async def support_ticket_entry(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[💬 Qo'llab-quvvatlash] → bir martalik murojaat yo'riqnomasi.

    Ekranda FAQAT bitta talab bor: savolni BITTA xabarda yozish. Holat
    ``SUPPORT_TICKET_INPUT`` ga o'tadi va birinchi xabardan keyin DARHOL
    yopiladi (``support_message_received`` → ``ConversationHandler.END``).
    """
    query = getattr(update, "callback_query", None)
    user = getattr(update, "effective_user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    lang = await _safe_lang(context, user_id)

    # 🧭 Navigatsiya: [◀️ Orqaga] Sozlamalar/Profil hub'iga qaytaradi.
    try:
        from handlers.navigation import remember_section, SECTION_SETTINGS

        remember_section(context, SECTION_SETTINGS)
    except Exception:
        pass

    if query is not None:
        await _answer(query)
        await _edit_or_reply(query, support_t("sp_prompt", lang),
                             get_support_ticket_keyboard(lang))
    else:
        msg = getattr(update, "effective_message", None)
        if msg is not None:
            await _reply_text(msg, support_t("sp_prompt", lang),
                              get_support_ticket_keyboard(lang))
    return SUPPORT_TICKET_INPUT


async def support_back_callback(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[◀️ Orqaga] — murojaat oqimi yopiladi va 👤 Profil hub'i qaytadi."""
    query = getattr(update, "callback_query", None)
    user = getattr(update, "effective_user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    lang = await _safe_lang(context, user_id)
    if query is not None:
        await _answer(query)

    try:
        from handlers.settings import build_settings_hub_text
        from keyboards.inline import get_settings_hub_keyboard

        is_admin = _is_admin(user_id)
        text = await build_settings_hub_text(user_id, lang, is_admin)
        markup = get_settings_hub_keyboard(lang)
    except Exception:
        # Hub chizilmasa ham foydalanuvchi javobsiz qolmaydi: qo'llab-quvvatlash
        # ma'lumot satri + hub'ga qaytish tugmasi ko'rsatiladi (fail-safe).
        from handlers.start import _help_support_line
        from keyboards.inline import get_settings_back_keyboard

        text, markup = _help_support_line(lang), get_settings_back_keyboard(lang)

    if query is not None:
        await _edit_or_reply(query, text, markup)
    return ConversationHandler.END


async def support_message_received(update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Foydalanuvchi murojaatini qabul qiladi va FSM holatini DARHOL yopadi.

    Ketma-ket yozish (spam) oldini olish: qaytariladigan qiymat HAR QANDAY
    holatda ``ConversationHandler.END`` — murojaat adminga yuborilgach yoki
    rad etilgach foydalanuvchi dialogsiz holatga qaytadi.
    """
    msg = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if msg is None or user is None:
        return ConversationHandler.END

    user_id, display_name = _extract_user_meta(user)
    lang = await _safe_lang(context, user_id)

    # --- Kontent tekshiruvi: matn yoki rasm+izoh bo'lishi shart ---
    if not has_submittable_content(msg):
        await _reply_text(msg, support_t("sp_need_text_user", lang))
        return SUPPORT_TICKET_INPUT  # iltimos qilindi — oqim ochiq qoladi

    # --- Anti-spam: qisqa cooldown va kunlik soft-limit ---
    if _cooldown_active(user_id):
        await _reply_text(msg, support_t("sp_cooldown", lang))
        return ConversationHandler.END
    try:
        import database as db

        recent = await db.run_db(db.count_user_support_tickets, user_id, 24)
        if int(recent or 0) >= SUPPORT_TICKET_DAILY_LIMIT:
            await _reply_text(msg, support_t("sp_cooldown", lang))
            return ConversationHandler.END
    except Exception:
        # Hisobni olish imkonsiz bo'lsa — murojaatni TO'XTATMAYMIZ (fail-open).
        logger.debug("Qo'llab-quvvatlash: kunlik limit tekshiruvi o'tkazib yuborildi")

    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    photo_file_id = _extract_photo_file_id(msg)
    ticket = {
        "id": 0,
        "user_id": user_id,
        "username": str(getattr(user, "username", "") or "").strip().lstrip("@"),
        "display_name": display_name,
        "message_text": text,
        "has_media": bool(photo_file_id),
    }

    # --- DB: murojaatni saqlash (fail-soft) ---
    try:
        import database as db

        ticket["id"] = int(await db.run_db(
            db.create_support_ticket, user_id,
            ticket["username"], text, bool(photo_file_id),
        ) or 0)
    except Exception as e:
        logger.error("Qo'llab-quvvatlash: murojaatni saqlab bo'lmadi: %s", e)

    # --- Adminlarga yuborish ---
    delivered = 0
    if ADMIN_IDS_SET:
        delivered = await _deliver_ticket_to_admins(context, ticket, photo_file_id)

    # --- Foydalanuvchiga tasdiq (ROSTGO'Y: yuborilmasa «yetkazildi» deyilmaydi) ---
    if not ADMIN_IDS_SET:
        await _reply_text(msg, support_t("sp_no_admins", lang))
    elif delivered <= 0:
        await _reply_text(msg, support_t("sp_failed", lang))
    else:
        _remember_ticket_time(user_id)
        await _reply_text(msg, support_t("sp_confirm", lang))

    # FSM DARHOL yopiladi: keyingi xabarlar adminga BORMASLIGI kafolatlanadi.
    return ConversationHandler.END


async def _deliver_ticket_to_admins(context, ticket: dict, photo_file_id: str = "") -> int:
    """Murojaatni ``ADMIN_IDS`` ro'yxatidagi HAR BIR adminga yuboradi.

    Qaytadi: muvaffaqiyatli yuborilgan adminlar soni. Har bir yuborilgan
    xabar ID'si murojaatga bog'lanadi (Reply kuzatuvi uchun) — avval keshga,
    so'ngra DB'ga (bot qayta ishga tushganda ham javob to'g'ri manzilga
    yetib borishi uchun).
    """
    delivered = 0
    ticket_id = int(ticket.get("id") or 0)
    for admin_id in sorted(ADMIN_IDS_SET):
        try:
            admin_lang = await _safe_lang(context, admin_id)
            text = build_admin_ticket_text(ticket, admin_lang)
            sent_messages = []
            if photo_file_id and len(text) <= SUPPORT_CAPTION_LIMIT:
                sent_messages.append(await context.bot.send_photo(
                    chat_id=admin_id, photo=photo_file_id, caption=text,
                    parse_mode="HTML",
                ))
            else:
                sent_messages.append(await context.bot.send_message(
                    chat_id=admin_id, text=text, parse_mode="HTML",
                ))
                if photo_file_id:
                    # Uzun izoh caption'ga sig'madi — rasm ALOHIDA, QISQA
                    # izoh bilan yuboriladi (ikkala xabar ham Reply
                    # kuzatuviga ulanadi, murojaat matni to'liq yuqorida).
                    sent_messages.append(await context.bot.send_photo(
                        chat_id=admin_id, photo=photo_file_id,
                        caption=support_t("sp_admin_photo_attached",
                                          admin_lang)[:SUPPORT_CAPTION_LIMIT],
                        parse_mode="HTML",
                    ))
        except Exception as e:
            logger.warning("Murojaatni adminga (%s) yuborishda xato: %s", admin_id, e)
            continue

        delivered += 1
        for sent in sent_messages:
            message_id = int(getattr(sent, "message_id", 0) or 0)
            if not message_id:
                continue
            _remember_delivery(admin_id, message_id, ticket)
            if ticket_id:
                try:
                    import database as db

                    await db.run_db(
                        db.attach_support_ticket_delivery,
                        ticket_id, admin_id, message_id,
                    )
                except Exception as e:
                    logger.debug("Delivery yozuvini saqlab bo'lmadi: %s", e)
    return delivered


# ---------------------------------------------------------------------------
# 2) ADMIN: «REPLY» ORQALI TO'G'RIDAN-TO'G'RI JAVOB (ADMIN REPLY DISPATCHER)
# ---------------------------------------------------------------------------

async def support_admin_reply(update, context: ContextTypes.DEFAULT_TYPE):
    """Admin murojaat xabariga «Reply» yozganda javobni egasiga yetkazadi.

    Oqim::

        admin javobi → (admin_chat_id, reply_to.message_id) → murojaat
                     → foydalanuvchiga «💬 Qo'llab-quvvatlash xizmati javobi:»
                     → adminga «✅ Javob foydalanuvchiga yetkazildi»

    Himoya (fail-closed):
      * ``from_user.id`` server-side tekshiriladi — admin bo'lmasa hech
        qanday amal bajarilmaydi (oddiy foydalanuvchi ta'sir qila olmaydi);
      * murojaatga bog'lanmagan reply — eski xatti-harakat saqlanadi
        (``unknown_message_fallback``), ya'ni boshqa oqim buzilmaydi.
    """
    msg = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if msg is None or user is None:
        return None

    admin_id = int(getattr(user, "id", 0) or 0)
    reply_to = getattr(msg, "reply_to_message", None)
    if reply_to is None or not _is_admin(admin_id):
        return None
    # Ikkinchi qatlam himoya: FAQAT bot bilan SHAXSIY chatdagi reply
    # (guruh/kanal reply'lari hech qachon javob sifatida yetkazilmaydi).
    chat_type = str(getattr(getattr(msg, "chat", None), "type", "") or "")
    if chat_type and chat_type != "private":
        return None

    admin_chat_id = int(getattr(msg, "chat_id", 0) or admin_id)
    reply_message_id = int(getattr(reply_to, "message_id", 0) or 0)
    ticket = await resolve_ticket_by_reply(admin_chat_id, reply_message_id)
    if ticket is None:
        # Bu qo'llab-quvvatlash javobi EMAS — eski xulq (fallback) saqlanadi.
        from handlers import unknown_message_fallback

        return await unknown_message_fallback(update, context)

    lang = await _safe_lang(context, admin_id)
    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    if not text:
        await _reply_text(msg, support_t("sp_need_text", lang))
        return None

    target_user_id = int(ticket.get("user_id") or 0)
    body = f"{support_t('sp_reply_header', lang)}\n\n{html_escape(text)}"
    try:
        await context.bot.send_message(
            chat_id=target_user_id, text=body, parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(
            "Qo'llab-quvvatlash javobini foydalanuvchiga (%s) yetkazib bo'lmadi: %s",
            target_user_id, e,
        )
        await _reply_text(msg, support_t("sp_cannot_deliver", lang))
        return None

    ticket_id = int(ticket.get("id") or 0)
    if ticket_id:
        try:
            import database as db

            await db.run_db(db.mark_support_ticket_answered, ticket_id, admin_id)
        except Exception as e:
            logger.debug("Murojaat holatini yangilab bo'lmadi: %s", e)

    await _reply_text(msg, support_t("sp_admin_delivered", lang))
    return None


__all__ = [
    "SUPPORT_TICKET_INPUT",
    "CB_SUPPORT_BACK",
    "SUPPORT_ADMIN_REPLY_ENABLED",
    "SUPPORT_ADMIN_REPLY_FILTER",
    "SUPPORT_TICKET_COOLDOWN_SEC",
    "SUPPORT_TICKET_DAILY_LIMIT",
    "build_admin_ticket_text",
    "cached_delivery",
    "has_submittable_content",
    "reset_support_runtime_state",
    "resolve_ticket_by_reply",
    "support_admin_reply",
    "support_back_callback",
    "support_message_received",
    "support_ticket_entry",
]
