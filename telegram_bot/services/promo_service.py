"""PromoService — promo-kod biznes mantiq.

Yaratish, faollashtirish (race-condition safe) va statistika.
DB CRUD qismlari ``database`` modulida qoladi.

Foydalanish::

    from services.promo_service import PromoService
    ok = PromoService.create_promo("KOD30", 30, 50)
    success, msg = PromoService.redeem_promo(user_id, "KOD30")
"""

import logging
from contextlib import contextmanager

from database import (
    db_cursor,
    _invalidate_user,
    _cache_clear,
)
# 6-bosqich: admin harakatlari auditi (promo-kod yaratish).
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


@contextmanager
def transaction(commit: bool = True):
    """Promo oqimi uchun BITTA atomik tranzaksiya bloki (5-bosqich).

    ``database.transaction()`` bilan bir xil semantika: blok ichidagi
    redemption + obuna + hisoblagich yozuvlari birga COMMIT yoki birga
    ROLLBACK bo'ladi.
    """
    with db_cursor(commit=commit) as cur:
        yield cur


class PromoService:
    """Promo-kodlarni boshqarish: create, redeem, stats."""

    # ──────────────────────────────────────────────────────────────
    # CREATE_PROMO — promo-kod yaratish (admin)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def create_promo(
        code: str,
        duration_days: int = 30,
        max_uses: int = None,
        expires_at=None,
        plan_type: str = "pro",
        admin_id: int = None,
    ) -> bool:
        """Yangi promo-kod yaratadi.

        Args:
            code: Promo-kod nomi (katta harflarga o'giriladi).
            duration_days: Obuna muddati (kun).
            max_uses: Maksimal ishlatish soni (None = cheksiz).
            expires_at: Amal qilish muddati (datetime, ixtiyoriy).
            plan_type: Beriladigan tarif (default: "pro").
            admin_id: (6-bosqich) kodni yaratgan admin — berilsa harakat
                ``admin_audit_logs`` jadvaliga SHU tranzaksiyada yoziladi.
        """
        code = (code or "").strip().upper()
        if not code:
            return False
        try:
            duration = int(duration_days)
        except (TypeError, ValueError):
            return False
        if duration <= 0:
            return False

        uses = None
        if max_uses is not None:
            try:
                uses = int(max_uses)
                if uses <= 0:
                    return False
            except (TypeError, ValueError):
                return False

        try:
            with transaction() as cur:
                cur.execute(
                    "INSERT INTO promo_codes (code, plan_type, duration_days, max_uses, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING",
                    (code, plan_type, duration, uses, expires_at),
                )
                inserted = cur.rowcount > 0
                if inserted and admin_id is not None:
                    # 6-bosqich: audit yozuvi SHU tranzaksiyada (atomik) —
                    # kod yaratildi, lekin audit yozuvi yo'q qolmaydi.
                    AuditService.log_promo_creation(
                        admin_id, code, duration_days=duration,
                        max_uses=uses, plan_type=plan_type, cur=cur,
                    )
                return inserted
        except Exception as e:
            logger.error("PromoService.create_promo xatosi: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────
    # REDEEM_PROMO — promo-kodni faollashtirish (race-condition safe)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def redeem_promo(user_id: int, code: str) -> tuple:
        """Promo-kodni bir marta, race-free tarzda faollashtiradi.

        Qoidalar:
          1) Promo ``FOR UPDATE`` bilan qulflanadi — parallel
             redemption'lar navbat bilan o'tadi.
          2) ``current_uses`` tekshiruvi va increment bitta tranzaksiyada.
          3) ``promo_redemptions`` UNIQUE(promo_id, user_id) — bir user
             bir promo-kodni faqat 1 marta ishlatadi.
          4) ``expires_at`` tekshiruvi (muddati o'tganmi?).
          5) ``is_active`` tekshiruvi (o'chirilganmi?).

        Returns: ``(success: bool, message: str)``
        """
        code = (code or "").strip().upper()
        if not code:
            return False, "Promo-kod kiritilmadi."
        try:
            # 5-bosqich: tekshiruv + redemption + obuna + hisoblagich —
            # hammasi BITTA atomik blokda (transaction).
            with transaction() as cur:
                # FOR UPDATE — boshqa tranzaksiya shu qatorni o'zgartira olmaydi
                cur.execute(
                    "SELECT id, plan_type, duration_days, max_uses, current_uses, "
                    "is_active, expires_at "
                    "FROM promo_codes WHERE code = %s FOR UPDATE",
                    (code,),
                )
                row = cur.fetchone()
                if not row:
                    return False, "Promo-kod topilmadi."

                promo_id, plan_type, duration_days, max_uses, current_uses, is_active, expires_at = row

                # 1) Faollik
                if not is_active:
                    return False, "Bu promo-kod o'chirilgan."

                # 2) Muddat
                if expires_at is not None:
                    cur.execute("SELECT (%s <= NOW())", (expires_at,))
                    if cur.fetchone()[0]:
                        return False, "Bu promo-kod muddati o'tgan."

                # 3) Ishlatish limiti
                if max_uses is not None and (current_uses or 0) >= max_uses:
                    return False, "Bu promo-kod ishlatib bo'lingan."

                # 4) Atomik yozuv (UNIQUE constraint himoya qiladi)
                cur.execute(
                    "INSERT INTO promo_redemptions (promo_id, user_id) "
                    "VALUES (%s, %s) ON CONFLICT (promo_id, user_id) DO NOTHING "
                    "RETURNING id",
                    (promo_id, user_id),
                )
                redemption = cur.fetchone()
                if not redemption:
                    return False, "Siz bu promo-kodni avval ishlatgansiz."

                # 5) Obuna berish: max(current_expiry, NOW()) + days
                cur.execute(
                    "UPDATE users SET plan_type = %s, "
                    "subscription_expires_at = GREATEST("
                    "COALESCE(subscription_expires_at, NOW()), NOW()) "
                    "+ (%s || ' days')::INTERVAL "
                    "WHERE user_id = %s",
                    (plan_type, str(duration_days), user_id),
                )
                if cur.rowcount == 0:
                    return False, "Foydalanuvchi topilmadi."

                # 6) Hisoblagichni oshirish
                cur.execute(
                    "UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = %s",
                    (promo_id,),
                )

            _invalidate_user(user_id)
            _cache_clear("system_stats")
            _cache_clear("admin_dashboard_stats")
            return True, f"Promo-kod faollashtirildi! {duration_days} kunlik {plan_type.upper()} tarif yoqildi."
        except Exception as e:
            logger.error("PromoService.redeem_promo xatosi: %s", e)
            return False, "Xatolik yuz berdi."

    # ──────────────────────────────────────────────────────────────
    # GET_PROMO_STATS — promo-kod statistikasi
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_promo_stats(code: str) -> dict:
        """Promo-kod statistikasini qaytaradi.

        Returns::

            {
                "code": str,
                "plan_type": str,
                "duration_days": int,
                "max_uses": int | None,
                "current_uses": int,
                "is_active": bool,
                "expires_at": datetime | None,
                "remaining_uses": int | None,   # None = cheksiz
            }
            yoki promo topilmaganida ``{}``.
        """
        code = (code or "").strip().upper()
        if not code:
            return {}
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT code, plan_type, duration_days, max_uses, "
                    "current_uses, is_active, expires_at "
                    "FROM promo_codes WHERE code = %s",
                    (code,),
                )
                row = cur.fetchone()
            if not row:
                return {}
            code_val, plan_type, duration, max_uses, current, is_active, expires_at = row
            remaining = None
            if max_uses is not None:
                remaining = max(0, max_uses - (current or 0))
            return {
                "code": code_val,
                "plan_type": plan_type,
                "duration_days": duration,
                "max_uses": max_uses,
                "current_uses": current or 0,
                "is_active": bool(is_active),
                "expires_at": expires_at,
                "remaining_uses": remaining,
            }
        except Exception as e:
            logger.error("PromoService.get_promo_stats xatosi: %s", e)
            return {}
