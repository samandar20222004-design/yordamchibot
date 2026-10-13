"""🔐 KANAL USLUBI — egalik (IDOR) tekshiruvi.

Muammo: ``tone_menu_callback`` (``tone_channel_id`` ni yozadi) va matnli
``tone_chosen`` (``set_channel_tone`` ni chaqiradi) kanal ustida ruxsatni
tekshirmasdi; faqat inline ``tone_chosen_callback`` tekshirardi.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/channel_tone_ownership_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TONE_OWNERSHIP_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


import database as db_mod  # noqa: E402
import handlers.channels as CH  # noqa: E402
from keyboards.default import TONE_LABELS  # noqa: E402
from services import rbac_service  # noqa: E402
from services.rbac_service import AccessDecision  # noqa: E402

OWNER, STRANGER = 777001, 888002
OWN_CH, FOREIGN_CH = "-1001234567890", "-1009999999999"


class _Msg:
    def __init__(self, uid, text=""):
        self.text = text
        self.from_user = SimpleNamespace(id=uid)
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


class _Query:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.message = _Msg(uid)

    async def answer(self, *a, **kw):
        return True


def _ctx(**ud):
    return SimpleNamespace(user_data={"lang": "uz", **ud}, chat_data={},
                           bot=SimpleNamespace(username="t_bot"), application=None)


def _run(coro_factory):
    """Soxta RBAC (faqat OWNER → OWN_CH) va soxta DB bilan bajaradi."""
    tone_writes = []

    async def fake_run_db(fn, *args, **kw):
        if fn is db_mod.set_channel_tone:
            tone_writes.append(args)
            return True
        if fn is db_mod.get_channel_tone:
            return "friendly"
        raise AssertionError(f"kutilmagan db chaqiruvi: {getattr(fn, '__name__', fn)}")

    async def fake_check(user_id, *, resource_type, resource_id, action, **kw):
        ok = user_id == OWNER and str(resource_id) == OWN_CH
        return AccessDecision(ok, user_id=user_id, resource_id=str(resource_id),
                              action=action, reason="ok" if ok else "denied")

    orig = (db_mod.run_db, rbac_service.check)
    db_mod.run_db, rbac_service.check = fake_run_db, fake_check
    try:
        result = asyncio.run(coro_factory())
    finally:
        db_mod.run_db, rbac_service.check = orig
    return result, tone_writes


def _tone_menu(uid, ch):
    q = _Query(f"ch_set:{ch}", uid)
    upd = SimpleNamespace(message=None, effective_message=q.message,
                          effective_user=q.from_user, callback_query=q)
    ctx = _ctx()
    state, writes = _run(lambda: CH.tone_menu_callback(upd, ctx))
    return state, ctx, q


def _tone_text(uid, ch, text=None):
    text = text or TONE_LABELS["formal"]
    msg = _Msg(uid, text)
    upd = SimpleNamespace(message=msg, effective_message=msg,
                          effective_user=msg.from_user, callback_query=None)
    ctx = _ctx(tone_channel_id=ch)
    state, writes = _run(lambda: CH.tone_chosen(upd, ctx))
    return state, writes, msg


print("\n== Kanal uslubi: egalik tekshiruvi ==")

state, ctx, q = _tone_menu(STRANGER, FOREIGN_CH)
check("begona: tone_menu_callback kanal ID'sini FSM'ga yozmaydi",
      "tone_channel_id" not in ctx.user_data, str(ctx.user_data))
check("begona: tone_menu_callback SET_TONE holatiga o'tkazmaydi",
      state != CH.SET_TONE, str(state))

state, ctx, q = _tone_menu(OWNER, OWN_CH)
check("egasi: tone_menu_callback SET_TONE ochadi",
      state == CH.SET_TONE and ctx.user_data.get("tone_channel_id") == OWN_CH, str(state))

state, writes, msg = _tone_text(STRANGER, FOREIGN_CH)
check("begona: matnli tone_chosen bazaga YOZMAYDI", writes == [], str(writes))
check("begona: foydalanuvchiga xato xabari ko'rsatiladi", len(msg.sent) == 1, str(msg.sent))

state, writes, msg = _tone_text(OWNER, OWN_CH)
check("egasi: matnli tone_chosen uslubni saqlaydi",
      writes == [(OWN_CH, "formal")], str(writes))

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
