#!/usr/bin/env python3
"""Bot: tabiiy til va ovozli rejalash oqimi (`handlers/schedule_smart.py`) — soxta Telegram/DB bilan.

* matn: takrorlanuvchi ibora tasdiq kartasiga o'tadi (holat kalitlari to'g'ri); oddiy vaqt eski parserga qoladi;
* ovoz: kvota STT'dan OLDIN; rad etilsa STT chaqirilmaydi; STT xatosi / tushunilmagan matn -> bron QAYTADI;
  muvaffaqiyatda bron saqlanadi; admin bron olmaydi; free'ga «bir martalik» eslatma;
* uch tilda matn mavjud va to'ldirilgan.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:SCHEDULE_SMART_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


from handlers import schedule_smart as ss  # noqa: E402
from locales.translations import TRANSLATIONS  # noqa: E402
from services.recurrence import TASHKENT  # noqa: E402

print("== Bot: tabiiy til va ovozli rejalash ==")

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=TASHKENT)


class Msg:
    def __init__(self, voice=True, duration=5, size=1000):
        self.sent = []
        self.voice = SimpleNamespace(file_id="f", duration=duration, file_size=size, file_name=None) if voice else None
        self.audio = None

    async def reply_text(self, text, **kw):
        self.sent.append(text)


def make(lang="uz", **kw):
    msg = Msg(**kw)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=555))

    class FakeFile:
        async def download_as_bytearray(self):
            return bytearray(b"x" * 100)

    class Bot:
        async def get_file(self, fid):
            return FakeFile()

    ctx = SimpleNamespace(user_data={"lang": lang}, bot=Bot())
    return upd, ctx, msg


# --- fake infratuzilma ---
state = {"reserved": 0, "released": 0, "stt_calls": 0, "cards": 0, "premium": False}
RES = {"allowed": True, "reservation_id": 11, "scope": "lifetime", "used": 1, "limit": 1, "reason": "ok"}
STT = {"text": "har dam olish kuni soat 12:00"}


async def fake_reserve(db, uid, pro, admin=False):
    state["reserved"] += 1
    return dict(RES)


async def fake_release(db, uid, rid):
    state["released"] += 1


async def fake_stt(data, filename):
    state["stt_calls"] += 1
    return dict(STT)


async def fake_run_db(fn, *a, **k):
    return state["premium"]


async def fake_card(message, context):
    state["cards"] += 1


ss.voice_quota.reserve = fake_reserve
ss.voice_quota.release = fake_release
ss.transcribe_voice = fake_stt
ss.db.run_db = fake_run_db
import handlers.new_post as np  # noqa: E402

np._show_confirmation = fake_card
ss.get_lang = lambda ctx: ctx.user_data.get("lang", "uz")


def reset(res=None, stt=None):
    global RES, STT
    state.update(reserved=0, released=0, stt_calls=0, cards=0, premium=False)
    RES = res or {"allowed": True, "reservation_id": 11, "scope": "lifetime", "used": 1, "limit": 1, "reason": "ok"}
    STT = stt or {"text": "har dam olish kuni soat 12:00"}


# --- matn ---
p = ss.try_text("har dam olish kuni soat 12:00", NOW)
check("matn: dam olish kuni -> weekdays proposal", p is not None and p["recurrence"]["type"] == "weekdays" and p["recurrence"]["day"] == 96, str(p))
p = ss.try_text("ikki kunda bir marta 18:30", NOW)
check("matn: ikki kunda bir -> interval 2", p is not None and p["recurrence"]["type"] == "interval" and p["recurrence"]["day"] == 2, str(p))
check("matn: oddiy vaqt (18:00) eski parserga qoladi (None)", ss.try_text("18:00", NOW) is None)
check("matn: bir martalik 'ertaga 9:00' ham eski parserga (None)", ss.try_text("ertaga 9:00", NOW) is None)
check("matn: bema'ni matn None", ss.try_text("salom qalaysan", NOW) is None)

# --- apply_proposal ---
ctx = SimpleNamespace(user_data={})
ss.apply_proposal(ctx, NOW, p["recurrence"] if p else {"type": "interval", "day": 2, "time": NOW.time()})
ud = ctx.user_data
check("apply: confirm_* kalitlari qo'lda kiritish shaklida", ud["confirm_recurrence_type"] == "interval" and ud["confirm_recurrence_day"] == 2
      and ud["confirm_recurrence_time_str"].endswith(":00") and ud["confirm_end_date"] is None and ud["confirm_post_time"] == NOW, str(ud))
ss.apply_proposal(ctx, NOW, None)
check("apply: bir martalik -> type none", ud["confirm_recurrence_type"] == "none" and ud["confirm_recurrence_time_str"] is None)

# --- ovoz: muvaffaqiyat (free) ---
reset()
upd, ctx, msg = make("uz")
r = asyncio.run(ss.time_voice_received(upd, ctx))
from handlers.new_post import CONFIRM_POST, GET_TIME  # noqa: E402
check("ovoz: muvaffaqiyat -> CONFIRM_POST, karta bir marta", r == CONFIRM_POST and state["cards"] == 1, str(r))
check("ovoz: bron saqlandi (qaytarilmadi), STT 1 marta", state["reserved"] == 1 and state["released"] == 0 and state["stt_calls"] == 1)
check("ovoz: holat — weekdays 96", ctx.user_data.get("confirm_recurrence_type") == "weekdays" and ctx.user_data.get("confirm_recurrence_day") == 96)
check("ovoz: free'ga «bir martalik» eslatma va eshitilgan matn ko'rsatildi", any("Eshitildi" in t and "bir marta" in t for t in msg.sent), str(msg.sent))

# --- ovoz: kvota rad ---
for res, label in (
    ({"allowed": False, "reservation_id": None, "scope": "lifetime", "used": 1, "limit": 1, "reason": "limit"}, "free limit"),
    ({"allowed": False, "reservation_id": None, "scope": "day", "used": 20, "limit": 20, "reason": "limit"}, "PRO limit"),
    ({"allowed": False, "reservation_id": None, "scope": "day", "used": 0, "limit": 0, "reason": "disabled"}, "o'chirilgan"),
    ({"allowed": False, "reservation_id": None, "scope": "day", "used": 0, "limit": 20, "reason": "unavailable"}, "DB xato"),
):
    reset(res)
    upd, ctx, msg = make("ru")
    r = asyncio.run(ss.time_voice_received(upd, ctx))
    check(f"ovoz rad ({label}): GET_TIME, STT chaqirilmadi, karta yo'q, xabar bor",
          r == GET_TIME and state["stt_calls"] == 0 and state["cards"] == 0 and len(msg.sent) == 1 and "🎤" in msg.sent[0], str(msg.sent))

# --- ovoz: STT xato / bo'sh / tushunilmagan -> bron qaytadi ---
for stt, label in (({"error": "x"}, "STT xato"), ({"text": ""}, "bo'sh matn"), ({"text": "salom qalaysan"}, "vaqt tushunilmadi")):
    reset(stt=stt)
    upd, ctx, msg = make("en")
    r = asyncio.run(ss.time_voice_received(upd, ctx))
    check(f"ovoz ({label}): GET_TIME, bron QAYTARILDI, karta yo'q", r == GET_TIME and state["released"] == 1 and state["cards"] == 0, str(state))

# --- ovoz: STT istisno ---
async def boom(data, filename):
    raise RuntimeError("tarmoq")
ss.transcribe_voice = boom
reset()
upd, ctx, msg = make()
r = asyncio.run(ss.time_voice_received(upd, ctx))
check("ovoz: STT istisnosi yutiladi, bron qaytadi", r == GET_TIME and state["released"] == 1)
ss.transcribe_voice = fake_stt

# --- ovoz: uzunlik chegarasi kvotadan oldin ---
reset()
upd, ctx, msg = make(duration=100000)
r = asyncio.run(ss.time_voice_received(upd, ctx))
check("ovoz: juda uzun -> kvota BRON QILINMADI", r == GET_TIME and state["reserved"] == 0 and state["stt_calls"] == 0)

# --- admin: reservation_id None, eslatma yo'q ---
reset(res={"allowed": True, "reservation_id": None, "scope": "admin", "used": 0, "limit": 0, "reason": "ok"})
_orig_admins = ss.ADMIN_IDS_SET
ss.ADMIN_IDS_SET = frozenset({555})
upd, ctx, msg = make()
r = asyncio.run(ss.time_voice_received(upd, ctx))
ss.ADMIN_IDS_SET = _orig_admins
check("admin: o'tadi, «bir martalik» eslatma yo'q", r == CONFIRM_POST and not any("bir marta" in t for t in msg.sent), str(msg.sent))

# --- ovozsiz xabar ---
reset()
upd, ctx, msg = make(voice=False)
r = asyncio.run(ss.time_voice_received(upd, ctx))
check("ovozsiz xabar: e'tiborsiz, kvota tegilmadi", r == GET_TIME and state["reserved"] == 0)

# --- i18n ---
KEYS = ("vs_limit_free", "vs_limit_pro", "vs_disabled", "vs_unavailable", "vs_heard", "vs_not_understood", "vs_free_used_note")
for lang in ("uz", "ru", "en"):
    tbl = TRANSLATIONS[lang]
    check(f"i18n {lang}: barcha vs_* kalitlari bor", all(tbl.get(k) for k in KEYS))
check("i18n: ru/en matnlari uz'dan farq qiladi", all(TRANSLATIONS["ru"][k] != TRANSLATIONS["uz"][k] and TRANSLATIONS["en"][k] != TRANSLATIONS["uz"][k] for k in KEYS))
for lang in ("uz", "ru", "en"):
    check(f"i18n {lang}: np_time_ask ovoz va tabiiy tilni eslatadi", "🎤" in TRANSLATIONS[lang]["np_time_ask"] and "{example}" in TRANSLATIONS[lang]["np_time_ask"])

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(1 if failed else 0)
