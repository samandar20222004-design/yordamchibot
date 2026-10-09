#!/usr/bin/env python3
"""🛡 MAXFIY KALIT SIZISH GARD'I — repozitoriyaga secret tushishini to'sadi.

Nima uchun (1-BOSQICH XAVFSIZLIK auditi):
  Bot token / DB paroli / API kaliti bir marta GitHub'ga chiqsa, uni
  «o'chirish» yetarli EMAS — u butun tarixda qoladi va har bir fork'da
  ko'rinadi. Shu sabab bu guard CI'da (tests/run_tests.sh orqali) HAR SAFAR
  ishlaydi va quyidagilarni tekshiradi:

    1) Git INDEKSIDA maxfiy `.env` fayli yo'q (faqat `.env.example`);
    2) `.gitignore` maxfiy fayl turlarini qamraydi (`.env`, `*.env`,
       `.env.*`, `.pem`, `.netrc`, ...), lekin `.env.example` ni
       OCHIB qoldiradi (ildizdagi kanonik `.env.example`);
    3) Kod ichida haqiqiy bo'lishi mumkin bo'lgan Telegram token
       (`<raqam>:<base64>`) YO'Q — soxta/test tokenlaridan farqlanadi;
    4) `.env.example` dagi maxfiy kalitlarning qiymati BO'SH;
    5) Git TARIXIDA (barcha refs) token namuna topilmaydi;
    6) `config.py` BOT_TOKEN'ni faqat `os.getenv` dan oladi va topilmasa
       `RuntimeError` beradi (hardcoded default yo'q).

Bu test statik (import'siz, DB/tarmoq'siz) va tez ishlaydi:

    PYTHON=/tmp/venv/bin/python python3 tests/secret_leak_scan_test.py
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh

💡 CI uchun qo'shimcha QATTIQ qatlam (gitleaks butun tarixni, jumladan
   base64/entropy kalitlarni ushlaydi) — `.github/workflows/` da ishga
   tushirish uchun `workflows` huquqi kerak:

    name: Secret Scan
    on: [push, pull_request]
    jobs:
      gitleaks:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
            with: {fetch-depth: 0}          # TO'LIQ tarix shart
          - uses: gitleaks/gitleaks-action@v2
            env: {GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}}
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / ".env.example",)
PROD_PKG = ROOT / "telegram_bot"

# Telegram bot token: <bot_id 8-10 raqam> ":" <35+ base64url belgi>
_TG_TOKEN = re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35,}\b")
# Soxta/namuna belgilari — bular HAQIQIY kalit EMAS.
_FAKE_MARKERS = (
    "fake", "dummy", "example", "placeholder", "mock", "test", "your_",
    "changeme", "xxxx", "sample",
)
# maxfiy kalit kalitlari: qiymati bo'sh bo'lishi SHART
SECRET_KEYS = (
    "BOT_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY",
    "SAMBANOVA_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "SENTRY_DSN", "CARD_NUMBER", "CARD_HOLDER",
)

PASSED = 0
FAILURES = 0


def check(condition: bool, label: str, detail: str = "") -> bool:
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label}" + (f" → {detail}" if detail else ""))
    return bool(condition)


def git(*args: str) -> tuple[int, str]:
    """git buyrug'ini xavfsiz ishga tushiradi (topilmasa kod 0)."""
    try:
        p = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, timeout=120,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # pragma: no cover — git yo'q muhit
        return 1, f"git ishga tushmadi: {exc}"


def is_placeholder_token(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _FAKE_MARKERS)


def test_env_not_tracked() -> None:
    print("\n== 1) Git indeksida maxfiy .env yo'q ==")
    rc, out = git("ls-files")
    if rc != 0:
        check(False, "git ls-files ishladi", out[:120])
        return
    tracked = [p for p in out.splitlines() if p.strip()]
    leaked = [
        p for p in tracked
        if re.search(r"(^|/)\.env($|\.)", p) or re.search(r"(^|/)[^/]*\.env$", p)
    ]
    leaked = [p for p in leaked if not p.endswith(".env.example")]
    check(not leaked, "indeksda maxfiy .env/ *.env fayli yo'q", str(leaked))

    bad_secrets = [
        p for p in tracked
        if re.search(r"(^|/)(secrets?/|\.netrc$|\.pgpass$)", p)
        or p.endswith((".pem", ".key", ".p12", ".pfx"))
    ]
    check(not bad_secrets, "indeksda sertifikat/credential fayli yo'q", str(bad_secrets[:5]))


def test_gitignore_rules() -> None:
    print("\n== 2) .gitignore maxfiy fayllarni qamraydi ==")
    gi = ROOT / ".gitignore"
    if not check(gi.is_file(), ".gitignore mavjud"):
        return
    rc, out = git("check-ignore", "--no-index",
                  ".env", "telegram_bot/.env", ".env.local", "prod.env",
                  "secrets/x.json", "a.pem", ".netrc")
    ignored = set(out.split()) if rc == 0 else set()
    for probe in (".env", "telegram_bot/.env", ".env.local", "prod.env",
                  "secrets/x.json", "a.pem", ".netrc"):
        check(probe in ignored, f"`.gitignore` ga tushadi: {probe}")

    rc, out = git("check-ignore", "--no-index",
                  ".env.example")
    not_ignored = set(out.split()) if rc == 0 else set()
    check(".env.example" not in not_ignored,
          "`.env.example` esa IGNORE QILINMAYDI (kanonik namuna)")

    text = gi.read_text(encoding="utf-8")
    check("!.env.example" in text,
          "`.gitignore` da `!.env.example` qoidasi bor")
    # Qoida tartibi: `.env.*` dan KEYIN kelishi shart.
    neg = text.find("!.env.example")
    dot_env_any = text.find(".env.*")
    check(dot_env_any != -1 and neg > dot_env_any,
          "`!.env.example` `.env.*` dan KEYIN keladi (tartib muhim)")


def test_code_tokens() -> None:
    print("\n== 3) Kod ichida haqiqiy Telegram token yo'q ==")
    rc, out = git("grep", "-nI", "-E", r"[0-9]{8,10}:[A-Za-z0-9_-]{35,}",
                  "--", "*.py", "*.yml", "*.yaml", "*.toml", "*.ini", "*.cfg")
    if rc not in (0, 1):
        check(False, "git grep ishladi", out[:120])
        return
    hits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        if _TG_TOKEN.search(line) and not is_placeholder_token(line):
            hits.append(line)
    check(not hits, "koding ichida token namuna yo'q", "; ".join(hits[:3]))

    # config.py: BOT_TOKEN faqat env dan, hardcoded default YO'Q.
    cfg = (PROD_PKG / "config.py").read_text(encoding="utf-8")
    check('BOT_TOKEN = os.getenv("BOT_TOKEN")' in cfg,
          "config.py: BOT_TOKEN = os.getenv(\"BOT_TOKEN\") (default yo'q)")
    check("if not BOT_TOKEN:" in cfg and "raise RuntimeError" in cfg,
          "config.py: BOT_TOKEN yo'q bo'lsa RuntimeError beradi")
    check(re.search(r'os\.getenv\(\s*["\']BOT_TOKEN["\']\s*,', cfg) is None,
          "config.py: BOT_TOKEN uchun os.getenv default qiymati yo'q")


def test_env_example_secrets_empty() -> None:
    print("\n== 4) `.env.example` dagi maxfiy qiymatlar BO'SH ==")
    key_line = re.compile(r"(?m)^([A-Z0-9_]+)=(.*)$")
    for path in ENV_FILES:
        rel = path.relative_to(ROOT).as_posix()
        if not check(path.is_file(), f"{rel} mavjud"):
            continue
        kv = {m.group(1): m.group(2).strip() for m in key_line.finditer(
            path.read_text(encoding="utf-8"))}
        leaked = [k for k in SECRET_KEYS
                  if k in kv and kv[k].strip("\"'") not in ("",)]
        # BOT_TOKEN/DATABASE_URL namunaviy qiymatga ega bo'lishi mumkin
        # (faqat haqiqiy secret bo'lmasligi kerak) — ularni alohida tekshiramiz.
        leaked = [k for k in leaked if k not in ("BOT_TOKEN",)]
        check(not leaked, f"{rel}: maxfiy qiymatlar bo'sh", str(leaked))

        tok = kv.get("BOT_TOKEN", "")
        check(
            not _TG_TOKEN.search(tok) or is_placeholder_token(tok),
            f"{rel}: BOT_TOKEN haqiqiy token EMAS (namuna)",
        )


def test_history_tokens() -> None:
    print("\n== 5) Git TARIXIDA token namuna yo'q ==")
    rc, out = git("log", "--all", "--pretty=format:%H")
    if rc != 0:
        check(False, "git log ishladi", out[:120])
        return
    commits = [c for c in out.split() if c]
    check(bool(commits), "tarix o'qildi", f"({len(commits)} komit)")

    # Faqat haqiqiy token bo'lgan kalitlarni tekshiramiz. `git grep <pattern>
    # <commit>` juda tez; soxta belgilar bilan filtrlanadi.
    bad = []
    for commit in commits:
        rc2, out2 = git("grep", "-I", "-l", "-E",
                        r"[0-9]{8,10}:[A-Za-z0-9_-]{35,}", commit)
        if rc2 not in (0, 1):
            continue
        for path in out2.split():
            if not path.strip():
                continue
            rc3, content = git("show", f"{commit}:{path.strip()}")
            if rc3 != 0:
                continue
            for line in content.splitlines():
                if _TG_TOKEN.search(line) and not is_placeholder_token(line):
                    bad.append(f"{commit[:8]}:{path.strip()}")
                    break
        if len(bad) >= 5:
            break
    check(not bad, "tarixdagi barcha komitlarda haqiqiy token yo'q",
          "; ".join(bad[:5]))


def main() -> int:
    print("=" * 70)
    print(" 🛡 MAXFIY KALIT SIZISH GARD'I")
    print("=" * 70)
    test_env_not_tracked()
    test_gitignore_rules()
    test_code_tokens()
    test_env_example_secrets_empty()
    test_history_tokens()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] MAXFIY KALIT XAVFI BOR ^^^")
        print("")
        print(" Tuzatish tartibi:")
        print("   1) Kalitni DARHOL aylantiring (@BotFather /Render /AI provider).")
        print("   2) git rm --cached <maxfiy fayl>")
        print("   3) Tarixni tozalang: git filter-repo --path .env --invert-paths")
        return 1
    print(" MAXFIY KALIT XAVFI TOPILMADI ✔")
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
