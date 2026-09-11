# Telegram Kanal Bot — Rejalashtirilgan Xabarlar

Bu bot sizning Telegram kanalingizga siz belgilagan vaqtda (bir marta yoki
har kuni, istalgan muddatgacha — masalan 1 yil) xabarlarni avtomatik jo'natadi.
Bot **AI Studio** (doimiy inline navigatsiya va zamonaviy AI prompt tizimi) orqali matn yaratish, kanal postlarini qayta ishlash va kontent-reja tuzish imkoniyatlarini taqdim etadi.

## Loyiha tuzilishi

```
telegram_bot/
├── main.py              # Botni ishga tushiruvchi asosiy fayl
├── config.py            # Sozlamalar (token, admin id, kanal)
├── database.py          # PostgreSQL (Neon/Render) bilan ishlash
├── schema.sql           # To'liq PostgreSQL sxemasi (idempotent, ishga tushishda qo'llanadi)
├── scheduler.py         # Vaqt bo'yicha jo'natish logikasi
├── handlers/
│   ├── start.py         # /start, /help, profil va bonuslar
│   ├── new_post.py      # /newpost — yangi xabar qo'shish
│   ├── post_enhancer.py # ✨ Postga Tugma & Reaksiya qo'shish
│   ├── pending.py       # Kutilayotgan postlar va bekor qilish
│   └── channels.py      # Kanal/guruh ulash
├── requirements.txt
└── .env.example
```

Kelajakda yangi bo'lim qo'shmoqchi bo'lsangiz, `handlers/` ichiga yangi fayl
qo'shib, uni `main.py` da bitta qator bilan ro'yxatga olasiz. Boshqa
fayllarga tegish shart emas.

## 1-qadam: Bot yaratish

1. Telegram'da **@BotFather** ga yozing.
2. `/newbot` buyrug'ini yuboring, nom va username bering.
3. Sizga **BOT_TOKEN** beriladi (masalan `123456789:AAExample...`) — saqlab qo'ying.

## 2-qadam: O'zingizning Telegram ID'ingizni bilib olish

1. Telegram'da **@userinfobot** ga yozing (yoki shunga o'xshash botlardan
   birortasiga).
2. U sizga ID raqamingizni beradi — bu **ADMIN_ID**.

## 3-qadam: Botni kanalga admin qilib qo'shish

1. Kanalingiz sozlamalariga kiring → **Administrators** → **Add Admin**.
2. Yaratgan botingizni qidirib toping va qo'shing.
3. Botga kamida **"Post Messages"** huquqini bering.
4. Kanal username'ini eslab qoling (masalan `@mening_kanalim`) — bu
   **CHANNEL_ID**. Agar kanal yopiq (private) bo'lsa, o'rniga kanalning
   raqamli ID'sidan foydalanish kerak bo'ladi (masalan `-1001234567890`) —
   buni topish uchun kanalga bir xabar forward qilib, **@userinfobot** yoki
   **@getidsbot** ga yuboring.

## 4-qadam: Kompyuteringizda sozlash

```bash
# 1) Python o'rnatilganini tekshiring (3.10+ tavsiya etiladi)
python3 --version

# 2) Loyiha papkasiga kiring
cd telegram_bot

# 3) Virtual muhit yaratish (tavsiya etiladi)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 4) Kutubxonalarni o'rnatish
pip install -r requirements.txt

# 5) .env faylini yaratish
cp .env.example .env
# .env faylini oching va o'z qiymatlaringizni kiriting:
# BOT_TOKEN=...
# ADMIN_ID=...
# CHANNEL_ID=...
```

## 5-qadam: Botni ishga tushirish

```bash
python main.py
```

Agar hammasi to'g'ri bo'lsa, terminalda `🤖 Bot ishga tushdi...` degan
yozuvni ko'rasiz. Endi Telegram'da botingizga `/start` yozing.

## Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/start` | Botni tanishtirish |
| `/newpost` | Yangi rejalashtirilgan xabar qo'shish |
| `/profile` | Kabinet va sozlamalar |
| `/help` | Yordam matni |
| `/cancel` | Joriy amalni bekor qilish |
| `/admin` | Admin paneli (faqat admin) |

`/yangi` bosilganda bot ketma-ket so'raydi: xabar (matn, YOKI rasm/video/fayl
— xohlasangiz izoh bilan) → bir marta yoki har kuni → sana/vaqt yoki muddat
(1 hafta / 1 oy / 3 oy / 6 oy / **1 yil** / cheksiz). Hammasi tugma orqali,
yozish shart emas.

### Media fayllar haqida

Rasm, video yoki fayl yuborsangiz, bot faylning o'zini emas, balki
Telegram'ning shu faylga beradigan qisqa "ishora"sini (`file_id`) bazaga
saqlaydi — bu bir necha o'nlab belgidan iborat matn, xolos. Fayl o'zi
Telegram serverlarida qoladi. Shuning uchun 10MB rasm ham, 100MB video ham
bazangizni og'irlashtirmaydi, va jo'natish vaqti kelganda bot shu ishora
orqali qayta jo'natadi — hech qanday hajm cheklovisiz.

**Albom:** bir nechta rasm/videoni birga yuborsangiz, bot ularni albom
sifatida saqlaydi va kanalga `sendMediaGroup` orqali chiqaradi (10 tagacha).

**Albom + tugma/reaksiya cheklovi:** Telegram Bot API qoidasiga ko'ra
`sendMediaGroup`'ga `inline_keyboard` (URL tugma yoki reaksiya) ulab
bo'lmaydi. Shu sababli albom yuborib tugma/reaksiya bosqichiga yetganda
bot ogohlantirish beradi va 2 ta tanlov taklif etadi:

- **[🖼 1-rasm qolsin + tugma qo'shilsin]** — post bitta rasmga aylanadi va
  tugma/reaksiya ulanadi;
- **[⏩ Tugmalarsiz to'liq albom chiqsin]** — 10 tagacha to'liq albom
  tugma/reaksiyasiz chiqadi.

Kanalga faqat foydalanuvchining asl matni (caption/text) va tanlangan
rasmlar toza holatda yuboriladi — "Postni tasdiqlang:", "Kanal:", "Turi:",
"Tugma:", "Reaksiyalar:", "Avto-o'chirish:" kabi botning ichki
preview/xizmat yozuvlari kanalda hech qachon chiqmaydi (scheduler ularni
yuborishdan oldin tozalaydi).

**Kanal ulash oqimi:** "➕ Kanal/Guruh qo'shish" bosilgach kanal manbasini
to'rt formatning birida yuborish mumkin: kanaldan **forward**, `@username`,
`t.me/kanal_nomi` havolasi yoki raqamli ID (`-1001234567890`). Yopiq
(invite/joinchat) havolalar rad etiladi. Bot admin qilinmagani uchun
tekshiruvdan o'tmasa, botga ruxsat berilgach **🔁 "Botni admin qildim — qayta
tekshirish"** tugmasi bosiladi — xabarni qayta yuborish shart emas. Muvaffaqiyatli
ulashdan so'ng darhol yangilangan kanal ro'yxati ko'rsatiladi (ushlab turish,
o'chirish va qo'shimcha kanal ulash shu yerda).

**Kanal xavfsizligi:** kanalni faqat o'sha kanal/guruh administratori ulay
oladi. Faol kanalni boshqa foydalanuvchi o'g'irlay olmaydi. Bot kanaldan
chiqarilsa, ulanish avtomatik nofaol bo'ladi.

### ✨ Postga Tugma & Reaksiya qo'shish (⚙️ Qo'shimcha funksiyalar)

"⚙️ Qo'shimcha funksiyalar" menyusidagi **Postga Tugma & Reaksiya qo'shish**
(post enhancer) bosqichma-bosqich ishlaydigan post-generator: tayyor postni
(matn, rasm, video, albom yoki forward) yuborasiz — **asl matnga tegilmaydi**.

**0. Kirish.** Birinchi xabardayoq eslatma chiqadi: *"💡 Eslatma: Bot postni
kanalingizga joylashi uchun avval uni kanalingizga **Admin** qilib
qo'shganingizga ishonch hosil qiling."* — keyin post so'raladi.

**1. 👍 Reaksiyalar (10 tagacha).** Emoji tugmalarini bosasiz yoki bir nechta
emojini **probel bilan bitta xabarda** yuborasiz (`👍 ❤️ 🔥 👏 🎉`) — bot barcha
emojilarni ajratib oladi, `✅ Reaksiyalar saqlandi: 👍 ❤️ 🔥` deb javob beradi va
o'sha zahoti postning yangilangan prevyusini ko'rsatadi. Takrorlar va
Variation Selector farqi (`❤` / `❤️`) hisobga olinmaydi. Har doim
`[➡️ Davom etish / URL tugmaga o'tish]`, `[⬅️ Orqaga]` va `[❌ Bekor qilish]`
tugmalari turadi.

**2. 🔗 URL tugmalar (10 tagacha).** 3 ta tayyor shablon bor —
`📢 1. Kanalga a'zo bo'lish`, `💬 2. Guruhga qo'shilish`, `🤖 3. Botga o'tish`.
Shablon tanlansa bot **faqat havolani** so'raydi (`https://t.me/kanalim`).
Qo'lda kiritish ham mumkin: `Tugma nomi - https://havola.uz`,
`Tugma nomi | @kanalim` yoki faqat havola (yozuv avtomatik tanlanadi).
Tugma saqlangach u darhol prevyuda ko'rinadi va
`[➡️ Tasdiqlash va Kanalga yuborish]` taklif qilinadi.

**3. 👁 Doimiy prevyu.** Har o'zgarishdan keyin postning to'liq ko'rinishi
(matn/rasm/video + URL tugmalar + reaksiyalar) bitta xabarda **yangilanib**
turadi — yangi xabar spam qilinmaydi.

**4. 🚀 Kanalga yuborish.** Ulangan kanallar ro'yxati → *"Ushbu post
**[Kanal nomi]**ga yuborilsinmi?"* → `[✅ Ha, yuborilsin]` /
`[❌ Bekor qilish]` → *"✅ Post kanalingizga muvaffaqiyatli joylandi!"* va
`[🏠 Asosiy menyu]`.

Bepul foydalanuvchilar uchun `scheduler`'dagi **via/watermark qoidalari**
to'liq qo'llanadi (post boshiga `@PostAssistrobot`), PRO/admin — toza chiqadi.
Reklamasiz rejim avtomatik: PRO/admin — reklama umuman qo'shilmaydi, oddiy
foydalanuvchi — admin belgilagan reklama oralig'i (ad_pool) qo'llanadi.
Telegram cheklovi tufayli inline klaviatura 10 qatordan oshmaydi.

## Render va UptimeRobot sozlamalari

Render'da **Root Directory** ni `telegram_bot`, Build Command'ni `pip install -r requirements.txt`, Start Command'ni `python main.py` qilib qo'ying. Environment Variables ichida `BOT_TOKEN`, `ADMIN_ID` va Render PostgreSQL bergan `DATABASE_URL` bo'lishi kerak. `PORT` ni qo'lda berish shart emas: kod Render bergan portni o'zi oladi.

### Neon PostgreSQL sozlamalari

Bot [Neon](https://neon.tech) serverless PostgreSQL bilan ham ishlaydi:

1. Neon'da project yarating va **Connection string**ni nusxalang (pooler uchun `-pooler` suffiksli host tavsiya etiladi):
   ```
   postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require
   ```
2. Bu URL'ni Render → Environment'dagi `DATABASE_URL` ga qo'ying.
3. SSL avtomatik: URL'da `sslmode=` bo'lsa o'sha ishlatiladi, bo'lmasa kod masofaviy host uchun `require` ni o'zi qo'yadi (`DB_SSLMODE` env bilan qo'lda boshqarish ham mumkin: `disable|allow|prefer|require`).
4. Neon bepul rejada ulanishlar soni cheklangan — `DB_POOL_MAX=5` (default) qoldirilsa yetarli.
5. Sxema (`telegram_bot/schema.sql`) bot har ishga tushganda avtomatik qo'llanadi — barcha operatorlar `IF NOT EXISTS` bilan idempotent, mavjud ma'lumotlar buzilmaydi. Bo'sh bazani qo'lda to'ldirish kerak bo'lsa:
   ```bash
   psql "$DATABASE_URL" -f telegram_bot/schema.sql
   ```

#### Ma'lumotlar butunligi (PostAssist V2 — 5-bosqich)

Sxema `schema.sql`da FK/CHECK/UNIQUE constraintlar va ularni tezlashtiruvchi
kompozit indekslar bilan mustahkamlangan:

| Obyekt | Ma'nosi |
|---|---|
| `channels.user_id → users(user_id)` (CASCADE) | kanal doim mavjud foydalanuvchiga tegishli |
| `scheduled_posts.channel_id → channels(channel_id)` (CASCADE) | post faqat ulangan kanalga rejalanadi |
| `post_deliveries.post_id → scheduled_posts(id)` (CASCADE) | delivery markeri yetim qolmaydi |
| `post_reactions.post_id → scheduled_posts(id)` (CASCADE) | reaksiyalar o'chirilgan postga yopishib qolmaydi |
| `promo_redemptions UNIQUE (promo_id, user_id)` | bitta kod — bitta hisobga bir marta |
| `chk_post_deliveries_status` | `pending / processing / sent / failed / dead_letter` |
| `chk_scheduled_posts_status` | `pending / processing / posted / failed / cancelled / completed` |
| `chk_payments_status` + `payments.status` | `pending / succeeded / failed / refunded` |
| `idx_posts_sched_status` (partial) | scheduler navbati: `status='pending' AND scheduled_time` |
| `idx_deliveries_lookup` / `idx_payments_user` / `idx_channels_owner` / `idx_scheduled_posts_channel` / `idx_deliveries_post` | issiq yo'nalishlar bo'yicha indekslar |

Migratsiya **idempotent va mavjud ma'lumotga tegmaydi**: obyekt allaqachon bo'lsa
hech narsa qilinmaydi; eski yozuvlar talabga javob bermasa, constraint
`NOT VALID` holatida qo'shiladi — ya'ni tarix o'chirilmaydi, lekin barcha
**yangi** yozuvlar baribir himoyalanadi. `NOT VALID` qismini keyin
`DB_VALIDATE_INTEGRITY=1` bilan (yoki `database.validate_integrity_constraints()`)
tekshirib tugatish mumkin. Holatni ko'rish: `database.integrity_report()` va
`database.integrity_orphan_counts()` — barcha yetim qatorlar `0` bo'lishi kerak.

Tranzaksiya API: `with db_transaction() as cur:` (sync) va
`async with transaction() as cur:` (async) — istisnoda avtomatik ROLLBACK,
muvaffaqiyatda COMMIT; ich-ma-ich chaqiruv SAVEPOINT bilan davom etadi va
`db_cursor()` tranzaksiya ichida qo'shimcha ulanish olmaydi (pool deadlock'idan
himoya). To'lov (`PaymentService.process_stars_payment`, karta chekini
tasdiqlash/rad etish), obuna (`SubscriptionService.activate/extend/revoke`) va
promo (`PromoService.redeem_promo`) oqimlari shu yagona atomik blokda ishlaydi.

Tekshirish: `cd telegram_bot && python tests/db_integrity_test.py`

UptimeRobot monitor turi **HTTP(s)** bo'lsin va URL quyidagicha berilsin:
`https://sizning-render-service.onrender.com/health/live`
Health endpoint `200` va JSON qaytaradi. UptimeRobot bot polling'ini emas, Render web-service'ni uyg'oq saqlaydi.

### Health endpointlar

| Endpoint | Vazifasi |
|---|---|
| `/health/live` | Bot jarayoni ishlayaptimi — doim `200` (UptimeRobot shu yerga qaraydi) |
| `/health/ready` | Bot ishlashga tayyormi — baza bilan aloqa tekshiradi (`200` yoki `503`) |
| `/health`, `/` | `/health/live` bilan bir xil (eski havolalar ishlashda davom etadi) |

### AI sozlamalari (kamida bitta bepul kalit; 8 ta provayder navbatma-navbat ishlaydi)

| # | Kalit | Qayerdan olinadi | Bepul limiti |
|---|---|---|---|
| 1 | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | kuniga ~1500 so'rov |
| 2 | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | kuniga ~1000 so'rov |
| 3 | `OPENROUTER_API_KEY` (ixtiyoriy) | [openrouter.ai](https://openrouter.ai) | `:free` modellar |
| 4 | `MISTRAL_API_KEY` (ixtiyoriy) | [console.mistral.ai](https://console.mistral.ai) | oyiga ~1 mlrd token |
| 5 | `CEREBRAS_API_KEY` (ixtiyoriy) | [cloud.cerebras.ai](https://cloud.cerebras.ai) | kuniga 1M token |
| 6 | `SAMBANOVA_API_KEY` (ixtiyoriy) | [cloud.sambanova.ai](https://cloud.sambanova.ai) | 10–30 RPM |
| 7 | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (ixtiyoriy) | [dash.cloudflare.com](https://dash.cloudflare.com) → Workers AI | kunlik 10K neuron |
| 8 | — (kalit shart emas) | Pollinations | cheklangan |

AI so'rovi ketma-ketlikda sinab ko'riladi: **Gemini → Groq → OpenRouter →
Mistral → Cerebras → SambaNova → Cloudflare → Pollinations**. Birinchisi
ishlasa — shu javob qaytadi, ishlamasa keyingisiga o'tadi. Har bir provayder
3 marta ketma-ket xato bersa, 10 daqiqaga vaqtincha o'tkazib yuboriladi
(tezroq javob uchun).

### AI Intent Routing (aqlli yo'naltirish)

AI yordamchisi har qanday kiruvchi xabarni (matn, rasm, forward, savol) tahlil
qilib, 3 yo'nalishdan biriga ajratadi:

- **❓ Savol-javob (FAQ):** bot imkoniyatlari, ballar, kanallar haqidagi
  savollarga to'g'ridan-to'g'ri javob beradi. Bot mavzusiga aloqador bo'lmagan
  savollarga muloyimlik bilan yo'naltiradi.
- **📝 Post yaratish/tahrir:** tayyor post/forward yuborilsa — matnini saqlab
  vaqt tanlashni so'raydi (postni qayta-qayta takrorlamaydi); "oxiriga telefon
  raqam qo'sh" kabi tahrir buyruqlarini bajaradi.
- **🕒 Erkin buyruq:** "ertaga ertalab 9 ga hamma kanalga", "1 soatdan keyin",
  "bugun 15:45 ga" kabi iboralarni tushunadi (lokal natural-time parser + AI
  zaxira sifatida) va Toshkent vaqti bo'yicha rejalashtiradi.

Foydalanuvchi hech qanday tugma bosmasdan, suhbatning istalgan joyida shunchaki
xabar yozsa ham — bot AI orqali javob beradi (eski "qat'iy vaqt kutish" holati
yo'q: vaqt ekranida ham savol berilsa javob qaytadi). AI postlari uchun alohida
bekor qilish/tahrirlash tugmalari mavjud; kunlik/haftalik takrorlanuvchi postlar
oddiy "➕ Yangi post rejalashtirish" oqimi orqali ishlaydi.

> 💡 **Model avto-diskoveri:** Bot ishga tushganda (va har 6 soatda) provayderning
> jonli model ro'yxatini o'zi oladi va faqat mavjud modellarni ishlatadi. AI
> kompaniyalari modellarni tez-tez o'chiradi (masalan, 2026-yil avgustda Groq'da
> `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` va `gemma2-9b-it` yopildi) —
> avto-diskoveri tufayli bunday holatda ham bot yangi modelga o'zi o'tadi.

### 🖼 Rasmdan post yaratish (Vision / Photo-to-Post)

**✨ AI Studio → 🖼 Rasmdan post yaratish** bo'limida rasm yuborilsa (yoki `/ai`
buyrug'idan keyin rasm yuborilsa), bot rasmni **Gemini vision** modeliga
(`inline_data` + base64) yuboradi va Telegram kanali uchun professional SMM
post yozadi: `<b>...</b>` sarlavha, sotuvchi matn, emojilar, bandlar, CTA va
mos hashtaglar. Natija inline tugmalar bilan chiqadi:

- **📅 Kanalga rejalashtirish** — mavjud vaqt tanlash va rejalashtirish oqimiga
  o'tadi (rasm postga biriktiriladi).
- **🔄 Qayta yozish** — rasmni qayta tahlil qilib, boshqa uslubda yangi post
  yozadi.
- **✏️ Tahrirlash** — "sarlavhani o'zgartir", "qisqartir" kabi matn talabi
  bilan postni tahrirlaydi.

Xotira himoyasi: rasm RAM'da ushlab turilmaydi — Telegram CDN'dan diskka
**stream** qilinadi (64KB chunk), API so'rovidan keyin temp fayl o'chiriladi
(`VISION_MAX_FILE_BYTES` = 10MB limit, `VISION_HARD_TIMEOUT` = 45s qat'iy
chegara). Rate-limit, noo'rin rasm yoki kvota xatolarida foydalanuvchiga
tushunarli o'zbekcha xabar qaytariladi.

### AI kontekst va parametrlar

- **Suhbat konteksti** — har bir foydalanuvchi uchun so'nggi 6 ta AI xabari
  (foydalanuvchi savoli **va** bot javobi) eslab qolinadi va keyingi so'rovga
  qo'shiladi. "Qisqartir", "vaqtini o'zgartir", "oxiriga qo'sh" kabi ergash
  buyruqlar oldingi mazmunni eslab ishlaydi (`AI_CONTEXT_MESSAGES`,
  `AI_MAX_CONTEXT_CHARS` orqali sozlanadi). Kontekst HTML teglarisiz, toza
  matn ko'rinishida saqlanadi; joriy xabar promptga faqat bir marta tushadi
  va muvaffaqiyatsiz (xato qaytgan) so'rovlar umuman eslab qolinmaydi.
- **Javob parametrlari** — `AI_TEMPERATURE`, `AI_MAX_TOKENS`, `AI_TOP_P`,
  `AI_MAX_PROMPT_CHARS` environment o'zgaruvchilari barcha provayderlarga
  uzatiladi. Admin panel **⚙️ AI parametrlar** bo'limida ularni qayta ishga
  tushirmasdan o'zgartirish mumkin. `max_tokens=off` / `top_p=off` deb
  belgilansa, parametr so'rovga umuman qo'shilmaydi (`null` yuborilmaydi —
  ba'zi provayderlar bunga 400 xatosi qaytaradi).
- **AI Extra Context** — `AI_EXTRA_CONTEXT` bilan botning umumiy ko'rsatmasiga
  qo'shimcha kontekst qo'shish mumkin.

### Admin panel: qo'shimcha boshqaruv

Admin boshqaruv paneldan quyidagilar ham bajariladi:

- **🏷 Post nishoni** — post oxiriga qo'shiladigan ixtiyoriy watermark/nishon
  (masalan `@PostAssistrobot`). Bo'sh qoldirilsa postlar toza chiqadi. Nishon
  matn Telegram limitiga (caption 1024, matn 4096) kesilgandan **keyin**
  qo'shiladi — shuning uchun uzun postlarda ham yo'qolib qolmaydi.

### 🎯 Reklama markazi — yagona reklama menyusi

Barcha reklama boshqaruvi endi BITTA menyuda: admin panel reply-klaviaturasidagi
**🎯 Reklama markazi** tugmasi yoki dashboard'dagi shu nomli inline tugma
orqali ochiladi. Ekrandan birida:

- **📢 Kanal posti puli** va **🤖 Javoblar puli** — ikkala reklama ro'yxati
  (nechta faol / jami) shu yerda ochiladi;
- **⏱ Kanal: har N-post** — kanal postlari oralig'i;
- **⏱ Javob: har N so'rov** — bot javoblari intervallari;
- **🔄 Bot javoblari reklamasi: ✅/❌** — yoqish/o'chirish;
- **✏️ Eski javob matni** — pul bo'sh bo'lganda ishlatiladigan yagona matn.

Har bir qaytarish ekranidan **🎯 Markazga** tugmasi shu hub'ga qaytaradi,
hub'dan **⬅️ Orqaga** — admin dashboard'ga. Avval ishlatilgan alohida
"Har 3-5 javob reklamasi" ekrani va ikki xil reklama tugmasi shu menyuga
birlashtirilgan (eski tugma nomlari bosilsa ham shu hub ochiladi).

### Avtomatik reklama rotatsiyasi (ad-pool)

Reklama puli (pool) bir nechta reklamani saqlaydi. Pulga reklama
qo'shasiz, bot ularni
navbatma-navbat (round-robin) ishlatadi:

- **Kanal postlari** — reklama **har N-postda** chiqadi (standart: har 3-post).
  Sanagich **har bir kanal uchun alohida** yuritiladi (`channel_post_counters`
  jadvali), shuning uchun bir kanaldagi postlar boshqasining hisobiga
  ta'sir qilmaydi.
- **Bot javoblari** — har 3-xabarga puldagi navbatdagi reklama qo'shiladi.

Pul menyusida quyidagilar bor:

- **➕ Yangi reklama qo'shish** — matn yozasiz, pulga qo'shiladi (yoki
  to'g'ridan-to'g'ri matn yozib yuborishingiz mumkin).
- **🟢/🔴 Reklama ustiga bosish** — tahrirlash kartochkasi ochiladi.
- **⏱ Reklama oralig'i** — reklama har nechanchi postda chiqishini tanlaysiz
  (har 3-, 4- yoki 5-post; yoki istalgan sonni yozib yuborasiz).
- **🧹 Hammasini tozalash** — butun pulni tozalaydi (`clear` deb yozsangiz ham bo'ladi).
- **ℹ️ Rotatsiya haqida** — bu funksiya qanday ishlashini tushuntiradi.

**Reklamani to'liq tahrirlash** (kartochka ichida):

- **✏️ Matnni tahrirlash** — HTML formatlash qo'llab-quvvatlanadi:
  `<b>qalin</b>`, `<i>kursiv</i>`, `<u>tagchiziq</u>`,
  `<a href="https://t.me/kanal">havola</a>`. Matn saqlashdan oldin
  tekshiriladi (ruxsat etilmagan teg, yopilmagan teg yoki yaroqsiz havola
  rad etiladi).
- **🔗 Inline URL tugma** — `Tugma matni | https://havola` ko'rinishida
  kiritiladi. Kanal postlarida haqiqiy inline tugma sifatida, bot
  javoblarida esa havola sifatida chiqadi. `clear` — tugmani olib tashlaydi.
- **🟢/🔴 Toggle Active/Inactive** — reklamani o'chirmasdan vaqtincha
  rotatsiyadan chiqarish/qaytarish.
- **🗑 Reklamani o'chirish** — puldan butunlay o'chiradi.

Har bir ekranda **❌ Bekor qilish** tugmasi bor — u FSM holatini to'liq
tozalaydi va admin panelga qaytaradi.

> Orqaga moslik: pul **bo'sh** bo'lganda bot eski yagona reklama
> sozlamasidan (`channel_ad_text` / `bot_reply_ad_text`) foydalanishda davom
> etadi — shuning uchun mavjud konfiguratsiya buzilmaydi.
- **⚙️ AI parametrlar** — temperature, max_tokens, top_p, prompt limit,
  kontekst hajmi va xabarlar sonini runtime'da o'zgartirish.
- **🗄️ DB/Kesh holati** — PostgreSQL pool holati va TTL kesh yozuvlari sonini
  ko'rish, kerak bo'lganda keshni tozalash.
- **📋 Kanallar ro'yxati** — eng so'nggi ulangan kanallar va ularning egalari
  (Telegramning 4096 belgilik limitiga moslab kesiladi).
- **🛠 Tizim sozlamalari** — `system_settings` kalitlari, reklama oraliqlari va
  kanallar bo'yicha post/reklama sanagichlari bir ekranda.

Kalitlarni Render → Environment bo'limiga qo'shing va botni qayta ishga tushiring.

### Hujum / ortiqcha yuklama himoyasi

- **Global flood** — butun bot 1 soniyada 60 tadan ortiq xabar olganda avtomatik sekinlashadi.
- **Foydalanuvchi burst** — bitta foydalanuvchi 2 soniyada 20 tadan ortiq xabar yuborsa, qolganlari tashlab yuboriladi.
- **Dublikat xabar** — bir xil xabar 1.5 soniya ichida qayta yuborilsa, e'tiborga olinmaydi.
- **AI limitlar** — daqiqasiga 4 ta, kuniga 30 ta (foydalanuvchi uchun); bir vaqtda 2 tadan ortiq AI so'rovi ishlamaydi.
- **Broadcast qulfi** — bir vaqtda faqat bitta xabar tarqatilishi mumkin.
- **Prompt limiti** — AI'ga yuboriladigan matn `AI_MAX_PROMPT_CHARS` (default 3000) belgidan oshsa kesiladi; admin paneldan sozlanadi.

### Render Free uchun optimallashtirish

- **PostgreSQL connection pool** — har bir so'rovda yangi ulanish ochilmaydi; ulanishlar qayta ishlatiladi (`DB_POOL_MAX=5`).
- **TTL kesh** — tez-tez so'raladigan sozlamalar, homiy kanallar, foydalanuvchi ballari/kanallari va statistika kichik TTL keshida saqlanadi (`DB_CACHE_ENABLED=1`, `DB_SETTINGS_CACHE_TTL`, `DB_USER_CACHE_TTL`, `DB_STATS_CACHE_TTL`). Yozishlar keshlarni avtomatik tozalaydi.
- **Event loop bloklanmaydi** — scheduler va og'ir DB operatsiyalari alohida thread'da bajariladi.
- **Telegram timeout/retry** — rate-limit va tarmoq xatolarida postlar yo'qolmaydi, keyingi urinish uchun navbatga qaytadi.
- **AI rate-limit** — har bir foydalanuvchi daqiqasiga ko'pi bilan 4 ta AI so'rovi yuborishi mumkin.
- **Broadcast batch** — xabar barcha foydalanuvchilarga fon rejimida, batch'lar bilan yuboriladi (Telegram rate-limit buzilmaydi).
- **DB cleanup** — eski ma'lumotlar har 6 soatda avtomatik tozalanadi.
- **1 hafta tugmasi** — "Har kuni" postlari uchun endi "1 hafta" muddati ham bor (7 kun).

## 🚀 Ommaviy reliz: 4 ta arxitekturaviy himoya

Bot ko'p foydalanuvchili ommaviy ishlatishga tayyorlangan. Quyidagi 4 ta
himoya qatlami mavjud DB (Neon), apscheduler va testlarni buzmasdan qo'shilgan.

### 1. Inline tugmalar xavfsizligi — 64 baytlik `callback_data` limiti

Telegram `callback_data` uchun **qat'iy 64 baytlik** chegara qo'yadi; undan
oshsa `BadRequest: BUTTON_DATA_INVALID` bilan butun klaviatura yiqiladi.

- Barcha prefikslar yagona manbada: `keyboards/callback_data.py`
  (`CB_CHANNEL_DELETE="ch_del:"`, `CB_CHANNEL_SETTINGS="ch_set:"`,
  `CB_POST_TIME="p_time:"`, `CB_POST_EDIT="p_edit:"`, `CB_POST_BUTTON="p_btn:"`,
  `CB_POST_REACTION="p_react:"`, `CB_POST_CANCEL="p_cancel:"` va h.k.).
- `cb(prefix, *parts)` helperi qiymatni yig'adi, **UTF-8 chegarasi bo'yicha**
  xavfsiz kesadi (emoji yarmidan bo'linmaydi) va ogohlantirish yozadi.
- `is_callback_safe()`, `callback_byte_len()`, `truncate_callback_data()`,
  `pattern()` — audit va handler ro'yxatga olish uchun.
- Butun repoda birorta ham "yalang'och" dinamik `callback_data=f"..."` qolmagan:
  hammasi `cb()` orqali o'tadi. Statik audit testi buni har run'da tekshiradi.

### 2. UZ/RU i18n xavfsiz fallback

`get_text(key, lang)` **hech qachon `KeyError` bermaydi** — 3 bosqichli zanjir:

1. tanlangan til → 2. `uz` (default) → 3. kalit nomining o'zi (crash o'rniga).

Format placeholderlari yetishmasa ham (`{name}` berilmagan) xom matn
qaytariladi, `.format()` xatosi foydalanuvchiga chiqmaydi.

Parity nazorati: `translation_parity_report()` → `{"uz_only": [], "ru_only": [],
"total": 552, "in_sync": True}`, `missing_keys(lang)`, `has_key(key, lang)`.
Test suite UZ/RU kalitlari **to'liq mos** ekanini har run'da tasdiqlaydi.

### 3. Scheduler va vaqt zonasi (Asia/Tashkent, UTC+5)

- `scheduler.TIMEZONE_NAME` / `tashkent_tz` / `now_tashkent()` — butun bot
  uchun **yagona vaqt manbai**; `main.py` dagi `AsyncIOScheduler` va uning
  barcha triggerlari ham shu zonaga pinlangan (server UTC'da ishlasa ham).
- `calculate_next_time()` naive datetime'ni localize qiladi, `replace()` dan
  keyin ofsetni `normalize()` bilan qayta hisoblaydi (DST-xavfsiz).
- Foydalanuvchi kiritgan vaqt **yagona parser** orqali o'tadi:
  `utils/helpers.parse_schedule_input(text) -> (datetime | None, reason)`.
  `reason` — `"empty"` / `"format"` / `"past"`.
  - Tabiiy til ham tushuniladi: `ertaga 5 da`, `2 soatdan keyin`, `завтра 18:00`.
  - **Mavjud bo'lmagan sana/soat jimgina "bugun"ga tushib qolmaydi**:
    `32.13.2026 18:00`, `30.02.2026 10:00`, `25:99` → format xatosi.
  - Xatoda foydalanuvchiga **o'z tilida** aniq namuna ko'rsatiladi:
    `DD.MM.YYYY HH:MM` (masalan `31.12.2026 18:00`, Toshkent vaqti UTC+5).
    Hech qanday holatda handler `ValueError` bilan yiqilmaydi.

### 4. FloodWait (429) + AI timeout himoyasi

**Telegram FloodWait:**

- `check_and_send_posts()` har post orasiga `SEND_MICRO_DELAY = 0.08s`
  (0.05–0.1 oralig'ida) mikro-kechikish qo'yadi.
- `telegram.error.RetryAfter` ushlanadi → `await asyncio.sleep(retry_after)` →
  post `retry_post` orqali qayta navbatga qo'yiladi. **Navbat to'xtamaydi,
  post yo'qolmaydi.** `flood_wait_seconds()` qiymatni `[1s, 60s]` ga cheklaydi,
  shuning uchun ulkan `retry_after` scheduler'ni muzlatib qo'ymaydi.

**AI timeout:**

- Barcha tashqi AI so'rovlari (Gemini, Groq, OpenRouter, Mistral, Cerebras,
  SambaNova, Cloudflare, Pollinations + model discovery) `AI_HTTP_TIMEOUT =
  ClientTimeout(total=35, connect=10, sock_connect=10, sock_read=35)` bilan
  yuboriladi — timeout **har bir so'rovga alohida** uzatiladi, faqat sessiya
  sozlamasiga tayanilmaydi.
- Timeout bo'lsa texnik xato o'rniga **xushmuomala xabar** qaytadi
  (`ai_timeout_message(lang)`, uz/ru), javob esa `{"error": ..., "timeout": True}`
  ko'rinishida bo'ladi — API kalit yo'riqnomasi foydalanuvchiga ko'rsatilmaydi.
- Sozlamalar: `AI_TOTAL_TIMEOUT` (default 35), `AI_CONNECT_TIMEOUT` (10),
  `AI_HARD_TIMEOUT` (butun provayder zanjiri uchun).

### 5. Ishonchlilik paketi: fallback, concurrency, idempotent scheduler, karta config

**Notanish xabar fallback'i (bot hech qachon jim qolmaydi).**
`register_all_handlers()` ning ENG OXIRIDA `MessageHandler(UNKNOWN_MESSAGE_FILTER,
unknown_message_fallback)` turadi — PTB bir guruhda faqat birinchi mos handlerni
ishlatgani uchun u faqat ConversationHandler, buyruqlar, to'lov/rasm handlerlari
xabarni tanimagandagina ishga tushadi. Foydalanuvchi dialogdan tashqarida
tasodifiy matn, voice, audio, kontakt, fayl yoki stiker yuborsa — o'z tilida
(`unknown_message_fallback`, uz/ru) javob va **asosiy reply-menyu** oladi.
Dialog ichida bosqich qabul qilmaydigan tur kelsa — holat buzilmaydi, qisqa
`unknown_in_dialog` eslatmasi chiqadi. Faqat shaxsiy chat; 2 s cooldown (spam yo'q).
Yangi global handler qo'shsangiz — uni fallback qatoridan YUQORIGA qo'ying.

**`main_menu_hint`** (uz: «Quyidagi menyudan kerakli bo‘limni tanlang 👇», ru:
«Выберите нужный раздел из меню ниже 👇») — start, obuna tasdig'i
(`sub_confirmed`), orqaga-menyu oqimlarida; `handlers/start.py: send_main_menu()`
yordamchisi bilan.

**Per-user concurrency (double click).** `main.py` da `GuardedApplication.process_update`
har update'ni `UpdateLockManager` dagi `asyncio.Lock` (kalit `user:<id>` /
`chat:<id>`) ostida ishlaydi: `concurrent_updates=True` bo'lsa ham bitta
foydalanuvchining update'lari **ketma-ket**, turli foydalanuvchilar parallel.
ConversationHandler holati va `context.user_data` race'dan himoyalangan.

**Idempotent scheduler.** `_execute_send`: (1) `mark_post_processing` — Telegramga
yuborishdan OLDIN (yozilmasa yuborilmaydi, keyinroq qayta uriniladi);
(2) yuborilgach `posted + sent_message_id + sent_post_messages` markeri
**backoff bilan** yoziladi (`SENT_MARKER_RETRY_DELAYS`); (3) DB baribir
yotgan bo'lsa marker xotira + journal faylda (`SENT_JOURNAL_PATH`, default
`/tmp/postassist_sent_journal.json`, `off` = faqat xotira) saqlanadi — shu post
**hech qachon qayta yuborilmaydi**, har tick boshida `flush_unpersisted_sent_markers()`
markerni DB'ga yozishga urinadi. `get_due_posts` faqat `pending` ni `FOR UPDATE
SKIP LOCKED` bilan oladi; `recover_stale_processing_posts` yuborilganlarni
`posted` ga o'tkazadi, faqat yuborilmaganlarni (10 daqiqadan eski) `pending` ga.

**Karta rekvizitlari FAQAT .env / Render da.** `config.CARD_NUMBER =
os.getenv("CARD_NUMBER", "")` va `config.CARD_HOLDER = os.getenv("CARD_HOLDER", "")`
— kodda hech qanday default karta raqami yoki egasi YO'Q. Render Environment
yoki `.env` da berilgan qiymatlar to'lov oynasida aynan shu ko'rinishda chiqadi;
bo'sh bo'lsa "rekvizitlar sozlanmagan" xabari ko'rsatiladi. Eski
`PAYMENT_CARD_NUMBER` / `PAYMENT_CARD_HOLDER` nomlari faqat import alias
sifatida qoldi (qiymatni belgilamaydi).

**Stiker filtri.** Post tayyorlash (GET_CONTENT) va tasdiqlash bosqichida stiker
kelsa `np_sticker_not_allowed` (uz: «Kechirasiz, stikerlar post sifatida qabul
qilinmaydi. Iltimos, rasm, video yoki matn yuboring», ru ekvivalenti); voice /
video_note / kontakt — `np_media_not_allowed`. Holat saqlanadi, bot osilmaydi.

### Testlar

```bash
cd telegram_bot
bash tests/run_tests.sh
```

| Suite | Testlar |
|---|---|
| `unit_test.py` | 2085 |
| `new_requirements_test.py` | 43 |
| `schema_test.py` | 68 |
| `ai_mock_test.py` | 52 |
| `load_test.py` (real PostgreSQL, `pip install pgserver`) | 100 |

## Bot "doim ishlashi" uchun

Yuqoridagi `python main.py` faqat siz uni ishga tushirib turgan vaqtda
ishlaydi (kompyuter/terminal yopilsa — to'xtaydi). 24/7 ishlashi uchun
quyidagilardan birini tanlang:

- **O'z kompyuteringiz doim yonib tursa**: `screen` yoki `tmux` orqali fonda
  ishga tushiring, masalan:
  ```bash
  screen -S mybot
  python main.py
  # Ctrl+A keyin D bosib chiqib ketasiz, bot ishlashda davom etadi
  ```
- **Server/VPS bo'lsa**: `systemd` service qilib qo'yish tavsiya etiladi
  (so'rasangiz, buning uchun ham tayyor fayl yozib beraman).
- **Bepul bulut xizmati** (Railway, Render, PythonAnywhere va h.k.):
  loyihani GitHub'ga yuklab, o'sha xizmatga ulash orqali ishga tushirish
  mumkin — so'rasangiz shu bo'yicha ham qadam-baqadam yo'riqnoma tayyorlab
  beraman.

## Muhim eslatmalar

- Bot faqat `ADMIN_ID` da ko'rsatilgan siz uchun ishlaydi — boshqa hech kim
  botga buyruq bera olmaydi.
- Barcha rejalashtirilgan xabarlar PostgreSQL (Neon/Render) bazasida saqlanadi —
  bot qayta ishga tushirilganda ular avtomatik qayta yuklanadi (yo'qolmaydi).
- Bir martalik xabar yuborilgach, ro'yxatdan avtomatik olib tashlanadi.
