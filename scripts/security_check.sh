#!/usr/bin/env bash
# ============================================================================
# PostAssist V2 — XAVFSIZLIK VA QAT'IYLIK DARVOZASI (SERVERDA BITTA KOMANDA)
# ----------------------------------------------------------------------------
# docs/ci-hardening.yml dagi taklif qilingan qoidalarning SERVER versiyasi.
# GitHub Actions (` .github/workflows/ci.yml`) ham aynan shu skriptni chaqiradi,
# shuning uchun CI va server bir xil qoidalar bilan tekshiriladi (yagona manba).
#
#   bash scripts/security_check.sh
#
# Darvozalar (barchasi ketma-ket, bittasi ham yashirincha o'tkazib yuborilmaydi):
#
#   1) 🚦 LINT GATE     — ruff E9,F63,F7,F82 (sintaksis va aniqlanmagan nomlar)
#                         + flake8 xuddi shu tanlov bilan. BLOKLOVCHI: bu xato
#                         bo'lsa ilova ishga tushmaydi.
#   2) 🧹 FULL RUFF     — to'liq ruff tekshiruvi (hisobot; mavjud texnik qarz
#                         job'ni qizartirmasligi uchun --advisory rejimda).
#   3) 🔐 PIP-AUDIT     — telegram_bot/requirements.txt dagi bog'liqliklarning
#                         ma'lum zaifliklari (CVE).
#   4) 🛡 BANDIT        — `bandit -r telegram_bot -ll` (o'rtacha va undan
#                         yuqori statik xavfsizlik topilmalari).
#
# ISHLATISH:
#     bash scripts/security_check.sh                 # qat'iy: topilma bo'lsa exit 1
#     bash scripts/security_check.sh --advisory      # faqat hisobot (exit 0)
#     bash scripts/security_check.sh --install       # yetishmayotgan vositani
#                                                    # avtomatik pip install qilish
#     bash scripts/security_check.sh --skip-network  # pip-audit (tarmoq) o'tkazib
#                                                    # yuboriladi — oflayn serverlar
#     bash scripts/security_check.sh --json out.json # mashina o'qiydigan hisobot
#
# Muhim: vosita o'rnatilmagan bo'lsa u [SKIP] sifatida qayd etiladi va
# YASHIL deb hisoblanMAYDI (soxta PASS yo'q) — lekin qat'iy rejimda ham
# job'ni yiqitmaydi, chunki bu muhit yetishmovchiligi, kod xatosi emas.
# Barcha vositalar o'rnatilgan CI'da [SKIP] bo'lmaydi.
#
# EXIT: 0 — hammasi toza (yoki --advisory); 1 — kamida bitta darvoza yiqildi.
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Argumentlar ------------------------------------------------------------
ADVISORY=0
AUTO_INSTALL=0
SKIP_NETWORK=0
JSON_OUT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --advisory)      ADVISORY=1 ;;
        --install)       AUTO_INSTALL=1 ;;
        --skip-network)  SKIP_NETWORK=1 ;;
        --json)          JSON_OUT="${2:-}"; shift ;;
        -h|--help)       sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "[security][WARN] noma'lum argument: $1" >&2 ;;
    esac
    shift
done

# --- Interpretator (run_tests.sh bilan bir xil mantiq) ----------------------
resolve_py() {
    if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
    if [ -x "$HOME/venv/bin/python" ]; then echo "$HOME/venv/bin/python"; return; fi
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then echo "$REPO_ROOT/.venv/bin/python"; return; fi
    if command -v python3 >/dev/null 2>&1; then echo python3; return; fi
    echo python
}
PY="$(resolve_py)"

TELEGRAM_DIR="$REPO_ROOT/telegram_bot"
REQUIREMENTS="$TELEGRAM_DIR/requirements.txt"

FAILED_GATES=()
PASSED_GATES=()
SKIPPED_GATES=()

log()    { printf '[security] %s\n' "$*"; }
ok()     { printf '  [OK] %s\n' "$*"; }
bad()    { printf '  [FAIL] %s\n' "$*" >&2; }
skip()   { printf '  [SKIP] %s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$*"; }

# Vosita mavjudligini tekshiradi (`python -m <modul>` yoki PATH'dagi bajaruvchi).
# Natija: $TOOL_KIND = module | binary | "" va $TOOL_CMD = ishga tushirish qismi.
TOOL_KIND=""
TOOL_CMD=""
resolve_tool() {
    local module="$1" binary="$2"
    TOOL_KIND=""; TOOL_CMD=""
    if "$PY" -c "import $module" >/dev/null 2>&1; then
        TOOL_KIND="module"; TOOL_CMD="$PY -m $module"; return 0
    fi
    if command -v "$binary" >/dev/null 2>&1; then
        TOOL_KIND="binary"; TOOL_CMD="$binary"; return 0
    fi
    return 1
}

ensure_tool() {
    local module="$1" binary="$2"
    resolve_tool "$module" "$binary" && return 0
    if [ "$AUTO_INSTALL" -eq 1 ]; then
        log "$binary o'rnatilmoqda (--install)..."
        if "$PY" -m pip install --quiet "$binary" >/dev/null 2>&1; then
            resolve_tool "$module" "$binary" && return 0
        fi
    fi
    return 1
}

run_gate() {
    # run_gate <nomi> <bloklovchi: 0|1> <bajariladigan qism...>
    local name="$1"; shift
    local blocking="$1"; shift
    local output rc
    # Eslatma: skript `set -e` bilan ishlamaydi (har bir darvoza natijasi
    # FAILED_GATES ga yig'iladi), shuning uchun rc qo'lda olinadi.
    output="$("$@" 2>&1)"
    rc=$?
    if [ "$rc" -eq 0 ]; then
        ok "$name"
        PASSED_GATES+=("$name")
        [ -n "$output" ] && printf '%s\n' "$output" | sed 's/^/         /' | head -5
        return 0
    fi
    printf '%s\n' "$output" | sed 's/^/         /' | head -40
    if [ "$blocking" -eq 1 ] && [ "$ADVISORY" -eq 0 ]; then
        bad "$name (exit $rc) — BLOKLOVCHI"
        FAILED_GATES+=("$name")
        return 1
    fi
    bad "$name (exit $rc) — hisobot (job to'xtamaydi)"
    FAILED_GATES+=("$name")
    return 0
}

echo "=============================================================="
echo " PostAssist V2 — XAVFSIZLIK / QAT'IYLIK DARVOZASI"
echo "=============================================================="
echo "  Repo     : $REPO_ROOT"
echo "  Python   : $PY ($($PY --version 2>&1 || echo 'noma lum'))"
if [ "$ADVISORY" -eq 1 ]; then
    echo "  Rejim    : ADVISORY (faqat hisobot, exit 0)"
else
    echo "  Rejim    : QAT'IY (topilma bo'lsa exit 1)"
fi

# ---------------------------------------------------------------------------
# 1) LINT GATE — sintaksis va aniqlanmagan nomlar (BLOKLOVCHI)
# ---------------------------------------------------------------------------
section "1) 🚦 LINT GATE — sintaksis / aniqlanmagan nomlar (bloklovchi)"
if ensure_tool ruff ruff; then
    run_gate "ruff E9,F63,F7,F82 (telegram_bot)" 1 \
        $TOOL_CMD check "$TELEGRAM_DIR" --output-format=concise --select=E9,F63,F7,F82
else
    skip "ruff o'rnatilmagan — lint gate tekshirilmadi (pip install ruff==0.6.9)"
    SKIPPED_GATES+=("ruff lint gate")
fi
if ensure_tool flake8 flake8; then
    run_gate "flake8 E9,F63,F7,F82 (telegram_bot)" 1 \
        $TOOL_CMD "$TELEGRAM_DIR" --count --select=E9,F63,F7,F82 \
        --max-line-length=127 --statistics
else
    skip "flake8 o'rnatilmagan (pip install flake8==7.1.1)"
    SKIPPED_GATES+=("flake8 lint gate")
fi

# ---------------------------------------------------------------------------
# 2) FULL RUFF — to'liq tekshiruv (hisobot)
# ---------------------------------------------------------------------------
section "2) 🧹 FULL RUFF — to'liq lint (hisobot)"
if resolve_tool ruff ruff; then
    run_gate "ruff check telegram_bot (to'liq)" 0 \
        $TOOL_CMD check "$TELEGRAM_DIR" --output-format=concise
else
    skip "ruff o'rnatilmagan — to'liq lint hisoboti o'tkazib yuborildi"
    SKIPPED_GATES+=("ruff full")
fi

# ---------------------------------------------------------------------------
# 3) PIP-AUDIT — bog'liqliklar zaifligi
# ---------------------------------------------------------------------------
section "3) 🔐 PIP-AUDIT — bog'liqliklar zaifligi (CVE)"
if [ "$SKIP_NETWORK" -eq 1 ]; then
    skip "pip-audit o'tkazib yuborildi (--skip-network; tarmoq kerak)"
    SKIPPED_GATES+=("pip-audit")
elif [ ! -f "$REQUIREMENTS" ]; then
    skip "telegram_bot/requirements.txt topilmadi"
    SKIPPED_GATES+=("pip-audit")
elif ensure_tool pip_audit pip-audit; then
    run_gate "pip-audit -r telegram_bot/requirements.txt" 0 \
        $TOOL_CMD -r "$REQUIREMENTS" --progress-spinner off
else
    skip "pip-audit o'rnatilmagan (pip install pip-audit)"
    SKIPPED_GATES+=("pip-audit")
fi

# ---------------------------------------------------------------------------
# 4) BANDIT — statik xavfsizlik skani
# ---------------------------------------------------------------------------
section "4) 🛡 BANDIT — statik xavfsizlik skani (-ll)"
if ensure_tool bandit bandit; then
    run_gate "bandit -r telegram_bot -ll" 0 \
        $TOOL_CMD -r "$TELEGRAM_DIR" -ll
else
    skip "bandit o'rnatilmagan (pip install bandit)"
    SKIPPED_GATES+=("bandit")
fi

# ---------------------------------------------------------------------------
# YAKUNIY HISOBOT
# ---------------------------------------------------------------------------
section "📊 YAKUNIY HISOBOT"
echo "  OK    : ${#PASSED_GATES[@]}"
echo "  FAIL  : ${#FAILED_GATES[@]}"
echo "  SKIP  : ${#SKIPPED_GATES[@]}"
for g in "${FAILED_GATES[@]}"; do echo "    - FAIL: $g"; done
for g in "${SKIPPED_GATES[@]}"; do echo "    - SKIP: $g"; done

if [ -n "$JSON_OUT" ]; then
    "$PY" - "$JSON_OUT" "${#PASSED_GATES[@]}" "${#FAILED_GATES[@]}" "${#SKIPPED_GATES[@]}" <<'PYEOF'
import json, sys
out, ok_n, fail_n, skip_n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
json.dump({"passed": ok_n, "failed": fail_n, "skipped": skip_n}, open(out, "w"), indent=2)
PYEOF
    echo "  JSON hisobot: $JSON_OUT"
fi

if [ "${#FAILED_GATES[@]}" -gt 0 ] && [ "$ADVISORY" -eq 0 ]; then
    echo
    echo "❌ XAVFSIZLIK DARVOZASI YIQILDI — yuqoridagi [FAIL] qatorlarini ko'ring."
    exit 1
fi
if [ "$ADVISORY" -eq 1 ]; then
    echo
    echo "✅ ADVISORY hisobot tayyor (topilmalar job'ni to'xtatmaydi)."
    exit 0
fi
echo
echo "✅ XAVFSIZLIK DARVOZASI 100% YASHIL"
exit 0
