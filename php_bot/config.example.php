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

    // 💳 Karta orqali to'lov (so'm). Bo'sh qoldirsangiz — faqat Telegram Stars. Chek adminlarga boradi, ✅ bosilsa tarif yoqiladi.
    'card_number' => '',          // masalan '8600 1234 5678 9012'
    'card_holder' => '',          // karta egasi
    // Payme (avtomatik to'lov). Kabinet: business.paycom.uz -> Kassa -> «Endpoint URL»: https://<domen>/<papka>/payme.php
    'payme_merchant_id' => '',    // kassa ID (merchant)
    'payme_key' => '',            // kassa kaliti (test yoki asosiy) — HECH KIMGA BERMANG
    'payme_test' => false,        // true — sinov muhiti (checkout.test.paycom.uz)
    // 'uzs_prices' => ['1m' => 29000, 'u1m' => 69000],   // so'm narxlarini o'zgartirish (standart: PRO 29 000/75 000/135 000/245 000, ULTRA 69 000/175 000/335 000/620 000)

    // ✨ AI (bepul kalitlar yetadi; kamida bittasi bo'lsa AI tugmalari chiqadi, birinchisi ishlamasa — keyingisi):
    //  - Google Gemini: https://aistudio.google.com/apikey  (tavsiya, o'zbek tilini yaxshi biladi)
    //  - Groq:          https://console.groq.com/keys
    //  - OpenRouter:    https://openrouter.ai/keys
    'gemini_api_key' => '',
    'groq_api_key' => '',
    'openrouter_api_key' => '',
    // Model nomlari (ixtiyoriy). setup.php «model topilmadi» desa — provayder saytidagi yangi nomni shu yerga yozing.
    // 'gemini_model' => 'gemini-3.8-flash',   // bo'sh qoldirsangiz bot o'zi mos modelni topadi
    // 'groq_model' => 'llama-3.3-70b-versatile',
    // 'openrouter_model' => 'meta-llama/llama-3.3-70b-instruct:free',
    // Kunlik AI so'rovlari (standart: free 5, pro 40, ultra 100). Tugasa — ballar ishlatiladi.
    // 'ai_daily' => ['free' => 5, 'pro' => 40, 'ultra' => 100],

    // Ixtiyoriy (2-bosqich): Telegram Stars narxlarini o'zgartirish. Yozilmasa — standart: PRO 195/510/910/1650,
    // ULTRA 470/1180/2260/4180 (1/3/6/12 oy). Kalitlar: 1m 3m 6m 1y (PRO), u1m u3m u6m u1y (ULTRA).
    // 'stars_prices' => ['1m' => 195, 'u1m' => 470],
    // Ixtiyoriy: PRO/ULTRA limitlari (standart: PRO 10 kanal / 300 post, ULTRA 30 / 900).
    // 'tier_limits' => ['pro' => ['channels' => 10, 'queue' => 300]],
];
