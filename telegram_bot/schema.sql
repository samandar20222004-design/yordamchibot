-- ============================================================
-- PostAssistBot (yordamchibot) — to'liq PostgreSQL sxemasi
-- ------------------------------------------------------------
-- Bu fayl database.py::_init_db_once() tomonidan bot har ishga
-- tushganda avtomatik bajariladi. Barcha operatorlar idempotent
-- (IF NOT EXISTS), shuning uchun faylni istalgancha qayta
-- bajarish mumkin — mavjud ma'lumotlarga zarar yetmaydi.
--
-- Neon/Render kabi boshqariladigan PostgreSQL'da bo'sh bazani
-- to'ldirish uchun ham shu fayldan foydalaniladi:
--     psql "$DATABASE_URL" -f telegram_bot/schema.sql
-- ============================================================

-- --- JADVALLAR ---

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
    language_code VARCHAR(10) DEFAULT 'uz',
    -- 🆕 Onboarding: foydalanuvchi "⚙️ To'liq menyuni ochish" tugmasini bosganmi?
    -- TRUE bo'lsa yangi foydalanuvchi ham darhol standart bosh menyuni ko'radi.
    full_menu_unlocked BOOLEAN DEFAULT FALSE,
    -- 🆕 6-bosqich (RBAC): rol ustuni. DEFAULT 'user' — eski yozuvlarning
    -- barchasi oddiy foydalanuvchi bo'lib qoladi (backward-compatible).
    role VARCHAR(20) DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id VARCHAR(255) UNIQUE NOT NULL,
    channel_title VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT
);

-- Avtomatik reklama rotatsiya puli. Har bir reklama (kanal posti yoki
-- bot javobi uchun) alohida qator; bot navbatma-navbat (round-robin)
-- ishlatadi. scope: 'channel' | 'reply'.
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
CREATE INDEX IF NOT EXISTS idx_ad_pool_scope ON ad_pool (scope, is_active);

-- Har bir kanal uchun yuborilgan postlar sanagichi. Reklama oralig'i
-- (masalan har 3-, 4- yoki 5-postda) shu sanagich asosida hisoblanadi,
-- shuning uchun kanallar bir-birining hisobiga ta'sir qilmaydi.
CREATE TABLE IF NOT EXISTS channel_post_counters (
    channel_id VARCHAR(255) PRIMARY KEY,
    post_count INTEGER NOT NULL DEFAULT 0,
    ad_count INTEGER NOT NULL DEFAULT 0,
    last_ad_post_number INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_channel_post_counters_updated
    ON channel_post_counters (updated_at DESC);

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

-- Telegramga yuborilgan har bir delivery uchun doimiy idempotency marker.
-- scheduled_posts tarixiy navbatni saqlaydi, bu jadval esa aynan Telegram
-- chaqiruvini bir marta bajarish kafolatini beradi.
-- PostAssist V2 (3-bosqich): statuslar 'pending' | 'processing' | 'sent' |
-- 'failed' | 'dead_letter' | 'unknown'. Vaqtinchalik xatolarda exponential
-- backoff (30s, 2m, 5m, 15m) next_retry_at orqali rejalashtiriladi;
-- 5-urinishdan keyin yoki doimiy xatoda (chat_not_found, bot_kicked)
-- 'dead_letter'. 'unknown' (UNKNOWN_DELIVERY, 11-bosqich) — Telegram API
-- javobi olinmagan (albom/media-group yuborishda TimedOut/NetworkError):
-- xabar kanalga chiqqan-chiqmagani NOMA'LUM, shuning uchun avtomatik
-- (blind) qayta yuborilmaydi — admin ko'rib chiqadi.
CREATE TABLE IF
NOT EXISTS post_deliveries (
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
ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
CREATE INDEX IF
NOT EXISTS idx_deliveries_sched ON post_deliveries(status, post_id);
CREATE INDEX IF
NOT EXISTS idx_deliveries_retry ON post_deliveries(status, next_retry_at);

CREATE TABLE IF NOT EXISTS post_reactions (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    user_id BIGINT NOT NULL,
    reaction_type VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, user_id)
);

-- Har bir recurring yuborishni alohida saqlaymiz: eski xabarlar ham o'chadi.
CREATE TABLE IF NOT EXISTS sent_post_messages (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    channel_id VARCHAR(255) NOT NULL,
    message_id BIGINT NOT NULL,
    delete_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE
);

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

-- Bir foydalanuvchi bitta promo-kodni faqat bir marta ishlata oladi.
CREATE TABLE IF
NOT EXISTS promo_redemptions (
    id BIGSERIAL PRIMARY KEY,
    promo_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    redeemed_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_promo_user UNIQUE (promo_id, user_id)
);

-- Real vaqtli kanal postlari tarixi (AI tahlil, kontent-reja va analitika uchun)
CREATE TABLE IF NOT EXISTS channel_posts_history (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(255) NOT NULL,
    message_id BIGINT,
    content TEXT,
    views INTEGER DEFAULT 0,
    post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_channel_posts_history_channel_date
    ON channel_posts_history (channel_id, post_date DESC);

-- Stars to'lovlari uchun alohida audit jadvali.
-- To'lovlar promo_codes jadvaliga yozilmaydi — har bir to'lov o'z
-- qatori bilan audit qilinadi (summa, valyuta, payload, charge_id).
-- PostAssist V2 (5-bosqich): status ustuni — to'lov audit holati
-- (pending | succeeded | failed | refunded) va (user_id, status) kompozit
-- indeksining qismi. DEFAULT tufayli eski yozuvlar 'succeeded' hisoblanadi.
-- 💳 payment_method: to'lov USULI ajratgichi (HUDUDIY tanlov — tilga bog'liq
-- EMAS): 'uzcard_humo' (🇺🇿 Uzcard / Humo, valyuta UZS) yoki
-- 'international_stars' (🌍 Telegram Stars / Crypto, valyuta XTR).
-- DEFAULT 'international_stars' — bu jadvalga yozilgan ESKI barcha
-- (Stars-only) yozuvlar migratsiyasiz to'g'ri nomlanadi.
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
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);

-- 💳 Karta orqali to'lov cheklari — Admin Approval Flow.
-- Foydalanuvchi chek (rasm/PDF) yuborganida pending holatida saqlanadi va
-- barcha adminlarga yuboriladi. Admin ✅ Tasdiqlash bosganda status='approved'
-- bo'lib, PRO muddati uzaytiriladi (atomik); ❌ Rad etishda 'rejected'.
-- amount_uzs — tanlangan tarifning so'mdagi summasi (CARD_TARIFFS). Admin
-- ✅ bosganda payments ledger'iga to'g'ri valyuta (UZS) va usul
-- ('uzcard_humo') bilan yozish uchun ishlatiladi; eski cheklarda 0.
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
CREATE INDEX IF NOT EXISTS idx_payment_receipts_status
    ON payment_receipts (status, created_at);

-- 💳 Karta to'lov buyurtmalari — chek user_data emas order_id ga bog'lanadi.
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
CREATE INDEX IF NOT EXISTS idx_payment_orders_user
    ON payment_orders (user_id, status);
ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS order_id TEXT;

-- 🔐 PostAssist V2 (6-bosqich): RBAC rollari.
-- ``users.role`` ustuni asosiy manba emas — aniq berilgan rollar shu jadvalda
-- saqlanadi (asosiy admin ``ADMIN_ID`` esa servis qatlamida avtomatik OWNER).
-- Jadval bo'sh bo'lsa ham bot avvalgidek ishlaydi: eski ``ADMIN_ID`` /
-- ``ADMIN_IDS`` ro'yxati orqali barcha adminlar taniladi.
CREATE TABLE IF NOT EXISTS admin_roles (
    user_id BIGINT PRIMARY KEY,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    granted_by BIGINT,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 📝 PostAssist V2 (6-bosqich): admin harakatlari auditi.
-- Har bir muhim admin amali (chek tasdiqlash/rad etish, PRO berish/bekor
-- qilish, promo yaratish, rol berish, tizim sozlamalari) shu jadvalga
-- yoziladi. Yozuv biznes tranzaksiyasi ICHIDA bajariladi — amal bajarilib,
-- audit yozuvi yo'qolib qolmaydi (atomiklik).
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
CREATE INDEX IF NOT EXISTS idx_audit_admin ON admin_audit_logs(admin_id, created_at);

-- 💰 PostAssist V2 (8-bosqich): credits ledger — AI-ballar auditi.
-- Har bir ball o'zgarishi (berilish = musbat, yechilish = manfiy) shu
-- jadvalga doimiy audit qatori qo'shiladi. ``balance_after`` — yozuvdan
-- keyingi balans; tarix bo'ylab to'liq hisob-kitobni tiklash imkonini beradi.
-- Jadval ``CreditsService`` (services/credits_service.py) orqali foydalanuvchi
-- bilan BIR tranzaksiyada yoziladi — balans va audit hech qachon uzil-kesik
-- qolmaydi. operation_type: 'daily_bonus' | 'referral' | 'ai_request' |
-- 'promo' | 'admin' (qo'shimcha: 'transfer' — foydalanuvchilararo o'tkazish).
CREATE TABLE IF NOT EXISTS credits_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INT NOT NULL, -- musbat (+10) yoki manfiy (-2)
    balance_after INT NOT NULL,
    operation_type VARCHAR(32) NOT NULL, -- 'daily_bonus', 'referral', 'ai_request', 'ai_refund', 'promo', 'admin'
    reference_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON credits_ledger(user_id, created_at);

-- 🔒 PHASE 2 / 1-QADAM: AI so'rov bronlari (atomik kvota + kredit).
-- ``reserve_ai_request()`` kunlik kvota YOKI kreditni BITTA tranzaksiyada
-- band qiladi va shu jadvalga bron qatorini yozadi. ``refund_ai_request()``
-- esa bronni ID bo'yicha, IDEMPOTENT tarzda qaytaradi (AI timeout/xatosida).
--
-- ``status``: 'active'  — bron amalda (so'rov hali bajarilmoqda);
--             'refunded'— bron qaytarilgan (kredit/kvota foydalanuvchiga qaytdi).
-- ``source``: 'daily_quota' — bepul kunlik kvotadan yechildi;
--             'credit'      — ai_credits balansidan yechildi.
-- Idempotentlik kafolati: refund FAQAT ``WHERE status = 'active'`` sharti bilan
-- bajariladi va natijada qaytargan qatoridagi ``source`` ga qarab qaytariladi —
-- bitta bronni ikki marta qaytarib bo'lmaydi (parallel refund'da ham).
CREATE TABLE IF NOT EXISTS ai_reservations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    operation_type VARCHAR(32) NOT NULL,
    cost INT NOT NULL DEFAULT 1,
    source VARCHAR(16) NOT NULL, -- 'daily_quota' | 'credit'
    status VARCHAR(16) NOT NULL DEFAULT 'active', -- 'active' | 'refunded'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    refunded_at TIMESTAMPTZ,
    CONSTRAINT chk_ai_reservations_source
        CHECK (source IN ('daily_quota', 'credit')),
    CONSTRAINT chk_ai_reservations_status
        CHECK (status IN ('active', 'refunded')),
    CONSTRAINT chk_ai_reservations_cost CHECK (cost > 0)
);
CREATE INDEX IF NOT EXISTS idx_ai_reservations_user
    ON ai_reservations(user_id, created_at);

-- --- MIGRATSIYALAR (eski bazalar uchun; yangi bazada allaqachon bor) ---
-- Eslatma: ADD COLUMN IF NOT EXISTS tufayli takroriy bajarish xavfsiz.

-- P0-01: eski payments jadvallarida bu ustun bo'lmasligi mumkin.
-- UNIQUE constraint uchun quyidagi normalizatsiya ham bajariladi: eski
-- implementatsiya bo'sh satr saqlagan bo'lsa, u idempotent NULL ga aylantiriladi.
ALTER TABLE payments ADD COLUMN IF NOT EXISTS telegram_payment_charge_id TEXT UNIQUE;
UPDATE payments SET telegram_payment_charge_id = NULL
 WHERE telegram_payment_charge_id IS NOT NULL AND BTRIM(telegram_payment_charge_id) = '';
-- Eski bazalarda ustun UNIQUE siz yaratilgan bo'lishi mumkin. Dublikat
-- charge-id'larni o'chirmasdan (auditni saqlab) faqat keyingi nusxalarni NULL
-- qilamiz va unique indexni yaratamiz.
WITH duplicate_charges AS (
    SELECT ctid, ROW_NUMBER() OVER (
        PARTITION BY telegram_payment_charge_id ORDER BY id
    ) AS rn
    FROM payments
    WHERE telegram_payment_charge_id IS NOT NULL
)
UPDATE payments p
SET telegram_payment_charge_id = NULL
FROM duplicate_charges d
WHERE p.ctid = d.ctid AND d.rn > 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_telegram_charge_id
    ON payments (telegram_payment_charge_id)
    WHERE telegram_payment_charge_id IS NOT NULL;

ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_code VARCHAR(8) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_credits INTEGER DEFAULT 5;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_posts INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_date DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_requests_today INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_limit_reset DATE DEFAULT CURRENT_DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS language_code VARCHAR(10) DEFAULT 'uz';
-- 🆕 Sodda klaviatura: foydalanuvchi to'liq menyuni o'zi ochganini eslab qolamiz
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_menu_unlocked BOOLEAN DEFAULT FALSE;
-- 🔐 PostAssist V2 (6-bosqich): RBAC rol ustuni (eski bazalarda yo'q).
-- DEFAULT 'user' tufayli mavjud yozuvlar oddiy foydalanuvchi bo'lib qoladi,
-- admin huquqi esa hamon ADMIN_ID/ADMIN_IDS orqali ishlayveradi.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';

ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_text VARCHAR(255);
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_url TEXT;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS enable_reactions BOOLEAN DEFAULT FALSE;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS reaction_emojis TEXT;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS delete_after_hours INTEGER DEFAULT 0;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS sent_message_id BIGINT;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS user_post_number INTEGER;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_type VARCHAR(20) DEFAULT 'none';
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_day INTEGER;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_time TIME;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS end_date TIMESTAMP WITH TIME ZONE;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE scheduled_posts ALTER COLUMN file_id TYPE TEXT;

ALTER TABLE channels ADD COLUMN IF NOT EXISTS tone_of_voice VARCHAR(30) DEFAULT 'friendly';

ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS invite_link TEXT;
ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_title VARCHAR(255);
ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_url VARCHAR(255);
ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- Reklama puli: HTML matn + inline URL tugma (tugma matni va havolasi).
ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_text VARCHAR(64);
ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_url TEXT;
ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Kanal postlari tarixi migratsiyalari
ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS message_id BIGINT;
ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 0;
ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- PostAssist V2 (3-bosqich): persistent delivery + backoff ustunlari.
ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS scheduled_time TIMESTAMPTZ;

-- PostAssist V2 (5-bosqich): to'lov audit holati. ADD COLUMN IF NOT EXISTS +
-- NOT NULL DEFAULT tufayli (PostgreSQL 11+ "fast default") migratsiya bir
-- necha milisekundda bajariladi va mavjud qatorlar 'succeeded' deb hisoblanadi.
ALTER TABLE payments ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'succeeded';

-- 💳 To'lov usuli (payment region feature, additive): ledger'da mahalliy va
-- xalqaro to'lovlar AJRATILIB saqlanadi — usul + valyuta birga yuradi.
-- Eski yozuvlar (FAQAT Stars bo'lgan) DEFAULT tufayli 'international_stars'.
ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32) NOT NULL DEFAULT 'international_stars';
-- Karta cheki summasi (so'm) — approve bo'lganda UZS ledger yozuvi uchun.
ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS amount_uzs INT DEFAULT 0;

-- --- INDEKSLAR (eng ko'p ishlatiladigan qidiruvlar uchun) ---
-- users.user_id PRIMARY KEY bo'lgani uchun u yerda indeks avtomatik mavjud.

CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_id ON scheduled_posts (user_id);
CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels (user_id);
CREATE INDEX IF NOT EXISTS idx_post_reactions_post_id ON post_reactions (post_id);

-- ============================================================
-- POSTASSIST V2 — 5-BOSQICH: MA'LUMOTLAR BUTUNLIGI
-- (composite indekslar + foreign key / check / unique constraintlar)
-- ------------------------------------------------------------
-- 1) INDEKSLAR. Barchasi IF NOT EXISTS — qayta-bajarish bepul va xavfsiz.
--    Eslatma: topshiriqda so'ralgan scheduled_posts.scheduled_at ustuni
--    sxemada scheduled_time deb yuritiladi (va unda allaqachon
--    idx_scheduled_posts_status_time bor), shuning uchun idx_posts_sched_status
--    shu ustun bilan va FAQAT 'pending' navbatini qamrab oluvchi qismiy
--    (partial) indeks sifatida quriladi — scheduler'ning eng issiq so'rovi
--    aynan shu, indeks esa butun jadvaldan bir necha barobar kichik.
--    Xuddi shu sababli idx_channels_owner idx_channels_user_id'ni takrorlamaydi:
--    u faqat faol kanallarni qamrab oluvchi partial indeks.
-- ============================================================

-- Scheduler navbati: status='pending' AND scheduled_time <= now ORDER BY scheduled_time
CREATE INDEX IF NOT EXISTS idx_posts_sched_status ON scheduled_posts (status, scheduled_time) WHERE status = 'pending';
-- Delivery qidiruvi: holat + post + kanallar bo'yicha bitta indeksda
CREATE INDEX IF NOT EXISTS idx_deliveries_lookup ON post_deliveries (status, post_id, channel_id);
-- To'lov tarixi holat bilan
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id, status);
-- Kanallar ro'yxati (faqat faollar) — get_user_channels / tone so'rovlari
CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels (user_id) WHERE is_active = TRUE;
-- FK ustunlarini indekslash: ota qatorni o'chirishda (ON DELETE CASCADE)
-- PostgreSQL bola jadvalini seq scan qilmasin.
CREATE INDEX IF NOT EXISTS idx_scheduled_posts_channel ON scheduled_posts (channel_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_post ON post_deliveries (post_id);

-- ============================================================
-- 2) CONSTRAINTLAR. Har bir obyekt alohida "xavfsiz" blokda:
--      * mavjud bo'lsa — CONTINUE (idempotent, qayta iskga tushirishda
--        hech qanday qulf/lock olinmaydi);
--      * eski (legacy) yozuvlar talabga javob bermasa — constraint
--        NOT VALID holatida qo'shiladi: tarixiy ma'lumot O'CHIRILMAYDI va
--        O'ZGARTIRILMAYDI, ammo barcha YANGI yozuvlar himoyalanadi.
--        Keyinchalik "ALTER TABLE ... VALIDATE CONSTRAINT" bilan tugatiladi
--        (database.validate_integrity_constraints() yordamchisi shuni qiladi).
--      * kutilmagan xato faqat RAISE WARNING — bot ishlayveradi.
--
--    E'lon qilingan nomlar sxemaning haqiqiy ustunlariga moslashtirildi:
--      channels.user_id      → users(user_id)      (users PK'si "id" emas)
--      scheduled_posts.channel_id → channels(channel_id)  (VARCHAR→VARCHAR;
--                               channels.id — int surrogate, tipsiz mos kelmaydi)
--      post_deliveries.post_id    → scheduled_posts(id)
--      post_reactions.post_id     → scheduled_posts(id)
--      promo_redemptions: UNIQUE (promo_id, user_id) tekshiriladi
--    ============================================================

-- 11-bosqich migratsiyasi: mavjud bazalarda eski status CHECK'lari
-- ('unknown' qiymatisiz) bo'lsa — tashlanadi, quyidagi idempotent blok
-- yangi ta'rif bilan qayta qo'shadi. Yangi baza uchun no-op.
DO $postassist_unknown_status_migration$
DECLARE
    spec RECORD;
    cur_def TEXT;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('post_deliveries', 'chk_post_deliveries_status'),
            ('scheduled_posts', 'chk_scheduled_posts_status')
        ) AS t(tbl, cname)
    LOOP
        IF to_regclass(spec.tbl) IS NULL THEN
            CONTINUE;
        END IF;
        SELECT pg_get_constraintdef(c.oid) INTO cur_def
          FROM pg_constraint c
         WHERE c.conrelid = spec.tbl::regclass AND c.conname = spec.cname;
        IF cur_def IS NOT NULL AND position('unknown' in cur_def) = 0 THEN
            EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', spec.tbl, spec.cname);
            RAISE NOTICE 'integrity: %.% eski ta''rifi tashlandi (unknown status uchun yangilanadi)',
                         spec.tbl, spec.cname;
        END IF;
    END LOOP;
END
$postassist_unknown_status_migration$;

DO $postassist_integrity$
DECLARE
    spec RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('channels', 'fk_channels_user', 'fk', 'FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE'),
            ('scheduled_posts', 'fk_scheduled_posts_channel', 'fk', 'FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE'),
            ('post_deliveries', 'fk_post_deliveries_post', 'fk', 'FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE'),
            ('post_reactions', 'fk_post_reactions_post', 'fk', 'FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE'),
            ('promo_redemptions', 'uq_promo_user', 'unique', 'UNIQUE (promo_id, user_id)'),
            ('post_deliveries', 'chk_post_deliveries_status', 'check', 'CHECK (status IN (''pending'', ''processing'', ''sent'', ''failed'', ''dead_letter'', ''unknown''))'),
            ('scheduled_posts', 'chk_scheduled_posts_status', 'check', 'CHECK (status IN (''pending'', ''processing'', ''posted'', ''failed'', ''cancelled'', ''completed'', ''unknown''))'),
            ('payments', 'chk_payments_status', 'check', 'CHECK (status IN (''pending'', ''succeeded'', ''failed'', ''refunded''))'),
            ('credits_ledger', 'fk_credits_ledger_user', 'fk', 'FOREIGN KEY (user_id) REFERENCES users(user_id)'),
            ('ai_reservations', 'fk_ai_reservations_user', 'fk', 'FOREIGN KEY (user_id) REFERENCES users(user_id)')
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
$postassist_integrity$;
