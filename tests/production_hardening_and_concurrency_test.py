#!/usr/bin/env python3
"""🛡⚡ FAZA 23/25/27/28/29 — PRODUCTION HARDENING & CONCURRENCY SUITE.

8-sprint yakuniy bosqichning QAT'IY qabul testi. Har bir natija FAQAT aniq
fakt bilan belgilanadi: ``[PASS]`` | ``[FAIL]`` | ``[NOT TESTED]``
(soxta PASS taqiqlanadi — resurs/muhit cheklovi bo'lsa NOT TESTED yoziladi).

Qamrov
------
TEST 1 (FAZA 23 — IDOR): ``handlers/pending.py`` dagi
    ``edit_post_time_start`` / ``edit_post_content_start`` /
    ``edit_post_btn_start`` / ``edit_post_react_start`` callback'lari post
    ID'si olingan ZAHOTI egalik tekshiruvidan o'tkaziladi (fail-closed):
      * begona post  → darhol rad (alert, FSM holati o'rnatilmaydi);
      * o'z posti    → ruxsat (FSM davom etadi);
      * post yo'q    → rad;
      * DB xatosi    → HAM rad (fail-closed — "except" ichida ruxsat yo'q).
    Sinfik tekshiruv: egalik guard'i FSM yozuvidan OLDIN chaqiriladi.

TEST 2 (FAZA 23 — SSRF): ichki tarmoq manzillari (localhost, 127.0.0.1,
    192.168.*, 10.*, 172.16-31.*, 169.254.* metadata) havolali tugmalarda
    (``utils.security.url_rejection_reason``) VA manbalarda
    (``validate_public_url``) QAT'IY bloklanadi; klassik chetlab o'tish
    shakllari (o'nlik/sakkizlik/hex IP, 127.1, [::1]) ham bloklanadi;
    ``pending.edit_post_btn_received`` orqali saqlanadigan tugma havolasi
    ham shu guard'dan o'tadi (xavfli URL DB'ga yozilmaydi).

TEST 3 (FAZA 23 — MAXFIYLIK): bot token, DB paroli (URL ichida), karta
    raqamlari va API kalitlar xato loglariga TUSHMAYDI — stdlib logging
    filtri (``utils.sentry_scrubber``) real handler oqimida tekshiriladi,
    config ro'yxatga olgan haqiqiy qiymatlar ham scrub qilinadi.

TEST 4 (FAZA 25 — TIMEOUTS): ``utils.handler_timeout`` qat'iy asinxron
    chegaralar; ``UPDATE_HANDLER_TIMEOUT_SECONDS`` /
    ``BACKGROUND_TASK_TIMEOUT_SECONDS`` konfiguratsiyasi hujjatlangan;
    ``main.py GuardedApplication`` update zanjiriga watchdog o'rnatilgan
    (fon vazifalari intake'ni bloklamaydi).

TEST 5 (FAZA 28/29 — CONCURRENCY / LOAD): parallel virtual foydalanuvchilar
    va concurrent AI so'rovlari simulyatsiyasi — semafor to'yintirilishi
    (peak ≤ limit), bounded queue to'lganda fail-closed ``AIQueueFullError``,
    40 ta parallel IDOR hujumi (har biri rad etiladi), 16 ta parallel
    "sekin provayder" timeout'i (barchasi chegarada kesiladi) va asyncio
    task-leak tekshiruvi.

Ishga tushirish::

    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
    # yoki alohida:
    python3 tests/production_hardening_and_concurrency_test.py
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

# ---- MUHIM: production modullar import qilinishidan OLDIN env sozlash ----
os.environ.setdefault("BOT_TOKEN", "123456:PH_HARDENING_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

PASS_COUNT = 0
FAIL_COUNT = 0
NOT_TESTED: list[tuple[str, str]] = []


def check(name: str, cond: bool, extra: str = "") -> bool:
    """Yagona natija belgilagich — [PASS] yoki [FAIL] (aniq fakt)."""
    global PASS_COUNT, FAIL_COUNT
    if cond:
        PASS_COUNT += 1
        print(f"  [PASS] {name}")
    else:
        FAIL_COUNT += 1
        print(f"  [FAIL] {name} {extra}")
    return bool(cond)


def not_tested(name: str, reason: str) -> None:
    """Muhit/resurs cheklovi — yashirilmaydi, NOT TESTED deb qayd etiladi."""
    NOT_TESTED.append((name, reason))
    print(f"  [NOT TESTED] {name} — {reason}")


def header(title: str) -> None:
    print()
    print("=" * 66)
    print(f" {title}")
    print("=" * 66)


# ============================================================================
# MOCK INFRASTRUKTURA — Telegram update/query/context taqlidi
# ============================================================================
class _FakeQuery:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat_id=user_id)
        self.answers: list[tuple] = []  # (text, show_alert)

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append((text, show_alert))


class _FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append(str(text))


class _FakeBot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text})


class _FakeContext:
    def __init__(self, lang: str = "uz"):
        self.user_data: dict = {"lang": lang}
        self.bot = _FakeBot()


class _FakeUpdate:
    def __init__(self, query: _FakeQuery | None, user_id: int,
                 message: _FakeMessage | None = None):
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=user_id)
        self.message = message or _FakeMessage()


def _patched_run_db(post_owners: dict, calls: list, *, fail: bool = False):
    """``database.run_db`` taqlidi: post egalari xaritasi va chaqiruv jurnali.

    ``fail=True`` — DB uzilib qolganini taqlid qiladi (fail-closed ssenariy).
    """
    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", repr(fn))
        calls.append((name, args))
        if fail:
            raise RuntimeError("simulyatsiya: DB uzildi")
        if name == "get_post_by_id":
            post_id = args[0]
            owner = post_owners.get(post_id)
            if owner is None:
                return None
            # select: id, user_id, channel_id, post_type, scheduled_time, ...
            return (post_id, owner, -100123456, "text", None, None, None, 1)
        if name in ("update_post_time", "update_post_content"):
            return True
        return None
    return fake_run_db


# ============================================================================
# TEST 1 — FAZA 23: IDOR (callback'lar bosilgan zahoti egalik tekshiruvi)
# ============================================================================
def test_idor_pending_callbacks() -> None:
    header("TEST 1 — FAZA 23: IDOR — pending.py callback egalik guard'i")
    import database as db_mod
    import handlers.pending as P
    from telegram.ext import ConversationHandler

    OWNER_ID = 700100001
    ATTACKER_ID = 800200002
    POST_ID = 4242

    handlers_map = (
        ("edit_post_time_start", P.edit_post_time_start, f"p_time:{POST_ID}",
         P.EDIT_POST_TIME),
        ("edit_post_content_start", P.edit_post_content_start,
         f"p_edit:{POST_ID}", P.EDIT_POST_CONTENT),
        ("edit_post_btn_start", P.edit_post_btn_start, f"p_btn:{POST_ID}",
         P.EDIT_POST_BTN),
        ("edit_post_react_start", P.edit_post_react_start,
         f"p_react:{POST_ID}", P.EDIT_POST_REACT),
    )

    original_run_db = db_mod.run_db
    try:
        from locales.translations import get_text
        expected_deny = get_text("pend_not_owned", "uz")

        for fname, fn, data, expected_state in handlers_map:
            # (a) BEGONA POST — darhol rad etiladi (fail-closed).
            calls: list = []
            db_mod.run_db = _patched_run_db({POST_ID: OWNER_ID}, calls)
            q = _FakeQuery(data, ATTACKER_ID)
            ctx = _FakeContext()
            upd = _FakeUpdate(q, ATTACKER_ID)
            state = asyncio.run(fn(upd, ctx))
            check(f"{fname}: begona post → ConversationHandler.END",
                  state == ConversationHandler.END, f"state={state}")
            check(f"{fname}: begona → FSM holati O'RNATILMADI",
                  "editing_post_id" not in ctx.user_data
                  and "edit_mode" not in ctx.user_data,
                  str(ctx.user_data))
            check(f"{fname}: begona → alert (show_alert=True)",
                  any(a[1] is True for a in q.answers), str(q.answers))
            check(f"{fname}: begona → rad xabari lokalizatsiyadan",
                  any(expected_deny in (a[0] or "") for a in q.answers),
                  str(q.answers)[:120])
            check(f"{fname}: begona → tahrirlash so'rovi YUBORILMADI",
                  not ctx.bot.sent, str(ctx.bot.sent)[:100])
            check(f"{fname}: begona → DB hech qanday YOZUV olmadi",
                  all(c[0] == "get_post_by_id" for c in calls), str(calls))

            # (b) O'Z POSTI — ruxsat beriladi, FSM to'g'ri holatga o'tadi.
            calls = []
            db_mod.run_db = _patched_run_db({POST_ID: OWNER_ID}, calls)
            q = _FakeQuery(data, OWNER_ID)
            ctx = _FakeContext()
            upd = _FakeUpdate(q, OWNER_ID)
            state = asyncio.run(fn(upd, ctx))
            check(f"{fname}: o'z posti → kutilgan FSM holati ({expected_state})",
                  state == expected_state, f"state={state}")
            check(f"{fname}: o'z posti → FSM ma'lumoti saqlandi",
                  ctx.user_data.get("editing_post_id") == POST_ID,
                  str(ctx.user_data))
            check(f"{fname}: o'z posti → savol xabari yuborildi",
                  len(ctx.bot.sent) == 1, str(ctx.bot.sent)[:100])
            check(f"{fname}: o'z posti → alert'siz answer",
                  all(a[1] is False for a in q.answers), str(q.answers))

            # (c) POST MAVJUD EMAS — rad etiladi.
            db_mod.run_db = _patched_run_db({}, calls)
            q = _FakeQuery(data, OWNER_ID)
            ctx = _FakeContext()
            state = asyncio.run(fn(_FakeUpdate(q, OWNER_ID), ctx))
            check(f"{fname}: post yo'q → rad (END + alert)",
                  state == ConversationHandler.END
                  and any(a[1] is True for a in q.answers), f"state={state}")

            # (d) DB XATOSI — fail-closed rad etiladi ("except"da ruxsat yo'q).
            db_mod.run_db = _patched_run_db({POST_ID: OWNER_ID}, calls, fail=True)
            q = _FakeQuery(data, OWNER_ID)
            ctx = _FakeContext()
            state = asyncio.run(fn(_FakeUpdate(q, OWNER_ID), ctx))
            check(f"{fname}: DB xatosi → FAIL-CLOSED rad (END, state yo'q)",
                  state == ConversationHandler.END
                  and "editing_post_id" not in ctx.user_data, f"state={state}")

        # (e) STATIK GARANTIYA: guard FSM yozuvidan OLDIN turadi.
        src = (ROOT / "telegram_bot" / "handlers" / "pending.py").read_text(
            encoding="utf-8")
        check("pending.py: _callback_owns_post funksiyasi mavjud",
              "async def _callback_owns_post" in src)
        for fname, _fn, _data, _state in handlers_map:
            body = src.split(f"async def {fname}", 1)[1].split(
                "\nasync def ", 1)[0]
            guard_pos = body.find("_callback_owns_post(query")
            fsm_pos = body.find('context.user_data["editing_post_id"]')
            check(f"{fname}: guard FSM yozuvidan OLDIN (statik tartib)",
                  0 < guard_pos < fsm_pos or (fsm_pos == -1 and guard_pos > 0),
                  f"guard={guard_pos} fsm={fsm_pos}")
        check("pending.py: IDOR urinishlari logga yoziladi (audit iz)",
              "IDOR urinishi bloklandi" in src)
    finally:
        db_mod.run_db = original_run_db


# ============================================================================
# TEST 2 — FAZA 23: SSRF — ichki tarmoq bloklanishi (tugmalar + manbalar)
# ============================================================================
def test_ssrf_button_and_sources() -> None:
    header("TEST 2 — FAZA 23: SSRF — ichki tarmoq manzillari bloklanadi")
    from utils.security import (
        url_rejection_reason, validate_button_url, is_blocked_private_host,
    )

    # Ichki tarmoq matritsasi — HAMMASI QAT'IY bloklanishi shart.
    blocked_urls = (
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "https://127.0.0.1/webhook",
        "http://127.1/",                             # qisqa shakl
        "http://2130706433/",                         # o'nlik (127.0.0.1)
        "http://0x7f000001/",                         # hex (127.0.0.1)
        "http://0177.0.0.1/",                         # sakkizlik
        "http://[::1]/",                              # IPv6 loopback
        "https://localhost/",                         # localhost nomi
        "http://localhost.localdomain/",
        "http://10.0.0.5/internal",
        "http://10.255.255.254/",
        "http://172.16.5.4/",
        "http://172.31.255.255/",
        "http://192.168.1.1/router",
        "http://192.168.0.254/",
        "http://169.254.169.254/latest/meta-data",    # AWS/GCP metadata!
        "http://100.64.0.1/",                         # CGNAT
        "http://metadata.google.internal/",           # ichki domen
        "http://app.corp/secret",                     # ichki suffix
        "http://wiki.intranet/",
        "http://[fe80::1]/",                          # link-local IPv6
        "http://[fc00::1]/",                          # unique-local IPv6
    )
    all_blocked = True
    bad_reasons = []
    for url in blocked_urls:
        ok = validate_button_url(url)
        if ok:
            all_blocked = False
            bad_reasons.append((url, f"RUXSAT: {url_rejection_reason(url)!r}"))
    check("SSRF: barcha ichki tarmoq havolalari tugmada bloklangan "
          f"({len(blocked_urls)} ta)", all_blocked, str(bad_reasons))

    # Blok sababi aniq: asosiy hollarda 'private_address'.
    for url, expect in (
        ("http://127.0.0.1/", "private_address"),
        ("http://192.168.1.1/", "private_address"),
        ("http://10.0.0.5/", "private_address"),
        ("http://169.254.169.254/", "private_address"),
        ("http://metadata.google.internal/", "private_address"),
        ("http://2130706433/", "private_address"),
        ("http://127.1/", "private_address"),
    ):
        check(f"SSRF: {url} → sabab '{expect}'",
              url_rejection_reason(url) == expect,
              url_rejection_reason(url))

    # Ommaviy (xavfsiz) havolalar o'zgarishsiz RUXSAT etiladi (regressiya yo'q).
    public_urls = (
        "https://t.me/kanal", "http://example.com/a?b=1",
        "tg://resolve?domain=yordamchibot", "https://t.me/x#anchor",
        "HTTPS://T.ME/KANAL", "https://example.com:8443/path",
    )
    for url in public_urls:
        check(f"SSRF: ommaviy havola ruxsat saqlangan: {url}",
              validate_button_url(url) is True, url_rejection_reason(url))

    # Xavfli sxemalar avvalgidek bloklanadi (regressiya yo'q).
    for url in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd"):
        check(f"SSRF: xavfli sxema bloklangan: {url.split(':')[0]}:",
              validate_button_url(url) is False)

    # is_blocked_private_host — to'g'ridan-to'g'ri birlik tekshiruvi.
    check("guard: 'localhost' bloklangan", is_blocked_private_host("localhost"))
    check("guard: 'example.com' bloklanmagan",
          not is_blocked_private_host("example.com"))

    # --- Manbalar qatlami (validate_public_url) bilan PARITET --------------
    try:
        from services.sources.url_extractor import validate_public_url
    except Exception as e:  # pragma: no cover
        not_tested("validate_public_url pariteti", f"import: {e}")
        return
    src_blocked = (
        "http://127.0.0.1/", "http://localhost/x", "http://192.168.1.1/",
        "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
        "http://[::1]/", "http://172.16.0.1/",
    )
    parity_ok = True
    detail = []
    for url in src_blocked:
        # IP literallari va bloklangan nomlar DNS'siz ham rad etiladi.
        res = validate_public_url(url, resolve_dns=False)
        if res.get("ok"):
            parity_ok = False
            detail.append(url)
        # Ikkala qatlam (tugma + manba) bir xil qarorga kelishi shart.
        if validate_button_url(url) is not False and res.get("ok") is False:
            parity_ok = False
            detail.append(f"farq: {url}")
    check("SSRF: manbalar qatlami (validate_public_url) ham bloklaydi "
          "→ IKKI QATLAM PARITETI", parity_ok, str(detail))

    # --- pending.edit_post_btn_received — saqlanadigan tugma URL guard'i ---
    import database as db_mod
    import handlers.pending as P
    OWNER_ID, POST_ID = 700100001, 5151
    original_run_db = db_mod.run_db
    try:
        for bad_url in ("http://192.168.1.1/x", "http://127.0.0.1:8080/a",
                        "http://169.254.169.254/", "javascript:alert(1)",
                        "file:///etc/passwd"):
            calls: list = []
            db_mod.run_db = _patched_run_db({POST_ID: OWNER_ID}, calls)
            ctx = _FakeContext()
            ctx.user_data["editing_post_id"] = POST_ID  # *_start bosqichi holati
            msg = _FakeMessage(text=f"Batafsil | {bad_url}")
            upd = _FakeUpdate(None, OWNER_ID, message=msg)
            state = asyncio.run(P.edit_post_btn_received(upd, ctx))
            check(f"btn flow: xavfli URL saqlanmadi: {bad_url[:36]}",
                  state == P.EDIT_POST_BTN
                  and not any(c[0] == "update_post_content" for c in calls),
                  f"state={state} calls={[c[0] for c in calls]}")
            check("btn flow: foydalanuvchiga ogohlantirish berildi",
                  bool(msg.replies))

        # Ijobiy nazorat: xavfsiz URL saqlanadi.
        calls = []
        db_mod.run_db = _patched_run_db({POST_ID: OWNER_ID}, calls)
        ctx = _FakeContext()
        ctx.user_data["editing_post_id"] = POST_ID
        msg = _FakeMessage(text="Batafsil | https://t.me/yordamchi")
        upd = _FakeUpdate(None, OWNER_ID, message=msg)
        state = asyncio.run(P.edit_post_btn_received(upd, ctx))
        check("btn flow: xavfsiz URL saqlandi (update_post_content)",
              any(c[0] == "update_post_content" for c in calls),
              str([c[0] for c in calls]))
    finally:
        db_mod.run_db = original_run_db


# ============================================================================
# TEST 3 — FAZA 23: MAXFIYLIK — secret'lar xato loglariga tushmaydi
# ============================================================================
def test_secrets_never_in_error_logs() -> None:
    header("TEST 3 — FAZA 23: MAXFIYLIK — loglar toza (scrubbing)")
    import config
    from utils.sentry_scrubber import (
        SecretScrubbingFilter, install_logging_scrubber, scrub_text,
        scrub_event, REDACTED_TOKEN,
    )

    fake_token = "9988776655:AAHfakeTokenStringForScrubTest_abcdef123456"
    db_url = "postgresql://botuser:SuperSecretDBPassw0rd_2026@db.internal:5432/prod"
    openai_key = "sk-TestOpenAIstyleKey_abcdef1234567890"
    gemini_key = "AIza" + "Sy" + "X" * 35
    gh_key = "ghp_" + "A1b2C3d4" * 5
    card = "8600 0609 5082 5589"

    # (1) scrub_text — PURE darajada.
    dirty = (f"provider failed: token={fake_token} dsn={db_url} "
             f"key={openai_key} g={gemini_key} gh={gh_key} card={card}")
    cleaned = scrub_text(dirty)
    for secret in (fake_token, "SuperSecretDBPassw0rd_2026", openai_key,
                   gemini_key, gh_key, "5589"):
        check(f"scrub_text: maxfiy qiymat yo'qoldi ({str(secret)[:18]}…)",
              secret not in cleaned, cleaned[:120])
    check("scrub_text: [REDACTED…] belgilari bor",
          "[REDACTED" in cleaned, cleaned[:120])

    # (2) REAL LOG OQIMI — handler + filtr orqali (xato loglari ssenariysi).
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(SecretScrubbingFilter("ph_test_filter"))
    test_logger = logging.getLogger("ph_hardening_secret_flow")
    test_logger.setLevel(logging.INFO)
    old_prop = test_logger.propagate
    test_logger.propagate = False
    test_logger.addHandler(handler)
    try:
        test_logger.error("AI provayder xatosi: token=%s dsn=%s",
                          fake_token, db_url)
        test_logger.error("To'lov xatosi: karta=%s", card)
        test_logger.info("Kalit: %s / %s / %s", openai_key, gemini_key, gh_key)
        # Config ro'yxatga olgan HAQIQIY env qiymati ham scrub qilinishi shart.
        test_logger.error("Config token: %s", config.BOT_TOKEN)
        try:
            raise ValueError(f"ichki xato: {openai_key}")
        except ValueError:
            test_logger.exception("Istisno tafsiloti (traceback):")
        out = buf.getvalue()
    finally:
        test_logger.removeHandler(handler)
        test_logger.propagate = old_prop

    leaked = [s for s in (fake_token, "SuperSecretDBPassw0rd_2026", openai_key,
                          gemini_key, gh_key, "8600 0609 5082 5589",
                          config.BOT_TOKEN) if s and s in out]
    check("LOG OQIMI: hech bir secret log yozuviga tushmadi", not leaked,
          f"sizib chiqqan: {[str(x)[:20] for x in leaked]}")
    check("LOG OQIMI: [REDACTED:BOT_TOKEN] belgisi qo'llangan",
          REDACTED_TOKEN in out or "[REDACTED]:BOT_TOKEN" in out, out[:160])
    check("LOG OQIMI: DB paroli [REDACTED] bilan almashtirilgan",
          "[REDACTED]" in out, out[:160])

    # (3) Root logger'ga scrubber o'rnatilgan (production yo'l: main.py).
    filt = install_logging_scrubber()
    root_ok = any(filt in h.filters for h in logging.getLogger().handlers) or \
        filt in logging.getLogger().filters
    main_src = (ROOT / "telegram_bot" / "main.py").read_text(encoding="utf-8")
    check("production: main.py install_logging_scrubber() chaqiradi",
          "install_logging_scrubber()" in main_src)
    check("production: root logger/handler'da filtr faol", root_ok)

    # (4) Sentry event scrubber — xato eventi tozalanganda secret yo'q.
    event = {
        "message": f"boom {fake_token}",
        "extra": {"password": "SuperSecretDBPassw0rd_2026",
                  "note": f"dsn={db_url}", "attempt": 3},
        "exception": {"values": [{"value": f"error {openai_key}"}]},
    }
    scrubbed = scrub_event(event)
    check("sentry event: parol maydoni [REDACTED]",
          scrubbed["extra"]["password"] == "[REDACTED]",
          str(scrubbed["extra"]))
    check("sentry event: token/DSN/kalit event matnida yo'q",
          fake_token not in str(scrubbed)
          and "SuperSecretDBPassw0rd_2026" not in str(scrubbed)
          and openai_key not in str(scrubbed))

    # (5) Config maxfiy qiymatlarni ro'yxatga olgan (haqiqiy kafolat).
    check("config: BOT_TOKEN sifatida ro'yxatdan o'tgan (scrub kafolati)",
          scrub_text(f"x {config.BOT_TOKEN} y") != f"x {config.BOT_TOKEN} y")


# ============================================================================
# TEST 4 — FAZA 25: TIMEOUTS — qat'iy asinxron xavfsizlik chegaralari
# ============================================================================
def test_handler_timeouts() -> None:
    header("TEST 4 — FAZA 25: TIMEOUTS — handler watchdog + fon vazifalari")
    import config
    from utils.handler_timeout import (
        await_with_timeout, run_background_task, get_handler_timeout,
        background_task_count,
    )

    # (1) Konfiguratsiya mavjud va hujjatlangan.
    check("config: UPDATE_HANDLER_TIMEOUT_SECONDS (default 110, >0)",
          isinstance(config.UPDATE_HANDLER_TIMEOUT_SECONDS, int)
          and config.UPDATE_HANDLER_TIMEOUT_SECONDS >= 30,
          str(config.UPDATE_HANDLER_TIMEOUT_SECONDS))
    check("config: BACKGROUND_TASK_TIMEOUT_SECONDS (default 300, >0)",
          isinstance(config.BACKGROUND_TASK_TIMEOUT_SECONDS, int)
          and config.BACKGROUND_TASK_TIMEOUT_SECONDS >= 60,
          str(config.BACKGROUND_TASK_TIMEOUT_SECONDS))
    for env_file in (ROOT / ".env.example",
                     ROOT / "telegram_bot" / ".env.example"):
        text = env_file.read_text(encoding="utf-8")
        check(f"{env_file.name} ({env_file.parent.name}): "
              "timeout o'zgaruvchilari hujjatlangan",
              "UPDATE_HANDLER_TIMEOUT_SECONDS=" in text
              and "BACKGROUND_TASK_TIMEOUT_SECONDS=" in text)

    # (2) await_with_timeout — sekin vazifa QAT'IY kesiladi.
    async def _slow_check():
        started = time.monotonic()
        try:
            await await_with_timeout(asyncio.sleep(10), 0.10, label="test-slow")
            return None, time.monotonic() - started
        except asyncio.TimeoutError:
            return asyncio.TimeoutError, time.monotonic() - started

    exc, elapsed = asyncio.run(_slow_check())
    check("await_with_timeout: sekin vazifa TimeoutError bilan kesildi",
          exc is asyncio.TimeoutError, str(exc))
    check("await_with_timeout: kesish vaqti chegaraga yaqin (< 2s)",
          elapsed < 2.0, f"{elapsed:.2f}s")

    # Tez vazifa natijasi o'zgarishsiz qaytadi.
    async def _fast():
        return await await_with_timeout(asyncio.sleep(0.01, result=42), 5)
    check("await_with_timeout: tez vazifa natijasi saqlanadi",
          asyncio.run(_fast()) == 42)
    check("get_handler_timeout() config qiymatini qaytaradi",
          abs(get_handler_timeout() - config.UPDATE_HANDLER_TIMEOUT_SECONDS) < 1e-9)

    # (3) Fon vazifalari: intake BLOKLANMAYDI + timeout'da tozalanadi.
    async def _background_flow():
        before = background_task_count()
        task = run_background_task(asyncio.sleep(10), name="ph-slow",
                                   timeout=0.15)
        # Asosiy zanjir darhol davom etadi (intake bloklanmaydi):
        started = time.monotonic()
        await asyncio.sleep(0.01)
        intake_delay = time.monotonic() - started
        await asyncio.wait_for(asyncio.shield(asyncio.sleep(0.3)), 1.0)
        await asyncio.sleep(0.2)  # task tugashiga imkon
        leak = background_task_count() - before
        return task, intake_delay, leak

    bg_task, intake_delay, leak = asyncio.run(_background_flow())
    check("fon vazifasi: ososiy zanjir bloklanmadi (< 0.1s kechikish)",
          intake_delay < 0.1, f"{intake_delay:.3f}s")
    check("fon vazifasi: timeout'da bekor qilindi (cancelled)",
          bg_task.cancelled() or bg_task.done(), str(bg_task.cancelled()))
    check("fon vazifasi: ro'yxatdan tozalandi (task leak yo'q)",
          leak <= 0, str(leak))

    # Xatoli fon vazifasi "jim yutilmaydi" — on_error chaqiriladi.
    async def _error_flow():
        errors: list = []

        async def _boom():
            raise RuntimeError("ph-fon-xatosi")

        run_background_task(_boom(), name="ph-boom", timeout=5,
                            on_error=errors.append)
        await asyncio.sleep(0.2)
        return errors
    bg_errors = asyncio.run(_error_flow())
    check("fon vazifasi: xato on_error orqali qayd etiladi",
          any("ph-fon-xatosi" in str(e) for e in bg_errors), str(bg_errors))

    # (4) main.py GuardedApplication — watchdog simli (statik + import).
    main_src = (ROOT / "telegram_bot" / "main.py").read_text(encoding="utf-8")
    check("main.py: process_update await_with_timeout bilan o'ralgan",
          "await_with_timeout(" in main_src
          and "super().process_update(update)" in main_src)
    check("main.py: TimeoutError ushlanadi va _answer_timeout chaqiriladi",
          "except asyncio.TimeoutError" in main_src
          and "_answer_timeout" in main_src)
    check("main.py: UPDATE_HANDLER_TIMEOUT_SECONDS config'dan o'qiladi",
          "UPDATE_HANDLER_TIMEOUT_SECONDS" in main_src)
    try:
        import main as main_mod  # noqa: F401
        check("main import: GuardedApplication modul darajasida yuklanadi",
              hasattr(main_mod, "GuardedApplication")
              and hasattr(main_mod.GuardedApplication, "_answer_timeout"))
    except Exception as e:
        check("main import: GuardedApplication modul darajasida yuklanadi",
              False, f"import xatosi: {e}")


# ============================================================================
# TEST 5 — FAZA 28/29: CONCURRENCY — parallel foydalanuvchilar va AI yuklama
# ============================================================================
def test_concurrency_and_load() -> None:
    header("TEST 5 — FAZA 28/29: CONCURRENCY — parallel foydalanuvchi + AI")

    # ---- (a) Semafor to'yintirilishi: peak concurrency ≤ limit ------------
    from services.ai.concurrency import (
        AIConcurrencyManager, AIQueueFullError,
    )

    async def _saturation():
        # Navbat sig'imi to'liq yukdan KATTA — bu test semafor to'yintirilishini
        # o'lchaydi (overflow ssenariysi alohida (b) bandda tekshiriladi).
        manager = AIConcurrencyManager(max_concurrency=4, max_queue=30,
                                       queue_timeout=5.0)
        active = 0
        peak = 0

        async def fake_ai_work(uid: int):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)          # provayder kutuvi taqlidi
            active -= 1
            return f"result_{uid}"

        results = await asyncio.gather(*(
            manager.run_with_queue(900000 + i,
                                   coro_fn=lambda i=i: fake_ai_work(i))
            for i in range(24)))
        return peak, results, manager

    peak, results, manager = asyncio.run(_saturation())
    check(f"CONCURRENCY: {len(results)} ta foydalanuvchi natijasi to'liq",
          len(results) == 24 and results[0] == "result_0",
          f"{len(results)}")
    check("CONCURRENCY: parallelizm cho'qqisi semafor limitidan oshmadi "
          "(peak ≤ 4)", peak <= 4 and peak >= 1, f"peak={peak}")
    status = manager.get_status()
    check("CONCURRENCY: yakunda task ro'yxati toza (leak yo'q)",
          status["tracked_users"] == 0 and status["active_slots"] == 0,
          str(status))

    # ---- (b) Bounded queue to'lganda — fail-closed AIQueueFullError -------
    async def _queue_full():
        mgr = AIConcurrencyManager(max_concurrency=1, max_queue=2,
                                   queue_timeout=0.15)
        full_errors = 0
        done = 0
        cancelled = 0

        async def slow(_uid):
            await asyncio.sleep(1.5)
            return "ok"

        async def one(uid):
            nonlocal full_errors, done, cancelled
            try:
                await mgr.run_with_queue(uid, coro_fn=lambda: slow(uid))
                done += 1
            except AIQueueFullError:
                full_errors += 1
            except asyncio.CancelledError:
                cancelled += 1
                raise

        tasks = [asyncio.create_task(one(600000 + i)) for i in range(8)]
        await asyncio.sleep(0.4)     # to'yinish nuqtasiga keldik
        snapshot_full = full_errors
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return snapshot_full, tasks

    full_cnt, _ = asyncio.run(_queue_full())
    check("CONCURRENCY: navbat to'lganda fail-closed AIQueueFullError",
          full_cnt >= 1, f"full={full_cnt}")

    # ---- (c) 40 parallel IDOR HUJUMI — hammasi rad etiladi ----------------
    import database as db_mod
    import handlers.pending as P
    from telegram.ext import ConversationHandler

    async def _idor_storm():
        from locales.translations import get_text
        expected_deny = get_text("pend_not_owned", "uz")
        owners = {pid: 900100 + pid for pid in range(1, 21)}  # 20 ta legit post
        calls: list = []
        db_mod.run_db = _patched_run_db(owners, calls)

        async def legit(i: int):
            pid = i + 1
            uid = owners[pid]
            q = _FakeQuery(f"p_time:{pid}", uid)
            ctx = _FakeContext()
            state = await P.edit_post_time_start(_FakeUpdate(q, uid), ctx)
            return ("ok", state, ctx, q, expected_deny)

        async def attacker(i: int):
            pid = i + 1
            uid = 555000 + i                    # egasi EMAS
            q = _FakeQuery(f"p_time:{pid}", uid)
            ctx = _FakeContext()
            state = await P.edit_post_time_start(_FakeUpdate(q, uid), ctx)
            return ("attack", state, ctx, q, expected_deny)

        results = await asyncio.gather(*(
            [legit(i) for i in range(20)] + [attacker(i) for i in range(20)]))
        return results, calls

    original_run_db = db_mod.run_db
    try:
        storm_results, storm_calls = asyncio.run(_idor_storm())
    finally:
        db_mod.run_db = original_run_db

    legit_all = all(
        r[1] == P.EDIT_POST_TIME and r[2].user_data.get("editing_post_id")
        for r in storm_results if r[0] == "ok")
    attack_all = all(
        r[1] == ConversationHandler.END
        and "editing_post_id" not in r[2].user_data
        and any(a[1] is True for a in r[3].answers)
        and any(r[4] in (a[0] or "") for a in r[3].answers)
        for r in storm_results if r[0] == "attack")
    check("LOAD: 20 parallel legit foydalanuvchi o'z postini tahrirlay oladi",
          legit_all)
    check("LOAD: 20 parallel IDOR hujumi — HAMMASI rad etildi (fail-closed)",
          attack_all)
    check("LOAD: stormda faqat get_post_by_id o'qildi (yozuv yo'q)",
          all(c[0] == "get_post_by_id" for c in storm_calls)
          and len(storm_calls) == 40,
          f"{len(storm_calls)} calls: {[c[0] for c in storm_calls][:5]}…")

    # ---- (d) 16 parallel "sekin provayder" — timeout izolyatsiyasi --------
    async def _provider_timeouts():
        started = time.monotonic()
        outcomes = await asyncio.gather(*(
            _one_timeout(i) for i in range(16)), return_exceptions=True)
        return outcomes, time.monotonic() - started

    async def _one_timeout(i):
        from utils.handler_timeout import await_with_timeout
        return await await_with_timeout(_slow(i), 0.12, label=f"prov:{i}")

    async def _slow(i):
        await asyncio.sleep(5)
        return i

    outcomes, elapsed = asyncio.run(_provider_timeouts())
    timeouts = sum(1 for o in outcomes if isinstance(o, asyncio.TimeoutError))
    check("LOAD: 16 parallel sekin provayder — HAMMASI timeout'da kesildi",
          timeouts == 16, f"timeouts={timeouts}")
    check("LOAD: parallel timeout izolyatsiyasi vaqtida (< 2s jami)",
          elapsed < 2.0, f"{elapsed:.2f}s")

    # ---- (e) asyncio task-leak yakuniy tekshiruvi --------------------------
    # O'lchov bitta ishlayotgan loop ichida (mini-storm oldin/keyin) —
    # agar menejer/foydalanuvchi kodi task yaratsa-u tozalamasa, leak > 0.
    async def _leak_probe():
        mgr = AIConcurrencyManager(max_concurrency=2, max_queue=10,
                                   queue_timeout=1.0)

        async def quick(uid: int):
            await asyncio.sleep(0.01)
            return uid

        before = len(asyncio.all_tasks())
        await asyncio.gather(*(
            mgr.run_with_queue(770000 + i, coro_fn=lambda i=i: quick(i))
            for i in range(10)))
        await asyncio.sleep(0.05)  # done-callback'lar ishlasin
        return len(asyncio.all_tasks()) - before

    leak = asyncio.run(_leak_probe())
    check("LOAD: asyncio task-leak yo'q (mini-storm oldin/keyin taqqoslash)",
          leak <= 0, f"leak={leak}")


# ============================================================================
# MAIN — yakuniy hisobot (PASS / FAIL / NOT TESTED — FAQAT ANIQ FAKTLAR)
# ============================================================================
def main() -> int:
    print("=" * 66)
    print(" 🛡⚡ FAZA 23/25/27/28/29 — PRODUCTION HARDENING & CONCURRENCY ")
    print("=" * 66)
    test_idor_pending_callbacks()
    test_ssrf_button_and_sources()
    test_secrets_never_in_error_logs()
    test_handler_timeouts()
    test_concurrency_and_load()

    print()
    print("=" * 66)
    print(" YAKUNIY NATIJALAR (FAQAT ANIQ FAKTLAR)")
    print("=" * 66)
    print(f"  PASS:       {PASS_COUNT}")
    print(f"  FAIL:       {FAIL_COUNT}")
    print(f"  NOT TESTED: {len(NOT_TESTED)}")
    for name, reason in NOT_TESTED:
        print(f"    - {name}: {reason}")
    if FAIL_COUNT:
        print(" ❌ HARDENING SUITE: FAIL (yuqoridagi [FAIL] qatorlarini ko'ring)")
        return 1
    print(" ✅ HARDENING SUITE: TO'LIQ PASS ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
