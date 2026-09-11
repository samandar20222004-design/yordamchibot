"""SubscriptionService — obuna boshqaruvi biznes mantiq.

Tariflar, muddat hisoblash, PRO tekshiruvi va admin bonus.
DB CRUD qismlari ``database`` modulida qoladi; bu servis faqat
biznes qoidlarni bajaradi va database funksiyalarini chaqiradi.

Foydalanish::

    from services.subscription_service import SubscriptionService
    ok = SubscriptionService.activate(user_id, "pro", 30)
"""

import logging
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2

from database import (
    db_cursor,
    PLAN_LIMITS,
    FREE_QUEUE_MAX_POSTS,
    _invalidate_user,
    _cache_clear,
    _ensure_limit_reset,
    _normalize_language_code,
)

logger = logging.getLogger(__name__)


@contextmanager
def transaction(commit: bool = True):
    """Obuna oqimi uchun BITTA atomik tranzaksiya bloki (5-bosqich).

    ``database.transaction()`` bilan bir xil semantika (blok oxirida COMMIT,
    istisnoda ROLLBACK). Sinkron servis kodi uchun ``db_cursor`` primitivi
    ustida qurilgan — testlar shu nuqtani mock qiladi.
    """
    with db_cursor(commit=commit) as cur:
        yield cur


class SubscriptionService:
    """Obuna boshqaruvi: activate, extend, get_status, grant, revoke."""

    # ──────────────────────────────────────────────────────────────
    # ACTIVATE — yangi obuna berish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def activate(user_id: int, plan: str = "pro", duration_days: int = 30) -> bool:
        """Foydalanuvchiga obuna beradi (yoki yangilaydi).

        Qoida: ``subscription_expires_at = max(current_expiry, NOW()) + days``.
        Agar foydalanuvchining allaqachon faol obunasi bo'lsa — qolgan
        muddat kuyib ketmaydi, yangi muddat qo'shiladi.
        """
        if plan not in PLAN_LIMITS:
            return False
        try:
            days = int(duration_days)
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            return False
        try:
            # Tarif + muddat BITTA blokda yangilanadi (5-bosqich).
            with transaction() as cur:
                cur.execute(
                    "UPDATE users SET plan_type = %s, "
                    "subscription_expires_at = GREATEST("
                    "COALESCE(subscription_expires_at, NOW()), NOW()) "
                    "+ (%s || ' days')::INTERVAL "
                    "WHERE user_id = %s",
                    (plan, str(days), user_id),
                )
                updated = cur.rowcount > 0
            if updated:
                _invalidate_user(user_id)
                _cache_clear("system_stats")
                _cache_clear("admin_dashboard_stats")
            return updated
        except Exception as e:
            logger.error("SubscriptionService.activate xatosi: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────
    # EXTEND — muddatni uzaytirish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def extend(user_id: int, duration_days: int = 30) -> bool:
        """Mavjud obuna muddatini uzaytiradi (plan o'zgarmaydi).

        Formula: ``max(current_expiry, NOW()) + duration_days``.
        """
        try:
            days = int(duration_days)
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            return False
        try:
            # Muddat uzaytirish — atomik (fallback/parallel chaqiruvlar
            # bir-birini ustma-ust yozib qolmasligi uchun bitta blok).
            with transaction() as cur:
                cur.execute(
                    "UPDATE users SET "
                    "subscription_expires_at = GREATEST("
                    "COALESCE(subscription_expires_at, NOW()), NOW()) "
                    "+ (%s || ' days')::INTERVAL "
                    "WHERE user_id = %s",
                    (str(days), user_id),
                )
                updated = cur.rowcount > 0
            if updated:
                _invalidate_user(user_id)
                _cache_clear("system_stats")
            return updated
        except Exception as e:
            logger.error("SubscriptionService.extend xatosi: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────
    # GET_STATUS — obuna holati
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_status(user_id: int) -> dict:
        """Foydalanuvchi obuna holatini qaytaradi.

        Returns::

            {
                "is_pro": bool,
                "plan_type": str,        # "free" | "pro" | "enterprise"
                "remaining_days": int,   # -1 = cheksiz (enterprise)
                "expiry_date": datetime | None,
            }
        """
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT plan_type, subscription_expires_at "
                    "FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
            if not row:
                return {
                    "is_pro": False,
                    "plan_type": "free",
                    "remaining_days": 0,
                    "expiry_date": None,
                }
            plan_type, expires_at = row
            plan_type = plan_type or "free"
            if plan_type in ("pro", "enterprise"):
                if expires_at is None:
                    # Cheksiz (enterprise yoki legacy)
                    return {
                        "is_pro": True,
                        "plan_type": plan_type,
                        "remaining_days": -1,
                        "expiry_date": None,
                    }
                now = datetime.now(timezone.utc)
                if expires_at > now:
                    remaining = (expires_at - now).days
                    return {
                        "is_pro": True,
                        "plan_type": plan_type,
                        "remaining_days": max(0, remaining),
                        "expiry_date": expires_at,
                    }
                # Muddat o'tgan — free ga tushiramiz
                try:
                    with db_cursor(commit=True) as wcur:
                        wcur.execute(
                            "UPDATE users SET plan_type = 'free' WHERE user_id = %s",
                            (user_id,),
                        )
                except Exception:
                    pass
                return {
                    "is_pro": False,
                    "plan_type": "free",
                    "remaining_days": 0,
                    "expiry_date": expires_at,
                }
            return {
                "is_pro": False,
                "plan_type": plan_type,
                "remaining_days": 0,
                "expiry_date": None,
            }
        except Exception as e:
            logger.error("SubscriptionService.get_status xatosi: %s", e)
            return {
                "is_pro": False,
                "plan_type": "free",
                "remaining_days": 0,
                "expiry_date": None,
            }

    # ──────────────────────────────────────────────────────────────
    # GRANT_ADMIN_BONUS — admin tomonidan bonus berish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def grant_admin_bonus(user_id: int, days: int, admin_id: int) -> bool:
        """Admin tomonidan PRO bonus berish (audit logging bilan).

        ``activate`` dan farqi: admin_id qo'shimcha audit uchun.
        """
        if not isinstance(days, int) or days <= 0:
            return False
        result = SubscriptionService.activate(user_id, "pro", days)
        if result:
            logger.info(
                "Admin %s foydalanuvchiga %s kunlik PRO berdi (user=%s)",
                admin_id, days, user_id,
            )
        return result

    # ──────────────────────────────────────────────────────────────
    # REVOKE — obunani bekor qilish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def revoke(user_id: int) -> bool:
        """Foydalanuvchi obunasini bekor qiladi (free ga qaytaradi)."""
        try:
            with transaction() as cur:
                cur.execute(
                    "UPDATE users SET plan_type = 'free', "
                    "subscription_expires_at = NULL "
                    "WHERE user_id = %s",
                    (user_id,),
                )
                updated = cur.rowcount > 0
            if updated:
                _invalidate_user(user_id)
                _cache_clear("system_stats")
            return updated
        except Exception as e:
            logger.error("SubscriptionService.revoke xatosi: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────
    # YORDAMCHI — is_premium tekshiruvi (backwards-compatible)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def is_premium(user_id: int) -> bool:
        """Foydalanuvchi PRO yoki Enterprise ekanligini tekshiradi."""
        status = SubscriptionService.get_status(user_id)
        return status["is_pro"]

    # ──────────────────────────────────────────────────────────────
    # YORDAMCHI — get_user_plan (backwards-compatible)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_user_plan(user_id: int) -> dict:
        """Foydalanuvchi obuna ma'lumotlarini qaytaradi (eski API mos)."""
        try:
            with db_cursor() as cur:
                _ensure_limit_reset(cur, user_id)
                cur.execute(
                    "SELECT plan_type, subscription_expires_at, ai_requests_today "
                    "FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
            if not row:
                return {"plan_type": "free", "expires_at": None, "ai_used": 0}
            plan_type, expires_at, ai_used = row
            return {
                "plan_type": plan_type or "free",
                "expires_at": expires_at,
                "ai_used": ai_used or 0,
            }
        except Exception as e:
            logger.error("SubscriptionService.get_user_plan xatosi: %s", e)
            return {"plan_type": "free", "expires_at": None, "ai_used": 0}
