"""✨ PostAssist V2 — Killer Feature i18n paketi (UZ / RU / EN).

Killer funksiyalarning barcha matnshunosligi (tugmalar, yo'riqnomalar,
uslub tavsiflari) shu paketda uchala tilda saqlanadi va paritet hisobotlari
(``magic_post_parity_report`` / ``voice_post_parity_report``) orqali 100%
pariteti testlarda qo'riqlanadi.

Modullar:
    magic_post — ✨ MAGIC POST: MAGIC_POST_I18N lug'ati, ``magic_t`` va paritet hisoboti.
    voice_post — 🎙 VOICE → POST: VOICE_POST_I18N lug'ati, ``voice_t`` va paritet hisoboti.
    post_score — 📊 POST SCORE & IMPROVER: POST_SCORE_I18N lug'ati, ``post_score_t``,
                 mezon yorliqlari/darajalari va paritet hisoboti (Killer Feature #4).
    content_menu — 🧩 KONTENT YARATISH submenu: CONTENT_MENU_I18N lug'ati,
                 ``content_menu_t`` va paritet hisoboti (PostAssist V2).
    manual_post — ✍️ ODDIY POST (AI'SIZ): MANUAL_POST_I18N lug'ati,
                 ``manual_post_t`` va paritet hisoboti (birlashtirilgan menyu).
    channels_queue — 📢 KANALLARIM + 📅 REJALASHTIRILGAN: CHANNELS_QUEUE_I18N
                 lug'ati, ``channels_queue_t``, kanal boshqaruv/post amal
                 tugma kalitlari va paritet hisoboti (PostAssist V2, 4-qadam).
    support — 💬 QO'LLAB-QUVVATLASH: SUPPORT_I18N lug'ati, ``support_t``,
                 bir martalik murojaat (one-time ticket) va admin javobi
                 matnlari hamda paritet hisoboti (PostAssist V2, 4-QISM).
    settings_stats — ⚙️ SOZLAMALAR + 📊 STATISTIKA + 🧰 VOSITALAR:
                 SETTINGS_STATS_I18N lug'ati, ``settings_stats_t``, sozlamalar
                 menyu (8 guruh + Orqaga), rewards/help submenu'lari, vositalar
                 submenyusi va statistika
                 qator kalitlari hamda paritet hisoboti
                 (PostAssist V2, 5-qadam + 3-qadam refaktori).

Foydalanish:
    from translations import magic_t, MAGIC_STYLE_KEYS
    from translations import voice_t
    from translations import post_score_t, post_score_criterion_label
    magic_t("mp_intro", lang="ru")
    voice_t("vp_listening", lang="en")
    post_score_t("ps_btn_improve", lang="uz")          # «✨ 95/100 ga yaxshilash»
    content_menu_t("cm_btn_ai", lang="en")              # «🤖 AI Assistant»
    channels_queue_t("cq_ch_btn_scheduled", lang="ru")  # «📅 Запланированные»
    post_score_criterion_label("cta", "ru")            # «📣 CTA»
"""

from translations.magic_post import (  # noqa: F401
    MAGIC_POST_I18N,
    MAGIC_POST_KEYS,
    MAGIC_STYLE_KEYS,
    magic_post_parity_report,
    magic_t,
)
from translations.voice_post import (  # noqa: F401
    VOICE_POST_I18N,
    VOICE_POST_KEYS,
    voice_post_parity_report,
    voice_t,
)
from translations.content_menu import (  # noqa: F401
    CONTENT_MENU_I18N,
    CONTENT_MENU_KEYS,
    content_menu_parity_report,
    content_menu_t,
)
from translations.manual_post import (  # noqa: F401
    MANUAL_POST_I18N,
    MANUAL_POST_KEYS,
    manual_post_parity_report,
    manual_post_t,
)
from translations.channels_queue import (  # noqa: F401
    CHANNEL_PANEL_BUTTON_KEYS,
    CHANNELS_QUEUE_I18N,
    CHANNELS_QUEUE_KEYS,
    SCHEDULED_ACTION_KEYS,
    channels_queue_parity_report,
    channels_queue_t,
)
from translations.post_score import (  # noqa: F401
    POST_SCORE_BANDS,
    POST_SCORE_CRITERIA_KEYS,
    POST_SCORE_I18N,
    POST_SCORE_LABEL_KEYS,
    post_score_advice,
    post_score_band,
    post_score_criterion_label,
    post_score_parity_report,
    post_score_t,
    score_band_key,
)
from translations.settings_stats import (  # noqa: F401
    CB_HELP_HUB,
    CB_REWARDS_HUB,
    CB_SETTINGS_HELP_HUB,
    CB_SETTINGS_HUB,
    CB_SETTINGS_PREFIX,
    CB_SETTINGS_REWARDS,
    CB_STATS_DETAIL,
    CB_STATS_OVERVIEW,
    CB_TOOLS_HUB,
    HELP_HUB_BUTTON_KEYS,
    MY_STATS_ROW_KEYS,
    REWARDS_MENU_BUTTON_KEYS,
    SETTINGS_HELP_HUB_BUTTON_KEYS,
    SETTINGS_MENU_BUTTON_KEYS,
    SETTINGS_REWARDS_BUTTON_KEYS,
    SETTINGS_STATS_I18N,
    SETTINGS_STATS_KEYS,
    STATS_ROW_KEYS,
    TOOLS_MENU_BUTTON_KEYS,
    settings_stats_parity_report,
    settings_stats_t,
)
from translations.autopilot import (  # noqa: F401
    AUTOPILOT_I18N,
    AUTOPILOT_KEYS,
    autopilot_parity_report,
    autopilot_t,
)
from translations.templates import (  # noqa: F401
    TEMPLATES_I18N,
    TEMPLATES_KEYS,
    templates_parity_report,
    templates_t,
)
from translations.sources import (  # noqa: F401
    SOURCES_BUTTON_KEYS,
    SOURCES_I18N,
    SOURCES_KEYS,
    sources_parity_report,
    sources_t,
)
from translations.support import (  # noqa: F401
    SUPPORT_BUTTON_KEYS,
    SUPPORT_EMPTY_MESSAGE_KEYS,
    SUPPORT_I18N,
    SUPPORT_KEYS,
    support_parity_report,
    support_t,
)
# 👑 FAZA 26 — admin panel i18n (handlers/admin.py matnlari, uz/ru/en).
from translations.admin_panel import (  # noqa: F401
    ADMIN_PANEL_I18N,
    admin_panel_parity_report,
    admin_t,
)

__all__ = [
    "MAGIC_POST_I18N",
    "MAGIC_POST_KEYS",
    "MAGIC_STYLE_KEYS",
    "magic_post_parity_report",
    "magic_t",
    "VOICE_POST_I18N",
    "VOICE_POST_KEYS",
    "voice_post_parity_report",
    "voice_t",
    "CONTENT_MENU_I18N",
    "CONTENT_MENU_KEYS",
    "content_menu_parity_report",
    "content_menu_t",
    "MANUAL_POST_I18N",
    "MANUAL_POST_KEYS",
    "manual_post_parity_report",
    "manual_post_t",
    "CHANNELS_QUEUE_I18N",
    "CHANNELS_QUEUE_KEYS",
    "CHANNEL_PANEL_BUTTON_KEYS",
    "SCHEDULED_ACTION_KEYS",
    "channels_queue_parity_report",
    "channels_queue_t",
    "POST_SCORE_I18N",
    "POST_SCORE_CRITERIA_KEYS",
    "POST_SCORE_LABEL_KEYS",
    "POST_SCORE_BANDS",
    "post_score_t",
    "post_score_band",
    "post_score_criterion_label",
    "post_score_advice",
    "post_score_parity_report",
    "score_band_key",
    "SETTINGS_STATS_I18N",
    "SETTINGS_STATS_KEYS",
    "SETTINGS_MENU_BUTTON_KEYS",
    "TOOLS_MENU_BUTTON_KEYS",
    "CB_SETTINGS_PREFIX",
    "CB_SETTINGS_HUB",
    "CB_TOOLS_HUB",
    "STATS_ROW_KEYS",
    "MY_STATS_ROW_KEYS",
    "CB_STATS_DETAIL",
    "CB_STATS_OVERVIEW",
    "settings_stats_t",
    "settings_stats_parity_report",
    "AUTOPILOT_I18N",
    "AUTOPILOT_KEYS",
    "autopilot_t",
    "autopilot_parity_report",
    "TEMPLATES_I18N",
    "TEMPLATES_KEYS",
    "templates_t",
    "templates_parity_report",
    "SOURCES_I18N",
    "SOURCES_KEYS",
    "SOURCES_BUTTON_KEYS",
    "sources_t",
    "sources_parity_report",
    "SUPPORT_I18N",
    "SUPPORT_KEYS",
    "SUPPORT_BUTTON_KEYS",
    "SUPPORT_EMPTY_MESSAGE_KEYS",
    "support_t",
    "support_parity_report",
    "ADMIN_PANEL_I18N",
    "admin_t",
    "admin_panel_parity_report",
]
