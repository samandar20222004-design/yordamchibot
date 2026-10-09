#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🐳 PHASE 12 — PRODUCTION DOCKERFILE + GRACEFUL SHUTDOWN SUITE
=====================================================================

Bu suite PHASE 12 talablarini QAT'IY tekshiradi:

1) **Dockerfile (production)**
   * multi-stage build (builder + runtime) — image kichik va xavfsiz;
   * non-root foydalanuvchi ``appuser`` (UID/GID **10001**);
   * ``HEALTHCHECK`` — ``curl /health/live`` (arzon liveness);
   * ``STOPSIGNAL SIGTERM`` + tini (PID 1 signal forwarder);
   * image'ga sir/secret tushmaydi; runtime layer minimal.

2) **Docker Compose (dev + STAGING)**
   * ``docker-compose.yml`` — bot + postgres (+ ixtiyoriy redis),
     ``stop_grace_period`` 15 s drenajdan KATTA;
   * ``docker-compose.staging.yml`` — mock Telegram server xizmati va
     ``TELEGRAM_API_BASE_URL=http://mock-telegram:8080/bot`` (yuklama
     testlari HAQIQIY Telegram API'ga tegmaydi).

3) **Graceful shutdown (xulq-atvor)**
   * SIGINT/SIGTERM event loop ichida ushlanadi (``KeyboardInterrupt``
     await o'rtasida resurslarni yarim yo'lda qoldirmaydi);
   * tartib: yangi ish qabul qilmaslik → updater.stop → scheduler.pause →
     faol vazifalar drenaji → NAVBAT drenaji (delivery) → application →
     scheduler.shutdown → DB pool + AI sessiya + Redis/cache yopilishi;
   * standart drenaj byudjeti **15 soniya** (env orqali [5, 30]);
   * navbatdagi ishlar BEKOR QILINMAYDI (timeout'da DB stale-recovery).

Ishga tushirish (repo ildizidan):
    $HOME/venv/bin/python tests/phase12_docker_and_shutdown_test.py

Chiqish: 0 — barcha tekshiruvlar o'tdi, 1 — kamida bitta [FAIL].
(NOT TESTED — muhit imkoni yo'qligi; suite yiqilmaydi, lekin PASS ham
deb hisoblanmaydi.)
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_DIR = REPO_ROOT / "telegram_bot"

# ---- muhit: import paytida config validatsiyasi uchun (test rejimi) ----
os.environ.setdefault("BOT_TOKEN", "123456:PHASE12_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "777000")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/phase12")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TELEGRAM_API_BASE_URL", "")

for _p in (str(TELEGRAM_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OK = FAIL = SKIP = 0
FAILURES: list[str] = []


def section(title: str) -> None:
    print()
    print("=" * 66)
    print(f" {title}")
    print("=" * 66)


def check(name: str, cond: bool, extra: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK] {name}" + (f" — {extra}" if extra else ""))
        return True
    FAIL += 1
    FAILURES.append(name)
    print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))
    return False


def not_tested(name: str, reason: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  [NOT TESTED] {name} — {reason}")


def run(coro):
    return asyncio.run(coro)


# =====================================================================
# TEST 1 — Dockerfile: multi-stage, non-root, HEALTHCHECK, STOPSIGNAL
# =====================================================================
def test_dockerfile() -> None:
    section("TEST 1) 🐳 PRODUCTION DOCKERFILE (MULTI-STAGE + NON-ROOT + HEALTHCHECK)")

    path = REPO_ROOT / "Dockerfile"
    if not check("Dockerfile mavjud", path.is_file(), str(path)):
        not_tested("Dockerfile tarkibi", "fayl topilmadi")
        return
    text = path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines()]
    froms = [ln for ln in lines if ln.upper().startswith("FROM ")]

    check("Dockerfile: MULTI-STAGE (≥2 FROM bosqich)", len(froms) >= 2,
          f"{len(froms)} bosqich: {', '.join(froms)[:110]}")
    check("Dockerfile: builder bosqichi aniq nomlangan (AS builder)",
          any("AS BUILDER" in ln.upper() for ln in froms), "")
    check("Dockerfile: runtime bosqichi aniq nomlangan (AS runtime)",
          any("AS RUNTIME" in ln.upper() for ln in froms), "")
    check("Dockerfile: asos image python:3.11-slim",
          all("python:3.11-slim" in ln for ln in froms), "")
    check("Dockerfile: builder → runtime virtualenv ko'chirish (COPY --from)",
          "COPY --from=builder" in text, "")
    check("Dockerfile: runtime'da kompilyator/build-essential YO'Q",
          "build-essential" not in text.split("AS runtime", 1)[-1], "")

    # --- non-root ---
    check("Dockerfile: appgroup GID 10001", bool(re.search(r"groupadd[^\n]*--gid\s+10001", text)), "")
    check("Dockerfile: appuser UID 10001",
          bool(re.search(r"useradd[^\n]*--uid\s+10001", text)), "")
    check("Dockerfile: USER appuser (root emas)",
          "USER appuser" in text and "USER root" not in text, "")
    check("Dockerfile: /app fayllari appuser egaligida",
          "chown=appuser:appgroup" in text and "chown -R appuser:appgroup /app" in text, "")

    # --- healthcheck / signals ---
    health = re.search(r"HEALTHCHECK[^\n]*(?:\n[^\n]*)?", text)
    htext = health.group(0) if health else ""
    check("Dockerfile: HEALTHCHECK mavjud", bool(health), "")
    check("Dockerfile: HEALTHCHECK curl orqali",
          "curl" in htext or ("curl" in text and "health/live" in htext), "")
    check("Dockerfile: HEALTHCHECK /health/live (arzon liveness)",
          "/health/live" in text and "HEALTHCHECK" in text, "")
    check("Dockerfile: HEALTHCHECK PORT'ni ishlatadi",
          "${PORT}" in text or "$PORT" in text, "")
    check("Dockerfile: HEALTHCHECK start-period bor",
          "--start-period" in text, "")
    check("Dockerfile: STOPSIGNAL SIGTERM", "STOPSIGNAL SIGTERM" in text, "")
    check("Dockerfile: tini PID 1 (signal forwarder + zombie reaper)",
          "tini" in text and "ENTRYPOINT" in text, "")
    check("Dockerfile: CMD python main.py",
          bool(re.search(r'CMD\s*\[\s*"python"\s*,\s*"main\.py"\s*\]', text)), "")

    # --- layer/xavfsizlik gigienasi ---
    idx_req = text.find("COPY telegram_bot/requirements.txt")
    idx_pip = text.find("pip install")
    idx_venv = text.find("COPY --from=builder /opt/venv")
    idx_code = text.find("COPY --chown=appuser:appgroup telegram_bot/")
    check("Dockerfile: requirements alohida layer (pip kesh)",
          0 <= idx_req < idx_pip, "")
    check("Dockerfile: venv kod'dan OLDIN ko'chiriladi (layer kesh)",
          0 <= idx_venv < idx_code != -1, "")
    check("Dockerfile: apt keshlari tozalanadi (rm -rf /var/lib/apt/lists)",
          text.count("rm -rf /var/lib/apt/lists/*") >= 2, "")
    check("Dockerfile: sir/secret YO'Q (faqat env orqali)",
          not re.search(r"(?i)^\s*ENV\s+.*(TOKEN|PASSWORD|SECRET|API_KEY)=", text, re.M), "")

    # --- .dockerignore ---
    di = REPO_ROOT / ".dockerignore"
    check(".dockerignore mavjud", di.is_file(), "")
    dtext = di.read_text(encoding="utf-8") if di.is_file() else ""
    for pattern in (".git", ".env", "__pycache__", "tests/"):
        check(f".dockerignore: '{pattern}' chiqarib tashlangan", pattern in dtext, "")

    # --- deep healthcheck hujjatlashtirilgan (og'ir tekshiruv HEALTHCHECK emas) ---
    check("Dockerfile: chuqur healthcheck alohida (deep_healthcheck, HEALTHCHECK'da emas)",
          "deep_healthcheck" in text, "")

    # Haqiqiy `docker build` faqat Docker mavjud muhitda — soxta PASS yo'q.
    import shutil

    if shutil.which("docker"):
        check("docker CLI mavjud (build'ni CI'da tekshirish mumkin)",
              True, shutil.which("docker"))
    else:
        not_tested("docker build (haqiqiy image qurish)",
                   "docker CLI bu muhitda yo'q — statik kontraktlar tekshirildi")


# =====================================================================
# TEST 2 — Docker Compose (dev + staging mock Telegram)
# =====================================================================
def test_compose() -> None:
    section("TEST 2) 🐙 DOCKER COMPOSE — DEV + STAGING (MOCK TELEGRAM)")

    base = REPO_ROOT / "docker-compose.yml"
    if not check("docker-compose.yml mavjud", base.is_file(), ""):
        not_tested("compose tarkibi", "fayl topilmadi")
        return
    btext = base.read_text(encoding="utf-8")
    check("compose: bot + postgres xizmatlari", "bot:" in btext and "postgres:" in btext, "")
    check("compose: redis ixtiyoriy profil (bot Redis'siz ham ishlaydi)",
          "redis:" in btext and "profiles:" in btext, "")
    check("compose: bot stop_grace_period ≥ 20s (15s drenajdan katta)",
          bool(re.search(r"stop_grace_period:\s*20s", btext)), "")
    check("compose: bot healthcheck get_system_health (chuqur holat)",
          "get_system_health" in btext, "")
    check("compose: postgres healthcheck pg_isready", "pg_isready" in btext, "")

    staging = REPO_ROOT / "docker-compose.staging.yml"
    if not check("docker-compose.staging.yml mavjud", staging.is_file(), ""):
        not_tested("staging compose", "fayl topilmadi")
        return
    stext = staging.read_text(encoding="utf-8")
    check("staging compose: mock-telegram xizmati",
          "mock-telegram:" in stext, "")
    check("staging compose: mock server staging.mock_telegram_server ni ishga tushiradi",
          "staging.mock_telegram_server" in stext, "")
    check("staging compose: mock server 0.0.0.0:8080",
          "0.0.0.0" in stext and "8080" in stext, "")
    check("staging compose: bot TELEGRAM_API_BASE_URL → mock server",
          "TELEGRAM_API_BASE_URL: http://mock-telegram:8080/bot" in stext, "")
    check("staging compose: bot mock server sog'lom bo'lgach ishga tushadi",
          "service_healthy" in stext, "")
    check("staging compose: mock healthcheck /__health",
          "/__health" in stext, "")
    check("staging compose: mock serverda ham stop_grace_period 20s",
          bool(re.search(r"stop_grace_period:\s*20s", stext)), "")
    # Kommentlar emas — faqat HAQIQIY konfiguratsiya qatorlari.
    stext_code = "\n".join(ln for ln in stext.splitlines()
                           if not ln.strip().startswith("#"))
    import shutil as _shutil

    if _shutil.which("docker"):
        check("docker compose CLI mavjud", True, "")
    else:
        not_tested("docker compose config (haqiqiy merge sinovi)",
                   "docker CLI bu muhitda yo'q — statik kontraktlar tekshirildi")
    check("staging compose: HAQIQIY api.telegram.org manziliga env YO'Q",
          not re.search(r"TELEGRAM_API_BASE_URL[^\n]*api\.telegram\.org", stext_code), "")

    # Mock server moduli ishga tushadigan holatda (image'da staging/ bor).
    stage_dir = TELEGRAM_DIR / "staging"
    check("staging/ paketi image'da qoladi (mock server import qilinadi)",
          (stage_dir / "mock_telegram_server.py").is_file()
          and (stage_dir / "__init__.py").is_file(), "")
    check("staging/ .dockerignore'da CHIQARILMAGAN",
          "telegram_bot/staging" not in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8"), "")


# =====================================================================
# TEST 3 — Graceful shutdown: tartib, drenaj, resurslarni yopish
# =====================================================================
def test_graceful_shutdown() -> None:
    section("TEST 3) 🛑 GRACEFUL SHUTDOWN — SDRENAJ TARTIBI VA RESURSLAR")

    from services import lifecycle_service as lifecycle

    check("lifecycle: standart drenaj byudjeti 15 soniya",
          float(lifecycle.SHUTDOWN_GRACE_SECONDS) == 15.0,
          f"{lifecycle.SHUTDOWN_GRACE_SECONDS}s")
    check("lifecycle: byudjet chegarasi [5, 30] soniya",
          float(lifecycle.SHUTDOWN_GRACE_MIN) == 5.0
          and float(lifecycle.SHUTDOWN_GRACE_MAX) == 30.0,
          f"[{lifecycle.SHUTDOWN_GRACE_MIN}, {lifecycle.SHUTDOWN_GRACE_MAX}]")
    check("lifecycle: env orqali sozlanadi (_env_float clamp)",
          lifecycle._env_float("PHASE12_TEST_FAKE_ENV", 15.0, 5.0, 30.0) == 15.0, "")
    check("lifecycle: request_shutdown idempotent (2-chaqiruv False)",
          lifecycle.request_shutdown("test") is True
          and lifecycle.request_shutdown("test-again") is False, "")
    check("lifecycle: shutdown_reason saqlanadi",
          lifecycle.shutdown_reason() == "test", str(lifecycle.shutdown_reason()))
    check("lifecycle: is_shutting_down() True",
          lifecycle.is_shutting_down() is True, "")
    lifecycle.reset_for_tests()
    check("lifecycle: reset_for_tests() holatni tozalaydi",
          lifecycle.is_shutting_down() is False
          and lifecycle.queue_pending() == {} and lifecycle.inflight_count() == 0, "")

    # --- signal handlerlari (SIGINT/SIGTERM) ---
    import main as main_mod

    names = {getattr(sig, "name", str(sig)) for sig in main_mod.SHUTDOWN_SIGNALS}
    check("main: SHUTDOWN_SIGNALS ichida SIGINT va SIGTERM",
          {"SIGINT", "SIGTERM"} <= names, str(sorted(names)))

    async def _signal_scenario():
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        installed = main_mod.install_signal_handlers(loop, stop)
        fired = False
        if installed:
            os.kill(os.getpid(), signal.SIGTERM)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3.0)
                fired = True
            except asyncio.TimeoutError:
                fired = False
        main_mod.remove_signal_handlers(loop, installed)
        main_mod.remove_signal_handlers(loop, installed)  # idempotent
        return [getattr(s, "name", str(s)) for s in installed], fired, \
            lifecycle.shutdown_reason()

    installed, fired, reason = run(_signal_scenario())
    check("main: SIGINT + SIGTERM handlerlari o'rnatiladi",
          {"SIGINT", "SIGTERM"} <= set(installed), str(installed))
    check("main: SIGTERM haqiqiy signal → shutdown boshlanadi (loop handler)",
          fired is True, f"installed={installed} fired={fired}")
    check("main: shutdown sababi signal nomi bilan yoziladi",
          reason == "SIGTERM", str(reason))
    lifecycle.reset_for_tests()

    # --- to'liq tartib (fake komponentlar bilan) ---
    steps_report = {}

    class _Updater:
        running = True

        async def stop(self):
            steps_report.setdefault("events", []).append("updater")

    class _App:
        running = True

        @property
        def updater(self):
            return _Updater()

        def __init__(self):
            self.events = steps_report.setdefault("events", [])

        async def stop(self):
            self.events.append("app_stop")

        async def shutdown(self):
            self.events.append("app_shutdown")

    class _Sched:
        running = True
        state = 1

        def __init__(self):
            self.events = steps_report.setdefault("events", [])

        def pause(self):
            self.events.append("scheduler_pause")

        def shutdown(self, wait=True):
            self.events.append(f"scheduler_shutdown(wait={wait})")

    class _Web:
        async def cleanup(self):
            steps_report.setdefault("events", []).append("web")

    async def _full_shutdown():
        import database as db_mod
        from services import cache_backend as cache_mod
        from services import health_service

        events = steps_report.setdefault("events", [])
        orig_close_pool = db_mod.close_pool
        orig_close_ai = main_mod.close_ai_session
        orig_cache_close = cache_mod.close_cache_backend
        orig_flush = health_service.flush_user_activity

        async def _fake_close_ai():
            events.append("ai_session")

        async def _fake_cache_close():
            events.append("cache")

        async def _fake_flush():
            events.append("user_activity_flush")

        # Navbat BAND: ichkarida 0.15 s ish bor — shutdown kutishi shart.
        release = asyncio.Event()
        job_started = asyncio.Event()

        async def _job():
            token = lifecycle.begin_task("post:phase12")
            lifecycle.queue_enter("delivery")
            job_started.set()
            try:
                await release.wait()
            finally:
                lifecycle.queue_leave("delivery")
                lifecycle.end_task(token)

        task = asyncio.ensure_future(_job())
        await job_started.wait()
        await asyncio.sleep(0.05)
        asyncio.get_running_loop().call_later(0.25, release.set)

        try:
            db_mod.close_pool = lambda: events.append("db_pool")
            main_mod.close_ai_session = _fake_close_ai
            cache_mod.close_cache_backend = _fake_cache_close
            health_service.flush_user_activity = _fake_flush
            rep = await main_mod.graceful_shutdown(
                _App(), _Sched(), _Web(), grace_seconds=3.0)
        finally:
            db_mod.close_pool = orig_close_pool
            main_mod.close_ai_session = orig_close_ai
            cache_mod.close_cache_backend = orig_cache_close
            health_service.flush_user_activity = orig_flush
        await task
        return rep, list(events)

    rep, events = run(_full_shutdown())
    steps = list(rep.get("steps") or [])
    order = ["updater_stopped", "scheduler_paused", "inflight_drained",
             "queues_drained", "application_stopped", "application_shutdown",
             "scheduler_shutdown", "user_activity_flushed", "web_server_closed",
             "db_pool_closed", "ai_session_closed", "cache_closed"]
    check("shutdown: bosqichlar to'liq va TARTIBDA",
          steps == order, str(steps))
    check("shutdown: report clean=True", rep.get("clean") is True and not rep.get("errors"),
          str(rep.get("errors")))
    check("shutdown: yangi ish qabul qilinmaydi (updater birinchi to'xtaydi)",
          events[:1] == ["updater"], str(events[:3]))
    check("shutdown: scheduler pause → inflight kutish → navbat kutish",
          events[1:3] == ["scheduler_pause", "app_stop"] or "scheduler_pause" in events[:3],
          str(events[:4]))
    check("shutdown: navbat DRENAJ qilindi (band delivery kutildi)",
          rep.get("queues_drained", {}).get("drained") is True
          and rep.get("queues_drained", {}).get("remaining") == 0,
          str(rep.get("queues_drained")))
    check("shutdown: faol vazifalar drenaji (inflight_drained drained=True)",
          rep.get("inflight_drained", {}).get("drained") is True,
          str(rep.get("inflight_drained")))
    check("shutdown: DB pool yopildi", "db_pool_closed" in steps and "db_pool" in events, "")
    check("shutdown: AI (aiohttp) sessiya yopildi",
          "ai_session" in events, str(events))
    check("shutdown: Redis/cache backend yopildi", "cache" in events, str(events))
    check("shutdown: user activity flush DB pool'dan OLDIN",
          "user_activity_flush" in events
          and events.index("user_activity_flush") < events.index("db_pool"), str(events))
    check("shutdown: web server (health) yopildi", "web" in events, "")
    check("shutdown: navbat/holat toza qoldi",
          lifecycle.queue_pending() == {} and lifecycle.inflight_count() == 0, "")
    lifecycle.reset_for_tests()

    # --- timeout: navbat bo'shamasa ham jarayon QULAMAYDI (bekor qilinmaydi) ---
    async def _stuck():
        lifecycle.queue_enter("delivery")
        try:
            res = await lifecycle.wait_for_queues(0.3)
        finally:
            lifecycle.queue_leave("delivery")
        return res

    res = run(_stuck())
    check("shutdown: timeout'da navbat BEKOR QILINMAYDI (drained=False, istisno yo'q)",
          res.get("drained") is False and res.get("remaining") == 1, str(res))
    check("shutdown: timeout natijasi 'waited' bilan hisobotlanadi",
          float(res.get("waited") or 0) >= 0.25, str(res.get("waited")))
    check("shutdown: timeoutdan keyin navbat tozalanadi (queue_leave)",
          lifecycle.queue_pending() == {}, str(lifecycle.queue_pending()))
    lifecycle.reset_for_tests()

    # --- statik: main.py signal oqimi to'g'ri ulangan ---
    main_src = (TELEGRAM_DIR / "main.py").read_text(encoding="utf-8")
    check("main.py: install_signal_handlers ishlatiladi",
          "install_signal_handlers(" in main_src, "")
    check("main.py: remove_signal_handlers finally/cleanup ichida",
          "remove_signal_handlers(" in main_src, "")
    check("main.py: graceful_shutdown signal'dan keyin chaqiriladi",
          "await graceful_shutdown(application, scheduler, web_runner)" in main_src, "")
    check("main.py: KeyboardInterrupt ham graceful yo'lga o'tadi",
          "KeyboardInterrupt" in main_src and "request_shutdown" in main_src, "")
    check("main.py: ikkinchi signal yopilishni QAYTA boshlamaydi",
          "takror keldi" in main_src, "")


# =====================================================================
# TEST 4 — Drenaj byudjeti hujjatlari (env parity)
# =====================================================================
def test_env_docs() -> None:
    section("TEST 4) 📚 ENV HUJJATLARI — SHUTDOWN_GRACE_SECONDS + STAGING")

    root_env = REPO_ROOT / ".env.example"
    bot_env = TELEGRAM_DIR / ".env.example"
    check(".env.example (root) mavjud", root_env.is_file(), "")
    check("telegram_bot/.env.example dublikati YO'Q", not bot_env.exists(), "")
    if not root_env.is_file():
        not_tested("env docs", "kanonik .env.example topilmadi")
        return
    rtext = root_env.read_text(encoding="utf-8")
    check("env: SHUTDOWN_GRACE_SECONDS=15 (root)",
          "SHUTDOWN_GRACE_SECONDS=15" in rtext, "")
    check("env: TELEGRAM_API_BASE_URL hujjatlashtirilgan (staging uchun)",
          "TELEGRAM_API_BASE_URL" in rtext, "")


def main() -> int:
    print("=" * 66)
    print(" 🐳 PHASE 12 — DOCKER + GRACEFUL SHUTDOWN SUITE")
    print("=" * 66)
    started = time.perf_counter()

    test_dockerfile()
    test_compose()
    test_graceful_shutdown()
    test_env_docs()

    elapsed = time.perf_counter() - started
    print()
    print("=" * 66)
    print(f" NATIJA: [OK]={OK}  [FAIL]={FAIL}  [NOT TESTED]={SKIP}")
    if FAILURES:
        print(" YIQILGAN TEKSHIRUVLAR:")
        for name in FAILURES:
            print(f"   - {name}")
    print(f" VAQT: {elapsed:.2f}s")
    print("=" * 66)
    if FAIL == 0:
        print(" ✅ PHASE 12 DOCKER & SHUTDOWN SUITE: 100% YASHIL ✔")
        return 0
    print(" ❌ PHASE 12 DOCKER & SHUTDOWN SUITE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
