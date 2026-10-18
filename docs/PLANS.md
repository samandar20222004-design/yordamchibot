# Tariflar va limitlar — e'lon qilingan == majburlanadigan

Yagona manba: `telegram_bot/config.py` (`TARIFF_CATALOG`, `TIER_LIMITS`; env bilan o'zgaradi). Bot tarif kartalari, tugma narxlari,
Stars/karta/Payme to'lovlari, Mini App (`/me`) va majburlash funksiyalari SHU qiymatlarni o'qiydi; matnlarda qattiq yozilgan raqam yo'q
(`tests/plan_limits_consistency_test.py`, `tests/tariff_tiers_test.py`). Narxlar va foizlar — egasi tasdiqlagan BOSHLANG'ICH model:
ishga tushirishdan oldin AI xarajati, to'lov komissiyalari va haqiqiy foydalanish statistikasi bilan tekshiriladi.

## Uch tarif

| | FREE | PRO | ULTRA |
| --- | --- | --- | --- |
| Kimlar uchun | sinab ko'ruvchi, kichik kanal | 1–10 kanal yuritadigan kanal egasi, kontent yaratuvchi | 10–30 kanal, SMM mutaxassis, jamoa |
| Kanallar | 3 | 10 | 30 |
| Kunlik AI so'rov | 5 | 40 | 100 |
| Navbat (kutilayotgan postlar, barcha kanallar bo'yicha) | 40 | 300 | 900 |
| Ovozli rejalash | 1 marta (butun umr) | kuniga 20 | kuniga 100 |
| Kontent-reja | 7 kunlik, haftasiga 1 | 7 va 30 kunlik | 7 va 30 kunlik |
| Kanal postida PostAssist imzosi | bor | yo'q | yo'q |
| Env | `FREE_*` | `PRO_*` | `ULTRA_*` |

`enterprise` — muddatsiz, admin bergan (cheksiz, 999 belgisi). Limit tekshiruvlari obuna MUDDATINI hisobga oladi (muddati o'tgan PRO/ULTRA
FREE limitiga tushadi; lazy downgrade + sweep). Har bir AI so'rov kunlik limitdan 1 ta ayiradi; limit tugasa kreditlar ishlatiladi.
"Cheksiz" so'zi faqat amalda cheksiz bo'lgan holatlarda (enterprise, eski to'langan PRO muddati) ko'rsatiladi.

Majburlash: `check_channel_limit`, `reserve_ai_request` / `check_ai_limit` (atomik), `check_queue_limit` (bot, autopilot, Mini App),
`services/voice_schedule_quota.py` (atomik bron, STT'dan OLDIN; xatoda qaytariladi; DB xatosida fail-closed), AI xarajat byudjeti
`services/ai/budget.py` (FREE/PRO/ULTRA alohida kunlik/oylik token va USD).

## Narxlar — 4 muddat: 1, 3, 6 oy va 1 yil (6 oy = 180 kun)

**Mintaqaga qarab:** O'zbekiston — so'm (Uzcard/Humo/Payme); chet el — dollar (Telegram Stars), O'zbekiston narxidan **1,7 baravar qimmat**
(`INTL_PRICE_MULTIPLIER`; Stars 5 ga yaxlitlanadi, 1 ★ = 0,02 $). Mintaqa: foydalanuvchi tanlovi (`users.pay_region`, tarif kartasidagi
«🌍 Dollar narxi» / «🇺🇿 So'm narxi» tugmasi yoki to'lov mintaqasi menyusi), tanlanmagan bo'lsa tildan (`uz` -> so'm, `ru`/`en` -> dollar).
Telegram mamlakatni bermaydi, shuning uchun bu taxmin; foydalanuvchi o'zi almashtira oladi. Stars faqat xalqaro mintaqada sotiladi.

| Muddat | PRO so'm | PRO $ (Stars) | ULTRA so'm | ULTRA $ (Stars) |
| --- | ---: | ---: | ---: | ---: |
| 1 oy | 29 000 | $3.90 (195) | 69 000 | $9.40 (470) |
| 3 oy | 75 000 | $10.20 (510) | 175 000 | $23.60 (1 180) |
| 6 oy | 135 000 | $18.20 (910) | 335 000 | $45.20 (2 260) |
| 1 yil | 245 000 | $33.00 (1 650) | 620 000 | $83.60 (4 180) |

Quyidagi jadvaldagi «Stars» ustunlari — O'ZBEKISTON EKVIVALENTI (asos, `STARS_PRICE_*`); mijoz to'laydigan xalqaro Stars yuqoridagi jadvalda.

| Muddat | PRO so'm | PRO tejam | PRO Stars | ULTRA so'm | ULTRA tejam | ULTRA Stars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 oy | 29 000 | — | 115 | 69 000 | — | 275 |
| 3 oy | 75 000 | 14% | 300 | 175 000 | 15% | 695 |
| 6 oy | 135 000 | 22% | 535 | 335 000 | 19% | 1 330 |
| 1 yil | 245 000 | 30% | 970 | 620 000 | 25% | 2 460 |

### Narx qanday belgilandi (bozor bilan solishtirish)
Hisob: 1 USD ≈ 12 600 so'm (`USD_UZS_RATE`), 1 ★ ≈ 0,02 USD. Ochiq manbalarda topilgan ko'rsatkichlar (aniq tarif sahifalari har xil va tez eskiradi — ishga
tushirishdan oldin qayta tekshiring):
* Telegram Premium ≈ 4,99 USD/oy (~63 000 so'm) — bu rejalash vositasi emas, lekin foydalanuvchi uchun «Telegram uchun to'lov» mezoni;
* xalqaro kanal rejalash xizmatlari ≈ 9–14 USD/oy (~115 000–175 000 so'm) (masalan Schedulala, Postmypost — 2020–2026 ma'lumotlari, manbalar bir-biriga mos kelmaydi);
* SMMplanner (RF) boshlang'ich ≈ 675 RUB/oy (~90 000 so'm).
Avvalgi 19 000 / 39 000 so'm (≈ 1,5 / 3,1 USD) bu darajalardan 5–10 baravar past edi va AI xarajati uchun ajratilgan ulush juda kichik qolardi
(oylik AI chegarasi narxning 40% i). Yangi PRO 29 000 (≈ 2,3 USD), ULTRA 69 000 (≈ 5,5 USD): xalqaro analoglardan hamon 2–5 baravar arzon, mahalliy
xarid qobiliyatiga mos, AI byudjeti esa mos ravishda oshadi (`services/ai/budget.py`). Tejam foizlari avvalgi qaror bilan bir xil (14/22/30 va 15/19/25).
Narxlar env bilan o'zgartiriladi; o'zgartirsangiz hujjat, matnlar va byudjet o'zi moslashadi.

Telegram o'zining rejalashi (har bir chatga odatda ~100 ta kutilayotgan xabar — rasmiy raqam e'lon qilinmagan) takroriy post, AI, ovozli rejalash va
bir nechta kanalni yagona navbatda boshqarishni bermaydi; bizda bepul navbat BARCHA kanallar bo'yicha 40 ta.

Tejam foizi `plan_discount_percent` bilan HAQIQIY narxlardan hisoblanadi (matnda qattiq foiz yo'q). Stars hisobi: taxminan 1 ★ ≈ 0,02 $ —
yakuniy qiymat emas; Stars bo'yicha tushum, komissiya va xarid narxi alohida tekshiriladi.
Tarif kalitlari: PRO `1m 3m 6m 1y` (eski callback/payload/buyurtmalar bilan mos), ULTRA `u1m u3m u6m u1y`. Stars payload: `sub_stars_<kalit>_<user_id>`.

## Tarif berish qoidalari (`services/plan_sql.py` — Stars, karta cheki, Payme, admin, promo uchun bir xil)

* to'lov muvaffaqiyatli bo'lmaguncha pullik tarif yoqilmaydi; keyin foydalanuvchiga tarif, amal qilish muddati va ochilgan imkoniyatlar ko'rsatiladi;
* muddat `max(joriy muddat, hozir) + kunlar` — qolgan muddat kuyib ketmaydi;
* PRO -> ULTRA: tarif darhol ULTRA, qolgan PRO kunlari ham ULTRA sifatida davom etadi;
* faol ULTRA foydalanuvchi PRO xarid qilsa tarif PASAYMAYDI (muddat qo'shiladi); bot ULTRA/enterprise'ga PRO sotish tugmasini ko'rsatmaydi;
* `enterprise` (muddatsiz) hech qachon o'zgarmaydi; Stars refund: shu to'lov kunlari ayriladi (`refund_stars_payment`);
* admin: `/grant_pro <user_id> <kun> [pro|ultra]`.

## Mavjud PRO foydalanuvchilar (grandfathering)

PRO limitlari 999 dan 10 / 40 / 100 ga tushdi. Tarif yangilanishidan OLDIN to'langan muddat eski limitlarda saqlanadi: `schema.sql`dagi BIR
martalik migratsiya (`system_settings.tariff_v2_legacy_marked`) faol PRO'larga `users.pro_legacy_until = to'langan muddat tugashi` qo'yadi
(muddatsiz PRO — cheksiz). Shu sanagacha `pro_legacy` limitlari (999) amal qiladi; keyin yangi PRO limitlari. Yangi xaridorlarga belgi qo'yilmaydi.
Tarif kartasida «Eski PRO shartlari <sana> gacha saqlanadi» eslatmasi ko'rinadi. Foydalanuvchilarga o'zgarishni oldindan e'lon qilish — egasining ishi
(bot xabari/kanal posti); kod huquqlarni birdan kamaytirmaydi.

## Hali e'lon QILINMAYDIGAN (amalga oshirilgach qo'shiladi)
Kengaytirilgan analitika va davriy hisobotlar, jamoa rollari, postni nashrdan oldin tasdiqlash, mijoz/jamoa ish joylari, ommaviy boshqaruv, kontent
variantlari, «ustuvor yordam» — tarif kartalarida va'da qilinmaydi (kodda majburlanmaydi). Channel DNA ham to'liq ishlashi tasdiqlanmaguncha tarif
imkoniyati sifatida yozilmaydi.

## Referal va chegirmalar
Hozirgi referal: do'st birinchi postini yaratgach kredit (`services/referral_service.py`). «Do'st birinchi marta PRO/ULTRA xarid qilsa taklif
qiluvchiga kredit/bonus» va yangi mijozga 5% birinchi xarid chegirmasi — keyingi bosqich (`docs/GROWTH_PLAN.md`): chegirma muddati, tariflar va
promo/yillik chegirmalar bilan qo'shilish qoidasi oldindan belgilanadi.
