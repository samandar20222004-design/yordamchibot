#!/usr/bin/env bash
# Compatibility shim: yagona test suite repo ildizidagi tests/run_tests.sh da.
# CI (working-directory: telegram_bot) va eski yo'llar shu yerda qoladi.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
exec bash tests/run_tests.sh
