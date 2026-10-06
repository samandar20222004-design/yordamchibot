#!/usr/bin/env python3
"""PHASE 5 · TELEGRAM DELIVERY ENGINE — markaziy yetkazib berish dvigateli.

Nima tekshiriladi (tarmoqsiz, deterministik):
  1) **Arxitektura** — yagona ``delivery_service`` mavjud, scheduler /
     broadcast / manual (enhancer, image, magic) manbalari shu engine
     orqali yuboradi (to'g'ridan-to'g'ri ``bot.send_message`` yo'q);
  2) **Rate limit** — 1 post/s (kanal) + 30 msg/s (umumiy) aniq interval
     limiter (injectable clock/sleep bilan — real kutishsiz);
  3) **RetryAfter (429)** — aniq kutish vaqti + jitter bilan qayta
     urinish; defer rejimida (scheduler) inline kutish YO'Q;
  4) **Failure classification** — doimiy xatolar (bot kicked / BadRequest
     HTML) birinchi urinishda to'xtaydi, ambiguous (TimedOut) faqat
     ``retry_network=True`` da qayta uriniladi;
  5) **Idempotency & crash recovery** — ``deliver_with_state``:
     PENDING → SENDING → DELIVERED; ``sent`` bo'lsa 0 duplikat, crash
     ``processing`` da qolsa qayta yuborilmaydi, DB yozuvi yiqilsa
     fail-closed (yuborilmaydi);
  6) **Bulk send** — ``_run_broadcast`` engine orqali: 3 RetryAfter
     urinishi, HTML → plain fallback, doimiy xatolar FAILED.

Ishga tushirish:
    cd telegram_bot && python tests/delivery_engine_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:DELIVERY_ENGINE_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILURES = 0


def check(name, cond, detail=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name}" + (f" -> {detail}" if detail else ""))
    return bool(cond)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------
class FakeClock:
    """Deterministik soat + sleep (engine injectable nuqtalari uchun)."""

    def __init__(self, start=1000.0):
        self.t = float(start)
        self.sleeps = []

    def mono(self):
        return self.t

    async def sleep(self, seconds):
        seconds = float(seconds)
        self.sleeps.append(seconds)
        self.t += seconds


def make_engine(service=None):
    from services.delivery import delivery_service
    svc = service or type(delivery_service)(
        global_per_second=30.0, channel_per_second=1.0, jitter_max=0.25,
    )
    clock = FakeClock()
    svc._mono = clock.mono
    svc._sleep = clock.sleep
    return svc, clock


class SequencedBot:
    """Har bir chaqiruv uchun navbatdagi javobni beradi (Success yoki Exception)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.kwargs_log = []

    async def send_message(self, **kwargs):
        self.calls += 1
        self.kwargs_log.append(kwargs)
        if not self.responses:
            return SimpleNamespace(message_id=self.calls)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    send_photo = send_message
    send_media_group = send_message


def make_retry_after(seconds):
    from telegram.error import RetryAfter
    return RetryAfter(retry_after=seconds)


def make_timed_out():
    from telegram.error import TimedOut
    return TimedOut()


def make_bad_request(text="Bad Request: can't parse entities"):
    from telegram.error import BadRequest
    return BadRequest(text)


class BotKicked(Exception):
    """PTB klassining test fake'i (nom bo'yicha permanent)."""


# ---------------------------------------------------------------------------
# 1) ARXITEKTURA — yagona engine va integratsiya nuqtalari
# ---------------------------------------------------------------------------
def test_architecture():
    print("\n== 1. Arxitektura: yagona delivery engine + integratsiya ==")
    from services.delivery import delivery_service, TelegramDeliveryService
    check("delivery_service yagona instansiasi (TelegramDeliveryService)",
          isinstance(delivery_service, TelegramDeliveryService))
    check("rate limit konstantsi: 30 msg/s umumiy + 1 post/s kanal",
          delivery_service.global_per_second == 30.0
          and delivery_service.channel_per_second == 1.0)

    # State-machine funksiyalar SHU identity bilan delegate (mock nuqtalari saqlanadi)
    from services.scheduler_service import SchedulerService
    check("claim_post_for_delivery delegate (identity saqlangan)",
          delivery_service.claim_post_for_delivery is SchedulerService.claim_post_for_delivery
          and delivery_service.claim_post_for_delivery.__name__ == "claim_post_for_delivery")
    check("mark_failed_by_key / mark_unknown_by_key delegate",
          delivery_service.mark_failed_by_key is SchedulerService.mark_failed_by_key
          and delivery_service.mark_unknown_by_key is SchedulerService.mark_unknown_by_key)
    check("PENDING→SENDING→DELIVERED statuslari motorshikda",
          delivery_service.STATUS_PENDING == "pending"
          and delivery_service.STATUS_PROCESSING == "processing"
          and delivery_service.STATUS_SENT == "sent")

    sch_src = (ROOT / "scheduler.py").read_text(encoding="utf-8")
    exec_body = sch_src.split("async def _execute_send", 1)[1].split("\nasync def ", 1)[0]
    check("scheduler: barcha post yuborishlari _delivery_send orqali",
          "_delivery_send(bot," in exec_body
          and "await bot.send_message" not in exec_body
          and "await bot.send_photo" not in exec_body, "xom bot.send_* qolgan")
    check("scheduler: delivery engine defer rejimi (inline_max_wait=0)",
          "inline_max_wait=0.0" in sch_src)
    check("scheduler: claim/mark funksiyalari delivery_service orqali",
          "delivery_service.claim_post_for_delivery" in sch_src
          and "delivery_service.mark_sent_by_key" in sch_src
          and "delivery_service.mark_failed_by_key" in sch_src)
    check("scheduler: RetryAfter aniq kutish + jitter (DB retry)",
          "delivery_service.retry_jitter()" in sch_src)

    admin_src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("broadcast: _run_broadcast delivery_service orqali yuboradi",
          "delivery_service.send_message(" in admin_src
          and "await bot.send_message(chat_id=uid" not in admin_src)
    enh_src = (ROOT / "handlers" / "post_enhancer.py").read_text(encoding="utf-8")
    check("manual post (enhancer): _dispatch_message delivery_service orqali",
          "delivery_service.send_media_group(" in enh_src
          and "delivery_service.send_photo(" in enh_src)
    img_src = (ROOT / "handlers" / "image_post.py").read_text(encoding="utf-8")
    check("image post: _send_photo_to_chat delivery_service orqali",
          "delivery_service.send_photo(bot" in img_src)
    mag_src = (ROOT / "handlers" / "magic_post.py").read_text(encoding="utf-8")
    check("magic post: _magic_deliver_one delivery_service orqali",
          "delivery_service.send_message(" in mag_src)


# ---------------------------------------------------------------------------
# 2) RATE LIMIT — 1 post/s (kanal) + 30 msg/s (umumiy)
# ---------------------------------------------------------------------------
def test_rate_limits():
    print("\n== 2. Rate limit: 1 post/s kanal + 30 msg/s umumiy ==")
    svc, clock = make_engine()
    bot = SequencedBot(SimpleNamespace(message_id=1))

    run(svc.send_message(bot, chat_id="-100A", text="bir"))
    run(svc.send_message(bot, chat_id="-100A", text="ikki"))
    check("bir xil kanal: ikkinchi yuborish ~1.0s kutiladi",
          len(clock.sleeps) == 1 and abs(clock.sleeps[0] - 1.0) < 1e-6,
          str(clock.sleeps))

    # Boshqa kanal — kanal limiti emas, faqat umumiy 30/s (≈0.033s)
    run(svc.send_message(bot, chat_id="-100B", text="uch"))
    check("boshqa kanal: faqat umumiy 30/s oraliq",
          len(clock.sleeps) == 2 and 0 < clock.sleeps[1] <= (1.0 / 30.0) + 1e-6,
          str(clock.sleeps))
    check("umumiy limit: keyingi slot ~1/30 s keyin",
          bot.calls == 3 and all("chat_id" in kw for kw in bot.kwargs_log))

    # Boshqa bot — limiterlar izolyatsiya (test fake botlari bir-biriga to'smaydi)
    svc2, clock2 = make_engine()
    bot2 = SequencedBot()
    run(svc2.send_message(bot2, chat_id="-100A", text="a"))
    run(svc2.send_message(bot2, chat_id="-100A", text="b"))
    check("botlar orasida limiter izolyatsiya (lekin ichida 1/s jiddiy)",
          len(clock2.sleeps) == 1 and abs(clock2.sleeps[0] - 1.0) < 1e-6,
          str(clock2.sleeps))


# ---------------------------------------------------------------------------
# 3) RETRYAFTER — aniq kutish + jitter / defer rejim
# ---------------------------------------------------------------------------
def test_retry_after():
    print("\n== 3. RetryAfter: aniq kutish + jitter, defer rejim ==")
    # 3a) Inline: birinchi 429 → aniq kutish (+jitter) → muvaffaqiyat
    svc, clock = make_engine()
    bot = SequencedBot(make_retry_after(5), SimpleNamespace(message_id=7))
    out = run(svc.send_message(bot, chat_id=-1001, text="x"))
    check("429 keyin aniq kutish + jitter bilan qayta urinish",
          bot.calls == 2 and getattr(out, "message_id", None) == 7,
          f"calls={bot.calls}")
    check("kutish vaqti [5.0, 5.25] (retry_after + jitter)",
          len(clock.sleeps) == 1 and 5.0 <= clock.sleeps[0] <= 5.0 + 0.25 + 1e-9,
          str(clock.sleeps))

    # 3b) Jitter chegarasi mustaqil
    svc_j, _ = make_engine()
    waits = [svc_j.retry_jitter() for _ in range(50)]
    check("retry_jitter(): 0..0.25 oralig'ida", all(0.0 <= w <= 0.25 for w in waits))
    check("retry_wait_with_jitter = aniq + jitter",
          5.0 <= svc_j.retry_wait_with_jitter(make_retry_after(5)) <= 5.25 + 1e-9)

    # 3c) defer rejim (scheduler): inline kutish YO'Q, asl RetryAfter qaytadi
    svc, clock = make_engine()
    bot = SequencedBot(make_retry_after(3))
    try:
        run(svc.send_message(bot, chat_id=-1002, text="x", inline_max_wait=0.0))
        raised = None
    except Exception as exc:
        raised = exc
    check("defer (inline_max_wait=0): aniq xato qaytadi, kutmaydi",
          raised is not None and type(raised).__name__ == "RetryAfter"
          and bot.calls == 1 and not clock.sleeps,
          f"raised={type(raised).__name__ if raised else None}, sleeps={clock.sleeps}")

    # 3d) Juda uzun kutish (60s) — interaktiv oqim kutmaydi, xato chaqiruvchiga
    svc, clock = make_engine()
    bot = SequencedBot(make_retry_after(60))
    try:
        run(svc.send_message(bot, chat_id=-1003, text="x", inline_max_wait=8.0))
        raised = None
    except Exception as exc:
        raised = exc
    check("uzun FloodWait (> inline_max_wait) — kutmaydi qaytaradi",
          raised is not None and type(raised).__name__ == "RetryAfter"
          and not clock.sleeps, str(clock.sleeps))

    # 3e) retry_after false/ buzilgan qiymatlar
    check("retry_after=0 → default 2.0", svc.retry_after_seconds(make_retry_after(0)) == 2.0)
    check("retry_after=9999 → 60s yuqori chegara", svc.retry_after_seconds(make_retry_after(9999)) == 60.0)
    check("retry_after str/buzilgan → default", svc.retry_after_seconds(SimpleNamespace(retry_after="olti")) == 2.0)
    check("atributsiz → default", svc.retry_after_seconds(object()) == 2.0)


# ---------------------------------------------------------------------------
# 4) FAILURE CLASSIFICATION — permanent / ambiguous / transient
# ---------------------------------------------------------------------------
def test_failure_classification():
    print("\n== 4. Failure classification: dead-letter & no-blind-retry ==")
    from services.delivery.engine import (
        FAILURE_PERMANENT, FAILURE_RATE_LIMIT, FAILURE_AMBIGUOUS, FAILURE_TRANSIENT,
        TelegramDeliveryService,
    )
    check("classify: RetryAfter → rate_limit",
          TelegramDeliveryService.classify(make_retry_after(2)) == FAILURE_RATE_LIMIT)
    check("classify: BadRequest (invalid HTML) → permanent",
          TelegramDeliveryService.classify(make_bad_request()) == FAILURE_PERMANENT)
    check("classify: BotKicked → permanent (dead-letter)",
          TelegramDeliveryService.classify(BotKicked("bot was kicked")) == FAILURE_PERMANENT)
    check("classify: TimedOut → ambiguous (blind retry yo'q)",
          TelegramDeliveryService.classify(make_timed_out()) == FAILURE_AMBIGUOUS)
    from telegram.error import TelegramError
    check("classify: oddiy TelegramError → transient",
          TelegramDeliveryService.classify(TelegramError("temporary")) == FAILURE_TRANSIENT)

    # 4a) Permanent: qayta urinish YO'Q (birinchi urinishda to'xtash)
    svc, clock = make_engine()
    bot = SequencedBot(BotKicked("bot was kicked from the chat"))
    try:
        run(svc.send_message(bot, chat_id=-1004, text="x", retry_network=True))
        raised = None
    except Exception as exc:
        raised = exc
    check("permanent: 1 urinish, kutishsiz qaytadi (dead-letter yo'li)",
          raised is not None and isinstance(raised, BotKicked)
          and bot.calls == 1 and not clock.sleeps,
          f"calls={bot.calls} sleeps={clock.sleeps}")

    # 4b) BadRequest ham permanent (fallback chaqiruvchida — dvigatel qayta urinmaydi)
    svc, clock = make_engine()
    bot = SequencedBot(make_bad_request())
    try:
        run(svc.send_message(bot, chat_id=-1005, text="x", retry_network=True))
        raised = None
    except Exception as exc:
        raised = exc
    check("BadRequest: asl istisno qaytadi (plain-text fallback saqlangan)",
          raised is not None and type(raised).__name__ == "BadRequest"
          and bot.calls == 1, f"calls={bot.calls}")

    # 4c) Ambiguous: retry_network=False → 1 urinish (dublikat xavfi yo'q)
    svc, clock = make_engine()
    bot = SequencedBot(make_timed_out())
    try:
        run(svc.send_message(bot, chat_id=-1006, text="x"))
        raised = None
    except Exception as exc:
        raised = exc
    check("ambiguous standart: blind retry yo'q (1 urinish)",
          raised is not None and bot.calls == 1 and not clock.sleeps,
          f"calls={bot.calls}")

    # 4d) Ambiguous: retry_network=True (broadcast) → backoff bilan qayta urinish
    svc, clock = make_engine()
    bot = SequencedBot(make_timed_out(), SimpleNamespace(message_id=9))
    out = run(svc.send_message(bot, chat_id=-1007, text="x", retry_network=True,
                               max_attempts=3))
    check("retry_network=True: tarmoq xatosidan keyin qayta urinish",
          bot.calls == 2 and getattr(out, "message_id", None) == 9,
          f"calls={bot.calls}")
    check("tarmoq backoff ≈1s + jitter",
          len(clock.sleeps) == 1 and 1.0 <= clock.sleeps[0] <= 1.0 + 0.25 + 1e-9,
          str(clock.sleeps))


# ---------------------------------------------------------------------------
# 5) IDEMPOTENCY & CRASH RECOVERY — PENDING → SENDING → DELIVERED
# ---------------------------------------------------------------------------
def test_state_machine():
    print("\n== 5. Idempotency: PENDING → SENDING → DELIVERED (crash-safe) ==")
    svc, clock = make_engine()
    store = {"status": "pending", "attempts": 0, "message_id": None,
             "key": "post_1_-1009_t"}

    async def run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "claim_post_for_delivery":
            if store["status"] == "sent":
                return {"claimed": False, "sent": True, "status": "sent",
                        "message_id": store["message_id"], "idempotency_key": store["key"]}
            if store["status"] == "unknown":
                return {"claimed": False, "unknown": True, "status": "unknown",
                        "idempotency_key": store["key"]}
            if store["status"] == "dead_letter":
                return {"claimed": False, "dead": True, "status": "dead_letter",
                        "idempotency_key": store["key"]}
            if store["status"] == "processing":
                # Boshqa (crash bo'lgan) worker hali egallagan — qayta yuborilmaydi
                return {"claimed": False, "status": "processing",
                        "idempotency_key": store["key"]}
            store["status"] = "processing"  # SENDING
            return {"claimed": True, "status": "processing", "attempt_count": store["attempts"],
                    "idempotency_key": store["key"]}
        if name == "mark_as_sent":
            store["status"] = "sent"
            store["message_id"] = args[2] if len(args) > 2 else None
            return True
        if name == "mark_failed_by_key":
            key, error, is_transient = args[0], args[1], args[2]
            permanent = (not is_transient) or svc.classify(error) == "permanent"
            if permanent:
                store["status"] = "dead_letter"
                return {"ok": True, "status": "dead_letter", "idempotency_key": key}
            store["attempts"] += 1
            store["status"] = "failed"
            return {"ok": True, "status": "failed", "attempt_count": store["attempts"],
                    "backoff_seconds": 30, "idempotency_key": key}
        if name == "mark_unknown_by_key":
            store["status"] = "unknown"
            return True
        raise AssertionError(f"model bilmagan DB funksiyasi: {name}")

    sent_calls = []

    async def send_ok():
        sent_calls.append(1)
        return SimpleNamespace(message_id=4242)

    # 5a) PENDING → SENDING → DELIVERED
    res = run(svc.deliver_with_state(1, "-1009", None, send_ok, run=run_db))
    check("muvaffaqiyat: PENDING→SENDING→DELIVERED (sent)",
          res.get("status") == "sent" and res.get("message_id") == 4242
          and store["status"] == "sent" and len(sent_calls) == 1, str(res))

    # 5b) Qayta chaqiruv (restartdan keyin) — 0 duplikat, send chaqirilmaydi
    res = run(svc.deliver_with_state(1, "-1009", None, send_ok, run=run_db))
    check("crash recovery: 'sent' bo'lsa qayta yuborilmaydi (0 duplikat)",
          res.get("duplicate") is True and res.get("status") == "sent"
          and len(sent_calls) == 1, str(res))

    # 5c) Crash: 'processing'da qolib ketgan — send yo'q, status processing
    store.update(status="processing", attempts=0)
    res = run(svc.deliver_with_state(2, "-1009", None, send_ok, run=run_db))
    check("crash: 'processing' qolganda send YO'Q (boshqa worker egallagan)",
          res.get("claimed") is False and res.get("status") == "processing"
          and len(sent_calls) == 1, str(res))

    # 5d) Permanent xato → darhol dead_letter (FAILED, qayta urinish yo'q)
    store.update(status="pending", attempts=0)

    async def send_kicked():
        sent_calls.append(1)
        raise BotKicked("bot was kicked")

    res = run(svc.deliver_with_state(3, "-1009", None, send_kicked, run=run_db))
    check("permanent → dead_letter (FAILED darhol, retry yo'q)",
          res.get("status") == "dead_letter" and res.get("classification") == "permanent"
          and store["status"] == "dead_letter", str(res))

    # 5e) Ambiguous (timeout) → UNKNOWN: blind retry taqiqlanadi
    store.update(status="pending", attempts=0)

    async def send_timeout():
        sent_calls.append(1)
        raise make_timed_out()

    res = run(svc.deliver_with_state(4, "-1009", None, send_timeout, run=run_db))
    check("timeout → UNKNOWN (blind retry taqiqlanadi)",
          res.get("status") == "unknown" and res.get("classification") == "ambiguous"
          and store["status"] == "unknown", str(res))
    before = len(sent_calls)
    res = run(svc.deliver_with_state(4, "-1009", None, send_ok, run=run_db))
    check("UNKNOWN keyin qayta yuborish → rad etiladi (send yo'q)",
          res.get("status") == "unknown" and len(sent_calls) == before, str(res))

    # 5f) Rate-limit xato → failed (backoff), yana yuborishga ruxsat
    store.update(status="pending", attempts=0)

    async def send_429():
        sent_calls.append(1)
        raise make_retry_after(5)

    res = run(svc.deliver_with_state(5, "-1009", None, send_429, run=run_db))
    check("429 → failed (backoff bilan qayta urinish mumkin)",
          res.get("status") == "failed" and res.get("classification") == "rate_limit"
          and store["attempts"] == 1, str(res))

    # 5g) DB claim yiqildi → fail-closed (yuborilmaydi)
    count_before_db_fail = len(sent_calls)

    async def run_db_down(fn, *args, **kwargs):
        raise RuntimeError("DB down")

    res = run(svc.deliver_with_state(6, "-1009", None, send_ok, run=run_db_down))
    check("DB yiqildi → fail-closed: send UMUMAN chaqirilmaydi",
          res.get("status") == "error" and len(sent_calls) == count_before_db_fail,
          str(res))


# ---------------------------------------------------------------------------
# 6) BULK SEND — _run_broadcast engine orqali (mavjud kontraktlar)
# ---------------------------------------------------------------------------
class BroadcastFakeBot:
    def __init__(self, delay=0.0):
        self.sent = []
        self.delay = delay
        self._blocked = set()
        self._bad_html = set()

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kwargs):
        if chat_id in self._blocked:
            from telegram.error import TelegramError
            raise TelegramError("blocked")
        if chat_id in self._bad_html and parse_mode == "HTML":
            from telegram.error import BadRequest
            raise BadRequest("can't parse entities")
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))


def test_broadcast():
    print("\n== 6. Bulk send: _run_broadcast delivery engine orqali ==")
    import handlers.admin as adm
    import database as db_mod

    async def fake_run_db(fn, *args, **kwargs):
        return True

    orig_run = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # 6a) 60 foydalanuvchi: 2 bloklangan + 1 HTML xato (plain fallback)
        bot = BroadcastFakeBot()
        bot._blocked = {"u5", "u30"}
        bot._bad_html = {"u10"}
        user_ids = [f"u{i}" for i in range(60)]
        asyncio.run(adm._run_broadcast(bot, user_ids, "<b>Xabar</b>", 777000))
        user_deliveries = [c for c, _ in bot.sent if c != 777000]
        check("broadcast: 58/60 yetib bordi (2 blok + 1 HTML fallback)",
              len(user_deliveries) == 58, f"sent={len(user_deliveries)}")
        check("broadcast: yakuniy admin hisobot yuborildi",
              any(c == 777000 for c, _ in bot.sent))

        # 6b) Doimiy 429: aynan 3 urinish, hammasi FAILED + admin hisobot 0/N
        class AlwaysRetryBot(BroadcastFakeBot):
            def __init__(self):
                super().__init__()
                self.calls = 0

            async def send_message(self, chat_id=None, text=None, reply_markup=None,
                                   parse_mode=None, **kwargs):
                if chat_id == 777000:
                    return await super().send_message(
                        chat_id=chat_id, text=text, reply_markup=reply_markup,
                        parse_mode=parse_mode)
                self.calls += 1
                raise make_retry_after(1)

        rbot = AlwaysRetryBot()
        rids = [f"r{i}" for i in range(5)]
        asyncio.run(adm._run_broadcast(rbot, rids, "xabar", 777000))
        check("429: har foydalanuvchi aynan 3 urinish (5×3=15)",
              rbot.calls == 15, f"calls={rbot.calls}")
        admin_msgs = [t for c, t in rbot.sent if c == 777000]
        check("429 admin hisobotida barchasi yuborilmagan (0 / 5)",
              bool(admin_msgs) and "0 / 5" in admin_msgs[0], str(admin_msgs)[:120])
    finally:
        db_mod.run_db = orig_run


def main():
    print("=" * 70)
    print(" PHASE 5 — TELEGRAM DELIVERY ENGINE TEST")
    print("=" * 70)
    test_architecture()
    test_rate_limits()
    test_retry_after()
    test_failure_classification()
    test_state_machine()
    test_broadcast()
    print()
    print(f"JAMI: o'tdi={PASSED}, xato={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
