# 🔗 Manba havolalari — kim qayerdan keldi

Har bir reklama joyi yoki hamkor uchun alohida havola: `https://t.me/<bot>?start=s_<kod>`.
Bot shu havola bilan kim kirganini, nechtasi kanal ulagani, post qilgani va to'laganini hisoblaydi.

## Admin buyruqlari (RBAC: `manage_promos` — owner, super_admin, admin)

| Buyruq | Nima qiladi |
|---|---|
| `/link_new KOD Nomi` | Reklama joyi uchun havola (egasiz: faqat statistika) |
| `/link_new KOD @username Nomi` | Hamkor havolasi: kelganlar uning takliflari sifatida yoziladi |
| `/links` | Barcha havolalar va natijasi |
| `/link KOD` | Tafsilot, foizlar va oxirgi 20 ta kelgan odam (ism, @username, ID, 📢 kanal · 📝 post · 💎 to'lov) |
| `/link_off KOD`, `/link_on KOD` | O'chirish / yoqish (o'chirilganda bot ishlayveradi, faqat hisob to'xtaydi) |
| `/link_user ID` yoki `/link_user @username` | Foydalanuvchi qaysi havola bilan ro'yxatdan o'tgani va qaysilarini bosgani |

Panel: `/admin` → Promo-kod → «🔗 Havolalar».
KOD: lotin harflari, raqam va `_` (2–24 belgi), katta harf va tire avtomatik `kichik_harf` ga aylanadi.

## Hamkor uchun

`/mylinks` — o'z havolalari va sonlar (bosish, yangi, post qilgan, to'lagan). Boshqa odamlarning shaxsiy ma'lumoti ko'rsatilmaydi.

## Ball kimga yoziladi

* Havolaning **egasi bo'lsa**, yangi foydalanuvchi egasining taklifi sifatida saqlanadi (`users.referrer_id`).
  Ball oddiy referal qoidasi bilan beriladi: taklif qilingan odam **birinchi postini** qilganda
  (`ReferralService.register_first_action`, 1–3 do'st +3, keyingilar +1). O'zini taklif qilish va takroriy profil rad etiladi.
  Egasiga «do'st qo'shildi» xabari boradi.
* **Egasi bo'lmasa** (reklama kanali) — ball hech kimga yozilmaydi, faqat statistika.
* Faqat **yangi** foydalanuvchi hisoblanadi. Botda avvaldan bor odam havolani bossa, bosish va tashrif yoziladi, lekin ball yo'q.
* **Birinchi tegish:** odam qaysi havola bilan ro'yxatdan o'tgan bo'lsa, o'sha havolaga yoziladi.
  Keyin boshqa havolani bossa ham bu o'zgarmaydi.

## Ko'rsatkichlar

| Belgi | Ma'nosi |
|---|---|
| 👆 bosish | havola orqali har bir /start (takrorlar bilan) |
| 👤 noyob | shu havolani bosgan turli odamlar |
| 🆕 yangi | shu havola bilan ro'yxatdan o'tganlar |
| 📢 kanal | yangilardan kanal ulagani (yoki post qilgani) |
| 📝 post | yangilardan kamida bitta post saqlagani (vaqt bir marta yoziladi, eski postlar tozalansa ham hisob buzilmaydi) |
| 💎 to'lov | yangilardan muvaffaqiyatli to'lov qilgani yoki PRO/ULTRA bo'lgani |

Eng muhim raqam — **narx ÷ 📝 post qilganlar**: bitta faol foydalanuvchi qanchaga tushdi.

## Texnik

* Jadvallar: `tracked_links`, `tracked_link_visits` (`schema.sql`, idempotent).
* Kod: `repositories/tracked_links_repository.py`, `handlers/tracked_links.py`, `translations/tracked_links.py`,
  /start — `handlers/start.py` (`s_` parametri), post hook — `posts_repository.add_post`, `scheduler_repository` (haftalik reja).
* Tashrif /start javobidan keyin fonda yoziladi; DB xatosi /start ni buzmaydi.
* Test: `tests/tracked_links_test.py` (real PG qismi `MINIAPP_TEST_DATABASE_URL`).
