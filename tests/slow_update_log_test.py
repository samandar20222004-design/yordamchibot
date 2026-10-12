"""«Sekin javob» logi (main._log_if_slow): faqat sekin update'lar yoziladi,
foydalanuvchi yozgan matn esa logga tushmaydi."""
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import main  # noqa: E402

failures = 0


def check(name, cond, extra=""):
    global failures
    print(f"  [{'OK' if cond else 'FAIL'}] {name} {'' if cond else extra}")
    failures += 0 if cond else 1


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _update(text=None, data=None):
    user = SimpleNamespace(id=42)
    query = SimpleNamespace(data=data) if data is not None else None
    message = SimpleNamespace(text=text) if text is not None else None
    return SimpleNamespace(callback_query=query, effective_message=message, effective_user=user)


def run(update, elapsed):
    cap = _Capture()
    main.logger.addHandler(cap)
    try:
        main._log_if_slow(update, elapsed)
    finally:
        main.logger.removeHandler(cap)
    return cap.lines


def test():
    print("== Sekin javob logi ==")
    limit = main.SLOW_UPDATE_SECONDS
    check("tez update logga yozilmaydi", run(_update(text="salom"), limit / 2) == [])

    secret = "parolim 12345 karta 8600"
    lines = run(_update(text=secret), limit + 1)
    check("sekin update logga yoziladi", len(lines) == 1, str(lines))
    check("foydalanuvchi matni logga tushmaydi",
          lines and "parolim" not in lines[0] and "8600" not in lines[0], str(lines))
    check("matn uzunligi ko'rsatiladi", lines and f"{len(secret)} belgi" in lines[0], str(lines))

    lines = run(_update(text="/start ref_99"), limit + 1)
    check("buyruq nomi yoziladi, argumenti yo'q",
          lines and "'/start'" in lines[0] and "ref_99" not in lines[0], str(lines))

    lines = run(_update(data="qdel:123:ok"), limit + 1)
    check("tugma faqat prefiks bilan yoziladi",
          lines and "'qdel'" in lines[0] and "123" not in lines[0], str(lines))


if __name__ == "__main__":
    test()
    print(f"JAMI xato: {failures}")
    sys.exit(1 if failures else 0)
