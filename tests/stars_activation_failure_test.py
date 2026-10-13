"""⭐ STARS TO'LOVI FAOLLASHMASA — xatoni kuzatish va adminni ogohlantirish.

Muammo: Telegram Stars to'lovi o'tgan, lekin ``process_stars_payment`` PRO'ni
faollashtira olmasa, handler faqat foydalanuvchiga xabar yuborib jim qolardi
(logda ``charge_id`` yo'q, admin bilmaydi).

Qamrov: odatiy oqim o'zgarmaydi; ``ok=False`` va istisno — log (``charge_id``,
user, qisqa sabab) + adminga xabar; admin xabari yiqilsa ham handler yiqilmaydi;
maxfiy ma'lumot (token, payload) logga chiqmaydi; matnlar uz/ru/en.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/stars_activation_failure_test.py
"""
import asyncio
import logging
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:STARS_FAILURE_TEST_TOKEN")
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
import handlers.subscription as SUB  # noqa: E402
from config import STARS_PLANS  # noqa: E402
from translations.admin_panel import admin_t  # noqa: E402

USER_ID, ADMIN_A, ADMIN_B = 777001, 900001, 900002
CHARGE = "stars_charge_ABC123"
PLAN = STARS_PLANS["stars_1m"]
PAYLOAD = f"sub_stars_1m_{USER_ID}"
BOT_TOKEN = os.environ["BOT_TOKEN"]


class _Msg:
    def __init__(self, payment):
        self.successful_payment = payment
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


class _Bot:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.fail_for:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(f"{record.levelname} {record.getMessage()}")


def _scenario(process_result, lang="uz", bot_fail_for=(), raise_exc=None):
    """successful_payment_callback ni soxta DB/bot bilan ishga tushiradi."""
    payment = SimpleNamespace(
        total_amount=PLAN["stars"], currency="XTR", invoice_payload=PAYLOAD,
        telegram_payment_charge_id=CHARGE, is_recurring=False,
        subscription_expiration_date=None)
    msg = _Msg(payment)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=USER_ID))
    bot = _Bot(bot_fail_for)
    ctx = SimpleNamespace(user_data={"lang": lang}, bot=bot, chat_data={})
    cap = _LogCapture()
    SUB.logger.addHandler(cap)
    old_level = SUB.logger.level
    SUB.logger.setLevel(logging.DEBUG)

    async def fake_run_db(fn, *args, **kw):
        if fn is db_mod.process_stars_payment:
            if raise_exc:
                raise raise_exc
            return process_result
        if fn is db_mod.get_user_language:
            return "ru" if args and args[0] == ADMIN_B else "uz"
        if fn is db_mod.sync_stars_subscription:
            return True
        return lang

    async def fake_ensure_lang(context, user_id):
        return lang

    orig = (db_mod.run_db, SUB.ensure_user_lang, SUB.ADMIN_IDS_SET)
    db_mod.run_db, SUB.ensure_user_lang = fake_run_db, fake_ensure_lang
    SUB.ADMIN_IDS_SET = frozenset({ADMIN_A, ADMIN_B})
    error = None
    try:
        asyncio.run(SUB.successful_payment_callback(upd, ctx))
    except BaseException as exc:  # noqa: BLE001 — handler yiqilmasligi tekshiriladi
        error = exc
    finally:
        db_mod.run_db, SUB.ensure_user_lang, SUB.ADMIN_IDS_SET = orig
        SUB.logger.removeHandler(cap)
        SUB.logger.setLevel(old_level)
    return msg, bot, cap.lines, error


print("\n== 1) Odatiy oqim o'zgarmaydi ==")
msg, bot, logs, err = _scenario({"ok": True, "duplicate": False, "days": 30})
check("muvaffaqiyat: handler xatosiz", err is None, repr(err))
check("muvaffaqiyat: foydalanuvchiga 1 ta xabar", len(msg.sent) == 1, str(msg.sent))
check("muvaffaqiyat: admin ogohlantirilmaydi", bot.sent == [], str(bot.sent))
check("muvaffaqiyat: xato logi yo'q", not any(ln.startswith("ERROR") for ln in logs), str(logs))

msg, bot, logs, err = _scenario({"ok": True, "duplicate": True, "days": 0})
check("duplicate: admin ogohlantirilmaydi", bot.sent == [] and err is None, str(bot.sent))

print("\n== 2) ok=False → log + admin ogohlantirishi ==")
msg, bot, logs, err = _scenario({"ok": False, "duplicate": False, "reason": "database_error"})
check("ok=False: handler yiqilmaydi", err is None, repr(err))
check("ok=False: foydalanuvchiga xabar yuborildi", len(msg.sent) == 1, str(msg.sent))
check("ok=False: log ERROR'da charge_id bor",
      any(ln.startswith("ERROR") and CHARGE in ln for ln in logs), str(logs))
check("ok=False: logda user_id va sabab bor",
      any(str(USER_ID) in ln and "database_error" in ln for ln in logs), str(logs))
check("ok=False: ikkala admin ogohlantirildi",
      sorted(c for c, _ in bot.sent) == [ADMIN_A, ADMIN_B], str(bot.sent))
check("ok=False: admin xabarida charge_id va user_id",
      bool(bot.sent) and all(CHARGE in t and str(USER_ID) in t for _, t in bot.sent), str(bot.sent))

print("\n== 3) Istisno → log + admin ogohlantirishi ==")
msg, bot, logs, err = _scenario(None, raise_exc=RuntimeError("pool timeout secret-dsn"))
check("istisno: handler yiqilmaydi", err is None, repr(err))
check("istisno: foydalanuvchiga xabar yuborildi", len(msg.sent) == 1, str(msg.sent))
check("istisno: log ERROR'da charge_id bor",
      any(ln.startswith("ERROR") and CHARGE in ln for ln in logs), str(logs))
check("istisno: admin ogohlantirishga urinildi", len(bot.sent) == 2, str(bot.sent))
check("istisno: istisno matni (DSN) logga/adminga chiqmaydi",
      not any("secret-dsn" in x for x in logs + [t for _, t in bot.sent]),
      str(logs))

print("\n== 4) Admin xabari xato bersa ==")
msg, bot, logs, err = _scenario({"ok": False, "reason": "user_not_found"},
                                bot_fail_for={ADMIN_A})
check("admin xatosi: handler yiqilmaydi", err is None, repr(err))
check("admin xatosi: ikkinchi admin baribir ogohlantirildi",
      [c for c, _ in bot.sent] == [ADMIN_B], str(bot.sent))
check("admin xatosi: foydalanuvchi xabari yuborildi", len(msg.sent) == 1, str(msg.sent))
check("admin xatosi: to'lov xatosi logda saqlandi",
      any(ln.startswith("ERROR") and CHARGE in ln and "user_not_found" in ln for ln in logs),
      str(logs))
msg, bot, logs, err = _scenario({"ok": False, "reason": "x"}, bot_fail_for={ADMIN_A, ADMIN_B})
check("barcha adminlar xato: handler yiqilmaydi", err is None, repr(err))

print("\n== 5) Foydalanuvchi xabari lokalizatsiyasi ==")
texts = {}
for lang in ("uz", "ru", "en"):
    msg, bot, logs, err = _scenario({"ok": False, "reason": "database_error"}, lang=lang)
    texts[lang] = msg.sent[0] if msg.sent else ""
check("uz/ru/en xabarlari farqli va bo'sh emas",
      all(texts.values()) and len(set(texts.values())) == 3, str(texts))

print("\n== 6) Maxfiylik ==")
msg, bot, logs, err = _scenario({"ok": False, "reason": "database_error"})
blob = "\n".join(logs + [t for _, t in bot.sent])
check("bot tokeni logda/adminga chiqmaydi", BOT_TOKEN not in blob)
check("invoice payload logda/adminga chiqmaydi", PAYLOAD not in blob, blob[:200])
long_reason = "x" * 500
msg, bot, logs, err = _scenario({"ok": False, "reason": long_reason})
check("sabab qisqartiriladi", not any(long_reason in ln for ln in logs + [t for _, t in bot.sent]))

print("\n== 7) Admin matnlari uz/ru/en ==")
for lang in ("uz", "ru", "en"):
    t = admin_t("stars_activation_failed_admin", lang, user_id=1, charge_id="C", days=30,
                reason="r")
    check(f"admin matni [{lang}] mavjud va to'ldirilgan",
          "C" in t and "{" not in t and t != "stars_activation_failed_admin", t)
check("admin matni tillar bo'yicha farqli",
      len({admin_t("stars_activation_failed_admin", ln, user_id=1, charge_id="C", days=30,
                   reason="r") for ln in ("uz", "ru", "en")}) == 3)

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
