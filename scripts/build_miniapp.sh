#!/usr/bin/env bash
# ============================================================================
# Mini App frontend build (IXTIYORIY qadam; botning ishga tushishiga bog'liq emas)
#
#   bash scripts/build_miniapp.sh        # miniapp/dist ni quradi (npm ci + npm run build)
#
# Docker image'da build Dockerfile'ning `miniapp-build` stage'ida avtomatik bajariladi.
# Render Native Python / VPS uchun shu skriptni Build Command'ga qo'shish mumkin:
#     pip install -r requirements.txt && bash ../scripts/build_miniapp.sh
# (Root Directory = telegram_bot bo'lsa ham repozitoriy to'liq klon qilinishi kerak —
#  `../miniapp` mavjudligini tekshiring; bo'lmasa MINIAPP_DIST_DIR bilan build qilingan
#  papkani ko'rsating.) Node >= 22.12 kerak (build uchun; testlar jsdom tufayli >= 22.22.2). MINIAPP_ENABLED=0 bo'lsa dist umuman ishlatilmaydi.
# EXIT: 0 — dist tayyor; 1 — node yo'q yoki build xatosi.
# ============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v node >/dev/null 2>&1 || { echo "[miniapp-build][ERROR] node topilmadi (Node >= 22.12 kerak)" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "[miniapp-build][ERROR] npm topilmadi" >&2; exit 1; }

cd "$ROOT/miniapp"
echo "[miniapp-build] node $(node -v), npm $(npm -v)"
npm ci --no-audit --no-fund
npm run build
echo "[miniapp-build] OK: $ROOT/miniapp/dist"
