# Tariflar va limitlar — e'lon qilingan == majburlanadigan

Yagona manba: `telegram_bot/config.py` (env bilan o'zgaradi). Bot tarif kartasi, tugma narxlari, Mini App (`/me`) va
majburlash funksiyalari SHU qiymatlarni o'qiydi; matnlarda qattiq yozilgan raqam yo'q (`tests/plan_limits_consistency_test.py`).

## Limitlar

| Limit | Free | PRO / Enterprise | Env | Qayerda majburlanadi |
| --- | --- | --- | --- | --- |
| Kanallar | 3 | cheksiz (999) | `FREE_MAX_CHANNELS`, `PRO_MAX_CHANNELS` | `check_channel_limit` |
| Kunlik AI so'rov | 5 | cheksiz (999) | `FREE_DAILY_AI`, `PRO_DAILY_AI` | `reserve_ai_request` / `check_ai_limit` (atomik); Mini App `POST /ai/generate` ham shu yo'ldan |
| Navbat (kutilayotgan postlar) | 5 | cheksiz (999) | `FREE_QUEUE_MAX_POSTS`, `PRO_QUEUE_MAX_POSTS` | `check_queue_limit` (bot navbati, autopilot, Mini App yaratish) |
| Kontent-reja | 7 kunlik, haftasiga 1 ta | 7 va 30 kunlik, cheklovsiz | — | `can_create_calendar` |
| Ovozli rejalash (botda vaqtni ovoz bilan aytish) | 1 ta, butun umr bo'yicha | kuniga 20 ta (24 soat oynasi); admin cheksiz | `FREE_VOICE_SCHEDULE_TOTAL`, `PRO_VOICE_SCHEDULE_DAILY` (0 = o'chiq) | `services/voice_schedule_quota.py` (atomik bron, STT'dan OLDIN; xatoda qaytariladi; DB xatosida fail-closed) |

Barcha limit tekshiruvlari obuna MUDDATINI hisobga oladi (muddati o'tgan PRO free limitiga tushadi; `_effective_plan`).
Free postlarga kanalda `🤖 @BOT` imzosi qo'shiladi, PRO/admin toza (`apply_post_watermark`).

## Narxlar (standart)

| Tarif | Stars | USD | So'm (karta/Payme) | 1 oylikka nisbatan tejam |
| --- | --- | --- | --- | --- |
| 1 oy | 75 | ~1.5 | 19 000 | — |
| 3 oy | 175 | ~3.5 | 45 000 | ~22% |
| 1 yil | 550 | ~11 | 140 000 | ~39% (`plan_discount_percent` hisoblaydi; matnda qattiq «-40%» yo'q) |

Stars↔USD (~0.02 $/★) va USD↔so'm (`USD_UZS_RATE` 12 600) bir-biriga mos; to'lov usullari bir xil `SUBSCRIPTION_PLANS` dan oladi.

## Tekshirib bo'lmaydigan e'lonlar (egasi tasdiqlaydi)
Tarif kartasidagi «Ustuvor yordam» va «To'liq analitika» kodda majburlanadigan funksiya emas: birinchisi qo'llab-quvvatlash jarayoni
(kodda yo'q), ikkinchisida bepul foydalanuvchi ham asosiy analitikani ko'radi. Matnni haqiqiy imkoniyatga moslash yoki jarayonni
yo'lga qo'yish egasining qarori.
