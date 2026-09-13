"""✨ PostAssist V2 — Magic Post i18n paketi (UZ / RU / EN).

"✨ Magic Post" killer funksiyasining barcha matnshunosligi (tugmalar,
yo'riqnomalar, uslub tavsiflari) shu paketning ``magic_post`` modulida
uchala tilda saqlanadi va ``magic_post_parity_report()`` orqali 100%
pariteti testlarda qo'riqlanadi.

Modullar:
    magic_post — MAGIC_POST_I18N lug'ati, ``magic_t`` va paritet hisoboti.

Foydalanish:
    from translations import magic_t, MAGIC_STYLE_KEYS
    magic_t("mp_intro", lang="ru")
"""

from translations.magic_post import (  # noqa: F401
    MAGIC_POST_I18N,
    MAGIC_POST_KEYS,
    MAGIC_STYLE_KEYS,
    magic_post_parity_report,
    magic_t,
)

__all__ = [
    "MAGIC_POST_I18N",
    "MAGIC_POST_KEYS",
    "MAGIC_STYLE_KEYS",
    "magic_post_parity_report",
    "magic_t",
]
