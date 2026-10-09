#!/usr/bin/env python3
"""AI drafting progress — localized stages under Telegram's edit rate limit.

Covers ``services.ai.progress.AIProgressReporter``:
  1) localized stage sets (post + analysis) for uz/ru/en;
  2) stages only advance while the AI call is still running (fast answers
     cost zero extra API calls);
  3) **≤ 1 edit per second** — per message AND per chat (shared clock), also
     across two concurrent generations in the same chat;
  4) 429 ``RetryAfter`` → stage skipped and chat blocked; "message is not
     modified" → harmless; arbitrary edit errors never fail generation;
  5) helpers ``for_reply`` / ``for_callback`` (incl. fallback to ONE reply);
  6) end-to-end: the Post Score "improve" handler shows 🧠 → ✍️ → result with
     every edit ≥ 1.05 s apart; static guard: no handler keeps the old
     hard-coded Uzbek placeholder.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

REPO = Path(__file__).resolve().parent.parent
BOT_ROOT = REPO / "telegram_bot"
sys.path.insert(0, str(BOT_ROOT))

from telegram.error import BadRequest, RetryAfter  # noqa: E402

from services.ai.progress import (  # noqa: E402
    AI_ANALYSIS_STAGES,
    AI_PROGRESS_STAGES,
    CHAT_EDIT_CLOCK,
    MIN_EDIT_INTERVAL_FLOOR,
    AIProgressReporter,
    ChatEditClock,
    progress_stages,
)

PASSED = 0
FAILED = 0
FLOOR = MIN_EDIT_INTERVAL_FLOOR - 0.01  # scheduler jitter tolerance


def check(label: str, condition, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILED += 1
        print(f"  [XATO] {label}" + (f" — {detail}" if detail else ""))


def gaps(times):
    return [b - a for a, b in zip(times, times[1:])]


class Recorder:
    """Editor double that records (monotonic time, text)."""

    def __init__(self, fail_with=None):
        self.calls: list[tuple[float, str]] = []
        self.fail_with = list(fail_with or [])

    async def __call__(self, text, **kwargs):
        if self.fail_with:
            exc = self.fail_with.pop(0)
            if exc is not None:
                raise exc
        self.calls.append((time.monotonic(), text))

    @property
    def texts(self):
        return [t for _, t in self.calls]

    @property
    def times(self):
        return [t for t, _ in self.calls]


async def slow(value, seconds):
    await asyncio.sleep(seconds)
    return value


# ---------------------------------------------------------------------------
def test_stage_texts():
    print("\n== 1) Lokalizatsiya qilingan bosqichlar ==")
    check("talab qilingan o'zbekcha matnlar",
          AI_PROGRESS_STAGES["uz"] == ("🧠 Mavzu tahlil qilinmoqda...", "✍️ Post yozilmoqda...",
                                       "✨ Emojilar va sayqal berilmoqda..."))
    for lang in ("uz", "ru", "en"):
        check(f"post + analysis bosqichlari 3 tadan ({lang})",
              len(AI_PROGRESS_STAGES[lang]) == 3 and len(AI_ANALYSIS_STAGES[lang]) == 3)
        check(f"bosqichlar o'zaro farqli ({lang})", len(set(AI_PROGRESS_STAGES[lang])) == 3)
    check("ru-RU → ru, noma'lum → uz", progress_stages("ru-RU") == AI_PROGRESS_STAGES["ru"]
          and progress_stages("de") == AI_PROGRESS_STAGES["uz"])
    check("kind='analysis'", progress_stages("en", "analysis") == AI_ANALYSIS_STAGES["en"])
    check("noma'lum kind → post", progress_stages("en", "zzz") == AI_PROGRESS_STAGES["en"])
    check("minimal interval 1 soniyadan kam bo'lolmaydi",
          AIProgressReporter(minimum_edit_interval=0.01).minimum_edit_interval >= 1.0)
    check("stage interval hech qachon edit intervalidan kichik emas",
          AIProgressReporter(stage_interval=0.1).stage_interval >= MIN_EDIT_INTERVAL_FLOOR)


def test_stage_progression_and_rate_limit():
    print("\n== 2) Bosqichlar faqat AI ishlayotganda o'zgaradi, ≤1 edit/s ==")
    CHAT_EDIT_CLOCK.clear()

    async def fast():
        rec = Recorder()
        rep = AIProgressReporter(rec, "uz", initial_displayed=True, chat_id=1001)
        result = await rep.run(slow("ok", 0.05))
        return result, rec

    result, rec = asyncio.run(fast())
    check("tez javob → natija qaytadi", result == "ok")
    check("tez javob → 0 ta qo'shimcha edit (initial yuborilgan)", rec.calls == [], str(rec.texts))

    async def long_run():
        rec = Recorder()
        rep = AIProgressReporter(rec, "ru", stage_interval=1.1, chat_id=1002)
        started = time.monotonic()
        result = await rep.run(slow({"post_text": "x"}, 2.6))
        await rep.finish()
        await rec("FINAL")  # the handler's result edit
        return result, rec, started, rep

    result, rec, started, rep = asyncio.run(long_run())
    stages = AI_PROGRESS_STAGES["ru"]
    check("uzun javob → 3 bosqich + natija ketma-ket",
          rec.texts == [stages[0], stages[1], stages[2], "FINAL"], str(rec.texts))
    check("har bir edit oralig'i ≥ 1.05 s (natija edit'i ham)",
          all(g >= FLOOR for g in gaps(rec.times)), str([round(g, 3) for g in gaps(rec.times)]))
    check("1-bosqich darhol ko'rinadi", rec.times[0] - started < 0.2)
    check("edit_count hisoblanadi", rep.edit_count == 3)

    async def cancelled():
        rec = Recorder()
        rep = AIProgressReporter(rec, "en", initial_displayed=True)
        inner = asyncio.ensure_future(slow("never", 30))
        runner = asyncio.ensure_future(rep.run(inner))
        await asyncio.sleep(0.05)
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        return inner.cancelled()

    check("handler bekor qilinsa AI vazifasi ham bekor qilinadi", asyncio.run(cancelled()))

    async def failing_op():
        rep = AIProgressReporter(Recorder(), "uz", initial_displayed=True)

        async def boom():
            raise ValueError("ai down")

        try:
            await rep.run(boom())
        except ValueError:
            return True
        return False

    check("AI xatosi chaqiruvchiga o'zgarishsiz uzatiladi", asyncio.run(failing_op()))


def test_shared_chat_clock():
    print("\n== 3) Bitta chatda parallel generatsiyalar — umumiy edit soati ==")
    CHAT_EDIT_CLOCK.clear()
    timeline: list[tuple[float, str]] = []

    class Shared(Recorder):
        async def __call__(self, text, **kwargs):
            await super().__call__(text, **kwargs)
            timeline.append((time.monotonic(), text))

    async def scenario():
        a = AIProgressReporter(Shared(), "uz", stage_interval=1.1, chat_id=2001)
        b = AIProgressReporter(Shared(), "en", stage_interval=1.1, chat_id=2001)
        await asyncio.gather(a.run(slow(1, 2.5)), b.run(slow(2, 2.5)))
        return a, b

    a, b = asyncio.run(scenario())
    times = sorted(t for t, _ in timeline)
    check("ikki reporter ham edit qildi", a.edit_count >= 1 and b.edit_count >= 1,
          f"{a.edit_count}/{b.edit_count}")
    check("chat bo'yicha barcha edit'lar ≥ 1.05 s oralig'ida",
          all(g >= FLOOR for g in gaps(times)), str([round(g, 3) for g in gaps(times)]))
    span = (times[-1] - times[0]) if len(times) > 1 else 0.0
    check("edit'lar to'planmaydi: soni ≤ davomiylik/1.05 + 1",
          len(times) <= int(span / MIN_EDIT_INTERVAL_FLOOR) + 1, f"{len(times)} edits / {span:.2f}s")

    async def other_chat():
        CHAT_EDIT_CLOCK.clear()
        r1, r2 = Recorder(), Recorder()
        a = AIProgressReporter(r1, "uz", chat_id=3001)
        b = AIProgressReporter(r2, "uz", chat_id=3002)
        await a.begin()
        await b.begin()
        return r1.times[0], r2.times[0]

    t1, t2 = asyncio.run(other_chat())
    check("turli chatlar bir-birini kutmaydi", abs(t2 - t1) < 0.5)

    clock = ChatEditClock(max_chats=3)
    for chat in range(10):
        clock.push(chat, 100.0 + chat)
    check("chat soati chegaralangan (LRU, xotira o'smaydi)",
          clock.next_allowed(0) == 0.0 and clock.next_allowed(9) == 109.0)
    clock.push(9, 50.0)
    check("soat orqaga surilmaydi (max)", clock.next_allowed(9) == 109.0)
    check("chat_id=None → cheklov yo'q", clock.next_allowed(None) == 0.0)


def test_flood_and_errors():
    print("\n== 4) 429 RetryAfter / not modified / boshqa xatolar ==")
    CHAT_EDIT_CLOCK.clear()

    async def flood():
        rec = Recorder(fail_with=[None, RetryAfter(3)])
        rep = AIProgressReporter(rec, "uz", stage_interval=1.1, chat_id=4001, max_finish_wait=0.3)
        result = await rep.run(slow("done", 2.4))
        before_finish = time.monotonic()
        await rep.finish()
        return result, rec, rep, time.monotonic() - before_finish

    result, rec, rep, waited = asyncio.run(flood())
    check("RetryAfter generatsiyani buzmaydi", result == "done")
    check("RetryAfter dan keyin bloklangan oynada edit yo'q",
          rec.texts == [AI_PROGRESS_STAGES["uz"][0]], str(rec.texts))
    check("o'tkazib yuborilgan bosqichlar hisoblanadi", rep.skipped_edits >= 2, str(rep.skipped_edits))
    check("chat soati RetryAfter bilan bloklandi",
          CHAT_EDIT_CLOCK.next_allowed(4001) > time.monotonic())
    check("finish() kutishi max_finish_wait bilan cheklangan", waited <= 0.6, f"{waited:.2f}s")

    class TDRetry(Exception):
        retry_after = timedelta(seconds=2)

    async def timedelta_retry():
        rep = AIProgressReporter(Recorder(fail_with=[TDRetry()]), "uz", chat_id=4002)
        await rep.begin()
        return CHAT_EDIT_CLOCK.next_allowed(4002) - time.monotonic()

    remaining = asyncio.run(timedelta_retry())
    check("PTB v22 timedelta retry_after ham qo'llab-quvvatlanadi", 1.5 < remaining <= 2.1, f"{remaining:.2f}")

    async def not_modified():
        rec = Recorder(fail_with=[BadRequest("Message is not modified: specified new message content...")])
        rep = AIProgressReporter(rec, "uz")
        await rep.begin()
        return rep

    rep = asyncio.run(not_modified())
    check("'message is not modified' → muvaffaqiyat (qayta urinish yo'q)",
          rep.last_text == AI_PROGRESS_STAGES["uz"][0] and rep.last_edit_at is not None)

    async def generic_error():
        rec = Recorder(fail_with=[RuntimeError("network"), RuntimeError("network")])
        rep = AIProgressReporter(rec, "uz")
        await rep.begin()
        failed_once = rep.last_text is None
        return await rep.run(slow(42, 0.01)), rep, failed_once

    value, rep, failed_once = asyncio.run(generic_error())
    check("boshqa edit xatosi → generatsiya davom etadi (xato yutiladi)",
          value == 42 and failed_once and rep.edit_count == 0)


class FakeMessage:
    def __init__(self, chat_id=5001, timeline=None, can_edit=True):
        self.chat_id = chat_id
        self.replies: list[str] = []
        self.edits: list[str] = []
        self.timeline = timeline if timeline is not None else []
        if not can_edit:
            self.edit_text = None

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        child = FakeMessage(self.chat_id, self.timeline)
        child.replies = self.replies
        self.timeline.append((time.monotonic(), "reply", text))
        self.child = child
        return child

    async def edit_text(self, text, **kwargs):  # noqa: F811 - may be disabled per instance
        self.edits.append(text)
        self.timeline.append((time.monotonic(), "edit", text))
        return self


class FakeQuery:
    def __init__(self, message, fail=False):
        self.message = message
        self.edits: list[str] = []
        self.fail = fail

    async def edit_message_text(self, text, **kwargs):
        if self.fail:
            raise BadRequest("Message can't be edited")
        self.edits.append(text)
        self.message.timeline.append((time.monotonic(), "edit", text))


def test_helpers():
    print("\n== 5) for_reply / for_callback yordamchilari ==")
    CHAT_EDIT_CLOCK.clear()

    async def reply_flow():
        source = FakeMessage(6001)
        rep = await AIProgressReporter.for_reply(source, "en", stage_interval=1.1)
        await rep.run(slow(None, 1.3))
        return source, rep

    source, rep = asyncio.run(reply_flow())
    check("for_reply: 1-bosqich yangi xabar sifatida", source.replies == [AI_PROGRESS_STAGES["en"][0]])
    check("for_reply: keyingi bosqich shu xabarni tahrirlaydi",
          rep.message is source.child and source.child.edits == [AI_PROGRESS_STAGES["en"][1]])
    check("for_reply: chat_id manba xabardan olinadi", rep.chat_id == 6001)

    async def reply_no_edit():
        source = FakeMessage(6002)
        source_child = FakeMessage(6002, can_edit=False)

        async def reply_text(text, **kwargs):
            source.replies.append(text)
            return source_child

        source.reply_text = reply_text
        rep = await AIProgressReporter.for_reply(source, "uz", stage_interval=1.1)
        await rep.run(slow(None, 1.3))
        return source, rep

    source, rep = asyncio.run(reply_no_edit())
    check("edit_text yo'q adapter → har bosqichga yangi xabar YUBORILMAYDI",
          len(source.replies) == 1 and rep.editor is None)

    async def callback_flow():
        msg = FakeMessage(6003)
        query = FakeQuery(msg)
        rep = await AIProgressReporter.for_callback(query, "uz", kind="analysis")
        return query, msg, rep

    query, msg, rep = asyncio.run(callback_flow())
    check("for_callback: menyu xabari 1-bosqichga tahrirlanadi",
          query.edits == [AI_ANALYSIS_STAGES["uz"][0]] and rep.message is msg)

    async def callback_fallback():
        msg = FakeMessage(6004)
        query = FakeQuery(msg, fail=True)
        rep = await AIProgressReporter.for_callback(query, "ru", stage_interval=1.1)
        await rep.run(slow(None, 1.3))
        return msg, rep

    msg, rep = asyncio.run(callback_fallback())
    check("for_callback fallback: BITTA yangi xabar yuboriladi",
          msg.replies == [AI_PROGRESS_STAGES["ru"][0]])
    check("for_callback fallback: keyingi bosqichlar o'sha xabarda",
          rep.message is msg.child and msg.child.edits == [AI_PROGRESS_STAGES["ru"][1]])


def test_handler_integration():
    print("\n== 6) Handler: Post Score «95 ga yaxshilash» — 🧠 → ✍️ → natija ==")
    CHAT_EDIT_CLOCK.clear()
    import handlers.post_score as ps
    from utils.post_scorer import score_post_locally

    sample = ("🔥 <b>Yangi kofe — 20% chegirma!</b>\n\nArabika endi arzon.\n"
              "👉 Hoziroq yozing!\n\n#kofe #chegirma #aksiya")

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", str(func))
        return {"is_premium": False, "check_ai_limit": (True, 0, 30),
                "use_user_credit": True}.get(name, True)

    async def slow_improve(text, lang="uz", is_pro=False):
        await asyncio.sleep(2.4)
        return {"post_text": sample.replace("arzon", "juda arzon"),
                "score": score_post_locally(sample, lang)}

    timeline: list = []
    message = FakeMessage(7001, timeline)
    query = FakeQuery(message)
    query.data = ps.PS_IMPROVE
    query.from_user = SimpleNamespace(id=880777)

    async def answer(*args, **kwargs):
        return None

    query.answer = answer
    update = SimpleNamespace(callback_query=query, message=None,
                             effective_user=SimpleNamespace(id=880777))

    class Bot:
        async def send_chat_action(self, **kwargs):
            return None

    ctx = SimpleNamespace(bot=Bot(), user_data={
        "lang": "uz", "ps_text": sample, "ps_post": "", "ps_improved": False,
        "ps_score": score_post_locally(sample, "uz"),
    })
    with patch.object(ps.db, "run_db", new=fake_run_db), \
         patch.object(ps, "improve_post_to_95", new=slow_improve):
        asyncio.run(ps.post_score_improve_callback(update, ctx))

    texts = [t for _, kind, t in timeline if kind == "edit"]
    times = [t for t, kind, _ in timeline if kind == "edit"]
    stages = AI_PROGRESS_STAGES["uz"]
    check("1-bosqich: 🧠 Mavzu tahlil qilinmoqda...", texts and texts[0] == stages[0], str(texts))
    check("2-bosqich: ✍️ Post yozilmoqda...", len(texts) > 1 and texts[1] == stages[1], str(texts))
    check("yakuniy natija o'sha xabarda", texts and "juda arzon" in texts[-1], str(texts[-1:]))
    check("eski «⏳ Post tayyorlanmoqda» placeholder ishlatilmadi",
          not any("tayyorlanmoqda, iltimos" in t for t in texts))
    check("handler darajasida barcha edit'lar ≥ 1.05 s oralig'ida",
          all(g >= FLOOR for g in gaps(times)), str([round(g, 3) for g in gaps(times)]))
    check("progress uchun qo'shimcha xabar yuborilmadi", message.replies == [])

    handlers_dir = BOT_ROOT / "handlers"
    leftovers = [p.name for p in handlers_dir.glob("*.py")
                 if "⏳ Post tayyorlanmoqda" in p.read_text(encoding="utf-8")]
    check("handler'larda qattiq yozilgan o'zbekcha placeholder qolmadi", not leftovers, str(leftovers))
    unfinished = []
    for path in handlers_dir.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "AIProgressReporter" in src and src.count("progress.run(") > src.count(".finish()"):
            unfinished.append(path.name)
    check("har progress.run() dan keyin finish() (natija edit'i ham limitda)",
          not unfinished, str(unfinished))


def main() -> int:
    print("=" * 70)
    print(" AI PROGRESS — lokalizatsiya + Telegram edit limiti (≤1/s)")
    print("=" * 70)
    test_stage_texts()
    test_stage_progression_and_rate_limit()
    test_shared_chat_clock()
    test_flood_and_errors()
    test_helpers()
    test_handler_integration()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    print(" AI PROGRESS — 100% YASHIL ✔" if FAILED == 0 else " AI PROGRESS — XATOLAR BOR ✘")
    print("=" * 70)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
