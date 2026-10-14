"""Real PostgreSQL URL'ini topish (test yordamchisi): muhit o'zgaruvchisi, bo'lmasa `pgserver` (CI).

Production bazaga HECH QACHON ulanmaydi: faqat aniq nomli *_TEST_DATABASE_URL yoki vaqtincha lokal pgserver.
`pgserver` o'rnatilmagan (yoki root sifatida ishga tushmaydigan) bo'lsa bo'sh satr qaytadi -> test SKIP/BLOCKED.
"""
from __future__ import annotations

import os
import tempfile


def real_pg_url(*env_names: str, server_dir: str = "yordamchi_pg_shared") -> str:
    for name in env_names:
        value = os.getenv(name, "")
        if value and "user:pass" not in value:
            return value
    try:
        import pgserver
    except ImportError:
        return ""
    try:
        server = pgserver.get_server(os.path.join(tempfile.gettempdir(), server_dir))
        return server.get_uri()
    except Exception:  # noqa: BLE001 — muhit (root, ruxsat) pgserver'ni ishga tushira olmasligi mumkin
        return ""
