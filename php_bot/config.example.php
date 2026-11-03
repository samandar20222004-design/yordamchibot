<?php
// Talab: PHP 7.4 yoki yangi, MySQL 5.7+ / MariaDB 10.3+, kengaytmalar: pdo_mysql, curl, mbstring, json.
// PostAssist (PHP) sozlamalari. Bu faylni `config.php` nomi bilan nusxalang va qiymatlarni to'ldiring.
// `config.php` ni hech kimga bermang va GitHub'ga qo'ymang (unda bot tokeni va baza paroli bor).
return [
    // @BotFather bergan token.
    'bot_token' => '123456789:AA...',
    // Bot username'i, @ belgisisiz (bepul tarif nishoni va havolalar uchun).
    'bot_username' => 'PostAssistrobot',
    // Adminlarning Telegram ID'lari.
    'admin_ids' => [123456789],

    // MySQL / MariaDB (hosting panelidagi «MySQL bazalar» bo'limidan).
    'db_host' => 'localhost',
    'db_port' => 3306,
    'db_name' => 'postassist',
    'db_user' => 'postassist',
    'db_pass' => '',

    // Webhook maxfiy kaliti: Telegram har so'rovda shu qiymatni sarlavhada yuboradi (A-Z, a-z, 0-9, _ -; 1-256 belgi).
    'webhook_secret' => 'uzun-tasodifiy-satr-yozing',
    // webhook.php ning to'liq HTTPS manzili (setup.php shu manzilga webhook o'rnatadi).
    'webhook_url' => 'https://sizning-domeningiz.uz/postassist/webhook.php',
    // cron.php va setup.php ni brauzerdan ochish uchun kalit (?key=...). CLI'da kerak emas.
    'cron_key' => 'boshqa-uzun-tasodifiy-satr',

    // Foydalanuvchiga ko'rsatiladigan vaqt mintaqasi (bazada vaqt UTC'da saqlanadi).
    'timezone' => 'Asia/Tashkent',
    // Bepul tarif limitlari (Python versiyadagi bilan bir xil: docs/PLANS.md).
    'free_max_channels' => 3,
    'free_max_queued' => 40,
];
