"""SchedulerService — post yuborish (delivery) biznes mantiqi.

PostAssist V2 (3-bosqich): ``post_deliveries`` jadvali Telegram delivery'sining
yagona, doimiy source-of-truth'i. Vaqtinchalik ``/tmp/*.json`` journalga
tayanilmaydi — barcha holatlar (pending/processing/sent/failed/dead_letter)
PostgreSQL'da saqlanadi va restart'lardan omon qoladi.

Idempotency kaliti QAT'IY uchlikdan tuziladi::

    post_id + channel_id + scheduled_time

Statuslar:
  - ``pending``    — yuborish kutilmoqda (yangi delivery).
  - ``processing`` — worker claim qilgan, Telegramga yuborilmoqda.
  - ``sent``       — yuborilgan (telegram_message_id saqlangan). HECH QACHON
                     qayta yuborilmaydi va boshqa statusga o'tkazilmaydi.
  - ``failed``     — vaqtinchalik xato; ``next_retry_at`` dagi backoff
                     (30s, 2m, 5m, 15m) o'tgach qayta claim qilinadi.
  - ``dead_letter``— doimiy xato (chat_not_found, bot_kicked, ...) yoki 5+
                     urinish tugagan. HECH QACHON qayta urinilmaydi.

Foydalanish::

    from services.scheduler_service import SchedulerService
    claim = SchedulerService.claim_post_for_delivery(post_id, channel_id, scheduled_time)
    if claim.get("sent"):
        return  # 0 duplikat
    ...
    SchedulerService.mark_as_sent(post_id, channel_id, message_id, scheduled_time)
"""

import logging

from database import (
    db_cursor,
    build_delivery_idempotency_key,
    _delivery_channel_number,
    claim_post_delivery,
    mark_post_delivery_sent,
    mark_post_delivery_unknown,
    DELIVERY_BACKOFF_SECONDS,
    DELIVERY_MAX_ATTEMPTS,
)

logger = logging.getLogger(__name__)


class SchedulerService:
    """Telegram delivery holatlarini boshqarish: claim / sent / failed / retry."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_DEAD_LETTER = "dead_letter"
    #: UNKNOWN_DELIVERY (11-bosqich): Telegram javobi olinmagan (albom
    #: yuborishda TimedOut/NetworkError). Qayta yuborish TAQIQLANADI.
    STATUS_UNKNOWN = "unknown"

    CLAIMABLE_STATUSES = (
        STATUS_PENDING,
        STATUS_FAILED,
        # 'processing' faqat stale bo'lsa (crash) qayta olinadi — bu mantiq
        # claim_post_delivery ichida.
    )

    # Vaqtinchalik xatodagi backoff jadvali: urinish → kutish (soniya).
    # 1 → 30s, 2 → 2 daqiqa, 3 → 5 daqiqa, 4 → 15 daqiqa, 5+ → dead_letter.
    BACKOFF_SECONDS = DELIVERY_BACKOFF_SECONDS
    MAX_ATTEMPTS = DELIVERY_MAX_ATTEMPTS

    # Doimiy (qayta urinib bo'lmaydigan) Telegram xatolarining belgilari.
    # Matn kichik harflarda qidiriladi; klass nomi ham tekshiriladi.
    PERMANENT_PATTERNS = (
        "chat_not_found",
        "chat not found",
        "bot_kicked",
        "bot was kicked",
        "kicked from",
        "bot was blocked",
        "bot is blocked",
        "blocked by the user",
        "user is deactivated",
        "deactivated",
        "chat is deactivated",
        "have no rights",
        "not enough rights",
        "need administrator rights",
        "bot is not a member",
        "not a member",
        "group chat was deleted",
        "chat was deleted",
        "channel is private",
        "message_thread_not_found",
        "message thread not found",
        "topic deleted",
        "topic_closed",
    )

    PERMANENT_EXCEPTION_NAMES = (
        "BotKicked",
        "ChatNotFound",
        "Forbidden",
        "ChatDeactivated",
        "Unauthorized",
    )

    # ──────────────────────────────────────────────────────────────
    # KALIT VA YORDAMCHILAR
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def build_idempotency_key(post_id, channel_id, scheduled_time) -> str:
        """Qat'iy idempotency kaliti: post_id + channel_id + scheduled_time."""
        return build_delivery_idempotency_key(post_id, channel_id, scheduled_time)

    @staticmethod
    def backoff_for_attempt(attempt_count: int):
        """Urininsh raqamiga mos backoff (soniya) yoki None (dead_letter).

        1 → 30, 2 → 120, 3 → 300, 4 → 900, 5+ → None.
        """
        try:
            attempt = int(attempt_count)
        except (TypeError, ValueError):
            return None
        if attempt < 1 or attempt > len(SchedulerService.BACKOFF_SECONDS):
            return None
        return SchedulerService.BACKOFF_SECONDS[attempt - 1]

    @staticmethod
    def normalize_error_text(error) -> str:
        """Xatoni DB'ga yoziladigan qisqa matnga keltiradi (maks. 4000 belgi)."""
        if error is None:
            return ""
        if isinstance(error, BaseException):
            name = type(error).__name__
            text = str(error) or name
            if name and name not in text:
                text = f"{name}: {text}"
            return text[:4000]
        return str(error)[:4000]

    @staticmethod
    def is_permanent_error(error) -> bool:
        """Xato doimiy (retry foydasiz)mi?

        ``BotKicked``/``ChatNotFound``/``Forbidden`` kabi istisno klasslari va
        ``chat_not_found``/``bot_kicked`` kabi matn naqshlari doimiy hisoblanadi.
        Noma'lum xatolar — vaqtinchalik (konservativ: kamida 5 marta uriniladi).
        """
        if error is None:
            return False
        class_name = type(error).__name__ if isinstance(error, BaseException) else ""
        if class_name in SchedulerService.PERMANENT_EXCEPTION_NAMES:
            return True
        haystack = str(error).lower()
        if class_name:
            haystack = f"{class_name.lower()} {haystack}"
        return any(p in haystack for p in SchedulerService.PERMANENT_PATTERNS)

    @staticmethod
    def _resolve_scheduled_time(cur, post_id, scheduled_time):
        """scheduled_time berilmagan bo'lsa scheduled_posts'dan o'qiydi."""
        if scheduled_time is not None:
            return scheduled_time
        try:
            cur.execute(
                "SELECT scheduled_time FROM scheduled_posts WHERE id = %s",
                (int(post_id),),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return row[0]
        except Exception as e:
            logger.debug("SchedulerService: scheduled_time o'qilmadi (post=%s): %s", post_id, e)
        return None

    @staticmethod
    def _resolve_key(cur, post_id, channel_id, scheduled_time, idempotency_key=None) -> str:
        if idempotency_key:
            return str(idempotency_key)
        resolved = SchedulerService._resolve_scheduled_time(cur, post_id, scheduled_time)
        return SchedulerService.build_idempotency_key(post_id, channel_id, resolved)

    # ──────────────────────────────────────────────────────────────
    # CLAIM — yuborish huquqini atomik olish
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def claim_post_for_delivery(post_id, channel_id, scheduled_time=None) -> dict:
        """Delivery'ni atomik claim qiladi (``SELECT ... FOR UPDATE``).

        Ikkita parallel worker bir xil postni bir vaqtda claim qila olmaydi:
        birinchi worker qatorni qulflaydi, ikkinchisi kutib keyin 'processing'
        ni ko'radi va ``claimed=False`` oladi — Telegramga faqat BIRINCHI
        murojaat qiladi.

        Qaytadi (har doim dict)::

            {"claimed": True, "status": "processing",
             "attempt_count": int, "idempotency_key": str}
            {"claimed": False, "sent": True, "status": "sent", ...}   # skip!
            {"claimed": False, "dead": True, "status": "dead_letter", ...}
            {"claimed": False, "status": "processing", ...}           # boshqa worker
            {"claimed": False, "status": "failed", "retry_pending": True, ...}
        """
        try:
            post_id = int(post_id)
        except (TypeError, ValueError):
            return {"claimed": False, "status": "invalid_post",
                    "idempotency_key": ""}
        try:
            if scheduled_time is None:
                # Kalit qat'iy uchlikdan tuzilishi uchun vaqtni DB'dan olamiz.
                try:
                    with db_cursor() as cur:
                        scheduled_time = SchedulerService._resolve_scheduled_time(
                            cur, post_id, None
                        )
                except Exception:
                    scheduled_time = None
            return claim_post_delivery(post_id, channel_id, scheduled_time)
        except Exception as e:
            logger.error("SchedulerService.claim xatosi (post=%s): %s", post_id, e)
            return {"claimed": False, "error": str(e), "idempotency_key": ""}

    # ──────────────────────────────────────────────────────────────
    # SENT — muvaffaqiyatli yuborishni belgilash
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def mark_as_sent(post_id, channel_id, telegram_message_id,
                     scheduled_time=None, idempotency_key=None) -> bool:
        """Delivery'ni 'sent' + telegram_message_id bilan idempotent belgilaydi.

        Qayta chaqiruv xavfsiz (``True``). ``telegram_message_id`` keyinchalik
        auto-delete to'g'ri ishlashi uchun saqlanadi.
        """
        try:
            if not idempotency_key:
                if scheduled_time is not None:
                    # Vaqt ma'lum — DB ulanishsiz kalit tuziladi.
                    idempotency_key = SchedulerService.build_idempotency_key(
                        post_id, channel_id, scheduled_time
                    )
                else:
                    with db_cursor() as cur:
                        idempotency_key = SchedulerService._resolve_key(
                            cur, post_id, channel_id, scheduled_time
                        )
            return bool(mark_post_delivery_sent(idempotency_key, telegram_message_id))
        except Exception as e:
            logger.error("SchedulerService.mark_as_sent xatosi (post=%s): %s", post_id, e)
            return False

    @staticmethod
    def mark_unknown_by_key(idempotency_key: str, error) -> bool:
        """Kalit bo'yicha ``unknown`` (UNKNOWN_DELIVERY) belgilash.

        Albom (media group) yuborishda TimedOut/NetworkError bo'lsa Telegram
        xabarni qabul qilgan bo'lishi mumkin — blind retry dublikat albom
        chiqaradi. Shuning uchun delivery 'unknown' bo'ladi va scheduler uni
        boshqa claim qilmaydi.
        """
        try:
            if not idempotency_key:
                return False
            return bool(mark_post_delivery_unknown(
                idempotency_key, SchedulerService.normalize_error_text(error)
            ))
        except Exception as e:
            logger.error("SchedulerService.mark_unknown_by_key xatosi: %s", e)
            return False

    @staticmethod
    def mark_sent_by_key(idempotency_key: str, telegram_message_id) -> bool:
        """Kalit bo'yicha 'sent' belgilash (scheduler marker oqimi uchun)."""
        try:
            if not idempotency_key:
                return False
            return bool(mark_post_delivery_sent(idempotency_key, telegram_message_id))
        except Exception as e:
            logger.error("SchedulerService.mark_sent_by_key xatosi: %s", e)
            return False

    # ──────────────────────────────────────────────────────────────
    # FAILED — xatoni qayd qilish (backoff yoki dead_letter)
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def mark_as_failed(post_id, channel_id, error, is_transient: bool = True,
                       scheduled_time=None, idempotency_key=None) -> dict:
        """Yuborish xatosini qayd qiladi.

        - ``sent`` yozuv HECH QACHON o'zgartirilmaydi (0 duplikat kafolati).
        - Doimiy xato (``is_transient=False`` yoki chat_not_found/bot_kicked
          va h.k.) → darhol ``dead_letter``.
        - Vaqtinchalik xato → ``attempt_count + 1`` va backoff
          (30s / 2m / 5m / 15m); 5-urinishda ham xato bo'lsa → ``dead_letter``.

        Qaytadi::

            {"ok": True, "status": "failed", "attempt_count": int,
             "backoff_seconds": int, "idempotency_key": str}
            {"ok": True, "status": "dead_letter", "reason": str, ...}
            {"ok": True, "status": "sent", ...}   # allaqachon yuborilgan
            {"ok": False, "reason": str, ...}     # DB xatosi
        """
        error_text = SchedulerService.normalize_error_text(error)
        try:
            with db_cursor(commit=True) as cur:
                key = SchedulerService._resolve_key(
                    cur, post_id, channel_id, scheduled_time, idempotency_key
                )
                cur.execute(
                    "INSERT INTO post_deliveries "
                    "(post_id, channel_id, status, idempotency_key, scheduled_time) "
                    "VALUES (%s, %s, 'pending', %s, %s) ON CONFLICT DO NOTHING",
                    (int(post_id), _delivery_channel_number(channel_id), key,
                     scheduled_time),
                )
                cur.execute(
                    "SELECT status, COALESCE(attempt_count, 0) "
                    "FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                    (key,),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "status": "missing", "reason": "missing",
                            "idempotency_key": key}
                status, attempt_count = row[0], int(row[1] or 0)

                if status == SchedulerService.STATUS_SENT:
                    # Yuborilgan fakt ustidan HECH QACHON yozilmaydi.
                    return {"ok": True, "status": status, "idempotency_key": key}
                if status == SchedulerService.STATUS_DEAD_LETTER:
                    return {"ok": True, "status": status, "idempotency_key": key}

                permanent = (not is_transient) or SchedulerService.is_permanent_error(error)
                if permanent:
                    reason = ("permanent" if not is_transient
                              else "permanent_error_pattern")
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "last_error = %s, next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (error_text, key),
                    )
                    logger.warning(
                        "Delivery dead_letter (post=%s, key=%s): %s",
                        post_id, key, error_text[:200],
                    )
                    return {"ok": True, "status": "dead_letter", "reason": reason,
                            "attempt_count": attempt_count, "idempotency_key": key}

                new_attempt = attempt_count + 1
                if new_attempt >= SchedulerService.MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "attempt_count = %s, last_error = %s, "
                        "next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (new_attempt, error_text, key),
                    )
                    logger.warning(
                        "Delivery dead_letter, urinishlar tugadi (post=%s, key=%s, "
                        "attempt=%s): %s",
                        post_id, key, new_attempt, error_text[:200],
                    )
                    return {"ok": True, "status": "dead_letter",
                            "reason": "attempts_exhausted",
                            "attempt_count": new_attempt, "idempotency_key": key}

                backoff = SchedulerService.backoff_for_attempt(new_attempt) or 30
                cur.execute(
                    "UPDATE post_deliveries SET status = 'failed', "
                    "attempt_count = %s, last_error = %s, "
                    "next_retry_at = NOW() + (%s || ' seconds')::INTERVAL, "
                    "updated_at = NOW() "
                    "WHERE idempotency_key = %s",
                    (new_attempt, error_text, str(int(backoff)), key),
                )
                return {"ok": True, "status": "failed", "attempt_count": new_attempt,
                        "backoff_seconds": int(backoff), "idempotency_key": key}
        except Exception as e:
            logger.error("SchedulerService.mark_as_failed xatosi (post=%s): %s", post_id, e)
            return {"ok": False, "reason": "database_error",
                    "idempotency_key": idempotency_key or ""}

    @staticmethod
    def mark_failed_by_key(idempotency_key: str, error,
                           is_transient: bool = True) -> dict:
        """Kalit bo'yicha xatoni qayd qilish (scheduler retry oqimi uchun).

        Kalitdan post_id/channel ajratib bo'lmaydi, shuning uchun yozuv
        mavjud bo'lishi shart (claim avval qilingan bo'ladi).
        """
        try:
            if not idempotency_key:
                return {"ok": False, "reason": "missing_key", "idempotency_key": ""}
            error_text = SchedulerService.normalize_error_text(error)
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "SELECT status, COALESCE(attempt_count, 0) "
                    "FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                    (str(idempotency_key),),
                )
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "status": "missing",
                            "reason": "missing", "idempotency_key": str(idempotency_key)}
                status, attempt_count = row[0], int(row[1] or 0)
                key = str(idempotency_key)
                if status == SchedulerService.STATUS_SENT:
                    return {"ok": True, "status": status, "idempotency_key": key}
                if status == SchedulerService.STATUS_DEAD_LETTER:
                    return {"ok": True, "status": status, "idempotency_key": key}
                permanent = (not is_transient) or SchedulerService.is_permanent_error(error)
                if permanent:
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "last_error = %s, next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (error_text, key),
                    )
                    return {"ok": True, "status": "dead_letter",
                            "reason": "permanent", "attempt_count": attempt_count,
                            "idempotency_key": key}
                new_attempt = attempt_count + 1
                if new_attempt >= SchedulerService.MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "attempt_count = %s, last_error = %s, "
                        "next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (new_attempt, error_text, key),
                    )
                    return {"ok": True, "status": "dead_letter",
                            "reason": "attempts_exhausted",
                            "attempt_count": new_attempt, "idempotency_key": key}
                backoff = SchedulerService.backoff_for_attempt(new_attempt) or 30
                cur.execute(
                    "UPDATE post_deliveries SET status = 'failed', "
                    "attempt_count = %s, last_error = %s, "
                    "next_retry_at = NOW() + (%s || ' seconds')::INTERVAL, "
                    "updated_at = NOW() "
                    "WHERE idempotency_key = %s",
                    (new_attempt, error_text, str(int(backoff)), key),
                )
                return {"ok": True, "status": "failed", "attempt_count": new_attempt,
                        "backoff_seconds": int(backoff), "idempotency_key": key}
        except Exception as e:
            logger.error("SchedulerService.mark_failed_by_key xatosi: %s", e)
            return {"ok": False, "reason": "database_error",
                    "idempotency_key": idempotency_key or ""}

    # ──────────────────────────────────────────────────────────────
    # HOLAT SO'ROVLARI
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_delivery_status(post_id, channel_id, scheduled_time=None,
                            idempotency_key=None):
        """Delivery holatini qaytaradi (topilmasa None)."""
        try:
            with db_cursor() as cur:
                key = SchedulerService._resolve_key(
                    cur, post_id, channel_id, scheduled_time, idempotency_key
                )
                cur.execute(
                    "SELECT status, COALESCE(attempt_count, 0), "
                    "telegram_message_id, last_error, next_retry_at, updated_at "
                    "FROM post_deliveries WHERE idempotency_key = %s",
                    (key,),
                )
                row = cur.fetchone()
            if not row:
                return None
            return {
                "status": row[0],
                "attempt_count": int(row[1] or 0),
                "telegram_message_id": row[2],
                "last_error": row[3],
                "next_retry_at": row[4],
                "updated_at": row[5],
                "idempotency_key": key,
            }
        except Exception as e:
            logger.error("SchedulerService.get_delivery_status xatosi: %s", e)
            return None

    @staticmethod
    def is_already_sent(post_id, channel_id, scheduled_time=None,
                        idempotency_key=None) -> bool:
        """Delivery 'sent' holatidami (Telegramga qayta murojaat shart emasmi)?"""
        info = SchedulerService.get_delivery_status(
            post_id, channel_id, scheduled_time, idempotency_key
        )
        return bool(info) and info.get("status") == SchedulerService.STATUS_SENT

    @staticmethod
    def get_pending_or_retry_posts(limit: int = 100) -> list:
        """Yuborilishi kerak delivery'lar: pending + backoff'i o'tgan failed.

        'sent' / 'processing' / 'dead_letter' va backoff'i hali o'tmagan
        'failed' yozuvlar qaytmaydi.
        """
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 100
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT post_id, channel_id, idempotency_key, "
                    "COALESCE(attempt_count, 0), last_error, next_retry_at, updated_at "
                    "FROM post_deliveries "
                    "WHERE status IN ('pending', 'failed') "
                    "AND (next_retry_at IS NULL OR next_retry_at <= NOW()) "
                    "ORDER BY updated_at ASC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall() or []
            return [
                {
                    "post_id": r[0],
                    "channel_id": r[1],
                    "idempotency_key": r[2],
                    "attempt_count": int(r[3] or 0),
                    "last_error": r[4],
                    "next_retry_at": r[5],
                    "updated_at": r[6],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("SchedulerService.get_pending_or_retry_posts xatosi: %s", e)
            return []
