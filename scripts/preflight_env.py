#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🛫 PRODUCTION PREFLIGHT — Muhit o'zgaruvchilari to'liqligi va siyosat tekshiruvi
=====================================================================

Maqsad: botni ishga tushirishdan OLDIN (deploy/bootstrap paytida) muhit
to'liqligini va xavfsizlik siyosatini tekshirish — yarim sozlangan server
ishga tushib, keyin foydalanuvchi oldida yiqilib qolmasligi uchun.

Nima tekshiriladi (FAZA: PRODUCTION RUNTIME & DEPLOYMENT VERIFICATION):

  1) MAJBURIY: ``BOT_TOKEN`` (mavjud + format) · ``DATABASE_URL`` (mavjud +
     sxema/host/baza) · ``PORT`` (1..65535);
  2) 🛡 P0-A SIYOSATI: ``ENVIRONMENT`` (production|staging|development|test;
     berilmasa — fail-closed ``production``) va ``AI_ALLOW_MOCK``
     (production'da yoqilgan bo'lsa — ERROR) · ``TELEGRAM_API_BASE_URL``
     production'da BO'SH bo'lishi shart (mock API'ga so'rov taqiqlanadi);
  3) 🔁 REDIS: ``REDIS_URL`` sxemasi (``redis://`` | ``rediss://``),
     ``REDIS_ENABLED=1`` bilan URL yo'qligi ziddiyati (ERROR);
  4) 🩺 HEALTH: ``HEALTH_READY_TOKEN`` — bo'sh bo'lsa ``/health/ready``
     fail-closed 404 (WARN; ``--strict`` bilan ERROR), weak (<16 belgi) WARN,
     BOT_TOKEN bilan bir xil bo'lsa ERROR;
  5) 🗄 DB POOL: ``DB_POOL_MIN`` > ``DB_POOL_SIZE/DB_POOL_MAX`` ziddiyati;
  6) 🤖 AI GATEWAY: kamida bitta provayder kaliti (CLOUDFLARE — id+token
     juftligi), aks holda WARN (bot ishlaydi, lekin AI javob bera olmaydi);
  7) 👤 ADMIN, 💳 to'lov rekvizitlari (faqat bittasi to'ldirilgan bo'lsa WARN),
     🌙 ``AUTOPILOT_QUIET_HOURS`` formati, ⏱ ``SHUTDOWN_GRACE_SECONDS``
     oralig'i (5..30).

Maxfiylik: hech bir kalitning QIYMATI chop etilmaydi — faqat mavjudlik va
uzunlik ("<set: len=46>"). Bu skript loglarga/CI artefaktlariga secret
chiqarmaydi.

Ishga tushirish::

    python3 scripts/preflight_env.py                       # jarayon env'i
    python3 scripts/preflight_env.py --env-file .env       # .env ni o'qib
    python3 scripts/preflight_env.py --env-file .env --strict --json
    bash scripts/start_production.sh --check-only          # (o'ram)

Chiqish kodlari::

    0 — ERROR yo'q (WARN bo'lishi mumkin; ``--strict`` bilan WARN ham to'sadi)
    1 — kamida bitta ERROR (yoki ``--strict`` dagi WARN)
    2 — foydalanish xatosi (noto'g'ri argument)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

OK = "OK"
WARN = "WARN"
ERROR = "ERROR"
LEVEL_ORDER = {OK: 0, WARN: 1, ERROR: 2}

#: ``ENVIRONMENT`` uchun ruxsat etilgan qiymatlar (config.py P0-A siyosati).
ALLOWED_ENVIRONMENTS = ("production", "staging", "development", "test")
#: Berilmagan ``ENVIRONMENT`` — fail-closed default (config.py bilan bir xil).
FAIL_CLOSED_ENVIRONMENT = "production"

#: Kod/CI tomonidan beriladigan, `.env` faylida bo'lishi shart bo'lmagan ichki
#: kalitlar (CI/test o'zi boshqaradi — hujjatda ham shunday yozilgan).
INTERNAL_KEYS = frozenset({
    "PYTHON", "PYTHONPATH", "PATH", "HOME", "PWD", "SHELL", "TERM", "LANG",
    "LC_ALL", "TZ", "CI", "GITHUB_ACTIONS", "GITHUB_TOKEN", "XDG_RUNTIME_DIR",
    "P0_TEST_DATABASE_URL", "INTEGRITY_TEST_SKIP_LIVE", "RBAC_TEST_SKIP_LIVE",
})

#: AI provayder kalitlari (kamida bittasi tavsiya etiladi).
AI_KEY_NAMES = (
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
)
#: Cloudflare Workers AI — id + token JUFTLIGI bo'lishi shart.
CLOUDFLARE_PAIR = ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")

_TRUTHY = {"1", "true", "yes", "on", "y", "ha"}
_TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{5,}$")
_STRICT_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
_QUIET_RE = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*[-–—to]+\s*(\d{1,2})(?::(\d{2}))?\s*$",
    re.IGNORECASE,
)
_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


#: `.env.example` dan nusxalangan "to'ldirilmagan" qiymat belgilari.
_PLACEHOLDER_MARKERS = (
    "your_", "here", "_here", "placeholder", "example", "changeme", "xxxx",
    "<", ">", "todo", "namuna",
)


def _looks_like_placeholder(value: str) -> bool:
    low = (value or "").strip().lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _mask(value: str) -> str:
    """Qiymatni chop etish uchun xavfsiz ko'rinishga keltiradi (hech qachon
    qiymatning o'zi ko'rsatilmaydi)."""
    if not value:
        return "<bo'sh>"
    return f"<set: len={len(value)}>"


def parse_env_file(path: Path) -> dict[str, str]:
    """Oddiy ``KEY=VALUE`` parser (``export``, qo'shtirnoq, ``#`` izoh).

    Muhit fayllari ``python-dotenv`` ishlatilmagan repo uchun qo'lda
    o'qiladi — qiymatlar orasida interpolatsiya YO'Q, ``#`` bilan boshlangan
    qatorlar va qator oxiridagi `` # izoh`` tashlab yuboriladi.
    """
    parsed: dict[str, str] = {}
    if not path.is_file():
        return parsed
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _KEY_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        value = value.strip()
        if value[:1] in ("'", '"') and len(value) >= 2 and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # "qiymat # izoh" — faqat bo'shliqdan keyingi izohni kesamiz.
            hash_at = value.find(" #")
            if hash_at != -1:
                value = value[:hash_at]
        parsed[key] = value.strip()
    return parsed


def load_environment(env_file: Path | None, *, use_process_env: bool = True) -> dict[str, str]:
    """Jarayon muhiti + (ixtiyoriy) ``.env`` faylini birlashtiradi.

    Ustuvorlik: JARAYON muhiti (systemd/Docker/CI) ``.env`` dan YUQORI —
    fayl faqat yetishmayotgan kalitlarni to'ldiradi.
    """
    merged: dict[str, str] = {}
    if env_file is not None:
        merged.update(parse_env_file(env_file))
    if use_process_env:
        merged.update({k: v for k, v in os.environ.items()})
    return merged


@dataclass
class Finding:
    level: str
    code: str
    message: str


@dataclass
class Report:
    """Topilmalar to'plami (ERROR/WARN/OK) va yakuniy qaror."""

    strict: bool = False
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> Finding:
        finding = Finding(level, code, message)
        self.findings.append(finding)
        return finding

    def ok(self, code: str, message: str) -> None:
        self.add(OK, code, message)

    def warn(self, code: str, message: str) -> None:
        self.add(WARN if not self.strict else ERROR, code, message)

    def error(self, code: str, message: str) -> None:
        self.add(ERROR, code, message)

    # ---- yakunlar ----------------------------------------------------
    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def oks(self) -> list[Finding]:
        return [f for f in self.findings if f.level == OK]

    @property
    def passed(self) -> bool:
        return not self.errors


# ──────────────────────────────────────────────────────────────
# TEKSHIRUVLAR
# ──────────────────────────────────────────────────────────────
def check_required_and_policy(env: dict[str, str], report: Report) -> str:
    """1/2-bo'lim: majburiy kalitlar + P0-A muhit siyosati. Effektiv muhitni
    qaytaradi (``ENVIRONMENT`` berilmasa — fail-closed ``production``)."""
    token = (env.get("BOT_TOKEN") or "").strip()
    if not token:
        report.error("BOT_TOKEN_MISSING",
                     "BOT_TOKEN bo'sh — bot ishga tushmaydi (config.py RuntimeError).")
    else:
        pattern = _STRICT_TOKEN_RE if _effective_env(env) == "production" else _TOKEN_RE
        if pattern.match(token):
            report.ok("BOT_TOKEN_FORMAT", f"BOT_TOKEN mavjud va format to'g'ri {_mask(token)}")
        elif _looks_like_placeholder(token):
            report.error("BOT_TOKEN_PLACEHOLDER",
                         f"BOT_TOKEN hali NAMUNA qiymatda {_mask(token)} — .env.example'ni "
                         "nusxalaganingizdan keyin @BotFather bergan HAQIQIY tokenni kiriting.")
        else:
            report.error("BOT_TOKEN_FORMAT",
                         f"BOT_TOKEN formati noto'g'ri {_mask(token)} — "
                         "@BotFather bergan token '123456789:AA...' shaklida bo'ladi.")

    db_url = (env.get("DATABASE_URL") or "").strip()
    if not db_url:
        report.error("DATABASE_URL_MISSING",
                     "DATABASE_URL bo'sh — baza ulanmasa bot ishga tushmaydi.")
    else:
        parts = urlsplit(db_url)
        # Host: TCP (`host:port`) YOKI Unix-socket (`?host=/var/run/postgresql`),
        # masalan pgserver yoki lokal `psql` DSN'lari.
        host_shown = parts.hostname or ""
        if not host_shown:
            from urllib.parse import parse_qs
            host_shown = (parse_qs(parts.query).get("host") or [""])[0]
        dsn_ok = parts.scheme in ("postgres", "postgresql") and bool(host_shown) \
            and bool((parts.path or "").strip("/")) and parts.port != 0
        if dsn_ok:
            report.ok("DATABASE_URL_FORMAT",
                      f"DATABASE_URL PostgreSQL DSN {_mask(db_url)} "
                      f"(host={host_shown}, db={parts.path.strip('/')})")
        else:
            report.error("DATABASE_URL_FORMAT",
                         "DATABASE_URL 'postgresql://user:parol@host:5432/baza' "
                         f"ko'rinishida bo'lishi shart {_mask(db_url)}")
        if dsn_ok and _effective_env(env) == "production" \
                and "sslmode=" not in db_url.lower() \
                and parts.hostname not in ("localhost", "127.0.0.1", "::1", "db", "postgres"):
            report.warn("DATABASE_URL_SSL",
                        "DATABASE_URL'da `?sslmode=require` yo'q — tashqi baza (Neon/Aiven) "
                        "uchun TLS majburiy tavsiya etiladi.")

    port_raw = (env.get("PORT") or "").strip()
    if not port_raw:
        report.ok("PORT_DEFAULT", "PORT berilmagan — ilova standart 10000 ni ishlatadi "
                                  "(deploy skripti 8080 ni taklif qiladi).")
    else:
        try:
            port = int(port_raw)
        except ValueError:
            port = -1
        if 1 <= port <= 65535:
            report.ok("PORT_VALID", f"PORT={port} (1..65535 oralig'ida)")
        else:
            report.error("PORT_INVALID", f"PORT noto'g'ri: {port_raw!r} (1..65535 bo'lishi kerak).")

    # P0-A: muhit siyosati
    raw_env = (env.get("ENVIRONMENT") or "").strip()
    effective = raw_env.lower() or FAIL_CLOSED_ENVIRONMENT
    if raw_env and effective not in ALLOWED_ENVIRONMENTS:
        report.error("ENVIRONMENT_INVALID",
                     f"ENVIRONMENT={raw_env!r} — ruxsat etilganlar: "
                     f"{', '.join(ALLOWED_ENVIRONMENTS)}.")
    elif raw_env:
        report.ok("ENVIRONMENT_SET", f"ENVIRONMENT={effective}")
    else:
        report.ok("ENVIRONMENT_DEFAULT",
                  f"ENVIRONMENT berilmagan — fail-closed '{FAIL_CLOSED_ENVIRONMENT}' "
                  "(config.py standarti).")

    mock = (env.get("AI_ALLOW_MOCK") or "").strip()
    if effective == "production" and _is_truthy(mock):
        report.error("AI_ALLOW_MOCK_FORBIDDEN",
                     "ENVIRONMENT=production bilan AI_ALLOW_MOCK yoqilgan — "
                     "soxta (shablon) javoblar TAQIQLANGAN (P0-A). AI_ALLOW_MOCK=0 qo'ying.")
    else:
        shown = mock if mock else "<bo'sh>"
        report.ok("AI_ALLOW_MOCK_POLICY",
                  f"AI_ALLOW_MOCK={shown} (muhit={effective}) — siyosatga mos.")

    api_base = (env.get("TELEGRAM_API_BASE_URL") or "").strip()
    if effective == "production" and api_base:
        report.error("TELEGRAM_API_BASE_URL_IN_PRODUCTION",
                     "TELEGRAM_API_BASE_URL production'da BO'SH bo'lishi shart "
                     "(mock Telegram server faqat staging/test uchun).")
    elif api_base:
        report.ok("TELEGRAM_API_BASE_URL_STAGING",
                  f"TELEGRAM_API_BASE_URL={api_base} (muhit={effective} — staging/mock).")
    return effective


def _effective_env(env: dict[str, str]) -> str:
    return (env.get("ENVIRONMENT") or "").strip().lower() or FAIL_CLOSED_ENVIRONMENT


def check_redis(env: dict[str, str], report: Report, effective_env: str) -> None:
    """3-bo'lim: Redis (distributed state) to'liqligi."""
    url = (env.get("REDIS_URL") or "").strip()
    enabled_raw = (env.get("REDIS_ENABLED") or "").strip()
    enabled = _is_truthy(enabled_raw) if enabled_raw else bool(url)
    if enabled and not url:
        report.error("REDIS_URL_MISSING",
                     "REDIS_ENABLED yoqilgan, lekin REDIS_URL bo'sh — Redis manzilini "
                     "kiriting yoki REDIS_ENABLED=0 qo'ying.")
        return
    if url:
        scheme = urlsplit(url).scheme.lower()
        if scheme in ("redis", "rediss"):
            report.ok("REDIS_URL_FORMAT",
                      f"REDIS_URL {scheme}:// sxemasida {_mask(url)} (REDIS_ENABLED={enabled_raw or 'auto'}).")
        else:
            shown_scheme = scheme if scheme else "<yo'q>"
            report.error("REDIS_URL_SCHEME",
                         f"REDIS_URL sxemasi noto'g'ri: {shown_scheme} "
                         "(redis:// yoki rediss:// bo'lishi shart).")
        return
    if effective_env == "production":
        report.warn("REDIS_DISABLED_IN_MEMORY",
                    "REDIS_URL bo'sh — holat (rate limit/kesh) faqat In-Memory'da qoladi. "
                    "Bir necha instance'da ishlatilsa Redis tavsiya etiladi "
                    "(bot baribir ishlaydi: circuit breaker + fallback).")
    else:
        report.ok("REDIS_DISABLED_IN_MEMORY",
                  "REDIS_URL bo'sh — In-Memory rejim (test/development uchun normal).")


def check_health_token(env: dict[str, str], report: Report) -> None:
    """4-bo'lim: /health/live va /health/ready kontrakti uchun token."""
    token = (env.get("HEALTH_READY_TOKEN") or "").strip()
    bot_token = (env.get("BOT_TOKEN") or "").strip()
    if not token:
        report.warn("HEALTH_READY_TOKEN_MISSING",
                    "HEALTH_READY_TOKEN bo'sh — /health/ready fail-closed 404 qaytaradi "
                    "(token o'rnatilganda 401/200/503). Production'da o'rnating: "
                    "openssl rand -hex 32")
        return
    if bot_token and token == bot_token:
        report.error("HEALTH_READY_TOKEN_EQUALS_BOT_TOKEN",
                     "HEALTH_READY_TOKEN BOT_TOKEN bilan bir xil — alohida kredensial "
                     "ishlating (bitta sir ikki maqsadga xizmat qilmasin).")
        return
    if len(token) < 16:
        report.warn("HEALTH_READY_TOKEN_WEAK",
                    f"HEALTH_READY_TOKEN juda qisqa {_mask(token)} — kamida 16 belgi "
                    "(tavsiya: 32 baytlik hex, openssl rand -hex 32).")
    else:
        report.ok("HEALTH_READY_TOKEN_SET",
                  f"HEALTH_READY_TOKEN o'rnatilgan {_mask(token)} — /health/ready himoyalangan.")


def check_db_pool(env: dict[str, str], report: Report) -> None:
    """5-bo'lim: DB pool sozlamalari izchilligi."""
    def _int(name: str, default: int) -> int | None:
        raw = (env.get(name) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            report.warn("DB_POOL_INVALID", f"{name}={raw!r} son emas — standart ishlatiladi.")
            return None

    pool_min = _int("DB_POOL_MIN", 2)
    pool_max = _int("DB_POOL_MAX", 10)
    pool_size = _int("DB_POOL_SIZE", 10)
    if pool_min is None or pool_max is None or pool_size is None:
        return
    if pool_min > max(pool_max, pool_size):
        report.warn("DB_POOL_INCONSISTENT",
                    f"DB_POOL_MIN={pool_min} > DB_POOL_SIZE={pool_size}/DB_POOL_MAX={pool_max} — "
                    "pool minimal hajmi maksimaldan katta bo'lmasligi kerak.")
    elif pool_size > 50:
        report.warn("DB_POOL_TOO_LARGE",
                    f"DB_POOL_SIZE={pool_size} juda katta — baza (Neon/Aiven free) "
                    "ulanish chegarasiga urilishi mumkin (tavsiya: 5..20).")
    else:
        report.ok("DB_POOL_VALID",
                  f"DB pool izchil (min={pool_min}, max={pool_max}, size={pool_size}).")


def check_ai_gateway(env: dict[str, str], report: Report, effective_env: str) -> None:
    """6-bo'lim: AI gateway provayder kalitlari."""
    present = [name for name in AI_KEY_NAMES if (env.get(name) or "").strip()]
    cf_account = (env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    cf_token = (env.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if cf_account or cf_token:
        if cf_account and cf_token:
            present.append("CLOUDFLARE")
        else:
            report.warn("CLOUDFLARE_PAIR_INCOMPLETE",
                        "CLOUDFLARE_ACCOUNT_ID va CLOUDFLARE_API_TOKEN JUFTLIKDA bo'lishi shart "
                        "(faqat bittasi to'ldirilgan).")
    if present:
        report.ok("AI_PROVIDERS_PRESENT",
                  f"AI provayder kalitlari: {', '.join(sorted(present))} "
                  f"(chain: {(env.get('AI_PROVIDER_CHAIN') or 'auto').strip() or 'auto'}).")
    else:
        report.warn("AI_PROVIDERS_MISSING",
                    "Hech bir AI provayder kaliti yo'q — bot ishlaydi, lekin AI "
                    "generatsiya o'rniga xavfsiz xabar qaytaradi (kvota refund).")


def check_admin_and_payments(env: dict[str, str], report: Report) -> None:
    """7-bo'lim: adminlar, to'lov rekvizitlari, quiet hours, shutdown byudjeti."""
    admin_ids = [p.strip() for p in (env.get("ADMIN_IDS") or "").split(",") if p.strip()]
    admin_id = (env.get("ADMIN_ID") or "0").strip()
    legacy_ok = admin_id not in ("", "0")
    if not admin_ids and not legacy_ok:
        report.warn("ADMIN_MISSING",
                    "ADMIN_IDS sozlanmagan (legacy ADMIN_ID ham yo'q) — admin "
                    "paneli va support murojaatlari yetib bormaydi.")
    else:
        extra = 1 if legacy_ok and admin_id not in admin_ids else 0
        report.ok("ADMIN_SET",
                  f"Adminlar: ADMIN_IDS={len(admin_ids)} ta"
                  + (f" + legacy ADMIN_ID={admin_id}" if extra else "")
                  + ".")

    card = (env.get("CARD_NUMBER") or "").strip()
    holder = (env.get("CARD_HOLDER") or "").strip()
    if card and not holder:
        report.warn("CARD_HOLDER_MISSING", "CARD_NUMBER bor, CARD_HOLDER yo'q — to'lov "
                                           "ekranida karta egasi ko'rsatilmaydi.")
    elif holder and not card:
        report.warn("CARD_NUMBER_MISSING", "CARD_HOLDER bor, CARD_NUMBER yo'q — karta "
                                           "orqali to'lov ishlamaydi.")
    elif card and not re.fullmatch(r"\d{16,19}", card.replace(" ", "")):
        report.warn("CARD_NUMBER_FORMAT", "CARD_NUMBER faqat raqamlardan iborat bo'lishi "
                                          "tavsiya etiladi (bo'sh joysiz, 16..19 raqam).")
    else:
        report.ok("PAYMENT_CONFIG",
                  "To'lov rekvizitlari izchil" + ("" if card else " (karta o'rnatilmagan — Stars ishlaydi)."))

    # Qo'shtirnoqlar (Render/Docker nusxasida qolib ketishi mumkin) olib tashlanadi.
    quiet = (env.get("AUTOPILOT_QUIET_HOURS") or "").strip().strip("\"'")
    if not quiet:
        report.ok("QUIET_HOURS_DEFAULT", "AUTOPILOT_QUIET_HOURS berilmagan — standart "
                                         "'23:00 - 08:00' ishlatiladi.")
    elif _QUIET_RE.match(quiet):
        report.ok("QUIET_HOURS_FORMAT", f"AUTOPILOT_QUIET_HOURS='{quiet}' formati to'g'ri.")
    else:
        report.warn("QUIET_HOURS_FORMAT",
                    f"AUTOPILOT_QUIET_HOURS={quiet!r} formati noto'g'ri — "
                    "'23:00 - 08:00' ko'rinishida bo'lishi kerak.")

    grace_raw = (env.get("SHUTDOWN_GRACE_SECONDS") or "").strip()
    if grace_raw:
        try:
            grace = int(grace_raw)
        except ValueError:
            report.warn("SHUTDOWN_GRACE_INVALID", f"SHUTDOWN_GRACE_SECONDS={grace_raw!r} son emas.")
        else:
            if 5 <= grace <= 30:
                report.ok("SHUTDOWN_GRACE_VALID", f"SHUTDOWN_GRACE_SECONDS={grace} (5..30).")
            else:
                report.warn("SHUTDOWN_GRACE_RANGE",
                            f"SHUTDOWN_GRACE_SECONDS={grace} 5..30 oralig'idan tashqarida "
                            "(qiymat avtomatik qisiladi, lekin Docker stop_grace_period "
                            "bundan KATTA bo'lishi kerak).")


def build_report(env: dict[str, str], *, strict: bool) -> tuple[Report, str]:
    report = Report(strict=strict)
    effective_env = check_required_and_policy(env, report)
    check_redis(env, report, effective_env)
    check_health_token(env, report)
    check_db_pool(env, report)
    check_ai_gateway(env, report, effective_env)
    check_admin_and_payments(env, report)
    return report, effective_env


def render(report: Report, *, env_file: Path | None, effective_env: str,
           use_process_env: bool) -> None:
    print("=" * 70)
    print(" 🛫 PRODUCTION PREFLIGHT — muhit to'liqligi va siyosat tekshiruvi")
    print("=" * 70)
    env_shown = str(env_file) if env_file and env_file.is_file() else "<yo'q>"
    print(f"  .env fayl       : {env_shown}")
    print("  jarayon muhiti  :", "ha" if use_process_env else "yo'q")
    print(f"  effektiv muhit  : {effective_env}   (strict={'on' if report.strict else 'off'})")
    print("-" * 70)
    for finding in report.findings:
        print(f"  [{finding.level}] {finding.code}: {finding.message}")
    print("-" * 70)
    print(f"  JAMI: OK={len(report.oks)}, WARN={len(report.warnings)}, ERROR={len(report.errors)}")
    if report.errors:
        print("  ❌ PREFLIGHT YIQILDI — yuqoridagi ERROR'larni tuzating.")
    elif report.warnings:
        print("  ⚠️  PREFLIGHT O'TDI (ogohlantirishlar bor — deploy davom etishi mumkin).")
    else:
        print("  ✅ PREFLIGHT 100% TOZA.")
    print("=" * 70)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Production preflight: muhit o'zgaruvchilari to'liqligi va siyosat tekshiruvi.",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE),
                        help="Muhit fayli (standart: .env; 'none' — o'qilmasin).")
    parser.add_argument("--no-process-env", action="store_true",
                        help="Faqat --env-file ishlatilsin (jarayon muhiti e'tiborsiz).")
    parser.add_argument("--strict", action="store_true",
                        help="Ogohlantirishlar ham deploy'ni to'xtatadi (exit 1).")
    parser.add_argument("--json", action="store_true",
                        help="Natijani mashina o'qiydigan JSON sifatida ham chiqarish.")
    parser.add_argument("--quiet", action="store_true",
                        help="Faqat yakuniy qatorni chop etish.")
    args = parser.parse_args(argv)

    env_file: Path | None
    if str(args.env_file).strip().lower() in ("none", "off", "-"):
        env_file = None
    else:
        env_file = Path(args.env_file).expanduser().resolve()

    env = load_environment(env_file, use_process_env=not args.no_process_env)
    report, effective_env = build_report(env, strict=args.strict)

    if not args.quiet:
        render(report, env_file=env_file, effective_env=effective_env,
               use_process_env=not args.no_process_env)

    if args.json:
        payload = {
            "ok": report.passed,
            "environment": effective_env,
            "strict": report.strict,
            "env_file": str(env_file) if env_file else None,
            "counts": {"ok": len(report.oks), "warn": len(report.warnings),
                       "error": len(report.errors)},
            "findings": [{"level": f.level, "code": f.code, "message": f.message}
                         for f in report.findings],
        }
        print(json.dumps(payload, ensure_ascii=False))

    if report.passed:
        if args.quiet:
            print(f"PREFLIGHT OK (warn={len(report.warnings)})")
        return 0
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover — kutilmagan xato ham aniq kod beradi
        print(f"[ERROR] PREFLIGHT_UNEXPECTED: {exc}", file=sys.stderr)
        sys.exit(1)
