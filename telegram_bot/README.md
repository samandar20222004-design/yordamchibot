# Telegram Kanal Bot — Rejalashtirilgan Xabarlar

Bu bot sizning Telegram kanalingizga siz belgilagan vaqtda (bir marta yoki
har kuni, istalgan muddatgacha — masalan 1 yil) xabarlarni avtomatik jo'natadi.
Bot **AI Studio** (doimiy inline navigatsiya va zamonaviy AI prompt tizimi) orqali matn yaratish, kanal postlarini qayta ishlash va kontent-reja tuzish imkoniyatlarini taqdim etadi.

## Loyiha tuzilishi

```
telegram_bot/
├── main.py              # Botni ishga tushiruvchi asosiy fayl
├── config.py            # Sozlamalar (token, admin id, kanal)
├── database.py          # SQLite baza bilan ishlash
├── scheduler.py         # Vaqt bo'yicha jo'natish logikasi
├── handlers/
│   ├── start.py         # /start, /help, profil va bonuslar
│   ├── new_post.py      # /newpost — yangi xabar qo'shish
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

**Kanal xavfsizligi:** kanalni faqat o'sha kanal/guruh administratori ulay
oladi. Faol kanalni boshqa foydalanuvchi o'g'irlay olmaydi. Bot kanaldan
chiqarilsa, ulanish avtomatik nofaol bo'ladi.

## Render va UptimeRobot sozlamalari

Render'da **Root Directory** ni `telegram_bot`, Build Command'ni `pip install -r requirements.txt`, Start Command'ni `python main.py` qilib qo'ying. Environment Variables ichida `BOT_TOKEN`, `ADMIN_ID` va Render PostgreSQL bergan `DATABASE_URL` bo'lishi kerak. `PORT` ni qo'lda berish shart emas: kod Render bergan portni o'zi oladi.

UptimeRobot monitor turi **HTTP(s)** bo'lsin va URL quyidagicha berilsin:
`https://sizning-render-service.onrender.com/health/live`
Health endpoint `200` va JSON qaytaradi. UptimeRobot bot polling'ini emas, Render web-service'ni uyg'oq saqlaydi.

### Health endpointlar

| Endpoint | Vazifasi |
|---|---|
| `/health/live` | Bot jarayoni ishlayaptimi — doim `200` (UptimeRobot shu yerga qaraydi) |
| `/health/ready` | Bot ishlashga tayyormi — baza bilan aloqa tekshiradi (`200` yoki `503`) |
| `/health`, `/` | `/health/live` bilan bir xil (eski havolalar ishlashda davom etadi) |

### AI sozlamalari (kamida bitta bepul kalit; 6 ta provayder navbatma-navbat ishlaydi)

| # | Kalit | Qayerdan olinadi | Bepul limiti |
|---|---|---|---|
| 1 | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | kuniga ~1500 so'rov |
| 2 | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | kuniga ~1000 so'rov |
| 3 | `OPENROUTER_API_KEY` (ixtiyoriy) | [openrouter.ai](https://openrouter.ai) | `:free` modellar |
| 4 | `MISTRAL_API_KEY` (ixtiyoriy) | [console.mistral.ai](https://console.mistral.ai) | oyiga ~1 mlrd token |
| 5 | `CEREBRAS_API_KEY` (ixtiyoriy) | [cloud.cerebras.ai](https://cloud.cerebras.ai) | kuniga 1M token |
| 6 | — (kalit shart emas) | Pollinations | cheklangan |

AI so'rovi ketma-ketlikda sinab ko'riladi: **Gemini → Groq → OpenRouter →
Mistral → Cerebras → Pollinations**. Birinchisi ishlasa — shu javob qaytadi,
ishlamasa keyingisiga o'tadi. Har bir provayder 3 marta ketma-ket xato bersa,
10 daqiqaga vaqtincha o'tkazib yuboriladi (tezroq javob uchun).

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

### Avtomatik reklama rotatsiyasi (ad-pool)

Admin panelda **📢 Kanal posti reklamasi** va **🤖 Bot xabari reklamasi** endi
bitta matn emas, **reklamalar puli** (pool) saqlaydi. Pulga bir nechta reklama
qo'shasiz, bot ularni navbatma-navbat (round-robin) ishlatadi:

- **Kanal postlari** — har postga puldagi navbatdagi reklama qo'shiladi.
- **Bot javoblari** — har 3-xabarga puldagi navbatdagi reklama qo'shiladi.

Pul menyusida quyidagilar bor:

- **➕ Yangi reklama qo'shish** — matn yozasiz, pulga qo'shiladi (yoki to'g'ridan-to'g'ri matn yozib yuborishingiz mumkin).
- **🗑 Reklama o'chirish** — puldagi reklamalardan birini tanlab o'chirasiz.
- **🧹 Hammasini tozalash** — butun pulni tozalaydi (`clear` deb yozsangiz ham bo'ladi).
- **ℹ️ Rotatsiya haqida** — bu funksiya qanday ishlashini tushuntiradi.

> Orqaga moslik: pul **bo'sh** bo'lganda bot eski yagona reklama
> sozlamasidan (`channel_ad_text` / `bot_reply_ad_text`) foydalanishda davom
> etadi — shuning uchun mavjud konfiguratsiya buzilmaydi.
- **⚙️ AI parametrlar** — temperature, max_tokens, top_p, prompt limit,
  kontekst hajmi va xabarlar sonini runtime'da o'zgartirish.
- **🗄️ DB/Kesh holati** — PostgreSQL pool holati va TTL kesh yozuvlari sonini
  ko'rish, kerak bo'lganda keshni tozalash.

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
- Barcha rejalashtirilgan xabarlar `bot_database.db` faylida saqlanadi —
  bot qayta ishga tushirilganda ular avtomatik qayta yuklanadi (yo'qolmaydi).
- Bir martalik xabar yuborilgach, ro'yxatdan avtomatik olib tashlanadi.
