"""Faol ConversationHandler holatini topish uchun yagona yordamchi.

Nima uchun kerak:
    PTB semantikasida bitta guruh (default group 0) ichida xabarni FAQAT
    BIRINCHI mos kelgan handler qayta ishlaydi. ``ConversationHandler``
    foydalanuvchi dialog ICHIDA bo'lib, xabar joriy holat handlerlariga mos
    kelmasa (va fallback'larga ham mos kelmasa) ``check_update`` dan ``None``
    qaytaradi — shunda update guruhdagi KEYINGI handlerlarga (masalan, global
    rasm handleriga) o'tib ketadi. Shu sababli "global" media handlerlar
    ishga tushishdan oldin foydalanuvchi AYNI QAYSI dialog holatida ekanini
    bilishi shart — aks holda (eski xato) yangi post jarayonidagi albom
    rasmlari "📸 Rasmingiz adminga yuborildi" spami bilan adminga yuborilib
    ketardi.

    Bu funksiya Application'dagi barcha ConversationHandler'larning ichki
    ``_conversations`` xaritasini o'qib, foydalanuvchi/chat uchun joriy
    holatni qaytaradi. Ichki atributlar PTB 13–22 oralig'ida barqaror;
    mavjud bo'lmasa (yoki biron xato chiqsa) "dialogda emas" (None) deb
    hisoblanadi — fail-safe yo'nalish.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def active_conversation_state(application, update):
    """Foydalanuvchi hozir biror ConversationHandler dialogi ICHIDA bo'lsa —
    uning joriy holatini, aks holda ``None`` qaytaradi.

    ``application`` yoki ``update`` mavjud bo'lmasa (masalan, handler to'g'ridan
    test qilinayotganda) ``None`` qaytadi.
    """
    if application is None or update is None:
        return None
    handlers = getattr(application, "handlers", None) or {}
    if not handlers:
        return None
    try:
        from telegram.ext import ConversationHandler
    except Exception:
        return None
    try:
        groups = sorted(handlers)
    except Exception:
        groups = list(handlers)
    for group in groups:
        for handler in handlers.get(group) or ():
            if not isinstance(handler, ConversationHandler):
                continue
            try:
                key = handler._get_key(update)
                state = handler._conversations.get(key)
            except Exception:
                continue
            if state is not None:
                return state
    return None
