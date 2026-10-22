#!/usr/bin/env python3
"""PostAssist yuk testi (sig'imni o'lchash). Ikki rejim:

1) ``local`` — O'Z kompyuteringizda/ sinov serverida, SINOV bazasi bilan (production bazaga TEGMAYDI):
     python scripts/loadtest.py local --db-url postgresql://u:p@127.0.0.1:5432/sinov_baza
   Stsenariylar (hammasi haqiqiy kod, soxta Telegram):
     scheduler — N post M kanalga yuborish tezligi (Telegram javob kechikishi taqlid qilinadi: --tg-latency)
     db        — botning odatiy o'qish/yozish so'rovlari parallel (oqimlar soni bo'yicha)
     miniapp   — Mini App API (/me, /channels, /scheduled-posts) parallel foydalanuvchilar bilan
   Boshlanishda ``loadtest_`` prefiksli foydalanuvchilar yoziladi va oxirida O'CHIRILADI.

2) ``remote`` — joylashtirilgan (deploy qilingan) Mini App'ga faqat O'QISH so'rovlari bilan (xavfsiz):
     python scripts/loadtest.py remote --url https://sizning.domen --init-data "query_id=...&hash=..."
   ``--init-data`` — Mini App'ni haqiqiy Telegram'da ochib olingan ``Telegram.WebApp.initData`` (qisqa muddatli: yangi oling).
   Bitta foydalanuvchi bilan o'lchanadi, shuning uchun foydalanuvchi bo'yicha tezlik chegarasi (rate limit)
   ``429`` berishi mumkin — bu xatolik emas, himoya; hisobotda alohida ko'rsatiladi.

Natija: jadval + ``--json fayl`` + yakuniy xulosa (p95 < 1,5 s va xato < 1% — «yaxshi»).
Telegram'ning o'z chegarasi: ~30 xabar/s (umumiy), bitta kanalga ~20/daqiqa — testda taqlid qilinmaydi, hisobotda eslatiladi.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "loadtest_"
BASE_USER = 7_700_000_000  # sinov foydalanuvchilari ID oralig'i (haqiqiy Telegram ID'laridan tashqarida)


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def stats_row(name, lat_ms, errors, elapsed, extra=""):
    n = len(lat_ms)
    return {"name": name, "ok": n, "errors": errors, "seconds": round(elapsed, 2), "rps": round(n / elapsed, 1) if elapsed else 0,
            "p50_ms": round(pct(lat_ms, 50), 1), "p95_ms": round(pct(lat_ms, 95), 1), "p99_ms": round(pct(lat_ms, 99), 1),
            "max_ms": round(max(lat_ms), 1) if lat_ms else 0, "note": extra}


def print_table(rows):
    print(f"\n{'stsenariy':<34}{'ok':>7}{'xato':>6}{'s':>7}{'so`rov/s':>10}{'p50ms':>8}{'p95ms':>8}{'p99ms':>8}{'maxms':>8}")
    for r in rows:
        print(f"{r['name']:<34}{r['ok']:>7}{r['errors']:>6}{r['seconds']:>7}{r['rps']:>10}{r['p50_ms']:>8}{r['p95_ms']:>8}{r['p99_ms']:>8}{r['max_ms']:>8}"
              + (f"   {r['note']}" if r["note"] else ""))


def verdict(rows):
    bad = [r for r in rows if r["ok"] + r["errors"] and (r["errors"] / (r["ok"] + r["errors"]) > 0.01 or r["p95_ms"] > 1500) and not r["name"].startswith("scheduler")]
    print("\nXULOSA:", "✅ barcha stsenariylar chegarada (p95 < 1,5 s, xato < 1%)" if not bad else
          "⚠️ chegaradan oshgan: " + ", ".join(r["name"] for r in bad))


# ------------------------------------------------------------------ remote
async def remote(args) -> list:
    import aiohttp

    init = args.init_data or os.getenv("LOADTEST_INIT_DATA", "")
    if not init:
        sys.exit("--init-data (yoki LOADTEST_INIT_DATA) kerak: Telegram'da Mini App'ni oching va Telegram.WebApp.initData ni nusxalang")
    base = args.url.rstrip("/") + "/api/v1"
    paths = ["/me", "/channels", "/scheduled-posts", "/draft"]
    rows = []
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"Authorization": "tma " + init}) as sess:
        async with sess.get(base + "/me") as r:
            if r.status != 200:
                sys.exit(f"/me javobi {r.status}: initData eskirgan yoki Mini App yoqilmagan (MINIAPP_ENABLED=1)")
        for level in args.levels:
            lat, errs, limited = [], 0, 0
            stop = time.perf_counter() + args.duration

            async def worker(i):
                nonlocal errs, limited
                n = 0
                while time.perf_counter() < stop:
                    path = paths[(i + n) % len(paths)]
                    n += 1
                    t0 = time.perf_counter()
                    try:
                        async with sess.get(base + path) as resp:
                            await resp.read()
                            if resp.status == 429:
                                limited += 1
                            elif resp.status >= 500 or resp.status in (401, 403):
                                errs += 1
                            else:
                                lat.append((time.perf_counter() - t0) * 1000)
                    except Exception:  # noqa: BLE001
                        errs += 1

            t0 = time.perf_counter()
            await asyncio.gather(*(worker(i) for i in range(level)))
            rows.append(stats_row(f"remote GET, {level} parallel", lat, errs, time.perf_counter() - t0,
                                  f"429(rate limit)={limited}" if limited else ""))
    return rows


# ------------------------------------------------------------------ local
def prepare_env(db_url: str, allow_remote: bool):
    host = urlparse(db_url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1") and not allow_remote:
        sys.exit(f"Xavfsizlik: baza '{host}' lokal emas. Production bazaga yuk BERMANG; sinov bazasi bo'lsa --allow-remote-db qo'shing.")
    os.environ["DATABASE_URL"] = db_url
    os.environ.setdefault("BOT_TOKEN", "123456:LOADTEST_TOKEN_NOT_REAL")
    os.environ.setdefault("ADMIN_ID", "123456789")
    os.environ.setdefault("DB_POOL_MAX", "10")
    sys.path.insert(0, str(ROOT / "telegram_bot"))
    sys.path.insert(0, str(ROOT / "tests"))


class LatencyBot:
    """Telegram'ga o'xshash: har yuborish ``latency`` soniya (parallel), natijani sanaydi."""

    def __init__(self, latency):
        self.latency = latency
        self.sent = 0
        self.lock = threading.Lock()

    async def send_message(self, chat_id, text=None, **kw):
        await asyncio.sleep(self.latency)
        with self.lock:
            self.sent += 1
            return SimpleNamespace(message_id=self.sent)

    async def _media(self, chat_id, *a, caption=None, **kw):
        return await self.send_message(chat_id, caption)

    send_photo = send_video = send_animation = send_document = send_audio = send_voice = _media

    async def delete_message(self, *a, **k):
        return True


def seed(db, users, posts_per_user):
    from datetime import datetime, timedelta

    import pytz

    tz = pytz.timezone("Asia/Tashkent")
    due = datetime.now(tz) - timedelta(minutes=1)
    ids = []
    for i in range(users):
        uid = BASE_USER + i
        db.save_user(uid, f"{PREFIX}{i}", f"LoadTest {i}")
        db.save_channel(uid, f"-100{9_000_000_000 + i}", f"{PREFIX}kanal{i}")
        ids.append(uid)
    n = 0
    for i, uid in enumerate(ids):
        for j in range(posts_per_user):
            db.add_post(user_id=uid, channel_id=f"-100{9_000_000_000 + i}", post_type="text", content=f"loadtest post {i}-{j}",
                        file_id=None, scheduled_time=due)
            n += 1
    return ids, n


def cleanup(db):
    with db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM scheduled_posts WHERE content LIKE 'loadtest post %%'")
        cur.execute("DELETE FROM channels WHERE channel_title LIKE %s", (PREFIX + "kanal%",))
        cur.execute("DELETE FROM users WHERE username LIKE %s", (PREFIX + "%",))


def scenario_scheduler(db, args, rows):
    import scheduler as sched

    users, per = args.users, args.posts_per_user
    ids, total = seed(db, users, per)
    bot = LatencyBot(args.tg_latency)
    t0 = time.perf_counter()
    for _ in range(3):  # bir nechta tick: navbat bo'shaguncha
        asyncio.run(sched.check_and_send_posts(bot))
        if bot.sent >= total:
            break
    el = time.perf_counter() - t0
    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE content LIKE 'loadtest post %%' AND status = 'posted'")
        posted = cur.fetchone()[0]
    rows.append({"name": f"scheduler {total} post/{users} kanal", "ok": posted, "errors": total - posted, "seconds": round(el, 2),
                 "rps": round(posted / el, 1), "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0,
                 "note": f"Telegram kechikishi {int(args.tg_latency * 1000)} ms taqlid; haqiqiy chegara ~30 post/s"})


def scenario_db(db, args, rows):
    ids, _ = seed(db, min(args.users, 200), 3)
    for threads in args.levels:
        lat, errs = [], [0]
        lock = threading.Lock()
        stop = time.perf_counter() + args.duration

        def work(k):
            i = 0
            while time.perf_counter() < stop:
                uid = ids[(k + i) % len(ids)]
                i += 1
                t0 = time.perf_counter()
                try:
                    with db.db_cursor() as cur:  # keshni chetlab: haqiqiy DB so'rovi (foydalanuvchi + kanallar + rejalangan postlar)
                        cur.execute("SELECT language_code, plan_type FROM users WHERE user_id = %s", (uid,))
                        cur.fetchone()
                        cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s", (uid,))
                        cur.fetchall()
                        cur.execute("SELECT id, status, scheduled_time FROM scheduled_posts WHERE user_id = %s ORDER BY scheduled_time LIMIT 20", (uid,))
                        cur.fetchall()
                    ms = (time.perf_counter() - t0) * 1000
                    with lock:
                        lat.append(ms)
                except Exception:  # noqa: BLE001
                    errs[0] += 1

        ts = [threading.Thread(target=work, args=(k,)) for k in range(threads)]
        t0 = time.perf_counter()
        [t.start() for t in ts]
        [t.join() for t in ts]
        rows.append(stats_row(f"db: bot so'rovi, {threads} oqim", lat, errs[0], time.perf_counter() - t0, "har 'op' = 3 ta so'rov (kesh yo'q)"))


async def scenario_miniapp(db, args, rows):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from miniapp_testkit import FAKE_TOKEN, NOW, make_init_data

    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings

    ids, _ = seed(db, min(args.users, 200), 2)
    settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                              "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=settings.max_inflight_db)
    service = MiniAppService(settings, runner)

    class Null:  # tezlik chegarasi o'chirilgan: API'ning o'zini o'lchaymiz
        async def hit(self, *a, **k):
            return None

    api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service)
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)
    client = TestClient(TestServer(app))
    await client.start_server()
    paths = ["/me", "/channels", "/scheduled-posts"]
    heads = {uid: {"Authorization": "tma " + make_init_data(uid)} for uid in ids}
    try:
        for level in args.levels:
            lat, errs, busy = [], 0, 0
            stop = time.perf_counter() + args.duration

            async def worker(k):
                nonlocal errs, busy
                i = 0
                while time.perf_counter() < stop:
                    uid = ids[(k + i) % len(ids)]
                    path = paths[i % len(paths)]
                    i += 1
                    t0 = time.perf_counter()
                    try:
                        r = await client.get("/api/v1" + path, headers=heads[uid])
                        await r.read()
                        if r.status == 503:
                            busy += 1
                        elif r.status >= 400:
                            errs += 1
                        else:
                            lat.append((time.perf_counter() - t0) * 1000)
                    except Exception:  # noqa: BLE001
                        errs += 1

            t0 = time.perf_counter()
            await asyncio.gather(*(worker(k) for k in range(level)))
            rows.append(stats_row(f"miniapp API, {level} parallel", lat, errs, time.perf_counter() - t0,
                                  f"503 (navbat to'lgan)={busy}" if busy else ""))
    finally:
        await client.close()


def local(args) -> list:
    prepare_env(args.db_url, args.allow_remote_db)
    import database as db

    db.init_db()
    rows: list = []
    cleanup(db)
    try:
        wanted = args.scenarios.split(",")
        if "db" in wanted:
            scenario_db(db, args, rows)
            cleanup(db)
        if "miniapp" in wanted:
            asyncio.run(scenario_miniapp(db, args, rows))
            cleanup(db)
        if "scheduler" in wanted:
            scenario_scheduler(db, args, rows)
    finally:
        cleanup(db)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="PostAssist yuk testi")
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("local", "remote"):
        p = sub.add_parser(name)
        p.add_argument("--levels", type=lambda s: [int(x) for x in s.split(",")], default=[10, 50, 200], help="parallel foydalanuvchilar darajalari")
        p.add_argument("--duration", type=float, default=8.0, help="har daraja necha soniya")
        p.add_argument("--json", help="natijani JSON faylga yozish")
    lp = sub.choices["local"]
    lp.add_argument("--db-url", required=True, help="SINOV bazasi (production emas!)")
    lp.add_argument("--allow-remote-db", action="store_true")
    lp.add_argument("--users", type=int, default=200)
    lp.add_argument("--posts-per-user", type=int, default=1, help="har kanalga bir vaqtda nechta post (1 = odatiy; >1 — bitta kanalga to`planish, kanal chegarasi 1 post/s)")
    lp.add_argument("--tg-latency", type=float, default=0.3, help="taqlid qilinadigan Telegram javob kechikishi (s)")
    lp.add_argument("--scenarios", default="db,miniapp,scheduler")
    rp = sub.choices["remote"]
    rp.add_argument("--url", required=True)
    rp.add_argument("--init-data", default="")
    args = ap.parse_args()
    rows = asyncio.run(remote(args)) if args.mode == "remote" else local(args)
    print_table(rows)
    verdict(rows)
    print("Eslatma: Telegram'ning o'z chegarasi (~30 xabar/s umumiy, bitta kanalga ~20/daqiqa) va masofadagi baza kechikishi natijaga ta'sir qiladi.")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
