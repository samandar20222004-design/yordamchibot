# PostAssist — PHP versiya (oddiy hosting uchun)

Bu Python botning PHP'dagi nusxasi: oddiy (shared) hostingda ishlaydi — Python, Docker yoki VPS kerak emas.
Tashqi kutubxona (Composer) ishlatilmagan: fayllarni yuklasangiz bo'ldi.

> **Holat: 3-bosqich** (yadro + tariflar, Telegram Stars, promo-kod, referal ballari, manba havolalari + takroriy post, albom,
> reaksiya, avto-o'chirish, har foydalanuvchiga vaqt mintaqasi).
> Qaysi imkoniyatlar bor va qaysilari keyingi bosqichlarda — [docs/PHP_PORT.md](../docs/PHP_PORT.md).

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

## Yangilash (oldingi bosqich o'rnatilgan bo'lsa)

1. Yangi fayllarni eskilari ustiga yuklang. **`config.php` va `storage/` ga tegmang.**
2. `https://domeningiz.uz/postassist/setup.php?key=CRON_KEY` ni bir marta oching — yangi jadvallar va ustunlar qo'shiladi
   (eski foydalanuvchi, kanal va postlar saqlanadi), webhook yangi turdagi yangilanishlar (to'lov) bilan qayta o'rnatiladi.

## To'lov (Telegram Stars)

Qo'shimcha sozlash kerak emas: Stars to'lovi uchun provayder tokeni talab qilinmaydi. Foydalanuvchi: ⚙️ Sozlamalar →
«💎 Tariflar» → PRO/ULTRA → muddat → Telegram oynasida to'laydi; tarif darhol yoqiladi. Narxlarni `config.php` →
`stars_prices` bilan o'zgartirish mumkin. Yig'ilgan Stars — @BotFather → bot → Payments (Fragment orqali yechiladi).

Admin buyruqlari: `/admin_help` (tarif berish, promo-kodlar, manba havolalari).

## 🖼 Rasm va 🎤 ovozdan post

`gemini_api_key` bo'lsa: botga rasm tashlang → «✨ AI bilan» → uslub → tayyor izoh (rasm izohi — ko'rsatma). Ovozli xabar yuboring (≤3 daqiqa) — bot tinglab, post yozadi.
Faqat Gemini rasm/ovozni tushunadi (Groq/OpenRouter — faqat matn). Fayl 5 MB gacha.

## 💳 Karta (so'm), 📣 xabar yuborish, 🔒 majburiy obuna

- **Karta:** `config.php` → `'card_number' => '8600 ...'`, `'card_holder' => '...'`. Foydalanuvchi ⚙️ Sozlamalar → «💎 Tariflar» → «💳 Karta» (o'z +998 raqamini ulashadi, raqam saqlanmaydi) → chek yuboradi → sizga ✅/❌ tugmali xabar keladi.
  Ko'rilmagan cheklar: `/receipts`. So'm narxlari: `uzs_prices`.
- **Hammaga xabar:** `/broadcast` → xabar yuboring (matn/rasm/video) → ko'rib «✅ Yuborish». Cron har daqiqada bo'laklab yuboradi; holati `/broadcast_status`, to'xtatish `/broadcast_stop`.
- **Majburiy obuna:** botni kanalga admin qiling → `/force_add @kanal` (`/force_list`, `/force_del ID`). Foydalanuvchi a'zo bo'lmaguncha bot ishlamaydi (adminlar mustasno).

## 🟦 Payme (avtomatik to'lov)

1. business.paycom.uz da kassa oching. «Endpoint URL»: `https://<domen>/PostAssist/payme.php`.
2. `config.php` ga `payme_merchant_id` (kassa ID) va `payme_key` (kalit) yozing. Avval sinov uchun `payme_test => true` va sinov kalitini qo'ying, keyin asosiy kalitga almashtiring.
3. Botda: Tariflar → «💳 So'mda» → tarif → «🟦 Payme orqali». To'lov o'tgach tarif o'zi yoqiladi.
4. Hostingda Payme «Ruxsat yetarli emas» desa — `.htaccess` dagi `SetEnvIf Authorization` qatori ishlamayapti; hosting yordamiga «Authorization sarlavhasini PHP'ga o'tkazish» kerakligini ayting.

## 🤖 Kontent-reja va autopilot

- `/contentplan` — kanal mavzusini yozing, AI 7 ta g'oya beradi; raqamni bosing — shu g'oyadan post.
- `/autopilot` (PRO — 1, ULTRA — 3) — har kuni belgilangan soatda AI post yozadi. «Tekshirib» rejimida post avval sizga keladi, «Avtomatik» — to'g'ri kanalga. Ishlashi uchun cron har daqiqa ishlab turishi kerak.

## 📰 RSS, 📤 yuborilganlar, 📢 ko'p kanal

- `/rss` (PRO/ULTRA): sayt, blog yoki YouTube lentasini ulang — yangi maqolalar kanalga o'zi chiqadi (cron kerak).
- `/sent`: kanalga chiqqan postni tahrirlash yoki kanaldan o'chirish.
- Post yaratishda «⚙️ Qo'shimcha» → «📢 Yana kanallar»: bitta postni bir nechta kanalga birdan.

## 📝 Shablonlar va 📊 statistika

- Post tayyorlab «⚙️ Qo'shimcha» → «💾 Shablon qilish». Keyin «✍️ Post yaratish» → «📝 Shablonlar» yoki `/templates`.
- «📊 Statistika»: har kanal uchun obunachilar o'sishi (bot har kuni o'lchaydi — cron kerak), grafik, postlar, reaksiyalar.

## 💬 Izohlar, 📦 ko'p post, 📈 hisobot

- «⚙️ Qo'shimcha» → «💬 Izohlar»: postga izoh tugmasi (muhokama guruhi shart emas). Har izoh sizga keladi — o'chirish yoki bloklash mumkin.
- «✍️ Post yaratish» → «📦 Ko'p post rejasi»: bir nechta postni yuboring, boshlanish vaqti va oraliqni tanlang.
- Har dushanba 09:00 da haftalik hisobot keladi (o'chirish: 📊 Statistika). `/report` — hozir ko'rish.
- Takror: «Ish kunlari Du–Ju», «Har 2 kunda», «Har 3 kunda».

## 📊 So'rovnoma va 👑 Mini App admin

- «✍️ Post yaratish» → «📊 So'rovnoma»: savol, keyin variantlar (har biri yangi qatorda). To'g'ri javob oldiga `*` qo'ysangiz — viktorina.
- Mini App → Men → «👑 Super admin» (faqat `admin_ids`): statistika, tarif berish, foydalanuvchi, promo-kodlar, karta cheklari.
- Mini App bosh sahifasida «💬 Izohlar»: postlaringizga yozilgan izohlar, javob, o'chirish, bloklash.

## ✨ Bot ko'rinishi: rangli tugmalar va premium emoji

- Tugmalar o'zi rangli: asosiy amal yashil, o'chirish/bekor qizil, muhim yo'l ko'k (Telegram'ning yangi versiyalarida ko'rinadi).
- Jonli premium emoji: botda `/emoji` → premium emojilarni yuboring (Telegram'da premium emoji paketidan). Bot 🤖 ✍️ 📢 kabi oddiy belgilarni xabar va tugmalarda jonli versiyasiga almashtiradi.
- Shart (Telegram qoidasi): bot egasida **Telegram Premium** bo'lishi kerak. Bo'lmasa bot o'zi oddiy ko'rinishga qaytadi — hech narsa buzilmaydi.

## 👥 Jamoa va 💰 reklama birjasi

- **Jamoa** (ULTRA tarif): Sozlamalar → «👥 Jamoa» yoki `/team` → ruxsat turini tanlang → havolani yordamchiga yuboring. U botda ham, Mini App'da ham sizning kanallaringiz bilan ishlaydi (faqat berilgan ruxsat doirasida).
- **Birja**: `/market` yoki kanallar ro'yxatidagi «💰 Birja». Kanal egasi e'lon qo'yadi, reklama beruvchi katalogdan tanlab bot orqali yozadi. Pul bot orqali o'tmaydi. Karta raqami, hamyon va havolalar suhbatda to'siladi; 3 ta shikoyat — avtomatik blok. Admin: `/market_ban ID`, `/market_unban ID`, `/market_userban ID`, `/market_userunban ID`.

## 📱 Mini App

Qo'shimcha sozlash shart emas: `webhook_url` `https://.../webhook.php` bo'lsa, Mini App manzili avtomatik `.../app.php` bo'ladi.
`setup.php` ni bir marta ochganda bot menyu tugmasi (chat pastidagi «Mini App») o'rnatiladi. Botda: asosiy menyuda «📱 Mini App»,
`/app`, post preview'da «📱 Mini App'da» (qoralama shu yerda davom etadi). O'chirish: `config.php` → `'miniapp_enabled' => false`.
Ixtiyoriy: @BotFather → Bot → Bot Settings → Configure Mini App → shu manzil (chat ro'yxatidagi «Ochish» tugmasi uchun).

## ✨ AI yoqish

`config.php` ga kamida bitta bepul kalit yozing (bir nechta bo'lsa — biri ishlamasa keyingisi):
- `gemini_api_key` — https://aistudio.google.com/apikey (tavsiya: o'zbek tilini yaxshi biladi)
- `groq_api_key` — https://console.groq.com/keys
- `openrouter_api_key` — https://openrouter.ai/keys

Shundan keyin menyuda «✨ AI post» va preview → «⚙️ Qo'shimcha» → «✨ AI tahrir» chiqadi. Kunlik limit: FREE 5, PRO 40, ULTRA 100
(`ai_daily` bilan o'zgaradi); tugasa ballar ishlatiladi; AI javob bermasa so'rov qaytariladi.

## Albom haqida (hosting sozlamasi)

Albom (bir nechta rasm) yig'ilishi uchun webhook Telegram'ga javobni darhol qaytaradi va 2 soniya kutadi. Bu oddiy Apache, LiteSpeed va
PHP-FPM hostinglarda ishlaydi. Agar bir vaqtda ishlaydigan jarayonlar soni juda kam bo'lsa ham albom yo'qolmaydi: kechikkan fayl
preview'dagi albomga qo'shiladi, jarayon uzilib qolsa — `cron.php` 10 soniyadan keyin yig'adi.

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
limitlar, navbat, cron, qayta urinish, qulf, bot chiqarilishi, IDOR), 2-bosqich: eski bazani yangilash, tarif ekrani, hisob (invoice),
pre_checkout tekshiruvi, to'lov (takror to'lov, mos kelmagan summa), PRO/ULTRA almashuvi, muddat eslatmasi va tugashi, promo-kodlar
(limit, bir marta, o'chiq, taxminga qarshi to'siq), referal ballari, manba havolalari; 3-bosqich: vaqt mintaqasi, takror (har kuni/hafta/oy,
kuniga 2 marta, yozgi vaqt, cron to'xtab qolsa), reaksiya ovozlari, avto-o'chirish (qayta urinish bilan), albom (yig'ish, kechikkan qism,
aralash turlar, uzilgan jarayon, 10 tadan ko'p). CI'da PHP 7.4 va 8.3 da ishlaydi.
