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
| **2. Tariflar** | FREE/PRO/ULTRA (1/3/6/12 oy), Telegram Stars to'lovi (tekshiruv, bir to'lov — bir marta), muddat eslatmasi va tugashi (cron), promo-kod (yaratish/ro'yxat/o'chirish, taxminga qarshi limit), referal ballari (do'stning birinchi postida +3/+1), manba havolalari (`s_<kod>`: kim qayerdan keldi), tarif bo'yicha limitlar, admin buyruqlari (`/admin_help`) | ✅ tayyor |
| 3. Kengaytirilgan post | takroriy postlar (har kuni/hafta/oy, kuniga 2 marta), albom, reaksiya, avto-o'chirish, vaqt mintaqasi (`/timezone`) | ⏳ |
| 4. AI | Magic Post, rasmdan post, AI yordamchi, AI byudjeti va kreditlar | ⏳ |
| 5. Pul va admin | karta/Payme to'lov, majburiy obuna, reklama, broadcast, to'liq admin panel, promo boshqaruvi | ⏳ |
| 6. Birja va jamoa | reklama birjasi (firibgarlikdan himoya bilan), jamoa va rollar | ⏳ |
| 7. Mini App | Mini App API (PHP), analitika | ⏳ |

Har bosqich: kod + uch tilda matn + testlar (unit va haqiqiy MariaDB) + PHP 7.4 tekshiruvi (CI `php` vazifasi).

## 1-bosqichdagi farqlar (Python'ga nisbatan)

- Yangi foydalanuvchi uchun soddalashtirilgan menyu, aqlli qabul («Bu bilan nima qilamiz?»), AI tugmalari hali yo'q.
- Takroriy post, albom, reaksiya, avto-o'chirish yo'q (3-bosqich).
- Vaqt mintaqasi hamma uchun bitta (`config.php` → `timezone`).

## 2-bosqich: qoidalar (Python bilan bir xil)

- Tarif kalitlari `1m 3m 6m 1y` (PRO) va `u1m u3m u6m u1y` (ULTRA); Stars narxi — xalqaro narx (`config.php` → `stars_prices` bilan o'zgaradi).
- To'lov: payload `sub_stars_<kalit>_<user_id>`; valyuta `XTR` va summa katalogga teng bo'lishi shart; `charge_id` UNIQUE.
- Tarif berish: `enterprise` o'zgarmaydi; faol ULTRA PRO olsa ham ULTRA qoladi; muddat = max(joriy, hozir) + kunlar.
- Promo faqat pro/ultra beradi; bir foydalanuvchi bir kodni bir marta; 10 daqiqada 5 noto'g'ri urinish — to'siladi;
  muddatsiz tarifli foydalanuvchida kod sarflanmaydi.
- Referal: do'st BIRINCHI postini saqlaganda taklif qiluvchiga 1–3-do'st uchun +3, keyingilari +1 ball (parallel postda ham bir marta).
- Manba havolasi egasi bo'lsa, yangi kelgan foydalanuvchi uning taklifi hisoblanadi; birinchi tegish; `/mylinks` — faqat sonlar.
- Hozircha karta/Payme (so'm) to'lovi yo'q — 5-bosqichda; ballar AI funksiyalari bilan (4-bosqich) ishlatiladi.

## Hostingga yuklash (GitHub'siz)

`php_bot/` ning ichidagi hamma narsani (yoki tayyor ZIP'ni) hostingga yuklang. Papkalar tuzilishi bosqichlar davomida
o'zgarmaydi: `src/` (`Handlers`, `Lang`, `Repo`, `Services`), `sql/`, `storage/`; yangi bosqichda faqat shu papkalar
ichida fayl qo'shiladi. Yangilashda `config.php` va `storage/` ni o'chirmang, keyin `setup.php?key=...` ni bir marta oching —
yangi jadval va ustunlar o'zi qo'shiladi (eski ma'lumot saqlanadi).

## Ma'lumotni ko'chirish

Python bot ishlab turgan bo'lsa, foydalanuvchilar va kanallarni PostgreSQL'dan MySQL'ga ko'chirish skripti alohida yoziladi
(foydalanuvchilar, tillar, kanallar, navbatdagi postlar). Ko'chirishdan oldin ikkala bot bir vaqtda ishlamasligi kerak
(bitta token — bitta webhook).
