# 👥 Jamoa va rol

**Qoida:** PRO — bitta odam hamma kanalni boshqaradi. ULTRA — egasi + 2 yordamchi (jami 3 akkaunt) bitta tarifda, narx o'zgarmagan.

## Rollar
- **Men kimman?** (`users.work_mode`): `owner` («kanalni o'zim yuritaman») yoki `helper` («yordamchiman»). Mini App birinchi ochilishda bir marta so'raydi,
  keyin Men → Jamoa va rol (botda Sozlamalar → Jamoa va rol, `/team`). Super admin uchun shu ro'yxatda 3-variant — «Super admin» (admin rejimi).
- **Kanal bo'yicha yordamchi roli** (`channel_members`): `editor` (post yozadi/tahrirlaydi/o'chiradi), `scheduler` (post qo'shadi va vaqtini o'zgartiradi, matnga tegmaydi),
  `analyst` (faqat ko'radi). Amallar jadvali — `services/team_invites.ROLE_ACTIONS`.

## Taklif
Egasi kanal + rol tanlaydi → bir martalik havola `https://t.me/<bot>?start=team_<token>` (7 kun). Token bazada FAQAT sha256 hash (`team_invites`).
Yordamchi havolani botda ochadi → `/start` taklifni qabul qiladi (`handlers/team_ui.accept_team_invite`), egasiga xabar boradi. Egasi bekor qiladi / a'zoni olib tashlaydi / rolni o'zgartiradi.

## O'rindiqlar
O'rindiq = egasining kanallaridagi NOYOB yordamchi (bir kishi ikki kanalda — bitta o'rindiq). Limit: `TIER_LIMITS[...]['team_seats']`
(`ULTRA_TEAM_SEATS`=2, `ENTERPRISE_TEAM_SEATS`=5, PRO/FREE=0). Kutilayotgan takliflar ham o'rindiqni band qiladi. Egasi ULTRA'dan tushsa, a'zolar o'chmaydi —
faqat ENG ESKI `team_seats` tasi ishlaydi (qolganlarida «vaqtincha yopiq»); ULTRA qaytsa hammasi tiklanadi.

## Ish joyi (Mini App)
Yordamchi «Ishlash» ni bossa mijoz har so'rovga `X-Workspace: <egasi_id>` qo'shadi (`miniapp_api/workspace.py`). Server: o'rindiq tekshiriladi, `user_id` egasiga almashadi
(egasining tarifi/navbati/kvotasi), repozitoriy SQL'i FAQAT ruxsat etilgan kanallarni ko'radi, amal rolga mos bo'lishi shart (aks holda `403 workspace_denied`).
Faqat belgilangan marshrutlar hisobga oladi: kanallar, rejalar, post tafsiloti/media, post yaratish/tahrirlash/o'chirish. Boshqalari (qoralama, shablon, sozlama, AI) yordamchining o'zi nomidan.
Ish joyida `use_draft` taqiqlangan (egasining qoralamasi o'qilmaydi/o'chirilmaydi). `/me`, `/team` sarlavhani e'tiborsiz qoldiradi.

## Cheklovlar (ataylab)
- Yordamchi botdan (chatdan) post yozmaydi — ish joyi Mini App'da; botda faqat boshqaruv (taklif, a'zolar, rol).
- Ish joyida media bilan yangi post yaratish yo'q (qoralama egasiniki); matnli post yaratib, keyin tahrirlashda media qo'shiladi.
- Yordamchining AI so'rovlari o'z kvotasidan hisoblanadi.

Testlar: `tests/team_invites_test.py` (real PG), `tests/miniapp_team_test.py` (real PG), `tests/team_ui_test.py`, `miniapp/src/team.test.tsx`.
