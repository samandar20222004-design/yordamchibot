#!/usr/bin/env bash
# ============================================================================
# PostAssist V2 — PRODUCTION START (entrypoint & bootstrap)
# ----------------------------------------------------------------------------
# Botni PRODUCTION tartibida ishga tushiradi:
#
#   1) 📄 .env ni yuklaydi (bo'lmasa — jarayon muhiti ishlatiladi);
#   2) 🛫 PREFLIGHT — muhit to'liqligi va siyosat tekshiruvi
#      (BOT_TOKEN, DATABASE_URL, REDIS_URL, HEALTH_READY_TOKEN, ENVIRONMENT,
#       AI_ALLOW_MOCK, PORT, ADMIN, AI provayderlar, DB pool);
#   3) 🗄 SAFE MIGRATION — schema.sql IDEMPOTENT qo'llanadi + schema check
#      (scripts/db_migrate.py; baza "cold start"da retry bilan kutadi);
#   4) 🚀 Botni ishga tushiradi (`telegram_bot/main.py`) — u O'ZI:
#        • web health-serverni 0.0.0.0:$PORT da ochadi (/health/live, /health/ready),
#        • Telegram pollingni boshlaydi,
#        • APScheduler background workerlarini ko'taradi (postlarni yuborish,
#          tozalash, RSS manbalar, obuna sweep, haftalik hisobot).
#
# 8080: PORT berilmagan bo'lsa healthcheck/self-hosted standart port 8080
# olinadi (Render o'z PORT'ini beradi — u ustuvor). Docker image'da ham
# HEALTHCHECK aynan shu PORT'ni tekshiradi.
#
# ISHLATISH (repo ildizidan):
#     cp .env.example .env && nano .env      # BOT_TOKEN, DATABASE_URL, ...
#     bash scripts/start_production.sh                    # preflight → migratsiya → bot
#     bash scripts/start_production.sh --check-only       # faqat tekshiruv (bot yo'q)
#     bash scripts/start_production.sh --skip-migrate     # migratsiyasiz start
#     PORT=8080 bash scripts/start_production.sh          # portni majburan berish
#
# EXIT: 0 — toza yopilish / tekshiruv OK; 1 — preflight yoki migratsiya xatosi.
# ============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${DEPLOY_ENV_FILE:-$REPO_ROOT/.env}"
DEFAULT_HEALTH_PORT=8080
STRICT="${DEPLOY_STRICT:-0}"
SKIP_MIGRATE=0
CHECK_ONLY=0
VALIDATE_INTEGRITY=0
MIGRATE_RETRIES="${DEPLOY_MIGRATE_RETRIES:-5}"
MIGRATE_RETRY_DELAY="${DEPLOY_MIGRATE_RETRY_DELAY:-3}"
PORT_OVERRIDE=""

log()  { printf '[bootstrap] %s\n' "$*" >&2; }
warn() { printf '[bootstrap][WARN] %s\n' "$*" >&2; }
die()  { printf '[bootstrap][ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
PostAssist V2 — production start (entrypoint & bootstrap)

  bash scripts/start_production.sh [opsiyalar]

Opsiyalar:
  --env-file FILE        Muhit fayli (standart: .env)
  --port N               Healthcheck/ilova porti (standart: PORT env yoki 8080)
  --strict               Preflight ogohlantirishlari ham to'xtatadi
  --skip-migrate         DB migratsiya/schema check bosqichini o'tkazib yuboradi
  --check-only           Faqat preflight + migratsiya; bot ISHGA TUSHMAYDI
  --validate-integrity   NOT VALID constraintlarni VALIDATE qiladi (qulf bo'lishi mumkin)
  --migrate-retries N    Baza ulanish urinishlari (standart 5)
  -h | --help            Ushbu yordam

Muhit orqali: DEPLOY_ENV_FILE, DEPLOY_STRICT=1, DEPLOY_MIGRATE_RETRIES,
DEPLOY_MIGRATE_RETRY_DELAY, PYTHON (interpreter yo'li), PORT.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --env-file)         ENV_FILE="${2:?-env-file uchun qiymat kerak}"; shift 2 ;;
        --port)             PORT_OVERRIDE="${2:?--port uchun qiymat kerak}"; shift 2 ;;
        --strict)           STRICT=1; shift ;;
        --skip-migrate)     SKIP_MIGRATE=1; shift ;;
        --check-only)       CHECK_ONLY=1; shift ;;
        --validate-integrity) VALIDATE_INTEGRITY=1; shift ;;
        --migrate-retries)  MIGRATE_RETRIES="${2:?--migrate-retries uchun qiymat kerak}"; shift 2 ;;
        -h|--help)          usage; exit 0 ;;
        *) die "Noma'lum argument: $1 (--help ni ko'ring)" ;;
    esac
done

# --- 0) Python interpreter --------------------------------------------------
resolve_python() {
    if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ]; then
        printf '%s' "$PYTHON"; return 0
    fi
    if [ -n "${PYTHON:-}" ]; then
        warn "PYTHON='$PYTHON' topilmadi/bajarilmaydi — avtomatik fallback."
    fi
    for candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/venv/bin/python" \
                     "$HOME/venv/bin/python" "$HOME/.venv/bin/python"; do
        if [ -x "$candidate" ]; then printf '%s' "$candidate"; return 0; fi
    done
    if command -v python3 >/dev/null 2>&1; then printf 'python3'; return 0; fi
    printf 'python'
}
PY="$(resolve_python)"
[ -n "$PY" ] || die "Python interpreter topilmadi (PYTHON env bilan bering)."

# --- 1) .env yuklash ---------------------------------------------------------
# `.env` ni XAVFSIZ yuklaydi (sourcing EMAS): qiymatlardagi bo'shliqlar
# (masalan `AUTOPILOT_QUIET_HOURS=23:00 - 08:00`) va qo'shtirnoqlar to'g'ri
# ishlanadi; `eval` ishlatilmaydi (in'yeksiya yo'q). Izohlar va noto'g'ri
# qatorlar o'tkazib yuboriladi.
load_env_file() {
    local file="$1" line key value
    [ -f "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            ''|'#'*) continue ;;
        esac
        case "$line" in
            export\ *) line="${line#export }" ;;
        esac
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac
        key="${line%%=*}"
        value="${line#*=}"
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            ''|*[!A-Za-z0-9_]*) continue ;;
        esac
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
            *) value="${value%% #*}" ;;
        esac
        printf -v "$key" '%s' "$value" 2>/dev/null || continue
        export "$key"
    done < "$file"
}

if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
    log ".env yuklanmoqda: $ENV_FILE"
    load_env_file "$ENV_FILE"
else
    warn "Muhit fayli topilmadi ($ENV_FILE) — jarayon muhiti ishlatiladi."
fi

# --- 2) Standart qiymatlar ---------------------------------------------------
# Self-hosted (VPS/Docker) uchun healthcheck porti: 8080. Render PORT'ni
# o'zi beradi — berilgan qiymat HECH QACHON ustidan yozilmaydi.
if [ -n "$PORT_OVERRIDE" ]; then
    export PORT="$PORT_OVERRIDE"
elif [ -z "${PORT:-}" ]; then
    export PORT="$DEFAULT_HEALTH_PORT"
    log "PORT berilmagan — healthcheck porti $PORT (self-hosted standart)."
fi
export PYTHONPATH="$REPO_ROOT/telegram_bot${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

log "Python: $($PY --version 2>&1 || echo '?') ($PY)"
log "Ilova porti (healthcheck): $PORT"

# --- 3) PREFLIGHT: muhit to'liqligi va siyosat ------------------------------
PREFLIGHT_ARGS=(--env-file "$ENV_FILE")
if [ "$STRICT" = "1" ]; then
    PREFLIGHT_ARGS+=(--strict)
fi
log "1/3 PREFLIGHT — muhit to'liqligi va xavfsizlik siyosati tekshirilmoqda..."
if ! "$PY" "$REPO_ROOT/scripts/preflight_env.py" "${PREFLIGHT_ARGS[@]}"; then
    die "Preflight yiqildi — .env ni to'ldiring yoki (ataylab bo'lsa) --strict olib tashlang."
fi

# --- 4) SAFE MIGRATION + SCHEMA CHECK ---------------------------------------
if [ "$SKIP_MIGRATE" = "1" ]; then
    log "2/3 MIGRASIYA o'tkazib yuborildi (--skip-migrate)."
else
    MIGRATE_ARGS=(--env-file "$ENV_FILE"
                  --retries "$MIGRATE_RETRIES"
                  --retry-delay "$MIGRATE_RETRY_DELAY")
    if [ "$CHECK_ONLY" = "1" ]; then
        MIGRATE_ARGS+=(--check-only)
    fi
    if [ "$VALIDATE_INTEGRITY" = "1" ]; then
        MIGRATE_ARGS+=(--validate-integrity)
    fi
    log "2/3 DB MIGRATSIYA + SCHEMA CHECK — schema.sql idempotent qo'llanadi..."
    if ! "$PY" "$REPO_ROOT/scripts/db_migrate.py" "${MIGRATE_ARGS[@]}"; then
        die "Migratsiya/sxema tekshiruvi yiqildi — baza holatini ko'ring."
    fi
fi

# --- 5) CHECK-ONLY: port bandligini ham tekshiramiz ------------------------
if [ "$CHECK_ONLY" = "1" ]; then
    if "$PY" - "$PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
sys.exit(0)
PY
    then
        log "3/3 Port $PORT bo'sh — start uchun tayyor."
    else
        warn "Port $PORT BAND (boshqa instance ishlayapti?) — startda bind xatosi bo'ladi."
    fi
    log "✅ CHECK-ONLY OK — preflight va migratsiya o'tdi, bot ishga tushirilmadi."
    exit 0
fi

# --- 6) BOT START -----------------------------------------------------------
# main.py o'zi: web health-server (0.0.0.0:$PORT) → Telegram polling →
# APScheduler background workerlar → graceful shutdown (SIGTERM/SIGINT).
log "3/3 BOT ishga tushirilmoqda (main.py) — web /health/live:$PORT, polling va"
log "     background workerlar (scheduler) parallel ko'tariladi..."
exec "$PY" "$REPO_ROOT/telegram_bot/main.py"
