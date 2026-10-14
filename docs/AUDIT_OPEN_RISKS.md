# PostAssist — audit natijasi: ochiq xavflar va qoldirilgan qarorlar

Bu hujjat audit (AUDIT-001…015 + P3) davomida **o'zgartirilmagan**, lekin yo'qotilmasligi kerak bo'lgan xavflar va
sabablarni qayd etadi. "Tuzatildi" bo'limi qisqacha; to'liq tafsilot — commit xabarlari va regression testlar.

## Tuzatilganlar (regression testi bilan)

| ID | Nima | Test |
|---|---|---|
| AUDIT-001 | Mini App CSP `img-src` ga `blob:` (qoralama rasmi) — boshqa direktivalar kengaytirilmagan | `tests/miniapp_static_regression_test.py`; Chromium'da tekshirildi |
| AUDIT-002 | `attempt_count` retry'larda yig'iladi (`DELIVERY_CARRY_ATTEMPTS`, sukut yoqilgan); `retry_post` kalitni o'zgartirganda "kanal tekshiruvi kutilmoqda" (AMBIGUOUS_VERIFY) markeri yangi delivery qatoriga ko'chiriladi | `tests/scheduler_retry_idempotency_test.py` (real PG) |
| AUDIT-003 | Recurring postni restart/stale recovery `posted`ga o'tkazib seriyani o'ldirmaydi (dalil — faqat shu davr delivery'si) | `tests/scheduler_recurring_recovery_test.py` (real PG) |
| AUDIT-004 | Lazy downgrade shartli UPDATE (`expires <= NOW()`): parallel to'lov faol obunani `free`ga tushirmaydi | `tests/subscription_downgrade_race_test.py` (real PG) |
| AUDIT-005 | Stars `SuccessfulPayment` validatsiyadan o'tmasa: PRO berilmaydi, lekin log + adminlarga ogohlantirish + foydalanuvchiga xabar | `tests/stars_rejected_payment_test.py` |
| AUDIT-009 | `end_date`dan keyingi ortiqcha post yo'q; vaqt + `pending` bitta UPDATE | `tests/scheduler_recurring_end_date_test.py` (real PG) |
| AUDIT-010 | `handlers/team.py` matnlari `locales` (`get_text`) orqali uz/ru/en | `tests/team_i18n_test.py` |
| AUDIT-011 | `plan_regenerate`, `ext_rewrite`, `ext_adapt`, `ap_regen`, `ap_refresh`, `ap_pregen:` AI chegarasiga qo'shildi (navigatsiya tugmalari bloklanmaydi) | `tests/rate_limiter_ai_actions_test.py` |
| AUDIT-012 | Repository'ga `user_id` sharti QO'SHILMADI (jamoa editor/admin oqimlarini buzardi); handler RBAC himoyasi testlar bilan qulflandi | `tests/channel_tone_ownership_test.py` |
| AUDIT-013 | Media sarlavhasi 1024 chegarasi server tomonida (`caption_too_long`), frontend/backend/scheduler konstantalari mos | `tests/miniapp_media_lifecycle_test.py`, `tests/miniapp_draft_test.py`, `miniapp/src/caption.test.tsx` |
| AUDIT-014 | Rasm olish uchun bitta `Bot`, ilova to'xtaganda yopiladi | `tests/miniapp_media_lifecycle_test.py` |
| P3 | Istisno matni foydalanuvchiga chiqmaydi; draftdagi reaksiya emoji prefiksi; `miniapp_drafts` 7 kunlik tozalash; Mini App `ERROR_KEYS` | `tests/exception_text_leak_test.py`, `tests/miniapp_drafts_cleanup_test.py`, `miniapp/src/i18n/i18n.test.ts` |

## Ataylab O'ZGARTIRILMAGAN (qaror yoki qo'shimcha dalil kerak)

### AUDIT-002 (qoldiq) — `attempt_count` retry'lar orasida yig'iladi — TUZATILDI (sukut YOQILGAN)
**Oldin:** kalit `(post, kanal, scheduled_time)`; `retry_post` vaqtni o'zgartirgani uchun har retry YANGI delivery qatori va
`attempt_count` 1 ga qaytardi, backoff doim 30 s, `dead_letter` hech qachon ishga tushmadi (cheksiz retry).
**Hozir:** `DELIVERY_CARRY_ATTEMPTS` SUKUT YOQILGAN (`0/false/no/off` o'chiradi). Yangi qator oldingi `failed` qatorning `attempt_count`ini
oladi → backoff 30s/2m/5m/15m o'sadi, 5-urinishda `dead_letter` (post `failed`). `sent` qatordan (recurring keyingi davr) hech narsa
ko'chmaydi. Test: `scheduler_attempt_count_test` (yoqilgan va o'chirilgan rejimlar, real PG).
**Xavf (bilib qabul qilingan):** ~22 daqiqadan uzoq Telegram uzilishida post `failed` bo'ladi va avtomatik qayta yuborilmaydi. Yumshatish
variantlari (kod yozilmagan): tarmoq xatosi uchun backoff 15 daqiqada "plato" qilish, dead_letter postlari uchun admin ogohlantirishi /
qayta navbatga qo'yish buyrug'i. DB sxemasi o'zgarmaydi; qaytarish — `DELIVERY_CARRY_ATTEMPTS=0`.

### AUDIT-003 / 009 (qoldiq) — yuborildi → qayta rejalash oralig'idagi crash — TUZATILDI
**Oldin:** `mark_post_as_sent` (`posted`) va `reschedule_recurring_post` ikki alohida tranzaksiya edi; oraliqda crash bo'lsa recurring
post `posted`da qolib seriya to'xtardi (journal sukutda o'chiq, shuning uchun jarayon ichidagi marker ham yo'qolardi).
**Hozir:** `mark_post_as_sent(..., next_time=...)` 'posted' markerini, delivery `sent` va keyingi davrni (`pending` + yangi vaqt) BITTA
tranzaksiyada yozadi; end_date o'tgan bo'lsa `completed=True` — `completed`. Scheduler (`_apply_sent_marker`) recurring marker uchun shuni
ishlatadi; oddiy postda argument yo'q (xulq o'zgarmagan). Test: `scheduler_crash_window_test` D–D5 (real PG; tuzatishsiz D2 qizil).
**Qolgan eslatma:** `reschedule_recurring_post` va `mark_post_status` ning alohida chaqiruvlari faqat zaxira yo'l (atomik yozuv xato bersa
yoki legacy adapter `TypeError` bersa) sifatida qoldi. Telegram'ga chiqdi → DB commit oralig'i (008/B) bunga kirmaydi va ochiq.
**Ataylab saqlangan xulq:** recurring postda OLDINGI davrdan qolgan `unknown` delivery bo'lsa, 'processing'da qotgan post `unknown`ga
o'tadi (davr bo'yicha toraytirilmagan; `scheduler_recurring_recovery_test` `r4` buni qayd etadi). Bu konservativ: ko'r-ko'rona retry
va dublikat yo'q, lekin admin ko'rib chiqmaguncha seriya to'xtaydi. Toraytirish — egasi qarori.
`calculate_next_time` xatosi jimgina yutiladi (post `posted`da qoladi) — log bor, alert yo'q.

### AUDIT-006 — Telegram Stars refund qayta ishlanmaydi
**Mavjud kod:** `handlers/subscription.py` faqat `pre_checkout` va `successful_payment` ni qayta ishlaydi; `refunded_payment`
(PTB 22.8 da `Message.refunded_payment`, `Bot.refund_star_payment` mavjud) uchun handler yo'q. Payme refund'i bor
(`payme_repository.revoke_subscription`, faqat `PAYME_ALLOW_REFUNDS=1`; muddatsiz enterprise'ga tegmaydi). Stars to'lovi
`payments.telegram_payment_charge_id` bilan UNIQUE (idempotent).
**Variantlar:** (1) faqat kuzatuv — `refunded_payment` kelsa log + admin ogohlantirishi (pul/huquq o'zgarmaydi; eng xavfsiz);
(2) refund'da qolgan muddatni qisqartirish (to'langan davr ichida qaytarilsa PRO'ni darhol yoki `expires -= days` bilan olish);
(3) refund → darhol `free`. Xavf: (2)/(3) da noto'g'ri ID/takroriy refund hodisasi foydalanuvchining boshqa to'lovlari bilan
qo'shilgan muddatni yo'qotadi; idempotentlik uchun `payments` jadvalida `refunded_at` ustuni (migratsiya) kerak.
**Qaror kerak:** refund'da obuna qanday o'zgaradi? Hozir hech narsa o'zgarmaydi.

### AUDIT-007 — karta cheki
**Mavjud kod:** foydalanuvchi tarifni tanlaydi (`user_data['card_plan']` → serverdagi `CARD_TARIFFS`: kunlar/summa serverdan);
chek rasmi adminga ketadi, admin summani ko'z bilan solishtiradi; `_approve_receipt` `FOR UPDATE` + `status='pending'` sharti va
`receipt:<id>` ledger UNIQUE bilan idempotent. Rasm takrori aniqlanmaydi (faqat `file_id`); foydalanuvchiga pending limiti yo'q.
**Variantlar:** (1) `payment_receipts.file_unique_id` + unique indeks (takroriy chekni rad etish; migratsiya, eski qatorlar NULL);
(2) foydalanuvchiga bitta faol pending (DB'siz, `status='pending'` sanash); (3) admin kartasida "bu rasm avval ko'rilgan" ogohlantirishi
(rad etmaydi, xavfi eng past). Xavf (1): bir chek ikki foydalanuvchi uchun qonuniy bo'lishi (oila) — blok soxta rad bo'ladi.
Eslatma: cheklarni faqat `ADMIN_IDS_SET` tasdiqlay oladi (DB-rolli `finance` emas).

### AUDIT-008 — Telegram'ga chiqdi, DB marker yozilmadi (crash oynasi) — QISMAN TUZATILDI
**Oldin:** recovery postni qayta navbatga qo'yardi va keyingi claim kanalni tekshirmay yuborardi → dublikat.
**Hozir:** restart recovery va stale-reclaim delivery'ga `AMBIGUOUS_VERIFY attempt=0` markerini qo'yadi; scheduler qayta yuborishdan OLDIN
kanalni o'qiydi (`channel_posts_history` yoki ochiq kanal `t.me/s/`): post bor → yuborilmaydi (delivery `sent`); yo'q → yuboriladi;
o'qib bo'lmasa → 30 s oralig'ida 3 urinish, so'ng `unknown` (avtomatik yuborish taqiqlanadi, admin ko'radi).
Tekshiruvga vaqt oynasi himoyasi qo'shildi: sanasi ma'lum va 15 daqiqadan eski xabar mos kelmaydi — takrorlanuvchi bir xil matnli
postda kechagi xabar bugungi postni "yuborilgan" deb yo'qotmaydi. Testlar: `scheduler_crash_window_test` B1–B3d (real PG; tuzatishsiz B1, B2, B3c qizil).
**Telegram exactly-once BERMAYDI; dublikat to'liq yo'qolmadi.** Qolgan oynalar: (a) kanal o'qildi, lekin yuborilgan xabar hali ko'rinmadi
(history/`t.me/s` kechikishi) → "yo'q" deb topilib qayta yuboriladi; (b) restart 15 daqiqadan keyin bo'lsa eski xabar oynadan chiqadi;
(c) bot o'z postlarini `channel_posts_history`ga yozmasa va kanal yopiq bo'lsa tekshirib bo'lmaydi.
**Narx:** crash yuborishdan OLDIN bo'lgan bo'lsa ham, yopiq/o'qib bo'lmaydigan kanalda post `unknown` bo'ladi va admin qo'lda qaror qiladi
(dublikat o'rniga "qo'lda tasdiq" tanlandi). `SENT_JOURNAL_PATH` (eski opt-in journal) bunga bog'liq emas.

### AUDIT-015 — `AI_GLOBAL_DAILY_USD=0` va kredit ekspluatatsiyasi
**Mavjud kod/hujjat:** `services/ai/budget.py:184` (`max(0.0, _float_env(...,0.0))`), `CLAUDE.md`, `DEPLOYMENT.md`: `0` = global
chegara O'CHIQ (cheksiz umumiy xarajat); DB'ga tegilmaydi. Yoqilgan va DB xato bersa yangi pullik so'rov rad etiladi (fail-closed).
Foydalanuvchi limitlari (kvota/kredit/tarif byudjeti) global chegaradan mustaqil ishlaydi; in-flight bronlar jarayon bo'yicha.
Kredit manbalari: yangi hisob 5, referral +3, o'tkazma 3–20 (jo'natuvchi ≥3 kunlik; qabul qiluvchi yoshi tekshirilmaydi),
dublikat-himoya faqat ism/username hash.
**Variantlar:** (1) production'da musbat `AI_GLOBAL_DAILY_USD` (kod o'zgarmaydi; tavsiya); (2) yangi hisob kreditlarini N kun/
birinchi to'lovdan keyin ochish; (3) qabul qiluvchi uchun yosh/kunlik qabul cap'i; (4) referral mukofotini birinchi amalga bog'lash
(qisman bor: `register_first_action`). Xavf: (2)–(4) o'sish/konversiyani pasaytiradi — iqtisodiy qaror.

### Vaqt zonalari
Kunlik AI kvota reseti `CURRENT_DATE` (DB sessiya zonasi, odatda UTC → Toshkent 05:00), bonus/streak esa Asia/Tashkent
kuni bilan. Qaysi chegara "to'g'ri" ekani biznes qarori; DB sessiya zonasi kodda o'rnatilmaydi.

### Boshqa ochiq kuzatuvlar
- Rate limiter backend nosoz bo'lsa **fail-open** (bot to'xtamasligi uchun, ataylab); AI xarajati `BudgetGuard` bilan cheklanadi.
  Media/ovoz xabarlari middleware'da cheklanmaydi (handler/AI limiti tomonida).
- `set_channel_tone`/`get_channel_posts_history`/`get_post_by_id` egasiz getter/setter — himoya handler RBAC'ida.
- `handlers/admin.py` sponsor/reklama tugmalarida aniq `PERM_*` tekshiruvi yo'q (faqat admin + callback tekshiruvi).
- Promo-kod brute-force uchun maxsus urinish limiti yo'q (global rate limiter ishlaydi); admin grant kunlariga yuqori chegara yo'q.
- NULL muddatli (muddatsiz) `pro` foydalanuvchi to'lov qilsa muddati chekli bo'lib qoladi (himoya faqat enterprise uchun).
- `process_stars_payment` `sub_` bo'lmagan payload'ni validatsiyasiz qabul qiladi (hozirgi yagona chaqiruvchi validatsiya qiladi — latent).
- Dependency pin: `python-telegram-bot>=`, `sentry-sdk>=`, `sniffio>=` pinlanmagan. Pin uchun production image'dagi aniq
  versiyalar (`pip freeze`) kerak; ko'r-ko'rona yangilanmadi.

## Takrorlangan / keraksiz kod bo'yicha xulosa
- `normalize_button_url` (`handlers/post_enhancer.py`) — `handlers/new_post.py` dagisiga o'ralgan (haqiqiy takror emas).
- `validate_button_url` (`utils/helpers.py`, tuple qaytaradi) va (`utils/security.py`, bool qaytaradi) — ikkalasi bitta
  `url_rejection_reason()` ustida (yagona manba; takror emas).
- 12 ta `*_stale_callback` (ai_post, autopilot, content_calendar_flow, image_post, magic_post, manual_post, post_enhancer,
  post_score, sources, templates, voice_post, `__init__.ai_photo_stale`) bir xil g'oya, lekin modulga xos matn/holat
  tozalash bor — birlashtirish keyingi bosqich (testlar bilan).
- Production'da chaqiruvi topilmagan, faqat testlarda ishlatiladigan 56 ta top-level funksiya/klass (o'chirilmadi —
  public API/test yordamchisi bo'lishi mumkin; o'chirishdan oldin har birini alohida tekshirish kerak):

  - `telegram_bot/database.py::_analytics_performance_index_statements`
  - `telegram_bot/database.py::current_transaction`
  - `telegram_bot/handlers/admin.py::start_set_bot_reply_ad`
  - `telegram_bot/handlers/admin.py::start_set_channel_ad`
  - `telegram_bot/handlers/channels.py::_extract_forward_chat_id`
  - `telegram_bot/handlers/content_plan.py::_get_plan_result_keyboard`
  - `telegram_bot/handlers/error_handler.py::_reset_error_stats`
  - `telegram_bot/handlers/new_post.py::_album_items_count_of`
  - `telegram_bot/handlers/new_post.py::reset_callback_throttle`
  - `telegram_bot/handlers/onboarding.py::build_instant_onboarding_greeting`
  - `telegram_bot/handlers/subscription.py::_get_stars_keyboard`
  - `telegram_bot/handlers/subscription.py::_plan_key_for_days`
  - `telegram_bot/keyboards/callback_data.py::callback_registry_report`
  - `telegram_bot/keyboards/callback_data.py::safe_callback_data`
  - `telegram_bot/keyboards/callback_data.py::validate_callback`
  - `telegram_bot/keyboards/default.py::exact_i18n`
  - `telegram_bot/keyboards/default.py::get_content_creation_keyboard`
  - `telegram_bot/keyboards/inline.py::get_close_keyboard`
  - `telegram_bot/keyboards/inline.py::get_hub_back_keyboard`
  - `telegram_bot/keyboards/inline.py::get_rewards_keyboard`
  - `telegram_bot/keyboards/inline.py::get_sponsors_delete_keyboard`
  - `telegram_bot/keyboards/inline.py::get_stgs_rewards_keyboard`
  - `telegram_bot/keyboards/inline.py::render_pending_list`
  - `telegram_bot/menu_commands.py::menu_commands_parity_report`
  - `telegram_bot/miniapp_api/errors.py::catalog_codes`
  - `telegram_bot/onboarding.py::cache_size`
  - `telegram_bot/onboarding.py::is_new_by_days`
  - `telegram_bot/scheduler.py::clear_channel_flood`
  - `telegram_bot/services/ai/engine/prompts.py::current_date`
  - `telegram_bot/services/ai/fallback.py::reset_default_service`
  - `telegram_bot/services/ai_quota.py::is_temp_error_reason`
  - `telegram_bot/services/cache_backend.py::backend_status`
  - `telegram_bot/services/lifecycle_service.py::completed_count`
  - `telegram_bot/services/lifecycle_service.py::reset_for_tests`
  - `telegram_bot/services/lifecycle_service.py::wait_for_drain`
  - `telegram_bot/services/observability.py::reset_metrics`
  - `telegram_bot/services/rbac_service.py::clear_denial_log`
  - `telegram_bot/services/rbac_service.py::is_legacy_admin`
  - `telegram_bot/services/rbac_service.py::list_admins`
  - `telegram_bot/services/rbac_service.py::permission_for_action`
  - `telegram_bot/services/rbac_service.py::resource_role_permissions`
  - `telegram_bot/translations/content_calendar.py::content_calendar_parity`
  - `telegram_bot/utils/ai_agent.py::audit_post_compat`
  - `telegram_bot/utils/ai_agent.py::generate_post_two_stage`
  - `telegram_bot/utils/ai_agent.py::language_directive`
  - `telegram_bot/utils/channel_reader.py::fetch_latest_channel_posts`
  - `telegram_bot/utils/helpers.py::check_ai_daily_limit`
  - `telegram_bot/utils/helpers.py::format_schedule_line`
  - `telegram_bot/utils/helpers.py::get_channel_ad_next_async`
  - `telegram_bot/utils/helpers.py::inject_auto_ad`
  - `telegram_bot/utils/helpers.py::is_user_ad_free_async`
  - `telegram_bot/utils/helpers.py::reset_user_interaction_count`
  - `telegram_bot/utils/helpers.py::schedule_error_key`
  - `telegram_bot/utils/security.py::normalize_username`
  - `telegram_bot/utils/security.py::safe_limit_html`
  - `telegram_bot/utils/security.py::strip_control_chars`

## Katta modullar (keyingi bosqich, kichik moslikni saqlovchi refaktoring bilan)
`handlers/__init__.py` (~2600 qator: guard + callback fallback + FSM qurish + ro'yxatga olish aralash),
`utils/ai_agent.py` (~4900), `database.py` (~3400), `scheduler.py` (~2400). Taklif: `handlers/__init__.py` dan
`register_*` va `_build_*_states` ni `handlers/registration/` ga, guard'larni `handlers/guards.py` ga ko'chirish
(importlar facade orqali saqlanadi); har qadamdan keyin `tests/run_tests.sh`. Ikki i18n tizimi (`locales/` va
`translations/`) hozircha birlashtirilmadi.
