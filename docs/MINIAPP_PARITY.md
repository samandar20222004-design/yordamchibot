# Bot va Mini App: qaysi funksiya qayerda

Maqsad: foydalanuvchi **botda ham, Mini App'da ham** davom eta oladi. Mini App yoqilgan bo'lsa (`MINIAPP_ENABLED=1`)
bot kerakli ekranlarda «📱 Mini App'da davom etish» tugmasini ko'rsatadi (`miniapp_api/menu.py`); o'chiq bo'lsa
bot hech narsasi o'zgarmaydi. Mini App'dan botga «Botni ochish» va `go_*` (tarif, sozlamalar, yordam, kanallar, taklif) orqali qaytiladi.

| Funksiya | Bot | Mini App | Izoh |
|---|---|---|---|
| Post yozish (qo'lda) | ✅ | ✅ | Bot post yaratish boshida va tasdiq kartasida Mini App tugmasi bor (qoralama o'tadi) |
| AI bilan post | ✅ | ✅ | Bot: AI Studio tugmasida Mini App qatori; limitlar bir xil |
| Rejalashtirish, takrorlash | ✅ | ✅ | Tabiiy til matni ikkalasida; **ovozli** rejalash faqat botda |
| Rejadagi postlarni ko'rish/tahrirlash/bekor qilish | ✅ | ✅ | Mini App'da media almashtirish ham bor |
| Shablonlar | ✅ | ✅ | Bot shablonlar menyusida Mini App qatori |
| Kanallar ro'yxati | ✅ | ✅ (ko'rish) | Kanal **ulash/o'chirish** faqat botda (bot huquqini tekshirish kerak) |
| Kanal tahlili | ✅ | ✅ | |
| Reklama birjasi | ✅ | ✅ | Suhbat ikkalasida; pul botdan o'tmaydi |
| Bildirishnoma / til sozlamalari | ✅ | ✅ | |
| Ko'rinish (rang, fon, tablar) | — | ✅ | Faqat Mini App |
| Tarif ko'rish | ✅ | ✅ | |
| **To'lov** (Stars, karta, Payme), promo | ✅ | ❌ | Ataylab faqat botda (xavfsizlik, chek yuborish) |
| Do'stlarni taklif (referal), bonus | ✅ | ❌ (botga havola) | `go_invite` |
| Autopilot, kontent reja, jamoa | ✅ | ❌ | Ataylab faqat botda |
| Magic post, rasm→post, ovoz→post, post bahosi | ✅ | ❌ | Faqat botda |
| **Super admin**: statistika, reklama, majburiy obuna, birja nazorati | ✅ (admin panel) | ✅ | Mini App'da alohida rejim (quyida) |
| Admin: foydalanuvchi/PRO berish, to'lovlar, promo, broadcast | ✅ | ❌ | Faqat botda |

## Super admin rejimi (Mini App)

* Faqat adminlar uchun: `/me` javobida `is_admin: true` bo'lsa **Men** sahifasida «Super admin rejimi» qatori chiqadi.
  Oddiy foydalanuvchi uchun qator ham, `/admin/*` marshrutlari ham yopiq (server `403 admin_only`; UI ruxsat bermaydi, server hal qiladi).
* Rejim almashadi: «Super admin rejimi» → admin pastki paneli (Umumiy · Reklama · Obuna · Birja · **Oddiy**);
  «Oddiy» oddiy Mini App'ga qaytaradi. Tanlov shu qurilmada eslab qolinadi (`localStorage`, faqat qulaylik).
  Botdagi admin panel tugmasida ham «📱 Mini App'da» (`?tab=admin`) bor.
* Ruxsat botdagi bilan **bir xil** qoida: `rbac_service.ADMIN_ROLES`; birja nazoratida bloklash/chetlatish uchun `manage_users` huquqi
  (finance roli ko'ra oladi, o'zgartira olmaydi).
* Bo'limlar: statistika; reklama (bot javoblari orasida va kanal postlarida: yoqish/oraliq 1–100, matn/tugma, faol/o'chirish);
  majburiy obuna (kanal qo'shish — bot o'sha kanalda admin ekani jonli tekshiriladi, o'chirish); birja nazorati (filtr, e'lonni bloklash/faollashtirish, egasini chetlatish/qaytarish).
* Qoidalar botdagi bilan bir xil: reklama HTML'i `validate_ad_html`, tugma `validate_button_*` (xavfli protokollar rad), har o'zgarish `admin_audit_logs` ga yoziladi,
  yozuv marshrutlari yozuv-limiti ostida.
* Testlar: `tests/miniapp_admin_test.py` (real PostgreSQL), `tests/miniapp_security_audit_test.py`, `miniapp/src/admin.test.tsx`.
