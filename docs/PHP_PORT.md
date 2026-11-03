# PostAssist — Python → PHP ko'chirish rejasi

Maqsad: botni oddiy (shared) PHP hostingda ishlatish (masalan myxvest). Python versiya (`telegram_bot/`) o'zgarmaydi;
PHP versiya alohida papkada — `php_bot/` (o'rnatish: [php_bot/README.md](../php_bot/README.md)).

## Asosiy qarorlar

| | Python | PHP |
|---|---|---|
| Ishlash usuli | doimiy jarayon (polling/webhook) | **webhook** — har yangilanish alohida so'rov |
| Rejalashtirilgan yuborish | APScheduler (har daqiqa) | **cron.php** har daqiqa (MySQL qulfi, ikki marta ishlamaydi) |
| Suhbat holati | xotirada (ConversationHandler) | bazada (`user_states`, 48 soat) |
| Baza | PostgreSQL | **MySQL 5.7+ / MariaDB 10.3+** |
| Til versiyasi | Python 3.11 | **PHP 7.4+** (8.x ham), tashqi kutubxonasiz |
| Vaqt | UTC saqlanadi, Toshkent ko'rsatiladi | xuddi shunday (`timezone` sozlamasi) |

## Bosqichlar

| Bosqich | Tarkibi | Holat |
|---|---|---|
| **1. Yadro** | start, referal (`ref_`), til (uz/ru/en), bosh menyu, kanal ulash/o'chirish (bot va foydalanuvchi admin tekshiruvi, bot chiqarilsa avtomatik o'chirish), oddiy post (matn, rasm, video, GIF, audio, hujjat; formatlash saqlanadi), havolali tugma, tahrirlash, hozir yuborish (rost natija), vaqt belgilash (tabiiy ifodalar va tezkor tugmalar), navbat (ko'rish/bekor), cron yuborish (qayta urinish, qulf, tiklash), bepul nishon, limitlar (3 kanal / 40 post), statistika, admin statistika | ✅ tayyor |
| 2. Tariflar | PRO/ULTRA, Telegram Stars, promo-kod, referal ballari, manba havolalari (`s_`), limitlar tarif bo'yicha | ⏳ |
| 3. Kengaytirilgan post | takroriy postlar (har kuni/hafta/oy, kuniga 2 marta), albom, reaksiya, avto-o'chirish, vaqt mintaqasi (`/timezone`) | ⏳ |
| 4. AI | Magic Post, rasmdan post, AI yordamchi, AI byudjeti va kreditlar | ⏳ |
| 5. Pul va admin | karta/Payme to'lov, majburiy obuna, reklama, broadcast, to'liq admin panel, promo boshqaruvi | ⏳ |
| 6. Birja va jamoa | reklama birjasi (firibgarlikdan himoya bilan), jamoa va rollar | ⏳ |
| 7. Mini App | Mini App API (PHP), analitika | ⏳ |

Har bosqich: kod + uch tilda matn + testlar (unit va haqiqiy MariaDB) + PHP 7.4 tekshiruvi (CI `php` vazifasi).

## 1-bosqichdagi farqlar (Python'ga nisbatan)

- Yangi foydalanuvchi uchun soddalashtirilgan menyu, aqlli qabul («Bu bilan nima qilamiz?»), AI tugmalari hali yo'q.
- Barcha foydalanuvchilar hozircha FREE (nishon bilan); adminlar — nishonsiz va limitsiz. Tariflar 2-bosqichda.
- Takroriy post, albom, reaksiya, avto-o'chirish yo'q (3-bosqich).
- Vaqt mintaqasi hamma uchun bitta (`config.php` → `timezone`).

## Ma'lumotni ko'chirish

Python bot ishlab turgan bo'lsa, foydalanuvchilar va kanallarni PostgreSQL'dan MySQL'ga ko'chirish skripti alohida yoziladi
(foydalanuvchilar, tillar, kanallar, navbatdagi postlar). Ko'chirishdan oldin ikkala bot bir vaqtda ishlamasligi kerak
(bitta token — bitta webhook).
