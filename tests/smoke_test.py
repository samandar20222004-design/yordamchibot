#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🧪 RUNTIME TELEGRAM SMOKE TEST — ishga tushirish (deploy) tekshiruvi
=====================================================================

Maqsad: bot SERVERDA (staging/production) ishga tushgandan keyin uni
"haqiqatan ishlayaptimi?" degan 3 ta qat'iy o'lchov bilan tekshirish:

  1) 📡 TELEGRAM API ULANISHI (``getMe``):
     * ``--live``/``--auto`` rejimida — HAQIQIY ``api.telegram.org`` ga
       tarmoq orqali ``getMe`` (token haqiqiy bo'lishi shart); token
       namuna/yo'q bo'lsa yoki tarmoq yopiq bo'lsa — halol ``[NOT TESTED]``
       (``--strict-live`` bilan FAIL);
     * HAR DOIM — in-process MOCK Telegram server orqali to'liq tarmoq
       zanjiri (PTB → HTTPX → HTTP → JSON) deterministik tekshiriladi
       (spam YO'Q, tashqi tarmoq kerak emas).

  2) 🔄 POLLING / WEBHOOK REJIMI:
     * polling: ``Application.updater.start_polling(drop_pending_updates=False)``
       haqiqiy bot klassi bilan ko'tariladi, server tomonidan update
       in'yeksiya qilinadi va handler + ``sendMessage`` javobi tasdiqlanadi,
       so'ng toza (graceful) to'xtatiladi;
     * webhook: ``TELEGRAM_WEBHOOK_URL`` berilgan bo'lsa ``setWebhook`` →
       ``getWebhookInfo`` (URL mos) → ``deleteWebhook`` sinaladi; mock
       rejimida webhook API kontrakti ham tekshiriladi.

  3) 🩺 HEALTH ENDPOINTLARI:
     * ``GET /health/live`` — 200 JSON ``{"status": "live", "uptime_seconds": N}``,
       ``Cache-Control: no-store``, ichida ``checks``/``metrics`` YO'Q;
     * ``GET /health/ready`` — fail-closed: token yo'q → 404 ``not_found``,
       noto'g'ri token → 401 ``unauthorized``, to'g'ri token → 200/503
       ``ready``/``not_ready`` + ``checks`` (database/redis/scheduler);
       javobda token/secret SIZIB CHIQMAYDI.

QO'SHIMCHA (0-bo'lim): deploy artefaktlari kontrakti — ``scripts/``
skriptlari mavjud/sintaksis toza, ``.env.example`` ikkala nusxada paritet,
``DEPLOYMENT.md`` 1-komandalik yo'riqnomaga ega, ``run_tests.sh`` shu smoke
testni chaqiradi.

ISHLATISH::

    # 1) Offline (CI/test runner — tashqi tarmoqsiz, mock Telegram):
    python3 tests/smoke_test.py --offline

    # 2) Ishga tushgan serverga qarshi (deploy.sh buni o'zi chaqiradi):
    python3 tests/smoke_test.py --base-url http://127.0.0.1:8080 --wait-health 60

    # 3) Haqiqiy Telegram bilan (serverda, token bilan):
    python3 tests/smoke_test.py --live --strict-live --base-url http://127.0.0.1:8080

Chiqish: 0 — barcha PASS; 1 — kamida bitta [FAIL]. ``[NOT TESTED]`` suite'ni
yiqitmaydi (muhit imkoni yo'qligi halol qayd etiladi).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_DIR = REPO_ROOT / "telegram_bot"
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENV_FILES = (REPO_ROOT / ".env.example", TELEGRAM_DIR / ".env.example")

#: Haqiqiy Telegram bot tokeniga o'xshash format (test tokenidan farqlash).
_REAL_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
#: Test/mock tokenlari — tarmoqqa chiqilmaydi.
_PLACEHOLDER_TOKEN = "123456:SMOKE_TEST_PLACEHOLDER_TOKEN"
_MOCK_TOKEN = "123456:SMOKE_MOCK_TOKEN"

PASSED = 0
FAILED = 0
NOT_TESTED: list[tuple[str, str]] = []
FINDINGS: list[dict] = []
_DEFAULT_HEALTH_TOKEN = "smoke-ready-token-0123456789abcdef"


def check(name: str, condition: Any, detail: str = "") -> bool:
    """Bitta tekshiruv natijasini qayd etadi ([OK]/[FAIL])."""
    global PASSED, FAILED
    ok = bool(condition)
    if ok:
        PASSED += 1
        print(f"  [OK] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
    FINDINGS.append({"level": "OK" if ok else "FAIL", "name": name, "detail": str(detail)})
    return ok


def not_tested(name: str, reason: str) -> None:
    """Muhit imkoni yo'qligi (soxta PASS berilmaydi)."""
    global NOT_TESTED
    NOT_TESTED.append((name, reason))
    print(f"  [NOT TESTED] {name} — {reason}")
    FINDINGS.append({"level": "NOT_TESTED", "name": name, "detail": reason})


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def _mask(value: str) -> str:
    if not value:
        return "<yo'q>"
    return f"<set: len={len(value)}>"


def _looks_like_real_token(token: str) -> bool:
    return bool(_REAL_TOKEN_RE.match((token or "").strip()))


def pick_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runtime Telegram smoke test (getMe, polling/webhook, health endpointlari).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true",
                      help="Faqat mock Telegram (tashqi tarmoqqa chiqilmaydi).")
    mode.add_argument("--live", action="store_true",
                      help="Haqiqiy Telegram API bilan getMe majburiy.")
    mode.add_argument("--auto", action="store_true",
                      help="Token haqiqiy bo'lsa live, aks holda offline (standart).")
    parser.add_argument("--strict-live", action="store_true",
                        help="Live tekshiruv imkonsiz bo'lsa [FAIL] (standart: NOT TESTED).")
    parser.add_argument("--base-url", default="",
                        help="Ishlayotgan health-server manzili "
                             "(masalan http://127.0.0.1:8080). Berilmasa — "
                             "in-process web-server ko'tariladi.")
    parser.add_argument("--port", type=int, default=0,
                        help="In-process web-server porti (0 = bo'sh port).")
    parser.add_argument("--health-token", default="",
                        help="HEALTH_READY_TOKEN (odatda env orqali beriladi; CLI'da "
                             "ko'rsatilsa `ps`da ko'rinadi).")
    parser.add_argument("--webhook-url", default="",
                        help="Webhook rejimini tekshirish uchun HTTPS manzil.")
    parser.add_argument("--wait-health", type=float, default=0.0,
                        help="Health endpointlarini tekshirishdan oldin 200 bo'lguncha "
                             "kutish byudjeti (soniya).")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="Bitta tarmoq tekshiruvi uchun timeout (soniya).")
    parser.add_argument("--json", default="", help="Hisobotni JSON faylga yozish.")
    return parser.parse_args(argv)


# =====================================================================
# 0) DEPLOY ARTEFAKTLARI KONTRAKTI
# =====================================================================
def section_artifacts() -> None:
    section("0) 📦 DEPLOY ARTEFAKTLARI KONTRAKTI")

    required = (
        SCRIPTS_DIR / "start_production.sh",
        SCRIPTS_DIR / "deploy.sh",
        SCRIPTS_DIR / "preflight_env.py",
        SCRIPTS_DIR / "db_migrate.py",
    )
    for path in required:
        rel = path.relative_to(REPO_ROOT).as_posix()
        exists = path.is_file() and path.stat().st_size > 0
        check(f"{rel} mavjud va bo'sh emas", exists, f"{path.stat().st_size if path.is_file() else 0} bayt")

    # Python skriptlari kompilyatsiya bo'ladi (sintaksis xatosi deploy'ni buzmaydi).
    for script in (SCRIPTS_DIR / "preflight_env.py", SCRIPTS_DIR / "db_migrate.py"):
        rel = script.relative_to(REPO_ROOT).as_posix()
        try:
            compile(script.read_text(encoding="utf-8"), rel, "exec")
            check(f"{rel} sintaksisi toza (compile)", True)
        except SyntaxError as exc:
            check(f"{rel} sintaksisi toza (compile)", False, f"{exc}")

    # Bash skriptlari `bash -n` bilan tekshiriladi.
    bash = None
    for candidate in ("bash", "/bin/bash", "/usr/bin/bash"):
        try:
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True,
                                   text=True, timeout=15)
            if probe.returncode == 0:
                bash = candidate
                break
        except Exception:
            continue
    if bash is None:
        not_tested("bash -n skript sintaksisi", "bash topilmadi")
    else:
        for script in (SCRIPTS_DIR / "start_production.sh", SCRIPTS_DIR / "deploy.sh"):
            rel = script.relative_to(REPO_ROOT).as_posix()
            proc = subprocess.run([bash, "-n", str(script)], capture_output=True,
                                  text=True, timeout=30)
            check(f"{rel} bash sintaksisi toza (bash -n)", proc.returncode == 0,
                  (proc.stderr or "").strip()[:160])

    # .env.example pariteti va yangi fazalar kalitlari.
    texts = []
    for path in ENV_FILES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if not path.is_file():
            check(f"{rel} mavjud", False)
            continue
        texts.append(path.read_text(encoding="utf-8"))
        content = texts[-1]
        for key in ("HEALTH_READY_TOKEN", "AUTOPILOT_QUIET_HOURS", "REDIS_URL",
                    "DB_POOL_SIZE", "AI_PROVIDER_CHAIN"):
            check(f"{rel}: {key} hujjatlashtirilgan", key in content)
    if len(texts) == 2:
        check(".env.example nusxalari AYNAN bir xil (paritet)", texts[0] == texts[1])

    # DEPLOYMENT.md — 1-komandalik yo'riqnoma.
    deployment = REPO_ROOT / "DEPLOYMENT.md"
    if deployment.is_file():
        text = deployment.read_text(encoding="utf-8")
        for marker, label in (
            ("scripts/deploy.sh", "DEPLOYMENT.md: 1-komandalik deploy ko'rsatilgan"),
            ("scripts/start_production.sh", "DEPLOYMENT.md: bootstrap skripti ko'rsatilgan"),
            ("tests/smoke_test.py", "DEPLOYMENT.md: smoke test ko'rsatilgan"),
            ("HEALTH_READY_TOKEN", "DEPLOYMENT.md: health token eslatilgan"),
        ):
            check(label, marker in text)
    else:
        check("DEPLOYMENT.md mavjud", False)

    # Docker HEALTHCHECK kontrakti (liveness) saqlanadi.
    dockerfile = REPO_ROOT / "Dockerfile"
    if dockerfile.is_file():
        text = dockerfile.read_text(encoding="utf-8")
        check("Dockerfile: HEALTHCHECK /health/live saqlangan",
              "HEALTHCHECK" in text and "/health/live" in text)
        check("Dockerfile: CMD python main.py saqlangan",
              bool(re.search(r'CMD\s*\[\s*"python"\s*,\s*"main\.py"\s*\]', text)))

    # Runner smoke testni chaqiradi (regressiya har doim tekshiriladi).
    runner = (REPO_ROOT / "tests" / "run_tests.sh")
    if runner.is_file():
        check("tests/run_tests.sh smoke testni chaqiradi",
              "smoke_test.py" in runner.read_text(encoding="utf-8"))
    else:
        check("tests/run_tests.sh mavjud", False)


# =====================================================================
# 1) MUHIT VA REJIM KONTRAKTI
# =====================================================================
def section_env(args: argparse.Namespace, *, live_mode: bool) -> None:
    section("1) 🛫 MUHIT VA REJIM KONTRAKTI")
    token = (os.environ.get("BOT_TOKEN") or "").strip()
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    port = (os.environ.get("PORT") or "").strip()
    api_base = (os.environ.get("TELEGRAM_API_BASE_URL") or "").strip()
    print(f"  BOT_TOKEN               : {_mask(token)}")
    print(f"  DATABASE_URL            : {_mask(db_url)}")
    port_shown = port if port else "<yo'q>"
    api_base_shown = api_base if api_base else "<bo'sh — haqiqiy API>"
    print(f"  PORT                    : {port_shown}")
    print(f"  TELEGRAM_API_BASE_URL   : {api_base_shown}")
    print(f"  rejim                   : {'LIVE' if live_mode else 'OFFLINE (mock Telegram)'}")
    check("BOT_TOKEN mavjud (bot ishga tushishi uchun)", bool(token))
    check("PORT 1..65535 oralig'ida",
          bool(port) and port.isdigit() and 1 <= int(port) <= 65535, port)
    check("TELEGRAM_API_BASE_URL production'da bo'sh yoki staging manzil",
          (os.environ.get("ENVIRONMENT", "test").strip().lower() != "production")
          or not api_base)


# =====================================================================
# 2) TELEGRAM getMe (live + mock)
# =====================================================================
async def telegram_getme_mock(server, *, token: str, timeout: float) -> None:
    """Mock serverga qarshi getMe — to'liq tarmoq zanjiri deterministik."""
    from telegram.request import HTTPXRequest
    from utils.telegram_delivery import SafeHTMLBot

    bot = SafeHTMLBot(
        token=token,
        base_url=server.base_url,
        request=HTTPXRequest(connect_timeout=5, read_timeout=timeout,
                             write_timeout=timeout, pool_timeout=5),
        get_updates_request=HTTPXRequest(connection_pool_size=1),
    )
    await bot.initialize()
    try:
        me = await bot.get_me()
        check("MOCK getMe: bot ma'lumotlari keldi",
              bool(getattr(me, "is_bot", False)) and bool(getattr(me, "username", "")),
              f"@{getattr(me, 'username', '?')} (id={getattr(me, 'id', '?')})")
        check("MOCK getMe: javob PTB modeliga to'g'ri o'girildi",
              getattr(me, "first_name", None) is not None)
    finally:
        await bot.shutdown()


async def telegram_getme_live(token: str, timeout: float) -> tuple[bool, str]:
    """Haqiqiy api.telegram.org ga getMe. (muvaffaqiyat, detal) qaytaradi."""
    from telegram import Bot
    from telegram.request import HTTPXRequest
    from telegram.error import TelegramError

    bot = Bot(token=token, request=HTTPXRequest(
        connect_timeout=min(10.0, timeout), read_timeout=timeout,
        write_timeout=timeout, pool_timeout=5,
    ))
    await bot.initialize()
    try:
        started = asyncio.get_running_loop().time()
        me = await asyncio.wait_for(bot.get_me(), timeout=timeout)
        latency_ms = (asyncio.get_running_loop().time() - started) * 1000
        return True, (f"@{me.username} (id={me.id}, {latency_ms:.0f} ms)")
    except (TelegramError, asyncio.TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    finally:
        try:
            await bot.shutdown()
        except Exception:
            pass


# =====================================================================
# 3) POLLING VA WEBHOOK REJIMI
# =====================================================================
async def polling_smoke(server, *, token: str, timeout: float) -> None:
    """Haqiqiy PTB polling siklini mock serverga qarshi ko'taradi."""
    from telegram.ext import ApplicationBuilder, MessageHandler, filters
    from telegram.request import HTTPXRequest
    from utils.telegram_delivery import SafeHTMLBot

    received: asyncio.Event = asyncio.Event()
    seen: dict[str, Any] = {}

    async def probe_handler(update, context):
        seen["text"] = (update.effective_message.text or "") if update.effective_message else ""
        seen["chat_id"] = update.effective_chat.id if update.effective_chat else None
        await update.effective_message.reply_text("smoke-pong")
        received.set()

    bot = SafeHTMLBot(
        token=token,
        base_url=server.base_url,
        request=HTTPXRequest(connect_timeout=5, read_timeout=timeout,
                             write_timeout=timeout, pool_timeout=5,
                             connection_pool_size=4),
        get_updates_request=HTTPXRequest(connection_pool_size=1),
    )
    application = (
        ApplicationBuilder()
        .bot(bot)
        .concurrent_updates(True)
        .build()
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, probe_handler))
    started = False
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=False)
        started = True
        check("polling: updater xatosiz ko'tarildi", bool(application.updater.running))

        chat_id = 424242
        server.state.enqueue_update({
            "update_id": 900001,
            "message": {
                "message_id": 1,
                "date": int(datetime.now(timezone.utc).timestamp()),
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": chat_id, "is_bot": False, "first_name": "Smoke"},
                "text": "smoke test xabari",
            },
        })
        try:
            await asyncio.wait_for(received.wait(), timeout=max(5.0, timeout))
            got = True
        except asyncio.TimeoutError:
            got = False
        check("polling: yuborilgan update handler'ga yetib bordi", got,
              f"matn={seen.get('text')!r}")
        check("polling: handler javobi Telegram'ga (mock) yuborildi",
              "smoke-pong" in (server.state.last_texts or []),
              f"sendMessage={server.state.methods.get('sendMessage', 0)} ta")
        check("polling: getUpdates so'rovi serverga yetib bordi",
              int(server.state.methods.get("getUpdates", 0)) >= 1,
              str(server.state.methods.get("getUpdates", 0)))
    finally:
        if started:
            try:
                await application.updater.stop()
            except Exception as exc:  # pragma: no cover
                check("polling: updater toza to'xtadi", False, f"{type(exc).__name__}: {exc}")
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass
    check("polling: updater graceful to'xtatildi",
          not bool(getattr(application.updater, "running", False)))


async def webhook_smoke(server, *, token: str, webhook_url: str, timeout: float) -> None:
    """Webhook rejimi: setWebhook → getWebhookInfo → deleteWebhook."""
    from telegram.request import HTTPXRequest
    from utils.telegram_delivery import SafeHTMLBot

    base_url = server.base_url if server is not None else None
    bot = SafeHTMLBot(
        token=token,
        **({"base_url": base_url} if base_url else {}),
        request=HTTPXRequest(connect_timeout=5, read_timeout=timeout,
                             write_timeout=timeout, pool_timeout=5),
        get_updates_request=HTTPXRequest(connection_pool_size=1),
    )
    await bot.initialize()
    try:
        ok = await bot.set_webhook(url=webhook_url, drop_pending_updates=False)
        check("webhook: setWebhook qabul qilindi", bool(ok), webhook_url)
        info = await bot.get_webhook_info()
        check("webhook: getWebhookInfo URL mos",
              str(getattr(info, "url", "") or "").startswith(webhook_url),
              str(getattr(info, "url", "")))
        removed = await bot.delete_webhook(drop_pending_updates=False)
        check("webhook: deleteWebhook (polling'ga qaytish) OK", bool(removed))
    except Exception as exc:
        check("webhook: setWebhook/getWebhookInfo/deleteWebhook xatosiz",
              False, f"{type(exc).__name__}: {str(exc)[:140]}")
    finally:
        await bot.shutdown()


# =====================================================================
# 4) BACKGROUND WORKERLAR (scheduler)
# =====================================================================
async def workers_smoke(timeout: float) -> None:
    """Background workerlar (APScheduler) parallel ko'tarilishini tasdiqlaydi."""
    try:
        import scheduler as sched
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except Exception as exc:
        check("workerlar: scheduler moduli import qilinadi", False,
              f"{type(exc).__name__}: {exc}")
        return

    worker_names = (
        "check_and_send_posts", "check_and_delete_expired_posts",
        "cleanup_old_data_job", "cleanup_old_records_job",
        "poll_content_sources_job", "weekly_channel_reports_job",
        "subscription_sweep_job", "recover_on_startup",
    )
    missing = [name for name in worker_names if not hasattr(sched, name)]
    check("workerlar: barcha scheduler vazifalari mavjud (main.py ulaydi)",
          not missing, f"yetishmayapti: {missing}")

    main_src = (TELEGRAM_DIR / "main.py").read_text(encoding="utf-8")
    for marker, label in (
        ("start_web_server", "main.py: web health-server ko'tariladi"),
        ("start_polling", "main.py: Telegram polling boshlanadi"),
        ("scheduler.start()", "main.py: APScheduler ishga tushiriladi"),
        ("concurrent_updates(True)", "main.py: update'lar parallel qabul qilinadi"),
        ("recover_on_startup", "main.py: startup tiklanish (recover) chaqiriladi"),
    ):
        check(label, marker in main_src)

    executed: asyncio.Event = asyncio.Event()

    async def _probe_job():
        executed.set()

    scheduler = AsyncIOScheduler(
        timezone=sched.tashkent_tz,
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
    )
    jobs = (
        ("check_and_send_posts", 60), ("check_and_delete_expired_posts", 60),
        ("cleanup_old_data", 360), ("subscription_sweep", 15),
        ("poll_content_sources", 15), ("weekly_channel_reports", None),
        ("cleanup_old_records", None), ("flush_user_activity", None),
    )
    for job_id, minutes in jobs:
        scheduler.add_job(_probe_job, "interval", minutes=minutes or 60, id=job_id,
                          max_instances=1, coalesce=True)
    # Fon vazifasi HAQIQATAN bajarilishini isbotlash uchun 0.3s dan keyingi job.
    scheduler.add_job(_probe_job, "date",
                      run_date=datetime.now(sched.tashkent_tz) + timedelta(seconds=0.3),
                      id="smoke_probe")
    scheduler.start()
    try:
        check("workerlar: scheduler ishga tushdi (running)", bool(scheduler.running))
        check("workerlar: 9 ta job ro'yxatga olindi", len(scheduler.get_jobs()) >= 9,
              str(len(scheduler.get_jobs())))
        try:
            await asyncio.wait_for(executed.wait(), timeout=max(5.0, timeout))
            ran = True
        except asyncio.TimeoutError:
            ran = False
        check("workerlar: fon vazifasi event loop'da HAQIQATAN bajarildi", ran)
    finally:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass


# =====================================================================
# 5) HEALTH ENDPOINTLARI
# =====================================================================
async def _http_get(session, url: str, headers: dict | None = None):
    async with session.get(url, headers=headers or {}, allow_redirects=False) as resp:
        body = await resp.text()
        try:
            payload = json.loads(body)
        except Exception:
            payload = None
        return resp.status, payload, dict(resp.headers), body


async def _wait_health(session, base_url: str, timeout: float) -> tuple[bool, str]:
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout)
    last = "javob yo'q"
    while asyncio.get_running_loop().time() < deadline:
        try:
            status, payload, _, _ = await _http_get(session, f"{base_url}/health/live")
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "live":
                return True, "200 live"
            last = f"HTTP {status}"
        except Exception as exc:
            last = type(exc).__name__
        await asyncio.sleep(1.0)
    return False, last


async def health_smoke(args: argparse.Namespace, *, timeout: float) -> None:
    """`/health/live` (public) va `/health/ready` (himoyalangan) kontraktlari."""
    import aiohttp

    in_process = not (args.base_url or "").strip()
    token = (args.health_token or os.environ.get("HEALTH_READY_TOKEN") or "").strip()
    original_token_env = os.environ.get("HEALTH_READY_TOKEN")
    started_runner = None
    base_url = (args.base_url or "").rstrip("/")

    if in_process:
        from utils.web_server import start_web_server

        port = int(args.port) if args.port else int(os.environ.get("PORT") or 0)
        base_url = f"http://127.0.0.1:{port}"
        started_runner = await start_web_server()
        check(f"in-process web health-server ko'tarildi ({base_url})", True)
        if not token:
            # In-process serverda tokenni O'ZIMIZ o'rnatamiz — himoyalangan
            # readiness yo'lini to'liq tekshirish uchun (fail-closed 404 ham
            # alohida sinaladi).
            token = _DEFAULT_HEALTH_TOKEN

    try:
        async with aiohttp.ClientSession() as session:
            if args.wait_health > 0:
                healthy, detail = await _wait_health(session, base_url, args.wait_health)
                check(f"/health/live {args.wait_health}s ichida 200 bo'ldi", healthy, detail)

            # --- /health/live: public liveness -----------------------------
            try:
                status, payload, headers, body = await _http_get(session, f"{base_url}/health/live")
            except Exception as exc:
                check("/health/live mavjud va javob beradi", False,
                      f"{type(exc).__name__}: {exc}")
                return
            check("/health/live → HTTP 200", status == 200, f"HTTP {status}")
            check("/health/live → JSON status='live'",
                  isinstance(payload, dict) and payload.get("status") == "live",
                  str(payload)[:120])
            check("/health/live → uptime_seconds butun son",
                  isinstance(payload, dict)
                  and isinstance(payload.get("uptime_seconds"), int)
                  and payload.get("uptime_seconds") >= 0,
                  str((payload or {}).get("uptime_seconds")))
            check("/health/live → faqat process liveness (checks/metrics YO'Q)",
                  isinstance(payload, dict)
                  and "checks" not in payload and "metrics" not in payload)
            check("/health/live → Cache-Control: no-store",
                  str(headers.get("Cache-Control", "")).lower() == "no-store",
                  str(headers.get("Cache-Control")))
            check("/health/live javobida secret YO'Q",
                  not any(v and v in body for v in
                          (token, os.environ.get("BOT_TOKEN", ""))))

            # --- Fail-closed: token o'rnatilmagan holat -------------------
            if in_process:
                os.environ.pop("HEALTH_READY_TOKEN", None)
                status_nc, payload_nc, _, _ = await _http_get(
                    session, f"{base_url}/health/ready")
                check("token o'rnatilmagan → /health/ready fail-closed 404 (ma'lumot YO'Q)",
                      status_nc == 404 and isinstance(payload_nc, dict)
                      and payload_nc.get("status") == "not_found"
                      and "checks" not in payload_nc,
                      f"HTTP {status_nc}: {str(payload_nc)[:80]}")
                os.environ["HEALTH_READY_TOKEN"] = token

            # --- /health/ready: autentifikatsiya qatlami ------------------
            status_open, payload_open, _, body_open = await _http_get(
                session, f"{base_url}/health/ready")
            check("/health/ready tokensiz → fail-closed (401/404)",
                  status_open in (401, 404)
                  and isinstance(payload_open, dict)
                  and payload_open.get("status") in ("unauthorized", "not_found"),
                  f"HTTP {status_open}: {str(payload_open)[:80]}")
            check("/health/ready tokensiz javobda ma'lumot yo'q (checks/metrics YO'Q)",
                  "checks" not in (payload_open or {}) and "metrics" not in (payload_open or {}))

            status_wrong, _, _, _ = await _http_get(
                session, f"{base_url}/health/ready",
                headers={"Authorization": "Bearer definitely-not-the-token"})
            check("/health/ready noto'g'ri token → 401/404", status_wrong in (401, 404),
                  f"HTTP {status_wrong}")

            if token:
                auth_headers = {"Authorization": f"Bearer {token}"}
                status_ok, payload_ok, headers_ok, body_ok = await _http_get(
                    session, f"{base_url}/health/ready", headers=auth_headers)
                check("/health/ready to'g'ri token → 200 ready yoki 503 not_ready",
                      status_ok in (200, 503)
                      and isinstance(payload_ok, dict)
                      and payload_ok.get("status") in ("ready", "not_ready"),
                      f"HTTP {status_ok}: {str(payload_ok)[:160]}")
                checks_obj = (payload_ok or {}).get("checks")
                check("/health/ready → checks: database/redis/scheduler",
                      isinstance(checks_obj, dict)
                      and {"database", "redis", "scheduler"} <= set(checks_obj),
                      str(checks_obj))
                check("/health/ready → Cache-Control: no-store",
                      str(headers_ok.get("Cache-Control", "")).lower() == "no-store")
                leaked = [name for name, value in (("health-token", token),
                                                   ("bot-token", os.environ.get("BOT_TOKEN", "")))
                          if value and value in (body_ok or "")]
                check("/health/ready javobida token/secret YO'Q", not leaked, str(leaked))
            else:
                # Tashqi server: token noma'lum — faqat fail-closed kontrakt
                # tekshiriladi (soxta PASS berilmaydi).
                not_tested("/health/ready authenticated readiness",
                           "HEALTH_READY_TOKEN noma'lum — himoyalangan javob tekshirilmadi")
    finally:
        if original_token_env is None:
            os.environ.pop("HEALTH_READY_TOKEN", None)
        else:
            os.environ["HEALTH_READY_TOKEN"] = original_token_env
        if started_runner is not None:
            await started_runner.cleanup()


# =====================================================================
# ASOSIY OQIM
# =====================================================================
async def run(args: argparse.Namespace) -> int:
    section_artifacts()

    token = (os.environ.get("BOT_TOKEN") or "").strip()
    live_token = _looks_like_real_token(token)
    if args.offline:
        live_mode = False
    elif args.live:
        live_mode = True
    else:
        live_mode = live_token and not (os.environ.get("TELEGRAM_API_BASE_URL") or "").strip()
    section_env(args, live_mode=live_mode)

    # --- Mock Telegram server (deterministik zanjir) -------------------
    server = None
    try:
        from staging.mock_telegram_server import MockTelegramServer
        server = MockTelegramServer(host="127.0.0.1", port=pick_free_port())
        await server.start()
    except Exception as exc:
        server = None
        check("mock Telegram server ko'tarildi (in-process)", False,
              f"{type(exc).__name__}: {exc}")
    if server is not None:
        check("mock Telegram server ko'tarildi (in-process)", True, server.base_url)

    section("2) 📡 TELEGRAM API ULANISHI (getMe)")
    if server is not None:
        await telegram_getme_mock(server, token=_MOCK_TOKEN, timeout=min(10.0, args.timeout))
    else:
        not_tested("MOCK getMe", "mock server ko'tarilmadi")

    if live_mode:
        if not live_token:
            msg = f"BOT_TOKEN haqiqiy tokenga o'xshamaydi {_mask(token)}"
            check("LIVE getMe (api.telegram.org)", False, msg) if args.strict_live \
                else not_tested("LIVE getMe (api.telegram.org)", msg)
        else:
            ok, detail = await telegram_getme_live(token, min(15.0, args.timeout))
            if ok:
                check("LIVE getMe (api.telegram.org) — bot mavjud", True, detail)
            elif args.strict_live:
                check("LIVE getMe (api.telegram.org)", False, detail)
            else:
                not_tested("LIVE getMe (api.telegram.org)",
                           f"ulanish imkonsiz — {detail}")
    else:
        reason = ("--offline rejimi" if args.offline else
                  "token namuna/yo'q yoki TELEGRAM_API_BASE_URL staging'ga qaratilgan")
        not_tested("LIVE getMe (api.telegram.org)", reason)

    section("3) 🔄 POLLING VA WEBHOOK REJIMI")
    if server is not None:
        await polling_smoke(server, token=_MOCK_TOKEN, timeout=min(15.0, args.timeout))
        await webhook_smoke(server, token=_MOCK_TOKEN,
                            webhook_url="https://example.invalid/smoke-hook",
                            timeout=min(10.0, args.timeout))
    else:
        not_tested("polling rejimi (mock)", "mock server yo'q")

    webhook_url = (args.webhook_url
                   or os.environ.get("TELEGRAM_WEBHOOK_URL")
                   or os.environ.get("WEBHOOK_URL") or "").strip()
    if webhook_url and live_token:
        await webhook_smoke(None, token=token, webhook_url=webhook_url,
                            timeout=min(15.0, args.timeout))
    else:
        not_tested("LIVE webhook rejimi (setWebhook/getWebhookInfo)",
                   "TELEGRAM_WEBHOOK_URL berilmagan — bot POLLING rejimida ishlaydi")

    section("4) ⚙️ BACKGROUND WORKERLAR (scheduler) — parallel ko'tarilish")
    await workers_smoke(timeout=min(15.0, args.timeout))

    section("5) 🩺 HEALTH ENDPOINTLARI (/health/live, /health/ready)")
    await health_smoke(args, timeout=min(15.0, args.timeout))

    if server is not None:
        try:
            await server.stop()
        except Exception:
            pass

    section("📊 YAKUNIY HISOBOT")
    print(f"  PASS       : {PASSED}")
    print(f"  FAIL       : {FAILED}")
    print(f"  NOT TESTED : {len(NOT_TESTED)}")
    for name, reason in NOT_TESTED:
        print(f"    - {name} — {reason}")
    if args.json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "live" if live_mode else "offline",
            "base_url": args.base_url or None,
            "passed": PASSED, "failed": FAILED,
            "not_tested": [{"name": n, "reason": r} for n, r in NOT_TESTED],
            "findings": FINDINGS,
        }
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  JSON hisobot: {out}")

    if FAILED:
        print("\n❌ SMOKE TEST YIQILDI — yuqoridagi [FAIL] qatorlarini ko'ring.")
        return 1
    print("\n✅ SMOKE TEST 100% YASHIL"
          + (f" ({len(NOT_TESTED)} ta tekshiruv muhit sababli NOT TESTED)" if NOT_TESTED else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # --- Muhit: production modullar import qilinishidan OLDIN ------------
    if args.port:
        health_port = int(args.port)
    elif args.base_url:
        health_port = 0  # tashqi server tekshiriladi — o'zimiz port ochmaymiz
    else:
        health_port = pick_free_port()
    os.environ.setdefault("BOT_TOKEN", _PLACEHOLDER_TOKEN)
    os.environ.setdefault("ADMIN_ID", "777000")
    os.environ.setdefault("DATABASE_URL", "postgresql://smoke:smoke@127.0.0.1:5432/smoke")
    os.environ.setdefault("ENVIRONMENT", "test")
    if health_port:
        os.environ["PORT"] = str(health_port)
    else:
        os.environ.setdefault("PORT", "10000")
    os.environ.setdefault("TELEGRAM_API_BASE_URL", "")
    sys.path.insert(0, str(TELEGRAM_DIR))
    sys.path.insert(0, str(REPO_ROOT))

    print("=" * 70)
    print(" 🧪 RUNTIME TELEGRAM SMOKE TEST — PostAssist V2")
    print("=" * 70)
    print(f"  Repo    : {REPO_ROOT}")
    print(f"  Python  : {sys.version.split()[0]}")

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:  # pragma: no cover
        print("\n[WARN] To'xtatildi (KeyboardInterrupt).")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover — kutilmagan xato aniq kod beradi
        print(f"\n❌ SMOKE TEST XATOLIK BILAN YIQILDI: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
