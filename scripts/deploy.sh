#!/usr/bin/env bash
# ============================================================================
# PostAssist V2 — 1-KOMANDALIK PRODUCTION DEPLOY (+ verification)
# ----------------------------------------------------------------------------
# Bitta buyruq bilan:
#
#   1) 🛫 PREFLIGHT   — .env to'liqligi va siyosat tekshiruvi;
#   2) 🗄 MIGRATION   — schema.sql idempotent qo'llanadi + schema check;
#   3) 🚀 START       — bot + web health-server + background workerlar
#                       (APScheduler) parallel ko'tariladi;
#   4) 🩺 HEALTH WAIT — `http://127.0.0.1:$PORT/health/live` 200 bo'lguncha
#                       kutadi (standart PORT=8080);
#   5) 🧪 SMOKE TEST  — `tests/smoke_test.py`: Telegram getMe, polling/
#                       webhook rejimi va /health/live + /health/ready JSON
#                       kontraktlari (natija `logs/` ga yoziladi);
#   6) 📊 REPORT      — yakuniy hisobot; xato bo'lsa bot to'xtatiladi.
#
# Keyin bot FOREGROUND'da qoladi (Ctrl-C → SIGTERM → graceful shutdown).
# Serverda 24/7 ishlatish uchun systemd/docker ishlatiladi (DEPLOYMENT.md,
# 7-bo'lim) — `deploy.sh --verify-only` esa faqat tekshirib chiqadi.
#
# ISHLATISH (repo ildizidan):
#     bash scripts/deploy.sh                       # deploy + verify + foreground
#     bash scripts/deploy.sh --verify-only         # tekshirib, botni to'xtatadi
#     bash scripts/deploy.sh --check-only          # preflight + HAQIQIY migratsiya (bot yo'q)
#     bash scripts/deploy.sh --no-smoke            # smoke testni o'tkazib yuborish
#
# EXIT: 0 — muvaffaqiyat; 1 — preflight/migratsiya/health/smoke xatosi.
# ============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${DEPLOY_ENV_FILE:-$REPO_ROOT/.env}"
DEFAULT_HEALTH_PORT=8080
STRICT="${DEPLOY_STRICT:-0}"
CHECK_ONLY=0
VERIFY_ONLY=0
RUN_SMOKE=1
OFFLINE_SMOKE=0
HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-60}"
SMOKE_TIMEOUT="${DEPLOY_SMOKE_TIMEOUT:-120}"

BOT_PID=""
STOPPED=0
LOG_DIR="$REPO_ROOT/logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/deploy-$STAMP.log"
SMOKE_JSON="$LOG_DIR/smoke-$STAMP.json"

log()  { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy][WARN] %s\n' "$*" >&2; }
die()  { printf '[deploy][ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
PostAssist V2 — 1-komandalik production deploy (+ verification)

  bash scripts/deploy.sh [opsiyalar]

Opsiyalar:
  --env-file FILE     Muhit fayli (standart: .env)
  --port N            Healthcheck porti (standart: PORT env yoki 8080)
  --strict            Preflight ogohlantirishlari ham to'xtatadi
  --check-only        Preflight + DB migratsiya (schema.sql qo'llaniladi);
                      bot ishga tushmaydi
  --verify-only       Botni ko'tarib tekshiradi va to'xtatadi (CI/staging uchun)
  --no-smoke          Smoke testni o'tkazib yuboradi
  --offline-smoke     Smoke testni faqat mock Telegram bilan (tashqi tarmoqsiz)
  --health-timeout N  /health/live kutish byudjeti, soniya (standart 60)
  --smoke-timeout N   Smoke test timeout'i, soniya (standart 120)
  -h | --help         Ushbu yordam

Muhit orqali: DEPLOY_ENV_FILE, DEPLOY_STRICT=1, DEPLOY_HEALTH_TIMEOUT,
DEPLOY_SMOKE_TIMEOUT, PORT, SHUTDOWN_GRACE_SECONDS.
EOF
}

PORT_OVERRIDE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --env-file)       ENV_FILE="${2:?--env-file uchun qiymat kerak}"; shift 2 ;;
        --port)           PORT_OVERRIDE="${2:?--port uchun qiymat kerak}"; shift 2 ;;
        --strict)         STRICT=1; shift ;;
        --check-only)     CHECK_ONLY=1; shift ;;
        --verify-only)    VERIFY_ONLY=1; shift ;;
        --no-smoke)       RUN_SMOKE=0; shift ;;
        --offline-smoke)  OFFLINE_SMOKE=1; shift ;;
        --health-timeout) HEALTH_TIMEOUT="${2:?--health-timeout uchun qiymat kerak}"; shift 2 ;;
        --smoke-timeout)  SMOKE_TIMEOUT="${2:?--smoke-timeout uchun qiymat kerak}"; shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        *) die "Noma'lum argument: $1 (--help ni ko'ring)" ;;
    esac
done

resolve_python() {
    if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ]; then printf '%s' "$PYTHON"; return 0; fi
    for candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/venv/bin/python" \
                     "$HOME/venv/bin/python" "$HOME/.venv/bin/python"; do
        if [ -x "$candidate" ]; then printf '%s' "$candidate"; return 0; fi
    done
    if command -v python3 >/dev/null 2>&1; then printf 'python3'; return 0; fi
    printf 'python'
}
PY="$(resolve_python)"
[ -n "$PY" ] || die "Python interpreter topilmadi."

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

# --- .env: deploy skriptining o'zi ham PORT/HEALTH tokenni ko'rishi kerak ----
if [ -f "$ENV_FILE" ]; then
    load_env_file "$ENV_FILE"
fi
if [ -n "$PORT_OVERRIDE" ]; then
    export PORT="$PORT_OVERRIDE"
elif [ -z "${PORT:-}" ]; then
    export PORT="$DEFAULT_HEALTH_PORT"
fi
HEALTH_URL="http://127.0.0.1:$PORT/health/live"

start_bot() {
    mkdir -p "$LOG_DIR"
    log "Botni fon rejimida ishga tushirish (log: $LOG_FILE)"
    bash "$REPO_ROOT/scripts/start_production.sh" \
        --env-file "$ENV_FILE" --skip-migrate >"$LOG_FILE" 2>&1 &
    BOT_PID=$!
    log "Bot PID=$BOT_PID"
}

stop_bot() {
    [ -n "$BOT_PID" ] || return 0
    [ "$STOPPED" = "1" ] && return 0
    STOPPED=1
    if kill -0 "$BOT_PID" 2>/dev/null; then
        local grace="${SHUTDOWN_GRACE_SECONDS:-15}"
        log "SIGTERM yuborilmoqda (graceful shutdown — delivery navbati + scheduler drenaji, ${grace}s)..."
        kill -TERM "$BOT_PID" 2>/dev/null || true
        local budget=$(( grace + 15 ))
        local waited=0
        while kill -0 "$BOT_PID" 2>/dev/null && [ "$waited" -lt "$budget" ]; do
            sleep 1
            waited=$(( waited + 1 ))
        done
        if kill -0 "$BOT_PID" 2>/dev/null; then
            warn "Bot ${budget}s ichida to'xtamadi — SIGKILL."
            kill -KILL "$BOT_PID" 2>/dev/null || true
        fi
    fi
    wait "$BOT_PID" 2>/dev/null || true
    log "Bot to'xtatildi (PID=$BOT_PID)."
}

on_signal() {
    log "Signal qabul qilindi — deploy to'xtatilmoqda..."
    stop_bot
    exit 0
}
trap on_signal INT TERM

tail_log() {
    if [ -f "$LOG_FILE" ]; then
        echo "----------------------------------- bot log (oxirgi 25 qator) ---"
        tail -n 25 "$LOG_FILE" || true
        echo "---------------------------------------------------------------"
    fi
}

wait_for_health() {
    local timeout="$1"
    log "Health kutilyapti: $HEALTH_URL (byudjet: ${timeout}s)"
    "$PY" - "$HEALTH_URL" "$timeout" "$BOT_PID" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

url, timeout, bot_pid = sys.argv[1], float(sys.argv[2]), sys.argv[3]
deadline = time.monotonic() + max(1.0, timeout)
last = "javob yo'q"
while time.monotonic() < deadline:
    if bot_pid and bot_pid != "0":
        try:
            import os
            os.kill(int(bot_pid), 0)
        except (OSError, ValueError):
            print("BOT_PROCESS_EXITED")
            sys.exit(2)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if resp.status == 200 and payload.get("status") == "live":
            print(f"LIVE (uptime={payload.get('uptime_seconds')}s)")
            sys.exit(0)
        last = f"HTTP {resp.status}: {payload}"
    except urllib.error.HTTPError as exc:
        last = f"HTTP {exc.code}"
    except Exception as exc:  # pragma: no cover — tarmoq kutilmoqda
        last = f"{type(exc).__name__}"
    time.sleep(1.0)
print(f"TIMEOUT: {last}")
sys.exit(1)
PY
}

# ============================================================================
# 1) PREFLIGHT + 2) MIGRATION (start_production.sh --migrate-only orqali)
# ============================================================================
log "1/5 PREFLIGHT + 2/5 DB MIGRASYON + SCHEMA CHECK"
# DIQQAT: bu yerda `--migrate-only` ishlatiladi (`--check-only` EMAS).
# `--check-only` read-only: db_migrate.py schemani YOZMAYDI — natijada YANGI
# (bo'sh) bazada schema check "yetishmayapti" deb yiqilardi va 1-komandalik
# deploy birinchi marta umuman ishlamasdi (P1 tuzatildi). `--migrate-only`
# esa preflight + HAQIQIY idempotent migratsiya + port tekshiruvini bajaradi
# va botni ishga tushirmaydi (uni deploy.sh o'zi ko'taradi).
CHECK_ARGS=(--migrate-only)
[ "$STRICT" = "1" ] && CHECK_ARGS+=(--strict)
bash "$REPO_ROOT/scripts/start_production.sh" --env-file "$ENV_FILE" "${CHECK_ARGS[@]}" \
    || die "Preflight/migratsiya bosqichi yiqildi — bot ishga tushirilmadi."

if [ "$CHECK_ONLY" = "1" ]; then
    log "✅ CHECK-ONLY yakunlandi — preflight + migratsiya (schema.sql qo'llanildi) bajarildi; bot ishga tushirilmadi."
    exit 0
fi

# ============================================================================
# 3) START (background) + 4) HEALTH WAIT
# ============================================================================
log "3/5 BOT START (fon rejimi)"
start_bot
sleep 1
if ! kill -0 "$BOT_PID" 2>/dev/null; then
    tail_log
    die "Bot darhol to'xtadi — logni ko'ring ($LOG_FILE)."
fi

log "4/5 HEALTH CHECK (liveness)"
if ! HEALTH_STATUS="$(wait_for_health "$HEALTH_TIMEOUT")"; then
    tail_log
    stop_bot
    die "Liveness tekshiruvi muvaffaqiyatsiz: $HEALTH_STATUS"
fi
log "✅ /health/live → $HEALTH_STATUS"

# ============================================================================
# 5) SMOKE TEST (Telegram + health endpointlari)
# ============================================================================
SMOKE_STATUS="SKIPPED"
if [ "$RUN_SMOKE" = "1" ]; then
    SMOKE_ARGS=(--base-url "http://127.0.0.1:$PORT"
                --wait-health "$HEALTH_TIMEOUT"
                --timeout "$SMOKE_TIMEOUT"
                --json "$SMOKE_JSON")
    [ "$OFFLINE_SMOKE" = "1" ] && SMOKE_ARGS+=(--offline)
    log "5/5 SMOKE TEST (rt: tests/smoke_test.py, hisobot: $SMOKE_JSON)"
    if "$PY" "$REPO_ROOT/tests/smoke_test.py" "${SMOKE_ARGS[@]}"; then
        SMOKE_STATUS="OK"
    else
        SMOKE_STATUS="FAILED"
        tail_log
        stop_bot
        die "Smoke test yiqildi — bot to'xtatildi ($SMOKE_JSON)."
    fi
else
    log "5/5 SMOKE TEST o'tkazib yuborildi (--no-smoke)."
fi

# ============================================================================
# REPORT
# ============================================================================
if [ "$VERIFY_ONLY" = "1" ]; then
    REJIM="VERIFY-ONLY (bot to'xtatiladi)"
else
    REJIM="FOREGROUND (Ctrl-C -> graceful shutdown)"
fi
cat <<EOF

============================================================================
 ✅ DEPLOY VERIFICATION YAKUNLANDI
----------------------------------------------------------------------------
  Port        : $PORT
  Health      : $HEALTH_URL
  Bot PID     : $BOT_PID
  Bot log     : $LOG_FILE
  Smoke test  : $SMOKE_STATUS$([ "$RUN_SMOKE" = "1" ] && printf ' (%s)' "$SMOKE_JSON")
  Rejim       : ${REJIM}
============================================================================
EOF

if [ "$VERIFY_ONLY" = "1" ]; then
    stop_bot
    log "✅ VERIFY-ONLY OK — bot to'xtatildi, xato yo'q."
    exit 0
fi

log "Bot ishlayapti (PID=$BOT_PID). To'xtatish: Ctrl-C yoki SIGTERM (graceful)."
EXIT_CODE=0
wait "$BOT_PID" || EXIT_CODE=$?
log "Bot tugadi (exit=$EXIT_CODE)."
exit "$EXIT_CODE"
