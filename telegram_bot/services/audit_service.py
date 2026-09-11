"""AuditService — PostAssist V2 (6-bosqich): admin harakatlari auditi.

Har bir muhim admin amali ``admin_audit_logs`` jadvaliga yoziladi:

* chekni tasdiqlash / rad etish (``receipt_approve`` / ``receipt_reject``);
* PRO berish / bekor qilish (``grant_pro`` / ``revoke_pro``);
* promo-kod yaratish (``create_promo``);
* rol berish / olish (``set_role`` / ``remove_role``);
* tizim sozlamalari va broadcast (``system_settings`` / ``broadcast``).

**Atomiklik.** ``log_action(..., cur=cur)`` shaklida chaqirilganda yozuv
chaqiruvchining tranzaksiyasida bajariladi: biznes amali bilan audit yozuvi
birga COMMIT yoki birga ROLLBACK bo'ladi — "amal bajarildi, lekin audit
yozuvi yo'q" holati mumkin emas. Shunday chaqiruvda xatolik yutilmaydi
(tranzaksiya egasi o'zi hal qiladi); mustaqil chaqiruvda esa xato logga
yozilib ``False`` qaytariladi va bot ishlashda davom etadi.

Foydalanish::

    from services.audit_service import AuditService, ACTION_RECEIPT_APPROVE

    # Tranzaksiya ichida (atomik):
    with transaction() as cur:
        cur.execute("UPDATE payment_receipts SET status = 'approved' ...")
        AuditService.log_action(admin_id, ACTION_RECEIPT_APPROVE,
                                target_type="payment_receipt", target_id=receipt_id,
                                new_value={"status": "approved"}, cur=cur)

    # Mustaqil:
    AuditService.log_action(admin_id, ACTION_BROADCAST, new_value={"sent": 100})
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import database as db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Amal nomlari (VARCHAR(64) — chegaradan oshmasligi shart)
# ──────────────────────────────────────────────────────────────
ACTION_RECEIPT_APPROVE = "receipt_approve"
ACTION_RECEIPT_REJECT = "receipt_reject"
ACTION_GRANT_PRO = "grant_pro"
ACTION_REVOKE_PRO = "revoke_pro"
ACTION_CREATE_PROMO = "create_promo"
ACTION_SET_ROLE = "set_role"
ACTION_REMOVE_ROLE = "remove_role"
ACTION_SYSTEM_SETTINGS = "system_settings"
ACTION_BROADCAST = "broadcast"
ACTION_AD_UPDATE = "ad_update"
ACTION_SPONSOR_UPDATE = "sponsor_update"

#: Ma'lum amallar ro'yxati (testlar/UI filtrlari uchun).
KNOWN_ACTIONS = (
    ACTION_RECEIPT_APPROVE, ACTION_RECEIPT_REJECT, ACTION_GRANT_PRO,
    ACTION_REVOKE_PRO, ACTION_CREATE_PROMO, ACTION_SET_ROLE,
    ACTION_REMOVE_ROLE, ACTION_SYSTEM_SETTINGS, ACTION_BROADCAST,
    ACTION_AD_UPDATE, ACTION_SPONSOR_UPDATE,
)

MAX_ACTION_LEN = 64
MAX_FIELD_LEN = 64
MAX_JSON_CHARS = 20000


def _as_int(value):
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip(value, limit: int = MAX_FIELD_LEN):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _json_default(value):
    """``json.dumps`` uchun standart bo'lmagan turlar (set/tuple/sana)."""
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _jsonable(value):
    """JSONB ustunga sig'adigan qiymatga o'giradi (serializatsiya xavfsiz)."""
    if value is None:
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=_json_default)
    except Exception:  # pragma: no cover - ekzotik obyektlar
        encoded = json.dumps({"_repr": str(value)}, ensure_ascii=False)
    if len(encoded) > MAX_JSON_CHARS:
        encoded = json.dumps(
            {"_truncated": True, "data": encoded[:MAX_JSON_CHARS]},
            ensure_ascii=False,
        )
    return json.loads(encoded)


class AuditService:
    """Admin harakatlarini qayd etish va o'qish."""

    # ──────────────────────────────────────────────────────────
    # YOZISH
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def log_action(
        admin_id,
        action,
        target_type=None,
        target_id=None,
        old_value=None,
        new_value=None,
        ip_or_metadata=None,
        cur=None,
        strict=None,
    ) -> bool:
        """Bitta admin harakatini audit jadvaliga yozadi.

        Args:
            admin_id: harakatni bajargan admin (Telegram user ID).
            action: qisqa amal nomi (``receipt_approve``, ...) — 64 belgi.
            target_type: obyekt turi (``payment_receipt``, ``user``, ...).
            target_id: obyekt ID (matn ko'rinishida saqlanadi).
            old_value/new_value: o'zgarishdan oldingi/keyingi holat (JSONB).
            ip_or_metadata: qo'shimcha kontekst (JSONB).
            cur: mavjud tranzaksiya kursori — berilsa yozuv SHU tranzaksiyada
                bajariladi (atomiklik kafolati).
            strict: ``True`` — xatoni yutmay, tashqariga ko'taradi.
                ``None`` (default) — ``cur`` berilgan bo'lsa ko'taradi.

        Returns:
            bool: yozuv qo'shildimi.
        """
        actor = _as_int(admin_id)
        if actor is None or actor <= 0:
            logger.debug("Audit yozuvi rad etildi: noto'g'ri admin_id=%r", admin_id)
            return False

        act = _clip(action, MAX_ACTION_LEN)
        if not act:
            logger.debug("Audit yozuvi rad etildi: bo'sh action")
            return False

        # Har bir yozuvda kamida "logged_at" bo'ladi (JSONB metadata).
        raw_metadata = _jsonable(ip_or_metadata)
        if isinstance(raw_metadata, dict):
            metadata = dict(raw_metadata)
        elif raw_metadata is None:
            metadata = {}
        else:
            metadata = {"data": raw_metadata}
        metadata.setdefault(
            "logged_at", datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

        strict = bool(cur is not None) if strict is None else bool(strict)

        try:
            return db.log_admin_action(
                actor,
                act,
                target_type=_clip(target_type),
                target_id=_clip(target_id),
                old_value=_jsonable(old_value),
                new_value=_jsonable(new_value),
                ip_or_metadata=metadata,
                cur=cur,
            )
        except Exception as e:
            if strict:
                # Tranzaksiya ichida — xatoni yuqoriga uzatamiz (ROLLBACK uchun).
                raise
            logger.warning("Audit yozuvi qo'shilmadi (%s / %s): %s", actor, act, e)
            return False

    # ──────────────────────────────────────────────────────────
    # TAYYOR YORDAMCHILAR (aniq domen amallari)
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def log_receipt_decision(admin_id, receipt_id, approved, user_id=None,
                             days=None, old_status="pending", cur=None) -> bool:
        """Chekni tasdiqlash/rad etish harakatini yozadi."""
        status = "approved" if approved else "rejected"
        action = ACTION_RECEIPT_APPROVE if approved else ACTION_RECEIPT_REJECT
        new_value = {"status": status, "user_id": _as_int(user_id)}
        if approved:
            new_value["days_granted"] = _as_int(days)
        return AuditService.log_action(
            admin_id,
            action,
            target_type="payment_receipt",
            target_id=receipt_id,
            old_value={"status": old_status},
            new_value=new_value,
            cur=cur,
        )

    @staticmethod
    def log_pro_grant(admin_id, target_user_id, days, plan="pro", cur=None) -> bool:
        """PRO berish harakatini yozadi."""
        return AuditService.log_action(
            admin_id,
            ACTION_GRANT_PRO,
            target_type="user",
            target_id=target_user_id,
            new_value={"plan": plan, "days": _as_int(days)},
            cur=cur,
        )

    @staticmethod
    def log_pro_revoke(admin_id, target_user_id, old_plan=None, cur=None) -> bool:
        """PRO bekor qilish harakatini yozadi."""
        return AuditService.log_action(
            admin_id,
            ACTION_REVOKE_PRO,
            target_type="user",
            target_id=target_user_id,
            old_value={"plan": old_plan},
            new_value={"plan": "free"},
            cur=cur,
        )

    @staticmethod
    def log_promo_creation(admin_id, code, duration_days=None, max_uses=None,
                           plan_type="pro", cur=None) -> bool:
        """Promo-kod yaratish harakatini yozadi."""
        return AuditService.log_action(
            admin_id,
            ACTION_CREATE_PROMO,
            target_type="promo_code",
            target_id=code,
            new_value={
                "code": code,
                "plan_type": plan_type,
                "duration_days": _as_int(duration_days),
                "max_uses": _as_int(max_uses),
            },
            cur=cur,
        )

    @staticmethod
    def log_system_settings(admin_id, key, old_value=None, new_value=None,
                            cur=None) -> bool:
        """Tizim sozlamasi o'zgarishini yozadi."""
        return AuditService.log_action(
            admin_id,
            ACTION_SYSTEM_SETTINGS,
            target_type="system_settings",
            target_id=key,
            old_value=old_value,
            new_value=new_value,
            cur=cur,
        )

    # ──────────────────────────────────────────────────────────
    # O'QISH
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def recent(limit: int = 50, admin_id=None, action=None) -> list:
        """Oxirgi audit yozuvlari (eng yangisi birinchi)."""
        return db.get_admin_audit_logs(limit=limit, admin_id=admin_id, action=action)

    @staticmethod
    def count(admin_id=None, action=None) -> int:
        """Audit yozuvlari soni (filtrlar ixtiyoriy)."""
        return db.count_admin_audit_logs(admin_id=admin_id, action=action)

    # ──────────────────────────────────────────────────────────
    # ASYNC ORAMI (handler'lar uchun)
    # ──────────────────────────────────────────────────────────
    @staticmethod
    async def log_action_async(admin_id, action, **kwargs) -> bool:
        """``log_action`` ni ``run_db`` orqali chaqiradi (event loop bloklanmaydi)."""
        return await db.run_db(AuditService.log_action, admin_id, action, **kwargs)


#: Modul darajasidagi qisqa aliaslar.
log_action = AuditService.log_action
recent_actions = AuditService.recent
count_actions = AuditService.count
