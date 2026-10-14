"""Mini App YOZUV amallari: post yaratish/tahrirlash/bekor qilish, til, AI matn.

Printsiplar:
  * Mavjud servislar QAYTA ISHLATILADI: ``posts_repository.add_post`` (post raqami, referal,
    keshlar), ``update_post_content``, ``cancel_post``, ``check_queue_limit``,
    ``set_user_language``, ``services.ai_quota`` (atomik kvota bron/qaytarish) va
    ``generate_magic_post``. Yuborishni Mini App BAJARMAYDI: post ``scheduled_posts`` ga
    yoziladi, yuborish botning mavjud scheduler'i (``get_due_posts`` — ``FOR UPDATE SKIP
    LOCKED``) orqali, bir marta amalga oshadi. «Hozir yuborish» = vaqti hozirgi vaqt bo'lgan
    post; scheduler uni keyingi tick'da (<= ~1 daqiqa) yuboradi.
  * Egalik HAR DOIM serverda: kanal ``channels.user_id`` orqali, post ``user_id = %s`` sharti
    SQL ichida. ``user_id`` faqat tasdiqlangan ``initData`` dan keladi.
  * Takroriy bosish: 30 soniya ichidagi AYNAN o'sha (foydalanuvchi, kanal, matn) post qayta
    yaratilmaydi (mavjudi qaytadi); jarayon ichida foydalanuvchi bo'yicha qulf ostida.
  * Hech qanday xato matni mijozga o'tmaydi (faqat katalogdagi xabarlar).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from aiohttp import web

from .errors import ApiError
from .service import MiniAppService, iso_utc
from .settings import MiniAppSettings

logger = logging.getLogger(__name__)

MAX_POST_CHARS = 4096          # Telegram matn limiti (utf-16 birligida ham tekshiriladi)
MAX_AI_INPUT_CHARS = 3500      # generate_magic_post kirish chegarasi
MIN_LEAD_SECONDS = 60
MAX_LEAD_DAYS = 366
DUPLICATE_WINDOW_SECONDS = 30
AI_STYLES = ("sales", "premium", "casual", "ads", "informative")
LANGS = ("uz", "ru", "en")

_CHANNEL_RE = re.compile(r"\A-?[0-9]{1,20}\Z|\A@[A-Za-z0-9_]{4,64}\Z")
_ISO_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?([Zz]|[+-]\d{2}:\d{2})\Z")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _reject_constant(_name):
    raise ValueError("constant")


async def read_json_object(request: web.Request, max_bytes: int) -> dict:
    """Qat'iy JSON tana: faqat ``application/json``, hajm chegarasi, faqat obyekt."""
    ctype = (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise ApiError("unsupported_media_type")
    declared = request.content_length
    if declared is not None and declared > max_bytes:
        raise ApiError("payload_too_large")
    raw = await request.content.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ApiError("payload_too_large")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ApiError("bad_request") from None
    if not isinstance(data, dict):
        raise ApiError("bad_request")
    return data


def _only_keys(data: dict, allowed: tuple[str, ...]) -> None:
    for key in data:
        if key not in allowed:
            raise ApiError("invalid_input")  # noma'lum maydon: mass-assignment yo'q


def parse_text(value, field: str, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ApiError("invalid_input", field=field)
    text = value.strip()
    if not text or _CTRL_RE.search(text):
        raise ApiError("invalid_input", field=field)
    from utils.telegram_sanitizer import utf16_length

    if len(text) > max_chars or utf16_length(text) > max_chars:
        raise ApiError("invalid_input", field=field)
    return text


def parse_channel_id(value) -> str:
    if not isinstance(value, str) or not _CHANNEL_RE.match(value):
        raise ApiError("invalid_input", field="channel_id")
    return value


def parse_when(value, now: datetime) -> datetime:
    """ISO-8601 (MAJBURIY vaqt zonasi) -> UTC. Kamida 1 daqiqa keyin, ko'pi bilan 366 kun."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise ApiError("invalid_input", field="scheduled_at")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise ApiError("invalid_input", field="scheduled_at") from None
    if when.tzinfo is None:
        raise ApiError("invalid_input", field="scheduled_at")
    when = when.astimezone(timezone.utc)
    if when < now + timedelta(seconds=MIN_LEAD_SECONDS):
        raise ApiError("schedule_in_past", field="scheduled_at")
    if when > now + timedelta(days=MAX_LEAD_DAYS):
        raise ApiError("invalid_input", field="scheduled_at")
    return when


class PostWriter:
    """Yozuv amallari. ``clock`` — test uchun ``datetime`` qaytaruvchi funksiya."""

    def __init__(self, service: MiniAppService, settings: MiniAppSettings, *, clock=None,
                 posts_repo=None, users_repo=None, ai=None) -> None:
        self._service = service
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._gate = asyncio.Semaphore(settings.max_inflight_db)
        self._ai_gate = asyncio.Semaphore(settings.ai_concurrency)
        self._locks: dict[int, asyncio.Lock] = {}
        self._posts = posts_repo
        self._users = users_repo
        self._ai = ai

    # ------------------------------------------------------------ yordamchilar
    def _posts_repo(self):
        if self._posts is None:
            from repositories import posts_repository as posts

            self._posts = posts
        return self._posts

    def _users_repo(self):
        if self._users is None:
            from repositories import users_repository as users

            self._users = users
        return self._users

    async def _blocking(self, fn, *args):
        """Sync DB funksiyasini thread'da, parallel chegara bilan bajaradi."""
        try:
            await asyncio.wait_for(self._gate.acquire(), self._settings.db_queue_wait_seconds or 0.01)
        except asyncio.TimeoutError:
            raise ApiError("service_unavailable", retry_after=2) from None
        try:
            return await asyncio.to_thread(fn, *args)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 — matn SQL/qiymat saqlashi mumkin
            logger.warning("miniapp write: DB xatosi (%s)", type(exc).__name__)
            raise ApiError("save_failed", retry_after=5) from None
        finally:
            self._gate.release()

    def _user_lock(self, user_id: int) -> asyncio.Lock:
        if len(self._locks) > 2048:  # cheksiz o'sishdan himoya (faqat bo'sh qulflar o'chiriladi)
            for key in [k for k, v in self._locks.items() if not v.locked()]:
                self._locks.pop(key, None)
        return self._locks.setdefault(user_id, asyncio.Lock())

    # ------------------------------------------------------------------ postlar
    async def create_post(self, user_id: int, body: dict) -> dict:
        _only_keys(body, ("channel_id", "text", "scheduled_at", "send_now"))
        channel_id = parse_channel_id(body.get("channel_id"))
        text = parse_text(body.get("text"), "text", max_chars=MAX_POST_CHARS)
        send_now = body.get("send_now", False)
        if not isinstance(send_now, bool):
            raise ApiError("invalid_input", field="send_now")
        has_when = body.get("scheduled_at") is not None
        if send_now == has_when:  # ikkalasi ham yo'q yoki ikkalasi ham bor
            raise ApiError("invalid_input", field="scheduled_at")
        now = self._clock()
        when = now if send_now else parse_when(body.get("scheduled_at"), now)

        ctx = await self._service.authorize(user_id)
        if not await self._service.owns_channel(user_id, channel_id):
            raise ApiError("channel_not_found", field="channel_id")

        async with self._user_lock(user_id):
            existing = await self._blocking(self._find_duplicate, user_id, channel_id, text)
            if existing:
                post_id, created = existing, False
            else:
                if not ctx["is_admin"]:
                    allowed, _current, _max = await self._blocking(
                        self._users_repo().check_queue_limit, user_id)
                    if not allowed:
                        raise ApiError("queue_limit_reached")
                post_id = await self._blocking(
                    lambda: self._posts_repo().add_post(
                        user_id, channel_id, "text", text, None, when))
                if not post_id:
                    raise ApiError("save_failed", retry_after=5)
                created = True
        post = await self._service.post(user_id, int(post_id))
        return {"post": post, "created": created,
                "delivery": "immediate" if send_now else "scheduled"}

    def _find_duplicate(self, user_id: int, channel_id: str, text: str):
        with self._db_cursor() as cur:
            cur.execute(
                "SELECT id FROM scheduled_posts WHERE user_id = %s AND channel_id = %s "
                "AND content = %s AND status <> 'cancelled' "
                "AND created_at > CURRENT_TIMESTAMP - (%s || ' seconds')::interval "
                "ORDER BY id DESC LIMIT 1",
                (user_id, channel_id, text, str(DUPLICATE_WINDOW_SECONDS)),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def _db_cursor(self, commit: bool = False):
        from repositories.runtime import db_cursor

        return db_cursor(commit=commit)

    async def update_post(self, user_id: int, post_id: int, body: dict) -> dict:
        _only_keys(body, ("text", "scheduled_at"))
        if not body:
            raise ApiError("invalid_input")
        text = parse_text(body["text"], "text", max_chars=MAX_POST_CHARS) if "text" in body else None
        now = self._clock()
        when = parse_when(body["scheduled_at"], now) if "scheduled_at" in body else None

        await self._service.authorize(user_id)
        posts = self._posts_repo()
        status = await self._blocking(posts.get_post_status, post_id, user_id)
        if not status:
            raise ApiError("not_found")
        if status != "pending":
            raise ApiError("not_editable")
        async with self._user_lock(user_id):
            if when is not None:
                ok = await self._blocking(self._reschedule_pending, user_id, post_id, when)
                if not ok:
                    raise ApiError("not_editable")
            if text is not None:
                ok = await self._blocking(
                    lambda: posts.update_post_content(post_id, user_id, content=text))
                if not ok:
                    raise ApiError("not_editable")
        return {"post": await self._service.post(user_id, post_id)}

    def _reschedule_pending(self, user_id: int, post_id: int, when: datetime) -> bool:
        """Vaqtni FAQAT egasining 'pending' va takrorlanmaydigan posti uchun o'zgartiradi."""
        with self._db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_posts SET scheduled_time = %s "
                "WHERE id = %s AND user_id = %s AND status = 'pending' "
                "AND COALESCE(recurrence_type, 'none') = 'none'",
                (when, post_id, user_id),
            )
            changed = cur.rowcount > 0
        if changed:
            from repositories.runtime import _invalidate_user

            _invalidate_user(user_id)
        return changed

    async def cancel_post(self, user_id: int, post_id: int) -> dict:
        await self._service.authorize(user_id)
        posts = self._posts_repo()
        status = await self._blocking(posts.get_post_status, post_id, user_id)
        if not status:
            raise ApiError("not_found")
        if status != "pending":
            raise ApiError("not_editable")
        ok = await self._blocking(posts.cancel_post, post_id, user_id)
        if not ok:
            raise ApiError("not_editable")  # poyga: shu orada yuborilib/bekor qilingan
        return {"id": post_id, "status": "cancelled"}

    # ------------------------------------------------------------------- sozlamalar
    async def set_language(self, user_id: int, body: dict) -> dict:
        _only_keys(body, ("language",))
        language = body.get("language")
        if language not in LANGS:
            raise ApiError("invalid_input", field="language")
        await self._service.authorize(user_id)
        ok = await self._blocking(self._users_repo().set_user_language, user_id, language)
        if not ok:
            raise ApiError("save_failed", retry_after=5)
        return {"language": language}

    # --------------------------------------------------------------------- AI
    async def ai_generate(self, user_id: int, body: dict) -> dict:
        _only_keys(body, ("text", "style"))
        text = parse_text(body.get("text"), "text", max_chars=MAX_AI_INPUT_CHARS)
        style = body.get("style", "casual")
        if style not in AI_STYLES:
            raise ApiError("invalid_input", field="style")
        ctx = await self._service.authorize(user_id)
        ai = self._ai or _BotAI()
        is_admin = ctx["is_admin"]
        is_pro = False if is_admin else await ai.is_pro(user_id)

        reservation = None
        if not is_admin and not is_pro:
            # Bot bilan AYNAN bir xil qoida (handlers/magic_post): kvota/kredit atomik bron.
            reservation = await ai.reserve(user_id)
            if not reservation.get("allowed"):
                if ai.is_balance_reason(reservation.get("reason")):
                    raise ApiError("ai_limit_reached")
                raise ApiError("service_unavailable", retry_after=5)

        refunded = False

        async def refund():
            nonlocal refunded
            if reservation and not refunded:
                refunded = True
                try:
                    await ai.release(user_id, reservation.get("reservation_id"))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("miniapp ai: bron qaytarilmadi (%s)", type(exc).__name__)

        try:
            await asyncio.wait_for(self._ai_gate.acquire(), 2.0)
        except asyncio.TimeoutError:
            await refund()
            raise ApiError("service_unavailable", retry_after=5) from None
        try:
            result = await ai.generate(text, style, ctx["language"], is_pro)
        except asyncio.CancelledError:
            await asyncio.shield(refund())  # mijoz uzildi / timeout: bron qaytariladi
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("miniapp ai: generatsiya xatosi (%s)", type(exc).__name__)
            await refund()
            raise ApiError("ai_unavailable", retry_after=10) from None
        finally:
            self._ai_gate.release()
        post_text = str((result or {}).get("post_text") or "").strip() if isinstance(result, dict) else ""
        if not post_text or (isinstance(result, dict) and result.get("error")):
            await refund()
            raise ApiError("ai_unavailable", retry_after=10)
        return {"text": post_text[:MAX_POST_CHARS], "style": style}


class _BotAI:
    """Botning mavjud AI servislariga adapter (testlarda almashtiriladi)."""

    async def is_pro(self, user_id: int) -> bool:
        import database as db

        try:
            return bool(await db.run_db(db.is_premium, user_id))
        except Exception:  # noqa: BLE001
            return False

    async def reserve(self, user_id: int) -> dict:
        import database as db
        from services.ai_quota import reserve_ai_quota

        return await reserve_ai_quota(db, user_id, "magic_post", 1)

    def is_balance_reason(self, reason) -> bool:
        from services.ai_quota import is_balance_reason

        return is_balance_reason(reason)

    async def release(self, user_id: int, reservation_id) -> None:
        import database as db
        from services.ai_quota import release_ai_quota

        await release_ai_quota(db, user_id, reservation_id)

    async def generate(self, text: str, style: str, lang: str, is_pro: bool) -> dict:
        from utils.ai_agent import generate_magic_post

        return await generate_magic_post(text, style, lang=lang, is_pro=is_pro)


__all__ = ["PostWriter", "read_json_object", "parse_when", "parse_text", "iso_utc"]
