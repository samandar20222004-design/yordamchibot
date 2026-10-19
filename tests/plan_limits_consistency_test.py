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
check("config: navbat limiti free=40, pro=300, ultra=900 (env bilan o'zgartiriladi)",
      (config.FREE_QUEUE_MAX_POSTS, config.PRO_QUEUE_MAX_POSTS, config.ULTRA_QUEUE_MAX_POSTS) == (40, 300, 900),
      f"{config.FREE_QUEUE_MAX_POSTS} {config.PRO_QUEUE_MAX_POSTS} {config.ULTRA_QUEUE_MAX_POSTS}")
check("config: kanallar 3/10/30 va kunlik AI 5/40/100",
      (config.FREE_MAX_CHANNELS, config.PRO_MAX_CHANNELS, config.ULTRA_MAX_CHANNELS) == (3, 10, 30)
      and (config.FREE_DAILY_AI, config.PRO_DAILY_AI, config.ULTRA_DAILY_AI) == (5, 40, 100))
check("config: ovozli rejalash free=1 (butun umr), PRO=20, ULTRA=100 (kuniga)",
      (config.FREE_VOICE_SCHEDULE_TOTAL, config.PRO_VOICE_SCHEDULE_DAILY, config.ULTRA_VOICE_SCHEDULE_DAILY) == (1, 20, 100))
from miniapp_api.service import plan_limits  # noqa: E402
from repositories import users_repository as UR  # noqa: E402

check("repozitoriy navbat limiti config'dan (nusxa emas)", UR.FREE_QUEUE_MAX_POSTS == getattr(config, "FREE_QUEUE_MAX_POSTS", None))
pl = plan_limits()
for name, mx, ai, qu in (("free", config.FREE_MAX_CHANNELS, config.FREE_DAILY_AI, config.FREE_QUEUE_MAX_POSTS),
                         ("pro", config.PRO_MAX_CHANNELS, config.PRO_DAILY_AI, config.PRO_QUEUE_MAX_POSTS),
                         ("ultra", config.ULTRA_MAX_CHANNELS, config.ULTRA_DAILY_AI, config.ULTRA_QUEUE_MAX_POSTS)):
    check(f"Mini App limitlari config bilan bir xil ({name})",
          {k: pl[name][k] for k in ("max_channels", "daily_ai_requests", "queued_posts")}
          == {"max_channels": mx, "daily_ai_requests": ai, "queued_posts": qu}, str(pl[name]))
check("repozitoriy PLAN_LIMITS (kanal/AI) ham config bilan bir xil: free/pro/ultra/pro_legacy/enterprise",
      all(UR.PLAN_LIMITS[k] == {"max_channels": config.TIER_LIMITS[k]["max_channels"], "daily_ai_requests": config.TIER_LIMITS[k]["daily_ai_requests"]}
          for k in ("free", "pro", "ultra", "pro_legacy", "enterprise")))

# ---- DB'siz: chegirma haqiqiy narxlardan ----
disc = getattr(config, "plan_discount_percent", None)
check("plan_discount_percent mavjud", callable(disc))
if callable(disc):
    cat = config.TARIFF_CATALOG
    got = {k: disc(cat[k]["uzs"], cat["1m" if not k.startswith("u") else "u1m"]["uzs"], cat[k]["months"]) for k in cat}
    check("haqiqiy tejam (so'm narxlaridan): PRO 3/6/12 oy = 14/22/30%, ULTRA = 15/19/25%",
          (got["3m"], got["6m"], got["1y"], got["u3m"], got["u6m"], got["u1y"]) == (14, 22, 30, 15, 19, 25), str(got))
    check("chegirma yo'q / noto'g'ri qiymat -> 0 (manfiy emas)", disc(100, 100, 1) == 0 and disc(300, 75, 3) == 0 and disc(0, 0, 0) == 0)

# ---- DB'siz: tarif kartasi navbat limitini ko'rsatadi ----
import handlers.subscription as SUB  # noqa: E402

for lang, word in (("uz", "Navbat"), ("ru", "Очередь"), ("en", "queue")):
    def queue_line(plan_type):
        card = SUB._build_subscription_card({"plan_type": plan_type, "expires_at": None if plan_type == "enterprise" else
                                             datetime.now(timezone.utc) + timedelta(days=5), "ai_used": 0}, lang)
        return [ln for ln in card.splitlines() if word.lower() in ln.lower() and "<b>" in ln and "ULTRA" not in ln]
    fl, pl_, ul, el = queue_line("free"), queue_line("pro"), queue_line("ultra"), queue_line("enterprise")
    check(f"[{lang}] free kartada navbat limiti qatori ({config.FREE_QUEUE_MAX_POSTS})", len(fl) == 1 and ">40<" in fl[0], str(fl))
    check(f"[{lang}] pro kartada navbat 300 (cheksiz deb ko'rsatilmaydi)", len(pl_) == 1 and ">300<" in pl_[0], str(pl_))
    check(f"[{lang}] ultra kartada navbat 900", len(ul) == 1 and ">900<" in ul[0], str(ul))
    check(f"[{lang}] enterprise (muddatsiz) kartada cheksiz", len(el) == 1 and ">40<" not in el[0] and ">300<" not in el[0] and ">900<" not in el[0], str(el))
free_uz = SUB._build_subscription_card({"plan_type": "free", "expires_at": None, "ai_used": 0}, "uz")
check("karta '-40%' qat'iy yozuvini ishlatmaydi (haqiqiy tejam)", "-40%" not in free_uz, free_uz[-400:])
tier_uz = SUB._build_tier_card("pro", "uz") + SUB._build_tier_card("ultra", "uz")
check("tarif kartalarida narx, Stars va haqiqiy tejam foizi bor (-14% / -22% / -30%; -15% / -19% / -25%)",
      all(t in tier_uz for t in ("29 000", "245 000", "620 000", "−14%", "−22%", "−30%", "−15%", "−19%", "−25%")) and "{" not in tier_uz, tier_uz[:200])

# ---- DB'siz: Stars tugma narxlari config'dan (qattiq yozilgan emas) ----
from keyboards.inline import get_intl_tariffs_keyboard  # noqa: E402
from locales.translations import get_text  # noqa: E402

for lang in ("uz", "ru", "en"):
    raw = [get_text(k, lang) for k in ("intl_tariff_tpl", "tariff_btn_tpl")]
    check(f"[{lang}] tugma matnlarida qattiq narx yo'q (shablon)", "{stars}" in raw[0] and "{uzs}" in raw[1], str(raw))
orig = dict(config.STARS_PLANS["stars_1m"]), dict(config.STARS_PLANS["stars_1y"])
config.STARS_PLANS["stars_1m"]["stars"], config.STARS_PLANS["stars_1y"]["stars"] = 99, 777
try:
    intl = [b.text for row in get_intl_tariffs_keyboard("uz").inline_keyboard for b in row]
    check("tarif o'zgarsa (99/777) xalqaro tarif klaviaturasi yangi narxni ko'rsatadi", any("99★" in t for t in intl) and any("777★" in t for t in intl), str(intl))
finally:
    config.STARS_PLANS["stars_1m"].update(orig[0])
    config.STARS_PLANS["stars_1y"].update(orig[1])
labels = [b.text for row in get_intl_tariffs_keyboard("uz").inline_keyboard for b in row]
check("standart narxlarda PRO Stars (xalqaro narx, O'zbekistondan 1,7x): 195★/510★/910★/1650★, shablon qolmaydi",
      all(any(f"{n}★" in t for t in labels) for n in (195, 510, 910, 1650)) and not any("{" in t for t in labels), str(labels))
ultra_labels = [b.text for row in get_intl_tariffs_keyboard("uz", plan_order=("u1m", "u3m", "u6m", "u1y")).inline_keyboard for b in row]
check("standart narxlarda ULTRA Stars (xalqaro narx): 470★/1180★/2260★/4180★",
      all(any(f"{n}★" in t for t in ultra_labels) for n in (470, 1180, 2260, 4180)), str(ultra_labels))

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
        for i in range(config.FREE_QUEUE_MAX_POSTS):
            q("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
              "VALUES (%s, %s, 'text', %s, %s, 'pending')", (uid, chan, f"p{i}", now + timedelta(days=1 + i)))

    lim = config.FREE_QUEUE_MAX_POSTS
    r = db.check_queue_limit(U_FREE)
    check("free, 40 post: navbat to'la (False, 40, 40)", r == (False, lim, lim) and lim == 40, str(r))
    r = db.check_queue_limit(U_PRO)
    check("faol PRO, 40 post: limit 300 (True, 40, 300)", r == (True, 40, config.PRO_QUEUE_MAX_POSTS) and r[2] == 300, str(r))
    r = db.check_queue_limit(U_ENT)
    check("muddatsiz enterprise: cheksiz (999)", r[0] is True and r[2] == config.TIER_LIMITS["enterprise"]["queued_posts"] == 999, str(r))
    r = db.check_queue_limit(U_EXP)
    check("MUDDATI O'TGAN PRO (sweep hali tushirmagan): free limiti qo'llanadi (False, 40, 40)", r == (False, 40, lim), str(r))
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
