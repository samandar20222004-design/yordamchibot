# Kanal analitikasi — ma'lumot manbalari va halollik qoidalari

Bu hujjat PostAssist analitikasi **qaysi raqamlarni haqiqatan bila olishi**, qaysilarini bila olmasligi va nima uchun ekanini belgilaydi.
Qoida: **Telegram bermaydigan qiymat to'qilmaydi.** Noma'lum = noma'lum (0 emas).

## Hozir yig'iladigan (ishonchli)
| Ko'rsatkich | Manba | Jadval | Izoh |
|---|---|---|---|
| Obunachilar soni | Bot API `getChatMemberCount` (rasmiy) | `channel_member_counts` | Kuniga BITTA snapshot (`snapshot_date`, Asia/Tashkent), `source`, `collected_at`. Bot kanalda a'zo/admin bo'lishi shart. Tarix faqat bot snapshot olgan kundan boshlanadi. |
| O'sish (7 / 30 kun) | Shu snapshot'lar | hisob (`services/channels/growth.py`) | Faqat mos eski snapshot bo'lsa; aks holda `None` ("ma'lumot yetarli emas"). Extrapolyatsiya YO'Q. |
| Bot orqali yuborilgan postlar soni, turlari, vaqtlari | botning o'z `scheduled_posts` | `scheduled_posts` | Ishonchli, lekin bu "kanal natijasi" emas, bot faoliyati. |
| Post chiqqan soat/hafta kuni | `channel_post_events` | `channel_post_events` | "Eng yaxshi vaqt" = post QACHON chiqarilgani taqsimoti, auditoriya faolligi EMAS. |

### Ishonch darajasi (`confidence`)
`none` — snapshot yo'q · `low` — kam (<4 nuqta yoki <7 kun) yoki eskirgan (>3 kun) · `medium` — ≥4 nuqta va ≥7 kun · `high` — ≥15 nuqta va ≥30 kun.
Dashboard `none/low/stale` da "Ishonch past" izohini ko'rsatadi.

## Hozir yig'ilmaydigan (va nima uchun)
* **Post ko'rishlari (views).** Telegram Bot API `Message` obyektida `views` maydoni **yo'q** (PTB `Message` da ham yo'q; tekshirilgan).
  Avvalgi kod `getattr(msg, "views", 0)` bilan har doim `0` yozardi. Endi `channel_posts_history.views` noma'lum bo'lsa **NULL**;
  `views_source` va `views_collected_at` qiymat qayerdan/qachon olinganini bildiradi (hozir hech bir oqim to'ldirmaydi).
  `get_channel_posts_history` eski iste'molchilar uchun `views` ni int (noma'lum -> 0) qaytaradi, lekin `views_known` bilan ajratiladi.
* **Reaksiyalar (Telegram native).** Bot `message_reaction_count` ni faqat kanal ADMINI bo'lsa va `allowed_updates` da so'ralsa oladi;
  handler hali yo'q. Hozir faqat bot qo'ygan inline tugma bosilishlari (`post_reactions`) haqiqiy.
* **Auditoriya faolligi, saqlashlar, ulashishlar** — Bot API bermaydi.

### Eski (soxta) `0` qiymatlar
Bu o'zgarishdan OLDIN saqlangan `channel_posts_history.views = 0` qatorlari o'lchanmagan (Bot API ko'rishlarni bermaydi), lekin haqiqiy `0`
dan ajratib bo'lmaydi — shuning uchun **avtomatik o'zgartirilmadi** (production ma'lumotiga tegilmaydi). Ular yangi NULL'lar bilan aralashib
`AVG/SUM` ni pasaytirishi mumkin; Python iste'molchilari (advisor, recycle, content-loop) NULL ni ham `0` deb o'qiydi (`views_known` dan hali
foydalanmaydi). Egasi tasdiqlasa, bir martalik tuzatish (ma'lumotni O'ZGARTIRADI, avval zaxira oling):
`UPDATE channel_posts_history SET views = NULL WHERE views = 0 AND views_source IS NULL;`

## Kelajakdagi manbalar (qurilmagan; faqat cheklovlar)
| Manba | Nima beradi | Cheklov |
|---|---|---|
| `t.me/s/<username>` ochiq sahifa | ko'rishlar (taxminiy, ommaviy) | Telegram ToS buni kafolatlamaydi; HTML o'zgarsa sinadi; private kanalda ishlamaydi. Faqat `views_source='tme_preview'` va "taxminiy" belgisi bilan ishlatilishi mumkin. |
| `message_reaction_count` | kanal postlari reaksiyalari jami | Bot ADMIN bo'lishi, `allowed_updates`; tarixiy ma'lumot yo'q. |
| MTProto (Telethon/Pyrogram) | to'liq `views`, `forwards`, reaksiyalar | Foydalanuvchi akkaunti sessiyasi (telefon + kod/2FA), saqlash xavfsizligi, userbot ToS riski, kanal egasi roziligi. |
| Telegram rasmiy "Statistics" | batafsil | 500+ obunachi va admin akkaunti; Bot API orqali berilmaydi. |

## Maxfiylik va xavfsizlik
* `get_channel_member_history(..., user_id)` natijani FAQAT kanal egasi uchun qaytaradi (callback'dagi kanal ID'siga ishonilmaydi).
* Kanal qatori o'chirilganda (90 kunlik nofaol tozalash) uning snapshot'lari ham keyingi `cleanup_old_data` da o'chadi (yetim qoldirilmaydi).
* Snapshot'lar 400 kundan keyin o'chiriladi (`cleanup_old_data`); hisob o'chirilganda kanal bilan bog'liq qatorlar ham o'chadi
  (`_ACCOUNT_DELETE_CHANNEL_SCOPED`).
* Snapshot ishi (`snapshot_channel_member_counts_job`): har 6 soatda, faqat BUGUN hali olinmagan faol kanallar (idempotent);
  bitta kanal xatosi ishni to'xtatmaydi, FloodWait'da to'xtaydi. Bot chiqarilgan / chat topilmagan ("o'lik") kanal 24 soat qayta
  so'ralmaydi (jarayon xotirasida), shuning uchun u navbat boshida turib sog'lom kanallarni to'smaydi.

## Testlar
`analytics_foundation_test` (real PG: sxema, NULL views, snapshot, tozalash, IDOR), `analytics_channel_post_test`,
`analytics_member_growth_test` (hisob + snapshot ishi), `analytics_dashboard_members_test` (ekran, uz/ru/en).

## Mini App

`GET /api/v1/channels/{channel_id}/analytics` (faqat egasi) va «Tahlil» tabi: bot dashboardi bilan bir xil `compute_member_growth` qoidalari; ma'lumot yo'q bo'lsa "to'planmoqda" ko'rsatiladi, soxta raqam yo'q.
