#!/usr/bin/env python3
"""DEPLOYMENT READINESS — `.env.example` KANONIK HOLAT VA PARITET GUARDI.

Nima uchun (Phase 0 auditi, 2-bo'lim va P2-O/P2-P topilmalari):
  * `.env.example` fayllarida **dublikat parametrlar** paydo bo'lgan edi
    (`GEMINI_VISION_MODEL`, `VISION_MAX_FILE_BYTES`) — ularning birida
    **o'chirilgan model** (`gemini-1.5-flash`) turgan edi;
  * ildiz va `telegram_bot/` nusxalari **sinxron emas** edi (Render Root
    Directory = `telegram_bot` bo'lgani uchun STT bo'limi prodda "yo'q" edi);
  * 25 ta **kodda o'qiladigan** o'zgaruvchi hujjatda **umuman yo'q** edi.

Bu test — hujjat gigiyenasini qulflaydigan statik (import'siz, DB/tarmoq'siz)
guard. U hech qanday production kodga tegmaydi va doim ishlaydi:

    PYTHON=/tmp/venv/bin/python python3 tests/env_docs_parity_test.py
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh

Tekshiruvlar:
  1) har bir faylda dublikat `KEY=` qatori YO'Q;
  2) ikkala faylning kalitlar TO'PLAMI va QIYMATLARI bir xil (paritet);
  3) majburiy kalitlar mavjud (BOT_TOKEN, DATABASE_URL, ENVIRONMENT, ...);
  4) P0-A siyosati: ENVIRONMENT=production, AI_ALLOW_MOCK=0 va izohlarda
     fail-closed qoida yozilgan;
  5) eskirgan (`gemini-1.5-flash`) MODEL QIYMATI sifatida YO'Q;
     GEMINI_VISION_MODEL — kanonik `gemini-2.5-flash`;
  6) kodda o'qiladigan HAR BIR production o'zgaruvchi hujjatlangan (P2-O);
  7) hujjatlangan har bir o'zgaruvchi kodda haqiqatan ishlatiladi (orphan
     yo'q — "o'lik" dokumentatsiya qoldiq bo'lib qolmaydi);
  8) maxfiylik: API kalitlar / DSN / karta rekvizitlari qiymatlari BO'SH
     (namunaga haqiqiy secret yozilmaydi).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / ".env.example", ROOT / "telegram_bot" / ".env.example")
PROD_PKG = ROOT / "telegram_bot"

# Kod ichidagi o'qish nuqtalari: os.getenv / os.environ.get / yordamchilar.
_ENV_READ = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_env_int|_env_float|_env_flag'
    r'|_int_env|_str_env)\(\s*["\']([A-Z][A-Z0-9_]{2,})["\']'
)
_KEY_LINE = re.compile(r"(?m)^([A-Z0-9_]+)=(.*)$")

# 3) Majburiy deb hisoblanadigan kalitlar (deploy uchun shart).
REQUIRED_KEYS = (
    "BOT_TOKEN", "BOT_USERNAME", "DATABASE_URL", "DB_SSLMODE", "ADMIN_ID",
    "ADMIN_IDS", "DB_POOL_MAX", "DB_POOL_SIZE", "ENVIRONMENT", "AI_ALLOW_MOCK",
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "AI_PROVIDER_CHAIN",
    "GEMINI_VISION_MODEL", "VISION_MAX_FILE_BYTES", "GEMINI_AUDIO_MODEL",
    "GROQ_STT_ENDPOINT", "GROQ_STT_MODEL", "STT_TOTAL_TIMEOUT",
    "POST_BATCH_SIZE", "SENT_JOURNAL_PATH", "SHUTDOWN_GRACE_SECONDS",
    "CLEANUP_BATCH_SIZE", "HEALTH_FAILED_ALERT", "SENTRY_DSN", "PORT",
    "CARD_NUMBER", "CARD_HOLDER", "PAYMENT_ADMIN_USERNAME", "SUPPORT_USERNAME",
    "PAYMENT_PRICE_1M_UZS", "STARS_PRICE_1M", "USD_EQUIV_1M",
    "FREE_MAX_CHANNELS", "PRO_MAX_CHANNELS",
)
# 5) O'chirilgan/eskirgan Gemini modellari — QIYMAT sifatida taqiqlanadi.
RETIRED_MODELS = (
    "gemini-1.5-flash", "gemini-1.5-flash-001", "gemini-1.5-flash-002",
    "gemini-1.5-flash-8b", "gemini-1.5-flash-latest",
)
VISION_CANONIC = "gemini-2.5-flash"
VISION_ALLOWED = {"gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"}
# 8) Qiymati bo'sh bo'lishi shart bo'lgan maxfiy kalitlar (placeholder'siz).
SECRET_KEYS = (
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "SENTRY_DSN",
    "CARD_NUMBER", "CARD_HOLDER",
)

PASSED = 0
FAILURES = 0


def check(condition, label, detail: str = "") -> bool:
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label}" + (f" → {detail}" if detail else ""))
    return bool(condition)


def parse(path: Path) -> list[tuple[str, str]]:
    """(kalit, qiymat) ro'yxati — tartib saqlanadi, izohlar hisobga olinmaydi."""
    text = path.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2).strip()) for m in _KEY_LINE.finditer(text)]


def prod_code_blob() -> str:
    """telegram_bot production kodini bitta matn qilib qaytaradi (tests/siz)."""
    chunks: list[str] = []
    for py in sorted(PROD_PKG.rglob("*.py")):
        if "tests" in py.parts:
            continue
        chunks.append(py.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def test_no_duplicates_and_shape() -> dict[str, dict[str, str]]:
    print("\n== 1) Fayllar mavjud va ichida dublikat kalit YO'Q ==")
    parsed: dict[str, dict[str, str]] = {}
    for path in ENV_FILES:
        rel = path.relative_to(ROOT).as_posix()
        if not check(path.is_file(), f"{rel} mavjud"):
            continue
        pairs = parse(path)
        keys = [k for k, _ in pairs]
        dups = sorted({k for k in keys if keys.count(k) > 1})
        check(not dups, f"{rel}: har bir kalit BITTA marta",
              f"dublikat: {dups}")
        check(len(keys) > 60,
              f"{rel}: to'liq o'zgaruvchilar to'plami ({len(keys)} ta)",
              str(len(keys)))
        kv = {}
        for k, v in pairs:
            kv[k] = v
        parsed[rel] = kv
        # Har bir `KEY=` qatoridan oldin yoki ustida izoh bo'lishi shart emas,
        # lekin fayl izohsiz bo'lib qolmasligi kerak.
        text = path.read_text(encoding="utf-8")
        comments = sum(1 for line in text.splitlines() if line.startswith("#"))
        check(comments >= len(keys), f"{rel}: har bir bo'lim izohlangan "
                                     f"({comments} izoh / {len(keys)} kalit)", str(comments))
    return parsed


def test_parity(parsed: dict[str, dict[str, str]]) -> None:
    print("\n== 2) Ikkala nusxa PARITYETI (Render = telegram_bot, Docker = root) ==")
    if len(parsed) != 2:
        check(False, "ikkala fayl ham o'qildi", str(list(parsed)))
        return
    (name_a, kv_a), (name_b, kv_b) = parsed.items()
    only_a = sorted(set(kv_a) - set(kv_b))
    only_b = sorted(set(kv_b) - set(kv_a))
    check(not only_a and not only_b,
          f"{name_a} va {name_b}: bir xil kalitlar to'plami",
          f"faqat {name_a}: {only_a} | faqat {name_b}: {only_b}")
    diff = sorted(k for k in set(kv_a) & set(kv_b) if kv_a[k] != kv_b[k])
    check(not diff, "har bir kalitning QIYMATI ham bir xil",
          ", ".join(f"{k}: {kv_a[k]!r} vs {kv_b[k]!r}" for k in diff[:5]))


def test_required_keys(parsed: dict[str, dict[str, str]]) -> None:
    print("\n== 3) Deploy uchun MAJBURIY kalitlar hujjatlangan ==")
    for rel, kv in parsed.items():
        missing = [k for k in REQUIRED_KEYS if k not in kv]
        check(not missing, f"{rel}: majburiy kalitlar to'liq", str(missing))


def test_p0_a_policy(parsed: dict[str, dict[str, str]]) -> None:
    print("\n== 4) 🛡 P0-A: ENVIRONMENT / AI_ALLOW_MOCK qiymati va izohi ==")
    for path in ENV_FILES:
        rel = path.relative_to(ROOT).as_posix()
        kv = parsed.get(rel)
        if kv is None:
            continue
        check(kv.get("ENVIRONMENT") == "production",
              f"{rel}: ENVIRONMENT=production (fail-closed default)")
        check(kv.get("AI_ALLOW_MOCK") == "0",
              f"{rel}: AI_ALLOW_MOCK=0 (prodda Mock o'chirilgan)")
        text = path.read_text(encoding="utf-8")
        # Izohlar siyosatni to'g'ri tushuntirishi shart (eski chalkashlik xatosi).
        for needle, label in (
            ("ENVIRONMENT", "ENVIRONMENT izohlangan"),
            ("AI_ALLOW_MOCK", "AI_ALLOW_MOCK izohlangan"),
            ("development", "ruxsat etilgan muhitlar ko'rsatilgan"),
            ("test", "test muhiti ko'rsatilgan"),
            ("SOXTA GENERATSIYA YO'Q", "prodda soxta generatsiya taqiqlangani yozilgan"),
            ("TO'LIQ qaytariladi", "kvota refund qoidasi yozilgan"),
            ("O'ZGARTIRMANG", "prodda qiymatni o'zgartirmaslik ogohlantirishi"),
        ):
            check(needle in text, f"{rel}: {label}")


def test_models_and_secrets(parsed: dict[str, dict[str, str]]) -> None:
    print("\n== 5) Model kanonik qiymatlari + 8) maxfiy kalitlar bo'sh ==")
    for rel, kv in parsed.items():
        bad = [k for k, v in kv.items() if v.strip('"\'') in RETIRED_MODELS]
        check(not bad,
              f"{rel}: o'chirilgan model (gemini-1.5-flash) QIYMAT'da yo'q",
              str(bad))
        check(kv.get("GEMINI_VISION_MODEL") == VISION_CANONIC,
              f"{rel}: GEMINI_VISION_MODEL = {VISION_CANONIC}",
              kv.get("GEMINI_VISION_MODEL", "<yo'q>"))
        check(kv.get("GEMINI_AUDIO_MODEL", "") in VISION_ALLOWED,
              f"{rel}: GEMINI_AUDIO_MODEL barqaror Gemini modeli",
              kv.get("GEMINI_AUDIO_MODEL", "<yo'q>"))
        leaked = [k for k in SECRET_KEYS if kv.get(k, "") != ""]
        check(not leaked, f"{rel}: secret namunalarining qiymati BO'SH",
              str(leaked))
        # Vision hajmi bitta joyda va 10 MB ga teng (eski dublikat bilan ziddiyat yo'q).
        check(kv.get("VISION_MAX_FILE_BYTES") == str(10 * 1024 * 1024),
              f"{rel}: VISION_MAX_FILE_BYTES = 10485760 (yagona manba)",
              kv.get("VISION_MAX_FILE_BYTES", "<yo'q>"))


def test_env_coverage(parsed: dict[str, dict[str, str]]) -> None:
    print("\n== 6/7) Kod ↔ hujjat qamrovi (P2-O: 25 ta yetishmagan edi) ==")
    blob = prod_code_blob()
    code_keys = sorted(set(_ENV_READ.findall(blob)))
    check(len(code_keys) > 80, f"production kodda o'qiladigan env'lar topildi ({len(code_keys)})")
    for rel, kv in parsed.items():
        undocumented = sorted(k for k in code_keys if k not in kv)
        check(not undocumented,
              f"{rel}: kod o'qiydigan HAMMA o'zgaruvchi hujjatlangan",
              f"yetishmayapti: {undocumented}")
        orphans = sorted(k for k in kv if k not in blob)
        check(not orphans, f"{rel}: hujjatda ORPHAN (kodda ishlatilmaydigan) kalit yo'q",
              f"orphan: {orphans}")


def main() -> int:
    print("=" * 70)
    print(" 🧾 DEPLOYMENT READINESS — .env.example KANONIK HOLAT VA PARITET")
    print("=" * 70)
    parsed = test_no_duplicates_and_shape()
    test_parity(parsed)
    test_required_keys(parsed)
    test_p0_a_policy(parsed)
    test_models_and_secrets(parsed)
    test_env_coverage(parsed)

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] ENV DOCS/HUJJATLARDA MUAMMO BOR ^^^")
        return 1
    print(" ENV DOCS PARITY — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
