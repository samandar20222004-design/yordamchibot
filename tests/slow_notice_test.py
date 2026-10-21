#!/usr/bin/env python3
"""Jim qolma: bot ~2 s javob bermasa «⏳ tahlil qilinmoqda» yozuvi chiqadi va handler tugagach o'chadi (DB'siz)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


from utils import slow_notice as sn  # noqa: E402
from locales.translations import get_text  # noqa: E402


class FakeBot:
    def __init__(self):
        self.sent, self.deleted, self.actions = [], [], []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=77)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_chat_action(self, chat_id, action):
        self.actions.append((chat_id, action))


def upd(chat_type="private", cb=False):
    chat = SimpleNamespace(id=5, type=chat_type)
    return SimpleNamespace(effective_chat=chat, message=None if cb else object(),
                           callback_query=object() if cb else None)


async def lang(_u):
    return "ru"


async def run(work, update=None, delay=0.1):
    bot = FakeBot()
    task, token = sn.start(update or upd(), bot, lang, delay)
    await work(bot)
    await sn.stop(task, token)
    return bot


async def main():
    async def fast(bot):
        await asyncio.sleep(0.01)
    b = await run(fast)
    check("tez handler: yozuv chiqmaydi", not b.sent and not b.deleted)

    async def slow(bot):
        await asyncio.sleep(0.4)
    b = await run(slow)
    check("sekin handler: yozuv chiqdi (ruscha)", b.sent == [(5, get_text("sys_working_notice", "ru"))], str(b.sent))
    check("«yozmoqda» holati yuborildi", b.actions == [(5, "typing")])
    check("handler tugagach yozuv o'chdi", b.deleted == [(5, 77)], str(b.deleted))

    async def slow_reply(bot):
        sn._STATE.get().responded = True  # handler o'zi javob yubordi
        await asyncio.sleep(0.4)
    b = await run(slow_reply)
    check("handler o'zi javob bergan bo'lsa yozuv chiqmaydi", not b.sent)

    b = await run(slow, update=upd("group"))
    check("guruhda yozuv chiqmaydi", not b.sent)
    b = await run(slow, update=upd(cb=True))
    check("tugma bosilganda ham chiqadi", len(b.sent) == 1)
    task, token = sn.start(upd(), FakeBot(), lang, 0)
    check("delay=0 o'chiradi", task is None and token is None)

    # Bot._post kuzatuvchisi: ko'rinadigan metod javob hisoblanadi, chat action emas
    calls = []

    async def fake_post(self, endpoint, data=None, *a, **k):
        calls.append(endpoint)
        return True
    sn.Bot._post = sn._ORIGINAL_POST  # kuzatuvchini olib tashlab, qayta o'rnatamiz
    sn._INSTALLED = False
    sn._ORIGINAL_POST = fake_post
    sn._install()
    bot = SimpleNamespace()
    st = sn._State(5)
    tok = sn._STATE.set(st)
    await sn.Bot._post(bot, "sendChatAction", {"chat_id": 5})
    check("sendChatAction javob hisoblanmaydi", not st.responded)
    await sn.Bot._post(bot, "answerCallbackQuery", {})
    check("answerCallbackQuery javob hisoblanmaydi", not st.responded)
    await sn.Bot._post(bot, "sendMessage", {"chat_id": 9})
    check("boshqa chatga yuborish hisoblanmaydi", not st.responded)
    await sn.Bot._post(bot, "editMessageText", {"chat_id": 5})
    check("editMessageText javob hisoblanadi", st.responded)
    sn._STATE.reset(tok)

    for lg in ("uz", "ru", "en"):
        check(f"matn {lg}", get_text("sys_working_notice", lg).startswith("⏳"))

asyncio.run(main())
print(f"\n{passed} OK, {failed} XATO")
sys.exit(1 if failed else 0)
