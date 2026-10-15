# Bonus, tariflar va taklif (referal) — tavsiya

Holat (kodda): ball/kredit (`credits_ledger`: kunlik bonus, faollik bonusi, promo, o'tkazma), referal **harakatga asoslangan** (do'st BIRINCHI
postini yaratgach, `services/referral_service.py`: self-referral, takror profil, noma'lum referrer himoyalari), PRO: 1 oy 19 000 / 3 oy 45 000 / 1 yil
140 000 so'm (+ Stars). Quyidagi — TAVSIYA; narxlar va foizlarni egasi belgilaydi, hech narsa kodga kiritilmagan.

## 1. Bonus — nimani qoldirish
* **Qoldiring:** kunlik/faollik bonusi (odat shakllantiradi), promo-kod. **Soddalashtiring:** ballni FAQAT AI so'rovlari va kichik «sovg'a»lar
  uchun ishlating; PRO'ni ballga sotib olishga ruxsat BERMANG (ballni qo'lga olish arzon — PRO daromadini yeydi).
* Bonus «cheksiz» bo'lmasin: kunlik/oylik yuqori chegara (`credits_ledger` dan hisoblanadi) — farming iqtisodini yopadi.

## 2. PRO'ni ko'paytirish (yo'nalish)
Hozir bitta PRO ham «yangi boshlovchi», ham «agentlik» uchun. Taklif — 3 pog'ona, farq FOYDALANISH hajmida (bor funksiyani yopib qo'ymasdan):

| Pog'ona | Kim uchun | Farqlovchi |
| --- | --- | --- |
| Free | sinab ko'ruvchi | 3 kanal, 5 AI/kun, 5 navbat, ovozli rejalash 1 marta, bot belgisi |
| PRO | bitta muallif/kichik kanallar | belgisiz, cheksiz navbat, AI kengroq, ovozli rejalash kunlik limit bilan, to'liq analitika |
| PRO Business | agentlik/jamoa | ko'p kanal, jamoa a'zolari (rollar), katta AI kvota, ustuvor yordam, RSS/Autopilot kengroq |
Avval Free/PRO farqini aniq o'lchang (kim qaysi limitga urilmoqda — `ai_usage_events`, navbat/kanal limiti loglari), keyin yuqori pog'onani
shu talab asosida ochiladigan qiling. Narxni «oy/3 oy/yil» chegirmasi bilan saqlang (`plan_discount_percent` hisoblaydi).

## 3. Taklif etilganlar evaziga chegirma
Tavsiya: **taklif qilingan odam to'lagandagina** mukofot (ro'yxatdan o'tgani uchun emas) — soxta hisob foydasiz bo'ladi.
* Taklif qilgan: do'sti **birinchi to'lovini** qilsa keyingi to'lovga chegirma yoki bepul kunlar. Pog'onali: 1 to'lagan do'st = 10%, 3 = 25%, 5+ = 40%
  (yuqori chegara 50%, promo-kod bilan qo'shilmaydi). Bepul KUN berish chegirmadan afzal: pul oqimiga ta'sir qilmaydi, oson hisoblanadi.
* Taklif qilingan do'st: birinchi oyga kichik chegirma (10–15%) — konversiyani oshiradi.
* «Faol do'st» ta'rifi: kanal ulagan + kamida bitta post yuborgan + 7 kun o'tgan (hozirgi «birinchi post» shartini kuchaytiradi).
* Himoya: bir to'lov usuli/karta ikkita hisobda ishlatilsa — chegirma berilmaydi; refund bo'lsa (Stars/Payme/chek) chegirma ham bekor
  (yangi `refund_stars_payment` va Payme `revoke_subscription` kancalari shu uchun tayyor); mukofot `credits_ledger`/`payments` kabi
  alohida audit jadvaliga yozilsin (kim, qaysi to'lov, qancha) — «berildi, lekin iz yo'q» bo'lmasin.
* Texnik tartib (alohida PR): 1) `referral_rewards` jadvali (referrer, referee, payment_id, kind, value, status), 2) to'lov tasdiqlanganda
  (Stars/karta/Payme) atomik hisoblash, 3) keyingi to'lov narxida qo'llash (Stars invoice, karta tarifi, Payme order), 4) Mini App profilida
  «Taklif: N ta to'lagan do'st, chegirma X%» ko'rinishi.

## 4. Tavsiya etilgan tartib
1. Bonus chegaralari va «ball PRO'ga aylanmaydi» qoidasi. 2. Free/PRO limitlarini o'lchash (1–2 hafta). 3. Referal chegirma (yuqoridagi tartib).
4. Faqat shundan keyin yangi PRO pog'onasi. Qaror egasida — qaysi biri birinchi bo'lishini ayting, shuni qilaman.
