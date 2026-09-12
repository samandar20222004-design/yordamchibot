"""Bot i18n (uz/ru/en) paketi."""
from locales.translations import (  # noqa: F401
    SUPPORTED_LANGS,
    DEFAULT_LANG,
    get_text,
    safe_t,
    localize_db_message,
    localize_service_error,
    is_main_menu_text,
    detect_language,
    normalize_lang,
    get_lang,
    set_lang_cache,
    clear_fsm_data,
    has_key,
    missing_keys,
    translation_parity_report,
)
