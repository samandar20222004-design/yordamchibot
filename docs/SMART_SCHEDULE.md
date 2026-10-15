# Aqlli rejalash (Mini App) va takrorlanuvchi postlar

Foydalanuvchi vaqtni oddiy tilda yozadi («har dam olish kuni soat 12:00 da», «ikki kunda bir marta 18:30», «каждый понедельник в 9»,
«every weekday at 8:15»). Server **taklif** qaytaradi, foydalanuvchi **tasdiqlaydi**, keyin post odatdagidek rejalanadi.
Qo'lda kiritish (sana + «Takrorlash» tanlovi) saqlangan. Hech narsa tasdiqsiz yozilmaydi.

## Takrorlanish modeli (sxema o'zgarmagan)
`services/recurrence.py`. Mavjud ustunlarga joylanadi:

| `recurrence_type` | `recurrence_day` | Ma'nosi |
| --- | --- | --- |
| `daily` | — | har kuni |
| `weekly` | 0..6 (dushanba=0) | haftada bir marta |
| `interval` | 2..30 | har N kunda (yangi) |
| `weekdays` | bitmask 1..127 (Du=1 … Ya=64) | tanlangan hafta kunlari: dam olish=96, ish kunlari=31 (yangi) |

Vaqt (`recurrence_time`) va barcha hisob — Asia/Tashkent. Normalizatsiya: `interval=1` → `daily`; bitta kun → `weekly`; 7 kun → `daily`.
Scheduler: `calculate_next_time` yangi turlarni qo'llaydi; yuborilgach «posted + qayta rejalash» avvalgidek BITTA tranzaksiyada,
`end_date` qoidasi (AUDIT-009) yangi turlarda ham ishlaydi.

## API
* `POST /api/v1/schedule/parse` `{text (<=300), default_time?: "HH:MM"}` → `{ok:true, source:"rules"|"ai", proposal:{scheduled_at (UTC ISO), recurrence|null}}`
  yoki `{ok:false, reason: empty|too_long|no_time|unrecognized|past}`. Hech narsa yozmaydi.
* `POST /api/v1/posts` endi ixtiyoriy `recurrence:{type,day,time}` oladi. Qat'iy: `scheduled_at` ning Toshkent vaqti `time` ga, hafta kuni
  qoidaga mos bo'lishi shart; `send_now` bilan birga bo'lmaydi (aks holda 422 `invalid_input`).
* Ro'yxat/kalendar/`GET /posts/{id}` javoblarida `recurrence_day`, `recurrence_time` (HH:MM).

## Qanday aniqlanadi
1. **Qoidalar** (`services/schedule_nlp.py`, uz/ru/en, deterministik, BEPUL): takrorlanish iboralari (har kuni, kunora, har N kunda, dam olish /
   ish kunlari, hafta kunlari, haftada bir), vaqt (`12:00`, `soat 9 da`, `в 9`, `6pm`, «shu vaqtda» = tahrirlagichdagi vaqt), kun so'zlari
   (bugun/ertaga/indinga, hafta kuni). **Taxmin yo'q**: soat aniqlanmasa `no_time`; o'tib ketgan vaqt rad etiladi (`past`).
2. **AI zaxirasi** — faqat qoidalar tushunmasa: qat'iy JSON kontrakt, matn `<untrusted_input>` ichida, natija `validate_proposal` dan o'tadi
   (kelajakda, <=366 kun, yaroqli takrorlanish). Free foydalanuvchida 1 AI so'rov bron qilinadi va AI foydasiz javob bersa/xato bo'lsa QAYTARILADI;
   PRO/admin bronsiz (xarajat umumiy AI byudjeti bilan cheklanadi). Kvota tugagan bo'lsa qoidalar yo'li baribir ishlaydi.

## Cheklovlar (ataylab)
Tugash sanasi («10 kun davomida»), oylik takror («har oyning 1-si»), so'z bilan yozilgan soat («o'n ikkida») qo'llab-quvvatlanmaydi — qo'lda kiritiladi.
Takrorlanish vaqti Toshkent bo'yicha; qurilma boshqa zonada bo'lsa interfeys buni eslatadi.

## Botda (post vaqti bosqichi)
- **Matn**: «har dam olish kuni 12:00», «ikki kunda bir marta 18:30» kabi iboralar `handlers/schedule_smart.py` orqali qoidalar bilan aniqlanadi
  (AI'siz, hamma uchun) va tasdiq kartasiga tushadi. Oddiy vaqt («18:00», «ertaga 9:00», `DD.MM.YYYY HH:MM`) eski parserda qoladi — xulq o'zgarmagan.
  Bot matnida AI zaxirasi yo'q (faqat Mini App'da).
- **Ovoz**: vaqt bosqichida ovozli/audio xabar. Kvota (`voice_schedule_usage`): free — butun umr bo'yicha **1 ta**, PRO — 24 soatda **20 ta**,
  admin — cheksiz. Bron ovozni matnga o'girishdan OLDIN (atomik); yuklash/STT xatosi yoki vaqt aniqlanmasa bron **qaytariladi**; DB xatosida rad (fail-closed).
  Natija doim tasdiq kartasida ko'rsatiladi — foydalanuvchi tasdiqlamaguncha hech narsa rejalanmaydi.
- Post botga yuborilgach (o'ziniki yoki boshqa kanaldan forward) davom etish: botda yoki «📱 Mini App'da» tugmasi (qoralama) — Mini App yoqilgan bo'lsa.
