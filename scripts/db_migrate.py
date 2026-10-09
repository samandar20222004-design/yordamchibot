#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🗄 SAFE DATABASE MIGRATION — sxema qo'llash va tekshirish (schema check)
=====================================================================

Maqsad: bot ishga tushishidan OLDIN ma'lumotlar bazasi sxemasini
**idempotent va xavfsiz** tarzda qo'llash hamda haqiqatan tayyor ekanini
tasdiqlash. Botning o'zi (`main.py` → `db.init_db()`) ham shu ishni
qiladi; bu skript esa deploy/bootstrap paytida buni ALOHIDA, aniq
hisobot bilan bajaradi (va muammoni bot ishga tushishidan oldin ushlaydi).

Nima qilinadi:

  1) 🔌 Ulanish: ``DATABASE_URL`` bo'yicha ping + latency (retry bilan —
     Render/Aiven cold start'da baza uyg'onishini kutadi);
  2) 🧱 MIGRATSIYA (``--check-only`` bo'lmasa): ``db.init_db()`` —
     ``schema.sql`` IDEMPOTENT qo'llanadi; jadvallar yetishmasa qayta
     qo'llaniladi; integrity constraintlar/indekslar tekshiriladi;
  3) 🔍 SCHEMA CHECK: jadvallar va indekslar ro'yxati kutilgan to'plam
     bilan solishtiriladi (yetishmaganlari nomma-nom ko'rsatiladi);
  4) 🧾 HISOBOT: pool holati, integrity (yetim qatorlar / NOT VALID
     constraintlar) va jadval/indeks qamrovi;
  5) 🔒 ``--validate-integrity``: NOT VALID constraintlarni VALIDATE qiladi
     (katta jadvallarda qulf olishi mumkin — ataylab opt-in).

Maxfiylik: DSN/parol hech qachon chop etilmaydi (faqat host va baza nomi).

Ishga tushirish::

    python3 scripts/db_migrate.py                       # .env + migratsiya
    python3 scripts/db_migrate.py --check-only          # faqat tekshiruv
    python3 scripts/db_migrate.py --env-file .env --json
    bash scripts/start_production.sh                    # (o'ram: preflight+migratsiya)

Chiqish kodlari: 0 — OK (WARN bo'lishi mumkin), 1 — xato, 2 — usage xatosi.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_DIR = REPO_ROOT / "telegram_bot"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

#: Bot tokeni yo'q bo'lsa ham migratsiya ishlashi uchun (config.py import
#: validatsiyasi uchun) — bu HAQIQIY token EMAS va hech qanday so'rovga
#: ishlatilmaydi (bu skript Telegram API'ga umuman murojaat qilmaydi).
_MIGRATION_PLACEHOLDER_TOKEN = "000000:MIGRATION_ONLY_PLACEHOLDER_TOKEN"

sys.path.insert(0, str(TELEGRAM_DIR))


def _load_env_file(path: Path) -> dict[str, str]:
    """Oddiy ``KEY=VALUE`` o'quvchi (qo'shtirnoq va izohlarni tushunadi)."""
    parsed: dict[str, str] = {}
    if not path.is_file():
        return parsed
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in ("'", '"') and len(value) >= 2 and value[-1] == value[0]:
            value = value[1:-1]
        else:
            hash_at = value.find(" #")
            if hash_at != -1:
                value = value[:hash_at]
        if key:
            parsed[key] = value.strip()
    return parsed


def _mask_dsn(url: str) -> str:
    """DSN ni parolsiz ko'rsatadi (faqat host/baza)."""
    info = _describe_dsn(url)
    host = info["host"] or "<host>"
    port = urlsplit(url).port
    return f"{info['scheme']}://{host}{':' + str(port) if port else ''}/{info['database'] or ''}"


def _describe_dsn(url: str) -> dict:
    from urllib.parse import parse_qs

    parts = urlsplit(url)
    host = parts.hostname or (parse_qs(parts.query).get("host") or [""])[0]
    return {"scheme": parts.scheme, "host": host,
            "database": (parts.path or "").strip("/"), "tls": "sslmode=" in url.lower()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Xavfsiz DB migratsiyasi + sxema tekshiruvi (schema check).",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE),
                        help="Muhit fayli (standart: .env; 'none' — o'qilmasin).")
    parser.add_argument("--no-process-env", action="store_true",
                        help="Faqat --env-file ishlatilsin.")
    parser.add_argument("--check-only", action="store_true",
                        help="Hech narsa YOZILMAYDI — faqat sxema/holat tekshiriladi.")
    parser.add_argument("--validate-integrity", action="store_true",
                        help="NOT VALID constraintlarni VALIDATE qilish (qulf olishi mumkin).")
    parser.add_argument("--retries", type=int, default=5,
                        help="Bazaga ulanish uchun urinishlar soni (standart 5).")
    parser.add_argument("--retry-delay", type=float, default=3.0,
                        help="Urinishlar orasidagi pauza, soniya (standart 3).")
    parser.add_argument("--json", action="store_true", help="JSON hisobot.")
    parser.add_argument("--quiet", action="store_true", help="Faqat yakuniy qator.")
    args = parser.parse_args(argv)

    env_file: Path | None
    if str(args.env_file).strip().lower() in ("none", "off", "-"):
        env_file = None
    else:
        env_file = Path(args.env_file).expanduser().resolve()

    merged: dict[str, str] = {}
    if env_file is not None:
        merged.update(_load_env_file(env_file))
    if not args.no_process_env:
        merged.update({k: v for k, v in os.environ.items()})
    os.environ.update(merged)

    dsn = (merged.get("DATABASE_URL") or "").strip()
    if not dsn:
        print("[ERROR] DATABASE_URL bo'sh — migratsiya/qo'llash mumkin emas.", file=sys.stderr)
        return 2
    bot_token = (merged.get("BOT_TOKEN") or "").strip()
    placeholder_used = False
    if not bot_token:
        # config.py import paytida BOT_TOKEN talab qiladi; bu skript Telegram
        # API'ga murojaat qilmaydi, shuning uchun xavfsiz placeholder.
        os.environ["BOT_TOKEN"] = _MIGRATION_PLACEHOLDER_TOKEN
        placeholder_used = True

    report: dict = {
        "env_file": str(env_file) if env_file else None,
        "database": _describe_dsn(dsn),
        "check_only": bool(args.check_only),
        "steps": [],
        "warnings": [],
        "errors": [],
    }

    def step(name: str, status: str, detail: str = "") -> None:
        report["steps"].append({"name": name, "status": status, "detail": detail})
        if not args.quiet:
            icon = {"ok": "✅", "warn": "⚠️", "error": "❌", "skip": "⏭️"}.get(status, "•")
            print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))

    if not args.quiet:
        print("=" * 70)
        print(" 🗄 SAFE DB MIGRATION — sxema qo'llash va tekshiruv")
        print("=" * 70)
        print(f"  Baza  : {_mask_dsn(dsn)}")
        print(f"  Rejim : {'CHECK-ONLY (yozmaydi)' if args.check_only else 'MIGRATSIYA + CHECK'}")
        if placeholder_used:
            print("  ℹ️  BOT_TOKEN berilmagan — import uchun vaqtinchalik placeholder "
                  "(Telegram API'ga so'rov YO'Q).")
        print("-" * 70)

    try:
        import database as db  # noqa: E402 — env tayyorlangandan keyin import
    except Exception as exc:  # pragma: no cover — konfiguratsiya xatosi
        print(f"[ERROR] DB_MODULE_IMPORT: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # ── 1) Ulanish (retry bilan — cold start) ────────────────────────────
    last_error: str | None = None
    for attempt in range(1, max(1, int(args.retries)) + 1):
        try:
            ping = db.ping_db_with_latency()
            if ping.get("ok"):
                step("connection", "ok", f"ping OK ({ping.get('latency_ms')} ms), "
                                         f"urinish {attempt}/{args.retries}")
                report["ping_latency_ms"] = ping.get("latency_ms")
                break
            last_error = str(ping.get("error") or "ping muvaffaqiyatsiz")
        except Exception as exc:  # pragma: no cover
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < args.retries:
            if not args.quiet:
                print(f"  … baza javob bermadi ({last_error}); {args.retry_delay}s dan "
                      f"keyin qayta urinish ({attempt}/{args.retries})")
            time.sleep(max(0.0, float(args.retry_delay)))
    else:
        step("connection", "error", f"bazaga ulanib bo'lmadi: {last_error}")
        report["errors"].append(f"connection: {last_error}")
        db.close_pool()
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        print("MIGRATION FAILED — baza javob bermadi.", file=sys.stderr)
        return 1

    # ── 2) Migratsiya (idempotent schema apply) ──────────────────────────
    if args.check_only:
        step("migration", "skip", "check-only rejimi — schema.sql qo'llanilmadi")
    else:
        try:
            db.init_db()
            step("migration", "ok", "schema.sql idempotent qo'llanildi + sxema tekshiruvi")
            report["migrated"] = True
        except Exception as exc:
            step("migration", "error", f"{type(exc).__name__}: {exc}")
            report["errors"].append(f"migration: {type(exc).__name__}: {exc}")
            db.close_pool()
            if args.json:
                print(json.dumps(report, ensure_ascii=False))
            print("MIGRATION FAILED — sxema qo'llanilmadi.", file=sys.stderr)
            return 1

    # ── 3) Schema check: jadvallar + indekslar ───────────────────────────
    required_tables = (*db.EXPECTED_TABLES, *db.REQUIRED_P0_TABLES, *db.AI_USAGE_TABLES,
                       *getattr(db, "PAYME_TABLES", ()))
    # P1 (5-qadam): analitika kompozit indekslari ham tekshiriladi (ular
    # alohida ro'yxatda — ``EXPECTED_INDEXES`` tarixiy/frozen ro'yxat).
    # Payme jadval/indekslari ham alohida ro'yxatda (database.PAYME_*).
    required_indexes = (*db.EXPECTED_INDEXES, *db.REQUIRED_P0_INDEXES,
                        *db.AI_USAGE_INDEXES,
                        *getattr(db, "ANALYTICS_PERFORMANCE_INDEX_NAMES", ()),
                        *getattr(db, "PAYME_INDEXES", ()))
    try:
        with db.db_cursor() as cur:  # readonly (commit yo'q)
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
            tables = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            indexes = {row[0] for row in cur.fetchall()}
        missing_tables = sorted({t for t in required_tables if t not in tables})
        missing_indexes = sorted({i for i in required_indexes if i not in indexes})
        report["schema"] = {
            "tables": {"required": len(set(required_tables)),
                       "present": len({t for t in required_tables if t in tables})},
            "indexes": {"required": len(set(required_indexes)),
                        "present": len({i for i in required_indexes if i in indexes})},
            "missing_tables": missing_tables,
            "missing_indexes": missing_indexes,
        }
        if missing_tables:
            step("schema_tables", "error",
                 f"yetishmayapti: {', '.join(missing_tables[:8])}"
                 + (" …" if len(missing_tables) > 8 else ""))
            report["errors"].append(f"missing tables: {missing_tables}")
        else:
            step("schema_tables", "ok", f"{len(set(required_tables))} ta jadval joyida")
        if missing_indexes:
            step("schema_indexes", "warn",
                 f"yetishmayapti: {', '.join(missing_indexes[:8])}"
                 + (" …" if len(missing_indexes) > 8 else ""))
            report["warnings"].append(f"missing indexes: {missing_indexes}")
        else:
            step("schema_indexes", "ok", f"{len(set(required_indexes))} ta indeks joyida")
    except Exception as exc:
        step("schema_check", "error", f"{type(exc).__name__}: {exc}")
        report["errors"].append(f"schema_check: {type(exc).__name__}: {exc}")

    # ── 4) Pool + integrity hisoboti ─────────────────────────────────────
    try:
        pool = db.get_db_pool_status()
        report["pool"] = pool
        step("pool", "ok" if pool.get("ready") else "warn",
             f"ready={pool.get('ready')}, collapsed={pool.get('collapsed')}, "
             f"min={pool.get('min')}, max={pool.get('max')}")
        if not pool.get("ready"):
            report["warnings"].append("db pool ready emas")
    except Exception as exc:
        step("pool", "warn", f"holatni o'qib bo'lmadi: {type(exc).__name__}: {exc}")

    try:
        integrity = db.integrity_report()
        report["integrity"] = {
            "missing": integrity.get("missing") or [],
            "not_valid": integrity.get("not_valid") or [],
            "orphans": integrity.get("orphans") or {},
        }
        if integrity.get("error"):
            step("integrity", "warn", f"tekshiruv xatosi: {integrity['error']}")
            report["warnings"].append(f"integrity: {integrity['error']}")
        else:
            orphans = {k: v for k, v in (integrity.get("orphans") or {}).items() if v}
            detail = (f"constraintlar: {len(integrity.get('constraints') or {})} ta, "
                      + (f"yetim qatorlar: {orphans}" if orphans else "yetim qator yo'q"))
            step("integrity", "ok", detail)
            if integrity.get("missing"):
                report["warnings"].append(f"missing constraints: {integrity['missing']}")
            if integrity.get("not_valid"):
                report["warnings"].append(f"not valid constraints: {integrity['not_valid']}")
    except Exception as exc:
        step("integrity", "warn", f"tekshiruv xatosi: {type(exc).__name__}: {exc}")

    # ── 5) Ixtiyoriy: NOT VALID constraintlarni VALIDATE qilish ──────────
    if args.validate_integrity:
        try:
            result = db.validate_integrity_constraints()
            bad = {k: v for k, v in result.items() if v not in ("ok", "validated")}
            report["validate_integrity"] = result
            step("validate_integrity", "warn" if bad else "ok",
                 f"{len(result)} ta constraint tekshirildi" +
                 (f", muammo: {bad}" if bad else ""))
        except Exception as exc:
            step("validate_integrity", "warn", f"{type(exc).__name__}: {exc}")
    elif not args.quiet:
        step("validate_integrity", "skip",
             "opt-in: --validate-integrity (katta jadvallarda qulf olishi mumkin)")

    try:
        db.close_pool()
    except Exception:
        pass

    errors = report.get("errors") or []
    warnings = report.get("warnings") or []
    if not args.quiet:
        print("-" * 70)
        print(f"  JAMI: WARN={len(warnings)}, ERROR={len(errors)}")
    if args.json:
        report["ok"] = not errors
        print(json.dumps(report, ensure_ascii=False))
    if errors:
        print("MIGRATION/SCHEMA CHECK YIQILDI — yuqoridagi ❌ qatorlarni ko'ring.",
              file=sys.stderr)
        return 1
    if not args.quiet:
        print("✅ DB MIGRATION + SCHEMA CHECK OK" +
              (" (ogohlantirishlar bor)" if warnings else ""))
    else:
        print(f"DB_MIGRATION OK (warn={len(warnings)}, errors=0)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] DB_MIGRATION_UNEXPECTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
