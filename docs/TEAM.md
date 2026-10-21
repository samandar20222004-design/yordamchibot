# 👥 Jamoa va rol

**Qoida:** PRO — bitta odam hamma kanalni boshqaradi. ULTRA — egasi + 2 yordamchi (jami 3 akkaunt) bitta tarifda, narx o'zgarmagan.

## Rol va ruxsatlar
- **Men kimman?** (`users.work_mode`: `owner` / `helper`) FAQAT sozlamada tanlanadi (Men → Jamoa va rol; botda Sozlamalar → Jamoa va rol, `/team`) — ochilganda hech qachon so'ralmaydi.
  Super admin uchun shu ro'yxatda 3-variant — «Super admin» (admin rejimi). Yordamchi bo'lib qo'shilgan odam ish joyiga o'zi kiradi (o'z kanali bo'lmasa yoki rejimi «yordamchi» bo'lsa).
- **Ruxsatlar** (egasi HAR yordamchiga alohida beradi; `channel_members.perms`): `create` (post yaratish/rejalash, media bilan), `edit` (matn/tugma/media tahriri),
  `reschedule` (vaqt va takror), `delete` (bekor qilish), `send_now` (darhol yuborish), `analytics` (statistika), `ai` (AI, EGASI kvotasidan). «Ko'rish» har doim bor.
  Tayyor shablonlar: **Hammasi** (taklifda standart — kengroq), Muharrir, Rejalovchi, Tahlilchi, Faqat ko'rish; keyin istalgan katakcha o'zgartiriladi. Eski (perms NULL) a'zolar rol shablonidan oladi.
  `channel_members.role` — ruxsatlardan hosil bo'lgan belgi (RBAC moslik uchun).
- **Limit egasidan:** yordamchi egasining tarifi ichida ishlaydi. Post egasi nomidan (`scheduled_posts.user_id` = egasi) saqlanadi, navbat limiti, AI kvotasi/krediti egasiniki;
  yordamchining o'z limiti sarflanmaydi (faqat so'rov tezligi cheklovi yordamchiga hisoblanadi).

## Taklif
Egasi bir yoki bir nechta kanal + ruxsatlar tanlaydi → bir martalik havola `https://t.me/<bot>?start=team_<token>` (7 kun). Token bazada FAQAT sha256 hash (`team_invites`).
Yordamchi havolani botda ochadi → `/start` taklifni qabul qiladi (`handlers/team_ui.accept_team_invite`), egasiga xabar boradi. Egasi bekor qiladi / a'zoni olib tashlaydi / rolni o'zgartiradi.

## O'rindiqlar
O'rindiq = egasining kanallaridagi NOYOB yordamchi (bir kishi ikki kanalda — bitta o'rindiq). Limit: `TIER_LIMITS[...]['team_seats']`
(`ULTRA_TEAM_SEATS`=2, `ENTERPRISE_TEAM_SEATS`=5, PRO/FREE=0). Kutilayotgan takliflar ham o'rindiqni band qiladi. Egasi ULTRA'dan tushsa, a'zolar o'chmaydi —
faqat ENG ESKI `team_seats` tasi ishlaydi (qolganlarida «vaqtincha yopiq»); ULTRA qaytsa hammasi tiklanadi.

## Ish joyi (Mini App)
Yordamchi «Ishlash» ni bossa (yoki o'zi kirsa) mijoz har so'rovga `X-Workspace: <egasi_id>` qo'shadi (`miniapp_api/workspace.py`). Server: o'rindiq tekshiriladi, `user_id` egasiga almashadi
(egasining tarifi/navbati/kvotasi), repozitoriy SQL'i FAQAT ruxsat etilgan kanallarni ko'radi, har amal ruxsatlar bilan solishtiriladi (aks holda `403 workspace_denied`).
Hisobga oladigan marshrutlar: kanallar, rejalar/kalendar, post tafsiloti/media, post yaratish/tahrirlash/o'chirish, statistika, AI (`/ai/generate`, `/schedule/parse`). Boshqalari (shablon, sozlama) yordamchining o'zi nomidan.
**Media:** qoralama (`miniapp_drafts`) yordamchining O'ZIDA qoladi, post esa egasi nomidan yaratiladi (`create_post(draft_user=...)`); egasining qoralamasiga tegilmaydi.
Mediani mavjud postga biriktirishda fayl yordamchining chatidan `file_id` oladi (egasiga yuborilmaydi).

## Bot
Media/matn bilan post hamisha botda boshlanadi. Yordamchida o'z kanali yo'q bo'lsa, «📝 Post qilish» post (media/albom) qoralamasini saqlaydi va Mini App'ni egasi ish joyida ochadi
(`manual_post._helper_handoff`; «kanal ulang» demaydi). Botda faqat boshqaruv: taklif (kanal + shablon), a'zoning ruxsat katakchalari, olib tashlash.

## Cheklovlar (ataylab)
- Yordamchi botda to'liq post oqimini egasi nomidan yurgizmaydi — rejalash/tahrir Mini App'da (bot → qoralama → Mini App).
- Bir taklifda 10 tagacha kanal; ruxsatlar taklif ichida hamma kanal uchun bir xil (keyin Mini App'da yordamchi kartasidan o'zgartiriladi).

Testlar: `tests/team_invites_test.py` (real PG), `tests/miniapp_team_test.py` (real PG), `tests/team_ui_test.py`, `miniapp/src/team.test.tsx`.
