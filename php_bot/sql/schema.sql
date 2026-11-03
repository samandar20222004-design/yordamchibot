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
    is_blocked TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    last_active_at DATETIME NULL,
    KEY idx_users_created (created_at)
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
