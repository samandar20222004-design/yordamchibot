# 🧭 UX NAVIGATION AUDIT — 3 QATORLI 6 TUGMA STANDARTI + CALLBACK REGISTRY

> **Holat:** ✅ PASS — `tests/ui_ux_and_navigation_standards_test.py`
> (FAZA 17/18/19/26), `tests/ux_v2_main_menu_test.py`,
> `tests/final_acceptance_suite_test.py` (TEST A..AG) — barchasi yashil,
> **BASH EXIT CODE: 0**.

Audit tugma parki (reply + inline), navigatsiya semantikasi va callback
xavfsizligining yakuniy holatini qayd etadi.

---

## 1. Asosiy Reply menyu — QAT'IY 3 qator / 6 tugma

Uchala tilda (uz/ru/en) aynan:

```
[✨ Kontent yaratish]  [📢 Kanallarim]
[📅 Rejalashtirilgan]  [📊 Statistika]
[💎 PRO]               [⚙️ Sozlamalar]
```

- **4-qator TAQIQLANADI** — admin variantida faqat `[⚙️ Admin Panel]`
  qatori qo'shiladi (va faqat ADMIN_IDS uchun RO'YXATdan ko'rinadi —
  oddiy foydalanuvchida butunlay yo'q).
- Eski tarqoq tugmalar jarayondan chiqarilgan, routing'da alias sifatida
  (backward compatibility) ishlaydi — eski chat xabarlarida qolgan
  tugmalar crash bermaydi.
- 8-sprint (FAZA 23/25) o'zgarishlari menyuga TEGMAGAN — standart
  o'zgarmagan va test yashil.

## 2. Kanonik navigatsiya (FAZA 17)

- `◀️/⬅️ Orqaga` = parent oyna; `❌ Bekor qilish` = FSM to'xtatish
  (kontekst tozalanib **O'SHA BO'LIM BOSHIGA** qaytish); `🏠/🔙 Asosiy
  menyu` = bosh menyu; `❌ Yopish` = vaqtinchalik xabarni yopish.
- Butun klaviatura parki bo'yicha **bir xil vazifali IKKITA tugma YO'Q**
  (`find_nav_conflicts == 0`); yorliq↔callback semantikasi mosligi
  testlanadi.
- FAZA 18: `get_cabinet_inline_keyboard` / `get_settings_hub_keyboard`
  dublikatlari KANONIK `get_settings_profile_keyboard` ga yo'naltirilgan
  (7 tugma, oxirgi qator `[❌ Yopish]`, callback'lar tilga bog'liq emas).

## 3. Callback Registry (FAZA 19) — `keyboards/callback_data.py`

- Barcha klaviatura callback'lari **yagona registry**da; kanonik prefiks
  yoki aniq token bo'yicha tekshiriladi.
- Noma'lum/soxta (tampered) callback → **FAIL-CLOSED** rad:
  `show_alert=True`, xabar o'chirilmaydi/tahrirlanmaydi,
  `callback_tampering` logiga yoziladi.
- 64-bayt Telegram limiti buzilgan qiymat rad etiladi
  (`callback_byte_len` guard).
- Namespace ostidagi soxta payload — handler darajasidagi **oq
  ro'yxat/RBAC ikkinchi qatlami** bilan zararsizlantiriladi (masalan,
  `adm_*` faqat adminlar uchun; `rc_ok:` payload buzilgan bo'lsa rad).
- FAZA 23 kengaytmasi: registry'dan o'tgan qonuniy `p_*` callback'larda
  ham **post ID egaligi serverda QAYTA tekshiriladi**
  (`pending._callback_owns_post`) — "registry bor" degani "mulk bor"
  degani emas (ikki mustaqil qatlam).

## 4. i18n 100% paritet (FAZA 26)

- `handlers/admin.py` va `handlers/channels.py` da foydalanuvchi
  ko'radigan qotirilgan o'zbekcha satrlar YO'Q (AST-skaner).
- `translations/admin_panel.py` (216 kalit) UZ↔RU↔EN `in_sync=True`;
  `channels_queue` / `settings_stats` / asosiy lug'at pariteti saqlangan;
  RBAC rad javoblari `adm:` i18n markeri orqali.
- FAZA 23 qo'shimchasi: `pend_btn_unsafe` kaliti **uz + ru + en
  (overlay)** da qo'shildi — paritet testi yashil.
- Regressiya: uz chiqishlari migratsiyagacha bo'lgan oltin fragmentlar
  bilan bir xil (dashboard/stats/dbcache/posts/sponsors);
  `CHANNEL_LIMIT_MSG` / `PRO_UPGRADE_KEYBOARD` / `parse_channel_target`
  orqaga mosligi 3 tilda.

## 5. Dead-end va tutashlik audit

- Aniqlashtirish wizard'i (`aip_cancel`) va Magic Post uslub menyusi
  (`mp_cancel`) da `[❌ Bekor qilish]` — foydalanuvchi hech qayerda
  "qotmaydi".
- Navigatsiya stacki: Kontent → AI Yordamchi → Orqaga → Kontent
  yaratish submenyusi (asosiy menyuga sakramaydi); Kanallarim → Kanal →
  Orqaga → ro'yxat; Sozlamalar → Vositalar → Orqaga → Sozlamalar.
- Throttle/rate-limit holatlarida tugmalar "yuklanmoqda" qolmaydi —
  `sys_wait_short` lokalizatsiyalangan toast (`main.py`).
- FAZA 25: handler timeout bo'lsa ham foydalanuvchi `_answer_timeout`
  lokalizatsiyalangan javobini oladi (UI muzlamaydi).

## 6. Test xulosasi

| Suite | Natija |
|---|---|
| `tests/ui_ux_and_navigation_standards_test.py` (1–6 band: menyu, navigatsiya, registry, i18n, regressiya) | ✅ PASS (175) |
| `tests/ux_v2_main_menu_test.py` (6 tugma, RBAC, onboarding) | ✅ PASS |
| `tests/final_acceptance_suite_test.py` (TEST A..AG — 33 tekshiruv) | ✅ PASS |
| `tests/fsm_navigation_safety_test.py` | ✅ PASS |
| FAZA 23/25: `pend_btn_unsafe` i18n, `_answer_timeout` | ✅ PASS (126 ichida) |

**XULOSA: navigatsiya va tugma parki standarti — PASS ✅**
