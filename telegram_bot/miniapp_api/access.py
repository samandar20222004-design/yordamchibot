"""Foydalanuvchi ruxsati (faqat O'QISH, yon ta'sirsiz).

Mavjud ``BetaGate.check()`` kutilayotgan foydalanuvchini ``pending`` ro'yxatiga
YOZADI va saqlaydi — shuning uchun API uni CHAQIRMAYDI. Bu yerda botdagi
qoidalar (``services/beta_gate.py``) holatni o'zgartirmasdan qayta ifodalanadi:

  * ``users`` jadvalida qator bo'lishi shart va ``deleted_at IS NULL``
    (soft-delete qilingan hisob kirmaydi). API foydalanuvchi YARATMAYDI;
  * darvoza o'chiq (``invite_only=False``) -> ruxsat;
  * admin (``ADMIN_ID``/``ADMIN_IDS`` yoki ``users.role``) -> ruxsat;
  * ``approved`` ro'yxatida -> ruxsat;
  * ``pending`` ro'yxatida -> RAD;
  * boshqa barcha holat -> RAD.

Botdagi ``REASON_EXISTING`` qoidasi (``BetaGate.check``: qatori bor, ``approved`` bo'lmasa ham,
``pending`` ro'yxatida BO'LMAGAN foydalanuvchi — beta yoqilishidan oldingi eski
foydalanuvchi) bu yerda ham AYNAN shunday: botga kira oladigan odam Mini App'ga ham kiradi.
Yangi foydalanuvchi botda kod/tasdiq bo'lmasa ``pending``ga tushadi, shuning uchun
``pending`` doim rad etiladi.

Beta holati o'qilmasa yoki JSON yaroqsiz bo'lsa — ruxsat berilmaydi
(:class:`AccessStateError`, ya'ni 503).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

BETA_STATE_KEY = "beta_gate_state"  # services.beta_gate.BETA_STATE_KEY bilan bir xil


class AccessStateError(Exception):
    """Beta holatini ishonchli o'qib bo'lmadi (fail-closed -> 503)."""


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    code: str | None  # ApiError kodi (rad bo'lsa)
    reason: str


def _strict_state(raw) -> dict:
    """``system_settings.value`` -> holat. Yo'q/bo'sh = bo'sh holat; buzuq = xato."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {"enabled": None, "approved": {}, "pending": {}}
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, RecursionError):
            raise AccessStateError("beta state JSON yaroqsiz") from None
    if not isinstance(data, dict):
        raise AccessStateError("beta state obyekt emas")
    approved = data.get("approved", {})
    pending = data.get("pending", {})
    if not isinstance(approved, dict) or not isinstance(pending, dict):
        raise AccessStateError("beta state bo'limlari yaroqsiz")
    enabled = data.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise AccessStateError("beta state 'enabled' yaroqsiz")
    return {"enabled": enabled, "approved": approved, "pending": pending}


def _invite_only(state_enabled, config_invite_only: bool) -> bool:
    return bool(state_enabled) if state_enabled is not None else bool(config_invite_only)


def evaluate_access(user_id: int, *, user_exists: bool, deleted: bool,
                    is_admin: bool, beta_raw, config_invite_only: bool) -> AccessDecision:
    if not user_exists or deleted:
        return AccessDecision(False, "not_registered", "not_registered")
    state = _strict_state(beta_raw)  # xato bo'lsa AccessStateError
    if not _invite_only(state["enabled"], config_invite_only):
        return AccessDecision(True, None, "open_mode")
    if is_admin:
        return AccessDecision(True, None, "admin_access")
    uid = str(int(user_id))
    if uid in state["approved"]:
        return AccessDecision(True, None, "admin_approved")
    if uid in state["pending"]:
        return AccessDecision(False, "beta_access_required", "pending_approval")
    # Bot bilan bir xil: ``pending`` emas va qator bor — eski foydalanuvchi, uzluksiz ishlaydi.
    return AccessDecision(True, None, "existing_user")
