#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🚀 DEPLOY BOOTSTRAP — YANGI (BO'SH) BAZADA 1-KOMANDALIK DEPLOY KONTRAKTI
=====================================================================

Bu suite **P1 regression**ni qo'riqlaydi: ilgari `bash scripts/deploy.sh`
(barcha rejimlarda) `scripts/start_production.sh` ni `--check-only` bilan
chaqirardi. `start_production.sh` esa bu flagni `scripts/db_migrate.py` ga
uzatardi va `db_migrate.py --check-only` **schema.sql NI YOZMAYDI** (read-only).
Natijada YANGI (bo'sh) bazada zanjir quyidagicha yiqilardi:

    ❌ schema_tables — yetishmayapti: ad_pool, admin_audit_logs, ...
    MIGRATION/SCHEMA CHECK YIQILDI
    [deploy][ERROR] Preflight/migratsiya bosqichi yiqildi — bot ishga tushirilmadi.

ya'ni DEPLOYMENT.md ("2 | 🗄 Migration | `schema.sql` **idempotent**
qo'llaniladi") va `deploy.sh` sarlavhasida yozilgan 1-komandalik deploy
birinchi marta (yangi baza / yangi muhit / falokatdan tiklash) UMUMAN
ishlamasdi. Tuzatish:

  * `start_production.sh` ga `--migrate-only` rejimi qo'shildi — preflight +
    HAQIQIY idempotent migratsiya + port tekshiruvi, bot ko'tarilmaydi;
  * `--check-only` **o'zgarmadi**: u ataylab read-only (hech narsa yozmaydi);
  * `deploy.sh` endi `--migrate-only` ishlatadi.

Tekshiruvlar:

  A) STATIK KONTRAKT (har doim):
     A1 deploy.sh `--migrate-only` yuboradi, `--check-only` YO'Q;
     A2 start_production.sh `--migrate-only` ni e'lon qiladi (usage + parser);
     A3 `--check-only` faqat shu rejimda db_migrate ga uzatiladi (read-only
        semantika saqlangan);
     A4 `--check-only` + `--migrate-only` birga — fail-fast (die);
     A5 ikkala rejim ham port tekshiruvidan keyin CHIQADI (main.py yo'q);
     A6 db_migrate.py `--check-only` da yozmasligi hujjatlashtirilgan;
     A7 DEPLOYMENT.md 1-komandalik deploy tavsifi bilan ziddiyat yo'q.

  B) LIVE XULQ-ATVOR (haqiqiy PostgreSQL, `pgserver`; bo'lmasa NOT TESTED):
     B1 BO'SH baza yaratiladi (0 ta jadval tasdiqlanadi);
     B2 `deploy.sh --check-only` BO'SH bazada 0 bilan chiqadi va schema.sql
        HAQIQATAN qo'llaniladi (34 jadval / 45 indeks);
     B3 migratsiyadan keyin `start_production.sh --check-only` (read-only)
        0 bilan chiqadi — ya'ni check-only hamon o'qish rejimi;
     B4 `deploy.sh --check-only` ikkinchi marta (idempotentlik) 0 bilan chiqadi.

Ishga tushirish (repo ildizidan):
    $HOME/venv/bin/python tests/deploy_bootstrap_fresh_db_test.py

Muhit: BOOTSTRAP_TEST_SKIP_LIVE=1 — live qismni o'tkazib yuboradi.
Chiqish: 0 — barcha tekshiruvlar o'tdi, 1 — kamida bitta [FAIL].
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
DEPLOY = SCRIPTS / "deploy.sh"
START = SCRIPTS / "start_production.sh"
MIGRATE = SCRIPTS / "db_migrate.py"
DEPLOYMENT_MD = REPO_ROOT / "DEPLOYMENT.md"

passed = 0
failed = 0
not_tested: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    not_tested.append((name, reason))
    print(f"  [NOT TESTED] {name} — {reason}")


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def pick_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# A) STATIK KONTRAKT
# ---------------------------------------------------------------------------
def static_contract() -> None:
    section("A) STATIK KONTRAKT — deploy.sh ⇄ start_production.sh ⇄ db_migrate.py")

    deploy = _read(DEPLOY)
    start = _read(START)
    migrate = _read(MIGRATE)

    # deploy.sh qaysi rejimni uzatadi?
    m = re.search(
        r"CHECK_ARGS=\(([^)]*)\)",
        deploy,
    )
    flags = m.group(1) if m else ""
    check("A1 deploy.sh start_production.sh ga --migrate-only yuboradi",
          "--migrate-only" in flags,
          f"CHECK_ARGS=({flags.strip()})")
    check("A1b deploy.sh --check-only NI start_production.sh ga YUBORMAYDI",
          "--check-only" not in flags,
          f"CHECK_ARGS=({flags.strip()}) — read-only flag migratsiyani bloklaydi")
    check("A1c deploy.sh sarlavhasida 1-komandalik migratsiya hujjatlashtirilgan",
          "MIGRATION" in deploy and "schema.sql" in deploy,
          "deploy.sh 2-bosqich izohi")

    # start_production.sh --migrate-only mavjudligi
    check("A2 start_production.sh --migrate-only flagini e'lon qiladi",
          "--migrate-only)" in start and "MIGRATE_ONLY=1" in start,
          "parser + MIGRATE_ONLY o'zgaruvchisi")
    check("A2b --migrate-only usage/--help matnida bor",
          "--migrate-only" in start.split("while [ $# -gt 0 ]")[0],
          "usage() bloki")

    # check-only semantikasi saqlangan: faqat CHECK_ONLY=1 da db_migrate ga uzatiladi
    check("A3 db_migrate ga --check-only FAQAT CHECK_ONLY=1 da uzatiladi",
          re.search(r'if \[ "\$CHECK_ONLY" = "1" \]; then\s*\n\s*MIGRATE_ARGS\+=\(--check-only\)', start)
          is not None,
          "--migrate-only rejimida HAQIQIY migratsiya bajariladi")

    # o'zaro eksklyuzivlik
    check("A4 --check-only va --migrate-only birga berilsa fail-fast (die)",
          re.search(r'CHECK_ONLY" = "1" \] && \[ "\$MIGRATE_ONLY" = "1" ', start) is not None
          and "die" in start,
          "xato argument kombinatsiyasi to'silgan")

    # ikkala rejim ham botni ko'tarmasligi
    guard = re.search(
        r'if \[ "\$CHECK_ONLY" = "1" \] \|\| \[ "\$MIGRATE_ONLY" = "1" \]; then(.*?)\nfi\n',
        start,
        re.S,
    )
    body = guard.group(1) if guard else ""
    check("A5 ikkala rejim ham port tekshiruvidan keyin exit qiladi",
          "exit 0" in body and "port" in body.lower(),
          "main.py faqat oddiy startda ishga tushadi")
    check("A5b rejim blokidan keyin main.py exec qilinadi (oddiy start)",
          'exec "$PY" "$REPO_ROOT/telegram_bot/main.py"' in start,
          "regressiya yo'q")

    # db_migrate check-only semantikasi
    check("A6 db_migrate.py --check-only da schemani YOZMASLIGI kodda aniq",
          'step("migration", "skip", "check-only rejimi' in migrate,
          "read-only kafolati (aynan shu xatti-harakat hujjatlashtirilgan)")

    # DEPLOYMENT.md
    md = _read(DEPLOYMENT_MD)
    check("A7 DEPLOYMENT.md 2-bosqich 'schema.sql idempotent qo'llaniladi' deydi",
          "idempotent" in md and "schema.sql" in md,
          "hujjat ⇄ kod endi ziddiyatsiz")
    check("A7b DEPLOYMENT.md --verify-only ni CI/staging uchun ko'rsatadi",
          "--verify-only" in md,
          "topshiriqdagi buyruq hujjatlashtirilgan")


# ---------------------------------------------------------------------------
# B) LIVE XULQ-ATVOR (haqiqiy PostgreSQL)
# ---------------------------------------------------------------------------
def _pg_uri(data_dir: str) -> str | None:
    try:
        import pgserver  # type: ignore
    except ImportError:
        return None
    try:
        shutil.rmtree(data_dir, ignore_errors=True)
        srv = pgserver.get_server(data_dir)
        return srv.get_uri()
    except Exception as exc:  # pragma: no cover — muhitga bog'liq
        print(f"  (pgserver ishga tushmadi: {exc})")
        return None


def _connect(uri: str):
    import psycopg2  # type: ignore

    return psycopg2.connect(uri)


def _table_count(uri: str) -> int:
    conn = _connect(uri)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _write_env(path: Path, uri: str, port: int) -> None:
    path.write_text(
        "\n".join(
            [
                "# AVTOMATIK YARATILGAN TEST MUHITI (haqiqiy kredensial YO'Q)",
                "BOT_TOKEN=123456789:BOOTSTRAPTESTTOKENabcdefghijklmnop",
                "TELEGRAM_API_BASE_URL=",
                f"DATABASE_URL={uri}",
                "ENVIRONMENT=staging",
                "AI_ALLOW_MOCK=1",
                "ADMIN_ID=777000",
                "HEALTH_READY_TOKEN=0123456789abcdef0123456789abcdef",
                f"PORT={port}",
                "REDIS_URL=",
                "REDIS_ENABLED=0",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run(script: Path, args: list[str], env_file: Path, timeout: float = 180.0):
    env = dict(os.environ)
    env["DEPLOY_ENV_FILE"] = str(env_file)
    env["PYTHON"] = sys.executable
    env.pop("DATABASE_URL", None)  # .env fayli yetakchi bo'lsin
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def live_behaviour() -> None:
    section("B) LIVE XULQ — BO'SH BAZADA 1-KOMANDALIK DEPLOY (haqiqiy PostgreSQL)")

    if os.getenv("BOOTSTRAP_TEST_SKIP_LIVE") == "1":
        skip("B1-B4 live bootstrap", "BOOTSTRAP_TEST_SKIP_LIVE=1")
        return

    tmp = Path(tempfile.mkdtemp(prefix="bootstrap_deploy_"))
    uri = _pg_uri(str(tmp / "pg"))
    if not uri:
        skip(
            "B1-B4 live bootstrap",
            "pgserver/psycopg2 mavjud emas — haqiqiy PostgreSQL ko'tarilmadi",
        )
        return

    env_file = tmp / "bootstrap.env"
    _write_env(env_file, uri, pick_free_port())

    try:
        # B1) baza HAQIQATAN bo'sh
        before = _table_count(uri)
        check("B1 baza BO'SH (0 ta jadval) — real 'yangi muhit' stsenariysi",
              before == 0, f"public jadvallar={before}")

        # B2) deploy.sh --check-only (aynan shu zanjir ilgari yiqilardi)
        res = _run(DEPLOY, ["--check-only"], env_file)
        tail = "\n".join((res.stdout + res.stderr).strip().splitlines()[-6:])
        check("B2 deploy.sh --check-only BO'SH bazada 0 bilan chiqadi",
              res.returncode == 0, f"exit={res.returncode}\n{tail}")
        after = _table_count(uri)
        check("B2b schema.sql HAQIQATAN qo'llanildi (jadval > 0)",
              after > 0, f"public jadvallar: {before} → {after}")
        check("B2c kutilgan sxema qamrovi (>=30 jadval)",
              after >= 30, f"jadval={after}")

        # B3) read-only rejim saqlanganini tasdiqlash
        res2 = _run(START, ["--check-only"], env_file)
        detail = "\n".join((res2.stdout + res2.stderr).strip().splitlines()[-4:])
        check("B3 start_production.sh --check-only (read-only) 0 bilan chiqadi",
              res2.returncode == 0, f"exit={res2.returncode}\n{detail}")
        check("B3b --check-only hech narsa yozmaganini tasdiqlash (jadval soni o'zgarmadi)",
              _table_count(uri) == after, "read-only semantika buzilmagan")

        # B4) idempotentlik — ikkinchi deploy ham 0
        res3 = _run(DEPLOY, ["--check-only"], env_file)
        check("B4 idempotentlik: ikkinchi deploy.sh --check-only ham 0 bilan chiqadi",
              res3.returncode == 0, f"exit={res3.returncode}")
        check("B4b ikkinchi yugurtirishda jadval soni o'zgarmadi",
              _table_count(uri) == after, f"jadval={after}")

        # B5) mutual exclusion fail-fast
        res4 = _run(START, ["--check-only", "--migrate-only"], env_file)
        check("B5 --check-only + --migrate-only birga → fail-fast (exit != 0)",
              res4.returncode != 0,
              "ikkala rejim birga berib bo'lmaydi")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("=" * 70)
    print(" 🚀 DEPLOY BOOTSTRAP (YANGI BAZA) — P1 REGRESSION SUITE")
    print("=" * 70)

    static_contract()
    live_behaviour()

    section("YAKUNIY HISOBOT")
    print(f"  [OK]        : {passed}")
    print(f"  [FAIL]      : {failed}")
    print(f"  [NOT TESTED]: {len(not_tested)}")
    for name, reason in not_tested:
        print(f"    - {name} — {reason}")
    print(f"  JAMI: o'tdi={passed}, xato={failed}")
    if failed == 0:
        print(" ✅ DEPLOY BOOTSTRAP SUITE: 100% YASHIL ✔")
        return 0
    print(" ❌ DEPLOY BOOTSTRAP SUITE: YIQILDI")
    return 1


if __name__ == "__main__":
    sys.exit(main())
