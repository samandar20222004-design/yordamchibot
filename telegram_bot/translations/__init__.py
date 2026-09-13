"""✨ PostAssist V2 — Killer Feature i18n paketi (UZ / RU / EN).

Killer funksiyalarning barcha matnshunosligi (tugmalar, yo'riqnomalar,
uslub tavsiflari) shu paketda uchala tilda saqlanadi va paritet hisobotlari
(``magic_post_parity_report`` / ``voice_post_parity_report``) orqali 100%
pariteti testlarda qo'riqlanadi.

Modullar:
    magic_post — ✨ MAGIC POST: MAGIC_POST_I18N lug'ati, ``magic_t`` va paritet hisoboti.
    voice_post — 🎙 VOICE → POST: VOICE_POST_I18N lug'ati, ``voice_t`` va paritet hisoboti.

Foydalanish:
    from translations import magic_t, MAGIC_STYLE_KEYS
    from translations import voice_t
    magic_t("mp_intro", lang="ru")
    voice_t("vp_listening", lang="en")
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
]
