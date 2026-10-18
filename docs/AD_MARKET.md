# 💰 Reklama birjasi (kanallar o'rtasida reklama)

Bot ichidagi bozor: kanal egasi kanalini qo'yadi, reklama beruvchi katalogdan kanalni **bot hisoblagan
ko'rsatkichlar** bilan ko'radi, so'rov yozadi va ikkalasi bot orqali kelishadi. Kirish: `/market`,
kanal panelidagi «💰 Reklama birjasi» tugmasi, birinchi kanal ulangandan keyingi taklif.

## Foydalanuvchi oqimi
- **Reklama beruvchi:** Katalog → mavzu → ro'yxat (obunachi / narx / faollik bo'yicha saralash, 5 tadan sahifa) →
  kanal kartasi → «✉️ Reklama so'rovi» (10–1000 belgi) → egasiga bot orqali boradi.
- **Kanal egasi:** «📢 Kanal qo'yish» → kanal → mavzu → narx (`50000`, `50k`, `1.5 mln`, «kelishiladi») → tavsif →
  e'lon. Boshqaruv: narx / tavsif / mavzu, to'xtatish, yangilash, olib tashlash; ko'rishlar va so'rovlar soni ko'rinadi.
- **Yozishma:** xabarlar bot orqali o'tadi (🔒 profil yashirin). Har bir tomon «👤 Kontakt berish» ni bossagina
  `tg://user?id=` havolasi ikkinchi tomonga yuboriladi. Suhbatni yopish, egasi uchun ⛔ bloklash bor.

## Ishonchlilik (halollik)
- E'lon qilishda bot **jonli** tekshiradi: kanal ochiq (username bor), bot admin, foydalanuvchi ham admin,
  `channels.user_id` egasi. Yopiq kanal qabul qilinmaydi.
- Obunachi — kunlik snapshot (`channel_member_counts`) yoki e'lon paytidagi jonli son; o'rtacha ko'rish — FAQAT
  `channel_posts_history.views` ning NULL bo'lmagan so'nggi 10 posti (kamida 3 ta, aks holda «ma'lumot yetarli emas»);
  ER = o'rtacha ko'rish / obunachi; o'sish — `services/channels/growth.py`. Soxta 0 yoki taxmin YO'Q.
  Kartada ko'rsatkichlar yangilangan vaqti va «faqat bot ko'rgan postlar bo'yicha» izohi bor.
- Telegram Bot API post ko'rishlarini bermaydi, shuning uchun ko'rish/ER faqat bot orqali yuborilgan yoki bot
  yig'gan postlar bo'yicha. Katalogdagi nishonlar («📈 O'smoqda», «🔥 Faol auditoriya», «⚡ Muntazam postlar») faqat shu faktlardan.

## Himoya
| Qoida | Joyi |
|---|---|
| Egalik/IDOR: e'lon faqat `channels.user_id` egasiniki; yozuvchi funksiyalar `owner_id` ni tekshiradi | `ad_market_repository` |
| Katalogda faqat faol e'lon + faol kanal + egasi o'zgarmagan (kanal o'chirilsa e'lon ko'rinmaydi) | `_LIVE_JOIN` |
| Kuniga 5 tadan ko'p yangi so'rov yo'q (advisory-lock, parallel ham) | `create_inquiry` |
| Bitta ochiq so'rov (listing × reklama beruvchi), o'z kanaliga yozib bo'lmaydi | unique indeks + tekshiruv |
| Suhbatda 40 xabar chegarasi; faqat ikki ishtirokchi o'qiydi/yozadi | `add_message`, `get_inquiry` |
| Egasi reklama beruvchini bloklaydi (ochiq so'rovlari yopiladi) | `block_advertiser` |
| 3 ta turli shikoyat → e'lon avtomatik `blocked`, adminlarga xabar; egasi o'zi qayta yoqa olmaydi | `report_listing` |
| Admin: `/market_ban <id>`, `/market_unban <id>` (shikoyatlar tozalanadi) | `market_admin_command` |
| Foydalanuvchi ma'lumotlarini o'chirish e'lon, so'rov, xabar, blok, shikoyatlarni ham o'chiradi | `delete_user_market_data` |
| Hamma matn HTML-escape; callback ≤ 64 bayt; `mk:` fail-closed reyestrda | `callback_data.py` |

## Pul
Pul bot orqali O'TMAYDI (kelishuv tomonlar o'rtasida; escrow yo'q). Kartada va qo'llanmada «oldindan to'lovdan
ehtiyot bo'ling» ogohlantirishi bor. Keyingi bosqich: escrow / to'lov kafolati.

## Mini App
«Birja» tabi (5-tab): katalog (mavzu chiplari, saralash, sahifalash), kanal kartasi (ko'rsatkichlar, so'rov, shikoyat), «Kanalim» (e'lon qilish, narx/tavsif/mavzu, to'xtatish, yangilash, olib tashlash), «Suhbatlar» (yozishma, yopish, bloklash). Bosh sahifada banner; `?tab=market`; bot birja ekranida «📱 Mini App» tugmasi (yoqilgan bo'lsa). API — `miniapp_api/market.py`, `miniapp/README.md`; test — `tests/miniapp_market_test.py`, `miniapp/src/market.test.tsx`. Kontakt ulashish faqat botda (Mini App'da yo'q).

## Kod
- Sxema: `telegram_bot/schema.sql` oxiri (`ad_market_listings`, `_inquiries`, `_messages`, `_reports`, `_blocks`).
- `repositories/ad_market_repository.py` — barcha DB qoidalari; `services/ad_market.py` — narx tahlili, ko'rsatkichlar (sof).
- `handlers/ad_market.py` — ekranlar va `mk:` callback marshrutlash; matn kiritish `context.user_data["mk_input"]`
  (10 daqiqa) + `MarketInputFilter` (faqat faol holatdagi foydalanuvchi matni; `/cancel` tozalaydi).
- `translations/ad_market.py` — uz/ru/en (paritet testda). Tugma yorlig'i ≤ 18 belgi.
- Test: `tests/ad_market_test.py` (real PG: egalik, katalog, limitlar, parallel, blok, shikoyat, bot oqimi).

## Hali qilinmagan (keyingi bosqich)
- Escrow/kafolatli to'lov, buyurtma holatlari (kelishildi / bajarildi / baho va sharh).
- Kunlik snapshotni e'lonlar uchun majburiy qilish va ko'rsatkichlarni fon vazifasida yangilash (hozir kartani ochganda ≥6 soat eskirgan bo'lsa bazadan qayta hisoblanadi).
- Haftalik hisobot kanal egasiga («kartangiz N marta ko'rildi, M so'rov») — o'sish uchun foydali.
