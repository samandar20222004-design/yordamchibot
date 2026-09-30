# -*- coding: utf-8 -*-
"""
=====================================================================
 🗄 DATABASE — CORE RUNTIME + REPOSITORY FACADE
=====================================================================

PostAssist V2 — faza 4: database modularizatsiyasi va repository pattern.

Bu modul endi **ikki qatlamdan** iborat:

**1) CORE RUNTIME** (bu faylda qoladi)
    ulanish pool'i (``_WarmPool``), atomik tranzaksiyalar
    (``db_transaction`` / ``transaction`` / ``db_atomic``), ichki TTL +
    profil keshlari, sxema bootstrap'i (``init_db`` / ``_init_db_once``),
    integritet tekshiruvlari, ulanish/offload leak o'lchovi va ``run_db``
    (sync -> thread offload).

**2) FACADE** (faylning oxiri)
    domain ma'lumotlariga kirish funksiyalari endi
    ``telegram_bot/repositories/`` paketidagi repository modullarida
    joylashgan; bu fayl ularni **o'z nomi bilan qayta eksport qiladi**.

Shu tariqa mavjud ``import database as db`` va ``from database import X``
chaqiruvlarining BARCHASI o'zgarishsiz ishlaydi (backward compatibility),
hamda yangi kod to'g'ridan-to'g'ri repository'ga murojaat qila oladi::

    from repositories.posts_repository import get_due_posts

Muhim: repository modullari yadroga ``from database import ...`` emas,
``repositories.runtime`` orqali **kech bog'lanadi** — shuning uchun
mock nuqtalari (``patch("database.db_cursor")``) saqlanadi.

Qatlamlar chizmasi::

    handlers / services / scheduler          tests (13 000+ tekshiruv)
                 |  import database as db             |
                 v                                    v
    +--------------------------------------------------------+
    |  telegram_bot/database.py                              |
    |   [CORE]   pool . transactions . cache . schema        |
    |   [FACADE] from repositories.<x>_repository import ...  |
    +---------------------------+----------------------------+
                                |  kech bog'lanish (runtime)
        +---------------+-------+-------+---------------+
        v               v               v               v
  repositories/   repositories/   repositories/   repositories/
    users_...         posts_...     payments_...     audit_...
"""


import os

import asyncio

import contextvars

import functools

import itertools as _itertools

import logging

import threading

import time as _time

from collections import OrderedDict

from datetime import datetime

from contextlib import contextmanager, asynccontextmanager

import psycopg2

from psycopg2.pool import ThreadedConnectionPool

import pytz

from config import DATABASE_URL

tashkent_tz = pytz.timezone("Asia/Tashkent")

logger = logging.getLogger(__name__)

PoolError = getattr(psycopg2.pool, "PoolError", RuntimeError)  # CI'dagi psycopg2 stub'ida PoolError yo'q

# Boshqariladigan PostgreSQL (Aiven va h.k.) uchun ulanishlar soni cheklangan.
# DB_POOL_MAX ni oshirishdan oldin xizmatning ulanish limitini tekshiring.
# 1-BOSQICH: DB_POOL_MIN standart 0 -> 2. Sabab: Aiven/Render free-tier
# da birinchi so'rov har doim TLS handshake + autentifikatsiyani TO'LIQ
# to'lashdan keyin chiqadi (300-800 ms). ``min`` ulanishlar ``init_db``
# paytida ``warm_pool()`` orqali ochiladi va ISITILADI — ya'ni foydalanuvchi
# birinchi /start yuborganda ulanish ALLTA tayyor turadi, 0-dan emas.
DB_POOL_MIN = max(0, int(os.getenv("DB_POOL_MIN", "2")))

# minconn=2, maxconn=10 (ThreadedConnectionPool). Aiven ulanish limitini tekshiring.
DB_POOL_MAX = max(DB_POOL_MIN + 1, int(os.getenv("DB_POOL_MAX", "10")))

# PostAssist V2 (10-BOSQICH): DB_POOL_SIZE — pool hajmi uchun qulay alias.
# Berilgan bo'lsa DB_POOL_MAX o'rniga shu qiymat ishlatiladi (Aiven ulanish
# cheklovlariga moslash uchun). Noto'g'ri qiymat e'tiborga olinmaydi.
_raw_pool_size = os.getenv("DB_POOL_SIZE", "").strip()

if _raw_pool_size:
    try:
        DB_POOL_MAX = max(DB_POOL_MIN + 1, int(_raw_pool_size))
    except ValueError:
        logger.warning(
            "DB_POOL_SIZE noto'g'ri qiymatga ega: %r. DB_POOL_MAX=%s saqlanadi.",
            _raw_pool_size, DB_POOL_MAX,
        )

# Har bir scheduler ishlashida ko'pi bilan shuncha post yuboriladi
# (ulkan navbat bitta tick'ni to'sib qo'ymasligi uchun).
POST_BATCH_SIZE = max(1, int(os.getenv("POST_BATCH_SIZE", "100")))

# 1-BOSQICH: standart 20s -> 8s. Ulanish osilib qolganda 20 soniya kutish
# botni «o'lik» ko'rsatadi; Aiven/Render free-tier da ulanish 8 soniyadan
# oshsa allaqasi muvaffaqiyatsiz bo'ladi, shunda tez urinish (retry) bilan
# qayta ulanish tezroq natija beradi.
DB_CONNECT_TIMEOUT = max(1, int(os.getenv("DB_CONNECT_TIMEOUT", "8")))

# 1-BOSQICH: Aiven idle-timeout ulanishni «o'lik» qilganda avtomatik
# QAYTA ulanish urinishlari soni (standart 1 = bir marta qayta urinadi,
# jami 2 urinish). 0 = faqat bir urinish, qayta urinish yo'q.
DB_RECONNECT_RETRIES = max(0, int(os.getenv("DB_RECONNECT_RETRIES", "1")))

# ``_WarmPool``: bo'sh ulanish PING_AFTER soniyadan keyin ishlatishdan OLDIN 1 RTT
# (``SELECT 1``) bilan tekshiriladi; ``minconn`` dan ortiqchasi IDLE_TTL soniyadan
# keyin yopiladi (0 = o'chirilgan).
DB_POOL_PING_AFTER = 30

DB_POOL_IDLE_TTL = 300

# Kanonik sxema fayli (database.py bilan bir katalogda yuradi).
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# Startup schema check: bot ishga tushganda mavjudligi tasdiqlanadigan
# jadvallar va indekslar (schema.sql bilan bir xil bo'lishi shart —
# tests/schema_test.py buni tekshirib turadi). Legacy ro'yxatlar saqlanadi;
# P0 obyektlari alohida REQUIRED_P0_* orqali ham startup'da tekshiriladi.
EXPECTED_TABLES = (
    "users", "channels", "sponsor_channels", "system_settings",
    "bot_settings", "ad_pool", "channel_post_counters", "scheduled_posts",
    "post_reactions", "sent_post_messages", "promo_codes", "payments",
    "payment_receipts", "payment_orders", "channel_posts_history",
    # PostAssist V2 (6-bosqich): RBAC rollari va admin auditi.
    "admin_roles", "admin_audit_logs",
    # PostAssist V2 (8-bosqich): AI-ballar auditi (credits ledger).
    "credits_ledger",
    # PHASE 2 / 1-qadam: atomik AI bron (kunlik kvota YOKI kredit).
    "ai_reservations",
    # PHASE A — Channel Intelligence baza poydevori (idempotent).
    "channel_intelligence_profiles",
    "channel_post_events",
    "channel_insights",
    # FAZA 8,9,22 — Kengaytirilgan Channel DNA (idempotent).
    "channel_dna",
    # PHASE C — Post shablonlari (7/9/10-bandlar refaktori).
    "post_templates",
    # PHASE D — Kontent manbalari (11, 12-bandlar): RSS/ATOM oqimi.
    "content_sources",
    "source_items",
    "source_drafts",
    # PHASE E — team membership + aggregate comment insights.
    "channel_members",
    "channel_comment_insights",
    # 💬 4-QISM — Qo'llab-quvvatlash: bir martalik murojaat (one-time ticket)
    # va admin javobini murojaat egasiga bog'lovchi yozuvlar.
    "support_tickets",
    "support_ticket_deliveries",
)

EXPECTED_INDEXES = (
    "idx_ad_pool_scope",
    "idx_channel_post_counters_updated",
    "idx_payments_user_id",
    "idx_payment_receipts_status",
    "idx_payment_orders_user",
    "idx_scheduled_posts_status_time",
    "idx_scheduled_posts_user_id",
    "idx_channels_user_id",
    "idx_post_reactions_post_id",
    "idx_channel_posts_history_channel_date",
    # PostAssist V2 (5-bosqich): scheduler/bot tezligi va FK ustunlari.
    "idx_posts_sched_status",
    "idx_deliveries_lookup",
    "idx_payments_user",
    "idx_channels_owner",
    "idx_scheduled_posts_channel",
    "idx_deliveries_post",
    # PostAssist V2 (6-bosqich): admin harakatlari auditi indeksi.
    "idx_audit_admin",
    # PostAssist V2 (8-bosqich): foydalanuvchi ballar tarixi indeksi.
    "idx_ledger_user",
    # PHASE 2 / 1-qadam: atomik AI bron indeksi (schema.sql'da mavjud).
    "idx_ai_reservations_user",
    # PHASE A — Channel Intelligence indekslari.
    "idx_channel_post_events_channel",
    "idx_channel_post_events_created",
    "idx_channel_insights_channel",
    "idx_channel_insights_dismissed",
    # FAZA 8,9,22 — Kengaytirilgan Channel DNA indekslari.
    "idx_channel_dna_channel",
    "idx_channel_dna_updated",
    # PHASE C — Post shablonlari indeksi.
    "idx_post_templates_user",
    # PHASE D — Kontent manbalari indekslari (RSS/ATOM oqimi).
    "idx_content_sources_user",
    "idx_content_sources_due",
    "idx_source_items_source",
    "idx_source_drafts_user",
    # PHASE E — team membership + aggregate comment insights.
    "idx_channel_members_channel",
    "idx_channel_members_user",
    "idx_comment_insights_channel",
)

REQUIRED_P0_TABLES = ("promo_redemptions", "post_deliveries")

REQUIRED_P0_INDEXES = ("idx_deliveries_sched", "idx_deliveries_retry", "uq_payments_telegram_charge_id")

# PHASE E names are also kept in separate lists for migration tooling and
# deployment diagnostics; EXPECTED_* above includes them for startup parity.
PHASE_E_TABLES = ("channel_members", "channel_comment_insights")

PHASE_E_INDEXES = ("idx_channel_members_channel", "idx_channel_members_user", "idx_comment_insights_channel")

APPROVAL_WORKFLOW_STATUSES = ("draft", "pending_approval", "approved", "scheduled", "published")

# --- MA'LUMOTLAR BUTUNLIGI (PostAssist V2 — 5-bosqich) -------------------
# Kanonik ro'yxat: schema.sql'dagi "5-BOSQICH" bo'limi bilan bir xil bo'lishi
# shart (tests/db_integrity_test.py buni tekshirib turadi). Har bir element
# idempotent: obyekt allaqachon bo'lsa qayta yaratilmaydi, mavjud ma'lumotlar
# esa umidan o'chirilmaydi yoki o'zgartirilmaydi.
#
# ``kind`` qiymatlari:
#   fk    — jadvallararo bog'lanish (ota yozuv bo'lmasa — yangi qator rad etiladi);
#   check — qiymatlar to'plami (noma'lum status yozib bo'lmaydi);
#   unique— takrorlanmas juftlik.
#
# Xavfsizlik qoidasi: eski (legacy) yozuvlar talabga javob bermasa, constraint
# ``NOT VALID`` holatida qo'shiladi — ya'ni tarix tekshirilmaydi (ma'lumot
# buzilmaydi), lekin BARCHA YANGI yozuvlar baribir himoyalanadi.
INTEGRITY_CONSTRAINTS = (
    {
        "table": "channels",
        "name": "fk_channels_user",
        "kind": "fk",
        "definition": "FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE",
        "note": "har bir kanal mavjud foydalanuvchiga tegishli bo'ladi",
    },
    {
        "table": "scheduled_posts",
        "name": "fk_scheduled_posts_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "post faqat ro'yxatdan o'tgan kanalga rejalanadi",
    },
    {
        "table": "post_deliveries",
        "name": "fk_post_deliveries_post",
        "kind": "fk",
        "definition": "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "note": "delivery markeri doim haqiqiy postga bog'liq",
    },
    {
        "table": "post_reactions",
        "name": "fk_post_reactions_post",
        "kind": "fk",
        "definition": "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "note": "yetim reaksiyalar endi DB tomonidan yo'q qilinadi",
    },
    {
        "table": "promo_redemptions",
        "name": "uq_promo_user",
        "kind": "unique",
        "definition": "UNIQUE (promo_id, user_id)",
        "note": "bitta kod — bitta foydalanuvchi uchun bir marta",
    },
    {
        "table": "post_deliveries",
        "name": "chk_post_deliveries_status",
        "kind": "check",
        "definition": "CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter', 'unknown'))",
        "note": ("delivery holatlari: 3-bosqich jadvali + 'unknown' "
                 "(UNKNOWN_DELIVERY — albom yuborishda javob olinmagan)"),
    },
    {
        "table": "scheduled_posts",
        "name": "chk_scheduled_posts_status",
        "kind": "check",
        "definition": (
            "CHECK (status IN ('draft', 'pending_approval', 'approved', 'scheduled', "
            "'published', 'pending', 'processing', 'posted', 'failed', 'cancelled', "
            "'completed', 'unknown'))"
        ),
        "note": (
            "Phase E approval statuslari legacy pending/posted statuslari bilan birga "
            "saqlanadi; bot "
            "'processing' (claim), 'completed' (recurring tick) va 'unknown' "
            "(UNKNOWN_DELIVERY — albom yuborishda javob olinmagan, blind "
            "retry taqiqlangan) holatlarini ham ishlatadi"
        ),
    },
    {
        "table": "payments",
        "name": "chk_payments_status",
        "kind": "check",
        "definition": "CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded'))",
        "note": "Stars/To'lov audit holatlari (yangi ustun)",
    },
    {
        "table": "credits_ledger",
        "name": "fk_credits_ledger_user",
        "kind": "fk",
        "definition": "FOREIGN KEY (user_id) REFERENCES users(user_id)",
        "note": "har bir ball audit yozuvi mavjud foydalanuvchiga tegishli",
    },
    {
        # PHASE 2 / 1-qadam: atomik AI bron qatori yetim qolmasligi uchun.
        "table": "ai_reservations",
        "name": "fk_ai_reservations_user",
        "kind": "fk",
        "definition": "FOREIGN KEY (user_id) REFERENCES users(user_id)",
        "note": "har bir AI bron (kvota/kredit) mavjud foydalanuvchiga tegishli",
    },
    # FAZA 8,9,22 — Channel DNA va bog'liq jadvallar uchun FK (yetim yozuvlar oldini olish)
    {
        "table": "channel_post_events",
        "name": "fk_channel_post_events_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "kanal post eventlari faqat mavjud kanalga bog'lanadi (yetim yo'q)",
    },
    {
        "table": "channel_intelligence_profiles",
        "name": "fk_channel_intelligence_profiles_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "intelligence profil faqat mavjud kanalga tegishli",
    },
    {
        "table": "channel_insights",
        "name": "fk_channel_insights_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "kanal insightlari faqat mavjud kanalga tegishli",
    },
    {
        "table": "channel_dna",
        "name": "fk_channel_dna_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "kengaytirilgan DNA profili faqat mavjud kanalga tegishli (FAZA 8,9,22)",
    },
    {
        "table": "channel_comment_insights",
        "name": "fk_channel_comment_insights_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "izoh insightlari faqat mavjud kanalga tegishli",
    },
    {
        "table": "channel_members",
        "name": "fk_channel_members_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "jamoa a'zolari faqat mavjud kanalga bog'lanadi",
    },
)

#: Startup'da mavjudligi tekshiriladigan constraintlar (schema.sql bilan bir xil).
INTEGRITY_CONSTRAINT_NAMES = tuple(item["name"] for item in INTEGRITY_CONSTRAINTS)

#: Kompozit indekslar: (nom, jadval, ustunlar ifodasi, SQL). ``ddl`` — schema.sql
# bilan bir xil matn; ``require_all`` — testlar bu indekslarni talab qiladi.
INTEGRITY_INDEXES = (
    {
        "name": "idx_posts_sched_status",
        "table": "scheduled_posts",
        "columns": "(status, scheduled_time)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_posts_sched_status "
               "ON scheduled_posts (status, scheduled_time) WHERE status = 'pending'",
        "note": "scheduler'ning eng issiq so'rovi: pending navbati (get_due_posts)",
    },
    {
        "name": "idx_deliveries_lookup",
        "table": "post_deliveries",
        "columns": "(status, post_id, channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_deliveries_lookup "
               "ON post_deliveries (status, post_id, channel_id)",
        "note": "delivery holati bo'yicha filtr + post/kanal bo'yicha izlash",
    },
    {
        "name": "idx_payments_user",
        "table": "payments",
        "columns": "(user_id, status)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id, status)",
        "note": "foydalanuvchi to'lov tarixi (holat bo'yicha)",
    },
    {
        "name": "idx_channels_owner",
        "table": "channels",
        "columns": "(user_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels (user_id) WHERE is_active = TRUE",
        "note": "get_user_channels (faqat faol kanallar) — idx_channels_user_id'ni takrorlamaydi",
    },
    {
        "name": "idx_scheduled_posts_channel",
        "table": "scheduled_posts",
        "columns": "(channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_scheduled_posts_channel ON scheduled_posts (channel_id)",
        "note": "FK (channel_id) tufayli kanal o'chirish/cascade tekshiruvlari tez bo'ladi",
    },
    {
        "name": "idx_deliveries_post",
        "table": "post_deliveries",
        "columns": "(post_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_deliveries_post ON post_deliveries (post_id)",
        "note": "post o'chirilganda cascade tekshiruvi uchun",
    },
    # FAZA 8,9,22 — Channel DNA va event indekslari (channel_id, created_at)
    {
        "name": "idx_channel_post_events_channel",
        "table": "channel_post_events",
        "columns": "(channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channel_post_events_channel ON channel_post_events (channel_id)",
        "note": "kanal post eventlari channel_id bo'yicha tez qidiruv (FAZA 8)",
    },
    {
        "name": "idx_channel_post_events_created",
        "table": "channel_post_events",
        "columns": "(created_at DESC)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channel_post_events_created ON channel_post_events (created_at DESC)",
        "note": "kanal post eventlari created_at bo'yicha saralash (FAZA 8)",
    },
    {
        "name": "idx_channel_dna_channel",
        "table": "channel_dna",
        "columns": "(channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channel_dna_channel ON channel_dna (channel_id)",
        "note": "kengaytirilgan DNA profili channel_id bo'yicha (FAZA 8,9,22)",
    },
    {
        "name": "idx_channel_dna_updated",
        "table": "channel_dna",
        "columns": "(updated_at DESC)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channel_dna_updated ON channel_dna (updated_at DESC)",
        "note": "DNA yangilanish vaqti bo'yicha saralash (FAZA 8,9,22)",
    },
)

INTEGRITY_INDEX_NAMES = tuple(item["name"] for item in INTEGRITY_INDEXES)

def resolve_sslmode(url: str = None) -> str:
    """Ulanish uchun sslmode'ni aniqlaydi (bo'sh satr = aralashmaslik).

    Tartib:
      1) URL ichida ``sslmode=`` bo'lsa — hech narsa qo'shmaymiz (URL g'olib).
      2) ``DB_SSLMODE`` env berilgan bo'lsa — aynan shu ishlatiladi
         (masalan: disable | allow | prefer | require | verify-full).
      3) Aks holda avtomatik: lokal host (localhost/127.0.0.1/::1) uchun
         ``prefer``, masofaviy host (Aiven, Render va h.k.) uchun ``require`` —
         Aiven TLS'siz ulanishni umuman qabul qilmaydi.
    """
    url = DATABASE_URL if url is None else url
    url = url or ""
    if "sslmode=" in url:
        return ""
    env_mode = os.getenv("DB_SSLMODE", "").strip().lower()
    if env_mode:
        return env_mode
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        pass
    if host in ("", "localhost", "127.0.0.1", "::1"):
        return "prefer"
    return "require"

def _connect_kwargs() -> dict:
    """psycopg2.connect()/ThreadedConnectionPool uchun umumiy parametrlar.

    SSL (Aiven talab qiladi) va TCP keepalive'lar (managed bazalar bo'sh
    turuvchi ulanishlarni o'chirib qo'yadi — keepalive buni yumshatadi).
    """
    kwargs = {
        "connect_timeout": DB_CONNECT_TIMEOUT,
        "application_name": "yordamchibot",
        "keepalives": 1,
        "keepalives_idle": 45,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
    sslmode = resolve_sslmode()
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs

# Tez-tez o'qiladigan (va kam o'zgaradigan) ma'lumotlar uchun kichik TTL kesh.
# Render Free'da har bir Telegram click DB so'rovini kamaytirish jiddiy
# yuklama pasaytiradi. Yozish funksiyalarida tegishli kesh avtomatik tozalanadi.
DB_CACHE_ENABLED = os.getenv("DB_CACHE_ENABLED", "1") == "1"

DB_SETTINGS_CACHE_TTL = max(1, int(os.getenv("DB_SETTINGS_CACHE_TTL", "60")))

DB_SPONSORS_CACHE_TTL = max(1, int(os.getenv("DB_SPONSORS_CACHE_TTL", "30")))

DB_USER_CACHE_TTL = max(1, int(os.getenv("DB_USER_CACHE_TTL", "15")))

DB_STATS_CACHE_TTL = max(1, int(os.getenv("DB_STATS_CACHE_TTL", "30")))

# Foydalanuvchi PROFILI (til, PRO, ball, kanallar soni ...) RAM'da shuncha soniya
# turadi (standart 5 daqiqa; 30..3600). Faqat haqiqiy o'zgarishda yangilanadi.
DB_PROFILE_CACHE_TTL = max(30, min(3600, int(os.getenv("DB_PROFILE_CACHE_TTL", "300"))))

_pool = None

_pool_lock = threading.Lock()

_pool_sem = None

def _pool_dsn() -> str:
    """Pool uchun DSN: config.DATABASE_URL + postgres:// → postgresql:// himoya.

    Aiven havolasi ``postgres://`` yoki ``postgresql://`` bilan kelishi mumkin.
    config.normalize_database_url allaqachon ishlagan bo'lsa ham, bu yerda
    qayta moslashtirish xavfsiz (idempotent) va hardcoded host YO'Q.
    """
    url = (DATABASE_URL or "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

# Kesh holati. ``_CACHE[key] = (expiry_timestamp, value)``
_CACHE = {}

_CACHE_LOCK = threading.Lock()

_MISS = object()

def _close_quietly(conns):
    for c in conns:
        try:
            c.close()
        except Exception:
            pass

class _WarmPool(ThreadedConnectionPool):
    """``ThreadedConnectionPool`` (psycopg2 2.9.x) ning 3 ta sekinlashtiruvchi xatti-harakatini tuzatadi:

    1. ``minconn`` dan ortiqcha qaytgan ulanishni YOPMAYDI (``maxconn`` gacha saqlaydi,
       ``DB_POOL_IDLE_TTL`` dan keyin ``minconn`` gacha qisqaradi) — aks holda har yuklama
       to'lqinida TCP+TLS+auth handshake (0.5-1 s) qayta to'lanadi;
    2. yangi ulanish ochish, ROLLBACK va ping (tarmoq round-trip) umumiy lock TASHQARISIDA —
       standart pool ularni lock ichida bajarib, butun jarayondagi DB chaqiruvlarini ketma-ketlashtiradi;
    3. ``DB_POOL_PING_AFTER`` dan uzoq bo'sh turgan ulanish beriladan oldin ``SELECT 1`` bilan tekshiriladi.
    """

    def __init__(self, minconn, maxconn, *args, **kwargs):
        self._idle_since = {}   # id(conn) -> poolga qaytgan vaqt (monotonic)
        self._opening = 0       # hozir ochilayotgan ulanishlar (maxconn hisobi uchun)
        super().__init__(minconn, maxconn, *args, **kwargs)
        now = _time.monotonic()
        for conn in list(getattr(self, "_pool", ())):
            self._idle_since[id(conn)] = now

    def getconn(self, key=None):
        while True:
            conn, idle_for, victims = None, 0.0, []
            try:
                with self._lock:
                    if self.closed:
                        raise PoolError("connection pool is closed")
                    if key is None:
                        key = self._getkey()
                    if key in self._used:
                        return self._used[key]
                    self._reap_idle(victims)
                    if self._pool:
                        conn = self._pool.pop()  # LIFO: eng «iliq» ulanish
                        now = _time.monotonic()
                        idle_for = now - self._idle_since.pop(id(conn), now)
                        self._used[key] = conn
                        self._rused[id(conn)] = key
                    elif len(self._used) + self._opening >= self.maxconn:
                        raise PoolError("connection pool exhausted")
                    else:
                        self._opening += 1
            finally:
                _close_quietly(victims)
            if conn is None:
                return self._open(key)
            if not conn.closed and (
                not DB_POOL_PING_AFTER or idle_for < DB_POOL_PING_AFTER or self._ping(conn)
            ):
                return conn
            with self._lock:  # o'lik ulanish — faqat o'zi tashlanadi
                self._used.pop(key, None)
                self._rused.pop(id(conn), None)
            _close_quietly([conn])

    def putconn(self, conn=None, key=None, close=False):
        with self._lock:
            if self.closed:
                raise PoolError("connection pool is closed")
            if key is None:
                key = self._rused.get(id(conn))
            if key is None:
                raise PoolError("trying to put unkeyed connection")
        keep = (not close) and self._clean(conn)  # ROLLBACK (tarmoq) — lock TASHQARISIDA
        victims = []
        try:
            with self._lock:
                if self.closed:
                    raise PoolError("connection pool is closed")
                self._used.pop(key, None)
                self._rused.pop(id(conn), None)
                if keep and len(self._pool) < self.maxconn:
                    self._pool.append(conn)
                    self._idle_since[id(conn)] = _time.monotonic()
                else:
                    victims.append(conn)
                self._reap_idle(victims)
        finally:
            _close_quietly(victims)

    def _open(self, key):
        """Yangi ulanish — lock TASHQARISIDA (sekin handshake boshqa thread'larni to'smaydi)."""
        try:
            conn = psycopg2.connect(*self._args, **self._kwargs)
        except BaseException:
            with self._lock:
                self._opening -= 1
            raise
        with self._lock:
            self._opening -= 1
            if not self.closed:
                self._used[key] = conn
                self._rused[id(conn)] = key
                return conn
        _close_quietly([conn])
        raise PoolError("connection pool is closed")

    def _reap_idle(self, victims):
        """``minconn`` dan ortiqcha, ``DB_POOL_IDLE_TTL`` dan uzoq bo'sh ulanishlarni yig'adi (lock ichida)."""
        if not DB_POOL_IDLE_TTL:
            return
        now = _time.monotonic()
        while len(self._pool) > self.minconn:
            oldest = self._pool[0]
            if now - self._idle_since.get(id(oldest), now) < DB_POOL_IDLE_TTL:
                break
            self._pool.pop(0)
            self._idle_since.pop(id(oldest), None)
            victims.append(oldest)

    @staticmethod
    def _ping(conn) -> bool:
        """Bo'sh ulanish tirikmi? Autocommit — BEGIN'siz atigi 1 RTT."""
        try:
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            finally:
                conn.autocommit = False
            return True
        except Exception:
            return False

    @staticmethod
    def _clean(conn) -> bool:
        """Qaytgan ulanishni tayyorlaydi (ochiq tranzaksiya → ROLLBACK). Yaroqsiz bo'lsa ``False``."""
        from psycopg2 import extensions as ext
        try:
            if conn.closed:
                return False
            status = conn.info.transaction_status
            if status == ext.TRANSACTION_STATUS_UNKNOWN:
                return False
            if status != ext.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            return not conn.closed
        except Exception:
            return False

def _get_pool() -> ThreadedConnectionPool:
    """Pool'ni yaratib beradi (bir marta, keyin qayta ishlatiladi)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _WarmPool(
                    DB_POOL_MIN, DB_POOL_MAX, _pool_dsn(),
                    **_connect_kwargs(),
                )
    return _pool

def _get_semaphore() -> threading.BoundedSemaphore:
    """Pool'dagi ulanishlar sonini qat'iy cheklaydigan semafor.

    psycopg2 ning ThreadedConnectionPool.getconn() ixtiyoriy vaqt cheklovisiz
    bloklanishi mumkin, shuning uchun ulanishlar sonini semafor orqali
    boshqaramiz — bu ham pool to'lib qolganda botni osib qo'ymaydi.
    """
    global _pool_sem
    if _pool_sem is None:
        with _pool_lock:
            if _pool_sem is None:
                _pool_sem = threading.BoundedSemaphore(DB_POOL_MAX)
    return _pool_sem

def _reset_pool():
    """Pool'ni yopib qayta yaratishga tayyorlaydi.

    Semafor SAQLANADI: in-flight ``acquire``/``release`` juftligi buzilmasin
    (Aiven uzilganda pool qayta quriladi, lekin band joylar hisobi saqlanadi).
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None

def close_pool():
    """Bot to'xtatilganda barcha DB ulanishlarini yopish."""
    global _pool_sem
    _reset_pool()
    with _pool_lock:
        _pool_sem = None
    logger.info("DB pool yopildi.")

# ---------------- Kichik TTL kesh ----------------

def _cache_get(key):
    """TTL keshidan qiymat olish; topilmasa ``_MISS`` qaytaradi."""
    if not DB_CACHE_ENABLED:
        return _MISS
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is not None:
            expires_at, value = item
            if _time.time() < expires_at:
                return value
            _CACHE.pop(key, None)
    return _MISS

def _cache_set(key, value, ttl):
    if not DB_CACHE_ENABLED:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (_time.time() + max(1, int(ttl)), value)

def _cache_clear(prefix=None):
    """Keshni tozalash. ``prefix`` berilsa faqat shu old qo'shimchali kalitlar o'chadi."""
    if prefix is None:
        _profile_clear_all()
    with _CACHE_LOCK:
        if prefix is None:
            _CACHE.clear()
            return
        for k in [k for k in _CACHE if k.startswith(prefix)]:
            _CACHE.pop(k, None)

def _cache_size() -> int:
    with _CACHE_LOCK:
        return len(_CACHE)

def cache_clear():
    """Admin panel uchun: barcha TTL keshini qo'lda tozalash."""
    _cache_clear()
    logger.info("DB kesh tozalandi.")

def _invalidate_user(user_id: int):
    """Bitta foydalanuvchiga tegishli kesh yozuvlarini (profil keshi bilan) tozalash.

    Servislar buni tranzaksiya ICHIDA (COMMIT'dan oldin) chaqiradi: shu oraliqda
    boshqa thread eski qiymatni qayta o'qib, uni 5 daqiqaga keshlab qo'yishi
    mumkin. Shuning uchun tozalash COMMIT'dan KEYIN yana bir marta bajariladi.
    """
    def _clear():
        for prefix in ("user_credits", "user_code", "user_channels", "user_stats",
                       "user_lang", "user_overview_stats"):
            _cache_clear(f"{prefix}:{user_id}")
        _profile_invalidate(user_id)

    _clear()
    _after_commit(_clear)

def _after_commit(fn):
    """``fn`` ni joriy tranzaksiya COMMIT bo'lgach chaqiradi (faol tranzaksiya yo'q
    bo'lsa — hech narsa: chaqiruvchi tozalashni allaqachon bajargan)."""
    tx = _TX_CTX.get()
    while tx is not None and tx.parent is not None:
        tx = tx.parent
    if tx is not None and tx.conn is not None and tx.commit:
        tx.after_commit.append(fn)

# ============================================================
# 👤 FOYDALANUVCHI PROFILI — RAM keshi (5 daqiqa)
# /start va «⚙️ Sozlamalar» til, PRO, ball, seriya, takliflar va kanallar sonini
# 4-6 ta ketma-ket so'rov bilan o'qirdi (har biri ~3 RTT). Endi BITTA birlashgan
# so'rov + RAM kesh: ``peek_user_profile`` faqat RAM (event loop'da xavfsiz),
# ``get_user_profile`` — RAM yoki 1 so'rov. Faqat o'zgarganda yangilanadi
# (``_invalidate_user``, til almashtirish, ``_cache_clear()``, kanal o'chirilishi).
# Kesh faqat KO'RSATISH uchun: limit/kvota/to'lov qarorlari doim bazadan.
# ============================================================
_PROFILE = OrderedDict()         # user_id -> (muddat_monotonic, snapshot)

_PROFILE_STAMPS = OrderedDict()  # user_id -> oxirgi bekor qilish vaqti

_PROFILE_LOCK = threading.Lock()

_PROFILE_MAX = 20000             # LRU chegarasi (~10 MB)

_PROFILE_STAMPS_MAX = 4096

_profile_cleared_at = 0.0

_PROFILE_SQL = """
    SELECT u.language_code, u.user_code, u.username, u.full_name,
           u.ai_credits, u.streak_days, u.plan_type, u.subscription_expires_at,
           (SELECT COUNT(*) FROM users r WHERE r.referrer_id = u.user_id),
           (SELECT COUNT(*) FROM channels c WHERE c.user_id = u.user_id AND c.is_active = TRUE)
      FROM users u WHERE u.user_id = %s
"""

def _profile_uid(user_id):
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None

def _profile_invalidate(user_id, **fields):
    """Profilni bekor qiladi; ``fields`` berilsa (write-through) keshdagi nusxa o'chirilmay yangilanadi.

    Ikkala holatda ham shu payt YUKLANAYOTGAN (eskirgan bo'lishi mumkin) natija
    keshga yozilmaydi (``_profile_store`` vaqt belgisini tekshiradi).
    """
    uid = _profile_uid(user_id)
    if uid is None:
        return
    with _PROFILE_LOCK:
        if not fields:
            _PROFILE.pop(uid, None)
        elif uid in _PROFILE:
            _PROFILE[uid][1].update(fields)
        _PROFILE_STAMPS[uid] = _time.monotonic()
        _PROFILE_STAMPS.move_to_end(uid)
        while len(_PROFILE_STAMPS) > _PROFILE_STAMPS_MAX:
            _PROFILE_STAMPS.popitem(last=False)

def _profile_clear_all():
    global _profile_cleared_at
    with _PROFILE_LOCK:
        _PROFILE.clear()
        _profile_cleared_at = _time.monotonic()

def _profile_store(uid, snap, started):
    with _PROFILE_LOCK:
        if started <= _profile_cleared_at or _PROFILE_STAMPS.get(uid, 0.0) >= started:
            return  # yuklash paytida bekor qilingan — eskirgan natijani keshlamaymiz
        _PROFILE[uid] = (_time.monotonic() + DB_PROFILE_CACHE_TTL, snap)
        _PROFILE.move_to_end(uid)
        while len(_PROFILE) > _PROFILE_MAX:
            _PROFILE.popitem(last=False)

def _plan_is_pro(plan_type, expires_at) -> bool:
    """``SubscriptionService.get_status`` bilan bir xil qoida (faqat KO'RSATISH uchun):
    PRO/enterprise va muddati o'tmagan. Muddat o'qish paytida hisoblanadi."""
    if (plan_type or "free") not in ("pro", "enterprise"):
        return False
    if expires_at is None:
        return True
    from datetime import timezone as _tz
    try:
        return expires_at > datetime.now(_tz.utc)
    except TypeError:  # tz-siz datetime
        return expires_at > datetime.utcnow()

def peek_user_profile(user_id):
    """Profil RAM'da bo'lsa NUSXASINI, aks holda ``None`` qaytaradi.

    DB'ga, thread'ga va tarmoqqa HECH QACHON tegmaydi — event loop ichida
    to'g'ridan-to'g'ri chaqirish xavfsiz (0 ms).
    """
    uid = _profile_uid(user_id)
    if uid is None or not DB_CACHE_ENABLED:
        return None
    with _PROFILE_LOCK:
        item = _PROFILE.get(uid)
        if item is None:
            return None
        if item[0] <= _time.monotonic():
            del _PROFILE[uid]
            return None
        _PROFILE.move_to_end(uid)
        prof = dict(item[1])
    prof["is_pro"] = _plan_is_pro(prof["plan_type"], prof["expires_at"])
    return prof

def get_user_profile(user_id: int):
    """Profil: RAM'dan (0 DB) yoki BITTA birlashgan so'rov bilan (oldin 4-6 ta so'rov).

    Qaytadi (nusxa): ``user_id, lang, user_code, username, full_name, ai_credits,
    streak, referrals_count, channels_count, plan_type, expires_at, is_pro``;
    foydalanuvchi yo'q yoki DB xatosi bo'lsa ``None`` (chaqiruvchi eski yo'lga qaytadi).
    """
    prof = peek_user_profile(user_id)
    if prof is not None:
        return prof
    uid = _profile_uid(user_id)
    if uid is None:
        return None
    started = _time.monotonic()
    try:
        with db_cursor() as cur:
            cur.execute(_PROFILE_SQL, (uid,))
            row = cur.fetchone()
    except Exception as e:
        logger.error(f"Profil o'qish xatosi: {e}")
        return None
    if not row:
        return None
    snap = {
        "user_id": uid,
        "lang": _normalize_language_code(row[0]),
        "user_code": row[1] or str(uid),
        "username": row[2] or "",
        "full_name": row[3] or "",
        "ai_credits": row[4] if row[4] is not None else 0,
        "streak": row[5] if row[5] is not None else 0,
        "plan_type": row[6] or "free",
        "expires_at": row[7],
        "referrals_count": int(row[8] or 0),
        "channels_count": int(row[9] or 0),
    }
    if DB_CACHE_ENABLED:
        _profile_store(uid, snap, started)
    return dict(snap, is_pro=_plan_is_pro(snap["plan_type"], snap["expires_at"]))

def get_db_pool_status() -> dict:
    """Admin/health uchun DB pool va kesh holati."""
    pool = _pool
    if pool is None:
        return {
            "ready": False,
            "message": "DB pool hali yaratilmagan",
            "max": DB_POOL_MAX,
            "min": DB_POOL_MIN,
            "used": 0,
            "available": 0,
            "collapsed": False,
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
            "sslmode": resolve_sslmode() or "url",
            **conn_stats(),
            **offload_stats(),
        }
    try:
        used = len(getattr(pool, "_used", {}))
        available = len(getattr(pool, "_pool", []))
        return {
            "ready": True,
            "message": "OK",
            "max": getattr(pool, "maxconn", DB_POOL_MAX),
            "min": getattr(pool, "minconn", DB_POOL_MIN),
            "used": used,
            "available": available,
            "collapsed": bool(getattr(pool, "closed", False)),
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
            "sslmode": resolve_sslmode() or "url",
            **conn_stats(),
            **offload_stats(),
        }
    except Exception as e:
        logger.warning("DB pool holatini o'qishda xato: %s", e)
        return {
            "ready": True,
            "message": f"o'qish xatosi: {e}",
            "max": DB_POOL_MAX,
            "min": DB_POOL_MIN,
            "used": 0,
            "available": 0,
            "collapsed": False,
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
            **conn_stats(),
            **offload_stats(),
        }

# ============================================================
# 💧 ULANISH HISOBI VA «LEAK» QARSHILIGI (PostAssist V2 — faza 4)
# ------------------------------------------------------------
# ``ThreadedConnectionPool`` o'zi ulanishni hisoblamaydi: ``getconn()``
# olingan ulanishni hech qachon ``putconn()`` qilinmasa, ``_used`` ichida
# qolib ketadi (odatda — xatolik yuz bergan, ``return`` qilmagan kod).
# Bunday «ko'rinmas» oqim ``DB_POOL_MAX`` ga yetganda botni butunlay
# to'xtatib qo'yadi.
#
# Shu sabab har bir olingan/berilgan ulanish alohida hisobga olinadi.
# O'lchovlar yengil (ikkita ``Lock`` + uchta ``int``), shuning uchun
# ishlashga sezilarli ta'sir qilmaydi, lekin "hamma joyda bir xil"
# degan daqiqatli raqam beradi:
#
#   * ``conn_inflight``  — hozirda ishlatilayotgan ulanishlar soni
#   * ``conn_high_water`` — shu bosqichgacha bo'lgan eng yuqori qiymat
#   * ``conn_overflow``  — ``DB_POOL_MAX`` dan oshgan urinishlar (teskari
#     da signallash: chegaraga tegilgan holatlar)
#   * ``conn_balance()``  — ``+1`` har olinganda, ``-1`` har berilganda
#
# ``conn_balance()`` nolga teng bo'lmasa — ulanish yo'qolgan bo'lishi
# mumkin (leak). ``tests/repository_layering_test.py`` shu muvozanatni
# soxta ulanish orqali tekshiradi.
# ============================================================

_CONN_LOCK = threading.Lock()
_CONN_INFLIGHT = 0
_CONN_HIGH_WATER = 0
_CONN_OVERFLOW = 0


def _conn_acquired() -> None:
    """Bitta ulanish olindi — hisobni yangilaydi."""
    global _CONN_INFLIGHT, _CONN_HIGH_WATER, _CONN_OVERFLOW
    with _CONN_LOCK:
        _CONN_INFLIGHT += 1
        if _CONN_INFLIGHT > _CONN_HIGH_WATER:
            _CONN_HIGH_WATER = _CONN_INFLIGHT
        if _CONN_INFLIGHT > DB_POOL_MAX:
            _CONN_OVERFLOW += 1


def _conn_released() -> None:
    """Bitta ulanish qaytarildi (yoki butunlay tashlandi) — hisobni kamaytiradi."""
    global _CONN_INFLIGHT
    with _CONN_LOCK:
        _CONN_INFLIGHT = max(0, _CONN_INFLIGHT - 1)


def conn_balance() -> int:
    """Olingan minus berilgan ulanishlar.

    ``0`` — hamma ulanish joyida (normal).
    ``>0`` — shuncha ulanish qaytarilmagan (potensial leak).
    """
    return _CONN_INFLIGHT


def conn_stats() -> dict:
    """Ulashish (pool) oqimi bo'yicha o'lchovlar — monitoring uchun."""
    return {
        "conn_inflight": _CONN_INFLIGHT,
        "conn_high_water": _CONN_HIGH_WATER,
        "conn_overflow": _CONN_OVERFLOW,
    }


# ============================================================
# ⚙️ OFFLOAD (THREAD POOL) O'LCHOVI
# ------------------------------------------------------------
# ``asyncio.to_thread`` ichki ``ThreadPoolExecutor`` dan foydalanadi; uning
# default worker soni cheklangan. Botda DB harakati ko'p (reja, navbat,
# to'lov, AI kvota) — offload soni chegaradan oshsa, so'rovlar navbatda
# kutadi va foydalanuvchi «bot javob bermayapti» degan holatni ko'radi.
# Doimiy worker pool o'rnatish **rad etilgan**: bo'sh worker thread'lar
# ``threading.active_count()`` ni oshirib qoladi va leak testlari (va
# haqiqiy xotira) uchun zararli. Shuning uchun faqat O'LCHOV qo'shildi.
# ============================================================

_OFFLOAD_LOCK = threading.Lock()
_OFFLOAD_INFLIGHT = 0
_OFFLOAD_PEAK = 0


def _connection_is_usable(conn) -> bool:

    """Pool'dan olingan ulanish hali tirikligini tekshiradi.

    Aiven (va boshqa managed PG) bo'sh turgan TCP sessiyalarni uzishi mumkin.
    ``closed`` yoki ``rollback()`` xatosi — ulanishni tashlab, qayta ulanamiz.
    """
    try:
        if getattr(conn, "closed", 0) in (1, True):
            return False
        conn.rollback()
        return True
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        return False

def _acquire_connection():
    """Pool'dan ulanish olish (maks. 15 soniya). O'lik ulanishda qayta urinadi.

    1-BOSQICH: urinishlar soni endi ``DB_RECONNECT_RETRIES`` (standart 1 →
    jami 2 urinish) orqali boshqariladi. Yaroqsiz ulanish FAQAT o'zi tashlanadi;
    pool BUTUNLAY qayta qurilmaydi: ``_reset_pool`` band ulanishlarni ham
    yopadi va yangi pool ``minconn`` ta ulanishni ketma-ket (har biri
    handshake) ochguncha hamma DB chaqiruvlari to'xtab qolardi (10-15 s
    «qotish»). Uzoq bo'sh turgan o'lik ulanishlarni ``_WarmPool`` o'zi aniqlaydi.
    Pool obyektining o'zi buzilgan bo'lsa (yopilgan va h.k.) — qayta quriladi.
    """
    sem = _get_semaphore()
    if not sem.acquire(timeout=15):
        raise TimeoutError("DB pool band: 15 soniya ichida bo'sh ulanish topilmadi")
    attempts = DB_RECONNECT_RETRIES + 1
    try:
        last_err = None
        for attempt in range(attempts):
            pool = None
            try:
                pool = _get_pool()
                conn = pool.getconn()
            except Exception as e:
                last_err = e
                logger.warning("DB pool xatosi (%s); qayta urinilmoqda...", e)
                if not isinstance(e, psycopg2.OperationalError):
                    _reset_pool()  # ulanish emas, pool o'zi yaroqsiz
                continue
            if _connection_is_usable(conn):
                _conn_acquired()
                return conn
            logger.warning(
                "DB ulanishi uzilgan (urinish %s/%s); qayta ulanilmoqda...",
                attempt + 1, attempts,
            )
            try:
                pool.putconn(conn, close=True)  # faqat shu ulanish; band boshqalarga tegilmaydi
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        if last_err is not None:
            raise last_err
        raise psycopg2.OperationalError("DB ulanish olinmadi")
    except Exception:
        sem.release()
        raise

def warm_pool() -> bool:
    """Ulashishlar havuzini «isitadi» — bitta ``SELECT 1;`` bilan.

    Render/Aiven free-tier da muammo shu: bot qayta ishga tushgach birinchi
    biror so'rov uchun TLS handshake, autentifikatsiya va PostgreSQL plan
    keshi sovuq bo'ladi — bu foydalanuvchi hissidan 0.3–1.0 soniya yuk qo'shadi.
    Bu funksiya:

      1. ``ThreadedConnectionPool(min, max, ...)`` yaratadi (``min`` ta
         ulanish shu zahoti ochiladi);
      2. havuzdagi har bir ulanishga bitta ``SELECT 1;`` yuboradi — server
         ham, havuz ham «ishlaydi»;
      3. uzilgan ulanishlarni tashlab, ``_acquire_connection`` orqali
         ``DB_RECONNECT_RETRIES`` marta qayta urinadi.

    ``init_db()`` dan OLDIN chaqiriladi: jadvallar yaratilgandan keyin
    degani qimmat ``CREATE TABLE IF NOT EXISTS`` bloklari ham sovuq ulanish
    ustida emas, iliq ulanish ustida ishlaydi.

    Qaytadi: ``True`` — havuz isitildi; ``False`` — DB hali ko'tarilmagan
    (bot ishlashda davom etadi, ``init_db`` o'z urinishlarini qiladi).
    """
    warmed = 0
    for attempt in range(DB_RECONNECT_RETRIES + 1):
        try:
            pool = _get_pool()
        except Exception as e:
            logger.warning("DB pool yaratib bo'lmadi (%s/%s): %s",
                           attempt + 1, DB_RECONNECT_RETRIES + 1, e)
            _time.sleep(0.5)
            continue
        warmed = 0
        for _ in range(max(1, DB_POOL_MIN)):
            conn = None
            try:
                conn = pool.getconn()
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
                warmed += 1
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logger.warning("Warm-up ulanishi uzildi: %s", e)
                _reset_pool()
                break
            except Exception as e:  # pragma: no cover — kutilmagan
                logger.warning("Warm-up ulanishida xato: %s", e)
                break
            finally:
                if conn is not None:
                    try:
                        pool.putconn(conn)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
        if warmed >= max(1, DB_POOL_MIN):
            logger.info(
                "DB pool isitildi: %s ulanish tayyor (min=%s, max=%s).",
                warmed, DB_POOL_MIN, DB_POOL_MAX,
            )
            return True
        _time.sleep(0.5)
    logger.warning("DB pool isitilmadi — bot ishlashda davom etadi "
                   "(init_db o'z urinishlarini qiladi).")
    return False

def _release_connection(conn):
    """Ulanishni pool'ga qaytarish (yana ishlatilishi mumkin)."""
    sem = _get_semaphore()
    try:
        try:
            _get_pool().putconn(conn)
        except Exception:
            conn.close()
    finally:
        _conn_released()
        sem.release()

def _discard_connection(conn):
    """Buzilgan ulanishni pool'dan butunlay o'chirish."""
    sem = _get_semaphore()
    try:
        try:
            _get_pool().putconn(conn, close=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    finally:
        _conn_released()
        sem.release()

# ============================================================
# ATOMIK TRANZAKSIYA YORDAMCHILARI (PostAssist V2 — 5-bosqich)
# ------------------------------------------------------------
# ``db_cursor(commit=True)`` avvallari ham bitta ulanishda implicit BEGIN +
# COMMIT/ROLLBACK qilardi. 5-bosqichda bu xatti-harakat rasmiy, ismli API'ga
# chiqarildi, shunda istalgan qavat (DB funksiyasi, servis yoki async handler)
# nechta SQL bo'lsin — BITTA atomik blokda bajariladi:
#
#   * blok ichida istisno ko'tarilsa  → avtomatik ROLLBACK (qismiy yozuv qolmaydi);
#   * blok muvaffaqiyatli tugasa      → COMMIT;
#   * ich-ma-ich chaqiruvda yangi tranzaksiya OCHILMAYDI — bir ulanishda
#     SAVEPOINT ishlatiladi va qaror tashqi blokka bo'ysunadi;
#   * tranzaksiya ichidagi ``db_cursor()`` qo'shimcha ulanish olmaydi (pool
#     to'lib, o'z-o'zini bloqlab qo'yishi mumkin, shuning uchun bir ulanish
#     va bir tranzaksiya davom etadi);
#   * server ulanishni uzsa — buzilgan ulanish pool'ga qaytarilmaydi.
#
# Sinkron kod uchun:  ``with db_transaction() as cur:``
# Asinxron kod uchun: ``async with transaction() as cur:``
# ============================================================

#: Ruxsat etilgan izolatsiya darajalari (SQL'ga string konkatensiyasi uchun
# oq ro'yxat — chaqiruvchi xato satri hech qachon SQL bo'la olmaydi).
TX_ISOLATION_LEVELS = ("read committed", "repeatable read", "serializable")

#: Tranzaksiya holati (faol blokningsiz o'zi). ContextVar — chunki
# ``asyncio.to_thread`` kontekstni ko'chirib oladi, ya'ni async blok ichida
# ishga tushadigan sinkron ``db_cursor()`` ham shu tranzaksiyani ko'radi.
_TX_CTX = contextvars.ContextVar("postassist_tx", default=None)

_TX_SEQ = _itertools.count(1)

class _Transaction:
    """Bitta atomik blokning holati: ulanish, kursor, savepoint va yakun.

    ``enter()`` — ulanishni oladi (yoki mavjud tranzaksiyada savepoint ochadi),
    ``finish(exc)`` — COMMIT/ROLLBACK va ulanishni pool'ga qaytaradi.
    """

    __slots__ = ("commit", "isolation_level", "readonly", "conn", "cur",
                 "savepoint", "parent", "owns_conn", "_token", "after_commit")

    def __init__(self, commit: bool = True, isolation_level: str = None,
                 readonly: bool = False):
        self.commit = bool(commit)
        level = (isolation_level or "").strip().lower() or None
        if level is not None and level not in TX_ISOLATION_LEVELS:
            raise ValueError(
                f"Noma'lum izolatsiya darajasi: {isolation_level!r} "
                f"(ruxsat etilgan: {', '.join(TX_ISOLATION_LEVELS)})"
            )
        self.isolation_level = level
        self.readonly = bool(readonly)
        self.conn = None
        self.cur = None
        self.savepoint = None
        self.parent = None
        self.owns_conn = True
        self._token = None
        self.after_commit = []  # COMMIT'dan keyin chaqiriladigan funksiyalar (kesh tozalash)

    # ---- kirish -------------------------------------------------------
    def enter(self):
        parent = _TX_CTX.get()
        if parent is not None and parent.conn is not None:
            # Ich-ma-ich: BITTA ulanish, SAVEPOINT. Alohida kursor ochiladi —
            # shunda tashqi blokning natijalari (fetchone/fetchall) buzilmaydi.
            self.parent = parent
            self.conn = parent.conn
            self.owns_conn = False
            self.savepoint = f"postassist_tx_{next(_TX_SEQ)}"
            self.cur = self.conn.cursor()
            self.cur.execute(f"SAVEPOINT {self.savepoint}")
            self._token = _TX_CTX.set(self)
            return self.cur

        conn = _acquire_connection()
        self.conn = conn
        try:
            self.cur = conn.cursor()
            if getattr(conn, "autocommit", False):
                # Autocommit ulanishda tranzaksiyani qo'lbella ochamiz.
                self.cur.execute("BEGIN")
            if self.isolation_level:
                self.cur.execute(
                    "SET LOCAL TRANSACTION ISOLATION LEVEL " + self.isolation_level
                )
            if self.readonly:
                self.cur.execute("SET LOCAL TRANSACTION READ ONLY")
            self._token = _TX_CTX.set(self)
        except Exception:
            self._reset_ctx()
            try:
                _discard_connection(conn)
            except Exception:
                pass
            self.conn = None
            raise
        return self.cur

    # ---- chiqish ------------------------------------------------------
    def finish(self, exc: BaseException = None):
        """``exc`` None bo'lsa — COMMIT (yoki savepoint release), aks holda ROLLBACK."""
        self._reset_ctx()
        if self.savepoint is not None:
            try:
                if exc is None:
                    self.cur.execute(f"RELEASE SAVEPOINT {self.savepoint}")
                else:
                    self.cur.execute(f"ROLLBACK TO SAVEPOINT {self.savepoint}")
            except Exception:
                # Ulanish buzilgan bo'lsa savepoint ham yo'q — tashqi blok
                # xatolikni o'zi boshqaradi.
                if exc is None:
                    raise
            finally:
                self._close_cursor()
            return

        conn, self.conn = self.conn, None
        if conn is None:
            return
        try:
            self._close_cursor()
        except Exception:
            pass
        if exc is None:
            try:
                if self.commit:
                    conn.commit()
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self._retire(conn, broken=True)
                raise
            except Exception:
                # COMMIT o'zi xato berdi — ulanish aniq holatda emas, tashlaymiz.
                self._retire(conn, broken=True)
                raise
            else:
                self._retire(conn, broken=False)
                self._run_after_commit()
            return
        # Xatolik yo'li: rollback, keyin ulanishni saqlab qolish.
        if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            self._retire(conn, broken=True)
            return
        try:
            conn.rollback()
        except Exception:
            self._retire(conn, broken=True)
            return
        self._retire(conn, broken=False)

    # ---- ichki yordamchilar -------------------------------------------
    def _run_after_commit(self):
        hooks, self.after_commit = self.after_commit, []
        for fn in hooks:
            try:
                fn()
            except Exception:  # kesh tozalash tranzaksiya natijasini buzmasligi kerak
                logger.debug("after_commit ilgagi xato berdi", exc_info=True)

    def _reset_ctx(self):
        token, self._token = self._token, None
        if token is not None:
            try:
                _TX_CTX.reset(token)
            except Exception:
                pass

    def _close_cursor(self):
        cur, self.cur = self.cur, None
        if cur is None:
            return
        try:
            cur.close()
        except Exception:
            pass

    @staticmethod
    def _retire(conn, broken: bool):
        try:
            if broken:
                _discard_connection(conn)
            else:
                _release_connection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

@contextmanager
def db_transaction(commit: bool = True, isolation_level: str = None,
                   readonly: bool = False):
    """Atomik tranzaksiya bloki (sync).

    Muvaffaqiyatli yakunda COMMIT, istisnoda avtomatik ROLLBACK qilinadi.
    Ich-ma-ich chaqirilganda yangi tranzaksiya ochilmaydi — SAVEPOINT
    ishlatiladi (ichki blok xatosi tashqi blokni buzmaydi).

    Ishlatish::

        with db_transaction() as cur:
            cur.execute("INSERT INTO payments ...", (...))
            cur.execute("UPDATE users SET ...", (...))   # bitta atomik blok

    Args:
        commit: ``False`` — o'qish uchun (hech qachon COMMIT qilinmaydi).
        isolation_level: ``read committed`` | ``repeatable read`` | ``serializable``.
        readonly: ``True`` — ``SET LOCAL TRANSACTION READ ONLY`` (tasodifiy
            yozishlarni bloklaydi).
    """
    tx = _Transaction(commit=commit, isolation_level=isolation_level, readonly=readonly)
    cur = tx.enter()
    try:
        yield cur
    except BaseException as exc:
        tx.finish(exc)
        raise
    tx.finish(None)

def current_transaction() -> _Transaction:
    """Faol tranzaksiya obyekti yoki ``None`` (tashqi chaqiruvlar uchun)."""
    return _TX_CTX.get()

@asynccontextmanager
async def transaction(commit: bool = True, isolation_level: str = None,
                     readonly: bool = False):
    """Asinxron atomik tranzaksiya bloki — ``db_transaction`` o'rami.

    psycopg2 sinkron, shuning uchun BEGIN/COMMIT/ROLLBACK alohida thread'da
    bajariladi (event loop bloklanmaydi). ``asyncio.to_thread`` kontekstni
    ko'chirib olgani uchun blok ichidagi sinkron ``db_cursor()`` chaqiruvlari
    ham shu tranzaksiyaga qo'shiladi.

    Ishlatish::

        async with transaction() as cur:
            await asyncio.to_thread(cur.execute, "INSERT INTO ...", (...))
    """
    holder = {}

    def _begin():
        tx = _Transaction(commit=commit, isolation_level=isolation_level,
                          readonly=readonly)
        cur = tx.enter()
        holder["tx"] = tx
        return cur

    cur = await asyncio.to_thread(_begin)
    # ``_begin`` alohida thread'da ishlagani uchun ContextVar shu thread'ning
    # nusxa ko'chirilgan kontekstiga yozildi — uni joriy (task) kontekstga ham
    # o'rnatamiz, shunda blok ichidagi sinkron ``db_cursor()`` chaqiruvlari ham
    # shu tranzaksiyani ko'radi.
    token = _TX_CTX.set(holder["tx"])
    try:
        yield cur
    except BaseException as exc:
        _TX_CTX.reset(token)
        await asyncio.to_thread(holder["tx"].finish, exc)
        raise
    else:
        _TX_CTX.reset(token)
        await asyncio.to_thread(holder["tx"].finish, None)

#: Asinxron API uchun qo'shimcha nom (chaqiruvchi uslubiga qarab).
atransaction = transaction

# ============================================================
# 🛡 `db_atomic` — BELGILANGAN VAZIFA ICHIDA BITTA TRANZAKSIYA
# ============================================================

def db_atomic(func):
    """Funksiyani **bir butun tranzaksiya** ichida bajarishga majburlaydi.

    Nima uchun kerak: ba'zi vazifalar bir necha ``db_cursor()`` blokini
    ketma-ket ishlatadi. Ularning orasida boshqa kod (boshqa task, signal)
    ishlab ketsa, natija yarim qolishi mumkin — masalan kvota yechildi,
    lekin «rezervatsiya yozuvi» yozilmadi.

    ``@db_atomic`` bitta ``_Transaction(commit=True)`` ochadi va uni
    ``finally`` da yopadi: xato bo'lsa ROLLBACK, muvaffaqiyat bo'lsa COMMIT.
    Ichki ``db_cursor()`` bloklari shu tranzaksiyaning SAVEPOINT'iga
    tushadi — qo'shimcha ulanish olinmaydi va ichki xato tashqarisini
    buzmaydi.

    Faqat ``ContextVar`` orqali ishlaydi: funksiya signaturasi O'ZGARMAYDI
    (``inspect.signature`` mos keladi), hech qanday ``cur=`` argumenti
    kiritilmaydi — mavjud chaqiruvlar butunlay mos keladi.

    Misol::

        @db.db_atomic
        def accept_payment(user_id: int, order_id: int) -> bool:
            with db.db_cursor() as cur:          # INSERT INTO payments ...
                cur.execute("UPDATE orders SET status = 'paid' ...")
            with db.db_cursor(commit=True) as cur:
                cur.execute("INSERT INTO payment_receipts ...")
            return True

    Xususiyatlari:
        * ``functools.wraps`` — nom, docstring, ``__module__`` saqlanadi;
        * ``__db_atomic__ = True`` — testlar va kod tahlili shundan
          aniqlaydi (funksiya haqiqatan ham atomikmi);
        * ich-ma-ich ``@db_atomic`` — tashqi tranzaksiya ustida SAVEPOINT
          ochiladi, qaror tashqi blokka bo'ysunadi (qayta nested
          ``commit`` xatosi yo'q).
    """
    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        tx = _Transaction(commit=True)
        tx.enter()
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:
            tx.finish(exc)
            raise
        tx.finish(None)
        return result

    _wrapper.__db_atomic__ = True
    return _wrapper

def db_cursor(commit: bool = False):
    """DB kursori (kanalik nomi). ``transaction()`` yordamchisiga delegat.

    ``commit=True`` — blok muvaffaqiyatli tugaganda COMMIT (atomik tranzaksiya),
    ``commit=False`` — o'qish rejimi (xatoda rollback, lekin COMMIT yo'q).
    Faol tranzaksiya ichida chaqirilsa, yangi ulanish OLINMAYDI — mavjud
    tranzaksiyaning SAVEPOINT'ida ishlanadi.
    """
    return db_transaction(commit=commit)

def offload_stats() -> dict:
    """Event loop -> thread offload oqimi bo'yicha o'lchovlar.

    ``offload_peak`` — bir vaqtda eng ko'p task ``asyncio.to_thread`` orqali
    ishlatilgan. Bu soni ``DB_POOL_MAX`` dan sezilarli katta bo'lsa, thread
    pool «to'lib» turadi: har bir offload o'z ulanishini kutadi va navbat
    uzayadi. Shu sababli monitoring uchun ochiq ko'rsatiladi.

    ``offload_inflight`` — hozirda ishlayotgan offload soni; ``run_db``
    ``finally`` blokida doim qaytaradi (xato bo'lsa ham).
    """
    return {"offload_inflight": _OFFLOAD_INFLIGHT, "offload_peak": _OFFLOAD_PEAK}


async def run_db(func, *args, **kwargs):
    """Sync DB funksiyasini alohida thread'da bajaradi — event loop bloklanmaydi.

    Async handler/scheduler ichida to'g'ridan-to'g'ri sync DB chaqirmang:
        result = await db.run_db(db.get_due_posts, now)
    """
    global _OFFLOAD_INFLIGHT, _OFFLOAD_PEAK
    with _OFFLOAD_LOCK:
        _OFFLOAD_INFLIGHT += 1
        if _OFFLOAD_INFLIGHT > _OFFLOAD_PEAK:
            _OFFLOAD_PEAK = _OFFLOAD_INFLIGHT
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    finally:
        # `finally` — vazifa xatolansa ham, offload hisobi doim qaytariladi
        with _OFFLOAD_LOCK:
            _OFFLOAD_INFLIGHT = max(0, _OFFLOAD_INFLIGHT - 1)

# Eski nom — mavjud chaqiruvlar ishlashi uchun
run_in_thread = run_db

def ping_db() -> bool:
    """Health-check uchun baza bilan tez aloqa tekshiruvi."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1
    except Exception as e:
        logger.warning(f"DB ping xatosi: {e}")
        return False

# ============================================================
# 🩺 SYSTEM HEALTH CHECK (PostAssist V2 — 7-BOSQICH)
# ------------------------------------------------------------
# HealthService (services/health_service.py) ishlatadigan yengil
# DB so'rovlari. HECH QANDAY mavjud funksiyani o'zgartirmaydi —
# faqat QO'SHIMCHA, xatosiz (hech qachon istisno ko'tarmaydi).
# ============================================================

def ping_db_with_latency() -> dict:
    """PostgreSQL ga oddiy ``SELECT 1`` ping + javob vaqti (latency ms).

    Returns:
        dict: ``{"ok": bool, "latency_ms": float | None, "error": str | None}``
              ``error`` matni FAQAT log/monitoring uchun — foydalanuvchiga
              hech qachon ko'rsatilmaydi (buning uchun global error handler
              va ``safe_html`` javobgar).
    """
    started = _time.perf_counter()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            ok = bool(row and row[0] == 1)
        elapsed_ms = (_time.perf_counter() - started) * 1000.0
        if ok:
            return {"ok": True, "latency_ms": round(elapsed_ms, 2), "error": None}
        return {"ok": False, "latency_ms": None,
                "error": "SELECT 1 kutilmagan natija qaytardi"}
    except Exception as e:
        logger.warning("DB ping (latency) xatosi: %s", e)
        return {
            "ok": False,
            "latency_ms": None,
            "error": f"{type(e).__name__}: {e}"[:200],
        }

def init_db():
    # 1-BOSQICH: avval havuzni «isitish» — jadvallarni yaratishdan oldin
    # ``SELECT 1;`` bilan ulanishlar tayyorlanadi, shunda startup'dagi
    # eng qimmat SQL (CREATE TABLE/INDEX) sovuq ulanish ustida emas,
    # iliq ulanish ustida bajariladi va Render port 0-dan tez ochiladi.
    warm_pool()
    last_err = None
    for attempt in range(3):
        try:
            _init_db_once()
            logger.info("Baza jadvallari tayyor.")
            return
        except psycopg2.OperationalError as e:
            last_err = e
            logger.warning(f"DB ishga tushirishda xatolik ({attempt + 1}/3 urinish): {e}")
            _time.sleep(3)
    raise last_err

def _apply_schema_file(cur) -> bool:
    """Kanonik ``schema.sql`` faylini bajaradi (idempotent).

    Fayl topilmasa (masalan, deploy'da nusxalanmagan bo'lsa) ogohlantirib
    ``False`` qaytaradi — eski ichki DDL zaxira sifatida ishlashda davom etadi.
    """
    if not os.path.exists(SCHEMA_FILE):
        logger.warning("schema.sql topilmadi (%s) — ichki DDL ishlatiladi.", SCHEMA_FILE)
        return False
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        cur.execute(f.read())
    return True

def _sql_literal(value: str) -> str:
    """SQL satr literali (bitta tirnoqlar ikkilantiriladi)."""
    return "'" + str(value).replace("'", "''") + "'"

def _integrity_values_rows() -> str:
    """``INTEGRITY_CONSTRAINTS`` ro'yxatidan DO blokidagi VALUES qatorlari."""
    rows = []
    for item in INTEGRITY_CONSTRAINTS:
        rows.append("            ({table}, {name}, {kind}, {definition})".format(
            table=_sql_literal(item["table"]),
            name=_sql_literal(item["name"]),
            kind=_sql_literal(item["kind"]),
            definition=_sql_literal(item["definition"]),
        ))
    return ",\n".join(rows)

def build_integrity_block() -> str:
    """Ma'lumotlar butunligi (FK/CHECK/UNIQUE) migratsiyasini qaytaradi.

    Ushbu blok ``INTEGRITY_CONSTRAINTS`` ro'yxatidan quriladi va schema.sql'dagi
    statik nusxasi bilan bir xil ish qiladi. Kafolatlar:

      * **Idempotent** — obyekt mavjud bo'lsa (``pg_constraint`` bo'yicha)
        hech narsa qilinmaydi, qayta-qayta bajarish xavfsiz;
      * **Ma'lumot buzilmaydi** — eski (legacy) yozuvlar talabga javob
        bermasa, constraint ``NOT VALID`` holatida qo'shiladi: tarix
        tekshirilmaydi, lekin barcha YANGI yozuvlar himoyalanadi;
      * **Bot to'xtamaydi** — har bir DDL alohida ``BEGIN ... EXCEPTION``
        blokida: bitta muvaffaqiyatsiz constraint qolganlarini va tranzaksiyani
        buzmaydi (faqat RAISE WARNING).
    """
    return """DO $postassist_integrity$
DECLARE
    spec RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
{rows}
        ) AS t(tbl, cname, kind, cdef)
    LOOP
        IF to_regclass(spec.tbl) IS NULL THEN
            RAISE NOTICE 'integrity: % jadvali topilmadi -- % otkazib yuborildi', spec.tbl, spec.cname;
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_constraint c
             WHERE c.conrelid = spec.tbl::regclass AND c.conname = spec.cname
        ) THEN
            CONTINUE;  -- idempotent: constraint allaqachon mavjud
        END IF;
        BEGIN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', spec.tbl, spec.cname, spec.cdef);
            RAISE NOTICE 'integrity: %.% qoshildi', spec.tbl, spec.cname;
        EXCEPTION
            WHEN foreign_key_violation THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s NOT VALID',
                                   spec.tbl, spec.cname, spec.cdef);
                    RAISE WARNING 'integrity: %.% NOT VALID holatda qoshildi (yetim yozuvlar bor) -- '
                                  'VALIDATE CONSTRAINT orqali tekshirish tugallanadi',
                                  spec.tbl, spec.cname;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
                END;
            WHEN check_violation THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s NOT VALID',
                                   spec.tbl, spec.cname, spec.cdef);
                    RAISE WARNING 'integrity: %.% NOT VALID holatda qoshildi (eski qiymatlar chekka mos emas)',
                                  spec.tbl, spec.cname;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
                END;
            WHEN unique_violation THEN
                RAISE WARNING 'integrity: %.% qoshilmadi -- jadvalda dublikat qatorlar bor, '
                              'avval tozalash kerak', spec.tbl, spec.cname;
            WHEN OTHERS THEN
                RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
        END;
    END LOOP;
END
$postassist_integrity$;""".format(rows=_integrity_values_rows())

#: schema.sql'dagi statik blokning belgisi (testlar shu orqali tekshiradi).
INTEGRITY_BLOCK_MARKER = "$postassist_integrity$"

#: ``integrity_orphan_counts()`` uchun tekshiruvlar:
# (bola jadval, bola ustun, ota jadval, ota ustun).
INTEGRITY_ORPHAN_CHECKS = (
    ("channels", "user_id", "users", "user_id"),
    ("scheduled_posts", "channel_id", "channels", "channel_id"),
    ("post_deliveries", "post_id", "scheduled_posts", "id"),
    ("post_reactions", "post_id", "scheduled_posts", "id"),
    ("promo_redemptions", "promo_id", "promo_codes", "id"),
    ("promo_redemptions", "user_id", "users", "user_id"),
    ("credits_ledger", "user_id", "users", "user_id"),
)

def _integrity_indexes_statements() -> list:
    """5-bosqich indekslarining DDL ro'yxati (schema.sql bilan bir xil)."""
    return [item["ddl"] + ";" for item in INTEGRITY_INDEXES]

def _apply_integrity_indexes(cur) -> None:
    """Kompozit indekslarni yaratadi (barchasi ``IF NOT EXISTS`` — idempotent)."""
    for ddl in _integrity_indexes_statements():
        try:
            cur.execute(ddl)
        except Exception as e:
            # Indeksdan xato chiqsa bot ishlashda davom etsin (masalan,
            # ustun migratsiyasi hali bajarmagan eski bazada).
            logger.warning("Integrity indeks yaratilmadi (%s): %s", ddl.split()[5], e)

def _apply_integrity_constraints(cur) -> None:
    """FK/CHECK/UNIQUE constraintlarini qo'llaydi (idempotent DO bloki)."""
    try:
        cur.execute(build_integrity_block())
    except Exception as e:
        # Bitta xato butun init'ni buzmasin: schema.sql allaqachon buni
        # qilgan bo'lishi mumkin yoki DB eski versiya bo'lishi mumkin.
        logger.warning("Integrity constraintlar qo'llanmadi: %s", e)

def _list_integrity_constraints(cur) -> dict:
    """``INTEGRITY_CONSTRAINT_NAMES`` bo'yicha {nom: {"valid": bool}} qaytaradi.

    Jadvallar bo'lmasa yoki bazada xato bo'lsa — bo'sh dict (fail-open).
    """
    if not INTEGRITY_CONSTRAINT_NAMES:
        return {}
    try:
        cur.execute(
            """
            SELECT c.conname, c.convalidated, r.relname
              FROM pg_constraint c
              JOIN pg_class r ON r.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = r.relnamespace
             WHERE n.nspname = current_schema()
               AND c.conname = ANY(%s)
            """,
            (list(INTEGRITY_CONSTRAINT_NAMES),),
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("Integrity constraintlar ro'yxati o'qilmadi: %s", e)
        return {}
    found = {}
    for conname, convalidated, _relname in rows:
        found[conname] = {"valid": bool(convalidated)}
    for name in INTEGRITY_CONSTRAINT_NAMES:
        found.setdefault(name, {"missing": True, "valid": False})
    return found

def integrity_orphan_counts() -> dict:
    """Yetim (ota-yozuvi yo'q) qatorlar soni: ``{"channels.user_id": 0, ...}``.

    Faqat ikkala jadval mavjud bo'lsa sanaladi. Xatoda 0 emas, belgilash
    uchun ``-1`` qaytadi (admin diagnostikasi shuni "tekshirib bo'lmadi"
    deb talqin qiladi).
    """
    counts = {}
    try:
        with db_cursor() as cur:
            for child, ccol, parent, pcol in INTEGRITY_ORPHAN_CHECKS:
                label = f"{child}.{ccol}"
                try:
                    cur.execute("SELECT to_regclass(%s), to_regclass(%s)", (child, parent))
                    child_reg, parent_reg = cur.fetchone()
                    if not child_reg or not parent_reg:
                        counts[label] = 0
                        continue
                    cur.execute(
                        f"SELECT COUNT(*) FROM {child} c "
                        f"LEFT JOIN {parent} p ON p.{pcol} = c.{ccol} "
                        f"WHERE p.{pcol} IS NULL AND c.{ccol} IS NOT NULL"
                    )
                    counts[label] = int(cur.fetchone()[0])
                except Exception as e:
                    logger.warning("Yetim sanagichi xatosi (%s): %s", label, e)
                    counts[label] = -1
    except Exception as e:
        logger.warning("integrity_orphan_counts xatosi: %s", e)
    return counts

def integrity_report() -> dict:
    """Ma'lumotlar butunligi holati — admin diagnostika va testlar uchun.

    Qaytadi::

        {"constraints": {nom: {"valid": bool, ...}},
         "missing": [nom, ...],          # umuman yo'q
         "not_valid": [nom, ...],        # bor, lekin eski yozuvlar tekshirilmagan
         "orphans": {"jadval.ustun": n}, # yetim qatorlar soni
         "indexes": {nom: True|False}}
    """
    report = {"constraints": {}, "missing": [], "not_valid": [], "orphans": {},
              "indexes": {}}
    try:
        with db_cursor() as cur:
            report["constraints"] = _list_integrity_constraints(cur)
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            )
            indexes = {row[0] for row in cur.fetchall()}
    except Exception as e:
        logger.warning("integrity_report xatosi: %s", e)
        report["error"] = str(e)
        return report
    for name, info in report["constraints"].items():
        if info.get("missing"):
            report["missing"].append(name)
        elif not info.get("valid"):
            report["not_valid"].append(name)
    for name in INTEGRITY_INDEX_NAMES:
        report["indexes"][name] = name in indexes
    report["orphans"] = integrity_orphan_counts()
    return report

def validate_integrity_constraints(names=None) -> dict:
    """``NOT VALID`` holatdagi constraintlarni tekshiradi (VALIDATE CONSTRAINT).

    Katta jadvallarda bu amol READ ONLY qulfini oladi (yozishlar to'xtab
    turadi), shuning uchun avtomatik ishga tushirilmaydi — tungi tekshiruv
    yoki admin buyrug'i uchun ajratilgan. ``DB_VALIDATE_INTEGRITY=1`` bo'lsa
    startup paytida ham bajariladi.

    Qaytadi: ``{nom: 'validated' | 'ok' | 'xato: ...'}``.
    """
    result = {}
    wanted = list(names) if names else list(INTEGRITY_CONSTRAINT_NAMES)
    try:
        with db_cursor(commit=True) as cur:
            current = _list_integrity_constraints(cur)
            for name in wanted:
                info = current.get(name) or {}
                if info.get("missing"):
                    result[name] = "missing"
                    continue
                if info.get("valid"):
                    result[name] = "ok"
                    continue
                table = next((it["table"] for it in INTEGRITY_CONSTRAINTS
                              if it["name"] == name), None)
                if not table:
                    result[name] = "unknown"
                    continue
                try:
                    cur.execute(f"SAVEPOINT validate_{name}")
                    cur.execute(
                        f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"
                    )
                    cur.execute(f"RELEASE SAVEPOINT validate_{name}")
                    result[name] = "validated"
                except Exception as e:
                    try:
                        cur.execute(f"ROLLBACK TO SAVEPOINT validate_{name}")
                        cur.execute(f"RELEASE SAVEPOINT validate_{name}")
                    except Exception:
                        pass
                    result[name] = f"xato: {e}"
                    logger.warning("VALIDATE CONSTRAINT %s xatosi: %s", name, e)
    except Exception as e:
        logger.error("validate_integrity_constraints xatosi: %s", e)
    return result

def _verify_schema(cur) -> None:
    """Startup schema check: server versiyasi va barcha kutilgan jadvallar
    hamda indekslarning mavjudligi tekshiriladi.

    Jadvallar topilmasa — schema.sql qayta qo'llanadi (o'z-o'zini tiklash) va
    baribir topilmasa RuntimeError: bot yarmi ishlagan holda xato yig'ishidan
    ko'ra, aniq sabab bilan tez o'chishi yaxshi.
    """
    cur.execute("SELECT version()")
    server = str((cur.fetchone() or [""])[0])
    provider = server.split(",")[0]
    if "Neon" in server:
        provider = "Neon"
    elif "aiven" in server.lower():
        provider = "Aiven"
    logger.info("DB server: %s", provider)

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema()"
    )
    tables = {row[0] for row in cur.fetchall()}
    required_tables = (*EXPECTED_TABLES, *REQUIRED_P0_TABLES)
    missing_tables = [t for t in required_tables if t not in tables]

    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
    )
    indexes = {row[0] for row in cur.fetchall()}
    required_indexes = (*EXPECTED_INDEXES, *REQUIRED_P0_INDEXES)
    missing_indexes = [i for i in required_indexes if i not in indexes]

    if missing_indexes:
        logger.warning("Sxema tekshiruvi: indekslar topilmadi: %s (schema.sql ularni yaratadi)",
                       ", ".join(missing_indexes))

    if missing_tables:
        logger.warning("Sxema tekshiruvi: jadvallar topilmadi: %s — schema.sql qayta qo'llanadi...",
                       ", ".join(missing_tables))
        _apply_schema_file(cur)
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
        tables = {row[0] for row in cur.fetchall()}
        missing_tables = [t for t in required_tables if t not in tables]
        if missing_tables:
            raise RuntimeError(
                "DB sxemasi to'liq emas, jadvallar yaratilmadi: "
                + ", ".join(missing_tables)
                + ". Deploy'da telegram_bot/schema.sql fayli kod bilan birga "
                  "yuborilganini tekshiring."
            )

    logger.info(
        "Sxema tekshiruvi OK: %d/%d jadval, %d/%d indeks.",
        len(required_tables) - len(missing_tables), len(required_tables),
        len(required_indexes) - len(missing_indexes), len(required_indexes),
    )

    # 5-bosqich: ma'lumotlar butunligi (FK / CHECK / UNIQUE) ham tekshiriladi.
    # Topilmasa — schema.sql + ichki migratsiya bloki qayta qo'llanadi; baribir
    # bo'lmasa ogohlantiramiz (bot ishlashda davom etadi — eski bazalarda
    # constraint qo'shish ma'lumot hajmi/tartibi tufayli imkonsiz bo'lishi mumkin).
    constraints = _list_integrity_constraints(cur)
    missing_constraints = [n for n, info in constraints.items() if info.get("missing")]
    if missing_constraints:
        logger.warning("Sxema tekshiruvi: integrity constraintlar topilmadi: %s — qayta qo'llanilmoqda...",
                       ", ".join(missing_constraints))
        _apply_integrity_indexes(cur)
        _apply_integrity_constraints(cur)
        constraints = _list_integrity_constraints(cur)
        missing_constraints = [n for n, info in constraints.items() if info.get("missing")]
        if missing_constraints:
            logger.warning("Integrity constraintlar qo'shib bo'lmadi: %s "
                           "(mavjud ma'lumotni buzmaslik uchun davom etamiz)",
                           ", ".join(missing_constraints))
    not_valid = [n for n, info in constraints.items()
                 if not info.get("missing") and not info.get("valid")]
    if not_valid:
        logger.warning("Integrity: %d ta constraint NOT VALID holatda (eski yozuvlar tekshirilmagan): %s. "
                       "Tungi yuklama kam paytda validate_integrity_constraints() bajaring.",
                       len(not_valid), ", ".join(not_valid))
    if os.getenv("DB_VALIDATE_INTEGRITY", "").strip().lower() in ("1", "true", "yes", "on"):
        validated = validate_integrity_constraints()
        ok = sum(1 for v in validated.values() if v in ("ok", "validated"))
        logger.info("Integrity VALIDATE: %d/%d tayyor.", ok, len(validated))

def _init_db_once():
    with db_cursor(commit=True) as cur:
        # 1) Kanonik sxema — schema.sql (barcha operatorlar idempotent).
        _apply_schema_file(cur)

        # 2) Zaxira ichki DDL: schema.sql fayli topilmasa yoki buzilgan bo'lsa
        # ham baza ishlayverishi uchun saqlanadi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                full_name VARCHAR(255),
                user_code VARCHAR(8) UNIQUE,
                referrer_id BIGINT,
                ai_credits INTEGER DEFAULT 5,
                ad_free_posts INTEGER DEFAULT 0,
                ad_free_active BOOLEAN DEFAULT TRUE,
                streak_days INTEGER DEFAULT 0,
                last_bonus_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                full_menu_unlocked BOOLEAN DEFAULT FALSE
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) UNIQUE NOT NULL,
                channel_title VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsor_channels (
                id SERIAL PRIMARY KEY,
                channel_id BIGINT UNIQUE,
                title TEXT,
                username TEXT,
                invite_link TEXT,
                channel_title VARCHAR(255),
                channel_url VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            );
        """)

        # Avtomatik reklama rotatsiya puli. Har bir reklama (kanal posti yoki
        # bot javobi uchun) alohida qator; bot navbatma-navbat (round-robin)
        # ishlatadi. scope: 'channel' | 'reply'.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ad_pool (
                id SERIAL PRIMARY KEY,
                scope VARCHAR(20) NOT NULL,
                text TEXT NOT NULL,
                button_text VARCHAR(64),
                button_url TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_pool_scope ON ad_pool (scope, is_active);")

        # Har bir kanal uchun yuborilgan postlar sanagichi (reklama oralig'i
        # shu sanagich bo'yicha hisoblanadi — kanallar bir-biriga ta'sir qilmaydi).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_post_counters (
                channel_id VARCHAR(255) PRIMARY KEY,
                post_count INTEGER NOT NULL DEFAULT 0,
                ad_count INTEGER NOT NULL DEFAULT 0,
                last_ad_post_number INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_post_counters_updated "
            "ON channel_post_counters (updated_at DESC);"
        )

        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                post_type VARCHAR(50) NOT NULL,
                content TEXT,
                file_id TEXT,
                inline_button_text VARCHAR(255),
                inline_button_url TEXT,
                enable_reactions BOOLEAN DEFAULT FALSE,
                reaction_emojis TEXT,
                delete_after_hours INTEGER DEFAULT 0,
                sent_message_id BIGINT,
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                user_post_number INTEGER,
                recurrence_type VARCHAR(20) DEFAULT 'none',
                recurrence_day INTEGER,
                recurrence_time TIME,
                end_date TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # P0-01: doimiy, DB-backed delivery idempotency registry.
        # PostAssist V2 (3-bosqich): backoff uchun next_retry_at va kalit
        # tarkibidagi scheduled_time ustunlari qo'shildi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_deliveries (
                id BIGSERIAL PRIMARY KEY,
                post_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempt_count INT DEFAULT 0,
                telegram_message_id BIGINT,
                idempotency_key TEXT UNIQUE NOT NULL,
                last_error TEXT,
                scheduled_time TIMESTAMPTZ,
                next_retry_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_sched ON post_deliveries(status, post_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_retry ON post_deliveries(status, next_retry_at);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_reactions (
                id SERIAL PRIMARY KEY,
                post_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                reaction_type VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(post_id, user_id)
            );
        """)
        # Har bir recurring yuborishni alohida saqlaymiz: eski xabarlar ham o'chadi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_post_messages (
                id SERIAL PRIMARY KEY,
                post_id INTEGER NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                message_id BIGINT NOT NULL,
                delete_at TIMESTAMP WITH TIME ZONE,
                deleted_at TIMESTAMP WITH TIME ZONE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                plan_type VARCHAR(20) NOT NULL DEFAULT 'pro',
                duration_days INTEGER NOT NULL DEFAULT 30,
                max_uses INTEGER DEFAULT NULL,
                current_uses INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id BIGSERIAL PRIMARY KEY,
                promo_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                redeemed_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_promo_user UNIQUE (promo_id, user_id)
            );
        """)

        # Real vaqtli kanal postlari tarixi
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_posts_history (
                id SERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                message_id BIGINT,
                content TEXT,
                views INTEGER DEFAULT 0,
                post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_posts_history_channel_date "
            "ON channel_posts_history (channel_id, post_date DESC);"
        )

        # Stars to'lovlari uchun alohida audit jadvali.
        # To'lovlar promo_codes jadvaliga yozilmaydi — har bir to'lov o'z
        # qatori bilan audit qilinadi (summa, valyuta, payload, charge_id).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount INT,
                currency VARCHAR(10),
                payload TEXT,
                telegram_payment_charge_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'succeeded',
                payment_method VARCHAR(32) NOT NULL DEFAULT 'international_stars'
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_telegram_charge_id "
            "ON payments (telegram_payment_charge_id) "
            "WHERE telegram_payment_charge_id IS NOT NULL;"
        )

        # 💳 Karta orqali to'lov cheklari — Admin Approval Flow.
        # Foydalanuvchi chek yuborganida pending holatida saqlanadi, adminlarga
        # yuboriladi. Admin tasdiqlaganda status='approved' + PRO uzaytiriladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_receipts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(255),
                full_name VARCHAR(255),
                language_code VARCHAR(10) DEFAULT 'uz',
                media_type VARCHAR(20) DEFAULT 'photo',
                file_id TEXT,
                caption TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP WITH TIME ZONE,
                decided_by BIGINT,
                days_granted INTEGER DEFAULT 30,
                amount_uzs INT DEFAULT 0
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_payment_receipts_status "
            "ON payment_receipts (status, created_at);"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_orders (
                order_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                plan VARCHAR(20) NOT NULL,
                days INTEGER NOT NULL,
                amount INT NOT NULL,
                currency VARCHAR(10) NOT NULL DEFAULT 'UZS',
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                receipt_id INTEGER,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_payment_orders_user "
            "ON payment_orders (user_id, status);"
        )
        cur.execute(
            "ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS order_id TEXT;"
        )

        # ⚙️ SOZLAMALAR (PostAssist V2, 5-mikro qadam): foydalanuvchining
        # shaxsiy sozlamalari (🔔 Bildirishnomalar / 🎨 Post sozlamalari).
        # Kalitlar handler tomonida OQ RO'YXAT bilan cheklanadi — jadvalga
        # faqat ma'lum kalitlar yoziladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id BIGINT NOT NULL,
                key VARCHAR(64) NOT NULL,
                value BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, key)
            );
        """)

        migrations = [
            # P0 backward-compatible migrations (har bir statement savepoint bilan bajariladi).
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS telegram_payment_charge_id TEXT UNIQUE;",
            "ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_code VARCHAR(8) UNIQUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_credits INTEGER DEFAULT 5;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_posts INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_active BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_date DATE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_text VARCHAR(255);",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_url TEXT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS enable_reactions BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS reaction_emojis TEXT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS delete_after_hours INTEGER DEFAULT 0;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS sent_message_id BIGINT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS user_post_number INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_type VARCHAR(20) DEFAULT 'none';",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_day INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_time TIME;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS end_date TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE scheduled_posts ALTER COLUMN file_id TYPE TEXT;",
            "ALTER TABLE channels ADD COLUMN IF NOT EXISTS tone_of_voice VARCHAR(30) DEFAULT 'friendly';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) DEFAULT 'free';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_requests_today INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_limit_reset DATE DEFAULT CURRENT_DATE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language_code VARCHAR(10) DEFAULT 'uz';",
            # 🆕 Onboarding: "⚙️ To'liq menyuni ochish" bosilganini eslab qolamiz
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_menu_unlocked BOOLEAN DEFAULT FALSE;",
            # 🆕 6-bosqich (RBAC): foydalanuvchi roli. DEFAULT 'user' — barcha
            # eski yozuvlar oddiy foydalanuvchi bo'lib qoladi (backward-compatible).
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS title TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS username TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS invite_link TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_title VARCHAR(255);",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_url VARCHAR(255);",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
            # Reklama puli: HTML matn + inline URL tugma (matn va havola).
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_text VARCHAR(64);",
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_url TEXT;",
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            # Kanal postlari tarixi migratsiyalari
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS message_id BIGINT;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS content TEXT;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 0;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            # PostAssist V2 (3-bosqich): persistent delivery + backoff ustunlari.
            "ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS scheduled_time TIMESTAMPTZ;",
            "ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;",
            # PostAssist V2 (5-bosqich): to'lov audit holati + idx_payments_user
            # (user_id, status) shu ustun bilan quriladi. DEFAULT tufayli eski
            # yozuvlar ham 'succeeded' hisoblanadi (ma'lumot o'zgarmaydi).
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'succeeded';",
            # 💳 To'lov mintaqasi/usuli (hududiy tanlov — tilga bog'liq EMAS):
            # 'uzcard_humo' (🇺🇿 UZS) | 'international_stars' (🌍 XTR).
            # ADD COLUMN + DEFAULT: eski (Stars) yozuvlar xuddi shu nom bilan
            # migratsiyasiz to'g'ri hisoblanadi.
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32) NOT NULL DEFAULT 'international_stars';",
            # 🇺🇿 Karta cheki uchun so'mdagi summa — ledger'ga to'g'ri valyuta
            # bilan yozish uchun (eski cheklar: 0 — hisob kitobi buzilmaydi).
            "ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS amount_uzs INT DEFAULT 0;",
            "ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS order_id TEXT;",
            # PHASE E — approval metadata (additive; existing single-owner rows unchanged).
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS delivery_options JSONB NOT NULL DEFAULT '{}'::jsonb;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_by BIGINT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS approval_requested_at TIMESTAMPTZ;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS approved_by BIGINT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS rejection_reason TEXT;",
        ]
        for index, migration in enumerate(migrations):
            # Bitta migration xatosi qolgan migrationlarni transaction aborted
            # holatiga tushirib qo'ymasligi uchun har birini savepoint bilan bajarish.
            savepoint = f"migration_{index}"
            try:
                cur.execute(f"SAVEPOINT {savepoint}")
                cur.execute(migration)
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception as e:
                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")
                logger.warning(f"Migratsiya eslatmasi: {e}")

        # Server crash paytida processing holatida qolgan postlarni qayta navbatga qaytaramiz (idempotent himoya bilan).
        cur.execute("""
            UPDATE scheduled_posts
            SET status = 'posted'
            WHERE status = 'processing'
              AND (sent_message_id IS NOT NULL 
                   OR id IN (SELECT post_id FROM sent_post_messages));
        """)
        cur.execute("""
            UPDATE scheduled_posts
            SET status = 'pending', processing_started_at = NULL
            WHERE status = 'processing'
              AND sent_message_id IS NULL
              AND id NOT IN (SELECT post_id FROM sent_post_messages)
              AND processing_started_at < NOW() - INTERVAL '10 minutes';
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);")
        # Eng ko'p ishlatiladigan foydalanuvchi/post qidiruvlari uchun indekslar.
        # users.user_id PRIMARY KEY bo'lgani uchun u yerda indeks avtomatik mavjud.
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_id ON scheduled_posts (user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels (user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_post_reactions_post_id ON post_reactions (post_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_history_channel_date ON channel_posts_history (channel_id, post_date DESC);")

        # 2b) PostAssist V2 (6-bosqich): RBAC rollari va admin auditi.
        # schema.sql fayli topilmasa ham bu jadvallar albatta yaratiladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_roles (
                user_id BIGINT PRIMARY KEY,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                granted_by BIGINT,
                granted_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id BIGSERIAL PRIMARY KEY,
                admin_id BIGINT NOT NULL,
                action VARCHAR(64) NOT NULL,
                target_type VARCHAR(64),
                target_id VARCHAR(64),
                old_value JSONB,
                new_value JSONB,
                ip_or_metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_admin "
            "ON admin_audit_logs(admin_id, created_at);"
        )

        # 💰 PostAssist V2 (8-bosqich): credits ledger — AI-ballar auditi.
        # schema.sql fayli topilmasa ham bu jadval albatta yaratiladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS credits_ledger (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INT NOT NULL,
                balance_after INT NOT NULL,
                operation_type VARCHAR(32) NOT NULL,
                reference_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ledger_user "
            "ON credits_ledger(user_id, created_at);"
        )

        # 🔒 PHASE 2 / 1-qadam: AI so'rov bronlari (atomik kvota + kredit).
        # ``reserve_ai_request()`` kunlik kvota YOKI kreditni BITTA
        # tranzaksiyada band qiladi; ``refund_ai_request()`` esa bronni ID
        # bo'yicha IDEMPOTENT qaytaradi. schema.sql fayli topilmasa ham bu
        # jadval albatta yaratiladi (aks holda barcha AI oqimi fail-closed
        # rad etardi).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_reservations (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                operation_type VARCHAR(32) NOT NULL,
                cost INT NOT NULL DEFAULT 1,
                source VARCHAR(16) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                refunded_at TIMESTAMPTZ,
                CONSTRAINT chk_ai_reservations_source
                    CHECK (source IN ('daily_quota', 'credit')),
                CONSTRAINT chk_ai_reservations_status
                    CHECK (status IN ('active', 'refunded')),
                CONSTRAINT chk_ai_reservations_cost CHECK (cost > 0)
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_reservations_user "
            "ON ai_reservations(user_id, created_at);"
        )

        # 🧠 PHASE A — Channel Intelligence baza poydevori (idempotent).
        # schema.sql fayli topilmasa ham bu jadvallar albatta yaratiladi
        # (aks holda analytics/audit oqimi ishlamasdi). Barcha CREATE TABLE
        # va indekslar IF NOT EXISTS — qayta-qayta bajarish xavfsiz.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_intelligence_profiles (
                channel_id VARCHAR(255) PRIMARY KEY,
                tone VARCHAR(64),
                avg_post_length INT,
                emoji_level VARCHAR(32),
                cta_style VARCHAR(64),
                formatting_style VARCHAR(64),
                top_topics JSONB,
                confidence INT,
                sample_size INT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_post_events (
                id SERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                message_id BIGINT,
                post_hour INT,
                post_weekday INT,
                has_media BOOLEAN,
                media_type VARCHAR(32),
                media_file_id VARCHAR(255),
                length INT,
                cta_detected BOOLEAN,
                emoji_density DOUBLE PRECISION,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_channel_post_events UNIQUE (channel_id, message_id)
            );
        """)
        # PHASE B: eski (Phase A) bazalar uchun yangi ustunlar — idempotent.
        # Media fayllarning O'ZI bazaga saqlanmaydi — faqat file_id va turi.
        cur.execute("ALTER TABLE channel_intelligence_profiles "
                    "ADD COLUMN IF NOT EXISTS formatting_style VARCHAR(64);")
        cur.execute("ALTER TABLE channel_post_events "
                    "ADD COLUMN IF NOT EXISTS media_type VARCHAR(32);")
        cur.execute("ALTER TABLE channel_post_events "
                    "ADD COLUMN IF NOT EXISTS media_file_id VARCHAR(255);")
        cur.execute("ALTER TABLE channel_post_events "
                    "ADD COLUMN IF NOT EXISTS emoji_density DOUBLE PRECISION;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_insights (
                id SERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                insight_type VARCHAR(64),
                text TEXT,
                severity VARCHAR(32),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                is_dismissed BOOLEAN DEFAULT FALSE
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_post_events_channel "
            "ON channel_post_events (channel_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_post_events_created "
            "ON channel_post_events (created_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_insights_channel "
            "ON channel_insights (channel_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_insights_dismissed "
            "ON channel_insights (is_dismissed);"
        )

        # 🧬 FAZA 8,9,22 — KENGAYTIRILGAN CHANNEL DNA (channel_dna)
        # Har bir metrika: language, tone, topics, avg_length, emoji_density,
        # best_hours, best_weekdays, high_performing_formats — profile JSONB da
        # sample_size, confidence, updated_at bilan saqlanadi.
        # Idempotent: CREATE TABLE IF NOT EXISTS + indekslar IF NOT EXISTS.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_dna (
                channel_id VARCHAR(255) PRIMARY KEY,
                language VARCHAR(16),
                tone VARCHAR(32),
                topics JSONB,
                avg_length INTEGER,
                emoji_density DOUBLE PRECISION,
                best_hours JSONB,
                best_weekdays JSONB,
                high_performing_formats JSONB,
                sample_size INTEGER,
                confidence DOUBLE PRECISION,
                profile JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # Eski bazalar uchun yangi ustunlar (idempotent)
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS language VARCHAR(16);")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS tone VARCHAR(32);")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS topics JSONB;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS avg_length INTEGER;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS emoji_density DOUBLE PRECISION;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS best_hours JSONB;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS best_weekdays JSONB;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS high_performing_formats JSONB;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS sample_size INTEGER;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS profile JSONB DEFAULT '{}'::jsonb;")
        cur.execute("ALTER TABLE channel_dna ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_dna_channel "
            "ON channel_dna (channel_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_dna_updated "
            "ON channel_dna (updated_at DESC);"
        )

        # 📋 PHASE C — POST SHABLONLARI (7/9/10-bandlar refaktori).
        # Foydalanuvchining takroriy post shablonlari: variables JSONB'da
        # {TITLE}/{TEXT}/{PRICE}/{LINK}/{CTA}/{SOURCE}/{DATE} ro'yxati
        # saqlanadi. Barcha so'rovlar user_id bilan filtrlanadi (IDOR).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_templates (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255),
                name VARCHAR(128) NOT NULL,
                content TEXT NOT NULL,
                variables JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_post_templates_user "
            "ON post_templates (user_id, created_at DESC);"
        )

        # 📥 PHASE D — KONTENT MANBALARI (11, 12-bandlar): RSS/ATOM manbalari,
        # o'qilgan elementlar (dublikat kaliti UNIQUE(source_id, external_id))
        # va Channel DNA asosidagi post qoralamalari (source_drafts).
        # Barcha jadvallar idempotent va foydalanuvchi izolyatsiyasi bilan.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS content_sources (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                channel_id VARCHAR(255),
                source_url TEXT,
                title TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                interval_minutes INT DEFAULT 60,
                autopublish BOOLEAN DEFAULT FALSE,
                last_checked_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_content_sources_user "
            "ON content_sources (user_id, created_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_content_sources_due "
            "ON content_sources (enabled, last_checked_at);"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS source_items (
                id SERIAL PRIMARY KEY,
                source_id INT REFERENCES content_sources(id) ON DELETE CASCADE,
                external_id TEXT,
                canonical_url TEXT,
                title TEXT,
                summary TEXT,
                processed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(source_id, external_id)
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_items_source "
            "ON source_items (source_id, created_at DESC);"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS source_drafts (
                id SERIAL PRIMARY KEY,
                source_id INT REFERENCES content_sources(id) ON DELETE CASCADE,
                source_item_id INT REFERENCES source_items(id) ON DELETE CASCADE,
                user_id BIGINT,
                channel_id VARCHAR(255),
                title TEXT,
                content TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                scheduled_post_id INT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(source_item_id)
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_drafts_user "
            "ON source_drafts (user_id, status, created_at DESC);"
        )

        # PHASE E — schema.sql fallback: team membership and aggregate audience
        # insights must still exist if an operator accidentally deploys without
        # the canonical schema file.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_members (
                id SERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                user_id BIGINT NOT NULL,
                role VARCHAR(20) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(channel_id, user_id),
                CONSTRAINT chk_channel_members_role
                    CHECK (role IN ('owner', 'editor', 'scheduler', 'analyst'))
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_channel ON channel_members (channel_id, role);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_user ON channel_members (user_id, channel_id);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_comment_insights (
                id BIGSERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                question_hash CHAR(64) NOT NULL,
                category VARCHAR(32) NOT NULL DEFAULT 'general',
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                first_seen_at TIMESTAMPTZ DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(channel_id, question_hash)
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_comment_insights_channel ON channel_comment_insights (channel_id, occurrence_count DESC);")

        # 💬 4-QISM — schema.sql fallback: qo'llab-quvvatlash murojaatlari va
        # admin javoblarini bog'lovchi jadvallar kanonik sxema fayli
        # qo'llanilmagan holatda ham mavjud bo'lishi shart.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(64),
                message_text TEXT NOT NULL,
                has_media BOOLEAN NOT NULL DEFAULT FALSE,
                status VARCHAR(16) NOT NULL DEFAULT 'new',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                answered_at TIMESTAMPTZ,
                answered_by BIGINT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS support_ticket_deliveries (
                id SERIAL PRIMARY KEY,
                ticket_id INT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                admin_chat_id BIGINT NOT NULL,
                admin_message_id BIGINT NOT NULL,
                delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (admin_chat_id, admin_message_id)
            );
        """)

        # 3) PostAssist V2 (5-bosqich): scheduler tezligi uchun kompozit indekslar
        # va jadvallararo FK/CHECK/UNIQUE constraintlar. Ikkalasi ham idempotent
        # va ma'lumotni o'zgartirmaydi (tafsilot: ``build_integrity_block``).
        _apply_integrity_indexes(cur)
        _apply_integrity_constraints(cur)

        # 4) Startup schema check: server versiyasi, jadvallar, indekslar va
        #    ma'lumotlar butunligi constraintlari.
        _verify_schema(cur)

# --- SETTINGS ---
# Reklama rotatsiya pullarini aniqlovchi doimiy qadriyatlar
AD_SCOPE_CHANNEL = "channel"

AD_SCOPE_REPLY = "reply"

# PostAssist V2 (3-bosqich): delivery backoff jadvali (urinish → kutish, soniya).
# 1-urinishdagi transient xato → 30s, 2- → 2 daqiqa, 3- → 5 daqiqa,
# 4- → 15 daqiqa; 5-urinishda ham xato bo'lsa → 'dead_letter' (qayta urinilmaydi).
DELIVERY_BACKOFF_SECONDS = (30, 120, 300, 900)

# ============================================================
# STARS PAYMENTS LOG
# ============================================================
# To'lov audit holatlari (5-bosqich). DB tomonida CHECK (chk_payments_status)
# bilan ham himolangan — Python to'plami bilan bir xil bo'lishi shart.
PAYMENT_STATUS_PENDING = "pending"

PAYMENT_STATUS_FAILED = "failed"

PAYMENT_STATUS_REFUNDED = "refunded"

RECEIPT_STATUS_APPROVED = "approved"

RECEIPT_STATUS_REJECTED = "rejected"

APPROVAL_STATUSES = ("draft", "pending_approval", "approved", "scheduled", "published")

# ============================================================
# 💬 POSTASSIST V2 · 4-QISM — QO'LLAB-QUVVATLASH (ONE-TIME TICKET)
# ------------------------------------------------------------
# BIR MARTALIK MUROJAAT (one-time ticket) + DIRECT ADMIN REPLY
# oqimining ma'lumot qatlami.
#
#  * ``support_tickets`` — murojaatning O'ZI (matn, muallif, holat).
#    [💬 Qo'llab-quvvatlash] ekranida foydalanuvchi yozgan BITTA xabar shu
#    jadvalga tushadi va FSM holati darhol yopiladi (spam to'xtatiladi).
#  * ``support_ticket_deliveries`` — murojaat har bir adminga yuborilganda
#    Telegram qaytargan ``message_id`` shu yerga yoziladi. Admin bot
#    xabariga Telegram'ning «Reply» funksiyasi bilan javob yozganda bot
#    (admin_chat_id, admin_message_id) → ticket → user_id zanjiri orqali
#    murojaat egasini topadi. Shu sababli javob bot QAYTA ISHGA
#    TUSHGANDAN KEYIN ham to'g'ri manzilga yetib boradi (xotiradagi kesh
#    yo'qolsa ham DB manba bo'lib qoladi).
#
# Barcha funksiyalar fail-safe: xato yuz bersa ``0`` / ``None`` / ``False``
# qaytaradi va faqat log yozadi — qo'llab-quvvatlash oqimi hech qachon
# yiqilmaydi (foydalanuvchi javobsiz qolmaydi).
# ============================================================

#: Ruxsat etilgan murojaat holatlari (schema.sql CHECK'i bilan bir xil).
SUPPORT_TICKET_STATUSES = ("new", "answered")

# ====================================================================
# 🧩 FACADE — repository delegatsiyasi (BACKWARD COMPATIBILITY)
# ====================================================================
#
# Quyidagi importlar faylning SO'NGI qismida, chunki ular
# yuqoridagi yadroni (pool / tranzaksiya / kesh / sxema) talab
# qiladi. Barchasi oddiy qayta eksport: `database.X` —
# `repositories.<mod>.X` bilan aynan bir xil obyekt, shuning uchun
# `import database as db` va `from database import X` chaqiruvlari
# o'zgarishsiz ishlaydi.

# --- ⚙️ SETTINGS — bot sozlamalari (kalit/qiymat) keshi bilan
from repositories.settings_repository import (  # noqa: F401
    delete_setting, get_setting, get_settings_map, set_setting
)
# --- 👤 USERS — profil, til, tier, kvota, kredits, referallar, onboarding
from repositories.users_repository import (  # noqa: F401
    AI_OPERATION_TYPES, AI_RESERVATION_ACTIVE, AI_RESERVATION_REFUNDED,
    AI_RESERVE_COST_MAX, AI_RESERVE_COST_MIN, AI_RESERVE_DB_ERROR,
    AI_RESERVE_INSUFFICIENT, AI_RESERVE_INVALID_REQUEST, AI_RESERVE_OK,
    AI_RESERVE_SOURCE_CREDIT, AI_RESERVE_SOURCE_QUOTA,
    AI_RESERVE_USER_NOT_FOUND, FREE_QUEUE_MAX_POSTS, PLAN_LIMITS,
    REFERRAL_BASE_REWARD, REFERRAL_TOP_TIER_FRIENDS, REFERRAL_TOP_TIER_REWARD,
    _AI_QUOTA_RESERVATIONS, _AI_QUOTA_RESERVATIONS_LOCK,
    _InsufficientBalanceSignal, _UserSaveResult, _consume_ai_quota_reservation,
    _deny_ai_reserve, _effective_plan, _effective_plan_strict,
    _ensure_limit_reset, _generate_user_code, _normalize_language_code,
    _remember_ai_quota_reservation, _subscription_expired, _today_tashkent,
    add_user_credit, check_ai_limit, check_channel_limit, check_queue_limit,
    claim_daily_streak_bonus, create_promo_code,
    downgrade_expired_subscriptions, find_user_by_target, get_all_user_ids,
    get_referral_stats, get_referrer_id, get_user_channel_list_for_analytics,
    get_user_code, get_user_credits, get_user_language, get_user_onboarding,
    get_user_overview_stats, get_user_plan, get_user_setting,
    get_user_settings_bulk, increment_ai_usage, invalidate_user_overview_stats,
    is_premium, redeem_promo_code, referral_reward_for, refund_ai_request,
    refund_ai_usage, reserve_ai_request, save_user,
    set_user_full_menu_unlocked, set_user_language, set_user_plan,
    set_user_setting, total_referral_reward, transfer_user_credits,
    use_user_credit
)
# --- 📢 CHANNELS — kanal CRUD, monitoring, Channel DNA, manba/RSS, reklama
from repositories.channels_repository import (  # noqa: F401
    AD_BUTTON_TEXT_MAX_LEN, AD_BUTTON_URL_MAX_LEN, AD_INTERVAL_MAX,
    AD_INTERVAL_MIN, AD_SCOPES, AD_TEXT_MAX_LEN, CHANNEL_AD_INTERVAL_DEFAULT,
    CHANNEL_AD_INTERVAL_KEY, CONTENT_SOURCES_LIMIT, SOURCE_DRAFTS_LIMIT,
    SOURCE_DRAFT_STATUSES, VALID_TONES, _ad_row_to_dict,
    _content_source_row_to_dict, _normalize_ad_button,
    _source_draft_row_to_dict, add_ad, add_sponsor_channel,
    bump_channel_post_count, clamp_ad_interval, clear_ads, count_ads,
    count_source_drafts, create_content_source, create_source_draft,
    deactivate_channel_by_id, delete_ad, delete_content_source,
    get_active_sponsors, get_ad, get_ad_settings, get_ads, get_ads_full,
    get_all_channels, get_channel_ad_interval, get_channel_dna,
    get_channel_dna_profile, get_channel_intelligence_profile,
    get_channel_owner_id, get_channel_post_count, get_channel_post_counters,
    get_channel_post_events, get_channel_posts_history,
    get_channel_posts_history_stats, get_channel_settings, get_channel_tone,
    get_content_source, get_due_content_sources, get_recycle_candidates,
    get_source_draft, get_source_item_external_ids, get_sponsor_channels,
    get_user_channels, get_user_channels_with_tone, insert_channel_post_event,
    is_channel_connected, list_content_sources, list_source_drafts,
    mark_channel_ad_shown, mark_source_item_processed, remove_channel,
    remove_sponsor_channel, reset_channel_post_count, save_channel,
    save_channel_dna, save_channel_dna_profile,
    save_channel_intelligence_profile, save_channel_post_history,
    save_source_item, set_ad_active, set_ad_interval, set_ad_status,
    set_channel_ad_interval, set_channel_ad_status, set_channel_tone,
    set_comment_analysis, set_content_source_autopublish,
    set_content_source_enabled, set_content_source_interval,
    set_source_draft_status, toggle_ad_active, touch_content_source, update_ad,
    update_ad_text
)
# --- 📝 POSTS — post CRUD, statuslar, media, navbat (queue), shablonlar
from repositories.posts_repository import (  # noqa: F401
    DEFAULT_QUEUE_SLOTS, POST_TEMPLATES_LIMIT, _template_row_to_dict, add_post,
    cancel_post, count_post_templates, create_post_template,
    defer_post_deletion, delete_post_template, get_channel_post_stats,
    get_due_posts, get_pending_posts, get_post_by_id,
    get_post_delivery_options, get_post_health_counts, get_post_template,
    get_post_templates, get_posts_to_delete, get_queue_occupied_times,
    get_queue_post_count, get_queue_post_detail, get_queue_posts,
    get_queue_slots, get_recent_posts, mark_post_as_deleted, mark_post_as_sent,
    mark_post_processing, mark_post_status, reschedule_recurring_post,
    retry_post, set_queue_slots, toggle_reaction, update_post_content,
    update_post_time
)
# --- ⏰ SCHEDULER — rejalashtirish, delivery jobs, tiklash, tozalash
from repositories.scheduler_repository import (  # noqa: F401
    DELIVERY_MAX_ATTEMPTS, DELIVERY_STALE_PROCESSING_SECONDS,
    _delivery_channel_number, _delivery_processing_is_stale,
    build_delivery_idempotency_key, claim_post_delivery, cleanup_old_data,
    find_next_queue_slot, mark_post_delivery_failed, mark_post_delivery_sent,
    mark_post_delivery_unknown, recover_processing_posts_on_startup,
    recover_stale_processing_posts, schedule_week_posts
)
# --- 👥 TEAMS — jamoa a'zolari, rollar, taklif/tasdiq oqimi, audens insight
from repositories.teams_repository import (  # noqa: F401
    TEAM_ROLES, _invalidate_rbac_resource_cache, _member_role_valid,
    add_channel_member, approve_post, approve_workflow_post, create_draft_post,
    create_workflow_post, edit_workflow_post, get_audience_question_insights,
    get_channel_member, get_channel_member_role, get_channel_weekly_posts,
    get_workflow_post, list_channel_members, reject_post, reject_workflow_post,
    remove_channel_member, request_post_approval, schedule_approved_post,
    schedule_post_after_approval, set_channel_member_role,
    submit_post_for_approval, upsert_audience_question
)
# --- 💳 PAYMENTS — to'lov cheklari, holatlar, orderlar, kvitansiyalar
from repositories.payments_repository import (  # noqa: F401
    PAYMENT_METHODS, PAYMENT_METHOD_INTERNATIONAL_STARS,
    PAYMENT_METHOD_UZCARD_HUMO, PAYMENT_STATUSES, PAYMENT_STATUS_SUCCEEDED,
    RECEIPT_STATUS_PENDING, _normalize_payment_method,
    _payment_receipt_row_to_dict, approve_payment_receipt,
    attach_receipt_to_order, create_payment_order, get_payment_order,
    get_payment_receipt, get_payments_health_counts,
    get_pending_receipts_count, get_user_payment_history,
    list_payment_receipts, list_pending_payment_receipts, log_stars_payment,
    process_stars_payment, reject_payment_receipt, save_payment_receipt
)
# --- 🔐 AUDIT — xavfsizlik ro'llari, audit loglari, qo'llab-quvvatlash
from repositories.audit_repository import (  # noqa: F401
    AUDIT_ACTION_MAX_LEN, AUDIT_FIELD_MAX_LEN, SUPPORT_TICKET_TEXT_LIMIT,
    _support_ticket_row_to_dict, _valid_admin_role,
    attach_support_ticket_delivery, count_admin_audit_logs,
    count_user_support_tickets, create_support_ticket, delete_admin_role,
    get_admin_audit_logs, get_admin_dashboard_stats, get_admin_role,
    get_recent_support_tickets, get_support_ticket,
    get_support_ticket_by_admin_message, get_system_stats, list_admin_roles,
    log_admin_action, mark_support_ticket_answered, set_admin_role
)