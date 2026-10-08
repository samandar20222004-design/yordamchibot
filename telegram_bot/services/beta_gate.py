# -*- coding: utf-8 -*-
"""🚪 SPRINT 4 — YOPIQ BETA DARVOZASI (CLOSED BETA ACCESS GATE).

Maqsad (SPRINT 4, 2-band): botni OMMAGA TO'LIQ ochishdan oldin 30–50 ta
saralangan kanal egasi bilan sinash. Darvoza bitta env bayrog'i bilan
boshqariladi:

    BETA_INVITE_ONLY=true   → faqat taklif kodi yoki admin tasdig'i bilan
    BETA_INVITE_ONLY=false  → odatiy ochiq rejim (standart)
    BETA_MAX_USERS=50       → beta o'rinlari soni (0 = cheksiz)

QOIDALAR (mavjud foydalanuvchilar BUZILMAYDI):

* **eski foydalanuvchi** (bazada yozuvi bor) — darvoza YOQILGAN bo'lsa ham
  uzluksiz ishlayveradi (``reason="existing_user"``);
* **admin** — har doim o'tadi;
* **yangi foydalanuvchi**:
    - taklif kodi to'g'ri va muddati tugamagan → kiritiladi (kod "sarflanadi");
    - allaqachon admin tasdiqlagan → kiritiladi;
    - kod yo'q/xato → kutilmoqda (``pending``) va adminga tasdiq so'rovi;
    - o'rinlar tugagan (``BETA_MAX_USERS``) → ``beta_full``.

Holat ``system_settings`` jadvalida BITTA hujjat sifatida saqlanadi
(``beta_gate_state`` — JSON): yangi jadval/migratsiya YO'Q, sxema
qulflangan sonlari (31 jadval / 33 indeks) o'zgarmaydi.

Ochig'i: baza yagona jarayon (bitta bot instansiyasi) uchun mo'ljallangan —
o'zgarishlar ``threading.RLock`` bilan himoyalangan; ko'p instansiyali
deploy'da qo'shimcha navbat talab qilinadi (bu modul buni yashirmaydi).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: Holat saqlanadigan kalit (``system_settings``).
BETA_STATE_KEY = "beta_gate_state"

#: Holat keshi TTL'i (soniya). ``/start`` HAR bir yangi foydalanuvchi uchun
#: holatni o'qiydi — shuning uchun baza so'rovi qisqa muddatga keshlanadi
#: (yozuvlar keshni darhol yangilaydi, shuning uchun o'qish izchil qoladi).
STATE_CACHE_TTL = 15

#: Kod formati: harflar/raqamlar va chiziqcha (o'qish oson, URL-xavfsiz).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # I/O/0/1 — chalkashmaydi
CODE_MAX_LEN = 32
DEFAULT_CODE_USES = 1
MAX_CODE_USES = 100
MAX_STATE_ITEMS = 2000  # bitta bo'limdagi yozuvlar chegarasi (memory guard)

# --- Qaror sabablari (kanonik, i18n kalitlari bilan bir xil) ----------------
REASON_OPEN = "open_mode"           # darvoza o'chiq — hamma kiraveradi
REASON_EXISTING = "existing_user"   # eski foydalanuvchi — har doim o'tadi
REASON_ADMIN = "admin_access"       # admin — har doim o'tadi
REASON_INVITE = "invite_code"       # taklif kodi bilan kiritildi
REASON_APPROVED = "admin_approved"  # admin tasdig'i bilan kiritildi
REASON_PENDING = "pending_approval"  # kod yo'q — admin tasdig'i kutilmoqda
REASON_INVALID_CODE = "invalid_code"
REASON_CODE_EXHAUSTED = "code_exhausted"
REASON_BETA_FULL = "beta_full"
REASON_STORE_ERROR = "store_error"  # holatni o'qib/yoza olmadik (fail-closed)


def _now_iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def normalize_code(raw) -> str:
    """Kodni kanonik ko'rinishga keltiradi (bo'shliq/chiziqcha olib tashlanadi)."""
    text = "".join(str(raw or "").strip().upper().split())
    text = text.replace("_", "-")
    return text[:CODE_MAX_LEN]


def _code_key(raw) -> str:
    """Qidiruv uchun kalit: chiziqchalar ham e'tiborsiz (BETA-1234 == BETA1234)."""
    return normalize_code(raw).replace("-", "")


def generate_code(seed: int | None = None) -> str:
    """Yangi taklif kodi (``BETA-XXXXXX``) — kriptografik bo'lmagan, lekin tasodifiy."""
    import random

    rnd = random.Random(seed) if seed is not None else random.SystemRandom()
    body = "".join(rnd.choice(CODE_ALPHABET) for _ in range(6))
    return f"BETA-{body}"


def empty_state() -> dict:
    return {"version": 1, "enabled": None, "codes": {}, "approved": {}, "pending": {}}


def parse_state(raw) -> dict:
    """Saqlangan JSON'ni xavfsiz o'qiydi (buzilgan bo'lsa — bo'sh holat)."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            logger.warning("beta_gate: holat JSON'i buzilgan — bo'sh holat olindi")
            data = {}
    if not isinstance(data, dict):
        data = {}
    state = empty_state()
    for key in ("codes", "approved", "pending"):
        value = data.get(key)
        if isinstance(value, dict):
            state[key] = dict(list(value.items())[:MAX_STATE_ITEMS])
    override = data.get("enabled")
    state["enabled"] = bool(override) if override is not None else None
    return state


def serialize_state(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Saqlash (store) — baza + xotira
# ---------------------------------------------------------------------------
class MemoryBetaStore:
    """Testlar va baza bo'lmagan muhit uchun xotira ombori."""

    def __init__(self, initial: dict | None = None) -> None:
        self._state = parse_state(initial) if initial else empty_state()
        self._fail = False

    def load(self) -> dict:
        if self._fail:
            raise RuntimeError("beta store unavailable")
        return parse_state(self._state)

    def save(self, state: dict) -> bool:
        if self._fail:
            return False
        self._state = parse_state(state)
        return True

    # testlar uchun
    def set_failing(self, value: bool = True) -> None:
        self._fail = bool(value)


class SettingsBetaStore:
    """``system_settings`` (kalit/qiymat) ustidagi ombor — yangi jadval YO'Q."""

    def __init__(self, db_module=None) -> None:
        self._db = db_module

    def _module(self):
        if self._db is not None:
            return self._db
        import database as db  # kech import — import sikli yo'q

        return db

    def load(self) -> dict:
        db = self._module()
        raw = db.get_setting(BETA_STATE_KEY, "")
        return parse_state(raw)

    def save(self, state: dict) -> bool:
        db = self._module()
        return bool(db.set_setting(BETA_STATE_KEY, serialize_state(state)))


# ---------------------------------------------------------------------------
# Darvoza
# ---------------------------------------------------------------------------
class BetaGate:
    """Yopiq beta darvozasi (holat + qarorlar).

    ``store`` — ``load()``/``save()`` interfeysi bo'lgan obyekt
    (``SettingsBetaStore`` yoki ``MemoryBetaStore``). ``invite_only`` /
    ``max_users`` berilmasa — config qiymatlari ishlatiladi (env'ni test
    vaqtida o'zgartirmaslik uchun ularni to'g'ridan-to'g'ri berish mumkin).
    """

    def __init__(self, store=None, *, invite_only: bool | None = None,
                 max_users: int | None = None, db_module=None,
                 state_ttl: int | None = None) -> None:
        self._store = store if store is not None else SettingsBetaStore(db_module)
        self._invite_only_override = invite_only
        self._max_users_override = max_users
        self._lock = threading.RLock()
        # Xotira ombori uchun kesh SHART EMAS (test arzonligi va yangiligi);
        # baza ombori uchun — qisqa TTL (spam so'rovlarning oldini oladi).
        if state_ttl is None:
            state_ttl = 0 if isinstance(self._store, MemoryBetaStore) else STATE_CACHE_TTL
        self._state_ttl = max(0, int(state_ttl))
        self._cached_state: "dict | None" = None
        self._cached_at = 0.0

    # ------------------------------------------------------------- sozlama
    @property
    def invite_only(self) -> bool:
        """Darvoza yoqilganmi (runtime override → env/config → standart)."""
        if self._invite_only_override is not None:
            return bool(self._invite_only_override)
        try:
            state = self._store.load()
        except Exception:  # noqa: BLE001 — holatni o'qib bo'lmasa env ishlaydi
            state = {}
        override = state.get("enabled")
        if override is not None:
            return bool(override)
        return bool(_config_invite_only())

    @property
    def max_users(self) -> int:
        if self._max_users_override is not None:
            return max(0, int(self._max_users_override))
        try:
            return max(0, int(_config_max_users()))
        except Exception:  # noqa: BLE001
            return 50

    def set_enabled(self, value: bool | None) -> bool:
        """Runtime rejim: ``True``/``False`` — yoqish/o'chirish, ``None`` — env."""
        with self._lock:
            state = self._load()
            state["enabled"] = None if value is None else bool(value)
            return self._save(state)

    def _config_enabled(self) -> bool:
        return bool(_config_invite_only())

    # -------------------------------------------------------------- holat
    def _load(self) -> dict:
        moment = time.time()
        with self._lock:
            if (self._state_ttl > 0 and self._cached_state is not None
                    and (moment - self._cached_at) < self._state_ttl):
                return parse_state(self._cached_state)
        try:
            state = parse_state(self._store.load())
        except Exception as exc:  # noqa: BLE001
            logger.warning("beta_gate: holatni o'qib bo'lmadi: %s", exc)
            return empty_state()
        with self._lock:
            self._cached_state = state
            self._cached_at = moment
        return parse_state(state)

    def _save(self, state: dict) -> bool:
        try:
            saved = bool(self._store.save(state))
        except Exception as exc:  # noqa: BLE001
            logger.warning("beta_gate: holatni saqlab bo'lmadi: %s", exc)
            return False
        if saved:
            with self._lock:
                self._cached_state = parse_state(state)
                self._cached_at = time.time()
        return saved

    def status(self, *, now: datetime | None = None) -> dict:
        """Darvoza holati: rejim, kodlar va navbatdagi so'rovlar soni."""
        state = self._load()
        approved = state.get("approved") or {}
        pending = state.get("pending") or {}
        codes = state.get("codes") or {}
        active_codes = [c for c, meta in codes.items()
                        if int((meta or {}).get("uses", 0)) < int((meta or {}).get("max_uses", 1))]
        limit = self.max_users
        return {
            "invite_only": self.invite_only,
            "enabled_source": ("override" if state.get("enabled") is not None
                               else "env"),
            "max_users": limit,
            "seats_used": len(approved),
            "seats_left": (None if limit <= 0 else max(0, limit - len(approved))),
            "approved": len(approved),
            "pending": len(pending),
            "codes": len(codes),
            "active_codes": sorted(active_codes),
            "generated_at": _now_iso(now),
        }

    # ------------------------------------------------------------ kodlar
    def add_code(self, code: str | None = None, *, max_uses: int = DEFAULT_CODE_USES,
                 created_by=None, note: str = "") -> dict | None:
        """Taklif kodi qo'shadi (kod berilmasa — generatsiya qilinadi)."""
        with self._lock:
            state = self._load()
            codes = state.setdefault("codes", {})
            key = normalize_code(code) if code else generate_code()
            if not key:
                return None
            if key in codes:
                return None
            try:
                uses = max(1, min(int(max_uses), MAX_CODE_USES))
            except (TypeError, ValueError):
                uses = DEFAULT_CODE_USES
            meta = {
                "max_uses": uses,
                "uses": 0,
                "created_by": int(created_by) if created_by is not None else None,
                "created_at": _now_iso(),
                "note": str(note or "")[:120],
            }
            codes[key] = meta
            while len(codes) > MAX_STATE_ITEMS:
                codes.pop(next(iter(codes)))
            if not self._save(state):
                return None
            return {"code": key, **meta}

    def revoke_code(self, code: str) -> bool:
        """Kodni o'chiradi (foydalanilmagan yoki ishlatilgan — farqi yo'q)."""
        with self._lock:
            state = self._load()
            codes = state.setdefault("codes", {})
            target = _code_key(code)
            removed = [key for key in codes if _code_key(key) == target]
            if not removed:
                return False
            for key in removed:
                codes.pop(key, None)
            return self._save(state)

    def list_codes(self) -> dict:
        """Barcha kodlar (kod → meta)."""
        state = self._load()
        return dict(state.get("codes") or {})

    def find_code(self, code: str) -> tuple[str | None, dict]:
        """Kodni topadi: ``(kod, meta)`` (topilmasa — ``(None, {})``)."""
        target = _code_key(code)
        if not target:
            return None, {}
        for key, meta in (self._load().get("codes") or {}).items():
            if _code_key(key) == target:
                return key, dict(meta or {})
        return None, {}

    # --------------------------------------------------- tasdiq / navbat
    def approve(self, user_id, *, approved_by=None, source: str = "admin",
                code: str | None = None) -> bool:
        """Foydalanuvchini beta'ga qabul qiladi (navbatdan olib tashlanadi)."""
        uid = str(int(user_id))
        with self._lock:
            state = self._load()
            approved = state.setdefault("approved", {})
            approved[uid] = {
                "approved_at": _now_iso(),
                "approved_by": int(approved_by) if approved_by is not None else None,
                "source": str(source or "admin")[:32],
                "code": normalize_code(code) if code else None,
            }
            (state.get("pending") or {}).pop(uid, None)
            return self._save(state)

    def reject(self, user_id, *, reason: str = "") -> bool:
        """Navbatdagi so'rovni rad etadi (qora ro'yxat emas — qayta so'rash mumkin)."""
        uid = str(int(user_id))
        with self._lock:
            state = self._load()
            pending = state.setdefault("pending", {})
            if uid not in pending:
                return False
            pending.pop(uid, None)
            state.setdefault("rejected", {})[uid] = {
                "rejected_at": _now_iso(), "reason": str(reason or "")[:120],
            }
            return self._save(state)

    def is_approved(self, user_id) -> bool:
        state = self._load()
        return str(int(user_id)) in (state.get("approved") or {})

    def pending_users(self) -> dict:
        state = self._load()
        return dict(state.get("pending") or {})

    def approved_users(self) -> dict:
        state = self._load()
        return dict(state.get("approved") or {})

    def _remember_pending(self, state: dict, user_id, *, username: str = "",
                          full_name: str = "", code: str = "") -> int:
        """Navbatdagi so'rovni yozadi va urinishlar sonini qaytaradi."""
        uid = str(int(user_id))
        pending = state.setdefault("pending", {})
        existing = pending.get(uid) or {}
        attempts = int(existing.get("attempts") or 0) + 1
        pending[uid] = {
            "username": str(username or existing.get("username") or "")[:64],
            "full_name": str(full_name or existing.get("full_name") or "")[:128],
            "requested_at": existing.get("requested_at") or _now_iso(),
            "last_attempt_at": _now_iso(),
            "attempts": attempts,
            "attempted_code": normalize_code(code) if code else "",
        }
        while len(pending) > MAX_STATE_ITEMS:
            pending.pop(next(iter(pending)))
        return attempts

    # ------------------------------------------------------------- qaror
    def check(self, user_id, *, is_new: bool, is_admin: bool = False,
              invite_code: str | None = None, username: str = "",
              full_name: str = "", consume: bool = True) -> dict:
        """Kirish qarori (yagona mantiq — /start shu funksiyani chaqiradi).

        Returns:
            dict::

                {"allowed": bool, "reason": str, "code": str | None,
                 "seats_left": int | None, "invite_only": bool}

        Xatti-harakat:
            * darvozasiz (``invite_only=False``) → hamma o'tadi;
            * eski foydalanuvchi / admin → har doim o'tadi;
            * yangi foydalanuvchi — kod yoki admin tasdig'i orqali.
        """
        if not self.invite_only:
            return {"allowed": True, "reason": REASON_OPEN, "code": None,
                    "seats_left": None, "invite_only": False, "attempts": 0}
        if is_admin:
            return {"allowed": True, "reason": REASON_ADMIN, "code": None,
                    "seats_left": self._seats_left(), "invite_only": True,
                    "attempts": 0}

        with self._lock:
            state = self._load()
            # ``setdefault`` SHART: ``state.get(...) or {}`` bo'sh holatda
            # holatga BOG'LANMAGAN yangi dict qaytaradi va kod bilan kirgan
            # foydalanuvchi tasdiqlanganlar ro'yxatiga TUSHMAS edi
            # (o'rinlar hisobi ham 0 bo'lib qolardi).
            approved = state.setdefault("approved", {})
            pending = state.setdefault("pending", {})
            uid = str(int(user_id))
            if uid in approved:
                return {"allowed": True, "reason": REASON_APPROVED,
                        "code": (approved[uid] or {}).get("code"),
                        "seats_left": self._seats_left(state), "invite_only": True,
                        "attempts": 0}
            if not is_new and uid not in pending:
                # Eski foydalanuvchi (beta yoqilishidan OLDIN ro'yxatdan
                # o'tgan) — uzluksiz ishlayveradi. Faqat beta paytida
                # navbatga qo'yilgan (hali tasdiqlanmagan) foydalanuvchi
                # to'xtatiladi.
                return {"allowed": True, "reason": REASON_EXISTING, "code": None,
                        "seats_left": self._seats_left(state), "invite_only": True,
                        "attempts": 0}

            code = normalize_code(invite_code) if invite_code else ""
            if code:
                found, meta = self._match_code(state, code)
                if found is None:
                    attempts = self._remember_pending(
                        state, user_id, username=username,
                        full_name=full_name, code=code)
                    self._save(state)
                    return {"allowed": False, "reason": REASON_INVALID_CODE,
                            "code": code, "seats_left": self._seats_left(state),
                            "invite_only": True, "attempts": attempts}
                if int(meta.get("uses", 0)) >= int(meta.get("max_uses", 1)):
                    attempts = self._remember_pending(
                        state, user_id, username=username,
                        full_name=full_name, code=code)
                    self._save(state)
                    return {"allowed": False, "reason": REASON_CODE_EXHAUSTED,
                            "code": found, "seats_left": self._seats_left(state),
                            "invite_only": True, "attempts": attempts}
                if not self._has_seat(state):
                    return {"allowed": False, "reason": REASON_BETA_FULL,
                            "code": found, "seats_left": 0, "invite_only": True,
                            "attempts": 0}
                if consume:
                    meta["uses"] = int(meta.get("uses", 0)) + 1
                    meta["last_used_at"] = _now_iso()
                    (state.setdefault("codes") or {})[found] = meta
                    approved[uid] = {
                        "approved_at": _now_iso(),
                        "approved_by": None,
                        "source": "code",
                        "code": found,
                    }
                    (state.get("pending") or {}).pop(uid, None)
                    if not self._save(state):
                        return {"allowed": False, "reason": REASON_STORE_ERROR,
                                "code": found, "seats_left": None,
                                "invite_only": True, "attempts": 0}
                return {"allowed": True, "reason": REASON_INVITE, "code": found,
                        "seats_left": self._seats_left(state), "invite_only": True,
                        "attempts": 0}

            if not self._has_seat(state):
                return {"allowed": False, "reason": REASON_BETA_FULL, "code": None,
                        "seats_left": 0, "invite_only": True, "attempts": 0}
            attempts = self._remember_pending(state, user_id, username=username,
                                              full_name=full_name)
            self._save(state)
            return {"allowed": False, "reason": REASON_PENDING, "code": None,
                    "seats_left": self._seats_left(state), "invite_only": True,
                    "attempts": (attempts if is_new else 0)}

    # -------------------------------------------------------------- ichki
    def _match_code(self, state: dict, code: str) -> tuple[str | None, dict]:
        target = _code_key(code)
        for key, meta in (state.get("codes") or {}).items():
            if _code_key(key) == target:
                return key, dict(meta or {})
        return None, {}

    def _has_seat(self, state: dict | None = None) -> bool:
        limit = self.max_users
        if limit <= 0:
            return True
        data = state if state is not None else self._load()
        return len(data.get("approved") or {}) < limit

    def _seats_left(self, state: dict | None = None) -> int | None:
        limit = self.max_users
        if limit <= 0:
            return None
        data = state if state is not None else self._load()
        return max(0, limit - len(data.get("approved") or {}))


# ---------------------------------------------------------------------------
# Jarayon bo'yicha yagona darvoza
# ---------------------------------------------------------------------------
_default_gate: "BetaGate | None" = None
_default_lock = threading.Lock()


def default_gate() -> BetaGate:
    """Jarayonning yagona darvozasi (holat bazadan har chaqiruvda o'qiladi)."""
    global _default_gate
    if _default_gate is None:
        with _default_lock:
            if _default_gate is None:
                _default_gate = BetaGate()
    return _default_gate


def reset_default_gate() -> None:
    """Faqat testlar uchun — yagona darvozani qayta yaratadi."""
    global _default_gate
    with _default_lock:
        _default_gate = None


def _config_invite_only() -> bool:
    try:
        from config import BETA_INVITE_ONLY  # type: ignore

        return bool(BETA_INVITE_ONLY)
    except Exception:  # noqa: BLE001 — config bo'lmasa darvoza yopiq emas
        return False


def _config_max_users() -> int:
    try:
        from config import BETA_MAX_USERS  # type: ignore

        return int(BETA_MAX_USERS)
    except Exception:  # noqa: BLE001
        return 50


# --- Admin yordamchilari (handlers/beta_access.py ishlatadi) ----------------
def code_row_summary(code: str, meta: dict) -> str:
    """Kod qatorini qisqa matn ko'rinishida (handler i18n bilan o'raydi)."""
    meta = meta or {}
    return (f"{code}: {int(meta.get('uses', 0))}/{int(meta.get('max_uses', 1))}")


__all__ = [
    "BETA_STATE_KEY",
    "BetaGate",
    "DEFAULT_CODE_USES",
    "MAX_CODE_USES",
    "MemoryBetaStore",
    "REASON_ADMIN",
    "REASON_APPROVED",
    "REASON_BETA_FULL",
    "REASON_CODE_EXHAUSTED",
    "REASON_EXISTING",
    "REASON_INVALID_CODE",
    "REASON_INVITE",
    "REASON_OPEN",
    "REASON_PENDING",
    "REASON_STORE_ERROR",
    "SettingsBetaStore",
    "code_row_summary",
    "default_gate",
    "empty_state",
    "generate_code",
    "normalize_code",
    "parse_state",
    "reset_default_gate",
    "serialize_state",
]
