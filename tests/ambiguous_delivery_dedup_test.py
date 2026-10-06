#!/usr/bin/env python3
"""P0 (VAZIFA 2) — NOANIQ (AMBIGUOUS) YETKAZIB BERISH VA DUBLIKAT DEDUPLIKATSIYASI.

Nima tekshiriladi (tarmoqsiz, deterministik):
  1) **Fingerprint (SHA256)** — post matni/mediasi uchun imzo deterministik va
     normalizatsiyaga bardosh (probel/qator farqlari dublikat deb hisoblanmaydi);
  2) **Kanal tekshiruvi xulosasi** — present / absent / unavailable
     (bo'sh ro'yxat "yo'q" degani EMAS — konservativ);
  3) **resolve_ambiguous** — topilsa DELIVERED (0 duplikat), yo'qligi
     tasdiqlansa xavfsiz retry, tasdiqlanmasa verify_pending, urinishlar
     tugagach UNKNOWN (hech qachon ko'r-ko'rrona yuborish yo'q);
  4) **deliver_with_state(verify=...)** — TimedOut → kanalda topilsa 'sent'
     (send AYNAN 1 marta), ko'r-ko'rrona retry yo'q;
  5) **Idempotent delivery lock** — bir xil kalit bilan parallel tasklardan
     faqat BITTA send; cache backend'da atomik SET NX primitivi;
  6) **Scheduler integratsiyasi** — `_execute_send`: TimedOut'da kanal
     tekshiriladi; post kanalda bo'lsa scheduled_posts 'posted' bo'ladi va
     `retry_post` CHAQIRILMAYDI; yo'qligi tasdiqlansa xavfsiz retry;
     tasdiqlanmasa verify_pending markeri yoziladi (yuborilmaydi);
  7) **Pre-send dedup gate** — delivery'da `AMBIGUOUS_VERIFY` markeri bo'lsa
     Telegramga YUBORMASDAN avval kanal tekshiriladi (0 duplikat).

Ishga tushirish:
    cd telegram_bot && python tests/ambiguous_delivery_dedup_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:AMBIGUOUS_DEDUP_TEST")
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


def make_engine():
    from services.delivery import delivery_service
    svc = type(delivery_service)(
        global_per_second=30.0, channel_per_second=1.0, jitter_max=0.25,
    )
    clock = FakeClock()
    svc._mono = clock.mono
    svc._sleep = clock.sleep
    return svc, clock


def make_timed_out():
    from telegram.error import TimedOut
    return TimedOut()


def _delivery():
    from services.delivery import delivery_service
    return delivery_service


# ===========================================================================
# 1) FINGERPRINT — SHA256 imzo
# ===========================================================================
def test_fingerprints():
    print("\n== 1. Fingerprint (SHA256): post ↔ kanal xabari solishtiruvi ==")
    svc = _delivery()

    text = "Assalomu alaykum!\n\nBugungi yangiliklar."
    sig_a = svc.build_delivery_signature(text, media_count=0)
    sig_b = svc.build_delivery_signature(text, media_count=0)
    check("imzo deterministik (bir xil matn → bir xil SHA256)",
          sig_a["text_hash"] == sig_b["text_hash"] and bool(sig_a["text_hash"]))
    check("imzo SHA256 hex (64 belgi)",
          len(sig_a["text_hash"]) == 64 and all(c in "0123456789abcdef" for c in sig_a["text_hash"]))

    # Probel/qator normalizatsiyasi — dublikatni o'tkazib yubormaslik uchun
    noisy = "Assalomu   alaykum!\n\n\n\nBugungi yangiliklar."
    sig_c = svc.build_delivery_signature(noisy, media_count=0)
    check("normalizatsiya: ortiqcha probel/qator imzoni buzmaydi",
          sig_c["text_hash"] == sig_a["text_hash"], f"{sig_c['text_hash'][:12]} != {sig_a['text_hash'][:12]}")

    check("media soni imzoda saqlanadi",
          svc.build_delivery_signature(text, media_count=3)["media_count"] == 3)
    check("bo'sh matn → text_hash yo'q", svc.build_delivery_signature("")["text_hash"] == "")
    check("marker imzoga qo'shiladi",
          svc.build_delivery_signature("", marker="uid-42")["marker"] == "uid-42")


def test_candidate_matching():
    print("\n== 1b. Kanal xabari mos kelish qoidalari ==")
    from services.delivery.engine import (build_delivery_signature,
                                          candidate_matches_signature)
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)

    text = "Bugungi post matni — juda muhim yangilik." * 4
    sig = build_delivery_signature(text, media_count=0)

    check("aynan bir xil matn → mos",
          candidate_matches_signature(sig, {"text": text}, now=now))
    check("boshqa matn → mos EMAS",
          not candidate_matches_signature(sig, {"text": "butunlay boshqa post"}, now=now))
    check("DB tarixi formati (content kaliti) ham o'qiladi",
          candidate_matches_signature(sig, {"content": text}, now=now))

    # Matn oxiri (Telegram kesishi/onish) — tail hash
    tail_text = text[-120:]
    text = "X" * 300 + tail_text
    tail_sig = build_delivery_signature(text, media_count=0)
    check("matn oxiri (tail) heshi mos keladi",
          candidate_matches_signature(tail_sig, {"text": "Y" * 50 + tail_text}, now=now))

    # Noyob marker
    marker_sig = build_delivery_signature("post matni", media_count=0, marker="post-777")
    check("noyob marker matnda topilsa → mos",
          candidate_matches_signature(marker_sig, {"text": "post matni (post-777)"}, now=now))

    # Matnsiz media post: media + vaqt oynasi
    media_sig = build_delivery_signature("", media_count=2)
    in_window = {"media_url": "https://cdn/x.jpg", "text": "",
                 "date": (now - timedelta(seconds=60)).isoformat()}
    out_window = {"media_url": "https://cdn/x.jpg", "text": "",
                  "date": (now - timedelta(seconds=7200)).isoformat()}
    check("matnsiz media post (vaqt oynasida) → mos",
          candidate_matches_signature(media_sig, in_window, now=now))
    check("matnsiz media post (oynadan tashqarida) → mos EMAS",
          not candidate_matches_signature(media_sig, out_window, now=now))


def test_probe_verdicts():
    print("\n== 2. Kanal tekshiruvi xulosasi (present/absent/unavailable) ==")
    from services.delivery.engine import (VERIFY_PRESENT, VERIFY_ABSENT,
                                          VERIFY_UNAVAILABLE,
                                          evaluate_channel_probe)
    svc = _delivery()
    text = "Kanalga chiqqan post matni"
    sig = svc.build_delivery_signature(text, media_count=0)
    verdict, matched = evaluate_channel_probe({"status": "ok", "items": [{"text": text}]}, sig)
    check("kanalda topildi → present", verdict == VERIFY_PRESENT and matched is not None, verdict)
    verdict, _ = evaluate_channel_probe({"status": "ok", "items": [{"text": "boshqa"}]}, sig)
    check("o'qildi, post yo'q → absent", verdict == VERIFY_ABSENT, verdict)
    verdict, _ = evaluate_channel_probe({"status": "unavailable", "items": []}, sig)
    check("o'qilmadi → unavailable (blind retry taqiqlanadi)", verdict == VERIFY_UNAVAILABLE, verdict)
    verdict, _ = evaluate_channel_probe({"status": "ok", "items": []}, sig)
    check("bo'sh ro'yxat 'yo'q' degani EMAS → unavailable", verdict == VERIFY_UNAVAILABLE, verdict)
    verdict, _ = evaluate_channel_probe(None, sig)
    check("probe=None → unavailable", verdict == VERIFY_UNAVAILABLE, verdict)


# ===========================================================================
# 3) resolve_ambiguous — DB oqimi
# ===========================================================================
class _ClaimStore:
    """post_deliveries yozuvini xotirada modellashtiruvchi fake DB runner."""

    def __init__(self, status="failed"):
        self.status = status
        self.calls = []
        self.last_error = None
        self.message_id = None

    async def run(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name == "mark_sent_by_key":
            self.status = "sent"
            self.message_id = args[1] if len(args) > 1 else None
            self.last_error = None
            return True
        if name == "mark_verify_pending_by_key":
            self.status = "failed"
            self.last_error = f"AMBIGUOUS_VERIFY attempt={args[2]} | {args[1]}" if len(args) > 2 else "AMBIGUOUS_VERIFY attempt=1"
            return {"ok": True, "status": "failed", "verify_pending": True}
        if name == "clear_verify_pending_by_key":
            self.status = "failed"
            self.last_error = None
            return True
        if name == "mark_unknown_by_key":
            self.status = "unknown"
            self.last_error = str(args[1])
            return True
        raise AssertionError(f"kutilmagan DB funksiyasi: {name}")


def test_resolve_ambiguous_present():
    print("\n== 3. resolve_ambiguous: post kanalda TOPILDI → DELIVERED ==")
    svc, _clock = make_engine()
    store = _ClaimStore()
    text = "Noaniq holatdagi post matni"
    sig = svc.build_delivery_signature(text, media_count=0)

    res = run(svc.resolve_ambiguous(
        probe={"status": "ok", "items": [{"text": text, "message_id": 555}]},
        channel_id="-1001", signature=sig, attempt=1, run=store.run, key="k1",
        error=make_timed_out(),
    ))
    names = [c[0] for c in store.calls]
    check("status 'sent' (DELIVERED)", res.get("status") == "sent", str(res))
    check("verified_duplicate belgisi (dublikat yuborilmadi)",
          res.get("verified_duplicate") is True, str(res))
    check("mark_sent_by_key chaqirildi + message_id 555",
          "mark_sent_by_key" in names and store.message_id == 555, str(store.calls))
    check("kanal topilganda 'unknown'/'retry' YO'Q",
          "mark_unknown_by_key" not in names and "mark_verify_pending_by_key" not in names,
          str(names))


def test_resolve_ambiguous_absent():
    print("\n== 3b. resolve_ambiguous: post YO'Q (tasdiqlandi) → xavfsiz retry ==")
    svc, _clock = make_engine()
    store = _ClaimStore(status="failed", )
    store.last_error = "AMBIGUOUS_VERIFY attempt=1"
    sig = svc.build_delivery_signature("boshqa post", media_count=0)

    res = run(svc.resolve_ambiguous(
        probe={"status": "ok", "items": [{"text": "kanaldagi boshqa post"}]},
        channel_id="-1001", signature=sig, attempt=1, run=store.run, key="k2",
        error=make_timed_out(),
    ))
    names = [c[0] for c in store.calls]
    check("status 'ready' (safe_retry)", res.get("status") == "ready" and res.get("safe_retry") is True,
          str(res))
    check("marker tozalandi (clear_verify_pending_by_key)",
          "clear_verify_pending_by_key" in names and store.last_error is None, str(store.calls))


def test_resolve_ambiguous_unavailable_defer():
    print("\n== 3c. resolve_ambiguous: tasdiqlanmadi → verify_pending (YUBORILMAYDI) ==")
    svc, _clock = make_engine()
    store = _ClaimStore()
    sig = svc.build_delivery_signature("post", media_count=0)

    res = run(svc.resolve_ambiguous(
        probe={"status": "unavailable", "items": []},
        channel_id="-1001", signature=sig, attempt=1, max_attempts=3,
        run=store.run, key="k3", error=make_timed_out(), delay=30.0,
    ))
    names = [c[0] for c in store.calls]
    check("status 'verify_pending'", res.get("status") == "verify_pending", str(res))
    check("retry_in 30s qaytadi", float(res.get("retry_in") or 0) == 30.0, str(res))
    check("marker yozildi (AMBIGUOUS_VERIFY attempt=1)",
          "mark_verify_pending_by_key" in names
          and _delivery().delivery_verify_attempt(store.last_error) == 1, str(store.last_error))
    check("unknown'ga o'tkazilmadi (hali tekshiruv davom etadi)",
          store.status == "failed" and "mark_unknown_by_key" not in names)


def test_resolve_ambiguous_unavailable_exhausted():
    print("\n== 3d. resolve_ambiguous: urinishlar tugadi → UNKNOWN ==")
    svc, _clock = make_engine()
    store = _ClaimStore()
    sig = svc.build_delivery_signature("post", media_count=0)

    res = run(svc.resolve_ambiguous(
        probe={"status": "unavailable", "items": []},
        channel_id="-1001", signature=sig, attempt=3, max_attempts=3,
        run=store.run, key="k4", error=make_timed_out(),
    ))
    names = [c[0] for c in store.calls]
    check("status 'unknown' (admin ko'radi)", res.get("status") == "unknown", str(res))
    check("mark_unknown_by_key chaqirildi", "mark_unknown_by_key" in names, str(names))
    check("verify_pending YOZILMADI (urinishlar tugagan)",
          "mark_verify_pending_by_key" not in names, str(names))


def test_verify_marker_roundtrip():
    print("\n== 3e. verify marker (last_error) formati ==")
    svc = _delivery()
    marker = svc.build_verify_marker(2, make_timed_out())
    check("marker 'AMBIGUOUS_VERIFY attempt=2' bilan boshlanadi",
          marker.startswith("AMBIGUOUS_VERIFY attempt=2"), marker)
    check("delivery_verify_pending(marker) → True", svc.delivery_verify_pending(marker) is True)
    check("delivery_verify_attempt(marker) → 2", svc.delivery_verify_attempt(marker) == 2)
    check("oddiy xato matni marker emas",
          svc.delivery_verify_pending("TimedOut: bo'ldi") is False
          and svc.delivery_verify_attempt("TimedOut") == 0)
    check("None/bo'sh xavfsiz", svc.delivery_verify_pending(None) is False
          and svc.delivery_verify_attempt(None) == 0)


# ===========================================================================
# 4) deliver_with_state(verify=...) — TimedOut dublikat chiqarmaydi
# ===========================================================================
def test_deliver_with_state_ambiguous_verify_present():
    print("\n== 4. deliver_with_state: TimedOut → kanalda topilsa 0 duplikat ==")
    svc, _clock = make_engine()
    store = {"status": "pending", "sent_calls": 0}
    text = "Uzun post matni — kanalga allaqachon chiqqan bo'lishi mumkin." * 2
    sig = svc.build_delivery_signature(text, media_count=0)

    async def run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "claim_post_for_delivery":
            store["status"] = "processing"
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": "k5"}
        if name == "mark_sent_by_key":
            store["status"] = "sent"
            return True
        if name == "clear_verify_pending_by_key":
            return True
        if name == "mark_failed_by_key":
            store["status"] = "failed"
            return {"ok": True, "status": "failed", "backoff_seconds": 30}
        if name == "mark_unknown_by_key":
            store["status"] = "unknown"
            return True
        return None

    async def send():
        store["sent_calls"] += 1
        raise make_timed_out()

    async def verify():
        # Kanalning oxirgi xabari — aynan biz yubormoqchi bo'lgan post.
        return {"status": "ok", "items": [{"text": text, "message_id": 9001}]}

    res = run(svc.deliver_with_state(
        10, "-1001", None, send, run=run_db, verify=verify, signature=sig,
    ))
    check("natija 'sent' + verified_duplicate",
          res.get("status") == "sent" and res.get("verified_duplicate") is True, str(res))
    check("Telegram send AYNAN 1 marta (dublikat YO'Q)", store["sent_calls"] == 1, str(store))
    check("delivery 'sent' holatida", store["status"] == "sent", str(store))


def test_deliver_with_state_ambiguous_verify_unavailable():
    print("\n== 4b. deliver_with_state: tasdiqlanmasa → verify_pending (retry yo'q) ==")
    svc, _clock = make_engine()
    store = {"status": "pending", "sent_calls": 0, "marker": None}

    async def run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "idempotency_key": "k6"}
        if name == "mark_verify_pending_by_key":
            store["marker"] = "AMBIGUOUS_VERIFY attempt=1"
            store["status"] = "failed"
            return {"ok": True}
        if name == "mark_failed_by_key":
            return {"ok": True, "status": "failed", "backoff_seconds": 30}
        if name == "mark_sent_by_key":
            store["status"] = "sent"
            return True
        if name == "mark_unknown_by_key":
            store["status"] = "unknown"
            return True
        return None

    async def send():
        store["sent_calls"] += 1
        raise make_timed_out()

    async def verify():
        raise OSError("kanal o'qilmadi (tarmoq)")

    res = run(svc.deliver_with_state(
        11, "-1001", None, send, run=run_db, verify=verify,
        signature=svc.build_delivery_signature("post", media_count=0),
    ))
    check("natija 'verify_pending'", res.get("status") == "verify_pending", str(res))
    check("Telegram send faqat 1 marta (qayta urinilmadi)", store["sent_calls"] == 1, str(store))
    check("verify markeri DB'ga yozildi", store["marker"] is not None, str(store))


# ===========================================================================
# 5) IDEMPOTENT DELIVERY LOCK
# ===========================================================================
def test_local_lock_serializes_parallel_tasks():
    print("\n== 5. Idempotent delivery lock: parallel tasklardan faqat BITTA send ==")
    svc, _clock = make_engine()
    sends = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "claim_post_for_delivery":
            # Ataylab HAR IKKI taskka "claimed" qaytaramiz — lock bo'lmasa
            # ikkita send bo'lardi (dublikat).
            return {"claimed": True, "status": "processing", "idempotency_key": "same-key"}
        if name == "mark_sent_by_key":
            return True
        return None

    async def send():
        sends.append(1)
        started.set()
        await release.wait()
        return SimpleNamespace(message_id=1)

    async def worker():
        return await svc.deliver_with_state(
            12, "-1001", None, send, run=run_db,
        )

    async def scenario():
        first = asyncio.create_task(worker())
        await asyncio.wait_for(started.wait(), timeout=2.0)
        second = asyncio.create_task(worker())
        await asyncio.sleep(0.05)          # ikkinchi task claim/lock bosqichida
        release.set()
        return await asyncio.gather(first, second)

    first, second = run(scenario())
    statuses = sorted([first.get("status", ""), second.get("status", "")])
    check("faqat bitta Telegram send (lock ishladi)", len(sends) == 1, f"sends={len(sends)}")
    check("birinchisi 'sent', ikkinchisi lock-band ('processing'/busy)",
          "sent" in statuses and any(s in ("processing", "failed", "verify_pending") for s in statuses),
          str(statuses))


def test_lock_release_and_acquire():
    print("\n== 5b. acquire/release_delivery_lock semantikasi ==")
    svc, _clock = make_engine()

    async def scenario():
        token1 = await svc.acquire_delivery_lock("lock-key")
        token2 = await svc.acquire_delivery_lock("lock-key")
        await svc.release_delivery_lock("lock-key", token1)
        token3 = await svc.acquire_delivery_lock("lock-key")
        await svc.release_delivery_lock("lock-key", token3)
        token4 = await svc.acquire_delivery_lock("lock-key")
        await svc.release_delivery_lock("lock-key", token4)
        return token1, token2, token3, token4

    token1, token2, token3, token4 = run(scenario())
    check("birinchi lock olindi (token)", bool(token1), str(token1))
    check("band bo'lganda ikkinchi lock → None (yuborish YO'Q)", token2 is None, str(token2))
    check("release'dan keyin yana olinadi", bool(token3) and bool(token4))


def test_cache_set_if_absent_atomic():
    print("\n== 5c. Cache backend: atomik SET NX primitivi ==")
    from services import cache_backend as cb

    async def scenario():
        backend = cb.make_memory_backend()
        first = await backend.set_if_absent("delivery:lock:1", "tok-a", ttl=30)
        second = await backend.set_if_absent("delivery:lock:1", "tok-b", ttl=30)
        wrong_release = await backend.compare_and_delete("delivery:lock:1", "tok-b")
        right_release = await backend.compare_and_delete("delivery:lock:1", "tok-a")
        third = await backend.set_if_absent("delivery:lock:1", "tok-c", ttl=30)
        return first, second, wrong_release, right_release, third

    first, second, wrong_release, right_release, third = run(scenario())
    check("birinchi SET NX → True", first is True)
    check("mavjud kalitga SET NX → False (lock boshqa egada)", second is False)
    check("begona token bilan o'chirilmaydi", wrong_release is False)
    check("egasi tokeni bilan o'chiriladi", right_release is True)
    check("bo'shagach yana SET NX → True", third is True)


# ===========================================================================
# 6) SCHEDULER INTEGRATSIYASI — _execute_send
# ===========================================================================
class SchedulerHarness:
    """`scheduler._execute_send` uchun minimal fake muhit."""

    def __init__(self, *, send_error=None, probe_result=None, claim_last_error=None):
        import scheduler as sch
        self.sch = sch
        self.calls = []
        self.sent = []
        self.send_error = send_error
        self.probe_result = probe_result
        self.claim_last_error = claim_last_error
        self.orig_run_db = sch.db.run_db
        self.orig_probe = sch._probe_channel_recent_posts

    def __enter__(self):
        sch = self.sch
        harness = self

        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", str(fn))
            harness.calls.append((name, args))
            if name == "get_post_delivery_options":
                return {}
            if name == "mark_post_processing":
                return True
            if name == "claim_post_for_delivery":
                payload = {"claimed": True, "status": "processing",
                           "attempt_count": 0, "idempotency_key": "delivery-key"}
                if harness.claim_last_error:
                    payload["last_error"] = harness.claim_last_error
                    payload["verify_pending"] = sch.delivery_service.delivery_verify_pending(
                        harness.claim_last_error)
                return payload
            if name == "mark_failed_by_key":
                return {"status": "failed", "backoff_seconds": 30, "attempt_count": 1}
            if name == "mark_verify_pending_by_key":
                return {"ok": True, "status": "failed", "verify_pending": True}
            if name == "clear_verify_pending_by_key":
                return True
            if name == "mark_unknown_by_key":
                return True
            if name == "mark_sent_by_key":
                return True
            if name in ("is_premium",):
                return True
            if name == "get_setting":
                return ""
            if name in ("bump_channel_post_count", "mark_post_as_sent", "retry_post",
                        "mark_post_status"):
                return True
            return None

        async def fake_probe(bot, channel_id, limit=None):
            return harness.probe_result

        sch.db.run_db = fake_run_db
        sch._probe_channel_recent_posts = fake_probe
        sch._UNPERSISTED_SENT.clear()
        sch._journal_loaded = True
        sch.clear_channel_flood()
        sch.SENT_JOURNAL_PATH = ""
        return self

    def __exit__(self, *exc):
        sch = self.sch
        sch.db.run_db = self.orig_run_db
        sch._probe_channel_recent_posts = self.orig_probe
        sch._UNPERSISTED_SENT.clear()
        return False

    def names(self):
        return [c[0] for c in self.calls]

    def args_of(self, name):
        return [args for n, args in self.calls if n == name]


def _text_post(pid=901, channel="-1001234", content="Noaniq post matni"):
    return (pid, 4242, channel, "text", content, None, None, None, False,
            datetime.now(timezone.utc), "none", None, None, None, 0, None)


def _album_post(pid=902, channel="-1001234", caption="Albom caption"):
    items = json.dumps([{"type": "photo", "file_id": "A1"},
                        {"type": "photo", "file_id": "A2"}])
    return (pid, 4242, channel, "album", caption, items, None, None, False,
            datetime.now(timezone.utc), "none", None, None, None, 0, None)



class _TimedOutBot:
    def __init__(self, error=None):
        self.sent_messages = []
        self.error = error or make_timed_out()

    async def send_message(self, *a, **kw):
        self.sent_messages.append(kw)
        raise self.error

    async def send_media_group(self, *a, **kw):
        self.sent_messages.append(kw)
        raise self.error

    async def get_chat(self, channel_id):
        return SimpleNamespace(username="testkanal")


def test_scheduler_timedout_dedup_present():
    print("\n== 6. _execute_send: TimedOut + post kanalda → DELIVERED, retry YO'Q ==")
    import scheduler as sch
    content = "Uzun post matni — kanalga chiqqan bo'lishi mumkin" * 3
    # Watermark/reklama qo'shilmasligi uchun fingerprint'ni kanal xabari matni
    # sifatida ham ishlatamiz: probe aynan shu matnni qaytaradi.
    with SchedulerHarness(probe_result={"status": "ok", "items": [{"text": content}]}) as h:
        bot = _TimedOutBot()
        run(sch._execute_send(bot, _text_post(content=content)))
        names = h.names()
        check("send_message 1 marta chaqirildi", len(bot.sent_messages) == 1, str(len(bot.sent_messages)))
        check("retry_post CHAQIRILMADI (dublikat yo'q)", "retry_post" not in names, str(names))
        check("mark_sent_by_key chaqirildi (DELIVERED)",
              "mark_sent_by_key" in names or "mark_post_as_sent" in names, str(names))
        check("scheduled_posts 'posted'",
              ("mark_post_status", (901, "posted")) in h.calls, str(h.args_of("mark_post_status")))
        check("'unknown' belgilanmadi", "mark_unknown_by_key" not in names, str(names))


def test_scheduler_timedout_absent_safe_retry():
    print("\n== 6b. _execute_send: post YO'Q (tasdiqlandi) → xavfsiz retry ==")
    import scheduler as sch
    with SchedulerHarness(probe_result={"status": "ok", "items": [{"text": "kanaldagi boshqa post"}]}) as h:
        bot = _TimedOutBot()
        run(sch._execute_send(bot, _text_post(content="Kanalga chiqmagan post matni")))
        names = h.names()
        check("retry_post chaqirildi (safe retry)", "retry_post" in names, str(names))
        check("mark_failed_by_key chaqirildi (backoff)",
              "mark_failed_by_key" in names, str(names))
        check("'unknown' belgilanmadi (yo'qligi tasdiqlandi)",
              "mark_unknown_by_key" not in names, str(names))


def test_scheduler_timedout_unavailable_verify_pending():
    print("\n== 6c. _execute_send: tasdiqlanmadi → verify_pending (ko'r-ko'rrona retry YO'Q) ==")
    import scheduler as sch
    with SchedulerHarness(probe_result={"status": "unavailable", "items": []}) as h:
        bot = _TimedOutBot()
        run(sch._execute_send(bot, _text_post(content="Kanal o'qilmagan post")))
        names = h.names()
        check("send AYNAN 1 marta (qayta yuborilmadi)", len(bot.sent_messages) == 1,
              str(len(bot.sent_messages)))
        check("mark_verify_pending_by_key chaqirildi (marker)",
              "mark_verify_pending_by_key" in names, str(names))
        check("retry_post chaqirildi (keyingi TEKSHIRUV uchun)",
              "retry_post" in names, str(names))
        check("birinchi urinishda 'unknown' YO'Q (hali tekshiriladi)",
              "mark_unknown_by_key" not in names, str(names))
        check("delivery kaliti marker bilan yozildi",
              bool(h.args_of("mark_verify_pending_by_key")), str(h.args_of("mark_verify_pending_by_key")))


def test_scheduler_presend_gate_blocks_duplicate():
    print("\n== 6d. Pre-send gate: AMBIGUOUS_VERIFY markeri → YUBORMASDAN dedup ==")
    import scheduler as sch
    text = "Avval chiqqan, lekin noaniq qolgan post matni"
    with SchedulerHarness(probe_result={"status": "ok", "items": [{"text": text}]},
                          claim_last_error="AMBIGUOUS_VERIFY attempt=1 | TimedOut") as h:
        class _NeverSendBot:
            def __init__(self):
                self.called = 0

            async def send_message(self, *a, **kw):
                self.called += 1
                return SimpleNamespace(message_id=1)

        bot = _NeverSendBot()
        run(sch._execute_send(bot, _text_post(content=text)))
        check("Telegramga UMUMAN yuborilmadi (0 duplikat)", bot.called == 0, str(bot.called))
        check("post 'posted' deb belgilandi (DELIVERED)",
              ("mark_post_status", (901, "posted")) in h.calls, str(h.args_of("mark_post_status")))
        check("retry_post yo'q", "retry_post" not in h.names(), str(h.names()))


def test_scheduler_album_present_delivered():
    print("\n== 6e. Albom: TimedOut + kanalda topilsa → DELIVERED (UNKNOWN emas) ==")
    import scheduler as sch
    caption = "Albom uchun caption matni"
    with SchedulerHarness(probe_result={"status": "ok", "items": [{"text": caption}]}) as h:
        bot = _TimedOutBot()
        run(sch._execute_send(bot, _album_post(caption=caption)))
        names = h.names()
        check("'unknown' belgilanmadi (post kanalda topildi)",
              "mark_unknown_by_key" not in names, str(names))
        check("retry_post yo'q (dublikat albom chiqmaydi)", "retry_post" not in names, str(names))
        check("post 'posted'", ("mark_post_status", (902, "posted")) in h.calls,
              str(h.args_of("mark_post_status")))


def test_scheduler_album_unavailable_unknown():
    print("\n== 6f. Albom: tasdiqlanmasa → UNKNOWN (eski konservativ xatti-harakat) ==")
    import scheduler as sch
    with SchedulerHarness(probe_result={"status": "unavailable", "items": []}) as h:
        bot = _TimedOutBot()
        run(sch._execute_send(bot, _album_post()))
        names = h.names()
        check("mark_unknown_by_key chaqirildi", "mark_unknown_by_key" in names, str(names))
        check("retry_post CHAQIRILMADI (blind retry yo'q)", "retry_post" not in names, str(names))
        check("scheduled_posts 'unknown'",
              ("mark_post_status", (902, "unknown")) in h.calls, str(h.args_of("mark_post_status")))


def main():
    print("=" * 70)
    print(" P0 (VAZIFA 2) — AMBIGUOUS DELIVERY & POST DEDUPLICATION")
    print("=" * 70)
    test_fingerprints()
    test_candidate_matching()
    test_probe_verdicts()
    test_resolve_ambiguous_present()
    test_resolve_ambiguous_absent()
    test_resolve_ambiguous_unavailable_defer()
    test_resolve_ambiguous_unavailable_exhausted()
    test_verify_marker_roundtrip()
    test_deliver_with_state_ambiguous_verify_present()
    test_deliver_with_state_ambiguous_verify_unavailable()
    test_local_lock_serializes_parallel_tasks()
    test_lock_release_and_acquire()
    test_cache_set_if_absent_atomic()
    test_scheduler_timedout_dedup_present()
    test_scheduler_timedout_absent_safe_retry()
    test_scheduler_timedout_unavailable_verify_pending()
    test_scheduler_presend_gate_blocks_duplicate()
    test_scheduler_album_present_delivered()
    test_scheduler_album_unavailable_unknown()
    print()
    print(f"JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES == 0:
        print("AMBIGUOUS DELIVERY & DEDUP — 100% YASHIL ✔")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
