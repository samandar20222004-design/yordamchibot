# PostAssist — PHP versiya (oddiy hosting uchun)

Bu Python botning PHP'dagi nusxasi: oddiy (shared) hostingda ishlaydi — Python, Docker yoki VPS kerak emas.
Tashqi kutubxona (Composer) ishlatilmagan: fayllarni yuklasangiz bo'ldi.

> **Holat: 1-bosqich (yadro).** Qaysi imkoniyatlar bor va qaysilari keyingi bosqichlarda — [docs/PHP_PORT.md](../docs/PHP_PORT.md).

## Talablar

| | |
|---|---|
| PHP | **7.4** yoki yangi (8.x ham ishlaydi) |
| Kengaytmalar | `pdo_mysql`, `curl`, `mbstring`, `json` (odatda hostingda yoqilgan) |
| Baza | MySQL 5.7+ yoki MariaDB 10.3+ |
| Domen | **HTTPS** (bepul Let's Encrypt SSL yetadi) — Telegram webhook faqat HTTPS'ga yuboradi |
| Cron | har daqiqada bir marta (rejalashtirilgan postlar uchun) |
| Joy | ~0,25 MB kod + baza (boshida 1 MB dan kam) |

## O'rnatish (cPanel / ISPmanager va shunga o'xshash panel)

1. **Baza yarating.** Panel → «MySQL bazalar»: yangi baza, foydalanuvchi va parol; foydalanuvchiga bazaga **barcha huquqlarni** bering.
2. **Fayllarni yuklang.** `php_bot` papkasi ichidagi hamma narsani (`src`, `sql`, `storage`, `.htaccess` fayllari bilan) masalan
   `public_html/postassist/` ga yuklang. `.htaccess` fayllari ko'rinmasa — fayl menejerida «yashirin fayllarni ko'rsatish» ni yoqing.
3. **Sozlamalar.** `config.example.php` dan nusxa olib `config.php` deb nomlang va to'ldiring:
   - `bot_token` — @BotFather tokeni, `bot_username` — bot nomi (@ siz), `admin_ids` — sizning Telegram ID'ingiz;
   - `db_*` — 1-qadamdagi baza ma'lumotlari;
   - `webhook_secret` va `cron_key` — har biriga kamida 16 belgili tasodifiy satr (faqat `A-Z a-z 0-9 _ -`);
   - `webhook_url` — `https://domeningiz.uz/postassist/webhook.php`.
4. **Ishga tushiring.** Brauzerda oching: `https://domeningiz.uz/postassist/setup.php?key=CRON_KEY`
   (yoki SSH: `php setup.php`). Hamma qatorda `OK` chiqishi kerak: jadvallar, webhook, buyruqlar menyusi.
5. **Cron qo'ying.** Panel → «Cron vazifalar» → **har daqiqa** (`* * * * *`):
   ```
   php /home/LOGIN/public_html/postassist/cron.php
   ```
   PHP yo'li hostingda boshqacha bo'lishi mumkin (masalan `/usr/local/bin/php` yoki `/opt/php74/bin/php`) — panel ko'rsatadi.
   CLI cron bo'lmasa: `wget -q -O - "https://domeningiz.uz/postassist/cron.php?key=CRON_KEY"`.
6. **Tekshiring.** Botga `/start` yozing → menyu chiqadi. Botni kanalingizga admin qiling, «📢 Kanallarim» → «➕ Kanal ulash»,
   kanaldan postni forward qiling. «✍️ Post yaratish» → matn → «🚀 Hozir yuborish».

## Xavfsizlik

- `config.php` da token va parol bor: uni hech kimga bermang, GitHub'ga qo'ymang (`.gitignore` da).
- `webhook.php` faqat Telegram yuborgan maxfiy kalit (`webhook_secret`) bilan ishlaydi; boshqa so'rovlar 403.
- `cron.php` va `setup.php` brauzerdan faqat `?key=CRON_KEY` bilan ochiladi.
- `.htaccess` `src/`, `sql/`, `tests/`, `storage/` va `config.php` ni brauzerdan yopadi (Apache). Nginx'da shu papkalarni
  `deny all` bilan yoping.
- Bazaga har so'rov tayyorlangan (prepared) holda yuboriladi; foydalanuvchi matni HTML-escape qilinadi.
- Kanal ulashda tekshiriladi: bot admin va xabar joylay oladi, foydalanuvchining o'zi kanal admini (begona kanal ulanmaydi).

## Xatolarni ko'rish

Xatolar `storage/bot.log` ga yoziladi (brauzerdan yopiq). Webhook holati:
`https://api.telegram.org/bot<TOKEN>/getWebhookInfo` — `last_error_message` maydoniga qarang.

## Testlar (dasturchi uchun)

```bash
# sinov bazasi (FAQAT sinov — jadvallar o'chiriladi!)
mysql -uroot -e "CREATE DATABASE pa_test; CREATE USER 'pa'@'localhost' IDENTIFIED BY 'pa_pass'; GRANT ALL ON pa_test.* TO 'pa'@'localhost';"
php tests/run.php          # PA_TEST_DB_HOST / _NAME / _USER / _PASS bilan o'zgartirish mumkin
```

Testlar: formatlash (UTF-16, emoji), vaqtni tushunish, havolalar, nishon, uch til pariteti, va haqiqiy MariaDB + soxta Telegram bilan
to'liq ssenariylar (start, referal, kanal ulash va rad etish holatlari, post, tugma, hozir yuborish, ikki marta bosish, vaqt belgilash,
limitlar, navbat, cron, qayta urinish, qulf, bot chiqarilishi, IDOR). CI'da PHP 7.4 va 8.3 da ishlaydi.
