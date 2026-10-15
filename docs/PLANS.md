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
| Navbat (kutilayotgan postlar) | 5 | 100 | 500 |
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

## Narxlar (so'm · Stars) — 4 muddat: 1, 3, 6 oy va 1 yil (6 oy = 180 kun)

| Muddat | PRO so'm | PRO tejam | PRO Stars | ULTRA so'm | ULTRA tejam | ULTRA Stars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 oy | 19 000 | — | 80 | 39 000 | — | 165 |
| 3 oy | 49 000 | 14% | 205 | 99 000 | 15% | 415 |
| 6 oy | 89 000 | 22% | 375 | 189 000 | 19% | 790 |
| 1 yil | 159 000 | 30% | 665 | 349 000 | 25% | 1 460 |

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
