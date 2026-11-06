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
| **3. Kengaytirilgan post** | ixcham preview paneli (5 tugma) + «⚙️ Qo'shimcha»; takroriy postlar (har kuni / har hafta / har oy / kuniga 2 marta, yozgi vaqt hisobga olinadi, cron to'xtab qolsa nusxalar yig'ilmaydi); albom 2–10 fayl (kechikkan qism ham qo'shiladi, jarayon uzilsa cron yig'adi); reaksiya tugmalari (ovoz, sonlar postda); avto-o'chirish (1–48 soat); har foydalanuvchiga vaqt mintaqasi (`/timezone`) | ✅ tayyor |
| **4. AI va navigatsiya** | «✨ AI post» (mavzu → 5 uslub → tayyor post, «🔄 Boshqa variant»), «✨ AI tahrir» (yaxshilash, qisqartirish, emoji, qayta yozish, UZ/RU/EN tarjima), aqlli qabul (dialogsiz matn/rasm → «Bu bilan nima qilamiz?»), Gemini → Groq → OpenRouter zaxira, kunlik limit (5/40/100) + ballar, xatoda qaytarish; hamma ekranda «◀️ Orqaga» / «🏠 Menyu», inline admin panel | ✅ tayyor |
| **4b. Rasm va ovoz** | rasmdan post (Gemini Vision: aqlli qabul → «✨ AI bilan» → uslub; rasm izohi ko'rsatma bo'ladi; faqat ko'ringan narsaga tayanadi), ovozli xabardan post (≤180 s, uslub «yangilik», «🔄 Boshqa variant»); fayl yuklanmasa limit sarflanmaydi | ✅ tayyor |
| **4c. Kontent-reja** | 📅 AI kontent-reja (`/contentplan`: mavzu → 7 g'oya → bir bosishda AI post), 🤖 autopilot (`/autopilot`: har kuni belgilangan vaqtda egasining mintaqasida AI post; «Tekshirib» — ✅ Kanalga / ✏️ Tahrirlash / 🔄 Boshqa variant / ❌, «Avtomatik» — darhol kanalga; PRO 1, ULTRA 3; tarif tugasa yoki kanal o'chsa to'xtaydi; 6 soatdan kech qolgan kun o'tkaziladi; AI xatosida limit qaytadi; oxirgi 5 post takrorlanmaydi) | ✅ tayyor |
| **5. Pul va admin** | karta (so'm) to'lovi: UZ raqam tasdig'i (+998, raqam saqlanmaydi), chek (rasm/PDF), adminlarga ✅/❌ (qaror bir marta, to'lov va tarif bitta tranzaksiyada), takror fayl ogohlantirishi, 3 chekdan ortig'i rad; hammaga xabar (`/broadcast`: copyMessage, cron bo'laklab, kursor, bloklaganlar belgilanadi, to'xtatish/holat); majburiy obuna (`/force_add`: 10 daqiqa kesh, Telegram javob bermasa foydalanuvchi o'tkaziladi); `/receipts`, admin panel tugmalari | ✅ tayyor |
| **5b. Payme** | `payme.php` (Merchant API JSON-RPC: Check/Create/Perform/Cancel/CheckTransaction/GetStatement), Basic auth (`Paycom:<kalit>`, doimiy vaqtli taqqoslash), bir martalik buyurtma (`payme_orders`), tarif faqat bir marta (`payments.charge_id = payme_<id>` UNIQUE, qatorlar FOR UPDATE), 12 soatlik timeout, qaytarish faqat `payme_allow_refunds`; botda «🟦 Payme orqali» (UZ tasdig'idan keyin) | ✅ tayyor |
| **6. Birja va jamoa** | **jamoa:** ULTRA/enterprise/admin — egasi + 2 yordamchi, bir martalik taklif havolasi (`/start team_<token>`), ruxsat shablonlari (hammasi/muharrir/ko'ruvchi), ish joyi bot va Mini App'da (post egasi nomidan, `created_by` = yordamchi); **reklama birjasi:** `/market` — 10 toifa, kanal e'loni (bot va egasi admin tekshiruvi, telefon tasdig'i), katalog, bot orqali suhbat (kontakt faqat ruxsat bilan), firibgarlik skaneri (karta/hamyon/havola to'siladi), kuniga 5 so'rov, blok, 3 shikoyat → e'lon yopiladi / foydalanuvchi ban, admin `/market_ban|unban|userban|userunban`; Mini App'da «💰 Birja» tabi (katalog, toifalar, e'lon kartasi, so'rov yuborish, suhbatlar va javob — bot bilan bir xil himoya `MarketHandler::send`; e'lon qo'yish botda); Mini App bosh sahifasida «Botdagi bo'limlar» (`?start=go_market|go_team|go_plans|go_channels`, ruxsat ro'yxati) | ✅ tayyor |
| **11. Raqobatchilardan** | «⚙️ Qo'shimcha» ichida: 🔕 ovozsiz, 🔗 havola ko'rinishisiz, 📌 pin (chiqqach kanalda qadaladi), 🛡 nusxa himoyasi (`scheduled_posts.options`); 🔒 «Obunachilar uchun» yashirin matn (≤180 belgi; kanal postida tugma, bosganda bot `getChatMember` bilan obunani tekshiradi; obuna bo'lmaganga «avval obuna bo'ling»; reaksiya ovozidan keyin ham tugma qoladi) — `Handlers/HiddenHandler.php` | ✅ tayyor |
| **12–15. Yangiliklar** | 📤 yuborilgan postni tahrirlash va kanaldan o'chirish (`/sent`, `SentHandler`: tugma/reaksiya/yashirin matn saqlanadi, bepul nishon qayta qo'yiladi); 📢 bir nechta kanalga birdan («⚙️ Qo'shimcha» → «Yana kanallar», natija har kanal bo'yicha, navbat limiti umumiy); 📰 RSS avtopost (`/rss`, `Services/Rss.php`: SSRF himoyasi, DNS mahkamlash, redirect tekshiruvi, XXE rad; har 15 daqiqa, ko'pi bilan 3 maqola; PRO 3 / ULTRA 10); Mini App muharririda sozlamalar, yashirin matn va «Yana kanallarga» | ✅ tayyor |
| **16–17. Shablon va statistika** | 📝 shablonlar (`/templates`, «⚙️ Qo'shimcha» → «💾 Shablon qilish», post boshida «📝 Shablonlar»; matn, media, albom, tugma, reaksiya, sozlamalar, yashirin matn saqlanadi; bepul 3 / PRO 20 / ULTRA 50; Mini App'da ochish va saqlash); 📊 kanal statistikasi (cron har kanalni kuniga bir marta `getChatMemberCount` bilan o'lchaydi; bugun/7/30 kun o'sish, 14 kunlik grafik, postlar, reaksiya ovozlari, yashirin matn ochilishlari, eng ko'p reaksiya olgan post; «🔄 Yangilash»; Mini App bosh sahifasida grafik). Ko'rishlar soni ko'rsatilmaydi — Bot API bermaydi | ✅ tayyor |
| **18–21. Izoh, reja, hisobot** | 💬 izohlar (bot orqali: «⚙️ Qo'shimcha» → «💬 Izohlar», kanal postida `?start=c_<post>` tugmasi, 2–500 belgi, 10 daqiqada 5 ta, havola faqat egasiga, egasiga xabar, 🗑/🚫, tugmada son); 📦 ko'p post rejasi (30 tagacha, boshlanish vaqti + oraliq 1/3/6/12 soat yoki har kuni); 📈 haftalik hisobot (har dushanba 09:00 egasining mintaqasida, o'chirish/yoqish, `/report`); 🔄 takrorlash: ish kunlari (Du–Ju), har 2/3 kunda (bot va Mini App) | ✅ tayyor |
| **22–24. So'rovnoma, Mini App izoh va admin** | 📊 so'rovnoma/viktorina posti (`PollHandler`: savol ≤300, 2–10 variant, `*` — to'g'ri javob, ko'p javob, anonim, rejalash/takror; bepul nishon savol oxirida); Mini App: egasi uchun 💬 izohlar (ro'yxat, javob, 🗑, 🚫) va 👑 super admin (statistika + 7 kunlik grafik, tarif berish, foydalanuvchi kartasi va birja bloki, promo yaratish/to'xtatish, karta cheklarini tasdiqlash — `MiniAdminApi`, har amal 403 `admin_only`) | ✅ tayyor |
| **25–26. Davlatlar va dizayn** | 🌍 247 davlat/hudud uch tilda (`Services/CountryData.php` — ICU'dan yasalgan statik fayl, `Services/Countries.php` — qidiruv, qisqa nomlar, shaharlar, bir xil vaqtli mintaqalarni birlashtirish, eski tzdata'da eski nomlar); bot `/timezone` va Mini App qidiruvi. 🎨 Mini App zamonaviy dizayn (gradient, shisha panel, avatar, jonli tugmalar) va «Ko'rinish»: mavzu (Telegram/yorug'/tungi), 8 rang, shrift, zichlik, animatsiya, panel yozuvlari, bosh sahifa bo'limlari, ochilish sahifasi (localStorage + Telegram CloudStorage) | ✅ tayyor |
| **27. Bot ko'rinishi** | 🎨 rangli tugmalar (`style`: success/danger/primary, callback_data bo'yicha) va 💫 premium (jonli) emoji: admin `/emoji` da premium emojilarni yuboradi → bot oddiy belgini (🤖 ✍️ …) jonli versiyasiga almashtiradi (xabarda `<tg-emoji>`, tugmada `icon_custom_emoji_id`), faqat shaxsiy chatda, kanal postiga tegmaydi; Telegram rad etsa (bot egasida Premium yo'q) xabar oddiy holda qayta yuboriladi va qatlam o'zi o'chadi — `Services/Look.php`, `Telegram::setDecorator`, `Handlers/LookHandler.php` | ✅ tayyor |
| **28. Tartib va to'lov oqimi** | Tugmalar 2 ustunda (`Keyboards::grid`, toq qolsa navigatsiya yoniga); bosh menyu, «⚙️ Qo'shimcha», preview, admin panel (+🧾 Cheklar `a:rc`), autopilot, post boshi tartibli. Sozlamalar — profil kartasi (ism, ID, tarif va muddat, kanallar, AI qoldig'i, ball, til, mintaqa) va guruhlangan tugmalar. Tariflar: AI limiti bilan solishtirma, «uzaytirish/ULTRA ga o'tish», muddatlar 2×2. So'mda to'lov: tasdiqsiz `pl:ct/pl:cb` bilan chetlab o'tib bo'lmaydi. Stars/karta/Payme/promo muvaffaqiyatidan keyin «Endi sizda» + [Yangi post][Tarifim][Menyu]. Mini App «Men»: profil kartasi (rasm, statistika), guruhlangan ro'yxat (Hisob / Sozlamalar / Ilova), Ko'rinish va mintaqa ochiladigan qator; muharrir sozlamalari ro'yxat, formatlash paneli bir qator — test `tests/UxTest.php` | ✅ tayyor |
| **29. Premium ko'rinish** | Rangli tugmalar va jonli emoji FAQAT Telegram Premium foydalanuvchiga (`from.is_premium` → `Look::setViewer`; premiumda hamma inline tugma rangli: asosiy yashil, o'chirish qizil, qolgani ko'k), boshqalarga bir xil oddiy; pastki menyuda Mini App tugmasi yo'q (Telegram menyu tugmasida), «⚙️ Sozlamalar» qisqa (eski yorliq `I18n::ALIASES` orqali taniladi). Mini App: `<style id="ui-premium">` (shisha kartalar, gradient hero, suzuvchi panel), birja ixcham (gorizontal kategoriyalar, `mk-head`, kanal belgisi), Telegram Premium foydalanuvchiga ⭐ belgi va oltin halqa (`data-tgp`) | ✅ tayyor |
| **30. Mini App'da tarif sotib olish** | Men → «Tarif va to'lov» endi Mini App ichida (`?tab=plans`): PRO/ULTRA, 4 muddat (1/3/6/12 oy) Stars narxi, oyiga ≈, tejam, «Eng foydali», solishtirma jadval; «⭐ … olish» → API `invoice` (`createInvoiceLink`, payload `PlansHandler::invoiceParams` — bot bilan bitta manba) → `tg.openInvoice`; to'lov odatdagi `successful_payment` orqali yoziladi. Admin/muddatsiz va yordamchi uchun bloklangan (sababi ko'rsatiladi). So'm va promo — botda. AI kartasida ulangan modellar (`me.ai.models`). Mini App to'liq ekran (`requestFullscreen`, xavfsiz zona). Botdan chalkash Mini App tugmalari olindi (Sozlamalar, preview); Mini App'dagi Birja qatori o'z tabini ochadi | ✅ tayyor |
| **7. Mini App** | `app.php` (bitta sahifa, tashqi kutubxonasiz) + `api.php`: initData HMAC imzo tekshiruvi; bosh sahifa (statistika), post muharriri (formatlash, rasm/video yuklash, tugma, reaksiya, takror, avto-o'chirish, jonli ko'rinish, hozir/vaqtli), AI (post yozish, tahrir/tarjima), rejalashtirilganlar (tahrir, bekor), profil (tarif, limit, til, mintaqa); botdagi qoralamani ochish; botda menyu tugmasi, «📱 Mini App», `/app`, preview'da «📱 Mini App'da» | ✅ tayyor |

Har bosqich: kod + uch tilda matn + testlar (unit va haqiqiy MariaDB) + PHP 7.4 tekshiruvi (CI `php` vazifasi).

## 1-bosqichdagi farqlar (Python'ga nisbatan)

- Yangi foydalanuvchi uchun soddalashtirilgan menyu, aqlli qabul («Bu bilan nima qilamiz?»), AI tugmalari hali yo'q.
- Yangi foydalanuvchida vaqt mintaqasi — bot mintaqasi (`config.php` → `timezone`); telefon orqali avtomatik aniqlash yo'q (`/timezone` bilan tanlanadi).

## 2-bosqich: qoidalar (Python bilan bir xil)

- Tarif kalitlari `1m 3m 6m 1y` (PRO) va `u1m u3m u6m u1y` (ULTRA); Stars narxi — xalqaro narx (`config.php` → `stars_prices` bilan o'zgaradi).
- To'lov: payload `sub_stars_<kalit>_<user_id>`; valyuta `XTR` va summa katalogga teng bo'lishi shart; `charge_id` UNIQUE.
- Tarif berish: `enterprise` o'zgarmaydi; faol ULTRA PRO olsa ham ULTRA qoladi; muddat = max(joriy, hozir) + kunlar.
- Promo faqat pro/ultra beradi; bir foydalanuvchi bir kodni bir marta; 10 daqiqada 5 noto'g'ri urinish — to'siladi;
  muddatsiz tarifli foydalanuvchida kod sarflanmaydi.
- Referal: do'st BIRINCHI postini saqlaganda taklif qiluvchiga 1–3-do'st uchun +3, keyingilari +1 ball (parallel postda ham bir marta).
- Manba havolasi egasi bo'lsa, yangi kelgan foydalanuvchi uning taklifi hisoblanadi; birinchi tegish; `/mylinks` — faqat sonlar.
- Karta (so'm) to'lovi 5-bosqichda qo'shildi; Payme avtomatik to'lovi hali yo'q.

## 3-bosqich: qoidalar

- Takror: birinchi chiqish tanlangan vaqtda; keyingisi egasining mintaqasida hisoblanadi (oyda 31-kun bo'lmasa — oxirgi kun).
  Chiqqan post o'sha qatorda keyingi vaqtga qaytadi (bitta UPDATE). Egasi faqat birinchi chiqishda xabar oladi. To'xtatish — navbatdan bekor qilish.
- Albom: Telegram har faylni alohida yuboradi; webhook «ok» ni darhol qaytaradi, 2 soniya kutadi, oxirgi qism yig'adi (`album_done` — bir marta).
  Kechikkan qism preview'dagi albomga qo'shiladi. Albomga tugma/reaksiya qo'yib bo'lmaydi (Telegram).
- Reaksiya: kanal postidagi `rx:<n>` tugmalari; bir kishi — bitta reaksiya (qayta bossa olinadi); `sent_messages` + `reaction_votes`.
- Avto-o'chirish: `sent_messages.delete_at`; vaqtinchalik xatoda 5 daqiqadan keyin (3 marta), xabar yo'q bo'lsa o'chirilgan deb belgilanadi.

## Hostingga yuklash (GitHub'siz)

`php_bot/` ning ichidagi hamma narsani (yoki tayyor ZIP'ni) hostingga yuklang. Papkalar tuzilishi bosqichlar davomida
o'zgarmaydi: `src/` (`Handlers`, `Lang`, `Repo`, `Services`), `sql/`, `storage/`; yangi bosqichda faqat shu papkalar
ichida fayl qo'shiladi. Yangilashda `config.php` va `storage/` ni o'chirmang, keyin `setup.php?key=...` ni bir marta oching —
yangi jadval va ustunlar o'zi qo'shiladi (eski ma'lumot saqlanadi).

## Ma'lumotni ko'chirish

Python bot ishlab turgan bo'lsa, foydalanuvchilar va kanallarni PostgreSQL'dan MySQL'ga ko'chirish skripti alohida yoziladi
(foydalanuvchilar, tillar, kanallar, navbatdagi postlar). Ko'chirishdan oldin ikkala bot bir vaqtda ishlamasligi kerak
(bitta token — bitta webhook).
