#!/usr/bin/env python3
"""Tarif limitlari: e'lon qilingan == haqiqatan majburlanadigan (real PostgreSQL + DB'siz qism).

Topilgan nomuvofiqliklar:
  * `check_queue_limit` obuna MUDDATINI hisobga olmasdi: muddati o'tgan, lekin sweep hali tushirmagan PRO cheksiz navbat olardi
    (kanal/AI limiti va Mini App esa muddatni hisobga oladi);
  * navbat limiti (5 / 999) kodda qattiq yozilgan, config'da yo'q va Mini App'da alohida nusxa edi;
  * bot tarif kartasi kanal va AI limitini ko'rsatardi, NAVBAT limitini (haqiqatan majburlanadi) ko'rsatmasdi;
  * yillik tarifdagi "-40%" qat'iy yozilgan edi (haqiqiy tejam narxlardan hisoblanadi: ~39%).
"""
from __future__ import annotations

import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_planlimits")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:PLAN_LIMITS_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
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


import config  # noqa: E402

print("== Tarif limitlari: yagona manba va e'lon == majburlash ==")

# ---- DB'siz: yagona manba ----
check("config: navbat limiti free=5, pro=999 (env bilan o'zgartiriladi)",
      getattr(config, "FREE_QUEUE_MAX_POSTS", None) == 5 and getattr(config, "PRO_QUEUE_MAX_POSTS", None) == 999,
      f"{getattr(config, 'FREE_QUEUE_MAX_POSTS', None)} {getattr(config, 'PRO_QUEUE_MAX_POSTS', None)}")
from miniapp_api.service import plan_limits  # noqa: E402
from repositories import users_repository as UR  # noqa: E402

check("repozitoriy navbat limiti config'dan (nusxa emas)", UR.FREE_QUEUE_MAX_POSTS == getattr(config, "FREE_QUEUE_MAX_POSTS", None))
pl = plan_limits()
check("Mini App limitlari config bilan bir xil (free)",
      pl["free"] == {"max_channels": config.FREE_MAX_CHANNELS, "daily_ai_requests": config.FREE_DAILY_AI,
                     "queued_posts": getattr(config, "FREE_QUEUE_MAX_POSTS", None)}, str(pl["free"]))
check("Mini App limitlari config bilan bir xil (pro)",
      pl["pro"] == {"max_channels": config.PRO_MAX_CHANNELS, "daily_ai_requests": config.PRO_DAILY_AI,
                    "queued_posts": getattr(config, "PRO_QUEUE_MAX_POSTS", None)}, str(pl["pro"]))

# ---- DB'siz: chegirma haqiqiy narxlardan ----
disc = getattr(config, "plan_discount_percent", None)
check("plan_discount_percent mavjud", callable(disc))
if callable(disc):
    check("yillik chegirma haqiqiy narxdan: 550 Stars vs 12x75 -> 38%..40% oralig'ida va butun son",
          isinstance(disc(550, 75, 12), int) and 38 <= disc(550, 75, 12) <= 40, str(disc(550, 75, 12)))
    check("3 oylik: 175 vs 3x75 -> 22%", disc(175, 75, 3) == 22, str(disc(175, 75, 3)))
    check("chegirma yo'q / noto'g'ri qiymat -> 0 (manfiy emas)", disc(100, 100, 1) == 0 and disc(300, 75, 3) == 0 and disc(0, 0, 0) == 0)

# ---- DB'siz: tarif kartasi navbat limitini ko'rsatadi ----
import handlers.subscription as SUB  # noqa: E402

for lang, word in (("uz", "Navbat"), ("ru", "Очередь"), ("en", "queue")):
    free = SUB._build_subscription_card({"plan_type": "free", "expires_at": None, "ai_used": 0}, lang)
    pro = SUB._build_subscription_card({"plan_type": "pro", "expires_at": None, "ai_used": 0}, lang)
    fl = [ln for ln in free.splitlines() if word.lower() in ln.lower() and "<b>" in ln]
    pl_ = [ln for ln in pro.splitlines() if word.lower() in ln.lower() and "<b>" in ln]
    check(f"[{lang}] free kartada navbat limiti qatori ({config.FREE_QUEUE_MAX_POSTS})", len(fl) == 1 and "5" in fl[0], str(fl))
    check(f"[{lang}] pro kartada navbat cheksiz deb ko'rsatiladi", len(pl_) == 1 and "5" not in pl_[0], str(pl_))
free_uz = SUB._build_subscription_card({"plan_type": "free", "expires_at": None, "ai_used": 0}, "uz")
check("karta '-40%' qat'iy yozuvini ishlatmaydi (haqiqiy tejam)", "-40%" not in free_uz, free_uz[-400:])

# ---- DB'siz: Stars tugma narxlari config'dan (qattiq yozilgan emas) ----
from keyboards.inline import get_intl_tariffs_keyboard  # noqa: E402
from locales.translations import get_text  # noqa: E402

for lang in ("uz", "ru", "en"):
    raw = [get_text(k, lang) for k in ("sub_pay_1m", "sub_pay_3m_full", "intl_tariff_1y")]
    check(f"[{lang}] Stars tugma matnlarida qattiq narx yo'q ({{stars}} shablon)", all("{stars}" in t for t in raw), str(raw))
orig = dict(config.STARS_PLANS["stars_1m"]), dict(config.STARS_PLANS["stars_1y"])
config.STARS_PLANS["stars_1m"]["stars"], config.STARS_PLANS["stars_1y"]["stars"] = 99, 777
try:
    labels = [b.text for row in SUB._get_subscription_keyboard("free", "en").inline_keyboard for b in row]
    check("tarif o'zgarsa (99/777) free tugmalari yangi narxni ko'rsatadi", any("99★" in t for t in labels) and any("777★" in t for t in labels), str(labels))
    stars_kb = [b.text for row in SUB._get_stars_keyboard("ru").inline_keyboard for b in row]
    check("Stars tanlash klaviaturasi ham", any("99★" in t for t in stars_kb) and any("777★" in t for t in stars_kb), str(stars_kb))
    intl = [b.text for row in get_intl_tariffs_keyboard("uz").inline_keyboard for b in row]
    check("xalqaro tarif klaviaturasi ham", any("99★" in t for t in intl) and any("777★" in t for t in intl), str(intl))
finally:
    config.STARS_PLANS["stars_1m"].update(orig[0]); config.STARS_PLANS["stars_1y"].update(orig[1])
labels = [b.text for row in SUB._get_stars_keyboard("uz").inline_keyboard for b in row]
check("standart narxlarda eski ko'rinish saqlanadi (75★/175★/550★), shablon qolmaydi",
      any("75★" in t for t in labels) and any("175★" in t for t in labels) and any("550★" in t for t in labels) and not any("{" in t for t in labels), str(labels))

# ---- Real PG: muddati o'tgan PRO navbat limiti ----
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q — DB qismi o'tkazildi")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=1")
    sys.exit(0 if failed == 0 else 1)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

U_FREE, U_PRO, U_EXP, U_ENT = 9_650_001, 9_650_002, 9_650_003, 9_650_004
CH = "-1009650001"
USERS = (U_FREE, U_PRO, U_EXP, U_ENT)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    for uid in USERS:
        q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (uid,))
        q("DELETE FROM scheduled_posts WHERE user_id = %s", (uid,))
        q("DELETE FROM channels WHERE user_id = %s", (uid,))
        q("DELETE FROM users WHERE user_id = %s", (uid,))


cleanup()
try:
    now = datetime.now(timezone.utc)
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, 'qf', 'free')", (U_FREE,))
    q("INSERT INTO users (user_id, username, plan_type, subscription_expires_at) VALUES (%s, 'qp', 'pro', %s)", (U_PRO, now + timedelta(days=10)))
    q("INSERT INTO users (user_id, username, plan_type, subscription_expires_at) VALUES (%s, 'qe', 'pro', %s)", (U_EXP, now - timedelta(hours=1)))
    q("INSERT INTO users (user_id, username, plan_type, subscription_expires_at) VALUES (%s, 'qn', 'enterprise', NULL)", (U_ENT,))
    for n, uid in enumerate(USERS):
        chan = f"-10096500{n:02d}"
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'PL', TRUE)", (uid, chan))
        for i in range(5):
            q("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
              "VALUES (%s, %s, 'text', %s, %s, 'pending')", (uid, chan, f"p{i}", now + timedelta(days=1 + i)))

    lim = config.FREE_QUEUE_MAX_POSTS
    r = db.check_queue_limit(U_FREE)
    check("free, 5 post: navbat to'la (False, 5, 5)", r == (False, 5, lim), str(r))
    r = db.check_queue_limit(U_PRO)
    check("faol PRO, 5 post: limit yo'q (True, 5, 999)", r == (True, 5, config.PRO_QUEUE_MAX_POSTS), str(r))
    r = db.check_queue_limit(U_ENT)
    check("muddatsiz enterprise: limit yo'q", r[0] is True and r[2] == config.PRO_QUEUE_MAX_POSTS, str(r))
    r = db.check_queue_limit(U_EXP)
    check("MUDDATI O'TGAN PRO (sweep hali tushirmagan): free limiti qo'llanadi (False, 5, 5)", r == (False, 5, lim), str(r))
    plan = q("SELECT plan_type FROM users WHERE user_id = %s", (U_EXP,))[0][0]
    check("muddati o'tgan PRO lazy ravishda 'free' qilindi (kanal/AI limiti bilan bir xil)", plan == "free", plan)
    # kanal limiti shu foydalanuvchi uchun allaqachon muddatni hisobga olgan (taqqoslash)
    q("UPDATE users SET plan_type = 'pro', subscription_expires_at = %s WHERE user_id = %s", (now - timedelta(hours=1), U_EXP))
    ch_ok, _cnt, ch_max = db.check_channel_limit(U_EXP)
    check("kanal limiti ham free (muddat hisobga olinadi): bir xil mantiq", ch_max == config.FREE_MAX_CHANNELS, str(ch_max))
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
