"""`/start` yuklash animatsiyasi: yuboriladi, javobdan keyin o'chadi, xato /start ni buzmaydi."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "telegram_bot"))
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")

from services import start_splash as sp  # noqa: E402

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [XATO] {name}")


class Sent:
    def __init__(self, fid="FID1", delete_error=False):
        self.animation = type("A", (), {"file_id": fid})()
        self.deleted = False
        self._err = delete_error

    async def delete(self):
        if self._err:
            raise RuntimeError("o'chirib bo'lmadi")
        self.deleted = True


class Msg:
    def __init__(self, error=False, slow=False):
        self.calls = []
        self.error, self.slow = error, slow

    async def reply_animation(self, animation=None, **kw):
        self.calls.append(animation)
        if self.error:
            raise RuntimeError("Forbidden")
        if self.slow:
            await asyncio.sleep(30)
        return Sent()


def run(c):
    return asyncio.run(c)


print("== /start yuklash animatsiyasi ==")
check("GIF fayl mavjud va GIF sarlavhali", sp.SPLASH_PATH.is_file() and sp.SPLASH_PATH.read_bytes()[:3] == b"GIF")
check("GIF hajmi 1 MB dan kichik", sp.SPLASH_PATH.stat().st_size < 1_000_000)

m = Msg()
sent = run(sp.send_splash(m))
check("birinchi yuborish: fayl ochiq obyekt sifatida", sent is not None and len(m.calls) == 1 and hasattr(m.calls[0], "read"))
check("file_id keshlandi", sp._file_id == "FID1")
m2 = Msg()
run(sp.send_splash(m2))
check("keyingi yuborish: keshlangan file_id (qayta yuklash yo'q)", m2.calls == ["FID1"])

run(sp.remove_splash(sent))
check("animatsiya o'chirildi", sent.deleted)
run(sp.remove_splash(None))
run(sp.remove_splash(Sent(delete_error=True)))
check("o'chirishda xato / None: istisno yo'q", True)

sp._file_id = None
check("yuborish xatosi: None, istisno yo'q", run(sp.send_splash(Msg(error=True))) is None)
sp.SEND_TIMEOUT_SECONDS = 0.05
sp._file_id = "FID1"
import time  # noqa: E402
t = time.time()
check("sekin yuborish: vaqt bilan kesiladi (None)", run(sp.send_splash(Msg(slow=True))) is None and time.time() - t < 2)
check("message=None yoki reply_animation yo'q: None", run(sp.send_splash(None)) is None and run(sp.send_splash(object())) is None)

os.environ["START_SPLASH"] = "0"
m3 = Msg()
check("START_SPLASH=0: umuman yuborilmaydi", run(sp.send_splash(m3)) is None and m3.calls == [])
del os.environ["START_SPLASH"]

import inspect  # noqa: E402
import importlib  # noqa: E402
st = importlib.import_module("handlers.start")
src = inspect.getsource(sys.modules["handlers.start"].start)
check("start(): animatsiya yuboriladi va finally'da o'chiriladi", "send_splash" in src and "finally" in src and "remove_splash" in src)

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(1 if failed else 0)
