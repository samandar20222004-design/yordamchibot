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
    channels_queue — 📢 KANALLARIM + 📅 REJALASHTIRILGAN: CHANNELS_QUEUE_I18N
                 lug'ati, ``channels_queue_t``, kanal boshqaruv/post amal
                 tugma kalitlari va paritet hisoboti (PostAssist V2, 4-qadam).

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
]
