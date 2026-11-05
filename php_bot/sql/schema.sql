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
    timezone VARCHAR(64) NULL,
    uz_verified TINYINT(1) NOT NULL DEFAULT 0,
    sub_ok_until DATETIME NULL,
    workspace_owner BIGINT NULL,
    phone_verified TINYINT(1) NOT NULL DEFAULT 0,
    market_banned TINYINT(1) NOT NULL DEFAULT 0,
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
    media MEDIUMTEXT NULL,
    reactions VARCHAR(64) NULL,
    delete_after INT NULL,
    recurrence_type VARCHAR(10) NULL,
    recurrence_time INT NULL,
    recurrence_day INT NULL,
    sent_count INT NOT NULL DEFAULT 0,
    created_by BIGINT NULL,
    options VARCHAR(40) NULL,
    hidden_text TEXT NULL,
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

-- ===================== 3-bosqich: takroriy post, albom, reaksiya, avto-o'chirish, vaqt mintaqasi =====================

-- Kanalga chiqqan har bir xabar (takroriy post har safar yangi xabar). Reaksiya va avto-o'chirish shu jadval orqali.
CREATE TABLE IF NOT EXISTS sent_messages (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    post_id INT NOT NULL,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    extra_ids VARCHAR(255) NULL,
    reactions VARCHAR(64) NULL,
    button_text VARCHAR(64) NULL,
    button_url VARCHAR(512) NULL,
    hidden_text TEXT NULL,
    delete_at DATETIME NULL,
    delete_attempts INT NOT NULL DEFAULT 0,
    deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_sent_msg (chat_id, message_id),
    KEY idx_sent_delete (deleted, delete_at),
    KEY idx_sent_post (post_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Reaksiya tugmalari ovozlari: bitta odam bitta xabarda bitta reaksiya (qayta bossa — olib tashlanadi).
CREATE TABLE IF NOT EXISTS reaction_votes (
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    idx TINYINT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (chat_id, message_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Albom (media group) qismlari: Telegram har rasmni alohida yuboradi — oxirgisi kelgach bitta postga yig'iladi.
CREATE TABLE IF NOT EXISTS album_items (
    user_id BIGINT NOT NULL,
    group_id VARCHAR(64) NOT NULL,
    message_id BIGINT NOT NULL,
    item_type VARCHAR(16) NOT NULL,
    file_id VARCHAR(255) NOT NULL,
    caption MEDIUMTEXT NULL,
    recv_ms BIGINT NOT NULL,
    PRIMARY KEY (user_id, group_id, message_id),
    KEY idx_album_recv (recv_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Yig'ib bo'lingan albomlar (bir albom ikki marta post bo'lmasin).
CREATE TABLE IF NOT EXISTS album_done (
    user_id BIGINT NOT NULL,
    group_id VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================== 4-bosqich: AI =====================

-- AI so'rovlari: kuniga tarif bo'yicha (FREE 5, PRO 40, ULTRA 100); tugasa — ballar (ai_credits) ishlatiladi.
CREATE TABLE IF NOT EXISTS ai_usage (
    user_id BIGINT NOT NULL,
    day DATE NOT NULL,
    used INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================== 5-bosqich: karta to'lovi (chek), hammaga xabar, majburiy obuna =====================

-- Karta orqali to'lov cheklari. status: pending -> approved | rejected (qaror bir marta, atomik).
CREATE TABLE IF NOT EXISTS payment_receipts (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    plan_key VARCHAR(8) NOT NULL,
    tier VARCHAR(16) NOT NULL,
    days INT NOT NULL,
    amount_uzs INT NOT NULL,
    media_type VARCHAR(16) NOT NULL,
    file_id VARCHAR(255) NOT NULL,
    file_unique_id VARCHAR(64) NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    decided_by BIGINT NULL,
    decided_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    KEY idx_receipts_user (user_id, status),
    KEY idx_receipts_uid (file_unique_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Hammaga xabar: admin xabari copyMessage bilan nusxalanadi; cron bo'laklab yuboradi (last_user_id — kursor).
CREATE TABLE IF NOT EXISTS broadcasts (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    admin_id BIGINT NOT NULL,
    from_chat BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'running',
    total INT NOT NULL DEFAULT 0,
    sent INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    blocked INT NOT NULL DEFAULT 0,
    last_user_id BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    KEY idx_broadcasts_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Majburiy obuna kanallari: foydalanuvchi shularga a'zo bo'lmaguncha bot ishlamaydi (adminlar bundan mustasno).
CREATE TABLE IF NOT EXISTS forced_channels (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    title VARCHAR(255) NULL,
    username VARCHAR(64) NULL,
    invite_link VARCHAR(255) NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_forced_chat (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================== Jamoa va rollar =====================

-- ULTRA egasi + 2 yordamchi. perms: create, send_now, delete, ai (vergul bilan).
CREATE TABLE IF NOT EXISTS team_members (
    owner_id BIGINT NOT NULL,
    member_id BIGINT NOT NULL,
    perms VARCHAR(64) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL,
    PRIMARY KEY (owner_id, member_id),
    KEY idx_team_member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bir martalik taklif havolalari (/start team_<token>); bazada faqat token xeshi.
CREATE TABLE IF NOT EXISTS team_invites (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    token_hash CHAR(64) NOT NULL,
    perms VARCHAR(64) NOT NULL DEFAULT '',
    expires_at DATETIME NOT NULL,
    used_by BIGINT NULL,
    used_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_team_token (token_hash),
    KEY idx_team_inv_owner (owner_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================== 💰 Reklama birjasi =====================
-- Pul botdan O'TMAYDI: bot faqat kanal katalogi va xavfsiz yozishma (kontakt faqat egasining o'zi ruxsat bersa).
CREATE TABLE IF NOT EXISTS market_listings (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    title VARCHAR(255) NULL,
    username VARCHAR(64) NOT NULL,
    category VARCHAR(20) NOT NULL DEFAULT 'other',
    price BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'UZS',
    description VARCHAR(500) NULL,
    subscribers INT NOT NULL DEFAULT 0,
    status VARCHAR(12) NOT NULL DEFAULT 'active',
    reports INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_market_channel (channel_id),
    KEY idx_market_cat (status, category, subscribers),
    KEY idx_market_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS market_threads (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    listing_id INT NOT NULL,
    buyer_id BIGINT NOT NULL,
    owner_id BIGINT NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'open',
    messages INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    last_at DATETIME NOT NULL,
    UNIQUE KEY uq_market_thread (listing_id, buyer_id),
    KEY idx_market_thread_buyer (buyer_id, last_at),
    KEY idx_market_thread_owner (owner_id, last_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS market_messages (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    thread_id INT NOT NULL,
    sender_id BIGINT NOT NULL,
    body TEXT NOT NULL,
    norm_hash CHAR(40) NOT NULL,
    created_at DATETIME NOT NULL,
    KEY idx_market_msg_thread (thread_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Shikoyatlar: e'longa (3 ta -> e'lon yopiladi) va foydalanuvchiga «firibgar» (3 ta -> birjadan ban). Bir kishi — bir marta.
CREATE TABLE IF NOT EXISTS market_reports (
    kind VARCHAR(8) NOT NULL,
    target_id BIGINT NOT NULL,
    reporter_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (kind, target_id, reporter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8-bosqich: AI kontent-reja va autopilot
CREATE TABLE IF NOT EXISTS content_plans (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    topic VARCHAR(500) NOT NULL,
    items TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    KEY idx_cp_user (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS autopilots (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_ref INT UNSIGNED NOT NULL,
    topic VARCHAR(500) NOT NULL,
    style VARCHAR(16) NOT NULL DEFAULT 'useful',
    post_time SMALLINT NOT NULL,
    mode VARCHAR(8) NOT NULL DEFAULT 'review',
    active TINYINT(1) NOT NULL DEFAULT 1,
    last_run DATE NULL,
    recent TEXT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_ap_channel (user_id, channel_ref),
    KEY idx_ap_active (active, last_run)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS autopilot_drafts (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    autopilot_id INT UNSIGNED NOT NULL,
    user_id BIGINT NOT NULL,
    channel_ref INT UNSIGNED NOT NULL,
    text TEXT NOT NULL,
    status VARCHAR(8) NOT NULL DEFAULT 'new',
    created_at DATETIME NOT NULL,
    KEY idx_apd_user (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9-bosqich: Payme (Merchant API)
CREATE TABLE IF NOT EXISTS payme_orders (
    order_id VARCHAR(32) NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    plan_key VARCHAR(8) NOT NULL,
    tier VARCHAR(16) NOT NULL,
    days INT NOT NULL,
    amount_tiyin BIGINT NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL,
    KEY idx_pmo_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payme_transactions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    payme_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(32) NOT NULL,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    state TINYINT NOT NULL,
    payme_time BIGINT NOT NULL,
    create_time BIGINT NOT NULL,
    perform_time BIGINT NOT NULL DEFAULT 0,
    cancel_time BIGINT NOT NULL DEFAULT 0,
    reason INT NULL,
    UNIQUE KEY uq_pmt_payme (payme_id),
    KEY idx_pmt_order (order_id, state),
    KEY idx_pmt_time (payme_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
