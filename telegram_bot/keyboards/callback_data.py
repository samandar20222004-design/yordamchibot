"""Inline tugmalar uchun ``callback_data`` xavfsizligi (Telegram 64-bayt limiti).

Telegram Bot API `InlineKeyboardButton.callback_data` uchun **1..64 bayt**
(UTF-8) chegarasini belgilaydi. Chegaradan oshgan qiymat butun klaviaturani
``BadRequest: BUTTON_DATA_INVALID`` bilan rad ettiradi — ya'ni bitta uzun
tugma tufayli FOYDALANUVCHI XABARNI UMUMAN OLMAYDI.

Shu sababli barcha dinamik (kanal id, post id, emoji, action kabi qiymatlar
qo'shiladigan) callback'lar shu moduldagi :func:`cb` orqali quriladi:

    >>> cb(CB_CHANNEL_DELETE, -1001234567890)
    'ch_del:-1001234567890'

Kafolatlar:
  * natija hech qachon 64 baytdan oshmaydi (kerak bo'lsa oxirgi bo'lak
    UTF-8 chegaralarini buzmasdan qisqartiriladi va WARNING log yoziladi);
  * natija hech qachon bo'sh bo'lmaydi (Telegram bo'sh qiymatni ham rad etadi);
  * prefikslar qisqa va kanonik — pastdagi ``CB_*`` konstantalari yagona
    manba (single source of truth) bo'lib, handler ``pattern`` lari ham
    shulardan quriladi.
"""

import logging

logger = logging.getLogger(__name__)

# Telegram Bot API qat'iy chegarasi (bayt, UTF-8).
CALLBACK_DATA_MAX_BYTES = 64

# Dinamik qiymat qo'shiladigan callback'lar uchun prefiks byudjeti: prefiks
# o'zi 16 baytdan oshmasligi kerak — qolgan >=48 bayt payload (id/emoji) uchun.
CALLBACK_PREFIX_MAX_BYTES = 16

# ---------------------------------------------------------------------------
# Kanonik QISQA prefikslar
# ---------------------------------------------------------------------------
# Eslatma: `react:` prefiksi ATAYLAB o'zgartirilmagan — u kanallarga ALLAQACHON
# yuborilgan postlar tugmalarida yashaydi; nomini o'zgartirish eski postlardagi
# reaksiya tugmalarini o'lik qilib qo'yadi. U allaqachon 6 bayt — xavfsiz.

# Kanal boshqaruvi (avval: remove_channel: / tone_menu:)
CB_CHANNEL_DELETE = "ch_del:"
CB_CHANNEL_SETTINGS = "ch_set:"

# Rejalashtirilgan post kartochkasi (avval: edit_time: / edit_content: / ...)
CB_POST_TIME = "p_time:"
CB_POST_EDIT = "p_edit:"
CB_POST_BTN = "p_btn:"
CB_POST_REACT = "p_react:"
CB_POST_CANCEL = "p_cancel:"
# Navbatdagi postni ko'rish. Bu yerda ATAYLAB "p_view:" emas, mavjud "qview:"
# saqlangan: u allaqachon 6 bayt (p_view: dan ham qisqa) va navbat modulining
# qolgan callback'lari (qdel:/qpush:/qpage:) bilan bitta nom fazosida turadi.
CB_POST_VIEW = "qview:"

# Homiy kanallar (avval: del_sponsor:)
CB_SPONSOR_DELETE = "sp_del:"

# To'lov cheki moderatsiyasi (avval: receipt_appr: / receipt_rej:)
CB_RECEIPT_APPROVE = "rc_ok:"
CB_RECEIPT_REJECT = "rc_no:"

# Rasm moderatsiyasi (avval: check_photo:app: / check_photo:rej:)
CB_PHOTO_APPROVE = "cph:a:"
CB_PHOTO_REJECT = "cph:r:"

# 🖼 Rasm → post: 3 uslub variantidan birini tanlash (formal/friendly/concise)
CB_PHOTO_VARIANT = "photo_v:"

# 🎙 Kanal ovozi tahlili (AI) — kanal profil tugmasi
CB_CHANNEL_VOICE = "ch_voice:"

# ---------------------------------------------------------------------------
# 📢 KANALLARIM — kanal boshqaruv ekrani (PostAssist V2, 4-mikro qadam)
# ---------------------------------------------------------------------------
# Kanal ro'yxatidan muayyan kanal tanlanganda ochiladigan submenu. Ichki
# amallar ASOSIY MENYUGA CHIQIB KETMAYDI: har bir tugma shu kanal konteksti
# (channel_id payload) bilan o'z ekranini ochadi va [◀️ Orqaga] ro'yxatga
# qaytaradi.
CB_CHANNEL_OPEN = "ch_op:"        # kanalni tanlash → boshqaruv ekrani
CB_CHANNEL_NEW_POST = "ch_np:"    # ➕ Post yaratish (shu kanal uchun)
CB_CHANNEL_SCHEDULED = "ch_sch:"  # 📅 Rejalashtirilgan (shu kanal bo'yicha)
CB_CHANNEL_STATS = "ch_st:"       # 📊 Statistika (shu kanal bo'yicha)
# 🧠 PHASE B — Channel Intelligence: kanal uslubiy profili va optimal vaqt
CB_CHANNEL_DNA = "ch_dna:"        # 🧠 Kanal DNA (uslubiy profil kartochkasi)
CB_CHANNEL_BEST_TIME = "ch_btm:"  # ⏰ Eng yaxshi vaqt (post statistikasi)
# PHASE E — haftalik Channel Advisor kartasi
CB_CHANNEL_ADVICE = "ch_adv:"
# PHASE E — approval card callbacks (post id is appended with ``cb``).
CB_TEAM_APPROVE = "team_ok:"
CB_TEAM_EDIT = "team_edit:"
CB_TEAM_REJECT = "team_no:"
# 🚀 PHASE C — 7 kunlik AI avtopilot va 📋 post shablonlari (kanal kontekstida)
CB_CHANNEL_AUTOPILOT = "ch_ap:"   # 🚀 AI Avtopilot (7 kunlik reja)
CB_CHANNEL_TEMPLATES = "ch_tpl:"  # 📋 Shablonlar (post shablonlari menyusi)
# 📥 PHASE D (2/2) — kontent manbalari HUB'i (kanal kontekstida)
CB_CHANNEL_SOURCES = "ch_src:"    # 📥 Kontent manbalari (URL→post, RSS, recycle)
CB_CHANNEL_BACK = "ch_back"       # ◀️ Orqaga → kanallar ro'yxati (payload'siz)

# 📥 PHASE D — kontent manbalari (11, 12, 13-bandlar): URL→post, RSS, recycle.
CB_SOURCE_URL = "src_url:"        # 🔗 Havoladan post (URL → post oqimi)
CB_SOURCE_RSS = "src_rss:"        # 📡 RSS/ATOM oqimi (manbalar ro'yxati)
CB_SOURCE_RECYCLE = "src_rec:"    # ♻️ Eski postni yangilash (content recycle)
CB_SOURCE_DRAFTS = "src_drf:"     # 🗂 Tasdiqlash kutayotgan qoralamalar
# Qoralama kartochkasi: src_draft:<action>:<draft_id> (dynamic payload).
CB_SOURCE_DRAFT = "src_draft:"
CB_SOURCE_BACK = "src_back"       # ◀️ Manbalar menyusiga qaytish (payload'siz)
CB_SOURCE_CANCEL = "src_cancel"   # ❌ Bekor qilish (payload'siz)
# 📥 PHASE D (2/2) — ichki amallar (hammasi 16 bayt byudjetida).
CB_SOURCE_FORMAT = "src_fmt:"     # 4 formatdan birini tanlash (news/short/...)
CB_SOURCE_ACTION = "src_act:"     # preview amallari: sched | now | regen
CB_SOURCE_RSS_ADD = "src_add"     # ➕ Yangi manba qo'shish (payload'siz)
CB_SOURCE_RSS_CHECK = "src_chk:"  # 🔄 Hoziroq tekshirish (payload: source id)
CB_SOURCE_RSS_TOGGLE = "src_tgl:" # ▶️/⏸ Manbani yoqish/to'xtatish (source id)
CB_SOURCE_RSS_AUTO = "src_auto:"  # 🤖 Avtopublish (payload: source id)
CB_SOURCE_RSS_DEL = "src_del:"    # 🗑 Manbani o'chirish (payload: source id)
CB_SOURCE_REC_PICK = "src_rp:"    # ♻️ Recycle nomzodi (payload: ro'yxat indeksi)

# ---------------------------------------------------------------------------
# 📅 REJALASHTIRILGAN — post kartochkasi amallari (PostAssist V2, 4-qadam)
# ---------------------------------------------------------------------------
# Ro'yxatdagi har bir post ostida [✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish]
# [🗑 O'chirish]. Tahrirlash/vaqt amallari mavjud, sinovdan o'tgan
# ``p_edit:`` / ``p_time:`` oqimlarini QAYTA ISHLATADI (yangi FSM yaratilmaydi),
# o'chirish esa navbat modulining ``qdel:`` amali bilan bir xil (alias).
CB_SCHED_EDIT = CB_POST_EDIT      # ✏️ Tahrirlash  → pending.edit_post_content_start
CB_SCHED_TIME = CB_POST_TIME      # ⏰ Vaqtni o'zgartirish → pending.edit_post_time_start
CB_SCHED_DELETE = "qdel:"         # 🗑 O'chirish (navbat moduli bilan bitta amal)
# 🔗 Tugma/Reaksiya tanlagichi (PostAssist V2 · 2-qadam — B1 yagona ro'yxati):
# yagona «📅 Rejalashtirilgan» ekranida har bir post ostida 4-amal sifatida
# turadi va mavjud ``p_btn:`` / ``p_react:`` oqimlariga yo'naltiradi.
CB_SCHED_BTN_REACT = "sched_br:"  # 9 bayt (16 bayt byudjetidan ancha past)

# Yangi post oqimidagi reaksiya tanlash (avval: npreact:tgl: / done / skip)
CB_REACT_TOGGLE = "nprt:t:"
CB_REACT_DONE = "nprt:done"
CB_REACT_SKIP = "nprt:skip"

# Kanal postidagi reaksiya hisoblagichi — O'ZGARMAYDI (eski postlar bilan mos).
CB_REACTION = "react:"

# 📊 Post Score & Improver (Killer Feature #4).
# ``ps_eval:<flow>`` — Magic Post / Voice / Image natijasidagi «📊 Baholash»
# tugmasi (flow = magic | voice | image); ``ps_ch:<idx>`` — kanal tanlash.
CB_POST_SCORE_EVAL = "ps_eval:"
CB_POST_SCORE_CHANNEL = "ps_ch:"
# Statik (payload'siz) post-score amallari.
CB_POST_SCORE_IMPROVE = "ps_improve"
CB_POST_SCORE_SEND = "ps_send"
CB_POST_SCORE_SCHEDULE = "ps_sched"
CB_POST_SCORE_NEW = "ps_new"
CB_POST_SCORE_SEND_ALL = "ps_chall"

#: Barcha kanonik prefikslar (test va audit uchun).
CANONICAL_PREFIXES = (
    CB_CHANNEL_DELETE,
    CB_CHANNEL_SETTINGS,
    CB_POST_TIME,
    CB_POST_EDIT,
    CB_POST_BTN,
    CB_POST_REACT,
    CB_POST_CANCEL,
    CB_POST_VIEW,
    CB_SPONSOR_DELETE,
    CB_RECEIPT_APPROVE,
    CB_RECEIPT_REJECT,
    CB_PHOTO_APPROVE,
    CB_PHOTO_REJECT,
    CB_PHOTO_VARIANT,
    CB_REACT_TOGGLE,
    CB_REACTION,
    # 📢 Kanallarim — kanal boshqaruv ekrani (dinamik channel_id payload).
    CB_CHANNEL_OPEN,
    CB_CHANNEL_NEW_POST,
    CB_CHANNEL_SCHEDULED,
    CB_CHANNEL_STATS,
    # 🧠 PHASE B — Channel Intelligence (DNA + Best Time).
    CB_CHANNEL_DNA,
    CB_CHANNEL_BEST_TIME,
    CB_CHANNEL_ADVICE,
    CB_TEAM_APPROVE,
    CB_TEAM_EDIT,
    CB_TEAM_REJECT,
    # 🚀 PHASE C — AI Avtopilot + post shablonlari (kanal kontekstida).
    CB_CHANNEL_AUTOPILOT,
    CB_CHANNEL_TEMPLATES,
    # 📥 PHASE D (2/2) — kontent manbalari HUB'i (kanal kontekstida).
    CB_CHANNEL_SOURCES,
    # 📥 PHASE D — kontent manbalari (URL→post, RSS/ATOM, recycle).
    CB_SOURCE_URL,
    CB_SOURCE_RSS,
    CB_SOURCE_RECYCLE,
    CB_SOURCE_DRAFTS,
    CB_SOURCE_DRAFT,
    CB_SOURCE_FORMAT,
    CB_SOURCE_ACTION,
    CB_SOURCE_RSS_CHECK,
    CB_SOURCE_RSS_TOGGLE,
    CB_SOURCE_RSS_AUTO,
    CB_SOURCE_RSS_DEL,
    CB_SOURCE_REC_PICK,
    # 📅 REJALASHTIRILGAN — yagona ro'yxat amallari (PostAssist V2 · 2-qadam).
    CB_SCHED_BTN_REACT,
    # 📊 Post Score — dinamik payload qo'shiladigan prefikslar.
    CB_POST_SCORE_EVAL,
    CB_POST_SCORE_CHANNEL,
)


# ===========================================================================
# 🗝 FAZA 19 — YAGONA CALLBACK REGISTRY (kanonik, fail-closed xavfsizlik)
# ---------------------------------------------------------------------------
# Telegram callback_query.data foydalanuvchi qo'lida bo'ladi: u eskirgan
# xabardagi TUGMANI bosishi (legitim) yoki API/bot nanny orqali SOXTA
# (tampered) qiymat yuborishi mumkin. Shu sababli bot BUHMODULDA yagona
# ro'yxatdan o'tmagan HAR QANDAY callback'ni xavfsiz rad etadi (fail-closed):
# ishlov hech qanday handler'ga bormaydi, foydalanuvchiga esa tildagi
# muloyim ogohlantirish ko'rsatiladi (handlers.expired_session_callback).
#
# Registry IKKI qatlamdan iborat:
#   1. REGISTERED_NAMESPACES  — dinamik payload'li prefikslar (``adm_``,
#      ``stgs_``, ``mnp_``, ``aip_``, ``cab_``, ``adp:`` va h.k.);
#   2. REGISTERED_STATIC_CALLBACKS — payload'siz aniq tokenlar
#      (``noop``, ``close_msg``, ``stgs_hub`` ...).
# Yangi callback qo'shilganda SHU YERGA yoziladi — handler ``pattern``i ham,
# testlar ham shu ro'yxatdan tekshiradi (single source of truth).
# ===========================================================================

#: Dinamik payload'li (prefiks + ``:id``/``:qiymat``) kanonik nomlar.
REGISTERED_NAMESPACES = (
    # 👑 Admin panel va reklama rotatsiyasi (handlers/admin.py).
    "adm_", "adp:",
    # 💳 Admin moderatsiya: to'lov cheklari (rc_ok:/rc_no:) va qo'lda rasm
    # tekshirish (cph:a:/cph:r: — PRO tasdiqlash, photo_check oqimi).
    "rc_ok:", "rc_no:", "cph:",
    # ⚙️ Sozlamalar hub'i va ichki oqimlari (handlers/settings.py).
    "stgs_", "claim_bonus", "referral_hub", "help",
    # 👤 Kabinet (eski ``cab_*`` xabarlar uchun routing aliasi).
    "cab_", "close_cabinet",
    # ✍️ ODDIY post (manual) paneli — universal amallar.
    "mnp_",
    # ✨ AI Post wizard (yo'nalish + format tanlash).
    "aip_",
    # 🧩 Kontent yaratish submenu (Magic/Enhancer takliflari).
    "cc_",
    # 🤖 AI Studio (AI Yordamchi) hub'i, ichki amallari va kontent-reja
    # oqimi (plan_back / plan_refresh / plan_ch:<id> / plan_day:<kun> ...).
    "studio_", "ai_", "plan_",
    # 📊 Statistika/analitika (shaxsiy + kanal bo'yicha).
    "an_",
    # 🗓 Smart content calendar + AI Avtopilot + shablonlar (stale oqimlar).
    "cal_", "ap_", "tpl_",
    # ✨ Magic Post / 📊 Post Score / 🎙 Voice / 📸 Image→Post / Vision.
    "mp_", "ps_", "vp_", "image_", "img_", "photo_",
    # 📢 Kanallarim (kanal kontekstli barcha amallar).
    "ch_", "sp_del:",
    # 📥 Kontent manbalari (URL→post, RSS, recycle, qoralamalar).
    "src_",
    # 📅 Rejalashtirilgan post kartochkasi amallari + navbat.
    "p_", "qview:", "qdel:", "qpush:", "qpage:", "qclose", "qslots:",
    "nprt:", "react:", "sched_br:",
    # 👥 Team approval kartochkalari.
    "team_",
    # 🔔 Majburiy obuna / PRO tarif oqimi.
    "sub_", "check_sub",
    # 🧰 Vositalar: Konvertor + Post Enhancer.
    "enh:", "ext_", "extra_", "conv_",
    # ❓ Qo'llanma ichki navigatsiyasi + qo'llab-quvvatlash.
    "sup_",
    # ✍️ Yangi post oqimi (eski new_post panellari) — tahrir maydonlari.
    "edit_field:", "confirm_post:", "album_choice:",
    # ➕ Kanal ulash ConversationHandler (retry/start).
    "add_channel_",
)

#: Payload'siz (aniq) kanonik callback tokenlari.
REGISTERED_STATIC_CALLBACKS = frozenset({
    "noop",                      # ma'lumot toast tugmasi
    "close_msg",                 # ❌ Yopish — vaqtinchalik xabarni yopish
    "close_cabinet",             # kabinet ekranini yopish
    "cache_clear",               # 🗑 admin: keshni tozalash
    "pending_refresh",           # 🔄 rejalashtirilgan ro'yxatini yangilash
    "check_sub_status",          # 🔔 obuna holatini qayta tekshirish
    "check_subscription",
    "add_channel_start",         # ➕ kanal ulash oqimini boshlash
    "add_channel_retry",         # 🔁 kanal tekshiruvini qayta urinish
    "help_hub", "help_support",  # ❓ qo'llanma / 💬 qo'llab-quvvatlash
    "claim_bonus",               # 🎁 kunlik bonus
    "referral_hub",              # 👥 referral ekran
    # ⚙️ Sozlamalar — payload'siz amallar (``stgs_`` ham qamraydi).
    "stgs_back", "stgs_hub", "stgs_lang", "stgs_post", "stgs_notif",
    "stgs_referral", "stgs_pay", "stgs_credits", "stgs_transfer",
    "stgs_points", "stgs_bonus", "stgs_tools", "stgs_profile",
    "stgs_rewards", "stgs_help_hub", "stgs_help", "stgs_about",
    # 👤 Kabinet (legacy routing aliaslari).
    "cab_main", "cab_lang", "cab_lang_uz", "cab_lang_ru", "cab_lang_en",
    "cab_channels", "cab_channels_delete", "cab_analytics", "cab_converter",
    "cab_bonus", "cab_referral", "cab_balance", "cab_pending", "cab_queue",
    "cab_guide",
    # ✍️ Manual post paneli (payload'siz amallar).
    "mnp_now", "mnp_time", "mnp_24h", "mnp_repeat", "mnp_edit",
    "mnp_cancel", "mnp_panel", "mnp_react", "mnp_url", "mnp_radd",
    "mnp_rback", "mnp_dup_go", "mnp_dup_ai",
    # ✨ AI Post wizard (payload'siz).
    "aip_back", "aip_cancel", "ai_post_cancel", "ai_post_retry",
    "ai_post_schedule", "ai_close", "ai_back_to_content", "ai_back_to_menu",
    "ai_menu", "ai_studio_sched",
    # 🤖 AI Studio (payload'siz).
    "studio_close", "studio_ai_post", "studio_ai_audit", "studio_extract",
    "studio_content_plan", "studio_ai_photo",
    # 🧩 Kontent yaratish submenu (payload'siz).
    "cc_magic", "cc_menu",
    # 📊 Statistika/analitika (payload'siz).
    "an_close", "an_detail", "an_other", "an_overview", "an_refresh",
    # 🗓 Calendar / Avtopilot / Shablonlar (payload'siz stale amallar).
    "cal_cancel", "ap_cancel", "ap_confirm", "ap_edit", "ap_force",
    "ap_refresh", "ap_regen", "tpl_back", "tpl_cancel",
    # ✨ Magic Post / Post Score / Voice / Image (payload'siz amallar).
    "mp_back", "mp_cancel", "mp_restyle", "mp_sched", "mp_send",
    "ps_improve", "ps_send", "ps_sched", "ps_new", "ps_chall",
    "vp_cancel", "image_back", "image_cancel", "img_cancel",
    "image_restyle", "image_schedule", "image_send",
    "photo_edit", "photo_rewrite", "photo_schedule",
    # 📅 Yangi post oqimi (eski panellarning payload'siz amallari).
    "plan_back", "plan_back_to_list", "plan_cancel", "plan_create_post",
    "plan_refresh", "plan_regenerate",
    # 🔔 Obuna / PRO (payload'siz).
    "sub_open", "sub_back", "sub_back_main", "sub_card_pay",
    "sub_send_receipt", "sub_promo",
    # 🧰 Vositalar (payload'siz).
    "extra_close", "extra_converter", "extra_enhancer",
    "ext_back", "ext_cancel", "ext_refresh", "ext_rewrite", "ext_schedule",
    "conv_close",
})

# ---------------------------------------------------------------------------
# 🧭 FAZA 17 — NAVIGATSIYA SEMANTIKASI (registry bilan bitta joyda)
# ---------------------------------------------------------------------------
#: ◀️/⬅️ Orqaga — oldingi (parent) oyna.
NAV_SEMANTIC_BACK = "back"
#: ❌ Bekor qilish — joriy FSM harakatini to'xtatish (kontekst tozalanadi).
NAV_SEMANTIC_CANCEL = "cancel"
#: 🏠/🔙 Asosiy menyu — bosh menyuga qaytish.
NAV_SEMANTIC_HOME = "home"
#: ❌ Yopish — vaqtinchalik inline xabarni o'chirish/yopish.
NAV_SEMANTIC_CLOSE = "close"

#: Kanonik callback → navigatsiya semantikasi.
#: ``*`` bilan tugagan yozuvlar REGISTERED_NAMESPACES'dagi prefiksga mos
#: keladi (masalan ``adp:*:back`` uchun ``adp:`` prefiks qayta ishlanadi).
CALLBACK_SEMANTICS = {
    # --- ◀️/⬅️ Orqaga (parent screen) ---
    "adm_back": NAV_SEMANTIC_BACK,        # admin dashboard (parent hub)
    "stgs_hub": NAV_SEMANTIC_BACK,        # ⚙️ Sozlamalar hub'i
    "ch_back": NAV_SEMANTIC_BACK,         # kanallar ro'yxati
    "src_back": NAV_SEMANTIC_BACK,        # manbalar menyusi
    "an_close": NAV_SEMANTIC_BACK,        # statistika ekranidan chiqish
    "an_overview": NAV_SEMANTIC_BACK,     # kanal analitikasi → shaxsiy
    "cab_main": NAV_SEMANTIC_BACK,        # kabinet ichki → profil hub
    "mnp_panel": NAV_SEMANTIC_BACK,       # kanal tanlash → preview panel
    "mnp_rback": NAV_SEMANTIC_BACK,       # reaksiyalar → preview panel
    "plan_back": NAV_SEMANTIC_BACK,
    "plan_back_to_list": NAV_SEMANTIC_BACK,
    "sub_back": NAV_SEMANTIC_BACK,
    "ext_back": NAV_SEMANTIC_BACK,
    "edit_field:back": NAV_SEMANTIC_BACK,
    "help:guide": NAV_SEMANTIC_BACK,      # FAQ → Qo'llanma
    "ai_back_to_menu": NAV_SEMANTIC_BACK,  # AI ichki ekran → AI Studio hub
    "ai_back_to_content": NAV_SEMANTIC_BACK,  # AI Studio → Kontent submenyu
    # --- ❌ Bekor qilish (FSM to'xtatish) ---
    "adm_cancel": NAV_SEMANTIC_CANCEL,
    "mnp_cancel": NAV_SEMANTIC_CANCEL,
    "mp_cancel": NAV_SEMANTIC_CANCEL,
    "aip_cancel": NAV_SEMANTIC_CANCEL,
    "ai_close": NAV_SEMANTIC_CANCEL,
    "ai_post_cancel": NAV_SEMANTIC_CANCEL,
    "vp_cancel": NAV_SEMANTIC_CANCEL,
    "image_cancel": NAV_SEMANTIC_CANCEL,
    "img_cancel": NAV_SEMANTIC_CANCEL,
    "cal_cancel": NAV_SEMANTIC_CANCEL,
    "ap_cancel": NAV_SEMANTIC_CANCEL,
    "tpl_cancel": NAV_SEMANTIC_CANCEL,
    "plan_cancel": NAV_SEMANTIC_CANCEL,
    "ext_cancel": NAV_SEMANTIC_CANCEL,
    "src_cancel": NAV_SEMANTIC_CANCEL,
    "enh:cancel": NAV_SEMANTIC_CANCEL,
    "confirm_post:cancel": NAV_SEMANTIC_CANCEL,
    # --- 🏠/🔙 Asosiy menyu ---
    "studio_close": NAV_SEMANTIC_HOME,
    "cc_menu": NAV_SEMANTIC_HOME,
    # --- ❌ Yopish (vaqtinchalik xabarni yopish) ---
    "close_msg": NAV_SEMANTIC_CLOSE,
    "qclose": NAV_SEMANTIC_CLOSE,
    "stgs_back": NAV_SEMANTIC_CLOSE,      # sozlamalar oynasini yopish
    "close_cabinet": NAV_SEMANTIC_CLOSE,
    "conv_close": NAV_SEMANTIC_CLOSE,
    "extra_close": NAV_SEMANTIC_CLOSE,
    "enh:home": NAV_SEMANTIC_CLOSE,       # enhancer preview'ni yopish
}

#: Noma'lum (registry'da yo'q) callback uchun xavfsiz rad javobi —
#: uchala tilda (FAZA 26: foydalanuvchi ko'radigan xabar i18n orqali).
CALLBACK_REJECT_KEY = "callback_rejected"


def match_registered_namespace(data) -> str | None:
    """``data`` mos tushadigan kanonik nomlar prefiksin qaytaradi (yo'qsa None)."""
    if not data:
        return None
    text = str(data)
    for ns in REGISTERED_NAMESPACES:
        if text.startswith(ns):
            return ns
    return None


def is_registered_callback(data) -> bool:
    """Callback REGISTRY'DA bormi? (kanonik prefiks yoki aniq token).

    Soxtalashtirilgan (tampered) yoki noma'lum qiymatlar uchun ``False`` —
    chaqiruvchi (dispatcher catch-all) bunday callback'ni fail-closed rad etadi.
    """
    if not data:
        return False
    text = str(data)
    if text in REGISTERED_STATIC_CALLBACKS:
        return True
    return match_registered_namespace(text) is not None


def callback_semantic(data) -> str | None:
    """Callback'ning navigatsiya semantikasi (back/cancel/home/close yoki None).

    Avval aniq token, keyin dinamik prefiks qoidalari tekshiriladi
    (masalan ``adp:channel:back`` → ``back``).
    """
    if not data:
        return None
    text = str(data)
    exact = CALLBACK_SEMANTICS.get(text)
    if exact:
        return exact
    # Dinamik prefiks qoidalari: ``adp:<scope>:back`` va ``src_act:*`` kabi.
    if text.startswith("adp:") and text.endswith(":back"):
        return NAV_SEMANTIC_BACK
    if text.startswith("adp:") and text.endswith(":cancel"):
        return NAV_SEMANTIC_CANCEL
    if text.startswith("src_") and text.endswith("cancel"):
        return NAV_SEMANTIC_CANCEL
    return CALLBACK_SEMANTICS.get(text.rsplit(":", 1)[0])


def validate_callback(data) -> bool:
    """Fail-closed kombinatsiyalangan tekshiruv: registry + 64-bayt limiti.

    ``True`` — callback qonuniy va Telegram chegarasida; aks holda ``False``
    (dispatcher bunday tugmani ishlov bermasdan rad etadi).
    """
    if not is_registered_callback(data):
        return False
    return is_callback_safe(data)


def callback_registry_report() -> dict:
    """Registry xulosasi (test/audit uchun): nomlar va tokenlar soni."""
    return {
        "namespaces": len(REGISTERED_NAMESPACES),
        "static_callbacks": len(REGISTERED_STATIC_CALLBACKS),
        "canonical_prefixes": len(CANONICAL_PREFIXES),
        "semantics": len(CALLBACK_SEMANTICS),
        "total_registered": len(REGISTERED_NAMESPACES)
        + len(REGISTERED_STATIC_CALLBACKS),
    }


def callback_byte_len(data) -> int:
    """``callback_data`` ning UTF-8 dagi bayt uzunligi (None → 0)."""
    if data is None:
        return 0
    try:
        return len(str(data).encode("utf-8"))
    except Exception:  # pragma: no cover — str() deyarli hech qachon yiqilmaydi
        return CALLBACK_DATA_MAX_BYTES + 1


def is_callback_safe(data) -> bool:
    """Qiymat Telegram limitiga mos (1..64 bayt) ekanini tekshiradi."""
    size = callback_byte_len(data)
    return 1 <= size <= CALLBACK_DATA_MAX_BYTES


def truncate_callback_data(data, max_bytes: int = CALLBACK_DATA_MAX_BYTES) -> str:
    """Qiymatni UTF-8 chegaralarini buzmasdan ``max_bytes`` gacha qisqartiradi.

    Ko'p baytli belgi (emoji, kirill) o'rtasidan kesilmaydi — aks holda
    ``UnicodeDecodeError`` yoki buzilgan matn chiqadi.
    """
    text = "" if data is None else str(data)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def cb(prefix: str, *parts, sep: str = ":") -> str:
    """64-bayt kafolatli ``callback_data`` quradi.

    ``prefix`` odatda ``CB_*`` konstantasi (o'zida ``:`` bilan tugashi mumkin),
    ``parts`` — qo'shiladigan qiymatlar (id, action, emoji ...).

    Agar yig'ilgan qiymat 64 baytdan oshsa — oxirgi bo'lak xavfsiz kesiladi
    va WARNING log yoziladi (klaviatura BadRequest bilan yiqilmasligi uchun).
    """
    head = "" if prefix is None else str(prefix)
    tail_parts = [str(p) for p in parts if p is not None and str(p) != ""]

    if head and tail_parts and not head.endswith(sep):
        data = head + sep + sep.join(tail_parts)
    else:
        data = head + sep.join(tail_parts)

    if not data:
        # Bo'sh callback_data ham Telegram tomonidan rad etiladi.
        return "noop"

    if callback_byte_len(data) > CALLBACK_DATA_MAX_BYTES:
        safe = truncate_callback_data(data)
        logger.warning(
            "callback_data 64 baytdan oshdi va qisqartirildi: %r → %r", data, safe
        )
        data = safe or "noop"
    return data


def safe_callback_data(data) -> str:
    """Tayyor qiymatni limitga moslashtiradi (bo'sh bo'lsa ``noop``)."""
    return cb(data)


def pattern(prefix: str) -> str:
    """``CallbackQueryHandler`` uchun prefiksdan regex qoliplaydi."""
    import re as _re

    return r"^" + _re.escape(str(prefix))


def split_callback(data, maxsplit: int = -1) -> list:
    """``callback_data`` ni ``:`` bo'yicha xavfsiz ajratadi (None → [])."""
    if not data:
        return []
    text = str(data)
    return text.split(":", maxsplit) if maxsplit and maxsplit > 0 else text.split(":")
