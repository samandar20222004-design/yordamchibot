-- PostAssist (PHP) — MySQL 5.7+ / MariaDB 10.3+ sxemasi. Qayta ishga tushirsa ham xavfsiz (IF NOT EXISTS).
-- Hamma vaqt ustunlari UTC (ulanishda time_zone = '+00:00').

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT NOT NULL PRIMARY KEY,
    username VARCHAR(64) NULL,
    full_name VARCHAR(255) NULL,
    lang VARCHAR(5) NOT NULL DEFAULT 'uz',
    lang_chosen TINYINT(1) NOT NULL DEFAULT 0,
    referrer_id BIGINT NULL,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'free',
    subscription_expires_at DATETIME NULL,
    plan_reminder_for DATETIME NULL,
    ai_credits INT NOT NULL DEFAULT 5,
    referral_rewarded_at DATETIME NULL,
    is_blocked TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    last_active_at DATETIME NULL,
    KEY idx_users_created (created_at),
    KEY idx_users_referrer (referrer_id),
    KEY idx_users_plan (plan_type, subscription_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Suhbat holati (PHP har so'rovda qaytadan ishga tushadi, shuning uchun holat bazada saqlanadi).
CREATE TABLE IF NOT EXISTS user_states (
    user_id BIGINT NOT NULL PRIMARY KEY,
    state VARCHAR(40) NOT NULL,
    data MEDIUMTEXT NULL,
    updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS channels (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    title VARCHAR(255) NULL,
    username VARCHAR(64) NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_channels_channel (channel_id),
    KEY idx_channels_user (user_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- status: pending -> processing -> sent | failed | cancelled
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    post_type VARCHAR(16) NOT NULL DEFAULT 'text',
    text MEDIUMTEXT NULL,
    file_id VARCHAR(255) NULL,
    button_text VARCHAR(64) NULL,
    button_url VARCHAR(512) NULL,
    scheduled_time DATETIME NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    last_error VARCHAR(255) NULL,
    message_id BIGINT NULL,
    notify_owner TINYINT(1) NOT NULL DEFAULT 1,
    processing_started_at DATETIME NULL,
    sent_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    KEY idx_posts_due (status, scheduled_time),
    KEY idx_posts_user (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Telegram bir xil yangilanishni qayta yuborsa (tarmoq uzilishi), ikki marta ishlamasligi uchun.
CREATE TABLE IF NOT EXISTS processed_updates (
    update_id BIGINT NOT NULL PRIMARY KEY,
    created_at DATETIME NOT NULL,
    KEY idx_updates_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================== 2-bosqich: tariflar, to'lov, promo, ballar, manba havolalari =====================

-- Telegram Stars to'lovlari. charge_id UNIQUE — bir to'lov ikki marta tarif bermaydi (Telegram qayta yuborsa ham).
CREATE TABLE IF NOT EXISTS payments (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    provider VARCHAR(16) NOT NULL DEFAULT 'stars',
    amount INT NOT NULL,
    currency VARCHAR(8) NOT NULL,
    payload VARCHAR(128) NOT NULL,
    charge_id VARCHAR(128) NOT NULL,
    plan_key VARCHAR(8) NOT NULL,
    tier VARCHAR(16) NOT NULL,
    days INT NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_payments_charge (charge_id),
    KEY idx_payments_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Promo-kodlar: faqat pro/ultra beradi. max_uses NULL = cheksiz.
CREATE TABLE IF NOT EXISTS promo_codes (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    plan_type VARCHAR(16) NOT NULL DEFAULT 'pro',
    duration_days INT NOT NULL,
    max_uses INT NULL,
    current_uses INT NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    expires_at DATETIME NULL,
    created_by BIGINT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_promo_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bir foydalanuvchi bir kodni faqat bir marta ishlatadi (PRIMARY KEY).
CREATE TABLE IF NOT EXISTS promo_redemptions (
    promo_id INT NOT NULL,
    user_id BIGINT NOT NULL,
    redeemed_at DATETIME NOT NULL,
    PRIMARY KEY (promo_id, user_id),
    KEY idx_redemptions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Noto'g'ri promo urinishlari (kod taxmin qilishga qarshi: 10 daqiqada 5 ta).
CREATE TABLE IF NOT EXISTS promo_attempts (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL,
    KEY idx_attempts_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ballar (AI kreditlari) tarixi: har o'zgarish yoziladi.
CREATE TABLE IF NOT EXISTS credits_ledger (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INT NOT NULL,
    balance_after INT NOT NULL,
    operation_type VARCHAR(32) NOT NULL,
    reference_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL,
    KEY idx_ledger_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Manba havolalari: https://t.me/<bot>?start=s_<kod> — kim qaysi reklama/hamkor havolasidan keldi.
CREATE TABLE IF NOT EXISTS tracked_links (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(24) NOT NULL,
    title VARCHAR(80) NOT NULL,
    owner_id BIGINT NULL,
    created_by BIGINT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    clicks INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_tracked_code (code),
    KEY idx_tracked_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bitta foydalanuvchi + bitta havola = bitta qator. is_new — shu havola bilan ro'yxatdan o'tgan (birinchi tegish).
CREATE TABLE IF NOT EXISTS tracked_link_visits (
    link_id INT NOT NULL,
    user_id BIGINT NOT NULL,
    is_new TINYINT(1) NOT NULL DEFAULT 0,
    first_at DATETIME NOT NULL,
    first_post_at DATETIME NULL,
    PRIMARY KEY (link_id, user_id),
    KEY idx_visits_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
