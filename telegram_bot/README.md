# PostAssist — bot imkoniyatlari

Telegram kanallar uchun yordamchi bot: postlarni yozish (qo'lda yoki AI bilan),
rejalashtirish, kanalga vaqtida joylash va statistikani ko'rsatish.
Interfeys uch tilda: o'zbek, rus, ingliz.

Ishga tushirish va kod tuzilishi — [repo ildizidagi README](../README.md).
Serverga chiqarish — [DEPLOYMENT.md](../DEPLOYMENT.md).

## Boshlash

1. @BotFather'da bot yarating va `BOT_TOKEN` ni oling.
2. Botni kanalingizga **administrator** qilib qo'shing (kamida "Post Messages" huquqi).
3. Botga `/start` yuboring → «📢 Kanallarim» (yangi foydalanuvchida «📢 Kanal ulash»)
   → kanaldan bitta postni forward qiling yoki `@username` yuboring.

## Asosiy menyu

| Tugma | Nima qiladi |
|---|---|
| ✍️ Post yaratish | Oddiy post (AI'siz), AI bilan post (Magic Post) yoki AI Yordamchi |
| 📢 Kanallarim | Ulangan kanallar, kanal sozlamalari, kanal uchun post/Autopilot |
| 📅 Rejalashtirilgan | Navbatdagi postlar: ko'rish, tahrirlash, vaqtini surish, o'chirish |
| 📊 Statistika | Postlar soni, ko'rishlar, eng yaxshi vaqt |
| ⚙️ Sozlamalar / Ko'proq | Til, bildirishnomalar, PRO, bonuslar, yordam |

Yangi foydalanuvchi birinchi kunlarda soddalashtirilgan menyuni ko'radi
(«🚀 1 daqiqada post yaratish», «🖼 Rasmdan post olish», «📢 Kanal ulash»).
«⚙️ To'liq menyuni ochish» yoki bir necha kundan keyin oddiy menyuga o'tadi.

### ⚙️ Sozlamalar

```
[🌐 Til / Язык]        [🔔 Bildirishnomalar]
[💎 PRO va Tariflar]   [👥 Do'stlarni taklif]
[❓ Yordam]
```

* **👥 Do'stlarni taklif** — referal havola va mukofotlar.
* **❓ Yordam** — qo'llab-quvvatlashga yozish, maxfiylik siyosati, ma'lumotlarni o'chirish.

## Post yaratish

* **Oddiy post** — matn, rasm, video, audio, hujjat yoki albom (10 tagacha fayl).
  Qo'shimcha: havolali tugma, reaksiyalar, avto-o'chirish (12/24/48/72 soat),
  takroriy e'lon (har kuni / har hafta).
* **✨ AI bilan (Magic Post)** — mavzu yoki xom matn yuborasiz, uslubni tanlaysiz,
  AI tayyor post yozadi.
* **🤖 AI Yordamchi** — rasm (📸 Image→Post), ovoz (🎙 Voice→Post), havola yoki
  forward qilingan postdan yangi post tayyorlaydi; postni baholaydi (📊 Post Score).
* **🚀 Autopilot** — kanal uchun 7 kunlik post rejasi.
* **📥 Manbalar** — RSS/sayt havolalaridan avtomatik qoralamalar.
* **📋 Shablonlar** — tez-tez ishlatiladigan postlarni saqlash.

Har bir post hozir yuborilishi yoki aniq vaqtga rejalashtirilishi mumkin.
Rejalashtiruvchi har daqiqada vaqti kelgan postlarni yuboradi.

## Buyruqlar

Telegram'dagi ☰ «Menu» tugmasida ko'rinadigan buyruqlar bot ishga tushganda
`set_my_commands` orqali uch tilda ro'yxatdan o'tkaziladi (manba:
`menu_commands.py`):

| Buyruq | Tavsif |
|---|---|
| `/start` | Bosh menyu |
| `/newpost` | Yangi post yaratish |
| `/settings` | Sozlamalar |
| `/help` | Qo'llanma |

Menyuda ko'rinmaydigan, lekin ishlaydigan buyruqlar: `/profile`, `/queue`,
`/cancel`, `/privacy`, `/ai`, `/imagepost`, `/channel_advice`.

Admin buyruqlari (faqat `ADMIN_IDS` yoki RBAC roli bo'lganlar uchun):
`/admin`, `/stats`, `/admin_stats`, `/broadcast`, `/grant_pro`, `/create_promo`,
`/setrole`, `/delrole`, `/audit`, `/health`, `/economics`, `/feature_usage`.
Manba havolalari (kim qaysi reklama/hamkor havolasidan keldi): `/links`, `/link_new`, `/link`, `/link_off`, `/link_on`, `/link_user`; hamkor uchun `/mylinks` — batafsil [docs/TRACKED_LINKS.md](../docs/TRACKED_LINKS.md).

## To'lovlar

PRO tarifni uch usulda olish mumkin: Telegram Stars, karta (chek admin
tomonidan tasdiqlanadi) va Payme (avtomatik, [docs/PAYME.md](../docs/PAYME.md)).
