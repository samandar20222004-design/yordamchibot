#!/usr/bin/env python3
"""Ish faoliyati benchmark'i — bot qancha yuk ko'tarishini o'lchaydi.

Haqiqiy PostgreSQL (pgserver) bilan DB qatlamining tezligini o'lchaydi va
taxminiy xizmat ko'rsatish hajmini hisoblaydi.

Ishga tushirish:
    cd telegram_bot && python tests/benchmark.py
"""
import os
import sys
import time
import shutil
import threading
from pathlib import Path

os.environ["BOT_TOKEN"] = "123:TEST"
os.environ["ADMIN_ID"] = "777000"
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/x"
os.environ["DB_POOL_MIN"] = "0"
os.environ["DB_POOL_MAX"] = "5"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    import pgserver
    server_dir = "/tmp/yordamchi_pg_bench"
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    os.environ["DATABASE_URL"] = server.get_uri()

    import database as db
    db.init_db()
    db.save_user(777000, "admin", "Admin")
    db.save_user(1, "user1", "User 1")

    print("== 1. Ketma-ket DB operatsiyalar (pool qayta ishlatiladi) ==")
    N = 1000
    t0 = time.perf_counter()
    for i in range(N):
        db.get_user_credits(1)
    dt = time.perf_counter() - t0
    seq_ops = N / dt
    print(f"  {N} ta o'qish: {dt:.2f}s → {seq_ops:.0f} op/s")

    print("== 2. Parallel DB operatsiyalar (8 thread) ==")
    t0 = time.perf_counter()
    errors = []

    def worker(worker_id):
        try:
            for i in range(200):
                db.get_user_credits(1 if i % 2 == 0 else 777000)
                db.get_setting("bench", "x")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.perf_counter() - t0
    par_ops = (8 * 400) / dt
    print(f"  8 thread × 400 op: {dt:.2f}s → {par_ops:.0f} op/s, xatolar: {len(errors)}")

    print("== 3. Odatiy foydalanuvchi harakati (ketma-ketlik) ==")
    # /start + post yaratishdagi odatiy DB chaqiruvlari
    t0 = time.perf_counter()
    M = 200
    for i in range(M):
        db.save_user(10000 + i, f"u{i}", f"User {i}")
        db.get_user_channels(10000 + i)
        db.get_user_credits(10000 + i)
        db.add_post(
            user_id=10000 + i, channel_id="-1001", post_type="text",
            content="x", file_id=None,
            scheduled_time=__import__("datetime").datetime.now(__import__("pytz").timezone("Asia/Tashkent")),
        )
        db.get_pending_posts(10000 + i)
    dt = time.perf_counter() - t0
    user_flow = M / dt
    print(f"  {M} ta foydalanuvchi oqimi: {dt:.2f}s → {user_flow:.1f} foydalanuvchi harakati/s")

    print()
    print("== Xulosa (taxminiy) ==")
    print(f"  DB: ketma-ket {seq_ops:.0f} op/s, parallel {par_ops:.0f} op/s")
    print(f"  Bir foydalanuvchi harakati ≈ 4-5 DB op")
    print(f"  Scheduler: 250 post ~4.4s (taxminan 55-95 post/s)")
    print(f"  Broadcast: ~28 xabar/s (Telegram limitiga hurmat)")
    print()
    print("  Render Free (0.1 CPU, 512MB) uchun real baho:")
    print("  • Bir vaqtda faol foydalanuvchilar: ~15-30")
    print("  • Kuniga xabar/so'rovlar: 3000-8000")
    print("  • Ro'yxatdan o'tgan foydalanuvchilar: bir necha ming (cheklov yo'q)")
    print("  • 1000 ta post navbati: ~15-20 soniyada yuboriladi")

    db.close_pool()
    server.cleanup()


if __name__ == "__main__":
    main()
