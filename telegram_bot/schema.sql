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
    language_code VARCHAR(10) DEFAULT 'uz'
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount INT,
    currency VARCHAR(10),
    payload TEXT,
    telegram_payment_charge_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);

-- --- MIGRATSIYALAR (eski bazalar uchun; yangi bazada allaqachon bor) ---
-- Eslatma: ADD COLUMN IF NOT EXISTS tufayli takroriy bajarish xavfsiz.

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

-- --- INDEKSLAR (eng ko'p ishlatiladigan qidiruvlar uchun) ---
-- users.user_id PRIMARY KEY bo'lgani uchun u yerda indeks avtomatik mavjud.

CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_id ON scheduled_posts (user_id);
CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels (user_id);
CREATE INDEX IF NOT EXISTS idx_post_reactions_post_id ON post_reactions (post_id);
