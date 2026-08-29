# Telegram Kanal Bot — Rejalashtirilgan Xabarlar

Bu bot sizning Telegram kanalingizga siz belgilagan vaqtda (bir marta yoki
har kuni, istalgan muddatgacha — masalan 1 yil) xabarlarni avtomatik jo'natadi.

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
