# -*- coding: utf-8 -*-
"""🚪 SPRINT 4 — YOPIQ BETA DARVOZASI: HANDLER QATLAMI.

Bu modul:
  * ``/start`` ichida chaqiriladigan :func:`enforce_beta_gate` — yangi
    foydalanuvchini darvoza qoidalari bo'yicha kiritadi yoki to'xtatadi
    (mavjud foydalanuvchi va admin HAR DOIM o'tadi);
  * admin uchun ``/beta`` buyrug'i — rejim, o'rinlar, kodlar, navbatdagi
    so'rovlar va tasdiqlash/rad etish.

Barcha matnlar i18n lug'atlaridan (``get_text`` / ``admin_t``) olinadi:
foydalanuvchi xabarlari uning tilida, admin xabarlari admin tilida.
Analitika/DB xatolari hech qachon asosiy oqimni buzdirmaydi (best-effort).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS_SET
from locales.translations import get_lang, get_text
from services import beta_gate as gate_service
from translations import admin_t
from utils.handler_timeout import run_background_task
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# --- /beta buyrug'i yordamchi so'zlari ---
CMD_STATUS = ("", "status", "holat")
CMD_CODE = ("code", "kod", "addcode")
CMD_CODES = ("codes", "kodlar", "list")
CMD_DELCODE = ("delcode", "del", "kodochir")
CMD_APPROVE = ("approve", "tasdiq", "tasdiqlash")
CMD_REJECT = ("reject", "rad", "radetish")
CMD_PENDING = ("pending", "navbat", "kutayotgan")
CMD_ON = ("on", "yoq", "enable")
CMD_OFF = ("off", "och", "disable")
CMD_RESET = ("reset", "env", "avto")


# ---------------------------------------------------------------------------
# Foydalanuvchi xabarlari (i18n)
# ---------------------------------------------------------------------------
#: Qaror sababi → foydalanuvchi xabari kaliti.
_NOTICE_KEYS = {
    gate_service.REASON_PENDING: "beta_pending",
    gate_service.REASON_INVALID_CODE: "beta_invalid_code",
    gate_service.REASON_CODE_EXHAUSTED: "beta_code_used",
    gate_service.REASON_BETA_FULL: "beta_beta_full",
    gate_service.REASON_STORE_ERROR: "beta_pending",
}


def beta_notice(decision: dict, lang: str = "uz") -> str:
    """Qaror sababiga mos foydalanuvchi xabari (uz/ru/en)."""
    reason = str((decision or {}).get("reason") or "")
    key = _NOTICE_KEYS.get(reason, "beta_pending")
    text = get_text(key, lang)
    if not text or text == key:
        text = get_text("beta_pending", lang)
    return text


def extract_invite_code(context) -> str:
    """``/start`` argumentlaridan taklif kodini ajratib oladi.

    ``ref_<id>`` — referal havolasi (o'zgarmaydi), qolgan birinchi argument
    taklif kodi sifatida qaraladi: ``/start BETA-ABC123`` yoki
    ``/start ref_42 BETA-ABC123``.
    """
    try:
        args = list(getattr(context, "args", None) or [])
    except Exception:  # noqa: BLE001
        return ""
    for raw in args:
        token = str(raw or "").strip()
        if not token or token.lower().startswith("ref_"):
            continue
        code = gate_service.normalize_code(token)
        if code:
            return code
    return ""


# ---------------------------------------------------------------------------
# /start uchun darvoza
# ---------------------------------------------------------------------------
async def enforce_beta_gate(update: Update, context: ContextTypes.DEFAULT_TYPE, *,
                            user, is_new: bool, is_admin: bool,
                            invite_code: str = "", gate=None) -> "dict | None":
    """Yangi foydalanuvchi uchun beta darvozasi (``/start`` dan chaqiriladi).

    Returns:
        Qaror lug'ati (``allowed=True``) — davom etish mumkin (eski
        foydalanuvchi / admin / kod / darvoza o'chiq); ``None`` — javob
        yuborildi va ``/start`` to'xtatilishi kerak.
    """
    gate = gate if gate is not None else gate_service.default_gate()
    lang = get_lang(context)
    try:
        decision = gate.check(
            user.id, is_new=is_new, is_admin=is_admin, invite_code=invite_code,
            username=getattr(user, "username", "") or "",
            full_name=getattr(user, "full_name", "") or "",
        )
    except Exception as exc:  # noqa: BLE001 — darvoza xatosi: mavjud oqim uzilmaydi
        log_silent_failure("handlers.beta_access:enforce_beta_gate:state",
                           exc, user_id=getattr(user, "id", None))
        return {"allowed": True, "reason": gate_service.REASON_OPEN,
                "code": None, "seats_left": None, "invite_only": False,
                "attempts": 0}
    if decision.get("allowed"):
        return decision

    try:
        await update.message.reply_text(beta_notice(decision, lang),
                                        parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — javob yuborilmasa ham to'xtatamiz
        log_silent_failure("handlers.beta_access:enforce_beta_gate:reply", exc,
                           user_id=getattr(user, "id", None), lang=lang)

    # Adminga birinchi so'rovdanoq xabar (spam emas: keyingi urinishlar jim).
    if int(decision.get("attempts") or 0) <= 1:
        run_background_task(
            notify_admins_about_request(context, user, decision),
            name=f"beta:request:{getattr(user, 'id', 'unknown')}",
        )
    return None


async def notify_admins_about_request(context, user, decision: dict) -> None:
    """Yangi beta so'rovi haqida barcha adminlarga xabar (best-effort)."""
    for admin_id in ADMIN_IDS_SET:
        if admin_id == getattr(user, "id", None):
            continue
        try:
            from database import run_db, get_user_language

            admin_lang = await run_db(get_user_language, admin_id)
            text = admin_t(
                "beta_admin_new_request", admin_lang or "uz",
                user_id=getattr(user, "id", ""),
                username=(f"@{user.username}" if getattr(user, "username", "")
                          else str(getattr(user, "id", ""))),
                code=str(decision.get("code") or "—"),
                reason=str(decision.get("reason") or ""),
            )
            await context.bot.send_message(chat_id=admin_id, text=text,
                                           parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — bitta admin xatosi boshqasini to'xtatmaydi
            log_silent_failure("handlers.beta_access:notify_admins", exc,
                               user_id=admin_id)


# ---------------------------------------------------------------------------
# /beta — admin buyrug'i
# ---------------------------------------------------------------------------
def _is_admin(user_id) -> bool:
    if user_id in ADMIN_IDS_SET:
        return True
    try:
        from services.rbac_service import is_admin as rbac_is_admin

        return bool(rbac_is_admin(user_id))
    except Exception:  # pragma: no cover — RBAC xatosi
        return False


def _status_text(gate, lang: str) -> str:
    status = gate.status()
    mode_key = "beta_admin_mode_on" if status["invite_only"] else "beta_admin_mode_off"
    seats = ("∞" if status["seats_left"] is None
             else f"{status['seats_used']}/{status['max_users']}")
    return (
        admin_t("beta_admin_title", lang) + "\n"
        + "━━━━━━━━━━━━━━━\n"
        + admin_t(mode_key, lang) + "\n"
        + admin_t("beta_admin_source", lang, source=status["enabled_source"]) + "\n"
        + admin_t("beta_admin_seats", lang, seats=seats,
                  pending=status["pending"]) + "\n"
        + admin_t("beta_admin_codes", lang, codes=status["codes"],
                  active=len(status["active_codes"])) + "\n\n"
        + admin_t("beta_admin_usage", lang)
    )


async def _reply(update, text: str) -> None:
    try:
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log_silent_failure("handlers.beta_access:reply", exc)


async def beta_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``/beta`` — yopiq beta darvozasini boshqarish (faqat admin).

    Ishlatilishi::

        /beta                      → holat
        /beta code [KOD] [N] [izoh]→ kod yaratish (N — nechta foydalanish)
        /beta codes                → kodlar ro'yxati
        /beta delcode KOD          → kodni o'chirish
        /beta pending              → navbatdagi so'rovlar
        /beta approve <user_id>    → tasdiqlash
        /beta reject <user_id>     → rad etish
        /beta on | off | reset     → runtime rejim (env'ga qaytish — reset)
    """
    user = update.effective_user
    if not _is_admin(getattr(user, "id", None)):
        return
    lang = get_lang(context)
    gate = gate_service.default_gate()
    args = [str(a or "").strip() for a in (getattr(context, "args", None) or [])]
    action = args[0].lower() if args else ""
    rest = args[1:]

    try:
        if action in CMD_CODE:
            code = rest[0] if rest and not rest[0].isdigit() else None
            max_uses = gate_service.DEFAULT_CODE_USES
            for token in rest:
                if token.isdigit():
                    max_uses = int(token)
                    break
            note = " ".join(t for t in rest
                            if t != code and not t.isdigit())[:120]
            created = gate.add_code(code, max_uses=max_uses,
                                    created_by=user.id, note=note)
            if not created:
                await _reply(update, admin_t("beta_admin_code_exists", lang,
                                             code=gate_service.normalize_code(code or "")))
                return
            await _reply(update, admin_t(
                "beta_admin_code_created", lang, code=created["code"],
                uses=created["max_uses"]))
            return

        if action in CMD_CODES:
            codes = gate.list_codes()
            if not codes:
                await _reply(update, admin_t("beta_admin_codes_empty", lang))
                return
            lines = [admin_t("beta_admin_codes_title", lang)]
            for code, meta in sorted(codes.items()):
                meta = meta or {}
                lines.append(admin_t(
                    "beta_admin_code_row", lang, code=code,
                    used=int(meta.get("uses", 0)), total=int(meta.get("max_uses", 1)),
                    note=str(meta.get("note") or "—")))
            await _reply(update, "\n".join(lines))
            return

        if action in CMD_DELCODE:
            if not rest:
                await _reply(update, admin_t("beta_admin_usage", lang))
                return
            if gate.revoke_code(rest[0]):
                await _reply(update, admin_t("beta_admin_code_deleted", lang,
                                             code=gate_service.normalize_code(rest[0])))
            else:
                await _reply(update, admin_t("beta_admin_code_missing", lang,
                                             code=gate_service.normalize_code(rest[0])))
            return

        if action in CMD_PENDING:
            pending = gate.pending_users()
            if not pending:
                await _reply(update, admin_t("beta_admin_pending_empty", lang))
                return
            lines = [admin_t("beta_admin_pending_title", lang,
                             count=len(pending))]
            for uid, meta in sorted(pending.items(),
                                    key=lambda item: str((item[1] or {}).get("requested_at") or "")):
                meta = meta or {}
                lines.append(admin_t(
                    "beta_admin_pending_row", lang, user_id=uid,
                    username=str(meta.get("username") or "—"),
                    attempts=int(meta.get("attempts") or 0)))
            lines.append(admin_t("beta_admin_pending_hint", lang))
            await _reply(update, "\n".join(lines))
            return

        if action in CMD_APPROVE or action in CMD_REJECT:
            if not rest or not rest[0].lstrip("-").isdigit():
                await _reply(update, admin_t("beta_admin_usage", lang))
                return
            target = int(rest[0])
            if action in CMD_APPROVE:
                ok = gate.approve(target, approved_by=user.id, source="admin")
                if not ok:
                    await _reply(update, admin_t("beta_admin_store_error", lang))
                    return
                await _reply(update, admin_t("beta_admin_approved", lang,
                                             user_id=target))
                run_background_task(
                    notify_user_approved(context, target),
                    name=f"beta:approved:{target}",
                )
            else:
                ok = gate.reject(target, reason=" ".join(rest[1:])[:120])
                await _reply(update, admin_t(
                    "beta_admin_rejected" if ok else "beta_admin_reject_missing",
                    lang, user_id=target))
            return

        if action in CMD_ON or action in CMD_OFF:
            enabled = action in CMD_ON
            if not gate.set_enabled(enabled):
                await _reply(update, admin_t("beta_admin_store_error", lang))
                return
            await _reply(update, admin_t(
                "beta_admin_mode_changed" if enabled else "beta_admin_mode_changed_off",
                lang))
            return

        if action in CMD_RESET:
            if not gate.set_enabled(None):
                await _reply(update, admin_t("beta_admin_store_error", lang))
                return
            await _reply(update, admin_t("beta_admin_mode_env", lang))
            return

        if action and action not in CMD_STATUS:
            await _reply(update, admin_t("beta_admin_usage", lang))
            return

        await _reply(update, _status_text(gate, lang))
    except Exception as exc:  # noqa: BLE001 — admin buyrug'i botni yiqitmaydi
        log_silent_failure("handlers.beta_access:beta_admin_command", exc,
                           user_id=getattr(user, "id", None), lang=lang)
        await _reply(update, admin_t("beta_admin_store_error", lang))


async def notify_user_approved(context, user_id: int) -> None:
    """Tasdiqlangan foydalanuvchiga xabar (best-effort, uning tilida)."""
    try:
        from database import run_db, get_user_language

        lang = await run_db(get_user_language, user_id)
        await context.bot.send_message(
            chat_id=user_id,
            text=get_text("beta_approved_notice", lang or "uz"),
            parse_mode="HTML",
        )
    except Exception as exc:  # noqa: BLE001 — foydalanuvchi botni bloklagan bo'lishi mumkin
        log_silent_failure("handlers.beta_access:notify_user_approved", exc,
                           user_id=user_id)


__all__ = [
    "beta_admin_command",
    "beta_notice",
    "enforce_beta_gate",
    "extract_invite_code",
    "notify_admins_about_request",
    "notify_user_approved",
]
